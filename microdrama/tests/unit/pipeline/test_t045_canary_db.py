"""T045-FIX B-S8/B-N5: the canary database tool's durable mode and down guard.

No real cluster is started here: the durable settings are checked from the
generated pg_ctl options, and down() is checked with subprocess and paths stubbed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))

import canary_db  # noqa: E402


def test_durable_mode_turns_on_fsync_synchronous_commit_and_full_page_writes() -> None:
    from microdrama.testing.services import postgres_server_opts

    opts = postgres_server_opts(durable=True).format(port=5433, root="/tmp/x")
    assert "-c fsync=on" in opts
    assert "-c synchronous_commit=on" in opts
    assert "-c full_page_writes=on" in opts
    # The throwaway test fixtures keep the fast settings.
    fast = postgres_server_opts().format(port=5433, root="/tmp/x")
    assert "-c fsync=off" in fast and "-c synchronous_commit=off" in fast


def test_down_refuses_a_state_file_pointing_outside_the_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "canary-db.json"
    state.write_text(
        json.dumps({"dsn": "x", "port": 1, "root": str(tmp_path / "evil"), "started_at": "x"})
    )
    monkeypatch.setattr(canary_db, "STATE_PATH", state)
    monkeypatch.setattr(canary_db, "DEFAULT_DATA_ROOT", tmp_path / "canary-pg")
    stopped: list[list[str]] = []
    monkeypatch.setattr(canary_db.subprocess, "run", lambda *a, **k: stopped.append(a[0]))
    rc = canary_db.down()
    assert rc == 1
    assert stopped == []  # nothing was stopped
    assert state.exists()  # the state is untouched


def test_down_uses_a_fast_shutdown_and_keeps_the_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "canary-pg"
    (root / "data").mkdir(parents=True)
    state = tmp_path / "canary-db.json"
    state.write_text(json.dumps({"dsn": "x", "port": 1, "root": str(root), "started_at": "x"}))
    monkeypatch.setattr(canary_db, "STATE_PATH", state)
    monkeypatch.setattr(canary_db, "DEFAULT_DATA_ROOT", root)
    commands: list[list[str]] = []
    monkeypatch.setattr(canary_db.subprocess, "run", lambda cmd, **k: commands.append(cmd))
    monkeypatch.setattr(canary_db.os, "geteuid", lambda: 1000)
    rc = canary_db.down()
    assert rc == 0
    assert commands and commands[0][commands[0].index("-m") + 1] == "fast"
    assert (root / "data").exists()  # the data is kept


def test_up_composes_the_durable_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """B-S8: up() asks EphemeralPostgres for a durable, stable-rooted cluster."""
    created: dict[str, object] = {}

    class _FakeServer:
        port = 5999
        root = tmp_path / "canary-pg"

        def __init__(self, **kwargs: object) -> None:
            created.update(kwargs)

        def start(self) -> str:
            return "postgresql://canary@127.0.0.1:5999/postgres"

    import microdrama.testing.services as services

    monkeypatch.setattr(services, "EphemeralPostgres", _FakeServer)
    monkeypatch.setattr("microdrama.testing.services.EphemeralPostgres", _FakeServer)
    state = tmp_path / "canary-db.json"
    monkeypatch.setattr(canary_db, "STATE_PATH", state)

    def _fake_seed(dsn: str) -> None:
        return None

    monkeypatch.setattr(canary_db, "_seed", _fake_seed)
    rc = canary_db.up(data_root=tmp_path / "canary-pg")
    assert rc == 0
    assert created["durable"] is True
    assert created["keep"] is True
    assert created["root"] == tmp_path / "canary-pg"
