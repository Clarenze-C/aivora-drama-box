"""Technical QA service (T017): one ``run_episode_qa`` over the actual exported media.

Flow: read the episode's CURRENT script (the expected side — critical terms, intended
speakers) and the asset under review; refuse oversized media before any ffmpeg work
(CPU bound); replay an identical run from its persisted findings; stage the media
bytes into a tmp workdir and verify their sha256 (the analyzed bytes ARE the
evidence); run the ffmpeg detectors (decode/streams/duration/audio/silence/peaks/
black/freeze) and pull the embedded captions out of the actual file; observe speech
and identities through the ``MediaObserver`` seam — the only metered step, reserved
in the QA_CAPTIONS category before dispatch and settled after it, with a failed
observation keeping its charge; compare observed against expected into typed
findings (flag or UNKNOWN — a pristine script never makes an unchecked or defective
media green); persist findings plus a bounded coverage event in one transaction.

Idempotency follows the house pattern: a deterministic run key (episode + asset sha +
script hash + config fingerprint) and deterministic finding ids make an identical
rerun a REPLAY that returns the stored findings without re-running anything.
"""

from __future__ import annotations

import threading
import uuid
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Protocol
from uuid import UUID

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.cost import (
    BudgetReservationRequest,
    ExposureCeilings,
    UsageReceipt,
)
from microdrama.contracts.enums import (
    AssetKind,
    BudgetCategory,
    BudgetScopeKind,
    CheckFamily,
    CostBasis,
    CoverageStatus,
    EvidenceSource,
    Provenance,
    QAOutcome,
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
    ServiceUnavailable,
)
from microdrama.contracts.hashing import canonical_hash, file_sha256
from microdrama.contracts.infra import Clock, IdGenerator, ObjectStore
from microdrama.contracts.media import AssetDescriptor, CaptionTrack
from microdrama.contracts.qa import CoverageWindow
from microdrama.contracts.season import Script, SeasonScope
from microdrama.editing.ffmpeg import FFmpegRunner, stage_bytes
from microdrama.persistence.db import Database
from microdrama.qa.audio import (
    SOURCE_UNREGISTERED,
    MediaObservation,
    MediaObserver,
    align_lines,
    caption_speech_findings,
    speech_findings,
)
from microdrama.qa.config import QAConfig
from microdrama.qa.coverage import partition_coverage
from microdrama.qa.models import (
    QA_NAMESPACE,
    QARunStatus,
    TechnicalQARun,
    build_finding,
)
from microdrama.qa.report import (
    build_report_view,
    find_run,
    green_summary,
    load_findings,
    load_run_coverage,
    persist_run,
)
from microdrama.qa.technical import (
    MediaAnalysisError,
    caption_findings,
    detect_black_windows,
    detect_frozen_windows,
    detect_silence_windows,
    ensure_video_asset,
    extract_embedded_captions,
    gather_facts,
    measure_peak_db,
    technical_coverage,
    technical_findings,
)
from microdrama.qa.visual import identity_findings, prop_findings

OBSERVE_OPERATION = "qa.observe_media"
OBSERVE_PROVIDER = "qa-offline-observer"
_SUFFIX = {AssetKind.VIDEO: "media.mp4", AssetKind.AUDIO: "media.wav"}


class CaptionSource(Protocol):
    """T015's editing readers this lane consumes (structural, read-only)."""

    def captions(self, episode_id: UUID) -> list[CaptionTrack]: ...

    def stale_caption_cues(self, episode_id: UUID) -> list[str]: ...


class TechnicalQAService:
    """Technical/audio/visual QA over actual media. Construct once per process."""

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
        caption_source: CaptionSource | None = None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._ids = ids
        self._settings = settings
        self._budget = budget
        self._store = store
        self._config = config or QAConfig()
        self._observer = observer
        self._caption_source = caption_source
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

    def _asset(self, asset_id: UUID) -> tuple[AssetDescriptor, str]:
        row = self._row("SELECT descriptor, object_key FROM assets WHERE id = %s", (asset_id,))
        if row is None:
            raise NotFound("asset under review not found", asset_id=str(asset_id))
        return AssetDescriptor.model_validate(row["descriptor"]), row["object_key"]

    def qa_report(self, episode_id: UUID):
        """Persisted findings/coverage view for T018/T030 (read-only)."""
        return build_report_view(
            self._db, episode_id, critical_check_ids=self._config.critical_check_ids
        )

    # --- the run ----------------------------------------------------------------------

    def run_episode_qa(self, episode_id: UUID, *, asset_id: UUID) -> TechnicalQARun:
        episode = self._row("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))
        if episode is None:
            raise NotFound("episode not found", episode_id=str(episode_id))
        script = self._script(episode_id)
        descriptor, object_key = self._asset(asset_id)
        ensure_video_asset(descriptor)
        if descriptor.media is None or descriptor.media.duration_ms <= 0:
            raise Conflict("asset under review carries no measured duration")
        if descriptor.media.duration_ms > self._config.max_media_duration_ms:
            raise SchemaInvalid(
                "media duration exceeds the configured QA ceiling (CPU bound)",
                duration_ms=descriptor.media.duration_ms,
                ceiling_ms=self._config.max_media_duration_ms,
            )
        run_key = _run_key(episode_id, descriptor, script, self._config)
        replay = self._replay(episode_id, asset_id, descriptor, run_key)
        if replay is not None:
            return replay

        with TemporaryDirectory(prefix="md-qa-") as tmp:
            workdir = Path(tmp)
            runner = FFmpegRunner(workdir=workdir, timeout_ms=self._config.ffmpeg_timeout_ms)
            staged = stage_bytes(
                runner,
                name=_SUFFIX[descriptor.asset_kind],
                data=self._store.get_bytes(object_key),
            )
            actual_sha = file_sha256(str(staged))
            if actual_sha != descriptor.sha256:
                raise Conflict(
                    "stored bytes do not hash to the registered asset sha256",
                    expected=descriptor.sha256[:16],
                    actual=actual_sha[:16],
                )
            facts = gather_facts(runner, staged, descriptor)
            black = frozen = silence = None
            peak_db = None
            embedded: list | None = None
            if facts.media is not None:
                try:
                    if facts.media.has_video:
                        black = detect_black_windows(workdir, staged, self._config)
                        frozen = detect_frozen_windows(workdir, staged, self._config)
                    if facts.media.has_audio:
                        silence = detect_silence_windows(workdir, staged, self._config)
                        peak_db = measure_peak_db(workdir, staged, self._config)
                    embedded = extract_embedded_captions(runner, staged)
                except MediaAnalysisError as exc:
                    raise ServiceUnavailable(
                        "ffmpeg detector failed; no QA claim was made", detail=str(exc)
                    ) from exc

            reservation = self._maybe_reserve(episode_id, descriptor, facts.duration_ms)
            observation, settled_micro_usd = self._observe(
                episode_id, descriptor, staged, facts.duration_ms, reservation
            )

            findings: list = technical_findings(
                run_key=run_key,
                episode_id=episode_id,
                descriptor=descriptor,
                facts=facts,
                config=self._config,
                black=black,
                frozen=frozen,
                silence=silence,
                peak_db=peak_db,
            )
            alignments = align_lines(
                script, observation, align_min_ratio=self._config.align_min_ratio
            )
            findings += speech_findings(
                run_key=run_key,
                episode_id=episode_id,
                asset_id=asset_id,
                asset_sha256=descriptor.sha256,
                alignments=alignments,
                observation=observation,
                duration_ms=facts.duration_ms,
            )
            findings += identity_findings(
                run_key=run_key,
                episode_id=episode_id,
                asset_id=asset_id,
                asset_sha256=descriptor.sha256,
                alignments=alignments,
                observation=observation,
            )
            findings += prop_findings(
                run_key=run_key,
                episode_id=episode_id,
                asset_id=asset_id,
                duration_ms=facts.duration_ms,
            )
            findings, notes = self._caption_checks(
                run_key, episode_id, asset_id, descriptor, script, facts, observation,
                embedded, findings,
            )  # fmt: skip
            findings = _dedupe(findings)
            coverage = self._coverage(descriptor, facts, observation, embedded is not None)
            all_green, blocking, unknown = green_summary(findings, self._config.critical_check_ids)
            now = self._now()
            correlation = self._new_id()
            codes = Counter(f.check_id for f in findings)
            with self._db.transaction() as tx:
                cycle = persist_run(
                    tx,
                    episode_id=episode_id,
                    findings=findings,
                    coverage=coverage,
                    payload={
                        "run_key": run_key,
                        "asset_id": str(asset_id),
                        "asset_sha256": descriptor.sha256[:16],
                        "duration_ms": facts.duration_ms,
                        "all_checks_green": all_green,
                        "blocking_check_ids": blocking,
                        "unknown_check_ids": unknown,
                        "finding_codes": dict(sorted(codes.items())),
                        "reservation_id": str(reservation.id) if reservation else None,
                        "settled_micro_usd": settled_micro_usd,
                        "notes": notes[:5],
                    },
                    now=now,
                    correlation_id=correlation,
                )
            return TechnicalQARun(
                episode_id=episode_id,
                asset_id=asset_id,
                asset_sha256=descriptor.sha256,
                run_key=run_key,
                qa_cycle=cycle,
                status=QARunStatus.COMPLETED,
                duration_ms=facts.duration_ms,
                findings=findings,
                coverage=coverage,
                all_checks_green=all_green,
                blocking_check_ids=blocking,
                unknown_check_ids=unknown,
                reservation_id=reservation.id if reservation else None,
                settled_micro_usd=settled_micro_usd,
                notes=notes,
            )

    # --- observation (the metered step) -------------------------------------------------

    def _observe(
        self,
        episode_id: UUID,
        descriptor: AssetDescriptor,
        staged: Path,
        duration_ms: int,
        reservation: Any,
    ) -> tuple[MediaObservation, int]:
        if self._observer is None:
            coverage: list[CoverageWindow] = [
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
            return (
                MediaObservation(
                    coverage=coverage,
                    provenance=Provenance.DERIVED_LOCAL,
                    source_label=SOURCE_UNREGISTERED,
                ),
                0,
            )
        try:
            observation = self._observer.observe(
                asset_id=descriptor.asset_id,
                asset_sha256=descriptor.sha256,
                media_path=staged,
                duration_ms=duration_ms,
            )
        except Exception as exc:  # the model call was dispatched; its charge is kept
            settled = self._settle_failure(reservation, episode_id, duration_ms)
            raise ProviderError(
                "observation step failed after dispatch; the charge is kept",
                provider=OBSERVE_PROVIDER,
                settled_micro_usd=settled,
            ) from exc
        settled = self._settle_success(reservation, episode_id, duration_ms)
        return observation, settled

    # --- budget hook ---------------------------------------------------------------------

    def _maybe_reserve(
        self, episode_id: UUID, descriptor: AssetDescriptor, duration_ms: int
    ) -> Any:
        price = self._config.observer_price
        if price is None:
            return None
        season_row = self._row("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))
        if season_row is None:
            raise NotFound("episode vanished before reservation")
        seconds = max(1, -(-duration_ms // 1000))
        now = self._now()
        # A retried paid observation is a NEW step: the semantic key versions past any
        # reservation that already settled (an ACTIVE one is reused by the budget
        # service's own idempotent replay — that path is untouched).
        base = f"qa:{episode_id}:observe:{descriptor.sha256[:16]}"
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
                request_id=_deterministic_id("qareq", semantic_key),
                semantic_key=semantic_key,
                scope_kind=BudgetScopeKind.EPISODE,
                episode_id=episode_id,
                category=BudgetCategory.QA_CAPTIONS,
                queue=QueueName.PRODUCTION,
                provider=OBSERVE_PROVIDER,
                operation_kind=OBSERVE_OPERATION,
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

    # --- captions / coverage --------------------------------------------------------------

    def _caption_checks(  # noqa: PLR0913 - one assembly step, single responsibility
        self,
        run_key: str,
        episode_id: UUID,
        asset_id: UUID,
        descriptor: AssetDescriptor,
        script: Script,
        facts: Any,
        observation: MediaObservation,
        embedded: list | None,
        findings: list,
    ) -> tuple[list, list[str]]:
        notes: list[str] = []
        if self._config.observer_price is None:
            notes.append("offline observation is free; no paid step configured")
        sources: list[tuple[str, list]] = []
        if embedded is not None:
            sources.append(("embedded", embedded))
        else:
            notes.append("no embedded caption track in the media")
        if self._caption_source is not None:
            for track in self._caption_source.captions(episode_id):
                sources.append((f"track:{track.locale}", list(track.cues)))
            stale = self._caption_source.stale_caption_cues(episode_id)
            if stale:
                findings.append(
                    build_finding(
                        run_key=run_key,
                        episode_id=episode_id,
                        asset_id=asset_id,
                        start_ms=0,
                        end_ms=facts.duration_ms,
                        check_id="caption.cue_stale",
                        family=CheckFamily.CAPTION,
                        severity=Severity.MAJOR,
                        outcome=QAOutcome.REPAIRABLE,
                        coverage=CoverageStatus.CHECKED,
                        expected="caption cues derive from the current line audio",
                        observed=f"{len(stale)} stale cue ids: {', '.join(stale[:8])}",
                        evidence_source=EvidenceSource.MEASURED_BENCHMARK,
                        evidence_ref=f"stale-cues:{descriptor.sha256[:16]}",
                        evidence_note="T015 stale_caption_cues seam (line audio changed)",
                        provenance=Provenance.DERIVED_LOCAL,
                        repair_targets=[RepairTarget.CAPTION],
                    )
                )
        for source_label, cues in sources:
            findings += caption_findings(
                run_key=run_key,
                episode_id=episode_id,
                asset_id=asset_id,
                asset_sha256=descriptor.sha256,
                cues=cues,
                duration_ms=facts.duration_ms,
                script=script,
                config=self._config,
                source_label=source_label,
            )
            findings += caption_speech_findings(
                run_key=run_key,
                episode_id=episode_id,
                asset_id=asset_id,
                asset_sha256=descriptor.sha256,
                cues=cues,
                observation=observation,
                source_label=source_label,
            )
        return findings, notes

    def _coverage(
        self,
        descriptor: AssetDescriptor,
        facts: Any,
        observation: MediaObservation,
        captions_found: bool,
    ) -> list[CoverageWindow]:
        windows: list[CoverageWindow] = []
        for family_windows in technical_coverage(descriptor.asset_id, facts, descriptor).values():
            windows += family_windows
        windows += observation.coverage
        windows += partition_coverage(
            descriptor.asset_id,
            CheckFamily.CAPTION,
            max(facts.duration_ms, 1),
            ((0, facts.duration_ms),) if captions_found else (),
            outside=CoverageStatus.UNAVAILABLE,
            note=None if captions_found else "no caption track found in the media",
        )
        return windows

    # --- idempotency -----------------------------------------------------------------------

    def _replay(
        self, episode_id: UUID, asset_id: UUID, descriptor: AssetDescriptor, run_key: str
    ) -> TechnicalQARun | None:
        row = find_run(self._db, episode_id, run_key)
        if row is None:
            return None
        payload = dict(row["payload"])
        cycle = int(payload["qa_cycle"])
        findings = load_findings(self._db, episode_id, cycle=cycle)
        coverage = load_run_coverage(self._db, episode_id, run_key)
        all_green, blocking, unknown = green_summary(findings, self._config.critical_check_ids)
        return TechnicalQARun(
            episode_id=episode_id,
            asset_id=asset_id,
            asset_sha256=descriptor.sha256,
            run_key=run_key,
            qa_cycle=cycle,
            status=QARunStatus.REPLAYED,
            duration_ms=int(payload.get("duration_ms", 0)),
            findings=findings,
            coverage=coverage,
            all_checks_green=all_green,
            blocking_check_ids=blocking,
            unknown_check_ids=unknown,
            reservation_id=None,
            settled_micro_usd=0,
            notes=["identical run already persisted; nothing re-analyzed"],
        )


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
        receipt_id=uuid.uuid5(
            QA_NAMESPACE, f"qareceipt:{reservation.semantic_key}:{suffix}:{units}"
        ),
        provider=OBSERVE_PROVIDER,
        provider_receipt_id=f"qa-observe-{suffix}:{reservation.id}",
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


def _run_key(
    episode_id: UUID, descriptor: AssetDescriptor, script: Script, config: QAConfig
) -> str:
    return canonical_hash(
        {
            "episode": str(episode_id),
            "asset": descriptor.sha256,
            "script": canonical_hash(script),
            "config": _config_fingerprint(config),
            "lane": "qa.technical",
        }
    )


def _deterministic_id(kind: str, key: str) -> UUID:
    return uuid.uuid5(QA_NAMESPACE, f"{kind}:{key}")


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


def _dedupe(findings: list) -> list:
    seen: set[UUID] = set()
    out = []
    for finding in findings:
        if finding.finding_id in seen:
            continue
        seen.add(finding.finding_id)
        out.append(finding)
    return out


def build_technical_qa_service(
    db: Database,
    clock: Clock,
    ids: IdGenerator,
    settings: Settings,
    *,
    budget: BudgetService,
    store: ObjectStore,
    config: QAConfig | None = None,
    observer: MediaObserver | None = None,
    caption_source: CaptionSource | None = None,
) -> TechnicalQAService:
    """Composition-time factory (the integrator registers routes/jobs, not this module)."""
    return TechnicalQAService(
        db,
        clock,
        ids,
        settings,
        budget=budget,
        store=store,
        config=config,
        observer=observer,
        caption_source=caption_source,
    )


__all__ = [
    "OBSERVE_OPERATION",
    "OBSERVE_PROVIDER",
    "CaptionSource",
    "TechnicalQAService",
    "build_technical_qa_service",
]
