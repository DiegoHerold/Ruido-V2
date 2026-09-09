from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

from ..runtime.artifacts import BrowserEvidence
from ..runtime.execution import ExecutionContext
from ..utils import mask_cpf, safe_filename


def collect_failure(page: Page, execution: ExecutionContext, evidence: BrowserEvidence, error: Exception, root: Path) -> dict[str, Any]:
    files = evidence.capture(page, f"failure_{execution.current_step}")
    bundle = {"execution_id": execution.execution_id, "current_step": execution.current_step, "last_action": execution.last_action, "timeline": execution.events[-100:], "checkpoints": execution.checkpoints, "evidence": files, "selectors_tried": execution.selectors_tried[-50:], "cpf": mask_cpf(execution.current_cpf), "company": execution.company, "error": f"{type(error).__name__}: {error}", "traceback": traceback.format_exc(), "url": page.url, "page_title": page.title(), "visible_text_excerpt": page.locator("body").inner_text(timeout=5000)[:5000]}
    path = execution.artifact_dir / f"failure-bundle-{safe_filename(execution.current_step)}.json"
    bundle["bundle_path"] = str(path.relative_to(root))
    path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    execution.event("failure_evidence_collected", "error", bundle=bundle["bundle_path"], evidence=files)
    return bundle


def persist_bundle(bundle: dict[str, Any], root: Path) -> None:
    (root / bundle["bundle_path"]).write_text(json.dumps(bundle, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
