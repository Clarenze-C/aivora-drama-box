"""T045 R7: lease billing finality — readiness states and the BILLED settlement.

Red-first: there was no lease-level BILLED, no BILLED receipt and no release of the
unused hold; `accounting_readiness` (removed) summed only wholly-inside buckets and
nothing called it.
"""

from __future__ import annotations

from datetime import timedelta
from hashlib import sha256

import pytest
from budget_support import World
from t045_support import ACCOUNT_REF, T0, closed_bucket, insert_runpod_lease

from microdrama.budget.billing import lease_billing_readiness, settle_billed_lease
from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode
from microdrama.persistence import Database

pytestmark = pytest.mark.db

HOUR = timedelta(hours=1)


def _reservation_row(db: Database, reservation_id):
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone("SELECT * FROM reservations WHERE id=%s", (reservation_id,))
    assert row is not None
    return row


def _paid(world: World):
    world.service._settings = Settings(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
    )


def _evidence(label: str) -> str:
    return sha256(f"t045-finality:{label}".encode()).hexdigest()


def _seed_straddling(world: World, db: Database, *, reservation_micro_usd: int = 900_000):
    """A 90-minute runpod lease whose hour buckets straddle two periods."""
    episode = world.episode()
    end = T0 + timedelta(minutes=90)
    with db.transaction() as tx:
        lease, reservation = insert_runpod_lease(
            tx,
            episode.episode_id,
            pod_id="pod-final",
            lease_state="RELEASED",
            pod_state="TERMINATED",
            create_requested_at=T0,
            compute_window_start_at=T0,
            compute_window_end_at=end,
            stop_verified_at=end,
            terminate_verified_at=end,
            reservation_micro_usd=reservation_micro_usd,
        )
    return episode, lease, reservation


def _buckets_and_verify(world: World, db: Database, repository):
    """Two hour buckets ingested under one covering query, then matched over [T0, 2h)."""
    from uuid import uuid4 as _uuid4

    aged = T0 + 2 * HOUR + timedelta(hours=1)
    first = closed_bucket(pod_id="pod-final", start=T0, end=T0 + HOUR, gpu=600_000, cpu=0, disk=0)
    second = closed_bucket(
        pod_id="pod-final",
        start=T0 + HOUR,
        end=T0 + 2 * HOUR,
        gpu=300_000,
        cpu=0,
        disk=0,
        observed_at=aged,
    )
    shared = _uuid4()
    query = type(first[0]).model_validate(
        first[0].model_dump(mode="python")
        | {
            "query_id": shared,
            "requested_window_start": T0,
            "requested_window_end": T0 + 2 * HOUR,
            "provider_resolved_window_start": T0,
            "provider_resolved_window_end": T0 + 2 * HOUR,
            "observed_at": aged,
            "bucket_observation_ids": [first[1].observation_id, second[1].observation_id],
        }
    )
    first_bucket = type(first[1]).model_validate(
        first[1].model_dump(mode="python")
        | {
            "query_id": shared,
            "provider_resolved_window_start": T0,
            "provider_resolved_window_end": T0 + 2 * HOUR,
            "observed_at": aged,
        }
    )
    second_bucket = type(second[1]).model_validate(
        second[1].model_dump(mode="python")
        | {
            "query_id": shared,
            "provider_resolved_window_start": T0,
            "provider_resolved_window_end": T0 + 2 * HOUR,
        }
    )
    repository.ingest(query, [first_bucket, second_bucket])
    result = repository.verify_invoice_period(
        provider_account_ref=ACCOUNT_REF,
        pod_id="pod-final",
        period_start=T0,
        period_end=T0 + 2 * HOUR,
        amount_micro_usd=900_000,
        currency="USD",
        evidence_sha256=_evidence("straddle"),
        source="INVOICE",
        observed_at=aged,
    )
    assert result.outcome == "MATCHED"
    return (query, first_bucket), (query, second_bucket)


def test_straddling_buckets_reach_billed_and_settle_the_exact_remainder(
    world: World, db: Database
) -> None:
    _paid(world)
    from microdrama.budget.billing import BillingRepository

    episode, lease, reservation = _seed_straddling(world, db)
    repository = BillingRepository(db, budget_service=world.service)
    _buckets_and_verify(world, db, repository)

    readiness = lease_billing_readiness(db, lease)
    assert readiness.state == "BILLED"
    settled = settle_billed_lease(db, world.service, lease_id=lease, context="t045 finality")
    assert settled == 900_000  # the amount equals the GPU postings on R

    reservation_row = _reservation_row(db, reservation)
    assert reservation_row["state"] == "SETTLED"
    assert reservation_row["settled_micro_usd"] == 900_000
    counters = world.counters(episode.account_id)
    assert counters["settled"] == 900_000
    # The exact remainder (900k hold - 900k posted) is released: nothing stays reserved.
    assert counters["reserved"] == 0

    with db.transaction(readonly=True) as tx:
        settlement = tx.fetchone(
            "SELECT amount_micro_usd, cost_basis, kind FROM charges "
            "WHERE kind='SETTLEMENT' AND reservation_id=%s",
            (reservation,),
        )
    assert settlement["amount_micro_usd"] == 900_000
    assert settlement["cost_basis"] == "BILLED"


def test_readiness_pending_then_awaiting_invoice_then_billed(world: World, db: Database) -> None:
    _paid(world)
    from microdrama.budget.billing import BillingRepository

    episode, lease, _reservation = _seed_straddling(world, db)
    del episode
    repository = BillingRepository(db, budget_service=world.service)
    # Before any query: the window's buckets are unqueried.
    assert lease_billing_readiness(db, lease).state == "PENDING_PROVIDER_FINALITY"
    first = closed_bucket(pod_id="pod-final", start=T0, end=T0 + HOUR, gpu=600_000, cpu=0, disk=0)
    second = closed_bucket(
        pod_id="pod-final",
        start=T0 + HOUR,
        end=T0 + 2 * HOUR,
        gpu=300_000,
        cpu=0,
        disk=0,
        observed_at=T0 + 2 * HOUR + timedelta(hours=1),
    )
    from uuid import uuid4 as _uuid4

    aged = T0 + 2 * HOUR + timedelta(hours=1)
    shared = _uuid4()
    query = type(first[0]).model_validate(
        first[0].model_dump(mode="python")
        | {
            "query_id": shared,
            "requested_window_start": T0,
            "requested_window_end": T0 + 2 * HOUR,
            "provider_resolved_window_start": T0,
            "provider_resolved_window_end": T0 + 2 * HOUR,
            "observed_at": aged,
            "bucket_observation_ids": [first[1].observation_id, second[1].observation_id],
        }
    )
    first_bucket = type(first[1]).model_validate(
        first[1].model_dump(mode="python")
        | {
            "query_id": shared,
            "provider_resolved_window_start": T0,
            "provider_resolved_window_end": T0 + 2 * HOUR,
            "observed_at": aged,
        }
    )
    second_bucket = type(second[1]).model_validate(
        second[1].model_dump(mode="python")
        | {
            "query_id": shared,
            "provider_resolved_window_start": T0,
            "provider_resolved_window_end": T0 + 2 * HOUR,
        }
    )
    repository.ingest(query, [first_bucket, second_bucket])
    # Queried (after the lag) but not yet invoice-verified.
    pending = lease_billing_readiness(db, lease)
    assert pending.state == "AWAITING_INVOICE"
    assert pending.pending_since is not None
    repository.verify_invoice_period(
        provider_account_ref=ACCOUNT_REF,
        pod_id="pod-final",
        period_start=T0,
        period_end=T0 + 2 * HOUR,
        amount_micro_usd=900_000,
        currency="USD",
        evidence_sha256=_evidence("awaiting"),
        source="INVOICE",
        observed_at=T0 + 2 * HOUR + timedelta(hours=1),
    )
    assert lease_billing_readiness(db, lease).state == "BILLED"


def test_an_expired_hold_reaches_billed(world: World, db: Database) -> None:
    _paid(world)
    from microdrama.budget.billing import BillingRepository

    episode, lease, reservation = _seed_straddling(world, db, reservation_micro_usd=900_000)
    repository = BillingRepository(db, budget_service=world.service)
    _buckets_and_verify(world, db, repository)
    # The hold expired while it waited for the invoice.
    world.clock.advance(seconds=int((T0 - world.clock.now()).total_seconds()) + 7 * 3600)
    assert world.service.expire_stale() == 1
    assert _reservation_row(db, reservation)["state"] == "EXPIRED"
    settled = settle_billed_lease(db, world.service, lease_id=lease, context="expired hold")
    assert settled == 900_000
    row = _reservation_row(db, reservation)
    assert row["state"] == "SETTLED"
    assert row["closed_reason"] == "settled after expiry"
    assert world.counters(episode.account_id)["settled"] == 900_000


def test_a_transferred_away_lease_reaches_billed(world: World, db: Database) -> None:
    _paid(world)
    from microdrama.budget.billing import BillingRepository

    episode_a = world.episode()
    episode_b = world.episode(number=2)
    transfer_instant = T0 + timedelta(minutes=30)
    with db.transaction() as tx:
        root, root_reservation = insert_runpod_lease(
            tx,
            episode_a.episode_id,
            pod_id="pod-transfer-final",
            client_token="tok-tf-root",
            lease_state="RELEASED",
            create_requested_at=T0,
            compute_window_start_at=T0,
            compute_window_end_at=transfer_instant,
        )
        insert_runpod_lease(
            tx,
            episode_b.episode_id,
            pod_id="pod-transfer-final",
            client_token="tok-tf-recv",
            lease_state="RELEASED",
            create_requested_at=transfer_instant,
            compute_window_start_at=transfer_instant,
            compute_window_end_at=T0 + HOUR,
            transferred_from=root,
        )
    repository = BillingRepository(db, budget_service=world.service)
    query, bucket = closed_bucket(
        pod_id="pod-transfer-final", start=T0, end=T0 + HOUR, gpu=600_000, cpu=0, disk=0
    )
    repository.ingest(query, [bucket])
    repository.verify_invoice_period(
        provider_account_ref=ACCOUNT_REF,
        pod_id="pod-transfer-final",
        period_start=T0,
        period_end=T0 + HOUR,
        amount_micro_usd=600_000,
        currency="USD",
        evidence_sha256=_evidence("transfer"),
        source="INVOICE",
        observed_at=T0 + 2 * HOUR,
    )
    assert lease_billing_readiness(db, root).state == "BILLED"
    settled = settle_billed_lease(db, world.service, lease_id=root, context="transferred away")
    assert settled == 300_000  # only the root's half hour of GPU postings
    assert _reservation_row(db, root_reservation)["state"] == "SETTLED"


def test_settlement_replay_adds_no_money(world: World, db: Database) -> None:
    _paid(world)
    from microdrama.budget.billing import BillingRepository

    episode, lease, reservation = _seed_straddling(world, db)
    repository = BillingRepository(db, budget_service=world.service)
    _buckets_and_verify(world, db, repository)
    first = settle_billed_lease(db, world.service, lease_id=lease, context="first")
    second = settle_billed_lease(db, world.service, lease_id=lease, context="replay")
    assert second == first == 900_000
    counters = world.counters(episode.account_id)
    assert counters["settled"] == 900_000
    with db.transaction(readonly=True) as tx:
        assert (
            tx.fetchval(
                "SELECT count(*) FROM charges WHERE kind='SETTLEMENT' AND reservation_id=%s",
                (reservation,),
            )
            == 1
        )


def test_post_billed_revision_posts_an_adjustment_and_reopens(world: World, db: Database) -> None:
    _paid(world)
    from microdrama.budget.billing import BillingRepository

    episode, lease, reservation = _seed_straddling(world, db)
    repository = BillingRepository(db, budget_service=world.service)
    first, second = _buckets_and_verify(world, db, repository)
    settle_billed_lease(db, world.service, lease_id=lease, context="billed")

    # The provider revises the second bucket upward after the settlement. The latest
    # stored revision is the internal verified one; the provider's revision links it.
    with db.transaction(readonly=True) as tx:
        latest = tx.fetchone(
            "SELECT payload FROM runpod_billing_buckets "
            "WHERE bucket_identity_sha256=%s ORDER BY revision DESC LIMIT 1",
            (second[1].bucket_identity_sha256,),
        )
    latest_model = type(second[1]).model_validate(latest["payload"])
    revision_payload = latest_model.model_dump(mode="python")
    from uuid import uuid4 as _uuid4

    revision_query_id = _uuid4()
    revision_payload.update(
        observation_id=_uuid4(),
        query_id=revision_query_id,
        revision=latest_model.revision + 1,
        prior_observation_id=latest_model.observation_id,
        prior_raw_response_sha256=latest_model.raw_response_sha256,
        total_amount_micro_usd=400_000,
        gpu_amount_micro_usd=400_000,
        observed_at=latest_model.observed_at + timedelta(hours=1),
        finality_state="ALLOCATED_PROVIDER_REPORTED",
        invoice_verification_id=None,
    )
    revision = type(second[1]).model_validate(revision_payload)
    from uuid import uuid4 as _uuid4

    revision_query = type(second[0]).model_validate(
        second[0].model_dump(mode="python")
        | {
            "query_id": revision_query_id,
            "raw_response_sha256": sha256(b"t045-finality-revision").hexdigest(),
            "bucket_observation_ids": [revision.observation_id],
            "requested_window_start": T0,
            "requested_window_end": T0 + 2 * HOUR,
            "provider_resolved_window_start": T0,
            "provider_resolved_window_end": T0 + 2 * HOUR,
        }
    )
    revision = revision.model_copy(
        update={"raw_response_sha256": revision_query.raw_response_sha256}
    )
    repository.ingest(revision_query, [revision])

    readiness = lease_billing_readiness(db, lease)
    assert readiness.state == "BILLED"
    assert readiness.reopened is True
    counters = world.counters(episode.account_id)
    assert counters["settled"] == 1_000_000  # the positive delta added to settled
    with db.transaction(readonly=True) as tx:
        adjustments = tx.fetchval(
            "SELECT count(*) FROM charges WHERE kind='ADJUSTMENT' AND reservation_id=%s",
            (reservation,),
        )
    assert adjustments >= 1


def test_overstatement_after_a_downward_revision_is_stored_as_evidence(
    world: World, db: Database
) -> None:
    _paid(world)
    from microdrama.budget.billing import BillingRepository

    episode, lease, _reservation = _seed_straddling(world, db)
    del episode
    repository = BillingRepository(db, budget_service=world.service)
    first, second = _buckets_and_verify(world, db, repository)
    # A downward provider revision arrives before settlement: negative delta is
    # evidence only, the posted spend stays higher than the invoice sum.
    with db.transaction(readonly=True) as tx:
        latest = tx.fetchone(
            "SELECT payload FROM runpod_billing_buckets "
            "WHERE bucket_identity_sha256=%s ORDER BY revision DESC LIMIT 1",
            (second[1].bucket_identity_sha256,),
        )
    latest_model = type(second[1]).model_validate(latest["payload"])
    revision_payload = latest_model.model_dump(mode="python")
    from uuid import uuid4 as _uuid4

    revision_query_id = _uuid4()
    revision_payload.update(
        observation_id=_uuid4(),
        query_id=revision_query_id,
        revision=latest_model.revision + 1,
        prior_observation_id=latest_model.observation_id,
        prior_raw_response_sha256=latest_model.raw_response_sha256,
        total_amount_micro_usd=200_000,
        gpu_amount_micro_usd=200_000,
        observed_at=latest_model.observed_at + timedelta(hours=1),
        finality_state="ALLOCATED_PROVIDER_REPORTED",
        invoice_verification_id=None,
    )
    revision = type(second[1]).model_validate(revision_payload)
    from uuid import uuid4 as _uuid4

    revision_query = type(second[0]).model_validate(
        second[0].model_dump(mode="python")
        | {
            "query_id": revision_query_id,
            "raw_response_sha256": sha256(b"t045-finality-downward").hexdigest(),
            "bucket_observation_ids": [revision.observation_id],
            "requested_window_start": T0,
            "requested_window_end": T0 + 2 * HOUR,
            "provider_resolved_window_start": T0,
            "provider_resolved_window_end": T0 + 2 * HOUR,
        }
    )
    revision = revision.model_copy(
        update={"raw_response_sha256": revision_query.raw_response_sha256}
    )
    repository.ingest(revision_query, [revision])
    # The later invoice matches the latest (lower) sum while posted spend is higher.
    with db.transaction(readonly=True) as tx:
        first_evidence_id = tx.fetchval(
            "SELECT period_evidence_id FROM runpod_billing_period_evidence "
            "WHERE evidence_sha256=%s",
            (_evidence("straddle"),),
        )
    matched = repository.verify_invoice_period(
        provider_account_ref=ACCOUNT_REF,
        pod_id="pod-final",
        period_start=T0,
        period_end=T0 + 2 * HOUR,
        amount_micro_usd=800_000,
        currency="USD",
        evidence_sha256=_evidence("downward-match"),
        source="INVOICE",
        observed_at=T0 + 3 * HOUR,
        supersedes_evidence_id=first_evidence_id,
        actor_ref="owner:test",
        reason="corrected invoice after the provider revision",
    )
    assert matched.outcome == "MATCHED"
    settled = settle_billed_lease(db, world.service, lease_id=lease, context="overstatement")
    assert settled == 900_000  # posted sum, not the lower invoice
    with db.transaction(readonly=True) as tx:
        events = tx.fetchall(
            "SELECT payload FROM domain_events WHERE event_type='billing.overstatement_recorded'"
        )
    assert len(events) == 1
    assert events[0]["payload"]["posted_micro_usd"] == 900_000
    assert events[0]["payload"]["invoice_micro_usd"] == 800_000


def test_overstatement_evidence_is_pod_level_across_leases_and_periods(
    world: World, db: Database
) -> None:
    """T045-FIX A-S5: the overstatement evidence compares the Pod's total posted GPU
    (all leases of the Pod, a warm transfer splits the bill) with the SUM of the
    distinct matched periods - never one lease's posting against the single largest
    period. Evidence only: both leases still settle exactly what they posted."""
    _paid(world)
    from uuid import uuid4 as _uuid4

    from microdrama.budget.billing import BillingRepository

    episode_a = world.episode()
    episode_b = world.episode(number=2)
    transfer_instant = T0 + timedelta(minutes=30)
    with db.transaction() as tx:
        root, _root_reservation = insert_runpod_lease(
            tx,
            episode_a.episode_id,
            pod_id="pod-s5-final",
            client_token="tok-s5-root",
            lease_state="RELEASED",
            pod_state="TERMINATED",
            create_requested_at=T0,
            compute_window_start_at=T0,
            compute_window_end_at=transfer_instant,
        )
        receiver, _recv_reservation = insert_runpod_lease(
            tx,
            episode_b.episode_id,
            pod_id="pod-s5-final",
            client_token="tok-s5-recv",
            lease_state="RELEASED",
            pod_state="TERMINATED",
            create_requested_at=transfer_instant,
            compute_window_start_at=transfer_instant,
            compute_window_end_at=T0 + 2 * HOUR,
            transferred_from=root,
        )
    repository = BillingRepository(db, budget_service=world.service)
    aged = T0 + 2 * HOUR + timedelta(hours=1)
    # Period 1 [T0, 1h) holds the warm transfer; period 2 [1h, 2h) is the receiver's.
    # One covering query per period: a bucket must sit wholly inside its period.
    first_query, first_bucket = closed_bucket(
        pod_id="pod-s5-final", start=T0, end=T0 + HOUR, gpu=600_000, cpu=0, disk=0
    )
    second_query, second_bucket = closed_bucket(
        pod_id="pod-s5-final",
        start=T0 + HOUR,
        end=T0 + 2 * HOUR,
        gpu=500_000,
        cpu=0,
        disk=0,
        observed_at=aged,
    )
    repository.ingest(first_query, [first_bucket])
    repository.ingest(second_query, [second_bucket])
    matched_one = repository.verify_invoice_period(
        provider_account_ref=ACCOUNT_REF,
        pod_id="pod-s5-final",
        period_start=T0,
        period_end=T0 + HOUR,
        amount_micro_usd=600_000,
        currency="USD",
        evidence_sha256=_evidence("s5-period-1"),
        source="INVOICE",
        observed_at=aged,
    )
    assert matched_one.outcome == "MATCHED"
    # A downward provider revision lands for period 2 before its invoice: the posted
    # spend stays at the pre-revision sum, the later invoice matches the lower one.
    with db.transaction(readonly=True) as tx:
        latest = tx.fetchone(
            "SELECT payload FROM runpod_billing_buckets "
            "WHERE bucket_identity_sha256=%s ORDER BY revision DESC LIMIT 1",
            (second_bucket.bucket_identity_sha256,),
        )
    latest_model = type(second_bucket).model_validate(latest["payload"])
    revision_payload = latest_model.model_dump(mode="python")
    revision_payload.update(
        observation_id=_uuid4(),
        query_id=_uuid4(),
        revision=latest_model.revision + 1,
        prior_observation_id=latest_model.observation_id,
        prior_raw_response_sha256=latest_model.raw_response_sha256,
        total_amount_micro_usd=400_000,
        gpu_amount_micro_usd=400_000,
        observed_at=latest_model.observed_at + timedelta(hours=1),
        finality_state="ALLOCATED_PROVIDER_REPORTED",
        invoice_verification_id=None,
    )
    revision = type(second_bucket).model_validate(revision_payload)
    revision_query = type(second_query).model_validate(
        second_query.model_dump(mode="python")
        | {
            "query_id": revision.query_id,
            "raw_response_sha256": sha256(b"t045-s5-downward").hexdigest(),
            "bucket_observation_ids": [revision.observation_id],
        }
    )
    revision = revision.model_copy(
        update={"raw_response_sha256": revision_query.raw_response_sha256}
    )
    repository.ingest(revision_query, [revision])
    matched_two = repository.verify_invoice_period(
        provider_account_ref=ACCOUNT_REF,
        pod_id="pod-s5-final",
        period_start=T0 + HOUR,
        period_end=T0 + 2 * HOUR,
        amount_micro_usd=400_000,
        currency="USD",
        evidence_sha256=_evidence("s5-period-2"),
        source="INVOICE",
        observed_at=T0 + 3 * HOUR,
    )
    assert matched_two.outcome == "MATCHED"
    # Posted across the Pod: root 300_000 + receiver 800_000 = 1_100_000 against an
    # invoice sum of 1_000_000 (600_000 + 400_000) - the Pod-level overstatement.
    settled_root = settle_billed_lease(db, world.service, lease_id=root, context="s5 root")
    settled_receiver = settle_billed_lease(
        db, world.service, lease_id=receiver, context="s5 receiver"
    )
    assert (settled_root, settled_receiver) == (300_000, 800_000)
    with db.transaction(readonly=True) as tx:
        events = tx.fetchall(
            "SELECT payload FROM domain_events WHERE event_type='billing.overstatement_recorded'"
        )
    assert events, "the pod-level overstatement must be recorded"
    assert {
        (
            event["payload"]["posted_micro_usd"],
            event["payload"]["invoice_micro_usd"],
            event["payload"]["scope"],
        )
        for event in events
    } == {(1_100_000, 1_000_000, "pod")}


def test_finality_survives_a_restart_readback(db_dsn: str, world: World, db: Database) -> None:
    _paid(world)
    from microdrama.budget.billing import BillingRepository

    _episode, lease, _reservation = _seed_straddling(world, db)
    repository = BillingRepository(db, budget_service=world.service)
    _buckets_and_verify(world, db, repository)
    settle_billed_lease(db, world.service, lease_id=lease, context="restart")
    from microdrama.persistence import Database as Db

    with Db(db_dsn) as restarted:
        readiness = lease_billing_readiness(restarted, lease)
        assert readiness.state == "BILLED"
        with restarted.transaction(readonly=True) as tx:
            assert tx.fetchval("SELECT count(*) FROM charges WHERE kind='SETTLEMENT'") == 1


# --- T045-FIX A-S1: the audited podless-create resolution ---------------------------------


def _seed_podless_sent_create(world: World, db: Database, *, pod_id=None):
    """A runpod lease whose create was sent but which never produced a Pod."""
    episode = world.episode()
    with db.transaction() as tx:
        lease, reservation = insert_runpod_lease(
            tx,
            episode.episode_id,
            pod_id=pod_id,
            lease_state="RELEASED",
            pod_state="REQUESTED",
            create_requested_at=T0,
            reservation_micro_usd=900_000,
        )
    return episode, lease, reservation


def test_podless_create_resolution_bills_zero_and_releases(world: World, db: Database) -> None:
    from microdrama.budget.billing import BillingRepository

    _paid(world)
    episode, lease, reservation = _seed_podless_sent_create(world, db)
    repository = BillingRepository(db, budget_service=world.service)
    readiness = lease_billing_readiness(db, lease)
    assert readiness.state == "PENDING_PROVIDER_FINALITY"
    repository.resolve_podless_create(
        lease,
        actor_ref="owner:test",
        reason="console shows no Pod and no charge",
        evidence_sha256=_evidence("podless"),
    )
    readiness = lease_billing_readiness(db, lease)
    assert readiness.state == "BILLED"
    assert readiness.billed_micro_usd == 0
    row = _reservation_row(db, reservation)
    assert row["state"] == "SETTLED"
    assert row["settled_micro_usd"] == 0
    counters = world.counters(episode.account_id)
    assert counters["reserved"] == 0  # the whole hold was released
    assert counters["settled"] == 0
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM runpod_podless_create_resolutions") == 1
        assert tx.fetchval("SELECT count(*) FROM charges WHERE kind='SETTLEMENT'") == 1


def test_podless_resolution_is_refused_once_a_pod_is_attached(world: World, db: Database) -> None:
    from microdrama.budget.billing import BillingRepository
    from microdrama.contracts.errors import Conflict

    _paid(world)
    _episode, lease, _reservation = _seed_podless_sent_create(world, db, pod_id="pod-attached")
    repository = BillingRepository(db, budget_service=world.service)
    with pytest.raises(Conflict, match="attached"):
        repository.resolve_podless_create(
            lease,
            actor_ref="owner:test",
            reason="stray adopted later",
            evidence_sha256=_evidence("attached"),
        )
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM runpod_podless_create_resolutions") == 0


def test_podless_resolution_requires_actor_and_reason(world: World, db: Database) -> None:
    from microdrama.budget.billing import BillingRepository
    from microdrama.contracts.errors import SchemaInvalid

    _paid(world)
    _episode, lease, _reservation = _seed_podless_sent_create(world, db)
    repository = BillingRepository(db, budget_service=world.service)
    with pytest.raises(SchemaInvalid, match="actor"):
        repository.resolve_podless_create(
            lease, actor_ref="  ", reason="reason", evidence_sha256=_evidence("a")
        )
    with pytest.raises(SchemaInvalid, match="reason"):
        repository.resolve_podless_create(
            lease, actor_ref="owner:test", reason="", evidence_sha256=_evidence("b")
        )


def test_replaying_a_podless_resolution_is_a_noop(world: World, db: Database) -> None:
    from microdrama.budget.billing import BillingRepository

    _paid(world)
    episode, lease, _reservation = _seed_podless_sent_create(world, db)
    repository = BillingRepository(db, budget_service=world.service)
    repository.resolve_podless_create(
        lease,
        actor_ref="owner:test",
        reason="console shows no Pod and no charge",
        evidence_sha256=_evidence("replay"),
    )
    repository.resolve_podless_create(
        lease,
        actor_ref="owner:test",
        reason="console shows no Pod and no charge",
        evidence_sha256=_evidence("replay"),
    )
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM runpod_podless_create_resolutions") == 1
        assert tx.fetchval("SELECT count(*) FROM charges WHERE kind='SETTLEMENT'") == 1
    assert world.counters(episode.account_id)["settled"] == 0


def test_a_pod_appearing_after_a_resolution_does_not_double_settle(
    world: World, db: Database
) -> None:
    from microdrama.budget.billing import BillingRepository
    from microdrama.contracts.errors import Conflict

    _paid(world)
    episode, lease, _reservation = _seed_podless_sent_create(world, db)
    repository = BillingRepository(db, budget_service=world.service)
    repository.resolve_podless_create(
        lease,
        actor_ref="owner:test",
        reason="console showed no Pod",
        evidence_sha256=_evidence("late-pod"),
    )
    with db.transaction() as tx:  # the stray the provider finally admitted
        tx.execute(
            "UPDATE pod_leases SET pod_id='pod-late', pod_state='RUNNING' WHERE id=%s", (lease,)
        )
    with pytest.raises(Conflict):
        # A second resolution is structurally impossible once the Pod exists; the
        # existing stray-adoption path (buckets, invoice, REOPENED adjustments) is
        # the only way cost can arrive now.
        repository.resolve_podless_create(
            lease, actor_ref="owner:test", reason="again", evidence_sha256=_evidence("again")
        )
    assert world.counters(episode.account_id)["settled"] == 0


def test_a_budgetless_repository_refuses_a_podless_resolution_without_writing_it(
    world: World, db: Database
) -> None:
    """T045-FIX RR-N1: the budget service is checked FIRST - a budget-less repository
    refuses and leaves no resolution row, no window end and no settlement behind."""
    from microdrama.budget.billing import BillingRepository
    from microdrama.contracts.errors import Conflict

    _paid(world)
    _episode, lease, _reservation = _seed_podless_sent_create(world, db)
    repository = BillingRepository(db, budget_service=None)
    with pytest.raises(Conflict, match="budget service"):
        repository.resolve_podless_create(
            lease,
            actor_ref="owner:test",
            reason="console shows no Pod and no charge",
            evidence_sha256=_evidence("budgetless"),
        )
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM runpod_podless_create_resolutions") == 0
        assert tx.fetchval("SELECT count(*) FROM charges WHERE kind='SETTLEMENT'") == 0
        window_end = tx.fetchval(
            "SELECT compute_window_end_at FROM pod_leases WHERE id=%s", (lease,)
        )
    assert window_end is None


def test_a_pod_without_a_window_start_is_pending_not_billed_zero(
    world: World, db: Database
) -> None:
    """T045-FIX A-S4: an attached Pod with no recorded window start is pending
    provider finality, never a free BILLED 0."""
    episode = world.episode()
    with db.transaction() as tx:
        lease, _reservation = insert_runpod_lease(
            tx,
            episode.episode_id,
            pod_id="pod-nostart",
            lease_state="ACTIVE",
            pod_state="RUNNING",
            create_requested_at=None,
            compute_window_start_at=None,
        )
    readiness = lease_billing_readiness(db, lease)
    assert readiness.state == "PENDING_PROVIDER_FINALITY"


def test_a_concurrent_adjustment_is_never_dropped_by_the_settlement(
    db_dsn: str, world: World, db: Database
) -> None:
    """T045-FIX A-S3: the settlement recomputes readiness and the GPU sum and posts in
    one transaction holding the reservation row lock. An ADJUSTMENT committing between
    an earlier read and the settlement ends with settled equal to the full posted sum —
    the stale SETTLEMENT that replaced (and dropped) the adjustment is impossible."""
    from concurrent.futures import ThreadPoolExecutor
    from datetime import UTC, datetime
    from uuid import uuid4

    import psycopg

    from microdrama.budget.billing import BillingRepository

    _paid(world)
    episode, lease, reservation = _seed_straddling(world, db)
    repository = BillingRepository(db, budget_service=world.service)
    _buckets_and_verify(world, db, repository)
    with db.transaction(readonly=True) as tx:
        posted_before = tx.fetchval(
            "SELECT COALESCE(SUM(amount_micro_usd),0) FROM charges "
            "WHERE reservation_id=%s AND kind IN ('ACCRUAL','ADJUSTMENT')",
            (reservation,),
        )
    adjustment = 137_000
    # A second session holds the reservation lock, mirroring an in-flight settlement
    # read; the adjustment commits inside that session before it releases the lock.
    blocker = psycopg.connect(db_dsn)
    blocker.autocommit = False
    try:
        with blocker.cursor() as cur:
            cur.execute("SELECT 1 FROM reservations WHERE id = %s FOR UPDATE", (str(reservation),))
            charge = uuid4()
            with blocker.cursor() as writer:
                writer.execute(
                    "INSERT INTO charges (id, account_id, reservation_id, receipt_id, "
                    "provider, provider_receipt_id, kind, cost_basis, provenance, category, "
                    "amount_micro_usd, units, unit, observed_at, receipt) VALUES "
                    "(%s, (SELECT account_id FROM reservations WHERE id=%s), %s, %s, "
                    "'runpod', %s, 'ADJUSTMENT', 'PROVIDER_REPORTED', 'LIVE_PROVIDER', "
                    "'GPU_GENERATION', %s, 0, 'GPU_SECOND', %s, '{}')",
                    (
                        str(charge),
                        str(reservation),
                        str(reservation),
                        str(uuid4()),
                        f"race-adjustment:{charge}",
                        adjustment,
                        datetime.now(UTC),
                    ),
                )
                writer.execute(
                    "UPDATE reservations SET accrued_micro_usd = accrued_micro_usd + %s "
                    "WHERE id = %s",
                    (adjustment, str(reservation)),
                )
                # Mirror an ADJUSTMENT on a fully-accrued ACTIVE hold: reserved does
                # not move, accrued rises on the account and its GPU category too.
                writer.execute(
                    "UPDATE budget_accounts SET accrued_micro_usd = accrued_micro_usd + %s "
                    "WHERE id = (SELECT account_id FROM reservations WHERE id = %s)",
                    (adjustment, str(reservation)),
                )
                writer.execute(
                    "UPDATE budget_category_allocations SET accrued_micro_usd = "
                    "accrued_micro_usd + %s WHERE account_id = "
                    "(SELECT account_id FROM reservations WHERE id = %s) "
                    "AND category = 'GPU_GENERATION'",
                    (adjustment, str(reservation)),
                )
        with ThreadPoolExecutor(max_workers=1) as pool:
            settled_task = pool.submit(
                settle_billed_lease,
                db,
                world.service,
                lease_id=lease,
                context="race",
            )
            import time

            time.sleep(1.0)  # the settlement reaches its lock before the adjustment commits
            blocker.commit()
            settled = settled_task.result(timeout=30)
        assert settled == int(posted_before) + adjustment
        with db.transaction(readonly=True) as tx:
            row = tx.fetchone("SELECT * FROM reservations WHERE id=%s", (reservation,))
            settlement = tx.fetchone(
                "SELECT amount_micro_usd FROM charges WHERE reservation_id=%s "
                "AND kind='SETTLEMENT'",
                (reservation,),
            )
        assert row["state"] == "SETTLED"
        assert row["settled_micro_usd"] == int(posted_before) + adjustment
        assert settlement["amount_micro_usd"] == int(posted_before) + adjustment
    finally:
        blocker.close()


def test_ceil_seconds_is_exact_integer_arithmetic() -> None:
    """T045-FIX B-N1: money/time math never passes through a binary float - exact
    boundaries (1 us, a day and 1 us, exactly one second) round-trip exactly."""
    from microdrama.budget.billing import _ceil_seconds

    assert _ceil_seconds(timedelta(microseconds=1)) == 1
    assert _ceil_seconds(timedelta(days=1, microseconds=1)) == 86_401
    assert _ceil_seconds(timedelta(seconds=1)) == 1
    assert _ceil_seconds(timedelta(seconds=1, microseconds=1)) == 2
