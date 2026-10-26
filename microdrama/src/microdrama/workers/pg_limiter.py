"""The PostgreSQL-backed shared rate limiter (build-review F04).

``SharedRateLimiter`` keeps buckets in a process-local dictionary: separate
worker processes each hold an independent full allowance, and a restart forgets
everything. This limiter keeps the SAME integer token math but stores every
bucket in ``rate_limit_buckets`` and takes the row lock on acquire, so all
processes and restarts share one allowance per provider+account key — the quota
a provider actually enforces. Registration (``set_limit``/``register``) resets
the bucket, exactly like the in-process limiter.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.infra import Clock, RateDecision
from microdrama.persistence.db import Database

from .limiter import ProviderLimit

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MILLI_PER_TOKEN = 1000


class PostgresSharedRateLimiter:
    """Token-bucket limiter whose buckets live in the shared database."""

    def __init__(
        self,
        db: Database,
        clock: Clock,
        *,
        default_capacity: int = 10,
        default_refill_per_second: int = 1,
    ) -> None:
        self._db = db
        self._clock = clock
        self._default = (default_capacity, default_refill_per_second)

    def set_limit(self, key: str, *, capacity: int, refill_per_second: int) -> None:
        if capacity < 1 or refill_per_second < 1:
            raise SchemaInvalid("capacity and refill rate must be at least 1")
        now_ms = self._now_ms()
        with self._db.transaction() as tx:
            # A registered limit starts fresh, never inherited (same rule as the
            # in-process limiter): full bucket stamped at registration time.
            tx.execute(
                "INSERT INTO rate_limit_buckets (limiter_key, capacity, refill_per_second, "
                "milli_tokens, last_ms) VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (limiter_key) DO UPDATE SET capacity = excluded.capacity, "
                "refill_per_second = excluded.refill_per_second, "
                "milli_tokens = excluded.milli_tokens, last_ms = excluded.last_ms, "
                "revision = rate_limit_buckets.revision + 1",
                (key, capacity, refill_per_second, capacity * _MILLI_PER_TOKEN, now_ms),
            )

    def register(self, limits: tuple[ProviderLimit, ...]) -> None:
        for limit in limits:
            self.set_limit(
                limit.key,
                capacity=limit.capacity,
                refill_per_second=limit.refill_per_second,
            )

    def _now_ms(self) -> int:
        return (self._clock.now() - _EPOCH) // timedelta(milliseconds=1)

    def try_acquire(self, key: str, *, cost: int = 1) -> RateDecision:
        if cost < 1:
            raise SchemaInvalid("cost must be at least 1")
        now_ms = self._now_ms()
        # The row lock is the atomicity: every concurrent acquire in every
        # process serializes here, so one account's tokens are spent once.
        with self._db.transaction() as tx:
            tx.execute(
                "INSERT INTO rate_limit_buckets (limiter_key, capacity, refill_per_second, "
                "milli_tokens, last_ms) VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (limiter_key) DO NOTHING",
                (key, *self._default, self._default[0] * _MILLI_PER_TOKEN, now_ms),
            )
            row = tx.fetchone(
                "SELECT capacity, refill_per_second, milli_tokens, last_ms "
                "FROM rate_limit_buckets WHERE limiter_key = %s FOR UPDATE",
                (key,),
            )
            assert row is not None  # inserted or existed; the lock holds either way
            capacity = int(row["capacity"])
            refill = int(row["refill_per_second"])
            full = capacity * _MILLI_PER_TOKEN
            milli = min(
                full, int(row["milli_tokens"]) + max(0, now_ms - int(row["last_ms"])) * refill
            )
            needed = cost * _MILLI_PER_TOKEN
            if milli >= needed:
                milli -= needed
                allowed = True
                wait_ms = 0
            else:
                allowed = False
                wait_ms = -(-(needed - milli) // refill)  # ceiling division, integer only
            tx.execute(
                "UPDATE rate_limit_buckets SET milli_tokens = %s, last_ms = %s, "
                "revision = revision + 1 WHERE limiter_key = %s",
                (milli, now_ms, key),
            )
        return RateDecision(
            allowed=allowed,
            retry_after_ms=wait_ms,
            limiter_key=key,
            remaining=milli // _MILLI_PER_TOKEN,
        )


__all__ = ["PostgresSharedRateLimiter"]
