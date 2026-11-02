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


# --- review fix round (2026-11-02): DB-10 first-boot seeding, DB-11 serve hardening ---


@pytest.mark.db
def test_first_boot_seed_is_atomic_when_it_fails_midway(db, offline_settings, monkeypatch):
    """DB-10: a crash mid-seed must not leave a half-seeded database.

    The old guard was read-then-seed across separate transactions: the preset
    catalog committed first, so a crash before the registries finished left a
    database the guard would then skip forever. Catalog and registries now
    seed in ONE transaction — the simulated crash rolls both back, and the
    next boot seeds completely."""
    from microdrama.pipeline import world as world_mod

    def boom(*args, **kwargs):
        raise RuntimeError("simulated crash after the catalog committed")

    monkeypatch.setattr(world_mod, "seed_mock_registries", boom)
    with pytest.raises(RuntimeError):
        world_mod.build_pipeline_world(offline_settings, db)
    with db.transaction(readonly=True) as tx:
        presets = int(
            tx.fetchval("SELECT count(*) FROM preset_registry WHERE preset_id LIKE 'fake-%'")
            or 0
        )
    assert presets == 0, "a crash mid-seed must roll the whole first boot back"

    monkeypatch.undo()
    clean = world_mod.build_pipeline_world(offline_settings, db)
    with clean.db.transaction(readonly=True) as tx:
        presets = int(
            tx.fetchval("SELECT count(*) FROM preset_registry WHERE preset_id LIKE 'fake-%'")
            or 0
        )
        rights = int(
            tx.fetchval(
                "SELECT count(*) FROM rights_registry WHERE rights_route_id = %s",
                ("mock-fake-synthetic-v1",),
            )
            or 0
        )
    assert presets > 0, "a clean retry seeds the catalog"
    assert rights > 0, "a clean retry seeds the mock rights route too"


@pytest.mark.db
def test_first_boot_seeding_holds_the_first_boot_advisory_lock(db, offline_settings, monkeypatch):
    """DB-10: check+seed run under a well-known advisory lock, so two first-boot
    processes serialize instead of interleaving their seeding."""
    from microdrama.pipeline import world as world_mod

    probes: list[bool] = []  # True when the lock was observed HELD by the seeder
    real = world_mod.seed_mock_registries

    def probing(*args, **kwargs):
        with db.transaction() as tx:  # a different session than the lock holder
            acquired = tx.fetchval(
                "SELECT pg_try_advisory_xact_lock(%s)", (world_mod.FIRST_BOOT_SEED_LOCK_KEY,)
            )
        probes.append(not acquired)  # could not acquire -> held by the seeder
        return real(*args, **kwargs)

    monkeypatch.setattr(world_mod, "seed_mock_registries", probing)
    world_mod.build_pipeline_world(offline_settings, db)
    assert probes and all(probes), "seeding runs under the first-boot advisory lock"


def test_health_fails_when_the_payload_is_not_ok(monkeypatch):
    """DB-11: a 200 response whose payload does not report status ok is a failed
    probe — the health command must check the payload, not just the status code."""
    import httpx

    from microdrama.api import serve

    class _Response:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: _Response({"status": "not-ok", "version": "x"})
    )
    assert serve._health() == 1, "a not-ok payload fails the probe"
    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: _Response({"status": "ok", "version": "x"})
    )
    assert serve._health() == 0


def test_secret_file_is_created_0600_and_never_overwritten(tmp_path):
    """DB-11: the owner password file is created with 0o600 from the first
    instant (O_CREAT|O_EXCL — no umask window, no overwrite)."""
    from microdrama.api.serve import _write_secret_file

    target = tmp_path / "owner-password.txt"
    _write_secret_file(target, "a-first-password\n")
    assert target.read_text() == "a-first-password\n"
    assert (target.stat().st_mode & 0o777) == 0o600
    with pytest.raises(FileExistsError):
        _write_secret_file(target, "a-second-password\n")
    assert target.read_text() == "a-first-password\n", "an existing file is never overwritten"
