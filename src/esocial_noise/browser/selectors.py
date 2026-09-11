from __future__ import annotations

import json
from typing import Any

from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from ..runtime.execution import ExecutionContext


class SelectorRegistry:
    def __init__(self, definitions: dict[str, Any], execution: ExecutionContext):
        self.definitions, self.execution = definitions, execution

    def definition(self, key: str) -> dict[str, Any]:
        if key not in self.definitions:
            raise KeyError(f"Selector inexistente: {key}")
        return self.definitions[key]

    def first_visible(self, page: Page, key: str, timeout_ms: int = 15000) -> Locator:
        return self.resolve(page, key, timeout_ms)[0]

    def resolve(self, page: Page, key: str, timeout_ms: int = 15000) -> tuple[Locator, dict[str, Any]]:
        definition = self.definition(key)
        options = [definition.get("primary", {})] + definition.get("fallbacks", [])
        for index, option in enumerate(options):
            serialized = json.dumps(option, ensure_ascii=False)
            self.execution.selectors_tried.append(f"{key}:{serialized}")
            if "role" in option:
                locator = page.get_by_role(option["role"], name=option.get("name"), exact=False).first
            elif "css" in option:
                locator = page.locator(option["css"]).first
            elif "label" in option:
                locator = page.get_by_label(option["label"], exact=False).first
            elif "placeholder" in option:
                locator = page.get_by_placeholder(option["placeholder"], exact=False).first
            elif "text" in option:
                locator = page.get_by_text(option["text"], exact=False).first
            elif "contains" in option:
                locator = page.get_by_text(option["contains"], exact=False).first
            else:
                continue
            try:
                locator.wait_for(state="visible", timeout=timeout_ms)
                self.execution.event(
                    "selector_resolved",
                    selector_key=key,
                    selector=serialized,
                    source="primary" if index == 0 else "declared_fallback",
                )
                if index:
                    self.execution.event("selector_fallback_used", selector_key=key, selector=serialized)
                return locator, definition
            except PlaywrightTimeoutError:
                continue
        raise PlaywrightTimeoutError(f"Nenhum seletor visível para {key}")
