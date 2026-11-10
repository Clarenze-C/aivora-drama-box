"""T031 H-2 build, package P2: unresolved items and the admission gate (spec v3 §4).

AT-0, AT-5, AT-10, AT-11, AT-13, AT-14 (plus the §9.3 extensions for AT-0/AT-10).
Every test drives public entry points (service execute/resume/reconcile/resolve_create
and the CLI ``main``) — the single documented exception is AT-10, which calls the
private admission helpers ``_acquisition``/``_claim_sample`` deliberately. AT-13 runs
its worker in a real subprocess killed with ``os._exit`` (§9.3 death harness): the
durable state and the parent's send counters survive the killed process.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from rendering_support import RenderWorld
from test_benchmark_experiments import _composed_world, _OfflineFinalityWorld
from test_t031_h2b_p1_modes import (
    _authorization_pair,
    _drive_resume,
    _execute_service,
    _paid_settings,
    _PatchedPolicy,
    _screen_quote,
)

from microdrama.contracts.cost import BudgetReservationRequest
from microdrama.persistence import Database
from microdrama.persistence.db import jsonb
from microdrama.pipeline.benchmark_service import BenchmarkService

pytestmark = pytest.mark.db

RENDERING_TESTS = Path(__file__).parent
UNIT_TESTS = RENDERING_TESTS.parent
SRC_ROOT = RENDERING_TESTS.parents[2] / "src"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _bench_seal_for(plan):
    from test_t031_h2b_p1_modes import _bench_seal

    return _bench_seal(plan)


def _item_kinds(db: Database, experiment_id: UUID, clock) -> list[str]:
    """The unresolved-item kinds the repository derives, via its public function."""
    from microdrama.rendering.benchmark_experiments import unresolved_items

    with db.transaction(readonly=True) as tx:
        return sorted({item.kind for item in unresolved_items(tx, experiment_id, now=clock.now())})


class _UnfinalOfflineWorld(_OfflineFinalityWorld):
    """Offline cleanup fixture whose finality is a knob (AT-5 phase B)."""

    final = False

    def cleanup(self, acquisition):
        receipt = super().cleanup(acquisition)
        if not self.final:
            return {
                **receipt,
                "verified": False,
                "billing_state": "PENDING_PROVIDER_FINALITY",
                "storage_final": False,
            }
        return receipt


def _lease_with_live_pod(db, world: RenderWorld, episode_id: UUID) -> str:
    """A canonical lease with a real (fake) bound pod through the public lease API."""
    from microdrama.rendering.leases import PodLeaseClaimRequest

    request = PodLeaseClaimRequest(
        episode_id=episode_id,
        semantic_key=f"benchmark-seed:{uuid4().hex[:8]}",
        gpu_type=world.config.allowed_gpu_types[0],
        host_ram_gb=world.config.min_host_ram_gb,
    )
    reservation, _ = world.leases._reserve_for_lease(request, world.config.lease_ttl_ms)
    handle = world.leases.claim_pre_reserved(request, reservation.id)
    world.leases.ensure_pod(handle.lease.lease_id)  # creates, binds and activates
    return handle.lease.lease_id


def _crash_seed_lease(db, world: RenderWorld, episode_id: UUID, *, create_requested: bool) -> str:
    """A podless CLAIMED lease, optionally carrying a committed create intent."""
    from microdrama.rendering.leases import PodLeaseClaimRequest

    request = PodLeaseClaimRequest(
        episode_id=episode_id,
        semantic_key=f"benchmark-seed:{uuid4().hex[:8]}",
        gpu_type=world.config.allowed_gpu_types[0],
        host_ram_gb=world.config.min_host_ram_gb,
    )
    reservation, _ = world.leases._reserve_for_lease(request, world.config.lease_ttl_ms)
    handle = world.leases.claim_pre_reserved(request, reservation.id)
    if create_requested:
        with db.transaction() as tx:
            tx.execute(
                "UPDATE pod_leases SET create_requested_at=%s WHERE id=%s",
                (world.clock.now(), handle.lease.lease_id),
            )
    return handle.lease.lease_id


def _insert_acquisition(
    db, world, adapter, plan, *, generation: int, state: str, lease_id=None, clock=None
) -> UUID:
    """A durable acquisition row with the world's own intent document."""
    acquisition_id = uuid5_seed(plan.experiment_id, generation)
    quote = _screen_quote(world)
    now = (clock or world.clock).now()
    with db.transaction(readonly=True) as tx:
        exp = tx.fetchone(
            "SELECT * FROM benchmark_experiments WHERE experiment_id=%s", (plan.experiment_id,)
        )
    intent = adapter.acquisition_requests(exp, quote, acquisition_id, generation, now)
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO benchmark_acquisitions(acquisition_id,experiment_id,generation,quote,"
            "quote_sha256,intent,state,create_intent_at,lease_id,authorization_sha256) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                acquisition_id,
                plan.experiment_id,
                generation,
                jsonb(quote),
                "1" * 64,
                jsonb(intent),
                state,
                now,
                lease_id,
                "2" * 64,
            ),
        )
    return acquisition_id


def uuid5_seed(experiment_id: UUID, generation: int) -> UUID:
    from uuid import uuid5

    from microdrama.rendering.leases import RENDERING_NAMESPACE

    return uuid5(RENDERING_NAMESPACE, f"benchmark:{experiment_id}:acq:{generation}")


def _prompt_hold_request(world: RenderWorld, episode_id: UUID, plan, sample_id: str, clock):
    from microdrama.rendering.leases import mock_pod_price

    price = mock_pod_price().model_copy(update={"unit_price_micro_usd": 1})
    return BudgetReservationRequest(
        request_id=uuid4(),
        semantic_key=f"benchmark:{plan.experiment_id}:sample:{sample_id}:a1",
        scope_kind="EPISODE",
        episode_id=episode_id,
        season_id=None,
        category="GPU_GENERATION",
        queue="production",
        provider="fake-runpod",
        operation_kind="comfy.queue_prompt",
        price=price,
        ceilings={"timeout_ms": 600000, "max_units": 1},
        worst_case_micro_usd=600000,
        expires_at=clock.now() + timedelta(hours=1),
        is_shutdown_or_cleanup=False,
    )


def _seed_sample_operation(
    db, plan, sample_id, state, clock, comfy=None, *, reservation_id=None, slot=False
):
    """A sample linked to a provider operation in ``state`` (via the reservation)."""
    operation_id = uuid4()
    with db.transaction() as tx:
        from microdrama.contracts.cost import RenderRequest
        from microdrama.rendering.comfy_jobs import render_id_for

        key = f"benchmark:{plan.experiment_id}:sample:{sample_id}:a1"
        job = comfy.jobs.enqueue(
            tx,
            job_type="render.shot",
            semantic_key=key,
            payload=RenderRequest(
                render_id=render_id_for(key),
                semantic_key=key,
                episode_id=plan.episode_id,
                episode_number=1,
                shot_id=f"bench-{sample_id.lower()}",
                manifest_version=1,
                attempt_number=1,
                preset_id="fake-quality-8step",
                tier="quality_eight_step",
                required_controls=["TEXT_PROMPT"],
                reference_asset_ids=[],
                workflow_sha256="9" * 64,
                seed=1,
                width=720,
                height=1280,
                fps=24,
                duration_ms=4000,
                reservation_id=reservation_id,
                prompt_text="Offline synthetic fixture.",
            ),
            max_attempts=1,
        )
        tx.execute(
            "INSERT INTO provider_operations(id,provider,operation_kind,client_token,request_hash,"
            "job_id,reservation_id,state,deadline_at) "
            "VALUES(%s,'fake-runpod','comfy.queue_prompt',%s,%s,%s,%s,%s,%s)",
            (
                operation_id,
                f"seed-{operation_id.hex[:12]}",
                "3" * 64,
                job.job_id,
                reservation_id,
                state,
                clock.now() + timedelta(hours=1),
            ),
        )
        if reservation_id is not None:
            tx.execute(
                "UPDATE benchmark_samples SET state='CLAIMED',reservation_id=%s "
                "WHERE experiment_id=%s AND sample_id=%s",
                (reservation_id, plan.experiment_id, sample_id),
            )
        if slot:
            tx.execute(
                "UPDATE benchmark_dispatch_slots SET sample_id=%s,revision=revision+1 "
                "WHERE experiment_id=%s",
                (sample_id, plan.experiment_id),
            )
    return operation_id


def _seed_claim(db, adapter, world, plan, acquisition: dict, sample_id: str) -> None:
    """Reproduce exactly ``_claim_sample``'s durable footprint through public pieces.

    A prompt hold through the canonical ``reserve_linked``, the immutable request
    through the world's own factory, the sample CLAIMED and the dispatch slot
    occupied — the §F "claim and hold committed" crash state.
    """
    with db.transaction(readonly=True) as tx:
        exp = tx.fetchone(
            "SELECT * FROM benchmark_experiments WHERE experiment_id=%s", (plan.experiment_id,)
        )
        sample = tx.fetchone(
            "SELECT * FROM benchmark_samples WHERE experiment_id=%s AND sample_id=%s",
            (plan.experiment_id, sample_id),
        )
    with db.transaction() as tx:
        reservation = adapter.budget.reserve_linked(
            tx,
            adapter.prompt_reservation(exp, sample),
            acquisition_id=acquisition["acquisition_id"],
            sample_id=sample_id,
            purpose="PROMPT",
        )
        request = adapter.request(sample, acquisition, reservation.id)
        tx.execute(
            "UPDATE benchmark_samples SET state='CLAIMED',reservation_id=%s,acquisition_id=%s,"
            "request=%s WHERE experiment_id=%s AND sample_id=%s",
            (
                reservation.id,
                acquisition["acquisition_id"],
                jsonb(request.model_dump(mode="json")),
                plan.experiment_id,
                sample_id,
            ),
        )
        tx.execute(
            "UPDATE benchmark_dispatch_slots SET sample_id=%s,revision=revision+1 "
            "WHERE experiment_id=%s",
            (sample_id, plan.experiment_id),
        )


def _record_pass(service, plan, state) -> None:
    sealed = service.status(plan.experiment_id)["seal"]["sealed_sha256"]
    service.record_screening(
        plan.experiment_id,
        {
            "sealed_sha256": sealed,
            "actor_ref": "offline-test-human",
            "output_hashes": {
                s["sample_id"]: s["output"]["sha256"]
                for s in state["samples"]
                if s["sample_id"] in ("S01-R1", "S03-R1", "S07-R1")
            },
            "decision": "PASS",
            "coverage": {"fixture-critical": "PASS"},
            "rubric_version": "offline-fixture",
        },
    )


# ---------------------------------------------------------------------------
# AT-0 — a healthy ACTIVE acquisition claims its samples; U2 never blocks normal
# execution (SC-2). §9.3: the real first create/prompt sequence goes through
# the guards; the original sends succeed exactly once and replay or takeover
# never sends again (SC2-1).
# ---------------------------------------------------------------------------


def test_at00_healthy_acquisition_claims_all_samples_and_replay_never_resends(
    db: Database, tmp_path: Path
):
    world = RenderWorld(db)
    ep, plan, service, budget, comfy, adapter = _composed_world(world, tmp_path)
    service.seal(plan.experiment_id, _bench_seal_for(plan))
    _, authorization, digest, raw = _authorization_pair(world, plan, tmp_path)
    # The original invocation: the first create and the three prompts go through
    # every admission/claim/dispatch gate and all succeed once (a fresh process
    # continues in-flight work through resume - §4.2's U3p rule).
    with _PatchedPolicy():
        state = _drive_resume(
            db, world, comfy, adapter, plan, authorization, digest, raw, phase="screen", limit=12
        )
    assert state["execution_state"] == "SCREEN_REVIEW", state["execution_state"]
    assert len(comfy.server.submissions) == 3
    assert {s["sample_id"] for s in state["samples"] if s["state"] == "SUCCEEDED"} == {
        "S01-R1",
        "S03-R1",
        "S07-R1",
    }
    # AT-0 proper: the healthy ACTIVE acquisition inside its execution window
    # never produced a U2 (or any other) blocking item.
    assert _item_kinds(db, plan.experiment_id, comfy.clock) == []
    with db.transaction(readonly=True) as tx:
        created = tx.fetchval("SELECT COUNT(*) FROM pod_leases WHERE pod_id IS NOT NULL")
    assert created == 1  # exactly one pod for the whole healthy screen

    # Replay: a fresh service resuming a finished screen sends nothing at all.
    replay = _execute_service(db, comfy, world.ids, adapter)
    resumed = replay.resume(
        plan.experiment_id,
        authorization=authorization,
        quote=_screen_quote(world),
        expected_sha256=digest,
        phase="screen",
        source_bytes=raw,
    )
    assert len(comfy.server.submissions) == 3
    assert resumed["execution_state"] == "SCREEN_REVIEW"

    # Takeover: the first prompt POST of the full phase times out AFTER the
    # provider accepted it. A fresh process takes over: reconciliation adopts
    # the accepted prompt by client identity and the run completes with each
    # sample sent exactly once (I1, SC2-1 - replay/takeover never re-send).
    from microdrama.contracts.errors import NeedsReconciliation
    from microdrama.testing.fakes.comfy import FakeComfyClient

    class TimeoutOnceClient(FakeComfyClient):
        def __init__(self, state):
            super().__init__(state)
            self.timed_out = False

        def queue_prompt(self, graph, *, client_id):
            prompt_id = super().queue_prompt(graph, client_id=client_id)
            if not self.timed_out:
                self.timed_out = True
                raise NeedsReconciliation("synthetic submit timeout after acceptance")
            return prompt_id

    _record_pass(service, plan, state)
    comfy.service._client = TimeoutOnceClient(comfy.server)
    first_full = _execute_service(db, comfy, world.ids, adapter)
    with _PatchedPolicy():
        ambiguous = first_full.resume(
            plan.experiment_id,
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            phase="screen",
            source_bytes=raw,
        )
    assert ambiguous["execution_state"] == "NEEDS_RECONCILIATION", ambiguous["execution_state"]
    assert len(comfy.server.submissions) == 4  # 3 screen + the one accepted-then-timeout

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
        for _ in range(90):
            if final["execution_state"] == "COMPUTE_COMPLETE":
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
    assert final["execution_state"] == "COMPUTE_COMPLETE", final["execution_state"]
    # Every sample exactly once: the timed-out prompt was adopted, never re-sent.
    assert len(comfy.server.submissions) == 24


# ---------------------------------------------------------------------------
# AT-5 — resume with CLEANUP_PENDING and a released lease: no acquire() on a
# terminal lease, no spurious FAILED, next acquisition only after finalization.
# ---------------------------------------------------------------------------


def test_at05_resume_finalizes_terminal_acquisition_before_any_new_admission(
    db: Database, tmp_path: Path
):
    from microdrama.pipeline.experimental_world import CanonicalExperimentWorld

    world = RenderWorld(db)
    ep, plan, service, budget, comfy, adapter = _composed_world(world, tmp_path)
    service.seal(plan.experiment_id, _bench_seal_for(plan))
    _, authorization, digest, raw = _authorization_pair(world, plan, tmp_path)

    class UnfinalWorld(_UnfinalOfflineWorld, CanonicalExperimentWorld):
        pass

    unfinal_adapter = UnfinalWorld(
        db=adapter.db,
        jobs=adapter.jobs,
        leases=adapter.leases,
        comfy=adapter.comfy,
        budget=adapter.budget,
        request_factory=adapter.request_factory,
    )

    # Generation 1 is ACTIVE with a live pod (canonical claim + ensure), then a
    # crash between cleanup and the finalization transaction leaves exactly the
    # durable state AT-5 names: CLEANUP_PENDING, lease RELEASED with termination
    # verified, STORAGE hold still open (R1).
    lease_id = _lease_with_live_pod(db, world, ep.episode_id)
    acquisition_id = uuid5_seed(plan.experiment_id, 1)
    adapter.leases.shutdown(lease_id, reason="at5 crash seed")
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO benchmark_acquisitions(acquisition_id,experiment_id,generation,quote,"
            "quote_sha256,intent,state,create_intent_at,lease_id,authorization_sha256) "
            "VALUES(%s,%s,1,%s,%s,%s,'CLEANUP_PENDING',%s,%s,%s)",
            (
                acquisition_id,
                plan.experiment_id,
                jsonb(_screen_quote(world)),
                "1" * 64,
                jsonb({"claim": {}}),
                comfy.clock.now(),
                lease_id,
                "2" * 64,
            ),
        )
    acquisition = {"acquisition_id": acquisition_id, "lease_id": lease_id}
    with db.transaction(readonly=True) as tx:
        lease = tx.fetchone("SELECT * FROM pod_leases WHERE id=%s", (lease_id,))
    assert lease["lease_state"] == "RELEASED"
    assert lease["stop_verified_at"] is not None or lease["terminate_verified_at"] is not None

    # Phase B — finalization incomplete: resume sweeps but admits NOTHING.
    resumed = _execute_service(db, comfy, world.ids, unfinal_adapter)
    with _PatchedPolicy():
        first = resumed.resume(
            plan.experiment_id,
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            phase="screen",
            source_bytes=raw,
        )
    assert first["execution_state"] != "FAILED"
    assert first["execution_outcome"] is None  # no spurious FAILED
    assert first["admission"]["permitted"] is False
    with db.transaction(readonly=True) as tx:
        count = tx.fetchval(
            "SELECT COUNT(*) FROM benchmark_acquisitions WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
        still = tx.fetchone("SELECT * FROM pod_leases WHERE id=%s", (acquisition["lease_id"],))
    assert count == 1  # U2 blocked the next acquisition's admission
    assert "U2" in _item_kinds(db, plan.experiment_id, comfy.clock)
    assert still["lease_state"] == "RELEASED"  # no acquire() on the terminal lease

    # Phase A — finalization completes: the NEXT resume admits generation 2 on a
    # NEW lease, never on the terminal one, and the screen continues.
    unfinal_adapter.final = True
    final_service = _execute_service(db, comfy, world.ids, unfinal_adapter)
    with _PatchedPolicy():
        second = final_service.resume(
            plan.experiment_id,
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            phase="screen",
            source_bytes=raw,
        )
    with db.transaction(readonly=True) as tx:
        rows = tx.fetchall(
            "SELECT * FROM benchmark_acquisitions WHERE experiment_id=%s ORDER BY generation",
            (plan.experiment_id,),
        )
        old_lease = tx.fetchone("SELECT * FROM pod_leases WHERE id=%s", (acquisition["lease_id"],))
    assert rows[0]["state"] == "CLOSED"  # finalization completed in the gate's way
    assert len(rows) == 2  # generation 2 admitted only now
    assert rows[1]["lease_id"] != acquisition["lease_id"]
    assert old_lease["lease_state"] == "RELEASED"  # never re-acquired
    assert second["execution_outcome"] in (None, "SUCCEEDED")


# ---------------------------------------------------------------------------
# AT-10 — the private admission helpers refuse inside their locked transaction
# while each unresolved kind exists (I3). U6 never blocks other work (§4.1
# scopes) and U2 does not block claims; both are asserted as such.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "blocks_admission", "claims_context"),
    [
        ("U1", True, "seeded"),
        ("U2", True, "healthy"),
        ("U3", True, "healthy"),
        ("U3p", True, "healthy"),
        ("U3u", True, "healthy"),
        ("U4", True, "healthy"),
        ("U5", True, "healthy"),
        ("U6", False, "seeded"),
    ],
)
def test_at10_admission_gates_apply_each_unresolved_kind(
    db: Database, tmp_path: Path, kind: str, blocks_admission: bool, claims_context: str
):
    world = RenderWorld(db)
    ep, plan, service, budget, comfy, adapter = _composed_world(world, tmp_path)
    clock = comfy.clock

    from microdrama.pipeline.benchmark_service import AdmissionBlocked

    seeded_acquisition: UUID | None = None
    if kind == "U1":
        # Committed create intent, no pod, no resolution — and deliberately NOT
        # labelled UNKNOWN (SC-3: the label is not the predicate).
        lease = _crash_seed_lease(db, world, ep.episode_id, create_requested=True)
        seeded_acquisition = _insert_acquisition(
            db, world, adapter, plan, generation=1, state="ADMITTED_WITHOUT_JOB", lease_id=lease
        )
    elif kind == "U2":
        # R1: NO_CREATE_PROVEN whose sweep finalization never ran — the STORAGE
        # hold is still canonically open, so the next admission must refuse.
        acq = _insert_acquisition(
            db, world, adapter, plan, generation=1, state="ADMITTED_WITHOUT_JOB"
        )
        with db.transaction(readonly=True) as tx:
            exp = tx.fetchone(
                "SELECT * FROM benchmark_experiments WHERE experiment_id=%s", (plan.experiment_id,)
            )
            intent = adapter.acquisition_requests(exp, _screen_quote(world), acq, 1, clock.now())
        with db.transaction() as tx:
            adapter.budget.reserve_linked(
                tx,
                BudgetReservationRequest.model_validate(intent["storage"]),
                acquisition_id=acq,
                purpose="STORAGE",
            )
            tx.execute(
                "UPDATE benchmark_acquisitions SET state='NO_CREATE_PROVEN' "
                "WHERE acquisition_id=%s",
                (acq,),
            )
    elif kind in ("U3", "U3p", "U4"):
        hold = adapter.budget.reserve(
            _prompt_hold_request(world, ep.episode_id, plan, "S02-R1", clock)
        )
        state = {"U3": "UNKNOWN", "U3p": "SUBMITTED", "U4": "FAILED"}[kind]
        # U4 stays un-projected and un-settled (slot free, sample not written).
        _seed_sample_operation(db, plan, "S02-R1", state, clock, comfy, reservation_id=hold.id)
    elif kind == "U3u":
        acq = _insert_acquisition(db, world, adapter, plan, generation=1, state="NO_CREATE_PROVEN")
        with db.transaction() as tx:
            tx.execute(
                "INSERT INTO benchmark_uploads(acquisition_id,asset_sha256,media_kind,role,"
                "subject_id,destination_slot,upload_key,state) "
                "VALUES(%s,%s,'image',%s,%s,%s,%s,'INTENT')",
                (
                    acq,
                    "4" * 64,
                    "character_identity",
                    "speaker-a",
                    "ref_images.ref_image_0",
                    "t031/x",
                ),
            )
    elif kind == "U5":
        lease = _crash_seed_lease(db, world, ep.episode_id, create_requested=True)
        with db.transaction() as tx:
            tx.execute(
                "UPDATE pod_leases SET pod_id=%s,lease_state='RELEASED' WHERE id=%s",
                ("pod-late", lease),
            )
        acq = _insert_acquisition(
            db, world, adapter, plan, generation=1, state="NO_CREATE_PROVEN", lease_id=lease
        )
        with db.transaction() as tx:
            tx.execute(
                "INSERT INTO runpod_podless_create_resolutions(resolution_id,lease_id,actor_ref,"
                "reason,evidence_sha256,resolved_at,contradicted_at,contradicted_pod_id) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    uuid4(),
                    lease,
                    "at10-operator",
                    "at10 contradiction seed",
                    "5" * 64,
                    clock.now(),
                    clock.now(),
                    "pod-late",
                ),
            )
    elif kind == "U6":
        # Intent and holds committed without job/lease links (§F): local-only.
        seeded_acquisition = _insert_acquisition(
            db, world, adapter, plan, generation=1, state="ADMITTED_WITHOUT_JOB"
        )

    expected = {"U6": ["U6"]}.get(kind) or [kind]
    if kind == "U6":
        assert "U6" in _item_kinds(db, plan.experiment_id, clock)
    else:
        assert _item_kinds(db, plan.experiment_id, clock) == expected, kind

    probe = BenchmarkService(db, _paid_settings(), clock=clock, ids=world.ids)
    probe.world_factory = lambda **_kwargs: adapter

    # --- Admission gate -----------------------------------------------------
    if blocks_admission:
        with pytest.raises(AdmissionBlocked):
            probe._acquisition(plan.experiment_id, adapter, _screen_quote(world))
        with db.transaction(readonly=True) as tx:
            admitted = tx.fetchval(
                "SELECT COUNT(*) FROM benchmark_acquisitions WHERE experiment_id=%s AND generation=2",
                (plan.experiment_id,),
            )
        assert admitted == 0  # refused inside the locked transaction, nothing written
    else:
        returned = probe._acquisition(plan.experiment_id, adapter, _screen_quote(world))
        assert str(returned["acquisition_id"]) == str(seeded_acquisition)  # U6 replays locally

    # --- Claims gate --------------------------------------------------------
    if claims_context == "seeded":
        with db.transaction(readonly=True) as tx:
            acquisition = tx.fetchone(
                "SELECT * FROM benchmark_acquisitions WHERE acquisition_id=%s",
                (seeded_acquisition,),
            )
        eligible = {"S01-R1", "S02-R1", "S07-R1"} - (
            {"S02-R1"} if kind in ("U3", "U3p", "U4") else set()
        )
        if kind == "U1":
            with pytest.raises(AdmissionBlocked):
                probe._claim_sample(plan.experiment_id, adapter, acquisition, eligible)
        else:  # U6: claiming proceeds; its own item's effect is what is gated
            claimed = probe._claim_sample(plan.experiment_id, adapter, acquisition, eligible)
            assert claimed is None or claimed["sample_id"] in eligible
    else:
        healthy_lease = _lease_with_live_pod(db, world, ep.episode_id)
        healthy = _insert_acquisition(
            db,
            world,
            adapter,
            plan,
            generation=3,
            state="ACTIVE",
            lease_id=healthy_lease,
            clock=clock,
        )
        if kind == "U3u":
            # U3u's sample block is acquisition-scoped (R2): the unverified
            # intent must sit on the acquisition whose samples are claimed.
            with db.transaction() as tx:
                tx.execute(
                    "INSERT INTO benchmark_uploads(acquisition_id,asset_sha256,media_kind,role,"
                    "subject_id,destination_slot,upload_key,state) "
                    "VALUES(%s,%s,'image',%s,%s,%s,%s,'UNKNOWN')",
                    (
                        healthy,
                        "7" * 64,
                        "character_identity",
                        "speaker-a",
                        "ref_images.ref_image_0",
                        "t031/y",
                    ),
                )
        with db.transaction(readonly=True) as tx:
            acquisition = tx.fetchone(
                "SELECT * FROM benchmark_acquisitions WHERE acquisition_id=%s", (healthy,)
            )
        eligible = {"S01-R1", "S07-R1"}  # S02-R1 carries the seeded item, if any
        if kind == "U2":
            # §4.1: U2 blocks admission of the NEXT acquisition and dispatch on
            # its own — never claims on the healthy one.
            claimed = probe._claim_sample(plan.experiment_id, adapter, acquisition, eligible)
            assert claimed is not None and claimed["sample_id"] in eligible
        else:
            with pytest.raises(AdmissionBlocked):
                probe._claim_sample(plan.experiment_id, adapter, acquisition, eligible)


# ---------------------------------------------------------------------------
# AT-11 — resume phase derivation: a durable PASS means full even when the CLI
# passes its default `screen` (§4.2).
# ---------------------------------------------------------------------------


def test_at11_resume_derives_full_from_durable_pass_not_the_cli_default(
    db: Database, tmp_path: Path
):
    world = RenderWorld(db)
    ep, plan, service, budget, comfy, adapter = _composed_world(world, tmp_path)
    service.seal(plan.experiment_id, _bench_seal_for(plan))
    _, authorization, digest, raw = _authorization_pair(world, plan, tmp_path)

    # No PASS recorded yet: the screen runs its three samples only.
    with _PatchedPolicy():
        state = _drive_resume(
            db, world, comfy, adapter, plan, authorization, digest, raw, phase="screen", limit=12
        )
    assert state["execution_state"] == "SCREEN_REVIEW"
    assert len(comfy.server.submissions) == 3

    _record_pass(service, plan, state)

    # The durable PASS wins over the CLI's `screen` default: resume drives the
    # FULL sample set (§4.2: the CLI default never overrides a durable PASS).
    resumed = _execute_service(db, comfy, world.ids, adapter)
    with _PatchedPolicy():
        final = resumed.resume(
            plan.experiment_id,
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            phase="screen",  # the CLI default
            source_bytes=raw,
        )
        for _ in range(90):
            if final["execution_state"] == "COMPUTE_COMPLETE":
                break
            comfy.clock.advance(seconds=1)
            final = resumed.resume(
                plan.experiment_id,
                authorization=authorization,
                quote=_screen_quote(world),
                expected_sha256=digest,
                phase="screen",
                source_bytes=raw,
            )
    assert final["execution_state"] == "COMPUTE_COMPLETE", final["execution_state"]
    assert final["execution_outcome"] == "SUCCEEDED"
    assert len(comfy.server.submissions) == 24  # 3 screen + the 21 remaining


# ---------------------------------------------------------------------------
# AT-13 — canonical create intent committed, worker died before the ambiguity
# handler could label anything: U1 is derived WITHOUT the acquisition label
# (SC-3), blocks all dispatch, and the run converges through the public
# operator resolution. Real subprocess death (os._exit mid-create, §9.3).
# ---------------------------------------------------------------------------


class _DeathOnCreatePods:
    """Fake provider that kills the worker inside the create POST.

    The durable create intent is committed before the POST (T045 R8), so dying
    here leaves exactly §E's "intent committed, no pod ID" state — with the
    acquisition NOT labelled UNKNOWN. The marker file and the database are the
    only state that survives the killed process.
    """

    def __init__(self, inner, marker: Path):
        self.inner = inner
        self.marker = marker
        self.creates = 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def create_pod(self, request):
        self.creates += 1
        self.marker.write_text("create-entered", encoding="utf-8")
        os._exit(86)  # §9.3: bypasses every exception cleanup path


def _at13_child(dsn: str, output_dir: str, marker: str, identity: str) -> None:
    """Runs INSIDE the subprocess: the real composed execute path until death."""
    sys.path.insert(0, str(SRC_ROOT))
    sys.path.insert(0, str(UNIT_TESTS))
    sys.path.insert(0, str(RENDERING_TESTS))
    _at13_child_world(dsn, output_dir, marker, identity)


def _at13_child_world(dsn: str, output_dir: str, marker: str, identity: str) -> None:
    import microdrama.pipeline.experimental_world as world_module
    from microdrama.pipeline.benchmark_authorization import BenchmarkAuthorization

    # Process-local patches (they die with the subprocess).
    world_module.ExperimentalPresetPolicy.validate = lambda *a, **k: None
    BenchmarkAuthorization.validate_for = lambda *a, **k: None

    from rendering_support import RenderWorld
    from test_benchmark_experiments import _composed_world
    from test_t031_h2b_p1_modes import _authorization_pair, _execute_service

    from microdrama.persistence import Database

    db = Database(dsn).open()
    world = RenderWorld(db)
    out = Path(output_dir)
    from test_t045_timing import RunpodIdFakePods

    from microdrama.rendering.leases import durable_created_pod_recorder

    ep, plan, service, budget, comfy, adapter = _composed_world(world, out)
    service.seal(plan.experiment_id, _bench_seal_for(plan))
    _, authorization, digest, raw = _authorization_pair(world, plan, out)
    # The operator resolution (resolve_podless_create) is the runpod billing
    # path, so the dying worker's lease must be runpod-addressed like the
    # pre-existing operator-resolution fixtures.
    inner = RunpodIdFakePods(clock=world.clock, ids=world.ids)
    inner.created_pod_recorder = durable_created_pod_recorder(world.db, world.clock.now)
    world.provider = inner
    world.manager._provider = _DeathOnCreatePods(inner, Path(marker))
    Path(identity).write_text(json.dumps({"experiment_id": str(plan.experiment_id)}))
    service = _execute_service(db, comfy, world.ids, adapter)
    service.execute(
        plan.experiment_id,
        phase="screen",
        authorization=authorization,
        quote=_screen_quote(world),
        expected_sha256=digest,
        source_bytes=raw,
    )


def _adapter_for(db, world: RenderWorld, comfy, plan_row: dict, experiment_id: UUID):
    """A parent-process composed adapter for the child's experiment."""
    from comfy_support import _workflow_sha_for
    from test_benchmark_experiments import _OfflineFinalityWorld

    from microdrama.contracts.cost import RenderRequest
    from microdrama.contracts.enums import ControlKind, RenderTier
    from microdrama.pipeline.experimental_world import CanonicalExperimentWorld
    from microdrama.rendering.benchmark_experiments import ExperimentBudgetService
    from microdrama.rendering.comfy_jobs import render_id_for

    reference = UUID(int=4242)

    def request_factory(sample, acquisition, reservation_id):
        key = f"benchmark:{experiment_id}:sample:{sample['sample_id']}:a1"
        return RenderRequest(
            render_id=render_id_for(key),
            semantic_key=key,
            episode_id=UUID(str(plan_row["episode_id"])),
            episode_number=1,
            shot_id=f"bench-{sample['sample_id'].lower()}",
            manifest_version=1,
            attempt_number=1,
            preset_id="fake-quality-8step",
            tier=RenderTier.QUALITY_EIGHT_STEP,
            required_controls=[ControlKind.CHARACTER_REFERENCE],
            reference_asset_ids=[reference],
            workflow_sha256=_workflow_sha_for("fake-quality-8step"),
            seed=sample["seed"],
            width=720,
            height=1280,
            fps=24,
            duration_ms=4000,
            reservation_id=reservation_id,
            prompt_text="Offline synthetic fixture.",
        )

    class ParentWorld(_OfflineFinalityWorld, CanonicalExperimentWorld):
        pass

    from microdrama.core.clock import UuidIds

    # The parent creates only NEW entities (replays are semantic-key
    # idempotent); random ids never collide with the child's deterministic
    # sequence, which died with the process.
    budget = ExperimentBudgetService(
        db, comfy.clock, UuidIds(), world.settings, experiment_id=experiment_id
    )
    comfy.service._budget = budget
    world.leases._budget = budget
    world.leases._clock = comfy.clock
    world.provider.clock = comfy.clock
    world.manager._clock = comfy.clock
    adapter = ParentWorld(
        db=db,
        jobs=comfy.jobs,
        leases=world.leases,
        comfy=comfy.service,
        budget=budget,
        request_factory=request_factory,
    )
    return adapter, budget


def test_at13_u1_without_label_from_real_subprocess_death_blocks_and_converges(
    db: Database, tmp_path: Path
):
    world = RenderWorld(db)
    marker = tmp_path / "at13.marker"
    identity = tmp_path / "at13-identity.json"

    script = (
        "import sys; sys.argv=['child']; "
        f"sys.path[:0] = [{str(SRC_ROOT)!r}, {str(UNIT_TESTS)!r}, {str(RENDERING_TESTS)!r}]; "
        "from test_t031_h2b_p2_gate import _at13_child as run; "
        f"run({db.dsn!r}, {str(tmp_path / 'at13-child-out')!r}, {str(marker)!r}, {str(identity)!r})"
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
        cwd=str(RENDERING_TESTS),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert marker.exists(), child.stderr[-2000:]
    assert child.returncode == 86, child.stderr[-2000:]

    experiment_id = UUID(json.loads(identity.read_text(encoding="utf-8"))["experiment_id"])

    # The parent process builds its own world for the child's experiment: the
    # authorization is loaded from the durable provenance row the child's
    # execute committed (§3.2), never from child memory.
    from dataclasses import replace as _replace

    from comfy_support import ComfyWorld

    from microdrama.pipeline.benchmark_authorization import BenchmarkAuthorization
    from microdrama.rendering.comfy_jobs import ComfyRenderConfig

    comfy = ComfyWorld(
        db,
        tmp_path / "at13-parent-out",
        config=_replace(ComfyRenderConfig.for_mock(), lease_covered=True),
        execution_ms=0,
    )
    with db.transaction(readonly=True) as tx:
        experiment = tx.fetchone(
            "SELECT * FROM benchmark_experiments WHERE experiment_id=%s", (experiment_id,)
        )
        acquisition = tx.fetchone(
            "SELECT * FROM benchmark_acquisitions WHERE experiment_id=%s", (experiment_id,)
        )
        lease = tx.fetchone("SELECT * FROM pod_leases WHERE id=%s", (acquisition["lease_id"],))
        auth_row = tx.fetchone(
            "SELECT z.* FROM benchmark_authorizations z JOIN benchmark_acquisitions a "
            "ON a.experiment_id=z.experiment_id "
            "AND a.authorization_sha256=z.authorization_sha256 "
            "WHERE a.experiment_id=%s LIMIT 1",
            (experiment_id,),
        )
    # The crash state: create intent committed, no pod bound, NO label anywhere.
    assert lease["create_requested_at"] is not None
    assert lease["pod_id"] is None
    assert acquisition["state"] != "UNKNOWN"
    assert experiment["execution_state"] != "NEEDS_RECONCILIATION"

    # U1 is derived from the canonical linkage, not from any label (SC-3).
    assert _item_kinds(db, experiment_id, comfy.clock) == ["U1"]

    adapter, budget = _adapter_for(db, world, comfy, experiment, experiment_id)
    comfy._seed_reference_assets([UUID(int=4242)])
    authorization = BenchmarkAuthorization.model_validate(auth_row["payload"])
    digest = auth_row["authorization_sha256"]
    raw = bytes(auth_row["source_bytes"])
    authorization._source_sha256 = digest  # what the operator's byte SHA proved
    # The parent continues from the child's durable time, never a fresh clock.
    comfy.clock.set(experiment["updated_at"] or experiment["created_at"])

    def parent_service():
        from microdrama.core.clock import UuidIds

        return BenchmarkService(
            db,
            _paid_settings(),
            clock=comfy.clock,
            ids=UuidIds(),
            world_factory=lambda **_kwargs: adapter,
        )

    resumed = parent_service()
    with _PatchedPolicy():
        blocked = resumed.resume(
            experiment_id,
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            phase="screen",
            source_bytes=raw,
        )
    assert blocked["admission"]["permitted"] is False
    assert any(
        "U1" in blocker or "create" in blocker for blocker in blocked["admission"]["blockers"]
    )
    assert comfy.server.submissions == []  # nothing was dispatched
    with db.transaction(readonly=True) as tx:
        still = tx.fetchone("SELECT * FROM pod_leases WHERE id=%s", (lease["id"],))
    assert still["pod_id"] is None  # never a second create from absence

    # Convergence: the audited operator resolution clears U1 and the run
    # continues on a NEW acquisition generation (public resolve_create).
    resumed.resolve_create(
        experiment_id,
        acquisition_id=acquisition["acquisition_id"],
        actor_ref="operator-console",
        reason="provider console shows no pod for the owned token",
        evidence_sha256="6" * 64,
    )
    # U1 is gone; only the cleanup the resolution owes remains (its lease and
    # storage hold close through the sweep, never through the resolution).
    assert "U1" not in _item_kinds(db, experiment_id, comfy.clock)
    # The killed worker still holds the coordinator token (its finally never
    # ran): the takeover happens at token expiry (§E), never by preempting it.
    comfy.clock.advance(seconds=3601)
    final_service = parent_service()
    with _PatchedPolicy():
        final = final_service.resume(
            experiment_id,
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
            final = final_service.resume(
                experiment_id,
                authorization=authorization,
                quote=_screen_quote(world),
                expected_sha256=digest,
                phase="screen",
                source_bytes=raw,
            )
    assert final["execution_state"] == "SCREEN_REVIEW", final["execution_state"]
    assert len(comfy.server.submissions) == 3  # the screen completed, once per sample


# ---------------------------------------------------------------------------
# AT-14 — claim and hold committed with no job/operation (§F): replay adopts
# the same hold (never a second one); after hold expiry only the positively
# unused liability is closed.
# ---------------------------------------------------------------------------


def _at14_context(db: Database, tmp_path: Path):
    """An ACTIVE acquisition with a live pod and one seeded claim, no job/operation."""
    world = RenderWorld(db)
    ep, plan, service, budget, comfy, adapter = _composed_world(world, tmp_path)
    service.seal(plan.experiment_id, _bench_seal_for(plan))
    lease_id = _lease_with_live_pod(db, world, ep.episode_id)
    with db.transaction() as tx:
        acquisition_id = uuid5_seed(plan.experiment_id, 1)
        tx.execute(
            "INSERT INTO benchmark_acquisitions(acquisition_id,experiment_id,generation,quote,"
            "quote_sha256,intent,state,create_intent_at,lease_id,authorization_sha256) "
            "VALUES(%s,%s,1,%s,%s,%s,'ACTIVE',%s,%s,%s)",
            (
                acquisition_id,
                plan.experiment_id,
                jsonb(_screen_quote(world)),
                "1" * 64,
                jsonb({"claim": {}}),
                comfy.clock.now(),
                lease_id,
                "2" * 64,
            ),
        )
    with db.transaction(readonly=True) as tx:
        acquisition = tx.fetchone(
            "SELECT * FROM benchmark_acquisitions WHERE acquisition_id=%s", (acquisition_id,)
        )
    _seed_claim(db, adapter, world, plan, acquisition, "S01-R1")
    return world, ep, plan, service, comfy, adapter, budget, acquisition


def _at14_authorization(world, plan, tmp_path):
    from test_t031_h2b_p1_modes import _authorization_pair as pair

    return pair(world, plan, tmp_path)


def test_at14_u6_claim_replay_adopts_the_hold_without_a_second_one(db: Database, tmp_path: Path):
    world, ep, plan, service, comfy, adapter, budget, acquisition = _at14_context(db, tmp_path)
    _, authorization, digest, raw = _at14_authorization(world, plan, tmp_path)
    key = f"benchmark:{plan.experiment_id}:sample:S01-R1:a1"
    with db.transaction(readonly=True) as tx:
        holds = tx.fetchval("SELECT COUNT(*) FROM reservations WHERE semantic_key=%s", (key,))

    # Replay (a fresh process, no first-send right of its own): the claim is
    # adopted — the SAME hold, never a second one — and the sample runs once.
    resumed = _execute_service(db, comfy, world.ids, adapter)
    with _PatchedPolicy():
        final = resumed.resume(
            plan.experiment_id,
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            phase="screen",
            source_bytes=raw,
        )
        for _ in range(12):
            if final["execution_state"] in ("SCREEN_REVIEW", "COMPUTE_COMPLETE"):
                break
            comfy.clock.advance(seconds=1)
            final = resumed.resume(
                plan.experiment_id,
                authorization=authorization,
                quote=_screen_quote(world),
                expected_sha256=digest,
                phase="screen",
                source_bytes=raw,
            )
    with db.transaction(readonly=True) as tx:
        after = tx.fetchone(
            "SELECT * FROM benchmark_samples WHERE experiment_id=%s AND sample_id='S01-R1'",
            (plan.experiment_id,),
        )
        holds_after = tx.fetchval("SELECT COUNT(*) FROM reservations WHERE semantic_key=%s", (key,))
    assert after["job_id"] is not None  # the §F replay materialized the canonical job
    assert holds_after == holds == 1  # adopted, no second hold
    assert after["state"] == "SUCCEEDED"
    assert after["operation_id"] is not None
    # A healthy mid-run resume continues on the SAME live pod: no churn, no
    # second create (the current unconditional sweep-first resume fails this).
    with db.transaction(readonly=True) as tx:
        with_pod = tx.fetchval(
            "SELECT COUNT(*) FROM benchmark_acquisitions a JOIN pod_leases l "
            "ON l.id=a.lease_id WHERE a.experiment_id=%s AND l.pod_id IS NOT NULL",
            (plan.experiment_id,),
        )
        lease_now = tx.fetchone("SELECT * FROM pod_leases WHERE id=%s", (acquisition["lease_id"],))
    assert with_pod == 1
    assert lease_now["pod_id"] is not None


def test_at14_u6_after_hold_expiry_closes_only_positively_unused_liability(
    db: Database, tmp_path: Path
):
    world, ep, plan, service, comfy, adapter, budget, acquisition = _at14_context(db, tmp_path)
    _, authorization, digest, raw = _at14_authorization(world, plan, tmp_path)
    with db.transaction(readonly=True) as tx:
        reservation_id = tx.fetchval(
            "SELECT reservation_id FROM benchmark_samples WHERE experiment_id=%s AND sample_id='S01-R1'",
            (plan.experiment_id,),
        )

    # The hold expires (canonical expire_stale) before anything was dispatched.
    comfy.clock.advance(seconds=700)
    budget.expire_stale()
    with db.transaction(readonly=True) as tx:
        expired = tx.fetchone("SELECT state FROM reservations WHERE id=%s", (reservation_id,))
    assert expired["state"] == "EXPIRED"

    # Replay after expiry: no effect is sent; only the positively unused
    # liability closes, the sample fails, and the slot frees (§F, §7.4).
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
    assert comfy.server.submissions == []  # nothing was dispatched
    with db.transaction(readonly=True) as tx:
        sample = tx.fetchone(
            "SELECT * FROM benchmark_samples WHERE experiment_id=%s AND sample_id='S01-R1'",
            (plan.experiment_id,),
        )
        reservation = tx.fetchone("SELECT * FROM reservations WHERE id=%s", (reservation_id,))
        operations = tx.fetchval(
            "SELECT COUNT(*) FROM provider_operations WHERE reservation_id=%s", (reservation_id,)
        )
        outcome = tx.fetchval(
            "SELECT execution_outcome FROM benchmark_experiments WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
    assert sample["state"] == "FAILED"
    assert reservation["state"] == "SETTLED"
    assert reservation["settled_micro_usd"] == 0  # positively unused: zero charge
    assert operations == 0  # no operation was ever begun
    assert outcome == "FAILED"  # §7.4 fail-fast
    exposure = service.status(plan.experiment_id)["exposure"]
    assert exposure["total"] >= 0 and exposure["holds"] == 0


# ---------------------------------------------------------------------------
# Cleanup-fixture strictness (§9.1): the offline composed fixture requires
# terminate_verified_at exactly like the production adapter — a stop without a
# verified termination is NOT cleanup evidence.
# ---------------------------------------------------------------------------


def test_cleanup_fixture_requires_verified_termination_evidence(db: Database, tmp_path: Path):
    """§9.1: the composed fixture's two unconditional assertions are restored -
    a pod-bound cleanup without durable stop/terminate evidence fails loudly,
    and only a podless close reports unverified (never a fabricated receipt)."""
    world = RenderWorld(db)
    ep, plan, service, budget, comfy, adapter = _composed_world(world, tmp_path)
    lease_id = _lease_with_live_pod(db, world, ep.episode_id)
    acquisition = {"acquisition_id": uuid5_seed(plan.experiment_id, 1), "lease_id": lease_id}

    # Happy path: the pod-bound cleanup carries durable stop evidence.
    receipt = adapter.cleanup(acquisition)
    assert receipt["verified"] is True
    assert receipt["billing_state"] == "BILLED"
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone("SELECT * FROM pod_leases WHERE id=%s", (lease_id,))
    assert row["stop_verified_at"] is not None or row["terminate_verified_at"] is not None

    # A pod-bound lease WITHOUT durable evidence must fail the fixture's
    # unconditional assertion - the H-2 softening that silently accepted a
    # missing timestamp (or fabricated BILLED) is gone.
    import pytest as _pytest

    from microdrama.rendering.leases import PodLeaseClaimRequest

    request = PodLeaseClaimRequest(
        episode_id=ep.episode_id,
        semantic_key=f"benchmark-strict:{uuid4().hex[:8]}",
        gpu_type=world.config.allowed_gpu_types[0],
        host_ram_gb=world.config.min_host_ram_gb,
    )
    reservation, _ = world.leases._reserve_for_lease(request, world.config.lease_ttl_ms)
    handle = world.leases.claim_pre_reserved(request, reservation.id)
    world.leases.ensure_pod(handle.lease.lease_id)
    # The pod vanished before any stop evidence existed: cleanup propagates the
    # provider failure instead of returning a fabricated verified receipt.
    with db.transaction(readonly=True) as tx:
        probe_pod = tx.fetchval(
            "SELECT pod_id FROM pod_leases WHERE id=%s", (handle.lease.lease_id,)
        )
    world.provider._pods.pop(probe_pod)
    with _pytest.raises(Exception):  # noqa: B017 - the loud failure is the point
        adapter.cleanup(
            {"acquisition_id": uuid5_seed(plan.experiment_id, 2), "lease_id": handle.lease.lease_id}
        )
