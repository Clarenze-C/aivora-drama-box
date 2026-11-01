"""T042b service tests: the continuity lane inside ``run_episode_qa``.

Real PostgreSQL/store/budget and the real composed service, with the offline
fixture continuity observer and a stub typed-expectations seam. Replay and
restart behavior run against the persisted rows, not in-memory state; the
cross-instance restart readback and the blocking propagation also run in the
integration lane (tests/integration/validation/test_t042b_continuity_qa.py).
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from microdrama.contracts.enums import QAOutcome
from microdrama.qa.continuity import (
    CHECK_SPECS,
    CONTINUITY_CHECK_IDS,
    ContinuityDimension,
    ContinuityEvaluator,
    ContinuityObservation,
    ContinuityObserver,
    EpisodeContinuityExpectations,
    FixtureContinuityObserver,
    observation_from_truth,
)
from microdrama.qa.service import TechnicalQAService
from microdrama.testing.media import (
    clean_continuity_expectations,
    continuity_defect_suite,
)

ALL_DIMENSIONS = {dimension: 9_000 for dimension in ContinuityDimension}
IDENTITY_CHECK = CHECK_SPECS[ContinuityDimension.IDENTITY].check_id
OUTFIT_CHECK = CHECK_SPECS[ContinuityDimension.OUTFIT].check_id


class StubExpectations:
    """Typed continuity expectations seam: one fixed expectations payload."""

    def __init__(self, expectations: EpisodeContinuityExpectations | None) -> None:
        self._expectations = expectations

    def continuity_expectations(
        self, episode_id: uuid.UUID
    ) -> EpisodeContinuityExpectations | None:
        return self._expectations


class CountingContinuityObserver:
    """Wraps the real fixture observer and counts dispatches (replay evidence)."""

    def __init__(self, inner: FixtureContinuityObserver) -> None:
        self._inner = inner
        self.evaluator = inner.evaluator
        self.calls = 0

    def observe_continuity(
        self,
        *,
        asset_id: uuid.UUID,
        asset_sha256: str,
        media_path,
        duration_ms: int,
    ) -> ContinuityObservation:
        self.calls += 1
        return self._inner.observe_continuity(
            asset_id=asset_id,
            asset_sha256=asset_sha256,
            media_path=media_path,
            duration_ms=duration_ms,
        )


class ForgedContinuityObserver:
    """Returns a prebuilt observation no matter what bytes are actually staged."""

    def __init__(self, evaluator: ContinuityEvaluator, observation: ContinuityObservation):
        self.evaluator = evaluator
        self._observation = observation
        self.calls = 0

    def observe_continuity(
        self,
        *,
        asset_id: uuid.UUID,
        asset_sha256: str,
        media_path,
        duration_ms: int,
    ) -> ContinuityObservation:
        self.calls += 1
        return self._observation


@pytest.fixture(scope="module")
def continuity_suite(tmp_path_factory, fixture_truth):
    """The labeled continuity fixtures, generated once, in the session registry."""
    return continuity_defect_suite(tmp_path_factory.mktemp("continuity-suite"), fixture_truth)


class ContinuityWorld:
    """A QA service factory with the continuity lane wired in.

    The typed-expectations payload is bound to the most recently seeded
    episode (the seam contract validates episode binding and window bounds,
    so the stub must return THIS episode's expectations); a changed
    expectations digest is a new run.
    """

    def __init__(self, qa_world, suite) -> None:
        self.qa_world = qa_world
        self.suite = suite
        self.expectations: EpisodeContinuityExpectations | None = None

    def observer(self, thresholds=None) -> CountingContinuityObserver:
        evaluator = ContinuityEvaluator(
            "fixture-continuity",
            "1",
            "fixture-truth",
            thresholds if thresholds is not None else dict(ALL_DIMENSIONS),
        )
        return CountingContinuityObserver(
            FixtureContinuityObserver(self.qa_world.truth, self.qa_world.settings, evaluator)
        )

    def service(
        self,
        *,
        observer: ContinuityObserver | None = None,
        expectations: EpisodeContinuityExpectations | None = None,
        with_lane: bool = True,
    ) -> TechnicalQAService:
        return TechnicalQAService(
            self.qa_world.db,
            self.qa_world.clock,
            self.qa_world.ids,
            self.qa_world.settings,
            budget=self.qa_world.budget,
            store=self.qa_world.store,
            observer=self.qa_world.observer(),
            continuity_observer=(
                (observer if observer is not None else self.observer()) if with_lane else None
            ),
            continuity_expectations=(
                StubExpectations(self.expectations if expectations is None else expectations)
                if with_lane
                else None
            ),
        )

    def seeded(self, kind: str) -> tuple[uuid.UUID, uuid.UUID]:
        episode_id, asset_id = self.qa_world.seeded_episode_with(fixture=self.suite[kind])
        # bound to this episode: the seam payload must match the episode under QA
        self.expectations = clean_continuity_expectations(episode_id)
        return episode_id, asset_id


@pytest.fixture
def continuity_world(qa_world, continuity_suite) -> ContinuityWorld:
    return ContinuityWorld(qa_world, continuity_suite)


def test_clean_media_with_continuity_is_green_and_persists_check_coverage(
    continuity_world,
) -> None:
    world = continuity_world
    episode_id, asset_id = world.seeded("clean")
    run = world.service().run_episode_qa(episode_id, asset_id=asset_id)
    assert run.all_checks_green, [
        (f.check_id, f.outcome.value) for f in run.findings if f.blocks_release
    ]
    passes = {f.check_id for f in run.findings if f.check_id in CONTINUITY_CHECK_IDS}
    assert passes == set(CONTINUITY_CHECK_IDS)
    assert all(
        f.outcome is QAOutcome.PASS for f in run.findings if f.check_id in CONTINUITY_CHECK_IDS
    )
    # per-check coverage is on the run and in the durable payload
    assert {w.check_id for w in run.per_check_coverage} == set(CONTINUITY_CHECK_IDS)
    assert all(w.status.value == "CHECKED" for w in run.per_check_coverage)
    payload = world.qa_world.run_events(episode_id)[-1]
    assert payload["continuity"]["observation_sha256"]
    assert payload["continuity"]["registered"] is True
    assert set(payload["per_check_coverage"]) == set(CONTINUITY_CHECK_IDS)
    assert payload["per_check_coverage"][IDENTITY_CHECK]["windows"] == [
        [0, 3_800, "CHECKED"],
        [3_800, 5_000, "CHECKED"],
    ]


def test_identity_defect_blocks_release_through_persisted_findings(
    continuity_world,
) -> None:
    world = continuity_world
    episode_id, asset_id = world.seeded("identity_defect")
    service = world.service()
    run = service.run_episode_qa(episode_id, asset_id=asset_id)
    assert not run.all_checks_green
    assert IDENTITY_CHECK in run.blocking_check_ids  # not in CRITICAL_CHECK_IDS
    stored = world.qa_world.findings_rows(episode_id)
    assert any(
        row["check_id"] == IDENTITY_CHECK and row["outcome"] == "REPAIRABLE" for row in stored
    )
    view = service.qa_report(episode_id)
    assert not view.all_checks_green
    assert IDENTITY_CHECK in view.blocking_check_ids


def test_replay_returns_stored_findings_without_reobservation(continuity_world) -> None:
    world = continuity_world
    episode_id, asset_id = world.seeded("clean")
    observer = world.observer()
    service = world.service(observer=observer)
    first = service.run_episode_qa(episode_id, asset_id=asset_id)
    assert first.status.value == "COMPLETED"
    calls_after_first = observer.calls
    rows_after_first = world.qa_world.findings_rows(episode_id)
    events_after_first = world.qa_world.run_events(episode_id)

    second = service.run_episode_qa(episode_id, asset_id=asset_id)
    assert second.status.value == "REPLAYED"
    assert second.qa_cycle == first.qa_cycle
    assert second.settled_micro_usd == 0
    assert sorted(f.finding_id for f in second.findings) == sorted(
        f.finding_id for f in first.findings
    )
    assert {w.check_id for w in second.per_check_coverage} == set(CONTINUITY_CHECK_IDS)
    assert observer.calls == calls_after_first  # nothing re-observed
    assert world.qa_world.findings_rows(episode_id) == rows_after_first  # no new rows
    assert world.qa_world.run_events(episode_id) == events_after_first  # no new spend


def test_restart_replays_from_persisted_state(continuity_world) -> None:
    """A brand-new service instance (fresh-process equivalent) replays."""
    world = continuity_world
    episode_id, asset_id = world.seeded("clean")
    first = world.service().run_episode_qa(episode_id, asset_id=asset_id)
    restarted = world.service()  # new object over the same db/store/registry
    replayed = restarted.run_episode_qa(episode_id, asset_id=asset_id)
    assert replayed.status.value == "REPLAYED"
    assert replayed.run_key == first.run_key
    assert sorted(f.finding_id for f in replayed.findings) == sorted(
        f.finding_id for f in first.findings
    )
    assert {w.check_id for w in replayed.per_check_coverage} == {
        w.check_id for w in first.per_check_coverage
    }
    assert all(w.status.value == "CHECKED" for w in replayed.per_check_coverage)


def test_evaluator_calibration_change_invalidates_the_cached_run(continuity_world) -> None:
    world = continuity_world
    episode_id, asset_id = world.seeded("clean")
    observer = world.observer()
    first = world.service(observer=observer).run_episode_qa(episode_id, asset_id=asset_id)
    stricter = world.observer(thresholds={**ALL_DIMENSIONS, ContinuityDimension.IDENTITY: 9_500})
    assert stricter.evaluator.capability_sha256() != observer.evaluator.capability_sha256()
    second = world.service(observer=stricter).run_episode_qa(episode_id, asset_id=asset_id)
    assert second.status.value == "COMPLETED"  # a new run, not a replay
    assert second.run_key != first.run_key
    assert second.qa_cycle == first.qa_cycle + 1


def test_changed_outfit_assignment_invalidates_and_flips_the_verdict(
    continuity_world,
) -> None:
    """A changed wardrobe assignment is a new expected side: new run, new verdict."""
    world = continuity_world
    episode_id, asset_id = world.seeded("clean")
    expectations = clean_continuity_expectations(episode_id)
    first = world.service(expectations=expectations).run_episode_qa(episode_id, asset_id=asset_id)
    assert first.all_checks_green
    # the wardrobe assignment changes after the run: lek now wears market-b
    window = expectations.windows[0]
    changed_outfits = dict(window.outfit_by_character)
    changed_outfits["lek"] = "outfit-lek-market-b"
    changed = EpisodeContinuityExpectations(
        episode_id=episode_id,
        windows=(
            dataclasses.replace(window, outfit_by_character=changed_outfits),
            *expectations.windows[1:],
        ),
    )
    assert changed.expectations_sha256() != expectations.expectations_sha256()
    second = world.service(expectations=changed).run_episode_qa(episode_id, asset_id=asset_id)
    assert second.status.value == "COMPLETED"
    assert second.run_key != first.run_key
    assert second.qa_cycle == first.qa_cycle + 1
    assert not second.all_checks_green
    assert OUTFIT_CHECK in second.blocking_check_ids


def test_media_sha_change_is_a_new_run(continuity_world) -> None:
    world = continuity_world
    clean_episode, clean_asset = world.seeded("clean")
    clean_run = world.service().run_episode_qa(clean_episode, asset_id=clean_asset)
    defect_episode, defect_asset = world.seeded("identity_defect")
    defect_run = world.service().run_episode_qa(defect_episode, asset_id=defect_asset)
    assert defect_run.run_key != clean_run.run_key
    assert not defect_run.all_checks_green
    assert IDENTITY_CHECK in defect_run.blocking_check_ids


def test_lane_unwired_stays_honest_unknown_and_v1_green(continuity_world) -> None:
    """Without a continuity observer the checks are typed UNKNOWNs, never PASS."""
    world = continuity_world
    episode_id, asset_id = world.seeded("clean")
    run = world.service(with_lane=False).run_episode_qa(episode_id, asset_id=asset_id)
    unknowns = {f.check_id: f for f in run.findings if f.check_id in CONTINUITY_CHECK_IDS}
    assert set(unknowns) == set(CONTINUITY_CHECK_IDS)
    for finding in unknowns.values():
        assert finding.outcome is QAOutcome.UNKNOWN
        assert finding.coverage.value == "UNAVAILABLE"
        assert finding.severity.value == "MAJOR"
    assert run.all_checks_green  # honest unknowns do not silently block
    assert all(check_id in run.unknown_check_ids for check_id in CONTINUITY_CHECK_IDS)
    assert {w.check_id for w in run.per_check_coverage} == set(CONTINUITY_CHECK_IDS)
    assert all(w.status.value == "UNAVAILABLE" for w in run.per_check_coverage)


def test_failed_continuity_observation_keeps_the_charge(continuity_world) -> None:
    """A continuity observer failure after dispatch settles the worst case."""
    from microdrama.contracts.enums import PriceUnit
    from microdrama.contracts.errors import ProviderError
    from microdrama.qa import QAConfig
    from microdrama.testing.fakes.common import fake_price_quote

    world = continuity_world
    episode_id, asset_id = world.seeded("clean")

    class RaisingContinuityObserver:
        def __init__(self) -> None:
            self.evaluator = world.observer().evaluator

        def observe_continuity(self, **_kwargs):
            raise RuntimeError("continuity model exploded after dispatch")

    priced = QAConfig(observer_price=fake_price_quote(PriceUnit.AUDIO_SECOND))
    with pytest.raises(ProviderError, match="charge is kept"):
        TechnicalQAService(
            world.qa_world.db,
            world.qa_world.clock,
            world.qa_world.ids,
            world.qa_world.settings,
            budget=world.qa_world.budget,
            store=world.qa_world.store,
            config=priced,
            observer=world.qa_world.observer(),
            continuity_observer=RaisingContinuityObserver(),
            continuity_expectations=StubExpectations(world.expectations),
        ).run_episode_qa(episode_id, asset_id=asset_id)
    reservations = world.qa_world.rows(
        "SELECT * FROM reservations WHERE episode_id = %s", (episode_id,)
    )
    assert reservations and reservations[0]["state"] == "SETTLED"  # kept, never released
    charges = world.qa_world.rows("SELECT * FROM charges WHERE episode_id = %s", (episode_id,))
    assert charges, "a failed observation must not be released as unbilled"
    rows = world.qa_world.findings_rows(episode_id)
    assert rows == []  # no QA claim was made


# --- scoped review fixes (31 Oct 2026): forged results and foreign inputs never green ----


def _priced_service(world: ContinuityWorld, continuity_observer, config):
    return TechnicalQAService(
        world.qa_world.db,
        world.qa_world.clock,
        world.qa_world.ids,
        world.qa_world.settings,
        budget=world.qa_world.budget,
        store=world.qa_world.store,
        config=config,
        observer=world.qa_world.observer(),
        continuity_observer=continuity_observer,
        continuity_expectations=StubExpectations(world.expectations),
    )


def test_forged_clean_windows_for_other_media_never_green(continuity_world) -> None:
    """An observer returning clean windows keyed to UNRELATED bytes settles as a
    failed observation: charge kept, no persisted claim, nothing cached."""
    from microdrama.contracts.enums import PriceUnit
    from microdrama.contracts.errors import ProviderError
    from microdrama.qa import QAConfig
    from microdrama.testing.fakes.common import fake_price_quote

    world = continuity_world
    episode_id, asset_id = world.seeded("identity_defect")
    honest = world.observer()
    # clean windows frozen against the CLEAN fixture's bytes — not the defective
    # bytes actually under review
    clean = world.suite["clean"]
    forged = ForgedContinuityObserver(
        honest.evaluator,
        observation_from_truth(clean.truth, clean.sha256, honest.evaluator),
    )
    priced = QAConfig(observer_price=fake_price_quote(PriceUnit.AUDIO_SECOND))
    with pytest.raises(ProviderError, match="charge is kept"):
        _priced_service(world, forged, priced).run_episode_qa(episode_id, asset_id=asset_id)
    assert forged.calls == 1  # dispatched, then rejected at settlement
    reservations = world.qa_world.rows(
        "SELECT * FROM reservations WHERE episode_id = %s", (episode_id,)
    )
    assert reservations and reservations[0]["state"] == "SETTLED"  # charge kept
    assert world.qa_world.rows("SELECT * FROM charges WHERE episode_id = %s", (episode_id,)), (
        "the dispatched observation must not be released as unbilled"
    )
    assert world.qa_world.findings_rows(episode_id) == []  # no QA claim was made
    assert world.qa_world.run_events(episode_id) == []
    # nothing was cached: the SAME priced configuration over the honest observer
    # is a fresh COMPLETED run with the honest (defective) verdict
    honest_run = _priced_service(world, honest, priced).run_episode_qa(
        episode_id, asset_id=asset_id
    )
    assert honest_run.status.value == "COMPLETED"
    assert not honest_run.all_checks_green
    assert IDENTITY_CHECK in honest_run.blocking_check_ids


def test_forged_observation_with_a_different_evaluator_never_green(
    continuity_world,
) -> None:
    """A returned observation stamped with ANOTHER evaluator cannot settle."""
    from microdrama.contracts.errors import ProviderError

    world = continuity_world
    episode_id, asset_id = world.seeded("identity_defect")
    honest = world.observer()
    foreign = ContinuityEvaluator(
        "fixture-continuity",
        "1",
        "fixture-truth",
        {**ALL_DIMENSIONS, ContinuityDimension.IDENTITY: 1_000},
    )
    assert foreign.capability_sha256() != honest.evaluator.capability_sha256()
    # clean windows keyed to the actual asset's sha but stamped with the foreign
    # evaluator — only the evaluator binding can catch this
    stamped = observation_from_truth(
        world.suite["clean"].truth, world.suite["identity_defect"].sha256, foreign
    )
    forged = ForgedContinuityObserver(honest.evaluator, stamped)
    with pytest.raises(ProviderError, match="charge is kept"):
        world.service(observer=forged).run_episode_qa(episode_id, asset_id=asset_id)
    assert forged.calls == 1
    assert world.qa_world.findings_rows(episode_id) == []
    assert world.qa_world.run_events(episode_id) == []
    honest_run = world.service(observer=honest).run_episode_qa(episode_id, asset_id=asset_id)
    assert honest_run.status.value == "COMPLETED"  # nothing replayed
    assert not honest_run.all_checks_green
    assert IDENTITY_CHECK in honest_run.blocking_check_ids


def test_cross_episode_expectations_are_rejected_before_any_work(continuity_world) -> None:
    """The seam returning another episode's payload is refused before dispatch."""
    from microdrama.contracts.errors import Conflict

    world = continuity_world
    episode_id, asset_id = world.seeded("clean")
    observer = world.observer()
    foreign = clean_continuity_expectations(uuid.uuid4())  # another episode
    with pytest.raises(Conflict, match="different episode"):
        world.service(observer=observer, expectations=foreign).run_episode_qa(
            episode_id, asset_id=asset_id
        )
    assert observer.calls == 0  # nothing was staged or observed
    assert world.qa_world.findings_rows(episode_id) == []
    assert world.qa_world.run_events(episode_id) == []
    bound = world.service(observer=observer).run_episode_qa(episode_id, asset_id=asset_id)
    assert bound.status.value == "COMPLETED"  # no cached wrong run
    assert bound.all_checks_green


def test_out_of_range_expectations_are_rejected_before_caching(continuity_world) -> None:
    """Expected windows beyond the measured media duration are refused."""
    from microdrama.contracts.errors import Conflict

    world = continuity_world
    episode_id, asset_id = world.seeded("clean")
    observer = world.observer()
    beyond = EpisodeContinuityExpectations(
        episode_id=episode_id,
        windows=(
            world.expectations.windows[0],
            dataclasses.replace(world.expectations.windows[1], end_ms=6_000),
        ),
    )
    with pytest.raises(Conflict, match="duration"):
        world.service(observer=observer, expectations=beyond).run_episode_qa(
            episode_id, asset_id=asset_id
        )
    assert observer.calls == 0
    assert world.qa_world.findings_rows(episode_id) == []
    assert world.qa_world.run_events(episode_id) == []
    run = world.service(observer=observer).run_episode_qa(episode_id, asset_id=asset_id)
    assert run.status.value == "COMPLETED"  # the honest payload runs fresh
    assert run.all_checks_green


def test_paid_mode_refuses_any_continuity_observer_before_provider_calls(
    continuity_world,
) -> None:
    """Outside OFFLINE_MOCK no continuity observer is qualified — not even a
    custom one; it is refused before any reservation or dispatch."""
    from microdrama.config import Settings
    from microdrama.contracts.enums import ExecutionMode
    from microdrama.contracts.errors import EffectDenied

    world = continuity_world
    episode_id, asset_id = world.seeded("clean")
    spy = ForgedContinuityObserver(world.observer().evaluator, None)
    paid = Settings(execution_mode=ExecutionMode.PAID_BENCHMARK)
    with pytest.raises(EffectDenied, match="OFFLINE_MOCK"):
        TechnicalQAService(
            world.qa_world.db,
            world.qa_world.clock,
            world.qa_world.ids,
            paid,
            budget=world.qa_world.budget,
            store=world.qa_world.store,
            observer=world.qa_world.observer(),
            continuity_observer=spy,
            continuity_expectations=StubExpectations(world.expectations),
        ).run_episode_qa(episode_id, asset_id=asset_id)
    assert spy.calls == 0  # zero dispatches, typed refusal
    assert (
        world.qa_world.rows("SELECT * FROM reservations WHERE episode_id = %s", (episode_id,)) == []
    )
    assert world.qa_world.findings_rows(episode_id) == []


def test_paid_mode_without_continuity_observer_stays_honest_unknown(
    continuity_world,
) -> None:
    """With no observer configured, a paid run may proceed honestly UNKNOWN."""
    from microdrama.config import Settings
    from microdrama.contracts.enums import ExecutionMode

    world = continuity_world
    episode_id, asset_id = world.seeded("clean")
    paid = Settings(execution_mode=ExecutionMode.PAID_BENCHMARK)
    run = TechnicalQAService(
        world.qa_world.db,
        world.qa_world.clock,
        world.qa_world.ids,
        paid,
        budget=world.qa_world.budget,
        store=world.qa_world.store,
        observer=None,
        continuity_observer=None,
        continuity_expectations=StubExpectations(world.expectations),
    ).run_episode_qa(episode_id, asset_id=asset_id)
    unknowns = {f.check_id for f in run.findings if f.check_id in CONTINUITY_CHECK_IDS}
    assert unknowns == set(CONTINUITY_CHECK_IDS)
    for finding in run.findings:
        if finding.check_id in CONTINUITY_CHECK_IDS:
            assert finding.outcome is QAOutcome.UNKNOWN
            assert finding.coverage.value == "UNAVAILABLE"
            assert finding.check_id not in run.blocking_check_ids  # never silently blocks
    # the V1 critical checks keep their own honesty: with no speech observer
    # configured either, they cannot PASS, so the run is honestly not green
    assert not run.all_checks_green
    assert all(check_id in run.unknown_check_ids for check_id in CONTINUITY_CHECK_IDS)
