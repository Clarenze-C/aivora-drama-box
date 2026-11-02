"""``python -m microdrama.api.serve`` — the private staging owner app (T046).

Serves the composed world's authenticated owner surfaces (login, review gates,
three-step Script Maker intake, workbench, progress, health) over durable
PostgreSQL and the filesystem object store, on the wall clock. Staging serves
the OFFLINE_MOCK composition ONLY: every paid/public/cloud effect stays refused
until T045/T031 qualify a live composition, so this process is safe to run
unattended on a private host.

Commands:
- ``serve`` (default): migrate (unless MICRODRAMA_SKIP_MIGRATE=1), build the
  world with ``SystemClock``, serve via uvicorn on MICRODRAMA_HOST:MICRODRAMA_PORT
  (default 127.0.0.1:8000 — private by default; the public bind happens only
  with the separately configured domain/TLS work).
- ``create-owner --username U [--write-password-to FILE]``: idempotent-ish
  owner bootstrap; a generated password is printed ONCE (and optionally written
  0600 to FILE). Existing usernames fail loudly rather than resetting.
- ``health``: GET MICRODRAMA_URL/health (default http://127.0.0.1:8000) and
  exit nonzero unless the view reports OK — used by compose healthchecks and
  the staging drills.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode


def _staging_guard(settings: Settings) -> None:
    """Staging refuses any non-offline mode: no live composition exists yet."""
    if settings.execution_mode is not ExecutionMode.OFFLINE_MOCK:
        print(
            "refusing to serve: staging runs the OFFLINE_MOCK composition only; "
            "a live composition must be qualified by T045/T031 first "
            f"(got {settings.execution_mode.value})",
            file=sys.stderr,
        )
        raise SystemExit(2)


def _build_world(settings: Settings, dsn: str):
    from microdrama.core.clock import SystemClock, UuidIds
    from microdrama.persistence import Database, migrate
    from microdrama.pipeline.world import build_pipeline_world

    if os.environ.get("MICRODRAMA_SKIP_MIGRATE") != "1":
        migrate(dsn)
    db = Database(dsn, min_size=1, max_size=8).open()
    world = build_pipeline_world(settings, db, clock=SystemClock(), ids=UuidIds())
    return world, db


def _build_app(world):
    from microdrama.api.app import create_app
    from microdrama.api.compose import Services, build_components
    from microdrama.pipeline.handlers import build_handlers  # noqa: F401  (worker-only)

    services = Services(
        settings=world.settings,
        db=world.db,
        clock=world.fakes.clock,
        ids=world.fakes.ids,
        jobs=world.jobs,
        idempotency=world.idempotency,
        auth=world.auth,
        budget=world.budget,
        store=world.store,
        review=world.review,
        intake=world.intake,
    )
    cookie_secure = os.environ.get("MICRODRAMA_COOKIE_SECURE") == "1"
    return create_app(build_components(services, cookie_secure=cookie_secure))


def _serve(settings: Settings, dsn: str) -> int:
    import uvicorn

    world, db = _build_world(settings, dsn)
    app = _build_app(world)
    host = os.environ.get("MICRODRAMA_HOST", "127.0.0.1")
    port = int(os.environ.get("MICRODRAMA_PORT", "8000"))
    print(f"[serve] staging owner app on {host}:{port} (OFFLINE_MOCK, durable)", flush=True)
    try:
        uvicorn.run(app, host=host, port=port, log_level="info", access_log=False)
    finally:
        db.close()
    return 0


def _write_secret_file(target: Path, secret: str) -> None:
    """Create the secret file at 0o600 from the first instant (DB-11).

    ``O_CREAT|O_EXCL`` — the file never exists at umask permissions, and an
    existing file is never silently overwritten (a stale password file must
    fail loudly, not be replaced under an operator's eye).
    """
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, secret.encode())
    finally:
        os.close(fd)


def _create_owner(settings: Settings, dsn: str, args: argparse.Namespace) -> int:
    world, db = _build_world(settings, dsn)
    try:
        with world.db.transaction(readonly=True) as tx:
            existing = tx.fetchone("SELECT id FROM owners WHERE username = %s", (args.username,))
        if existing is not None:
            print(f"owner {args.username!r} already exists; nothing done", file=sys.stderr)
            return 3
        password = secrets.token_urlsafe(18)
        owner_id = world.auth.create_owner(args.username, password)
        if args.write_password_to:
            target = Path(args.write_password_to)
            try:
                _write_secret_file(target, password + "\n")
            except FileExistsError:
                print(
                    f"refusing to overwrite {target}; the owner was created — "
                    "write the password manually or remove the file first",
                    file=sys.stderr,
                )
                return 4
            print(f"[create-owner] {args.username} = {owner_id}; password written 0600 to {target}")
        else:
            # Printed exactly once to stdout; the operator captures or discards it.
            print(f"[create-owner] {args.username} = {owner_id}; one-time password: {password}")
        return 0
    finally:
        db.close()


def _health() -> int:
    import json

    import httpx

    base = os.environ.get("MICRODRAMA_URL", "http://127.0.0.1:8000").rstrip("/")
    try:
        response = httpx.get(f"{base}/health", timeout=5.0)
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 — a probe reports, never crashes
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    # DB-11: the view must actually report ok — a 200 whose payload does not
    # say so (a proxy error page, a half-started app) is a failed probe.
    ok = response.status_code == 200 and isinstance(payload, dict) and payload.get("status") == "ok"
    print(json.dumps(payload))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="microdrama.api.serve")
    parser.add_argument(
        "command", nargs="?", default="serve", choices=["serve", "create-owner", "health"]
    )
    parser.add_argument("--username")
    parser.add_argument("--write-password-to")
    args = parser.parse_args(argv)

    if args.command == "health":
        return _health()

    dsn = os.environ.get("MICRODRAMA_DATABASE_URL")
    if not dsn:
        print("MICRODRAMA_DATABASE_URL is required", file=sys.stderr)
        return 2
    settings = Settings.from_env()
    _staging_guard(settings)
    if args.command == "create-owner":
        if not args.username:
            print("--username is required", file=sys.stderr)
            return 2
        return _create_owner(settings, dsn, args)
    return _serve(settings, dsn)


if __name__ == "__main__":
    raise SystemExit(main())
