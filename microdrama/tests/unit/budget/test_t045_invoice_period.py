"""T045 R5+R6: pod-scoped period invoice evidence, idempotent replay, typed conflicts.

Red-first: there was no period-level verification at all — replaying an invoice raised
IntegrityError or wrote a second verification row.
"""

from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from budget_support import World
from t045_support import ACCOUNT_REF, T0, closed_bucket, insert_runpod_lease

from microdrama.budget.billing import BillingRepository
from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode
from microdrama.contracts.errors import Conflict, IdempotencyConflict, SchemaInvalid
from microdrama.persistence import Database

pytestmark = pytest.mark.db

HOUR = timedelta(hours=1)


def _paid(world: World) -> BillingRepository:
    world.service._settings = Settings(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
    )
    return BillingRepository(world.db, budget_service=world.service)


def _evidence(label: str) -> str:
    return sha256(f"t045-evidence:{label}".encode()).hexdigest()


def _seed_episode_with_lease(world: World, db: Database, *, pod_id: str):
    episode = world.episode()
    with db.transaction() as tx:
        insert_runpod_lease(
            tx,
            episode.episode_id,
            pod_id=pod_id,
            lease_state="RELEASED",
            pod_state="TERMINATED",
            create_requested_at=T0,
            compute_window_start_at=T0,
            compute_window_end_at=T0 + HOUR,
            stop_verified_at=T0 + HOUR,
            terminate_verified_at=T0 + HOUR,
        )
    return episode


def _verify(repository, **overrides):
    kwargs = dict(
        provider_account_ref=ACCOUNT_REF,
        pod_id="pod-period",
        period_start=T0,
        period_end=T0 + HOUR,
        amount_micro_usd=600_000,
        currency="USD",
        evidence_sha256=_evidence("first"),
        source="INVOICE",
        observed_at=T0 + 2 * HOUR,
    )
    kwargs.update(overrides)
    return repository.verify_invoice_period(**kwargs)


def test_match_writes_period_revisions_verifications_and_finalizations_in_one_transaction(
    world: World, db: Database
) -> None:
    repository = _paid(world)
    episode = _seed_episode_with_lease(world, db, pod_id="pod-period")
    query, bucket = closed_bucket(
        pod_id="pod-period", start=T0, end=T0 + HOUR, gpu=600_000, cpu=0, disk=0
    )
    repository.ingest(query, [bucket])
    result = _verify(repository)
    assert result.outcome == "MATCHED"
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM runpod_billing_period_evidence") == 1
        assert (
            tx.fetchval(
                "SELECT count(*) FROM runpod_billing_buckets WHERE finality_state='INVOICE_VERIFIED'"
            )
            == 1
        )
        assert tx.fetchval("SELECT count(*) FROM runpod_billing_invoice_verifications") == 1
        assert tx.fetchval("SELECT count(*) FROM runpod_billing_budget_finalizations") == 1
        verified = tx.fetchone(
            "SELECT revision, raw_response_sha256, invoice_verification_id "
            "FROM runpod_billing_buckets WHERE finality_state='INVOICE_VERIFIED'"
        )
    assert verified["revision"] == 2
    assert verified["raw_response_sha256"] == bucket.raw_response_sha256
    assert verified["invoice_verification_id"] is not None
    # The episode keeps its posted provider spend as accrual against the lease hold
    # (R7's BILLED settlement moves it to settled); verification added no money.
    assert world.counters(episode.account_id)["accrued"] == 600_000


def test_identical_replay_is_a_no_op(world: World, db: Database) -> None:
    repository = _paid(world)
    _seed_episode_with_lease(world, db, pod_id="pod-period")
    query, bucket = closed_bucket(
        pod_id="pod-period", start=T0, end=T0 + HOUR, gpu=600_000, cpu=0, disk=0
    )
    repository.ingest(query, [bucket])
    first = _verify(repository)
    second = _verify(repository)
    assert second.replayed is True
    assert second.period_evidence_id == first.period_evidence_id
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM runpod_billing_period_evidence") == 1
        assert tx.fetchval("SELECT count(*) FROM runpod_billing_buckets") == 2
        assert tx.fetchval("SELECT count(*) FROM runpod_billing_invoice_verifications") == 1
        assert tx.fetchval("SELECT count(*) FROM runpod_billing_budget_finalizations") == 1


def test_conflicting_replay_raises_a_typed_idempotency_conflict(world: World, db: Database) -> None:
    repository = _paid(world)
    _seed_episode_with_lease(world, db, pod_id="pod-period")
    query, bucket = closed_bucket(
        pod_id="pod-period", start=T0, end=T0 + HOUR, gpu=600_000, cpu=0, disk=0
    )
    repository.ingest(query, [bucket])
    _verify(repository)
    with pytest.raises(IdempotencyConflict):
        _verify(repository, amount_micro_usd=599_999)
    with pytest.raises(IdempotencyConflict):
        _verify(repository, currency="EUR")


def test_new_evidence_for_a_verified_period_conflicts_unless_superseded(
    world: World, db: Database
) -> None:
    repository = _paid(world)
    _seed_episode_with_lease(world, db, pod_id="pod-period")
    query, bucket = closed_bucket(
        pod_id="pod-period", start=T0, end=T0 + HOUR, gpu=600_000, cpu=0, disk=0
    )
    repository.ingest(query, [bucket])
    first = _verify(repository)
    with pytest.raises(Conflict, match="verified"):
        _verify(repository, evidence_sha256=_evidence("other"))
    # An explicit supersede is audited with actor and reason.
    superseded = _verify(
        repository,
        evidence_sha256=_evidence("corrected"),
        supersedes_evidence_id=first.period_evidence_id,
        actor_ref="owner:test",
        reason="operator corrected the invoice export",
    )
    assert superseded.outcome == "MATCHED"
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT * FROM runpod_billing_period_evidence WHERE evidence_sha256=%s",
            (_evidence("corrected"),),
        )
    assert row["supersedes_evidence_id"] == first.period_evidence_id
    assert row["actor_ref"] == "owner:test"
    assert row["reason"]


def test_supersede_requires_actor_and_reason(world: World, db: Database) -> None:
    repository = _paid(world)
    _seed_episode_with_lease(world, db, pod_id="pod-period")
    query, bucket = closed_bucket(
        pod_id="pod-period", start=T0, end=T0 + HOUR, gpu=600_000, cpu=0, disk=0
    )
    repository.ingest(query, [bucket])
    first = _verify(repository)
    with pytest.raises(SchemaInvalid, match="actor and reason"):
        _verify(
            repository,
            evidence_sha256=_evidence("unaudited"),
            supersedes_evidence_id=first.period_evidence_id,
        )


def test_mismatch_writes_only_the_period_row(world: World, db: Database) -> None:
    repository = _paid(world)
    _seed_episode_with_lease(world, db, pod_id="pod-period")
    query, bucket = closed_bucket(
        pod_id="pod-period", start=T0, end=T0 + HOUR, gpu=600_000, cpu=0, disk=0
    )
    repository.ingest(query, [bucket])
    result = _verify(repository, amount_micro_usd=999_000)
    assert result.outcome == "MISMATCHED"
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM runpod_billing_period_evidence") == 1
        assert (
            tx.fetchval(
                "SELECT count(*) FROM runpod_billing_buckets WHERE finality_state='INVOICE_VERIFIED'"
            )
            == 0
        )
        assert tx.fetchval("SELECT count(*) FROM runpod_billing_invoice_verifications") == 0
        assert tx.fetchval("SELECT count(*) FROM runpod_billing_budget_finalizations") == 0
    # A lower invoice decrements nothing: posted spend stays exactly as it was.
    _verify(repository, evidence_sha256=_evidence("true-sum"))  # corrected match
    with db.transaction(readonly=True) as tx:
        settled = tx.fetchval(
            "SELECT COALESCE(SUM(amount_micro_usd),0) FROM charges WHERE provider='runpod'"
        )
    assert settled == 600_000


def test_billed_zero_matches_an_empty_query_after_the_lag(world: World, db: Database) -> None:
    repository = _paid(world)
    _seed_episode_with_lease(world, db, pod_id="pod-zero-live")
    # The pod lived seconds inside a bucket that never materialised: an EMPTY query
    # after the settle lag is the evidence for a zero invoice.
    empty_query, _bucket = closed_bucket(
        pod_id="pod-zero-live", start=T0, end=T0 + HOUR, gpu=0, cpu=0, disk=0
    )
    empty = empty_query.model_copy(update={"result_state": "EMPTY", "bucket_observation_ids": []})
    empty = type(empty_query).model_validate(empty.model_dump(mode="python"))
    repository.ingest(empty, [])
    result = repository.verify_invoice_period(
        provider_account_ref=ACCOUNT_REF,
        pod_id="pod-zero-live",
        period_start=T0,
        period_end=T0 + HOUR,
        amount_micro_usd=0,
        currency="USD",
        evidence_sha256=_evidence("zero"),
        source="CONSOLE",
        observed_at=T0 + 2 * HOUR,
    )
    assert result.outcome == "MATCHED_ZERO"
    with db.transaction(readonly=True) as tx:
        assert (
            tx.fetchval("SELECT count(*) FROM runpod_billing_buckets WHERE pod_id='pod-zero-live'")
            == 0
        )


def test_non_boundary_period_is_refused(world: World, db: Database) -> None:
    repository = _paid(world)
    _seed_episode_with_lease(world, db, pod_id="pod-period")
    query, bucket = closed_bucket(
        pod_id="pod-period", start=T0, end=T0 + HOUR, gpu=600_000, cpu=0, disk=0
    )
    repository.ingest(query, [bucket])
    with pytest.raises(SchemaInvalid, match="bucket boundaries"):
        _verify(repository, period_start=T0 + timedelta(minutes=10))


def test_period_with_skipped_open_buckets_is_refused(world: World, db: Database) -> None:
    repository = _paid(world)
    _seed_episode_with_lease(world, db, pod_id="pod-period")
    closed = closed_bucket(pod_id="pod-period", start=T0, end=T0 + HOUR, gpu=600_000, cpu=0, disk=0)
    open_bucket = closed_bucket(
        pod_id="pod-period",
        start=T0 + HOUR,
        end=T0 + 2 * HOUR,
        gpu=10,
        cpu=0,
        disk=0,
        observed_at=T0 + HOUR + timedelta(minutes=5),
    )
    shared = uuid4()
    aged = T0 + 2 * HOUR + timedelta(hours=1)
    query = closed[0].model_copy(
        update={
            "query_id": shared,
            "requested_window_end": T0 + 2 * HOUR,
            "provider_resolved_window_end": T0 + 2 * HOUR,
            "observed_at": aged,
            "bucket_observation_ids": [closed[1].observation_id, open_bucket[1].observation_id],
        }
    )
    query = type(closed[0]).model_validate(query.model_dump(mode="python"))
    closed_model = closed[1].model_copy(
        update={
            "query_id": shared,
            "provider_resolved_window_start": T0,
            "provider_resolved_window_end": T0 + 2 * HOUR,
            "observed_at": aged,
        }
    )
    open_model = open_bucket[1].model_copy(
        update={
            "query_id": shared,
            "provider_resolved_window_start": T0,
            "provider_resolved_window_end": T0 + 2 * HOUR,
            "observed_at": T0 + HOUR + timedelta(minutes=5),  # still open
        }
    )
    repository.ingest(query, [closed_model, open_model])
    with pytest.raises(Conflict, match="skipped"):
        _verify(
            repository,
            period_start=T0,
            period_end=T0 + 2 * HOUR,
            amount_micro_usd=600_010,
        )


def test_no_completed_query_after_the_lag_is_refused(world: World, db: Database) -> None:
    repository = _paid(world)
    _seed_episode_with_lease(world, db, pod_id="pod-period")
    query, bucket = closed_bucket(
        pod_id="pod-period",
        start=T0,
        end=T0 + HOUR,
        gpu=600_000,
        cpu=0,
        disk=0,
        observed_at=T0 + HOUR + timedelta(minutes=5),
    )
    repository.ingest(query, [bucket])  # everything open: skipped, nothing stored
    with pytest.raises(Conflict, match="query"):
        _verify(repository)


# --- T045-FIX: A-B1, A-N3, A-N4 -----------------------------------------------------------


def _response(
    repository: BillingRepository,
    *,
    pod_id: str,
    buckets: list,
    observed_at,
    window: tuple,
) -> None:
    """Ingest one provider response whose every bucket shares one query."""
    query_id = uuid4()
    payload = buckets[0][0].model_dump(mode="python")
    payload.update(
        query_id=query_id,
        requested_window_start=window[0],
        requested_window_end=window[1],
        provider_resolved_window_start=window[0],
        provider_resolved_window_end=window[1],
        observed_at=observed_at,
        bucket_observation_ids=[b[1].observation_id for b in buckets],
    )
    query = type(buckets[0][0]).model_validate(payload)
    models = []
    for b in buckets:
        body = b[1].model_dump(mode="python")
        body.update(
            query_id=query_id,
            provider_resolved_window_start=window[0],
            provider_resolved_window_end=window[1],
            observed_at=observed_at,
        )
        models.append(type(b[1]).model_validate(body))
    repository.ingest(query, models)


def _skip_fixtures(pod_id: str) -> list:
    """Two half-hour buckets covering [T0, T0+1H], gpu 300_000 each."""
    return [
        closed_bucket(
            pod_id=pod_id, start=T0, end=T0 + timedelta(minutes=30), gpu=300_000, cpu=0, disk=0
        ),
        closed_bucket(
            pod_id=pod_id,
            start=T0 + timedelta(minutes=30),
            end=T0 + HOUR,
            gpu=300_000,
            cpu=0,
            disk=0,
        ),
    ]


def test_a_skip_closed_by_a_later_observation_no_longer_blocks_verification(
    world: World, db: Database
) -> None:
    """T045-FIX A-B1: an open poll writes skips; once a later poll of the same buckets
    observes them closed, the period verifies, the lease reaches BILLED and the hold's
    remainder is released."""
    from microdrama.budget.billing import lease_billing_readiness, settle_billed_lease
    from t045_support import insert_runpod_lease

    repository = _paid(world)
    episode = world.episode()
    with db.transaction() as tx:
        lease_id, reservation_id = insert_runpod_lease(
            tx,
            episode.episode_id,
            pod_id="pod-skip",
            lease_state="RELEASED",
            pod_state="TERMINATED",
            create_requested_at=T0,
            compute_window_start_at=T0,
            compute_window_end_at=T0 + HOUR,
            stop_verified_at=T0 + HOUR,
            terminate_verified_at=T0 + HOUR,
            provider_account_ref=ACCOUNT_REF,
        )
    buckets = _skip_fixtures("pod-skip")
    # Poll 1, 10 min into the run: both buckets are still open -> skipped, query UNKNOWN.
    _response(
        repository,
        pod_id="pod-skip",
        buckets=buckets,
        observed_at=T0 + timedelta(minutes=10),
        window=(T0, T0 + HOUR),
    )
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM runpod_billing_query_skipped_buckets") == 2
    # Poll 2 (past the settle lag): the same identities, now closed -> stored.
    _response(
        repository,
        pod_id="pod-skip",
        buckets=buckets,
        observed_at=T0 + HOUR + timedelta(minutes=20),
        window=(T0, T0 + HOUR),
    )
    result = repository.verify_invoice_period(
        provider_account_ref=ACCOUNT_REF,
        pod_id="pod-skip",
        period_start=T0,
        period_end=T0 + HOUR,
        amount_micro_usd=600_000,
        currency="USD",
        evidence_sha256=_evidence("skip-closed"),
        source="INVOICE",
        observed_at=T0 + 2 * HOUR,
    )
    assert result.outcome == "MATCHED"
    readiness = lease_billing_readiness(db, lease_id)
    assert readiness.state == "BILLED"
    settled = settle_billed_lease(db, world.service, lease_id=lease_id, context="t045-fix a-b1")
    assert settled == 600_000
    with db.transaction(readonly=True) as tx:
        reservation = tx.fetchone("SELECT * FROM reservations WHERE id=%s", (reservation_id,))
    assert reservation["state"] == "SETTLED"
    # The 300_000 remainder of the 900_000 hold was released, not kept.
    counters = world.counters(episode.account_id)
    assert counters["reserved"] == 0
    assert counters["settled"] == 600_000


def test_a_skip_with_no_later_closed_observation_still_refuses(world: World, db: Database) -> None:
    """T045-FIX A-B1 keeps the refusal when no closed observation follows the skip.

    (This boundary already refused before the fix; it is kept as the guard that the
    A-B1 change does not over-correct.)"""
    repository = _paid(world)
    _seed_episode_with_lease(world, db, pod_id="pod-skip")
    buckets = _skip_fixtures("pod-skip")
    _response(
        repository,
        pod_id="pod-skip",
        buckets=buckets,
        observed_at=T0 + timedelta(minutes=10),
        window=(T0, T0 + HOUR),
    )
    # A later covering poll returns only the first bucket; the second skip never closes.
    _response(
        repository,
        pod_id="pod-skip",
        buckets=[buckets[0]],
        observed_at=T0 + HOUR + timedelta(minutes=20),
        window=(T0, T0 + HOUR),
    )
    with pytest.raises(Conflict, match="skipped"):
        repository.verify_invoice_period(
            provider_account_ref=ACCOUNT_REF,
            pod_id="pod-skip",
            period_start=T0,
            period_end=T0 + HOUR,
            amount_micro_usd=600_000,
            currency="USD",
            evidence_sha256=_evidence("skip-open"),
            source="INVOICE",
            observed_at=T0 + 2 * HOUR,
        )


def test_an_account_scoped_covering_query_is_not_coverage(world: World, db: Database) -> None:
    """T045-FIX A-N3: a completed query whose buckets belong to another Pod does not
    cover this Pod's period."""
    repository = _paid(world)
    _seed_episode_with_lease(world, db, pod_id="pod-scoped")
    other = closed_bucket(
        pod_id="pod-other", start=T0, end=T0 + HOUR, gpu=600_000, cpu=0, disk=0
    )
    repository.ingest(other[0], [other[1]])
    with pytest.raises(Conflict, match="covers the period"):
        repository.verify_invoice_period(
            provider_account_ref=ACCOUNT_REF,
            pod_id="pod-scoped",
            period_start=T0,
            period_end=T0 + HOUR,
            amount_micro_usd=600_000,
            currency="USD",
            evidence_sha256=_evidence("scoped"),
            source="INVOICE",
            observed_at=T0 + 2 * HOUR,
        )


def test_a_bucket_straddling_the_period_edge_is_refused(world: World, db: Database) -> None:
    """T045-FIX A-N4: every counted bucket must lie fully inside the period, even when
    aligned buckets exist at both edges."""
    repository = _paid(world)
    _seed_episode_with_lease(world, db, pod_id="pod-straddle")
    window = (T0, T0 + HOUR + timedelta(minutes=15))
    first = closed_bucket(
        pod_id="pod-straddle",
        start=T0,
        end=T0 + timedelta(minutes=30),
        gpu=300_000,
        cpu=0,
        disk=0,
        query_window=window,
    )
    second = closed_bucket(
        pod_id="pod-straddle",
        start=T0 + timedelta(minutes=30),
        end=T0 + HOUR,
        gpu=300_000,
        cpu=0,
        disk=0,
        query_window=window,
    )
    straddler = closed_bucket(
        pod_id="pod-straddle",
        start=T0 + timedelta(minutes=45),
        end=T0 + HOUR + timedelta(minutes=15),
        gpu=50_000,
        cpu=0,
        disk=0,
        query_window=window,
    )
    repository.ingest(first[0], [first[1]])
    repository.ingest(second[0], [second[1]])
    repository.ingest(straddler[0], [straddler[1]])
    with pytest.raises(SchemaInvalid, match="straddle"):
        repository.verify_invoice_period(
            provider_account_ref=ACCOUNT_REF,
            pod_id="pod-straddle",
            period_start=T0,
            period_end=T0 + HOUR,
            amount_micro_usd=600_000,
            currency="USD",
            evidence_sha256=_evidence("straddle"),
            source="INVOICE",
            observed_at=T0 + 2 * HOUR,
        )
