"""T031 R5c (RR-T8): the guarded live schema comparison stays decisive.

A live schema mismatch at readiness refuses BEFORE any upload (the seal's
mapped hash governs); a match records the live capture durably on the
acquisition-keyed coverage record (``t031_live_schema``) and the raw JSON in
the object store.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_t031_r5b_staging import _office_compose

from microdrama.persistence import Database

pytestmark = pytest.mark.db


def _live_record(db: Database, experiment_id) -> dict:
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT coverage FROM benchmark_samples WHERE experiment_id=%s "
            "ORDER BY sample_id LIMIT 1",
            (experiment_id,),
        )
    records = (row["coverage"] or {}).get("t031_acquisitions") or {}
    for record in records.values():
        if record.get("live_schema"):
            return record["live_schema"]
    return {}


def test_rr_t8_live_mismatch_refuses_before_any_upload(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # A seal whose pinned mapped hash CANNOT match the pod (bound
    # consistently: seal + authorization) - the guarded attest at readiness
    # must refuse before any upload leaves.
    harness = _office_compose(
        db, tmp_path, monkeypatch, seal_overrides={"node_schema_sha256": "9" * 64}
    )
    plan = harness.plan
    from microdrama.contracts.errors import SchemaInvalid

    with pytest.raises(SchemaInvalid, match="schema differs"):
        harness.service.execute(
            plan.experiment_id,
            phase="screen",
            authorization=harness.authorization,
            quote=harness.quote,
            expected_sha256=harness.authorization.authorization_sha256,
        )
    assert harness.server.upload_posts == 0, "a schema mismatch must refuse BEFORE any upload"
    with db.transaction(readonly=True) as tx:
        states = {
            row["state"]
            for row in tx.fetchall(
                "SELECT state FROM benchmark_samples WHERE experiment_id=%s",
                (plan.experiment_id,),
            )
        }
    # No sample completed anything: the refusal preceded every upload/prompt.
    assert "SUCCEEDED" not in states, states


def test_rr_t8_live_match_records_the_capture_during_staging(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    harness = _office_compose(db, tmp_path, monkeypatch)
    plan = harness.plan
    last = harness.service.execute(
        plan.experiment_id,
        phase="screen",
        authorization=harness.authorization,
        quote=harness.quote,
        expected_sha256=harness.authorization.authorization_sha256,
    )
    assert last["execution_state"] != "FAILED", last
    for _ in range(24):
        if last["execution_state"] == "SCREEN_REVIEW":
            break
        last = harness.service.resume(
            plan.experiment_id,
            authorization=harness.authorization,
            quote=harness.quote,
            expected_sha256=harness.authorization.authorization_sha256,
            phase="screen",
        )
        harness.clock.advance(seconds=1)
    assert last["execution_state"] == "SCREEN_REVIEW", last["execution_state"]
    record = _live_record(db, plan.experiment_id)
    assert record, "the live capture must be recorded durably"
    assert record["mapped_sha256"] == harness.seal.node_schema_sha256
    assert record["acquisition_id"]
    # The raw JSON itself is in the object store.
    stored = [
        path
        for path in (tmp_path / "office-objects").rglob("*.json")
        if "live-schema" in path.parts
    ]
    assert stored, "the raw live schema JSON must be in the object store"
