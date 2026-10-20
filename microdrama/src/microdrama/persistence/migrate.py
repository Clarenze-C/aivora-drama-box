"""Ordered SQL migration runner (integrator-owned).

- Files ``migrations/NNNN_name.sql`` apply in numeric order, each in its own
  transaction, recorded in ``schema_migrations`` with a SHA-256 checksum.
- An applied migration whose file later changes is refused (no silent drift).
- A transaction-scoped advisory lock serializes concurrent migrators.
- Never point this at an unrelated live database: it is for the isolated
  microdrama database only.

CLI: ``python -m microdrama.persistence.migrate <database-url> [--status]``
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"
_ADVISORY_KEY = 0x6D6472616D61  # "mdrama"
_NAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path
    checksum: str

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")


class MigrationError(RuntimeError):
    pass


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    found: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        match = _NAME.match(path.name)
        if not match:
            raise MigrationError(f"bad migration file name: {path.name}")
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        found.append(Migration(match.group(1), match.group(2), path, checksum))
    versions = [m.version for m in found]
    if len(set(versions)) != len(versions):
        raise MigrationError("duplicate migration version numbers")
    return found


def _ensure_table(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version     text PRIMARY KEY,
          name        text NOT NULL,
          checksum    text NOT NULL,
          applied_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def applied(conn: psycopg.Connection) -> dict[str, str]:
    _ensure_table(conn)
    rows = conn.execute(
        "SELECT version, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def migrate(dsn: str, *, directory: Path = MIGRATIONS_DIR, target: str | None = None) -> list[str]:
    """Apply pending migrations up to ``target`` (inclusive). Returns versions applied."""
    migrations = discover(directory)
    done: list[str] = []
    with psycopg.connect(dsn, autocommit=False) as conn:
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (_ADVISORY_KEY,))
            _ensure_table(conn)
        for migration in migrations:
            if target is not None and migration.version > target:
                break
            with conn.transaction():
                conn.execute("SELECT pg_advisory_xact_lock(%s)", (_ADVISORY_KEY,))
                existing = applied(conn)
                if migration.version in existing:
                    if existing[migration.version] != migration.checksum:
                        raise MigrationError(
                            f"migration {migration.version}_{migration.name} changed after it was applied"
                        )
                    continue
                conn.execute(migration.sql)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, checksum) VALUES (%s, %s, %s)",
                    (migration.version, migration.name, migration.checksum),
                )
                done.append(migration.version)
        # Verify no applied migration is unknown to this code base.
        unknown = set(applied(conn)) - {m.version for m in migrations}
        conn.commit()
    if unknown:
        raise MigrationError(f"database has migrations unknown to this code: {sorted(unknown)}")
    return done


def status(dsn: str, *, directory: Path = MIGRATIONS_DIR) -> list[tuple[str, str, str]]:
    """(version, name, APPLIED|PENDING|CHANGED) for every known migration."""
    migrations = discover(directory)
    with psycopg.connect(dsn, autocommit=True) as conn:
        existing = applied(conn)
    out = []
    for m in migrations:
        if m.version not in existing:
            state = "PENDING"
        elif existing[m.version] != m.checksum:
            state = "CHANGED"
        else:
            state = "APPLIED"
        out.append((m.version, m.name, state))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply microdrama migrations")
    parser.add_argument("database_url")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args(argv)
    if args.status:
        for version, name, state in status(args.database_url):
            print(f"{version} {name}: {state}")
        return 0
    applied_now = migrate(args.database_url)
    print(f"applied: {applied_now or 'nothing (up to date)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
