"""T031 H-2 build, package P4 (spec v3 §6): the audited create resolution,
storage-hold finalization, the late-contradiction incident path and the shared
lock order. AT-6, AT-7 (+ the §9.3 extensions: resolve without adoption, R1
storage retention until sweep, SC2-3 attestation replay), AT-21 (lock races).

Public entry points only: BenchmarkService.execute/resume/reconcile/
resolve_create/resolve_sample/sweep and the CLI main().
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from rendering_support import RenderWorld
from test_benchmark_experiments import _composed_world
from test_t031_h2b_p1_modes import (
    _authorization_pair,
    _bench_seal,
    _execute_service,
    _PatchedPolicy,
    _screen_quote,
)
from test_t031_h2b_p2_gate import (
    _crash_seed_lease,
    _insert_acquisition,
    _item_kinds,
)

from microdrama.contracts.errors import Conflict, ServiceUnavailable
from microdrama.persistence import Database

pytestmark = pytest.mark.db


def _at6_context(db: Database, tmp_path: Path):
    """A sealed experiment whose generation-1 acquisition is U1 exactly: a
    committed create intent on a podless lease, COMPUTE + STORAGE holds linked
    like a real admission, no pod anywhere."""
    world = RenderWorld(db)
    ep, plan, service, budget, comfy, adapter = _composed_world(world, tmp_path)
    # The operator resolution (resolve_podless_create) is the runpod billing
    # path: the lease and its holds must be runpod-addressed like the
    # pre-existing operator-resolution fixtures (P2's AT-13 child).
    from test_t045_timing import RunpodIdFakePods

    from microdrama.rendering.leases import durable_created_pod_recorder

    inner = RunpodIdFakePods(clock=world.clock, ids=world.ids)
    inner.created_pod_recorder = durable_created_pod_recorder(world.db, world.clock.now)
    world.provider = inner
    world.manager._provider = inner
    service.seal(plan.experiment_id, _bench_seal(plan))
    # Admission first (its holds link to it), then the lease claim - the claim's
    # reserve links the lease reservation as this acquisition's COMPUTE hold,
    # exactly like a real admission, and the crash seed commits the create
    # intent without any pod.
    acquisition_id = _insert_acquisition(
        db,
        world,
        adapter,
        plan,
        generation=1,
        state="ADMITTED_WITHOUT_JOB",
        clock=comfy.clock,
    )
    lease_id = _crash_seed_lease(db, world, ep.episode_id, create_requested=True)
    with db.transaction() as tx:
        tx.execute(
            "UPDATE benchmark_acquisitions SET lease_id=%s WHERE acquisition_id=%s",
            (lease_id, acquisition_id),
        )
    quote = _screen_quote(world)
    with db.transaction(readonly=True) as tx:
        exp = tx.fetchone(
            "SELECT * FROM benchmark_experiments WHERE experiment_id=%s", (plan.experiment_id,)
        )
    intent = adapter.acquisition_requests(exp, quote, acquisition_id, 1, comfy.clock.now())
    from microdrama.contracts.cost import BudgetReservationRequest

    with db.transaction() as tx:
        budget.reserve_linked(
            tx,
            BudgetReservationRequest.model_validate(intent["storage"]),
            acquisition_id=acquisition_id,
            purpose="STORAGE",
        )
    _, authorization, digest, raw = _authorization_pair(world, plan, tmp_path)
    # The crash window labels the acquisition UNKNOWN only after admission
    # committed its holds (exactly the AT-13 crash-before-label state).
    with db.transaction() as tx:
        tx.execute(
            "UPDATE benchmark_acquisitions SET state='UNKNOWN' WHERE acquisition_id=%s",
            (acquisition_id,),
        )
        tx.execute(
            "UPDATE benchmark_experiments SET execution_state='NEEDS_RECONCILIATION' "
            "WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
    return {
        "world": world,
        "ep": ep,
        "plan": plan,
        "comfy": comfy,
        "adapter": adapter,
        "budget": budget,
        "acquisition_id": acquisition_id,
        "lease_id": lease_id,
        "authorization": authorization,
        "digest": digest,
        "raw": raw,
    }


def _hold_states(db: Database, acquisition_id: UUID) -> dict[str, str]:
    with db.transaction(readonly=True) as tx:
        rows = tx.fetchall(
            "SELECT l.purpose, r.state FROM benchmark_reservation_links l "
            "JOIN reservations r ON r.id=l.reservation_id WHERE l.acquisition_id=%s "
            "ORDER BY l.purpose",
            (acquisition_id,),
        )
    return {row["purpose"]: row["state"] for row in rows}


def _service(fixed: dict):
    return _execute_service(fixed["world"].db, fixed["comfy"], fixed["world"].ids, fixed["adapter"])


def _resolution_rows(db: Database, lease_id) -> list[dict]:
    with db.transaction(readonly=True) as tx:
        return tx.fetchall(
            "SELECT * FROM runpod_podless_create_resolutions WHERE lease_id=%s", (lease_id,)
        )


def test_at06_resolve_without_admission_keeps_storage_until_sweep_r1(db: Database, tmp_path: Path):
    fixed = _at6_context(db, tmp_path)
    plan = fixed["plan"]
    assert "U1" in _item_kinds(db, plan.experiment_id, fixed["comfy"].clock)

    resolved = _service(fixed).resolve_create(
        plan.experiment_id,
        acquisition_id=fixed["acquisition_id"],
        actor_ref="operator-console",
        reason="provider console shows no pod for the owned token",
        evidence_sha256="a" * 64,
    )
    holds = _hold_states(db, fixed["acquisition_id"])
    assert resolved["acquisitions"][0]["state"] == "NO_CREATE_PROVEN"
    (row,) = _resolution_rows(db, fixed["lease_id"])
    assert row["actor_ref"] == "operator-console" and row["evidence_sha256"] == "a" * 64
    # The compute hold closed through the canonical zero-BILLED settlement.
    assert holds["COMPUTE"] == "SETTLED"
    # §6.2 step 4 / §6.3: the resolution NEVER releases the STORAGE hold - only
    # the sweep finalization transaction may, after re-checking under lock.
    assert holds["STORAGE"] == "ACTIVE"
    kinds = _item_kinds(db, plan.experiment_id, fixed["comfy"].clock)
    assert "U1" not in kinds
    # R1: admission stays blocked until the STORAGE hold is canonically
    # finalised - the partial-index exclusion never authorizes the next
    # acquisition by itself. (Resume would sweep the owed cleanup first; the
    # gate itself is what must refuse, so this drives execute.)
    from microdrama.pipeline.benchmark_service import AdmissionBlocked

    with _PatchedPolicy():
        with pytest.raises(AdmissionBlocked) as refused:
            _service(fixed).execute(
                plan.experiment_id,
                phase="screen",
                authorization=fixed["authorization"],
                quote=_screen_quote(fixed["world"]),
                expected_sha256=fixed["digest"],
                source_bytes=fixed["raw"],
            )
    assert any("U2" in blocker and "R1" in blocker for blocker in refused.value.blockers), (
        refused.value.blockers
    )

    # The sweep finalizes: podless lease close + storage release, under its
    # locked re-checks; only then may a new generation be admitted.
    _service(fixed).sweep(plan.experiment_id)
    assert _hold_states(db, fixed["acquisition_id"])["STORAGE"] != "ACTIVE"
    assert "U2" not in _item_kinds(db, plan.experiment_id, fixed["comfy"].clock)
    with _PatchedPolicy():
        after = _service(fixed).resume(
            plan.experiment_id,
            authorization=fixed["authorization"],
            quote=_screen_quote(fixed["world"]),
            expected_sha256=fixed["digest"],
            phase="screen",
            source_bytes=fixed["raw"],
        )
    assert after["admission"]["permitted"] is True


def test_at06_replay_attestation_identity_sc23(db: Database, tmp_path: Path):
    fixed = _at6_context(db, tmp_path)
    plan = fixed["plan"]
    service = _service(fixed)
    args = dict(
        actor_ref="operator-console",
        reason="provider console shows no pod for the owned token",
        evidence_sha256="a" * 64,
    )
    service.resolve_create(plan.experiment_id, acquisition_id=fixed["acquisition_id"], **args)
    with db.transaction(readonly=True) as tx:
        settlements_before = tx.fetchval(
            "SELECT COUNT(*) FROM charges WHERE reservation_id=("
            "SELECT reservation_id FROM benchmark_reservation_links WHERE acquisition_id=%s "
            "AND purpose='COMPUTE')",
            (fixed["acquisition_id"],),
        )

    # SC2-3: the IDENTICAL attestation replays successfully - no new audit row,
    # no new settlement - before and after the sweep finalization.
    replay = service.resolve_create(
        plan.experiment_id, acquisition_id=fixed["acquisition_id"], **args
    )
    assert replay["acquisitions"][0]["state"] == "NO_CREATE_PROVEN"
    assert len(_resolution_rows(db, fixed["lease_id"])) == 1
    service.sweep(plan.experiment_id)
    replay_after_sweep = service.resolve_create(
        plan.experiment_id, acquisition_id=fixed["acquisition_id"], **args
    )
    assert replay_after_sweep["acquisitions"][0]["state"] == "NO_CREATE_PROVEN"
    assert len(_resolution_rows(db, fixed["lease_id"])) == 1

    # A DIFFERENT attestation for the same resolution is a Conflict, never a
    # second audit.
    with pytest.raises(Conflict):
        service.resolve_create(
            plan.experiment_id,
            acquisition_id=fixed["acquisition_id"],
            actor_ref="other-operator",
            reason="a different story about the same create",
            evidence_sha256="b" * 64,
        )
    assert len(_resolution_rows(db, fixed["lease_id"])) == 1
    with db.transaction(readonly=True) as tx:
        settlements_after = tx.fetchval(
            "SELECT COUNT(*) FROM charges WHERE reservation_id=("
            "SELECT reservation_id FROM benchmark_reservation_links WHERE acquisition_id=%s "
            "AND purpose='COMPUTE')",
            (fixed["acquisition_id"],),
        )
    assert settlements_after == settlements_before


@pytest.mark.parametrize("boundary", ["adoption_before_resolution", "adoption_after_resolution"])
def test_at06_janitor_adoption_at_each_boundary(boundary: str, db: Database, tmp_path: Path):
    fixed = _at6_context(db, tmp_path)
    plan = fixed["plan"]
    world, comfy = fixed["world"], fixed["comfy"]

    def seed_late_pod():

        with db.transaction(readonly=True) as tx:
            token = tx.fetchval(
                "SELECT client_token FROM pod_leases WHERE id=%s", (fixed["lease_id"],)
            )
        from microdrama.testing.fakes.common import fake_https
        from microdrama.testing.fakes.pods import _Pod

        world.provider._pods["late-pod-0001"] = _Pod(
            pod_id="late-pod-0001",
            name="recovered-late-pod-0001",
            owned_tag=world.config.owned_tag,
            client_token=token,
            gpu_type="FAKE-GPU-24GB",
            hourly_price_micro_usd=900_000,
            created_at=comfy.clock.now(),
            endpoint_url=fake_https("late-pod-0001.pods.fake", ""),
            pipeline_owned=True,
        )

    if boundary == "adoption_before_resolution":
        # The pod appears first: the janitor adopts it onto the (dead worker's)
        # lease, so the lease has a Pod and the resolution must refuse (nothing
        # was proven).
        seed_late_pod()
        comfy.clock.advance(seconds=3601)  # the worker is gone; the lease expired
        world.janitor().sweep()
        with db.transaction(readonly=True) as tx:
            pod_id = tx.fetchval("SELECT pod_id FROM pod_leases WHERE id=%s", (fixed["lease_id"],))
        assert pod_id == "late-pod-0001"
        with pytest.raises(Conflict):
            _service(fixed).resolve_create(
                plan.experiment_id,
                acquisition_id=fixed["acquisition_id"],
                actor_ref="operator-console",
                reason="provider console shows no pod",
                evidence_sha256="a" * 64,
            )
        assert _resolution_rows(db, fixed["lease_id"]) == []
        assert _hold_states(db, fixed["acquisition_id"])["STORAGE"] == "ACTIVE"
        return

    # Resolution first (STORAGE retained), THEN the late pod: the janitor
    # attaches it and contradicts the resolution; its cleanup attempt fails
    # transiently, so U5 holds with the STORAGE still held - the contradiction
    # never releases it either; finalization comes after verified cleanup.
    _service(fixed).resolve_create(
        plan.experiment_id,
        acquisition_id=fixed["acquisition_id"],
        actor_ref="operator-console",
        reason="provider console shows no pod",
        evidence_sha256="a" * 64,
    )
    seed_late_pod()
    comfy.clock.advance(seconds=3601)  # the worker is gone; the janitor takes over
    # The janitor dies mid-adoption AFTER its bind+contradict transaction
    # committed but BEFORE the verified termination (§9.3-style injected death:
    # a non-Microdrama error escapes every handler). The discovered pod stays
    # unfinalized - exactly the U5 window.
    original_stop = world.provider.stop_pod
    calls = {"n": 0}

    def dying_stop(pod_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("janitor died mid-adoption (injected)")
        return original_stop(pod_id)

    world.provider.stop_pod = dying_stop
    with pytest.raises(TimeoutError):
        world.janitor().sweep()
    world.provider.stop_pod = original_stop
    (row,) = _resolution_rows(db, fixed["lease_id"])
    assert row["contradicted_at"] is not None and row["contradicted_pod_id"] == "late-pod-0001"
    kinds = _item_kinds(db, plan.experiment_id, comfy.clock)
    assert "U5" in kinds
    assert _hold_states(db, fixed["acquisition_id"])["STORAGE"] == "ACTIVE"

    # U5 blocks all dispatch on the experiment until the discovered pod is
    # finalized; then the sweep finalizes the storage under its re-checks.
    # (Resume would sweep the owed cleanup itself; the gate is what must
    # refuse, so this drives execute.)
    from microdrama.pipeline.benchmark_service import AdmissionBlocked

    with _PatchedPolicy():
        with pytest.raises(AdmissionBlocked) as refused:
            _service(fixed).execute(
                plan.experiment_id,
                phase="screen",
                authorization=fixed["authorization"],
                quote=_screen_quote(world),
                expected_sha256=fixed["digest"],
                source_bytes=fixed["raw"],
            )
    assert any("U5" in blocker for blocker in refused.value.blockers), refused.value.blockers

    # HC-1 (HCF round): the sweep's cleanup finishes the discovered pod's
    # terminate->verify tail, but finalization ALSO requires the pod's
    # canonical INVOICE finality - terminate-verified + ownership closed alone
    # no longer clears U5 or releases the STORAGE hold.
    _service(fixed).sweep(plan.experiment_id)
    assert "U5" in _item_kinds(db, plan.experiment_id, comfy.clock)
    assert _hold_states(db, fixed["acquisition_id"])["STORAGE"] == "ACTIVE"

    # The provider's billing evidence arrives and verifies (the recovery
    # allocation the degenerate adopted window opens is resolved through the
    # audited canonical tail); the next sweep finalizes.
    from test_t031_hcf_f3_finality import _bill_lease_to_billed

    _bill_lease_to_billed(db, fixed["world"], lease_id=fixed["lease_id"], amount_micro_usd=900_250)
    _service(fixed).sweep(plan.experiment_id)
    assert "U5" not in _item_kinds(db, plan.experiment_id, comfy.clock)
    assert _hold_states(db, fixed["acquisition_id"])["STORAGE"] != "ACTIVE"


def test_at07_late_adoption_after_newer_admission_blocks_then_clears(db: Database, tmp_path: Path):
    fixed = _at6_context(db, tmp_path)
    plan = fixed["plan"]
    world, comfy = fixed["world"], fixed["comfy"]
    service = _service(fixed)

    service.resolve_create(
        plan.experiment_id,
        acquisition_id=fixed["acquisition_id"],
        actor_ref="operator-console",
        reason="provider console shows no pod",
        evidence_sha256="a" * 64,
    )
    service.sweep(plan.experiment_id)
    assert _hold_states(db, fixed["acquisition_id"])["STORAGE"] != "ACTIVE"

    # The newer generation is admitted (no partial-index collision) and runs
    # healthy work with a live pod.
    with _PatchedPolicy():
        state = None
        for _ in range(12):
            service = _service(fixed)
            state = service.resume(
                plan.experiment_id,
                authorization=fixed["authorization"],
                quote=_screen_quote(world),
                expected_sha256=fixed["digest"],
                phase="screen",
                source_bytes=fixed["raw"],
            )
            comfy.clock.advance(seconds=1)
            if any(a["generation"] == 2 for a in state["acquisitions"]):
                break
    assert any(a["generation"] == 2 for a in state["acquisitions"]), state["acquisitions"]

    # The disproved pod appears AFTER the newer admission committed: the old
    # acquisition stays NO_CREATE_PROVEN (never reopened into the index), U5 is
    # derived and blocks every dispatch on the experiment.
    with db.transaction(readonly=True) as tx:
        token = tx.fetchval("SELECT client_token FROM pod_leases WHERE id=%s", (fixed["lease_id"],))
    from microdrama.testing.fakes.common import fake_https
    from microdrama.testing.fakes.pods import _Pod

    world.provider._pods["late-pod-0002"] = _Pod(
        pod_id="late-pod-0002",
        name="recovered-late-pod-0002",
        owned_tag=world.config.owned_tag,
        client_token=token,
        gpu_type="FAKE-GPU-24GB",
        hourly_price_micro_usd=900_000,
        created_at=comfy.clock.now(),
        endpoint_url=fake_https("late-pod-0002.pods.fake", ""),
        pipeline_owned=True,
    )
    # Only the OLD generation's lease is dead (its expiry is in the past); the
    # healthy gen-2 lease is untouched. The janitor adopts the late pod onto
    # gen-1's lease and dies mid-adoption (§9.3 injected death) - the pod stays
    # unfinalized, so U5 opens with the original STORAGE hold still retained.
    from datetime import timedelta

    with db.transaction() as tx:
        tx.execute(
            "UPDATE pod_leases SET lease_expires_at=%s WHERE id=%s",
            (comfy.clock.now() - timedelta(seconds=1), fixed["lease_id"]),
        )
    original_stop = world.provider.stop_pod
    calls = {"n": 0}

    def dying_stop(pod_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("janitor died mid-adoption (injected)")
        return original_stop(pod_id)

    world.provider.stop_pod = dying_stop
    with pytest.raises(TimeoutError):
        world.janitor().sweep()
    world.provider.stop_pod = original_stop
    (row,) = _resolution_rows(db, fixed["lease_id"])
    assert row["contradicted_pod_id"] == "late-pod-0002"
    with db.transaction(readonly=True) as tx:
        old_state = tx.fetchval(
            "SELECT state FROM benchmark_acquisitions WHERE acquisition_id=%s",
            (fixed["acquisition_id"],),
        )
    assert old_state == "NO_CREATE_PROVEN"  # never reopened into the index
    kinds = _item_kinds(db, plan.experiment_id, comfy.clock)
    assert "U5" in kinds
    with _PatchedPolicy():
        blocked = _service(fixed).resume(
            plan.experiment_id,
            authorization=fixed["authorization"],
            quote=_screen_quote(world),
            expected_sha256=fixed["digest"],
            phase="screen",
            source_bytes=fixed["raw"],
        )
    assert blocked["admission"]["permitted"] is False
    assert any("U5" in blocker for blocker in blocked["admission"]["blockers"])

    # GPU accounting: the contradicted acquisition counts from its ORIGINAL
    # create intent through the discovered pod's verified termination, ignoring
    # the disproved no-create window end.
    with db.transaction(readonly=True) as tx:
        from microdrama.rendering.benchmark_experiments import gpu_ms

        counted = gpu_ms(tx, plan.experiment_id, comfy.clock.now())
        create_intent = tx.fetchval(
            "SELECT create_intent_at FROM benchmark_acquisitions WHERE acquisition_id=%s",
            (fixed["acquisition_id"],),
        )
    asserted_min_ms = int((comfy.clock.now() - create_intent).total_seconds() * 1000) - 1500
    assert counted >= max(asserted_min_ms, 1)

    # Cleanup + replay: the janitor's retry finishes the discovered pod's
    # terminate->verify tail, then the sweep finalizes the storage; U5 clears
    # and dispatch may continue (the healthy gen-2 work recovers through the
    # same resume's reconcile). The retry is scoped to this account's pods
    # (CR-9), so the fixture pins the account ref on lease and config alike.
    from dataclasses import replace as _replace

    with db.transaction() as tx:
        tx.execute(
            "UPDATE pod_leases SET provider_account_ref='acct:fixture' "
            "WHERE id=%s OR pod_id='late-pod-0002'",
            (fixed["lease_id"],),
        )
    janitor_config = _replace(world.config, provider_account_ref="acct:fixture")
    world.janitor(config=janitor_config).sweep()
    with db.transaction(readonly=True) as tx:
        terminate_verified = tx.fetchval(
            "SELECT terminate_verified_at FROM pod_leases WHERE id=%s", (fixed["lease_id"],)
        )
    assert terminate_verified is not None
    # HC-1 (HCF round): the sweep finalizes only at the discovered pod's
    # canonical INVOICE finality - drive the verified billing evidence first.
    from test_t031_hcf_f3_finality import _bill_lease_to_billed

    _bill_lease_to_billed(db, fixed["world"], lease_id=fixed["lease_id"], amount_micro_usd=900_250)
    _service(fixed).sweep(plan.experiment_id)
    assert "U5" not in _item_kinds(db, plan.experiment_id, comfy.clock)
    assert _hold_states(db, fixed["acquisition_id"])["STORAGE"] != "ACTIVE"
    with _PatchedPolicy():
        after = None
        for _ in range(6):
            after = _service(fixed).resume(
                plan.experiment_id,
                authorization=fixed["authorization"],
                quote=_screen_quote(world),
                expected_sha256=fixed["digest"],
                phase="screen",
                source_bytes=fixed["raw"],
            )
            comfy.clock.advance(seconds=1)
            if after["admission"].get("permitted"):
                break
    assert after["admission"]["permitted"] is True


# ---------------------------------------------------------------------------
# AT-21 — lock races on two real PostgreSQL connections (§6.1/R5): bounded
# lock_timeout, barrier-driven interleave, no deadlock (SQLSTATE 40P01), no
# unsafe release, and the gate serialises with operation transitions and
# upload-intent insertion (including rows that are initially absent).
# ---------------------------------------------------------------------------


def _race_connection(db: Database):
    """A second, real connection with a bounded lock timeout."""
    import psycopg

    conn = psycopg.connect(db.dsn, autocommit=True)
    conn.execute("SET lock_timeout = '2500ms'")
    return conn


def _bounded_worker_locks(db: Database, *, seconds: str = "2500ms") -> None:
    """HC-10 (HCF): the race WORKERS run on the service's own pool, so the
    bounded ``lock_timeout`` the helper connections get must apply to them
    too - every currently pooled connection gets the session setting and the
    database default covers connections the pool opens later. A deadlock or a
    lock wedge then FAILS the test instead of hanging it."""
    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    assert seconds.replace("m", "").replace("s", "").isdigit()
    name = conninfo_to_dict(db.dsn)["dbname"]
    with psycopg.connect(db.dsn, autocommit=True) as admin:
        admin.execute(f"ALTER DATABASE \"{name}\" SET lock_timeout TO '{seconds}'")
    # The pool's currently IDLE connections (checked-out ones are not in this
    # container - the race threads have not started yet) get the session
    # setting too (a deque in psycopg_pool 3.3, a dict in older versions).
    idle = getattr(db._pool, "_pool", [])
    if hasattr(idle, "values"):
        idle = list(idle.values())
    for conn in list(idle):
        conn.execute(f"SET lock_timeout TO '{seconds}'")
        conn.commit()


def _deadlocks(exc: BaseException) -> bool:
    """HD-3 (HCF R4): a deadlock or lock timeout fails the race proof in BOTH
    shapes - the raw psycopg error (SQLSTATE 40P01 / 55P03) and the
    ``ServiceUnavailable`` the production translator (persistence/db.py
    ``translate_db_error``) turns it into on every worker path that runs
    through ``Database.transaction``."""
    import psycopg

    if isinstance(exc, psycopg.errors.DeadlockDetected | psycopg.errors.LockNotAvailable):
        return True
    return isinstance(exc, ServiceUnavailable)


def _expected_race_refusals() -> tuple[type, ...]:
    """HD-3 (HCF R4): the ONLY error classes the three-way race may record -
    precise admission/reconciliation refusals. ``ServiceUnavailable``
    (including every translated SQLSTATE 40P01/55P03) is deliberately absent:
    the old ``all(isinstance(exc, MicrodramaError))`` whitelist accepted a
    translated worker deadlock, so the proof passed despite the defect it
    claimed to exclude."""
    from microdrama.contracts.errors import NeedsReconciliation, PolicyDenied
    from microdrama.pipeline.benchmark_service import AdmissionBlocked

    return (AdmissionBlocked, NeedsReconciliation, PolicyDenied, Conflict)


def test_at21_race_proof_rejects_translated_deadlock_and_lock_timeout():
    """HD-3: prove the proof works. The production translator turns SQLSTATE
    40P01 (DeadlockDetected) and 55P03 (LockNotAvailable) into
    ``ServiceUnavailable``; each translated failure is injected into the
    recorded-error list and EVERY strengthened race assertion must FAIL on it
    (before R4 the deadlock check missed both shapes and the blanket
    ``MicrodramaError`` whitelist accepted them)."""
    import psycopg

    from microdrama.persistence.db import translate_db_error

    for sqlstate in ("40P01", "55P03"):
        raw = psycopg.errors.lookup(sqlstate)("race proof injection")
        raw.sqlstate = sqlstate
        translated = translate_db_error(raw)
        assert isinstance(translated, ServiceUnavailable), repr(translated)
        errors = [translated]
        with pytest.raises(AssertionError):
            assert not any(_deadlocks(exc) for exc in errors), [repr(e) for e in errors]
        with pytest.raises(AssertionError):
            assert all(not isinstance(exc, ServiceUnavailable) for exc in errors), [
                repr(e) for e in errors
            ]
        with pytest.raises(AssertionError):
            assert all(isinstance(exc, _expected_race_refusals()) for exc in errors), [
                repr(e) for e in errors
            ]


def test_at21_billing_wrapper_vs_resolve_create_never_deadlocks(db: Database, tmp_path: Path):
    """HC-10 (HCF R4): the REAL canonical billing wrapper
    (``billing.resolve_podless_create``: account->categories->advisory->L) and
    the benchmark resolution (the same shared order) cannot deadlock - and the
    proof now catches the historical inversion. A lease-row (L) holder parks
    the wrapper INSIDE its lock sequence while the resolver holds the account
    rows: with the pre-P4 wrapper order (advisory+L BEFORE account) that
    closes a real ABBA cycle the moment the L holder commits - PostgreSQL
    breaks it with SQLSTATE 40P01 and this test fails (proven on a scratch
    branch that restores the old order). Queuing the wrapper first behind an
    ACCOUNT holder (the pre-R4 shape) completed orderly even with the
    inversion, because the resolver held nothing while it waited."""
    import threading

    from microdrama.budget.billing import BillingRepository

    fixed = _at6_context(db, tmp_path)
    plan = fixed["plan"]
    _bounded_worker_locks(db)
    helper = _race_connection(db)
    helper.execute("BEGIN")
    helper.execute("SELECT 1 FROM pod_leases WHERE id=%s FOR UPDATE", (str(fixed["lease_id"]),))
    outcome: dict[str, object] = {}

    def wrapper_call():
        try:
            BillingRepository(db, budget_service=fixed["budget"]).resolve_podless_create(
                fixed["lease_id"],
                actor_ref="operator-console",
                reason="provider console shows no pod",
                evidence_sha256="a" * 64,
                now=fixed["comfy"].clock.now(),
            )
            outcome["wrapper"] = True
        except BaseException as exc:  # noqa: BLE001 - recorded, asserted below
            outcome["wrapper_error"] = exc

    def resolver():
        try:
            _service(fixed).resolve_create(
                plan.experiment_id,
                acquisition_id=fixed["acquisition_id"],
                actor_ref="operator-console",
                reason="provider console shows no pod",
                evidence_sha256="a" * 64,
            )
            outcome["resolved"] = True
        except BaseException as exc:  # noqa: BLE001 - recorded, asserted below
            outcome["error"] = exc

    wrapper_thread = threading.Thread(target=wrapper_call)
    wrapper_thread.start()
    wrapper_thread.join(timeout=1.0)
    # The wrapper is parked inside its lock sequence on the lease row (L),
    # holding whatever its order takes before L.
    assert wrapper_thread.is_alive()
    resolver_thread = threading.Thread(target=resolver)
    resolver_thread.start()
    resolver_thread.join(timeout=1.0)
    # The resolver holds the account rows and waits for what the wrapper
    # holds (the billing advisory under the old order; nothing under the
    # shared order, because the wrapper already holds the account rows).
    assert resolver_thread.is_alive()
    helper.execute("COMMIT")
    wrapper_thread.join(timeout=15.0)
    resolver_thread.join(timeout=15.0)
    helper.close()
    assert not wrapper_thread.is_alive() and not resolver_thread.is_alive()
    assert "wrapper_error" not in outcome, repr(outcome.get("wrapper_error"))
    assert "error" not in outcome, repr(outcome.get("error"))
    assert outcome.get("wrapper") is True and outcome.get("resolved") is True
    (row,) = _resolution_rows(db, fixed["lease_id"])
    assert row["actor_ref"] == "operator-console"
    # No unsafe release: the resolution kept the STORAGE hold (R1).
    assert _hold_states(db, fixed["acquisition_id"])["STORAGE"] == "ACTIVE"


def test_at21_ambiguity_vs_admission_vs_sweep_ordered(db: Database, tmp_path: Path):
    """The ambiguity markers, admission gates and the sweep finalization all
    take account->categories->E(->A) in the same order: concurrent public
    calls under a bounded lock timeout converge without a deadlock and without
    double effects."""
    import threading

    fixed = _at6_context(db, tmp_path)
    plan = fixed["plan"]
    _bounded_worker_locks(db)
    helper = _race_connection(db)
    helper.execute("BEGIN")
    helper.execute(
        "SELECT * FROM benchmark_experiments WHERE experiment_id=%s FOR UPDATE",
        (str(plan.experiment_id),),
    )
    barrier = threading.Barrier(3, timeout=10)
    errors: list[BaseException] = []

    def call(name, fn):
        def run():
            try:
                barrier.wait()
                fn()
            except BaseException as exc:  # noqa: BLE001 - recorded, asserted below
                errors.append(exc)

        return run

    def admit():
        with _PatchedPolicy():
            # HC-10 (HCF): no swallowed exceptions - a refusal is fine, but it
            # must be a precise, expected one; anything else (deadlock
            # included) fails the test through the recorded errors below.
            _service(fixed).execute(
                plan.experiment_id,
                phase="screen",
                authorization=fixed["authorization"],
                quote=_screen_quote(fixed["world"]),
                expected_sha256=fixed["digest"],
                source_bytes=fixed["raw"],
            )

    def sweep():
        _service(fixed).sweep(plan.experiment_id)

    def mark():
        _service(fixed).reconcile(plan.experiment_id)

    threads = [
        threading.Thread(target=call("admission", admit)),
        threading.Thread(target=call("sweep", sweep)),
        threading.Thread(target=call("reconcile", mark)),
    ]
    for thread in threads:
        thread.start()
    import time

    time.sleep(0.5)
    for thread in threads:
        assert thread.is_alive()  # all blocked behind the E lock, none errored
    helper.execute("COMMIT")
    helper.close()
    for thread in threads:
        thread.join(timeout=15)
    assert not any(_deadlocks(exc) for exc in errors), [repr(e) for e in errors]
    # HC-10 (HCF) + HD-3 (HCF R4): no swallowed exceptions and no blanket
    # MicrodramaError acceptance - any recorded error must be one of the
    # SPECIFIC expected admission/reconciliation refusals. A translated
    # deadlock or lock timeout (ServiceUnavailable, SQLSTATE 40P01/55P03), a
    # driver error or a bug surfaces here; the pre-R4 whitelist accepted
    # every MicrodramaError and let a worker deadlock pass the proof.
    assert all(not isinstance(exc, ServiceUnavailable) for exc in errors), [repr(e) for e in errors]
    assert all(isinstance(exc, _expected_race_refusals()) for exc in errors), [
        repr(e) for e in errors
    ]
    assert all(not thread.is_alive() for thread in threads)
    # Nothing was dispatched while U1 held (I3 held under the race).
    with db.transaction(readonly=True) as tx:
        operations = tx.fetchall(
            "SELECT o.id FROM provider_operations o JOIN benchmark_samples s "
            "ON s.reservation_id=o.reservation_id WHERE s.experiment_id=%s",
            (plan.experiment_id,),
        )
        acquisitions = tx.fetchall(
            "SELECT state FROM benchmark_acquisitions WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
    assert operations == []
    assert {row["state"] for row in acquisitions} == {"UNKNOWN"}


def test_at21_gate_serialises_with_absent_rows_r5(db: Database, tmp_path: Path):
    """R5 (HC-10/HCF): the REAL standalone gate (``_gate``: account ->
    categories -> E, then the ONE shared-order row helper incl. the operation
    and upload rows) serialises with an inserter holding the acquisition
    ownership row: the gate blocks behind the ownership lock while the
    inserter commits an initially-absent upload intent AND a provider
    operation, and the gate - through the real §4.1 evaluation - then refuses
    admission naming BOTH rows. An initially-absent row cannot slip past the
    locked gate, and the gate cannot miss rows an inserter committed first.
    (The inserter's raw SQL is the injected adversarial boundary; the
    implementation under test is the gate itself.)"""
    import threading
    import time
    import uuid as uuid_module

    from test_t031_h2b_p2_gate import _at14_context

    from microdrama.pipeline.benchmark_service import AdmissionBlocked

    world, ep, plan, service, comfy, adapter, budget, acquisition = _at14_context(db, tmp_path)
    fixed = {
        "world": world,
        "ep": ep,
        "plan": plan,
        "comfy": comfy,
        "adapter": adapter,
        "budget": budget,
        "acquisition_id": acquisition["acquisition_id"],
    }
    acquisition_id = acquisition["acquisition_id"]
    _bounded_worker_locks(db)

    with db.transaction(readonly=True) as tx:
        sample = tx.fetchone(
            "SELECT reservation_id FROM benchmark_samples WHERE experiment_id=%s "
            "AND sample_id='S01-R1'",
            (plan.experiment_id,),
        )
        provider = tx.fetchval(
            "SELECT provider FROM reservations WHERE id=%s", (sample["reservation_id"],)
        )
    now = comfy.clock.now()

    # The adversarial inserter: holds the acquisition ownership row, then
    # commits an initially-absent upload intent AND provider operation.
    inserter = _race_connection(db)
    inserter.execute("BEGIN")
    inserter.execute(
        "SELECT acquisition_id FROM benchmark_acquisitions WHERE acquisition_id=%s FOR UPDATE",
        (str(acquisition_id),),
    )
    inserter.execute(
        "INSERT INTO benchmark_uploads(acquisition_id,asset_sha256,media_kind,role,"
        "subject_id,destination_slot,upload_key,state) VALUES(%s,%s,'image',"
        "'character_identity','speaker-a','ref_images.ref_image_0',%s,'UNKNOWN')",
        (str(acquisition_id), "c" * 64, "t031/race/key"),
    )
    job_id = uuid_module.uuid4()
    inserter.execute(
        "INSERT INTO jobs(id,job_type,job_version,queue,semantic_key,input_hash,input,"
        "status,priority,attempt,max_attempts,run_after,episode_id,correlation_id,"
        "causation_id,created_at,updated_at) "
        "VALUES(%s,'render.shot',1,'production',%s,%s,'{}'::jsonb,'QUEUED',100,0,3,%s,%s,%s,%s,%s,%s)",
        (
            str(job_id),
            f"benchmark:{plan.experiment_id}:race:r5",
            "e" * 64,
            str(now),
            str(ep.episode_id),
            str(uuid_module.uuid4()),
            str(uuid_module.uuid4()),
            str(now),
            str(now),
        ),
    )
    inserter.execute(
        "INSERT INTO provider_operations(id,provider,operation_kind,client_token,"
        "request_hash,job_id,reservation_id,state,attempt,deadline_at,episode_id,"
        "created_at,updated_at) "
        "VALUES(%s,%s,'comfy.queue_prompt',%s,%s,%s,%s,'PENDING_SUBMIT',1,%s,%s,%s,%s)",
        (
            str(uuid_module.uuid4()),
            provider,
            str(uuid_module.uuid4()),
            "d" * 64,
            str(job_id),
            str(sample["reservation_id"]),
            str(now.replace(year=now.year + 1)),
            str(ep.episode_id),
            str(now),
            str(now),
        ),
    )
    outcome: dict[str, object] = {}

    def gate_call():
        try:
            _service(fixed)._gate(plan.experiment_id, "admission")
            outcome["gate"] = "permitted"
        except BaseException as exc:  # noqa: BLE001 - recorded, asserted below
            outcome["gate"] = exc

    waiter = threading.Thread(target=gate_call)
    waiter.start()
    time.sleep(0.5)
    assert waiter.is_alive()  # the REAL gate is blocked at its ownership prefix
    inserter.execute("COMMIT")
    waiter.join(timeout=5)
    inserter.close()
    assert not waiter.is_alive()

    # Through the real §4.1 evaluation the gate now sees BOTH committed rows:
    # the upload intent (U3u) and the PENDING_SUBMIT operation (U3).
    gate_result = outcome["gate"]
    assert isinstance(gate_result, AdmissionBlocked), repr(gate_result)
    text = " ".join(gate_result.blockers)
    assert "upload intent" in text, gate_result.blockers
    assert "PENDING_SUBMIT" in text, gate_result.blockers
    with db.transaction(readonly=True) as tx:
        uploads = tx.fetchval(
            "SELECT COUNT(*) FROM benchmark_uploads WHERE acquisition_id=%s AND state='UNKNOWN'",
            (acquisition_id,),
        )
        operations = tx.fetchval(
            "SELECT COUNT(*) FROM provider_operations WHERE reservation_id=%s "
            "AND state='PENDING_SUBMIT'",
            (sample["reservation_id"],),
        )
    assert uploads == 1 and operations == 1  # exactly once, no duplicates


def test_hb9_reconcile_never_restores_running_over_canonical_blockers(db: Database, tmp_path: Path):
    """HB-9: the NEEDS_RECONCILIATION -> running transition is predicated on
    ZERO canonical blocking items (the common repository function, under the
    gate locks) - not on separate label/slot/upload conditions. A U5 that
    survives a late adoption while all three of those are clear must keep
    the experiment in NEEDS_RECONCILIATION; only finalization lets reconcile
    restore running."""
    from datetime import timedelta

    from microdrama.testing.fakes.common import fake_https
    from microdrama.testing.fakes.pods import _Pod

    fixed = _at6_context(db, tmp_path)
    plan = fixed["plan"]
    world, comfy = fixed["world"], fixed["comfy"]

    _service(fixed).resolve_create(
        plan.experiment_id,
        acquisition_id=fixed["acquisition_id"],
        actor_ref="operator-console",
        reason="provider console shows no pod",
        evidence_sha256="a" * 64,
    )
    _service(fixed).sweep(plan.experiment_id)
    with _PatchedPolicy():
        for _ in range(12):
            state = _service(fixed).resume(
                plan.experiment_id,
                authorization=fixed["authorization"],
                quote=_screen_quote(world),
                expected_sha256=fixed["digest"],
                phase="screen",
                source_bytes=fixed["raw"],
            )
            comfy.clock.advance(seconds=1)
            if any(a["generation"] == 2 for a in state["acquisitions"]):
                break
    assert any(a["generation"] == 2 for a in state["acquisitions"])

    with db.transaction(readonly=True) as tx:
        token = tx.fetchval("SELECT client_token FROM pod_leases WHERE id=%s", (fixed["lease_id"],))
    world.provider._pods["late-pod-0002"] = _Pod(
        pod_id="late-pod-0002",
        name="recovered-late-pod-0002",
        owned_tag=world.config.owned_tag,
        client_token=token,
        gpu_type="FAKE-GPU-24GB",
        hourly_price_micro_usd=900_000,
        created_at=comfy.clock.now(),
        endpoint_url=fake_https("late-pod-0002.pods.fake", ""),
        pipeline_owned=True,
    )
    with db.transaction() as tx:
        tx.execute(
            "UPDATE pod_leases SET lease_expires_at=%s WHERE id=%s",
            (comfy.clock.now() - timedelta(seconds=1), fixed["lease_id"]),
        )
    original_stop = world.provider.stop_pod
    calls = {"n": 0}

    def dying_stop(pod_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("janitor died mid-adoption (injected)")
        return original_stop(pod_id)

    world.provider.stop_pod = dying_stop
    with pytest.raises(TimeoutError):
        world.janitor().sweep()
    world.provider.stop_pod = original_stop
    assert "U5" in _item_kinds(db, plan.experiment_id, comfy.clock)

    # The separate conditions the old transition checked are ALL clear: no
    # UNKNOWN acquisition label, no stuck slot, no open upload - only the
    # canonical U5 remains. Reconcile must NOT restore running.
    with db.transaction() as tx:
        tx.execute(
            "UPDATE benchmark_experiments SET execution_state='NEEDS_RECONCILIATION' "
            "WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
    blocked = _service(fixed).reconcile(plan.experiment_id)
    assert blocked["execution_state"] == "NEEDS_RECONCILIATION"

    # Finalization clears U5; reconcile may then restore running.
    from dataclasses import replace as _replace

    with db.transaction() as tx:
        tx.execute(
            "UPDATE pod_leases SET provider_account_ref='acct:fixture' "
            "WHERE id=%s OR pod_id='late-pod-0002'",
            (fixed["lease_id"],),
        )
    world.janitor(config=_replace(world.config, provider_account_ref="acct:fixture")).sweep()
    # HC-1 (HCF round): U5 clears only at the discovered pod's canonical
    # INVOICE finality - terminate-verified alone no longer finalizes.
    from test_t031_hcf_f3_finality import _bill_lease_to_billed

    _bill_lease_to_billed(db, fixed["world"], lease_id=fixed["lease_id"], amount_micro_usd=900_250)
    _service(fixed).sweep(plan.experiment_id)
    assert "U5" not in _item_kinds(db, plan.experiment_id, comfy.clock)
    with _PatchedPolicy():
        for _ in range(8):
            cleared = _service(fixed).reconcile(plan.experiment_id)
            if cleared["execution_state"] != "NEEDS_RECONCILIATION":
                break
            comfy.clock.advance(seconds=1)
            with _PatchedPolicy():
                _service(fixed).resume(
                    plan.experiment_id,
                    authorization=fixed["authorization"],
                    quote=_screen_quote(world),
                    expected_sha256=fixed["digest"],
                    phase="screen",
                    source_bytes=fixed["raw"],
                )
    assert cleared["execution_state"] != "NEEDS_RECONCILIATION"


def test_hb12_u2_counts_expired_storage_debt(db: Database, tmp_path: Path):
    """HB-12/R1: the no-create storage debt is detected while the hold is
    EXPIRED-but-unfinalized too - expiry retains exposure and never
    authorizes the next acquisition (I4)."""
    from datetime import timedelta

    from microdrama.budget import BudgetService
    from microdrama.rendering.benchmark_experiments import unresolved_items

    fixed = _at6_context(db, tmp_path)
    plan = fixed["plan"]
    _service(fixed).resolve_create(
        plan.experiment_id,
        acquisition_id=fixed["acquisition_id"],
        actor_ref="operator-console",
        reason="provider console shows no pod",
        evidence_sha256="a" * 64,
    )
    # The original STORAGE hold expires unfinalized (the sweep has not run).
    # Its window is days long, so the expiry is moved to just past the clock
    # first (the column is the comparison input, not a protected identity).
    world = fixed["world"]
    with db.transaction() as tx:
        tx.execute(
            "UPDATE reservations SET expires_at=%s WHERE id=("
            "SELECT reservation_id FROM benchmark_reservation_links l "
            "JOIN reservations r ON r.id=l.reservation_id "
            "WHERE l.acquisition_id=%s AND l.purpose='STORAGE')",
            (world.clock.now() - timedelta(seconds=1), fixed["acquisition_id"]),
        )
    BudgetService(db, world.clock, world.ids, world.settings).expire_stale()
    with db.transaction(readonly=True) as tx:
        expired = tx.fetchval(
            "SELECT r.state FROM benchmark_reservation_links l JOIN reservations r "
            "ON r.id=l.reservation_id WHERE l.acquisition_id=%s AND l.purpose='STORAGE'",
            (fixed["acquisition_id"],),
        )
        items = unresolved_items(tx, plan.experiment_id, now=world.clock.now())
    assert expired == "EXPIRED"
    assert any(
        item.kind == "U2" and "R1" in item.detail
        for item in items
        if item.acquisition_id == fixed["acquisition_id"]
    ), [item.describe() for item in items]


def test_hb12_u5_requires_complete_finality(db: Database, tmp_path: Path):
    """HB-12/§4.1 U5: finalization requires ALL THREE durable signals - the
    discovered pod's verified termination, its storage ownership closed, and
    the lease's compute reservation canonically closed (the BILLED settlement
    path; an ACTIVE/EXPIRED reservation after a verified termination keeps
    the reopened liability blocking). The runpod invoice-level readiness is
    the janitor's own finalization gate (§6.3) and is offline-unreachable -
    recorded as the offline boundary of this predicate."""
    from datetime import timedelta

    from microdrama.rendering.benchmark_experiments import unresolved_items
    from microdrama.testing.fakes.common import fake_https
    from microdrama.testing.fakes.pods import _Pod

    fixed = _at6_context(db, tmp_path)
    plan = fixed["plan"]
    world, comfy = fixed["world"], fixed["comfy"]
    _service(fixed).resolve_create(
        plan.experiment_id,
        acquisition_id=fixed["acquisition_id"],
        actor_ref="operator-console",
        reason="provider console shows no pod",
        evidence_sha256="a" * 64,
    )
    _service(fixed).sweep(plan.experiment_id)
    with _PatchedPolicy():
        for _ in range(12):
            state = _service(fixed).resume(
                plan.experiment_id,
                authorization=fixed["authorization"],
                quote=_screen_quote(world),
                expected_sha256=fixed["digest"],
                phase="screen",
                source_bytes=fixed["raw"],
            )
            comfy.clock.advance(seconds=1)
            if any(a["generation"] == 2 for a in state["acquisitions"]):
                break
    with db.transaction(readonly=True) as tx:
        token = tx.fetchval("SELECT client_token FROM pod_leases WHERE id=%s", (fixed["lease_id"],))
    world.provider._pods["late-pod-0004"] = _Pod(
        pod_id="late-pod-0004",
        name="recovered-late-pod-0004",
        owned_tag=world.config.owned_tag,
        client_token=token,
        gpu_type="FAKE-GPU-24GB",
        hourly_price_micro_usd=900_000,
        created_at=comfy.clock.now(),
        endpoint_url=fake_https("late-pod-0004.pods.fake", ""),
        pipeline_owned=True,
    )
    with db.transaction() as tx:
        tx.execute(
            "UPDATE pod_leases SET lease_expires_at=%s WHERE id=%s",
            (comfy.clock.now() - timedelta(seconds=1), fixed["lease_id"]),
        )

    def items_now():
        with db.transaction(readonly=True) as tx:
            return unresolved_items(tx, plan.experiment_id, now=comfy.clock.now())

    # Signal 1 missing (termination unverified): U5 blocks.
    with db.transaction() as tx:
        tx.execute(
            "UPDATE pod_leases SET pod_id='late-pod-0004' WHERE id=%s",
            (fixed["lease_id"],),
        )
        tx.execute(
            "UPDATE runpod_podless_create_resolutions SET contradicted_at=%s, "
            "contradicted_pod_id='late-pod-0004' WHERE lease_id=%s",
            (comfy.clock.now(), fixed["lease_id"]),
        )
    assert any(
        item.kind == "U5" and item.acquisition_id == fixed["acquisition_id"] for item in items_now()
    )

    # Termination verified but the discovered pod's storage ownership is
    # OPEN: U5 still blocks.
    from uuid import uuid4 as _uuid4

    with db.transaction() as tx:
        tx.execute(
            "UPDATE pod_leases SET terminate_verified_at=%s WHERE id=%s",
            (comfy.clock.now(), fixed["lease_id"]),
        )
        tx.execute(
            "INSERT INTO pod_storage_ownership(id,provider,pod_id,owner_episode_id,"
            "valid_from,valid_until) VALUES(%s,'runpod','late-pod-0004',%s,%s,NULL) "
            "ON CONFLICT DO NOTHING",
            (_uuid4(), fixed["ep"].episode_id, comfy.clock.now()),
        )
    assert any(
        item.kind == "U5" and item.acquisition_id == fixed["acquisition_id"] for item in items_now()
    )

    # Ownership closed but the discovered pod's billing is NOT final: HC-1
    # (HCF round, ruling 2) - a reservation settled BEFORE the contradiction
    # is never billing evidence, so U5 KEEPS blocking until the provider's
    # verified invoice evidence covers the pod's liability window.
    with db.transaction() as tx:
        tx.execute(
            "UPDATE pod_storage_ownership SET valid_until=%s WHERE pod_id='late-pod-0004' "
            "AND valid_until IS NULL",
            (comfy.clock.now() + timedelta(seconds=1),),
        )
    assert any(
        item.kind == "U5" and item.acquisition_id == fixed["acquisition_id"] for item in items_now()
    ), "invoice-pending discovered pod must keep U5 blocking (HC-1)"

    # The canonical invoice finality of the discovered resource clears it.
    from test_t031_hcf_f3_finality import _bill_lease_to_billed

    _bill_lease_to_billed(db, fixed["world"], lease_id=fixed["lease_id"], amount_micro_usd=900_250)
    assert not any(
        item.kind == "U5" and item.acquisition_id == fixed["acquisition_id"] for item in items_now()
    ), [item.describe() for item in items_now()]
