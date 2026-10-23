"""``python -m microdrama.scheduling`` — fire due schedules once and exit.

Deployment: a systemd timer/service (or supervisor loop) runs this every
minute. One-shot by design — no background threads; the process is stateless
apart from ``schedule_state`` rows. Requires MICRODRAMA_DATABASE_URL.

Live provider wiring arrives with T031/T032; until then firing runs the
composed offline-pilot world (which refuses every paid/public effect), so the
timer can be deployed safely before live qualification.
"""

from __future__ import annotations

import json
import os
import sys

from microdrama.config import Settings
from microdrama.persistence import Database, migrate


def main(argv: list[str] | None = None) -> int:
    del argv
    dsn = os.environ.get("MICRODRAMA_DATABASE_URL")
    if not dsn:
        print("MICRODRAMA_DATABASE_URL is required", file=sys.stderr)
        return 2
    settings = Settings.from_env()
    db = Database(dsn, min_size=1, max_size=4).open()
    try:
        migrate(dsn)
        from microdrama.pipeline.world import build_pipeline_world
        from microdrama.scheduling import TriggerScheduler, default_catalog

        world = build_pipeline_world(settings, db, seed_registries=False)
        scheduler = TriggerScheduler(world, default_catalog())
        report = scheduler.fire()
        print(json.dumps(report.as_dict(), default=str))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
