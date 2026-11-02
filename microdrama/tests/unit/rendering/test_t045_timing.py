"""T045 R8 (timing): durable create-request proof, compute-window bounds, the
no-create release guard for Runpod holds, and terminate-verified final release.

Red-first: every test here failed against the pre-T045 tree (no create_requested_at
write, no release guard, no transfer window end, no terminate path).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from uuid import UUID

import pytest
from rendering_support import T0, RenderWorld

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.errors import Conflict, NeedsReconciliation
from microdrama.persistence import Database
from microdrama.testing.fakes import (
    FakeClock,
    FakePodProvider,
    PodCreateScenario,
    SequentialIds,
)
from microdrama.testing.seed import seed_episode, seed_season

pytestmark = pytest.mark.db


class RunpodIdFakePods(FakePodProvider):
    """The T007 fake lifecycle addressed as the runpod provider (pairing only)."""

    provider_id = "runpod"


def _budget(db: Database) -> BudgetService:
    return BudgetService(db, FakeClock(T0), SequentialIds("t045-timing"), Settings())


def _insert_runpod_claim(tx, *, create_requested: bool) -> tuple[UUID, UUID]:
    season = seed_season(tx)
    episode = seed_episode(tx, season)
    account = uuid.uuid4()
    tx.execute(
        "INSERT INTO budget_accounts (id, scope_kind, season_id, episode_id, cap_micro_usd, "
        "reserved_outstanding_micro_usd) VALUES (%s, 'EPISODE', %s, %s, 10000000, 100000)",
        (account, season, episode),
    )
    for category in (
        "RESEARCH_SCRIPT_PROMPTS_METADATA",
        "REFERENCES_DIALOGUE",
        "QA_CAPTIONS",
        "CPU_STORAGE_TRANSFER",
        "RECOVERY_HEADROOM",
    ):
        tx.execute(
            "INSERT INTO budget_category_allocations (account_id, category, "
            "allocated_micro_usd, protected) VALUES (%s, %s, 0, true)",
            (account, category),
        )
    tx.execute(
        "INSERT INTO budget_category_allocations (account_id, category, allocated_micro_usd, "
        "reserved_outstanding_micro_usd, protected) "
        "VALUES (%s, 'GPU_GENERATION', 100000, 100000, true)",
        (account,),
    )
    tx.execute(
        "INSERT INTO budget_category_allocations (account_id, category, "
        "allocated_micro_usd, protected) VALUES (%s, 'METERED_MANAGEMENT', 0, false)",
        (account,),
    )
    reservation = uuid.uuid4()
    tx.execute(
        "INSERT INTO reservations (id, account_id, request_id, semantic_key, request_hash, "
        "category, queue, provider, operation_kind, price, ceilings, reserved_micro_usd, "
        "state, expires_at) VALUES (%s, %s, %s, %s, %s, 'GPU_GENERATION', 'production', "
        "'runpod', 'pod.lease', '{}', '{}', 100000, 'ACTIVE', %s)",
        (reservation, account, uuid.uuid4(), f"t045:{reservation}", "0" * 64, T0),
    )
    lease = uuid.uuid4()
    tx.execute(
        "INSERT INTO pod_leases (id, provider, pod_id, owned_tag, client_token, "
        "owner_episode_id, reservation_id, lease_state, pod_state, gpu_type, "
        "hourly_price_micro_usd, lease_expires_at, create_requested_at) "
        "VALUES (%s, 'runpod', NULL, 'md-owned', %s, %s, %s, 'CLAIMED', 'REQUESTED', 'FAKE', "
        "900000, %s, %s)",
        (
            lease,
            f"tok-{lease}",
            episode,
            reservation,
            T0 + timedelta(hours=1),
            T0 if create_requested else None,
        ),
    )
    return lease, reservation


def _reservation_state(db: Database, reservation_id: UUID) -> str:
    with db.transaction(readonly=True) as tx:
        return tx.fetchval("SELECT state FROM reservations WHERE id=%s", (reservation_id,))


def test_create_request_is_durable_before_the_create_call(world: RenderWorld) -> None:
    episode = world.episode()
    handle = world.claim(episode, "t045-create-proof")
    world.provider.queue_scenarios(PodCreateScenario.CREATE_TIMEOUT_NOT_CREATED)
    with pytest.raises(NeedsReconciliation):
        world.leases.ensure_pod(handle.lease.lease_id)
    # The request was durably recorded before the (ambiguous) create call: this is the
    # evidence the release guard keys on, and it survives the crash the timeout models.
    row = world.lease_row(handle.lease.lease_id)
    assert row["create_requested_at"] is not None
    assert row["compute_window_start_at"] == row["create_requested_at"]


def test_shutdown_of_an_ambiguous_create_keeps_the_runpod_hold(db: Database) -> None:
    # A runpod lease whose create was sent and whose reconcile-by-token found nothing:
    # the provider list miss the code itself calls out as not being proof of failure.
    with db.transaction() as tx:
        lease_id, reservation_id = _insert_runpod_claim(tx, create_requested=True)
    with pytest.raises(Conflict, match="billing finality"):
        _budget(db).release(reservation_id, reason="ambiguous create must keep the hold")
    assert _reservation_state(db, reservation_id) == "ACTIVE"


def test_claim_that_never_sent_a_create_still_releases(db: Database) -> None:
    with db.transaction() as tx:
        lease_id, reservation_id = _insert_runpod_claim(tx, create_requested=False)
    released = _budget(db).release(reservation_id, reason="nothing was ever sent")
    assert released.state.value == "RELEASED"
    assert _reservation_state(db, reservation_id) == "RELEASED"


def test_transferred_lease_window_end_is_the_transfer_instant(world: RenderWorld) -> None:
    episode = world.episode()
    other = world.episode(number=2)
    handle, _ = world.claim_and_acquire(episode, "t045-transfer-window")
    lease_id = handle.lease.lease_id
    world.clock.advance(seconds=600)
    transfer_instant = world.clock.now()
    world.leases.transfer(
        lease_id, to_episode_id=other.episode_id, to_semantic_key="t045-transfer-receiver"
    )
    old = world.lease_row(lease_id)
    assert old["lease_state"] == "RELEASED"
    assert old["compute_window_end_at"] == transfer_instant
    assert old["stop_verified_at"] is None
    new = world.live_leases()[0]
    assert new["transferred_from"] == lease_id
    assert new["compute_window_start_at"] == transfer_instant
    assert new["compute_window_end_at"] is None


def test_runpod_final_shutdown_terminates_and_records_verified_terminate(
    db: Database,
) -> None:
    provider = RunpodIdFakePods(clock=FakeClock(T0), ids=SequentialIds("t045-runpod"))
    world = RenderWorld(db, provider=provider)
    episode = world.episode()
    handle, _ = world.claim_and_acquire(episode, "t045-runpod-final")
    lease_id = handle.lease.lease_id
    result = world.leases.shutdown(lease_id, reason="t045 final release")
    calls = [c.method for c in provider.calls]
    assert "terminate_pod" in calls
    row = world.lease_row(lease_id)
    assert row["terminate_verified_at"] is not None
    assert row["compute_window_end_at"] == row["terminate_verified_at"]
    assert row["pod_state"] == "TERMINATED"
    assert result.stop_verified_at is not None


def test_fake_provider_shutdown_stays_stop_only(world: RenderWorld) -> None:
    episode = world.episode()
    handle, _ = world.claim_and_acquire(episode, "t045-fake-stop-only")
    lease_id = handle.lease.lease_id
    world.leases.shutdown(lease_id, reason="fake keeps the stop-only path")
    calls = [c.method for c in world.provider.calls]
    assert "terminate_pod" not in calls
    row = world.lease_row(lease_id)
    assert row["terminate_verified_at"] is None
    assert row["compute_window_end_at"] == row["stop_verified_at"]
