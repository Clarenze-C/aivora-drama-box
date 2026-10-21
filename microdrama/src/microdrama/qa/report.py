"""QA run persistence and report helpers (T017).

Findings persist as ``qa_findings`` rows (the frozen contract table: append-oriented,
body-immutable, coverage/outcome honesty enforced by CHECK constraints) and each run
appends one bounded ``qa.technical.completed`` event carrying the checked coverage
windows — unsampled windows are visible as UNSAMPLED/UNAVAILABLE, so "checked" and
"not checked" stay distinguishable after a restart. Finding ids are deterministic
per run content, so an identical run replays without duplicating rows.

``qa_report`` is the read-only view T018/T030 consume: latest-cycle findings with
stable check ids, the blocking set, and the explicit unknown set.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from microdrama.contracts.enums import QAOutcome
from microdrama.contracts.errors import Conflict
from microdrama.contracts.primitives import Identifier
from microdrama.contracts.qa import CoverageWindow, QAFinding
from microdrama.core.events import append_event
from microdrama.persistence.db import Database, Tx, insert_row, jsonb
from microdrama.qa.coverage import summarize_coverage
from microdrama.qa.models import QAReportView

RUN_EVENT = "qa.technical.completed"
_BAD_OUTCOMES = (QAOutcome.REPAIRABLE, QAOutcome.BLOCKED, QAOutcome.UNKNOWN)


def persist_run(
    tx: Tx,
    *,
    episode_id: UUID,
    findings: list[QAFinding],
    coverage: list[CoverageWindow],
    payload: dict[str, Any],
    now: datetime,
    correlation_id: UUID,
) -> int:
    """Insert new findings (cycle = latest + 1) and append the run event, in one tx."""
    cycle_row = tx.fetchone(
        "SELECT COALESCE(MAX(qa_cycle), 0) + 1 AS cycle FROM qa_findings WHERE episode_id = %s",
        (episode_id,),
    )
    cycle = int(cycle_row["cycle"])
    for finding in findings:
        existing = tx.fetchone("SELECT body FROM qa_findings WHERE id = %s", (finding.finding_id,))
        if existing is not None:
            stored = QAFinding.model_validate(existing["body"])
            if stored == finding:
                continue  # identical content from a prior cycle: nothing new to write
            raise Conflict(
                "deterministic finding id collides with different content",
                finding_id=str(finding.finding_id),
            )
        insert_row(
            tx,
            "qa_findings",
            {
                "id": finding.finding_id,
                "episode_id": episode_id,
                "qa_cycle": cycle,
                "asset_id": finding.asset_id,
                "start_ms": finding.start_ms,
                "end_ms": finding.end_ms,
                "check_id": finding.check_id,
                "check_family": finding.check_family.value,
                "source_pass": finding.source_pass.value,
                "severity": finding.severity.value,
                "coverage": finding.coverage.value,
                "outcome": finding.outcome.value,
                "body": jsonb(finding),
                "resolution": "OPEN",
            },
            returning="id",
        )
    payload = {**payload, "qa_cycle": cycle, "coverage": summarize_coverage(coverage)}
    append_event(
        tx,
        aggregate_type="episode",
        aggregate_id=episode_id,
        event_type=RUN_EVENT,
        payload=payload,
        correlation_id=correlation_id,
        occurred_at=now,
    )
    return cycle


def find_run(tx_db: Database, episode_id: UUID, run_key: str) -> dict[str, Any] | None:
    """The persisted run event for this exact run key, if one exists (replay check)."""
    with tx_db.transaction(readonly=True) as tx:
        return tx.fetchone(
            "SELECT payload FROM domain_events WHERE aggregate_id = %s AND event_type = %s "
            "AND payload ->> 'run_key' = %s LIMIT 1",
            (episode_id, RUN_EVENT, run_key),
        )


def load_findings(db: Database, episode_id: UUID, *, cycle: int | None = None) -> list[QAFinding]:
    with db.transaction(readonly=True) as tx:
        if cycle is None:
            row = tx.fetchone(
                "SELECT MAX(qa_cycle) AS cycle FROM qa_findings WHERE episode_id = %s",
                (episode_id,),
            )
            if row is None or row["cycle"] is None:
                return []
            cycle = int(row["cycle"])
        rows = tx.fetchall(
            "SELECT body FROM qa_findings WHERE episode_id = %s AND qa_cycle = %s ORDER BY id",
            (episode_id, cycle),
        )
    return [QAFinding.model_validate(row["body"]) for row in rows]


def load_cycles(db: Database, episode_id: UUID) -> list[int]:
    with db.transaction(readonly=True) as tx:
        rows = tx.fetchall(
            "SELECT DISTINCT qa_cycle AS cycle FROM qa_findings WHERE episode_id = %s "
            "ORDER BY cycle",
            (episode_id,),
        )
    return [int(row["cycle"]) for row in rows]


def load_run_coverage(db: Database, episode_id: UUID, run_key: str) -> list[CoverageWindow]:
    """Coverage windows persisted on the run event (the checked-window record)."""
    row = find_run(db, episode_id, run_key)
    if row is None:
        return []
    payload = dict(row["payload"])
    coverage: list[CoverageWindow] = []
    for family, summary in (payload.get("coverage") or {}).items():
        from microdrama.contracts.enums import CheckFamily

        for start_ms, end_ms, status in summary.get("windows", []):
            coverage.append(
                CoverageWindow(
                    asset_id=UUID(payload["asset_id"]),
                    check_family=CheckFamily(family),
                    start_ms=start_ms,
                    end_ms=end_ms,
                    status=status,
                )
            )
    return coverage


def green_summary(
    findings: list[QAFinding], critical_check_ids: tuple[str, ...]
) -> tuple[bool, list[Identifier], list[Identifier]]:
    """(all green, blocking check ids, unknown check ids) for one cycle's findings.

    A critical check is green only when it has a PASS finding and no bad-outcome
    finding; a critical check that never emitted anything was not run and is not
    green either. Blocking follows the frozen contract (CRITICAL severity or BLOCKED
    outcome) across ALL findings, not only the configured critical set.
    """
    blocking = sorted({f.check_id for f in findings if f.blocks_release})
    unknown = sorted({f.check_id for f in findings if f.outcome is QAOutcome.UNKNOWN})
    all_green = not any(f.blocks_release for f in findings)
    for check_id in critical_check_ids:
        mine = [f for f in findings if f.check_id == check_id]
        if not mine:
            all_green = False
            continue
        if not any(f.outcome is QAOutcome.PASS for f in mine) or any(
            f.outcome in _BAD_OUTCOMES for f in mine
        ):
            all_green = False
    return all_green, blocking, unknown


def build_report_view(
    db: Database, episode_id: UUID, *, critical_check_ids: tuple[str, ...]
) -> QAReportView:
    cycles = load_cycles(db, episode_id)
    findings = load_findings(db, episode_id) if cycles else []
    all_green, blocking, unknown = green_summary(findings, critical_check_ids)
    return QAReportView(
        episode_id=episode_id,
        cycles=cycles,
        findings=findings,
        critical_check_ids=list(critical_check_ids),
        all_checks_green=all_green,
        blocking_check_ids=blocking,
        unknown_check_ids=unknown,
    )


__all__ = [
    "RUN_EVENT",
    "build_report_view",
    "find_run",
    "green_summary",
    "load_cycles",
    "load_findings",
    "load_run_coverage",
    "persist_run",
]
