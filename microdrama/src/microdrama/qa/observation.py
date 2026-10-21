"""Blind observation, Pass A of the observation-first QA lane (T018; IMP-04/AT-06).

The actual media is observed and transcribed BEFORE any intended answer is consulted,
through T017's ``MediaObserver`` seam in a call of its own. The Pass A input builder
(``build_observation_request``) can carry actual media and NEUTRAL questions only:
the frozen ``ObservationRequest`` contract has no field for script text, expected
terms or canon facts, ``screen_for_intended_content`` refuses a question that quotes
any of them, and the request identity (its hash) is derived from the media and the
questions alone — two different scripts produce the byte-identical Pass A request.

The result freezes as one append-only ``qa_observations`` row (the table rejects
UPDATE/DELETE at the database level; a re-freeze with different content under the
same request id is a typed ``IdempotencyConflict``), carrying the request identity
hash, the media sha256s and the full ``contracts.ObservationReport``. Pass B
(``microdrama.qa.comparison``) reads that row read-only and compares it against the
script/canon/anchors; nothing can rewrite the first report to agree with the script.

Costs (``QAConfig.observer_price``, consumed from T017): unset (default) the offline
observation is free and nothing is reserved; with a price a real QA_CAPTIONS
reservation is held BEFORE the observer is dispatched and settled after it, and a
failed observation KEEPS its charge (settled at the held worst case, never released).
A retry is a new versioned reservation; an identical completed request replays from
the frozen row and charges nothing.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
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
    Provenance,
    QueueName,
    ReceiptKind,
)
from microdrama.contracts.errors import (
    Conflict,
    IdempotencyConflict,
    NotFound,
    PolicyDenied,
    ProviderError,
    SchemaInvalid,
)
from microdrama.contracts.hashing import canonical_hash, file_sha256
from microdrama.contracts.infra import Clock, IdGenerator, ObjectStore
from microdrama.contracts.media import AssetDescriptor
from microdrama.contracts.primitives import ContractModel, MicroUSD, ShortText
from microdrama.contracts.qa import (
    MediaUnderReview,
    NeutralQuestion,
    Observation,
    ObservationReport,
    ObservationRequest,
    SamplingPlan,
)
from microdrama.contracts.season import Script, SeasonScope
from microdrama.core.events import append_event
from microdrama.editing.ffmpeg import FFmpegRunner, stage_bytes
from microdrama.persistence.db import Database, insert_row, jsonb
from microdrama.qa.audio import SOURCE_UNREGISTERED, MediaObservation, MediaObserver
from microdrama.qa.config import QAConfig
from microdrama.qa.coverage import partition_coverage, summarize_coverage
from microdrama.qa.models import ObservedIdentity
from microdrama.qa.service import OBSERVE_PROVIDER
from microdrama.qa.technical import ensure_video_asset

PASS_A_EVENT = "qa.observation.frozen"
PASS_A_OPERATION = "qa.observe_blind"
T018_NAMESPACE = uuid5(UUID(int=0), "https://microdrama.invalid/ns/qa-observation-first")

# Neutral question ids (stable): what to look at, never what to expect.
Q_TRANSCRIPT = "q-transcript-th"
Q_IDENTITY = "q-visible-characters"
Q_TEXT = "q-onscreen-text"
Q_SOURCE = "q-observation-source"

_DEFAULT_QUESTIONS: tuple[tuple[str, str], ...] = (
    (
        Q_TRANSCRIPT,
        "Transcribe every spoken line in this media in the language it is spoken "
        "(th-TH), with its time range and the speaker label as heard.",
    ),
    (Q_IDENTITY, "For each time range, list which distinct characters are visible on screen."),
    (Q_TEXT, "List any on-screen or embedded caption text together with its time range."),
    (Q_SOURCE, "Report which observation source and model configuration produced this report."),
)
_SUFFIX = "media.mp4"


class FrozenObservation(ContractModel):
    """What one ``observe_media`` call returns. Failed attempts keep their spend."""

    request: ObservationRequest
    report: ObservationReport
    replayed: bool
    reservation_id: UUID | None = None
    settled_micro_usd: MicroUSD = 0
    notes: list[ShortText] = Field(default_factory=list)


def _norm(text: str) -> str:
    return "".join(text.split())


def default_neutral_questions() -> list[NeutralQuestion]:
    """The neutral question set: what to observe, never what the script expects."""
    return [NeutralQuestion(question_id=qid, text=text) for qid, text in _DEFAULT_QUESTIONS]


def intended_content_tokens(
    script: Script | None = None, canon_statements: Sequence[str] = ()
) -> list[str]:
    """Every intended-answer string Pass A must never be shown (screening input only)."""
    tokens: list[str] = []
    if script is not None:
        for scene in script.scenes:
            for line in scene.lines:
                tokens.append(line.text_th)
                tokens.append(line.text_en)
                for term in line.critical_terms:
                    tokens.append(term.value_th)
                    if term.value_en is not None:
                        tokens.append(term.value_en)
    tokens.extend(statement for statement in canon_statements if statement)
    return tokens


def screen_for_intended_content(
    questions: Sequence[NeutralQuestion],
    *,
    script: Script | None = None,
    canon_statements: Sequence[str] = (),
) -> None:
    """Refuse (typed) any question that quotes intended script/canon content.

    The frozen contract keeps intended answers out structurally; this screen keeps
    them out at the content level — a neutral question may not smuggle an expected
    line, term or canon fact in its own text.
    """
    banned = intended_content_tokens(script, canon_statements)
    for question in questions:
        text = _norm(question.text)
        for token in banned:
            if _norm(token) and _norm(token) in text:
                raise PolicyDenied(
                    "a neutral question quotes intended content and cannot reach the observer",
                    question_id=question.question_id,
                    matched=token[:80],
                )


def request_fingerprint(questions: Sequence[NeutralQuestion], locale: str) -> str:
    """Fingerprint of the question set. Deliberately script-free."""
    return canonical_hash(
        {"questions": [q.question_id for q in questions], "transcript_locale": locale}
    )


def build_observation_request(
    *,
    episode_id: UUID,
    media: Sequence[MediaUnderReview],
    questions: Sequence[NeutralQuestion],
    request_id: UUID,
    transcript_locale: str = "th-TH",
    sampling: SamplingPlan | None = None,
    reservation_id: UUID | None = None,
) -> ObservationRequest:
    """Build the Pass A input: actual media plus neutral questions, nothing else.

    The contract is closed (extra fields are rejected), so intended answers cannot
    ride along even by accident; ``screen_for_intended_content`` is the content-level
    guard the caller runs on caller-supplied questions before this.
    """
    return ObservationRequest(
        request_id=request_id,
        episode_id=episode_id,
        media=list(media),
        questions=list(questions),
        transcript_locale=transcript_locale,
        sampling=sampling or SamplingPlan(),
        reservation_id=reservation_id,
    )


def request_identity(request: ObservationRequest) -> str:
    """Canonical hash of the request's input identity.

    ``reservation_id`` is dispatch metadata (it differs per paid attempt), not input,
    so it is excluded: an identical rerun keeps the identical request identity.
    """
    return canonical_hash(request.model_dump(mode="json", exclude={"reservation_id"}))


def observation_request_id(episode_id: UUID, sha16: str, fingerprint: str) -> UUID:
    """Deterministic request id over (episode, media, questions). No script component."""
    return uuid5(T018_NAMESPACE, f"obsreq:{episode_id}:{sha16}:{fingerprint}")


# --- frozen-report reads ------------------------------------------------------------------


def _validated(row: dict[str, Any]) -> ObservationReport:
    stored = ObservationReport.model_validate(row["report"])
    if canonical_hash(stored) != row["report_sha256"]:
        raise Conflict(
            "the frozen observation row fails its recorded hash; it may have been tampered with",
            report_id=str(stored.report_id),
        )
    return stored


def frozen_report(db: Database, report_id: UUID) -> ObservationReport:
    """Load one frozen report read-only; a body/hash mismatch is a typed Conflict."""
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT report, report_sha256 FROM qa_observations WHERE id = %s", (report_id,)
        )
    if row is None:
        raise NotFound("no frozen observation report with this id", report_id=str(report_id))
    return _validated(dict(row))


def latest_frozen_report(db: Database, episode_id: UUID) -> ObservationReport | None:
    """The newest frozen report for an episode (read-only, hash-verified)."""
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT report, report_sha256 FROM qa_observations WHERE episode_id = %s "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (episode_id,),
        )
    return None if row is None else _validated(dict(row))


def observed_identities(report: ObservationReport) -> list[ObservedIdentity]:
    """Identity observations decoded back into T017's observed-identity view."""
    out: list[ObservedIdentity] = []
    for entry in report.observations:
        if entry.question_id == Q_IDENTITY and entry.description.startswith("character:"):
            out.append(
                ObservedIdentity(
                    start_ms=entry.start_ms,
                    end_ms=entry.end_ms,
                    character_id=entry.description.removeprefix("character:"),
                )
            )
    return out


def observation_source(report: ObservationReport) -> tuple[str, str | None]:
    """(source_label, fixture_id) as the observer reported about itself."""
    for entry in report.observations:
        if entry.question_id == Q_SOURCE and entry.description.startswith("source:"):
            parts = entry.description.split(":", 2)
            fixture = parts[2].removeprefix("fixture:") if len(parts) == 3 else ""
            return parts[1], fixture or None
    return SOURCE_UNREGISTERED, None


# --- the Pass A service -------------------------------------------------------------------


class ObservationService:
    """Runs and freezes the blind observation. Construct once per process."""

    def __init__(
        self,
        db: Database,
        clock: Clock,
        ids: IdGenerator,
        settings: Settings,
        *,
        budget: BudgetService,
        store: ObjectStore,
        config: QAConfig | None = None,
        observer: MediaObserver | None = None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._ids = ids
        self._settings = settings
        self._budget = budget
        self._store = store
        self._config = config or QAConfig()
        self._observer = observer
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

    # --- reads -----------------------------------------------------------------------

    def _script(self, episode_id: UUID) -> Script:
        row = self._row(
            "SELECT body FROM scripts WHERE episode_id = %s AND status = 'CURRENT'",
            (episode_id,),
        )
        if row is None:
            raise NotFound("episode has no current script", episode_id=str(episode_id))
        return Script.model_validate(row["body"])

    def _canon_statements(self, episode_id: UUID) -> list[str]:
        season = self._row("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))
        if season is None:
            return []
        row = self._row(
            "SELECT facts FROM canon_versions WHERE season_id = %s AND kind = 'PLANNED' "
            "ORDER BY version DESC LIMIT 1",
            (season["season_id"],),
        )
        if row is None or not isinstance(row["facts"], dict):
            return []
        bible = row["facts"].get("bible")
        if not isinstance(bible, dict):
            return []
        return [
            str(item["statement"])
            for item in bible.get("facts", [])
            if isinstance(item, dict) and item.get("statement")
        ]

    def _asset(self, asset_id: UUID) -> tuple[AssetDescriptor, str]:
        row = self._row("SELECT descriptor, object_key FROM assets WHERE id = %s", (asset_id,))
        if row is None:
            raise NotFound("asset under observation not found", asset_id=str(asset_id))
        return AssetDescriptor.model_validate(row["descriptor"]), row["object_key"]

    # --- the blind observation ---------------------------------------------------------

    def observe_media(
        self,
        episode_id: UUID,
        *,
        asset_id: UUID,
        questions: Sequence[NeutralQuestion] | None = None,
    ) -> FrozenObservation:
        """One Pass A call: build (blind) → replay-check → reserve → dispatch → freeze."""
        episode = self._row("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))
        if episode is None:
            raise NotFound("episode not found", episode_id=str(episode_id))
        descriptor, object_key = self._asset(asset_id)
        ensure_video_asset(descriptor)
        if descriptor.media is None or descriptor.media.duration_ms <= 0:
            raise Conflict("asset under observation carries no measured duration")
        if descriptor.media.duration_ms > self._config.max_media_duration_ms:
            raise SchemaInvalid(
                "media duration exceeds the configured QA ceiling (CPU bound)",
                duration_ms=descriptor.media.duration_ms,
                ceiling_ms=self._config.max_media_duration_ms,
            )

        notes: list[str] = []
        if questions is None:
            questions = default_neutral_questions()
        else:
            # Screening input only: the script is consulted to REFUSE a leaking
            # question, never copied into the request.
            screen_for_intended_content(
                questions,
                script=self._script(episode_id),
                canon_statements=self._canon_statements(episode_id),
            )
            notes.append("caller-supplied questions screened against intended content")
        question_list = list(questions)
        duration_ms = descriptor.media.duration_ms
        request_id = observation_request_id(
            episode_id, descriptor.sha256[:16], request_fingerprint(question_list, "th-TH")
        )
        request = build_observation_request(
            episode_id=episode_id,
            media=[
                MediaUnderReview(
                    asset_id=descriptor.asset_id,
                    asset_sha256=descriptor.sha256,
                    duration_ms=duration_ms,
                )
            ],
            questions=question_list,
            request_id=request_id,
        )
        replay = self._replay(request)
        if replay is not None:
            return replay

        with TemporaryDirectory(prefix="md-qa-pass-a-") as tmp:
            runner = FFmpegRunner(workdir=Path(tmp), timeout_ms=self._config.ffmpeg_timeout_ms)
            staged = stage_bytes(runner, name=_SUFFIX, data=self._store.get_bytes(object_key))
            actual_sha = file_sha256(str(staged))
            if actual_sha != descriptor.sha256:
                raise Conflict(
                    "stored bytes do not hash to the registered asset sha256",
                    expected=descriptor.sha256[:16],
                    actual=actual_sha[:16],
                )
            reservation = self._maybe_reserve(episode_id, descriptor, request_id)
            try:
                media_observation = self._dispatch(descriptor, staged, duration_ms)
            except Exception as exc:  # dispatched; the charge is kept
                settled = self._settle_failure(reservation, episode_id, duration_ms)
                raise ProviderError(
                    "blind observation failed after dispatch; the charge is kept",
                    provider=OBSERVE_PROVIDER,
                    settled_micro_usd=settled,
                ) from exc
            settled = self._settle_success(reservation, episode_id, duration_ms)
            if reservation is None:
                notes.append("offline observation is free; no paid step configured")

            paid_request = request.model_copy(
                update={"reservation_id": reservation.id if reservation is not None else None}
            )
            report = self._freeze(episode_id, descriptor, media_observation, paid_request)
            self._persist(episode_id, paid_request, report, reservation, settled)
            return FrozenObservation(
                request=paid_request,
                report=report,
                replayed=False,
                reservation_id=reservation.id if reservation is not None else None,
                settled_micro_usd=settled,
                notes=notes,
            )

    def _dispatch(
        self, descriptor: AssetDescriptor, staged: Path, duration_ms: int
    ) -> MediaObservation:
        if self._observer is None:
            coverage = [
                window
                for family in (CheckFamily.ASR, CheckFamily.VISUAL_IDENTITY)
                for window in partition_coverage(
                    descriptor.asset_id,
                    family,
                    max(duration_ms, 1),
                    (),
                    outside=CoverageStatus.UNAVAILABLE,
                    note="no observation source configured",
                )
            ]
            return MediaObservation(
                coverage=coverage,
                provenance=Provenance.DERIVED_LOCAL,
                source_label=SOURCE_UNREGISTERED,
            )
        return self._observer.observe(
            asset_id=descriptor.asset_id,
            asset_sha256=descriptor.sha256,
            media_path=staged,
            duration_ms=duration_ms,
        )

    def _freeze(
        self,
        episode_id: UUID,
        descriptor: AssetDescriptor,
        observation: MediaObservation,
        request: ObservationRequest,
    ) -> ObservationReport:
        duration_ms = descriptor.media.duration_ms if descriptor.media else 1
        entries: list[Observation] = [
            Observation(
                observation_id=f"obs-identity-{index}",
                question_id=Q_IDENTITY,
                asset_id=descriptor.asset_id,
                start_ms=identity.start_ms,
                end_ms=identity.end_ms,
                description=f"character:{identity.character_id}",
                confidence_bp=None,
            )
            for index, identity in enumerate(observation.identities)
        ]
        entries.append(
            Observation(
                observation_id="obs-source",
                question_id=Q_SOURCE,
                asset_id=descriptor.asset_id,
                start_ms=0,
                end_ms=max(duration_ms, 1),
                description=(
                    f"source:{observation.source_label}:fixture:{observation.fixture_id or 'none'}"
                ),
                confidence_bp=None,
            )
        )
        return ObservationReport(
            report_id=uuid5(T018_NAMESPACE, f"report:{request.request_id}"),
            request_id=request.request_id,
            request_sha256=request_identity(request),
            episode_id=episode_id,
            media_sha256=[descriptor.sha256],
            transcript=list(observation.segments),
            observations=entries,
            coverage=list(observation.coverage),
            model_config_ref=observation.model_ref,
            provenance=observation.provenance,
            frozen_at=self._now(),
        )

    def _persist(
        self,
        episode_id: UUID,
        request: ObservationRequest,
        report: ObservationReport,
        reservation: Any,
        settled_micro_usd: int,
    ) -> None:
        report_sha = canonical_hash(report)
        now = self._now()
        with self._db.transaction() as tx:
            existing = tx.fetchone(
                "SELECT report, report_sha256 FROM qa_observations WHERE request_id = %s",
                (request.request_id,),
            )
            if existing is not None:
                if canonical_hash(ObservationReport.model_validate(existing["report"])) == (
                    report_sha
                ):
                    return  # an identical freeze won the race; the row stands
                raise IdempotencyConflict(
                    "a different observation is already frozen for this request id",
                    request_id=str(request.request_id),
                )
            insert_row(
                tx,
                "qa_observations",
                {
                    "id": report.report_id,
                    "episode_id": episode_id,
                    "request_id": request.request_id,
                    "request_sha256": report.request_sha256,
                    "media_sha256": jsonb(report.media_sha256),
                    "report": jsonb(report),
                    "report_sha256": report_sha,
                    "provenance": report.provenance.value,
                    "frozen_at": report.frozen_at,
                    "created_at": now,
                },
                returning="id",
            )
            append_event(
                tx,
                aggregate_type="episode",
                aggregate_id=episode_id,
                event_type=PASS_A_EVENT,
                payload={
                    "request_id": str(request.request_id),
                    "report_id": str(report.report_id),
                    "request_sha256": report.request_sha256,
                    "report_sha256": report_sha,
                    "asset_sha256": report.media_sha256[0][:16],
                    "duration_ms": max((w.end_ms for w in report.coverage), default=0),
                    "provenance": report.provenance.value,
                    "coverage": summarize_coverage(report.coverage),
                    "reservation_id": str(reservation.id) if reservation else None,
                    "settled_micro_usd": settled_micro_usd,
                },
                correlation_id=self._new_id(),
                occurred_at=now,
            )

    def _replay(self, request: ObservationRequest) -> FrozenObservation | None:
        row = self._row(
            "SELECT report, report_sha256 FROM qa_observations WHERE request_id = %s",
            (request.request_id,),
        )
        if row is None:
            return None
        stored = _validated(dict(row))
        if request_identity(request) != stored.request_sha256:
            raise IdempotencyConflict(
                "this request id is already frozen for a different input",
                request_id=str(request.request_id),
            )
        return FrozenObservation(
            request=request,
            report=stored,
            replayed=True,
            notes=["identical request already frozen; nothing re-observed"],
        )

    # --- budget hook (the paid Pass A step) ---------------------------------------------

    def _maybe_reserve(
        self, episode_id: UUID, descriptor: AssetDescriptor, request_id: UUID
    ) -> Any:
        price = self._config.observer_price
        if price is None:
            return None
        season_row = self._row("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))
        if season_row is None:
            raise NotFound("episode vanished before reservation")
        seconds = max(1, -(-descriptor.media.duration_ms // 1000))  # type: ignore[union-attr]
        now = self._now()
        # A retried paid observation is a NEW step: the semantic key versions past any
        # reservation that already settled (an ACTIVE one is reused by the budget
        # service's own idempotent replay — that path is untouched).
        base = f"qa:{episode_id}:observe_a:{descriptor.sha256[:16]}:{request_id.hex[:8]}"
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
                raise Conflict("season has no approved scope; a paid observation cannot reserve")
            scope = SeasonScope.model_validate(scope_row["scope"])
            self._budget.open_episode_account(
                tx,
                season_id=season_row["season_id"],
                episode_id=episode_id,
                policy=scope.cost_policy,
            )
        return self._budget.reserve(
            BudgetReservationRequest(
                request_id=uuid5(T018_NAMESPACE, f"qareq:{semantic_key}"),
                semantic_key=semantic_key,
                scope_kind=BudgetScopeKind.EPISODE,
                episode_id=episode_id,
                category=BudgetCategory.QA_CAPTIONS,
                queue=QueueName.PRODUCTION,
                provider=OBSERVE_PROVIDER,
                operation_kind=PASS_A_OPERATION,
                price=price,
                ceilings=ExposureCeilings(
                    timeout_ms=self._config.ffmpeg_timeout_ms,
                    max_units=seconds,
                    max_duration_ms=descriptor.media.duration_ms,  # type: ignore[union-attr]
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
            _observation_receipt(
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
        """A failed observation keeps its charge: settle the held worst case, never release."""
        if reservation is None:
            return 0
        price = self._config.observer_price
        if price is None:  # pragma: no cover - a reservation implies a configured price
            raise SchemaInvalid("observer price disappeared between plan and dispatch")
        units = max(1, -(-duration_ms // 1000))
        amount = max(price.unit_price_micro_usd * units, int(reservation.reserved_micro_usd))
        self._budget.record_usage(
            _observation_receipt(
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


def _observation_receipt(
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
        receipt_id=uuid5(T018_NAMESPACE, f"obsreceipt:{reservation.semantic_key}:{suffix}:{units}"),
        provider=OBSERVE_PROVIDER,
        provider_receipt_id=f"qa-observe-a-{suffix}:{reservation.id}",
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


def build_observation_service(
    db: Database,
    clock: Clock,
    ids: IdGenerator,
    settings: Settings,
    *,
    budget: BudgetService,
    store: ObjectStore,
    config: QAConfig | None = None,
    observer: MediaObserver | None = None,
) -> ObservationService:
    """Composition-time factory (the integrator registers routes/jobs, not this module)."""
    return ObservationService(
        db,
        clock,
        ids,
        settings,
        budget=budget,
        store=store,
        config=config,
        observer=observer,
    )


__all__ = [
    "PASS_A_EVENT",
    "PASS_A_OPERATION",
    "Q_IDENTITY",
    "Q_SOURCE",
    "Q_TEXT",
    "Q_TRANSCRIPT",
    "FrozenObservation",
    "ObservationService",
    "build_observation_request",
    "build_observation_service",
    "default_neutral_questions",
    "frozen_report",
    "intended_content_tokens",
    "latest_frozen_report",
    "observation_request_id",
    "observation_source",
    "observed_identities",
    "request_fingerprint",
    "request_identity",
    "screen_for_intended_content",
]
