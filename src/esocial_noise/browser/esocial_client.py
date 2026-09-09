from __future__ import annotations

import re
import time
from decimal import Decimal, InvalidOperation
from typing import Any

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from ..contracts import EmployeeInput, EmployeeResult, SafetyBlocked
from ..runtime.artifacts import BrowserEvidence
from ..runtime.execution import ExecutionContext
from ..safety.policy import ReadOnlyPolicy
from ..utils import mask_cpf, normalize_text
from .selectors import SelectorRegistry

SST_WORKERS_URL = "https://frontend.esocial.gov.br/sst/gestaoTrabalhadores"
ESOCIAL_LOGIN_URL = "https://login.esocial.gov.br/login.aspx"
SESSION_RENEWAL_TEXT = "Sua sessÃ£o vai expirar em breve"
GENERIC_LOADING_MARKERS = (
    "aguarde um momento",
    "carregando",
    "processando",
)


class ESocialClient:
    def __init__(self, page: Page, selectors: SelectorRegistry, policy: ReadOnlyPolicy, evidence: BrowserEvidence, execution: ExecutionContext, sst_workers_url: str = SST_WORKERS_URL):
        self.page, self.selectors, self.policy, self.evidence, self.execution = page, selectors, policy, evidence, execution
        self.sst_workers_url = sst_workers_url

    def open_login(self, url: str) -> None:
        self.execution.current_step = "esocial_loaded"
        print(f"Abrindo URL inicial: {url}", flush=True)
        self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        files = self.evidence.capture(self.page, "esocial_loaded", include_dom=False)
        self.execution.checkpoint("esocial_loaded", "ok", {"host": "www.gov.br"}, {"url": self.page.url, "title": self.page.title()}, files)

    def login_pending(self) -> bool:
        text = normalize_text(self.page.locator("body").inner_text(timeout=5000))
        return "certificado digital" in text and "entrar" in text

    def is_authenticated(self) -> bool:
        """Prova a chegada ao eSocial; nÃ£o infere autenticaÃ§Ã£o somente pela URL."""
        if "esocial.gov.br/portal" not in self.page.url:
            return False
        text = normalize_text(self.page.locator("body").inner_text(timeout=5000))
        return "titular do certificado" in text and "sair" in text

    def certificate_option_available(self) -> bool:
        try:
            self.selectors.first_visible(self.page, "govbr.certificate", timeout_ms=1500)
            return True
        except PlaywrightTimeoutError:
            return False

    def open_govbr_login(self) -> None:
        self.execution.current_step = "certificate_login_completed"
        print("Abrindo login gov.br...", flush=True)
        self.click("login.govbr")
        self.page.wait_for_timeout(800)

    def open_esocial_access(self) -> None:
        self.execution.current_step = "esocial_loaded"
        print("Acessando entrada do eSocial...", flush=True)
        try:
            self.click("portal.esocial_access")
        except PlaywrightTimeoutError:
            print("Botao Acesse nao ficou disponivel; usando URL direta do login eSocial.", flush=True)
            self.execution.event("selector_fallback_used", selector_key="portal.esocial_access", fallback="direct_login_url")
            self.page.goto(ESOCIAL_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        self.page.wait_for_timeout(800)

    def open_certificate_dialog(self) -> None:
        self.execution.current_step = "certificate_login_completed"
        print("Clicando em 'Seu certificado digital'...", flush=True)
        self.click("govbr.certificate")

    def renew_session_if_prompted(self) -> bool:
        """Confirma somente o aviso conhecido de renovaÃ§Ã£o de sessÃ£o, uma Ãºnica vez."""
        prompt = self.page.get_by_text(SESSION_RENEWAL_TEXT, exact=False).first
        try:
            prompt.wait_for(state="visible", timeout=250)
        except PlaywrightTimeoutError:
            return False
        body = self.page.locator("body").inner_text(timeout=3000)
        if SESSION_RENEWAL_TEXT.casefold() not in body.casefold() or "Deseja renovar o tempo de expiraÃ§Ã£o" not in body:
            raise SafetyBlocked("Modal de sessÃ£o nÃ£o corresponde ao aviso conhecido; revisÃ£o humana necessÃ¡ria.")
        confirmation = self.page.get_by_role("button", name="SIM", exact=True)
        if confirmation.count() != 1:
            raise SafetyBlocked("BotÃ£o SIM da renovaÃ§Ã£o de sessÃ£o nÃ£o Ã© unÃ­voco.")
        before = self.evidence.capture(self.page, "before_session_renewal", include_dom=False)
        self.policy.assert_target_allowed(confirmation.inner_text(timeout=3000), {"do_not_match_text": []})
        self.execution.event("session_renewal_detected", evidence=before)
        confirmation.click(timeout=5000)
        self.page.wait_for_timeout(400)
        try:
            prompt.wait_for(state="hidden", timeout=3000)
        except PlaywrightTimeoutError as error:
            raise SafetyBlocked("A renovaÃ§Ã£o da sessÃ£o nÃ£o foi confirmada; feche o Chrome e retome do Ãºltimo CPF gravado.") from error
        after = self.evidence.capture(self.page, "after_session_renewal", include_dom=False)
        self.execution.event("session_renewal_confirmed", evidence=after)
        return True

    def return_to_worker_management(self, represented_document: str) -> None:
        """Retorna ao ponto de busca sem relogar nem trocar o contexto jÃ¡ validado."""
        self.execution.current_step = "employee_search_started"
        self._close_open_dialogs()
        before = self.evidence.capture(self.page, "before_return_to_worker_management", include_dom=False)
        self.execution.event("action_started", action="navigate:sst_worker_management", evidence=before)
        self.page.goto(self.sst_workers_url, wait_until="domcontentloaded", timeout=30000)
        self.page.wait_for_timeout(1000)
        text = self.page.locator("body").inner_text(timeout=5000)
        document_visible = represented_document in "".join(filter(str.isdigit, text))
        page_ready = "gestao de trabalhadores" in normalize_text(text) or "empregados" in normalize_text(text)
        after = self.evidence.capture(self.page, "after_return_to_worker_management", include_dom=False)
        self.execution.event("action_completed", action="navigate:sst_worker_management", evidence=after)
        if not page_ready or not document_visible:
            raise SafetyBlocked("O retorno Ã  GestÃ£o de Trabalhadores nÃ£o comprovou o mesmo CNPJ/CPF representado.")

    def switch_representation(self, item: EmployeeInput) -> None:
        """Troca perfil por procuracao usando o Perfil + CNPJ/CPF da planilha."""
        self.execution.current_step = "represented_company_selected"
        document = "".join(filter(str.isdigit, item.represented_document))
        label = "CNPJ" if item.representation_type == "pessoa_juridica" else "CPF"
        typed_document = self._format_cnpj(document) if item.representation_type == "pessoa_juridica" else self._format_cpf(document)
        if not document:
            raise SafetyBlocked("Documento representado ausente na planilha.")
        print(f"Trocando perfil por procuracao: {label} {typed_document}", flush=True)

        self.assert_session_active()
        before = self.evidence.capture(self.page, "before_switch_representation", include_dom=False)
        self.execution.event("action_started", action="switch_representation", document=document, type=item.representation_type, evidence=before)

        if "trocarPerfil=true" not in self.page.url:
            self._click_any([
                self.page.get_by_text(re.compile(r"trocar\s+perfil", re.I)).first,
                self.page.locator("a", has_text=re.compile(r"trocar\s+perfil", re.I)).first,
                self.page.locator("button", has_text=re.compile(r"trocar\s+perfil", re.I)).first,
            ], "Trocar Perfil/Modulo")
            self.page.wait_for_timeout(800)
            self.assert_session_active()

        profile_value = "PROCURADOR_PJ" if item.representation_type == "pessoa_juridica" else "PROCURADOR_PF"
        document_field = "#procuradorCnpj" if item.representation_type == "pessoa_juridica" else "#procuradorCpf"
        verify_button = "#btn-verificar-procuracao-cnpj" if item.representation_type == "pessoa_juridica" else "#btn-verificar-procuracao-cpf"

        print(f"Selecionando perfil: {profile_value}", flush=True)
        self.page.locator("#perfilAcesso").select_option(profile_value)
        self.page.wait_for_timeout(800)
        self.assert_session_active()
        self.page.locator(document_field).wait_for(state="visible", timeout=10000)

        print(f"Preenchendo {label} representado: {typed_document}", flush=True)
        field = self.page.locator(document_field)
        self._type_masked_document(field, typed_document, document, label)
        filled_value = "".join(filter(str.isdigit, field.input_value(timeout=3000)))
        if filled_value != document:
            raise SafetyBlocked(f"O campo de {label} nao manteve o documento preenchido antes do Verificar.")

        print("Verificando procuracao...", flush=True)
        verifier = self.page.locator(verify_button)
        verifier.wait_for(state="visible", timeout=10000)
        verifier.click(timeout=5000)
        self._wait_for_sst_module_after_verify()
        self.assert_session_active()

        print("Selecionando modulo SST...", flush=True)
        self._select_sst_module()
        self.page.wait_for_timeout(1500)
        self.assert_session_active()

        if not self._is_sst_frontend_loaded():
            print("Continuando com perfil por procuracao...", flush=True)
            continue_button = self.page.locator("#btnProcuracao")
            if continue_button.count() > 0:
                try:
                    continue_button.click(timeout=5000)
                except PlaywrightTimeoutError:
                    print("Clique normal em Continuar falhou; tentando clique via JavaScript.", flush=True)
                    continue_button.evaluate("element => element.click()")
                self.page.wait_for_timeout(1800)
                self.assert_session_active()
            else:
                print("Botao Continuar nao apareceu; o clique no SST ja levou ao modulo.", flush=True)

        body = self.page.locator("body").inner_text(timeout=5000)
        valid = document in "".join(filter(str.isdigit, body)) or "frontend.esocial.gov.br" in self.page.url.casefold() or "sst" in self.page.url.casefold()
        after = self.evidence.capture(self.page, "after_switch_representation", include_dom=False)
        self.execution.checkpoint("represented_company_selected", "ok" if valid else "failed", {"document": document, "type": item.representation_type}, {"url": self.page.url, "title": self.page.title()}, before + after)
        self.execution.event("action_completed", action="switch_representation", document=document, type=item.representation_type, evidence=after)
        if not valid:
            raise SafetyBlocked("Nao foi possivel comprovar o perfil por procuracao da planilha ativo.")
        return

    def assert_session_active(self) -> None:
        body = self.page.locator("body").inner_text(timeout=5000)
        normalized = normalize_text(body)
        if "sessao no sistema foi encerrada" in normalized or "necessario fechar todas as abas" in normalized:
            raise SafetyBlocked("Sessao do eSocial encerrada. Feche todas as janelas do Chrome e recomece o login manual.")

    def _close_open_dialogs(self) -> None:
        dialogs = self.page.locator("[role='dialog']")
        for _ in range(3):
            try:
                if dialogs.count() == 0 or not dialogs.last.is_visible(timeout=300):
                    return
                print("Fechando modal aberto antes de continuar...", flush=True)
                dialog = dialogs.last
                back = dialog.get_by_role("button", name=re.compile(r"voltar|fechar|ok", re.I)).last
                if back.count():
                    back.click(timeout=3000)
                else:
                    self.page.keyboard.press("Escape")
                self.page.wait_for_timeout(600)
            except Exception:
                try:
                    self.page.keyboard.press("Escape")
                    self.page.wait_for_timeout(600)
                except Exception:
                    return

    def _ensure_worker_search_ready(self, represented_document: str) -> None:
        self._close_open_dialogs()
        try:
            text = self.page.locator("body").inner_text(timeout=4000)
        except Exception:
            text = ""
        normalized = normalize_text(text)
        digits = "".join(filter(str.isdigit, text))
        ready = (
            "frontend.esocial.gov.br/sst/gestaoTrabalhadores".casefold() in self.page.url.casefold()
            and "cpf completo" in normalized
            and represented_document in digits
        )
        if ready:
            return
        print("Tela de busca de CPF nao estava pronta; retornando para Gestao de Empregados.", flush=True)
        self.return_to_worker_management(represented_document)

    def _is_sst_frontend_loaded(self) -> bool:
        current_url = self.page.url.casefold()
        if "frontend.esocial.gov.br/sst" in current_url:
            return True
        try:
            normalized = normalize_text(self.page.locator("body").inner_text(timeout=3000))
        except Exception:
            return False
        return (
            "modulo simplificado saude e seguranca do trabalho" in normalized
            or "gestao de empregados" in normalized
            or "gestao de trabalhadores" in normalized
        )

    def select_company(self, company: str, company_cnpj: str | None) -> None:
        self.execution.current_step = "represented_company_selected"
        print(f"Selecionando empresa/certificado: {company}", flush=True)
        candidates = self.page.get_by_text(company, exact=False)
        if not company or candidates.count() != 1:
            self.execution.checkpoint("represented_company_selected", "suspicious", {"company": company}, {"matches": candidates.count() if company else 0}, [])
            raise SafetyBlocked("Empresa representada nÃ£o foi identificada de forma unÃ­voca.")
        target = candidates.first
        self.policy.assert_target_allowed(target.inner_text(timeout=3000), {"do_not_match_text": ["Cadastrar", "Alterar", "Excluir"]})
        before = self.evidence.capture(self.page, "before_company_selection", include_dom=False)
        target.click(timeout=5000)
        self.page.wait_for_timeout(600)
        body = self.page.locator("body").inner_text(timeout=5000)
        valid = normalize_text(company) in normalize_text(body)
        if company_cnpj:
            valid = valid and "".join(filter(str.isdigit, company_cnpj)) in "".join(filter(str.isdigit, body))
        after = self.evidence.capture(self.page, "after_company_selection", include_dom=False)
        self.execution.checkpoint("represented_company_selected", "ok" if valid else "failed", {"company": company, "cnpj": company_cnpj or "not_provided"}, {"selected_text": target.inner_text()}, before + after)
        if not valid:
            raise SafetyBlocked("NÃ£o foi possÃ­vel provar a empresa representada ativa.")

    def inspect_employee(self, item: EmployeeInput) -> EmployeeResult:
        self.execution.current_cpf, self.execution.current_step = item.cpf, "employee_search_started"
        print(f"Consultando CPF linha {item.source_row}: {mask_cpf(item.cpf)}", flush=True)
        self.renew_session_if_prompted()
        self._ensure_worker_search_ready(item.represented_document)
        start = self.evidence.capture(self.page, f"employee_{item.cpf[-4:]}_search_start", include_dom=False)
        self.execution.checkpoint("employee_search_started", "ok", {"cpf": mask_cpf(item.cpf)}, {"source_row": item.source_row, "source_name": item.name}, start)
        field = self.selectors.first_visible(self.page, "employee.search")
        typed_cpf = self._format_cpf(item.cpf)
        self._search_and_select_employee(field, item, typed_cpf)
        self.page.wait_for_timeout(1000)
        text = self.page.locator("body").inner_text(timeout=5000)
        normalized = normalize_text(text)
        absent = any(value in normalized for value in ("nenhum registro", "nao encontrado", "sem resultado"))
        cpf_visible = item.cpf in "".join(filter(str.isdigit, text))
        found = not absent and cpf_visible
        searched = self.evidence.capture(self.page, f"employee_{item.cpf[-4:]}_search_result", include_dom=False)
        self.execution.checkpoint("employee_found_or_not_found", "ok" if found or absent else "suspicious", {"cpf": mask_cpf(item.cpf)}, {"found": found, "not_found_signal": absent}, searched)
        if absent:
            return EmployeeResult(
                cpf=item.cpf, nome=item.name, status_consulta="not_found", ruido_encontrado="não",
                data_planilha=item.expected_start_date, intensidade_planilha=item.expected_intensity,
                detalhe_observado="FuncionÃ¡rio nÃ£o encontrado no contexto da empresa.", evidencia_principal=searched[-1],
            )
        if not found:
            raise SafetyBlocked("Resultado da busca nÃ£o prova correspondÃªncia do CPF; consulta interrompida.")
        self.execution.current_step = "noise_information_checked"
        self.click("sst.noise_section")
        self.page.wait_for_timeout(900)
        self._wait_while_generic_loading("lista de eventos de condicoes ambientais", timeout_ms=30000)
        event_date = self._open_exposure_event_for_date(item.expected_start_date)
        if not event_date:
            print("Data da planilha nao localizada na lista; abrindo primeiro evento disponivel.", flush=True)
            event_date = self._open_exposure_event_for_date("")
        if not event_date:
            raise SafetyBlocked("Nao encontrei evento de Condicoes Ambientais para verificar agentes nocivos.")
        self._wait_exposure_detail_loaded(timeout_ms=45000)
        self._wait_agent_section_ready(timeout_ms=45000)
        agent_list_text = self.page.locator("body").inner_text(timeout=5000)
        has_noise_agent_in_list = bool(re.search(r"\b02\.01\.001\b", agent_list_text))
        if has_noise_agent_in_list:
            self._open_noise_agent_detail_if_present()
        text = self.page.locator("body").inner_text(timeout=5000)
        normalized = normalize_text(text)
        # NÃ£o basta encontrar a palavra "ruÃ­do": a consulta sÃ³ Ã© positiva para o cÃ³digo oficial.
        no_noise_proven = (
            not has_noise_agent_in_list
            or any(value in normalized for value in ("nao existe agente nocivo", "nenhum agente nocivo", "sem exposicao", "nao ha informacao"))
        )
        noise = "sim" if has_noise_agent_in_list or re.search(r"\b02\.01\.001\b", text) else "não" if no_noise_proven else "inconclusivo"
        esocial_date = self._start_date_from_page() or event_date or self._first_date(text)
        esocial_intensity = self._intensity(text)
        date_matches = self._matches_date(item.expected_start_date, esocial_date)
        intensity_matches = self._matches_intensity(item.expected_intensity, esocial_intensity)
        checked = self.evidence.capture(self.page, f"employee_{item.cpf[-4:]}_noise", include_dom=False)
        identified = esocial_date != "" and esocial_intensity != ""
        mismatch = date_matches == "não" or intensity_matches == "não"
        compared = noise in {"sim", "não"}
        self.execution.checkpoint("noise_information_checked", "ok" if compared else "suspicious", {"section": "SST/noise", "agent_code": "02.01.001"}, {"noise": noise, "date_matches": date_matches, "intensity_matches": intensity_matches}, checked)
        detail = " ".join(line.strip() for line in text.splitlines() if "02.01.001" in line or "intensidade" in normalize_text(line))[:1000]
        return EmployeeResult(
            cpf=item.cpf, nome=item.name,
            status_consulta="completed" if compared else "inconclusive", ruido_encontrado=noise,
            data_planilha=item.expected_start_date, data_esocial=esocial_date, data_confere=date_matches,
            intensidade_planilha=item.expected_intensity, intensidade_esocial=esocial_intensity, intensidade_confere=intensity_matches,
            detalhe_observado="Não há Agente de Ruído" if noise == "não" else detail or "Informação do agente 02.01.001 não pôde ser comprovada.",
            evidencia_principal=checked[-1], revisao_humana="não" if compared else "sim",
        )

    @staticmethod
    def _first_date(text: str) -> str:
        match = re.search(r"\b(0[1-9]|[12]\d|3[01])/(0[1-9]|1[0-2])/\d{4}\b", text)
        return match.group(0) if match else ""

    def _start_date_from_page(self) -> str:
        """Le a Data de Inicio exibida em input; inner_text nao captura esse valor."""
        candidates = self.page.locator("input[placeholder='DD/MM/AAAA'], input[type='text']")
        for index in range(candidates.count()):
            field = candidates.nth(index)
            try:
                if not field.is_visible(timeout=200):
                    continue
                value = field.input_value(timeout=1000).strip()
            except Exception:
                continue
            if re.fullmatch(r"(0[1-9]|[12]\d|3[01])/(0[1-9]|1[0-2])/\d{4}", value):
                print(f"Data de inicio lida na pagina: {value}", flush=True)
                return value
        return ""

    @staticmethod
    def _intensity(text: str) -> str:
        normalized = normalize_text(text)
        match = re.search(
            r"intensidade,\s*concentracao\s*ou\s*dose\s*da\s*exposicao.*?quantitativo\s+(\d+(?:[,.]\d+)?)\s+dose",
            normalized,
        )
        if match:
            return match.group(1).replace(",", ".")
        position = normalized.find("intensidade")
        if position < 0:
            return ""
        following = normalized[position:]
        match = re.search(r"\b(\d+(?:[,.]\d+)?)\b\s+dose", following)
        return match.group(1).replace(",", ".") if match else ""

    @staticmethod
    def _matches_date(expected: str, observed: str) -> str:
        if not expected or not observed:
            return ""
        return "sim" if expected == observed else "não"

    @staticmethod
    def _matches_intensity(expected: str, observed: str) -> str:
        if not observed:
            return ""
        try:
            return "sim" if Decimal(expected) == Decimal(observed) else "não"
        except InvalidOperation:
            return ""

    @staticmethod
    def _format_cnpj(document: str) -> str:
        digits = "".join(filter(str.isdigit, document))
        if len(digits) != 14:
            return document
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"

    @staticmethod
    def _format_cpf(document: str) -> str:
        digits = "".join(filter(str.isdigit, document))
        if len(digits) != 11:
            return document
        return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"

    def click(self, selector_key: str) -> None:
        self.renew_session_if_prompted()
        print(f"Resolvendo seletor: {selector_key}", flush=True)
        definition = self.selectors.definition(selector_key)
        locator = self.selectors.first_visible(self.page, selector_key)
        self.policy.assert_target_allowed(locator.inner_text(timeout=3000), definition)
        self.execution.last_action = f"click:{selector_key}"
        print(f"Clicando: {selector_key}", flush=True)
        before = self.evidence.capture(self.page, f"before_{selector_key}", include_dom=False)
        self.execution.event("action_started", action=self.execution.last_action, evidence=before)
        locator.click(timeout=15000)
        self.page.wait_for_timeout(500)
        after = self.evidence.capture(self.page, f"after_{selector_key}", include_dom=False)
        self.execution.event("action_completed", action=self.execution.last_action, evidence=after)

    def _select_employee_autocomplete(self, item: EmployeeInput) -> None:
        typed_cpf = self._format_cpf(item.cpf)
        print("Selecionando funcionario na lista de sugestao...", flush=True)
        deadline = time.monotonic() + 10
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            self.renew_session_if_prompted()
            self._wait_employee_loading(timeout_ms=12000)
            locators = [
                self.page.get_by_text(typed_cpf, exact=False).last,
                self.page.get_by_text(item.cpf, exact=False).last,
            ]
            if item.name:
                locators.append(self.page.get_by_text(re.compile(re.escape(item.name), re.I)).last)
            for locator in locators:
                try:
                    if locator.count() and locator.is_visible(timeout=300):
                        text = locator.inner_text(timeout=1000)
                        if item.cpf in "".join(filter(str.isdigit, text)):
                            print(f"Clicando funcionario: {text.strip()}", flush=True)
                            locator.click(timeout=5000)
                            self.page.wait_for_timeout(800)
                            return
                except Exception as error:
                    last_error = error
            self.page.keyboard.press("ArrowDown")
            self.page.wait_for_timeout(150)
            self.page.keyboard.press("Enter")
            self.page.wait_for_timeout(800)
            try:
                body_digits = "".join(filter(str.isdigit, self.page.locator("body").inner_text(timeout=2000)))
                if item.cpf in body_digits:
                    print("Funcionario selecionado via teclado.", flush=True)
                    return
            except Exception as error:
                last_error = error
        raise PlaywrightTimeoutError(f"Nao consegui selecionar a sugestao do CPF {typed_cpf}: {last_error}")

    def _search_and_select_employee(self, field: Any, item: EmployeeInput, typed_cpf: str) -> None:
        last_error: Exception | None = None
        for attempt in range(1, 4):
            print(f"Preenchendo CPF na busca tentativa {attempt}: {typed_cpf}", flush=True)
            self._type_masked_document(field, typed_cpf, item.cpf, "CPF")
            try:
                self._select_employee_autocomplete(item)
                return
            except PlaywrightTimeoutError as error:
                last_error = error
                print("Funcionario ainda nao apareceu; aguardando e tentando novamente.", flush=True)
                self.page.wait_for_timeout(2500)
        raise PlaywrightTimeoutError(f"Nao consegui selecionar o funcionario apos novas tentativas: {last_error}")

    def _wait_employee_loading(self, timeout_ms: int = 12000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        saw_loading = False
        while time.monotonic() < deadline:
            try:
                body = normalize_text(self.page.locator("body").inner_text(timeout=1000))
                if "carregando" not in body:
                    if saw_loading:
                        self.page.wait_for_timeout(400)
                    return
                saw_loading = True
                print("Aguardando lista de funcionarios carregar...", flush=True)
            except Exception:
                return
            self.page.wait_for_timeout(700)

    def _wait_while_generic_loading(self, context: str, timeout_ms: int = 30000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        saw_loading = False
        while time.monotonic() < deadline:
            self.renew_session_if_prompted()
            try:
                body = normalize_text(self.page.locator("body").inner_text(timeout=1500))
            except Exception:
                self.page.wait_for_timeout(500)
                continue
            if not any(marker in body for marker in GENERIC_LOADING_MARKERS):
                if saw_loading:
                    self.page.wait_for_timeout(500)
                return
            saw_loading = True
            print(f"Aguardando {context} carregar...", flush=True)
            self.page.wait_for_timeout(800)
        raise SafetyBlocked(f"{context} nao terminou de carregar dentro do tempo esperado.")

    def _type_masked_document(self, field: Any, value_to_type: str, expected_digits: str, label: str) -> None:
        """Digita em campos mascarados/autocomplete sem usar fill(), que pode ser limpo pelo React."""
        expected_digits = "".join(filter(str.isdigit, expected_digits))
        last_value = ""
        for attempt in range(1, 4):
            print(f"Digitando {label} tentativa {attempt}: {value_to_type}", flush=True)
            field.wait_for(state="visible", timeout=10000)
            field.click(timeout=5000)
            self.page.keyboard.press("Control+A")
            self.page.keyboard.press("Backspace")
            self.page.wait_for_timeout(150)
            field.type(value_to_type, delay=45, timeout=10000)
            self.page.wait_for_timeout(700)
            last_value = field.input_value(timeout=3000)
            current_digits = "".join(filter(str.isdigit, last_value))
            if current_digits == expected_digits:
                return
            print(f"Campo de {label} nao estabilizou; valor atual: '{last_value}'", flush=True)
        raise SafetyBlocked(f"O campo de {label} apagou ou alterou o valor digitado. Ultimo valor: '{last_value}'")

    def _open_exposure_event_for_date(self, expected_date: str) -> str:
        self.renew_session_if_prompted()
        date = (expected_date or "").strip()
        deadline = time.monotonic() + 35
        if not date:
            print("Data da planilha vazia; usando primeiro evento de condicao ambiental disponivel.", flush=True)
        else:
            print(f"Selecionando evento de condicao ambiental da data: {date}", flush=True)
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            self.renew_session_if_prompted()
            self._wait_while_generic_loading("lista de eventos de condicoes ambientais", timeout_ms=8000)
            if not date:
                row = self.page.locator("tr", has_text=re.compile(r"\b(0[1-9]|[12]\d|3[01])/(0[1-9]|1[0-2])/\d{4}\b")).filter(has=self.page.get_by_role("button", name=re.compile(r"visualizar\s+evento", re.I))).first
            else:
                row = self.page.locator("tr", has_text=date).filter(has=self.page.get_by_role("button", name=re.compile(r"visualizar\s+evento", re.I))).first
            try:
                if row.count() == 0 or not row.is_visible(timeout=800):
                    print("Evento ainda nao apareceu na lista; aguardando...", flush=True)
                    self.page.wait_for_timeout(1200)
                    continue
                row.scroll_into_view_if_needed(timeout=3000)
                row_text = row.inner_text(timeout=3000)
                clicked_date = self._first_date(row_text) or date
                view = row.get_by_role("button", name=re.compile(r"visualizar\s+evento", re.I)).first
                if view.count() != 1:
                    print("Botao 'visualizar evento' ainda nao estabilizou na linha; aguardando...", flush=True)
                    self.page.wait_for_timeout(1200)
                    continue
                view.click(timeout=7000)
                self.page.wait_for_timeout(1200)
                self.assert_session_active()
                self._wait_exposure_detail_loaded(timeout_ms=45000)
                print(f"Evento de condicao ambiental aberto: {clicked_date}", flush=True)
                return clicked_date
            except (PlaywrightTimeoutError, SafetyBlocked) as error:
                last_error = error
                print("Evento ainda nao respondeu; repetindo tentativa apos carregar.", flush=True)
                self.page.wait_for_timeout(1500)
        if last_error:
            print(f"Nao consegui abrir evento no tempo esperado: {last_error}", flush=True)
        return ""

    def _wait_exposure_detail_loaded(self, timeout_ms: int = 20000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            self.assert_session_active()
            try:
                raw_body = self.page.locator("body").inner_text(timeout=2500)
                body = normalize_text(raw_body)
                if any(marker in body for marker in GENERIC_LOADING_MARKERS):
                    print("Aguardando detalhe das condicoes ambientais carregar...", flush=True)
                elif "agentes nocivos" in body and "identificacao do trabalhador" in body:
                    return
            except Exception:
                pass
            self.page.wait_for_timeout(700)
        raise SafetyBlocked("A tela de detalhes das Condicoes Ambientais nao terminou de carregar.")

    def _wait_agent_section_ready(self, timeout_ms: int = 30000) -> None:
        """Evita concluir 'sem ruido' enquanto a tabela de agentes ainda estÃ¡ renderizando."""
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            self.assert_session_active()
            try:
                raw_body = self.page.locator("body").inner_text(timeout=2500)
                body = normalize_text(raw_body)
                if any(marker in body for marker in GENERIC_LOADING_MARKERS):
                    print("Aguardando tabela de Agentes Nocivos carregar...", flush=True)
                elif "agentes nocivos" in body and (
                    re.search(r"\b\d{2}\.\d{2}\.\d{3}\b", raw_body)
                    or "nao existe agente nocivo" in body
                    or "nenhum agente nocivo" in body
                    or "sem exposicao" in body
                ):
                    return
                else:
                    print("Tabela de Agentes Nocivos ainda nao estabilizou; aguardando...", flush=True)
            except Exception:
                pass
            self.page.wait_for_timeout(900)
        raise SafetyBlocked("A tabela de Agentes Nocivos nao terminou de carregar; nao vou marcar como sem ruido sem comprovar.")

    def _open_noise_agent_detail_if_present(self) -> bool:
        self.renew_session_if_prompted()
        deadline = time.monotonic() + 30
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            self._wait_agent_section_ready(timeout_ms=10000)
            try:
                body = self.page.locator("body").inner_text(timeout=5000)
            except Exception as error:
                last_error = error
                self.page.wait_for_timeout(800)
                continue
            try:
                if not re.search(r"\b02\.01\.001\b", body):
                    print("Agente 02.01.001 nao apareceu; registrando como sem agente de ruido.", flush=True)
                    return False
                print("Abrindo detalhe do agente nocivo 02.01.001...", flush=True)
                clicked = self.page.evaluate("""() => {
                    const rows = Array.from(document.querySelectorAll('tr'));
                    const row = rows.find(item => (item.innerText || '').includes('02.01.001'));
                    if (!row) return false;
                    row.scrollIntoView({block: 'center', inline: 'center'});
                    const button = row.querySelector('button');
                    if (!button) return false;
                    button.click();
                    return true;
                }""")
                if not clicked:
                    row = self.page.locator("tr", has_text=re.compile(r"02\.01\.001")).first
                    row.scroll_into_view_if_needed(timeout=2000)
                    row.locator("button").first.click(timeout=7000)
                self.page.wait_for_timeout(1200)
                self._wait_noise_detail_loaded(timeout_ms=30000)
                return True
            except PlaywrightTimeoutError as error:
                last_error = error
                print("Detalhe do agente 02.01.001 ainda nao abriu; tentando novamente.", flush=True)
                self.page.wait_for_timeout(1200)
        print(f"Nao foi possivel abrir o detalhe do agente dentro do tempo esperado: {last_error}", flush=True)
        return False

    def _wait_noise_detail_loaded(self, timeout_ms: int = 12000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            try:
                body = normalize_text(self.page.locator("body").inner_text(timeout=2000))
                if any(marker in body for marker in GENERIC_LOADING_MARKERS):
                    print("Aguardando detalhe do agente nocivo carregar...", flush=True)
                elif "visualizar agente nocivo" in body and (
                    "intensidade" in body or "nao existe agente nocivo" in body
                ):
                    return
            except Exception:
                pass
            self.page.wait_for_timeout(500)
        raise SafetyBlocked("O detalhe do agente nocivo nao terminou de carregar.")

    def _click_any(self, locators: list[Any], description: str, timeout_ms: int = 20000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            for locator in locators:
                try:
                    if locator.count() and locator.is_visible(timeout=250):
                        text = ""
                        try:
                            text = locator.inner_text(timeout=1000)
                        except Exception:
                            text = description
                        self.policy.assert_target_allowed(text or description, {"do_not_match_text": ["Excluir", "Transmitir", "Assinar", "Retificar"]})
                        print(f"Clicando: {description}", flush=True)
                        locator.click(timeout=7000)
                        return
                except Exception as error:
                    last_error = error
            self.page.wait_for_timeout(250)
        raise PlaywrightTimeoutError(f"Nao encontrei elemento visivel para {description}: {last_error}")

    def _select_sst_module(self) -> None:
        module = self.page.locator("#sst")
        if module.count() != 1:
            raise PlaywrightTimeoutError("Modulo SST nao encontrado pelo id #sst.")
        state = module.evaluate("""element => ({
            display: getComputedStyle(element).display,
            visibility: getComputedStyle(element).visibility,
            opacity: getComputedStyle(element).opacity,
            rect: element.getBoundingClientRect().toJSON ? element.getBoundingClientRect().toJSON() : {
                x: element.getBoundingClientRect().x,
                y: element.getBoundingClientRect().y,
                width: element.getBoundingClientRect().width,
                height: element.getBoundingClientRect().height
            }
        })""")
        print(f"Estado do modulo SST: {state}", flush=True)
        try:
            module.scroll_into_view_if_needed(timeout=2000)
            module.click(timeout=3000)
            return
        except PlaywrightTimeoutError:
            print("Clique normal no modulo SST falhou; tentando clique via JavaScript.", flush=True)
        module.evaluate("""element => {
            element.scrollIntoView({block: 'center', inline: 'center'});
            element.click();
        }""")

    def _wait_for_sst_module_after_verify(self, timeout_ms: int = 15000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        last_body = ""
        while time.monotonic() < deadline:
            self.assert_session_active()
            try:
                body = self.page.locator("body").inner_text(timeout=2000)
                last_body = body
                normalized = normalize_text(body)
                module = self.page.locator("#sst")
                if module.count() == 1 and (
                    "selecione o modulo" in normalized
                    or "seguranca e saude no trabalho" in normalized
                    or module.is_visible(timeout=300)
                ):
                    print("Procuracao verificada; modulo SST liberado.", flush=True)
                    return
            except Exception:
                pass
            self.page.wait_for_timeout(500)
        raise SafetyBlocked(
            "Cliquei em Verificar, mas o eSocial nao liberou a selecao do modulo SST. "
            f"Trecho visivel: {last_body[:300]}"
        )

    def _document_field(self, patterns: list[str]):
        for pattern in patterns:
            compiled = re.compile(pattern, re.I)
            for factory in (self.page.get_by_label, self.page.get_by_placeholder):
                try:
                    field = factory(compiled).first
                    if field.count() and field.is_visible(timeout=500):
                        return field
                except Exception:
                    pass
        candidates = self.page.locator("input[type='text'], input:not([type]), input[type='tel'], input[type='search']")
        for index in range(candidates.count()):
            field = candidates.nth(index)
            try:
                if field.is_visible(timeout=300):
                    return field
            except Exception:
                pass
        raise PlaywrightTimeoutError("Nao encontrei campo para documento da procuracao.")

