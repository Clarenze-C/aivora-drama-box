"""V-2: release() refuses while provider work on the reservation is still in flight.

Probe (reproduced by the validator): reserve A, record a provider operation as SUBMITTED, release A,
reserve more, then A's late usage pushes committed past the cap. The release must be refused while
the operation is in flight, and allowed once it is terminal.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from budget_support import T0, World, fake_receipt, request_for

from microdrama.contracts.enums import ProviderOperationState, ReceiptKind
from microdrama.contracts.errors import BudgetExhausted, Conflict
from microdrama.contracts.hashing import canonical_hash
from microdrama.persistence import Database
from microdrama.persistence.db import insert_row

pytestmark = pytest.mark.db

IN_FLIGHT = [
    ProviderOperationState.PENDING_SUBMIT,
    ProviderOperationState.SUBMITTED,
    ProviderOperationState.RUNNING,
    ProviderOperationState.UNKNOWN,
]


def _operation(db: Database, reservation_id: uuid.UUID, state: ProviderOperationState) -> uuid.UUID:
    op_id = uuid.uuid4()
    with db.transaction() as tx:
        insert_row(
            tx,
            "provider_operations",
            {
                "id": op_id,
                "provider": "fake-runpod",
                "operation_kind": "gpu.render_shot",
                "client_token": f"op-{op_id.hex}",
                "request_hash": canonical_hash({"op": op_id.hex}),
                "reservation_id": reservation_id,
                "state": state.value,
                "deadline_at": T0 + timedelta(hours=1),
            },
        )
    return op_id


def _set_state(db: Database, op_id: uuid.UUID, state: ProviderOperationState) -> None:
    with db.transaction() as tx:
        tx.execute("UPDATE provider_operations SET state = %s WHERE id = %s", (state.value, op_id))


@pytest.mark.parametrize("state", IN_FLIGHT, ids=lambda s: s.value)
def test_release_is_refused_while_the_operation_is_in_flight_and_allowed_once_terminal(
    world: World, db: Database, check_consistent, state: ProviderOperationState
) -> None:
    ep = world.episode()
    svc = world.service
    reservation = svc.reserve(
        request_for(key=f"v2.{state.value}", episode_id=ep.episode_id, worst=1_000_000)
    )
    op = _operation(db, reservation.id, state)
    with pytest.raises(Conflict, match="in flight"):
        svc.release(reservation.id, reason="cancelled by reviewer")
    assert world.reservation_state(reservation.id)["state"] == "ACTIVE"
    assert world.counters(ep.account_id)["committed"] == 1_000_000

    _set_state(db, op, ProviderOperationState.SUCCEEDED)
    released = svc.release(reservation.id, reason="cancelled by reviewer")
    assert released.state.value == "RELEASED"
    assert world.counters(ep.account_id)["committed"] == 0
    check_consistent(ep.account_id)


def test_probe_release_then_late_usage_cannot_breach_the_cap(
    world: World, db: Database, check_consistent
) -> None:
    """Probe from the validator: a 4,000,000 hold with a submitted operation cannot be released to
    make room for 5,000,000 more. The hold stays, the second reservation is refused, and the hold's
    later usage keeps committed within the cap."""
    ep = world.episode()
    svc = world.service
    hold = svc.reserve(request_for(key="v2.probe.hold", episode_id=ep.episode_id, worst=4_000_000))
    op = _operation(db, hold.id, ProviderOperationState.SUBMITTED)
    with pytest.raises(Conflict):
        svc.release(hold.id, reason="make room")
    with pytest.raises(BudgetExhausted):
        svc.reserve(request_for(key="v2.probe.more", episode_id=ep.episode_id, worst=5_000_000))
    svc.record_usage(
        fake_receipt(
            provider_receipt_id="v2.probe.usage",
            kind=ReceiptKind.SETTLEMENT,
            amount=4_000_000,
            reservation=hold,
            episode_id=ep.episode_id,
            observed_at=world.clock.now(),
        )
    )
    counters = world.counters(ep.account_id)
    assert counters["committed"] == 4_000_000 and counters["overrun"] == 0
    _set_state(db, op, ProviderOperationState.SUCCEEDED)
    check_consistent(ep.account_id)


def test_release_refuses_usage_and_names_in_flight_operations(world: World, db: Database) -> None:
    ep = world.episode()
    svc = world.service
    used = svc.reserve(request_for(key="v2.accrued", episode_id=ep.episode_id, worst=1_000_000))
    svc.record_usage(
        fake_receipt(
            provider_receipt_id="v2.accrued.usage",
            kind=ReceiptKind.ACCRUAL,
            amount=1,
            reservation=used,
            episode_id=ep.episode_id,
            observed_at=world.clock.now(),
        )
    )
    with pytest.raises(Conflict, match="settled, not released"):
        svc.release(used.id, reason="too late")

    idle = svc.reserve(request_for(key="v2.idle", episode_id=ep.episode_id, worst=1_000_000))
    op = _operation(db, idle.id, ProviderOperationState.RUNNING)
    with pytest.raises(Conflict) as refused:
        svc.release(idle.id, reason="also in flight")
    assert refused.value.details["operations"] == [str(op)]
    assert refused.value.details["states"] == ["RUNNING"]
    assert world.reservation_state(idle.id)["state"] == "ACTIVE"
