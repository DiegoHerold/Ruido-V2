from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import load_yaml
from ..runtime.execution import ExecutionContext


def find_hypotheses(root: Path, execution: ExecutionContext) -> list[dict[str, Any]]:
    execution.event("knowledge_search_started", current_step=execution.current_step)
    matches: list[dict[str, Any]] = []
    for path, key in ((root / "memory" / "hints.yaml", "hints"), (root / "memory" / "learned-findings.yaml", "learned_findings")):
        for item in load_yaml(path).get(key, []):
            if execution.current_step in item.get("applies_near", []):
                matches.append({"id": item.get("id"), "type": item.get("type", "learned"), "confidence": item.get("confidence", "low"), "note": item.get("note", "")})
    execution.event("knowledge_search_completed", matches=matches, authority="hypothesis_only")
    return matches
