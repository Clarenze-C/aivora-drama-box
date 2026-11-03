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

    root = tmp_path / "canary-pg"
    # The same ownership code up() runs: the parent becomes 0755 (traversable by the
    # postgres OS user), the root/data dir are the server user's own 0700.
    canary_db._prepare_durable_root(root)
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
