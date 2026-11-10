"""Private T031 benchmark CLI. Local preparation is not permission to spend."""

from __future__ import annotations

import argparse
import hmac
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode
from microdrama.contracts.errors import MicrodramaError, PolicyDenied, SchemaInvalid
from microdrama.persistence import Database
from microdrama.persistence.object_store import FilesystemObjectStore
from microdrama.pipeline.benchmark_authorization import (
    MAX_DOCUMENT_BYTES,
    AcquisitionQuote,
    BenchmarkPlan,
    BenchmarkSeal,
    load_benchmark_authorization,
    load_document,
)
from microdrama.pipeline.canary import refuse_non_loopback_dsn


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "prepare",
            "seal",
            "preflight",
            "status",
            "execute",
            "resume",
            "reconcile",
            "resolve",
            "record-screening",
            "sweep",
            "export",
        ),
    )
    parser.add_argument("--experiment-id", required=True, type=UUID)
    parser.add_argument("--plan")
    parser.add_argument("--manifest")
    parser.add_argument("--authorization")
    parser.add_argument("--authorization-sha256")
    parser.add_argument("--quote")
    parser.add_argument("--phase", choices=("screen", "full"), default="screen")
    parser.add_argument("--cleanup-only", action="store_true")
    parser.add_argument("--decision")
    parser.add_argument("--acquisition-id", type=UUID)
    parser.add_argument("--sample-id")
    parser.add_argument("--actor-ref")
    parser.add_argument("--reason")
    parser.add_argument("--evidence-sha256")
    parser.add_argument("--output")
    return parser


def _read_mapping(path: str) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file() or source.stat().st_size > MAX_DOCUMENT_BYTES:
        raise SchemaInvalid("benchmark input must be a bounded regular JSON file")
    try:
        raw = source.read_bytes()
        if len(raw) > MAX_DOCUMENT_BYTES:
            raise ValueError("oversized document")
        value = json.loads(
            raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite"))
        )
        if not isinstance(value, dict):
            raise ValueError("object required")
        return value
    except (ValueError, UnicodeDecodeError):
        raise SchemaInvalid("benchmark input is not a valid JSON object") from None


def _service(db: Database, settings: Settings, store: Any, injection: dict[str, Any]) -> Any:
    # Imports stay lazy: local validation/help has no world/provider bootstrap.
    from microdrama.pipeline.benchmark_service import BenchmarkService
    from microdrama.pipeline.experimental_world import build_experiment_world_factory

    clock = injection.get("clock")
    ids = injection.get("ids")
    factory = injection.get("world_factory")
    if factory is None:
        factory = build_experiment_world_factory(db, settings, store, clock=clock, ids=ids)
    return BenchmarkService(db, settings, store=store, clock=clock, ids=ids, world_factory=factory)


def _emit(result: Any, output: str | None) -> None:
    encoded = json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2, default=str) + "\n"
    if output is None:
        print(encoded, end="")
        return
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(target)


def main(argv: list[str] | None = None, *, _injection: dict[str, Any] | None = None) -> int:
    args = _parser().parse_args(argv)
    injection = _injection or {}
    db = None
    owns_db = "db" not in injection
    try:
        settings = injection.get("settings") or Settings.from_env()
        # Only `execute` hard-refuses on flags up front: `resume` runs its
        # identity-checked recovery first (spec §4.2) and reports admission
        # blockers instead of raising when new work is not currently permitted.
        if args.command == "execute" and (
            settings.execution_mode is not ExecutionMode.PAID_BENCHMARK
            or not settings.paid_requests_enabled
            or not settings.cloud_resources_enabled
        ):
            raise PolicyDenied(
                "new benchmark work requires PAID_BENCHMARK and explicit paid/cloud flags"
            )
        authorization = None
        digest = None
        authorization_bytes = None
        if args.authorization:
            authorization, digest = load_benchmark_authorization(args.authorization)
            authorization_bytes = Path(args.authorization).read_bytes()
            if authorization.experiment_id != args.experiment_id:
                raise PolicyDenied("authorization names another experiment")
        admits_work = args.command == "execute" or (
            args.command == "resume" and not args.cleanup_only
        )
        if admits_work and args.command == "execute":
            if not authorization or not args.authorization_sha256 or not args.quote:
                raise SchemaInvalid(
                    "new benchmark work requires authorization, verified SHA-256 and acquisition quote"
                )
            if not hmac.compare_digest(digest or "", args.authorization_sha256):
                raise PolicyDenied("benchmark authorization file SHA-256 mismatch")
        elif args.authorization_sha256 and (
            not digest or not hmac.compare_digest(digest, args.authorization_sha256)
        ):
            raise PolicyDenied("benchmark authorization file SHA-256 mismatch")
        quote = load_document(args.quote, AcquisitionQuote) if args.quote else None

        # H-2: the audited operator resolution validates its attestation shape
        # before any DB or provider work (same rule as the work-command gates).
        if args.command == "resolve":
            if not args.actor_ref or not args.reason or not args.evidence_sha256:
                raise SchemaInvalid("resolve requires --actor-ref, --reason and --evidence-sha256")
            if bool(args.acquisition_id) == bool(args.sample_id):
                raise SchemaInvalid("resolve requires exactly one of --acquisition-id/--sample-id")

        # The DSN is never a flag or output; retain every canary loopback guard.
        database_url = settings.database_url
        if not database_url:
            raise SchemaInvalid("MICRODRAMA_DATABASE_URL is required")
        refuse_non_loopback_dsn(database_url)
        store = injection.get("store")
        # Every command that may compose a world gets the durable store (spec
        # §3.1): every mode requires a non-null store, reconcile and resolve
        # included.
        if args.command in {"execute", "resume", "sweep", "reconcile", "resolve"} and (
            store is None
        ):
            store_root = settings.object_store_root
            if not store_root or not Path(store_root).is_absolute():
                raise SchemaInvalid(
                    "MICRODRAMA_OBJECT_STORE_ROOT must be an explicit absolute path"
                )
            store = FilesystemObjectStore(Path(store_root))
        # Read-only/local commands never construct an object store or mkdir it.
        db = injection.get("db")
        if db is None:
            db = Database(database_url).open()
        service_factory = injection.get("service_factory") or _service
        service = service_factory(db, settings, store, injection)
        exp = args.experiment_id
        if args.command == "prepare":
            if not args.plan:
                raise SchemaInvalid("prepare requires --plan")
            plan = load_document(args.plan, BenchmarkPlan)
            plan = plan.model_copy(update={"experiment_id": exp})
            result = service.prepare(plan)
        elif args.command == "seal":
            if not args.manifest:
                raise SchemaInvalid("seal requires --manifest")
            manifest = load_document(args.manifest, BenchmarkSeal)
            if manifest.experiment_id != exp:
                raise PolicyDenied("seal names another experiment")
            result = service.seal(exp, manifest)
        elif args.command == "preflight":
            result = service.preflight(exp, authorization=authorization, quote=quote)
        elif args.command == "status":
            result = service.status(exp)
        elif args.command == "execute":
            result = service.execute(
                exp,
                authorization=authorization,
                quote=quote,
                expected_sha256=args.authorization_sha256,
                phase=args.phase,
                source_bytes=authorization_bytes,
            )
        elif args.command == "resume":
            result = service.resume(
                exp,
                authorization=authorization,
                quote=quote,
                expected_sha256=args.authorization_sha256,
                phase=args.phase,
                cleanup_only=args.cleanup_only,
                source_bytes=authorization_bytes,
            )
        elif args.command == "reconcile":
            result = service.reconcile(exp, authorization=authorization, quote=quote)
        elif args.command == "resolve":
            # H-2: the audited operator resolution for an UNKNOWN create (§E).
            # No new work is admitted; the command records positive proof only.
            if args.acquisition_id:
                result = service.resolve_create(
                    exp,
                    acquisition_id=args.acquisition_id,
                    actor_ref=args.actor_ref,
                    reason=args.reason,
                    evidence_sha256=args.evidence_sha256,
                )
            else:
                result = service.resolve_sample(
                    exp,
                    sample_id=args.sample_id,
                    actor_ref=args.actor_ref,
                    reason=args.reason,
                    evidence_sha256=args.evidence_sha256,
                )
        elif args.command == "record-screening":
            if not args.decision:
                raise SchemaInvalid("record-screening requires --decision")
            result = service.record_screening(exp, _read_mapping(args.decision))
        elif args.command == "sweep":
            result = service.sweep(exp, authorization=authorization, quote=quote)
        else:
            result = service.export(exp)
        _emit(result, args.output)
        return 0
    except MicrodramaError as exc:
        print(f"benchmark refused: {exc.code}: {exc.message}", file=sys.stderr)
        return 2
    except (OSError, ValueError):
        # Do not leak DSNs, input values or raw parser/provider bodies.
        print("benchmark refused: invalid or unavailable local input", file=sys.stderr)
        return 2
    finally:
        if owns_db and db is not None:
            db.close()


if __name__ == "__main__":
    raise SystemExit(main())
