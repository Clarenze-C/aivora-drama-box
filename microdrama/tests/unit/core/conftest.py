"""Fixtures for the core tests (T004): deterministic clock and ids, the real database handle."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from microdrama.testing.fakes import FakeClock, SequentialIds


@pytest.fixture
def clock() -> FakeClock:
    """Deterministic clock anchored at the current instant (DB-side checks use server time)."""
    return FakeClock(datetime.now(UTC).replace(microsecond=0))


@pytest.fixture
def ids() -> SequentialIds:
    return SequentialIds("core-tests")
