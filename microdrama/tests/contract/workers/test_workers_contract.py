"""Contract tests for the workers lane (T028): the frozen surfaces it consumes.

Pins, against the frozen 1.6.0 contracts and the real migrated database:
- the ``RateLimiter`` protocol and ``RateDecision`` model (a denial always
  carries ``retry_after_ms`` and the bucket key);
- the real ``SharedRateLimiter`` produces the SAME decisions as the T007
  ``InMemoryRateLimiter`` oracle for identical call sequences — the fake is
  the frozen behavioral spec of a token bucket;
- the frozen JOB_SPECS routing table the runtime relies on: every job type
  maps to exactly one of the three queues, and all three queues carry specs;
- the ``jobs`` table queue CHECK (only the three isolated queues exist).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from microdrama.contracts.enums import QueueName
from microdrama.contracts.infra import RateDecision
from microdrama.contracts.jobs import JOB_SPECS
from microdrama.testing.fakes.common import FakeClock, SequentialIds
from microdrama.testing.fakes.infra import InMemoryRateLimiter
from microdrama.workers import SharedRateLimiter

T0 = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def test_rate_decision_denials_always_carry_a_wait() -> None:
    denial = RateDecision(allowed=False, retry_after_ms=750, limiter_key="youtube:a")
    assert denial.retry_after_ms >= 1
    assert denial.limiter_key == "youtube:a"
    allowed = RateDecision(allowed=True, limiter_key="k")
    assert allowed.allowed and allowed.retry_after_ms == 0  # zero wait: no delay to honor


def test_real_limiter_matches_the_frozen_fake_oracle() -> None:
    """Same clock, same calls, same decisions — the T007 fake IS the spec."""
    fake_clock = FakeClock(T0)
    real_clock = FakeClock(T0)
    fake = InMemoryRateLimiter(fake_clock, default_capacity=3, default_refill_per_second=2)
    real = SharedRateLimiter(real_clock, default_capacity=3, default_refill_per_second=2)
    script = [
        ("k", 1),
        ("k", 1),
        ("k", 1),  # bucket now empty
        ("k", 1),  # denial
        ("other", 2),
        ("other", 1),  # denial on the second bucket
    ]
    for key, cost in script:
        expected = fake.try_acquire(key, cost=cost)
        actual = real.try_acquire(key, cost=cost)
        assert actual.allowed is expected.allowed
        assert actual.remaining == expected.remaining
        assert actual.retry_after_ms == expected.retry_after_ms
    fake_clock.advance(seconds=1)
    real_clock.advance(seconds=1)
    expected = fake.try_acquire("k")
    actual = real.try_acquire("k")
    assert actual.allowed is expected.allowed  # both refilled identically


def test_job_specs_route_every_type_to_exactly_one_queue() -> None:
    queues = {QueueName.PRODUCTION, QueueName.PUBLICATION, QueueName.COMMUNITY}
    seen: dict[str, QueueName] = {}
    for spec in JOB_SPECS:
        assert spec.queue in queues
        assert spec.job_type not in seen, f"{spec.job_type} routed twice"
        seen[spec.job_type] = spec.queue
    assert set(seen.values()) == queues  # all three queues carry real work


def test_each_queue_has_paid_and_unpaid_work_where_specified() -> None:
    by_queue: dict[QueueName, list[bool]] = {q: [] for q in QueueName}
    for spec in JOB_SPECS:
        by_queue[spec.queue].append(spec.paid)
    assert any(by_queue[QueueName.PRODUCTION]) and not all(by_queue[QueueName.PRODUCTION])
    assert any(by_queue[QueueName.COMMUNITY]) and not all(by_queue[QueueName.COMMUNITY])


def test_jobs_table_accepts_only_the_three_queues(db) -> None:
    from microdrama.contracts.errors import Conflict
    from microdrama.persistence.db import insert_row

    values = {
        "id": SequentialIds("contract").new_id(),
        "job_type": "qa.technical",
        "queue": "community",
        "semantic_key": "workers-contract-ok",
        "input_hash": "c" * 64,
        "input": {"episode_id": "00000000-0000-0000-0000-000000000000"},
        "status": "QUEUED",
        "priority": 100,
        "max_attempts": 3,
        "run_after": T0,
    }
    with db.transaction() as tx:
        insert_row(tx, "jobs", values)
    with pytest.raises(Conflict):  # queue CHECK: only the three frozen queues
        with db.transaction() as tx:
            insert_row(
                tx,
                "jobs",
                {
                    **values,
                    "id": SequentialIds("contract2").new_id(),
                    "semantic_key": "workers-contract-bad",
                    "queue": "urgent",
                },
            )
