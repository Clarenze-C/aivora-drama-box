"""T045-FIX B-S8/B-N5: the canary database tool's durable mode and down guard.

No real cluster is started here: the durable settings are checked from the
generated pg_ctl options, and down() is checked with subprocess and paths stubbed.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))

import canary_db  # noqa: E402

# T045-FIX F-6: no module-wide db mark - only the tests that request the ``db``
# fixture carry pytest.mark.db; the rest are pure unit tests over the tool module.


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
    # T045-FIX O-2: the traversal check does not apply to this composition test
    # (the server is faked); as a non-root caller up() just creates the root.
    monkeypatch.setattr(canary_db.os, "geteuid", lambda: 1000)

    def _fake_seed(dsn: str) -> None:
        return None

    monkeypatch.setattr(canary_db, "_seed", _fake_seed)
    rc = canary_db.up(data_root=tmp_path / "canary-pg")
    assert rc == 0
    assert created["durable"] is True
    assert created["keep"] is True
    assert created["root"] == tmp_path / "canary-pg"


# --- T045-FIX RR-N2: down honours the data root up was given --------------------------------


def test_down_accepts_the_data_root_up_was_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "custom-root"
    (root / "data").mkdir(parents=True)
    state = tmp_path / "canary-db.json"
    state.write_text(
        json.dumps(
            {
                "dsn": "x",
                "port": 1,
                "root": str(root),
                "data_root": str(root),
                "started_at": "x",
            }
        )
    )
    monkeypatch.setattr(canary_db, "STATE_PATH", state)
    commands: list[list[str]] = []
    monkeypatch.setattr(canary_db.subprocess, "run", lambda cmd, **k: commands.append(cmd))
    monkeypatch.setattr(canary_db.os, "geteuid", lambda: 1000)
    assert canary_db.down(data_root=root) == 0
    assert commands and "-m" in commands[0]


def test_down_refuses_a_tampered_state_file_pointing_elsewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "custom-root"
    (root / "data").mkdir(parents=True)
    state = tmp_path / "canary-db.json"
    state.write_text(
        json.dumps(
            {
                "dsn": "x",
                "port": 1,
                "root": str(tmp_path / "evil"),  # tampered: not the recorded root
                "data_root": str(root),
                "started_at": "x",
            }
        )
    )
    monkeypatch.setattr(canary_db, "STATE_PATH", state)
    stopped: list[list[str]] = []
    monkeypatch.setattr(canary_db.subprocess, "run", lambda *a, **k: stopped.append(a[0]))
    assert canary_db.down(data_root=root) == 1
    assert stopped == []
    assert state.exists()


# --- T045-FIX RR-S2/O-2: a data root the server OS user can traverse -----------------------


def test_an_untraversable_existing_ancestor_is_refused_with_its_mode_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """T045-FIX O-2: a directory that already existed is never chmod'ed. A 0700
    ancestor (an operator home, /tmp/pytest-of-root on a stock host) makes the
    preparation refuse with exit 2, name the directory and the fix - creating
    nothing, changing no mode."""
    import os as _os
    import stat as _stat

    assert canary_db.DEFAULT_DATA_ROOT == Path("/var/lib/microdrama/canary-pg")
    root = tmp_path / "deep" / "canary-pg"
    _os.chmod(tmp_path, 0o700)
    with pytest.raises(SystemExit) as exc:
        canary_db._prepare_durable_root(root)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert str(tmp_path) in err and "chmod 0755" in err
    # Nothing was created and no mode changed.
    assert not root.exists() and not root.parent.exists()
    assert _stat.S_IMODE(_os.stat(tmp_path).st_mode) == 0o700


def test_directories_the_tool_creates_are_0755_and_nothing_existing_widens(
    tmp_path: Path,
) -> None:
    """T045-FIX O-2: below the deepest existing ancestor the tool creates the chain
    itself, 0755 - and a traversable pre-existing parent keeps its exact mode."""
    import os as _os
    import stat as _stat
    import tempfile

    # The test's own traversable parent (it may not widen tmp_path, which pytest
    # made 0700 and the test did not create).
    parent = Path(tempfile.mkdtemp())
    parent.chmod(0o755)
    root = parent / "deep" / "canary-pg"
    canary_db._prepare_durable_root(root)
    assert root.is_dir()
    assert _stat.S_IMODE(_os.stat(root.parent).st_mode) == 0o755
    assert _stat.S_IMODE(_os.stat(root).st_mode) == 0o755
    assert _stat.S_IMODE(_os.stat(parent).st_mode) == 0o755  # untouched, as created


def test_the_default_var_lib_chain_is_already_traversable() -> None:
    """T045-FIX O-2: the default /var/lib/microdrama/canary-pg needs no widening -
    /var and /var/lib are 0755 on a stock host, so the ancestor check passes."""
    import stat as _stat

    for ancestor in (Path("/"), Path("/var"), Path("/var/lib")):
        assert _stat.S_IMODE(ancestor.stat().st_mode) & 0o055 == 0o055, ancestor


# --- T045-FIX RR-S3: up is re-runnable on the data it keeps --------------------------------


def _fake_server_factory(tmp_path: Path, dsn: str) -> tuple[type, dict[str, list[str]]]:
    events: dict[str, list[str]] = {"starts": [], "stops": []}

    class _FakeServer:
        port = 5998
        root = tmp_path / "canary-pg"

        def __init__(self, **kwargs: object) -> None:
            del kwargs

        def start(self) -> str:
            events["starts"].append(dsn)
            return dsn

        def stop(self) -> None:
            events["stops"].append(dsn)

    return _FakeServer, events


@pytest.mark.db
def test_up_down_up_leaves_one_episode_and_a_valid_state_file(
    db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RR-S3: after down keeps the data, the next up seeds NOTHING new - exactly one
    canary episode with its budget account remains and the state file is valid."""
    import microdrama.testing.services as services
    from microdrama.pipeline.canary_authorization import CANARY_EPISODE_ID

    fake, _events = _fake_server_factory(tmp_path, db.dsn)
    monkeypatch.setattr(services, "EphemeralPostgres", fake)
    monkeypatch.setattr("microdrama.testing.services.EphemeralPostgres", fake)
    state = tmp_path / "canary-db.json"
    monkeypatch.setattr(canary_db, "STATE_PATH", state)
    stopped: list[list[str]] = []
    monkeypatch.setattr(canary_db.subprocess, "run", lambda cmd, **k: stopped.append(cmd))
    monkeypatch.setattr(canary_db.os, "geteuid", lambda: 1000)
    assert canary_db.up(data_root=tmp_path / "canary-pg") == 0
    assert canary_db.down(data_root=tmp_path / "canary-pg") == 0
    assert canary_db.up(data_root=tmp_path / "canary-pg") == 0
    with db.transaction(readonly=True) as tx:
        episodes = tx.fetchval(
            "SELECT count(*) FROM episodes e JOIN budget_accounts a "
            "ON a.episode_id = e.id AND a.scope_kind='EPISODE' WHERE e.id=%s",
            (uuid.UUID(CANARY_EPISODE_ID),),
        )
    assert episodes == 1
    recorded = json.loads(state.read_text())
    assert recorded["dsn"] == db.dsn
    assert Path(recorded["data_root"]) == tmp_path / "canary-pg"


@pytest.mark.db
def test_an_injected_seed_failure_leaves_no_running_server(
    db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RR-S3: a failure after the server starts stops the server - a running cluster
    without a state file is impossible."""
    import microdrama.testing.services as services

    def _boom(_dsn: str) -> None:
        raise RuntimeError("fixture: seed exploded")

    fake, events = _fake_server_factory(tmp_path, db.dsn)
    monkeypatch.setattr(services, "EphemeralPostgres", fake)
    monkeypatch.setattr("microdrama.testing.services.EphemeralPostgres", fake)
    monkeypatch.setattr(canary_db, "STATE_PATH", tmp_path / "canary-db.json")
    # T045-FIX O-2: non-root caller (the server lifecycle is faked here; the
    # traversal refusal is covered by the O-2 tests above).
    monkeypatch.setattr(canary_db.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(canary_db, "_seed", _boom)
    with pytest.raises(RuntimeError, match="seed exploded"):
        canary_db.up(data_root=tmp_path / "canary-pg")
    assert events["stops"], "the started server must be stopped on a seed failure"
    assert not (tmp_path / "canary-db.json").exists()
