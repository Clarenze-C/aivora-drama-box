"""T031 H-2 HCF round, F1 (HC-2): canonical receipt replay identity and content.

The P4/P5 canonical edits (the ACCRUAL->ADJUSTMENT conversion in
``budget/service.py`` and the SETTLEMENT->ADJUSTMENT flip in
``rendering/leases.py``) are reverted per the orchestrator's ruling: they broke
replay (the deterministic receipt's identity reused with different content) and
double-counted late cost (``_settlement_totals`` restated as another
ADJUSTMENT). Late billing for a closed hold is met at the benchmark layer
instead (``ExperimentBudgetService``). These tests pin:

- the same receipt identity replays with identical content (settle replay);
- a closed reservation with a prior late adjustment posts only genuinely new
  deltas - a restated settle posts nothing (100 stays 100);
- an interval crash after posting but before ``accrued_until`` advances
  replays cleanly;
- the §6.4 incident path bills the discovered pod exactly once, as
  ADJUSTMENT receipts, end to end through the composed benchmark world.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from uuid import uuid5

import pytest
from rendering_support import T0, RenderWorld

from microdrama.contracts.cost import ReceiptKind, UsageReceipt
from microdrama.contracts.enums import (
    BudgetCategory,
    CostBasis,
    PriceUnit,
    Provenance,
)
from microdrama.persistence import Database
from microdrama.rendering.benchmark_experiments import ExperimentBudgetService
from microdrama.rendering.leases import accrue_lease_usage, settle_from_recorded_usage
from microdrama.testing.fakes.common import fake_https
from microdrama.testing.fakes.pods import _Pod
from microdrama.testing.seed import seed_episode, seed_season

pytestmark = pytest.mark.db

#: The fixture pod's hourly price (micro-USD/hour); 600 s of usage is 150_000.
PRICE = 900_000


def _elapsed_lease(db: Database):
    """A live lease over a real fake pod, an open GPU hold, and the benchmark's
    own budget service - the composition a benchmark experiment uses."""
    world = RenderWorld(db)
    with db.transaction() as tx:
        season = seed_season(tx)
        episode = seed_episode(tx, season)
        account = uuid.uuid4()
        tx.execute(
            "INSERT INTO budget_accounts (id, scope_kind, season_id, episode_id, "
            "cap_micro_usd, reserved_outstanding_micro_usd) "
            "VALUES (%s, 'EPISODE', %s, %s, 10000000, 900000)",
            (account, season, episode),
        )
        for category in (
            "RESEARCH_SCRIPT_PROMPTS_METADATA",
            "REFERENCES_DIALOGUE",
            "QA_CAPTIONS",
            "CPU_STORAGE_TRANSFER",
            "RECOVERY_HEADROOM",
            "METERED_MANAGEMENT",
        ):
            tx.execute(
                "INSERT INTO budget_category_allocations (account_id, category, "
                "allocated_micro_usd, protected) VALUES (%s, %s, 0, %s)",
                (account, category, "false" if category == "METERED_MANAGEMENT" else "true"),
            )
        tx.execute(
            "INSERT INTO budget_category_allocations (account_id, category, "
            "allocated_micro_usd, reserved_outstanding_micro_usd, protected) "
            "VALUES (%s, 'GPU_GENERATION', 900000, 900000, true)",
            (account,),
        )
        reservation = uuid.uuid4()
        tx.execute(
            "INSERT INTO reservations (id, account_id, request_id, semantic_key, "
            "request_hash, category, queue, provider, operation_kind, price, ceilings, "
            "reserved_micro_usd, state, expires_at) "
            "VALUES (%s, %s, %s, %s, %s, 'GPU_GENERATION', 'production', 'fake-runpod', "
            "'pod.lease', '{}', '{}', 900000, 'ACTIVE', %s)",
            (
                reservation,
                account,
                uuid.uuid4(),
                f"f1:{reservation}",
                "0" * 64,
                T0 + timedelta(hours=6),
            ),
        )
        lease = uuid.uuid4()
        tx.execute(
            "INSERT INTO pod_leases (id, provider, pod_id, owned_tag, client_token, "
            "owner_episode_id, reservation_id, lease_state, pod_state, gpu_type, "
            "hourly_price_micro_usd, lease_expires_at, create_requested_at, "
            "compute_window_start_at) "
            "VALUES (%s, 'fake-runpod', 'f1-pod-0001', 'microdrama-owned:f1', %s, %s, %s, "
            "'ACTIVE', 'RUNNING', 'FAKE-GPU-24GB', %s, %s, %s, %s)",
            (
                lease,
                f"tok-{lease}",
                episode,
                reservation,
                PRICE,
                T0 + timedelta(hours=6),
                T0,
                T0,
            ),
        )
    world.provider._pods["f1-pod-0001"] = _Pod(
        pod_id="f1-pod-0001",
        name="recovered-f1-pod-0001",
        owned_tag="microdrama-owned:f1",
        client_token=f"tok-{lease}",
        gpu_type="FAKE-GPU-24GB",
        hourly_price_micro_usd=PRICE,
        created_at=T0,
        endpoint_url=fake_https("f1-pod-0001.pods.fake", ""),
        pipeline_owned=True,
    )
    budget = ExperimentBudgetService(
        db, world.clock, world.ids, world.settings, experiment_id=uuid.uuid4()
    )
    return world, budget, lease, reservation, episode


def _charges(db: Database, reservation_id) -> list[dict]:
    with db.transaction(readonly=True) as tx:
        return tx.fetchall(
            "SELECT kind, amount_micro_usd, provider_receipt_id FROM charges "
            "WHERE reservation_id=%s ORDER BY created_at, id",
            (reservation_id,),
        )


def _settled_total(db: Database, reservation_id) -> int:
    with db.transaction(readonly=True) as tx:
        return int(
            tx.fetchval("SELECT settled_micro_usd FROM reservations WHERE id=%s", (reservation_id,))
            or 0
        )


def test_hc2_settle_replay_keeps_receipt_identity_and_content(db: Database) -> None:
    """HC-2 proof 1: the deterministic settle receipt replays identically.

    The P4 flip rebuilt the same receipt_id as an ADJUSTMENT once the
    reservation had closed, so an ordinary replay raised IdempotencyConflict.
    """
    world, budget, lease, reservation, _episode = _elapsed_lease(db)
    accrue_lease_usage(db, budget, world.manager, lease_id=lease, until=T0 + timedelta(seconds=600))
    first = settle_from_recorded_usage(db, budget, world.settings, lease_id=lease, context="f1")
    accrued = PRICE * 600_000 // 3_600_000
    assert first.settled_micro_usd == accrued
    assert _settled_total(db, reservation) == accrued

    # The replay a retried sweep performs: same identity, same content.
    second = settle_from_recorded_usage(db, budget, world.settings, lease_id=lease, context="f1")
    assert second.settled_micro_usd == accrued
    rows = _charges(db, reservation)
    assert [row["kind"] for row in rows].count("SETTLEMENT") == 1
    assert len(rows) == 2  # one ACCRUAL, one SETTLEMENT - the replay added nothing
    assert _settled_total(db, reservation) == accrued


def test_hc2_closed_reservation_with_prior_late_adjustment_never_restates(
    db: Database,
) -> None:
    """HC-2 proof 2: a closed hold's settle never restates its late cost.

    A prior late adjustment of 100 must stay 100: the settle on the closed
    reservation reuses the recorded final and posts only genuinely new deltas
    (there are none). The P4 flip reposted ``_settlement_totals`` as another
    ADJUSTMENT - 100 became 200.
    """
    world, budget, lease, reservation, episode = _elapsed_lease(db)
    accrue_lease_usage(db, budget, world.manager, lease_id=lease, until=T0 + timedelta(seconds=600))
    settle_from_recorded_usage(db, budget, world.settings, lease_id=lease, context="f1")
    accrued = PRICE * 600_000 // 3_600_000

    late = UsageReceipt(
        receipt_id=uuid5(lease, "f1-late-100"),
        provider="fake-runpod",
        provider_receipt_id="f1-late-100",
        kind=ReceiptKind.ADJUSTMENT,
        cost_basis=CostBasis.SYNTHETIC_FAKE,
        reservation_id=reservation,
        episode_id=episode,
        season_id=None,
        category=BudgetCategory.GPU_GENERATION,
        amount_micro_usd=100,
        currency="USD",
        units=0,
        unit=PriceUnit.GPU_SECOND,
        interval_start=None,
        interval_end=None,
        observed_at=T0,
        provenance=Provenance.FAKE_SYNTHETIC,
    )
    budget.record_usage(late)
    assert _settled_total(db, reservation) == accrued + 100

    # The settle the incident path performs on the CLOSED hold: reuse, never
    # a second final amount.
    again = settle_from_recorded_usage(db, budget, world.settings, lease_id=lease, context="f1")
    assert again.settled_micro_usd == accrued + 100
    rows = _charges(db, reservation)
    assert [row["kind"] for row in rows].count("SETTLEMENT") == 1
    assert [row["kind"] for row in rows].count("ADJUSTMENT") == 1
    assert _settled_total(db, reservation) == accrued + 100  # 100 stays 100


def test_hc2_late_interval_crash_before_accrued_until_replays_cleanly(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HC-2 proof 3: a crash after the interval post but before the
    ``accrued_until`` advance replays cleanly.

    The P4 conversion rewrote the stored receipt to an ADJUSTMENT AFTER its
    replay check, so the crash replay presented the original ACCRUAL payload
    against the stored ADJUSTMENT and raised IdempotencyConflict. The benchmark
    layer's late receipts keep one immutable identity for the late window.
    """
    world, budget, lease, reservation, _episode = _elapsed_lease(db)
    accrue_lease_usage(db, budget, world.manager, lease_id=lease, until=T0 + timedelta(seconds=600))
    settle_from_recorded_usage(db, budget, world.settings, lease_id=lease, context="f1")

    # The hold is closed; the pod keeps billing (it is discovered late). The
    # interval post commits, then the process dies before accrued_until moves.
    from microdrama.rendering import leases as leases_module

    original = leases_module.update_with_revision

    def dying_advance(tx, table, row_id, revision, values, **kwargs):
        if table == "pod_leases" and "accrued_until" in values:
            raise RuntimeError("died after the interval post, before accrued_until")
        return original(tx, table, row_id, revision, values, **kwargs)

    monkeypatch.setattr(leases_module, "update_with_revision", dying_advance)
    with pytest.raises(RuntimeError):
        accrue_lease_usage(
            db, budget, world.manager, lease_id=lease, until=T0 + timedelta(seconds=1200)
        )
    monkeypatch.undo()

    # The replay: same interval, same receipt - converges, posts nothing new.
    accrue_lease_usage(
        db, budget, world.manager, lease_id=lease, until=T0 + timedelta(seconds=1200)
    )
    rows = _charges(db, reservation)
    adjustments = [row for row in rows if row["kind"] == "ADJUSTMENT"]
    assert len(adjustments) == 1  # exactly one late charge for the second window
    assert adjustments[0]["amount_micro_usd"] == PRICE * 600_000 // 3_600_000
    assert adjustments[0]["provider_receipt_id"].startswith("late:")
    with db.transaction(readonly=True) as tx:
        advanced = tx.fetchval("SELECT accrued_until FROM pod_leases WHERE id=%s", (lease,))
    assert advanced == T0 + timedelta(seconds=1200)


def test_hc2_incident_path_bills_discovered_pod_once_as_adjustments(db: Database, tmp_path) -> None:
    """The §6.4 incident path's late billing, end to end: the discovered pod's
    cost lands as exactly one ADJUSTMENT per interval on the closed hold, the
    settle reuses the recorded final (never a restatement), and the replay
    adds nothing."""
    from test_t031_h2b_p2_gate import _item_kinds
    from test_t031_h2b_p4_resolution import _at6_context, _hold_states, _service

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
    # The disproved pod appears: created by the ORIGINAL create attempt (its
    # provider-side created_at is that create instant), found by the janitor
    # after the worker died.
    with db.transaction(readonly=True) as tx:
        token = tx.fetchval("SELECT client_token FROM pod_leases WHERE id=%s", (fixed["lease_id"],))
    pod_created = comfy.clock.now()
    world.provider._pods["late-f1-pod"] = _Pod(
        pod_id="late-f1-pod",
        name="recovered-late-f1-pod",
        owned_tag=world.config.owned_tag,
        client_token=token,
        gpu_type="FAKE-GPU-24GB",
        hourly_price_micro_usd=900_000,
        created_at=pod_created,
        endpoint_url=fake_https("late-f1-pod.pods.fake", ""),
        pipeline_owned=True,
    )
    comfy.clock.advance(seconds=3601)  # the worker is gone; the lease expired
    world.janitor().sweep()
    with db.transaction(readonly=True) as tx:
        compute = tx.fetchone(
            "SELECT r.id, r.settled_micro_usd, l.terminate_verified_at FROM "
            "benchmark_reservation_links k JOIN reservations r ON r.id=k.reservation_id "
            "JOIN pod_leases l ON l.id=%s WHERE k.acquisition_id=%s AND k.purpose='COMPUTE'",
            (fixed["lease_id"], fixed["acquisition_id"]),
        )
    assert compute["terminate_verified_at"] is not None

    _service(fixed).sweep(plan.experiment_id)  # cleanup; HC-1: storage RETAINED while billing pends
    assert "U5" in _item_kinds(db, plan.experiment_id, comfy.clock)
    assert _hold_states(db, fixed["acquisition_id"])["STORAGE"] == "ACTIVE"

    rows = _charges(db, compute["id"])
    adjustments = [row for row in rows if row["kind"] == "ADJUSTMENT"]
    # Exactly one late ADJUSTMENT for the discovered pod's one billed window -
    # the P4 settle flip reposted the total as a second ADJUSTMENT.
    assert len(adjustments) == 1, rows
    ms = int((compute["terminate_verified_at"] - pod_created).total_seconds() * 1000)
    expected = -(-(900_000 * ms) // 3_600_000)
    assert adjustments[0]["amount_micro_usd"] == expected
    assert _settled_total(db, compute["id"]) == expected  # settled once, never restated

    # HC-1 (F3): the discovered pod's canonical INVOICE finality - the
    # verified invoice covering its liability window, with the recovery
    # allocation the degenerate adopted window opens resolved through the
    # audited canonical tail - is what finalizes; the invoice equals the
    # recorded interval cost.
    from test_t031_hcf_f3_finality import _bill_lease_to_billed

    _bill_lease_to_billed(db, fixed["world"], lease_id=fixed["lease_id"], amount_micro_usd=expected)
    _service(fixed).sweep(plan.experiment_id)
    assert "U5" not in _item_kinds(db, plan.experiment_id, comfy.clock)
    assert _hold_states(db, fixed["acquisition_id"])["STORAGE"] != "ACTIVE"
    assert _charges(db, compute["id"]) == rows
    assert _settled_total(db, compute["id"]) == expected

    # The sweep replay adds nothing.
    _service(fixed).sweep(plan.experiment_id)
    assert _charges(db, compute["id"]) == rows
    assert _settled_total(db, compute["id"]) == expected
