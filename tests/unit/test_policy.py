import pytest

from esocial_noise.contracts import SafetyBlocked
from esocial_noise.safety.policy import ReadOnlyPolicy


def test_blocks_transmission_semantics() -> None:
    policy = ReadOnlyPolicy({"limits": {"max_total_attempts": 2}})
    with pytest.raises(SafetyBlocked):
        policy.assert_target_allowed("Transmitir evento", {})


def test_allows_read_only_search() -> None:
    policy = ReadOnlyPolicy({"limits": {"max_total_attempts": 2}})
    policy.assert_target_allowed("Pesquisar trabalhador", {"do_not_match_text": []})
    assert policy.can_retry(1)
    assert not policy.can_retry(2)
