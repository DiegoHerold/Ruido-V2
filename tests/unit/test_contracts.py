import pytest

from esocial_noise.contracts import Diagnosis


def test_diagnosis_contract_rejects_invalid_classification() -> None:
    payload = {"classification": "wrong", "probable_root_cause_step": "x", "is_last_action_root_cause": True, "diagnosis": "x", "confidence": 0.5, "recommended_recovery": {}, "required_validation": [], "risk": "low", "requires_human": True}
    with pytest.raises(ValueError):
        Diagnosis.from_payload(payload)


def test_diagnosis_contract_accepts_required_schema() -> None:
    payload = {"classification": "timing_issue", "probable_root_cause_step": "employee_search_started", "is_last_action_root_cause": True, "diagnosis": "loading", "confidence": 0.8, "recommended_recovery": {"type": "wait"}, "required_validation": ["field visible"], "risk": "low", "requires_human": False}
    assert Diagnosis.from_payload(payload).classification == "timing_issue"
