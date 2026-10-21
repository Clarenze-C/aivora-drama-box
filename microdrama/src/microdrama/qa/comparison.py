"""Comparison, Pass B of the observation-first QA lane (T018; IMP-04/AT-06).

Pass B is a SEPARATE call from Pass A: it receives the FROZEN ``ObservationReport``
(read-only, hash-verified, append-only at the database level) plus the intended
answers Pass A never saw — the current script, the compiled canon and the identity
lock's anchored members — and turns the differences into typed ``QAFinding`` rows
(``source_pass=PASS_B_COMPARISON``). The comparator seam (``MediaComparator``) is a
pure function of the frozen report and the intent: it holds no database handle and
no write path, the report it receives was loaded in a READ ONLY transaction, and the
service re-hashes the report after the comparator returns — an in-memory rewrite
attempt is refused with a typed ``Conflict`` and keeps its charge. A live comparator
provider is integrator-wired; offline the deterministic ``OfflineMediaComparator``
reuses T017's imported check kernels (``align_lines``/``speech_findings``/
``identity_findings``) so both lanes speak the same check ids.

Honesty follows the frozen contract: unchecked coverage is UNKNOWN, never PASS —
UNSAMPLED windows never count as checked, and per-window coverage is persisted both
on the frozen report (Pass A) and on the comparison run event. Costs mirror Pass A:
with ``QAConfig.observer_price`` unset nothing is reserved; with a price every paid
comparison holds a real QA_CAPTIONS reservation before dispatch and a failed attempt
keeps its charge.
"""

from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid5

from pydantic import Field

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.cost import (
    BudgetReservationRequest,
    ExposureCeilings,
    UsageReceipt,
)
from microdrama.contracts.enums import (
    BudgetCategory,
    BudgetScopeKind,
    CheckFamily,
    CostBasis,
    CoverageStatus,
    EvidenceSource,
    Provenance,
    QAOutcome,
    QAPass,
    QueueName,
    ReceiptKind,
    RepairTarget,
    Severity,
)
from microdrama.contracts.errors import (
    Conflict,
    NotFound,
    ProviderError,
    SchemaInvalid,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.infra import Clock, IdGenerator
from microdrama.contracts.primitives import ContractModel, Identifier, MicroUSD, ShortText
from microdrama.contracts.qa import (
    ComparisonRequest,
    CoverageWindow,
    ObservationReport,
    QAFinding,
)
from microdrama.contracts.season import Script, SeasonScope
from microdrama.core.events import append_event
from microdrama.persistence.db import Database, Tx, insert_row, jsonb
from microdrama.qa.audio import SOURCE_FIXTURE, align_lines, speech_findings
from microdrama.qa.config import QAConfig
from microdrama.qa.coverage import coverage_for, summarize_coverage
from microdrama.qa.models import (
    MediaObservation,
    QARunStatus,
    build_finding,
)
from microdrama.qa.observation import (
    T018_NAMESPACE,
    frozen_report,
    latest_frozen_report,
    observation_source,
    observed_identities,
)
from microdrama.qa.report import green_summary, load_findings
from microdrama.qa.visual import identity_findings
from microdrama.references.identity_lock import IdentityLocks

PASS_B_EVENT = "qa.comparison.completed"
PASS_B_OPERATION = "qa.compare_intent"
PASS_B_PROVIDER = "qa-offline-comparator"

# New stable check ids this lane adds (T030 consumes them); the script-side ids
# (asr.*, visual_identity.match) are T017's, reused through the imported kernels.
ANCHOR_CHECK = "visual_identity.anchor_match"
REVEAL_CHECK = "narrative.planned_reveal_absent"

# The critical set THIS lane can satisfy on its own. The final release gate composes
# lanes (T017 technical + T018 comparison) at the integrator; anchor/reveal checks
# surface through severity/blocking instead of this list.
COMPARISON_CRITICAL_IDS: tuple[str, ...] = (
    "asr.critical_term_match",
    "asr.speaker_match",
    "asr.line_present",
    "visual_identity.match",
)

# What "no compiled canon" hashes as: an honest statement of what was consulted.
NO_CANON_PAYLOAD = {"source": "none"}


class LockedAnchor(ContractModel):
    """One identity-lock member the comparison may verify observed identities against."""

    ref_kind: ShortText
    ref_key: ShortText
    version: int
    state: ShortText
    character_key: Identifier | None = None


class ComparisonIntent(ContractModel):
    """Everything Pass B may see: the intended answers Pass A never saw."""

    script: Script
    script_id: UUID
    script_version: int
    script_sha256: str
    canon_version: int
    canon_sha256: str
    planned_reveals: list[ShortText] = Field(default_factory=list)
    identity_lock_id: UUID | None = None
    locked_anchors: list[LockedAnchor] = Field(default_factory=list)
    acceptance_criteria: list[ShortText] = Field(default_factory=list)


class ComparisonRun(ContractModel):
    """What one ``compare`` call returns. Failed attempts keep their spend."""

    request: ComparisonRequest
    episode_id: UUID
    observation_report_id: UUID
    qa_cycle: int
    status: QARunStatus
    findings: list[QAFinding] = Field(default_factory=list)
    coverage: list[CoverageWindow] = Field(default_factory=list)
    all_checks_green: bool
    blocking_check_ids: list[Identifier] = Field(default_factory=list)
    unknown_check_ids: list[Identifier] = Field(default_factory=list)
    reservation_id: UUID | None = None
    settled_micro_usd: MicroUSD = 0
    notes: list[ShortText] = Field(default_factory=list)


def _norm(text: str) -> str:
    return "".join(text.split())


def observation_view(report: ObservationReport) -> MediaObservation:
    """The frozen report as T017's observation view (read-only lens for the kernels)."""
    source_label, fixture_id = observation_source(report)
    return MediaObservation(
        segments=list(report.transcript),
        identities=observed_identities(report),
        coverage=list(report.coverage),
        provenance=report.provenance,
        source_label=source_label,
        fixture_id=fixture_id,
        model_ref=report.model_config_ref,
    )


def _as_pass_b(findings: list[QAFinding]) -> list[QAFinding]:
    """Restamp T017 kernel findings with this lane's pass label (ids are unchanged)."""
    return [f.model_copy(update={"source_pass": QAPass.PASS_B_COMPARISON}) for f in findings]


def _planned_reveals(facts: Any) -> list[str]:
    """PLANNED_REVEAL statements out of a canon row's facts (defensively parsed)."""
    if not isinstance(facts, dict):
        return []
    bible = facts.get("bible")
    if not isinstance(bible, dict):
        return []
    out: list[str] = []
    for item in bible.get("facts", []):
        if isinstance(item, dict) and item.get("kind") == "PLANNED_REVEAL" and item.get(
            "statement"
        ):  # fmt: skip
            out.append(str(item["statement"]))
    return out


class MediaComparator(Protocol):
    """Pass B seam: frozen report + intended answers → typed findings.

    A pure function — no database, no write path; the service persists and meters.
    """

    def compare(
        self,
        *,
        report: ObservationReport,
        intent: ComparisonIntent,
        run_key: str,
        episode_id: UUID,
        asset_id: UUID,
        asset_sha256: str,
        duration_ms: int,
    ) -> list[QAFinding]: ...


class OfflineMediaComparator:
    """The deterministic offline comparator.

    No quality claim is made here (a live labeled Thai evaluation is T031 evidence).
    It reuses T017's check kernels by import so both QA lanes emit the same stable
    check ids, then adds the anchor (identity-lock) and canon (planned-reveal) checks
    that need the intended side.
    """

    def __init__(self, config: QAConfig | None = None) -> None:
        self._config = config or QAConfig()

    def compare(
        self,
        *,
        report: ObservationReport,
        intent: ComparisonIntent,
        run_key: str,
        episode_id: UUID,
        asset_id: UUID,
        asset_sha256: str,
        duration_ms: int,
    ) -> list[QAFinding]:
        view = observation_view(report)
        alignments = align_lines(intent.script, view, align_min_ratio=self._config.align_min_ratio)
        findings = _as_pass_b(
            speech_findings(
                run_key=run_key,
                episode_id=episode_id,
                asset_id=asset_id,
                asset_sha256=asset_sha256,
                alignments=alignments,
                observation=view,
                duration_ms=duration_ms,
            )
        )
        findings += _as_pass_b(
            identity_findings(
                run_key=run_key,
                episode_id=episode_id,
                asset_id=asset_id,
                asset_sha256=asset_sha256,
                alignments=alignments,
                observation=view,
            )
        )
        findings += _as_pass_b(
            self._anchor_findings(
                run_key=run_key,
                episode_id=episode_id,
                asset_id=asset_id,
                report=report,
                intent=intent,
                duration_ms=duration_ms,
            )
        )
        findings += _as_pass_b(
            self._reveal_findings(
                run_key=run_key,
                episode_id=episode_id,
                asset_id=asset_id,
                report=report,
                intent=intent,
                duration_ms=duration_ms,
            )
        )
        return findings

    # --- anchors ------------------------------------------------------------------------

    def _anchor_findings(
        self,
        *,
        run_key: str,
        episode_id: UUID,
        asset_id: UUID,
        report: ObservationReport,
        intent: ComparisonIntent,
        duration_ms: int,
    ) -> list[QAFinding]:
        identities = observed_identities(report)
        fixture = observation_source(report)[0] == SOURCE_FIXTURE
        evidence_note = (
            f"frozen report {report.report_id} compared with identity lock "
            f"{intent.identity_lock_id}"
            if intent.identity_lock_id is not None
            else f"frozen report {report.report_id}; no identity lock provided"
        )

        def add(**kwargs: object) -> QAFinding:
            return build_finding(
                run_key=run_key,
                episode_id=episode_id,
                asset_id=asset_id,
                evidence_source=(
                    EvidenceSource.FAKE_FIXTURE if fixture else EvidenceSource.MEASURED_BENCHMARK
                ),
                evidence_ref=f"anchors:{report.report_id}",
                evidence_note=evidence_note,
                provenance=(Provenance.ORIGINAL_FIXTURE if fixture else Provenance.DERIVED_LOCAL),
                **kwargs,  # type: ignore[arg-type]
            )

        if intent.identity_lock_id is None:
            return [
                add(
                    check_id=ANCHOR_CHECK,
                    family=CheckFamily.VISUAL_IDENTITY,
                    start_ms=0,
                    end_ms=duration_ms,
                    severity=Severity.MAJOR,
                    outcome=QAOutcome.UNKNOWN,
                    coverage=CoverageStatus.UNAVAILABLE,
                    expected="observed identities verified against a locked identity anchor",
                    observed="no identity lock provided to the comparison",
                )
            ]
        faces = {
            anchor.character_key: anchor
            for anchor in intent.locked_anchors
            if anchor.ref_kind == "FACE" and anchor.character_key is not None
        }
        if not identities:
            return [
                add(
                    check_id=ANCHOR_CHECK,
                    family=CheckFamily.VISUAL_IDENTITY,
                    start_ms=0,
                    end_ms=duration_ms,
                    severity=Severity.MAJOR,
                    outcome=QAOutcome.UNKNOWN,
                    coverage=coverage_for(
                        report.coverage, CheckFamily.VISUAL_IDENTITY, 0, max(duration_ms, 1)
                    ),
                    expected="observed identities verified against locked anchors",
                    observed="no identity was observed in the frozen report",
                )
            ]
        out: list[QAFinding] = []
        for identity in identities:
            status = coverage_for(
                report.coverage,
                CheckFamily.VISUAL_IDENTITY,
                identity.start_ms,
                max(identity.end_ms, identity.start_ms + 1),
            )
            member = faces.get(identity.character_id)
            if member is None:
                out.append(
                    add(
                        check_id=ANCHOR_CHECK,
                        family=CheckFamily.VISUAL_IDENTITY,
                        start_ms=identity.start_ms,
                        end_ms=identity.end_ms,
                        severity=Severity.CRITICAL,
                        outcome=QAOutcome.REPAIRABLE,
                        coverage=status,
                        expected=f"a locked FACE anchor for {identity.character_id}",
                        observed=(
                            f"{identity.character_id} appears with no locked anchor "
                            "in the identity lock"
                        ),
                        repair_targets=[RepairTarget.SHOT],
                    )
                )
            elif member.state != "LOCKED":
                out.append(
                    add(
                        check_id=ANCHOR_CHECK,
                        family=CheckFamily.VISUAL_IDENTITY,
                        start_ms=identity.start_ms,
                        end_ms=identity.end_ms,
                        severity=Severity.CRITICAL,
                        outcome=QAOutcome.REPAIRABLE,
                        coverage=status,
                        expected=f"the locked anchor for {identity.character_id} stays LOCKED",
                        observed=f"locked anchor {member.ref_key} is {member.state}",
                        repair_targets=[RepairTarget.SHOT],
                    )
                )
            else:
                out.append(
                    add(
                        check_id=ANCHOR_CHECK,
                        family=CheckFamily.VISUAL_IDENTITY,
                        start_ms=identity.start_ms,
                        end_ms=identity.end_ms,
                        severity=Severity.INFO,
                        outcome=(
                            QAOutcome.PASS
                            if status is CoverageStatus.CHECKED
                            else QAOutcome.UNKNOWN
                        ),
                        coverage=status,
                        expected=f"the locked anchor for {identity.character_id}",
                        observed=(
                            f"identity matches locked anchor {member.ref_key} v{member.version}"
                        ),
                    )
                )
        return out

    # --- canon --------------------------------------------------------------------------

    def _reveal_findings(
        self,
        *,
        run_key: str,
        episode_id: UUID,
        asset_id: UUID,
        report: ObservationReport,
        intent: ComparisonIntent,
        duration_ms: int,
    ) -> list[QAFinding]:
        fixture = observation_source(report)[0] == SOURCE_FIXTURE
        evidence_note = (
            f"frozen report {report.report_id} compared with canon v{intent.canon_version}"
            if intent.planned_reveals
            else f"frozen report {report.report_id}; no compiled canon to compare"
        )

        def add(**kwargs: object) -> QAFinding:
            return build_finding(
                run_key=run_key,
                episode_id=episode_id,
                asset_id=asset_id,
                evidence_source=(
                    EvidenceSource.FAKE_FIXTURE if fixture else EvidenceSource.MEASURED_BENCHMARK
                ),
                evidence_ref=f"canon:{report.report_id}",
                evidence_note=evidence_note,
                provenance=(Provenance.ORIGINAL_FIXTURE if fixture else Provenance.DERIVED_LOCAL),
                **kwargs,  # type: ignore[arg-type]
            )

        if not intent.planned_reveals:
            return [
                add(
                    check_id=REVEAL_CHECK,
                    family=CheckFamily.NARRATIVE,
                    start_ms=0,
                    end_ms=duration_ms,
                    severity=Severity.MAJOR,
                    outcome=QAOutcome.UNKNOWN,
                    coverage=CoverageStatus.UNSAMPLED,
                    expected="the transcript contains none of the canon's planned reveals",
                    observed="no compiled canon; the reveal check was not run",
                )
            ]
        segments = list(report.transcript)
        if not segments:
            return [
                add(
                    check_id=REVEAL_CHECK,
                    family=CheckFamily.NARRATIVE,
                    start_ms=0,
                    end_ms=duration_ms,
                    severity=Severity.MAJOR,
                    outcome=QAOutcome.UNKNOWN,
                    coverage=coverage_for(report.coverage, CheckFamily.ASR, 0, max(duration_ms, 1)),
                    expected="the transcript contains none of the canon's planned reveals",
                    observed="no speech was observed; the reveal check saw nothing",
                )
            ]
        span_start = min(s.start_ms for s in segments)
        span_end = max(s.end_ms for s in segments)
        span_status = coverage_for(report.coverage, CheckFamily.ASR, span_start, span_end)
        out: list[QAFinding] = []
        for statement in intent.planned_reveals:
            leaked = next((s for s in segments if _norm(statement) in _norm(s.text)), None)
            if leaked is not None:
                out.append(
                    add(
                        check_id=REVEAL_CHECK,
                        family=CheckFamily.NARRATIVE,
                        start_ms=leaked.start_ms,
                        end_ms=leaked.end_ms,
                        severity=Severity.CRITICAL,
                        outcome=QAOutcome.REPAIRABLE,
                        coverage=coverage_for(
                            report.coverage, CheckFamily.ASR, leaked.start_ms, leaked.end_ms
                        ),
                        expected="a planned reveal stays unspoken before its episode",
                        observed=f"the transcript speaks the planned reveal: {statement}",
                        repair_targets=[RepairTarget.LINE],
                    )
                )
            else:
                out.append(
                    add(
                        check_id=REVEAL_CHECK,
                        family=CheckFamily.NARRATIVE,
                        start_ms=span_start,
                        end_ms=span_end,
                        severity=Severity.INFO,
                        outcome=(
                            QAOutcome.PASS
                            if span_status is CoverageStatus.CHECKED
                            else QAOutcome.UNKNOWN
                        ),
                        coverage=span_status,
                        expected="a planned reveal stays unspoken before its episode",
                        observed="the transcript does not contain this planned reveal",
                    )
                )
        return out


class ComparisonService:
    """Runs Pass B against a frozen report. Construct once per process."""

    def __init__(
        self,
        db: Database,
        clock: Clock,
        ids: IdGenerator,
        settings: Settings,
        *,
        budget: BudgetService,
        config: QAConfig | None = None,
        comparator: MediaComparator | None = None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._ids = ids
        self._settings = settings
        self._budget = budget
        self._config = config or QAConfig()
        self._comparator = comparator
        self._id_lock = threading.Lock()

    # --- plumbing --------------------------------------------------------------------

    def _new_id(self) -> UUID:
        with self._id_lock:
            return self._ids.new_id()

    def _now(self) -> datetime:
        now = self._clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise SchemaInvalid("clock must return a timezone-aware instant")
        return now

    @property
    def config(self) -> QAConfig:
        return self._config

    def _row(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        with self._db.transaction(readonly=True) as tx:
            return tx.fetchone(sql, params)

    # --- intent (the intended answers; loaded read-only) ---------------------------------

    def _intent(
        self,
        episode_id: UUID,
        season_id: UUID,
        *,
        identity_lock_id: UUID | None,
        acceptance_criteria: Sequence[str],
    ) -> ComparisonIntent:
        with self._db.transaction(readonly=True) as tx:
            script_row = tx.fetchone(
                "SELECT id, version, body FROM scripts WHERE episode_id = %s "
                "AND status = 'CURRENT'",
                (episode_id,),
            )
            if script_row is None:
                raise NotFound("episode has no current script", episode_id=str(episode_id))
            script = Script.model_validate(script_row["body"])
            canon_row = tx.fetchone(
                "SELECT version, facts, facts_hash FROM canon_versions "
                "WHERE season_id = %s AND kind = 'PLANNED' ORDER BY version DESC LIMIT 1",
                (season_id,),
            )
            planned_reveals: list[str] = []
            canon_version = script.canon_version
            canon_sha = canonical_hash(NO_CANON_PAYLOAD)
            if canon_row is not None:
                canon_version = int(canon_row["version"])
                canon_sha = str(canon_row["facts_hash"])
                planned_reveals = _planned_reveals(canon_row["facts"])
                if canon_version != script.canon_version:
                    raise Conflict(
                        "the current script was compiled against a different canon "
                        "version; recompile before comparing",
                        script_canon_version=script.canon_version,
                        canon_version=canon_version,
                    )
            anchors: list[LockedAnchor] = []
            if identity_lock_id is not None:
                lock = tx.fetchone(
                    "SELECT id FROM identity_locks WHERE id = %s", (identity_lock_id,)
                )
                if lock is None:
                    raise NotFound(
                        "identity lock not found", identity_lock_id=str(identity_lock_id)
                    )
                anchors = [
                    LockedAnchor(
                        ref_kind=str(member["ref_kind"]),
                        ref_key=str(member["ref_key"]),
                        version=int(member["version"]),
                        state=str(member["state"]),
                        character_key=member.get("character_key"),
                    )
                    for member in IdentityLocks.members(tx, identity_lock_id)
                ]
        return ComparisonIntent(
            script=script,
            script_id=script_row["id"],
            script_version=int(script_row["version"]),
            script_sha256=canonical_hash(script),
            canon_version=canon_version,
            canon_sha256=canon_sha,
            planned_reveals=planned_reveals,
            identity_lock_id=identity_lock_id,
            locked_anchors=anchors,
            acceptance_criteria=list(acceptance_criteria),
        )

    # --- the comparison ------------------------------------------------------------------

    def compare(
        self,
        episode_id: UUID,
        *,
        observation_report_id: UUID | None = None,
        identity_lock_id: UUID | None = None,
        acceptance_criteria: Sequence[str] = (),
    ) -> ComparisonRun:
        """One Pass B call: load frozen report (read-only) → replay-check → reserve →
        dispatch the comparator → refuse any report rewrite → persist typed findings."""
        episode = self._row("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))
        if episode is None:
            raise NotFound("episode not found", episode_id=str(episode_id))
        if observation_report_id is not None:
            report = frozen_report(self._db, observation_report_id)
            if report.episode_id != episode_id:
                raise Conflict(
                    "the frozen observation belongs to a different episode",
                    observation_episode=str(report.episode_id),
                )
        else:
            report = latest_frozen_report(self._db, episode_id)
            if report is None:
                raise NotFound(
                    "no frozen observation for this episode; run Pass A first",
                    episode_id=str(episode_id),
                )
        intent = self._intent(
            episode_id,
            episode["season_id"],
            identity_lock_id=identity_lock_id,
            acceptance_criteria=acceptance_criteria,
        )
        duration_ms = max((window.end_ms for window in report.coverage), default=1)
        asset_id = report.coverage[0].asset_id
        asset_sha = report.media_sha256[0]
        run_key = _run_key(episode_id, report, intent, self._config)
        replay = self._replay(episode_id, run_key, report, intent)
        if replay is not None:
            return replay

        comparator = self._comparator if self._comparator is not None else OfflineMediaComparator(
            self._config
        )  # fmt: skip
        reservation = self._maybe_reserve(episode_id, report)
        frozen_sha = canonical_hash(report)
        try:
            findings = comparator.compare(
                report=report,
                intent=intent,
                run_key=run_key,
                episode_id=episode_id,
                asset_id=asset_id,
                asset_sha256=asset_sha,
                duration_ms=duration_ms,
            )
        except Exception as exc:  # dispatched; the charge is kept
            settled = self._settle_failure(reservation, episode_id, duration_ms)
            raise ProviderError(
                "comparison failed after dispatch; the charge is kept",
                provider=PASS_B_PROVIDER,
                settled_micro_usd=settled,
            ) from exc
        if canonical_hash(report) != frozen_sha:
            # The comparator tried to rewrite the frozen observation in memory.
            settled = self._settle_failure(reservation, episode_id, duration_ms)
            raise Conflict(
                "the comparator attempted to modify the frozen observation; refused",
                report_id=str(report.report_id),
                settled_micro_usd=settled,
            )
        settled = self._settle_success(reservation, episode_id, duration_ms)
        request = _request(episode_id, report, intent, run_key, reservation)
        notes: list[str] = []
        if reservation is None:
            notes.append("offline comparison is free; no paid step configured")

        all_green, blocking, unknown = green_summary(findings, COMPARISON_CRITICAL_IDS)
        now = self._now()
        correlation = self._new_id()
        codes = Counter(f.check_id for f in findings)
        with self._db.transaction() as tx:
            cycle = _persist_findings(
                tx,
                episode_id=episode_id,
                report=report,
                findings=findings,
                payload={
                    "run_key": run_key,
                    "observation_report_id": str(report.report_id),
                    "observation_report_sha256": frozen_sha,
                    "script_sha256": intent.script_sha256[:16],
                    "canon_version": intent.canon_version,
                    "canon_sha256": intent.canon_sha256[:16],
                    "identity_lock_id": (
                        str(identity_lock_id) if identity_lock_id is not None else None
                    ),
                    "asset_sha256": asset_sha[:16],
                    "duration_ms": duration_ms,
                    "all_checks_green": all_green,
                    "blocking_check_ids": blocking,
                    "unknown_check_ids": unknown,
                    "finding_codes": dict(sorted(codes.items())),
                    "reservation_id": str(reservation.id) if reservation else None,
                    "settled_micro_usd": settled,
                    "notes": notes[:5],
                },
                now=now,
                correlation_id=correlation,
            )
        return ComparisonRun(
            request=request,
            episode_id=episode_id,
            observation_report_id=report.report_id,
            qa_cycle=cycle,
            status=QARunStatus.COMPLETED,
            findings=findings,
            coverage=list(report.coverage),
            all_checks_green=all_green,
            blocking_check_ids=blocking,
            unknown_check_ids=unknown,
            reservation_id=reservation.id if reservation is not None else None,
            settled_micro_usd=settled,
            notes=notes,
        )

    def _replay(
        self,
        episode_id: UUID,
        run_key: str,
        report: ObservationReport,
        intent: ComparisonIntent,
    ) -> ComparisonRun | None:
        row = self._row(
            "SELECT payload FROM domain_events WHERE aggregate_id = %s AND event_type = %s "
            "AND payload ->> 'run_key' = %s LIMIT 1",
            (episode_id, PASS_B_EVENT, run_key),
        )
        if row is None:
            return None
        payload = dict(row["payload"])
        cycle = int(payload["qa_cycle"])
        findings = load_findings(self._db, episode_id, cycle=cycle)
        all_green, blocking, unknown = green_summary(findings, COMPARISON_CRITICAL_IDS)
        return ComparisonRun(
            request=_request(episode_id, report, intent, run_key, None),
            episode_id=episode_id,
            observation_report_id=report.report_id,
            qa_cycle=cycle,
            status=QARunStatus.REPLAYED,
            findings=findings,
            coverage=list(report.coverage),
            all_checks_green=all_green,
            blocking_check_ids=blocking,
            unknown_check_ids=unknown,
            reservation_id=None,
            settled_micro_usd=0,
            notes=["identical comparison already persisted; nothing re-compared"],
        )

    # --- budget hook (the paid Pass B step) ----------------------------------------------

    def _maybe_reserve(self, episode_id: UUID, report: ObservationReport) -> Any:
        price = self._config.observer_price
        if price is None:
            return None
        season_row = self._row("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))
        if season_row is None:
            raise NotFound("episode vanished before reservation")
        duration_ms = max((window.end_ms for window in report.coverage), default=1)
        now = self._now()
        # A retried paid comparison is a NEW step (the version loop below); each call
        # bills over the media duration it re-reads.
        base = f"qa:{episode_id}:compare_b:{report.report_id.hex[:12]}"
        version = 1
        while True:
            existing = self._row(
                "SELECT state FROM reservations WHERE semantic_key = %s",
                (f"{base}:v{version}",),
            )
            if existing is None or existing["state"] == "ACTIVE":
                break
            version += 1
        semantic_key = f"{base}:v{version}"
        with self._db.transaction() as tx:
            scope_row = tx.fetchone(
                "SELECT scope FROM season_proposals WHERE season_id = %s AND status = 'APPROVED'",
                (season_row["season_id"],),
            )
            if scope_row is None:
                raise Conflict("season has no approved scope; a paid comparison cannot reserve")
            scope = SeasonScope.model_validate(scope_row["scope"])
            self._budget.open_episode_account(
                tx,
                season_id=season_row["season_id"],
                episode_id=episode_id,
                policy=scope.cost_policy,
            )
        # A comparator call is billed over the same media duration it re-reads (the
        # price's unit governs; audio/video-second prices need max_duration_ms bound).
        seconds = max(1, -(-duration_ms // 1000))
        return self._budget.reserve(
            BudgetReservationRequest(
                request_id=uuid5(T018_NAMESPACE, f"qareq:{semantic_key}"),
                semantic_key=semantic_key,
                scope_kind=BudgetScopeKind.EPISODE,
                episode_id=episode_id,
                category=BudgetCategory.QA_CAPTIONS,
                queue=QueueName.PRODUCTION,
                provider=PASS_B_PROVIDER,
                operation_kind=PASS_B_OPERATION,
                price=price,
                ceilings=ExposureCeilings(
                    timeout_ms=self._config.ffmpeg_timeout_ms,
                    max_units=seconds,
                    max_duration_ms=duration_ms,
                ),
                worst_case_micro_usd=price.unit_price_micro_usd * seconds,
                expires_at=now + timedelta(milliseconds=self._config.reservation_ttl_ms),
            )
        )

    def _settle_success(self, reservation: Any, episode_id: UUID, duration_ms: int) -> int:
        if reservation is None:
            return 0
        price = self._config.observer_price
        if price is None:  # pragma: no cover - a reservation implies a configured price
            raise SchemaInvalid("observer price disappeared between plan and dispatch")
        units = max(1, -(-duration_ms // 1000))
        amount = price.unit_price_micro_usd * units
        self._budget.record_usage(
            _comparison_receipt(
                reservation=reservation,
                episode_id=episode_id,
                unit=price.unit,
                unit_price_micro_usd=price.unit_price_micro_usd,
                units=units,
                amount_micro_usd=amount,
                suffix="settle",
                observed_at=self._now(),
            )
        )
        return amount

    def _settle_failure(self, reservation: Any, episode_id: UUID, duration_ms: int) -> int:
        """A failed comparison keeps its charge: settle the held worst case, never release."""
        if reservation is None:
            return 0
        price = self._config.observer_price
        if price is None:  # pragma: no cover - a reservation implies a configured price
            raise SchemaInvalid("observer price disappeared between plan and dispatch")
        units = max(1, -(-duration_ms // 1000))
        amount = max(price.unit_price_micro_usd * units, int(reservation.reserved_micro_usd))
        self._budget.record_usage(
            _comparison_receipt(
                reservation=reservation,
                episode_id=episode_id,
                unit=price.unit,
                unit_price_micro_usd=price.unit_price_micro_usd,
                units=units,
                amount_micro_usd=amount,
                suffix="failure",
                observed_at=self._now(),
            )
        )
        return amount


# --- module-level helpers ------------------------------------------------------------------


def _request(
    episode_id: UUID,
    report: ObservationReport,
    intent: ComparisonIntent,
    run_key: str,
    reservation: Any,
) -> ComparisonRequest:
    return ComparisonRequest(
        request_id=uuid5(T018_NAMESPACE, f"cmpreq:{run_key}"),
        episode_id=episode_id,
        observation_report_id=report.report_id,
        observation_report_sha256=canonical_hash(report),
        script_id=intent.script_id,
        script_version=intent.script_version,
        script_sha256=intent.script_sha256,
        canon_version=intent.canon_version,
        canon_sha256=intent.canon_sha256,
        identity_lock_id=intent.identity_lock_id,
        acceptance_criteria=list(intent.acceptance_criteria),
        reservation_id=reservation.id if reservation is not None else None,
    )


def _persist_findings(
    tx: Tx,
    *,
    episode_id: UUID,
    report: ObservationReport,
    findings: list[QAFinding],
    payload: dict[str, Any],
    now: datetime,
    correlation_id: UUID,
) -> int:
    """Insert new findings (cycle = latest + 1) bound to the frozen report, one tx."""
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
                "observation_id": report.report_id,
                "body": jsonb(finding),
                "resolution": "OPEN",
            },
            returning="id",
        )
    body = {
        **payload,
        "qa_cycle": cycle,
        "coverage": summarize_coverage(report.coverage),
    }
    append_event(
        tx,
        aggregate_type="episode",
        aggregate_id=episode_id,
        event_type=PASS_B_EVENT,
        payload=body,
        correlation_id=correlation_id,
        occurred_at=now,
    )
    return cycle


def _run_key(
    episode_id: UUID, report: ObservationReport, intent: ComparisonIntent, config: QAConfig
) -> str:
    return canonical_hash(
        {
            "episode": str(episode_id),
            "report": str(report.report_id),
            "report_sha": canonical_hash(report),
            "script": intent.script_sha256,
            "canon": {"version": intent.canon_version, "sha": intent.canon_sha256},
            "lock": str(intent.identity_lock_id) if intent.identity_lock_id else None,
            "acceptance": list(intent.acceptance_criteria),
            "config": _config_fingerprint(config),
            "lane": "qa.comparison",
        }
    )


def _config_fingerprint(config: QAConfig) -> str:
    payload = asdict(config)
    if config.observer_price is not None:
        payload["observer_price"] = config.observer_price.model_dump(mode="json")
    # Canonical JSON forbids floats; scale the float knobs to exact integers.
    payload = {
        key: (f"e4:{round(value * 10_000)}" if isinstance(value, float) else value)
        for key, value in payload.items()
    }
    return canonical_hash(payload)


def _comparison_receipt(
    *,
    reservation: Any,
    episode_id: UUID,
    unit,
    unit_price_micro_usd: int,
    units: int,
    amount_micro_usd: int,
    suffix: str,
    observed_at: datetime,
) -> UsageReceipt:
    return UsageReceipt(
        receipt_id=uuid5(T018_NAMESPACE, f"cmpreceipt:{reservation.semantic_key}:{suffix}:{units}"),
        provider=PASS_B_PROVIDER,
        provider_receipt_id=f"qa-compare-{suffix}:{reservation.id}",
        kind=ReceiptKind.SETTLEMENT,
        cost_basis=CostBasis.SYNTHETIC_FAKE,
        reservation_id=reservation.id,
        episode_id=episode_id,
        category=BudgetCategory.QA_CAPTIONS,
        amount_micro_usd=amount_micro_usd,
        units=units,
        unit=unit,
        observed_at=observed_at,
        provenance=Provenance.FAKE_SYNTHETIC,
    )


def build_comparison_service(
    db: Database,
    clock: Clock,
    ids: IdGenerator,
    settings: Settings,
    *,
    budget: BudgetService,
    config: QAConfig | None = None,
    comparator: MediaComparator | None = None,
) -> ComparisonService:
    """Composition-time factory (the integrator registers routes/jobs, not this module)."""
    return ComparisonService(
        db,
        clock,
        ids,
        settings,
        budget=budget,
        config=config,
        comparator=comparator,
    )


__all__ = [
    "ANCHOR_CHECK",
    "COMPARISON_CRITICAL_IDS",
    "ComparisonIntent",
    "ComparisonRun",
    "ComparisonService",
    "LockedAnchor",
    "MediaComparator",
    "NO_CANON_PAYLOAD",
    "OfflineMediaComparator",
    "PASS_B_EVENT",
    "PASS_B_OPERATION",
    "PASS_B_PROVIDER",
    "REVEAL_CHECK",
    "build_comparison_service",
    "observation_view",
]
