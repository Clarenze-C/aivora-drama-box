"""T031 H-2 HCF round, F2: HC-6 (the one ordered lock helper, L and S included)
and HC-5 (live coordinator ownership on every control write and the first-send
authorisation).

- a gate decision serialises behind a canonical L-only janitor adoption (the
  gate locks the lease rows it evaluates, not just A/D/R/O/uploads);
- ``_claim_sample`` validates BOTH durable tokens with live ownership leases,
  not the slot token's value alone;
- the ACTIVE control write requires the slot ownership too;
- the create-ambiguity control write refuses a fenced coordinator (the stale
  worker can no longer rewrite the old acquisition to UNKNOWN and collide
  with a newer acquisition's partial-index slot);
- the first-send right is consumed only inside a transaction that still sees
  the coordinator's live ownership - a coordinator fenced between the
  dispatch gate and the claim sends nothing and consumes nothing; a fresh
  coordinator then submits exactly once.
"""

from __future__ import annotations

import threading

import pytest
from test_t031_h2b_p1_modes import (
    _authorization_pair,
    _bench_seal,
    _drive_execute,
    _execute_service,
    _PatchedPolicy,
    _screen_quote,
)
from test_t031_h2b_p2_gate import _at14_context
from test_t031_h2b_p4_resolution import _at6_context

from microdrama.persistence import Database

pytestmark = pytest.mark.db


def _race_connection(db: Database, *, autocommit: bool = False):
    import psycopg

    conn = psycopg.connect(db.dsn, autocommit=autocommit)
    conn.execute("SET lock_timeout = '2500ms'")
    return conn


def _set_tokens(
    db: Database,
    experiment_id,
    acquisition_id,
    *,
    slot_token,
    acq_token,
):
    """Stamp the two durable coordinator tokens (NULL = fenced/revoked).

    A non-null token always carries a LIVE ownership lease (the staleness the
    tests inject is the token VALUE mismatch or revocation, never a lapsed
    lease - that shape is HB-7's, already covered)."""
    with db.transaction() as tx:
        tx.execute(
            "UPDATE benchmark_dispatch_slots SET coordinator_token=%s,"
            "coordinator_lease_until=CASE WHEN %s::uuid IS NULL THEN NULL "
            "ELSE NOW() + interval '1 hour' END WHERE experiment_id=%s",
            (slot_token, slot_token, experiment_id),
        )
        tx.execute(
            "UPDATE benchmark_acquisitions SET coordinator_token=%s,"
            "coordinator_lease_until=CASE WHEN %s::uuid IS NULL THEN NULL "
            "ELSE NOW() + interval '1 hour' END WHERE acquisition_id=%s",
            (acq_token, acq_token, acquisition_id),
        )


def test_hc6_gate_serialises_with_l_only_adoption(db: Database, tmp_path) -> None:
    """HC-6: the gate's lock set includes the canonical L rows it evaluates.

    A canonical janitor adoption holds only the lease row (L) while it binds
    the pod and contradicts a resolution; a gate transaction that omits L can
    proceed to its running-state or claim write on stale information. With the
    shared-order helper the gate BLOCKS behind the adoption lock, then
    evaluates the items (U1 refuses this admission).
    """
    from test_t031_h2b_p4_resolution import _bounded_worker_locks, _service

    fixed = _at6_context(db, tmp_path)
    plan = fixed["plan"]
    # HC-10 (HCF R4): the holder's lock_timeout alone proves nothing about the
    # worker - the WORKER connection gets the bounded session setting too
    # (every currently pooled connection, plus the database default for any
    # the pool opens later), so an unexpected lock wedge FAILS the test
    # instead of hanging it.
    _bounded_worker_locks(db)
    holder = _race_connection(db)
    holder.execute("BEGIN")
    holder.execute("SELECT 1 FROM pod_leases WHERE id=%s FOR UPDATE", (str(fixed["lease_id"]),))

    from microdrama.pipeline.benchmark_service import AdmissionBlocked

    outcome: dict = {}

    def run_gate():
        try:
            _service(fixed)._gate(plan.experiment_id, "admission")
            outcome["result"] = "allowed"
        except AdmissionBlocked as exc:
            outcome["result"] = "blocked"
            outcome["blockers"] = exc.blockers
        except BaseException as exc:  # noqa: BLE001 - recorded and asserted below
            outcome["result"] = f"error:{type(exc).__name__}:{exc}"

    thread = threading.Thread(target=run_gate)
    thread.start()
    thread.join(timeout=1.5)
    # The gate is still waiting behind the adoption's L lock.
    assert thread.is_alive(), (
        "the gate decision must lock the lease rows (L) it evaluates - it "
        "completed while a canonical L-only adoption held the lease"
    )
    holder.execute("COMMIT")
    holder.close()
    thread.join(timeout=15)
    assert outcome.get("result") == "blocked", outcome
    assert any("U1" in blocker for blocker in outcome["blockers"]), outcome


def test_hc5_claim_validates_full_coordination(db: Database, tmp_path) -> None:
    """HC-5: a claim is authorised only by BOTH durable tokens with live
    ownership leases - a slot token that still matches while the acquisition
    token was fenced is a stale coordinator (HB-7's probe shape). The healthy
    AT-14 world has no blocking items, so the refusal can only come from the
    ownership predicate."""
    import uuid

    from microdrama.pipeline.benchmark_service import AdmissionBlocked

    world, ep, plan, service, comfy, adapter, budget, acquisition = _at14_context(db, tmp_path)
    token = uuid.uuid4()
    # The slot still names this coordinator; the acquisition token was revoked
    # at the recovery deadline (the fence revokes both - partial staleness is
    # the probe's shape).
    _set_tokens(
        db,
        plan.experiment_id,
        acquisition["acquisition_id"],
        slot_token=token,
        acq_token=None,
    )
    resumed = _execute_service(db, comfy, world.ids, adapter)
    with pytest.raises(AdmissionBlocked):
        resumed._claim_sample(
            plan.experiment_id,
            adapter,
            acquisition,
            {"S01-R1", "S03-R1", "S07-R1"},
            coordinator_token=token,
        )
    with db.transaction(readonly=True) as tx:
        claimed = tx.fetchval(
            "SELECT COUNT(*) FROM benchmark_samples WHERE experiment_id=%s "
            "AND state='CLAIMED' AND reservation_id IS NULL",
            (plan.experiment_id,),
        )
    assert claimed == 0  # no NEW claim was made by the stale coordinator


def test_hc5_active_write_requires_slot_ownership(db: Database, tmp_path) -> None:
    """HC-5: the ACTIVE control write validates the full live ownership (both
    tokens), not the acquisition row alone - a coordinator whose slot token
    was fenced writes no control state."""
    import uuid

    from microdrama.pipeline.benchmark_service import AdmissionBlocked

    fixed = _at6_context(db, tmp_path)
    plan = fixed["plan"]
    token = uuid.uuid4()
    _set_tokens(
        db,
        plan.experiment_id,
        fixed["acquisition_id"],
        slot_token=None,
        acq_token=token,
    )
    service = _execute_service(
        fixed["world"].db, fixed["comfy"], fixed["world"].ids, fixed["adapter"]
    )
    with pytest.raises(AdmissionBlocked):
        service._activate_acquisition(
            plan.experiment_id, fixed["acquisition_id"], coordinator_token=token
        )
    with db.transaction(readonly=True) as tx:
        state = tx.fetchval(
            "SELECT state FROM benchmark_acquisitions WHERE acquisition_id=%s",
            (fixed["acquisition_id"],),
        )
    assert state != "ACTIVE"

    # Control: full live ownership writes ACTIVE.
    _set_tokens(
        db,
        plan.experiment_id,
        fixed["acquisition_id"],
        slot_token=token,
        acq_token=token,
    )
    service._activate_acquisition(
        plan.experiment_id, fixed["acquisition_id"], coordinator_token=token
    )
    with db.transaction(readonly=True) as tx:
        state = tx.fetchval(
            "SELECT state FROM benchmark_acquisitions WHERE acquisition_id=%s",
            (fixed["acquisition_id"],),
        )
    assert state == "ACTIVE"


def test_hc5_create_ambiguity_write_refuses_a_fenced_coordinator(db: Database, tmp_path) -> None:
    """HC-5: the create-ambiguity control write carries and validates the
    coordinator's live ownership. A stalled original create that returns after
    takeover and fencing must NOT rewrite its acquisition to UNKNOWN - the
    newer acquisition occupying the partial-index slot stays intact."""
    import uuid

    from microdrama.pipeline.benchmark_service import AdmissionBlocked

    fixed = _at6_context(db, tmp_path)
    plan = fixed["plan"]
    stale = uuid.uuid4()
    # A newer coordinator owns the slot; the stalled worker's token was fenced.
    _set_tokens(
        db,
        plan.experiment_id,
        fixed["acquisition_id"],
        slot_token=uuid.uuid4(),  # someone else's live slot token
        acq_token=None,  # the stale coordinator's acquisition token was revoked
    )
    with db.transaction() as tx:
        tx.execute(
            "UPDATE benchmark_acquisitions SET state='ADMITTED_WITHOUT_JOB' "
            "WHERE acquisition_id=%s",
            (fixed["acquisition_id"],),
        )
    service = _execute_service(
        fixed["world"].db, fixed["comfy"], fixed["world"].ids, fixed["adapter"]
    )
    with pytest.raises(AdmissionBlocked):
        service._mark_create_ambiguity(
            plan.experiment_id,
            {"acquisition_id": fixed["acquisition_id"], "lease_id": fixed["lease_id"]},
            fixed["adapter"],
            coordinator_token=stale,
        )
    with db.transaction(readonly=True) as tx:
        state = tx.fetchval(
            "SELECT state FROM benchmark_acquisitions WHERE acquisition_id=%s",
            (fixed["acquisition_id"],),
        )
    assert state == "ADMITTED_WITHOUT_JOB"  # the stale write never landed


def test_hc5_first_send_claim_requires_live_ownership(db: Database, tmp_path) -> None:
    """HC-5/SC2-1: the first-send right is consumed only by a coordinator whose
    ownership is STILL live inside the claim's own transaction. A coordinator
    fenced between the dispatch gate and the claim sends nothing and consumes
    nothing; the next (fresh) coordinator submits exactly once."""
    world, ep, plan, service, comfy, adapter, budget, acquisition = _at14_context(db, tmp_path)
    service.seal(plan.experiment_id, _bench_seal(plan))
    _, authorization, digest, raw = _authorization_pair(world, plan, tmp_path)

    import microdrama.rendering.comfy_jobs as comfy_jobs

    original_begin = comfy_jobs.begin
    revolved: dict = {"done": False}

    def revoking_begin(tx, **kwargs):
        if not revolved["done"]:
            revolved["done"] = True
            # The R3 fence lands between the dispatch gate and the claim: an
            # independent connection revokes both coordinator tokens while the
            # claim transaction is open.
            conn = _race_connection(db, autocommit=True)
            conn.execute(
                "UPDATE benchmark_dispatch_slots SET coordinator_token=NULL,"
                "coordinator_lease_until=NULL WHERE experiment_id=%s",
                (str(plan.experiment_id),),
            )
            conn.execute(
                "UPDATE benchmark_acquisitions SET coordinator_token=NULL,"
                "coordinator_lease_until=NULL WHERE acquisition_id=%s",
                (str(acquisition["acquisition_id"]),),
            )
            conn.close()
        return original_begin(tx, **kwargs)

    comfy_jobs.begin = revoking_begin
    try:
        first = _drive_execute(
            db, world, comfy, adapter, plan, authorization, digest, raw, phase="screen", limit=1
        )
    finally:
        comfy_jobs.begin = original_begin
    # The fenced coordinator consumed no first-send right and sent nothing.
    assert comfy.server.submissions == [], comfy.server.submissions
    with db.transaction(readonly=True) as tx:
        operations = tx.fetchall(
            "SELECT o.id FROM provider_operations o JOIN benchmark_samples s "
            "ON s.reservation_id=o.reservation_id WHERE s.experiment_id=%s",
            (plan.experiment_id,),
        )
    assert operations == []
    assert first["admission"]["permitted"] is False
    assert any("R3 fence" in blocker for blocker in first["admission"]["blockers"])

    # A fresh coordinator (a new resume pass takes its own token) submits once.

    with _PatchedPolicy():
        final = None
        for _ in range(8):
            resumed = _execute_service(db, comfy, world.ids, adapter)
            final = resumed.resume(
                plan.experiment_id,
                authorization=authorization,
                quote=_screen_quote(world),
                expected_sha256=digest,
                phase="screen",
                source_bytes=raw,
            )
            comfy.clock.advance(seconds=1)
            if final["execution_state"] in ("SCREEN_REVIEW", "FAILED", "NEEDS_RECONCILIATION"):
                break
    # Three screen samples, exactly one POST each - the refused (fenced)
    # attempt contributed none, so no sample was ever submitted twice.
    assert comfy.server.submissions == [
        "fake-prompt-0001",
        "fake-prompt-0002",
        "fake-prompt-0003",
    ], comfy.server.submissions
    assert final["execution_state"] == "SCREEN_REVIEW", final["execution_state"]
