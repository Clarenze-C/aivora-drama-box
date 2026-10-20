"""Shutdown reserve and blocked-account bypass (V-1, V-19).

Only a production cleanup operation may draw on the shutdown reserve or bypass the blocked flag: a pod
stop or terminate in GPU or recovery work, or a storage cleanup in CPU/storage or recovery work. A
flagged render is refused even at cap minus reserve, where an unflagged render would be refused by the
floor. The contract refuses these shapes; the service refuses them again for requests built past it.
"""

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


def _flagged(ep_id, **kwargs):
    """A request that asks for the shutdown reserve. model_copy skips validation on purpose: these
    are the shapes the contract refuses, to exercise the service's own refusal."""
    return request_for(**kwargs).model_copy(update={"is_shutdown_or_cleanup": True})


def test_contract_refuses_flagged_renders_and_non_cleanup_queues_and_accepts_pod_stop() -> None:
    base = dict(
        request_for(
            key="v19.contract",
            episode_id=None,
            worst=1_000_000,
            category=METERED,
            queue=QueueName.COMMUNITY,
            operation_kind="pod.stop",
        ).model_dump()
    )
    with pytest.raises(ValidationError):  # community pod stop: not production
        BudgetReservationRequest(**{**base, "is_shutdown_or_cleanup": True})
    render = {
        **base,
        "queue": QueueName.PRODUCTION,
        "category": GPU,
        "operation_kind": "gpu.render_shot",
        "is_shutdown_or_cleanup": True,
    }
    with pytest.raises(ValidationError):  # V-19: a flagged render
        BudgetReservationRequest(**render)
    BudgetReservationRequest(**{**render, "operation_kind": "pod.stop"})  # a real stop is valid


def test_flagged_render_at_cap_minus_reserve_is_refused_and_writes_nothing(
    world: World, check_consistent, db: Database
) -> None:
    ep = world.episode()
    fill_to_cap_minus_shutdown(world, ep)
    before = world.counters(ep.account_id)
    assert before["committed"] == 9_750_000
    flagged_render = _flagged(
        ep.episode_id,
        key="v19.render.flagged",
        episode_id=ep.episode_id,
        worst=250_000,
        category=GPU,
        operation_kind="gpu.render_shot",
    )
    with pytest.raises(PolicyDenied):
        world.service.reserve(flagged_render)
    assert world.counters(ep.account_id) == before
    # Control: the same render without the flag is refused by the floor, not admitted.
    with pytest.raises(BudgetExhausted):
        world.service.reserve(
            request_for(key="v19.render.plain", episode_id=ep.episode_id, worst=250_000)
        )
    check_consistent(ep.account_id)


def test_a_later_real_pod_stop_still_reserves_into_the_shutdown_reserve(
    world: World, check_consistent
) -> None:
    ep = world.episode()
    fill_to_cap_minus_shutdown(world, ep)
    stop = world.service.reserve(
        request_for(
            key="v19.pod.stop",
            episode_id=ep.episode_id,
            worst=250_000,
            cleanup=True,
            operation_kind="pod.stop",
        )
    )
    assert stop.reserved_micro_usd == 250_000
    assert world.counters(ep.account_id)["committed"] == 10_000_000  # the reserve is funded
    check_consistent(ep.account_id)


def test_storage_cleanup_works_only_in_cpu_storage_and_recovery(
    world: World, check_consistent
) -> None:
    ep = world.episode()
    svc = world.service
    svc.reserve(
        request_for(
            key="v19.storage.cpu",
            episode_id=ep.episode_id,
            worst=250_000,
            category=CPU,
            cleanup=True,
            operation_kind="storage.cleanup",
        )
    )
    svc.reserve(
        request_for(
            key="v19.storage.recovery",
            episode_id=ep.episode_id,
            worst=250_000,
            category=RECOVERY,
            cleanup=True,
            operation_kind="storage.cleanup",
        )
    )
    # The contract allows these shapes (GPU is a cleanup category, storage.cleanup a cleanup kind),
    # so the service is the place that refuses them.
    storage_on_gpu = request_for(
        key="v19.storage.gpu",
        episode_id=ep.episode_id,
        worst=250_000,
        category=GPU,
        cleanup=True,
        operation_kind="storage.cleanup",
    )
    with pytest.raises(PolicyDenied):
        svc.reserve(storage_on_gpu)
    pod_stop_on_cpu = request_for(
        key="v19.pod.cpu",
        episode_id=ep.episode_id,
        worst=250_000,
        category=CPU,
        cleanup=True,
        operation_kind="pod.stop",
    )
    with pytest.raises(PolicyDenied):
        svc.reserve(pod_stop_on_cpu)
    check_consistent(ep.account_id)


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
    community = _flagged(
        ep.episode_id,
        key="v1.community.cleanup",
        episode_id=ep.episode_id,
        worst=1,
        category=METERED,
        queue=QueueName.COMMUNITY,
        operation_kind="pod.stop",
    )
    publication = _flagged(
        ep.episode_id,
        key="v1.publication.cleanup",
        episode_id=ep.episode_id,
        worst=1,
        category=CPU,
        queue=QueueName.PUBLICATION,
        operation_kind="storage.cleanup",
    )
    with pytest.raises(PolicyDenied):
        svc.reserve(community)
    with pytest.raises(PolicyDenied):
        svc.reserve(publication)
    assert world.counters(ep.account_id) == before
    check_consistent(ep.account_id)


def test_blocked_account_bypass_is_granted_only_to_production_cleanup(
    world: World, check_consistent
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

    community = _flagged(
        ep.episode_id,
        key="v1.blocked.community",
        episode_id=ep.episode_id,
        worst=1,
        category=METERED,
        queue=QueueName.COMMUNITY,
        operation_kind="pod.stop",
    )
    with pytest.raises(PolicyDenied):  # blocked does not turn a non-production flag into a grant
        svc.reserve(community)
    with pytest.raises(BudgetExhausted):  # new paid work is still stopped
        svc.reserve(request_for(key="v1.paid.while.blocked", episode_id=ep.episode_id, worst=1))

    svc.release(held["met"].id, reason="community plan withdrawn")
    cleanup = svc.reserve(
        request_for(
            key="v1.production.cleanup",
            episode_id=ep.episode_id,
            worst=250_000,
            category=RECOVERY,
            cleanup=True,
            operation_kind="pod.stop",
        )
    )
    assert cleanup.reserved_micro_usd == 250_000
    counters = world.counters(ep.account_id)
    assert counters["blocked"] is True and counters["overrun"] == 750_000
    assert counters["committed"] == 10_000_000
    check_consistent(ep.account_id)
