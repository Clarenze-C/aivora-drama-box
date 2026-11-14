#!/usr/bin/env python
"""T031 R5e: map a ``benchmark export`` JSON onto ``results-template.csv``.

The template (docs/microdrama-system/t031-benchmark/results-template.csv) is
the authoritative column order; this tool only fills the columns the pipeline
actually knows - ids, state, output sha, timings, cost fields. The nine
quality/coverage columns stay ``UNKNOWN`` for the human Pass A / Pass B, and
every value the pipeline does not know is left blank (or ``UNKNOWN`` for the
judgment columns), never coerced to 0.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

#: The template's fixed columns, in order; a different template is refused.
TEMPLATE_COLUMNS: tuple[str, ...] = (
    "sample_id",
    "configuration_id",
    "execution_state",
    "outcome",
    "prompt_sha256",
    "reference_manifest_sha256",
    "output_sha256",
    "actual_duration_ms",
    "cold_start_ms",
    "full_job_ms",
    "sampler_ms",
    "billed_micro_usd",
    "billing_state",
    "thai_meaning",
    "pronunciation",
    "speaker_identity",
    "lip_sync",
    "visual_identity",
    "wardrobe",
    "prop_continuity",
    "emotion",
    "coverage_evidence",
    "accepted_retained_ms",
    "failure_reason",
)

#: The fixed 24 samples (S01..S08 x R1..R3).
SAMPLE_IDS: tuple[str, ...] = tuple(
    f"S0{shot}-R{repeat}" for shot in range(1, 9) for repeat in range(1, 4)
)

#: Sample states that carry a terminal outcome; everything else is UNMEASURED.
_TERMINAL_STATES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED"})

DEFAULT_CONFIGURATION_ID = "pika-flex-ref2va-480p-candidate"


def _cell(value: object) -> str:
    """A known value renders as its integer; an unknown one stays blank,
    never 0 (RR-T10 / spec R5e)."""
    if value is None:
        return ""
    return str(int(value))


def map_export(export: dict, configuration_id: str) -> list[dict[str, str]]:
    """The template rows for one benchmark export document."""
    samples = {s.get("sample_id"): s for s in export.get("samples") or []}
    missing = [sample_id for sample_id in SAMPLE_IDS if sample_id not in samples]
    extra = sorted(set(samples) - set(SAMPLE_IDS))
    if missing or extra:
        raise SystemExit(
            "refused: the export does not carry exactly the fixed 24 samples "
            f"(missing {missing[:3]}, unexpected {extra[:3]})"
        )
    billed = export.get("billed_micro_usd")
    billing_state = export.get("billing_state") or "UNKNOWN"
    rows: list[dict[str, str]] = []
    for sample_id in SAMPLE_IDS:
        sample = samples[sample_id]
        state = sample.get("state") or "NOT_RUN"
        timings = sample.get("timings") or {}
        output = sample.get("output") or {}
        rows.append(
            {
                "sample_id": sample_id,
                "configuration_id": configuration_id,
                "execution_state": state,
                "outcome": state if state in _TERMINAL_STATES else "UNMEASURED",
                # Per-sample values the export does not carry stay blank:
                # the prompt hash is plan-level, the reference manifest hash
                # seal-level, and cold_start_ms is a per-acquisition record.
                "prompt_sha256": "",
                "reference_manifest_sha256": "",
                "output_sha256": str(output.get("sha256") or ""),
                "actual_duration_ms": "",
                "cold_start_ms": "",
                "full_job_ms": _cell(timings.get("full_job_ms")),
                "sampler_ms": _cell(timings.get("sampler_ms")),
                "billed_micro_usd": _cell(billed),
                "billing_state": billing_state,
                # The human judgment columns (Pass A / Pass B): the eight
                # quality dimensions ship UNKNOWN; the coverage evidence
                # column stays blank for the human attach.
                **{column: "UNKNOWN" for column in TEMPLATE_COLUMNS[13:21]},
                "coverage_evidence": "",
                "accepted_retained_ms": "",
                "failure_reason": "",
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", required=True, type=Path, help="benchmark export JSON")
    parser.add_argument(
        "--template", required=True, type=Path, help="results-template.csv (header source)"
    )
    parser.add_argument("--output", required=True, type=Path, help="CSV to write")
    parser.add_argument("--configuration-id", default=DEFAULT_CONFIGURATION_ID)
    args = parser.parse_args(argv)

    with args.template.open(newline="", encoding="utf-8") as handle:
        header = next(csv.reader(handle), [])
    if tuple(header) != TEMPLATE_COLUMNS:
        raise SystemExit("refused: the template header differs from the fixed 24 results columns")
    export = json.loads(args.export.read_text(encoding="utf-8"))
    rows = map_export(export, args.configuration_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(TEMPLATE_COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(
        json.dumps(
            {
                "results": str(args.output),
                "rows": len(rows),
                "configuration_id": args.configuration_id,
                "billing_state": export.get("billing_state"),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
