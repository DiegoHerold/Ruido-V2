from __future__ import annotations

from typing import Any

from ..contracts import SafetyBlocked
from ..utils import normalize_text

IMMUTABLE_FORBIDDEN = ("transmit", "enviar", "envio definitivo", "retificar", "excluir", "alterar", "assinar", "salvar")


class ReadOnlyPolicy:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    def assert_target_allowed(self, target_text: str, selector: dict[str, Any]) -> None:
        observed = normalize_text(target_text)
        prohibited = [normalize_text(item) for item in IMMUTABLE_FORBIDDEN + tuple(selector.get("do_not_match_text", []))]
        if any(item and item in observed for item in prohibited):
            raise SafetyBlocked("Política bloqueou alvo com semântica de escrita, transmissão ou alteração.")

    def can_retry(self, attempts: int) -> bool:
        return attempts < int(self.config["limits"].get("max_total_attempts", 5))

    def recovery_allowed(self, kind: str, attempts: int = 0) -> bool:
        """Autoriza somente recuperaÃ§Ãµes declaradas e dentro do limite local."""
        if kind not in set(self.config.get("allowed_auto_recovery", [])):
            return False
        contract = self.config.get("recovery_contracts", {}).get(kind, {})
        return attempts < int(contract.get("max_attempts_per_context", 1))

    def requires_human(self, reason: str) -> bool:
        return reason in set(self.config.get("requires_human", []))
