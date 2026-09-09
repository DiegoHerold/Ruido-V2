from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..utils import mask_cpf, utc_now


@dataclass
class ExecutionContext:
    execution_id: str
    artifact_dir: Path
    output_dir: Path
    company: str
    redact_events: bool = True
    current_step: str = "preflight"
    last_action: str = ""
    current_cpf: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    selectors_tried: list[str] = field(default_factory=list)
    recovery_attempts: int = 0
    ai_calls: int = 0

    def __post_init__(self) -> None:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.artifact_dir / "events.jsonl"

    def event(self, event_type: str, severity: str = "info", **payload: Any) -> None:
        record = {"event_id": f"evt_{uuid.uuid4().hex}", "event_type": event_type, "timestamp": utc_now(), "execution_id": self.execution_id, "step_id": self.current_step, "severity": severity, "payload": self._redact(payload)}
        self.events.append(record)
        with self.events_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def checkpoint(self, name: str, status: str, expected: dict[str, Any], observed: dict[str, Any], evidence: list[str]) -> None:
        item = {"checkpoint": name, "status": status, "timestamp": utc_now(), "expected": expected, "observed": self._redact(observed), "evidence": evidence, "safe_to_resume_from_here": status == "ok"}
        self.checkpoints.append(item)
        (self.artifact_dir / "checkpoints.json").write_text(json.dumps(self.checkpoints, ensure_ascii=False, indent=2), encoding="utf-8")
        self.event("checkpoint_recorded", "error" if status == "failed" else "info", checkpoint=name, status=status, evidence=evidence)

    def _redact(self, value: Any) -> Any:
        if not self.redact_events:
            return value
        if isinstance(value, dict):
            return {key: self._redact("[REDACTED]" if re.search(r"password|senha|token|cookie|authorization|certificate|certificado|private", key, re.I) else item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, str) and self.current_cpf:
            return value.replace(self.current_cpf, mask_cpf(self.current_cpf) or "")
        return value
