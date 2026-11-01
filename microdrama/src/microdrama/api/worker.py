"""``python -m microdrama.api.worker`` — the staging worker + janitor loop (T046).

Runs the composed world's lane deployments (production/publication/community
queues, shared rate limiter, T028 semantics) on the wall clock, independently
of the API process, plus the workers janitor sweep on a slow cadence. The
OFFLINE_MOCK composition refuses every paid/public/cloud effect, so this loop
is safe unattended: it drains durable work (research/enrichment/rearm jobs,
scheduling drains) and keeps stale jobs honest without any provider traffic.

``--once``: drain until idle, sweep the janitor once, print a JSON report and
exit (the drill/cron shape). ``--janitor-only``: one sweep and exit.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from datetime import UTC, datetime

from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode

_STOP = False


def _handle_term(_signum, _frame) -> None:
    global _STOP
    _STOP = True


def _world(settings: Settings, dsn: str):
    from microdrama.core.clock import SystemClock, UuidIds
    from microdrama.persistence import Database, migrate
    from microdrama.pipeline.world import build_pipeline_world

    if os.environ.get("MICRODRAMA_SKIP_MIGRATE") != "1":
        migrate(dsn)
    db = Database(dsn, min_size=1, max_size=4).open()
    world = build_pipeline_world(settings, db, clock=SystemClock(), ids=UuidIds())
    return world, db


def _report(world, cycles: int, sweeps: int) -> dict:
    return {
        "worker": "staging-worker",
        "cycles": cycles,
        "janitor_sweeps": sweeps,
        "at": datetime.now(UTC).isoformat(),
        "mode": world.settings.execution_mode.value,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="microdrama.api.worker")
    parser.add_argument("--once", action="store_true", help="drain to idle, sweep, exit")
    parser.add_argument("--janitor-only", action="store_true", help="one janitor sweep, exit")
    parser.add_argument("--idle-sleep", type=float, default=2.0)
    parser.add_argument("--janitor-every", type=int, default=25, help="sweep every N cycles")
    args = parser.parse_args(argv)

    dsn = os.environ.get("MICRODRAMA_DATABASE_URL")
    if not dsn:
        print("MICRODRAMA_DATABASE_URL is required", file=sys.stderr)
        return 2
    settings = Settings.from_env()
    if settings.execution_mode is not ExecutionMode.OFFLINE_MOCK:
        print("staging worker runs the OFFLINE_MOCK composition only", file=sys.stderr)
        return 2

    world, db = _world(settings, dsn)
    try:
        from microdrama.pipeline.handlers import build_handlers

        runtime = world.runtime(build_handlers(world), name="staging-worker")
        janitor = world.workers_janitor

        def sweep() -> dict:
            return janitor.sweep().to_dict()

        if args.janitor_only:
            print(json.dumps(sweep(), default=str))
            return 0

        signal.signal(signal.SIGTERM, _handle_term)
        signal.signal(signal.SIGINT, _handle_term)
        cycles = 0
        sweeps = 0
        while not _STOP:
            cycle = runtime.run_cycle()
            cycles += 1
            if cycles % args.janitor_every == 0:
                print(json.dumps({"janitor": sweep()}, default=str))
                sweeps += 1
            all_idle = len(cycle.idle_queues) == len(runtime._deployment.slots)  # noqa: SLF001
            if args.once:
                if all_idle:
                    break
                continue
            if all_idle:
                time.sleep(args.idle_sleep)
        if args.once:
            final = sweep()
            sweeps += 1
            print(
                json.dumps({**_report(world, cycles, sweeps), "last_janitor": final}, default=str)
            )
        else:
            print(json.dumps(_report(world, cycles, sweeps), default=str))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
