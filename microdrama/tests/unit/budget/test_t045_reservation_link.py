"""T045 R2 (G2): GPU postings link to the lease's own reservation; CPU/DISK post
unreserved; zero-delta rows post nothing at all.

Red-first: the GPU link used to be "newest runpod reservation of the account", which
billed the wrong lease's hold whenever two Runpod reservations existed on one account.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from budget_support import GPU, World, request_for
from budget_support import T0 as BT0
from t045_support import T0, closed_bucket, insert_runpod_lease

from microdrama.budget.billing import BillingRepository
from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode
from microdrama.persistence import Database

pytestmark = pytest.mark.db

HOUR = timedelta(hours=1)


def _paid(world: World) -> None:
    world.service._settings = Settings(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
    )


def test_gpu_posts_to_the_overlapping_leases_reservation_not_the_newest(
    world: World, db: Database
) -> None:
    _paid(world)
    episode = world.episode()
    # Two separate transactions so the reservations' created_at ordering is strict:
    # the root (earlier reservation) owns the bucket's minutes, the receiver was
    # reserved later, so "newest per account" would bill the receiver's hold.
    with db.transaction() as tx:
        root_lease, root_reservation = insert_runpod_lease(
            tx,
            episode.episode_id,
            pod_id="pod-link",
            client_token="tok-root",
            lease_state="RELEASED",
            create_requested_at=T0,
            compute_window_start_at=T0,
            compute_window_end_at=T0 + timedelta(minutes=30),
        )
    import time

    time.sleep(0.002)
    with db.transaction() as tx:
        insert_runpod_lease(
            tx,
            episode.episode_id,
            pod_id="pod-link",
            client_token="tok-receiver",
            lease_state="RELEASED",
            create_requested_at=T0 + timedelta(minutes=45),
            compute_window_start_at=T0 + timedelta(minutes=45),
            compute_window_end_at=T0 + HOUR,
            transferred_from=root_lease,
        )
    query, bucket = closed_bucket(
        pod_id="pod-link",
        start=T0 + timedelta(minutes=5),
        end=T0 + timedelta(minutes=10),
        gpu=600_000,
        cpu=0,
        disk=0,
    )
    BillingRepository(db, budget_service=world.service).ingest(query, [bucket])
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT reservation_id, category, kind FROM charges WHERE provider='runpod'"
        )
    assert row is not None
    assert row["reservation_id"] == root_reservation
    assert row["category"] == "GPU_GENERATION"


def test_uncovered_existence_gpu_posts_to_the_root_lease_reservation(
    world: World, db: Database
) -> None:
    _paid(world)
    episode = world.episode()
    with db.transaction() as tx:
        root_lease, root_reservation = insert_runpod_lease(
            tx,
            episode.episode_id,
            pod_id="pod-uncovered",
            lease_state="RELEASED",
            create_requested_at=T0,
            compute_window_start_at=T0,
            compute_window_end_at=T0 + timedelta(minutes=10),
        )
    import time

    time.sleep(0.002)
    with db.transaction() as tx:
        # A receiver whose window starts late leaves uncovered existence on the root.
        insert_runpod_lease(
            tx,
            episode.episode_id,
            pod_id="pod-uncovered",
            client_token="tok-late",
            lease_state="RELEASED",
            create_requested_at=T0 + timedelta(minutes=40),
            compute_window_start_at=T0 + timedelta(minutes=40),
            compute_window_end_at=T0 + HOUR,
            transferred_from=root_lease,
        )
    query, bucket = closed_bucket(
        pod_id="pod-uncovered",
        start=T0 + timedelta(minutes=15),
        end=T0 + timedelta(minutes=20),
        gpu=600_000,
        cpu=0,
        disk=0,
    )
    BillingRepository(db, budget_service=world.service).ingest(query, [bucket])
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone("SELECT reservation_id FROM charges WHERE provider='runpod'")
    assert row is not None
    assert row["reservation_id"] == root_reservation


def test_cpu_and_disk_post_unreserved_as_settled_spend(world: World, db: Database) -> None:
    _paid(world)
    episode = world.episode()
    with db.transaction() as tx:
        lease, _ = insert_runpod_lease(
            tx,
            episode.episode_id,
            pod_id="pod-cpu-disk",
            lease_state="RELEASED",
            create_requested_at=T0,
            compute_window_start_at=T0,
            compute_window_end_at=T0 + HOUR,
        )
        from t045_support import insert_storage_ownership

        insert_storage_ownership(
            tx, episode.episode_id, pod_id="pod-cpu-disk", valid_from=T0, creating_lease=lease
        )
    query, bucket = closed_bucket(
        pod_id="pod-cpu-disk", start=T0, end=T0 + HOUR, gpu=0, cpu=200_000, disk=100_000
    )
    BillingRepository(db, budget_service=world.service).ingest(query, [bucket])
    with db.transaction(readonly=True) as tx:
        rows = tx.fetchall(
            "SELECT category, reservation_id, amount_micro_usd FROM charges "
            "WHERE provider='runpod' ORDER BY category"
        )
    assert [(r["category"], r["reservation_id"]) for r in rows] == [
        ("CPU_STORAGE_TRANSFER", None),
        ("CPU_STORAGE_TRANSFER", None),
    ]
    assert sum(r["amount_micro_usd"] for r in rows) == 300_000
    after = world.counters(episode.account_id)
    assert after["settled"] == 300_000


def test_zero_delta_rows_post_nothing_and_never_block_reservations(
    world: World, db: Database
) -> None:
    _paid(world)
    episode = world.episode()
    # No lease rows: every component of a zero-amount bucket derives a zero-delta
    # RECOVERY row. Nothing may be posted and nothing may block a later reservation.
    query, bucket = closed_bucket(pod_id="pod-zero", start=T0, end=T0 + HOUR, gpu=0, cpu=0, disk=0)
    BillingRepository(db, budget_service=world.service).ingest(query, [bucket])
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM runpod_billing_budget_postings") == 0
        assert tx.fetchval("SELECT count(*) FROM charges") == 0
    # A later Runpod reservation is not blocked: run it under the offline settings
    # (a synthetic quote is only admissible there) on a fresh service instance.
    from microdrama.budget import BudgetService
    from microdrama.config import Settings as _Settings
    from microdrama.testing.fakes import FakeClock, SequentialIds

    offline = BudgetService(
        db,
        FakeClock(BT0),
        SequentialIds("t045-zero"),
        _Settings(execution_mode=ExecutionMode.OFFLINE_MOCK),
    )
    request = request_for(
        key="t045-zero-delta-not-blocking",
        episode_id=episode.episode_id,
        provider="runpod",
        category=GPU,
    )
    assert offline.reserve(request).reserved_micro_usd > 0

    # A later revision that changes nothing posts nothing either.
    revision_query, revision_bucket = closed_bucket(
        pod_id="pod-zero",
        start=T0,
        end=T0 + HOUR,
        gpu=0,
        cpu=0,
        disk=0,
        revision=2,
        prior_observation_id=bucket.observation_id,
        prior_raw=bucket.raw_response_sha256,
    )
    BillingRepository(db, budget_service=world.service).ingest(revision_query, [revision_bucket])
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM runpod_billing_budget_postings") == 0


def test_positive_recovery_still_blocks_until_resolved(world: World, db: Database) -> None:
    _paid(world)
    episode = world.episode()
    del episode
    query, bucket = closed_bucket(
        pod_id="pod-blocked", start=T0, end=T0 + HOUR, gpu=500_000, cpu=0, disk=0
    )
    BillingRepository(db, budget_service=world.service).ingest(query, [bucket])
    with db.transaction(readonly=True) as tx:
        pending = tx.fetchall(
            "SELECT delta_micro_usd FROM runpod_billing_budget_postings "
            "WHERE posting_state='RECOVERY_PENDING'"
        )
    assert [row["delta_micro_usd"] for row in pending] == [500_000]


def test_a_gpu_billing_post_does_not_lock_the_lease_rows(
    db_dsn: str, world: World, db: Database
) -> None:
    """T045-FIX A-N7: the lease-window lookup locks only the reservation row it posts
    against (FOR UPDATE OF r) - never the joined pod_leases rows - so a lease
    lifecycle write such as a heartbeat is not blocked by an in-flight billing post."""
    import psycopg

    from microdrama.budget import BudgetService
    from microdrama.testing.fakes import FakeClock, SequentialIds

    _paid(world)
    episode = world.episode()
    with db.transaction() as tx:
        lease, _reservation = insert_runpod_lease(
            tx,
            episode.episode_id,
            pod_id="pod-n7",
            lease_state="ACTIVE",
            create_requested_at=T0,
            compute_window_start_at=T0,
            compute_window_end_at=T0 + HOUR,
        )
    probe: dict[str, bool | None] = {"blocked": None}

    class HeartbeatProbingService(BudgetService):
        def _post_charge(self, tx, ledger, receipt, reservation, **kwargs):
            if str(receipt.provider_receipt_id).startswith("billing-allocation:"):
                try:
                    with psycopg.connect(db_dsn) as conn:
                        conn.execute("SET lock_timeout = '500ms'")
                        conn.execute(
                            "UPDATE pod_leases SET heartbeat_at = %s WHERE id = %s",
                            (T0 + timedelta(seconds=1), lease),
                        )
                        conn.commit()
                    probe["blocked"] = False
                except psycopg.errors.LockNotAvailable:
                    probe["blocked"] = True
            return super()._post_charge(tx, ledger, receipt, reservation, **kwargs)

    settings = Settings(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
    )
    service = HeartbeatProbingService(db, FakeClock(BT0), SequentialIds("t045-n7"), settings)
    query, bucket = closed_bucket(
        pod_id="pod-n7", start=T0, end=T0 + timedelta(minutes=5), gpu=600_000, cpu=0, disk=0
    )
    BillingRepository(db, budget_service=service).ingest(query, [bucket])
    assert probe["blocked"] is False
