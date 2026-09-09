from __future__ import annotations

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from ..browser.selectors import SelectorRegistry
from ..runtime.artifacts import BrowserEvidence
from ..runtime.execution import ExecutionContext
from ..safety.policy import ReadOnlyPolicy


def deterministic_retry(page: Page, selectors: SelectorRegistry, policy: ReadOnlyPolicy, evidence: BrowserEvidence, execution: ExecutionContext) -> bool:
    if not policy.can_retry(execution.recovery_attempts):
        return False
    execution.recovery_attempts += 1
    execution.event("self_healing_attempt_started", kind="wait_and_requery", attempt=execution.recovery_attempts)
    page.wait_for_timeout(1800)
    files = evidence.capture(page, f"deterministic_recovery_{execution.current_step}", include_dom=False)
    allowed = False
    if execution.current_step == "employee_search_started":
        try:
            selectors.first_visible(page, "employee.search", timeout_ms=1200)
            allowed = True
        except PlaywrightTimeoutError:
            pass
    execution.event("self_healing_attempt_completed", kind="wait_and_requery", outcome="retry_allowed" if allowed else "no_safe_recovery", evidence=files)
    return allowed
