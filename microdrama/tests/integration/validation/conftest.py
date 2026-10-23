"""T030 validator fixtures (independent cross-system validation).

``validation_world`` builds a fresh composed world per test: every fault
injection below drives the REAL composed services (``build_pipeline_world``),
never a module-local re-implementation, and the offline network guard stays
active (autouse from ``tests/conftest.py``).

``pilot`` is ONE completed two-gate mock run (the ``make pilot`` path) on a
dedicated database, shared by the assertions that need a finished episode —
Gate 2 replay, hooks, membership truth, qualification. Tests may only attempt
mutations the system must DENY; if one is granted that is a finding and the
suite fails right there.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode
from microdrama.persistence import Database
from microdrama.pipeline.runner import MockPipelineRunner
from microdrama.pipeline.world import PipelineWorld, build_pipeline_world


@pytest.fixture
def validation_world(db: Database, tmp_path, offline_settings: Settings):
    """A fresh composed world for fault injection (own database per test)."""
    return build_pipeline_world(offline_settings, db)


@pytest.fixture
def qa_world(db: Database, tmp_path, offline_settings: Settings, fixture_truth):
    """A composed world whose observer reads the session defect-suite truth
    registry, so seeded-defect media observes its real contents."""
    return build_pipeline_world(offline_settings, db, truth=fixture_truth)


@pytest.fixture(scope="session")
def pilot(
    pg_server_dsn: str, migrated_template_dsn: str, tmp_path_factory
) -> Iterator[tuple[PipelineWorld, object]]:
    """One completed two-gate mock run, shared read-mostly by the suite.

    Runs the exact ``make pilot`` sequence once (real FFmpeg assembly, fake
    providers) and yields ``(world, report)``. Attempted mutations on this world
    must be denials — the assertions say so explicitly.
    """
    template = psycopg.conninfo.conninfo_to_dict(migrated_template_dsn)["dbname"]
    name = f"md_t030_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(pg_server_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}" TEMPLATE "{template}"')
    dsn = make_conninfo(pg_server_dsn, dbname=name)
    root = tmp_path_factory.mktemp("t030-pilot")
    settings = Settings(
        execution_mode=ExecutionMode.OFFLINE_MOCK, object_store_root=root / "objects"
    )
    database = Database(dsn, min_size=1, max_size=20).open()
    try:
        world = build_pipeline_world(settings, database)
        report = MockPipelineRunner(world).run()
        yield world, report
    finally:
        database.close()
        with psycopg.connect(pg_server_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
