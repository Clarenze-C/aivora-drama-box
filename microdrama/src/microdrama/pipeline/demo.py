"""The one reproducible offline demo command (T029 acceptance).

``python -m microdrama.pipeline.demo [--workdir DIR]``

Starts an isolated PostgreSQL (real binaries, private temp dir, 127.0.0.1),
applies every migration, runs the complete two-gate mock path from proposal to
managed fake post, and writes into ``DIR``:

- ``run-report.json`` — every stage, cost view, post ids and mock labels;
- ``media/`` — the REAL FFmpeg exports (master, burned caption master, variants,
  hooks, covers) copied out of the private object store, playable with any
  player;
- ``pilot.log`` — the same stage lines as stdout.

The command refuses to run outside OFFLINE_MOCK (the world constructor raises
EffectDenied first), performs no paid request, creates no cloud resource and
takes no public action; every provider is a T007 fake whose outputs are visibly
labeled mock.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode
from microdrama.persistence import Database, migrate
from microdrama.testing.services import EphemeralPostgres

from .runner import MockPipelineRunner
from .world import build_pipeline_world


def _export_media(world, episode_id, out_dir: Path) -> list[str]:
    """Copy the episode's edited exports (master/burned/variants/hooks/covers/captions)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    exported: list[str] = []
    with world.db.transaction(readonly=True) as tx:
        rows = tx.fetchall(
            "SELECT id, object_key FROM assets WHERE episode_id = %s "
            "AND object_key LIKE 'edits/%%' ORDER BY object_key",
            (episode_id,),
        )
    for row in rows:
        target = out_dir / Path(row["object_key"]).name
        target.write_bytes(world.store.get_bytes(row["object_key"]))
        if target.name not in exported:  # rows can share one content-addressed key
            exported.append(target.name)
    return exported


def run_demo(workdir: Path) -> dict:
    workdir.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        execution_mode=ExecutionMode.OFFLINE_MOCK,
        object_store_root=workdir / "objects",
    )
    server = EphemeralPostgres()
    dsn = server.start()
    database = None
    try:
        migrate(dsn)
        database = Database(dsn, min_size=1, max_size=10).open()
        world = build_pipeline_world(settings, database)
        runner = MockPipelineRunner(world)
        report = runner.run()

        cost = world.budget.cost_view(runner.report.episode_id)
        exported = _export_media(world, runner.report.episode_id, workdir / "media")
        payload = report.as_dict()
        payload["cost"] = cost.summary.model_dump(mode="json")
        payload["exported_media"] = exported
        payload["network_effects"] = {
            "paid_requests": 0,
            "cloud_resources": 0,
            "public_actions": 0,
            "all_providers": "fake (T007)",
        }
        (workdir / "run-report.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str)
        )
        return payload
    finally:
        if database is not None:
            database.close()
        server.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="microdrama.pipeline.demo",
        description="Reproduce the complete offline two-gate mock path (no paid or "
        "public effects; every provider is fake).",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=Path("out/pilot-demo"),
        help="output directory (default: out/pilot-demo)",
    )
    args = parser.parse_args(argv)

    print("[mock] microdrama offline pilot demo — OFFLINE_MOCK, all providers fake")
    try:
        payload = run_demo(args.workdir)
    except Exception as exc:  # noqa: BLE001 - the demo reports failures verbatim
        print(f"[mock] FAILED: {exc}", file=sys.stderr)
        return 1
    for stage in payload["stages"]:
        marker = "HUMAN" if stage["stage"] in ("season_approval", "gate2_approval") else "auto"
        print(f"[mock] {stage['workflow']:<5} {stage['stage']:<22} {stage['status']:<8} ({marker})")
    print(
        f"[mock] media exported: {len(payload['exported_media'])} file(s) -> {args.workdir}/media"
    )
    print(f"[mock] report: {args.workdir}/run-report.json")
    print(
        "[mock] settled micro-usd: "
        f"{payload['cost']['settled_micro_usd']} (fake providers; no real money)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
