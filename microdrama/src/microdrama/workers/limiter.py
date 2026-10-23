"""The shared provider/account rate limiter (T028, IMP-06, MD-013).

One limiter instance is shared by every queue's worker runtime: a provider or
account quota is global to the pipeline, not per queue. Truth rules:

- **One key per provider+account.** ``limiter_key`` builds the canonical key;
  a community reply and a publication submit against the same account serialize
  through the same bucket.
- **Integer token math only.** Tokens are tracked in milli-tokens refilled from
  the clock — deterministic under ``FakeClock``, no floats anywhere (the same
  arithmetic the T007 fake proved; this is the real, registered instance).
- **Registration is configuration.** Limits arrive as an explicit mapping
  (``ProviderLimit`` records) the integrator owns; an unregistered key uses the
  default bucket, and ``set_limit`` refuses non-positive capacities.
- **A denial is a wait, never a bypass.** ``try_acquire`` returns the
  ``retry_after_ms`` the caller must honor; there is no code path that forces a
  token or acquires on credit. Retries re-acquire from zero patience like
  everyone else.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.infra import Clock, RateDecision

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MILLI_PER_TOKEN = 1000


def limiter_key(provider: str, account_ref: str) -> str:
    """The canonical shared-quota key for one provider account."""
    return f"{provider}:{account_ref}"


@dataclass(frozen=True)
class ProviderLimit:
    """Registered bucket shape for one provider+account key (integrator config)."""

    key: str
    capacity: int
    refill_per_second: int


class SharedRateLimiter:
    """Token-bucket limiter over the frozen ``RateLimiter`` protocol."""

    def __init__(
        self,
        clock: Clock,
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
        self._buckets.pop(key, None)  # a re-registered limit starts fresh, not inherited

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
        capacity, refill = self._limits.get(key, self._default)
        full = capacity * _MILLI_PER_TOKEN
        now = self._now_ms()
        milli, last = self._buckets.get(key, (full, now))
        elapsed = max(0, now - last)
        milli = min(full, milli + elapsed * refill)
        needed = cost * _MILLI_PER_TOKEN
        if milli >= needed:
            milli -= needed
            self._buckets[key] = (milli, now)
            return RateDecision(allowed=True, limiter_key=key, remaining=milli // _MILLI_PER_TOKEN)
        self._buckets[key] = (milli, now)
        wait_ms = -(-(needed - milli) // refill)  # ceiling division, integer only
        return RateDecision(
            allowed=False,
            retry_after_ms=wait_ms,
            limiter_key=key,
            remaining=milli // _MILLI_PER_TOKEN,
        )


__all__ = ["ProviderLimit", "SharedRateLimiter", "limiter_key"]
