from pathlib import Path

import pytest

from esocial_noise.config import Settings
from esocial_noise.contracts import SafetyBlocked


def test_manifest_requires_read_only_contract(tmp_path: Path) -> None:
    (tmp_path / "automation.yaml").write_text("policy: {mode: write, block_write_actions: false}\n", encoding="utf-8")
    (tmp_path / "recovery-policy.yaml").write_text("mode: read_only\n", encoding="utf-8")
    with pytest.raises(SafetyBlocked):
        Settings.load(tmp_path)
