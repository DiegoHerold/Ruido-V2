from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
import unicodedata


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip().casefold()


def normalize_cpf(value: Any) -> str:
    if value is None or str(value).strip() in {"", "nan", "None"}:
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    digits = re.sub(r"\D", "", text)
    return digits.zfill(11) if digits else ""


def mask_cpf(cpf: str | None) -> str | None:
    return f"***.***.***-{cpf[-2:]}" if cpf else cpf


def safe_filename(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value)[:100]
