from __future__ import annotations

import os
import json
import re
from typing import Any

import httpx

from ..contracts import Diagnosis
from ..runtime.execution import ExecutionContext
from ..runtime.costs import AICostManager


def _redact_for_ai(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_for_ai("[REDACTED]" if re.search(r"password|senha|token|cookie|authorization|certificate|certificado|private", key, re.I) else item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_for_ai(item) for item in value]
    if isinstance(value, str):
        return re.sub(r"(?<!\d)\d{11}(?!\d)", "***.***.***-**", value)
    return value


def _response_diagnosis(body: dict[str, Any]) -> dict[str, Any]:
    if "diagnosis" in body:
        return body["diagnosis"]
    if "classification" in body:
        return body
    for output in body.get("output", []):
        for content in output.get("content", []):
            text = content.get("text") or content.get("output_text")
            if text:
                return json.loads(text)
    raise ValueError("A resposta da IA não contém o JSON de diagnóstico esperado.")


def diagnose_if_enabled(bundle: dict[str, Any], manifest: dict[str, Any], execution: ExecutionContext, costs: AICostManager) -> Diagnosis | None:
    """Adaptador opcional: envia apenas o resumo redigido, nunca DOM, imagens ou credenciais."""
    endpoint = os.getenv("AI_DIAGNOSIS_ENDPOINT")
    enabled = os.getenv("AI_DIAGNOSIS_ENABLED", "false").strip().lower() == "true"
    if not endpoint or not enabled or not manifest["self_healing"].get("ai_diagnosis_enabled"):
        return None
    payload: dict[str, Any] = _redact_for_ai({"current_step": bundle["current_step"], "last_action": bundle["last_action"], "error": bundle["error"], "checkpoints": bundle["checkpoints"], "visible_text_excerpt": bundle["visible_text_excerpt"], "knowledge": bundle.get("knowledge", []), "required_schema": list(Diagnosis.__dataclass_fields__)})
    costs.assert_can_call(estimated_input_tokens=len(str(payload)) // 4)
    execution.event("ai_call_started", reason="deterministic_recovery_insufficient")
    headers = {"Authorization": f"Bearer {os.environ['AI_DIAGNOSIS_API_KEY']}"} if os.getenv("AI_DIAGNOSIS_API_KEY") else {}
    provider = os.getenv("AI_DIAGNOSIS_PROVIDER", "diagnostic_proxy")
    if provider == "openai_responses":
        request = {"model": os.getenv("AI_DIAGNOSIS_MODEL", "gpt-5.6-luna"), "store": False, "max_output_tokens": costs.max_output_tokens, "instructions": "Você diagnostica falhas de uma automação de consulta somente leitura do eSocial. Retorne somente um JSON válido com os campos exigidos. Nunca recomende transmissão, alteração, exclusão, assinatura, captura de credenciais ou bypass de autenticação.", "input": json.dumps(payload, ensure_ascii=False)}
    else:
        request = {"model": os.getenv("AI_DIAGNOSIS_MODEL", ""), "evidence": payload}
    response = httpx.post(endpoint, json=request, headers=headers, timeout=30)
    response.raise_for_status()
    response_body = response.json()
    diagnosis = Diagnosis.from_payload(_response_diagnosis(response_body))
    record = costs.record("deterministic_recovery_insufficient", os.getenv("AI_DIAGNOSIS_MODEL", "unspecified"), response_body.get("usage"), response_body.get("cost_usd"))
    execution.ai_calls += 1
    execution.event("ai_call_completed", classification=diagnosis.classification, risk=diagnosis.risk, confidence=diagnosis.confidence, cost_usd=record.cost_usd, input_tokens=record.input_tokens, output_tokens=record.output_tokens)
    return diagnosis
