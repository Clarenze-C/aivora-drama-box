"""T031 H-2 build, package P5 (spec v3 §7): terminal finalization, mapping,
monotonic projection, R6 atomic fail-fast and the operator resolution with the
R7 live-source matrix. AT-8, AT-9, AT-12, AT-22 (+ the §9.3 extensions).

Public entry points only: BenchmarkService.execute/resume/reconcile/
resolve_create/resolve_sample/sweep and the CLI main().
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

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
    projection (the AT-22a / R6 crash windows)."""
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
        assert counts1["charges"] >= counts0["charges"]  # canonical settlement only
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

    # sweep_finalization_mid: the resolution committed, the lease is still
    # live, the storage still held - the sweep finishes idempotently.
    from test_t031_h2b_p4_resolution import _at6_context, _hold_states

    fixed = _at6_context(db, tmp_path)
    plan = fixed["plan"]
    service = _service_for(fixed)
    service.resolve_create(
        plan.experiment_id,
        acquisition_id=fixed["acquisition_id"],
        actor_ref="operator-console",
        reason="no pod",
        evidence_sha256="9" * 64,
    )
    counts0 = _counts(db, plan.experiment_id)
    service.sweep(plan.experiment_id)
    service.sweep(plan.experiment_id)  # the replay converges, nothing doubles
    assert _counts(db, plan.experiment_id) == counts0
    assert _hold_states(db, fixed["acquisition_id"])["STORAGE"] != "ACTIVE"


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
