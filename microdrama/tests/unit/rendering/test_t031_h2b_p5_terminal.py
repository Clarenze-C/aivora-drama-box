"""T031 H-2 build, package P5 (spec v3 §7): terminal finalization, mapping,
monotonic projection, R6 atomic fail-fast and the operator resolution with the
R7 live-source matrix. AT-8, AT-9, AT-12, AT-22 (+ the §9.3 extensions).

Public entry points only: BenchmarkService.execute/resume/reconcile/
resolve_create/resolve_sample/sweep and the CLI main().
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from test_t031_h2b_p1_modes import (
    _authorization_pair,
    _bench_seal,
    _execute_service,
    _paid_settings,
    _PatchedPolicy,
    _screen_quote,
)
from test_t031_h2b_p2_gate import _at14_context, _seed_sample_operation
from test_t031_h2b_p3_ambiguity import _crash_state

from microdrama.contracts.errors import Conflict, PolicyDenied
from microdrama.persistence import Database
from microdrama.persistence.db import jsonb
from microdrama.pipeline.benchmark_service import BenchmarkService

pytestmark = pytest.mark.db


def _base(db: Database, tmp_path: Path):
    # One composed world (the AT-14 context): an ACTIVE acquisition with a
    # live pod, the first sample claimed - the two-world mix of the parked WIP
    # collided on the deterministic account ids.
    world, ep, plan, service, comfy, adapter, budget, acquisition = _at14_context(db, tmp_path)
    service.seal(plan.experiment_id, _bench_seal(plan))
    _, authorization, digest, raw = _authorization_pair(world, plan, tmp_path)
    return world, ep, plan, service, comfy, adapter, authorization, digest, raw


def _service_for(fixed):
    return _execute_service(fixed["world"].db, fixed["comfy"], fixed["world"].ids, fixed["adapter"])


def _counts(db: Database, experiment_id: UUID) -> dict[str, int]:
    with db.transaction(readonly=True) as tx:
        return {
            "acquisitions": tx.fetchval(
                "SELECT COUNT(*) FROM benchmark_acquisitions WHERE experiment_id=%s",
                (experiment_id,),
            ),
            "operations": tx.fetchval(
                "SELECT COUNT(*) FROM provider_operations o JOIN benchmark_samples s "
                "ON s.reservation_id=o.reservation_id WHERE s.experiment_id=%s",
                (experiment_id,),
            ),
            "charges": tx.fetchval(
                "SELECT COUNT(DISTINCT receipt_id) FROM charges c JOIN reservations r "
                "ON r.id=c.reservation_id JOIN benchmark_reservation_links l "
                "ON l.reservation_id=r.id WHERE l.experiment_id=%s",
                (experiment_id,),
            ),
            "operator_audits": tx.fetchval(
                "SELECT COUNT(*) FROM domain_events WHERE event_type="
                "'provider_operation.operator_resolved'"
            ),
        }


# ---------------------------------------------------------------------------
# AT-8 + the §9.3 R7 extension — the operator resolution and its replay.
# ---------------------------------------------------------------------------


def test_at08_replayed_resolve_after_resolution_commit_converges(db: Database, tmp_path: Path):
    world, ep, plan, service, comfy, adapter, slot, operation, authorization, digest, raw = (
        _crash_state(db, tmp_path, operation_state="UNKNOWN", with_prompt=True)
    )
    fixed = {
        "world": world,
        "comfy": comfy,
        "adapter": adapter,
        "authorization": authorization,
        "digest": digest,
        "raw": raw,
    }
    experiment_id = plan.experiment_id

    # The crash window AT-8 names: the operator resolution COMMITTED (audit
    # event + terminal FAILED transition, through the comfy layer) but the
    # finalization (settlement completion, projection, slot clear) never ran.
    # (The prompt WAS submitted - submitted_at is durable on the operation.)
    with db.transaction() as tx:
        tx.execute(
            "UPDATE provider_operations SET submitted_at=%s WHERE id=%s",
            (comfy.clock.now(), operation["id"]),
        )
    comfy.service.resolve_unknown_operation(
        operation["id"],
        actor_ref="operator-console",
        reason="provider console shows the prompt failed",
        evidence_sha256="8" * 64,
    )
    with db.transaction(readonly=True) as tx:
        mid = tx.fetchone("SELECT state FROM provider_operations WHERE id=%s", (operation["id"],))
        sample_mid = tx.fetchone(
            "SELECT state, operation_id FROM benchmark_samples WHERE experiment_id=%s "
            "AND sample_id=%s",
            (experiment_id, slot["sample_id"]),
        )
    assert mid["state"] == "FAILED"
    assert sample_mid["state"] != "FAILED" and sample_mid["operation_id"] is None

    # The REPLAYED resolve succeeds idempotently (§7.3 replay before anything).
    replayed = _service_for(fixed).resolve_sample(
        experiment_id,
        sample_id=slot["sample_id"],
        actor_ref="operator-console",
        reason="provider console shows the prompt failed",
        evidence_sha256="8" * 64,
        world=adapter,
    )
    assert {s["sample_id"]: s["state"] for s in replayed["samples"]}[slot["sample_id"]] == (
        "FAILED"
    )
    assert replayed["execution_outcome"] == "FAILED"  # §7.4 fail-fast, once
    counts_after_replay = _counts(db, experiment_id)
    assert counts_after_replay["operator_audits"] == 1  # ONE audit row
    assert counts_after_replay["charges"] == 1  # ONE settlement

    # A second replay (the crash repeated at the next boundary) changes nothing.
    again = _service_for(fixed).resolve_sample(
        experiment_id,
        sample_id=slot["sample_id"],
        actor_ref="operator-console",
        reason="provider console shows the prompt failed",
        evidence_sha256="8" * 64,
        world=adapter,
    )
    assert again["execution_outcome"] == "FAILED"
    assert _counts(db, experiment_id) == counts_after_replay  # I6: no duplicates

    # reconcile runs finalize_terminal for the U4 item the crash left: the
    # slot clears and the financial finalization completes through billing
    # closure (the sweep finishes the pod cleanup).
    with _PatchedPolicy():
        _service_for(fixed).reconcile(experiment_id, world=adapter)
    with db.transaction(readonly=True) as tx:
        slot_row = tx.fetchone(
            "SELECT sample_id FROM benchmark_dispatch_slots WHERE experiment_id=%s",
            (experiment_id,),
        )
        reservation_state = tx.fetchval(
            "SELECT state FROM reservations WHERE id=%s", (slot["reservation_id"],)
        )
    assert slot_row["sample_id"] is None
    assert reservation_state in ("SETTLED", "RELEASED")
    assert _counts(db, experiment_id) == counts_after_replay


def test_at08b_r7_binding_recoverability_force_matrix(db: Database, tmp_path: Path):
    """§9.3 (AT-8/AT-25 extension): the binding x recoverability x force
    matrix, with identical replay accepted BEFORE any live-source check."""
    world, ep, plan, service, comfy, adapter, slot, operation, authorization, digest, raw = (
        _crash_state(db, tmp_path, operation_state="UNKNOWN", with_prompt=True)
    )
    fixed = {
        "world": world,
        "comfy": comfy,
        "adapter": adapter,
        "authorization": authorization,
        "digest": digest,
        "raw": raw,
    }
    experiment_id = plan.experiment_id
    service = _service_for(fixed)
    args = dict(
        sample_id=slot["sample_id"],
        actor_ref="operator-console",
        reason="provider console evidence",
        evidence_sha256="7" * 64,
    )

    with db.transaction(readonly=True) as tx:
        acquisition_id = tx.fetchval(
            "SELECT acquisition_id FROM benchmark_samples WHERE experiment_id=%s AND sample_id=%s",
            (plan.experiment_id, slot["sample_id"]),
        )
    assert adapter.bind_for_recovery(acquisition_id) == "BOUND"  # live pod, endpoint

    # BOUND with POSITIVELY RECOVERABLE work: the prompt COMPLETED on the
    # server - reconciliation owns it; even force refuses. (The refusal's
    # probe poll may adopt the terminal outcome durably - that IS the
    # reconciliation owning it - so the forced retry refuses on terminal
    # provenance, and reconcile then completes the recovery.)
    comfy.clock.advance(seconds=5)
    with pytest.raises(Conflict, match="recoverable work"):
        service.resolve_sample(experiment_id, **args, world=adapter)
    with pytest.raises(Conflict):
        service.resolve_sample(experiment_id, **args, world=adapter, force_unrecoverable=True)
    with _PatchedPolicy():
        service.reconcile(experiment_id, world=adapter)
    with db.transaction(readonly=True) as tx:
        adopted = tx.fetchone(
            "SELECT state, output FROM benchmark_samples WHERE experiment_id=%s AND sample_id=%s",
            (experiment_id, slot["sample_id"]),
        )
    assert adopted["state"] == "SUCCEEDED" and adopted["output"]["sha256"]


def test_at08b_r7_verified_source_gone_resolves_without_force(db: Database, tmp_path: Path):
    """R7 (continued): VERIFIED_SOURCE_GONE - a verified-terminated source with
    an unresolved UNKNOWN operation resolves ORDINARILY (no force needed)."""
    world, ep, plan, service, comfy, adapter, slot, operation, authorization, digest, raw = (
        _crash_state(db, tmp_path, operation_state="UNKNOWN", with_prompt=False)
    )
    fixed = {
        "world": world,
        "comfy": comfy,
        "adapter": adapter,
        "authorization": authorization,
        "digest": digest,
        "raw": raw,
    }
    with db.transaction(readonly=True) as tx:
        acquisition_id = tx.fetchval(
            "SELECT acquisition_id FROM benchmark_samples WHERE experiment_id=%s AND sample_id=%s",
            (plan.experiment_id, slot["sample_id"]),
        )
    with db.transaction() as tx:
        tx.execute(
            "UPDATE pod_leases SET terminate_verified_at=%s WHERE id=("
            "SELECT lease_id FROM benchmark_acquisitions WHERE acquisition_id=%s)",
            (comfy.clock.now(), acquisition_id),
        )
    assert adapter.bind_for_recovery(acquisition_id) == "VERIFIED_SOURCE_GONE"
    gone = _service_for(fixed).resolve_sample(
        plan.experiment_id,
        sample_id=slot["sample_id"],
        actor_ref="operator-console",
        reason="provider console evidence",
        evidence_sha256="7" * 64,
        world=adapter,
    )
    assert gone["execution_outcome"] == "FAILED"


def test_at08b_r7_bound_unrecoverable_forces_and_replays(db: Database, tmp_path: Path):
    """R7 (continued): BOUND but the history never shows the prompt -
    reachable-but-unrecoverable: force is required and recorded; the identical
    forced attestation replays successfully before any live-source check."""
    world2, ep2, plan2, service2, comfy2, adapter2, slot2, op2, auth2, d2, r2 = _crash_state(
        db, tmp_path, operation_state="UNKNOWN", with_prompt=False
    )
    fixed2 = {
        "world": world2,
        "comfy": comfy2,
        "adapter": adapter2,
        "authorization": auth2,
        "digest": d2,
        "raw": r2,
    }
    service2 = _service_for(fixed2)
    with db.transaction(readonly=True) as tx:
        acquisition2 = tx.fetchval(
            "SELECT acquisition_id FROM benchmark_samples WHERE experiment_id=%s AND sample_id=%s",
            (plan2.experiment_id, slot2["sample_id"]),
        )
    assert adapter2.bind_for_recovery(acquisition2) == "BOUND"
    with pytest.raises(PolicyDenied, match="force-unrecoverable"):
        service2.resolve_sample(
            plan2.experiment_id,
            sample_id=slot2["sample_id"],
            actor_ref="operator-console",
            reason="provider console evidence",
            evidence_sha256="7" * 64,
            world=adapter2,
        )
    resolved = service2.resolve_sample(
        plan2.experiment_id,
        sample_id=slot2["sample_id"],
        actor_ref="operator-console",
        reason="provider console evidence",
        evidence_sha256="7" * 64,
        force_unrecoverable=True,
        world=adapter2,
    )
    assert resolved["execution_outcome"] == "FAILED"

    # IDENTICAL REPLAY before any live-source check: even with the source now
    # BOUND carrying recoverable work (a completed prompt appears), the
    # identical attestation replays successfully.
    _service_for(fixed2).reconcile(plan2.experiment_id, world=adapter2)
    replay = service2.resolve_sample(
        plan2.experiment_id,
        sample_id=slot2["sample_id"],
        actor_ref="operator-console",
        reason="provider console evidence",
        evidence_sha256="7" * 64,
        force_unrecoverable=True,  # same recorded attestation
        world=adapter2,
    )
    assert replay["execution_outcome"] == "FAILED"


# ---------------------------------------------------------------------------
# AT-9 — crash at every boundary (parametrised over the transaction
# inventory): each durable state a committed transaction can leave behind,
# then a public replay; convergence with no duplicate rows.
# ---------------------------------------------------------------------------


def _seed_terminal(db, plan, comfy, state, *, error_code=None, outputs=None):
    """A sample operation in a TERMINAL state with its recorded result - the
    durable state after record_result committed and before the benchmark
    projection (the AT-22a / R6 crash windows). HC-4 (HCF round): the real
    success flow registers the durable assets BEFORE the terminal result is
    recorded, so a seeded SUCCEEDED operation seeds its assets too - the
    finalization projects from the durable registry, never from last_result."""
    with db.transaction(readonly=True) as tx:
        reservation_id = tx.fetchval(
            "SELECT reservation_id FROM benchmark_samples WHERE experiment_id=%s "
            "AND sample_id='S01-R1'",
            (plan.experiment_id,),
        )
    operation_id = _seed_sample_operation(
        db,
        plan,
        "S01-R1",
        "SUBMITTED",
        comfy.clock,
        comfy,
        reservation_id=reservation_id,
        slot=True,
        external_id=f"seeded-{state.lower()}",
    )
    result = {"operation_id": str(operation_id), "state": state, "outputs": outputs or []}
    if error_code:
        result["error_code"] = error_code
    with db.transaction() as tx:
        tx.execute(
            "UPDATE provider_operations SET state=%s, last_result=%s, submitted_at=%s WHERE id=%s",
            (state, jsonb(result), comfy.clock.now(), operation_id),
        )
    if outputs:
        from microdrama.contracts.enums import AssetKind, AssetState, Provenance
        from microdrama.contracts.media import AssetDescriptor, MediaInfo
        from microdrama.persistence.assets import register_asset

        with db.transaction(readonly=True) as tx:
            request_hash = tx.fetchval(
                "SELECT request_hash FROM provider_operations WHERE id=%s", (operation_id,)
            )
        with db.transaction() as tx:
            for output in outputs:
                audio = "audio" in output["media_type"]
                register_asset(
                    tx,
                    AssetDescriptor(
                        asset_id=uuid4(),
                        asset_kind=AssetKind.AUDIO if audio else AssetKind.VIDEO,
                        object_key=output["provider_ref"],
                        sha256=output["sha256"],
                        size_bytes=output["size_bytes"],
                        media_type=output["media_type"],
                        media=MediaInfo(
                            duration_ms=1000,
                            has_video=not audio,
                            has_audio=audio,
                            width=64 if not audio else None,
                            height=64 if not audio else None,
                            fps_num=24 if not audio else None,
                            fps_den=1 if not audio else None,
                        ),
                        state=AssetState.PROVISIONAL,
                        provenance=Provenance.FAKE_SYNTHETIC,
                        created_at=comfy.clock.now(),
                    ),
                    generation_key=request_hash,
                )
    return operation_id


@pytest.mark.parametrize(
    "boundary",
    [
        "submit_ambiguity_before_labelling",
        "resolve_create_after_commit",
        "resolve_sample_after_commit",
        "ambiguity_handler_after_label",
        "sweep_finalization_mid",
    ],
)
def test_at09_crash_boundaries_converge(boundary: str, db: Database, tmp_path: Path):
    if boundary == "submit_ambiguity_before_labelling":
        # The submit POST was accepted, the result never committed, the
        # experiment never labelled: a fresh resume reconciles and converges.
        world, ep, plan, service, comfy, adapter, slot, operation, authorization, digest, raw = (
            _crash_state(db, tmp_path, operation_state="SUBMITTED", with_prompt=True)
        )
        with db.transaction() as tx:
            tx.execute(
                "UPDATE benchmark_experiments SET execution_state='SCREEN_RUNNING' "
                "WHERE experiment_id=%s",
                (plan.experiment_id,),
            )
        counts0 = _counts(db, plan.experiment_id)
        with _PatchedPolicy():
            last = None
            for _ in range(12):
                service = _execute_service(db, comfy, world.ids, adapter)
                last = service.resume(
                    plan.experiment_id,
                    authorization=authorization,
                    quote=_screen_quote(world),
                    expected_sha256=digest,
                    phase="screen",
                    source_bytes=raw,
                )
                comfy.clock.advance(seconds=1)
                if last["execution_state"] == "SCREEN_REVIEW":
                    break
        assert last["execution_state"] == "SCREEN_REVIEW"
        counts1 = _counts(db, plan.experiment_id)
        assert counts1["acquisitions"] == counts0["acquisitions"]
        # HC-10 (HCF): exact, never >= - the converged screen posts exactly
        # its canonical receipts (three zero-charge prompt settlements plus
        # the compute hold's accrual and settlement: five distinct ids, none
        # twice, across the replayed resume loop).
        assert counts1["charges"] == counts0["charges"] + 5
        with db.transaction(readonly=True) as tx:
            unique = tx.fetchval(
                "SELECT COUNT(*) = COUNT(DISTINCT receipt_id) FROM charges c "
                "JOIN reservations r ON r.id=c.reservation_id "
                "JOIN benchmark_reservation_links l ON l.reservation_id=r.id "
                "WHERE l.experiment_id=%s",
                (plan.experiment_id,),
            )
        assert unique is True  # no receipt id appears twice
        assert len(comfy.server.submissions) == 3  # one prompt per screen sample
        return

    if boundary == "resolve_create_after_commit":
        from test_t031_h2b_p4_resolution import _at6_context, _hold_states

        fixed = _at6_context(db, tmp_path)
        plan = fixed["plan"]
        _service_for(fixed).resolve_create(
            plan.experiment_id,
            acquisition_id=fixed["acquisition_id"],
            actor_ref="operator-console",
            reason="no pod",
            evidence_sha256="9" * 64,
        )
        counts0 = _counts(db, plan.experiment_id)
        # The replay + the owed sweep converge; nothing duplicates.
        service = _service_for(fixed)
        service.resolve_create(
            plan.experiment_id,
            acquisition_id=fixed["acquisition_id"],
            actor_ref="operator-console",
            reason="no pod",
            evidence_sha256="9" * 64,
        )
        service.sweep(plan.experiment_id)
        counts1 = _counts(db, plan.experiment_id)
        assert counts1 == counts0
        assert _hold_states(db, fixed["acquisition_id"])["STORAGE"] != "ACTIVE"
        return

    if boundary == "resolve_sample_after_commit":
        world, ep, plan, service, comfy, adapter, slot, operation, authorization, digest, raw = (
            _crash_state(db, tmp_path, operation_state="UNKNOWN", with_prompt=True)
        )
        comfy.service.resolve_unknown_operation(
            operation["id"],
            actor_ref="operator-console",
            reason="console evidence",
            evidence_sha256="9" * 64,
        )
        counts0 = _counts(db, plan.experiment_id)
        service = _execute_service(db, comfy, world.ids, adapter)
        service.resolve_sample(
            plan.experiment_id,
            sample_id=slot["sample_id"],
            actor_ref="operator-console",
            reason="console evidence",
            evidence_sha256="9" * 64,
            world=adapter,
        )
        service.reconcile(plan.experiment_id, world=adapter)
        assert _counts(db, plan.experiment_id) == counts0
        return

    if boundary == "ambiguity_handler_after_label":
        world, ep, plan, service, comfy, adapter, slot, operation, authorization, digest, raw = (
            _crash_state(db, tmp_path, operation_state="UNKNOWN", with_prompt=False)
        )
        with db.transaction() as tx:
            tx.execute(
                "UPDATE benchmark_acquisitions SET state='UNKNOWN' WHERE acquisition_id="
                "(SELECT acquisition_id FROM benchmark_samples WHERE experiment_id=%s "
                "AND sample_id=%s)",
                (plan.experiment_id, slot["sample_id"]),
            )
            tx.execute(
                "UPDATE benchmark_experiments SET execution_state='NEEDS_RECONCILIATION' "
                "WHERE experiment_id=%s",
                (plan.experiment_id,),
            )
        counts0 = _counts(db, plan.experiment_id)
        with _PatchedPolicy():
            service = _execute_service(db, comfy, world.ids, adapter)
            status = service.resume(
                plan.experiment_id,
                authorization=authorization,
                quote=_screen_quote(world),
                expected_sha256=digest,
                phase="screen",
                source_bytes=raw,
            )
        assert status["admission"]["permitted"] is False  # U1/U3 still owed
        service.sweep(plan.experiment_id, world=adapter)
        assert _counts(db, plan.experiment_id)["acquisitions"] == counts0["acquisitions"]
        return

    # sweep_finalization_mid (HC-10/HCF R4): a REAL subprocess crash between
    # the sweep's finalization stages. The child resolves the podless create
    # (stage R committed), then sweeps; the death lands AFTER the lease-close
    # stage committed and BEFORE the storage-release transaction - the next
    # sweep completes every remaining stage exactly once.
    import json
    import os
    import subprocess
    import sys

    from test_t031_h2b_p2_gate import RENDERING_TESTS, SRC_ROOT, UNIT_TESTS, _adapter_for
    from test_t031_h2b_p4_resolution import _at6_context, _hold_states

    marker = tmp_path / "at9-sweep-mid.marker"
    identity = tmp_path / "at9-sweep-mid-identity.json"

    script = (
        "import sys; sys.argv=['child']; "
        f"sys.path[:0] = [{str(SRC_ROOT)!r}, {str(UNIT_TESTS)!r}, {str(RENDERING_TESTS)!r}]; "
        "from test_t031_h2b_p5_terminal import _at9_sweep_mid_child as run; "
        f"run({db.dsn!r}, {str(tmp_path / 'at9-child-out')!r}, {str(marker)!r}, {str(identity)!r})"
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
    ids = json.loads(identity.read_text(encoding="utf-8"))
    experiment_id = UUID(ids["experiment_id"])
    acquisition_id = UUID(ids["acquisition_id"])
    lease_id = UUID(ids["lease_id"])

    # The durable state the mid-finalization crash leaves: the resolution and
    # the lease close committed (stages 1-2), the storage release never ran.
    with db.transaction(readonly=True) as tx:
        acquisition = tx.fetchone(
            "SELECT state FROM benchmark_acquisitions WHERE acquisition_id=%s", (acquisition_id,)
        )
        lease = tx.fetchone("SELECT lease_state FROM pod_leases WHERE id=%s", (lease_id,))
    assert acquisition["state"] == "NO_CREATE_PROVEN"
    assert lease["lease_state"] == "RELEASED", "the child's sweep closed the lease before dying"
    assert _hold_states(db, acquisition_id)["STORAGE"] == "ACTIVE", (
        "the crash must land BEFORE the storage-release stage"
    )
    counts_mid = _counts(db, experiment_id)

    # The parent process builds its own world from the durable provenance and
    # completes the finalization with ONE sweep; a second sweep changes
    # nothing (every stage exactly once).
    from dataclasses import replace as _replace

    from comfy_support import ComfyWorld
    from rendering_support import RenderWorld

    from microdrama.rendering.comfy_jobs import ComfyRenderConfig

    world = RenderWorld(db)
    comfy = ComfyWorld(
        db,
        tmp_path / "at9-parent-out",
        config=_replace(ComfyRenderConfig.for_mock(), lease_covered=True),
        execution_ms=0,
    )
    with db.transaction(readonly=True) as tx:
        experiment = tx.fetchone(
            "SELECT * FROM benchmark_experiments WHERE experiment_id=%s", (experiment_id,)
        )
    adapter, _budget = _adapter_for(db, world, comfy, experiment, experiment_id)
    comfy.clock.set(experiment["updated_at"] or experiment["created_at"])
    parent_service = BenchmarkService(
        db,
        _paid_settings(),
        clock=comfy.clock,
        ids=world.ids,
        world_factory=lambda **_kwargs: adapter,
    )
    parent_service.sweep(experiment_id, world=adapter)
    assert _hold_states(db, acquisition_id)["STORAGE"] == "RELEASED"
    counts_done = _counts(db, experiment_id)
    assert counts_done["acquisitions"] == counts_mid["acquisitions"] == 1
    assert counts_done["operator_audits"] == counts_mid["operator_audits"] == 0
    assert counts_done["operations"] == counts_mid["operations"] == 0
    # The storage release is a pure release (no new charge receipt): the
    # completed finalization posts NOTHING beyond what the crash left - the
    # exactly-once proof is the hold's own state transition plus these exact
    # counts.
    assert counts_done == counts_mid
    with db.transaction(readonly=True) as tx:
        resolution_rows = tx.fetchall(
            "SELECT * FROM runpod_podless_create_resolutions WHERE lease_id=%s", (lease_id,)
        )
    assert len(resolution_rows) == 1
    # The replay sweep completes nothing new.
    parent_service.sweep(experiment_id, world=adapter)
    assert _counts(db, experiment_id) == counts_done
    assert _hold_states(db, acquisition_id)["STORAGE"] != "ACTIVE"
    return


# ---------------------------------------------------------------------------
# AT-12 (R8) — the money projection identity across states and late
# adjustments.
# ---------------------------------------------------------------------------


def test_at12_r8_exposure_projection(db: Database, tmp_path: Path):
    from microdrama.rendering.benchmark_experiments import exposure

    # One composed world (the AT-14 context): an ACTIVE acquisition with a
    # live pod, the first sample claimed - the two-world mix of the parked WIP
    # collided on the deterministic account ids.
    world, ep, plan, service, comfy, adapter, budget, acquisition = _at14_context(db, tmp_path)
    service.seal(plan.experiment_id, _bench_seal(plan))
    from test_t031_h2b_p1_modes import _enter_submit_ambiguity

    _enter_submit_ambiguity(db, world, comfy, adapter, plan, tmp_path)
    experiment_id = plan.experiment_id

    def identity(tx_exposure):
        # R8: total == accrued + settled + max(reserved-accrued,0) for ACTIVE
        # only + distinct linked unreserved non-CREDIT usage.
        assert tx_exposure["total"] == (
            tx_exposure["accrued"]
            + tx_exposure["settled"]
            + tx_exposure["holds"]
            + tx_exposure["unreserved_settled"]
        )
        return tx_exposure

    with db.transaction(readonly=True) as tx:
        active = identity(exposure(tx, experiment_id))
    assert active["holds"] > 0  # the open remainder of the ACTIVE prompt hold

    # expire_stale(): the EXPIRED-but-unfinalized hold keeps the total EXACTLY
    # where it was (I4: expiry retains the exposure - the open hold component
    # drops to zero but the liability moves into the expired counters, never
    # vanishes). Only the audited settlement below may release the positively
    # unused remainder.
    comfy.clock.advance(seconds=601)
    budget.expire_stale()
    with db.transaction(readonly=True) as tx:
        expired = identity(exposure(tx, experiment_id))
    assert expired["holds"] < active["holds"]
    assert expired["total"] == active["total"]

    # The audited resolution settles the EXPIRED liability canonically, once.
    service = _execute_service(db, comfy, world.ids, adapter)
    with db.transaction(readonly=True) as tx:
        sample = tx.fetchone(
            "SELECT s.sample_id, s.reservation_id FROM benchmark_dispatch_slots d "
            "JOIN benchmark_samples s ON s.experiment_id=d.experiment_id "
            "AND s.sample_id=d.sample_id WHERE d.experiment_id=%s",
            (experiment_id,),
        )
    # HC-3 (T031 HCF): the timed-out POST was ACCEPTED, so the prompt is
    # positively recoverable by its deterministic client id and the operator
    # resolution would refuse even with force. The audited force resolution
    # needs the genuinely unrecoverable shape: the provider's queue and
    # history no longer show any prompt for the client id.
    from test_t031_h2b_p1_modes import _evict_prompt_history

    _evict_prompt_history(comfy, experiment_id, sample["sample_id"])
    resolved = service.resolve_sample(
        experiment_id,
        sample_id=sample["sample_id"],
        actor_ref="operator-console",
        reason="console evidence",
        evidence_sha256="c" * 64,
        force_unrecoverable=True,
        world=adapter,
    )
    assert resolved["execution_outcome"] == "FAILED"
    with db.transaction(readonly=True) as tx:
        settled = identity(exposure(tx, experiment_id))
        receipt_ids = tx.fetchall(
            "SELECT receipt_id FROM charges WHERE reservation_id=%s",
            (sample["reservation_id"],),
        )
    # The zero-charge settlement releases exactly the expired prompt hold's
    # former open remainder - the never-dispatched hold was positively unused.
    released = active["holds"] - expired["holds"]
    assert settled["total"] == active["total"] - released
    assert len({row["receipt_id"] for row in receipt_ids}) == len(receipt_ids)  # no dup

    # A LATE ADJUSTMENT (reopened liability) lands in the settled counters -
    # never in holds - and its identical replay never double counts.
    from uuid import uuid5

    from microdrama.contracts.cost import ReceiptKind, UsageReceipt
    from microdrama.contracts.enums import BudgetCategory, CostBasis, PriceUnit, Provenance

    with db.transaction(readonly=True) as tx:
        hold_provider = tx.fetchval(
            "SELECT provider FROM reservations WHERE id=%s", (sample["reservation_id"],)
        )
    receipt = UsageReceipt(
        receipt_id=uuid5(plan.experiment_id, "at12-late-adjustment"),
        provider=hold_provider,
        provider_receipt_id="at12-late",
        kind=ReceiptKind.ADJUSTMENT,
        # the offline world's canonical basis (leases.py uses exactly this
        # pair for its own late ADJUSTMENT receipts)
        cost_basis=CostBasis.SYNTHETIC_FAKE,
        reservation_id=sample["reservation_id"],
        episode_id=ep.episode_id,
        season_id=None,
        category=BudgetCategory.GPU_GENERATION,
        amount_micro_usd=1_000,
        currency="USD",
        units=4,
        unit=PriceUnit.GPU_SECOND,
        interval_start=None,
        interval_end=None,
        observed_at=comfy.clock.now(),
        provenance=Provenance.FAKE_SYNTHETIC,
    )
    budget.record_usage(receipt)
    budget.record_usage(receipt)  # the identical replay is a no-op
    with db.transaction(readonly=True) as tx:
        adjusted = identity(exposure(tx, experiment_id))
    assert adjusted["settled"] == settled["settled"] + 1_000
    assert adjusted["holds"] == settled["holds"]
    assert adjusted["total"] == settled["total"] + 1_000


# ---------------------------------------------------------------------------
# AT-22 (+ the R6 extension) — terminal commit before settlement; output
# persisted before the terminal commit; the R6 fail-fast projection for
# FAILED, CANCELLED and NOT_FOUND.
# ---------------------------------------------------------------------------


def test_at22_terminal_commit_before_settlement_recovers(db: Database, tmp_path: Path):
    # One composed world (the AT-14 context): an ACTIVE acquisition with a
    # live pod, the first sample claimed - the two-world mix of the parked WIP
    # collided on the deterministic account ids.
    world, ep, plan, service, comfy, adapter, budget, acquisition = _at14_context(db, tmp_path)
    service.seal(plan.experiment_id, _bench_seal(plan))

    with db.transaction(readonly=True) as tx:
        reservation_id = tx.fetchval(
            "SELECT reservation_id FROM benchmark_samples WHERE experiment_id=%s "
            "AND sample_id='S01-R1'",
            (plan.experiment_id,),
        )
    operation_id = _seed_terminal(
        db,
        plan,
        comfy,
        "SUCCEEDED",
        outputs=[
            {
                "name": "save_video:out.mp4",
                "media_type": "video/mp4",
                "provider_ref": "renders/at22.mp4",
                "sha256": "e" * 64,
                "size_bytes": 128,
                "complete": True,
            }
        ],
    )
    # The durable crash state: terminal commit DONE, settlement/projection/slot
    # never ran (AT-22a: financial and asset recovery converge).
    with db.transaction(readonly=True) as tx:
        mid = tx.fetchone(
            "SELECT state, operation_id FROM benchmark_samples WHERE experiment_id=%s "
            "AND sample_id='S01-R1'",
            (plan.experiment_id,),
        )
    assert mid["state"] != "SUCCEEDED" and mid["operation_id"] is None

    # The world=None path: reconcile composes its own RECOVERY worlds, and a
    # recovery world that does not NAME its acquisition refuses under HB-3
    # (§3.1) whenever the experiment has acquisitions - the naming factory
    # fails loudly on the regression.
    def naming_factory(**kwargs):
        assert kwargs.get("mode") != "RECOVERY" or kwargs.get("acquisition_id") is not None, (
            "a RECOVERY world must name the acquisition it recovers"
        )
        return adapter

    service = BenchmarkService(
        db,
        _paid_settings(),
        clock=comfy.clock,
        ids=world.ids,
        world_factory=naming_factory,
    )
    service.reconcile(plan.experiment_id)
    with db.transaction(readonly=True) as tx:
        after = tx.fetchone(
            "SELECT state, operation_id, output FROM benchmark_samples "
            "WHERE experiment_id=%s AND sample_id='S01-R1'",
            (plan.experiment_id,),
        )
        slot = tx.fetchone(
            "SELECT sample_id FROM benchmark_dispatch_slots WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
        reservation_state = tx.fetchval(
            "SELECT state FROM reservations WHERE id=%s", (reservation_id,)
        )
    assert after["state"] == "SUCCEEDED"
    assert str(after["operation_id"]) == str(operation_id)
    assert after["output"]["sha256"] == "e" * 64  # the durable output projected
    assert slot["sample_id"] is None
    assert reservation_state in ("SETTLED", "RELEASED")  # financial recovery


def test_at22b_output_persisted_before_terminal_recovers(db: Database, tmp_path: Path):
    (
        world,
        ep,
        plan,
        service,
        comfy,
        adapter,
        slot,
        operation,
        authorization,
        digest,
        raw,
    ) = _crash_state(db, tmp_path, operation_state="SUBMITTED", with_prompt=True)
    # The prompt COMPLETED on the server (its output bytes exist); the worker
    # died before recording anything. A fresh reconcile polls, persists the
    # output once and projects - idempotently.
    comfy.clock.advance(seconds=5)
    service = _execute_service(db, comfy, world.ids, adapter)
    with _PatchedPolicy():
        service.resume(
            plan.experiment_id,
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            phase="screen",
            source_bytes=raw,
        )
        second = service.resume(
            plan.experiment_id,
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            phase="screen",
            source_bytes=raw,
        )
    with db.transaction(readonly=True) as tx:
        sample = tx.fetchone(
            "SELECT state, output FROM benchmark_samples WHERE experiment_id=%s "
            "AND sample_id='S01-R1'",
            (plan.experiment_id,),
        )
        # S01's own attempt only - the screen may legitimately continue
        # past it (later samples get their own operations).
        ops = tx.fetchall(
            "SELECT id FROM provider_operations o JOIN benchmark_samples s "
            "ON s.reservation_id=o.reservation_id WHERE s.experiment_id=%s "
            "AND s.sample_id='S01-R1'",
            (plan.experiment_id,),
        )
        # The recovered output's own asset exists EXACTLY once under its
        # attempt-derived key (I6; persist_output is idempotent by asset id) -
        # the screen may legitimately continue past S01, and the fake server's
        # deterministic bytes make other samples' shas coincide.
        key_assets = tx.fetchall(
            "SELECT id FROM assets WHERE object_key=%s",
            (sample["output"]["object_key"],),
        )
    assert sample["state"] == "SUCCEEDED"
    assert sample["output"]["sha256"]
    assert len(key_assets) == 1
    assert len(ops) == 1  # one operation for the sample's attempt
    assert second["execution_state"] in ("SCREEN_RUNNING", "SCREEN_REVIEW", "NEEDS_RECONCILIATION")


@pytest.mark.parametrize("terminal_state", ["FAILED", "CANCELLED", "NOT_FOUND"])
def test_at09b_r6_failfast_projection(terminal_state: str, db: Database, tmp_path: Path):
    """§9.3 (AT-9/AT-22 extension, R6): a crash between the failed-operation
    settlement and the failed-sample/outcome/slot projection, for each of
    FAILED, CANCELLED and NOT_FOUND - reconcile's finalize_terminal repairs all
    of it idempotently, in one transaction's worth of effects."""
    # One composed world (the AT-14 context): an ACTIVE acquisition with a
    # live pod, the first sample claimed - the two-world mix of the parked WIP
    # collided on the deterministic account ids.
    world, ep, plan, service, comfy, adapter, budget, acquisition = _at14_context(db, tmp_path)
    service.seal(plan.experiment_id, _bench_seal(plan))

    _seed_terminal(db, plan, comfy, terminal_state, error_code=f"SEEDED_{terminal_state}")
    with db.transaction(readonly=True) as tx:
        mid = tx.fetchone(
            "SELECT state, operation_id FROM benchmark_samples WHERE experiment_id=%s "
            "AND sample_id='S01-R1'",
            (plan.experiment_id,),
        )
        slot_mid = tx.fetchone(
            "SELECT sample_id FROM benchmark_dispatch_slots WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
    assert mid["state"] != "FAILED" and mid["operation_id"] is None
    assert slot_mid["sample_id"] == "S01-R1"

    service = _execute_service(db, comfy, world.ids, adapter)
    service.reconcile(plan.experiment_id, world=adapter)
    service.reconcile(plan.experiment_id, world=adapter)  # the replay is idempotent
    with db.transaction(readonly=True) as tx:
        after = tx.fetchone(
            "SELECT state, output FROM benchmark_samples WHERE experiment_id=%s "
            "AND sample_id='S01-R1'",
            (plan.experiment_id,),
        )
        outcome = tx.fetchone(
            "SELECT execution_outcome, execution_state FROM benchmark_experiments "
            "WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
        slot = tx.fetchone(
            "SELECT sample_id FROM benchmark_dispatch_slots WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
    assert after["state"] == "FAILED"  # the §7.2 mapping keeps FAILED
    assert after["output"]["error_code"] == f"SEEDED_{terminal_state}"  # original reason
    assert outcome["execution_outcome"] == "FAILED"  # R6: set once
    assert slot["sample_id"] is None  # the dispatch slot cleared


# ---------------------------------------------------------------------------
# AT-9 sweep_finalization_mid — the §9.3 death harness for the sweep's
# finalization stages (HC-10/HCF R4: a REAL crash between the stages, not two
# completed sweeps).
# ---------------------------------------------------------------------------


class _DeathAfterLeaseClose:
    """Kills the sweep worker AFTER the lease-close stage committed and BEFORE
    the storage-release transaction - between the sweep's finalization stages
    (§9.3: ``os._exit`` bypasses every exception cleanup path; the marker file
    and the database are the only state that survives the killed process)."""

    def __init__(self, inner, marker: Path) -> None:
        self.inner = inner
        self.marker = marker

    def shutdown(self, lease_id, *, reason=None, **kwargs):
        self.inner.shutdown(lease_id, reason=reason, **kwargs)
        self.marker.write_text("lease-closed", encoding="utf-8")
        import os

        os._exit(86)  # §9.3: bypasses every exception cleanup path

    def __getattr__(self, name):
        return getattr(self.inner, name)


def _at9_sweep_mid_child(dsn: str, output_dir: str, marker: str, identity: str) -> None:
    """Runs INSIDE the subprocess: the real composed resolution, then the real
    sweep until death between its finalization stages. The caller's script
    prefix has already put SRC_ROOT/UNIT_TESTS/RENDERING_TESTS on sys.path."""
    import json
    from pathlib import Path

    from test_t031_h2b_p1_modes import _execute_service
    from test_t031_h2b_p4_resolution import _at6_context

    from microdrama.persistence import Database

    db = Database(dsn).open()
    fixed = _at6_context(db, Path(output_dir))
    plan = fixed["plan"]
    service = _execute_service(
        fixed["world"].db, fixed["comfy"], fixed["world"].ids, fixed["adapter"]
    )
    service.resolve_create(
        plan.experiment_id,
        acquisition_id=fixed["acquisition_id"],
        actor_ref="operator-console",
        reason="no pod",
        evidence_sha256="9" * 64,
    )
    # The death wrapper: the sweep dies right after the lease close commits.
    fixed["adapter"].leases = _DeathAfterLeaseClose(fixed["adapter"].leases, Path(marker))
    Path(identity).write_text(
        json.dumps(
            {
                "experiment_id": str(plan.experiment_id),
                "acquisition_id": str(fixed["acquisition_id"]),
                "lease_id": str(fixed["lease_id"]),
            }
        ),
        encoding="utf-8",
    )
    service.sweep(plan.experiment_id)
