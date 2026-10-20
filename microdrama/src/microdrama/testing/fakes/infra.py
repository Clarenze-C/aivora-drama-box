"""In-memory test doubles for the queue transport and the shared rate limiter (T007).

Both are test doubles, not production infrastructure. They never block or sleep:
``dequeue`` returns immediately (``timeout_ms`` is accepted and ignored), and the rate
limiter refills from ``FakeClock`` time only.

Queue semantics follow the contract: delivery is at least once. A dequeued job stays
in flight until ``ack``; ``redeliver_unacked`` puts unacknowledged jobs back at the front,
so consumers must be idempotent.
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime, timedelta
from uuid import UUID

from microdrama.contracts.enums import QueueName
from microdrama.contracts.errors import NotFound, SchemaInvalid
from microdrama.contracts.infra import RateDecision
from microdrama.testing.fakes.common import FakeClock

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class InMemoryQueueTransport:
    """Job-id queue with in-flight tracking and explicit redelivery."""

    def __init__(self) -> None:
        self._pending: dict[QueueName, deque[UUID]] = {q: deque() for q in QueueName}
        self._inflight: dict[tuple[QueueName, UUID], None] = {}
        self.calls: list[tuple[str, str, str]] = []

    def enqueue(self, queue: QueueName, job_id: UUID) -> None:
        self.calls.append(("enqueue", queue.value, str(job_id)))
        self._pending[queue].append(job_id)

    def dequeue(self, queue: QueueName, *, timeout_ms: int) -> UUID | None:
        if timeout_ms < 0:
            raise SchemaInvalid("timeout_ms cannot be negative")
        self.calls.append(("dequeue", queue.value, ""))
        if not self._pending[queue]:
            return None
        job_id = self._pending[queue].popleft()
        self._inflight[(queue, job_id)] = None
        return job_id

    def ack(self, queue: QueueName, job_id: UUID) -> None:
        self.calls.append(("ack", queue.value, str(job_id)))
        if (queue, job_id) not in self._inflight:
            raise NotFound("job is not in flight on this queue", queue=queue.value)
        del self._inflight[(queue, job_id)]

    def depth(self, queue: QueueName) -> int:
        return len(self._pending[queue])

    def redeliver_unacked(self) -> list[UUID]:
        """Simulate a consumer crash: unacknowledged jobs return to the front, oldest first."""
        redelivered: list[UUID] = []
        for queue, job_id in reversed(list(self._inflight)):
            self._pending[queue].appendleft(job_id)
            redelivered.insert(0, job_id)
        self._inflight.clear()
        self.calls.append(("redeliver", "", str(len(redelivered))))
        return redelivered


class InMemoryRateLimiter:
    """Token bucket per key, refilled from the fake clock with integer milli-token maths.

    One token is 1000 milli-tokens. Refill adds ``elapsed_ms * refill_per_second`` milli-tokens
    (one milli-token per millisecond at one token per second), capped at the bucket capacity.
    """

    def __init__(
        self,
        clock: FakeClock,
        *,
        default_capacity: int = 10,
        default_refill_per_second: int = 1,
    ) -> None:
        self._clock = clock
        self._limits: dict[str, tuple[int, int]] = {}
        self._default = (default_capacity, default_refill_per_second)
        self._buckets: dict[str, tuple[int, int]] = {}  # key -> (milli_tokens, last_ms)

    def set_limit(self, key: str, *, capacity: int, refill_per_second: int) -> None:
        if capacity < 1 or refill_per_second < 1:
            raise SchemaInvalid("capacity and refill rate must be at least 1")
        self._limits[key] = (capacity, refill_per_second)
        self._buckets.pop(key, None)

    def _now_ms(self) -> int:
        return (self._clock.now() - _EPOCH) // timedelta(milliseconds=1)

    def try_acquire(self, key: str, *, cost: int = 1) -> RateDecision:
        if cost < 1:
            raise SchemaInvalid("cost must be at least 1")
        capacity, refill = self._limits.get(key, self._default)
        full = capacity * 1000
        now = self._now_ms()
        milli, last = self._buckets.get(key, (full, now))
        elapsed = max(0, now - last)
        milli = min(full, milli + elapsed * refill)
        needed = cost * 1000
        if milli >= needed:
            milli -= needed
            self._buckets[key] = (milli, now)
            return RateDecision(allowed=True, limiter_key=key, remaining=milli // 1000)
        self._buckets[key] = (milli, now)
        wait_ms = -(-(needed - milli) // refill)  # ceiling division, integer only
        return RateDecision(
            allowed=False,
            retry_after_ms=wait_ms,
            limiter_key=key,
            remaining=milli // 1000,
        )


__all__ = ["InMemoryQueueTransport", "InMemoryRateLimiter"]
