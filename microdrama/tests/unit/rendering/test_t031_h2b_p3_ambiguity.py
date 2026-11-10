"""T031 H-2 build, package P3: ambiguity at run time (spec v3 §5).

AT-1, AT-15, AT-16, AT-25 and the §5.1 classification first (create vs upload
vs submit/poll ambiguity label exactly what §5.1 says); the grace/deadline ATs
(AT-2/AT-3/AT-17..AT-19) follow in this package. Public entry points only.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

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
