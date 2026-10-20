"""Fresh create, upgrade, restart round trip and drift protection (T003)."""

from __future__ import annotations

import shutil
import tempfile
import threading
import uuid
from pathlib import Path

import psycopg
import pytest

from microdrama.contracts.examples import asset_descriptor
from microdrama.persistence import (
    Database,
    FilesystemObjectStore,
    get_asset,
    migrate,
    register_asset,
    status,
)
from microdrama.persistence.migrate import MIGRATIONS_DIR, MigrationError, discover
from microdrama.testing.seed import seed_episode, seed_season
from microdrama.testing.services import EphemeralPostgres

pytestmark = pytest.mark.db

EXPECTED_TABLES = {
    "owners",
    "human_sessions",
    "service_credentials",
    "jobs",
    "aggregate_sequences",
    "domain_events",
    "event_dispatches",
    "event_consumptions",
    "idempotency_records",
    "provider_operations",
    "webhook_events",
    "manual_interventions",
    "seasons",
    "season_proposals",
    "canon_versions",
    "episodes",
    "scripts",
    "shot_manifests",
    "characters",
    "voices",
    "reference_versions",
    "approval_events",
    "feedback_events",
    "identity_locks",
    "identity_lock_assets",
    "preference_rules",
    "budget_accounts",
    "budget_category_allocations",
    "budget_transfers",
    "reservations",
    "charges",
    "cost_allocations",
    "cost_overruns",
    "pod_leases",
    "pod_usage_intervals",
    "assets",
    "asset_lineage",
    "edit_manifests",
    "caption_tracks",
    "hook_experiments",
    "hook_exposures",
    "qa_observations",
    "qa_findings",
    "repair_plans",
    "release_packages",
    "platform_posts",
    "metadata_versions",
    "community_events",
    "management_actions",
    "membership_catalog",
    "entitlement_links",
    "performance_snapshots",
    "qualification_runs",
    "credential_refs",
    "capability_registry",
    "rights_registry",
    "preset_registry",
    "policy_versions",
    "schema_migrations",
}


def _tables(dsn: str) -> set[str]:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ).fetchall()
    return {r[0] for r in rows}


def _fresh_db(server_dsn: str) -> str:
    name = f"md_mig_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(server_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    return psycopg.conninfo.make_conninfo(server_dsn, dbname=name)


def test_fresh_create_has_every_entity_group(pg_server_dsn: str) -> None:
    dsn = _fresh_db(pg_server_dsn)
    assert migrate(dsn) == [m.version for m in discover()]
    assert EXPECTED_TABLES <= _tables(dsn)
    assert all(state == "APPLIED" for _, _, state in status(dsn))
    assert migrate(dsn) == []  # idempotent re-run


def test_upgrade_preserves_existing_data(pg_server_dsn: str) -> None:
    dsn = _fresh_db(pg_server_dsn)
    assert migrate(dsn, target="0002") == ["0001", "0002"]
    with Database(dsn) as db, db.transaction() as tx:
        season_id = seed_season(tx)
        episode_id = seed_episode(tx, season_id)
    assert migrate(dsn) == [m.version for m in discover() if m.version > "0002"]
    with Database(dsn) as db, db.transaction() as tx:
        assert (
            tx.fetchval("SELECT season_id FROM episodes WHERE id = %s", (episode_id,)) == season_id
        )
        tx.execute(
            "INSERT INTO budget_accounts (id, scope_kind, season_id, episode_id, cap_micro_usd) "
            "VALUES (%s, 'EPISODE', %s, %s, 10000000)",
            (uuid.uuid4(), season_id, episode_id),
        )


def test_restart_round_trip_keeps_rows_assets_and_hashes(tmp_path: Path) -> None:
    # The server data dir must be traversable by the postgres OS user, so it lives in
    # its own mkdtemp directory rather than pytest's root-only tmp_path.
    pg_root = Path(tempfile.mkdtemp(prefix="microdrama-pg-restart-"))
    server = EphemeralPostgres(root=pg_root, keep=True)
    dsn = server.start()
    try:
        migrate(dsn)
        store_root = tmp_path / "objects"
        store = FilesystemObjectStore(store_root)
        descriptor = asset_descriptor()
        stored = store.put_bytes(descriptor.object_key, b"fake media bytes", media_type="video/mp4")
        descriptor = descriptor.model_copy(
            update={"sha256": stored.sha256, "size_bytes": stored.size_bytes}
        )
        with Database(dsn) as db, db.transaction() as tx:
            season_id = seed_season(tx)
            episode_id = seed_episode(tx, season_id)
            descriptor = descriptor.model_copy(update={"episode_id": episode_id, "lineage": []})
            register_asset(tx, descriptor)
    finally:
        server.stop()  # keep=True: data directory survives

    restarted = EphemeralPostgres(root=pg_root, port=server.port, keep=False)
    dsn = restarted.start()
    try:
        assert migrate(dsn) == []
        new_store = FilesystemObjectStore(store_root)  # new process-equivalent instance
        with Database(dsn) as db, db.transaction() as tx:
            again = get_asset(tx, descriptor.asset_id)
        assert again == descriptor
        assert new_store.verify(again.object_key, again.sha256)
        assert new_store.get_bytes(again.object_key) == b"fake media bytes"
    finally:
        restarted.stop()


def test_changed_applied_migration_is_refused(pg_server_dsn: str, tmp_path: Path) -> None:
    copy = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS_DIR, copy)
    dsn = _fresh_db(pg_server_dsn)
    migrate(dsn, directory=copy)
    target = copy / "0006_registries.sql"
    target.write_text(target.read_text() + "\n-- edited after apply\n")
    with pytest.raises(MigrationError):
        migrate(dsn, directory=copy)
    assert ("0006", "registries", "CHANGED") in status(dsn, directory=copy)


def test_concurrent_migrators_apply_each_version_once(pg_server_dsn: str) -> None:
    dsn = _fresh_db(pg_server_dsn)
    results: list[list[str]] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            results.append(migrate(dsn))
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not errors
    applied = sorted(v for r in results for v in r)
    assert applied == [m.version for m in discover()]
