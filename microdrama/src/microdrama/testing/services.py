"""Isolated PostgreSQL and Redis processes for tests and local exploration.

No Docker is required. Each server runs as a temporary child process bound to
127.0.0.1 on a free port, with its data directory under a private temp dir, so
it can never touch an existing AIVORA database or Redis instance.

PostgreSQL is the real server (``initdb``/``pg_ctl`` from the installed
PostgreSQL 16 binaries), so row locks, ``SELECT ... FOR UPDATE`` and
transaction isolation behave exactly as in production. Only durability knobs
(``fsync``/``synchronous_commit``/``full_page_writes``) are relaxed for speed;
they do not change locking or visibility semantics.

``initdb`` refuses to run as root; when the current user is root the server
commands run as the ``postgres`` OS account via ``runuser``.

Environment overrides:
  MICRODRAMA_TEST_DATABASE_URL  use an existing *disposable* server instead
  MICRODRAMA_TEST_REDIS_URL     use an existing *disposable* Redis instead
  MICRODRAMA_PG_BINDIR          directory holding initdb/pg_ctl
"""

from __future__ import annotations

import argparse
import contextlib
import glob
import json
import os
import pwd
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

PG_SUPERUSER = "microdrama"
_STATE_FILE = Path(".local/services.json")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def find_pg_bindir() -> Path:
    override = os.environ.get("MICRODRAMA_PG_BINDIR")
    candidates = [override] if override else []
    candidates += sorted(glob.glob("/usr/lib/postgresql/*/bin"), reverse=True)
    for cand in candidates:
        if cand and (Path(cand) / "initdb").exists() and (Path(cand) / "pg_ctl").exists():
            return Path(cand)
    which = shutil.which("initdb")
    if which:
        return Path(which).parent
    raise RuntimeError(
        "PostgreSQL server binaries (initdb/pg_ctl) not found. Install postgresql-16 "
        "or set MICRODRAMA_PG_BINDIR / MICRODRAMA_TEST_DATABASE_URL."
    )


def _as_pg_user(cmd: list[str]) -> list[str]:
    if os.geteuid() == 0:
        return ["runuser", "-u", "postgres", "--", *cmd]
    return cmd


@dataclass
class EphemeralPostgres:
    """A throwaway PostgreSQL cluster. ``start()`` returns a superuser DSN."""

    port: int = field(default_factory=free_port)
    root: Path | None = None
    keep: bool = False
    _started: bool = False

    @property
    def data_dir(self) -> Path:
        assert self.root is not None
        return self.root / "data"

    @property
    def dsn(self) -> str:
        return f"postgresql://{PG_SUPERUSER}@127.0.0.1:{self.port}/postgres"

    def start(self) -> str:
        bindir = find_pg_bindir()
        if self.root is None:
            self.root = Path(tempfile.mkdtemp(prefix="microdrama-pg-"))
        self.root.mkdir(parents=True, exist_ok=True)
        if os.geteuid() == 0:
            pg = pwd.getpwnam("postgres")
            os.chown(self.root, pg.pw_uid, pg.pw_gid)
        os.chmod(self.root, 0o700)
        if not (self.data_dir / "PG_VERSION").exists():
            subprocess.run(
                _as_pg_user(
                    [
                        str(bindir / "initdb"),
                        "-D",
                        str(self.data_dir),
                        "-U",
                        PG_SUPERUSER,
                        "-A",
                        "trust",
                        "-E",
                        "UTF8",
                        "--no-locale",
                        "--no-sync",
                    ]
                ),
                check=True,
                capture_output=True,
            )
        opts = (
            f"-p {self.port} -k {self.root} -c listen_addresses=127.0.0.1 "
            "-c fsync=off -c synchronous_commit=off -c full_page_writes=off "
            "-c max_connections=200"
        )
        subprocess.run(
            _as_pg_user(
                [
                    str(bindir / "pg_ctl"),
                    "-D",
                    str(self.data_dir),
                    "-o",
                    opts,
                    "-l",
                    str(self.root / "server.log"),
                    "-w",
                    "-t",
                    "60",
                    "start",
                ]
            ),
            check=True,
            capture_output=True,
        )
        self._started = True
        return self.dsn

    def stop(self) -> None:
        if self.root is None:
            return
        if self._started or (self.data_dir / "postmaster.pid").exists():
            bindir = find_pg_bindir()
            subprocess.run(
                _as_pg_user(
                    [str(bindir / "pg_ctl"), "-D", str(self.data_dir), "-m", "fast", "-w", "stop"]
                ),
                check=False,
                capture_output=True,
            )
            self._started = False
        if not self.keep:
            shutil.rmtree(self.root, ignore_errors=True)


@dataclass
class EphemeralRedis:
    """A throwaway Redis server with persistence disabled."""

    port: int = field(default_factory=free_port)
    root: Path | None = None
    keep: bool = False
    _proc: subprocess.Popen[bytes] | None = None

    @property
    def url(self) -> str:
        return f"redis://127.0.0.1:{self.port}/0"

    def start(self) -> str:
        binary = shutil.which("redis-server")
        if binary is None:
            raise RuntimeError(
                "redis-server not found; install redis or set MICRODRAMA_TEST_REDIS_URL"
            )
        if self.root is None:
            self.root = Path(tempfile.mkdtemp(prefix="microdrama-redis-"))
        self._proc = subprocess.Popen(
            [
                binary,
                "--port",
                str(self.port),
                "--bind",
                "127.0.0.1",
                "--save",
                "",
                "--appendonly",
                "no",
                "--dir",
                str(self.root),
                "--protected-mode",
                "yes",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with (
                contextlib.suppress(OSError),
                socket.create_connection(("127.0.0.1", self.port), 0.2),
            ):
                return self.url
            if self._proc.poll() is not None:
                raise RuntimeError("redis-server exited during startup")
            time.sleep(0.05)
        raise RuntimeError("redis-server did not start within 15s")

    def stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        if self.root is not None and not self.keep:
            shutil.rmtree(self.root, ignore_errors=True)


def _cli(argv: list[str] | None = None) -> int:
    """``python -m microdrama.testing.services up|down`` for manual exploration."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["up", "down"])
    args = parser.parse_args(argv)
    state_path = _STATE_FILE.resolve()
    if args.action == "up":
        if state_path.exists():
            print(f"already running: {state_path.read_text()}")
            return 0
        local = state_path.parent
        local.mkdir(parents=True, exist_ok=True)
        pg = EphemeralPostgres(root=local / "pg", keep=True)
        rd = EphemeralRedis(root=local / "redis", keep=True)
        dsn = pg.start()
        url = rd.start()
        assert rd._proc is not None
        state = {
            "database_url": dsn,
            "redis_url": url,
            "pg_root": str(pg.root),
            "redis_pid": rd._proc.pid,
        }
        state_path.write_text(json.dumps(state, indent=2))
        print(json.dumps(state, indent=2))
        print("export MICRODRAMA_TEST_DATABASE_URL=" + dsn)
        print("export MICRODRAMA_TEST_REDIS_URL=" + url)
        return 0
    if not state_path.exists():
        print("not running")
        return 0
    state = json.loads(state_path.read_text())
    pg = EphemeralPostgres(root=Path(state["pg_root"]), keep=True)
    pg._started = True
    pg.stop()
    with contextlib.suppress(ProcessLookupError):
        os.kill(int(state["redis_pid"]), 15)
    state_path.unlink()
    print("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
