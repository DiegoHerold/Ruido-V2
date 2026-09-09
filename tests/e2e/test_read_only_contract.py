import json
from pathlib import Path

from esocial_noise.safety.policy import IMMUTABLE_FORBIDDEN


def test_registry_does_not_define_write_selector_as_an_allowed_step() -> None:
    root = Path(__file__).resolve().parents[2]
    selectors = json.loads((root / "selectors.json").read_text(encoding="utf-8"))
    for key, value in selectors.items():
        serialized = json.dumps(value, ensure_ascii=False).casefold()
        assert not any(word in key.casefold() for word in IMMUTABLE_FORBIDDEN)
        assert "transmitir" in serialized or "employee" in key or "login" in key or "company" in key or "sst" in key
