from __future__ import annotations

import json
import os
from pathlib import Path

from ..contracts import EmployeeResult
from ..utils import utc_now


class ExecutionState:
    """Snapshot local atômico por CPF, para auditoria e retomada manual segura."""
    def __init__(self, path: Path, execution_id: str) -> None:
        self.path, self.execution_id = path, execution_id
        self.data = {"execution_id": execution_id, "updated_at": utc_now(), "context_trusted": True, "employees": []}
        self._flush()

    def record(self, result: EmployeeResult, context_trusted: bool) -> None:
        self.data["updated_at"] = utc_now()
        self.data["context_trusted"] = context_trusted
        self.data["employees"].append(result.as_dict())
        self._flush()

    def _flush(self) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)
