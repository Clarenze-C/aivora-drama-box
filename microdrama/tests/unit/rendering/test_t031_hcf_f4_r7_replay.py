"""T031 H-2 HCF round, F4: HC-3 (R7 recoverability refuses
``--force-unrecoverable`` on positively recoverable work - recoverability is
probed through the RECOVERY path with client-ID discovery, and an EXPIRED
hold's recovery read no longer looks unreachable to the operator probe) and
HC-4 (every terminal replay independently completes ALL finalization stages;
U4 includes the missing failed-outcome projection; success requires durable
assets)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from test_t031_h2b_p1_modes import _PatchedPolicy
from test_t031_h2b_p3_ambiguity import _crash_state, _valid_fake_graph
from test_t031_h2b_p5_terminal import _service_for

from microdrama.contracts.errors import Conflict, EffectDenied
from microdrama.persistence import Database
from microdrama.persistence.db import jsonb
from microdrama.rendering.benchmark_experiments import unresolved_items
from microdrama.rendering.comfy_jobs import render_client_id
from microdrama.testing.fakes.comfy import FakeComfyClient

pytestmark = pytest.mark.db


def _fixed(world, comfy, adapter, authorization, digest, raw):
    return {
        "world": world,
        "comfy": comfy,
        "adapter": adapter,
        "authorization": authorization,
        "digest": digest,
        "raw": raw,
    }


def _sample_row(db: Database, experiment_id: UUID, sample_id: str):
    with db.transaction(readonly=True) as tx:
        return tx.fetchone(
            "SELECT * FROM benchmark_samples WHERE experiment_id=%s AND sample_id=%s",
            (experiment_id, sample_id),
        )


def _kinds(db: Database, experiment_id: UUID, clock) -> list[str]:
    with db.transaction(readonly=True) as tx:
        return [item.kind for item in unresolved_items(tx, experiment_id, now=clock.now())]


# ---------------------------------------------------------------------------
# HC-3 - positively recoverable work refuses resolution EVEN WITH force.
# ---------------------------------------------------------------------------


def test_hc3_client_id_recoverable_work_refuses_force(db: Database, tmp_path: Path) -> None:
    """HC-3: the worker's POST landed under the DETERMINISTIC client id but
    the operation never recorded it (UNKNOWN without external_id). The bare
    ``poll`` the old probe used raises before querying the server, so force
    could fail a sample whose accepted prompt is positively recoverable by
    client-id reconciliation. Recoverability must be determined through the
    RECOVERY path; force still refuses."""
    world, ep, plan, service, comfy, adapter, slot, operation, authorization, digest, raw = (
        _crash_state(db, tmp_path, operation_state="UNKNOWN", with_prompt=False)
    )
    fixed = _fixed(world, comfy, adapter, authorization, digest, raw)
    experiment_id = plan.experiment_id
    svc = _service_for(fixed)

    # The POST did land: the server holds the prompt under the deterministic
    # client id, and the fake server completes it.
    key = f"benchmark:{experiment_id}:sample:S01-R1:a1"
    FakeComfyClient(comfy.server).queue_prompt(_valid_fake_graph(), client_id=render_client_id(key))
    comfy.clock.advance(seconds=5)
    with db.transaction(readonly=True) as tx:
        state = tx.fetchval("SELECT state FROM provider_operations WHERE id=%s", (operation["id"],))
        assert state == "UNKNOWN" and _sample_row(db, experiment_id, slot["sample_id"])

    args = dict(
        sample_id=slot["sample_id"],
        actor_ref="operator-console",
        reason="provider console evidence",
        evidence_sha256="7" * 64,
        world=adapter,
    )
    # Positively recoverable: even --force-unrecoverable refuses.
    with pytest.raises(Conflict, match="recoverable"):
        svc.resolve_sample(experiment_id, **args, force_unrecoverable=True)

    # And reconciliation - the owner of recoverable work - completes it.
    with _PatchedPolicy():
        svc.reconcile(experiment_id, world=adapter)
    recovered = _sample_row(db, experiment_id, slot["sample_id"])
    assert recovered["state"] == "SUCCEEDED" and recovered["output"]["sha256"]


class _CleanupReadGuard:
    """Boundary injection of the canonical request guard
    (``live_world.durable_comfy_request_guard``): through any non-RECOVERY
    world, every scoped live read of an EXPIRED-but-retained hold is denied -
    AT-20 proves CLEANUP is never on the §3.3 exception list, and the
    canonical guard requires an ACTIVE reservation (live_world.py:353-360).
    Only the live reads (poll / reconcile_unknown) are wrapped; the audited
    DB writes (resolve_unknown_operation, settle_terminal) are not HTTP and
    stay available, exactly as in the real composition."""

    def __init__(self, comfy, db: Database):
        self._comfy = comfy
        self._db = db

    def _guard(self, operation_id: UUID) -> None:
        with self._db.transaction(readonly=True) as tx:
            row = tx.fetchone(
                "SELECT r.state FROM provider_operations o "
                "JOIN reservations r ON r.id=o.reservation_id WHERE o.id=%s",
                (operation_id,),
            )
        if row is not None and row["state"] == "EXPIRED":
            raise EffectDenied("ComfyUI HTTP request lacks a matching active reservation/job")

    def poll(self, operation_id: UUID):
        self._guard(operation_id)
        return self._comfy.poll(operation_id)

    def reconcile_unknown(self, operation_id: UUID):
        self._guard(operation_id)
        return self._comfy.reconcile_unknown(operation_id)

    def __getattr__(self, name):
        return getattr(self._comfy, name)


class _GuardedCleanupWorld:
    """The fixture adapter with its live comfy reads behind the canonical
    EXPIRED-read denial - what a real non-RECOVERY composition enforces."""

    def __init__(self, adapter, db: Database):
        self._adapter = adapter
        self.comfy = _CleanupReadGuard(adapter.comfy, db)

    def __getattr__(self, name):
        return getattr(self._adapter, name)


def test_hc3_expired_hold_recovery_read_refuses_force(db: Database, tmp_path: Path) -> None:
    """HC-3 (second exposure): the sample's PROMPT hold expired (exposure
    retained) while its accepted prompt completed on the server. The EXPIRED
    recovery-read exception admits RECOVERY only, so the operator probe's
    CLEANUP composition cannot read the history at all - the recoverable
    operation used to look unreachable and force would fail it. The probe must
    read through a RECOVERY composition (no fixture world is handed in: the
    service composes its own, as the operator path does); force still
    refuses."""
    from test_t031_h2b_p1_modes import _paid_settings

    from microdrama.pipeline.benchmark_service import BenchmarkService

    world, ep, plan, service, comfy, adapter, slot, operation, authorization, digest, raw = (
        _crash_state(db, tmp_path, operation_state="UNKNOWN", with_prompt=True)
    )
    experiment_id = plan.experiment_id

    sample = _sample_row(db, experiment_id, slot["sample_id"])
    with db.transaction() as tx:
        tx.execute(
            "UPDATE reservations SET state='EXPIRED',closed_at=%s,closed_reason=%s WHERE id=%s",
            (comfy.clock.now(), "expired before recovery read (fixture)", sample["reservation_id"]),
        )
    comfy.clock.advance(seconds=5)

    # A mode-honoring world factory (what production composes): RECOVERY gets
    # the §3.3 read exception; every other mode gets the canonical EXPIRED
    # read denial. The modes record proves which composition the probe used.
    modes: list[str] = []

    def factory(
        *,
        experiment_id,
        budget,
        authorization=None,
        quote=None,
        mode="EXECUTE",
        acquisition_id=None,
    ):
        modes.append(mode)
        if mode == "RECOVERY":
            return adapter
        return _GuardedCleanupWorld(adapter, db)

    svc = BenchmarkService(
        db, _paid_settings(), clock=comfy.clock, ids=world.ids, world_factory=factory
    )

    with pytest.raises(Conflict, match="recoverable"):
        svc.resolve_sample(
            experiment_id,
            sample_id=slot["sample_id"],
            actor_ref="operator-console",
            reason="provider console evidence",
            evidence_sha256="7" * 64,
            force_unrecoverable=True,
        )
    # The recoverability probe read through a RECOVERY composition - never
    # through the resolution's CLEANUP world.
    assert "CLEANUP" in modes and "RECOVERY" in modes

    # Reconciliation composes its own RECOVERY world per acquisition and reads
    # through the EXPIRED-but-retained hold (§3.3): the work completes.
    with _PatchedPolicy():
        svc.reconcile(experiment_id)
    recovered = _sample_row(db, experiment_id, slot["sample_id"])
    assert recovered["state"] == "SUCCEEDED" and recovered["output"]["sha256"]


# ---------------------------------------------------------------------------
# HC-4 - every terminal replay completes ALL finalization stages.
# ---------------------------------------------------------------------------


def _terminal_crash(db, tmp_path, *, clear_slot: bool, settle: bool):
    """A FAILED operation whose sample projection committed but whose slot
    clear and R6 fail-fast outcome writes did not (the crash windows HC-4
    names): the sample is FAILED, the matching slot may still be occupied and
    the experiment outcome may still be unset."""
    world, ep, plan, service, comfy, adapter, slot, operation, authorization, digest, raw = (
        _crash_state(db, tmp_path, operation_state="FAILED")
    )
    fixed = _fixed(world, comfy, adapter, authorization, digest, raw)
    with db.transaction() as tx:
        tx.execute(
            "UPDATE benchmark_samples SET state='FAILED',operation_id=%s,"
            "output=%s WHERE experiment_id=%s AND sample_id=%s",
            (
                operation["id"],
                jsonb({"error_code": "UNKNOWN_FAILURE"}),
                plan.experiment_id,
                slot["sample_id"],
            ),
        )
        if clear_slot:
            tx.execute(
                "UPDATE benchmark_dispatch_slots SET sample_id=NULL WHERE experiment_id=%s",
                (plan.experiment_id,),
            )
        if settle:
            tx.execute(
                "UPDATE reservations SET state='SETTLED',closed_at=%s,closed_reason=%s WHERE id=%s",
                (
                    comfy.clock.now(),
                    "settled before outcome repair (fixture)",
                    slot["reservation_id"],
                ),
            )
    return fixed, plan, comfy, slot, operation


def test_hc4_replay_repairs_matching_slot_and_failfast(db: Database, tmp_path: Path) -> None:
    """HC-4: a terminal sample with its matching slot still occupied is repaired
    by the replay - the slot clears and the R6 fail-fast outcome is restored
    atomically, while the terminal sample state itself is preserved."""
    fixed, plan, comfy, slot, operation = _terminal_crash(
        db, tmp_path, clear_slot=False, settle=True
    )
    svc = _service_for(fixed)

    with _PatchedPolicy():
        svc.reconcile(plan.experiment_id, world=fixed["adapter"])

    with db.transaction(readonly=True) as tx:
        occupied = tx.fetchval(
            "SELECT sample_id FROM benchmark_dispatch_slots WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
        outcome = tx.fetchval(
            "SELECT execution_outcome FROM benchmark_experiments WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
        state = tx.fetchval(
            "SELECT state FROM benchmark_samples WHERE experiment_id=%s AND sample_id=%s",
            (plan.experiment_id, slot["sample_id"]),
        )
    assert occupied is None, "the matching slot must clear on replay"
    assert outcome == "FAILED", "the R6 fail-fast outcome must be restored on replay"
    assert state == "FAILED"  # terminal state preserved, never overwritten


def test_hc4_u4_includes_missing_failed_outcome(db: Database, tmp_path: Path) -> None:
    """HC-4: a FAILED sample whose slot cleared and hold settled but whose R6
    experiment outcome never committed is U4 - the missing fail-fast
    projection blocks fresh work until the replay repairs it."""
    fixed, plan, comfy, slot, operation = _terminal_crash(
        db, tmp_path, clear_slot=True, settle=True
    )
    svc = _service_for(fixed)

    assert "U4" in _kinds(db, plan.experiment_id, comfy.clock)
    with _PatchedPolicy():
        svc.reconcile(plan.experiment_id, world=fixed["adapter"])
    assert "U4" not in _kinds(db, plan.experiment_id, comfy.clock)
    with db.transaction(readonly=True) as tx:
        outcome = tx.fetchval(
            "SELECT execution_outcome FROM benchmark_experiments WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
    assert outcome == "FAILED"


def test_hc4_success_never_projects_without_durable_assets(db: Database, tmp_path: Path) -> None:
    """HC-4: a SUCCEEDED operation row whose outputs exist only in
    last_result - no durable asset registered for the attempt - never projects
    SUCCEEDED; U4 keeps blocking (the fabricated shape AT-22 seeded)."""
    world, ep, plan, service, comfy, adapter, slot, operation, authorization, digest, raw = (
        _crash_state(db, tmp_path, operation_state="SUCCEEDED", with_prompt=True)
    )
    fixed = _fixed(world, comfy, adapter, authorization, digest, raw)
    experiment_id = plan.experiment_id
    svc = _service_for(fixed)

    fabricated = {
        "state": "SUCCEEDED",
        "outputs": [
            {
                "provider_ref": "t031/fabricated.mp4",
                "sha256": "c" * 64,
                "media_type": "video/mp4",
                "size_bytes": 4,
            }
        ],
    }
    with db.transaction() as tx:
        tx.execute(
            "UPDATE provider_operations SET last_result=%s WHERE id=%s",
            (jsonb(fabricated), operation["id"]),
        )

    with _PatchedPolicy():
        svc.reconcile(experiment_id, world=adapter)
    sample = _sample_row(db, experiment_id, slot["sample_id"])
    assert sample["state"] != "SUCCEEDED", "no durable asset: never a success projection"
    assert "U4" in _kinds(db, experiment_id, comfy.clock)


def test_hc4_success_projection_carries_the_durable_asset(db: Database, tmp_path: Path) -> None:
    """HC-4: the real flow - an UNKNOWN prompt that completed server-side -
    reconciles to SUCCEEDED with the projection's output taken from the
    durable asset the completion registered."""
    world, ep, plan, service, comfy, adapter, slot, operation, authorization, digest, raw = (
        _crash_state(db, tmp_path, operation_state="UNKNOWN", with_prompt=True)
    )
    fixed = _fixed(world, comfy, adapter, authorization, digest, raw)
    experiment_id = plan.experiment_id
    svc = _service_for(fixed)

    comfy.clock.advance(seconds=5)
    with _PatchedPolicy():
        svc.reconcile(experiment_id, world=adapter)

    sample = _sample_row(db, experiment_id, slot["sample_id"])
    assert sample["state"] == "SUCCEEDED"
    with db.transaction(readonly=True) as tx:
        asset = tx.fetchone(
            "SELECT descriptor FROM assets WHERE generation_key=("
            "SELECT request_hash FROM provider_operations WHERE id=%s) ORDER BY id LIMIT 1",
            (operation["id"],),
        )
    assert asset is not None, "the real flow registers the durable asset"
    assert sample["output"]["sha256"] == asset["descriptor"]["sha256"]
