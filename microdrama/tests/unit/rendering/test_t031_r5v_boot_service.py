"""T031 R5 fix round 1 (Codex review R5V-1/2/3/5): boot-window durability.

R5V-1 - resume of a genuinely existing, already-booted acquisition past the
initial boot deadline is recovery, never ``BOOT_TIMEOUT`` (R5C-9).
R5V-2 - the complete initial acquisition path is bounded by the boot request
deadline, the deadline is rechecked between requests, and budget exhaustion
mid-boot classifies as typed ``BOOT_TIMEOUT`` - never the generic terminal
FAILED handler (R5C-2/8).
R5V-3 - a persisted typed boot failure atomically carries its cleanup
obligation; ``unresolved_items``/``_needs_finalization`` recognize
``PROVISION_FAILED``/``BOOT_TIMEOUT`` as cleanup owed until verified.
R5V-5 - readiness retries only the tolerated gateway failures; permanent HTTP
failures (401/403) classify immediately through typed pre-sample cleanup.
"""

from __future__ import annotations

import pytest
import test_t031_h2b_p1_modes as h2b_modes  # noqa: E402  (patch target)
import test_t031_r5b_boot as r5b_boot  # noqa: E402  (patch target)
from rendering_support import RenderWorld
from test_benchmark_experiments import _composed_world
from test_t031_h2b_p1_modes import (
    _authorization_pair,
    _drive_resume,
    _execute_service,
    _PatchedPolicy,
    _screen_quote,
)
from test_t031_r5b_boot import (
    BootReadyClient,
    _acquisition_records,
    _create_posts,
    _drive_boot,
)

from microdrama.contracts.errors import EffectDenied, ProviderError
from microdrama.persistence import Database
from microdrama.pipeline.benchmark_service import BenchmarkService
from microdrama.rendering.benchmark_experiments import unresolved_items
from microdrama.rendering.diagnostics import _REQUEST_DEADLINE

pytestmark = pytest.mark.db


# ---------------------------------------------------------------------------
# R5V-1 - the existing full-phase acquisition at minute 40
# ---------------------------------------------------------------------------


def test_r5v1_existing_acquisition_past_boot_deadline_resumes_without_reclassification(
    db: Database, tmp_path, monkeypatch
):
    """A full-phase acquisition that booted 40 minutes ago (durable
    ``cold_start_ms``), interrupted mid-run, is resumed on the SAME pod - the
    initial boot deadline never reclassifies it as ``BOOT_TIMEOUT``."""
    harness = r5b_boot._boot_harness(db, tmp_path, monkeypatch, ready_sequence=["NO_PROVISIONING"])
    world, comfy, adapter, plan = harness.world, harness.comfy, harness.adapter, harness.plan
    seal, authorization, digest, raw = _authorization_pair(world, plan, tmp_path)
    BenchmarkService(db, world.settings, clock=comfy.clock).seal(plan.experiment_id, seal)

    # Screen to completion + a durable PASS (the public path).
    state = _drive_boot(
        db, world, comfy, adapter, plan, authorization, digest, raw, phase="screen", limit=8
    )
    assert state["execution_state"] == "SCREEN_REVIEW", state
    screen_hashes = {
        s["sample_id"]: (s["output"] or {}).get("sha256")
        for s in state["samples"]
        if s["sample_id"] in ("S01-R1", "S03-R1", "S07-R1")
    }
    harness.service.record_screening(
        plan.experiment_id,
        {
            "sealed_sha256": seal.sealed_sha256,
            "actor_ref": "offline-test-human",
            "output_hashes": screen_hashes,
            "decision": "PASS",
            "coverage": {"fixture": "PASS"},
            "rubric_version": "offline-fixture",
        },
    )
    creates_after_screen = _create_posts(world)

    # The full acquisition is created, boots and submits; execute returns at
    # the first observation. A LONG runtime window keeps the lease alive past
    # minute 40 so the boot budget - not the lease - is the deadline in play.
    long_quote = dict(_screen_quote(world), maximum_runtime_ms=7_200_000)
    monkeypatch.setattr(h2b_modes, "_screen_quote", lambda w: dict(long_quote))
    monkeypatch.setattr(r5b_boot, "_screen_quote", lambda w: dict(long_quote))
    with _PatchedPolicy():
        service = _execute_service(db, comfy, world.ids, adapter)
        first = service.execute(
            plan.experiment_id,
            phase="full",
            authorization=authorization,
            quote=dict(long_quote),
            expected_sha256=digest,
            source_bytes=raw,
        )
    assert first["execution_state"] == "FULL_RUNNING", first["execution_state"]
    records = _acquisition_records(db, plan.experiment_id)
    assert len(records) == 2, "the full acquisition exists beside the screen's"
    assert all(record.get("cold_start_ms") is not None for record in records.values())

    # Minute 40: far past the initial boot budget, work still in flight, and
    # the interruption means the rest arrives through resume/reconcile.
    comfy.clock.advance(seconds=40 * 60)
    state = _drive_resume(
        db, world, comfy, adapter, plan, authorization, digest, raw, phase="full", limit=30
    )
    assert state["execution_state"] == "COMPUTE_COMPLETE", state
    # R5V-1: no boot-timeout incident on ANY acquisition - the healthy pod was
    # recovered, never reclassified and never torn down for a second create.
    records = _acquisition_records(db, plan.experiment_id)
    for record in records.values():
        assert (record.get("incident") or {}).get("reason") != "BOOT_TIMEOUT", record
    assert _create_posts(world) == creates_after_screen + 1


# ---------------------------------------------------------------------------
# R5V-2 - deadline exhaustion mid-boot is typed, and the whole path is bounded
# ---------------------------------------------------------------------------


class DeadlineBurningClient(BootReadyClient):
    """A client whose boot ``/object_info`` read outlives the remaining budget
    (exactly what the real transport's ``bound_request_timeout`` refuses)."""

    def __init__(self, state, clock, **kwargs):
        super().__init__(state, **kwargs)
        self._clock = clock

    def boot_object_info(self):
        if self.object_info_reads == 0:
            self.object_info_reads += 1
            # The gateway is PROVISIONED; the first /object_info consumes the
            # remainder of the boot budget (the clock crosses the deadline
            # mid-request) and the transport refuses to start it.
            self._clock.advance(seconds=120)
            raise EffectDenied(
                "the request deadline has passed; refusing to start another provider request"
            )
        return super().boot_object_info()


def test_r5v2_budget_exhausted_inside_the_ready_read_is_typed_boot_timeout(
    db: Database, tmp_path, monkeypatch
):
    harness = r5b_boot._boot_harness(db, tmp_path, monkeypatch, ready_sequence=["NO_PROVISIONING"])
    harness.comfy.service._client = DeadlineBurningClient(
        harness.comfy.server, clock=harness.comfy.clock
    )
    harness.adapter._boot_budget_ms = 60_000
    seal, authorization, digest, raw = _authorization_pair(harness.world, harness.plan, tmp_path)
    BenchmarkService(db, harness.world.settings, clock=harness.comfy.clock).seal(
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
    # The typed classification: never the generic terminal failure handler.
    assert state["execution_outcome"] is None, state
    with db.transaction(readonly=True) as tx:
        outcome = tx.fetchval(
            "SELECT execution_outcome FROM benchmark_experiments WHERE experiment_id=%s",
            (harness.plan.experiment_id,),
        )
    assert outcome is None, "boot-budget exhaustion must not fail the experiment"
    records = _acquisition_records(db, harness.plan.experiment_id)
    assert next(iter(records.values()))["incident"]["reason"] == "BOOT_TIMEOUT"


def test_r5v2_post_ensure_provider_get_stays_inside_the_boot_request_bound(
    db: Database, tmp_path, monkeypatch
):
    """The provider GET after warmup (endpoint binding) is part of the initial
    acquisition path, so it runs under the boot request deadline (CN-6): no
    provider request outlives the authorized wall limit."""
    from microdrama.contracts.errors import TransientProviderError

    world = RenderWorld(db)
    ep, plan, service, budget, comfy, adapter = _composed_world(world, tmp_path)
    comfy.service._client = BootReadyClient(comfy.server)
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
        if warmup_reads["count"] <= 1:
            raise TransientProviderError("pod is not running yet (warmup incomplete)")
        return real_ensure(lease_id)

    world.leases.ensure_pod = warming_ensure

    # Only provider GETs made INSIDE the world's acquire() are boot-window
    # requests; later GETs (the sweep's cleanup) legitimately reset the bound.
    boot_window = {"active": False, "tag": "?"}
    real_acquire = adapter.acquire

    def tracking_acquire(acquisition):
        boot_window["active"] = True
        try:
            return real_acquire(acquisition)
        finally:
            boot_window["active"] = False

    adapter.acquire = tracking_acquire

    get_bounds: list[object] = []
    real_get_pod = world.provider.get_pod

    def recording_get_pod(pod_id):
        if boot_window["active"]:
            get_bounds.append((boot_window["tag"], _REQUEST_DEADLINE.get() is not None))
        return real_get_pod(pod_id)

    world.provider.get_pod = recording_get_pod

    # Tag each acquire pass: the FIRST one is the initial boot window; every
    # later one adopts an already-ready pod (R5V-1: no boot timing applies).
    acquire_pass = {"n": 0}
    tracked_acquire = adapter.acquire

    def counting_acquire(acquisition):
        acquire_pass["n"] += 1
        boot_window["tag"] = f"acquire#{acquire_pass['n']}"
        return tracked_acquire(acquisition)

    adapter.acquire = counting_acquire

    seal, authorization, digest, raw = _authorization_pair(world, plan, tmp_path)
    BenchmarkService(db, world.settings, clock=comfy.clock).seal(plan.experiment_id, seal)
    state = _drive_boot(
        db, world, comfy, adapter, plan, authorization, digest, raw, phase="screen", limit=6
    )
    assert state["execution_state"] not in ("FAILED", "NEEDS_RECONCILIATION"), state
    # The INITIAL boot-window acquire (#1) is deadline-bounded on every
    # provider GET it makes - including the post-ensure endpoint-bind GET.
    initial = [bound for tag, bound in get_bounds if tag == "acquire#1"]
    assert initial, "the boot-window provider GETs ran"
    assert all(initial), "every initial-boot provider GET must run inside the boot request bound"


# ---------------------------------------------------------------------------
# R5V-3 - the durable cleanup obligation of a typed boot failure
# ---------------------------------------------------------------------------


def _boot_failure_with_failing_cleanup(db, tmp_path, monkeypatch, *, reason_sequence):
    """Drive one typed boot failure whose cleanup cannot complete (the sweep
    raises): the interruption-before-sweep / failed-shutdown durable state."""
    harness = r5b_boot._boot_harness(db, tmp_path, monkeypatch, ready_sequence=reason_sequence)
    harness.adapter._boot_budget_ms = 30_000
    seal, authorization, digest, raw = _authorization_pair(harness.world, harness.plan, tmp_path)
    BenchmarkService(db, harness.world.settings, clock=harness.comfy.clock).seal(
        harness.plan.experiment_id, seal
    )
    real_sweep = BenchmarkService.sweep

    def failing_sweep(self, experiment_id, **kwargs):
        raise RuntimeError("simulated cleanup interruption")

    monkeypatch.setattr(BenchmarkService, "sweep", failing_sweep)
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
        limit=2,
    )
    monkeypatch.setattr(BenchmarkService, "sweep", real_sweep)
    return harness, state, authorization, digest, raw


def test_r5v3_persisted_boot_failure_owes_cleanup_until_verified(
    db: Database, tmp_path, monkeypatch
):
    """With the sweep failing (interruption/failed shutdown), the persisted
    boot failure is a durable cleanup obligation: ``unresolved_items`` carries
    a U2 blocker and ``_needs_finalization`` routes through cleanup - and a
    later public resume drives the cleanup and unblocks admission."""
    harness, state, authorization, digest, raw = _boot_failure_with_failing_cleanup(
        db, tmp_path, monkeypatch, reason_sequence=["PROVISION_FAILED"]
    )
    assert state.get("boot_failure", {}).get("reason") == "PROVISION_FAILED"
    experiment_id = harness.plan.experiment_id
    with db.transaction(readonly=True) as tx:
        acquisition = tx.fetchone(
            "SELECT * FROM benchmark_acquisitions WHERE experiment_id=%s", (experiment_id,)
        )
        items = unresolved_items(tx, experiment_id, now=harness.comfy.clock.now())
    # R5V-3: cleanup is owed - recognized, not silent.
    assert acquisition["state"] == "PROVISION_FAILED"
    owed = [item for item in items if item.kind == "U2"]
    assert owed, f"the persisted boot failure must owe cleanup: {items}"

    service = _execute_service(db, harness.comfy, harness.world.ids, harness.adapter)
    with _PatchedPolicy():
        assert service._needs_finalization(experiment_id, dict(acquisition)) is True

        # The gateway recovers: a later public resume drives the owed cleanup
        # to verified first, then the fresh attempt (fresh quote window)
        # proceeds on a new acquisition.
        harness.client._ready = ["NO_PROVISIONING"]
        recovered = _drive_resume(
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
    assert recovered["execution_state"] == "SCREEN_REVIEW", recovered
    with db.transaction(readonly=True) as tx:
        states = [
            row["state"]
            for row in tx.fetchall(
                "SELECT state FROM benchmark_acquisitions WHERE experiment_id=%s "
                "ORDER BY generation",
                (experiment_id,),
            )
        ]
    assert states[0] in ("CLOSED", "CLEANUP_PENDING"), states


def test_r5v3_incident_and_cleanup_obligation_persist_atomically(
    db: Database, tmp_path, monkeypatch
):
    """The coverage incident and the acquisition's incident state commit in ONE
    transaction: a failure between the two writes can never leave the incident
    recorded without its cleanup obligation (or vice versa)."""
    harness, first, _authorization, _digest, _raw = _boot_failure_with_failing_cleanup(
        db, tmp_path, monkeypatch, reason_sequence=["PROVISION_FAILED"]
    )
    assert first.get("boot_failure", {}).get("reason") == "PROVISION_FAILED"
    with db.transaction(readonly=True) as tx:
        acquisition = dict(
            tx.fetchone(
                "SELECT * FROM benchmark_acquisitions WHERE experiment_id=%s",
                (harness.plan.experiment_id,),
            )
        )
    assert acquisition["state"] == "PROVISION_FAILED"

    # A crash BETWEEN the two persistence writes must leave NO trace of the
    # new classification: the incident coverage and the incident state commit
    # atomically, so the second transaction (the state write, call #2 after
    # the coverage merge's #1) failing leaves the committed PROVISION_FAILED
    # incident unchanged.
    service = _execute_service(db, harness.comfy, harness.world.ids, harness.adapter)
    real_transaction = service.db.transaction
    calls = {"n": 0}

    def crashing_second_transaction(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated crash between the incident and state writes")
        return real_transaction(*args, **kwargs)

    monkeypatch.setattr(service.db, "transaction", crashing_second_transaction)

    class Failure:  # the typed failure being persisted
        reason = "BOOT_TIMEOUT"

    try:
        service._record_boot_failure(
            harness.plan.experiment_id,
            dict(acquisition),
            harness.adapter,
            Failure(),
            phase="screen",
        )
    except RuntimeError:
        # The injected crash landed before the persistence completed.
        pass
    monkeypatch.setattr(service.db, "transaction", real_transaction)
    with db.transaction(readonly=True) as tx:
        states = [
            row["state"]
            for row in tx.fetchall(
                "SELECT state FROM benchmark_acquisitions WHERE experiment_id=%s "
                "ORDER BY generation",
                (harness.plan.experiment_id,),
            )
        ]
    records = _acquisition_records(db, harness.plan.experiment_id)
    # ATOMIC: the persisted incident and the acquisition's incident state can
    # never disagree - the crash between two separate writes used to split
    # them (the incident overwritten while the state never moved).
    incident = next(iter(records.values()))["incident"]
    assert incident["reason"] == states[0], (incident, states)


# ---------------------------------------------------------------------------
# R5V-5 - permanent gateway failures do not get retried as paid waits
# ---------------------------------------------------------------------------


class PermanentGatewayClient(BootReadyClient):
    """The gateway answers the ready poll with a permanent HTTP 401."""

    def ready_state(self):
        self.ready_reads += 1
        raise ProviderError("ComfyUI returned an HTTP error: 401", status=401)


class BriefOutageClient(BootReadyClient):
    """Two tolerated 502s, then the gateway serves PROVISIONED."""

    def __init__(self, state):
        super().__init__(state)
        self._served = 0

    def ready_state(self):
        self.ready_reads += 1
        self._served += 1
        if self._served <= 2:
            raise ProviderError("ComfyUI returned an HTTP error: 502 bad gateway", status=502)
        return super().ready_state()


def test_r5v5_permanent_http_failure_classifies_immediately_not_as_paid_wait(
    db: Database, tmp_path, monkeypatch
):
    harness = r5b_boot._boot_harness(db, tmp_path, monkeypatch)
    client = PermanentGatewayClient(harness.comfy.server)
    harness.comfy.service._client = client
    harness.adapter._boot_budget_ms = 25 * 60 * 1000  # the full paid window
    seal, authorization, digest, raw = _authorization_pair(harness.world, harness.plan, tmp_path)
    BenchmarkService(db, harness.world.settings, clock=harness.comfy.clock).seal(
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
        limit=3,
    )
    # A 401 is classified through typed pre-sample cleanup IMMEDIATELY - one
    # read, not a 25-minute paid wait ending in BOOT_TIMEOUT.
    assert client.ready_reads <= 2, client.ready_reads
    assert state.get("boot_failure", {}).get("reason") not in (None, "BOOT_TIMEOUT"), state
    assert state["execution_outcome"] is None, state


def test_r5v5_tolerated_gateway_statuses_keep_waiting(db: Database, tmp_path, monkeypatch):
    harness = r5b_boot._boot_harness(db, tmp_path, monkeypatch)
    client = BriefOutageClient(harness.comfy.server)
    harness.comfy.service._client = client
    harness.adapter._boot_budget_ms = 120_000
    seal, authorization, digest, raw = _authorization_pair(harness.world, harness.plan, tmp_path)
    BenchmarkService(db, harness.world.settings, clock=harness.comfy.clock).seal(
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
        limit=6,
    )
    assert state["execution_state"] not in ("FAILED", "NEEDS_RECONCILIATION"), state
    assert "boot_failure" not in state, state
    assert client.ready_reads >= 3
