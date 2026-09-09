from __future__ import annotations

from typing import Any

from ..contracts import Diagnosis
from ..runtime.execution import ExecutionContext


def analyze(bundle: dict[str, Any], execution: ExecutionContext) -> Diagnosis:
    suspicious = [checkpoint["checkpoint"] for checkpoint in bundle["checkpoints"] if checkpoint["status"] in {"suspicious", "failed"}]
    diagnosis = Diagnosis("previous_step_suspicious" if suspicious else "unknown_screen", suspicious[-1] if suspicious else execution.current_step, not bool(suspicious), "Checkpoint anterior requer revisão." if suspicious else "Falha sem classificação determinística.", 0.75 if suspicious else 0.2, {}, ["validar checkpoints anteriores"], "medium", bool(suspicious))
    execution.event("root_cause_analyzed", classification=diagnosis.classification, root_cause_step=diagnosis.probable_root_cause_step, requires_human=diagnosis.requires_human)
    return diagnosis
