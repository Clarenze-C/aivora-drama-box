"""The shared limiter: token math, registration, canonical keys (T028)."""

from __future__ import annotations

import pytest

from microdrama.contracts.errors import SchemaInvalid
from microdrama.workers import ProviderLimit, limiter_key


class TestTokenMath:
    def test_full_bucket_allows_and_decrements(self, world):
        world.limiter.set_limit("youtube:acct", capacity=2, refill_per_second=1)
        first = world.limiter.try_acquire("youtube:acct")
        second = world.limiter.try_acquire("youtube:acct")
        assert first.allowed and second.allowed
        third = world.limiter.try_acquire("youtube:acct")
        assert not third.allowed
        assert third.retry_after_ms >= 1  # a denial always says how long to wait

    def test_refill_recovers_exactly_one_token_per_second(self, world):
        world.limiter.set_limit("youtube:acct", capacity=1, refill_per_second=1)
        assert world.limiter.try_acquire("youtube:acct").allowed
        assert not world.limiter.try_acquire("youtube:acct").allowed
        world.clock.advance(seconds=1)
        assert world.limiter.try_acquire("youtube:acct").allowed

    def test_burst_cost_denials_report_the_wait(self, world):
        world.limiter.set_limit("tiktok:acct", capacity=1, refill_per_second=2)
        world.limiter.try_acquire("tiktok:acct", cost=1)
        denial = world.limiter.try_acquire("tiktok:acct", cost=1)
        assert not denial.allowed
        assert denial.retry_after_ms == 500  # half a second at 2 tokens/s

    def test_keys_are_isolated_buckets(self, world):
        world.limiter.set_limit("youtube:a", capacity=1, refill_per_second=1)
        world.limiter.set_limit("youtube:b", capacity=1, refill_per_second=1)
        assert world.limiter.try_acquire("youtube:a").allowed
        assert world.limiter.try_acquire("youtube:b").allowed
        assert not world.limiter.try_acquire("youtube:a").allowed


class TestRegistration:
    def test_register_applies_every_profile(self, world):
        world.limiter.register(
            (
                ProviderLimit("youtube:acct", capacity=5, refill_per_second=1),
                ProviderLimit("tiktok:acct", capacity=1, refill_per_second=1),
            )
        )
        for _ in range(5):
            assert world.limiter.try_acquire("youtube:acct").allowed
        assert not world.limiter.try_acquire("youtube:acct").allowed
        assert world.limiter.try_acquire("tiktok:acct").allowed
        assert not world.limiter.try_acquire("tiktok:acct").allowed

    def test_reregistration_starts_fresh(self, world):
        world.limiter.set_limit("youtube:acct", capacity=1, refill_per_second=1)
        assert world.limiter.try_acquire("youtube:acct").allowed
        world.limiter.set_limit("youtube:acct", capacity=1, refill_per_second=1)
        assert world.limiter.try_acquire("youtube:acct").allowed  # not inherited depletion

    def test_non_positive_limits_are_refused(self, world):
        with pytest.raises(SchemaInvalid):
            world.limiter.set_limit("k", capacity=0, refill_per_second=1)
        with pytest.raises(SchemaInvalid):
            world.limiter.set_limit("k", capacity=1, refill_per_second=0)

    def test_non_positive_cost_is_refused(self, world):
        with pytest.raises(SchemaInvalid):
            world.limiter.try_acquire("k", cost=0)


class TestKeys:
    def test_key_is_provider_then_account(self):
        assert limiter_key("youtube", "acct:main") == "youtube:acct:main"

    def test_default_bucket_serves_unregistered_keys(self, world):
        # The unregistered default is small but usable; a deployment that
        # forgets to register a key still throttles instead of erroring.
        for _ in range(10):
            assert world.limiter.try_acquire("unknown:acct").allowed
        assert not world.limiter.try_acquire("unknown:acct").allowed
