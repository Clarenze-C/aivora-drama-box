"""T031 H-2 HCF round, F3: HC-1 (storage exposure closes only at financial
finality), HC-7 (every reservation entry point carries the mode refusal),
HC-8 (a failed binding still owns its durable ambiguity episode) and HC-9
(the effective deadline is recomputed under locks before bounded recovery
work, and aggregate exhaustion counts every open window).
"""

from __future__ import annotations

import sys
import uuid
from datetime import timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from test_t031_h2b_p1_modes import (
    _bench_seal,
    _execute_service,
    _screen_quote,
)
from test_t031_h2b_p2_gate import _item_kinds
from test_t031_h2b_p4_resolution import _at6_context, _hold_states, _service

from microdrama.persistence import Database

_BUDGET_DIR = Path(__file__).resolve().parents[1] / "budget"
if str(_BUDGET_DIR) not in sys.path:
    sys.path.insert(0, str(_BUDGET_DIR))

from t045_support import closed_bucket  # noqa: E402

pytestmark = pytest.mark.db


def _bill_lease_to_billed(
    db: Database,
    world,
    *,
    lease_id,
    amount_micro_usd: int,
) -> str:
    """Drive one lease's billing to canonical BILLED readiness through the
    REAL repository tail: ingest the covering bucket under one query, resolve
    the recovery allocations its derivation opens (a janitor-adopted late pod
    holds a terminal lease whose immutable podless window bound cannot cover
    the Pod's existence, so the allocation engine honestly parks the GPU cost
    in the recovery pool until the audited reassignment), then verify the
    matching invoice period (HC-1's "canonical invoice finality of the
    discovered resource")."""
    from microdrama.budget import BudgetService
    from microdrama.budget.billing import BillingRepository, lease_billing_readiness

    with db.transaction(readonly=True) as tx:
        lease = tx.fetchone("SELECT * FROM pod_leases WHERE id=%s", (lease_id,))
        assert lease is not None and lease["pod_id"] is not None
        # The canonical coverage window readiness charges against: the compute
        # window (falling back to the create request) extended to every
        # storage-ownership end - the adopted late pod's disk ownership ran to
        # the verified terminate while its immutable podless window bound sits
        # at the resolution instant, so the invoice must cover the whole
        # liability, not the stale bound.
        start = lease["compute_window_start_at"] or lease["create_requested_at"]
        end = lease["compute_window_end_at"] or lease["terminate_verified_at"]
        for own in tx.fetchall(
            "SELECT valid_until FROM pod_storage_ownership WHERE provider=%s AND pod_id=%s "
            "AND owner_episode_id=%s",
            (lease["provider"], lease["pod_id"], lease["owner_episode_id"]),
        ):
            end = max(end, own["valid_until"] or lease["terminate_verified_at"])
        assert start is not None and end is not None and end > start
        account_ref = lease["provider_account_ref"]
        episode_id = lease["owner_episode_id"]
    ref = account_ref or "acct:runpod-hcf"
    # The audited recovery reassignment posts a PROVIDER_REPORTED (measured)
    # receipt; the canonical reconciliation suite admits exactly this tail by
    # running the budget service under PAID_BENCHMARK settings (the DB and the
    # bucket are fixture-local - nothing live is contacted).
    from microdrama.config import Settings
    from microdrama.contracts.enums import ExecutionMode

    budget = BudgetService(
        db,
        world.clock,
        world.ids,
        Settings(
            execution_mode=ExecutionMode.PAID_BENCHMARK,
            paid_requests_enabled=True,
            cloud_resources_enabled=True,
        ),
    )
    repository = BillingRepository(db, budget_service=budget)
    query, bucket = closed_bucket(
        pod_id=lease["pod_id"],
        start=start,
        end=end,
        gpu=amount_micro_usd,
        cpu=0,
        disk=0,
        account_ref=ref,
    )
    repository.ingest(query, [bucket])
    with db.transaction(readonly=True) as tx:
        recoveries = tx.fetchall(
            "SELECT a.allocation_id FROM runpod_billing_allocations a "
            "LEFT JOIN runpod_billing_recovery_resolutions r USING (allocation_id) "
            "WHERE a.owner_kind='RECOVERY' AND a.delta_micro_usd > 0 "
            "AND r.allocation_id IS NULL AND a.bucket_observation_id=%s",
            (bucket.observation_id,),
        )
    for row in recoveries:
        budget.resolve_billing_recovery(
            row["allocation_id"],
            assigned_episode_id=episode_id,
            actor_ref="operator-console",
            reason="adopted late pod cost attributed to its owning episode",
        )
    result = repository.verify_invoice_period(
        provider_account_ref=ref,
        pod_id=lease["pod_id"],
        period_start=start,
        period_end=end,
        amount_micro_usd=amount_micro_usd,
        currency="USD",
        evidence_sha256=sha256(f"hcf-f3:{lease['pod_id']}".encode()).hexdigest(),
        source="INVOICE",
        observed_at=bucket.observed_at,
    )
    assert result.outcome == "MATCHED", result.outcome
    return lease_billing_readiness(db, lease_id).state


def _contradicted_discovery(db: Database, tmp_path, *, expire_storage: bool = False):
    """Resolve a U1 create, then let the janitor discover and terminate the
    disproved pod - terminate verified, ownership closed, and NO billing
    evidence yet (the disk and compute invoices are still pending)."""
    from microdrama.testing.fakes.common import fake_https
    from microdrama.testing.fakes.pods import _Pod

    fixed = _at6_context(db, tmp_path)
    plan = fixed["plan"]
    world, comfy = fixed["world"], fixed["comfy"]
    _service(fixed).resolve_create(
        plan.experiment_id,
        acquisition_id=fixed["acquisition_id"],
        actor_ref="operator-console",
        reason="provider console shows no pod for the owned token",
        evidence_sha256="a" * 64,
    )
    with db.transaction(readonly=True) as tx:
        token = tx.fetchval("SELECT client_token FROM pod_leases WHERE id=%s", (fixed["lease_id"],))
    pod_created = comfy.clock.now()
    world.provider._pods["late-f3-pod"] = _Pod(
        pod_id="late-f3-pod",
        name="recovered-late-f3-pod",
        owned_tag=world.config.owned_tag,
        client_token=token,
        gpu_type="FAKE-GPU-24GB",
        hourly_price_micro_usd=900_000,
        created_at=pod_created,
        endpoint_url=fake_https("late-f3-pod.pods.fake", ""),
        pipeline_owned=True,
    )
    comfy.clock.advance(seconds=3601)
    world.janitor().sweep()
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT l.terminate_verified_at FROM pod_leases l WHERE l.id=%s",
            (fixed["lease_id"],),
        )
    assert row["terminate_verified_at"] is not None  # the tail completed
    if expire_storage:
        storage = _storage_reservation(db, fixed["acquisition_id"])
        with db.transaction() as tx:
            tx.execute(
                "UPDATE reservations SET expires_at=%s WHERE id=%s",
                (comfy.clock.now() - timedelta(seconds=1), storage["id"]),
            )
        # The composed budget carries the fixture clock (the RenderWorld's own
        # service still ticks at T0).
        fixed["budget"].expire_stale()
    return fixed


def _storage_reservation(db: Database, acquisition_id):
    with db.transaction(readonly=True) as tx:
        return tx.fetchone(
            "SELECT r.id, r.state FROM benchmark_reservation_links l "
            "JOIN reservations r ON r.id=l.reservation_id "
            "WHERE l.acquisition_id=%s AND l.purpose='STORAGE'",
            (acquisition_id,),
        )


def test_hc1_u5_requires_invoice_finality_of_the_discovered_resource(
    db: Database, tmp_path
) -> None:
    """HC-1/ruling 2: a reservation settled BEFORE the contradiction is never
    billing evidence. With termination verified but the pod's invoice still
    pending, U5 keeps blocking and the sweep keeps the STORAGE hold; once the
    canonical billing evidence is BILLED, U5 clears and the sweep releases."""
    fixed = _contradicted_discovery(db, tmp_path)
    plan = fixed["plan"]

    # Termination verified, ownership closed - but billing pending.
    assert "U5" in _item_kinds(db, plan.experiment_id, fixed["comfy"].clock)
    _service(fixed).sweep(plan.experiment_id)
    assert _hold_states(db, fixed["acquisition_id"])["STORAGE"] == "ACTIVE"

    # The provider's billing evidence arrives and verifies.
    assert (
        _bill_lease_to_billed(
            db, fixed["world"], lease_id=fixed["lease_id"], amount_micro_usd=900_250
        )
        == "BILLED"
    )
    assert "U5" not in _item_kinds(db, plan.experiment_id, fixed["comfy"].clock)
    _service(fixed).sweep(plan.experiment_id)
    assert _hold_states(db, fixed["acquisition_id"])["STORAGE"] != "ACTIVE"


def test_hc1_expired_storage_closure_waits_for_the_finalization_decision(
    db: Database, tmp_path
) -> None:
    """HC-1: the EXPIRED STORAGE hold's zero-settlement rides the SAME locked
    finalization decision - a contradicted acquisition whose discovered pod's
    invoice is pending never loses its exposure, EXPIRED or not."""
    fixed = _contradicted_discovery(db, tmp_path, expire_storage=True)
    plan = fixed["plan"]
    storage = _storage_reservation(db, fixed["acquisition_id"])
    assert storage["state"] == "EXPIRED"

    # Billing pending: the sweep must not close the EXPIRED hold either.
    _service(fixed).sweep(plan.experiment_id)
    storage = _storage_reservation(db, fixed["acquisition_id"])
    assert storage["state"] == "EXPIRED"

    # With the invoice final, the same decision closes it (I4: settled, never
    # released while liability was open).
    _bill_lease_to_billed(db, fixed["world"], lease_id=fixed["lease_id"], amount_micro_usd=900_250)
    _service(fixed).sweep(plan.experiment_id)
    storage = _storage_reservation(db, fixed["acquisition_id"])
    assert storage["state"] == "SETTLED"
    assert "U5" not in _item_kinds(db, plan.experiment_id, fixed["comfy"].clock)


def test_hc7_every_reservation_entry_point_carries_the_mode_refusal(db: Database, tmp_path) -> None:
    """HC-7/HB-11: the composed recovery world's budget refuses a work
    reservation through the transaction-owning canonical core too - not only
    through reserve/reserve_linked."""
    from microdrama.contracts.cost import BudgetReservationRequest
    from microdrama.contracts.errors import EffectDenied
    from microdrama.rendering.benchmark_experiments import ExperimentBudgetService

    fixed = _at6_context(db, tmp_path)
    plan = fixed["plan"]
    with db.transaction(readonly=True) as tx:
        exp = tx.fetchone(
            "SELECT * FROM benchmark_experiments WHERE experiment_id=%s", (plan.experiment_id,)
        )
    intent = fixed["adapter"].acquisition_requests(
        exp, _screen_quote(fixed["world"]), fixed["acquisition_id"], 1, fixed["comfy"].clock.now()
    )
    work = BudgetReservationRequest.model_validate(intent["compute"])
    assert not work.is_shutdown_or_cleanup

    restricted = ExperimentBudgetService(
        db,
        fixed["comfy"].clock,
        fixed["world"].ids,
        fixed["world"].settings,
        experiment_id=plan.experiment_id,
        cleanup_grants_only=True,
    )
    with db.transaction() as tx:
        with pytest.raises(EffectDenied):
            restricted.reserve_in_transaction(tx, work)

    # The canonical cleanup grant is preserved; an executing budget reserves.
    executing = ExperimentBudgetService(
        db,
        fixed["comfy"].clock,
        fixed["world"].ids,
        fixed["world"].settings,
        experiment_id=plan.experiment_id,
    )
    with db.transaction() as tx:
        result = executing.reserve_in_transaction(tx, work)
        assert result.state.value == "ACTIVE"


def test_hc8_failed_binding_still_persists_its_durable_episode(db: Database, tmp_path) -> None:
    """HC-8/HB-5: an UNKNOWN operation whose pod cannot be bound (here: the
    pod died at the provider while the lease still names it) still gets the
    durable ambiguity episode - without it, repeated public recovery leaves
    the item blocked with no deadline and no deadline-driven cleanup."""
    from test_t031_h2b_p1_modes import _enter_submit_ambiguity
    from test_t031_h2b_p2_gate import _at14_context

    world, ep, plan, service, comfy, adapter, budget, acquisition = _at14_context(db, tmp_path)
    service.seal(plan.experiment_id, _bench_seal(plan))
    _enter_submit_ambiguity(db, world, comfy, adapter, plan, tmp_path)
    # The worker died before ANY handler wrote its episode: the durable state
    # has the UNKNOWN operation with no persisted deadline (the ambiguity
    # handler's write is what never ran).
    with db.transaction() as tx:
        tx.execute(
            "UPDATE benchmark_acquisitions SET recovery_started_at=NULL,"
            "recovery_deadline=NULL WHERE acquisition_id=%s",
            (acquisition["acquisition_id"],),
        )
    with db.transaction(readonly=True) as tx:
        pod_id = tx.fetchval(
            "SELECT pod_id FROM pod_leases WHERE id=%s", (acquisition["lease_id"],)
        )
    assert pod_id is not None
    # The pod vanishes at the provider (stop+terminate without the lease's
    # verified tail): §3.4 binding is INDETERMINATE - not RUNNING, no verified
    # lease-side termination, no resolved create.
    world.provider.stop_pod(pod_id)
    world.provider.terminate_pod(pod_id)

    resumed = _execute_service(db, comfy, world.ids, adapter)
    resumed.reconcile(plan.experiment_id, world=adapter)
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT recovery_started_at, recovery_deadline FROM benchmark_acquisitions "
            "WHERE acquisition_id=%s",
            (acquisition["acquisition_id"],),
        )
    assert row["recovery_started_at"] is not None, (
        "a failed binding must still establish the durable ambiguity episode (HC-8)"
    )
    assert row["recovery_deadline"] is not None


def test_hc9_deadline_recomputed_and_fenced_when_exhausted(db: Database, tmp_path) -> None:
    """HC-9: ordinary recovery recomputes the effective deadline UNDER the
    locks before its bounded work and persists only a shortening; an episode
    exhausted by newly discovered liability fences immediately instead of
    polling against the stale, longer stored deadline."""
    from test_t031_h2b_p1_modes import _enter_submit_ambiguity
    from test_t031_h2b_p2_gate import _at14_context

    world, ep, plan, service, comfy, adapter, budget, acquisition = _at14_context(db, tmp_path)
    service.seal(plan.experiment_id, _bench_seal(plan))
    _enter_submit_ambiguity(db, world, comfy, adapter, plan, tmp_path)
    with db.transaction(readonly=True) as tx:
        stored = tx.fetchone(
            "SELECT recovery_deadline FROM benchmark_acquisitions WHERE acquisition_id=%s",
            (acquisition["acquisition_id"],),
        )
    assert stored["recovery_deadline"] is not None
    assert comfy.clock.now() < stored["recovery_deadline"]

    # Liability discovered since persistence exhausts the funded window: the
    # compute hold's deadline moved into the shutdown margin, so the effective
    # deadline (compute expiry minus the margin) is already in the past.
    # (gpu_limit_ms is immutable post-prepare; the funded-work bound is the
    # lever the durable rows actually own.) AT-14's fixture builds the
    # acquisition row directly with only a lease-level COMPUTE link; complete
    # its durable shape to the real acquisition flow's - an acquisition-owned
    # COMPUTE hold - whose expiry is the funded window's bound.
    with db.transaction() as tx:
        account = tx.fetchval(
            "SELECT account_id FROM benchmark_experiments WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
        compute = uuid.uuid4()
        tx.execute(
            "INSERT INTO reservations (id, account_id, request_id, semantic_key, "
            "request_hash, category, queue, provider, operation_kind, price, ceilings, "
            "reserved_micro_usd, state, expires_at) "
            "VALUES (%s, %s, %s, %s, %s, 'GPU_GENERATION', 'production', 'fake-runpod', "
            "'pod.lease', '{}', '{}', 900000, 'ACTIVE', %s)",
            (
                compute,
                account,
                uuid.uuid4(),
                f"hc9:{compute}",
                "0" * 64,
                comfy.clock.now() + timedelta(seconds=30),  # margin is 60 s
            ),
        )
        tx.execute(
            "INSERT INTO benchmark_reservation_links (reservation_id, experiment_id, "
            "acquisition_id, purpose) VALUES (%s, %s, %s, 'COMPUTE')",
            (compute, plan.experiment_id, acquisition["acquisition_id"]),
        )

    resumed = _execute_service(db, comfy, world.ids, adapter)
    resumed.reconcile(plan.experiment_id, world=adapter)
    with db.transaction(readonly=True) as tx:
        after = tx.fetchone(
            "SELECT recovery_deadline FROM benchmark_acquisitions WHERE acquisition_id=%s",
            (acquisition["acquisition_id"],),
        )
        slot = tx.fetchone(
            "SELECT coordinator_token FROM benchmark_dispatch_slots WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
    assert after["recovery_deadline"] <= comfy.clock.now(), (
        "the exhausted episode's deadline must be shortened to the past before any bounded work"
    )
    assert slot["coordinator_token"] is None  # the R3 fence fired at exhaustion


def test_hc9_aggregate_deadline_counts_every_open_window(db: Database, tmp_path) -> None:
    """HC-9: aggregate exhaustion is computed from ALL open-window consumption
    and EVERY required shutdown allowance - the late-contradiction scenario
    (the reopened original window plus the newer generation) has two open
    windows at once, not one."""
    fixed = _at6_context(db, tmp_path)
    plan = fixed["plan"]
    world, comfy = fixed["world"], fixed["comfy"]
    _service(fixed).resolve_create(
        plan.experiment_id,
        acquisition_id=fixed["acquisition_id"],
        actor_ref="operator-console",
        reason="provider console shows no pod for the owned token",
        evidence_sha256="a" * 64,
    )
    # The disproved pod appears and the janitor adopts it (bind + contradict)
    # but dies before the verified termination: gen-1's REOPENED window stays
    # open while the newer generation runs.
    from microdrama.testing.fakes.common import fake_https
    from microdrama.testing.fakes.pods import _Pod

    with db.transaction(readonly=True) as tx:
        token = tx.fetchval("SELECT client_token FROM pod_leases WHERE id=%s", (fixed["lease_id"],))
    world.provider._pods["late-f3b-pod"] = _Pod(
        pod_id="late-f3b-pod",
        name="recovered-late-f3b-pod",
        owned_tag=world.config.owned_tag,
        client_token=token,
        gpu_type="FAKE-GPU-24GB",
        hourly_price_micro_usd=900_000,
        created_at=comfy.clock.now(),
        endpoint_url=fake_https("late-f3b-pod.pods.fake", ""),
        pipeline_owned=True,
    )
    comfy.clock.advance(seconds=3601)
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

    # The newer generation's window is open too (AT-7's shape: gen-1 is
    # NO_CREATE_PROVEN, so the partial index admits gen-2).
    from test_t031_h2b_p2_gate import _insert_acquisition

    _insert_acquisition(
        db,
        world,
        fixed["adapter"],
        plan,
        generation=2,
        state="ADMITTED_WITHOUT_JOB",
        clock=comfy.clock,
    )
    now = comfy.clock.now()
    margin_ms = 60_000
    with db.transaction(readonly=True) as tx:
        limit = int(
            tx.fetchval(
                "SELECT gpu_limit_ms FROM benchmark_experiments WHERE experiment_id=%s",
                (plan.experiment_id,),
            )
        )
        used_ms = int(
            tx.fetchval(
                "SELECT COALESCE(SUM(GREATEST(0,EXTRACT(EPOCH FROM (%s-create_intent_at))*1000))"
                ",0)::bigint FROM benchmark_acquisitions WHERE experiment_id=%s "
                "AND create_intent_at IS NOT NULL",
                (now, plan.experiment_id),
            )
        )
    expected = now + timedelta(milliseconds=max((limit - used_ms - 2 * margin_ms) / 2, 0))
    deadline = _service(fixed)._effective_recovery_deadline(
        plan.experiment_id,
        fixed["acquisition_id"],
        margin_ms=margin_ms,
    )
    assert abs((deadline - expected).total_seconds()) < 1.0, (deadline, expected)
    # Sanity: the two-window bound is materially tighter than the one-window
    # formula HC-9 replaced.
    one_window = now + timedelta(milliseconds=max(limit - used_ms - margin_ms, 0))
    assert expected < one_window
