"""T045-FIX RR-S2: the durable canary cluster REALLY starts under a traversable root.

Unlike the mocked tests in tests/unit/pipeline/test_t045_canary_db.py, this starts a
real local loopback PostgreSQL (never ports 8091/8093, never a container) under a
test-owned root prepared by the same ownership code ``canary_db up`` uses, and checks
the durability settings from the live server. Allowed: it is a loopback test PG, the
same thing every db-marked test here runs.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))

import canary_db  # noqa: E402

pytestmark = pytest.mark.db


def test_the_durable_cluster_runs_with_fsync_synchronous_commit_and_full_page_writes(
    tmp_path: Path,
) -> None:
    import psycopg

    from microdrama.testing.services import EphemeralPostgres

    # T045-FIX O-2: the test builds its own traversable parent - a directory IT
    # creates and sets to 0755 - under tmp_path's chain only when that chain is
    # already traversable; otherwise a fresh mkdtemp it also sets to 0755. Either
    # way it widens no directory it did not create.
    def traversable_chain(start: Path) -> bool:
        node = start
        while True:
            if stat.S_IMODE(node.stat().st_mode) & 0o055 != 0o055:
                return False
            if node.parent == node:
                return True
            node = node.parent

    if traversable_chain(tmp_path):
        parent = tmp_path / "traversable-parent"
        parent.mkdir()
    else:
        import tempfile

        parent = Path(tempfile.mkdtemp())
    parent.chmod(0o755)
    tmp_mode_before = stat.S_IMODE(tmp_path.stat().st_mode)
    root = parent / "canary-pg"
    # The same ownership code up() runs: the tool creates the chain below the
    # deepest existing ancestor 0755 (traversable by the postgres OS user); the
    # root/data dir are the server user's own 0700.
    canary_db._prepare_durable_root(root)
    assert stat.S_IMODE(tmp_path.stat().st_mode) == tmp_mode_before  # O-2: no widening
    server = EphemeralPostgres(keep=True, durable=True, root=root)
    assert server.port not in canary_db.FORBIDDEN_PORTS
    try:
        dsn = server.start()
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT current_setting('fsync'), "
                    "current_setting('synchronous_commit'), "
                    "current_setting('full_page_writes')"
                )
                fsync, sync_commit, full_page = cur.fetchone()
        assert (fsync, sync_commit, full_page) == ("on", "on", "on")
        # The ownership the ruling demands: data dir 0700, owned by the server user.
        data_mode = stat.S_IMODE(root.joinpath("data").stat().st_mode)
        assert data_mode == 0o700
        if sys.platform == "linux":  # pragma: no branch
            import pwd

            pg_user = pwd.getpwnam("postgres")
            data_stat = root.joinpath("data").stat()
            assert data_stat.st_uid == pg_user.pw_uid
    finally:
        server.stop()
    # keep=True: the data survives the stop (it is the canary's only ledger).
    assert (root / "data" / "PG_VERSION").exists()


def test_up_down_up_restarts_on_the_server_owned_0700_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T045-FIX CR-1: the REAL kept-data restart shape. A real ``up`` leaves the
    data root itself 0700 and owned by the ``postgres`` OS user
    (``EphemeralPostgres.start`` does the chown/chmod); ``down`` keeps it. The
    next ``up`` must restart on that kept data: the traversal check ends at the
    data root's PARENT - the server-owned 0700 root is its correct state and is
    never in the checked chain. No faked server lifecycle and no geteuid patch:
    this is the restart an operator gets after a real up/down."""
    import os as _os
    import stat as _stat
    import tempfile

    def traversable_chain(start: Path) -> bool:
        node = start
        while True:
            if _stat.S_IMODE(node.stat().st_mode) & 0o055 != 0o055:
                return False
            if node.parent == node:
                return True
            node = node.parent

    # The test's own traversable parent (it may not widen tmp_path, which pytest
    # may have left under a 0700 chain the test did not create).
    if traversable_chain(tmp_path):
        parent = tmp_path / "traversable-parent"
        parent.mkdir()
    else:
        parent = Path(tempfile.mkdtemp())
    parent.chmod(0o755)
    root = parent / "canary-pg"
    state = tmp_path / "canary-db.json"
    monkeypatch.setattr(canary_db, "STATE_PATH", state)
    try:
        assert canary_db.up(data_root=root) == 0
        # The real shape the restart must survive: the data root itself 0700,
        # owned by the server's OS user when the tool runs as root (checked, not
        # faked - the suite runs as root on the operator host).
        import pwd

        root_stat = root.stat()
        assert _stat.S_IMODE(root_stat.st_mode) == 0o700
        if _os.geteuid() == 0:  # pragma: no branch - the operator host runs as root
            pg_user = pwd.getpwnam("postgres")
            assert root_stat.st_uid == pg_user.pw_uid
        assert canary_db.down(data_root=root) == 0
        assert (root / "data" / "PG_VERSION").exists()  # the data is kept
        # The kept root is still the server's own 0700 when the restart begins.
        kept = root.stat()
        assert _stat.S_IMODE(kept.st_mode) == 0o700
        assert canary_db.up(data_root=root) == 0  # CR-1: the restart passes
        assert canary_db.status() == 0  # ...and the kept cluster answers
    finally:
        canary_db.down(data_root=root)
