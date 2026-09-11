from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

DIAGNOSIS_CLASSES = {
    "selector_changed", "popup_blocking", "timing_issue", "wrong_context", "employee_not_found",
    "no_noise_info", "business_validation_failed", "unknown_screen", "previous_step_suspicious",
}
REPORT_COLUMNS = [
    "cpf", "nome", "status_consulta", "ruido_encontrado",
    "data_planilha", "data_esocial", "data_confere",
    "intensidade_planilha", "intensidade_esocial", "intensidade_confere",
    "detalhe_observado", "evidencia_principal", "erro", "recuperacao",
    "houve_ia", "revisao_humana",
]


class SafetyBlocked(RuntimeError):
    """Uma regra imutável de consulta impediu a execução."""


class RepresentationContextNotConfirmed(SafetyBlocked):
    """A tela SST nao comprovou o documento; o runner decide a recuperacao."""


class OCRSafetyBlocked(SafetyBlocked):
    """O diálogo nativo não forneceu evidência OCR suficiente para um clique seguro."""


@dataclass(frozen=True)
class Diagnosis:
    classification: str
    probable_root_cause_step: str
    is_last_action_root_cause: bool
    diagnosis: str
    confidence: float
    recommended_recovery: dict[str, Any]
    required_validation: list[str]
    risk: str
    requires_human: bool

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Diagnosis":
        required = set(cls.__dataclass_fields__)
        if required - payload.keys() or payload.get("classification") not in DIAGNOSIS_CLASSES:
            raise ValueError("Diagnóstico IA não cumpre o contrato obrigatório.")
        if payload.get("risk") not in {"low", "medium", "high"} or not isinstance(payload.get("confidence"), (int, float)) or not 0 <= payload["confidence"] <= 1:
            raise ValueError("Risco ou confiança do diagnóstico IA é inválido.")
        return cls(**{name: payload[name] for name in required})

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EmployeeInput:
    cpf: str
    name: str = ""
    source_row: int = 0
    representation_type: str = ""
    represented_document: str = ""
    expected_start_date: str = ""
    expected_intensity: str = ""


@dataclass
class EmployeeResult:
    cpf: str
    nome: str
    status_consulta: str
    ruido_encontrado: str
    detalhe_observado: str
    data_planilha: str = ""
    data_esocial: str = ""
    data_confere: str = ""
    intensidade_planilha: str = ""
    intensidade_esocial: str = ""
    intensidade_confere: str = ""
    evidencia_principal: str = ""
    erro: str = ""
    recuperacao: str = ""
    houve_ia: str = "não"
    revisao_humana: str = "não"

    def as_dict(self) -> dict[str, str]:
        return asdict(self)
