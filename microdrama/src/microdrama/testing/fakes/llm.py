"""Fake language-model provider (T007).

Outputs are deterministic: a response scripted for a ``client_token`` wins, then one scripted
for the ``RuntimeRole``, then a default object synthesised from the request's ``output_schema``.
``MALFORMED_OUTPUT`` returns an output that violates the schema (a required key is dropped), so
callers must validate. A repeated ``client_token`` returns the identical response and is never
billed twice.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, ClassVar

from microdrama.contracts.enums import (
    BudgetCategory,
    PriceUnit,
    Provenance,
    ReceiptKind,
    RuntimeRole,
)
from microdrama.contracts.errors import PolicyDenied, TransientProviderError
from microdrama.contracts.providers import LLMRequest, LLMResponse
from microdrama.testing.fakes.common import (
    FakeBase,
    FakeClock,
    SequentialIds,
    priced,
    synthetic_receipt,
)


class LLMScenario(StrEnum):
    HAPPY = "HAPPY"
    TRANSIENT_TIMEOUT = "TRANSIENT_TIMEOUT"  # raises TransientProviderError; nothing billed
    DENIED = "DENIED"  # raises PolicyDenied
    MALFORMED_OUTPUT = "MALFORMED_OUTPUT"  # output does not satisfy output_schema


def synthesize(schema: Mapping[str, Any], label: str) -> Any:
    """Smallest deterministic value that satisfies the common JSON-schema keywords."""
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object" or (kind is None and "properties" in schema):
        props: Mapping[str, Any] = schema.get("properties", {})
        required = schema.get("required", list(props))
        return {k: synthesize(props[k], f"{label}.{k}") for k in required if k in props}
    if kind == "array":
        items: Mapping[str, Any] = schema.get("items", {})
        return [synthesize(items, f"{label}[{i}]") for i in range(int(schema.get("minItems", 0)))]
    if kind == "string":
        return f"fake {label}"
    if kind in ("integer", "number"):
        return int(schema.get("minimum", 0))
    if kind == "boolean":
        return False
    return None


def malform(schema: Mapping[str, Any], output: Mapping[str, Any]) -> dict[str, Any]:
    """Break the output so it fails the schema: drop a required key (or add a marker)."""
    required = list(schema.get("required", []))
    if required:
        broken = dict(output)
        broken.pop(required[0], None)
        return broken
    return {"__malformed__": True}


def _approx_tokens(text: str) -> int:
    return max(1, -(-len(text) // 4))  # ceiling of chars/4, a deterministic stand-in for tokens


class FakeLLMProvider(FakeBase):
    provider_id: str = "fake-llm"
    default_scenario: ClassVar[LLMScenario] = LLMScenario.HAPPY

    def __init__(
        self,
        *,
        clock: FakeClock,
        ids: SequentialIds,
        scenarios: tuple[LLMScenario, ...] = (),
    ) -> None:
        super().__init__(clock=clock, ids=ids, scenarios=scenarios)
        self._scripted_by_role: dict[RuntimeRole, dict[str, Any]] = {}
        self._scripted_by_token: dict[str, dict[str, Any]] = {}
        self._responses: dict[str, LLMResponse] = {}

    def script_role(self, role: RuntimeRole, output: Mapping[str, Any]) -> None:
        self._scripted_by_role[role] = dict(output)

    def script_token(self, client_token: str, output: Mapping[str, Any]) -> None:
        self._scripted_by_token[client_token] = dict(output)

    def _output_for(self, request: LLMRequest) -> dict[str, Any]:
        if request.client_token in self._scripted_by_token:
            return dict(self._scripted_by_token[request.client_token])
        if request.role in self._scripted_by_role:
            return dict(self._scripted_by_role[request.role])
        synthesized = synthesize(request.output_schema, request.role.value.lower())
        return synthesized if isinstance(synthesized, dict) else {}

    def generate(self, request: LLMRequest) -> LLMResponse:
        if request.client_token in self._responses:
            self._log_replay("generate", request.client_token)
            return self._responses[request.client_token]
        step = self._step("generate", key=request.client_token)
        if step is LLMScenario.TRANSIENT_TIMEOUT:
            raise TransientProviderError(
                "fake LLM timed out before a response", client_token=request.client_token
            )
        if step is LLMScenario.DENIED:
            raise PolicyDenied("fake LLM denied this request", client_token=request.client_token)

        output = self._output_for(request)
        if step is LLMScenario.MALFORMED_OUTPUT:
            output = malform(request.output_schema, output)

        now = self.clock.now()
        in_text = request.instruction + "".join(request.untrusted_documents)
        in_tokens = min(request.max_input_tokens, _approx_tokens(in_text))
        out_tokens = min(
            request.max_output_tokens, _approx_tokens(json.dumps(output, ensure_ascii=False))
        )
        usage = [
            synthetic_receipt(
                provider=self.provider_id,
                provider_receipt_id=f"llm:{request.client_token}:in",
                kind=ReceiptKind.SETTLEMENT,
                category=BudgetCategory.RESEARCH_SCRIPT_PROMPTS_METADATA,
                unit=PriceUnit.INPUT_TOKEN_1K,
                units=-(-in_tokens // 1000) or 1,
                amount_micro_usd=priced(PriceUnit.INPUT_TOKEN_1K, -(-in_tokens // 1000) or 1),
                observed_at=now,
                reservation_id=request.reservation_id,
            ),
            synthetic_receipt(
                provider=self.provider_id,
                provider_receipt_id=f"llm:{request.client_token}:out",
                kind=ReceiptKind.SETTLEMENT,
                category=BudgetCategory.RESEARCH_SCRIPT_PROMPTS_METADATA,
                unit=PriceUnit.OUTPUT_TOKEN_1K,
                units=-(-out_tokens // 1000) or 1,
                amount_micro_usd=priced(PriceUnit.OUTPUT_TOKEN_1K, -(-out_tokens // 1000) or 1),
                observed_at=now,
                reservation_id=request.reservation_id,
            ),
        ]
        response = LLMResponse(
            request_id=request.request_id,
            output=output,
            stop_reason="end_turn",
            usage=usage,
            model_config_ref=request.model_config_ref,
            provenance=Provenance.FAKE_SYNTHETIC,
        )
        self._responses[request.client_token] = response
        self._bill(usage)
        return response


__all__ = ["FakeLLMProvider", "LLMScenario", "malform", "synthesize"]
