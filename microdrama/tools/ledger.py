"""Update docs/microdrama-system/task_status.csv (orchestrator-only tool).

Usage:
  python tools/ledger.py T001 status=ACCEPTED owner=Integrator completed_at=now evidence="..."
``now`` expands to the current UTC timestamp.
"""

from __future__ import annotations

import csv
import sys
from datetime import UTC, datetime
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[2] / "docs" / "microdrama-system" / "task_status.csv"
STATUSES = {
    "TODO",
    "CLAIMED",
    "IN_PROGRESS",
    "REVIEW",
    "ACCEPTED",
    "DONE",
    "BLOCKED_EXTERNAL",
    "FAILED",
    "CANCELLED",
}


def main(argv: list[str]) -> int:
    task_id, *assignments = argv
    with LEDGER.open(newline="") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    target = next((r for r in rows if r["task_id"] == task_id), None)
    if target is None:
        raise SystemExit(f"unknown task {task_id}")
    for item in assignments:
        key, _, value = item.partition("=")
        if key not in fields:
            raise SystemExit(f"unknown column {key}")
        if value == "now":
            value = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        if key == "status" and value not in STATUSES:
            raise SystemExit(f"invalid status {value}")
        target[key] = value
    with LEDGER.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
    print({k: target[k] for k in ("task_id", "status", "owner", "started_at", "completed_at")})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
