"""Stand up the dedicated canary database (T045 R11; see the live-provider runbook).

A fresh loopback PostgreSQL with every migration applied and the canary's own
registry seed: the rights route (real evidence labels, so it stays eligible in
PAID_BENCHMARK), the enabled benchmark preset, and one canary episode with its
budget account. The T046 staging stack refuses PAID_BENCHMARK, so the canary
cannot use it — this database is the canary's own.

Safety: it binds 127.0.0.1 on a free port (never 8091 or 8093, the staging
stack's), never touches a running container or any other database, and refuses to
stop a cluster whose data directory is not under its own data root.

T045-FIX B-S8: the canary cluster runs in DURABLE mode (fsync, synchronous_commit
and full_page_writes on) in a stable data directory outside /tmp, created 0700.
``down`` is a fast (crash-safe) shutdown that KEEPS the data - this database is
the only ledger of a paid run.

Usage (from ``microdrama/``):
    python tools/canary_db.py up      # start (or report) the canary database
    python tools/canary_db.py down    # stop the cluster (fast) and keep its data
    python tools/canary_db.py status  # show the stored state without starting it

State lives in ``out/canary-db.json`` (dsn, port, pid, root).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

STATE_PATH = ROOT / "out" / "canary-db.json"
#: T045-FIX B-S8: the canary cluster's stable, non-/tmp data root.
DEFAULT_DATA_ROOT = Path("/root/.local/share/microdrama/canary-pg")
#: Ports owned by the T046 staging stack — the canary database must never take them.
FORBIDDEN_PORTS = {8091, 8093}


def _state() -> dict | None:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return None


def _reachable(dsn: str) -> bool:
    import psycopg

    try:
        with psycopg.connect(dsn, connect_timeout=2):
            return True
    except Exception:
        return False


def _seed(dsn: str) -> None:
    """Apply migrations and seed the canary's registries and episode."""
    from microdrama.config import Settings
    from microdrama.contracts.enums import (
        EvidenceSource,
        Provenance,
        RightsStatus,
        RightsSubjectKind,
    )
    from microdrama.contracts.primitives import EvidenceRef
    from microdrama.contracts.registries import RightsRecord
    from microdrama.core.clock import SystemClock
    from microdrama.core.registry.presets import PresetRegistry
    from microdrama.core.registry.rights import RightsRegistry
    from microdrama.persistence import Database, migrate
    from microdrama.pipeline.catalog import mock_catalog_presets

    migrate(dsn)
    settings = Settings()
    db = Database(dsn, min_size=1, max_size=5).open()
    preset_registry = PresetRegistry(db, settings)
    preset = next(p for p in mock_catalog_presets() if p.preset_id == "fake-quality-8step")
    preset = preset.model_copy(update={"gpu_type": "A40", "host_ram_gb": 64})
    preset_registry.record(preset, source_provenance=Provenance.FAKE_SYNTHETIC)
    rights_registry = RightsRegistry(db, SystemClock(), settings)
    now = datetime.now(UTC)
    rights_registry.record(
        RightsRecord(
            record_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "canary-rights-route")),
            rights_route_id="route-video-fake",
            version=1,
            subject_kind=RightsSubjectKind.MODEL_OUTPUT,
            subject_ref="model-output:qualified",
            territories=["TH"],
            commercial_use=True,
            output_release_allowed=True,
            # Real labels: a FAKE_FIXTURE record reads UNKNOWN outside OFFLINE_MOCK.
            evidence=[
                EvidenceRef(source=EvidenceSource.LICENSE_DOCUMENT, ref="canary:rights-license")
            ],
            status=RightsStatus.ELIGIBLE,
            recorded_at=now,
        ),
        source_provenance=Provenance.LIVE_PROVIDER,
    )
    with db.transaction() as tx:
        from microdrama.pipeline.canary_authorization import CANARY_EPISODE_ID
        from microdrama.testing.seed import seed_episode, seed_season

        season = seed_season(tx)
        seeded = seed_episode(tx, season, number=1)
        # T045-FIX B-S9: the deterministic canary episode the authorization pins.
        episode = uuid.UUID(CANARY_EPISODE_ID)
        tx.execute("UPDATE episodes SET id=%s WHERE id=%s", (episode, seeded))
        account = uuid.uuid4()
        tx.execute(
            "INSERT INTO budget_accounts (id, scope_kind, season_id, episode_id, cap_micro_usd) "
            "VALUES (%s, 'EPISODE', %s, %s, 10000000)",
            (account, season, episode),
        )
        for category in (
            "RESEARCH_SCRIPT_PROMPTS_METADATA",
            "REFERENCES_DIALOGUE",
            "QA_CAPTIONS",
            "CPU_STORAGE_TRANSFER",
            "RECOVERY_HEADROOM",
        ):
            tx.execute(
                "INSERT INTO budget_category_allocations (account_id, category, "
                "allocated_micro_usd, protected) VALUES (%s, %s, 0, true)",
                (account, category),
            )
        tx.execute(
            "INSERT INTO budget_category_allocations (account_id, category, "
            "allocated_micro_usd, protected) VALUES (%s, 'GPU_GENERATION', 9000000, true)",
            (account,),
        )
        tx.execute(
            "INSERT INTO budget_category_allocations (account_id, category, "
            "allocated_micro_usd, protected) VALUES (%s, 'METERED_MANAGEMENT', 0, false)",
            (account,),
        )
    db.close()


def up(data_root: Path = DEFAULT_DATA_ROOT) -> int:
    state = _state()
    if state and _reachable(state["dsn"]):
        print(f"canary database already up: {state['dsn']}")
        return 0
    from microdrama.testing.services import EphemeralPostgres

    # T045-FIX B-S8: durable settings, stable data root outside /tmp, 0700.
    server = EphemeralPostgres(keep=True, durable=True, root=data_root)
    while server.port in FORBIDDEN_PORTS:  # pragma: no cover - free-port collision
        server = EphemeralPostgres(keep=True, durable=True, root=data_root)
    dsn = server.start()
    _seed(dsn)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(
            {
                "dsn": dsn,
                "port": server.port,
                "root": str(server.root),
                "started_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
        )
        + "\n"
    )
    from microdrama.pipeline.canary_authorization import CANARY_EPISODE_ID

    print(f"canary database up: {dsn}")
    print(f"canary episode: {CANARY_EPISODE_ID}")
    print(f"state: {STATE_PATH}")
    print(
        "Run the canary with MICRODRAMA_DATABASE_URL set to this DSN "
        "(see the runbook's canary section)."
    )
    return 0


def down() -> int:
    state = _state()
    if state is None:
        print("no canary database recorded")
        return 0
    root = Path(state["root"]).resolve()
    # T045-FIX B-N5: never stop a cluster this tool does not own - the state file is
    # untrusted input, its data dir must sit under the canary-db data root.
    if not root.is_relative_to(DEFAULT_DATA_ROOT.resolve()):
        print(
            "refusing to stop a cluster whose data directory is not under "
            f"{DEFAULT_DATA_ROOT} (state says {root}); stop it by hand"
        )
        return 1
    data_dir = root / "data"
    if data_dir.exists():
        # T045-FIX B-S8: a fast (crash-safe) shutdown; the data is kept.
        from microdrama.testing.services import find_pg_bindir

        bindir = find_pg_bindir()
        command = [
            str(bindir / "pg_ctl"),
            "-D",
            str(data_dir),
            "-o",
            f"-p {state['port']}",
            "stop",
            "-m",
            "fast",
        ]
        if os.geteuid() == 0:  # pragma: no cover - test suites run as root
            import pwd

            pg = pwd.getpwnam("postgres")
            subprocess.run(command, user=pg.pw_name, check=False, capture_output=True)
        else:  # pragma: no cover
            subprocess.run(command, check=False, capture_output=True)
    STATE_PATH.unlink(missing_ok=True)
    print(f"canary database down (fast shutdown; cluster data kept at {root})")
    return 0


def status() -> int:
    state = _state()
    if state is None:
        print("no canary database recorded")
        return 1
    up = _reachable(state["dsn"])
    print(f"canary database {'UP' if up else 'DOWN'}: {state['dsn']} (port {state['port']})")
    return 0 if up else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="canary_db")
    parser.add_argument("command", choices=("up", "down", "status"))
    parser.add_argument(
        "--data-root",
        type=Path,
        default=DEFAULT_DATA_ROOT,
        help="the canary cluster's durable data directory (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    if args.command == "up":
        return up(data_root=args.data_root)
    if args.command == "down":
        return down()
    return status()


if __name__ == "__main__":
    raise SystemExit(main())
