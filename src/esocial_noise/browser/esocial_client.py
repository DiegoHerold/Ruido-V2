from __future__ import annotations

import re
import time
from decimal import Decimal, InvalidOperation
from typing import Any

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from ..contracts import EmployeeInput, EmployeeResult, RepresentationContextNotConfirmed, SafetyBlocked
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

    def return_to_worker_management(self, item: EmployeeInput) -> None:
        """Retorna ao ponto de busca sem relogar nem trocar o contexto jÃ¡ validado."""
        represented_document = item.represented_document
        self.execution.current_step = "employee_search_started"
        self._close_open_dialogs()
        before = self.evidence.capture(self.page, "before_return_to_worker_management", include_dom=False)
        self.execution.event("action_started", action="navigate:sst_worker_management", evidence=before)
        self.page.goto(self.sst_workers_url, wait_until="domcontentloaded", timeout=30000)
        # O frontend do SST termina de montar o cabeÃ§alho (onde fica o CNPJ/CPF
        # representado) depois do DOMContentLoaded. Uma leitura Ãºnica logo apÃ³s
        # a navegaÃ§Ã£o criava falsos bloqueios em retornos mais lentos.
        deadline = time.monotonic() + 15
        text = ""
        document_visible = False
        page_ready = False
        while time.monotonic() < deadline:
            try:
                text = self.page.locator("body").inner_text(timeout=1500)
            except PlaywrightTimeoutError:
                text = ""
            digits = "".join(filter(str.isdigit, text))
            normalized = normalize_text(text)
            document_visible = represented_document in digits
            page_ready = (
                "gestao de trabalhadores" in normalized
                or "gestao de empregados" in normalized
            ) and "cpf completo" in normalized
            if page_ready and document_visible:
                break
            self.page.wait_for_timeout(250)
        after = self.evidence.capture(self.page, "after_return_to_worker_management", include_dom=False)
        self.execution.event("action_completed", action="navigate:sst_worker_management", evidence=after)
        if not page_ready or not document_visible:
            self.execution.checkpoint(
                "represented_context_after_return",
                "suspicious",
                {"document": represented_document},
                {"page_ready": page_ready, "document_visible": document_visible, "url": self.page.url},
                after,
            )
            raise RepresentationContextNotConfirmed("O retorno Ã  GestÃ£o de Trabalhadores nÃ£o comprovou o mesmo CNPJ/CPF representado.")

    def retry_representation_context(self, item: EmployeeInput, attempt: int, reason: str) -> None:
        """Executa a recuperacao; a autorizacao e limite pertencem ao main."""
        before = self.evidence.capture(self.page, "before_retry_representation_context", include_dom=False)
        self.execution.event(
            "represented_context_recovery_started",
            reason=reason,
            document=item.represented_document,
            type=item.representation_type,
            attempt=attempt,
            previous_url=self.page.url,
            evidence=before,
        )
        self.page.goto("https://www.esocial.gov.br/portal/Home/Inicial", wait_until="domcontentloaded", timeout=30000)
        self.switch_representation(item)
        self.return_to_worker_management(item)
        after = self.evidence.capture(self.page, "after_retry_representation_context", include_dom=False)
        self.execution.event("represented_context_recovery_completed", attempt=attempt, outcome="context_confirmed", evidence=after)

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
            self.click("representation.switch", wait_for_validation=False)
            self._wait_for_any_text(
                ("selecione o seu perfil", "procurador de pessoa juridica", "procurador de pessoa fisica"),
                "troca de perfil",
            )
            self.assert_session_active()

        profile_value = "PROCURADOR_PJ" if item.representation_type == "pessoa_juridica" else "PROCURADOR_PF"
        document_key = "representation.document_pj" if item.representation_type == "pessoa_juridica" else "representation.document_pf"
        verify_key = "representation.verify_pj" if item.representation_type == "pessoa_juridica" else "representation.verify_pf"

        print(f"Selecionando perfil: {profile_value}", flush=True)
        self.select_option("representation.profile", profile_value)
        self.assert_session_active()

        print(f"Preenchendo {label} representado: {typed_document}", flush=True)
        field = self.type_document(document_key, typed_document, document, label)
        filled_value = "".join(filter(str.isdigit, field.input_value(timeout=3000)))
        if filled_value != document:
            raise SafetyBlocked(f"O campo de {label} nao manteve o documento preenchido antes do Verificar.")

        print("Verificando procuracao...", flush=True)
        self.click(verify_key, wait_for_validation=False)
        self._wait_for_sst_module_after_verify()
        self.assert_session_active()

        print("Selecionando modulo SST...", flush=True)
        self._select_sst_module()
        self.assert_session_active()

        if not self._is_sst_frontend_loaded():
            print("Continuando com perfil por procuracao...", flush=True)
            try:
                self.click("representation.continue", wait_for_validation=False)
                self._wait_for_sst_frontend()
            except PlaywrightTimeoutError:
                print("Botao Continuar nao apareceu; o clique no SST ja levou ao modulo.", flush=True)
            else:
                self.assert_session_active()

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

    def _ensure_worker_search_ready(self, item: EmployeeInput) -> None:
        represented_document = item.represented_document
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
        self.return_to_worker_management(item)

    def _is_sst_frontend_loaded(self) -> bool:
        current_url = self.page.url.casefold()
        try:
            normalized = normalize_text(self.page.locator("body").inner_text(timeout=3000))
        except Exception:
            return False
        return (
            "frontend.esocial.gov.br/sst" in current_url
            and not any(marker in normalized for marker in GENERIC_LOADING_MARKERS)
            and (
                "modulo simplificado saude e seguranca do trabalho" in normalized
                or "gestao de empregados" in normalized
                or "gestao de trabalhadores" in normalized
            )
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
        self._ensure_worker_search_ready(item)
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
        if self._has_no_environmental_conditions_registered():
            print("Trabalhador sem Condicoes Ambientais registradas; registrando sem agente de ruido.", flush=True)
            checked = self.evidence.capture(self.page, f"employee_{item.cpf[-4:]}_no_environmental_conditions", include_dom=False)
            self.execution.checkpoint(
                "noise_information_checked",
                "ok",
                {"section": "SST/noise", "agent_code": "02.01.001"},
                {"noise": "não", "reason": "no_environmental_conditions_registered"},
                checked,
            )
            return EmployeeResult(
                cpf=item.cpf, nome=item.name,
                status_consulta="completed", ruido_encontrado="não",
                data_planilha=item.expected_start_date, data_esocial="", data_confere="",
                intensidade_planilha=item.expected_intensity, intensidade_esocial="", intensidade_confere="",
                detalhe_observado="Não há Condições Ambientais do Trabalho - Agentes Nocivos registradas para o trabalhador; Não há Agente de Ruído",
                evidencia_principal=checked[-1], revisao_humana="não",
            )
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

    def _wait_for_text(self, expected: tuple[str, ...], context: str, timeout_ms: int = 10000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            try:
                body = normalize_text(self.page.locator("body").inner_text(timeout=1500))
                if all(value in body for value in expected):
                    return
            except PlaywrightTimeoutError:
                pass
            self.page.wait_for_timeout(200)
        raise PlaywrightTimeoutError(f"Nao observei o estado esperado apos {context}: {expected}")

    def _wait_for_any_text(self, expected: tuple[str, ...], context: str, timeout_ms: int = 10000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            try:
                body = normalize_text(self.page.locator("body").inner_text(timeout=1500))
                if any(value in body for value in expected):
                    return
            except PlaywrightTimeoutError:
                pass
            self.page.wait_for_timeout(200)
        raise PlaywrightTimeoutError(f"Nao observei nenhum estado esperado apos {context}: {expected}")

    def _wait_for_sst_frontend(self, timeout_ms: int = 15000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            if self._is_sst_frontend_loaded():
                return
            self.page.wait_for_timeout(250)
        raise PlaywrightTimeoutError("Modulo SST nao ficou disponivel apos a acao.")

    def _record_action(self, action: str, selector_key: str, operation, wait_for_validation: bool = True) -> Any:
        """Executa acoes relevantes com politica, evidencias e validacao observavel."""
        self.renew_session_if_prompted()
        print(f"Resolvendo seletor: {selector_key}", flush=True)
        locator, definition = self.selectors.resolve(self.page, selector_key)
        target_text = locator.inner_text(timeout=3000) if definition.get("kind") != "textbox" else selector_key
        self.policy.assert_target_allowed(target_text, definition)
        self.execution.last_action = f"{action}:{selector_key}"
        before = self.evidence.capture(self.page, f"before_{action}_{selector_key}", include_dom=False)
        self.execution.event("action_started", action=self.execution.last_action, selector_key=selector_key, evidence=before)
        operation(locator)
        if wait_for_validation:
            validation = definition.get("validation", {})
            values = tuple(normalize_text(value) for value in validation.get("visible_text_any", []))
            if values:
                deadline = time.monotonic() + 10000 / 1000
                validated = False
                while time.monotonic() < deadline:
                    body = normalize_text(self.page.locator("body").inner_text(timeout=1500))
                    # O eSocial alterna entre "Agente nocivo" e "Agentes
                    # Nocivos" no titulo da mesma tela.
                    if any(value in body for value in values) or (
                        "agente nocivo" in values and "agentes nocivos" in body
                    ):
                        validated = True
                        break
                    self.page.wait_for_timeout(200)
                if not validated:
                    raise PlaywrightTimeoutError(f"Acao {selector_key} nao produziu a validacao declarada.")
        after = self.evidence.capture(self.page, f"after_{action}_{selector_key}", include_dom=False)
        self.execution.event("action_completed", action=self.execution.last_action, selector_key=selector_key, evidence=after)
        return locator

    def click(self, selector_key: str, wait_for_validation: bool = True) -> None:
        self._record_action("click", selector_key, lambda locator: locator.click(timeout=15000), wait_for_validation)

    def select_option(self, selector_key: str, value: str) -> None:
        self._record_action("select_option", selector_key, lambda locator: locator.select_option(value), wait_for_validation=False)

    def type_document(self, selector_key: str, value_to_type: str, expected_digits: str, label: str):
        locator, definition = self.selectors.resolve(self.page, selector_key)
        self.policy.assert_target_allowed(selector_key, definition)
        before = self.evidence.capture(self.page, f"before_type_{selector_key}", include_dom=False)
        self.execution.event("action_started", action=f"type:{selector_key}", selector_key=selector_key, evidence=before)
        self._type_masked_document(locator, value_to_type, expected_digits, label)
        after = self.evidence.capture(self.page, f"after_type_{selector_key}", include_dom=False)
        self.execution.event("action_completed", action=f"type:{selector_key}", selector_key=selector_key, evidence=after)
        return locator

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

    def _has_no_environmental_conditions_registered(self) -> bool:
        try:
            body = normalize_text(self.page.locator("body").inner_text(timeout=3000))
        except Exception:
            return False
        return (
            "nao ha condicoes ambientais do trabalho" in body
            and "agentes nocivos registradas para o(a) trabalhador(a)" in body
        )

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
                row = self.page.locator("tr", has_text=re.compile(r"02\.01\.001")).first
                row.wait_for(state="visible", timeout=5000)
                row.scroll_into_view_if_needed(timeout=2000)
                selector = self.selectors.definition("sst.noxious_agent_view")["primary"]["css"]
                agent_button = row.locator(selector).first
                self.policy.assert_target_allowed(agent_button.get_attribute("aria-label") or "visualizar item", self.selectors.definition("sst.noxious_agent_view"))
                before = self.evidence.capture(self.page, "before_click_sst.noxious_agent_view", include_dom=False)
                self.execution.event("action_started", action="click:sst.noxious_agent_view", evidence=before)
                agent_button.click(timeout=7000)
                after = self.evidence.capture(self.page, "after_click_sst.noxious_agent_view", include_dom=False)
                self.execution.event("action_completed", action="click:sst.noxious_agent_view", evidence=after)
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
        try:
            self.click("representation.sst_module", wait_for_validation=False)
            self._wait_for_sst_frontend()
            return
        except PlaywrightTimeoutError:
            # Fallback excepcional e auditado para o botao SST que o portal por
            # vezes mantem com overlay apesar de visivel no DOM.
            locator, definition = self.selectors.resolve(self.page, "representation.sst_module", timeout_ms=3000)
            self.policy.assert_target_allowed(locator.inner_text(timeout=3000), definition)
            before = self.evidence.capture(self.page, "before_javascript_click_representation.sst_module", include_dom=False)
            self.execution.event("javascript_click_fallback_used", selector_key="representation.sst_module", reason="normal_click_timed_out", evidence=before)
            locator.evaluate("element => { element.scrollIntoView({block: 'center', inline: 'center'}); element.click(); }")
            self._wait_for_sst_frontend()
            after = self.evidence.capture(self.page, "after_javascript_click_representation.sst_module", include_dom=False)
            self.execution.event("action_completed", action="javascript_click:representation.sst_module", selector_key="representation.sst_module", evidence=after)

    def _wait_for_sst_module_after_verify(self, timeout_ms: int = 15000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        last_body = ""
        while time.monotonic() < deadline:
            self.assert_session_active()
            try:
                body = self.page.locator("body").inner_text(timeout=2000)
                last_body = body
                normalized = normalize_text(body)
                module = self.selectors.first_visible(self.page, "representation.sst_module", timeout_ms=300)
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

