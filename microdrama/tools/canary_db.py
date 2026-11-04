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

State lives in ``out/canary-db.json`` (dsn, port, root, data_root).
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
#: T045-FIX B-S8 + RR-S2: the canary cluster's stable, non-/tmp data root, under a
#: parent the postgres OS user can traverse (0755).
DEFAULT_DATA_ROOT = Path("/var/lib/microdrama/canary-pg")
#: Ports owned by the T046 staging stack — the canary database must never take them.
FORBIDDEN_PORTS = {8091, 8093}


def _prepare_durable_root(root: Path) -> None:
    """T045-FIX RR-S2 + O-2: make the data root reachable by the server's OS user -
    without ever widening a directory that already existed.

    The cluster runs as the ``postgres`` OS user (``runuser -u postgres``); it can
    only reach the data dir if EVERY directory from ``/`` down to the data root's
    PARENT is traversable. Directories that already exist keep their mode: if any
    of them is not traversable, the command refuses (exit 2) naming it and how to
    fix it, changing no mode and creating nothing. Only the directories this call
    creates itself - below the deepest existing ancestor - are made 0755.
    ``EphemeralPostgres.start`` then owns the root itself (0700, postgres) and
    initdb creates the data dir 0700 as the server user.

    T045-FIX CR-1: the data root itself is NEVER in the checked chain when it
    already exists - after a real ``up`` it is 0700 and owned by the server's OS
    user (its correct state), and a kept-data restart must pass, not refuse.
    """
    import stat as _stat

    root = root.resolve()
    missing: list[Path] = []
    node = root
    while not node.exists():
        missing.append(node)
        if node.parent == node:
            break
        node = node.parent
    if os.geteuid() != 0:
        # The server runs as the invoking user: create what is missing (0755) and
        # go - no cross-user traversal requirement applies.
        for part in reversed(missing):
            part.mkdir()
            os.chmod(part, 0o755)
        return
    # Every ancestor from / down to the data root's PARENT must already be
    # traversable by the server's OS user (CR-1: when the data root itself
    # already exists, the checked chain stops at its parent - the root is the
    # server user's own 0700 and never a traversal failure); a directory this
    # tool did not create in this call is never chmod'ed (O-2: the old walk
    # widened e.g. a 0700 operator home).
    untraversable: list[Path] = []
    node_chain: list[Path] = []
    walk = node.parent if node == root else node
    while True:
        node_chain.append(walk)
        if walk.parent == walk:
            break
        walk = walk.parent
    for ancestor in reversed(node_chain):
        if _stat.S_IMODE(os.stat(ancestor).st_mode) & 0o055 != 0o055:
            untraversable.append(ancestor)
    if untraversable:
        worst = untraversable[-1]  # the failure closest to the data root
        print(
            f"canary-db: {worst} is not traversable by the server OS user and this "
            "tool never changes the mode of a directory it did not create; chmod "
            "0755 it (or choose a --data-root under a traversable parent) and retry",
            file=sys.stderr,
        )
        raise SystemExit(2)
    for part in reversed(missing):
        part.mkdir()
        os.chmod(part, 0o755)


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
    """Apply migrations and seed the canary's registries and episode.

    T045-FIX RR-S3: idempotent on kept data - when the pinned canary episode already
    exists (a previous ``up``), the seeded rows are verified (fixed episode id, its
    budget account, the rights route and the benchmark preset) and nothing is written.
    """
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
    try:
        from microdrama.pipeline.canary_authorization import CANARY_EPISODE_ID
        from microdrama.testing.seed import seed_episode, seed_season

        # T045-FIX B-S9: the deterministic canary episode the authorization pins.
        episode = uuid.UUID(CANARY_EPISODE_ID)
        with db.transaction(readonly=True) as tx:
            seeded_episode = tx.fetchone(
                "SELECT 1 FROM episodes e JOIN budget_accounts a ON a.episode_id = e.id "
                "AND a.scope_kind = 'EPISODE' WHERE e.id = %s",
                (episode,),
            )
            preset = tx.fetchval(
                "SELECT 1 FROM preset_registry WHERE preset_id = %s AND current",
                ("fake-quality-8step",),
            )
            rights = tx.fetchval(
                "SELECT 1 FROM rights_registry WHERE rights_route_id = %s AND current",
                ("route-video-fake",),
            )
        if seeded_episode is not None:
            # Kept data: verify the rest of the seed is present, then write nothing.
            missing = [
                name for name, present in (("preset", preset), ("rights", rights)) if not present
            ]
            if missing:
                raise RuntimeError(
                    f"the kept canary data is missing its {missing}; "
                    "rebuild the canary database from scratch"
                )
            return
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
            season = seed_season(tx)
            seeded = seed_episode(tx, season, number=1)
            tx.execute("UPDATE episodes SET id=%s WHERE id=%s", (episode, seeded))
            account = uuid.uuid4()
            tx.execute(
                "INSERT INTO budget_accounts (id, scope_kind, season_id, episode_id, "
                "cap_micro_usd) VALUES (%s, 'EPISODE', %s, %s, 10000000)",
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
    finally:
        db.close()


def up(data_root: Path | None = None) -> int:
    data_root = data_root or DEFAULT_DATA_ROOT
    state = _state()
    if state and _reachable(state["dsn"]):
        print(f"canary database already up: {state['dsn']}")
        return 0
    from microdrama.testing.services import EphemeralPostgres

    # T045-FIX B-S8 + RR-S2: durable settings, a stable data root outside /tmp whose
    # parent the server OS user can traverse.
    _prepare_durable_root(data_root)
    server = EphemeralPostgres(keep=True, durable=True, root=data_root)
    while server.port in FORBIDDEN_PORTS:  # pragma: no cover - free-port collision
        server = EphemeralPostgres(keep=True, durable=True, root=data_root)
    dsn = server.start()
    try:
        _seed(dsn)
    except BaseException:
        # T045-FIX RR-S3: a failure after the server started must stop it - a running
        # cluster without a state file is impossible.
        server.stop()
        raise
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(
            {
                "dsn": dsn,
                "port": server.port,
                "root": str(server.root),
                # T045-FIX RR-N2: the root ``up`` was given, so ``down`` can validate.
                "data_root": str(data_root.resolve()),
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


def down(data_root: Path | None = None) -> int:
    data_root = data_root or DEFAULT_DATA_ROOT
    state = _state()
    if state is None:
        print("no canary database recorded")
        return 0
    root = Path(state["root"]).resolve()
    # T045-FIX B-N5 + RR-N2: never stop a cluster this tool does not own - the state
    # file is untrusted input. The data dir must sit under the root ``up`` recorded,
    # and the operator's --data-root must equal it.
    recorded = Path(state.get("data_root", state["root"])).resolve()
    expected = data_root.resolve()
    if root != expected or recorded != expected:
        print(
            "refusing to stop a cluster whose data directory is not under "
            f"{expected} (state says {root}, recorded root {recorded}); stop it by hand"
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
        # T045-FIX RR-N2: down accepts the same --data-root up was given.
        return down(data_root=args.data_root)
    return status()


if __name__ == "__main__":
    raise SystemExit(main())
