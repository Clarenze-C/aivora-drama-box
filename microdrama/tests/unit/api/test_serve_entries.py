"""T046 staging entry units: the offline-mode guard and restart-idempotent seeding."""

from __future__ import annotations

import pytest


def test_serve_refuses_non_offline_modes(monkeypatch, tmp_path):
    from microdrama.api import serve

    monkeypatch.setenv("MICRODRAMA_DATABASE_URL", "postgresql://x/y")
    monkeypatch.setenv("MICRODRAMA_OBJECT_STORE_ROOT", str(tmp_path))
    monkeypatch.setenv("MICRODRAMA_EXECUTION_MODE", "PAID_BENCHMARK")
    with pytest.raises(SystemExit) as caught:
        serve.main(["serve"])
    assert caught.value.code == 2


def test_worker_refuses_non_offline_modes(monkeypatch, tmp_path):
    from microdrama.api import worker

    monkeypatch.setenv("MICRODRAMA_DATABASE_URL", "postgresql://x/y")
    monkeypatch.setenv("MICRODRAMA_OBJECT_STORE_ROOT", str(tmp_path))
    monkeypatch.setenv("MICRODRAMA_EXECUTION_MODE", "PRODUCTION")
    assert worker.main([]) == 2


def test_worker_requires_dsn(monkeypatch, tmp_path):
    from microdrama.api import worker

    monkeypatch.delenv("MICRODRAMA_DATABASE_URL", raising=False)
    monkeypatch.setenv("MICRODRAMA_OBJECT_STORE_ROOT", str(tmp_path))
    assert worker.main(["--once"]) == 2


@pytest.mark.db
def test_world_build_is_restart_idempotent(db, offline_settings):
    """A durable deployment boots twice against the same database (T046).

    The second build must not attempt to re-record the version-1 mock preset
    catalog (which would Conflict) — the registry-seeding guard skips seeding
    when the mock presets are already present.
    """
    from microdrama.core.clock import SystemClock
    from microdrama.pipeline.world import build_pipeline_world

    first = build_pipeline_world(offline_settings, db)
    del first
    second = build_pipeline_world(offline_settings, db, clock=SystemClock())
    with second.db.transaction(readonly=True) as tx:
        presets = int(
            tx.fetchval("SELECT count(*) FROM preset_registry WHERE preset_id LIKE 'fake-%'") or 0
        )
    assert presets > 0, "fresh databases still get the mock catalog exactly once"
