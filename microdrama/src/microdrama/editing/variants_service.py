"""Variants/covers/hooks service (T016): the step behind ``edit.variants_and_hooks``.

Scope and guarantees (packet T016 / SPEC §9 / IMP-07):

- Capability-aware: every destination variant and cover is planned from the
  account's CURRENT ``CapabilityRecord`` (T006 registry, consumed read-only).
  No record, an ambiguous route or untested limits are typed blockers — never a
  silently skipped platform and never an invented limit.
- Hooks are EDL re-cuts of ACCEPTED assets only. This module imports nothing from
  the rendering lane and has no code path to the T013 dispatch: hook generation
  creates zero video-render jobs and (with the default config) zero reservations;
  the exports run through the same local, free FFmpeg discipline T015 established.
- Three candidates create no obligations: no release slots, no platform posts, no
  hook exposures — ``HookExperiment.assignments`` stays empty until a release
  lane assigns ELIGIBLE slots (T020). Candidates reach the final review through
  ``final_review_media`` (what the review package embeds).
- Idempotency: deterministic uuid5 ids, content-addressed derivative assets and
  replay checks per variant/cover/experiment mean identical inputs return the
  existing outputs without re-export (house pattern).
- Budget hook mirrors T015: local exports are free and reserve NOTHING by
  default; when ``EditingConfig.transfer_price`` is configured the full
  reservation discipline runs (hold before dispatch, release with an explicit
  reason when the local export completes unbilled).

Episode production state is deliberately untouched: this step reads the assembled
master and writes derivative rows; state transitions stay with the assembly and
QA steps that own them.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID

from pydantic import Field

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.cost import BudgetReservationRequest, ExposureCeilings
from microdrama.contracts.enums import (
    AssetKind,
    AssetState,
    BudgetCategory,
    BudgetScopeKind,
    Platform,
    Provenance,
    QueueName,
    TrackKind,
)
from microdrama.contracts.errors import Conflict, MicrodramaError, NotFound, SchemaInvalid
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.infra import Clock, IdGenerator, ObjectStore
from microdrama.contracts.media import (
    AssetDescriptor,
    CaptionTrack,
    EditDecisionList,
    HookCandidate,
    HookExperiment,
    MediaInfo,
)
from microdrama.contracts.primitives import (
    AccountRef,
    ContractModel,
    Identifier,
    MicroUSD,
    Sha256Hex,
    ShortText,
)
from microdrama.contracts.release import MediaRef
from microdrama.contracts.season import Script, SeasonScope, ShotManifest
from microdrama.core.events import append_event
from microdrama.core.registry import CapabilityRegistry
from microdrama.editing.captions import (
    SpeechObserver,
    spot_caption_track,
    srt_bytes,
    track_body_hash,
)
from microdrama.editing.config import EditingConfig
from microdrama.editing.covers import (
    CoverBlocker,
    CoverPlan,
    CoverSpec,
    plan_cover_specs,
    run_cover_extract,
)
from microdrama.editing.export import run_burned_export
from microdrama.editing.ffmpeg import FFmpegRunner, stage_bytes, stage_file
from microdrama.editing.fonts import resolve_caption_font
from microdrama.editing.hooks import HookPlan, plan_hook_candidates
from microdrama.editing.models import AssemblyStatus
from microdrama.editing.variants import (
    FramingChange,
    VariantBlocker,
    VariantSpec,
    build_variant_edl,
    framing_change,
    plan_variant_specs,
    run_cropped_export,
    uuid5_name,
    variant_asset_id_for,
    variant_burned_asset_id_for,
    variant_semantic_hash,
)
from microdrama.persistence.assets import register_asset
from microdrama.persistence.db import Database, Tx, insert_row, jsonb

VARIANTS_OPERATION = "editing.variants_export"
COVERS_OPERATION = "editing.covers_export"
HOOKS_OPERATION = "editing.hooks_export"
_ACCEPTED_ASSET_STATES = (AssetState.ACCEPTED.value, AssetState.LOCKED.value)
_STAGE_SUFFIX = {
    AssetKind.VIDEO: ".mp4",
    AssetKind.AUDIO: ".wav",
    AssetKind.IMAGE: ".jpg",
    AssetKind.CAPTION: ".srt",
}


# --- outcomes ---------------------------------------------------------------------------


class VariantTarget(ContractModel):
    """One destination account a variant/cover set is planned for."""

    platform: Platform
    account_ref: AccountRef
    provider_route: Identifier | None = None


class VariantResult(ContractModel):
    variant_key: Identifier
    platform: Platform
    edl_id: UUID
    duration_ms: int
    clean_asset_id: UUID
    clean_sha256: Sha256Hex
    burned_asset_id: UUID | None = None
    burned_sha256: Sha256Hex | None = None
    framing: FramingChange
    replayed: bool = False


class VariantsOutcome(ContractModel):
    episode_id: UUID
    status: AssemblyStatus
    results: list[VariantResult] = Field(default_factory=list)
    blockers: list[VariantBlocker] = Field(default_factory=list)
    notes: list[ShortText] = Field(default_factory=list)
    reservation_ids: list[UUID] = Field(default_factory=list)
    settled_micro_usd: MicroUSD = 0


class CoverResult(ContractModel):
    variant_key: Identifier
    asset_id: UUID
    sha256: Sha256Hex
    width: int
    height: int
    timestamp_ms: int
    source_asset_id: UUID
    replayed: bool = False


class CoversOutcome(ContractModel):
    episode_id: UUID
    status: AssemblyStatus
    covers: list[CoverResult] = Field(default_factory=list)
    blockers: list[CoverBlocker] = Field(default_factory=list)
    notes: list[ShortText] = Field(default_factory=list)
    reservation_ids: list[UUID] = Field(default_factory=list)
    settled_micro_usd: MicroUSD = 0


class HookAssetResult(ContractModel):
    candidate_id: Identifier
    treatment: ShortText
    edl_id: UUID
    duration_ms: int
    clean_asset_id: UUID
    clean_sha256: Sha256Hex
    burned_asset_id: UUID | None = None
    burned_sha256: Sha256Hex | None = None
    changed_framing: bool
    reading_load_note: ShortText
    replayed: bool = False


class HooksOutcome(ContractModel):
    episode_id: UUID
    experiment_id: UUID
    status: AssemblyStatus
    candidates: list[HookAssetResult] = Field(min_length=3, max_length=3)
    payoff_shot_id: Identifier
    payoff_line_ids: list[Identifier]
    new_video_render_job_ids: list[UUID] = Field(
        default_factory=list, max_length=0, description="Must stay empty (IMP-07)"
    )
    notes: list[ShortText] = Field(default_factory=list)
    reservation_ids: list[UUID] = Field(default_factory=list)
    settled_micro_usd: MicroUSD = 0


class FinalReviewMedia(ContractModel):
    """What the ordinary final-review package (T020/Gate 2) embeds for this episode."""

    episode_id: UUID
    media: list[MediaRef]
    caption_track_ids: list[UUID] = Field(default_factory=list)
    hook_experiment_id: UUID | None = None
    variant_keys: list[Identifier] = Field(default_factory=list)
    hook_candidate_ids: list[Identifier] = Field(default_factory=list)


# --- service -----------------------------------------------------------------------------


class VariantsService:
    """Platform variants, covers and hook candidates. Construct once per process."""

    def __init__(
        self,
        db: Database,
        clock: Clock,
        ids: IdGenerator,
        settings: Settings,
        *,
        budget: BudgetService,
        store: ObjectStore,
        config: EditingConfig | None = None,
        speech_observer: SpeechObserver | None = None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._ids = ids
        self._settings = settings
        self._budget = budget
        self._store = store
        self._config = config or EditingConfig()
        self._observer = speech_observer
        self._capabilities = CapabilityRegistry(db, clock, settings)
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
    def config(self) -> EditingConfig:
        return self._config

    def _row(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        with self._db.transaction(readonly=True) as tx:
            return tx.fetchone(sql, params)

    def _rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._db.transaction(readonly=True) as tx:
            return tx.fetchall(sql, params)

    # --- reads -----------------------------------------------------------------------

    def script(self, episode_id: UUID) -> Script:
        row = self._row(
            "SELECT body FROM scripts WHERE episode_id = %s AND status = 'CURRENT'", (episode_id,)
        )
        if row is None:
            raise NotFound("episode has no current script", episode_id=str(episode_id))
        return Script.model_validate(row["body"])

    def manifest(self, episode_id: UUID) -> ShotManifest:
        row = self._row(
            "SELECT body FROM shot_manifests WHERE episode_id = %s AND status = 'CURRENT'",
            (episode_id,),
        )
        if row is None:
            raise NotFound("episode has no current shot manifest", episode_id=str(episode_id))
        return ShotManifest.model_validate(row["body"])

    def edit_manifest(self, episode_id: UUID) -> EditDecisionList | None:
        """The episode's assembled main EDL (same reader shape as T015's)."""
        row = self._row(
            "SELECT edl FROM edit_manifests WHERE episode_id = %s AND variant_key = 'main' "
            "ORDER BY version DESC LIMIT 1",
            (episode_id,),
        )
        return EditDecisionList.model_validate(row["edl"]) if row is not None else None

    def hook_experiment(self, episode_id: UUID) -> HookExperiment | None:
        """The episode's latest persisted hook experiment (T027's ledger reader)."""
        row = self._row(
            "SELECT body FROM hook_experiments WHERE episode_id = %s ORDER BY created_at DESC "
            "LIMIT 1",
            (episode_id,),
        )
        return HookExperiment.model_validate(row["body"]) if row is not None else None

    def _require_main_edl(self, episode_id: UUID) -> EditDecisionList:
        edl = self.edit_manifest(episode_id)
        if edl is None:
            raise NotFound(
                "episode has no assembled master; run the assembly step before variants/hooks",
                episode_id=str(episode_id),
            )
        return edl

    def _episode_row(self, episode_id: UUID) -> dict[str, Any]:
        row = self._row("SELECT e.id, e.season_id FROM episodes e WHERE e.id = %s", (episode_id,))
        if row is None:
            raise NotFound("episode not found", episode_id=str(episode_id))
        return row

    def _asset(self, asset_id: UUID) -> AssetDescriptor:
        row = self._row("SELECT descriptor FROM assets WHERE id = %s", (asset_id,))
        if row is None:
            raise NotFound("asset not found", asset_id=str(asset_id))
        return AssetDescriptor.model_validate(row["descriptor"])

    def _asset_state(self, asset_id: UUID) -> str:
        row = self._row("SELECT state FROM assets WHERE id = %s", (asset_id,))
        if row is None:
            raise NotFound("asset not found", asset_id=str(asset_id))
        return str(row["state"])

    def _accepted_guard(self, asset_ids: set[UUID], *, what: str) -> None:
        """Refuse anything that is not accepted/locked footage (typed, before staging)."""
        bad: dict[str, str] = {}
        for asset_id in sorted(asset_ids):
            state = self._asset_state(asset_id)
            if state not in _ACCEPTED_ASSET_STATES:
                bad[str(asset_id)] = state
        if bad:
            raise Conflict(
                f"{what} may only re-cut accepted assets; found non-accepted sources",
                states=bad,
            )

    def _source_dims(self, edl: EditDecisionList) -> dict[UUID, tuple[int, int]]:
        dims: dict[UUID, tuple[int, int]] = {}
        for clip in edl.clips:
            if clip.source_asset_id in dims:
                continue
            descriptor = self._asset(clip.source_asset_id)
            if descriptor.asset_kind is not AssetKind.VIDEO:
                continue
            if (
                descriptor.media is None
                or not descriptor.media.width
                or not descriptor.media.height
            ):
                raise Conflict(
                    "video source carries no measured dimensions",
                    asset_id=str(clip.source_asset_id),
                )
            dims[clip.source_asset_id] = (descriptor.media.width, descriptor.media.height)
        return dims

    def _duration_ceiling(self, duration_ms: int) -> None:
        if duration_ms > self._config.max_export_duration_ms:
            raise SchemaInvalid(
                "duration exceeds the configured export ceiling (CPU bound)",
                duration_ms=duration_ms,
                ceiling_ms=self._config.max_export_duration_ms,
            )

    def _stage_assets(self, runner: FFmpegRunner, asset_ids: set[UUID]) -> dict[UUID, str]:
        names: dict[UUID, str] = {}
        for index, asset_id in enumerate(sorted(asset_ids)):
            descriptor = self._asset(asset_id)
            name = f"src-{index}{_STAGE_SUFFIX.get(descriptor.asset_kind, '.bin')}"
            stage_bytes(runner, name=name, data=self._store.get_bytes(descriptor.object_key))
            names[asset_id] = name
        return names

    def _caption_track(self, episode_id: UUID, locale: str) -> CaptionTrack | None:
        row = self._row(
            "SELECT body FROM caption_tracks WHERE episode_id = %s AND locale = %s "
            "AND state = 'CURRENT'",
            (episode_id, locale),
        )
        return CaptionTrack.model_validate(row["body"]) if row is not None else None

    def _line_sha(self, main_edl: EditDecisionList) -> dict[str, str]:
        """line_id -> sha256 of the measured audio the main EDL placed (hook re-spotting)."""
        out: dict[str, str] = {}
        for clip in main_edl.clips:
            if clip.dialogue_line_ids:
                out[clip.dialogue_line_ids[0]] = self._asset(clip.source_asset_id).sha256
        return out

    # --- budget hook (CPU/storage/transfer; idle by default) ---------------------------

    def _maybe_reserve(
        self, kind: str, episode_id: UUID, season_id: UUID, total_ms: int
    ) -> list[UUID]:
        price = self._config.transfer_price
        if price is None:
            return []
        seconds = max(1, -(-total_ms // 1000))
        worst = price.unit_price_micro_usd * seconds
        semantic_key = f"edit:{episode_id}:{kind}:v1"
        now = self._now()
        with self._db.transaction() as tx:
            scope_row = tx.fetchone(
                "SELECT scope FROM season_proposals WHERE season_id = %s AND status = 'APPROVED'",
                (season_id,),
            )
            if scope_row is None:
                raise Conflict("season has no approved scope; a paid export step cannot reserve")
            scope = SeasonScope.model_validate(scope_row["scope"])
            self._budget.open_episode_account(
                tx, season_id=season_id, episode_id=episode_id, policy=scope.cost_policy
            )
        reservation = self._budget.reserve(
            BudgetReservationRequest(
                request_id=uuid5_name(f"{kind}req", semantic_key),
                semantic_key=semantic_key,
                scope_kind=BudgetScopeKind.EPISODE,
                episode_id=episode_id,
                category=BudgetCategory.CPU_STORAGE_TRANSFER,
                queue=QueueName.PRODUCTION,
                provider="local-ffmpeg",
                operation_kind={
                    "variants": VARIANTS_OPERATION,
                    "covers": COVERS_OPERATION,
                    "hooks": HOOKS_OPERATION,
                }[kind],
                price=price,
                ceilings=ExposureCeilings(
                    timeout_ms=self._config.ffmpeg_timeout_ms,
                    max_units=seconds,
                    max_duration_ms=total_ms,
                ),
                worst_case_micro_usd=worst,
                expires_at=now + timedelta(milliseconds=self._config.reservation_ttl_ms),
            )
        )
        return [reservation.id]

    def _release_reservations(self, reservation_ids: Sequence[UUID], *, reason: str) -> None:
        for reservation_id in reservation_ids:
            try:
                self._budget.release(reservation_id, reason=reason)
            except MicrodramaError:
                pass  # already closed; the ledger keeps the original close reason

    # --- platform variants ---------------------------------------------------------------

    def build_variants(
        self, episode_id: UUID, *, targets: Sequence[VariantTarget]
    ) -> VariantsOutcome:
        """Build capability-aware variants for the given destination accounts."""
        main_edl = self._require_main_edl(episode_id)
        episode = self._episode_row(episode_id)
        self._duration_ceiling(main_edl.duration_ms)
        notes: list[str] = []
        blockers: list[VariantBlocker] = []
        specs: list[VariantSpec] = []
        for target in targets:
            record = self._current_capability(target)
            if record is None:
                blockers.append(
                    VariantBlocker(
                        platform=target.platform,
                        account_ref=target.account_ref,
                        reason="no current capability record; variants wait for a tested record",
                    )
                )
                continue
            plan = plan_variant_specs(
                record,
                master=main_edl.output,
                episode_duration_ms=main_edl.duration_ms,
                burn_locale=self._config.burn_locale,
            )
            specs.extend(plan.specs)
            blockers.extend(plan.blockers)
            notes.extend(
                f"{target.platform.value}/{target.account_ref}: {note}" for note in plan.notes
            )
        deduped: list[VariantSpec] = []
        seen: set[str] = set()
        for spec in specs:
            if spec.variant_key in seen:
                notes.append(
                    f"{spec.variant_key}: planned again for another account; "
                    "the shared re-cut is exported once"
                )
                continue
            seen.add(spec.variant_key)
            deduped.append(spec)
        dims = self._source_dims(main_edl)
        results: list[VariantResult] = []
        pending: list[tuple[VariantSpec, EditDecisionList, str]] = []
        for spec in deduped:
            edl = build_variant_edl(main_edl, spec, source_dims=dims)
            vhash = variant_semantic_hash(edl, variant_key=spec.variant_key)
            replay = self._variant_replay(edl, spec)
            if replay is not None:
                results.append(replay)
            else:
                pending.append((spec, edl, vhash))
        reservation_ids: list[UUID] = []
        exported: list[VariantResult] = []
        if pending:
            total_ms = sum(edl.duration_ms for _spec, edl, _hash in pending)
            reservation_ids = self._maybe_reserve(
                "variants", episode_id, episode["season_id"], total_ms
            )
            try:
                exported = self._export_variants(episode_id, episode["season_id"], pending)
            except BaseException:
                self._release_reservations(
                    reservation_ids, reason="variant export failed before any billing"
                )
                raise
        self._release_reservations(
            reservation_ids, reason="local variant exports completed; no billed transfer"
        )
        results.extend(exported)
        if exported or not results:
            status = AssemblyStatus.ASSEMBLED
        else:
            status = AssemblyStatus.REPLAYED
        self._emit(
            episode_id,
            "editing.variants_built",
            {
                "status": status.value,
                "variant_keys": sorted({r.variant_key for r in results}),
                "assets": [str(r.clean_asset_id) for r in exported],
                "framing": [
                    {
                        "variant_key": r.variant_key,
                        "cropped": r.framing.cropped,
                        "lost_pixels": r.framing.lost_pixels,
                    }
                    for r in exported
                ],
                "blockers": [b.reason[:120] for b in blockers],
                "reservation_ids": [str(rid) for rid in reservation_ids],
            },
        )
        return VariantsOutcome(
            episode_id=episode_id,
            status=status,
            results=sorted(results, key=lambda r: r.variant_key),
            blockers=blockers,
            notes=notes,
            reservation_ids=reservation_ids,
        )

    def _current_capability(self, target: VariantTarget):
        try:
            return self._capabilities.current(
                target.platform, target.account_ref, provider_route=target.provider_route
            )
        except Conflict as exc:
            raise Conflict(
                "capability lookup is ambiguous for this target; name provider_route",
                account_ref=target.account_ref,
                detail=str(exc),
            ) from exc

    def _variant_replay(self, edl: EditDecisionList, spec: VariantSpec) -> VariantResult | None:
        row = self._row(
            "SELECT output_asset_id FROM edit_manifests WHERE id = %s "
            "AND state = 'RENDERED' AND output_asset_id IS NOT NULL",
            (edl.edl_id,),
        )
        if row is None:
            return None
        clean = self._asset(row["output_asset_id"])
        burned = self._burned_derivative(clean.asset_id)
        crops = [clip.crop for clip in edl.clips if clip.track is TrackKind.VIDEO]
        return VariantResult(
            variant_key=spec.variant_key,
            platform=spec.platform,
            edl_id=edl.edl_id,
            duration_ms=edl.duration_ms,
            clean_asset_id=clean.asset_id,
            clean_sha256=clean.sha256,
            burned_asset_id=burned.asset_id if burned else None,
            burned_sha256=burned.sha256 if burned else None,
            framing=framing_change(edl.output, spec, crops),
            replayed=True,
        )

    def _export_variants(
        self,
        episode_id: UUID,
        season_id: UUID,
        pending: Sequence[tuple[VariantSpec, EditDecisionList, str]],
    ) -> list[VariantResult]:
        asset_ids = {clip.source_asset_id for _spec, edl, _hash in pending for clip in edl.clips}
        self._accepted_guard(asset_ids, what="variant export")
        track = self._caption_track(episode_id, self._config.burn_locale)
        with TemporaryDirectory(prefix="md-variants-") as tmp:
            runner = FFmpegRunner(workdir=Path(tmp), timeout_ms=self._config.ffmpeg_timeout_ms)
            names = self._stage_assets(runner, asset_ids)
            srt_name: str | None = None
            font_family: str | None = None
            if track is not None:
                srt_name = f"captions-{self._config.burn_locale}.srt"
                (runner.workdir / srt_name).write_bytes(srt_bytes(track))
                font = resolve_caption_font(self._config, [cue.text for cue in track.cues])
                if font.path is not None and font.coverage_ok:
                    stage_file(runner, name="caption-font.otf", source=Path(font.path))
                    font_family = font.family
            results: list[VariantResult] = []
            for index, (spec, edl, vhash) in enumerate(pending):
                clean_name = f"variant-{index}.mp4"
                clean_path = run_cropped_export(
                    runner, edl=edl, config=self._config, names=names, output=clean_name
                )
                clean_media = runner.probe(clean_path)
                burned_name: str | None = None
                burned_media: MediaInfo | None = None
                if srt_name is not None and font_family is not None:
                    burned_name = f"variant-burned-{index}.mp4"
                    burned_path = run_burned_export(
                        runner,
                        master_name=clean_name,
                        srt_name=srt_name,
                        font_family=font_family,
                        config=self._config,
                        output=burned_name,
                    )
                    burned_media = runner.probe(burned_path)
                results.append(
                    self._persist_variant(
                        episode_id=episode_id,
                        season_id=season_id,
                        spec=spec,
                        edl=edl,
                        vhash=vhash,
                        runner=runner,
                        clean_name=clean_name,
                        burned_name=burned_name,
                        clean_media=clean_media,
                        burned_media=burned_media,
                        caption_track=track,
                    )
                )
            return results

    def _persist_variant(
        self,
        *,
        episode_id: UUID,
        season_id: UUID,
        spec: VariantSpec,
        edl: EditDecisionList,
        vhash: str,
        runner: FFmpegRunner,
        clean_name: str,
        burned_name: str | None,
        clean_media: MediaInfo,
        burned_media: MediaInfo | None,
        caption_track: CaptionTrack | None,
    ) -> VariantResult:
        now = self._now()
        source_ids = sorted({clip.source_asset_id for clip in edl.clips})
        clean_id = variant_asset_id_for(vhash)
        burned_id = (
            variant_burned_asset_id_for(vhash, track_body_hash(caption_track))
            if burned_name is not None and caption_track is not None
            else None
        )
        clean_bytes = (runner.workdir / clean_name).read_bytes()
        burned_bytes = (
            (runner.workdir / burned_name).read_bytes() if burned_name is not None else None
        )
        with self._db.transaction() as tx:
            stored_clean = self._store.put_bytes(
                f"edits/{episode_id}/variants/{vhash[:32]}.mp4",
                clean_bytes,
                media_type="video/mp4",
            )
            register_asset(
                tx,
                self._video_descriptor(
                    clean_id, stored_clean, clean_media, episode_id, season_id, source_ids, now
                ),
            )
            stored_burned = None
            if burned_id is not None and burned_bytes is not None and burned_media is not None:
                stored_burned = self._store.put_bytes(
                    f"edits/{episode_id}/variants/{vhash[:32]}-burned.mp4",
                    burned_bytes,
                    media_type="video/mp4",
                )
                register_asset(
                    tx,
                    self._video_descriptor(
                        burned_id,
                        stored_burned,
                        burned_media,
                        episode_id,
                        season_id,
                        [clean_id],
                        now,
                    ),
                )
            self._write_edl_row(
                tx,
                edl=edl,
                edl_hash=vhash,
                variant_key=spec.variant_key,
                output_asset_id=clean_id,
                now=now,
            )
        crops = [clip.crop for clip in edl.clips if clip.track is TrackKind.VIDEO]
        return VariantResult(
            variant_key=spec.variant_key,
            platform=spec.platform,
            edl_id=edl.edl_id,
            duration_ms=edl.duration_ms,
            clean_asset_id=clean_id,
            clean_sha256=stored_clean.sha256,
            burned_asset_id=burned_id,
            burned_sha256=stored_burned.sha256 if stored_burned is not None else None,
            framing=framing_change(edl.output, spec, crops),
            replayed=False,
        )

    @staticmethod
    def _video_descriptor(
        asset_id: UUID,
        stored: Any,
        media: MediaInfo,
        episode_id: UUID,
        season_id: UUID,
        lineage: list[UUID],
        now: datetime,
    ) -> AssetDescriptor:
        return AssetDescriptor(
            asset_id=asset_id,
            asset_kind=AssetKind.VIDEO,
            object_key=stored.key,
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            media_type="video/mp4",
            media=media,
            state=AssetState.ACCEPTED,
            provenance=Provenance.DERIVED_LOCAL,
            episode_id=episode_id,
            season_id=season_id,
            lineage=lineage,
            created_at=now,
        )

    def _burned_derivative(self, clean_asset_id: UUID) -> AssetDescriptor | None:
        """The asset derived from exactly this clean asset (the burned export)."""
        episode_row = self._row("SELECT episode_id FROM assets WHERE id = %s", (clean_asset_id,))
        if episode_row is None:
            return None
        for row in self._rows(
            "SELECT descriptor FROM assets WHERE episode_id = %s AND asset_kind = 'VIDEO' "
            "AND provenance = 'DERIVED_LOCAL'",
            (episode_row["episode_id"],),
        ):
            descriptor = AssetDescriptor.model_validate(row["descriptor"])
            if descriptor.lineage == [clean_asset_id]:
                return descriptor
        return None

    # --- covers --------------------------------------------------------------------------

    def derive_covers(self, episode_id: UUID, *, targets: Sequence[VariantTarget]) -> CoversOutcome:
        """Derive one static cover per tested aspect ratio from the review master."""
        main_edl = self._require_main_edl(episode_id)
        episode = self._episode_row(episode_id)
        self._duration_ceiling(main_edl.duration_ms)
        main_row = self._row(
            "SELECT output_asset_id FROM edit_manifests WHERE episode_id = %s "
            "AND variant_key = 'main' AND output_asset_id IS NOT NULL "
            "ORDER BY version DESC LIMIT 1",
            (episode_id,),
        )
        if main_row is None:
            raise NotFound(
                "episode has no assembled master asset; run the assembly step first",
                episode_id=str(episode_id),
            )
        master_id = main_row["output_asset_id"]
        source = self._burned_derivative(master_id)
        notes: list[str] = []
        if source is None:
            source = self._asset(master_id)
            notes.append("no burned master found; covers derive from the clean master")
        self._accepted_guard({source.asset_id}, what="cover derivation")
        specs: list[CoverSpec] = []
        blockers: list[CoverBlocker] = []
        for target in targets:
            record = self._current_capability(target)
            if record is None:
                blockers.append(
                    CoverBlocker(
                        platform=target.platform,
                        account_ref=target.account_ref,
                        reason="no current capability record; covers wait for a tested record",
                    )
                )
                continue
            plan: CoverPlan = plan_cover_specs(
                record, master=main_edl.output, master_duration_ms=main_edl.duration_ms
            )
            specs.extend(plan.specs)
            blockers.extend(plan.blockers)
            notes.extend(
                f"{target.platform.value}/{target.account_ref}: {note}" for note in plan.notes
            )
        deduped: list[CoverSpec] = []
        seen: set[str] = set()
        for spec in specs:
            if spec.variant_key in seen:
                continue
            seen.add(spec.variant_key)
            deduped.append(spec)
        covers: list[CoverResult] = []
        pending: list[CoverSpec] = []
        for spec in deduped:
            row = self._row(
                "SELECT descriptor FROM assets WHERE id = %s", (self._cover_id(source, spec),)
            )
            if row is not None:
                descriptor = AssetDescriptor.model_validate(row["descriptor"])
                covers.append(
                    CoverResult(
                        variant_key=spec.variant_key,
                        asset_id=descriptor.asset_id,
                        sha256=descriptor.sha256,
                        width=spec.width,
                        height=spec.height,
                        timestamp_ms=spec.timestamp_ms,
                        source_asset_id=source.asset_id,
                        replayed=True,
                    )
                )
            else:
                pending.append(spec)
        reservation_ids: list[UUID] = []
        derived: list[CoverResult] = []
        if pending:
            reservation_ids = self._maybe_reserve(
                "covers", episode_id, episode["season_id"], len(pending) * 1_000
            )
            try:
                derived = self._export_covers(episode_id, episode["season_id"], source, pending)
            except BaseException:
                self._release_reservations(
                    reservation_ids, reason="cover derivation failed before any billing"
                )
                raise
        self._release_reservations(
            reservation_ids, reason="local cover extracts completed; no billed transfer"
        )
        covers.extend(derived)
        status = AssemblyStatus.ASSEMBLED if derived or not covers else AssemblyStatus.REPLAYED
        self._emit(
            episode_id,
            "editing.covers_built",
            {
                "status": status.value,
                "covers": [
                    {"variant_key": c.variant_key, "asset_id": str(c.asset_id)} for c in covers
                ],
                "source_asset_id": str(source.asset_id),
                "blockers": [b.reason[:120] for b in blockers],
            },
        )
        return CoversOutcome(
            episode_id=episode_id,
            status=status,
            covers=sorted(covers, key=lambda c: c.variant_key),
            blockers=blockers,
            notes=notes,
            reservation_ids=reservation_ids,
        )

    @staticmethod
    def _cover_id(source: AssetDescriptor, spec: CoverSpec) -> UUID:
        return uuid5_name("cover", f"{source.sha256[:32]}:{spec.variant_key}:{spec.timestamp_ms}")

    def _export_covers(
        self,
        episode_id: UUID,
        season_id: UUID,
        source: AssetDescriptor,
        pending: Sequence[CoverSpec],
    ) -> list[CoverResult]:
        now = self._now()
        master_bytes = self._store.get_bytes(source.object_key)
        results: list[CoverResult] = []
        with TemporaryDirectory(prefix="md-covers-") as tmp:
            runner = FFmpegRunner(workdir=Path(tmp), timeout_ms=self._config.ffmpeg_timeout_ms)
            master_name = "master.mp4"
            stage_bytes(runner, name=master_name, data=master_bytes)
            with self._db.transaction() as tx:
                for index, spec in enumerate(pending):
                    path = run_cover_extract(
                        runner,
                        master_name=master_name,
                        spec=spec,
                        output=f"cover-{index}.jpg",
                    )
                    cover_id = self._cover_id(source, spec)
                    stored = self._store.put_bytes(
                        f"edits/{episode_id}/covers/{cover_id.hex}.jpg",
                        path.read_bytes(),
                        media_type="image/jpeg",
                    )
                    register_asset(
                        tx,
                        AssetDescriptor(
                            asset_id=cover_id,
                            asset_kind=AssetKind.IMAGE,
                            object_key=stored.key,
                            sha256=stored.sha256,
                            size_bytes=stored.size_bytes,
                            media_type="image/jpeg",
                            media=None,  # still images carry no stream duration to probe
                            state=AssetState.ACCEPTED,
                            provenance=Provenance.DERIVED_LOCAL,
                            episode_id=episode_id,
                            season_id=season_id,
                            lineage=[source.asset_id],
                            created_at=now,
                        ),
                    )
                    results.append(
                        CoverResult(
                            variant_key=spec.variant_key,
                            asset_id=cover_id,
                            sha256=stored.sha256,
                            width=spec.width,
                            height=spec.height,
                            timestamp_ms=spec.timestamp_ms,
                            source_asset_id=source.asset_id,
                            replayed=False,
                        )
                    )
        return results

    # --- hooks -------------------------------------------------------------------------

    def generate_hook_candidates(
        self,
        episode_id: UUID,
        *,
        target_durations_ms: Sequence[int] = (24_000, 28_000, 32_000),
    ) -> HooksOutcome:
        """Plan and export three hook candidates from accepted footage (IMP-07).

        No video-render job is ever created: candidates are local re-cuts. No
        release slot, platform post or exposure row is created either — candidates
        are review material; only an eligible-slot assignment (T020) publishes.
        """
        main_edl = self._require_main_edl(episode_id)
        episode = self._episode_row(episode_id)
        script = self.script(episode_id)
        manifest = self.manifest(episode_id)
        plan: HookPlan = plan_hook_candidates(
            main_edl=main_edl,
            manifest=manifest,
            script=script,
            target_durations_ms=target_durations_ms,
            source_dims=self._source_dims(main_edl),
        )
        experiment = self._experiment_for(episode_id, plan)
        replay = self._hooks_replay(episode_id, experiment, plan)
        if replay is not None:
            return replay
        asset_ids = {
            clip.source_asset_id for candidate in plan.candidates for clip in candidate.edl.clips
        }
        self._accepted_guard(asset_ids, what="hook generation")
        reservation_ids = self._maybe_reserve(
            "hooks",
            episode_id,
            episode["season_id"],
            sum(c.candidate.duration_ms for c in plan.candidates),
        )
        try:
            results, notes = self._export_hooks(episode_id, episode["season_id"], main_edl, plan)
            body_hash = canonical_hash(experiment)
            with self._db.transaction() as tx:
                existing = tx.fetchone(
                    "SELECT id FROM hook_experiments WHERE episode_id = %s AND body_hash = %s",
                    (episode_id, body_hash),
                )
                if existing is None:
                    insert_row(
                        tx,
                        "hook_experiments",
                        {
                            "id": experiment.experiment_id,
                            "episode_id": episode_id,
                            "body": jsonb(experiment),
                            "body_hash": body_hash,
                        },
                        returning="id",
                    )
                append_event(
                    tx,
                    aggregate_type="episode",
                    aggregate_id=episode_id,
                    event_type="editing.hooks_built",
                    payload={
                        "experiment_id": str(experiment.experiment_id),
                        "candidates": [
                            {
                                "candidate_id": r.candidate_id,
                                "treatment": r.treatment,
                                "duration_ms": r.duration_ms,
                                "changed_framing": r.changed_framing,
                                "reading_load": r.reading_load_note[:160],
                                "asset_id": str(r.clean_asset_id),
                            }
                            for r in results
                        ],
                        "payoff": {
                            "shot_id": plan.payoff.shot_id,
                            "line_ids": plan.payoff.line_ids,
                        },
                        "new_video_render_job_ids": [],
                        "assignments_created": 0,
                    },
                    correlation_id=self._new_id(),
                    occurred_at=self._now(),
                )
        except BaseException:
            self._release_reservations(
                reservation_ids, reason="hook export failed before any billing"
            )
            raise
        self._release_reservations(
            reservation_ids, reason="local hook exports completed; no billed transfer"
        )
        return HooksOutcome(
            episode_id=episode_id,
            experiment_id=experiment.experiment_id,
            status=AssemblyStatus.ASSEMBLED,
            candidates=results,
            payoff_shot_id=plan.payoff.shot_id,
            payoff_line_ids=list(plan.payoff.line_ids),
            new_video_render_job_ids=[],
            notes=notes,
            reservation_ids=reservation_ids,
        )

    def _experiment_for(self, episode_id: UUID, plan: HookPlan) -> HookExperiment:
        probe = HookExperiment(
            experiment_id=uuid5_name("hookexp", "pending"),
            episode_id=episode_id,
            candidates=[candidate.candidate for candidate in plan.candidates],
        )
        body_hash = canonical_hash(probe.model_dump(mode="json", exclude={"experiment_id"}))
        return probe.model_copy(
            update={"experiment_id": uuid5_name("hookexp", f"{episode_id}:{body_hash[:32]}")}
        )

    def _hooks_replay(
        self, episode_id: UUID, experiment: HookExperiment, plan: HookPlan
    ) -> HooksOutcome | None:
        row = self._row(
            "SELECT body FROM hook_experiments WHERE episode_id = %s AND body_hash = %s",
            (episode_id, canonical_hash(experiment)),
        )
        if row is None:
            return None
        stored = HookExperiment.model_validate(row["body"])
        results: list[HookAssetResult] = []
        for candidate in plan.candidates:
            edl_row = self._row(
                "SELECT output_asset_id FROM edit_manifests WHERE id = %s "
                "AND state = 'RENDERED' AND output_asset_id IS NOT NULL",
                (candidate.candidate.edl_id,),
            )
            if edl_row is None:
                return None  # experiment exists but an export is missing: rebuild it
            clean = self._asset(edl_row["output_asset_id"])
            burned = self._burned_derivative(clean.asset_id)
            results.append(
                HookAssetResult(
                    candidate_id=candidate.candidate.candidate_id,
                    treatment=candidate.candidate.treatment,
                    edl_id=candidate.candidate.edl_id,
                    duration_ms=candidate.candidate.duration_ms,
                    clean_asset_id=clean.asset_id,
                    clean_sha256=clean.sha256,
                    burned_asset_id=burned.asset_id if burned else None,
                    burned_sha256=burned.sha256 if burned else None,
                    changed_framing=candidate.candidate.changed_framing,
                    reading_load_note=candidate.candidate.reading_load_note,
                    replayed=True,
                )
            )
        return HooksOutcome(
            episode_id=episode_id,
            experiment_id=stored.experiment_id,
            status=AssemblyStatus.REPLAYED,
            candidates=results,
            payoff_shot_id=plan.payoff.shot_id,
            payoff_line_ids=list(plan.payoff.line_ids),
            new_video_render_job_ids=[],
            notes=["identical hook experiment already exists; nothing re-exported"],
        )

    def _export_hooks(
        self,
        episode_id: UUID,
        season_id: UUID,
        main_edl: EditDecisionList,
        plan: HookPlan,
    ) -> tuple[list[HookAssetResult], list[str]]:
        asset_ids = {
            clip.source_asset_id for candidate in plan.candidates for clip in candidate.edl.clips
        }
        notes: list[str] = list(plan.notes)
        line_sha = self._line_sha(main_edl)
        script = self.script(episode_id)
        line_text_th = {
            line.line_id: line.text_th for scene in script.scenes for line in scene.lines
        }
        line_text_en = {
            line.line_id: line.text_en for scene in script.scenes for line in scene.lines
        }
        locale = self._config.burn_locale
        results: list[HookAssetResult] = []
        with TemporaryDirectory(prefix="md-hooks-") as tmp:
            runner = FFmpegRunner(workdir=Path(tmp), timeout_ms=self._config.ffmpeg_timeout_ms)
            names = self._stage_assets(runner, asset_ids)
            for index, candidate in enumerate(plan.candidates):
                edl = candidate.edl
                candidate_id = candidate.candidate.candidate_id
                hhash = variant_semantic_hash(edl, variant_key=candidate_id)
                clean_name = f"hook-{index}.mp4"
                clean_path = run_cropped_export(
                    runner, edl=edl, config=self._config, names=names, output=clean_name
                )
                clean_media = runner.probe(clean_path)
                # Re-spot captions on the HOOK's actual audio placement (the master's
                # cue times do not apply to a re-cut). Ephemeral tracks: they drive
                # the burn and the reading-load note, never the caption_tracks table.
                track, findings, obs_notes = spot_caption_track(
                    episode_id=episode_id,
                    locale=locale,
                    edl=edl,
                    line_sha256=line_sha,
                    line_text=line_text_th if locale.startswith("th") else line_text_en,
                    line_spoken_text=line_text_th,
                    observer=self._observer,
                    tail_pad_ms=self._config.cue_tail_pad_ms,
                    min_cue_ms=self._config.min_cue_ms,
                )
                notes.extend(f"{candidate_id}:{note}" for note in obs_notes)
                srt_name = f"hook-{index}.srt"
                (runner.workdir / srt_name).write_bytes(srt_bytes(track))
                font = resolve_caption_font(self._config, [cue.text for cue in track.cues])
                burned_name: str | None = None
                burned_media: MediaInfo | None = None
                if font.path is not None and font.coverage_ok:
                    stage_file(runner, name="caption-font.otf", source=Path(font.path))
                    burned_name = f"hook-burned-{index}.mp4"
                    burned_path = run_burned_export(
                        runner,
                        master_name=clean_name,
                        srt_name=srt_name,
                        font_family=font.family,
                        config=self._config,
                        output=burned_name,
                    )
                    burned_media = runner.probe(burned_path)
                else:
                    notes.append(
                        f"{candidate_id}: no Thai-safe font; hook ships clean (burn skipped)"
                    )
                notes.extend(
                    f"{candidate_id}: {finding.code} ({finding.severity.value})"
                    for finding in findings
                )
                results.append(
                    self._persist_hook(
                        episode_id=episode_id,
                        season_id=season_id,
                        candidate=candidate.candidate,
                        edl=edl,
                        hhash=hhash,
                        runner=runner,
                        clean_name=clean_name,
                        burned_name=burned_name,
                        clean_media=clean_media,
                        burned_media=burned_media,
                        caption_body_hash=track_body_hash(track),
                    )
                )
        return results, notes

    def _persist_hook(
        self,
        *,
        episode_id: UUID,
        season_id: UUID,
        candidate: HookCandidate,
        edl: EditDecisionList,
        hhash: str,
        runner: FFmpegRunner,
        clean_name: str,
        burned_name: str | None,
        clean_media: MediaInfo,
        burned_media: MediaInfo | None,
        caption_body_hash: str,
    ) -> HookAssetResult:
        now = self._now()
        source_ids = sorted({clip.source_asset_id for clip in edl.clips})
        clean_id = uuid5_name("hook", hhash)
        burned_id = uuid5_name("hook-burned", f"{hhash}:{caption_body_hash[:32]}")
        clean_bytes = (runner.workdir / clean_name).read_bytes()
        burned_bytes = (
            (runner.workdir / burned_name).read_bytes() if burned_name is not None else None
        )
        with self._db.transaction() as tx:
            stored_clean = self._store.put_bytes(
                f"edits/{episode_id}/hooks/{hhash[:32]}.mp4",
                clean_bytes,
                media_type="video/mp4",
            )
            register_asset(
                tx,
                self._video_descriptor(
                    clean_id, stored_clean, clean_media, episode_id, season_id, source_ids, now
                ),
            )
            stored_burned = None
            if burned_bytes is not None and burned_media is not None:
                stored_burned = self._store.put_bytes(
                    f"edits/{episode_id}/hooks/{hhash[:32]}-burned.mp4",
                    burned_bytes,
                    media_type="video/mp4",
                )
                register_asset(
                    tx,
                    self._video_descriptor(
                        burned_id,
                        stored_burned,
                        burned_media,
                        episode_id,
                        season_id,
                        [clean_id],
                        now,
                    ),
                )
            self._write_edl_row(
                tx,
                edl=edl,
                edl_hash=hhash,
                variant_key=candidate.candidate_id,
                output_asset_id=clean_id,
                now=now,
            )
        return HookAssetResult(
            candidate_id=candidate.candidate_id,
            treatment=candidate.treatment,
            edl_id=edl.edl_id,
            duration_ms=edl.duration_ms,
            clean_asset_id=clean_id,
            clean_sha256=stored_clean.sha256,
            burned_asset_id=burned_id if stored_burned is not None else None,
            burned_sha256=stored_burned.sha256 if stored_burned is not None else None,
            changed_framing=candidate.changed_framing,
            reading_load_note=candidate.reading_load_note,
            replayed=False,
        )

    def _write_edl_row(
        self,
        tx: Tx,
        *,
        edl: EditDecisionList,
        edl_hash: str,
        variant_key: str,
        output_asset_id: UUID,
        now: datetime,
    ) -> None:
        existing = tx.fetchone("SELECT id FROM edit_manifests WHERE id = %s", (edl.edl_id,))
        if existing is not None:
            tx.execute(
                "UPDATE edit_manifests SET state = 'RENDERED', output_asset_id = %s, "
                "revision = revision + 1, updated_at = %s WHERE id = %s",
                (output_asset_id, now, edl.edl_id),
            )
            return
        version = int(
            tx.fetchval(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM edit_manifests "
                "WHERE episode_id = %s AND purpose = %s AND variant_key = %s",
                (edl.episode_id, edl.purpose.value, variant_key),
            )
        )
        insert_row(
            tx,
            "edit_manifests",
            {
                "id": edl.edl_id,
                "episode_id": edl.episode_id,
                "purpose": edl.purpose.value,
                "variant_key": variant_key,
                "version": version,
                "edl": jsonb(edl),
                "edl_hash": edl_hash,
                "output_asset_id": output_asset_id,
                "state": "RENDERED",
            },
            returning="id",
        )

    # --- final-review references ----------------------------------------------------------

    def final_review_media(self, episode_id: UUID) -> FinalReviewMedia:
        """Everything the ordinary final-review package embeds for this episode."""
        media: list[MediaRef] = []
        main_row = self._row(
            "SELECT output_asset_id FROM edit_manifests WHERE episode_id = %s "
            "AND variant_key = 'main' AND output_asset_id IS NOT NULL "
            "ORDER BY version DESC LIMIT 1",
            (episode_id,),
        )
        if main_row is not None:
            master = self._asset(main_row["output_asset_id"])
            media.append(MediaRef(asset_id=master.asset_id, sha256=master.sha256, role="master"))
            burned = self._burned_derivative(master.asset_id)
            if burned is not None:
                media.append(
                    MediaRef(asset_id=burned.asset_id, sha256=burned.sha256, role="burned")
                )
        variant_keys: list[str] = []
        hook_ids: list[str] = []
        for row in self._rows(
            "SELECT variant_key, purpose, output_asset_id FROM edit_manifests "
            "WHERE episode_id = %s AND state = 'RENDERED' AND output_asset_id IS NOT NULL "
            "AND variant_key <> 'main' ORDER BY variant_key, version",
            (episode_id,),
        ):
            descriptor = self._asset(row["output_asset_id"])
            if row["purpose"] == "HOOK":
                media.append(
                    MediaRef(asset_id=descriptor.asset_id, sha256=descriptor.sha256, role="hook")
                )
                hook_ids.append(row["variant_key"])
                continue
            media.append(
                MediaRef(asset_id=descriptor.asset_id, sha256=descriptor.sha256, role="variant")
            )
            variant_keys.append(row["variant_key"])
            burned = self._burned_derivative(descriptor.asset_id)
            if burned is not None:
                media.append(
                    MediaRef(asset_id=burned.asset_id, sha256=burned.sha256, role="variant")
                )
        for row in self._rows(
            "SELECT descriptor FROM assets WHERE episode_id = %s AND asset_kind = 'IMAGE' "
            "AND provenance = 'DERIVED_LOCAL' ORDER BY id",
            (episode_id,),
        ):
            descriptor = AssetDescriptor.model_validate(row["descriptor"])
            media.append(
                MediaRef(asset_id=descriptor.asset_id, sha256=descriptor.sha256, role="cover")
            )
        caption_ids = [
            row["id"]
            for row in self._rows(
                "SELECT id FROM caption_tracks WHERE episode_id = %s AND state = 'CURRENT' "
                "ORDER BY locale",
                (episode_id,),
            )
        ]
        experiment = self.hook_experiment(episode_id)
        return FinalReviewMedia(
            episode_id=episode_id,
            media=media,
            caption_track_ids=caption_ids,
            hook_experiment_id=experiment.experiment_id if experiment else None,
            variant_keys=sorted(set(variant_keys)),
            hook_candidate_ids=sorted(set(hook_ids)),
        )

    # --- events ---------------------------------------------------------------------------

    def _emit(self, episode_id: UUID, event_type: str, payload: Mapping[str, Any]) -> None:
        with self._db.transaction() as tx:
            append_event(
                tx,
                aggregate_type="episode",
                aggregate_id=episode_id,
                event_type=event_type,
                payload=dict(payload),
                correlation_id=self._new_id(),
                occurred_at=self._now(),
            )


def build_variants_service(
    db: Database,
    clock: Clock,
    ids: IdGenerator,
    settings: Settings,
    *,
    budget: BudgetService,
    store: ObjectStore,
    config: EditingConfig | None = None,
    speech_observer: SpeechObserver | None = None,
) -> VariantsService:
    """Composition-time factory (the integrator registers routes/jobs, not this module)."""
    return VariantsService(
        db,
        clock,
        ids,
        settings,
        budget=budget,
        store=store,
        config=config,
        speech_observer=speech_observer,
    )


__all__ = [
    "COVERS_OPERATION",
    "CoverResult",
    "CoversOutcome",
    "FinalReviewMedia",
    "HOOKS_OPERATION",
    "HookAssetResult",
    "HooksOutcome",
    "VARIANTS_OPERATION",
    "VariantResult",
    "VariantTarget",
    "VariantsOutcome",
    "VariantsService",
    "build_variants_service",
]
