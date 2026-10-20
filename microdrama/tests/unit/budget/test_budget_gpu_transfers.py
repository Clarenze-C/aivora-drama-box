"""GPU interval attribution (counted once) and transfer rules (protected reserves)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from budget_support import (
    GPU,
    METERED,
    QA,
    RECOVERY,
    REFERENCES,
    RESEARCH,
    T0,
    World,
    fake_receipt,
    request_for,
)

from microdrama.contracts.enums import CostBasis, Provenance, ReceiptKind
from microdrama.contracts.errors import (
    Conflict,
    PolicyDenied,
    ProtectedReserveViolation,
    SchemaInvalid,
)

MIN = timedelta(minutes=1)


def _lease_setup(world: World, *, lease_pod: str = "pod-1"):
    ep = world.episode()
    res = world.service.reserve(
        request_for(key="gpu.lease.res", episode_id=ep.episode_id, worst=900_000)
    )
    lease = world.lease(episode=ep, reservation=res, pod_id=lease_pod)
    return ep, res, lease


def _interval(
    world,
    *,
    ep,
    res,
    lease,
    key: str,
    start_min: int,
    end_min: int,
    amount: int,
    pod_id: str = "pod-1",
    provider: str = "fake-runpod",
    basis: str = "RUNNING",
):
    receipt = fake_receipt(
        provider_receipt_id=key,
        kind=ReceiptKind.ACCRUAL,
        amount=amount,
        category=GPU,
        reservation=res,
        episode_id=ep.episode_id,
        observed_at=T0 + timedelta(minutes=end_min),
        interval=(T0 + start_min * MIN, T0 + end_min * MIN),
        provider=provider,
    )
    return world.service.record_gpu_interval(
        lease_id=lease,
        provider=provider,
        pod_id=pod_id,
        account_id=ep.account_id,
        interval_start=T0 + start_min * MIN,
        interval_end=T0 + end_min * MIN,
        basis=basis,
        receipt=receipt,
    )


def test_gpu_interval_is_counted_once_even_when_reported_twice(
    world: World, check_consistent
) -> None:
    ep, res, lease = _lease_setup(world)
    first = _interval(
        world, ep=ep, res=res, lease=lease, key="iv.1", start_min=0, end_min=10, amount=300_000
    )
    again = _interval(
        world, ep=ep, res=res, lease=lease, key="iv.1", start_min=0, end_min=10, amount=300_000
    )
    assert again.replayed is True and again.charge_id == first.charge_id
    counters = world.counters(ep.account_id)
    assert counters["accrued"] == 300_000 and counters["reserved"] == 600_000
    assert world.count("SELECT count(*) FROM pod_usage_intervals") == 1
    check_consistent(ep.account_id)


def test_overlapping_interval_from_another_lease_is_refused_and_adjacent_is_allowed(
    world: World, check_consistent
) -> None:
    ep, res, lease = _lease_setup(world)
    other_res = world.service.reserve(
        request_for(key="gpu.other.res", episode_id=ep.episode_id, worst=900_000)
    )
    # Warm-pod reuse: a released lease of the same pod reports the same paid time late.
    released = world.lease(
        episode=ep, reservation=other_res, pod_id="pod-1", lease_state="RELEASED"
    )
    _interval(
        world, ep=ep, res=res, lease=lease, key="ov.a", start_min=0, end_min=10, amount=300_000
    )
    before = world.counters(ep.account_id)
    with pytest.raises(Conflict, match="already attributed"):
        _interval(
            world,
            ep=ep,
            res=other_res,
            lease=released,
            key="ov.b.same",
            start_min=0,
            end_min=10,
            amount=300_000,
        )
    with pytest.raises(Conflict, match="already attributed"):
        _interval(
            world,
            ep=ep,
            res=other_res,
            lease=released,
            key="ov.b.partial",
            start_min=5,
            end_min=15,
            amount=300_000,
        )
    assert world.counters(ep.account_id) == before  # totals unchanged by the refusals
    _interval(
        world,
        ep=ep,
        res=other_res,
        lease=released,
        key="ov.b.adjacent",
        start_min=10,
        end_min=20,
        amount=200_000,
    )
    counters = world.counters(ep.account_id)
    assert counters["accrued"] == 500_000
    assert world.count("SELECT count(*) FROM pod_usage_intervals") == 2
    check_consistent(ep.account_id)


def test_interval_must_name_its_lease_reservation_pod_and_basis(
    world: World, check_consistent
) -> None:
    ep, res, lease = _lease_setup(world)
    other = world.service.reserve(
        request_for(key="gpu.foreign.res", episode_id=ep.episode_id, worst=900_000)
    )
    before = world.counters(ep.account_id)
    with pytest.raises(Conflict):
        _interval(
            world,
            ep=ep,
            res=res,
            lease=lease,
            key="bad.pod",
            start_min=0,
            end_min=5,
            amount=10,
            pod_id="pod-other",
        )
    with pytest.raises(Conflict):
        _interval(
            world, ep=ep, res=other, lease=lease, key="bad.res", start_min=0, end_min=5, amount=10
        )
    with pytest.raises(Conflict):  # a provider other than the lease's is not this pod's interval
        _interval(
            world,
            ep=ep,
            res=res,
            lease=lease,
            key="bad.provider",
            start_min=0,
            end_min=5,
            amount=10,
            provider="other-provider",
        )
    with pytest.raises(SchemaInvalid):
        _interval(
            world,
            ep=ep,
            res=res,
            lease=lease,
            key="bad.basis",
            start_min=0,
            end_min=5,
            amount=10,
            basis="NAPPING",
        )
    with pytest.raises(SchemaInvalid):
        _interval(
            world,
            ep=ep,
            res=res,
            lease=lease,
            key="bad.reversed",
            start_min=5,
            end_min=5,
            amount=10,
        )
    assert world.counters(ep.account_id) == before
    check_consistent(ep.account_id)


def test_lease_reservation_settles_after_its_interval_accruals(
    world: World, check_consistent
) -> None:
    ep, res, lease = _lease_setup(world)
    _interval(
        world, ep=ep, res=res, lease=lease, key="cyc.1", start_min=0, end_min=10, amount=300_000
    )
    _interval(
        world,
        ep=ep,
        res=res,
        lease=lease,
        key="cyc.2",
        start_min=10,
        end_min=20,
        amount=200_000,
        basis="IDLE",
    )
    world.service.record_usage(
        fake_receipt(
            provider_receipt_id="cyc.final",
            kind=ReceiptKind.SETTLEMENT,
            amount=500_000,
            reservation=res,
            episode_id=ep.episode_id,
            observed_at=T0 + 20 * MIN,
        )
    )
    counters = world.counters(ep.account_id)
    assert counters["reserved"] == 0 and counters["accrued"] == 0
    assert counters["settled"] == 500_000 and counters["committed"] == 500_000
    assert world.count("SELECT count(*) FROM pod_usage_intervals") == 2
    check_consistent(ep.account_id)


def test_gpu_interval_receipts_follow_the_same_mode_rules(world: World, check_consistent) -> None:
    ep, res, lease = _lease_setup(world)
    billed = fake_receipt(
        provider_receipt_id="mode.1",
        kind=ReceiptKind.ACCRUAL,
        amount=1,
        reservation=res,
        episode_id=ep.episode_id,
        observed_at=T0,
        interval=(T0, T0 + MIN),
    ).model_copy(update={"cost_basis": CostBasis.BILLED, "provenance": Provenance.LIVE_PROVIDER})
    with pytest.raises(PolicyDenied):
        world.service.record_gpu_interval(
            lease_id=lease,
            provider="fake-runpod",
            pod_id="pod-1",
            account_id=ep.account_id,
            interval_start=T0,
            interval_end=T0 + MIN,
            basis="RUNNING",
            receipt=billed,
        )
    check_consistent(ep.account_id)


# --- transfers ------------------------------------------------------------------------


def test_transfer_into_metered_management_from_protected_funds_is_refused(
    world: World, check_consistent
) -> None:
    ep = world.episode()
    for source in (GPU, REFERENCES, RECOVERY):
        with pytest.raises(ProtectedReserveViolation):
            world.service.transfer(
                ep.account_id,
                from_category=source,
                to_category=METERED,
                amount=100_000,
                reason="community wants more",
            )
    assert world.category(ep.account_id, METERED)["allocated"] == 1_000_000
    assert world.category(ep.account_id, GPU)["allocated"] == 2_500_000
    check_consistent(ep.account_id)


def test_transfer_cannot_leave_the_source_below_its_committed_spend(
    world: World, check_consistent, db
) -> None:
    ep = world.episode()
    world.service.reserve(request_for(key="xfer.gpu", episode_id=ep.episode_id, worst=2_000_000))
    with pytest.raises(ProtectedReserveViolation):
        world.service.transfer(
            ep.account_id, from_category=GPU, to_category=QA, amount=1_000_000, reason="too much"
        )
    world.service.transfer(
        ep.account_id, from_category=GPU, to_category=QA, amount=500_000, reason="qa needs headroom"
    )
    assert world.category(ep.account_id, GPU)["allocated"] == 2_000_000
    assert world.category(ep.account_id, QA)["allocated"] == 1_500_000
    with db.transaction() as tx:
        rows = tx.fetchall(
            "SELECT amount_micro_usd, reason FROM budget_transfers WHERE account_id = %s",
            (ep.account_id,),
        )
    assert [(r["amount_micro_usd"], r["reason"]) for r in rows] == [(500_000, "qa needs headroom")]
    check_consistent(ep.account_id)


def test_recovery_headroom_transfer_keeps_the_shutdown_reserve(
    world: World, check_consistent
) -> None:
    ep = world.episode()
    world.service.transfer(
        ep.account_id,
        from_category=RECOVERY,
        to_category=RESEARCH,
        amount=2_250_000,
        reason="research sprint",
    )
    assert world.category(ep.account_id, RECOVERY)["allocated"] == 250_000
    with pytest.raises(ProtectedReserveViolation):
        world.service.transfer(
            ep.account_id,
            from_category=RECOVERY,
            to_category=RESEARCH,
            amount=1,
            reason="one more micro-USD",
        )
    check_consistent(ep.account_id)


def test_metered_leftover_can_return_to_production_and_totals_stay_fixed(
    world: World, check_consistent
) -> None:
    ep = world.episode()
    world.service.transfer(
        ep.account_id,
        from_category=METERED,
        to_category=GPU,
        amount=500_000,
        reason="community plan unused",
    )
    assert world.category(ep.account_id, GPU)["allocated"] == 3_000_000
    assert world.category(ep.account_id, METERED)["allocated"] == 500_000
    check_consistent(ep.account_id)  # the cap total still equals the sum of allocations


def test_transfer_arguments_are_validated(world: World) -> None:
    ep = world.episode()
    with pytest.raises(SchemaInvalid):
        world.service.transfer(
            ep.account_id, from_category=GPU, to_category=QA, amount=0, reason="x"
        )
    with pytest.raises(SchemaInvalid):
        world.service.transfer(
            ep.account_id, from_category=GPU, to_category=GPU, amount=1, reason="x"
        )
    with pytest.raises(SchemaInvalid):
        world.service.transfer(
            ep.account_id, from_category=GPU, to_category=QA, amount=1, reason=" "
        )
