from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

from .browser.esocial_client import ESOCIAL_LOGIN_URL, ESocialClient
from .browser.profile import clear_browser_auth_state, close_all_chrome_instances, mirrored_last_chrome_profile, open_debug_chrome
from .browser.selectors import SelectorRegistry
from .config import Settings
from .contracts import EmployeeResult, OCRSafetyBlocked
from .desktop.certificate_ocr import CertificateOCR
from .healing.failure import collect_failure, persist_bundle
from .healing.ai_diagnosis import diagnose_if_enabled
from .healing.knowledge import find_hypotheses
from .healing.recovery import deterministic_retry
from .healing.root_cause import analyze
from .reporting.input_excel import load_employees, mark_source_row_completed, prepare_output_workbook
from .reporting.output_reports import write_reports
from .runtime.artifacts import BrowserEvidence
from .runtime.execution import ExecutionContext
from .runtime.state import ExecutionState
from .runtime.costs import AICostManager
from .safety.policy import ReadOnlyPolicy
from .utils import mask_cpf, normalize_text, utc_now


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "sim", "yes", "y", "s"}


def _manual_login_enabled() -> bool:
    """Novo nome claro, mantendo compatibilidade com o .env anterior."""
    if os.getenv("MANUAL_LOGIN_BEFORE_RUN") is not None:
        return _env_bool("MANUAL_LOGIN_BEFORE_RUN", True)
    return _env_bool("REAL_USER_LOGIN_BOOTSTRAP", True)


def _manual_login_ready(page) -> bool:
    """Comprova que o navegador controlado herdou uma sessao dentro do eSocial/SST."""
    try:
        text = page.locator("body").inner_text(timeout=7000)
    except Exception:
        return False
    normalized = normalize_text(text)
    current_url = page.url.casefold()
    login_signals = (
        "login.esocial.gov.br" in current_url
        or "sso.acesso.gov.br" in current_url
        or ("certificado digital" in normalized and "entrar" in normalized)
        or "gov.br" in normalized and "cpf" in normalized and "senha" in normalized
    )
    ended_signals = (
        "sessao no sistema foi encerrada" in normalized
        or "necessario fechar todas as abas" in normalized
    )
    sst_signals = (
        "frontend.esocial.gov.br" in current_url
        and any(signal in normalized for signal in ("gestao de trabalhadores", "gestao de empregados", "empregados", "cpf completo"))
    )
    portal_signals = (
        "esocial.gov.br/portal" in current_url
        and any(signal in normalized for signal in ("titular do certificado", "empregador", "sair"))
    )
    return (sst_signals or portal_signals) and not login_signals and not ended_signals


def _wait_for_chrome_cdp(port: int, timeout_seconds: int = 8) -> bool:
    deadline = time.monotonic() + timeout_seconds
    url = f"http://127.0.0.1:{port}/json/version"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                return response.status == 200
        except (OSError, urllib.error.URLError):
            time.sleep(0.5)
    return False


def _save_employee_output(input_workbook: Path, output_workbook: Path, employee_row: int, result: EmployeeResult) -> Path:
    output_workbook.parent.mkdir(parents=True, exist_ok=True)
    if not output_workbook.exists():
        print(f"Planilha de resultado nao encontrada; recriando copia: {output_workbook}", flush=True)
        output_workbook = prepare_output_workbook(input_workbook, output_workbook.parent)
    has_noise = result.ruido_encontrado.strip().casefold() == "sim"
    is_final = has_noise or result.status_consulta in {"completed", "not_found"}
    status = "Concluido" if is_final else "Revisao"
    if has_noise:
        log_text = "Agente de Ruído encontrado"
        agent_code = "02.01.001"
    elif is_final:
        log_text = "Não há Agente de Ruído"
        agent_code = ""
    else:
        log_text = result.detalhe_observado or result.erro or "Revisão humana necessária"
        agent_code = ""
    saved_path = mark_source_row_completed(
        output_workbook,
        employee_row,
        no_noise=not has_noise,
        esocial_date=result.data_esocial or result.data_planilha,
        esocial_intensity=result.intensidade_esocial,
        agent_code=agent_code,
        log_text=log_text,
        status=status,
    )
    if saved_path != output_workbook:
        print(f"Planilha principal estava bloqueada; continuando em: {saved_path}", flush=True)
    return saved_path


def _complete_certificate_login(client: ESocialClient, execution: ExecutionContext, evidence: BrowserEvidence, settings: Settings) -> None:
    execution.current_step = "certificate_login_completed"
    files = evidence.capture(client.page, "certificate_login_requested", include_dom=False)
    automatic = False
    certificate_used = False
    # Caminho estável: retorno direto autenticado ou certificado configurado por OCR.
    # Qualquer outra tela é bloqueada para revisão humana; IA não participa deste fluxo.
    client.page.wait_for_timeout(1000)
    if client.is_authenticated() and settings.manifest["certificate_ocr"].get("allow_direct_authenticated_return", False):
        automatic = True
        execution.event("deterministic_login_path", path="direct_authenticated_return")
    elif not client.certificate_option_available():
        raise RuntimeError("Estado de login não reconhecido: não autenticado e opção de certificado ausente. Revisão humana necessária.")
    try:
        if not automatic:
            execution.event("deterministic_login_path", path="govbr_certificate_ocr")
            client.open_certificate_dialog()
            pre_ocr_wait = int(settings.manifest["certificate_ocr"].get("pre_ocr_human_wait_seconds", 0))
            if pre_ocr_wait:
                print("Se aparecer CAPTCHA, resolva manualmente agora.", flush=True)
                print("Quando a janela 'Selecione um certificado' estiver visivel, pressione ENTER aqui no terminal para iniciar o OCR.", flush=True)
                input()
            files.extend(CertificateOCR(execution, settings.root, settings.manifest["certificate_ocr"]).select_and_confirm())
            certificate_used = True
            deadline = time.monotonic() + int(settings.manifest["certificate_ocr"].get("post_selection_wait_seconds", 25))
            while time.monotonic() < deadline:
                if client.is_authenticated():
                    automatic = True
                    break
                client.page.wait_for_timeout(1000)
    except OCRSafetyBlocked as error:
        execution.event("human_review_requested", "warning", reason="certificate_ocr_not_proven", error=str(error))
        raise RuntimeError(f"OCR do certificado não comprovado; revisão humana necessária: {error}") from error
    files.extend(evidence.capture(client.page, "certificate_login_confirmed", include_dom=False))
    if not client.is_authenticated():
        raise RuntimeError("Login não foi concluído; revisão humana necessária.")
    execution.checkpoint("certificate_login_completed", "ok", {"authenticated": True}, {"url": client.page.url, "title": client.page.title(), "certificate_ocr_completed": certificate_used}, files)


def _chrome_extension_args() -> list[str]:
    raw = os.getenv("CHROME_EXTENSION_PATHS", "").strip()
    if not raw:
        return []
    paths = [str(Path(item.strip()).expanduser()) for item in raw.split(";") if item.strip()]
    existing = [path for path in paths if Path(path).exists()]
    missing = [path for path in paths if not Path(path).exists()]
    if missing:
        print(f"Aviso: extensoes configuradas nao encontradas: {'; '.join(missing)}", flush=True)
    if not existing:
        return []
    joined = ",".join(existing)
    print(f"Carregando extensoes Chrome: {joined}", flush=True)
    return [f"--disable-extensions-except={joined}", f"--load-extension={joined}"]


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consulta local e somente leitura de ruído no eSocial.")
    parser.add_argument("--input", type=Path, help="Planilha única. Se omitido, processa INPUT_FOLDER.")
    parser.add_argument("--company", help="Nome do titular do certificado; pode vir de ESOCIAL_COMPANY.")
    parser.add_argument("--company-cnpj")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env")
    args.company = args.company or os.getenv("ESOCIAL_COMPANY", "BIASON CONTABILIDADE")
    args.company_cnpj = args.company_cnpj or os.getenv("ESOCIAL_COMPANY_CNPJ")
    if args.input is None:
        input_folder = Path(os.getenv("INPUT_FOLDER", ""))
        if not input_folder.is_dir():
            print("Defina INPUT_FOLDER no .env com uma pasta existente de planilhas.")
            return 2
        inputs = sorted(
            path for path in input_folder.iterdir()
            if path.is_file() and path.suffix.lower() in {".xlsx", ".xls", ".csv"} and not path.name.startswith("~$")
        )
        if not inputs:
            print(f"Nenhuma planilha encontrada em: {input_folder}")
            return 2
        outcomes = []
        for input_path in inputs:
            try:
                if not load_employees(input_path):
                    print(f"Ignorada (todas as linhas concluídas): {input_path.name}")
                    outcomes.append(0)
                    continue
            except Exception:
                # A chamada individual registra a pré-validação e segue para a próxima planilha.
                pass
            command = ["--input", str(input_path), "--company", args.company]
            if args.company_cnpj:
                command.extend(["--company-cnpj", args.company_cnpj])
            print(f"Processando planilha da pasta de entrada: {input_path}", flush=True)
            outcomes.append(run(command))
            if _env_bool("CLOSE_CHROME_BETWEEN_SPREADSHEETS", True):
                print("Fechando todas as sessoes do Chrome antes da proxima planilha...", flush=True)
                close_all_chrome_instances()
        return 0 if all(code == 0 for code in outcomes) else 3
    settings = Settings.load(root)
    execution_id = f"esocial-noise-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    results_root = Path(os.getenv("RESULTS_FOLDER", str(root / settings.manifest["artifacts"]["output_root"]))).expanduser()
    results_root.mkdir(parents=True, exist_ok=True)
    execution = ExecutionContext(execution_id, root / settings.manifest["artifacts"]["root"] / execution_id, results_root / execution_id, args.company, settings.evidence_policy["redaction"].get("event_cpf") == "mask_last_4")
    state = ExecutionState(execution.artifact_dir / "employee-state.json", execution_id)
    costs = AICostManager(execution.artifact_dir, settings.manifest)
    started, rows = utc_now(), []
    try:
        employees = load_employees(args.input)
        output_workbook = prepare_output_workbook(args.input, execution.output_dir)
        print(f"Planilha de resultado criada: {output_workbook}", flush=True)
        execution.current_step = "spreadsheet_loaded"
        execution.checkpoint("spreadsheet_loaded", "ok", {"required_column": "cpf"}, {"rows": len(employees), "has_name": any(employee.name for employee in employees), "output_workbook": str(output_workbook)}, [])
        execution.event("run_started", input_file=args.input.name, output_workbook=str(output_workbook), input_sha256=hashlib.sha256(args.input.read_bytes()).hexdigest())
    except Exception as error:
        execution.event("execution_failed", "error", error=str(error))
        print(f"Pré-validação falhou: {error}")
        return 2
    browser_config = settings.manifest["runtime"]["browser"]
    if browser_config.get("close_all_instances_before_start", False):
        execution.event("browser_session_reset_started", action="close_all_chrome_instances")
        close_all_chrome_instances(int(browser_config.get("close_wait_seconds", 10)))
        execution.event("browser_session_reset_completed", action="close_all_chrome_instances")
    automation_profile_root = root / ".chrome-automation-profile"
    manual_login = _manual_login_enabled()
    if manual_login:
        debug_port = int(os.getenv("CHROME_REMOTE_DEBUGGING_PORT", "9222"))
        debug_user_data_dir = Path(os.getenv("CHROME_DEBUG_USER_DATA_DIR", "C:/tmp/chrome-debug-esocial")).expanduser()
        start_url = os.getenv("ESOCIAL_MANUAL_LOGIN_START_URL", ESOCIAL_LOGIN_URL).strip() or ESOCIAL_LOGIN_URL
        if _env_bool("CLEAR_ESOCIAL_SESSION_BEFORE_LOGIN", True):
            print("Limpando sessao/cookies antigos do perfil de automacao, preservando extensoes...", flush=True)
            clear_browser_auth_state(debug_user_data_dir / "Default")
        print(f"Abrindo Chrome de automacao no eSocial com porta de controle {debug_port}...", flush=True)
        open_debug_chrome(start_url, debug_user_data_dir, debug_port)
        if not _wait_for_chrome_cdp(debug_port):
            message = (
                f"O Chrome de automacao abriu, mas nao liberou a porta de controle {debug_port}. "
                "Sem essa porta, o robo nao consegue continuar na mesma janela depois do login. "
                f"Perfil usado: {debug_user_data_dir}. "
                "Teste no PowerShell se http://127.0.0.1:9222/json/version abre depois do Chrome iniciar. "
                "Se nao abrir, precisamos trocar a porta ou liberar o Chrome/firewall/politica."
            )
            execution.event("execution_failed", "error", error=message)
            close_all_chrome_instances(int(browser_config.get("close_wait_seconds", 10)))
            write_reports(rows, execution, root, started, costs.total_usd)
            print(f"Execucao interrompida com seguranca: {message}")
            print(f"Evidencias: {execution.artifact_dir}")
            return 3
        print("", flush=True)
        print("LOGIN MANUAL:", flush=True)
        print("1) Faca o login no eSocial neste Chrome de automacao.", flush=True)
        print("   Na primeira vez, instale/configure a Redtrust neste perfil se ela nao aparecer.", flush=True)
        print("2) Se precisar, selecione o perfil/procuracao correto.", flush=True)
        print("3) Quando estiver dentro do eSocial, volte aqui e pressione ENTER para o robo continuar nesta mesma janela.", flush=True)
        input()
        print("ENTER recebido. Conectando o robo na mesma janela do Chrome...", flush=True)
        profile_root, profile_name = debug_user_data_dir, "debug_automation_profile"
    else:
        refresh_profile = os.getenv("CHROME_PROFILE_REFRESH", "true").strip().casefold() in {"1", "true", "sim", "yes"}
        print("Preparando espelho do ultimo perfil Chrome com extensoes...", flush=True)
        profile_root, profile_name = mirrored_last_chrome_profile(automation_profile_root, refresh=refresh_profile)
    print(f"Perfil Chrome pronto: {profile_name}", flush=True)
    with sync_playwright() as playwright:
        evidence, policy = BrowserEvidence(execution, root), ReadOnlyPolicy(settings.recovery_policy)
        selectors = SelectorRegistry(settings.selectors, execution)
        context = None
        browser = None
        try:
            if manual_login:
                print("Conectando ao Chrome aberto apos o login manual...", flush=True)
                debug_port = int(os.getenv("CHROME_REMOTE_DEBUGGING_PORT", "9222"))
                browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{debug_port}")
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.pages[0] if context.pages else context.new_page()
                profile_mode = "debug_user_data_dir_cdp"
            else:
                print("Abrindo Chrome no eSocial...", flush=True)
                chrome_args = [
                    "--disable-session-crashed-bubble",
                    f"--profile-directory={profile_name}",
                ] + _chrome_extension_args()
                context = playwright.chromium.launch_persistent_context(
                    str(profile_root),
                    channel="chrome",
                    headless=False,
                    args=chrome_args,
                    ignore_default_args=[
                        "--disable-extensions",
                        "--disable-component-extensions-with-background-pages",
                    ],
                    viewport=None,
                )
                page = context.new_page()
                start_url = settings.manifest["application"]["base_url"]
                print(f"Navegando para: {start_url}", flush=True)
                page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
                for old_page in list(context.pages):
                    if old_page != page and old_page.url == "about:blank":
                        old_page.close()
            client = ESocialClient(page, selectors, policy, evidence, execution, settings.manifest["application"]["sst_worker_management_url"])
            execution.current_step = "browser_opened"
            browser_files = evidence.capture(page, "browser_opened", include_dom=False)
            profile_mode = profile_mode if manual_login else "mirrored_last_user"
            execution.checkpoint("browser_opened", "ok", {"browser": "Google Chrome", "interactive": True, "maximized": False}, {"profile": profile_name, "profile_mode": profile_mode}, browser_files)
            if manual_login:
                print("Controle conectado. Continuando no Chrome ja logado...", flush=True)
                if not _manual_login_ready(page):
                    files = evidence.capture(page, "manual_login_not_ready_before_proxy", include_dom=False)
                    execution.checkpoint(
                        "manual_login_handoff",
                        "failed",
                        {"manual_login": True},
                        {"url": page.url, "title": page.title()},
                        files,
                    )
                    raise RuntimeError("Entre no portal do eSocial antes de pressionar ENTER. A tela atual ainda nao comprova login ativo.")
                print("Trocando perfil por procuracao conforme a primeira linha da planilha...", flush=True)
                client.switch_representation(employees[0])
                print(f"Abrindo Gestao de Trabalhadores: {settings.manifest['application']['sst_worker_management_url']}", flush=True)
                page.goto(settings.manifest["application"]["sst_worker_management_url"], wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1200)
                if not _manual_login_ready(page):
                    files = evidence.capture(page, "manual_login_not_reused", include_dom=False)
                    execution.checkpoint(
                        "manual_login_handoff",
                        "failed",
                        {"manual_login": True},
                        {"url": page.url, "title": page.title()},
                        files,
                    )
                    raise RuntimeError(
                        "O login manual nao foi comprovado no Chrome controlavel. "
                        "Faça o login manual no Chrome real ate entrar no eSocial antes de pressionar ENTER."
                    )
                files = evidence.capture(page, "manual_login_reused", include_dom=False)
                execution.checkpoint(
                    "manual_login_handoff",
                    "ok",
                    {"manual_login": True},
                    {"url": page.url, "title": page.title()},
                    files,
                )
                print("Login manual confirmado. Continuando o fluxo SST.", flush=True)
                execution.event("deterministic_login_path", path="manual_login_handoff")
            else:
                client.open_login(settings.manifest["application"]["base_url"])
                client.open_esocial_access()
                if client.is_authenticated():
                    print("Sessao autenticada reaproveitada do usuario real. Pulando certificado.", flush=True)
                    execution.event("deterministic_login_path", path="real_user_authenticated_session")
                else:
                    client.open_govbr_login()
                    _complete_certificate_login(client, execution, evidence, settings)
                client.select_company(args.company, args.company_cnpj)
            context_safe = True
            for index, employee in enumerate(employees):
                if not context_safe:
                    rows.append(EmployeeResult(
                        cpf=employee.cpf, nome=employee.name, status_consulta="human_review_required", ruido_encontrado="inconclusivo",
                        data_planilha=employee.expected_start_date, intensidade_planilha=employee.expected_intensity,
                        detalhe_observado="Consulta não iniciada: contexto anterior não confiável.", erro="Execução pausada após falha anterior.", revisao_humana="sim",
                    ))
                    state.record(rows[-1], context_trusted=False)
                    continue
                try:
                    result = client.inspect_employee(employee)
                except Exception as error:
                    bundle = collect_failure(page, execution, evidence, error, root)
                    bundle["knowledge"] = find_hypotheses(root, execution)
                    persist_bundle(bundle, root)
                    if deterministic_retry(page, selectors, policy, evidence, execution):
                        try:
                            rows.append(client.inspect_employee(employee))
                            output_workbook = _save_employee_output(args.input, output_workbook, employee.source_row, rows[-1])
                            state.record(rows[-1], context_trusted=True)
                            execution.current_step = "employee_result_recorded"
                            execution.checkpoint("employee_result_recorded", "ok", {"cpf": mask_cpf(employee.cpf)}, {"status": rows[-1].status_consulta, "recovered": True}, [rows[-1].evidencia_principal] if rows[-1].evidencia_principal else [])
                            continue
                        except Exception as retry_error:
                            error = retry_error
                    diagnosis = analyze(bundle, execution)
                    if settings.manifest["self_healing"].get("ai_diagnosis_enabled", False):
                        try:
                            ai_diagnosis = diagnose_if_enabled(bundle, settings.manifest, execution, costs)
                            if ai_diagnosis:
                                diagnosis = ai_diagnosis
                        except Exception as ai_error:
                            execution.event("ai_call_completed", "error", error=str(ai_error))
                    rows.append(EmployeeResult(
                        cpf=employee.cpf, nome=employee.name, status_consulta="human_review_required" if diagnosis.requires_human else "error", ruido_encontrado="inconclusivo",
                        data_planilha=employee.expected_start_date, intensidade_planilha=employee.expected_intensity,
                        detalhe_observado=diagnosis.diagnosis, evidencia_principal=bundle["evidence"][0] if bundle["evidence"] else "",
                        erro=str(error), recuperacao=json.dumps(diagnosis.recommended_recovery, ensure_ascii=False),
                        houve_ia="sim" if execution.ai_calls else "não", revisao_humana="sim",
                    ))
                    output_workbook = _save_employee_output(args.input, output_workbook, employee.source_row, rows[-1])
                    context_safe = True
                else:
                    rows.append(result)
                    output_workbook = _save_employee_output(args.input, output_workbook, employee.source_row, result)
                state.record(rows[-1], context_trusted=context_safe)
                execution.current_step = "employee_result_recorded"
                execution.checkpoint("employee_result_recorded", "ok", {"cpf": mask_cpf(employee.cpf)}, {"status": rows[-1].status_consulta}, [rows[-1].evidencia_principal] if rows[-1].evidencia_principal else [])
                next_employee = employees[index + 1] if index + 1 < len(employees) else None
                same_context = next_employee and (
                    next_employee.representation_type == employee.representation_type
                    and next_employee.represented_document == employee.represented_document
                )
                if context_safe and same_context:
                    # O CNPJ/CPF representado já foi validado: não refaz login nem troca perfil.
                    client.return_to_worker_management(employee.represented_document)
                elif context_safe and next_employee:
                    # Nunca consulta a próxima linha com o CNPJ anterior ainda ativo.
                    execution.event("represented_context_change_required", representation_type=next_employee.representation_type)
                    page.goto("https://www.esocial.gov.br/portal/Home/Inicial", wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(800)
                    client.switch_representation(next_employee)
                    client.return_to_worker_management(next_employee.represented_document)
            write_reports(rows, execution, root, started, costs.total_usd)
            execution.event("execution_succeeded", rows=len(rows), output=str(execution.output_dir))
            print(f"Concluído. Relatórios: {execution.output_dir}")
            return 0
        except Exception as error:
            execution.event("execution_failed", "error", error=str(error))
            write_reports(rows, execution, root, started, costs.total_usd)
            print(f"Execução interrompida com segurança: {error}\nEvidências: {execution.artifact_dir}")
            return 3
        finally:
            if browser:
                browser.close()
            elif context:
                context.close()
