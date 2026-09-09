from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .contracts import SafetyBlocked


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


@dataclass(frozen=True)
class Settings:
    root: Path
    manifest: dict[str, Any]
    evidence_policy: dict[str, Any]
    recovery_policy: dict[str, Any]
    selectors: dict[str, Any]

    @classmethod
    def load(cls, root: Path) -> "Settings":
        manifest = load_yaml(root / "automation.yaml")
        recovery = load_yaml(root / "recovery-policy.yaml")
        required = {"id", "runtime", "application", "execution", "capabilities", "inputs", "outputs", "steps", "selectors", "self_healing", "policy", "artifacts", "certificate_ocr"}
        missing = required - manifest.keys()
        if missing:
            raise SafetyBlocked(f"Manifesto inválido: campos obrigatórios ausentes: {sorted(missing)}")
        if manifest.get("policy", {}).get("mode") != "read_only" or not manifest.get("policy", {}).get("block_write_actions") or recovery.get("mode") != "read_only":
            raise SafetyBlocked("Configuração inválida: apenas modo read_only com bloqueio de escrita é aceito.")
        import json
        selectors = json.loads((root / manifest["selectors"]["file"]).read_text(encoding="utf-8"))
        required_selectors = {"portal.esocial_access", "login.govbr", "govbr.certificate", "employee.search", "employee.search_submit", "sst.noise_section"}
        if required_selectors - selectors.keys():
            raise SafetyBlocked("Registry de seletores não contém todos os controles obrigatórios.")
        return cls(root, manifest, load_yaml(root / "evidence-policy.yaml"), recovery, selectors)
