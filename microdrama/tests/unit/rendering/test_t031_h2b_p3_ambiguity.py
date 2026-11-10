"""T031 H-2 build, package P3: ambiguity at run time (spec v3 §5).

AT-1, AT-15, AT-16, AT-25 and the §5.1 classification first (create vs upload
vs submit/poll ambiguity label exactly what §5.1 says); part 2 adds the
durable-grace ATs (AT-2/AT-18/AT-19), the §5.3 upload readback (AT-17) and
AT-3. Public entry points only.
"""

from __future__ import annotations

import json
import os
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


def test_at16b_u3p_missing_linkage_blocks_fresh_admission(db: Database, tmp_path: Path):
    """§9.3 extension for AT-16: a known in-flight operation whose sample
    linkage never landed (U3p) blocks fresh admission until it is recovered
    and finalised - the reservation linkage, not the missing sample link, is
    what the gate reads."""
    from microdrama.pipeline.benchmark_service import AdmissionBlocked

    world, ep, plan, service, comfy, adapter, slot, operation, authorization, digest, raw = (
        _crash_state(db, tmp_path, operation_state="SUBMITTED", with_prompt=True)
    )
    assert slot["operation_id"] is None

    fresh = _execute_service(db, comfy, world.ids, adapter)
    with _PatchedPolicy():
        with pytest.raises(AdmissionBlocked) as refused:
            fresh.execute(
                plan.experiment_id,
                phase="screen",
                authorization=authorization,
                quote=_screen_quote(world),
                expected_sha256=digest,
                source_bytes=raw,
            )
    assert any("U3p" in blocker for blocker in refused.value.blockers), refused.value.blockers
    # The linkage is still missing: nothing was dispatched to repair it.
    with db.transaction(readonly=True) as tx:
        after = tx.fetchone(
            "SELECT operation_id FROM benchmark_samples WHERE experiment_id=%s "
            "AND sample_id='S01-R1'",
            (plan.experiment_id,),
        )
        states = tx.fetchall(
            "SELECT DISTINCT state FROM benchmark_samples WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
    assert after["operation_id"] is None
    assert all(row["state"] != "SUCCEEDED" for row in states)


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
    # sample's send was authorised BEFORE the fence - but the janitor's
    # cleanup STOPPED the pod (verified stop; termination verify is the
    # janitor's separate tail), so the §3.4 (HB-2) binding is INDETERMINATE:
    # the takeover can neither read the stopped pod's history nor adopt the
    # prompt, and never resubmits. The sample stays unprojected; exactly one
    # prompt exists under its deterministic client id (I1/I6). Only an audited
    # resolution (§7.3) or the janitor's terminal tail closes this.
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
    # Inherited SCREEN_RUNNING (worker 2's resume had recovered S01 before
    # the fence) is fine: the stuck slot silently blocks all progress.
    assert after["execution_state"] in ("SCREEN_RUNNING", "NEEDS_RECONCILIATION")
    with db.transaction(readonly=True) as tx:
        parked_sample = tx.fetchone(
            "SELECT state FROM benchmark_samples WHERE experiment_id=%s AND sample_id='S03-R1'",
            (plan.experiment_id,),
        )
        still_one = tx.fetchval(
            "SELECT COUNT(*) FROM provider_operations o JOIN benchmark_samples s "
            "ON s.reservation_id=o.reservation_id WHERE s.experiment_id=%s "
            "AND s.sample_id='S03-R1'",
            (plan.experiment_id,),
        )
        parked_op = tx.fetchval(
            "SELECT o.state FROM provider_operations o JOIN benchmark_samples s "
            "ON s.reservation_id=o.reservation_id WHERE s.experiment_id=%s "
            "AND s.sample_id='S03-R1'",
            (plan.experiment_id,),
        )
    assert parked_sample["state"] == "CLAIMED"  # never projected; not adoptable
    # The released worker's own SUBMITTED write committed (the comfy-level
    # result write carries no coordinator token); whether a takeover saw
    # PENDING_SUBMIT or SUBMITTED first is timing - either way the stopped
    # pod leaves the outcome unadoptable and blocked.
    assert parked_op in ("UNKNOWN", "SUBMITTED")
    assert still_one == 1  # one operation, one prompt - no duplicate anything (I1/I6)
    # The fresh takeover dispatched nothing: no new prompt POST for the parked
    # intent and no new sample send while the outcome stays uncertain.
    assert len(comfy.server.submissions) == submissions_before


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


# ---------------------------------------------------------------------------
# AT-3 — worker SIGKILLed mid-poll, pod alive: a fresh-process CLI reconcile
# binds BOUND from the durable lease, persists the output into the CLI-built
# store and sends ZERO posts (§9.3 death harness: the fake server state and
# send counters survive the killed process on disk).
# ---------------------------------------------------------------------------


def _snapshot_server(state, path: Path) -> None:
    """Serialize the fake ComfyUI server state (§9.3: outside process memory)."""

    payload = {
        "now": state.clock.now().isoformat(),
        "counter": len(state.submissions),
        "submissions": list(state.submissions),
        "prompts": [
            {
                "prompt_id": prompt.prompt_id,
                "completes_at": prompt.completes_at.isoformat(),
                "scenario": prompt.scenario.value,
                "first_node": prompt.first_node,
                "sampler_node": prompt.sampler_node,
                "client_id": prompt.client_id,
                "outputs": [
                    output.model_dump(mode="json")
                    if hasattr(output, "model_dump")
                    else dict(output)
                    for output in prompt.outputs
                ],
            }
            for prompt in state.prompts.values()
        ],
        "files": [
            [filename, media_kind, scenario.value]
            for filename, (media_kind, scenario) in state._files.items()
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _restore_server(state, payload: dict) -> None:
    from datetime import datetime

    from microdrama.contracts.providers import ComfyOutputFile
    from microdrama.testing.fakes.comfy import ComfyScenario, _Prompt

    for entry in payload["prompts"]:
        state.prompts[entry["prompt_id"]] = _Prompt(
            prompt_id=entry["prompt_id"],
            completes_at=datetime.fromisoformat(entry["completes_at"]),
            scenario=ComfyScenario(entry["scenario"]),
            first_node=entry["first_node"],
            sampler_node=entry["sampler_node"],
            outputs=[ComfyOutputFile.model_validate(output) for output in entry["outputs"]],
            client_id=entry["client_id"],
        )
    state.submissions.extend(payload["submissions"])
    state._counter = payload["counter"]
    for filename, media_kind, scenario in payload["files"]:
        state.register_output(filename, media_kind, ComfyScenario(scenario))


class _DieMidPollClient(FakeComfyClient):
    """Kills the worker inside the first poll of a COMPLETED prompt.

    The submit already committed SUBMITTED with its prompt id; the death lands
    between the external effect and the observation commit - exactly §E's
    mid-poll window. The server state is serialized first so the parent can
    reconstruct what the killed process left behind."""

    def __init__(self, state, snapshot: Path, marker: Path):
        super().__init__(state)
        self.snapshot = snapshot
        self.marker = marker

    def history(self, prompt_id):
        prompt = self._prompt(prompt_id)
        if (
            not self.marker.exists()
            and prompt is not None
            and not self._running(prompt)
            and prompt.outputs
        ):
            _snapshot_server(self.state, self.snapshot)
            self.marker.write_text("mid-poll", encoding="utf-8")
            os._exit(86)  # §9.3: bypasses every exception cleanup path
        return super().history(prompt_id)


def _at3_child(dsn: str, out_dir: str, marker: str, snapshot: str, identity: str) -> None:
    """Runs INSIDE the subprocess: the real composed execute path until death.

    The paths are already set by the launching script; only the process-local
    policy patches happen here (they die with the subprocess)."""
    import microdrama.pipeline.experimental_world as world_module
    from microdrama.pipeline.benchmark_authorization import BenchmarkAuthorization

    world_module.ExperimentalPresetPolicy.validate = lambda *a, **k: None
    BenchmarkAuthorization.validate_for = lambda *a, **k: None

    from rendering_support import RenderWorld
    from test_benchmark_experiments import _composed_world
    from test_t031_h2b_p1_modes import _authorization_pair, _bench_seal, _execute_service

    from microdrama.persistence import Database

    db = Database(dsn).open()
    world = RenderWorld(db)
    out = Path(out_dir)
    ep, plan, service, budget, comfy, adapter = _composed_world(world, out)
    service.seal(plan.experiment_id, _bench_seal(plan))
    _, authorization, digest, raw = _authorization_pair(world, plan, out)
    Path(identity).write_text(json.dumps({"experiment_id": str(plan.experiment_id)}))
    comfy.service._client = _DieMidPollClient(comfy.server, Path(snapshot), Path(marker))
    # Step 1 (public execute) submits the first prompt and commits SUBMITTED
    # with its prompt id. Every later step continues through public resume()
    # (a fresh process never re-admits while U3p work is in flight; its
    # reconcile polls the in-flight operation first) - and that poll of the
    # now-completed prompt is where the worker dies mid-poll (os._exit),
    # between the durable external-effect record and the observation commit
    # (§9.3 death window).
    quote = _screen_quote(world)
    dying = _execute_service(db, comfy, world.ids, adapter)
    dying.execute(
        plan.experiment_id,
        phase="screen",
        authorization=authorization,
        quote=quote,
        expected_sha256=digest,
        source_bytes=raw,
    )
    comfy.clock.advance(seconds=1)
    for _ in range(30):
        dying = _execute_service(db, comfy, world.ids, adapter)
        dying.resume(
            plan.experiment_id,
            authorization=authorization,
            quote=quote,
            expected_sha256=digest,
            phase="screen",
            source_bytes=raw,
        )
        comfy.clock.advance(seconds=1)
    import sys

    print("child finished its steps without the mid-poll death", file=sys.stderr)


def test_at03_worker_sigkill_mid_poll_cli_reconcile_binds_bound_and_persists_output(
    db: Database, tmp_path: Path
):
    import subprocess
    import sys

    marker = tmp_path / "at3.marker"
    snapshot = tmp_path / "at3-server.json"
    identity = tmp_path / "at3-identity.json"
    script = (
        "import sys; sys.argv=['child']; "
        "sys.path[:0] = ["
        f"{str(Path(__file__).resolve().parents[3] / 'src')!r}, "
        f"{str(Path(__file__).resolve().parents[1])!r}, "
        f"{str(Path(__file__).parent)!r}]; "
        "from test_t031_h2b_p3_ambiguity import _at3_child as run; "
        f"run({db.dsn!r}, {str(tmp_path / 'at3-child-out')!r}, {str(marker)!r}, "
        f"{str(snapshot)!r}, {str(identity)!r})"
    )
    env = dict(os.environ)
    env.update(
        {
            "MICRODRAMA_EXECUTION_MODE": "OFFLINE_MOCK",
            "MICRODRAMA_PAID_REQUESTS_ENABLED": "false",
            "MICRODRAMA_CLOUD_RESOURCES_ENABLED": "false",
            "MICRODRAMA_PUBLIC_ACTIONS_ENABLED": "false",
        }
    )
    child = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(Path(__file__).parent),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert marker.exists(), child.stderr[-2000:]
    assert child.returncode == 86, child.stderr[-2000:]
    experiment_id = UUID(json.loads(identity.read_text(encoding="utf-8"))["experiment_id"])

    # The durable state the killed worker left: an ACTIVE acquisition with a
    # live pod, the dispatch slot claimed, and the operation SUBMITTED with
    # its prompt id - the outcome never observed.
    with db.transaction(readonly=True) as tx:
        acquisition = tx.fetchone(
            "SELECT a.*, l.pod_id, l.lease_state FROM benchmark_acquisitions a "
            "JOIN pod_leases l ON l.id=a.lease_id WHERE a.experiment_id=%s",
            (experiment_id,),
        )
        operation = tx.fetchone(
            "SELECT o.id, o.state, o.external_id FROM provider_operations o "
            "JOIN benchmark_samples s ON s.reservation_id=o.reservation_id "
            "WHERE s.experiment_id=%s",
            (experiment_id,),
        )
    assert acquisition["state"] == "ACTIVE"
    assert acquisition["pod_id"] is not None
    # The poll had observed progress (RUNNING) before the death landed in the
    # history call - the outcome itself was never observed or projected.
    assert operation["state"] in ("SUBMITTED", "RUNNING")
    assert operation["external_id"]

    # §3.4 from the durable lease alone: the recovery world binds BOUND.
    assert adapter_for_at3(db, tmp_path, experiment_id)[1] == "BOUND"

    # Fresh-process CLI reconcile: output persisted into the CLI-built store,
    # zero posts (the counters survived the killed child on disk).

    comfy, adapter, store_root = _at3_parent_world(db, tmp_path, experiment_id, snapshot)
    from test_t031_h2b_p1_modes import _offline_settings

    from microdrama.pipeline.benchmark import main
    from microdrama.pipeline.benchmark_service import BenchmarkService

    settings = _offline_settings(store_root, db)
    submissions_before = len(comfy.server.submissions)

    def service_factory(db, settings, store, injection):
        from microdrama.core.clock import UuidIds

        return BenchmarkService(
            db,
            settings,
            store=store,
            clock=comfy.clock,
            ids=UuidIds(),
            world_factory=lambda **_kwargs: adapter,
        )

    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(
            ["reconcile", "--experiment-id", str(experiment_id)],
            _injection={"db": db, "settings": settings, "service_factory": service_factory},
        )
    assert code == 0, buffer.getvalue()
    payload = json.loads(buffer.getvalue())
    assert {s["sample_id"]: s["state"] for s in payload["samples"]}["S01-R1"] == "SUCCEEDED"
    assert len(comfy.server.submissions) == submissions_before  # ZERO posts (I5)
    assert list(store_root.rglob("*")), "the CLI-built store received no output object"
    with db.transaction(readonly=True) as tx:
        stored = tx.fetchone(
            "SELECT state, output FROM benchmark_samples WHERE experiment_id=%s "
            "AND sample_id='S01-R1'",
            (experiment_id,),
        )
    assert stored["state"] == "SUCCEEDED"
    assert stored["output"]["sha256"]


def adapter_for_at3(db: Database, tmp_path: Path, experiment_id: UUID):
    """Compose a parent-side world and return (acquisition_id, bind result)."""
    comfy, adapter, _ = _at3_parent_world(db, tmp_path, experiment_id, None)
    with db.transaction(readonly=True) as tx:
        acquisition_id = tx.fetchval(
            "SELECT acquisition_id FROM benchmark_acquisitions WHERE experiment_id=%s",
            (experiment_id,),
        )
    return acquisition_id, adapter.bind_for_recovery(acquisition_id)


def _at3_seed_live_pod(db: Database, world, comfy, experiment_id: UUID) -> None:
    """Rebuild the killed worker's pod in the parent's fresh fake provider.

    The pod is alive at the provider regardless of the worker process: its
    identity (pod id, client token, create instant) is durable on the lease,
    and the fake endpoint URL is derived from the pod id exactly the way
    ``create_pod`` derives it. This mirrors the provider-side pod the killed
    child left behind - the same role the on-disk server snapshot plays for
    the ComfyUI state."""
    from microdrama.testing.fakes.common import fake_https
    from microdrama.testing.fakes.pods import (
        FAKE_GPU_TYPE,
        FAKE_POD_HOURLY_MICRO_USD,
        _Pod,
    )

    with db.transaction(readonly=True) as tx:
        lease = tx.fetchone(
            "SELECT l.pod_id, l.client_token, l.create_requested_at "
            "FROM pod_leases l JOIN benchmark_acquisitions a ON a.lease_id = l.id "
            "WHERE a.experiment_id = %s",
            (experiment_id,),
        )
    assert lease is not None and lease["pod_id"], "the child died before any pod existed"
    world.provider._pods[lease["pod_id"]] = _Pod(
        pod_id=lease["pod_id"],
        name=f"recovered-{lease['pod_id']}",
        owned_tag=world.config.owned_tag,
        client_token=lease["client_token"],
        gpu_type=FAKE_GPU_TYPE,
        hourly_price_micro_usd=FAKE_POD_HOURLY_MICRO_USD,
        created_at=lease["create_requested_at"] or comfy.clock.now(),
        endpoint_url=fake_https(f"{lease['pod_id']}.pods.fake", ""),
        pipeline_owned=True,
    )


def _at3_parent_world(db: Database, tmp_path: Path, experiment_id: UUID, snapshot):
    """The parent's composed world: same durable rows, reconstructed server."""
    from dataclasses import replace

    from comfy_support import ComfyWorld
    from rendering_support import RenderWorld
    from test_t031_h2b_p2_gate import _adapter_for

    from microdrama.rendering.comfy_jobs import ComfyRenderConfig

    world = RenderWorld(db)
    store_root = tmp_path / "at3-cli-store"
    comfy = ComfyWorld(
        db,
        store_root,
        config=replace(ComfyRenderConfig.for_mock(), lease_covered=True),
        execution_ms=0,
    )
    if snapshot is not None:
        payload = json.loads(Path(snapshot).read_text(encoding="utf-8"))
        from datetime import datetime

        comfy.clock.set(datetime.fromisoformat(payload["now"]))
        _restore_server(comfy.server, payload)
    else:
        comfy.clock.set(world.clock.now())
    world.clock = comfy.clock
    world.leases._clock = comfy.clock
    world.provider.clock = comfy.clock
    world.manager._clock = comfy.clock
    _at3_seed_live_pod(db, world, comfy, experiment_id)
    with db.transaction(readonly=True) as tx:
        plan_row = tx.fetchone(
            "SELECT * FROM benchmark_experiments WHERE experiment_id=%s", (experiment_id,)
        )
    adapter, budget = _adapter_for(db, world, comfy, plan_row, experiment_id)
    comfy.service._client = FakeComfyClient(comfy.server)
    comfy.service._budget = budget
    return comfy, adapter, store_root


# ---------------------------------------------------------------------------
# AT-17 (§5.3) + §9.3 extensions — upload POST ambiguity on a REAL composed
# native-inputs world (build_experiment_world with the real PikaHttpClient
# and scripted in-memory transports). The pod-side ComfyUI accepts every input
# upload and then loses the response: recovery may only checksum-read the
# inputs back (GET /view), never POST a second upload, never invent a prompt
# operation; an unverifiable readback leaves U3u blocking every dependent
# sample; an EXPIRED hold still allows the input readback in RECOVERY (R4);
# wrong owner and wrong mode are refused at the request guard.
# ---------------------------------------------------------------------------


def _at17_png(index: int) -> bytes:
    """A distinct valid PNG per port (validate_input_bytes must accept it)."""
    import struct
    import zlib

    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00" + bytes([0xA0 + index]) * 12))
        + chunk(b"IEND", b"")
    )


class _At17RunpodTransport:
    """In-memory Runpod API: echoes the create POST as a RUNNING pod with the
    declared 8188 proxy port (the endpoint the Pika client binds)."""

    def __init__(self, now, server=None) -> None:
        self.now = now
        self.calls: list[tuple[str, str]] = []
        self.pod: dict | None = None
        self.server = server

    def request(self, method, url, *, headers, body=None):
        self.calls.append((method, url))
        if method == "GET" and url.startswith("https://api.runpod.io/v2/pods?"):
            return type(
                "R",
                (),
                {"status": 200, "body": b'{"pods": [], "pagination": {}}'},
            )()
        if method == "POST" and url.endswith("/pods"):
            request = json.loads(body)
            self.pod = {
                "id": "pod-at17-1",
                "name": request["name"],
                "image": request["image"],
                "status": "RUNNING",
                "cost": "0.500000",
                "createdAt": self.now().isoformat(),
                "gpu": request["gpu"] | {"memory": 48, "vcpuCount": 16},
                "ports": request.get("ports"),
                "runtime": {"ports": [{"private": 8188, "public": 8188, "type": "http"}]},
            }
            return type("R", (), {"status": 200, "body": json.dumps(self.pod).encode()})()
        if method == "GET" and "/pods/pod-at17-1" in url:
            return type("R", (), {"status": 200, "body": json.dumps(self.pod).encode()})()
        if method == "POST" and url.endswith("/action"):
            assert self.pod is not None, "stop before create"
            assert json.loads(body) == {"action": "stop"}
            self.pod["status"] = "STOPPED"
            if self.server is not None:
                self.server.alive = False
            return type("R", (), {"status": 200, "body": b'{"status": "in progress"}'})()
        if method == "DELETE" and "/pods/pod-at17-1" in url:
            assert self.pod is not None, "terminate before create"
            self.pod["status"] = "TERMINATED"
            if self.server is not None:
                self.server.alive = False
            return type("R", (), {"status": 200, "body": b'{"status": "terminated"}'})()
        raise AssertionError(f"unexpected Runpod call: {method} {url}")


class _At17ComfyServer:
    """The pod-side ComfyUI state that outlives any one client/transport.

    Inputs, prompts, rendered outputs and the POST counters are SERVER state
    (HB-2): a fresh recovery client - a new transport over the same server -
    sees exactly what the killed worker's server held. The server also serves
    the /queue and /history scans the deterministic client-id finder makes."""

    def __init__(self, schema_bytes: bytes):
        self.schema_bytes = schema_bytes
        self.alive = True  # the pod-side server lives only as long as its pod
        self.inputs: dict[str, bytes] = {}
        self.outputs: dict[str, bytes] = {}
        self.prompts: dict[str, dict] = {}  # prompt_id -> {"client_id", "completed"}
        self.upload_posts = 0
        self.view_gets: list[str] = []
        self.prompt_posts = 0
        self._clip: bytes | None = None

    def output_bytes(self) -> bytes:
        # The exact native SaveVideo shape (verify_native_output pins
        # 480x832, 24 fps, ~5.17 s, 32 kHz stereo AAC): a real ffmpeg render.
        if self._clip is None:
            import subprocess
            import tempfile
            from pathlib import Path as _Path

            with tempfile.TemporaryDirectory(prefix="at17-native-") as tmp:
                path = _Path(tmp) / "native.mp4"
                subprocess.run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-f",
                        "lavfi",
                        "-i",
                        "color=c=black:s=480x832:r=24:d=5.166667",
                        "-f",
                        "lavfi",
                        "-i",
                        "sine=frequency=440:sample_rate=32000",
                        "-ac",
                        "2",
                        "-c:a",
                        "aac",
                        "-t",
                        "5.166667",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "ultrafast",
                        "-pix_fmt",
                        "yuv420p",
                        "-y",
                        str(path),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=60,
                )
                self._clip = path.read_bytes()
        return self._clip

    def accept_prompt(self, client_id: str) -> str:
        self.prompt_posts += 1
        prompt_id = f"at17-prompt-{self.prompt_posts:04d}"
        self.prompts[prompt_id] = {"client_id": client_id, "completed": True}
        self.outputs[f"at17-out-{self.prompt_posts:04d}.mp4"] = self.output_bytes()
        return prompt_id

    def queue_document(self) -> bytes:
        return json.dumps({"queue_running": [], "queue_pending": []}).encode()

    def history_document(self) -> bytes:
        return json.dumps(
            {
                prompt_id: {
                    "prompt": [0, prompt_id, 0, {"client_id": entry["client_id"]}],
                    "status": {"completed": entry["completed"], "status_str": "success"},
                }
                for prompt_id, entry in self.prompts.items()
            }
        ).encode()

    def entry_document(self, prompt_id: str) -> bytes | None:
        entry = self.prompts.get(prompt_id)
        if entry is None:
            return None
        number = int(prompt_id.rsplit("-", 1)[1])
        return json.dumps(
            {
                prompt_id: {
                    "status": {"completed": entry["completed"], "status_str": "success"},
                    "outputs": {
                        "save_video": {
                            "images": [
                                {
                                    "filename": f"at17-out-{number:04d}.mp4",
                                    "subfolder": "",
                                    "type": "output",
                                }
                            ]
                        }
                    },
                }
            }
        ).encode()


class _At17PodComfyTransport:
    """Scripted pod-side ComfyUI over the SHARED server state.

    Per-transport knobs model one worker session: ``upload_timeout`` accepts
    every input upload POST then loses the response (§9.3's acceptance
    window, per port); ``prompt_timeouts`` accepts that many prompt POSTs then
    loses the response (AT-1's submit-acceptance window). Read routes
    (/queue, /history, /view) always serve the shared server, so a FRESH
    client sees the killed worker's server state (HB-2)."""

    def __init__(
        self,
        server: _At17ComfyServer,
        *,
        upload_timeout: bool = False,
        prompt_timeouts: int = 0,
        corrupt_readback: bool = False,
    ):
        self.server = server
        self.upload_timeout = upload_timeout
        self.prompt_timeouts = prompt_timeouts
        self.corrupt_readback = corrupt_readback

    # The POST/GET counters are server state (a fresh client still must never
    # re-POST); existing assertions read them off the transport.
    @property
    def upload_posts(self) -> int:
        return self.server.upload_posts

    @property
    def prompt_posts(self) -> int:
        return self.server.prompt_posts

    @property
    def view_gets(self) -> list[str]:
        return self.server.view_gets

    def request(self, method, url, *, headers, body=None):
        import re as _re
        from urllib.parse import parse_qs, urlparse

        from microdrama.rendering.diagnostics import bound_request_timeout

        # Production fidelity (HB-4): the real UrllibTransport bounds every
        # request by the recovery deadline context and REFUSES once it passed.
        bound_request_timeout(30)
        server = self.server
        if not server.alive:
            # The pod stopped/terminated: its ComfyUI is unreachable.
            raise TimeoutError("pod-side ComfyUI is gone with its pod")
        if method == "GET" and url.endswith("/object_info"):
            return server.schema_bytes
        if method == "POST" and url.endswith("/upload/image"):
            server.upload_posts += 1
            match = _re.search(rb'filename="([^"]+)"\r\nContent-Type: [^\r]+\r\n\r\n', body)
            assert match is not None, "upload multipart lacks the image part"
            start = match.end()
            end = body.rfind(b"\r\n--t031_")
            assert end > start, "upload multipart lacks its closing boundary"
            filename = match.group(1).decode()
            server.inputs[filename] = body[start:end]
            if self.upload_timeout:
                raise TimeoutError("pod accepted the upload; the response was lost")
            subfolder = _re.search(rb'name="subfolder"\r\n\r\n([^\r]+)\r\n', body).group(1).decode()
            return json.dumps({"name": filename, "subfolder": subfolder, "type": "input"}).encode()
        if method == "GET" and "/view" in url:
            server.view_gets.append(url)
            query = parse_qs(urlparse(url).query)
            filename = query["filename"][0]
            folder = query.get("type", ["input"])[0]
            source = server.outputs if folder == "output" else server.inputs
            if filename not in source:
                raise TimeoutError("file absent")
            if self.corrupt_readback and folder != "output":
                return b"corrupt-readback-bytes"
            return source[filename]
        if method == "GET" and url.endswith("/queue"):
            return server.queue_document()
        if method == "GET" and url.endswith("/history"):
            return server.history_document()
        if method == "GET" and "/history/" in url:
            entry = server.entry_document(url.rsplit("/", 1)[1])
            if entry is None:
                return b"{}"
            return entry
        if method == "POST" and url.endswith("/prompt"):
            from microdrama.contracts.errors import NeedsReconciliation

            client_id = json.loads(body)["client_id"]
            prompt_id = server.accept_prompt(client_id)
            if self.prompt_timeouts > 0:
                self.prompt_timeouts -= 1
                # The real UrllibTransport converts the timeout to
                # NeedsReconciliation before world.submit sees it.
                raise NeedsReconciliation("pod accepted the prompt; the response was lost")
            return json.dumps({"prompt_id": prompt_id}).encode()
        raise AssertionError(f"unexpected ComfyUI call: {method} {url}")


class _At17Harness:
    pass


def _at17_compose(
    db: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    corrupt_readback: bool = False,
    upload_timeout: bool = True,
    prompt_timeouts: int = 0,
) -> _At17Harness:
    from datetime import UTC, datetime, timedelta

    from test_benchmark_experiments import plan_for
    from test_t031_h2b_p1_modes import _at4_quote, _paid_settings

    from microdrama.budget import BudgetService

    # The preset policy's live-eligibility layers (disabled+unmeasured preset,
    # model-output rights pins) are covered by the preflight suites; this AT
    # drives the native upload/prompt mechanics, so validate returns a real
    # disabled, unmeasured PresetRecord for the sealed control set instead.
    from microdrama.contracts.enums import (
        AssetKind,
        AssetState,
        ControlKind,
        EvidenceSource,
        Provenance,
        RenderTier,
        RightsStatus,
        RightsSubjectKind,
    )
    from microdrama.contracts.examples import media_info
    from microdrama.contracts.hashing import sha256_hex
    from microdrama.contracts.media import AssetDescriptor
    from microdrama.contracts.primitives import EvidenceRef
    from microdrama.contracts.registries import PresetRecord, RightsRecord
    from microdrama.contracts.season import CostPolicy
    from microdrama.contracts.v2 import ShotReferenceBinding
    from microdrama.core.registry.rights import RightsRegistry
    from microdrama.persistence import register_asset
    from microdrama.persistence.object_store import FilesystemObjectStore
    from microdrama.pipeline.benchmark_authorization import (
        BenchmarkAuthorization,
        BenchmarkSeal,
        document_sha256,
    )
    from microdrama.pipeline.benchmark_service import BenchmarkService
    from microdrama.pipeline.experimental_world import build_experiment_world
    from microdrama.rendering.pika_transport import mapped_schema_sha256
    from microdrama.rendering.workflows.templates import PIKA_TEMPLATE
    from microdrama.rendering.workflows.templates import (
        template_sha256 as _template_sha256,
    )
    from microdrama.testing.fakes import FakeClock, SequentialIds
    from microdrama.testing.media import make_wav_bytes
    from microdrama.testing.seed import seed_episode, seed_season

    preset = PresetRecord(
        preset_id="pika-h3-flex-ref2va-benchmark-v1",
        version=1,
        tier=RenderTier.QUALITY_EIGHT_STEP,
        workflow_sha256=_template_sha256(PIKA_TEMPLATE),
        model_mode="fixture",
        gpu_type="NVIDIA A40",
        min_vram_gb=24,
        host_ram_gb=64,
        precision="fp16",
        width=480,
        height=832,
        frames=124,
        fps=24,
        steps=8,
        attention_backend="fixture",
        supported_controls=[
            ControlKind.TEXT_PROMPT,
            ControlKind.SEED,
            ControlKind.CHARACTER_REFERENCE,
            ControlKind.WARDROBE_REFERENCE,
            ControlKind.LOCATION_REFERENCE,
        ],
        supports_thai_dialogue=None,
        rights_route_id=None,
        measured=None,
        evidence=[],
        enabled=False,
    )
    monkeypatch.setattr(
        "microdrama.pipeline.experimental_world.ExperimentalPresetPolicy.validate",
        lambda *a, **k: preset,
    )
    monkeypatch.setattr(
        "microdrama.pipeline.benchmark_authorization.BenchmarkAuthorization.validate_for",
        lambda *a, **k: None,
    )

    t0 = datetime(2026, 11, 10, 12, tzinfo=UTC)
    clock = FakeClock(t0)
    ids = SequentialIds("at17")
    settings = _paid_settings()
    store = FilesystemObjectStore(tmp_path / "at17-objects")
    budget = BudgetService(db, clock, ids, settings)
    with db.transaction() as tx:
        season_id = seed_season(tx)
        episode_id = seed_episode(tx, season_id, number=1)
        budget.open_episode_account(
            tx, season_id=season_id, episode_id=episode_id, policy=CostPolicy()
        )

    # Real canonical assets behind every sealed port: distinct PNGs for the
    # image roles and a real PCM WAV for the voice role, each registered with
    # its exact bytes in the store and a current WORLDWIDE ELIGIBLE rights row.
    payloads: dict[str, bytes] = {}
    references, ports = [], []
    for index, role in enumerate(("character_identity", "outfit", "location", "voice")):
        data = _at17_png(index) if role != "voice" else make_wav_bytes(1500)
        digest = sha256_hex(data)
        asset_id = UUID(int=1700 + index)
        key = f"at17-inputs/{asset_id}.{'png' if role != 'voice' else 'wav'}"
        stored = store.put_bytes(
            key, data, media_type="image/png" if role != "voice" else "audio/wav"
        )
        assert stored.sha256 == digest
        descriptor = AssetDescriptor(
            asset_id=asset_id,
            asset_kind=AssetKind.IMAGE if role != "voice" else AssetKind.AUDIO,
            object_key=key,
            sha256=digest,
            size_bytes=stored.size_bytes,
            media_type="image/png" if role != "voice" else "audio/wav",
            media=media_info() if role == "voice" else None,
            state=AssetState.ACCEPTED,
            provenance=Provenance.ORIGINAL_FIXTURE,
            episode_id=episode_id,
            season_id=season_id,
            created_at=t0,
        )
        with db.transaction() as tx:
            register_asset(tx, descriptor)
        route = f"at17-rights-{role}"
        kind = RightsSubjectKind.VOICE if role == "voice" else RightsSubjectKind.REFERENCE
        grant = {
            "rights_route_id": route,
            "subject_kind": kind.value,
            "subject_ref": "speaker-a",
            "rights_version": 1,
            "status": "ELIGIBLE",
            "territories": ["TH"],
            "commercial_use": True,
            "output_release_allowed": True,
            "expires_at": None,
            "evidence_sha256": ["e" * 64],
        }
        RightsRegistry(db, clock, settings).record(
            RightsRecord(
                record_id=UUID(int=1800 + index),
                rights_route_id=route,
                version=1,
                subject_kind=kind,
                subject_ref="speaker-a",
                territories=["WORLDWIDE"],
                commercial_use=True,
                output_release_allowed=True,
                required_disclosures=[],
                expires_at=None,
                evidence=[
                    EvidenceRef(
                        source=EvidenceSource.OFFICIAL_DOCUMENTATION, ref="fixture:at17-rights"
                    )
                ],
                status=RightsStatus.ELIGIBLE,
                recorded_at=t0,
            ),
            source_provenance=Provenance.LIVE_PROVIDER,
        )
        payloads[f"{role}"] = data
        # V2Record.seal computes the canonical content hash of the binding.
        binding = ShotReferenceBinding.seal(
            record_id=UUID(int=1900 + index),
            version=1,
            created_at=t0 - timedelta(hours=1),
            updated_at=t0 - timedelta(hours=1),
            valid_from=t0 - timedelta(hours=1),
            valid_until=None,
            role=role,
            subject_id="speaker-a",
            asset_id=asset_id,
            asset_version=1,
            asset_sha256=digest,
            rights=grant,
        )
        references.append(binding.model_dump(mode="json"))
        ports.append(
            {
                "role": role,
                "subject_id": "speaker-a",
                "asset_id": str(asset_id),
                "asset_version": 1,
                "asset_sha256": digest,
                "media_kind": "audio" if role == "voice" else "image",
                "destination_slot": "ref_audios.ref_audio_0"
                if role == "voice"
                else f"ref_images.ref_image_{index}",
            }
        )
    rights_hash = document_sha256(
        {
            "rights": [
                ShotReferenceBinding.model_validate(item).rights.model_dump(mode="json")
                for item in references
            ],
            "territories": ["TH"],
        }
    )
    # The pod serves the captured real runtime schema for the pika template.
    fixture = json.loads(
        (
            Path(__file__).parents[2]
            / "fixtures/pika_h3_flex_object_info_OFFLINE_FIXTURE_ONLY.json"
        ).read_text()
    )
    raw_schema = fixture["schemas"]
    schema_bytes = json.dumps(raw_schema).encode()
    # The native prompt retains the frozen speaker identities: every shot names
    # exactly the sealed voice anchor's subject.
    plan = plan_for(
        episode_id,
        shots=[
            {
                "shot_id": f"S0{i}",
                "thai_line": "สวัสดี",
                "english_line": "Hello",
                "english_prompt": "A street food stall at dusk, warm practical light.",
                "speaker_subject_ids": ["speaker-a"],
            }
            for i in range(1, 9)
        ],
    )
    service = BenchmarkService(db, settings, clock=clock, ids=ids)
    service.prepare(plan)
    seal = BenchmarkSeal.model_validate(
        {
            "experiment_id": str(plan.experiment_id),
            "plan_sha256": plan.plan_sha256,
            "references": references,
            "port_map": ports,
            "runtime_profile": {"profile": "fixture"},
            "image_ref": "registry.example/drama@sha256:" + "b" * 64,
            "node_schema_sha256": mapped_schema_sha256(raw_schema, PIKA_TEMPLATE.node_classes),
            "rights_evidence_hash": rights_hash,
            "schema_evidence": "LIVE_PROVIDER",
            "schema_attestation_source": "INDEPENDENT_RUNTIME_CAPTURE",
            "territories": ["TH"],
            # The pika preflight binds at max(world clock, real now)
            # (pika_h3_flex.py: `at=max(context.at, datetime.now(UTC))`), so a
            # short seal window time-bombs the test against wall-clock time.
            "eligible_until": (t0 + timedelta(days=365)).isoformat(),
            "hard_stop_utc": (t0 + timedelta(hours=4)).isoformat(),
        }
    )
    service.seal(plan.experiment_id, seal)
    authorization = BenchmarkAuthorization.model_validate(
        {
            "operator": "fixture-operator.invalid",
            "change_ref": "at17-native-inputs",
            "experiment_id": str(plan.experiment_id),
            "episode_id": str(plan.episode_id),
            "plan_sha256": plan.plan_sha256,
            "sealed_sha256": seal.sealed_sha256,
            "provider_account_ref": "acct:fixture",
            "max_new_exposure_micro_usd": 8_000_000,
            "max_gpu_ms": 14_400_000,
            "hard_stop_utc": (t0 + timedelta(hours=4)).isoformat(),
            "allowed_gpu_types": ["NVIDIA A40"],
            "minimum_host_ram_gb": 64,
            "max_hourly_micro_usd": 850_000,
            "max_storage_exposure_micro_usd": 2_000_000,
            "container_disk_gb": 100,
            "persistent_volume_gb": 100,
            "shutdown_reserve_micro_usd": 500_000,
            "namespace": "benchx",
            "runpod_credential_ref": "credref:fixture-runpod",
            "comfy_credential_ref": "credref:fixture-comfy",
            "rights_evidence_hash": seal.rights_evidence_hash,
        }
    )
    for ref in (authorization.runpod_credential_ref, authorization.comfy_credential_ref):
        import os as _os

        path = tmp_path / f"{ref.replace(':', '_')}.secret"
        path.write_text(f"synthetic-{ref}", encoding="utf-8")
        _os.chmod(path, 0o600)
        with db.transaction() as tx:
            tx.execute(
                "INSERT INTO credential_refs(ref, purpose, provider, store, locator) "
                "VALUES(%s, 'fixture', 'runpod', 'FILE', %s)",
                (ref, str(path)),
            )
    server = _At17ComfyServer(schema_bytes)
    runpod = _At17RunpodTransport(clock.now, server)
    comfy = _At17PodComfyTransport(
        server,
        upload_timeout=upload_timeout,
        prompt_timeouts=prompt_timeouts,
        corrupt_readback=corrupt_readback,
    )

    def factory(
        *,
        experiment_id,
        budget,
        authorization=None,
        quote=None,
        mode="EXECUTE",
        acquisition_id=None,
    ):
        return build_experiment_world(
            settings,
            db,
            budget,
            store,
            experiment_id=experiment_id,
            authorization=authorization,
            quote=quote,
            mode=mode,
            acquisition_id=acquisition_id,
            clock=clock,
            ids=ids,
            runpod_transport=runpod,
            comfy_transport=comfy,
        )

    harness = _At17Harness()
    harness.db = db
    harness.settings = settings
    harness.store = store
    harness.clock = clock
    harness.ids = ids
    harness.plan = plan
    harness.seal = seal
    harness.authorization = authorization
    harness.quote = _at4_quote(clock)
    harness.payloads = payloads
    harness.runpod = runpod
    harness.server = server
    harness.comfy = comfy
    harness.factory = factory
    harness.service = BenchmarkService(db, settings, clock=clock, ids=ids, world_factory=factory)
    return harness


def _at17_resume(harness, *, limit=24):
    """Drive public resume until the first prompt operation exists (or the
    limit hits), one dispatch step per call."""
    last = None
    for _ in range(limit):
        last = harness.service.resume(
            harness.plan.experiment_id,
            authorization=harness.authorization,
            quote=harness.quote,
            expected_sha256=harness.authorization.authorization_sha256,
            phase="screen",
        )
        with harness.db.transaction(readonly=True) as tx:
            operation = tx.fetchone(
                "SELECT o.id FROM provider_operations o JOIN benchmark_samples s "
                "ON s.reservation_id=o.reservation_id WHERE s.experiment_id=%s",
                (harness.plan.experiment_id,),
            )
        if operation is not None:
            return last
        harness.clock.advance(seconds=1)
    return last


def test_at17_upload_ambiguity_readback_verifies_and_never_reposts(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    harness = _at17_compose(db, tmp_path, monkeypatch)
    plan = harness.plan

    first = harness.service.execute(
        plan.experiment_id,
        phase="screen",
        authorization=harness.authorization,
        quote=harness.quote,
        expected_sha256=harness.authorization.authorization_sha256,
    )
    # §5.1: the upload ambiguity is classified as such - the experiment needs
    # reconciliation, the acquisition stays ACTIVE, the intent stays open and
    # NO prompt operation was invented.
    assert first["execution_state"] == "NEEDS_RECONCILIATION"
    assert first["acquisitions"][0]["state"] == "ACTIVE"
    with db.transaction(readonly=True) as tx:
        open_uploads = tx.fetchall(
            "SELECT state FROM benchmark_uploads WHERE acquisition_id=%s",
            (first["acquisitions"][0]["acquisition_id"],),
        )
        operations = tx.fetchall(
            "SELECT o.id FROM provider_operations o JOIN benchmark_samples s "
            "ON s.reservation_id=o.reservation_id WHERE s.experiment_id=%s",
            (plan.experiment_id,),
        )
    assert open_uploads and all(row["state"] == "UNKNOWN" for row in open_uploads)
    assert operations == []  # no prompt operation exists (§5.1)
    assert harness.comfy.upload_posts == 1  # the first port POSTed once, then died

    # §5.3 recovery: every open intent reconciles ONLY by checksum readback.
    final = _at17_resume(harness)
    assert final is not None and final["execution_state"] != "NEEDS_RECONCILIATION", final[
        "execution_state"
    ]
    with db.transaction(readonly=True) as tx:
        rows = tx.fetchall(
            "SELECT state, verified_readback_sha256 FROM benchmark_uploads WHERE acquisition_id=%s",
            (first["acquisitions"][0]["acquisition_id"],),
        )
        operation = tx.fetchone(
            "SELECT o.id, o.state, o.external_id FROM provider_operations o "
            "JOIN benchmark_samples s ON s.reservation_id=o.reservation_id "
            "WHERE s.experiment_id=%s",
            (plan.experiment_id,),
        )
    assert len(rows) == 4 and all(row["state"] == "VERIFIED" for row in rows)
    assert all(row["verified_readback_sha256"] for row in rows)
    # Exactly one prompt operation now exists (dispatch continued after the
    # readbacks) and it was never invented during the ambiguity.
    assert operation is not None and operation["state"] == "SUBMITTED"
    assert operation["external_id"]
    # §5.3/I1: four upload intents, exactly four upload POSTs - never a second
    # POST for any intent; readbacks served every recovery; one prompt POST.
    assert harness.comfy.upload_posts == 4
    assert len(harness.comfy.view_gets) >= 4
    assert harness.comfy.prompt_posts == 1
    assert sum(1 for method, _ in harness.runpod.calls if method == "POST") == 1


def test_at17b_unverifiable_readback_blocks_every_dependent_sample(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from microdrama.rendering.benchmark_experiments import blocking, unresolved_items

    harness = _at17_compose(db, tmp_path, monkeypatch, corrupt_readback=True)
    plan = harness.plan
    first = harness.service.execute(
        plan.experiment_id,
        phase="screen",
        authorization=harness.authorization,
        quote=harness.quote,
        expected_sha256=harness.authorization.authorization_sha256,
    )
    acquisition_id = first["acquisitions"][0]["acquisition_id"]

    # The readback cannot verify: U3u stays open and blocks every dependent
    # sample (acquisition-scoped), across repeated fresh-process resumes.
    for _ in range(3):
        status = harness.service.resume(
            plan.experiment_id,
            authorization=harness.authorization,
            quote=harness.quote,
            expected_sha256=harness.authorization.authorization_sha256,
            phase="screen",
        )
        harness.clock.advance(seconds=1)
    assert status["execution_state"] == "NEEDS_RECONCILIATION"
    blockers = status["admission"]["blockers"]
    assert any("U3u" in blocker for blocker in blockers), blockers
    with db.transaction(readonly=True) as tx:
        rows = tx.fetchall(
            "SELECT state FROM benchmark_uploads WHERE acquisition_id=%s", (acquisition_id,)
        )
        operations = tx.fetchall(
            "SELECT o.id FROM provider_operations o JOIN benchmark_samples s "
            "ON s.reservation_id=o.reservation_id WHERE s.experiment_id=%s",
            (plan.experiment_id,),
        )
        items = unresolved_items(tx, plan.experiment_id, now=harness.clock.now())
    assert rows and all(row["state"] == "UNKNOWN" for row in rows)
    assert operations == []  # no prompt was dispatched while blocked
    assert any(item.kind == "U3u" for item in blocking(items, "claims"))
    # Never a second upload POST for the open intent (I1).
    assert harness.comfy.upload_posts == 1
    assert harness.comfy.prompt_posts == 0


def test_at17d_expired_hold_input_readback_allowed_in_recovery_r4(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from microdrama.budget import BudgetService

    harness = _at17_compose(db, tmp_path, monkeypatch)
    plan = harness.plan
    first = harness.service.execute(
        plan.experiment_id,
        phase="screen",
        authorization=harness.authorization,
        quote=harness.quote,
        expected_sha256=harness.authorization.authorization_sha256,
    )
    acquisition_id = first["acquisitions"][0]["acquisition_id"]
    with db.transaction(readonly=True) as tx:
        reservation_id = tx.fetchval(
            "SELECT s.reservation_id FROM benchmark_samples s WHERE s.experiment_id=%s "
            "AND s.sample_id='S01-R1'",
            (plan.experiment_id,),
        )

    # AT-20's extension: expire_stale() moves the sample's hold to EXPIRED
    # with exposure retained while the upload intent is still open and NO
    # prompt operation exists.
    harness.clock.advance(seconds=601)
    BudgetService(harness.db, harness.clock, harness.ids, harness.settings).expire_stale()
    with db.transaction(readonly=True) as tx:
        state = tx.fetchval("SELECT state FROM reservations WHERE id=%s", (reservation_id,))
    assert state == "EXPIRED"

    # §3.3/R4: the input readback is authorised in RECOVERY through the
    # durable upload-intent linkage (experiment/acquisition/reservation/job/pod
    # + intent), with no prompt operation to link through.
    uploads_before = harness.comfy.upload_posts
    status = harness.service.reconcile(plan.experiment_id)
    with db.transaction(readonly=True) as tx:
        rows = tx.fetchall(
            "SELECT state, verified_readback_sha256 FROM benchmark_uploads WHERE acquisition_id=%s",
            (acquisition_id,),
        )
    assert rows and all(row["state"] == "VERIFIED" for row in rows)
    assert all(row["verified_readback_sha256"] for row in rows)
    assert harness.comfy.upload_posts == uploads_before  # never a second POST
    assert harness.comfy.prompt_posts == 0  # no prompt operation appeared
    assert status["execution_state"] != "NEEDS_RECONCILIATION"


def test_at17e_wrong_owner_and_wrong_mode_refusals(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from microdrama.contracts.errors import EffectDenied
    from microdrama.contracts.hashing import sha256_hex
    from microdrama.rendering.benchmark_experiments import ExperimentBudgetService
    from microdrama.rendering.pika_transport import upload_key_for

    harness = _at17_compose(db, tmp_path, monkeypatch)
    plan = harness.plan
    first = harness.service.execute(
        plan.experiment_id,
        phase="screen",
        authorization=harness.authorization,
        quote=harness.quote,
        expected_sha256=harness.authorization.authorization_sha256,
    )
    acquisition_id = first["acquisitions"][0]["acquisition_id"]
    with db.transaction(readonly=True) as tx:
        sample = tx.fetchone(
            "SELECT * FROM benchmark_samples WHERE experiment_id=%s AND sample_id='S01-R1'",
            (plan.experiment_id,),
        )
    digest = sha256_hex(harness.payloads["character_identity"])
    key = upload_key_for(plan.experiment_id, acquisition_id, digest, "image")

    def world_budget():
        return ExperimentBudgetService(
            db, harness.clock, harness.ids, harness.settings, experiment_id=plan.experiment_id
        )

    execute_client = harness.factory(
        experiment_id=plan.experiment_id,
        budget=world_budget(),
        authorization=harness.authorization,
        quote=harness.quote,
    ).comfy._client
    execute_client.bind_pod_endpoint("pod-at17-1", "https://pod-at17-1-8188.proxy.runpod.net")
    # Wrong owner: a scope naming a foreign job never reaches the transport.
    with execute_client.authorization_scope(
        reservation_id=sample["reservation_id"],
        episode_id=plan.episode_id,
        job_id=UUID(int=999999),
        operation_id=None,
    ):
        with pytest.raises(EffectDenied):
            execute_client.reconcile_input(expected_sha256=digest, upload_key=key)
    posts_before = harness.comfy.upload_posts

    # Wrong mode: a RECOVERY world never uploads and never dispatches prompts,
    # even scoped exactly like the original send (I5).
    recovery = harness.factory(
        experiment_id=plan.experiment_id,
        budget=world_budget(),
        authorization=None,
        quote=None,
        mode="RECOVERY",
        acquisition_id=acquisition_id,
    )
    recovery_client = recovery.comfy._client
    recovery_client.bind_pod_endpoint("pod-at17-1", "https://pod-at17-1-8188.proxy.runpod.net")
    with recovery_client.authorization_scope(
        reservation_id=sample["reservation_id"],
        episode_id=plan.episode_id,
        job_id=sample["job_id"],
        operation_id=None,
    ):
        with pytest.raises(EffectDenied, match="recovery world cannot upload"):
            recovery_client.upload_input(
                harness.payloads["character_identity"], "image", digest, key
            )
        with pytest.raises(EffectDenied):
            recovery_client.queue_prompt(_valid_fake_graph(), client_id="at17e")
    assert harness.comfy.upload_posts == posts_before
    assert harness.comfy.prompt_posts == 0


# ---------------------------------------------------------------------------
# HB-2 (Codex P1-P3 review): fresh UNKNOWN recovery binds its client first.
# ---------------------------------------------------------------------------


def test_hb2_at1_unknown_prompt_recovery_binds_the_fresh_client_first(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """HB-2: a fresh recovery world's client is UNBOUND; the UNKNOWN lookup
    ran before any binding, its first authenticated call refused with
    EffectDenied and the tolerant handler swallowed it - the ACCEPTED prompt
    stayed unrecovered forever. AT-1 through a real fresh client: recovery
    binds the acquisition's durable pod (§3.4) BEFORE the client-id lookup,
    adopts the accepted prompt, persists its output and continues the run -
    with zero resubmits."""
    harness = _at17_compose(db, tmp_path, monkeypatch, upload_timeout=False, prompt_timeouts=1)
    plan = harness.plan

    first = harness.service.execute(
        plan.experiment_id,
        phase="screen",
        authorization=harness.authorization,
        quote=harness.quote,
        expected_sha256=harness.authorization.authorization_sha256,
    )
    # The prompt POST was accepted then lost: submit ambiguity (§5.1), the
    # acquisition stays ACTIVE, the operation is UNKNOWN with no external id.
    assert first["execution_state"] == "NEEDS_RECONCILIATION"
    assert first["acquisitions"][0]["state"] == "ACTIVE"
    with db.transaction(readonly=True) as tx:
        operation = tx.fetchone(
            "SELECT o.id, o.state, o.external_id FROM provider_operations o "
            "JOIN benchmark_samples s ON s.reservation_id=o.reservation_id "
            "WHERE s.experiment_id=%s",
            (plan.experiment_id,),
        )
    assert operation is not None and operation["state"] == "UNKNOWN"
    assert operation["external_id"] is None
    assert harness.comfy.prompt_posts == 1  # the accepted-then-lost POST
    assert harness.comfy.upload_posts == 4  # every port uploaded once

    # A FRESH process recovers through a fresh client over the same server.
    fresh = type(harness.service)(
        db, harness.settings, clock=harness.clock, ids=harness.ids, world_factory=harness.factory
    )
    recovered = fresh.resume(
        plan.experiment_id,
        authorization=harness.authorization,
        quote=harness.quote,
        expected_sha256=harness.authorization.authorization_sha256,
        phase="screen",
    )
    assert recovered["execution_state"] != "NEEDS_RECONCILIATION", recovered["execution_state"]
    states = {s["sample_id"]: s["state"] for s in recovered["samples"]}
    assert states["S01-R1"] == "SUCCEEDED"
    with db.transaction(readonly=True) as tx:
        after = tx.fetchone(
            "SELECT o.state, o.external_id FROM provider_operations o "
            "JOIN benchmark_samples s ON s.reservation_id=o.reservation_id "
            "WHERE s.experiment_id=%s AND s.sample_id='S01-R1'",
            (plan.experiment_id,),
        )
        sample = tx.fetchone(
            "SELECT output FROM benchmark_samples WHERE experiment_id=%s AND sample_id='S01-R1'",
            (plan.experiment_id,),
        )
    assert after["state"] == "SUCCEEDED"
    assert after["external_id"] == "at17-prompt-0001"  # adopted by client id
    assert sample["output"] and sample["output"]["sha256"]  # output persisted

    # The same resume continued the run: the NEXT screen sample dispatched
    # with a new prompt POST. Zero resubmit: S01's recovered operation is the
    # server's FIRST prompt (adopted by client id, never re-POSTed) and the
    # new POST belongs to a different sample's new operation.
    assert harness.comfy.prompt_posts == 2
    with db.transaction(readonly=True) as tx:
        operations = tx.fetchall(
            "SELECT s.sample_id, o.external_id FROM provider_operations o "
            "JOIN benchmark_samples s ON s.reservation_id=o.reservation_id "
            "WHERE s.experiment_id=%s ORDER BY s.sample_id",
            (plan.experiment_id,),
        )
    by_sample = {row["sample_id"]: row["external_id"] for row in operations}
    assert by_sample["S01-R1"] == "at17-prompt-0001"
    assert by_sample["S03-R1"] == "at17-prompt-0002"


def _hb2_seed_pending_submit(harness, *, accepted: bool) -> None:
    """The durable shape of a worker death between begin() and the prompt
    POST's result commit, on the composed world: the first sample is claimed
    with its job and hold, the dispatch slot holds it, and a PENDING_SUBMIT
    operation row exists whose submit result was never observed. The compose
    stops at the upload ambiguity (no operation row yet), so the seed inserts
    the operation against the REAL job and reservation. ``accepted`` also
    lands the POST server-side under the deterministic client id (§5.2 (b))."""
    import uuid as _uuid
    from datetime import timedelta

    from microdrama.rendering.comfy_jobs import render_client_id, render_client_token

    plan = harness.plan
    first = harness.service.execute(
        plan.experiment_id,
        phase="screen",
        authorization=harness.authorization,
        quote=harness.quote,
        expected_sha256=harness.authorization.authorization_sha256,
    )
    assert first["execution_state"] == "NEEDS_RECONCILIATION"  # upload ambiguity
    with harness.db.transaction(readonly=True) as tx:
        sample = tx.fetchone(
            "SELECT * FROM benchmark_samples WHERE experiment_id=%s AND sample_id='S01-R1'",
            (plan.experiment_id,),
        )
    assert sample["job_id"] is not None and sample["reservation_id"] is not None
    key = f"benchmark:{plan.experiment_id}:sample:S01-R1:a1"
    if accepted:
        harness.server.accept_prompt(render_client_id(key))
    with harness.db.transaction() as tx:
        provider = tx.fetchval(
            "SELECT provider FROM reservations WHERE id=%s", (sample["reservation_id"],)
        )
        tx.execute(
            "INSERT INTO provider_operations(id,provider,operation_kind,client_token,"
            "request_hash,job_id,reservation_id,state,external_id,deadline_at) "
            "VALUES(%s,%s,'comfy.queue_prompt',%s,%s,%s,%s,'PENDING_SUBMIT',NULL,%s)",
            (
                _uuid.uuid4(),
                provider,
                render_client_token(key),
                "3" * 64,
                sample["job_id"],
                sample["reservation_id"],
                harness.clock.now() + timedelta(hours=1),
            ),
        )
        tx.execute(
            "UPDATE benchmark_samples SET operation_id=(SELECT id FROM provider_operations "
            "WHERE reservation_id=%s) WHERE experiment_id=%s AND sample_id='S01-R1'",
            (sample["reservation_id"], plan.experiment_id),
        )


def test_hb2_at15_pending_submit_takeover_through_a_fresh_real_client(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """HB-2 + §5.2 (AT-15 b) through a real fresh client: the worker died
    between begin() and the POST's result commit, and the POST DID land. The
    takeover (coordinator token expired) moves PENDING_SUBMIT to UNKNOWN,
    binds the fresh client to the durable pod FIRST (HB-2), adopts the prompt
    by its deterministic client id and persists the output - never resubmits."""
    harness = _at17_compose(db, tmp_path, monkeypatch, upload_timeout=True)
    _hb2_seed_pending_submit(harness, accepted=True)
    plan = harness.plan
    posts_before = harness.comfy.prompt_posts
    assert posts_before == 1  # the worker's accepted POST

    # The coordinator token expired with the dead process (its lease lapsed
    # while the funded window still lives): takeover.
    with db.transaction() as tx:
        tx.execute(
            "UPDATE benchmark_dispatch_slots SET coordinator_lease_until=%s - interval '1 second' "
            "WHERE experiment_id=%s",
            (harness.clock.now(), plan.experiment_id),
        )
    fresh = type(harness.service)(
        db, harness.settings, clock=harness.clock, ids=harness.ids, world_factory=harness.factory
    )
    takeover = fresh.reconcile(plan.experiment_id)
    with db.transaction(readonly=True) as tx:
        after = tx.fetchone(
            "SELECT o.state, o.external_id FROM provider_operations o "
            "JOIN benchmark_samples s ON s.reservation_id=o.reservation_id "
            "WHERE s.experiment_id=%s AND s.sample_id='S01-R1'",
            (plan.experiment_id,),
        )
    assert after["state"] == "SUCCEEDED"  # UNKNOWN -> adopted by client id
    assert after["external_id"] == "at17-prompt-0001"
    assert takeover["execution_state"] != "NEEDS_RECONCILIATION"
    # Never resubmitted: the takeover sent nothing (HB-2's bound lookup only reads).
    assert harness.comfy.prompt_posts == posts_before


def test_hb2_at15a_invisible_prompt_stays_unknown_with_a_fresh_real_client(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """HB-2 + §5.2 (AT-15 a): identical durable PENDING_SUBMIT takeover, but
    the server holds NO prompt for the deterministic client id - the outcome
    stays UNKNOWN (a miss never proves "not sent", I2) with its exposure,
    blocking admission; nothing is adopted and nothing re-POSTed."""
    harness = _at17_compose(db, tmp_path, monkeypatch, upload_timeout=True)
    _hb2_seed_pending_submit(harness, accepted=False)
    plan = harness.plan
    posts_before = harness.comfy.prompt_posts
    assert posts_before == 0  # the POST never left the dead worker

    with db.transaction() as tx:
        tx.execute(
            "UPDATE benchmark_dispatch_slots SET coordinator_lease_until=%s - interval '1 second' "
            "WHERE experiment_id=%s",
            (harness.clock.now(), plan.experiment_id),
        )
    fresh = type(harness.service)(
        db, harness.settings, clock=harness.clock, ids=harness.ids, world_factory=harness.factory
    )
    status = fresh.reconcile(plan.experiment_id)
    with db.transaction(readonly=True) as tx:
        after = tx.fetchone(
            "SELECT o.state FROM provider_operations o "
            "JOIN benchmark_samples s ON s.reservation_id=o.reservation_id "
            "WHERE s.experiment_id=%s AND s.sample_id='S01-R1'",
            (plan.experiment_id,),
        )
    assert after["state"] == "UNKNOWN"
    assert status["execution_state"] == "NEEDS_RECONCILIATION"
    assert harness.comfy.prompt_posts == posts_before  # nothing re-POSTed


def test_hb2_bind_for_recovery_binds_only_a_running_pod(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """HB-2 (§3.4 predicate): BOUND requires a RUNNING pod with an endpoint -
    an endpoint-bearing pod that is no longer running is INDETERMINATE, not
    BOUND (its server state is not reachable through it)."""
    harness = _at17_compose(db, tmp_path, monkeypatch, upload_timeout=False)
    plan = harness.plan
    first = harness.service.execute(
        plan.experiment_id,
        phase="screen",
        authorization=harness.authorization,
        quote=harness.quote,
        expected_sha256=harness.authorization.authorization_sha256,
    )
    acquisition_id = first["acquisitions"][0]["acquisition_id"]

    from microdrama.rendering.benchmark_experiments import ExperimentBudgetService

    def world_budget():
        return ExperimentBudgetService(
            harness.db,
            harness.clock,
            harness.ids,
            harness.settings,
            experiment_id=plan.experiment_id,
        )

    world = harness.factory(
        experiment_id=plan.experiment_id,
        budget=world_budget(),
        authorization=None,
        quote=None,
        mode="RECOVERY",
        acquisition_id=acquisition_id,
    )
    assert world.bind_for_recovery(acquisition_id) == "BOUND"

    # The pod stopped but keeps its recorded endpoint: never BOUND.
    harness.runpod.pod["status"] = "STOPPED"
    assert world.bind_for_recovery(acquisition_id) == "INDETERMINATE"


# ---------------------------------------------------------------------------
# HB-3 (Codex P1-P3 review): recovery provenance is acquisition-owned.
# ---------------------------------------------------------------------------


def test_hb3_recovery_provenance_is_acquisition_owned(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """HB-3 (§3.2): RECOVERY/CLEANUP provenance is the acquisition's OWN
    durable record, verified from its stored bytes. Caller-supplied
    new-generation documents never replace it (a later authorization under a
    different namespace would compose the wrong ownership scope and fail
    every check), 'latest by timestamp' is never selected, and an experiment
    WITH acquisitions must name the acquisition it touches."""
    import json as _json

    from microdrama.contracts.errors import Conflict
    from microdrama.persistence.db import jsonb as _jsonb
    from microdrama.pipeline.benchmark_authorization import (
        canonical_document_bytes,
        document_sha256,
    )
    from microdrama.rendering.benchmark_experiments import ExperimentBudgetService

    harness = _at17_compose(db, tmp_path, monkeypatch, upload_timeout=False, prompt_timeouts=1)
    plan = harness.plan
    first = harness.service.execute(
        plan.experiment_id,
        phase="screen",
        authorization=harness.authorization,
        quote=harness.quote,
        expected_sha256=harness.authorization.authorization_sha256,
    )
    acquisition_id = first["acquisitions"][0]["acquisition_id"]

    # A SECOND authorization, recorded LATER under a DIFFERENT namespace -
    # identity-legal for this seal/plan, but not this acquisition's record.
    second = harness.authorization.model_copy(
        update={"change_ref": "at17-hb3-later", "namespace": "benchyhb3"}
    )
    raw2 = canonical_document_bytes(second)
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO benchmark_authorizations(experiment_id,authorization_sha256,"
            "payload,source_bytes,authorized_at) VALUES(%s,%s,%s,%s,%s)",
            (
                plan.experiment_id,
                document_sha256(second),
                _jsonb(_json.loads(raw2.decode("utf-8"))),
                raw2,
                harness.clock.now(),
            ),
        )

    def world_budget():
        return ExperimentBudgetService(
            db, harness.clock, harness.ids, harness.settings, experiment_id=plan.experiment_id
        )

    # Supplied new-generation arguments must NOT replace the acquisition's
    # own provenance: the world composes from the durable record - the
    # original namespace/change_ref, never the later benchyhb3 document.
    world = harness.factory(
        experiment_id=plan.experiment_id,
        budget=world_budget(),
        authorization=second,  # the WRONG, later authorization
        quote=harness.quote,
        mode="RECOVERY",
        acquisition_id=acquisition_id,
    )
    assert world.authorization.namespace == harness.authorization.namespace
    assert world.authorization.change_ref == harness.authorization.change_ref

    # And "latest by timestamp" is never selected: an experiment WITH
    # acquisitions refuses an acquisition-less recovery world outright - the
    # caller names the acquisition whose records it recovers (§3.2).
    with pytest.raises(Conflict):
        harness.factory(
            experiment_id=plan.experiment_id,
            budget=world_budget(),
            authorization=None,
            quote=None,
            mode="RECOVERY",
        )


def test_hb4_historical_grace_deadline_never_bounds_healthy_work(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """HB-4/SC2-2: a successfully recovered episode's HISTORICAL deadline
    never bounds later healthy work. After the deadline passes, a healthy
    SUBMITTED poll through a fresh resume must proceed (the scripted
    transport honors the production request-deadline context and refuses
    past-deadline requests, like UrllibTransport); before the fix the refused
    poll was swallowed, U3p stayed in flight forever and admission was
    blocked with no deadline cleanup owed."""
    harness = _at17_compose(db, tmp_path, monkeypatch, upload_timeout=False, prompt_timeouts=1)
    plan = harness.plan
    first = harness.service.execute(
        plan.experiment_id,
        phase="screen",
        authorization=harness.authorization,
        quote=harness.quote,
        expected_sha256=harness.authorization.authorization_sha256,
    )
    acquisition_id = first["acquisitions"][0]["acquisition_id"]

    # Recover the first episode INSIDE its grace; the same resume continues
    # the run and dispatches the next sample (healthy SUBMITTED).
    fresh = type(harness.service)(
        db, harness.settings, clock=harness.clock, ids=harness.ids, world_factory=harness.factory
    )
    recovered = fresh.resume(
        plan.experiment_id,
        authorization=harness.authorization,
        quote=harness.quote,
        expected_sha256=harness.authorization.authorization_sha256,
        phase="screen",
    )
    states = {s["sample_id"]: s["state"] for s in recovered["samples"]}
    assert states["S01-R1"] == "SUCCEEDED"  # the episode recovered in grace
    with db.transaction(readonly=True) as tx:
        deadline = tx.fetchval(
            "SELECT recovery_deadline FROM benchmark_acquisitions WHERE acquisition_id=%s",
            (acquisition_id,),
        )
        in_flight = tx.fetchone(
            "SELECT o.state FROM provider_operations o JOIN benchmark_samples s "
            "ON s.reservation_id=o.reservation_id WHERE s.experiment_id=%s "
            "AND s.sample_id='S03-R1'",
            (plan.experiment_id,),
        )
    assert deadline is not None  # the episode's deadline persists (SC2-2 keeps it)
    assert in_flight["state"] == "SUBMITTED"  # healthy later work exists

    # The historical deadline passes; fresh resumes keep polling S03.
    harness.clock.advance(seconds=(deadline - harness.clock.now()).total_seconds() + 60)
    final = None
    for _ in range(4):
        final = fresh.resume(
            plan.experiment_id,
            authorization=harness.authorization,
            quote=harness.quote,
            expected_sha256=harness.authorization.authorization_sha256,
            phase="screen",
        )
        harness.clock.advance(seconds=1)
        with db.transaction(readonly=True) as tx:
            s03 = tx.fetchone(
                "SELECT state FROM benchmark_samples WHERE experiment_id=%s AND sample_id='S03-R1'",
                (plan.experiment_id,),
            )
        if s03["state"] == "SUCCEEDED":
            break
    assert s03["state"] == "SUCCEEDED"  # the historical deadline never stalled it
    assert final["execution_state"] in ("SCREEN_RUNNING", "SCREEN_REVIEW")


def test_hb5_takeover_discovered_ambiguity_persists_grace_and_cleanup_starts(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """HB-5: a worker that died before its dispatch-time handler left a
    PENDING_SUBMIT with NO deadline. The takeover must enter the SAME durable
    classification and grace (§5.1/§5.4) before recovery proceeds, and once
    the persisted deadline is exhausted with the ambiguity unresolved,
    reconcile starts the R3 fence + cleanup despite every intermediate read
    failing (the op keeps UNKNOWN with its exposure, I4)."""
    harness = _at17_compose(db, tmp_path, monkeypatch, upload_timeout=True)
    _hb2_seed_pending_submit(harness, accepted=False)
    plan = harness.plan
    acquisition_id = None
    with db.transaction(readonly=True) as tx:
        acquisition_id = tx.fetchval(
            "SELECT acquisition_id FROM benchmark_acquisitions WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
        lease_id = tx.fetchval(
            "SELECT lease_id FROM benchmark_acquisitions WHERE acquisition_id=%s",
            (acquisition_id,),
        )
    assert harness.comfy.prompt_posts == 0  # the POST never left the dead worker

    # The coordinator token expired (in-window: the funded window still
    # lives); the takeover discovers the ambiguity.
    with db.transaction() as tx:
        tx.execute(
            "UPDATE benchmark_dispatch_slots SET coordinator_lease_until=%s - interval '1 second' "
            "WHERE experiment_id=%s",
            (harness.clock.now(), plan.experiment_id),
        )
    fresh = type(harness.service)(
        db, harness.settings, clock=harness.clock, ids=harness.ids, world_factory=harness.factory
    )
    takeover = fresh.reconcile(plan.experiment_id)
    with db.transaction(readonly=True) as tx:
        after = tx.fetchone(
            "SELECT o.state, o.external_id FROM provider_operations o "
            "JOIN benchmark_samples s ON s.reservation_id=o.reservation_id "
            "WHERE s.experiment_id=%s AND s.sample_id='S01-R1'",
            (plan.experiment_id,),
        )
        grace = tx.fetchone(
            "SELECT recovery_started_at, recovery_deadline FROM benchmark_acquisitions "
            "WHERE acquisition_id=%s",
            (acquisition_id,),
        )
    assert after["state"] == "UNKNOWN"
    # HB-5 red line: the durable grace EXISTS from the takeover on - before
    # the fix no deadline was ever persisted for a crash-before-handler.
    assert grace["recovery_started_at"] is not None
    assert grace["recovery_deadline"] is not None
    assert takeover["execution_state"] == "NEEDS_RECONCILIATION"
    assert harness.comfy.prompt_posts == 0  # still nothing re-POSTed

    # The deadline is already exhausted at this clock (the compute hold's
    # funded window passed while the worker was dead): reconcile routes the
    # owed U2 to the sweep - the R3 fence revokes the tokens and cleanup
    # starts despite the failed reads, while the operation keeps UNKNOWN with
    # its exposure retained (I4 - only an audited resolution closes it).
    deadline = grace["recovery_deadline"]
    if harness.clock.now() < deadline:
        harness.clock.advance(seconds=(deadline - harness.clock.now()).total_seconds() + 1)
    fenced = fresh.reconcile(plan.experiment_id)
    with db.transaction(readonly=True) as tx:
        slot_token = tx.fetchval(
            "SELECT coordinator_token FROM benchmark_dispatch_slots WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
        lease = tx.fetchone(
            "SELECT stop_verified_at, terminate_verified_at FROM pod_leases WHERE id=%s",
            (lease_id,),
        )
        final_op = tx.fetchone(
            "SELECT o.state FROM provider_operations o JOIN benchmark_samples s "
            "ON s.reservation_id=o.reservation_id WHERE s.experiment_id=%s "
            "AND s.sample_id='S01-R1'",
            (plan.experiment_id,),
        )
    assert slot_token is None  # the R3 fence revoked the coordinator token
    assert (
        lease["stop_verified_at"] is not None or lease["terminate_verified_at"] is not None
    )  # cleanup STARTED at the deadline
    assert final_op["state"] == "UNKNOWN"  # exposure retained, never resolved by cleanup
    assert fenced["execution_state"] == "NEEDS_RECONCILIATION"
    assert harness.comfy.prompt_posts == 0  # nothing re-POSTed through it all
