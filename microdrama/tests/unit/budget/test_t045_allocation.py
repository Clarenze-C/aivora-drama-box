"""T045 R1 (G1): Runpod allocation basis is lease-window existence, never bucket length.

Red-first on real PostgreSQL: a 90-minute lease in two hourly buckets previously sent
the unused half hour to the recovery pool (the denominator was the bucket length).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from t045_support import T0, closed_bucket, insert_runpod_lease, open_episode_account

from microdrama.budget.billing import BillingRepository
from microdrama.persistence import Database

pytestmark = pytest.mark.db

HOUR = timedelta(hours=1)


def _allocations_by_owner(db: Database, observation_ids: list[uuid.UUID]) -> dict:
    with db.transaction(readonly=True) as tx:
        rows = tx.fetchall(
            "SELECT a.owner_kind, a.owner_id, a.component, a.delta_micro_usd "
            "FROM runpod_billing_allocations a WHERE a.bucket_observation_id = ANY(%s)",
            (observation_ids,),
        )
    return {(r["owner_kind"], r["owner_id"], r["component"]): r["delta_micro_usd"] for r in rows}


def test_ninety_minute_single_lease_fills_two_buckets_with_no_recovery(db: Database) -> None:
    with db.transaction() as tx:
        _, episode, _ = open_episode_account(tx)
        end = T0 + timedelta(minutes=90)
        lease, _reservation = insert_runpod_lease(
            tx,
            episode,
            pod_id="pod-90min",
            lease_state="RELEASED",
            pod_state="TERMINATED",
            create_requested_at=T0,
            compute_window_start_at=T0,
            compute_window_end_at=end,
            stop_verified_at=end,
            terminate_verified_at=end,
        )
    first = closed_bucket(pod_id="pod-90min", start=T0, end=T0 + HOUR, gpu=600_000, cpu=0, disk=0)
    second = closed_bucket(
        pod_id="pod-90min",
        start=T0 + HOUR,
        end=T0 + 2 * HOUR,
        gpu=600_000,
        cpu=0,
        disk=0,
    )
    repository = BillingRepository(db)
    repository.ingest(first[0], [first[1]])
    repository.ingest(second[0], [second[1]])

    for _query, bucket in (first, second):
        shares = _allocations_by_owner(db, [bucket.observation_id])
        episode_gpu = shares.get(("EPISODE", str(episode), "GPU"))
        assert episode_gpu == 600_000
        recovery_gpu = [
            amount
            for (kind, _, component), amount in shares.items()
            if kind == "RECOVERY" and component == "GPU"
        ]
        assert recovery_gpu in ([], [0])
    # The second bucket held only 30 minutes of existence; still 100% to the episode.


def test_two_warm_leases_in_one_bucket_split_between_episodes(db: Database) -> None:
    with db.transaction() as tx:
        _, episode_a, _ = open_episode_account(tx)
        _, episode_b, _ = open_episode_account(tx, number=2)
        root, _ = insert_runpod_lease(
            tx,
            episode_a,
            pod_id="pod-warm",
            lease_state="RELEASED",
            create_requested_at=T0,
            compute_window_start_at=T0,
            compute_window_end_at=T0 + timedelta(minutes=30),
        )
        insert_runpod_lease(
            tx,
            episode_b,
            pod_id="pod-warm",
            lease_state="RELEASED",
            compute_window_start_at=T0 + timedelta(minutes=30),
            compute_window_end_at=T0 + HOUR,
            transferred_from=root,
        )
    query, bucket = closed_bucket(
        pod_id="pod-warm", start=T0, end=T0 + HOUR, gpu=600_000, cpu=0, disk=0
    )
    BillingRepository(db).ingest(query, [bucket])
    shares = _allocations_by_owner(db, [bucket.observation_id])
    assert shares[("EPISODE", str(episode_a), "GPU")] == 300_000
    assert shares[("EPISODE", str(episode_b), "GPU")] == 300_000
    assert not [
        amount
        for (kind, _, component), amount in shares.items()
        if kind == "RECOVERY" and component == "GPU" and amount
    ]


def test_uncovered_existence_goes_to_the_root_lease_episode(db: Database) -> None:
    with db.transaction() as tx:
        _, episode_a, _ = open_episode_account(tx)
        _, episode_b, _ = open_episode_account(tx, number=2)
        root, _ = insert_runpod_lease(
            tx,
            episode_a,
            pod_id="pod-gap",
            lease_state="RELEASED",
            create_requested_at=T0,
            compute_window_start_at=T0,
            compute_window_end_at=T0 + timedelta(minutes=20),
        )
        # A receiver whose window starts late leaves 20 minutes of covered existence
        # attached to no lease: that time belongs to the root lease's episode.
        insert_runpod_lease(
            tx,
            episode_b,
            pod_id="pod-gap",
            lease_state="RELEASED",
            compute_window_start_at=T0 + timedelta(minutes=40),
            compute_window_end_at=T0 + HOUR,
            transferred_from=root,
        )
    query, bucket = closed_bucket(
        pod_id="pod-gap", start=T0, end=T0 + HOUR, gpu=600_000, cpu=0, disk=0
    )
    BillingRepository(db).ingest(query, [bucket])
    shares = _allocations_by_owner(db, [bucket.observation_id])
    assert shares[("EPISODE", str(episode_a), "GPU")] == 400_000
    assert shares[("EPISODE", str(episode_b), "GPU")] == 200_000
    assert not [
        amount
        for (kind, _, component), amount in shares.items()
        if kind == "RECOVERY" and component == "GPU" and amount
    ]


def test_pod_with_no_root_lease_sends_uncovered_existence_to_recovery(db: Database) -> None:
    with db.transaction() as tx:
        _, other_episode, _ = open_episode_account(tx)
        _, episode, _ = open_episode_account(tx, number=2)
        # The root lives on another pod; this pod's leases are receivers whose windows
        # leave twenty uncovered minutes.
        root_elsewhere, _ = insert_runpod_lease(
            tx,
            other_episode,
            pod_id="pod-elsewhere",
            lease_state="RELEASED",
            create_requested_at=T0,
            compute_window_start_at=T0,
            compute_window_end_at=T0 + HOUR,
        )
        insert_runpod_lease(
            tx,
            episode,
            pod_id="pod-no-root",
            lease_state="RELEASED",
            create_requested_at=T0,
            compute_window_start_at=T0,
            compute_window_end_at=T0 + timedelta(minutes=20),
            transferred_from=root_elsewhere,
        )
        insert_runpod_lease(
            tx,
            episode,
            pod_id="pod-no-root",
            client_token="tok-no-root-second",
            lease_state="RELEASED",
            create_requested_at=T0 + timedelta(minutes=40),
            compute_window_start_at=T0 + timedelta(minutes=40),
            compute_window_end_at=T0 + HOUR,
            transferred_from=root_elsewhere,
        )
    query, bucket = closed_bucket(
        pod_id="pod-no-root", start=T0, end=T0 + HOUR, gpu=600_000, cpu=0, disk=0
    )
    BillingRepository(db).ingest(query, [bucket])
    shares = _allocations_by_owner(db, [bucket.observation_id])
    assert shares[("EPISODE", str(episode), "GPU")] == 400_000
    assert shares[("RECOVERY", "recovery_pool", "GPU")] == 200_000


def test_nonzero_bucket_without_recorded_existence_is_all_recovery(db: Database) -> None:
    with db.transaction() as tx:
        open_episode_account(tx)
    query, bucket = closed_bucket(
        pod_id="pod-unknown", start=T0, end=T0 + HOUR, gpu=600_000, cpu=0, disk=0
    )
    BillingRepository(db).ingest(query, [bucket])
    shares = _allocations_by_owner(db, [bucket.observation_id])
    assert shares[("RECOVERY", "recovery_pool", "GPU")] == 600_000
    assert not [key for key in shares if key[0] == "EPISODE"]


def test_failed_attempt_stays_charged_to_its_episode(db: Database) -> None:
    with db.transaction() as tx:
        _, episode, _ = open_episode_account(tx)
        # An ambiguous create that the janitor attached, then closed without compute: the
        # provider still billed the pod's first minutes, and the episode keeps paying.
        insert_runpod_lease(
            tx,
            episode,
            pod_id="pod-failed",
            lease_state="RELEASED",
            pod_state="TERMINATED",
            create_requested_at=T0,
            compute_window_start_at=T0,
            compute_window_end_at=T0 + timedelta(minutes=10),
        )
    query, bucket = closed_bucket(
        pod_id="pod-failed", start=T0, end=T0 + HOUR, gpu=600_000, cpu=0, disk=0
    )
    BillingRepository(db).ingest(query, [bucket])
    shares = _allocations_by_owner(db, [bucket.observation_id])
    assert shares[("EPISODE", str(episode), "GPU")] == 600_000
    assert not [
        amount
        for (kind, _, component), amount in shares.items()
        if kind == "RECOVERY" and component == "GPU" and amount
    ]


def test_disk_splits_by_storage_ownership_and_missing_owner_is_recovery(db: Database) -> None:
    with db.transaction() as tx:
        _, episode_a, _ = open_episode_account(tx)
        _, episode_b, _ = open_episode_account(tx, number=2)
        root, _ = insert_runpod_lease(
            tx,
            episode_a,
            pod_id="pod-disk",
            lease_state="RELEASED",
            create_requested_at=T0,
            compute_window_start_at=T0,
            compute_window_end_at=T0 + HOUR,
            stop_verified_at=T0 + HOUR,
            terminate_verified_at=T0 + HOUR,
        )
        from t045_support import insert_storage_ownership

        insert_storage_ownership(
            tx,
            episode_a,
            pod_id="pod-disk",
            valid_from=T0,
            valid_until=T0 + timedelta(minutes=40),
            creating_lease=root,
        )
        insert_storage_ownership(
            tx, episode_b, pod_id="pod-disk", valid_from=T0 + timedelta(minutes=40)
        )
    query, bucket = closed_bucket(
        pod_id="pod-disk", start=T0, end=T0 + HOUR, gpu=0, cpu=0, disk=300_000
    )
    BillingRepository(db).ingest(query, [bucket])
    shares = _allocations_by_owner(db, [bucket.observation_id])
    assert shares[("EPISODE", str(episode_a), "DISK")] == 200_000
    assert shares[("EPISODE", str(episode_b), "DISK")] == 100_000
    assert not [key for key in shares if key[0] == "RECOVERY"]

    # The same pod with no ownership rows at all: disk goes to the recovery pool.
    query2, bucket2 = closed_bucket(
        pod_id="pod-disk-orphan",
        start=T0,
        end=T0 + HOUR,
        gpu=0,
        cpu=0,
        disk=300_000,
    )
    with db.transaction() as tx:
        insert_runpod_lease(
            tx,
            episode_a,
            pod_id="pod-disk-orphan",
            lease_state="RELEASED",
            create_requested_at=T0,
            compute_window_start_at=T0,
            compute_window_end_at=T0 + HOUR,
        )
    BillingRepository(db).ingest(query2, [bucket2])
    shares2 = _allocations_by_owner(db, [bucket2.observation_id])
    assert shares2[("RECOVERY", "recovery_pool", "DISK")] == 300_000
    assert not [key for key in shares2 if key[0] == "EPISODE" and key[2] == "DISK"]


def test_post_stop_disk_charges_the_owner_up_to_the_verified_terminate(db: Database) -> None:
    """T045 R3: storage billing continues past the verified stop, to the verified terminate."""
    with db.transaction() as tx:
        from t045_support import insert_storage_ownership

        _, episode, _ = open_episode_account(tx)
        stopped = T0 + timedelta(minutes=40)
        terminated = T0 + timedelta(minutes=50)
        lease, _ = insert_runpod_lease(
            tx,
            episode,
            pod_id="pod-poststop",
            lease_state="RELEASED",
            pod_state="TERMINATED",
            create_requested_at=T0,
            compute_window_start_at=T0,
            compute_window_end_at=terminated,
            stop_verified_at=stopped,
            terminate_verified_at=terminated,
        )
        insert_storage_ownership(
            tx,
            episode,
            pod_id="pod-poststop",
            valid_from=T0,
            valid_until=terminated,
            creating_lease=lease,
        )
    query, bucket = closed_bucket(
        pod_id="pod-poststop", start=T0, end=T0 + HOUR, gpu=0, cpu=0, disk=300_000
    )
    BillingRepository(db).ingest(query, [bucket])
    shares = _allocations_by_owner(db, [bucket.observation_id])
    assert shares[("EPISODE", str(episode), "DISK")] == 300_000
    assert not [
        amount
        for (kind, _, component), amount in shares.items()
        if kind == "RECOVERY" and component == "DISK" and amount
    ]
