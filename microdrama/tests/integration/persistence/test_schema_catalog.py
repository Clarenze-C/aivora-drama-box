"""Schema-wide guarantees, checked against the live catalog (so future tables are covered).

Every public table must (a) refuse row DELETE (unless it is the runtime-mode singleton,
which has its own guard), (b) refuse TRUNCATE, and (c) refuse non-integer numbers anywhere
in a row, except the explicitly exempt tables. A new migration that adds a table without
these guards fails here.
"""

from __future__ import annotations

import pytest

from microdrama.persistence import Database

pytestmark = pytest.mark.db

TRIGGER_BEFORE, TRIGGER_INSERT, TRIGGER_DELETE, TRIGGER_UPDATE, TRIGGER_TRUNCATE = 2, 4, 8, 16, 32
DELETE_GUARDS = {"md_forbid_mutation", "md_runtime_mode_change_guard"}
INTEGER_EXEMPT = {"policy_versions", "schema_migrations", "md_runtime_mode"}


def _catalog(db: Database) -> tuple[set[str], list[dict]]:
    with db.transaction() as tx:
        tables = {
            r["relname"]
            for r in tx.fetchall(
                "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind = 'r'"
            )
        }
        triggers = tx.fetchall(
            "SELECT c.relname, t.tgname, t.tgtype::int AS tgtype, p.proname, t.tgenabled "
            "FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace JOIN pg_proc p ON p.oid = t.tgfoid "
            "WHERE n.nspname = 'public' AND NOT t.tgisinternal"
        )
    return tables, triggers


def _has(triggers: list[dict], table: str, bit: int, functions: set[str]) -> bool:
    return any(
        t["relname"] == table
        and t["tgtype"] & TRIGGER_BEFORE
        and t["tgtype"] & bit
        and t["proname"] in functions
        and t["tgenabled"] in ("O", "A")  # replica-only ('R') or disabled ('D') guards do not count
        for t in triggers
    )


def test_every_table_refuses_delete(db: Database) -> None:
    tables, triggers = _catalog(db)
    missing = sorted(t for t in tables if not _has(triggers, t, TRIGGER_DELETE, DELETE_GUARDS))
    assert missing == []


def test_every_table_refuses_truncate(db: Database) -> None:
    tables, triggers = _catalog(db)
    missing = sorted(
        t for t in tables if not _has(triggers, t, TRIGGER_TRUNCATE, {"md_forbid_mutation"})
    )
    assert missing == []


def test_every_table_refuses_non_integer_numbers(db: Database) -> None:
    tables, triggers = _catalog(db)
    guard = {"md_forbid_non_integer_numbers"}
    missing = sorted(
        t
        for t in tables - INTEGER_EXEMPT
        if not (
            _has(triggers, t, TRIGGER_INSERT, guard) and _has(triggers, t, TRIGGER_UPDATE, guard)
        )
    )
    assert missing == []
    assert len(tables) >= 60  # the catalog really was inspected


def test_no_guard_trigger_is_disabled(db: Database) -> None:
    _, triggers = _catalog(db)
    assert [t["tgname"] for t in triggers if t["tgenabled"] not in ("O", "A")] == []
