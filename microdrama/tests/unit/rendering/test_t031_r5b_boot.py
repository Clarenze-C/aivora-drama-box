"""T031 R5b: ready gate, typed pre-sample boot failures, acquisition coverage.

RR-T5 (wait semantics, one create, janitor liveness, minute-40 recovery),
RR-T13 (typed boot failures before the generic terminal handler, attempt cap),
RR-T14 (acquisition-keyed coverage on the deterministic unclaimed sample row).

Built on the composed offline harness (real services + fake pod provider +
fake Comfy client whose readiness is scripted), driving PUBLIC service entry
points (execute / resume / sweep) exactly like the H-2 suites.
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
    _screen_quote,
)

from microdrama.persistence import Database
from microdrama.pipeline.benchmark_service import BenchmarkService
from microdrama.testing.fakes.comfy import FakeComfyClient


def _drive_boot(db, world, comfy, adapter, plan, authorization, digest, raw, *, phase, limit):
    """One public execute(), then public resume() steps (§4.2: a fresh process
    continues in-flight work through resume; execute would correctly refuse
    behind U3p). Stops on a typed boot failure or a terminal state."""
    with _PatchedPolicy():
        service = _execute_service(db, comfy, world.ids, adapter)
        last = service.execute(
            plan.experiment_id,
            phase=phase,
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            source_bytes=raw,
        )
        comfy.clock.advance(seconds=1)
        for _ in range(limit):
            if last.get("boot_failure") or last["execution_state"] in (
                "SCREEN_REVIEW",
                "COMPUTE_COMPLETE",
                "FAILED",
                "NEEDS_RECONCILIATION",
            ):
                return last
            service = _execute_service(db, comfy, world.ids, adapter)
            last = service.resume(
                plan.experiment_id,
                authorization=authorization,
                quote=_screen_quote(world),
                expected_sha256=digest,
                phase=phase,
                source_bytes=raw,
            )
            comfy.clock.advance(seconds=1)
    return last


pytestmark = pytest.mark.db


class BootReadyClient(FakeComfyClient):
    """A fake pod client whose gateway serves a scripted ready sequence."""

    def __init__(self, state, ready_sequence=(), *, fail_object_info=0):
        super().__init__(state)
        self.ready_reads = 0
        self.object_info_reads = 0
        # Each entry: a state string served by GET /__drama/ready. The final
        # entry repeats forever.
        self._ready = list(ready_sequence) or ["NO_PROVISIONING"]
        self._fail_object_info = fail_object_info
        self.scopes: list[dict] = []

    def ready_state(self):
        self.ready_reads += 1
        index = min(self.ready_reads - 1, len(self._ready) - 1)
        state = self._ready[index]
        provision = None
        if state == "PROVISIONED":
            provision = {
                "state": "PROVISIONED",
                "started_at": "2026-11-14T01:00:00Z",
                "ended_at": "2026-11-14T01:05:00Z",
                "exit_code": 0,
            }
        return {"state": state, "provision": provision}

    def boot_object_info(self):
        self.object_info_reads += 1
        if self.object_info_reads <= self._fail_object_info:
            # The real client's boot_object_info answers None for tolerated
            # boot-window failures (a gateway 502 while ComfyUI starts).
            return None
        return {"UNETLoader": {}}

    def acquisition_read_scope(self, **kwargs):
        from contextlib import nullcontext

        self.scopes.append(kwargs)
        return nullcontext()


def _boot_harness(db: Database, tmp_path, monkeypatch, *, ready_sequence=(), fail_object_info=0):
    """The composed world with a scripted gateway readiness client."""
    world = RenderWorld(db)
    ep, plan, service, budget, comfy, adapter = _composed_world(world, tmp_path)
    client = BootReadyClient(
        comfy.server, ready_sequence=ready_sequence, fail_object_info=fail_object_info
    )
    comfy.service._client = client
    monkeypatch.setattr(
        "microdrama.pipeline.experimental_world.ExperimentalPresetPolicy.validate",
        lambda *a, **k: None,
    )
    # Boot sleeps advance the fixture clock instead of real time.
    adapter._boot_sleep = lambda seconds: comfy.clock.advance(seconds=int(seconds))
    harness = type(
        "BootHarness",
        (),
        {
            "db": db,
            "ep": ep,
            "plan": plan,
            "service": service,
            "budget": budget,
            "comfy": comfy,
            "world": world,
            "adapter": adapter,
            "client": client,
            "quote": _screen_quote(world),
        },
    )()
    return harness


def _create_posts(world) -> int:
    return len([call for call in world.provider.calls if call.method == "create_pod"])


def _acquisition_records(db: Database, experiment_id) -> dict:
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT coverage FROM benchmark_samples WHERE experiment_id=%s "
            "ORDER BY sample_id LIMIT 1",
            (experiment_id,),
        )
    return (row["coverage"] or {}).get("t031_acquisitions") or {}


def _carrier_row(db: Database, experiment_id) -> dict:
    with db.transaction(readonly=True) as tx:
        return dict(
            tx.fetchone(
                "SELECT * FROM benchmark_samples WHERE experiment_id=%s ORDER BY sample_id LIMIT 1",
                (experiment_id,),
            )
        )


# ---------------------------------------------------------------------------
# RR-T5 — wait semantics
# ---------------------------------------------------------------------------


def test_rr_t5_boot_window_waits_through_provisioning_then_proceeds(
    db: Database, tmp_path, monkeypatch
):
    """BOOTING -> PROVISIONING -> PROVISIONED keep waiting (no provider
    operation, no ambiguity); readiness completes; staging proceeds."""
    harness = _boot_harness(
        db,
        tmp_path,
        monkeypatch,
        ready_sequence=["BOOTING", "PROVISIONING", "PROVISIONED"],
        fail_object_info=1,
    )
    seal, authorization, digest, raw = _authorization_pair(harness.world, harness.plan, tmp_path)
    BenchmarkService(harness.db, harness.world.settings, clock=harness.comfy.clock).seal(
        harness.plan.experiment_id, seal
    )
    state = _drive_boot(
        db,
        harness.world,
        harness.comfy,
        harness.adapter,
        harness.plan,
        authorization,
        digest,
        raw,
        phase="screen",
        limit=8,
    )
    assert state["execution_state"] not in ("FAILED", "NEEDS_RECONCILIATION"), state
    # The boot window was observed end to end: every ready state was consumed
    # before the first upload/prompt could happen, with no extra create.
    assert harness.client.ready_reads >= 4  # BOOTING, PROVISIONING, PROVISIONED(+repeats)
    assert harness.client.object_info_reads >= 2  # one tolerated 502, then success
    # Exactly one create POST for the whole boot (retries are owned reads).
    assert _create_posts(harness.world) == 1
    # Readiness persisted: cold_start_ms recorded on the acquisition record.
    records = _acquisition_records(db, harness.plan.experiment_id)
    assert len(records) == 1
    record = next(iter(records.values()))
    assert record["cold_start_ms"] >= 0
    assert record["provision_ms"] == 300_000  # 01:00 -> 01:05 state-file window


def test_rr_t5_provision_failure_refuses_with_typed_boot_failure(
    db: Database, tmp_path, monkeypatch
):
    harness = _boot_harness(
        db, tmp_path, monkeypatch, ready_sequence=["BOOTING", "PROVISION_FAILED"]
    )
    seal, authorization, digest, raw = _authorization_pair(harness.world, harness.plan, tmp_path)
    BenchmarkService(harness.db, harness.world.settings, clock=harness.comfy.clock).seal(
        harness.plan.experiment_id, seal
    )
    state = _drive_boot(
        db,
        harness.world,
        harness.comfy,
        harness.adapter,
        harness.plan,
        authorization,
        digest,
        raw,
        phase="screen",
        limit=4,
    )
    # Typed boot failure: NOT a terminal experiment failure.
    assert state["execution_outcome"] is None, state
    with db.transaction(readonly=True) as tx:
        outcome = tx.fetchval(
            "SELECT execution_outcome FROM benchmark_experiments WHERE experiment_id=%s",
            (harness.plan.experiment_id,),
        )
        assert outcome is None  # R5C-2: no sample/model failure outcome
        states = tx.fetchall(
            "SELECT state FROM benchmark_samples WHERE experiment_id=%s",
            (harness.plan.experiment_id,),
        )
        assert {s["state"] for s in states} == {"PLANNED"}  # nothing claimed
    records = _acquisition_records(db, harness.plan.experiment_id)
    assert len(records) == 1
    incident = next(iter(records.values()))["incident"]
    assert incident["reason"] == "PROVISION_FAILED"
    assert incident["phase"] == "screen"
    assert incident["attempt"] == 1


def test_rr_t5_boot_deadline_is_boot_timeout_not_experiment_failure(
    db: Database, tmp_path, monkeypatch
):
    """A gateway stuck at BOOTING past the boot budget: BOOT_TIMEOUT + cleanup,
    execution_outcome stays NULL."""
    harness = _boot_harness(db, tmp_path, monkeypatch, ready_sequence=["BOOTING"])
    adapter = harness.adapter
    adapter._boot_budget_ms = 60_000  # one minute, so the test budget is small
    seal, authorization, digest, raw = _authorization_pair(harness.world, harness.plan, tmp_path)
    BenchmarkService(harness.db, harness.world.settings, clock=harness.comfy.clock).seal(
        harness.plan.experiment_id, seal
    )
    state = _drive_boot(
        db,
        harness.world,
        harness.comfy,
        adapter,
        harness.plan,
        authorization,
        digest,
        raw,
        phase="screen",
        limit=4,
    )
    assert state["execution_outcome"] is None
    records = _acquisition_records(db, harness.plan.experiment_id)
    incident = next(iter(records.values()))["incident"]
    assert incident["reason"] == "BOOT_TIMEOUT"


def test_rr_t5_pending_pod_and_missing_endpoint_wait_with_exactly_one_create(
    db: Database, tmp_path, monkeypatch
):
    """R5C-1: pending hardware and a missing endpoint BEFORE acquire()
    completes are waited on inside the boot window - retries are owned reads
    against the same durable lease/pod, never a second create."""
    from microdrama.contracts.errors import TransientProviderError

    world = RenderWorld(db)
    ep, plan, service, budget, comfy, adapter = _composed_world(world, tmp_path)
    monkeypatch.setattr(
        "microdrama.pipeline.experimental_world.ExperimentalPresetPolicy.validate",
        lambda *a, **k: None,
    )
    adapter._boot_budget_ms = 120_000
    adapter._boot_sleep = lambda seconds: comfy.clock.advance(seconds=int(seconds))

    real_ensure = world.leases.ensure_pod
    warmup_reads = {"count": 0}

    def warming_ensure(lease_id):
        warmup_reads["count"] += 1
        if warmup_reads["count"] <= 3:
            # Pending hardware (2 passes), then endpoint-not-exposed (1 pass):
            # exactly the verify transients pods.py raises while warming.
            raise TransientProviderError("pod is not running yet (warmup incomplete)")
        return real_ensure(lease_id)

    world.leases.ensure_pod = warming_ensure
    seal, authorization, digest, raw = _authorization_pair(world, plan, tmp_path)
    BenchmarkService(db, world.settings, clock=comfy.clock).seal(plan.experiment_id, seal)
    state = _drive_boot(
        db, world, comfy, adapter, plan, authorization, digest, raw, phase="screen", limit=6
    )
    assert state["execution_state"] not in ("FAILED", "NEEDS_RECONCILIATION"), state
    assert warmup_reads["count"] >= 4  # the transients were retried, not fatal
    assert _create_posts(world) == 1


def test_rr_t5_twenty_five_minute_boot_survives_concurrent_janitor_sweeps(
    db: Database, tmp_path, monkeypatch
):
    """R5C-8: a 25-minute provisioning boot with the janitor sweeping on every
    poll tick keeps its lease alive (heartbeat maintained, deadline checked
    before every request and after every sleep) and leaves no expired hold."""
    harness = _boot_harness(
        db,
        tmp_path,
        monkeypatch,
        # ~20 minutes of BOOTING (120 ten-second polls) before PROVISIONED -
        # far past the 5-minute heartbeat timeout the janitor enforces.
        ready_sequence=["BOOTING"] * 120 + ["PROVISIONING", "PROVISIONED"],
    )
    adapter = harness.adapter
    adapter._boot_budget_ms = 25 * 60 * 1000
    janitor = harness.world.janitor()
    janitor_actions: list[str] = []
    boot_sleeps: list[float] = []

    def janitor_sweep_sleep(seconds: float):
        boot_sleeps.append(seconds)
        harness.comfy.clock.advance(seconds=int(seconds))
        report = janitor.sweep()
        janitor_actions.extend(
            f"{action.action}:{action.outcome}" for action in report.lease_outcomes
        )
        return None

    adapter._boot_sleep = janitor_sweep_sleep
    seal, authorization, digest, raw = _authorization_pair(harness.world, harness.plan, tmp_path)
    BenchmarkService(harness.db, harness.world.settings, clock=harness.comfy.clock).seal(
        harness.plan.experiment_id, seal
    )
    state = _drive_boot(
        db,
        harness.world,
        harness.comfy,
        adapter,
        harness.plan,
        authorization,
        digest,
        raw,
        phase="screen",
        limit=6,
    )
    assert state["execution_state"] not in ("FAILED", "NEEDS_RECONCILIATION"), state
    # The boot genuinely spanned a ~20-minute window under sweeps...
    total = sum(boot_sleeps)
    assert total >= 20 * 60, total  # (the sequence finishes ~20 min in)
    # ...and the janitor never took the healthy provisioning lease: not one
    # lease action fired across all ~120 sweeps, yet the heartbeat timeout
    # is 5 minutes - liveness was maintained throughout, and no hold was
    # expired out from under the boot (the run completed on the same lease).
    assert not any("lease" in action for action in janitor_actions), janitor_actions
    with db.transaction(readonly=True) as tx:
        orphans = tx.fetchall("SELECT id FROM pod_leases WHERE lease_state='ORPHANED'")
        assert not orphans, "the janitor orphaned the boot lease"
        lease = tx.fetchone(
            "SELECT lease_state, pod_id FROM pod_leases ORDER BY created_at DESC LIMIT 1"
        )
    assert lease["pod_id"] is not None, "the booted pod stayed bound to its lease"


def test_rr_t5_minute_40_recovery_is_not_boot_timeout(db: Database, tmp_path, monkeypatch):
    """R5C-9: an already-booted, admitted full-phase pod at minute 40 with a
    newly submitted prompt is recovered by resume - the initial boot deadline
    never reclassifies admitted work."""
    harness = _boot_harness(db, tmp_path, monkeypatch, ready_sequence=["NO_PROVISIONING"])
    seal, authorization, digest, raw = _authorization_pair(harness.world, harness.plan, tmp_path)
    BenchmarkService(harness.db, harness.world.settings, clock=harness.comfy.clock).seal(
        harness.plan.experiment_id, seal
    )
    # Screen to completion + a durable PASS.
    state = _drive_boot(
        db,
        harness.world,
        harness.comfy,
        harness.adapter,
        harness.plan,
        authorization,
        digest,
        raw,
        phase="screen",
        limit=8,
    )
    assert state["execution_state"] == "SCREEN_REVIEW", state
    screen_hashes = {
        s["sample_id"]: (s["output"] or {}).get("sha256")
        for s in state["samples"]
        if s["sample_id"] in ("S01-R1", "S03-R1", "S07-R1")
    }
    harness.service.record_screening(
        harness.plan.experiment_id,
        {
            "sealed_sha256": seal.sealed_sha256,
            "actor_ref": "offline-test-human",
            "output_hashes": screen_hashes,
            "decision": "PASS",
            "coverage": {"fixture": "PASS"},
            "rubric_version": "offline-fixture",
        },
    )
    # The full-phase pod is now at minute 40 - far past the initial boot
    # budget - with work still flowing.
    harness.comfy.clock.advance(seconds=40 * 60)
    state = _drive_resume(
        db,
        harness.world,
        harness.comfy,
        harness.adapter,
        harness.plan,
        authorization,
        digest,
        raw,
        phase="full",
        limit=30,
    )
    assert state["execution_state"] == "COMPUTE_COMPLETE", state
    records = _acquisition_records(db, harness.plan.experiment_id)
    for record in records.values():
        assert record.get("incident", {}).get("reason") != "BOOT_TIMEOUT"


# ---------------------------------------------------------------------------
# RR-T13 / RR-T14 — attempt cap and the durable carrier
# ---------------------------------------------------------------------------


def test_rr_t13_fourth_boot_attempt_refused_and_retries_leave_outcome_null(
    db: Database, tmp_path, monkeypatch
):
    """Typed boot failures are retryable with a fresh quote (outcome stays
    NULL) up to three attempts per phase; the FOURTH is refused under the
    admission locks."""
    harness = _boot_harness(db, tmp_path, monkeypatch, ready_sequence=["PROVISION_FAILED"])
    seal, authorization, digest, raw = _authorization_pair(harness.world, harness.plan, tmp_path)
    BenchmarkService(harness.db, harness.world.settings, clock=harness.comfy.clock).seal(
        harness.plan.experiment_id, seal
    )
    from microdrama.contracts.errors import Conflict

    for attempt in (1, 2, 3):
        state = _drive_boot(
            db,
            harness.world,
            harness.comfy,
            harness.adapter,
            harness.plan,
            authorization,
            digest,
            raw,
            phase="screen",
            limit=1,
        )
        assert state["execution_outcome"] is None, (attempt, state)
        records = _acquisition_records(db, harness.plan.experiment_id)
        assert len(records) == attempt
        # jsonb key order is server-normalized: index by the durable attempt
        # identity, not by dict position.
        by_attempt = {record["incident"]["attempt"]: record for record in records.values()}
        assert set(by_attempt) == set(range(1, attempt + 1))
        harness.comfy.clock.advance(seconds=1)
    # A fourth boot attempt is refused under the admission locks.
    service = _execute_service(db, harness.comfy, harness.world.ids, harness.adapter)
    with _PatchedPolicy():
        with pytest.raises(Conflict, match="boot attempt"):
            service.execute(
                harness.plan.experiment_id,
                phase="screen",
                authorization=authorization,
                quote=_screen_quote(harness.world),
                expected_sha256=digest,
                source_bytes=raw,
            )


def test_rr_t14_two_boot_attempts_survive_cleanup_transitions_on_one_carrier(
    db: Database, tmp_path, monkeypatch
):
    """Both attempts' incident records are present on the SAME deterministic
    prepared-but-unclaimed sample row after the sweep transitions the
    acquisitions through CLEANUP_PENDING/CLOSED; refusal evidence precedes
    cleanup; existing coverage keys are never replaced."""
    harness = _boot_harness(db, tmp_path, monkeypatch, ready_sequence=["BOOTING"])
    harness.adapter._boot_budget_ms = 30_000
    seal, authorization, digest, raw = _authorization_pair(harness.world, harness.plan, tmp_path)
    BenchmarkService(harness.db, harness.world.settings, clock=harness.comfy.clock).seal(
        harness.plan.experiment_id, seal
    )
    for _ in (1, 2):
        _drive_boot(
            db,
            harness.world,
            harness.comfy,
            harness.adapter,
            harness.plan,
            authorization,
            digest,
            raw,
            phase="screen",
            limit=3,
        )
        harness.comfy.clock.advance(seconds=1)
    carrier = _carrier_row(db, harness.plan.experiment_id)
    # Deterministic: the first sample row by sample_id carries everything.
    assert carrier["sample_id"] == "S01-R1"
    # Unclaimed: the carrier never took a job/hold/acquisition link.
    assert carrier["job_id"] is None
    assert carrier["reservation_id"] is None
    assert carrier["acquisition_id"] is None
    records = _acquisition_records(db, harness.plan.experiment_id)
    assert len(records) == 2  # BOTH attempts preserved, keyed by acquisition id
    with db.transaction(readonly=True) as tx:
        states = [
            row["state"]
            for row in tx.fetchall(
                "SELECT state FROM benchmark_acquisitions WHERE experiment_id=%s "
                "ORDER BY generation",
                (harness.plan.experiment_id,),
            )
        ]
    assert all(state in ("CLOSED", "CLEANUP_PENDING", "UNKNOWN") for state in states), states
    # The earlier attempt's evidence was not replaced by the later attempt.
    for record in records.values():
        assert record["incident"]["reason"] == "BOOT_TIMEOUT"
