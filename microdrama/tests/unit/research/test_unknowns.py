"""Typed UNKNOWN outcomes: failures, missing dates, disabled providers, bad model output
never become PASS and are never silently dropped (T009)."""

from __future__ import annotations

from research_support import World, request

from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode
from microdrama.research import ProbeOutcome
from microdrama.testing.fakes import LLMScenario, SourceScenario


def test_provider_reported_failure_stays_unknown(world: World) -> None:
    world.sources.queue_scenarios(SourceScenario.SOURCE_FAILURE)
    season = world.season()
    result = world.service.run_research(season, request())
    assert result.state == "COMPLETED"
    outcome = result.outcome
    assert outcome is not None
    by_source = {probe.source_id: probe for probe in outcome.probes}
    assert by_source["src-thai-drama-1"].outcome is ProbeOutcome.UNKNOWN
    assert "failed" in (by_source["src-thai-drama-1"].detail or "")
    assert by_source["src-thai-drama-2"].outcome is ProbeOutcome.RETRIEVED
    # The failed source produced no document; nothing was dropped silently.
    assert [entry.source_id for entry in outcome.documents] == ["src-thai-drama-2"]


def test_missing_publication_date_is_a_typed_unknown(world: World) -> None:
    world.sources.queue_scenarios(SourceScenario.MISSING_PUBLISHED_AT)
    season = world.season()
    result = world.service.run_research(season, request())
    outcome = result.outcome
    assert outcome is not None
    assert outcome.date_unknown_source_ids == ["src-thai-drama-1", "src-thai-drama-2"]
    ledger = world.service.ledger(season)
    assert all(entry.published_at is None for entry in ledger)
    assert all(entry.date_status.value == "UNKNOWN" for entry in ledger)


def test_unregistered_provider_is_typed_unknown_with_zero_spend(world: World, db) -> None:
    from microdrama.research import build_research_service

    service = build_research_service(
        db,
        world.clock,
        world.ids,
        world.settings,
        budget=world.budget,
        source_providers={"fake-sources": world.sources},
        llm=None,
    )
    season = world.season()
    result = service.run_research(season, request(provider_id="no-such-provider"))
    assert result.state == "COMPLETED"
    outcome = result.outcome
    assert outcome is not None
    assert outcome.probes and all(
        probe.outcome is ProbeOutcome.UNKNOWN and "not registered" in (probe.detail or "")
        for probe in outcome.probes
    )
    assert outcome.documents == []
    assert world.account(season)["settled_micro_usd"] == 0
    assert world.sources.calls == [] and world.llm.calls == []


def test_live_provider_stub_stays_disabled_and_never_dispatches(world: World, db) -> None:
    from microdrama.research import build_research_service

    class LiveStub:
        provider_id = "live-web-sources"

        def search(self, query):  # pragma: no cover - must never be reached
            raise AssertionError("a disabled live adapter must never be dispatched")

    service = build_research_service(
        db,
        world.clock,
        world.ids,
        world.settings,
        budget=world.budget,
        source_providers={"live-web-sources": LiveStub(), "fake-sources": world.sources},
        llm=None,
    )
    record = service.registry["live-web-sources"]
    assert record.enabled is False and record.disabled_reason is not None
    season = world.season()
    result = service.run_research(season, request(provider_id="live-web-sources"))
    outcome = result.outcome
    assert outcome is not None
    assert all(probe.outcome is ProbeOutcome.UNKNOWN for probe in outcome.probes)
    assert world.account(season)["settled_micro_usd"] == 0


def test_fake_sources_disabled_outside_offline_mock(db, world: World) -> None:
    from microdrama.research import build_research_service

    paid = Settings(execution_mode=ExecutionMode.PAID_BENCHMARK)
    service = build_research_service(
        db,
        world.clock,
        world.ids,
        paid,
        budget=world.budget,
        source_providers={"fake-sources": world.sources},
        llm=None,
        config=None,
    )
    assert service.registry["fake-sources"].enabled is False
    season = world.season()
    result = service.run_research(season, request())
    outcome = result.outcome
    assert outcome is not None
    assert all(probe.outcome is ProbeOutcome.UNKNOWN for probe in outcome.probes)
    assert world.sources.calls == []
    assert world.account(season)["settled_micro_usd"] == 0


def test_transient_source_failure_retries_then_recovers(world: World) -> None:
    class FlakyOnce:
        """Wraps the fake: the first search raises, the second delegates (same provider id,
        so the receipts still match the reservation's provider)."""

        provider_id = "fake-sources"

        def __init__(self, inner) -> None:
            self._inner = inner
            self._raised = False

        def search(self, query):
            from microdrama.contracts.errors import TransientProviderError

            if not self._raised:
                self._raised = True
                raise TransientProviderError("flaky source timed out")
            return self._inner.search(query)

    flaky = FlakyOnce(world.sources)
    from microdrama.research import build_research_service

    service = build_research_service(
        world.db,
        world.clock,
        world.ids,
        world.settings,
        budget=world.budget,
        source_providers={"fake-sources": flaky},
        llm=world.llm,
    )
    season = world.season()
    result = service.run_research(season, request())
    assert result.state == "COMPLETED"
    outcome = result.outcome
    assert outcome is not None
    assert all(probe.outcome is ProbeOutcome.RETRIEVED for probe in outcome.probes)
    assert len(outcome.documents) == 2
    # One search reservation, settled once: the retry reused the same paid step.
    search_reservations = [
        row
        for row in world.reservations(season)
        if row["operation_kind"] == "research.source_search"
    ]
    assert len(search_reservations) == 1
    assert search_reservations[0]["state"] == "SETTLED"


def test_transient_source_failure_exhausting_releases_unbilled_exposure(world: World) -> None:
    from microdrama.contracts.errors import TransientProviderError

    class AlwaysTransient:
        provider_id = "fake-sources"

        def search(self, query):
            raise TransientProviderError("source down")

    from microdrama.research import build_research_service

    service = build_research_service(
        world.db,
        world.clock,
        world.ids,
        world.settings,
        budget=world.budget,
        source_providers={"fake-sources": AlwaysTransient()},
        llm=world.llm,
    )
    season = world.season()
    result = service.run_research(season, request())
    outcome = result.outcome
    assert outcome is not None
    assert all(probe.outcome is ProbeOutcome.UNKNOWN for probe in outcome.probes)
    # Nothing was billed for the search: no spend exists to retain, so the hold was freed.
    assert world.account(season)["reserved_outstanding_micro_usd"] == 0
    search_charges = world.rows(
        "SELECT c.* FROM charges c JOIN reservations r ON r.id = c.reservation_id "
        "WHERE c.season_id = %s AND r.operation_kind = 'research.source_search'",
        (season,),
    )
    assert search_charges == []


def test_malformed_llm_output_is_unknown_and_keeps_both_attempts_charges(world: World) -> None:
    world.llm.queue_scenarios(LLMScenario.MALFORMED_OUTPUT, LLMScenario.MALFORMED_OUTPUT)
    season = world.season()
    result = world.service.run_research(season, request())
    outcome = result.outcome
    assert outcome is not None
    assert outcome.synthesis.value == "UNKNOWN"
    assert any("model uncertainty notes unavailable" in note for note in outcome.uncertainty_notes)
    # Both paid attempts settled (failed attempts retain their spend, MD-008).
    llm_reservations = [
        row for row in world.reservations(season) if row["operation_kind"] == "research.llm_notes"
    ]
    assert len(llm_reservations) == 4  # two attempts x (input hold + output hold)
    assert all(row["state"] == "SETTLED" for row in llm_reservations)
    assert world.account(season)["settled_micro_usd"] == outcome.settled_micro_usd


def test_transient_llm_recovers_on_the_same_reservation(world: World) -> None:
    from microdrama.contracts.enums import RuntimeRole

    world.llm.queue_scenarios(LLMScenario.TRANSIENT_TIMEOUT)
    world.llm.script_role(
        RuntimeRole.RESEARCHER, {"uncertainty_notes": ["fixture signals are unmeasured"]}
    )
    season = world.season()
    result = world.service.run_research(season, request())
    outcome = result.outcome
    assert outcome is not None
    assert outcome.synthesis.value == "USED"
    assert "fixture signals are unmeasured" in outcome.uncertainty_notes
    llm_reservations = [
        row for row in world.reservations(season) if row["operation_kind"] == "research.llm_notes"
    ]
    assert len(llm_reservations) == 2 and all(
        row["state"] == "SETTLED" for row in llm_reservations
    )  # one input hold + one output hold, both settled once


def test_no_llm_configured_leaves_synthesis_unknown_without_inventing_notes(
    world: World, db
) -> None:
    from microdrama.research import build_research_service

    service = build_research_service(
        db,
        world.clock,
        world.ids,
        world.settings,
        budget=world.budget,
        source_providers={"fake-sources": world.sources},
        llm=None,
    )
    season = world.season()
    result = service.run_research(season, request())
    outcome = result.outcome
    assert outcome is not None
    assert outcome.synthesis.value == "UNKNOWN"
    # No "model notes unavailable" note is added when no LLM was configured at all.
    assert "model uncertainty notes unavailable" not in outcome.uncertainty_notes
    assert world.account(season)["settled_micro_usd"] > 0  # the search still ran
