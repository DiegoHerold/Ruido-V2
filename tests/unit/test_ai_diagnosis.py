from esocial_noise.healing.ai_diagnosis import _redact_for_ai, _response_diagnosis


def test_ai_payload_redacts_cpf_and_password() -> None:
    payload = _redact_for_ai({"visible_text": "CPF 00123456789", "password": "secret"})
    assert "00123456789" not in payload["visible_text"]
    assert payload["password"] == "[REDACTED]"


def test_openai_response_text_is_parsed() -> None:
    body = {"output": [{"content": [{"text": '{"classification":"unknown_screen"}'}]}]}
    assert _response_diagnosis(body)["classification"] == "unknown_screen"
