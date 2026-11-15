"""T031 R5b (RR-T6): t031_timings coverage semantics (R5C-12).

``full_job_ms`` stays UNKNOWN through SUBMITTED and intermediate polls
(submission acknowledgement is not duration), is written at the FIRST terminal
observation with verified durable output, and survives replay. ``sampler_ms``
is null when the transport's history carries no sampler timestamps, and is
carried through when it does. Per-acquisition ``cold_start_ms``/``provision_ms``
land on the acquisition-keyed record (RR-T5's writer, asserted here for the
export surface).
"""

from __future__ import annotations

import pytest
from rendering_support import RenderWorld
from test_benchmark_experiments import _composed_world
from test_t031_h2b_p1_modes import (
    _authorization_pair,
    _drive_resume,
    _execute_service,
    _PatchedPolicy,
)
from test_t031_r5b_boot import _drive_boot, _screen_quote

from microdrama.persistence import Database
from microdrama.pipeline.benchmark_service import BenchmarkService

pytestmark = pytest.mark.db


def _sample_coverage(db: Database, experiment_id, sample_id) -> dict:
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT coverage FROM benchmark_samples WHERE experiment_id=%s AND sample_id=%s",
            (experiment_id, sample_id),
        )
    return (row["coverage"] or {}).get("t031_timings") or {}


def _first_submitted_state(db, tmp_path):
    world = RenderWorld(db)
    ep, plan, service, budget, comfy, adapter = _composed_world(world, tmp_path)
    from test_t031_r5b_boot import BootReadyClient

    import microdrama.pipeline.experimental_world as world_module

    comfy.service._client = BootReadyClient(comfy.server)
    adapter._boot_sleep = lambda seconds: comfy.clock.advance(seconds)
    original_validate = world_module.ExperimentalPresetPolicy.validate
    world_module.ExperimentalPresetPolicy.validate = lambda *a, **k: None
    try:
        seal, authorization, digest, raw = _authorization_pair(world, plan, tmp_path)
        BenchmarkService(db, world.settings, clock=comfy.clock).seal(plan.experiment_id, seal)
        return world, comfy, adapter, plan, authorization, digest, raw, seal
    finally:
        world_module.ExperimentalPresetPolicy.validate = original_validate


def test_rr_t6_full_job_ms_unknown_through_submission_written_at_completion(db: Database, tmp_path):
    world, comfy, adapter, plan, authorization, digest, raw, seal = _first_submitted_state(
        db, tmp_path
    )
    with _PatchedPolicy():
        service = _execute_service(db, comfy, world.ids, adapter)
        first = service.execute(
            plan.experiment_id,
            phase="screen",
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            source_bytes=raw,
        )
    # execute returns at the first observation (normally SUBMITTED): that is
    # NOT phase completion and NOT a duration measurement.
    assert first["execution_state"] == "SCREEN_RUNNING", first["execution_state"]
    assert _sample_coverage(db, plan.experiment_id, "S01-R1") == {}, "no timing yet"

    last = _drive_resume(
        db, world, comfy, adapter, plan, authorization, digest, raw, phase="screen", limit=8
    )
    assert last["execution_state"] == "SCREEN_REVIEW", last["execution_state"]
    timings = _sample_coverage(db, plan.experiment_id, "S01-R1")
    assert timings.get("full_job_ms") is not None
    assert timings["full_job_ms"] >= 0
    # The transport's history carries no sampler timestamps: UNKNOWN, never 0.
    assert timings.get("sampler_ms") is None

    # Replay (resume over completed work) preserves the recorded duration.
    measured = timings["full_job_ms"]
    comfy.clock.advance(seconds=90)
    resumed = _drive_resume(
        db, world, comfy, adapter, plan, authorization, digest, raw, phase="screen", limit=3
    )
    assert resumed["execution_state"] == "SCREEN_REVIEW"
    assert _sample_coverage(db, plan.experiment_id, "S01-R1")["full_job_ms"] == measured


def test_rr_t6_sampler_ms_carried_when_history_has_timestamps(db: Database, tmp_path):
    from test_t031_r5b_boot import BootReadyClient

    world = RenderWorld(db)
    ep, plan, service, budget, comfy, adapter = _composed_world(world, tmp_path)
    client = BootReadyClient(comfy.server)
    original_history = client.history

    def history_with_sampler(prompt_id):
        entry = original_history(prompt_id)
        if entry is not None and entry.completed:
            entry = entry.model_copy(update={"sampler_ms": 4321})
        return entry

    client.history = history_with_sampler
    comfy.service._client = client
    import microdrama.pipeline.experimental_world as world_module

    original_validate = world_module.ExperimentalPresetPolicy.validate
    world_module.ExperimentalPresetPolicy.validate = lambda *a, **k: None
    try:
        seal, authorization, digest, raw = _authorization_pair(world, plan, tmp_path)
        BenchmarkService(db, world.settings, clock=comfy.clock).seal(plan.experiment_id, seal)
        last = _drive_boot(
            db, world, comfy, adapter, plan, authorization, digest, raw, phase="screen", limit=8
        )
        assert last["execution_state"] == "SCREEN_REVIEW", last["execution_state"]
        timings = _sample_coverage(db, plan.experiment_id, "S01-R1")
        assert timings.get("sampler_ms") == 4321
        assert timings.get("full_job_ms") is not None
    finally:
        world_module.ExperimentalPresetPolicy.validate = original_validate


def test_r5v8_recovery_uses_the_result_operation_for_timings(db: Database, tmp_path):
    """R5V-8: a submit whose projection never committed (the worker died
    before ``_observe``) leaves the sample's operation link NULL; recovery
    discovers the successful operation and must time the sample from the
    RESULT's verified operation id - the stale NULL lookup loses the timing
    forever."""
    world, comfy, adapter, plan, authorization, digest, raw, seal = _first_submitted_state(
        db, tmp_path
    )
    # The crash-before-projection durable state, produced NATURALLY: the
    # submit happens (job, reservation, slot and the in-flight operation all
    # live) but the projection never commits - the worker died between the
    # submit and _observe, so the sample row still carries no operation link.
    original_observe = BenchmarkService._observe
    BenchmarkService._observe = lambda self, experiment_id, sample, result, **kwargs: None
    try:
        with _PatchedPolicy():
            service = _execute_service(db, comfy, world.ids, adapter)
            service.execute(
                plan.experiment_id,
                phase="screen",
                authorization=authorization,
                quote=_screen_quote(world),
                expected_sha256=digest,
                source_bytes=raw,
            )
    finally:
        BenchmarkService._observe = original_observe
    with db.transaction(readonly=True) as tx:
        probe = tx.fetchone(
            "SELECT state, operation_id, job_id, reservation_id FROM benchmark_samples "
            "WHERE experiment_id=%s AND sample_id='S01-R1'",
            (plan.experiment_id,),
        )
    assert probe["state"] == "CLAIMED" and probe["operation_id"] is None, dict(probe)
    comfy.clock.advance(seconds=30)  # the fake pod finishes the prompt
    last = _drive_resume(
        db, world, comfy, adapter, plan, authorization, digest, raw, phase="screen", limit=8
    )
    assert last["execution_state"] == "SCREEN_REVIEW", last["execution_state"]
    timings = _sample_coverage(db, plan.experiment_id, "S01-R1")
    assert timings.get("full_job_ms") is not None, "the recovered timing was lost"
    with db.transaction(readonly=True) as tx:
        linked = tx.fetchval(
            "SELECT operation_id FROM benchmark_samples WHERE experiment_id=%s "
            "AND sample_id='S01-R1'",
            (plan.experiment_id,),
        )
    assert linked is not None


def test_r5v8_sampler_evidence_survives_interruption_before_projection(db: Database, tmp_path):
    """R5V-8: sampler timing is persisted with the terminal completion (the
    operation's durable result), so the delayed replay that projects the
    sample (``finalize_terminal``) still writes it - the transient completion
    return alone loses it."""
    from test_t031_r5b_boot import BootReadyClient

    world = RenderWorld(db)
    ep, plan, service, budget, comfy, adapter = _composed_world(world, tmp_path)
    client = BootReadyClient(comfy.server)
    original_history = client.history

    def history_with_sampler(prompt_id):
        entry = original_history(prompt_id)
        if entry is not None and entry.completed:
            entry = entry.model_copy(update={"sampler_ms": 4321})
        return entry

    client.history = history_with_sampler
    comfy.service._client = client
    import microdrama.pipeline.experimental_world as world_module

    original_validate = world_module.ExperimentalPresetPolicy.validate
    world_module.ExperimentalPresetPolicy.validate = lambda *a, **k: None
    try:
        seal, authorization, digest, raw = _authorization_pair(world, plan, tmp_path)
        BenchmarkService(db, world.settings, clock=comfy.clock).seal(plan.experiment_id, seal)
        with _PatchedPolicy():
            boot_service = _execute_service(db, comfy, world.ids, adapter)
            first = boot_service.execute(
                plan.experiment_id,
                phase="screen",
                authorization=authorization,
                quote=_screen_quote(world),
                expected_sha256=digest,
                source_bytes=raw,
            )
        assert first["execution_state"] == "SCREEN_RUNNING", first["execution_state"]

        # The interruption: the terminal observation commits on the operation
        # row, but the sample projection never runs.
        comfy.clock.advance(seconds=30)
        original_observe = BenchmarkService._observe

        def skipping_observe(self, experiment_id, sample, result, **kwargs):
            return None

        BenchmarkService._observe = skipping_observe
        try:
            with _PatchedPolicy():
                poll_service = _execute_service(db, comfy, world.ids, adapter)
                poll_service.resume(
                    plan.experiment_id,
                    authorization=authorization,
                    quote=_screen_quote(world),
                    expected_sha256=digest,
                    phase="screen",
                    source_bytes=raw,
                )
        finally:
            BenchmarkService._observe = original_observe
        with db.transaction(readonly=True) as tx:
            operation_state = tx.fetchval(
                "SELECT o.state FROM provider_operations o JOIN benchmark_samples s "
                "ON s.reservation_id=o.reservation_id "
                "WHERE s.experiment_id=%s AND s.sample_id='S01-R1'",
                (plan.experiment_id,),
            )
        assert operation_state == "SUCCEEDED", operation_state

        # The delayed replay (reconcile's finalize_terminal) projects the
        # sample and must recover BOTH timings from durable state.
        last = _drive_resume(
            db, world, comfy, adapter, plan, authorization, digest, raw, phase="screen", limit=8
        )
        assert last["execution_state"] == "SCREEN_REVIEW", last["execution_state"]
        timings = _sample_coverage(db, plan.experiment_id, "S01-R1")
        assert timings.get("full_job_ms") is not None, "the replay lost full_job_ms"
        assert timings.get("sampler_ms") == 4321, "the replay lost the sampler evidence"
    finally:
        world_module.ExperimentalPresetPolicy.validate = original_validate


def test_rr_t6_export_carries_timings_and_acquisition_records(db: Database, tmp_path):
    from test_t031_r5b_boot import _acquisition_records

    world, comfy, adapter, plan, authorization, digest, raw, seal = _first_submitted_state(
        db, tmp_path
    )
    service = BenchmarkService(db, world.settings, clock=comfy.clock)
    last = _drive_boot(
        db, world, comfy, adapter, plan, authorization, digest, raw, phase="screen", limit=8
    )
    assert last["execution_state"] == "SCREEN_REVIEW"
    exported = service.export(plan.experiment_id)
    by_id = {sample["sample_id"]: sample for sample in exported["samples"]}
    assert by_id["S01-R1"]["timings"]["full_job_ms"] is not None
    assert by_id["S01-R1"]["timings"]["sampler_ms"] is None
    records = _acquisition_records(db, plan.experiment_id)
    exported_records = {entry["acquisition_id"]: entry for entry in exported["acquisitions"]}
    assert set(exported_records) == set(records), "export carries every acquisition record"
    first_record = next(iter(exported_records.values()))
    assert first_record["cold_start_ms"] is not None
