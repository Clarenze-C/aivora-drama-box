"""Source and LLM fakes: deterministic outputs, scripted failures, and injection text kept as data."""

from __future__ import annotations

import uuid

import jsonschema
import pytest

from microdrama.contracts.enums import Provenance, RuntimeRole, SourceQuality
from microdrama.contracts.errors import PolicyDenied, TransientProviderError
from microdrama.contracts.providers import LLMProvider, LLMRequest, SourceProvider, SourceQuery
from microdrama.testing.fakes import (
    FakeClock,
    FakeLLMProvider,
    FakeSourceProvider,
    LLMScenario,
    SequentialIds,
    SourceScenario,
)
from microdrama.testing.fakes.llm import malform, synthesize
from microdrama.testing.fakes.sources import INJECTION_TEXT

SCHEMA = {
    "type": "object",
    "required": ["title", "budget_micro_usd"],
    "properties": {
        "title": {"type": "string"},
        "budget_micro_usd": {"type": "integer", "minimum": 0},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
}


def _query(
    *sources: str, max_results: int = 20, reservation: uuid.UUID | None = None
) -> SourceQuery:
    return SourceQuery(
        query_id=uuid.UUID(int=7),
        query_text="fixture research topic",
        allowed_source_ids=list(sources),
        max_results=max_results,
        reservation_id=reservation,
    )


def _llm_request(token: str = "tok-1", role: RuntimeRole = RuntimeRole.RESEARCHER) -> LLMRequest:
    return LLMRequest(
        request_id=uuid.UUID(int=11),
        role=role,
        model_config_ref="fake-research-profile",
        instruction="Summarise the fixture documents as JSON.",
        untrusted_documents=["doc one body", "doc two body"],
        output_schema=SCHEMA,
        max_input_tokens=4_000,
        max_output_tokens=500,
        client_token=token,
    )


@pytest.fixture
def sources(clock: FakeClock, ids: SequentialIds) -> FakeSourceProvider:
    return FakeSourceProvider(clock=clock, ids=ids)


@pytest.fixture
def llm(clock: FakeClock, ids: SequentialIds) -> FakeLLMProvider:
    return FakeLLMProvider(clock=clock, ids=ids)


def test_both_fakes_satisfy_their_protocols(
    sources: FakeSourceProvider, llm: FakeLLMProvider
) -> None:
    assert isinstance(sources, SourceProvider)
    assert isinstance(llm, LLMProvider)


def test_source_happy_path_returns_fixture_documents_with_fake_labels(
    sources: FakeSourceProvider,
) -> None:
    result = sources.search(_query("alpha", "beta"))
    assert [d.source_id for d in result.documents] == ["alpha", "beta"]
    assert result.failed_source_ids == []
    for doc in result.documents:
        assert doc.quality is SourceQuality.FIXTURE
        assert doc.provenance is Provenance.FAKE_SYNTHETIC
        assert doc.url.startswith("https://sources.fake.invalid/")
        assert doc.published_at is not None
    assert result.usage[0].provenance is Provenance.FAKE_SYNTHETIC


def test_source_failure_lists_the_failed_id_and_omits_its_document(
    clock: FakeClock, ids: SequentialIds
) -> None:
    fake = FakeSourceProvider(clock=clock, ids=ids, scenarios=(SourceScenario.SOURCE_FAILURE,))
    result = fake.search(_query("alpha", "beta"))
    assert result.failed_source_ids == ["alpha"]
    assert [d.source_id for d in result.documents] == ["beta"]


def test_missing_published_at_is_none_not_a_guess(clock: FakeClock, ids: SequentialIds) -> None:
    fake = FakeSourceProvider(
        clock=clock, ids=ids, scenarios=(SourceScenario.MISSING_PUBLISHED_AT,)
    )
    assert all(d.published_at is None for d in fake.search(_query("alpha")).documents)


def test_injection_text_is_only_excerpt_data(clock: FakeClock, ids: SequentialIds) -> None:
    fake = FakeSourceProvider(
        clock=clock, ids=ids, scenarios=(SourceScenario.INJECTION_IN_EXCERPT,)
    )
    result = fake.search(_query("alpha", "beta"))
    assert INJECTION_TEXT in result.documents[0].excerpt
    assert INJECTION_TEXT not in result.documents[1].excerpt
    # The fake never acts on the text: budgets and reservations are untouched by it.
    assert result.usage[0].amount_micro_usd == 1_000


def test_source_usage_is_billed_once_per_query_and_repeats_add_nothing(
    sources: FakeSourceProvider,
) -> None:
    sources.search(_query("alpha"))
    sources.search(_query("alpha"))
    assert len(sources.ledger) == 1


def test_llm_happy_path_output_satisfies_its_schema(llm: FakeLLMProvider) -> None:
    response = llm.generate(_llm_request())
    jsonschema.validate(response.output, SCHEMA)
    assert response.provenance is Provenance.FAKE_SYNTHETIC
    assert all(r.provenance is Provenance.FAKE_SYNTHETIC for r in response.usage)
    assert {r.unit.value for r in response.usage} == {"INPUT_TOKEN_1K", "OUTPUT_TOKEN_1K"}


def test_llm_scripted_outputs_win_by_token_then_role(llm: FakeLLMProvider) -> None:
    llm.script_role(RuntimeRole.RESEARCHER, {"title": "by role", "budget_micro_usd": 1})
    llm.script_token("tok-special", {"title": "by token", "budget_micro_usd": 2})
    assert llm.generate(_llm_request("tok-plain")).output["title"] == "by role"
    assert llm.generate(_llm_request("tok-special")).output["title"] == "by token"


def test_llm_transient_timeout_raises_and_bills_nothing(
    clock: FakeClock, ids: SequentialIds
) -> None:
    fake = FakeLLMProvider(clock=clock, ids=ids, scenarios=(LLMScenario.TRANSIENT_TIMEOUT,))
    with pytest.raises(TransientProviderError) as info:
        fake.generate(_llm_request())
    assert info.value.transient is True
    assert fake.ledger == []


def test_llm_denied_raises_policy_denied(clock: FakeClock, ids: SequentialIds) -> None:
    fake = FakeLLMProvider(clock=clock, ids=ids, scenarios=(LLMScenario.DENIED,))
    with pytest.raises(PolicyDenied):
        fake.generate(_llm_request())


def test_llm_malformed_output_fails_schema_validation(clock: FakeClock, ids: SequentialIds) -> None:
    fake = FakeLLMProvider(clock=clock, ids=ids, scenarios=(LLMScenario.MALFORMED_OUTPUT,))
    response = fake.generate(_llm_request())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(response.output, SCHEMA)
    assert response.provenance is Provenance.FAKE_SYNTHETIC


def test_duplicate_client_token_returns_identical_response_without_double_billing(
    llm: FakeLLMProvider,
) -> None:
    first = llm.generate(_llm_request("tok-dup"))
    second = llm.generate(_llm_request("tok-dup"))
    assert first == second
    assert len(llm.ledger) == 2  # one input and one output receipt, billed once
    assert [c.scenario for c in llm.calls] == ["HAPPY", "REPLAYED"]


def test_synthesize_and_malform_follow_the_schema_rules() -> None:
    value = synthesize(SCHEMA, "x")
    jsonschema.validate(value, SCHEMA)
    broken = malform(SCHEMA, value)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(broken, SCHEMA)
