from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

from ..runtime.execution import ExecutionContext
from ..utils import safe_filename


class BrowserEvidence:
    def __init__(self, execution: ExecutionContext, root: Path):
        self.execution, self.root = execution, root

    def capture(self, page: Page, label: str, include_dom: bool = True) -> list[str]:
        stamp = f"{int(time.time() * 1000)}_{safe_filename(label)}"
        files: list[str] = []
        screenshot = self.execution.artifact_dir / f"{stamp}.png"
        page.screenshot(path=str(screenshot), full_page=True)
        files.append(str(screenshot.relative_to(self.root)))
        text = page.locator("body").inner_text(timeout=5000)[:30000]
        text_file = self.execution.artifact_dir / f"{stamp}.visible-text.txt"
        text_file.write_text(text, encoding="utf-8")
        files.append(str(text_file.relative_to(self.root)))
        if include_dom:
            dom_file = self.execution.artifact_dir / f"{stamp}.dom.html"
            dom_file.write_text(page.content(), encoding="utf-8")
            files.append(str(dom_file.relative_to(self.root)))
            tree = page.locator("body").evaluate("""el => [...el.querySelectorAll('button,a,input,select,textarea,[role]')]
                .slice(0,500).map(x => ({tag:x.tagName,role:x.getAttribute('role'),name:x.getAttribute('aria-label') || x.innerText || x.value || '',disabled:x.disabled || false}))""")
            tree_file = self.execution.artifact_dir / f"{stamp}.accessibility.json"
            tree_file.write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8")
            files.append(str(tree_file.relative_to(self.root)))
        self.execution.event("artifact_created", label=label, artifacts=files)
        return files
