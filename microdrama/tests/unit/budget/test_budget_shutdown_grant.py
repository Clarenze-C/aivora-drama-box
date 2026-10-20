"""V-1: only production GPU, recovery or storage shutdown/cleanup may use the shutdown reserve and
bypass the blocked-account flag. Community and publication requests with the flag are refused, both
by the contract and, for requests built past it, by the service (one helper decides both)."""

from __future__ import annotations

import pytest
from budget_support import (
    CPU,
    GPU,
    METERED,
    RECOVERY,
    World,
    fake_receipt,
    fill_to_cap_minus_shutdown,
    request_for,
)
from pydantic import ValidationError

from microdrama.contracts.cost import BudgetReservationRequest
from microdrama.contracts.enums import QueueName, ReceiptKind
from microdrama.contracts.errors import BudgetExhausted, PolicyDenied
from microdrama.persistence import Database

pytestmark = pytest.mark.db


def _community_cleanup(ep_id, worst: int):
    return request_for(
        key="v1.community.cleanup",
        episode_id=ep_id,
        worst=worst,
        category=METERED,
        queue=QueueName.COMMUNITY,
    ).model_copy(update={"is_shutdown_or_cleanup": True})


def _publication_cleanup(ep_id, worst: int):
    return request_for(
        key="v1.publication.cleanup",
        episode_id=ep_id,
        worst=worst,
        category=CPU,
        queue=QueueName.PUBLICATION,
    ).model_copy(update={"is_shutdown_or_cleanup": True})


def test_contract_refuses_cleanup_outside_production_gpu_recovery_and_storage() -> None:
    base = request_for(
        key="v1.contract",
        episode_id=None,
        worst=1_000_000,
        category=METERED,
        queue=QueueName.COMMUNITY,
    ).model_dump()
    with pytest.raises(ValidationError):
        BudgetReservationRequest(**{**base, "is_shutdown_or_cleanup": True})
    gpu = {**base, "queue": QueueName.PRODUCTION, "category": GPU, "is_shutdown_or_cleanup": True}
    BudgetReservationRequest(**gpu)  # production GPU cleanup is valid


def test_community_and_publication_cleanup_is_refused_by_the_service_and_writes_nothing(
    world: World, check_consistent
) -> None:
    ep = world.episode()
    svc = world.service
    # Control: the same community request without the flag is admitted.
    svc.reserve(
        request_for(
            key="v1.control",
            episode_id=ep.episode_id,
            worst=1_000_000,
            category=METERED,
            queue=QueueName.COMMUNITY,
        )
    )
    before = world.counters(ep.account_id)
    with pytest.raises(PolicyDenied):
        svc.reserve(_community_cleanup(ep.episode_id, 1))
    with pytest.raises(PolicyDenied):
        svc.reserve(_publication_cleanup(ep.episode_id, 1))
    with pytest.raises(PolicyDenied):
        svc.reserve(
            request_for(
                key="v1.gpu.community",
                episode_id=ep.episode_id,
                worst=1,
                category=GPU,
                queue=QueueName.COMMUNITY,
            ).model_copy(update={"is_shutdown_or_cleanup": True})
        )
    assert world.counters(ep.account_id) == before
    check_consistent(ep.account_id)


def test_blocked_account_bypass_is_granted_only_to_production_cleanup(
    world: World, check_consistent, db: Database
) -> None:
    ep = world.episode()
    svc = world.service
    held = fill_to_cap_minus_shutdown(world, ep)
    # Observed overrun: the 3,250,000 final on the 2,250,000 hold pushes committed to 10,750,000.
    svc.record_usage(
        fake_receipt(
            provider_receipt_id="v1.blocked.final",
            kind=ReceiptKind.SETTLEMENT,
            amount=3_250_000,
            reservation=held["gpu2"],
            episode_id=ep.episode_id,
            observed_at=world.clock.now(),
        )
    )
    assert world.counters(ep.account_id)["blocked"] is True

    with pytest.raises(PolicyDenied):  # blocked does not turn a non-production flag into a grant
        svc.reserve(_community_cleanup(ep.episode_id, 1))
    with pytest.raises(PolicyDenied):
        svc.reserve(_publication_cleanup(ep.episode_id, 1))
    with pytest.raises(BudgetExhausted):  # new paid work is still stopped
        svc.reserve(request_for(key="v1.paid.while.blocked", episode_id=ep.episode_id, worst=1))

    # Release the community hold (no usage): committed drops to 9,750,000 and the block stays.
    svc.release(held["met"].id, reason="community plan withdrawn")
    # Production recovery cleanup is still admitted while blocked, because the cap allows it.
    cleanup = svc.reserve(
        request_for(
            key="v1.production.cleanup",
            episode_id=ep.episode_id,
            worst=250_000,
            category=RECOVERY,
            cleanup=True,
        )
    )
    assert cleanup.reserved_micro_usd == 250_000
    counters = world.counters(ep.account_id)
    assert counters["blocked"] is True and counters["overrun"] == 750_000
    assert counters["committed"] == 10_000_000
    check_consistent(ep.account_id)


def test_production_gpu_cleanup_still_reaches_the_shutdown_reserve_when_not_blocked(
    world: World, check_consistent
) -> None:
    ep = world.episode()
    cleanup = world.service.reserve(
        request_for(key="v1.gpu.cleanup", episode_id=ep.episode_id, worst=1_000_000, cleanup=True)
    )
    assert cleanup.state.value == "ACTIVE"
    check_consistent(ep.account_id)
