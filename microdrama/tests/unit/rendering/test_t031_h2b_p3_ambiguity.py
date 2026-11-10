"""T031 H-2 build, package P3: ambiguity at run time (spec v3 §5).

AT-1, AT-15, AT-16, AT-25 and the §5.1 classification first (create vs upload
vs submit/poll ambiguity label exactly what §5.1 says); part 2 adds the
durable-grace ATs (AT-2/AT-18/AT-19), the §5.3 upload readback (AT-17) and
AT-3. Public entry points only.
"""

from __future__ import annotations

import threading
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from rendering_support import RenderWorld
from test_benchmark_experiments import _composed_world
from test_t031_h2b_p1_modes import (
    _authorization_pair,
    _execute_service,
    _PatchedPolicy,
    _screen_quote,
)

from microdrama.persistence import Database
from microdrama.testing.fakes.comfy import FakeComfyClient

pytestmark = pytest.mark.db


def _valid_fake_graph() -> dict:
    """The smallest graph the fake ComfyUI server accepts and completes."""
    return {
        "1": {
            "class_type": "FakeVideoModelSampler",
            "inputs": {"model": ["0", 0], "prompt": "offline fixture", "frames": 4},
        },
        "0": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "fixture.safetensors"},
        },
        "2": {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "images": ["1", 0],
                "frame_rate": 24,
                "filename_prefix": "bench",
                "format": "video/h264-mp4",
            },
        },
    }


RECOVERY_GRACE_MAX_S = 600  # spec §5.4 module constant


class _TimeoutOnceClient(FakeComfyClient):
    """The prompt POST times out after the server accepted it."""

    def __init__(self, state):
        super().__init__(state)
        self.timed_out = False

    def queue_prompt(self, graph, *, client_id):
        prompt_id = super().queue_prompt(graph, client_id=client_id)
        if not self.timed_out:
            self.timed_out = True
            from microdrama.contracts.errors import NeedsReconciliation

            raise NeedsReconciliation("synthetic submit timeout after acceptance")
        return prompt_id


def _base(db: Database, tmp_path: Path):
    world = RenderWorld(db)
    ep, plan, service, budget, comfy, adapter = _composed_world(world, tmp_path)
    service.seal(plan.experiment_id, _bench_seal_for(plan))
    _, authorization, digest, raw = _authorization_pair(world, plan, tmp_path)
    return world, ep, plan, service, comfy, adapter, authorization, digest, raw


def _bench_seal_for(plan):
    from test_t031_h2b_p1_modes import _bench_seal

    return _bench_seal(plan)


def _experiment_row(db, experiment_id):
    with db.transaction(readonly=True) as tx:
        return tx.fetchone(
            "SELECT * FROM benchmark_experiments WHERE experiment_id=%s", (experiment_id,)
        )


# ---------------------------------------------------------------------------
# §5.1 classification + AT-1: submit ambiguity inside the grace recovers.
# ---------------------------------------------------------------------------


def test_at01_submit_ambiguity_keeps_acquisition_active_and_recovers_in_grace(
    db: Database, tmp_path: Path
):
    world, ep, plan, service, comfy, adapter, authorization, digest, raw = _base(db, tmp_path)
    comfy.service._client = _TimeoutOnceClient(comfy.server)
    first = _execute_service(db, comfy, world.ids, adapter)
    with _PatchedPolicy():
        ambiguous = first.execute(
            plan.experiment_id,
            phase="screen",
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            source_bytes=raw,
        )
    assert ambiguous["execution_state"] == "NEEDS_RECONCILIATION"
    # §5.1: a submit ambiguity leaves the ACQUISITION ACTIVE (only a create
    # ambiguity may label it UNKNOWN) - the pod stays for the recovery grace.
    acquisition = ambiguous["acquisitions"][0]
    assert acquisition["state"] == "ACTIVE"
    # §5.4: the grace is persisted BEFORE recovery, from absolute timestamps.
    assert acquisition["recovery_started_at"] is not None
    assert acquisition["recovery_deadline"] is not None
    started = acquisition["recovery_started_at"]
    deadline = acquisition["recovery_deadline"]
    assert deadline <= started + timedelta(seconds=RECOVERY_GRACE_MAX_S)
    assert deadline >= started  # absolute timestamps, never durations

    # Recovery inside the grace: the accepted prompt is adopted by client id,
    # the output persists, the run continues, and nothing is re-submitted.
    takeover = _execute_service(db, comfy, world.ids, adapter)
    with _PatchedPolicy():
        final = takeover.resume(
            plan.experiment_id,
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            phase="screen",
            source_bytes=raw,
        )
        for _ in range(12):
            if final["execution_state"] == "SCREEN_REVIEW":
                break
            comfy.clock.advance(seconds=1)
            final = takeover.resume(
                plan.experiment_id,
                authorization=authorization,
                quote=_screen_quote(world),
                expected_sha256=digest,
                phase="screen",
                source_bytes=raw,
            )
    assert final["execution_state"] == "SCREEN_REVIEW", final["execution_state"]
    assert len(comfy.server.submissions) == 3  # one prompt per screen sample
    with db.transaction(readonly=True) as tx:
        reused = tx.fetchone(
            "SELECT recovery_started_at, recovery_deadline FROM benchmark_acquisitions "
            "WHERE acquisition_id=%s",
            (acquisition["acquisition_id"],),
        )
    assert reused["recovery_started_at"] == started  # a takeover never re-grants
    assert reused["recovery_deadline"] == deadline


# ---------------------------------------------------------------------------
# §5.2 (SC-4): PENDING_SUBMIT on takeover.
# ---------------------------------------------------------------------------


def _crash_state(db: Database, tmp_path: Path, *, operation_state: str, with_prompt: bool = False):
    """The durable state a worker death leaves between dispatch stages.

    An ACTIVE acquisition with a live pod, the first sample claimed under its
    fixed hold, the dispatch slot occupied, and a provider operation committed
    in ``operation_state`` - with the sample's own operation link never written
    and no submit result ever observed (exactly §E's crash windows).
    """
    from test_t031_h2b_p2_gate import _at14_context, _seed_sample_operation

    world, ep, plan, service, comfy, adapter, budget, acquisition = _at14_context(db, tmp_path)
    from microdrama.rendering.comfy_jobs import render_client_id

    key = f"benchmark:{plan.experiment_id}:sample:S01-R1:a1"
    client_id = render_client_id(key)
    external_id = None
    if with_prompt:
        # The worker's POST did land: the server holds the prompt under the
        # deterministic client id, and the operation recorded its id.
        external_id = FakeComfyClient(comfy.server).queue_prompt(
            _valid_fake_graph(), client_id=client_id
        )
    with db.transaction(readonly=True) as tx:
        reservation_id = tx.fetchval(
            "SELECT reservation_id FROM benchmark_samples WHERE experiment_id=%s "
            "AND sample_id='S01-R1'",
            (plan.experiment_id,),
        )
    _seed_sample_operation(
        db,
        plan,
        "S01-R1",
        operation_state,
        comfy.clock,
        comfy,
        reservation_id=reservation_id,
        external_id=external_id,
    )
    with db.transaction(readonly=True) as tx:
        slot = tx.fetchone(
            "SELECT s.sample_id, s.reservation_id, s.operation_id FROM benchmark_samples s "
            "WHERE s.experiment_id=%s AND s.sample_id='S01-R1'",
            (plan.experiment_id,),
        )
        operation = tx.fetchone(
            "SELECT id, state FROM provider_operations WHERE reservation_id=%s",
            (slot["reservation_id"],),
        )
    assert operation is not None
    _, authorization, digest, raw = _authorization_pair(world, plan, tmp_path)
    return world, ep, plan, service, comfy, adapter, slot, operation, authorization, digest, raw


def test_at15_pending_submit_takeover_moves_to_unknown_and_never_resubmits(
    db: Database, tmp_path: Path
):
    world, ep, plan, service, comfy, adapter, slot, operation, authorization, digest, raw = (
        _crash_state(db, tmp_path, operation_state="PENDING_SUBMIT")
    )

    # The coordinator is gone (its token expired with the process): a takeover
    # reconcile moves the unrefused PENDING_SUBMIT to UNKNOWN under the lock
    # (§5.2) and never POSTs it again.
    comfy.clock.advance(seconds=3601)
    takeover = _execute_service(db, comfy, world.ids, adapter)
    with _PatchedPolicy():
        takeover.reconcile(plan.experiment_id, world=adapter)
    with db.transaction(readonly=True) as tx:
        after = tx.fetchone("SELECT state FROM provider_operations WHERE id=%s", (operation["id"],))
    assert after["state"] == "UNKNOWN"  # absence of a prompt never proves "not sent"
    assert len(comfy.server.submissions) == 0  # no resubmit, no invented prompt

    # (a) stays UNKNOWN without visible evidence: only the audited operator
    # resolution closes it (§7.3 via resolve_sample is P5; here: it persists).
    resolved = takeover.resolve_sample(
        plan.experiment_id,
        sample_id=slot["sample_id"],
        actor_ref="operator-console",
        reason="queue and history show no prompt for the deterministic client id",
        evidence_sha256="a" * 64,
        world=adapter,
    )
    states = {s["sample_id"]: s["state"] for s in resolved["samples"]}
    assert states[slot["sample_id"]] == "FAILED"  # §7.4 fail-fast
    assert resolved["execution_outcome"] == "FAILED"


def test_at15b_post_accepted_before_result_commit_is_adopted_by_client_id(
    db: Database, tmp_path: Path
):
    """§5.2 (b): identical durable state, but the POST DID land - the takeover
    adopts it by deterministic client id and the run continues (I2, I6)."""
    world, ep, plan, service, comfy, adapter, slot, operation, authorization, digest, raw = (
        _crash_state(db, tmp_path, operation_state="PENDING_SUBMIT")
    )
    from microdrama.rendering.comfy_jobs import render_client_id

    key = f"benchmark:{plan.experiment_id}:sample:{slot['sample_id']}:a1"
    FakeComfyClient(comfy.server).queue_prompt(_valid_fake_graph(), client_id=render_client_id(key))
    accepted = len(comfy.server.submissions)
    assert accepted == 1

    comfy.clock.advance(seconds=3601)
    takeover = _execute_service(db, comfy, world.ids, adapter)
    with _PatchedPolicy():
        takeover.reconcile(plan.experiment_id, world=adapter)
    with db.transaction(readonly=True) as tx:
        after = tx.fetchone("SELECT state FROM provider_operations WHERE id=%s", (operation["id"],))
        sample = tx.fetchone(
            "SELECT state FROM benchmark_samples WHERE experiment_id=%s AND sample_id=%s",
            (plan.experiment_id, slot["sample_id"]),
        )
    assert after["state"] in ("SUBMITTED", "RUNNING", "SUCCEEDED")  # adopted, never re-sent
    assert sample["state"] == "SUCCEEDED"
    assert len(comfy.server.submissions) == accepted  # exactly the one accepted POST


# ---------------------------------------------------------------------------
# AT-16 — in-flight operation with the sample linkage missing (SC-3).
# ---------------------------------------------------------------------------


def test_at16_inflight_operation_found_via_reservation_linkage(db: Database, tmp_path: Path):
    world, ep, plan, service, comfy, adapter, slot, operation, authorization, digest, raw = (
        _crash_state(db, tmp_path, operation_state="SUBMITTED", with_prompt=True)
    )
    assert slot["operation_id"] is None  # the sample link never landed

    # §5.1: no ambiguity was observed - the acquisition is not labelled and a
    # fresh resume finds the work through the reservation and finalises it.
    takeover = _execute_service(db, comfy, world.ids, adapter)
    with _PatchedPolicy():
        final = takeover.resume(
            plan.experiment_id,
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            phase="screen",
            source_bytes=raw,
        )
        for _ in range(12):
            if final["execution_state"] == "SCREEN_REVIEW":
                break
            comfy.clock.advance(seconds=1)
            final = takeover.resume(
                plan.experiment_id,
                authorization=authorization,
                quote=_screen_quote(world),
                expected_sha256=digest,
                phase="screen",
                source_bytes=raw,
            )
    assert final["execution_state"] == "SCREEN_REVIEW", final["execution_state"]
    assert len(comfy.server.submissions) == 3


# ---------------------------------------------------------------------------
# AT-25 — the client-id scan returns TWO prompt ids (§5.2 rule 3).
# ---------------------------------------------------------------------------


def test_at25_two_matching_prompt_ids_stay_unknown_and_report_conflict(
    db: Database, tmp_path: Path
):
    world, ep, plan, service, comfy, adapter, slot, operation, authorization, digest, raw = (
        _crash_state(db, tmp_path, operation_state="PENDING_SUBMIT")
    )
    from microdrama.rendering.comfy_jobs import render_client_id

    key = f"benchmark:{plan.experiment_id}:sample:{slot['sample_id']}:a1"
    client_id = render_client_id(key)
    graph = _valid_fake_graph()
    FakeComfyClient(comfy.server).queue_prompt(graph, client_id=client_id)
    FakeComfyClient(comfy.server).queue_prompt(graph, client_id=client_id)  # duplicate id

    comfy.clock.advance(seconds=3601)
    takeover = _execute_service(db, comfy, world.ids, adapter)
    with _PatchedPolicy():
        takeover.reconcile(plan.experiment_id, world=adapter)
    with db.transaction(readonly=True) as tx:
        after = tx.fetchone(
            "SELECT state, external_id FROM provider_operations WHERE id=%s", (operation["id"],)
        )
    # It NEVER adopts the first match: the ambiguity stays UNKNOWN (I2).
    assert after["state"] == "UNKNOWN"
    assert after["external_id"] is None


# ---------------------------------------------------------------------------
# §5.4 helpers: clients for the grace/deadline ATs.
# ---------------------------------------------------------------------------


class _NeverAcceptedTimeoutClient(FakeComfyClient):
    """The prompt POST times out BEFORE the server ever accepts it.

    History will never show the prompt: AT-2's "times out; history never
    shows it" case."""

    def queue_prompt(self, graph, *, client_id):
        from microdrama.contracts.errors import NeedsReconciliation

        raise NeedsReconciliation("synthetic submit timeout before acceptance")


class _BoundedProbeClient(FakeComfyClient):
    """Records the §5.4 deadline bound around each nested recovery call.

    The real UrllibTransport derives its per-request timeout from
    ``bound_request_timeout`` (CN-6); the fake client has no transport, so the
    probe consults the SAME production function from the standard client
    methods the reconciler drives, proving the service set the deadline
    context around the nested recovery request."""

    def __init__(self, state):
        super().__init__(state)
        self.bounds = []

    def _bound(self):
        from microdrama.rendering.diagnostics import bound_request_timeout

        value = bound_request_timeout(30)
        self.bounds.append(value)
        return value

    def history(self, prompt_id):
        self._bound()
        return super().history(prompt_id)

    def in_queue(self, prompt_id):
        self._bound()
        return super().in_queue(prompt_id)

    def find_prompt_id_by_client(self, client_id):
        # The real client's finder issues the /queue and /history GETs
        # (comfy_transport.find_prompt_id_by_client); the fake scans memory,
        # so the probe consults the production bound at the same boundary.
        self._bound()
        return super().find_prompt_id_by_client(client_id)


def _grace_row(db: Database, acquisition_id: UUID) -> dict:
    with db.transaction(readonly=True) as tx:
        return tx.fetchone(
            "SELECT recovery_started_at, recovery_deadline FROM benchmark_acquisitions "
            "WHERE acquisition_id=%s",
            (acquisition_id,),
        )


def _acquisition_row(db: Database, experiment_id, sample_id: str = "S01-R1") -> dict:
    with db.transaction(readonly=True) as tx:
        return tx.fetchone(
            "SELECT a.* FROM benchmark_acquisitions a JOIN benchmark_samples s "
            "ON s.acquisition_id=a.acquisition_id WHERE a.experiment_id=%s "
            "AND s.sample_id=%s",
            (experiment_id, sample_id),
        )


# ---------------------------------------------------------------------------
# AT-18 — grace near the limits: earliest-of deadline, bounded nested
# requests, cleanup starting at the deadline (SC-5/R3).
# ---------------------------------------------------------------------------


def test_at18_deadline_is_earliest_limit_and_nested_requests_are_bounded(
    db: Database, tmp_path: Path
):
    from microdrama.rendering.benchmark_experiments import experiment_row, gpu_ms

    world, ep, plan, service, comfy, adapter, authorization, digest, raw = _base(db, tmp_path)
    comfy.service._client = _NeverAcceptedTimeoutClient(comfy.server)
    first = _execute_service(db, comfy, world.ids, adapter)
    with _PatchedPolicy():
        ambiguous = first.execute(
            plan.experiment_id,
            phase="screen",
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            source_bytes=raw,
        )
    assert ambiguous["execution_state"] == "NEEDS_RECONCILIATION"
    acquisition = _acquisition_row(db, plan.experiment_id)
    grace = _grace_row(db, acquisition["acquisition_id"])
    started, deadline = grace["recovery_started_at"], grace["recovery_deadline"]
    assert started is not None and deadline is not None

    # The deadline is the EARLIEST of the four absolute candidates (R3),
    # recomputed here from the durable rows the handler read.
    margin = timedelta(milliseconds=adapter.leases._config.shutdown_margin_ms)
    with db.transaction(readonly=True) as tx:
        exp = experiment_row(tx, plan.experiment_id)
        compute_expires = tx.fetchval(
            "SELECT r.expires_at FROM benchmark_reservation_links l "
            "JOIN reservations r ON r.id=l.reservation_id "
            "WHERE l.acquisition_id=%s AND l.purpose='COMPUTE'",
            (acquisition["acquisition_id"],),
        )
        remaining_gpu_ms = exp["gpu_limit_ms"] - gpu_ms(tx, plan.experiment_id, started)
    candidates = [started + timedelta(seconds=RECOVERY_GRACE_MAX_S)]
    if exp["hard_stop"] is not None:
        candidates.append(exp["hard_stop"] - margin)
    if compute_expires is not None:
        candidates.append(compute_expires - margin)
    candidates.append(started + timedelta(milliseconds=max(remaining_gpu_ms, 0)))
    assert deadline == min(candidates)

    # A slow nested recovery request near the deadline is BOUNDED by the time
    # left before recovery_deadline (the probe consults the production
    # bound_request_timeout the real transport uses).
    comfy.service._client = _BoundedProbeClient(comfy.server)
    comfy.clock.advance(seconds=(deadline - comfy.clock.now()).total_seconds() - 3)
    takeover = _execute_service(db, comfy, world.ids, adapter)
    with _PatchedPolicy():
        takeover.reconcile(plan.experiment_id, world=adapter)
    assert comfy.service._client.bounds, "reconcile made no nested recovery request"
    assert all(0 < bound <= 3.0 + 1e-6 for bound in comfy.service._client.bounds)

    # At the deadline, cleanup STARTS even though the intermediate poll never
    # resolved the ambiguity (history is empty): the janitor/sweep fences the
    # coordinator tokens and terminates the pod; the operation stays UNKNOWN
    # with its exposure retained (I4).
    comfy.clock.advance(seconds=3600)
    resumed = _execute_service(db, comfy, world.ids, adapter)
    with _PatchedPolicy():
        resumed.resume(
            plan.experiment_id,
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            phase="screen",
            source_bytes=raw,
        )
    with db.transaction(readonly=True) as tx:
        lease = tx.fetchone("SELECT * FROM pod_leases WHERE id=%s", (acquisition["lease_id"],))
        operation = tx.fetchone(
            "SELECT o.state FROM provider_operations o JOIN benchmark_samples s "
            "ON s.reservation_id=o.reservation_id WHERE s.experiment_id=%s "
            "AND s.sample_id='S01-R1'",
            (plan.experiment_id,),
        )
        slot = tx.fetchone(
            "SELECT coordinator_token FROM benchmark_dispatch_slots WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
        acq_after = tx.fetchone(
            "SELECT * FROM benchmark_acquisitions WHERE acquisition_id=%s",
            (acquisition["acquisition_id"],),
        )
    stopped = (lease["stop_verified_at"], lease["terminate_verified_at"])
    # Pod compute stopped/terminated at the deadline; the janitor separate
    # terminate-verify closes the rest (offline fixture evidence standard).
    assert any(stopped), stopped
    assert operation["state"] == "UNKNOWN"  # never resolved by absence (I2)
    assert slot["coordinator_token"] is None  # R3 fence revoked the slot token
    assert acq_after["coordinator_token"] is None  # ...and the acquisition token
    assert acq_after["recovery_deadline"] == deadline  # never re-granted nor extended


# ---------------------------------------------------------------------------
# AT-18 extension (SC2-2) — recover, run past the historical deadline, then a
# second ambiguity reuses it and cleans up immediately.
# ---------------------------------------------------------------------------


class _TimeoutOnNthClient(FakeComfyClient):
    """Times out on the 1st and 3rd prompt POST, after the server accepted."""

    def __init__(self, state, *, on={1, 3}):  # noqa: B006
        super().__init__(state)
        self.on = set(on)
        self.count = 0

    def queue_prompt(self, graph, *, client_id):
        prompt_id = super().queue_prompt(graph, client_id=client_id)
        self.count += 1
        if self.count in self.on:
            from microdrama.contracts.errors import NeedsReconciliation

            raise NeedsReconciliation("synthetic submit timeout after acceptance")
        return prompt_id


def test_at18b_second_ambiguity_reuses_elapsed_deadline_and_cleans_immediately(
    db: Database, tmp_path: Path
):
    world, ep, plan, service, comfy, adapter, authorization, digest, raw = _base(db, tmp_path)
    timed = _TimeoutOnNthClient(comfy.server)  # POSTs 1 and 3 time out
    comfy.service._client = timed
    first = _execute_service(db, comfy, world.ids, adapter)
    with _PatchedPolicy():
        ambiguous = first.execute(
            plan.experiment_id,
            phase="screen",
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            source_bytes=raw,
        )
    assert ambiguous["execution_state"] == "NEEDS_RECONCILIATION"
    acquisition = _acquisition_row(db, plan.experiment_id)
    first_deadline = _grace_row(db, acquisition["acquisition_id"])["recovery_deadline"]

    # Recovery inside the grace succeeds (the accepted prompt is adopted
    # WITHOUT a new POST) and the run continues onto sample 2 - healthy work,
    # still inside the first grace (SC2-2: the historical deadline does not
    # block it).
    takeover = _execute_service(db, comfy, world.ids, adapter)
    with _PatchedPolicy():
        status = takeover.resume(
            plan.experiment_id,
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            phase="screen",
            source_bytes=raw,
        )
    assert timed.count == 2, timed.count  # sample 2's POST, no resubmit of 1
    assert status["execution_state"] != "NEEDS_RECONCILIATION", status.get("admission")
    assert comfy.clock.now() < first_deadline  # still inside the first grace

    # Healthy work continues PAST the historical deadline (a recovered
    # episode's deadline never terminates later healthy work by itself).
    comfy.clock.advance(seconds=(first_deadline - comfy.clock.now()).total_seconds() + 60)
    with _PatchedPolicy():
        second = takeover.resume(
            plan.experiment_id,
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            phase="screen",
            source_bytes=raw,
        )

    # The SECOND ambiguity (sample 3's POST times out after acceptance) reuses
    # the persisted deadline - already elapsed - so cleanup starts
    # IMMEDIATELY: no fresh 600 s grace, no extension.
    assert timed.count == 3, timed.count
    assert second["execution_state"] == "NEEDS_RECONCILIATION"
    assert _grace_row(db, acquisition["acquisition_id"])["recovery_deadline"] == first_deadline
    with db.transaction(readonly=True) as tx:
        lease = tx.fetchone("SELECT * FROM pod_leases WHERE id=%s", (acquisition["lease_id"],))
        operation = tx.fetchone(
            "SELECT o.state FROM provider_operations o JOIN benchmark_samples s "
            "ON s.reservation_id=o.reservation_id WHERE s.experiment_id=%s "
            "AND s.sample_id='S07-R1'",
            (plan.experiment_id,),
        )
    assert (
        lease["terminate_verified_at"] is not None or lease["stop_verified_at"] is not None
    )  # immediate deadline cleanup
    assert operation["state"] == "UNKNOWN"  # exposure retained, never resubmitted


# ---------------------------------------------------------------------------
# AT-19 — process death during grace: janitor/sweep takeover reuses the
# persisted deadline and fences a STILL-VALID coordinator token (R3); the
# stale worker's control writes and dispatch both fail.
# ---------------------------------------------------------------------------


class _ParkAfterAcceptClient(FakeComfyClient):
    """Parks the worker INSIDE the submit call, after the server accepted.

    The durable state is exactly §E's accepted-but-unrecorded window: the
    prompt is on the server, the operation stays PENDING_SUBMIT, and the
    coordinator tokens persist (a returning worker still holds them)."""

    def __init__(self, state, gate: threading.Event, release: threading.Event):
        super().__init__(state)
        self.gate = gate
        self.release = release

    def queue_prompt(self, graph, *, client_id):
        prompt_id = super().queue_prompt(graph, client_id=client_id)
        self.gate.set()
        self.release.wait(timeout=30)  # the stalled coordinator
        return prompt_id


def test_at19_janitor_fences_still_valid_token_and_stale_worker_is_fenced(
    db: Database, tmp_path: Path
):
    world, ep, plan, service, comfy, adapter, authorization, digest, raw = _base(db, tmp_path)
    gate, release = threading.Event(), threading.Event()
    parked = _ParkAfterAcceptClient(comfy.server, gate, release)

    # Worker 1: the first POST times out after acceptance; the grace persists
    # and the run recovers (as AT-1) so a durable deadline exists.
    timed = _TimeoutOnNthClient(comfy.server, on={1})
    comfy.service._client = timed
    first = _execute_service(db, comfy, world.ids, adapter)
    with _PatchedPolicy():
        ambiguous = first.execute(
            plan.experiment_id,
            phase="screen",
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            source_bytes=raw,
        )
    assert ambiguous["execution_state"] == "NEEDS_RECONCILIATION"
    acquisition = _acquisition_row(db, plan.experiment_id)
    deadline = _grace_row(db, acquisition["acquisition_id"])["recovery_deadline"]

    # Worker 2 (a stale coordinator in the making) resumes: sample 2's POST is
    # accepted and the worker PARKS inside the submit call - dead to the
    # world, still holding valid coordinator tokens (no finally ran).
    comfy.service._client = parked
    stalled = _execute_service(db, comfy, world.ids, adapter)
    result: dict = {}

    def _stalled_worker():
        with _PatchedPolicy():
            result["status"] = stalled.resume(
                plan.experiment_id,
                authorization=authorization,
                quote=_screen_quote(world),
                expected_sha256=digest,
                phase="screen",
                source_bytes=raw,
            )

    worker = threading.Thread(target=_stalled_worker)
    with _PatchedPolicy():
        worker.start()
        assert gate.wait(timeout=30)
    with db.transaction(readonly=True) as tx:
        slot = tx.fetchone(
            "SELECT coordinator_token, coordinator_lease_until "
            "FROM benchmark_dispatch_slots WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
    live_token = slot["coordinator_token"]
    assert live_token is not None and slot["coordinator_lease_until"] > comfy.clock.now()

    # The deadline passes with the PENDING_SUBMIT ambiguity unresolved: the
    # independently invoked sweep (janitor) reuses the persisted deadline,
    # commits the R3 fence - revoking the STILL-VALID tokens - and finishes
    # cleanup outside the transaction.
    comfy.clock.advance(seconds=(deadline - comfy.clock.now()).total_seconds() + 1)
    janitor = _execute_service(db, comfy, world.ids, adapter)
    try:
        with _PatchedPolicy():
            janitor.sweep(plan.experiment_id, world=adapter)
        with db.transaction(readonly=True) as tx:
            fenced = tx.fetchone(
                "SELECT coordinator_token FROM benchmark_dispatch_slots WHERE experiment_id=%s",
                (plan.experiment_id,),
            )
            fenced_acq = tx.fetchone(
                "SELECT coordinator_token, recovery_deadline "
                "FROM benchmark_acquisitions WHERE acquisition_id=%s",
                (acquisition["acquisition_id"],),
            )
            lease = tx.fetchone("SELECT * FROM pod_leases WHERE id=%s", (acquisition["lease_id"],))
        assert fenced["coordinator_token"] is None  # the still-valid token was fenced
        assert fenced_acq["coordinator_token"] is None
        assert fenced_acq["recovery_deadline"] == deadline  # reused, never re-granted
        assert lease["terminate_verified_at"] is not None or lease["stop_verified_at"] is not None
    finally:
        # The stale worker returns: its control write (observing its own
        # result) and its dispatch are both REFUSED - and it sends nothing
        # new. (Always release the thread so a failure cannot leak it past
        # the database fixture.)
        submissions_before = len(comfy.server.submissions)
        release.set()
        worker.join(timeout=60)
        assert not worker.is_alive()
    stalled_status = result["status"]
    assert stalled_status["admission"]["permitted"] is False
    assert any("R3 fence" in blocker for blocker in stalled_status["admission"]["blockers"])
    assert len(comfy.server.submissions) == submissions_before  # no further dispatch
    with db.transaction(readonly=True) as tx:
        sample2 = tx.fetchone(
            "SELECT state, output FROM benchmark_samples WHERE experiment_id=%s "
            "AND sample_id='S03-R1'",
            (plan.experiment_id,),
        )
    assert sample2["output"] is None  # the stale worker's projection was refused

    # A FRESH takeover no longer waits out the one-hour coordinator lease:
    # the fence, not token expiry, unblocked the dispatch slot. The parked
    # sample's send was authorised BEFORE the fence, so its positively-known
    # outcome is adopted by recovery (never resubmitted: exactly one prompt
    # under its deterministic client id).
    from microdrama.rendering.comfy_jobs import render_client_id

    parked_key = f"benchmark:{plan.experiment_id}:sample:S03-R1:a1"
    parked_client_id = render_client_id(parked_key)
    parked_prompts = [
        prompt_id
        for prompt_id, prompt in comfy.server.prompts.items()
        if prompt.client_id == parked_client_id
    ]
    assert len(parked_prompts) == 1  # never a second POST for the same intent
    comfy.service._client = FakeComfyClient(comfy.server)
    fresh = _execute_service(db, comfy, world.ids, adapter)
    with _PatchedPolicy():
        after = fresh.resume(
            plan.experiment_id,
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            phase="screen",
            source_bytes=raw,
        )
    assert after["execution_state"] in ("SCREEN_RUNNING", "SCREEN_REVIEW", "NEEDS_RECONCILIATION")
    with db.transaction(readonly=True) as tx:
        parked = tx.fetchone(
            "SELECT state FROM benchmark_samples WHERE experiment_id=%s AND sample_id='S03-R1'",
            (plan.experiment_id,),
        )
        still_one = tx.fetchval(
            "SELECT COUNT(*) FROM provider_operations o JOIN benchmark_samples s "
            "ON s.reservation_id=o.reservation_id WHERE s.experiment_id=%s "
            "AND s.sample_id='S03-R1'",
            (plan.experiment_id,),
        )
    assert parked["state"] == "SUCCEEDED"  # recovered by the fresh takeover
    assert still_one == 1  # one operation, one prompt - no duplicate anything (I1/I6)


# ---------------------------------------------------------------------------
# AT-2 — deadline expiry: pod terminated, op UNKNOWN with exposure, fresh
# resume writes nothing, resolve -> sample FAILED -> experiment FAILED (§7.4).
# ---------------------------------------------------------------------------


def _snapshot(db: Database, experiment_id) -> dict:
    with db.transaction(readonly=True) as tx:
        return {
            "experiments": [
                dict(r)
                for r in tx.fetchall(
                    "SELECT * FROM benchmark_experiments WHERE experiment_id=%s", (experiment_id,)
                )
            ],
            "acquisitions": [
                dict(r)
                for r in tx.fetchall(
                    "SELECT * FROM benchmark_acquisitions WHERE experiment_id=%s "
                    "ORDER BY acquisition_id",
                    (experiment_id,),
                )
            ],
            "samples": [
                dict(r)
                for r in tx.fetchall(
                    "SELECT * FROM benchmark_samples WHERE experiment_id=%s ORDER BY sample_id",
                    (experiment_id,),
                )
            ],
            "operations": [
                dict(r)
                for r in tx.fetchall(
                    "SELECT o.* FROM provider_operations o JOIN benchmark_samples s "
                    "ON s.reservation_id=o.reservation_id WHERE s.experiment_id=%s ORDER BY o.id",
                    (experiment_id,),
                )
            ],
        }


def test_at02_deadline_expiry_terminates_pod_and_resolution_fails_experiment(
    db: Database, tmp_path: Path
):
    world, ep, plan, service, comfy, adapter, authorization, digest, raw = _base(db, tmp_path)
    comfy.service._client = _NeverAcceptedTimeoutClient(comfy.server)
    first = _execute_service(db, comfy, world.ids, adapter)
    with _PatchedPolicy():
        ambiguous = first.execute(
            plan.experiment_id,
            phase="screen",
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            source_bytes=raw,
        )
    assert ambiguous["execution_state"] == "NEEDS_RECONCILIATION"
    acquisition = _acquisition_row(db, plan.experiment_id)
    deadline = _grace_row(db, acquisition["acquisition_id"])["recovery_deadline"]

    # Past the deadline: resume terminates the pod at recovery_deadline; the
    # operation stays UNKNOWN with its exposure retained (I2/I4).
    comfy.service._client = FakeComfyClient(comfy.server)
    comfy.clock.advance(seconds=(deadline - comfy.clock.now()).total_seconds() + 1)
    takeover = _execute_service(db, comfy, world.ids, adapter)
    with _PatchedPolicy():
        takeover.resume(
            plan.experiment_id,
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            phase="screen",
            source_bytes=raw,
        )
    with db.transaction(readonly=True) as tx:
        lease = tx.fetchone("SELECT * FROM pod_leases WHERE id=%s", (acquisition["lease_id"],))
        reservation = tx.fetchone(
            "SELECT r.* FROM reservations r JOIN benchmark_samples s "
            "ON s.reservation_id=r.id WHERE s.experiment_id=%s AND s.sample_id='S01-R1'",
            (plan.experiment_id,),
        )
    assert lease["terminate_verified_at"] is not None or lease["stop_verified_at"] is not None
    assert reservation["state"] in ("ACTIVE", "EXPIRED")  # liability keeps exposure (I4)

    # A FRESH resume writes nothing: identical durable rows, zero sends.
    before = _snapshot(db, plan.experiment_id)
    submissions_before = len(comfy.server.submissions)
    fresh = _execute_service(db, comfy, world.ids, adapter)
    with _PatchedPolicy():
        status = fresh.resume(
            plan.experiment_id,
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            phase="screen",
            source_bytes=raw,
        )
    assert status["execution_state"] == "NEEDS_RECONCILIATION"
    assert status["admission"]["permitted"] is False
    assert len(comfy.server.submissions) == submissions_before
    assert _snapshot(db, plan.experiment_id) == before  # no state write at all

    # The audited operator resolution closes the UNKNOWN: sample FAILED,
    # experiment FAILED once (§7.4), financial finalization and cleanup reach
    # closure, and nothing is ever dispatched again.
    resolved = fresh.resolve_sample(
        plan.experiment_id,
        sample_id="S01-R1",
        actor_ref="operator-console",
        reason="queue and history show no prompt for the deterministic client id",
        evidence_sha256="b" * 64,
        world=adapter,
    )
    assert {s["sample_id"]: s["state"] for s in resolved["samples"]}["S01-R1"] == "FAILED"
    assert resolved["execution_outcome"] == "FAILED"
    with _PatchedPolicy():
        final = fresh.sweep(plan.experiment_id, world=adapter)
        after = fresh.resume(
            plan.experiment_id,
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            phase="screen",
            source_bytes=raw,
        )
    assert final["cleanup_state"] == "VERIFIED"
    assert final["billing_state"] == "BILLED"
    assert after["admission"]["permitted"] is False  # no further dispatch
    assert len(comfy.server.submissions) == submissions_before
