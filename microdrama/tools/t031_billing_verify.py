#!/usr/bin/env python
"""T031 R5f: executable per-pod billing verification for the benchmark.

Thin wrapper over the EXISTING invoice verifier
(``RunpodInvoiceFinality.verify_invoice_period``) - the same pattern as the
canary's ``run_invoice`` (pipeline/canary.py): the operator captures the
RunPod console invoice/billing evidence for the pod's period to a file, and
this tool verifies that period against the pod's billed buckets. Only the
sha256 of the evidence file is stored - the file itself (and any credential)
never enters the database or the output.

No new verification logic, no migration, no network calls: the verifier and
the ``runpod_billing_period_evidence`` path already exist (§3 R5f).

Usage (from ``microdrama/``; the DSN is an argument like prepare_run's):
  PYTHONPATH=src .venv/bin/python tools/t031_billing_verify.py \
      --dsn <loopback paid DB> --experiment-id <UUID> --pod-id <POD> \
      --period-start <ISO> --period-end <ISO> --amount-micro-usd <N> \
      --evidence <file> [--source INVOICE|CONSOLE] [--actor ...] [--reason ...]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SystemExit(f"refused: {value} must be a timezone-aware ISO datetime")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--experiment-id", required=True, type=UUID)
    parser.add_argument("--pod-id", required=True)
    parser.add_argument("--period-start", required=True)
    parser.add_argument("--period-end", required=True)
    parser.add_argument("--amount-micro-usd", required=True, type=int)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--source", choices=("INVOICE", "CONSOLE"), default="CONSOLE")
    parser.add_argument("--actor")
    parser.add_argument("--reason")
    parser.add_argument("--observed-at")
    parser.add_argument("--supersedes", type=UUID)
    args = parser.parse_args(argv)

    from microdrama.budget import BudgetService
    from microdrama.config import Settings
    from microdrama.contracts.errors import MicrodramaError
    from microdrama.core.clock import SystemClock, UuidIds
    from microdrama.persistence import Database
    from microdrama.rendering.finality import RunpodInvoiceFinality

    period_start = _parse_datetime(args.period_start)
    period_end = _parse_datetime(args.period_end)
    observed_at = _parse_datetime(args.observed_at) if args.observed_at else datetime.now(UTC)
    evidence = args.evidence
    if not evidence.is_file():
        raise SystemExit("refused: the console evidence file is missing")
    evidence_bytes = evidence.read_bytes()
    evidence_sha256 = hashlib.sha256(evidence_bytes).hexdigest()

    settings = Settings.from_env().model_copy(update={"database_url": args.dsn})
    db = Database(args.dsn, min_size=1, max_size=5).open()
    try:
        # The provider account comes from the experiment's own durable
        # authorization (stored at execute with its source bytes).
        with db.transaction(readonly=True) as tx:
            payload = tx.fetchval(
                "SELECT payload FROM benchmark_authorizations WHERE experiment_id=%s "
                "ORDER BY authorized_at DESC, authorization_sha256 DESC LIMIT 1",
                (args.experiment_id,),
            )
        if payload is None:
            raise SystemExit(
                "refused: the experiment has no durable authorization to name its provider account"
            )
        provider_account_ref = payload.get("provider_account_ref")
        if not isinstance(provider_account_ref, str) or not provider_account_ref:
            raise SystemExit("refused: the stored authorization lacks a provider account")
        repository = RunpodInvoiceFinality(
            db, budget_service=BudgetService(db, SystemClock(), UuidIds(), settings)
        )
        try:
            result = repository.verify_invoice_period(
                provider_account_ref=provider_account_ref,
                pod_id=args.pod_id,
                period_start=period_start,
                period_end=period_end,
                amount_micro_usd=args.amount_micro_usd,
                currency="USD",
                evidence_sha256=evidence_sha256,
                source=args.source,
                observed_at=observed_at,
                supersedes_evidence_id=args.supersedes,
                actor_ref=args.actor,
                reason=args.reason,
            )
        except MicrodramaError as exc:
            print(f"billing verification refused: {exc.code}: {exc.message}", file=sys.stderr)
            return 2
    finally:
        db.close()
    print(
        json.dumps(
            {
                "outcome": result.outcome,
                "replayed": result.replayed,
                "pod_id": args.pod_id,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "amount_micro_usd": result.amount_micro_usd,
                "bucket_sum_micro_usd": result.bucket_sum_micro_usd,
                # The sha ONLY - never the evidence bytes or a credential.
                "evidence_sha256": evidence_sha256,
            },
            sort_keys=True,
        )
    )
    return 0 if result.outcome in ("MATCHED", "MATCHED_ZERO") else 1


if __name__ == "__main__":
    raise SystemExit(main())
