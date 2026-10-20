"""Fixtures for the budget tests (T005). Builders live in ``budget_support``."""

from __future__ import annotations

import uuid

import pytest
from budget_support import World, assert_consistent

from microdrama.persistence import Database


@pytest.fixture
def world(db: Database) -> World:
    return World(db)


@pytest.fixture
def check_consistent(db: Database):
    """Callable: ``check_consistent(account_id)`` recomputes every counter and asserts it."""

    def _check(account_id: uuid.UUID) -> dict[str, int]:
        return assert_consistent(db, account_id)

    return _check
