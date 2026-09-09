from pathlib import Path

import pytest

from esocial_noise.contracts import SafetyBlocked
from esocial_noise.runtime.costs import AICostManager


def test_cost_is_persisted_even_when_budget_is_exceeded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_AI_COST_USD_PER_RUN", "0.01")
    manager = AICostManager(tmp_path, {"policy": {}})
    with pytest.raises(SafetyBlocked):
        manager.record("test", "model", {"input_tokens": 0, "output_tokens": 0}, reported_cost_usd=0.02)
    assert manager.total_usd == 0.02
    assert (tmp_path / "ai-costs.json").is_file()
