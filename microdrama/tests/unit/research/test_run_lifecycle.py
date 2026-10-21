"""Run lifecycle: happy path, ledger dedupe, idempotent replays, typed refusals (T009)."""

from __future__ import annotations

import uuid

import pytest
from research_support import (
    World,
    default_concepts,
    request,
)

from microdrama.contracts.errors import (
    BudgetExhausted,
    Conflict,
    IdempotencyConflict,
    InvalidTransition,
    NotFound,
    SchemaInvalid,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.persistence import insert_row
from microdrama.research import normalized_request_hash


def test_happy_path_writes_versioned_proposal_with_provenance(world: World) -> None:
    season = world.season()
    result = world.service.run_research(season, request())
    assert result.state == "COMPLETED"
    assert result.replayed is False
    assert result.proposal_id is not None

    outcome = result.outcome
    assert outcome is not None
    assert [p.outcome.value for p in outcome.probes] == ["RETRIEVED", "RETRIEVED"]
    assert len(outcome.documents) == 2
    assert outcome.new_documents == 2 and outcome.duplicate_documents == 0
    assert outcome.synthesis.value == "USED"
    assert outcome.chosen_concept_id == "concept-a"
    assert outcome.settled_micro_usd > 0
    assert outcome.ranked[0].rank == 1 and outcome.ranked[0].concept_id == "concept-a"
    assert outcome.ranked[1].rank == 2

    proposal = world.row("SELECT * FROM season_proposals WHERE id = %s", (result.proposal_id,))
    assert proposal is not None
    assert proposal["scope_version"] == 1
    assert proposal["status"] == "PROPOSED"
    scope = proposal["scope"]
    assert scope["season_id"] == str(season)
    assert scope["source_proposal_id"] == str(result.proposal_id)
    assert proposal["scope_hash"] == canonical_hash(scope)
    provenance = proposal["source_provenance"]
    assert len(provenance) == 2
    assert {entry["source_id"] for entry in provenance} == {
        "src-thai-drama-1",
        "src-thai-drama-2",
    }
    assert len(proposal["research_reservation_ids"]) == 3  # search + llm in/out holds
    season_row = world.row("SELECT * FROM seasons WHERE id = %s", (season,))
    assert season_row["current_proposal_id"] == result.proposal_id

    run = world.run_row(season)
    assert run["state"] == "COMPLETED"
    assert run["settled_micro_usd"] == outcome.settled_micro_usd
    assert run["planned_worst_case_micro_usd"] >= outcome.settled_micro_usd


def test_second_run_versions_the_proposal_and_dedupes_the_ledger(world: World) -> None:
    season = world.season()
    first = world.service.run_research(season, request())
    second = world.service.run_research(season, request(key="research.daily:v2"))
    assert second.state == "COMPLETED" and second.replayed is False
    assert second.proposal_id != first.proposal_id
    versions = [row["scope_version"] for row in world.proposals(season)]
    assert versions == [1, 2]

    ledger = world.service.ledger(season)
    assert len(ledger) == 2  # deduped: same fixture excerpts hash identically
    assert all(entry.mention_count == 2 for entry in ledger)
    assert {entry.first_seen_run_id for entry in ledger} == {first.run_id}
    assert {entry.last_seen_run_id for entry in ledger} == {second.run_id}
    assert second.outcome is not None
    assert second.outcome.new_documents == 0 and second.outcome.duplicate_documents == 2


def test_repeated_schedule_trigger_replays_without_resetting_the_allowance(world: World) -> None:
    season = world.season()
    first = world.service.run_research(season, request())
    settled_after_first = world.account(season)["settled_micro_usd"]
    reservations_after_first = len(world.reservations(season))

    replay = world.service.run_research(season, request())  # same trigger key, same content

    assert replay.replayed is True
    assert replay.run_id == first.run_id
    assert replay.proposal_id == first.proposal_id
    assert world.count("SELECT count(*) FROM research_runs WHERE season_id = %s", (season,)) == 1
    assert len(world.reservations(season)) == reservations_after_first
    assert world.account(season)["settled_micro_usd"] == settled_after_first
    assert world.committed(season) == settled_after_first
    assert len(world.proposals(season)) == 1


def test_same_trigger_key_with_different_content_is_refused(world: World) -> None:
    season = world.season()
    world.service.run_research(season, request())
    with pytest.raises(IdempotencyConflict):
        world.service.run_research(season, request(queries=("a different query text",)))
    assert world.count("SELECT count(*) FROM research_runs WHERE season_id = %s", (season,)) == 1


def test_running_run_conflicts_until_terminal(world: World) -> None:
    season = world.season()
    req = request()
    run_id = uuid.uuid4()
    with world.db.transaction() as tx:
        insert_row(
            tx,
            "research_runs",
            {
                "id": run_id,
                "season_id": season,
                "trigger_kind": req.trigger.value,
                "semantic_key": req.trigger_key,
                "request_hash": normalized_request_hash(req),
                "state": "RUNNING",
                "planned_worst_case_micro_usd": 1,
                "started_at": world.clock.now(),
            },
        )
    with pytest.raises(Conflict):
        world.service.run_research(season, req)


def test_missing_envelope_is_typed_not_found_and_nothing_dispatches(world: World) -> None:
    season = world.season(envelope=None)
    with pytest.raises(NotFound, match="research envelope"):
        world.service.run_research(season, request())
    assert world.sources.calls == []
    assert world.llm.calls == []
    assert world.count("SELECT count(*) FROM research_runs WHERE season_id = %s", (season,)) == 0


def test_envelope_too_small_refuses_to_start(world: World) -> None:
    season = world.season(envelope=7_999)  # planned worst case is 8,000
    with pytest.raises(BudgetExhausted) as excinfo:
        world.service.run_research(season, request())
    assert excinfo.value.details["planned_worst_case_micro_usd"] == 8_000
    assert world.sources.calls == []
    assert world.count("SELECT count(*) FROM research_runs WHERE season_id = %s", (season,)) == 0
    assert world.committed(season) == 0


def test_non_proposed_season_refuses_new_runs_but_replays_old_ones(world: World) -> None:
    season = world.season()
    first = world.service.run_research(season, request())
    with world.db.transaction() as tx:
        tx.execute("UPDATE seasons SET state = 'REJECTED' WHERE id = %s", (season,))
    with pytest.raises(InvalidTransition):
        world.service.run_research(season, request(key="research.daily:v2"))
    # A repeated trigger of the recorded run still replays; replay never starts new work.
    replay = world.service.run_research(season, request())
    assert replay.replayed is True and replay.run_id == first.run_id


def test_query_count_is_bounded_before_any_dispatch(world: World) -> None:
    season = world.season()
    with pytest.raises(SchemaInvalid):
        world.service.run_research(season, request(queries=tuple(f"query {i}" for i in range(9))))
    assert world.sources.calls == []


def test_all_concepts_blocked_completes_without_a_proposal_and_keeps_spend(world: World) -> None:
    from research_support import COMPARATOR_SCENE

    concepts = default_concepts()
    copied = concepts[0].scope.model_copy(
        update={"premise": f"Verbatim copy. {COMPARATOR_SCENE} Nothing original here."}
    )
    copied2 = concepts[1].scope.model_copy(
        update={"premise": f"Another copy. {COMPARATOR_SCENE} Nothing original here."}
    )
    season = world.season()
    result = world.service.run_research(
        season,
        request(
            concepts=[
                concepts[0].model_copy(update={"scope": copied}),
                concepts[1].model_copy(update={"scope": copied2}),
            ]
        ),
    )
    assert result.state == "COMPLETED"
    assert result.outcome is not None
    assert result.outcome.chosen_concept_id is None
    assert result.proposal_id is None
    assert world.proposals(season) == []
    assert world.account(season)["settled_micro_usd"] == result.outcome.settled_micro_usd > 0
