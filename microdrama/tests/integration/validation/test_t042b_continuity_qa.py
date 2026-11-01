"""T042b integration: the actual-media continuity lane against isolated PostgreSQL.

Everything runs through the real composed persistence: seeded episodes, real
media assets, the real BudgetService and the real service with the offline
fixture continuity observer and a stub typed-expectations seam. The suite
proves the durable behavior the spec demands — seeded defects fail at the QA
stage and block the release view, replays never duplicate findings or spend,
a restart (a second database connection, as a fresh process would open) reads
the same evidence back, and changed source media invalidates a cached run.
Fixture labels are OFFLINE_FIXTURE_ONLY: they verify software behavior, never
a real-model quality claim.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from validation_qa_support import (
    register_media_asset,
    seed_episode_with_script,
    seed_season_with_gate1,
)

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode, QAOutcome
from microdrama.contracts.errors import EffectDenied, ProviderError
from microdrama.persistence import Database, FilesystemObjectStore
from microdrama.qa.audio import OfflineMediaObserver
from microdrama.qa.config import CRITICAL_CHECK_IDS
from microdrama.qa.continuity import (
    CHECK_SPECS,
    CONTINUITY_CHECK_IDS,
    ContinuityDimension,
    ContinuityEvaluator,
    ContinuityObservation,
    EpisodeContinuityExpectations,
    FixtureContinuityObserver,
    observation_from_truth,
)
from microdrama.qa.report import build_report_view, load_run_check_coverage
from microdrama.qa.service import TechnicalQAService
from microdrama.testing.fakes import FakeClock, SequentialIds
from microdrama.testing.media import (
    FixtureTruthRegistry,
    clean_continuity_expectations,
    continuity_defect_suite,
)

ALL_DIMENSIONS = {dimension: 9_000 for dimension in ContinuityDimension}
IDENTITY_CHECK = CHECK_SPECS[ContinuityDimension.IDENTITY].check_id
SUBTITLE_CHECK = CHECK_SPECS[ContinuityDimension.SUBTITLE_SAFE_AREA].check_id
#: Defects whose continuity mismatch is CRITICAL and must block the release view.
CRITICAL_DEFECTS = (
    "identity_defect",
    "outfit_defect",
    "prop_holder_defect",
    "location_defect",
    "eyeline_defect",
    "proof_text_defect",
    "thai_voice_defect",
)


class StubExpectations:
    def __init__(self, expectations: EpisodeContinuityExpectations | None) -> None:
        self._expectations = expectations

    def continuity_expectations(self, episode_id: uuid.UUID) -> EpisodeContinuityExpectations:
        return self._expectations


class _Fakes:
    """What validation_qa_support.register_media_asset reads off a world."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock


@pytest.fixture(scope="module")
def continuity_suite(tmp_path_factory, fixture_truth: FixtureTruthRegistry):
    return continuity_defect_suite(tmp_path_factory.mktemp("t042b-suite"), fixture_truth)


class ValidationContinuityWorld:
    """Composed QA stack for the validation lane, continuity wired in."""

    def __init__(
        self, db: Database, settings: Settings, registry: FixtureTruthRegistry, suite, tmp_path
    ) -> None:
        self.db = db
        self.settings = settings
        self.registry = registry
        self.suite = suite
        self.clock = FakeClock(datetime(2026, 10, 31, tzinfo=UTC))
        self.ids = SequentialIds("t042b")
        self.budget = BudgetService(db, self.clock, SequentialIds("t042b-budget"), settings)
        # bound to the most recently seeded episode (the seam contract validates
        # episode binding and window bounds against the media under review)
        self.expectations: EpisodeContinuityExpectations | None = None
        self.store = FilesystemObjectStore(tmp_path / "t042b-objects")
        self.fakes = _Fakes(self.clock)
        self._season: uuid.UUID | None = None

    def media_observer(self) -> OfflineMediaObserver:
        """The speech/identity observer over the same session truth registry."""
        return OfflineMediaObserver(self.registry, self.settings)

    def continuity_observer(self) -> FixtureContinuityObserver:
        return FixtureContinuityObserver(
            self.registry,
            self.settings,
            ContinuityEvaluator("fixture-continuity", "1", "fixture-truth", dict(ALL_DIMENSIONS)),
        )

    def service(self, *, with_lane: bool = True) -> TechnicalQAService:
        return TechnicalQAService(
            self.db,
            self.clock,
            self.ids,
            self.settings,
            budget=self.budget,
            store=self.store,
            observer=self.media_observer(),
            continuity_observer=self.continuity_observer() if with_lane else None,
            continuity_expectations=(StubExpectations(self.expectations) if with_lane else None),
        )

    def season(self) -> uuid.UUID:
        if self._season is None:
            self._season = seed_season_with_gate1(self.db)
        return self._season

    def seeded_episode(self, kind: str) -> tuple[uuid.UUID, uuid.UUID]:
        episode_id = seed_episode_with_script(self.db, self.season())
        asset_id = register_media_asset(self, episode_id, self.suite[kind].path)
        self.expectations = clean_continuity_expectations(episode_id)
        return episode_id, asset_id


@pytest.fixture
def world(db, offline_settings, continuity_suite, fixture_truth, tmp_path):
    w = ValidationContinuityWorld(db, offline_settings, fixture_truth, continuity_suite, tmp_path)
    w.season()  # gate-1 season exists before any QA run
    return w


def db_rows(db: Database, sql: str, params: tuple):
    with db.transaction(readonly=True) as tx:
        return tx.fetchall(sql, params)


@pytest.mark.parametrize("kind", sorted(CRITICAL_DEFECTS))
def test_seeded_critical_defect_blocks_the_release_view(world, db, kind) -> None:
    episode_id, asset_id = world.seeded_episode(kind)
    run = world.service().run_episode_qa(episode_id, asset_id=asset_id)
    assert run.status.value == "COMPLETED"
    assert not run.all_checks_green, f"{kind} must break the green summary"
    expected_check = world.suite[kind].defect_check_ids[0]
    assert expected_check in run.blocking_check_ids
    assert expected_check not in CRITICAL_CHECK_IDS  # blocking via severity, not config
    view = build_report_view(db, episode_id, critical_check_ids=CRITICAL_CHECK_IDS)
    assert not view.all_checks_green
    assert expected_check in view.blocking_check_ids
    # the finding is persisted as a CRITICAL repairable defect in its window
    rows = db_rows(
        db,
        "SELECT check_id, outcome, severity FROM qa_findings WHERE episode_id = %s "
        "AND check_id = %s",
        (episode_id, expected_check),
    )
    assert rows
    assert any(row["outcome"] == "REPAIRABLE" and row["severity"] == "CRITICAL" for row in rows)


def test_subtitle_safe_area_is_repairable_and_routed_to_caption_or_edit(world) -> None:
    episode_id, asset_id = world.seeded_episode("subtitle_safe_area_defect")
    run = world.service().run_episode_qa(episode_id, asset_id=asset_id)
    subtitle = [f for f in run.findings if f.check_id == SUBTITLE_CHECK]
    defective = [f for f in subtitle if f.outcome is QAOutcome.REPAIRABLE]
    assert defective  # the s1 window's box spills past the safe area
    for finding in defective:
        assert {t.value for t in finding.repair_targets} == {"CAPTION", "EDIT"}
    # the clean s2 window stays a PASS: only the defective window is flagged
    assert any(f.outcome is QAOutcome.PASS for f in subtitle)
    # MAJOR placement defect: repairable and surfaced, not severity-blocking
    assert SUBTITLE_CHECK not in run.blocking_check_ids


def test_clean_media_is_green_and_check_coverage_survives_restart(world, db, db_dsn) -> None:
    episode_id, asset_id = world.seeded_episode("clean")
    run = world.service().run_episode_qa(episode_id, asset_id=asset_id)
    assert run.all_checks_green, [
        (f.check_id, f.outcome.value) for f in run.findings if f.blocks_release
    ]

    # restart: a SECOND database connection (what a fresh process opens) reads
    # the same durable evidence back — findings and per-check coverage.
    restarted_db = Database(db_dsn, min_size=1, max_size=2).open()
    try:
        replayed = TechnicalQAService(
            restarted_db,
            world.clock,
            SequentialIds("t042b-restarted"),
            world.settings,
            budget=BudgetService(
                restarted_db, world.clock, SequentialIds("t042b-budget-2"), world.settings
            ),
            store=world.store,
            observer=world.media_observer(),
            continuity_observer=world.continuity_observer(),
            continuity_expectations=StubExpectations(world.expectations),
        ).run_episode_qa(episode_id, asset_id=asset_id)
    finally:
        restarted_db.close()
    assert replayed.status.value == "REPLAYED"
    assert replayed.run_key == run.run_key
    assert sorted(f.finding_id for f in replayed.findings) == sorted(
        f.finding_id for f in run.findings
    )
    assert {w.check_id for w in replayed.per_check_coverage} == set(CONTINUITY_CHECK_IDS)
    assert all(w.status.value == "CHECKED" for w in replayed.per_check_coverage)
    # one run event, one cycle: the restart duplicated nothing
    events = db_rows(
        db,
        "SELECT payload FROM domain_events WHERE aggregate_id = %s AND event_type = %s",
        (episode_id, "qa.technical.completed"),
    )
    assert len(events) == 1
    # and the per-check coverage record reads back from the persisted payload
    direct = load_run_check_coverage(db, episode_id, run.run_key)
    assert {w.check_id for w in direct} == set(CONTINUITY_CHECK_IDS)


def test_replay_charges_nothing_and_reruns_nothing(world, db) -> None:
    episode_id, asset_id = world.seeded_episode("identity_defect")
    service = world.service()
    first = service.run_episode_qa(episode_id, asset_id=asset_id)
    charges_before = db_rows(db, "SELECT * FROM charges WHERE episode_id = %s", (episode_id,))
    second = service.run_episode_qa(episode_id, asset_id=asset_id)
    assert second.status.value == "REPLAYED"
    assert second.qa_cycle == first.qa_cycle
    assert second.settled_micro_usd == 0
    assert (
        db_rows(db, "SELECT * FROM charges WHERE episode_id = %s", (episode_id,)) == charges_before
    )


def test_changed_source_media_invalidates_the_cached_run(world, db) -> None:
    episode_id, asset_id = world.seeded_episode("clean")
    service = world.service()
    clean_run = service.run_episode_qa(episode_id, asset_id=asset_id)
    assert clean_run.all_checks_green

    # the exported media is replaced by a defective render: same episode, new
    # bytes/sha — a new run that must not replay the green cached result
    defect_asset = register_media_asset(world, episode_id, world.suite["identity_defect"].path)
    defect_run = service.run_episode_qa(episode_id, asset_id=defect_asset)
    assert defect_run.status.value == "COMPLETED"
    assert defect_run.run_key != clean_run.run_key
    assert defect_run.qa_cycle == clean_run.qa_cycle + 1
    assert not defect_run.all_checks_green
    assert IDENTITY_CHECK in defect_run.blocking_check_ids
    # the report view serves the LATEST cycle (the defective one)
    view = build_report_view(db, episode_id, critical_check_ids=CRITICAL_CHECK_IDS)
    assert not view.all_checks_green
    assert view.cycles == [clean_run.qa_cycle, defect_run.qa_cycle]


def test_unwired_lane_reports_typed_unknowns_not_silence(world) -> None:
    episode_id, asset_id = world.seeded_episode("clean")
    run = world.service(with_lane=False).run_episode_qa(episode_id, asset_id=asset_id)
    unknowns = {f.check_id for f in run.findings if f.check_id in CONTINUITY_CHECK_IDS}
    assert unknowns == set(CONTINUITY_CHECK_IDS)
    for finding in run.findings:
        if finding.check_id in CONTINUITY_CHECK_IDS:
            assert finding.outcome is QAOutcome.UNKNOWN
            assert finding.coverage.value == "UNAVAILABLE"
    assert run.all_checks_green  # honest unknowns never silently block


# --- scoped review fixes (31 Oct 2026): forged observations and paid-mode refusal ----------


class _ForgedContinuityObserver:
    """Returns a prebuilt observation regardless of the staged bytes."""

    def __init__(
        self, evaluator: ContinuityEvaluator, observation: ContinuityObservation | None
    ) -> None:
        self.evaluator = evaluator
        self._observation = observation
        self.calls = 0

    def observe_continuity(self, **_kwargs) -> ContinuityObservation | None:
        self.calls += 1
        return self._observation


def test_forged_continuity_observation_never_greens_or_replays(world, db) -> None:
    """A forged observer returning the clean fixture's windows for the defective
    asset's bytes settles as a failed observation and caches nothing."""
    episode_id, asset_id = world.seeded_episode("identity_defect")
    evaluator = ContinuityEvaluator(
        "fixture-continuity", "1", "fixture-truth", dict(ALL_DIMENSIONS)
    )
    clean = world.suite["clean"]
    forged = _ForgedContinuityObserver(
        evaluator, observation_from_truth(clean.truth, clean.sha256, evaluator)
    )
    with pytest.raises(ProviderError, match="charge is kept"):
        TechnicalQAService(
            world.db,
            world.clock,
            world.ids,
            world.settings,
            budget=world.budget,
            store=world.store,
            observer=world.media_observer(),
            continuity_observer=forged,
            continuity_expectations=StubExpectations(world.expectations),
        ).run_episode_qa(episode_id, asset_id=asset_id)
    assert forged.calls == 1  # dispatched, then rejected at settlement
    assert db_rows(db, "SELECT * FROM qa_findings WHERE episode_id = %s", (episode_id,)) == []
    assert (
        db_rows(
            db,
            "SELECT payload FROM domain_events WHERE aggregate_id = %s "
            "AND event_type = 'qa.technical.completed'",
            (episode_id,),
        )
        == []
    )
    # nothing replayed: the honest observer produces a fresh, blocking verdict
    honest = world.service().run_episode_qa(episode_id, asset_id=asset_id)
    assert honest.status.value == "COMPLETED"
    assert not honest.all_checks_green
    assert IDENTITY_CHECK in honest.blocking_check_ids


def test_paid_mode_refuses_a_configured_continuity_observer_with_zero_calls(world, db) -> None:
    """No continuity detector is qualified outside OFFLINE_MOCK — any configured
    observer is refused before a reservation or dispatch can happen."""
    episode_id, asset_id = world.seeded_episode("clean")
    spy = _ForgedContinuityObserver(
        ContinuityEvaluator("fixture-continuity", "1", "fixture-truth", dict(ALL_DIMENSIONS)),
        None,
    )
    paid = Settings(execution_mode=ExecutionMode.PAID_BENCHMARK)
    with pytest.raises(EffectDenied, match="OFFLINE_MOCK"):
        TechnicalQAService(
            world.db,
            world.clock,
            world.ids,
            paid,
            budget=world.budget,
            store=world.store,
            observer=world.media_observer(),
            continuity_observer=spy,
            continuity_expectations=StubExpectations(world.expectations),
        ).run_episode_qa(episode_id, asset_id=asset_id)
    assert spy.calls == 0
    assert db_rows(db, "SELECT * FROM reservations WHERE episode_id = %s", (episode_id,)) == []
    assert db_rows(db, "SELECT * FROM qa_findings WHERE episode_id = %s", (episode_id,)) == []
