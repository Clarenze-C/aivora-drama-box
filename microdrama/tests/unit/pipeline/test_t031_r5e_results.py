"""T031 R5e (RR-T10): ``tools/t031_results.py`` maps a benchmark export onto
the results template.

An all-NOT_RUN export reproduces the template body exactly (the header byte
for byte); a filled export fills only the cells the pipeline knows - ids,
state, output sha, timings, cost fields - while unknown values stay blank
(never 0) and the nine quality/coverage columns stay UNKNOWN for the human
Pass A / Pass B.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[3] / "tools"
sys.path.insert(0, str(TOOLS))

import t031_results as results  # noqa: E402

HEADER = ",".join(results.TEMPLATE_COLUMNS)
#: The template's own body for an experiment that has not run (eight UNKNOWN
#: quality dimensions; coverage_evidence and the two trailing cells blank).
NOT_RUN_ROW = (
    "pika-flex-ref2va-480p-candidate,NOT_RUN,UNMEASURED,,,,,,,,,"
    "NOT_INCURRED,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,"
    "UNKNOWN,,,"
)


def _template(tmp_path: Path) -> Path:
    template = tmp_path / "results-template.csv"
    body = "\n".join(
        f"S0{shot}-R{repeat},{NOT_RUN_ROW}" for shot in range(1, 9) for repeat in range(1, 4)
    )
    template.write_text(HEADER + "\n" + body + "\n", encoding="utf-8")
    return template


def _export(samples: list[dict], *, billing_state: str = "NOT_INCURRED", billed=None) -> dict:
    return {
        "experiment_id": "11111111-2222-3333-4444-555555555555",
        "execution_state": "COMPUTE_COMPLETE",
        "execution_outcome": None,
        "cleanup_state": "NOT_REQUIRED",
        "billing_state": billing_state,
        "gpu_ms": 0,
        "incidents": [],
        "costs": {"total": 0, "settled": 0, "unreserved_settled": 0},
        "billed_micro_usd": billed,
        "samples": samples,
        "acquisitions": [],
    }


def _sample(sample_id: str, state: str = "NOT_RUN", **extra) -> dict:
    return {
        "sample_id": sample_id,
        "state": state,
        "output": extra.get("output"),
        "quality": "UNKNOWN",
        "timings": {
            "full_job_ms": extra.get("full_job_ms"),
            "sampler_ms": extra.get("sampler_ms"),
        },
        "cost_micro_usd": None,
    }


def _rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_rr_t10_unstarted_export_reproduces_the_template_exactly(tmp_path) -> None:
    template = _template(tmp_path)
    export = tmp_path / "export.json"
    export.write_text(json.dumps(_export([_sample(s) for s in results.SAMPLE_IDS])))
    output = tmp_path / "results.csv"
    assert (
        results.main(
            [
                "--export",
                str(export),
                "--template",
                str(template),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert output.read_text(encoding="utf-8") == template.read_text(encoding="utf-8")


def test_rr_t10_filled_export_fills_only_known_cells(tmp_path) -> None:
    template = _template(tmp_path)
    samples = [_sample(s) for s in results.SAMPLE_IDS]
    # S01-R1 succeeded with a durable output and both timings; S02-R1 failed
    # with no output; every other sample stayed untouched.
    samples[0] = _sample(
        "S01-R1",
        "SUCCEEDED",
        output={"sha256": "a" * 64},
        full_job_ms=123_456,
        sampler_ms=987,
    )
    samples[3] = _sample("S02-R1", "FAILED")
    export = tmp_path / "export.json"
    export.write_text(json.dumps(_export(samples, billing_state="BILLED", billed=999_999)))
    output = tmp_path / "results.csv"
    assert (
        results.main(
            [
                "--export",
                str(export),
                "--template",
                str(template),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    rows = {row["sample_id"]: row for row in _rows(output)}
    assert output.read_text(encoding="utf-8").splitlines()[0] == HEADER
    succeeded = rows["S01-R1"]
    assert succeeded["execution_state"] == "SUCCEEDED"
    assert succeeded["outcome"] == "SUCCEEDED"
    assert succeeded["output_sha256"] == "a" * 64
    assert succeeded["full_job_ms"] == "123456"
    assert succeeded["sampler_ms"] == "987"
    assert succeeded["billed_micro_usd"] == "999999"
    assert succeeded["billing_state"] == "BILLED"
    failed = rows["S02-R1"]
    assert failed["execution_state"] == "FAILED"
    assert failed["outcome"] == "FAILED"
    assert failed["output_sha256"] == ""
    # Unknown values stay blank (never 0) and the human judgment columns stay
    # UNKNOWN on every row - including the filled ones.
    for row in rows.values():
        assert row["cold_start_ms"] == "" and row["actual_duration_ms"] == ""
        for column in results.TEMPLATE_COLUMNS[13:21]:
            assert row[column] == "UNKNOWN"
        assert row["coverage_evidence"] == ""
        assert row["accepted_retained_ms"] == "" and row["failure_reason"] == ""
    # A non-terminal state is UNMEASURED, and a missing sampler timing stays
    # blank, not 0.
    samples[0] = _sample("S01-R1", "SUBMITTED", full_job_ms=None)
    export.write_text(json.dumps(_export(samples)))
    assert (
        results.main(
            [
                "--export",
                str(export),
                "--template",
                str(template),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    resubmitted = {row["sample_id"]: row for row in _rows(output)}["S01-R1"]
    assert resubmitted["outcome"] == "UNMEASURED"
    assert resubmitted["full_job_ms"] == "" and resubmitted["sampler_ms"] == ""


def test_rr_t10_refuses_exports_and_templates_off_the_fixed_shape(tmp_path) -> None:
    template = _template(tmp_path)
    partial = tmp_path / "partial.json"
    partial.write_text(json.dumps(_export([_sample(s) for s in results.SAMPLE_IDS[:23]])))
    with pytest.raises(SystemExit, match="fixed 24 samples"):
        results.main(
            [
                "--export",
                str(partial),
                "--template",
                str(template),
                "--output",
                str(tmp_path / "o.csv"),
            ]
        )
    alien = tmp_path / "alien-template.csv"
    alien.write_text("sample_id,some_other_column\n", encoding="utf-8")
    export = tmp_path / "export.json"
    export.write_text(json.dumps(_export([_sample(s) for s in results.SAMPLE_IDS])))
    with pytest.raises(SystemExit, match="header differs"):
        results.main(
            ["--export", str(export), "--template", str(alien), "--output", str(tmp_path / "o.csv")]
        )
