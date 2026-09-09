from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..contracts import SafetyBlocked
from ..utils import utc_now


def _number(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError as error:
        raise SafetyBlocked(f"Variável {name} deve ser numérica.") from error


@dataclass(frozen=True)
class AICostRecord:
    timestamp: str
    reason: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    provider_reported_cost_usd: float | None


class AICostManager:
    """Impõe orçamento antes da chamada e persiste o custo depois dela."""
    def __init__(self, artifact_dir: Path, manifest: dict[str, Any]) -> None:
        policy = manifest["policy"]
        self.path = artifact_dir / "ai-costs.json"
        self.max_calls = int(os.getenv("MAX_AI_CALLS_PER_RUN", policy.get("max_ai_calls_per_run", 1)))
        self.max_input_tokens = int(os.getenv("MAX_AI_INPUT_TOKENS_PER_RUN", policy.get("max_ai_input_tokens_per_run", 12000)))
        self.max_output_tokens = int(os.getenv("MAX_AI_OUTPUT_TOKENS_PER_RUN", policy.get("max_ai_output_tokens_per_run", 1500)))
        self.max_cost_usd = _number("MAX_AI_COST_USD_PER_RUN", policy.get("max_ai_cost_usd_per_run", 0.25))
        self.input_price_per_million = _number("AI_INPUT_COST_USD_PER_1M", 0)
        self.output_price_per_million = _number("AI_OUTPUT_COST_USD_PER_1M", 0)
        self.records: list[AICostRecord] = []
        self._write()

    @property
    def total_usd(self) -> float:
        return round(sum(record.cost_usd for record in self.records), 8)

    def assert_can_call(self, estimated_input_tokens: int = 0) -> None:
        if len(self.records) >= self.max_calls:
            raise SafetyBlocked("Orçamento IA bloqueou nova chamada: máximo de chamadas atingido.")
        if sum(record.input_tokens for record in self.records) + estimated_input_tokens > self.max_input_tokens:
            raise SafetyBlocked("Orçamento IA bloqueou nova chamada: máximo de tokens de entrada atingido.")
        projected = self.total_usd + estimated_input_tokens * self.input_price_per_million / 1_000_000
        if projected > self.max_cost_usd:
            raise SafetyBlocked("Orçamento IA bloqueou nova chamada: custo estimado excede o limite.")

    def record(self, reason: str, model: str, usage: dict[str, Any] | None, reported_cost_usd: float | None = None) -> AICostRecord:
        usage = usage or {}
        input_tokens = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
        output_tokens = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
        token_exceeded = sum(item.input_tokens for item in self.records) + input_tokens > self.max_input_tokens or sum(item.output_tokens for item in self.records) + output_tokens > self.max_output_tokens
        estimated = input_tokens * self.input_price_per_million / 1_000_000 + output_tokens * self.output_price_per_million / 1_000_000
        cost = float(reported_cost_usd) if reported_cost_usd is not None else estimated
        record = AICostRecord(utc_now(), reason, model, input_tokens, output_tokens, round(cost, 8), reported_cost_usd)
        self.records.append(record)
        self._write()
        if token_exceeded:
            raise SafetyBlocked("Resposta IA excedeu o orçamento de tokens; gasto registrado e novas chamadas bloqueadas.")
        if self.total_usd > self.max_cost_usd:
            raise SafetyBlocked("Resposta IA excedeu o orçamento de custo; gasto registrado e novas chamadas bloqueadas.")
        return record

    def _write(self) -> None:
        self.path.write_text(json.dumps({"currency": "USD", "max_cost_usd": self.max_cost_usd, "total_cost_usd": self.total_usd, "records": [asdict(record) for record in self.records]}, ensure_ascii=False, indent=2), encoding="utf-8")
