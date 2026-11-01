"""Migration 0024: the season-to-owner relation and its conservative backfill.

Only a season whose own row names the UNIQUE human Gate 1 APPROVE for that season
is assigned; a proposed season and a season with two candidate approvals stay
unassigned (hidden from every owner until an audited assignment). The table is
append-only, and a backfill-sourced link must cite the season's own approval
whose actor is the linked owner.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

from microdrama.contracts.hashing import canonical_hash
from microdrama.persistence import Database, migrate
from microdrama.persistence.db import insert_row
from microdrama.testing.seed import (
    link_season_owner,
    seed_gate1_approval,
    seed_human_session,
    seed_owner,
)

pytestmark = pytest.mark.db


def _fresh_db(server_dsn: str) -> str:
    name = f"md_owner_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(server_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    return psycopg.conninfo.make_conninfo(server_dsn, dbname=name)


def _season_row(tx, season_id: uuid.UUID, *, state: str, approval_id, scope_hash: str) -> None:
    approved = approval_id is not None
    insert_row(
        tx,
        "seasons",
        {
            "id": season_id,
            "state": state,
            "title_th": f"ฤดูกาล {season_id.hex[:6]}",
            "title_en": f"Season {season_id.hex[:6]}",
            "approved_scope_version": 1 if approved else None,
            "approved_scope_hash": scope_hash if approved else None,
            "approval_event_id": approval_id,
            "approved_at": tx.fetchval("SELECT now()") if approved else None,
        },
    )


@pytest.fixture
def backfilled(pg_server_dsn: str) -> tuple[str, dict]:
    """A 0023 database with one clean, one unapproved and one ambiguous season."""
    dsn = _fresh_db(pg_server_dsn)
    assert migrate(dsn, target="0023")[-1] == "0023"
    ids: dict[str, uuid.UUID] = {}
    with Database(dsn) as db, db.transaction() as tx:
        owner_a = seed_owner(tx, username="owner-alpha")
        owner_b = seed_owner(tx, username="owner-beta")
        ids["owner_a"], ids["owner_b"] = owner_a, owner_b

        # Clean: the season row names its only human Gate 1 APPROVE (actor A).
        ids["clean"] = uuid.uuid4()
        clean_scope = canonical_hash({"season": "clean"})
        ids["clean_approval"] = seed_gate1_approval(tx, ids["clean"], clean_scope, owner_id=owner_a)
        _season_row(
            tx,
            ids["clean"],
            state="SEASON_APPROVED",
            approval_id=ids["clean_approval"],
            scope_hash=clean_scope,
        )

        # Unapproved: no approval event at all.
        ids["proposed"] = uuid.uuid4()
        _season_row(tx, ids["proposed"], state="PROPOSED", approval_id=None, scope_hash="0" * 64)

        # Ambiguous: two SEASON_CONCEPT APPROVE events for the same season.
        ids["ambiguous"] = uuid.uuid4()
        ambiguous_scope = canonical_hash({"season": "ambiguous"})
        ids["ambiguous_approval"] = seed_gate1_approval(
            tx, ids["ambiguous"], ambiguous_scope, owner_id=owner_b
        )
        second_session = seed_human_session(tx, owner_b)
        insert_row(
            tx,
            "approval_events",
            {
                "id": uuid.uuid4(),
                "gate_type": "SEASON_CONCEPT",
                "action": "APPROVE",
                "entity_type": "season",
                "entity_id": ids["ambiguous"],
                "expected_revision": 1,
                "package_hash": ambiguous_scope,
                "actor_owner_id": owner_b,
                "actor_session_id": second_session,
                "idempotency_key": f"second-{uuid.uuid4().hex}",
                "command_hash": canonical_hash({"season": "ambiguous", "second": True}),
            },
        )
        _season_row(
            tx,
            ids["ambiguous"],
            state="SEASON_APPROVED",
            approval_id=ids["ambiguous_approval"],
            scope_hash=ambiguous_scope,
        )
    assert migrate(dsn) == ["0024"]
    return dsn, ids


def test_backfill_assigns_only_uniquely_verified_seasons(backfilled) -> None:
    dsn, ids = backfilled
    with Database(dsn) as db, db.transaction(readonly=True) as tx:
        rows = {row["season_id"]: row for row in tx.fetchall("SELECT * FROM season_owners")}
    assert set(rows) == {ids["clean"]}
    linked = rows[ids["clean"]]
    assert linked["owner_id"] == ids["owner_a"]
    assert linked["source"] == "GATE1_APPROVAL_BACKFILL"
    assert linked["approval_event_id"] == ids["clean_approval"]
    # The proposed and the ambiguous season stay unassigned — hidden until audited.
    del dsn


def test_the_relation_is_append_only(backfilled) -> None:
    dsn, ids = backfilled
    with psycopg.connect(dsn) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    "UPDATE season_owners SET owner_id = %s WHERE season_id = %s",
                    (ids["owner_b"], ids["clean"]),
                )
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute("DELETE FROM season_owners")
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute("TRUNCATE season_owners")


def test_provenance_of_a_backfill_link_is_enforced(backfilled) -> None:
    dsn, ids = backfilled
    with psycopg.connect(dsn) as conn:
        # Citing another season's approval does not prove this season's owner.
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO season_owners (season_id, owner_id, source, approval_event_id) "
                    "VALUES (%s, %s, 'GATE1_APPROVAL_BACKFILL', %s)",
                    (ids["proposed"], ids["owner_a"], ids["clean_approval"]),
                )
        # The backfill source must cite an approval event at all.
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO season_owners (season_id, owner_id, source) "
                    "VALUES (%s, %s, 'GATE1_APPROVAL_BACKFILL')",
                    (ids["proposed"], ids["owner_a"]),
                )
        # An actor that is not a human owner row cannot claim a season.
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO season_owners (season_id, owner_id, source) "
                    "VALUES (%s, %s, 'AUDITED_ASSIGNMENT')",
                    (ids["proposed"], uuid.uuid4()),
                )


def test_creator_and_audited_links_are_the_unapproved_paths(backfilled) -> None:
    dsn, ids = backfilled
    with Database(dsn) as db, db.transaction() as tx:
        link_season_owner(tx, ids["proposed"], ids["owner_a"])  # CREATOR_AT_CREATION
        link_season_owner(tx, ids["ambiguous"], ids["owner_b"], source="AUDITED_ASSIGNMENT")
        rows = {row["season_id"]: row for row in tx.fetchall("SELECT * FROM season_owners")}
    assert rows[ids["proposed"]]["source"] == "CREATOR_AT_CREATION"
    assert rows[ids["ambiguous"]]["owner_id"] == ids["owner_b"]
    assert rows[ids["ambiguous"]]["approval_event_id"] is None
