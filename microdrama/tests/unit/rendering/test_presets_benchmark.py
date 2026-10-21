"""The offline preset benchmark tool: cold/warm timings, receipts, paid samples."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from test_routing_support import (
    T0,
    ColdPenaltyComfyClient,
    RoutingWorld,
    preset_record,
    shot,
)

from microdrama.config import Settings
from microdrama.contracts.enums import (
    ControlKind,
    ExecutionMode,
    Provenance,
    RenderTier,
    ShotPattern,
)
from microdrama.contracts.errors import EffectDenied, NotFound, SchemaInvalid
from microdrama.persistence import Database
from microdrama.rendering.presets_benchmark import (
    BENCHMARK_RECEIPT_EVENT,
    default_benchmark_matrix,
)
from microdrama.testing.fakes import FakeClock, FakeComfyServerState
from microdrama.testing.fakes.comfy import ComfyScenario

pytestmark = [pytest.mark.db, pytest.mark.ffmpeg]


def _stub_preset():
    """A disabled, unmeasured stub record the benchmark adds measurements to."""
    return preset_record(
        preset_id="fake-quality-8step",
        tier=RenderTier.QUALITY_EIGHT_STEP,
        controls=(ControlKind.TEXT_PROMPT, ControlKind.CHARACTER_REFERENCE),
        measured=None,
        enabled=False,
    )


def _matrix(world: RoutingWorld, classes: int = 2) -> list:
    references = world.seed_reference_assets(count=1)
    return default_benchmark_matrix(references)[:classes]


def test_live_mode_is_refused_typed_with_zero_provider_calls(db: Database, tmp_path: Path) -> None:
    """The tool exists offline; enabling real presets requires T031 evidence."""
    world = RoutingWorld(
        db,
        tmp_path / "store",
        settings=Settings(execution_mode=ExecutionMode.CONTROLLED_ACCOUNT_TEST),
    )
    world.seed_presets([_stub_preset()])
    episode = world.episode()
    with pytest.raises(EffectDenied, match="T031"):
        world.benchmark.run(
            "fake-quality-8step",
            episode_id=episode.episode_id,
            matrix=_matrix(world, classes=1),
            samples_per_class=1,
        )
    assert world.client.calls == []


def test_the_receipt_distinguishes_cold_start_from_warm_full_jobs(
    db: Database, tmp_path: Path
) -> None:
    """Acceptance: cold/warm/full-job timings distinguished, from separate contexts.

    The cold-penalty fake server makes the FIRST full job of the run slower (model
    load); the receipt must carry that as ``cold_start_ms`` and the later full jobs
    as ``warm_full_job_ms`` — proving the two are measured independently, not
    derived from one number.
    """
    clock = FakeClock(T0)
    server = FakeComfyServerState(clock)
    client = ColdPenaltyComfyClient(server, cold_extra_ms=4_000)
    world = RoutingWorld(db, tmp_path / "store", server=server, clock=clock, client=client)
    world.seed_presets([_stub_preset()])
    episode = world.episode()
    receipt = world.benchmark.run(
        "fake-quality-8step",
        episode_id=episode.episode_id,
        matrix=_matrix(world, classes=2),
        samples_per_class=2,
    )
    cold = [s for s in receipt.samples if s.cold]
    warm = [s for s in receipt.samples if not s.cold and s.accepted]
    assert len(cold) == 1
    assert len(warm) == 3
    assert receipt.cold_start_ms == cold[0].full_job_ms
    assert receipt.warm_full_job_ms == max(s.full_job_ms for s in warm)
    assert receipt.cold_start_ms > receipt.warm_full_job_ms  # the penalty is real
    assert all(s.full_job_ms >= 1 for s in receipt.samples)


def test_every_sample_is_a_paid_full_job_with_a_durable_receipt(
    db: Database, tmp_path: Path
) -> None:
    world = RoutingWorld(db, tmp_path / "store")
    world.seed_presets([_stub_preset()])
    episode = world.episode()
    receipt = world.benchmark.run(
        "fake-quality-8step",
        episode_id=episode.episode_id,
        matrix=_matrix(world, classes=2),
        samples_per_class=2,
    )
    # four paid samples: four provider operations, each with its own reservation
    operations = world.operation_rows()
    assert len(operations) == 4
    assert all(op["reservation_id"] is not None for op in operations)
    assert all(op["external_id"] in world.server.submissions for op in operations)
    # the receipt is durable twice over: preset_registry version + domain event
    rows = world.preset_rows("fake-quality-8step")
    assert len(rows) == 2  # the stub, then the measured version
    measured_row = rows[-1]
    assert measured_row["current"] is True
    assert measured_row["enabled"] is False
    record = measured_row["record"]
    assert record["measured"]["sample_count"] == 4
    assert record["measured"]["measured_with_references"] is True
    events = world.events_of_type(BENCHMARK_RECEIPT_EVENT)
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["preset_id"] == "fake-quality-8step"
    assert payload["enabled"] is False
    assert payload["provenance"] == Provenance.FAKE_SYNTHETIC.value
    assert len(payload["samples"]) == 4
    assert receipt.event_id == events[0]["event_id"]
    # costs come from actually settled charges, not a price guess
    assert receipt.cost_per_accepted_shot_micro_usd > 0
    total = sum(s.settled_micro_usd for s in receipt.samples)
    assert total == payload["total_settled_micro_usd"]
    assert receipt.cost_per_retained_second_micro_usd > 0


def test_a_failed_sample_keeps_its_charge_and_lowers_class_acceptance(
    db: Database, tmp_path: Path
) -> None:
    """A sampler that 'executes' without saved output is a failed paid attempt."""
    world = RoutingWorld(db, tmp_path / "store", scenarios=(ComfyScenario.EXECUTED_WITHOUT_OUTPUT,))
    world.seed_presets([_stub_preset()])
    episode = world.episode()
    matrix = _matrix(world, classes=1)
    receipt = world.benchmark.run(
        "fake-quality-8step",
        episode_id=episode.episode_id,
        matrix=matrix,
        samples_per_class=2,
    )
    failed = [s for s in receipt.samples if not s.accepted]
    assert failed and failed[0].error_code == "NO_COMPLETE_OUTPUT"
    assert failed[0].settled_micro_usd > 0  # the charge is kept
    shot_class = matrix[0].shot.shot_pattern_id.value
    assert receipt.acceptance_bp_by_shot_class[shot_class] == 5_000  # 1 of 2 accepted


def test_a_benchmarked_preset_stays_disabled_until_t031_enables_it(
    db: Database, tmp_path: Path
) -> None:
    world = RoutingWorld(db, tmp_path / "store")
    world.seed_presets([_stub_preset()])
    episode = world.episode()
    receipt = world.benchmark.run(
        "fake-quality-8step",
        episode_id=episode.episode_id,
        matrix=_matrix(world, classes=1),
        samples_per_class=1,
    )
    assert receipt.enabled is False
    assert "T031" in receipt.notes[0]
    # routing still refuses the measured-but-disabled preset (T031 owns enabling)
    from microdrama.rendering.routing import NoCompatiblePreset

    reference_shot = shot(controls=(ControlKind.TEXT_PROMPT, ControlKind.CHARACTER_REFERENCE))
    with pytest.raises(NoCompatiblePreset) as excinfo:
        world.router.route_shot(reference_shot, episode_id=episode.episode_id, manifest_version=1)
    reasons = {r["reason"] for r in excinfo.value.details["rejections"]}
    assert "DISABLED" in reasons


def test_the_default_matrix_covers_all_six_patterns_with_references() -> None:
    references = [uuid.uuid4()]
    matrix = default_benchmark_matrix(references)
    assert [b.shot.shot_pattern_id for b in matrix] == list(ShotPattern)
    assert all(ControlKind.CHARACTER_REFERENCE in b.shot.required_identity_controls for b in matrix)
    assert all(b.reference_asset_ids == references for b in matrix)
    with pytest.raises(SchemaInvalid):
        default_benchmark_matrix([])


def test_samples_per_class_is_bounded_by_the_ordinary_attempt_cap(
    db: Database, tmp_path: Path
) -> None:
    world = RoutingWorld(db, tmp_path / "store")
    world.seed_presets([_stub_preset()])
    episode = world.episode()
    with pytest.raises(SchemaInvalid, match="attempt cap"):
        world.benchmark.run(
            "fake-quality-8step",
            episode_id=episode.episode_id,
            matrix=_matrix(world, classes=1),
            samples_per_class=4,
        )


def test_unmapped_and_unrecorded_presets_are_typed_not_found(db: Database, tmp_path: Path) -> None:
    world = RoutingWorld(db, tmp_path / "store")
    episode = world.episode()
    # unmapped id: the template check fires first (T013-owned mapping)
    with pytest.raises(NotFound, match="PRESET_TEMPLATES"):
        world.benchmark.run(
            "fake-control-baseline",
            episode_id=episode.episode_id,
            matrix=_matrix(world, classes=1),
        )
    # mapped id without a registry record: the caller must record a stub first
    with pytest.raises(NotFound, match="stub"):
        world.benchmark.run(
            "fake-quality-8step",
            episode_id=episode.episode_id,
            matrix=_matrix(world, classes=1),
        )
