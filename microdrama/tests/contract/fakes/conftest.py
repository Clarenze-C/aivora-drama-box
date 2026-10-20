"""Fixtures for the T007 fake contract tests (offline; media generated into temp dirs)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from microdrama.testing.media import FixtureTruthRegistry, seeded_defect_suite


@pytest.fixture(scope="session")
def defect_suite(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[dict, FixtureTruthRegistry]]:
    """The seeded defect suite, generated once per session into a private temp dir."""
    registry = FixtureTruthRegistry()
    yield seeded_defect_suite(tmp_path_factory.mktemp("contract-suite"), registry), registry
