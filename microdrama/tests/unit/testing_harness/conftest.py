"""Fixtures for the T007 fake-provider harness unit tests (offline, deterministic)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from microdrama.testing.fakes import FakeClock, SequentialIds
from microdrama.testing.media import FixtureTruthRegistry, seeded_defect_suite

T0 = datetime(2026, 10, 20, tzinfo=UTC)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(T0)


@pytest.fixture
def ids() -> SequentialIds:
    return SequentialIds("unit")


@pytest.fixture(scope="session")
def defect_suite(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[dict, FixtureTruthRegistry]]:
    """The seeded defect suite, generated once per session into a private temp dir."""
    registry = FixtureTruthRegistry()
    root: Path = tmp_path_factory.mktemp("seeded-suite")
    yield seeded_defect_suite(root, registry), registry
