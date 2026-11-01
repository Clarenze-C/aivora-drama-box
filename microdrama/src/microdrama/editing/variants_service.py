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
from hashlib import sha256
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
    RightsStatus,
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
    EvidenceRef,
    Identifier,
    MicroUSD,
    Sha256Hex,
    ShortText,
)
from microdrama.contracts.registries import RightsRecord
from microdrama.contracts.release import (
    CreativeDerivativeRef,
    DerivativeSourceRef,
    MediaRef,
    PlatformSafeZone,
    SafeZoneTextBox,
)
from microdrama.contracts.season import Script, SeasonScope, ShotManifest
from microdrama.contracts.v2 import validate_current_rights_grant
from microdrama.core.events import append_event
from microdrama.core.registry import CapabilityRegistry, RightsRegistry
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
from microdrama.editing.creative_derivatives import (
    PosterPlan,
    PreviewPlan,
    run_poster_export,
    run_preview_export,
)
from microdrama.editing.export import run_burned_export
from microdrama.editing.ffmpeg import FFmpegRunner, stage_bytes, stage_file
from microdrama.editing.fonts import resolve_caption_font
from microdrama.editing.hooks import HookPlan, plan_hook_candidates
from microdrama.editing.models import AssemblyStatus, DerivedOutputsRebuild
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
from microdrama.persistence.db import (
    Database,
    Tx,
    insert_row,
    jsonb,
    update_with_revision,
)

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
    creative_derivatives: list[CreativeDerivativeRef] | None = None
    creative_derivation_manifests: list[dict[str, Any]] = Field(default_factory=list)


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
        row = self._row(
            "SELECT e.id, e.season_id, e.episode_number FROM episodes e WHERE e.id = %s",
            (episode_id,),
        )
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
        """Refuse re-cutting imagery that is not accepted/locked footage (typed, before staging).

        Only VIDEO sources are guarded: a variant/hook re-cut composes imagery, so an
        unreviewed frame must never reach one (AT-10 "accepted source footage").
        Dialogue AUDIO lanes legitimately live PROVISIONAL until the episode-one
        identity lock at Gate 2 — they are mixed underneath, never re-cut, and their
        truth is enforced by QA on the exported artifact and by the lock itself
        (T030-02: guarding them made every pre-Gate 2 variant/hook export impossible).
        """
        bad: dict[str, str] = {}
        for asset_id in sorted(asset_ids):
            kind, state = self._asset_kind_state(asset_id)
            if kind is not AssetKind.VIDEO:
                continue
            if state not in _ACCEPTED_ASSET_STATES:
                bad[str(asset_id)] = state
        if bad:
            raise Conflict(
                f"{what} may only re-cut accepted footage; found non-accepted video sources",
                states=bad,
            )

    def _asset_kind_state(self, asset_id: UUID) -> tuple[AssetKind, str]:
        row = self._row("SELECT state, descriptor FROM assets WHERE id = %s", (asset_id,))
        if row is None:
            raise NotFound("asset not found", asset_id=str(asset_id))
        kind = AssetKind(row["descriptor"]["asset_kind"])
        return kind, str(row["state"])

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

    # --- burned-derivative rebuild (build-review F03) --------------------------------------

    def rebuild_burned_variants(self, episode_id: UUID) -> DerivedOutputsRebuild:
        """Re-burn every variant's burned derivative from the CURRENT caption track.

        A caption repair changed the burn-locale cues; each variant's burned
        export is a direct derivative of those cues (its asset id embeds the
        caption body hash), so a stale burn must be superseded and re-burned
        before any package binds it. Variants whose export honestly skipped the
        burn (no covering font, no track at export time) are skipped again with
        a note — a rebuild never invents a derivative the original export did
        not produce. Idempotent: an already-rebuilt burn replays as a note.
        """
        from microdrama.contracts.enums import AssetState as _AS

        episode_row = self._row("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))
        if episode_row is None:
            raise NotFound("episode not found", episode_id=str(episode_id))
        season_id = episode_row["season_id"]
        track = self._caption_track(episode_id, self._config.burn_locale)
        result = DerivedOutputsRebuild()
        if track is None:
            result.notes.append(
                f"no current {self._config.burn_locale} caption track; nothing to re-burn"
            )
            return result
        body_hash = track_body_hash(track)
        rows = self._rows(
            "SELECT id, edl_hash, variant_key, output_asset_id FROM edit_manifests "
            "WHERE episode_id = %s AND variant_key <> 'main' AND state = 'RENDERED' "
            "AND output_asset_id IS NOT NULL ORDER BY variant_key, version",
            (episode_id,),
        )
        font = resolve_caption_font(self._config, [cue.text for cue in track.cues])
        if font.path is None or not font.coverage_ok:
            result.notes.append(
                "no installed font covers the repaired caption text; burns are skipped"
            )
            return result
        now = self._now()
        with TemporaryDirectory(prefix="md-variants-rebuild-") as tmp:
            runner = FFmpegRunner(workdir=Path(tmp), timeout_ms=self._config.ffmpeg_timeout_ms)
            srt_name = f"captions-{self._config.burn_locale}.srt"
            (runner.workdir / srt_name).write_bytes(srt_bytes(track))
            stage_file(runner, name="caption-font.otf", source=Path(font.path))
            for row in rows:
                vhash = str(row["edl_hash"])
                clean = self._asset(row["output_asset_id"])
                stale = self._burned_derivative(clean.asset_id)
                expected = variant_burned_asset_id_for(vhash, body_hash)
                if stale is not None and stale.asset_id == expected and stale.state == _AS.ACCEPTED:
                    result.notes.append(f"{row['variant_key']}: burned variant already rebuilt")
                    continue
                if stale is None:
                    # The original export produced no burn for this variant; a
                    # rebuild does not invent one now.
                    continue
                clean_name = f"variant-{row['variant_key']}.mp4"
                stage_bytes(runner, name=clean_name, data=self._store.get_bytes(clean.object_key))
                burned_path = run_burned_export(
                    runner,
                    master_name=clean_name,
                    srt_name=srt_name,
                    font_family=font.family,
                    config=self._config,
                    output=f"burned-{row['variant_key']}.mp4",
                )
                burned_media = runner.probe(burned_path)
                burned_bytes = burned_path.read_bytes()
                with self._db.transaction() as tx:
                    revision = int(
                        tx.fetchval("SELECT revision FROM assets WHERE id = %s", (stale.asset_id,))
                        or 0
                    )
                    update_with_revision(
                        tx,
                        "assets",
                        stale.asset_id,
                        revision,
                        {"state": _AS.SUPERSEDED.value},
                        now=now,
                    )
                    result.superseded_asset_ids.append(stale.asset_id)
                    existing_expected = tx.fetchone(
                        "SELECT id, sha256, state FROM assets WHERE id = %s", (expected,)
                    )
                    stored = self._store.put_bytes(
                        f"edits/{episode_id}/variants/{vhash[:32]}-burned-{body_hash[:8]}.mp4",
                        burned_bytes,
                        media_type="video/mp4",
                    )
                    if existing_expected is not None:
                        update_with_revision(
                            tx,
                            "assets",
                            expected,
                            int(
                                tx.fetchval(
                                    "SELECT revision FROM assets WHERE id = %s", (expected,)
                                )
                                or 0
                            ),
                            {
                                "state": _AS.ACCEPTED.value,
                                "descriptor": jsonb(
                                    self._video_descriptor(
                                        expected,
                                        stored,
                                        burned_media,
                                        episode_id,
                                        season_id,
                                        [clean.asset_id],
                                        now,
                                    )
                                ),
                            },
                            now=now,
                        )
                    else:
                        register_asset(
                            tx,
                            self._video_descriptor(
                                expected,
                                stored,
                                burned_media,
                                episode_id,
                                season_id,
                                [clean.asset_id],
                                now,
                            ),
                        )
                    result.new_asset_ids.append(expected)
                    result.notes.append(
                        f"{row['variant_key']}: burned variant re-burned from repaired captions"
                    )
        return result

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

    # --- V2 poster and episode-one preview ------------------------------------------------

    def _creative_sources_current(
        self, sources: Sequence[DerivativeSourceRef]
    ) -> list[AssetDescriptor]:
        current: list[AssetDescriptor] = []
        for source in sources:
            descriptor = self._asset(source.asset_id)
            if descriptor.sha256 != source.asset_sha256:
                raise Conflict(
                    "creative source changed after planning",
                    asset_id=str(source.asset_id),
                    expected=source.asset_sha256,
                    actual=descriptor.sha256,
                )
            if descriptor.version != source.asset_version:
                raise Conflict(
                    "creative source version changed after planning",
                    asset_id=str(source.asset_id),
                    expected=source.asset_version,
                    actual=descriptor.version,
                )
            if self._asset_state(source.asset_id) not in _ACCEPTED_ASSET_STATES:
                raise Conflict(
                    "creative source is not accepted or locked", asset_id=str(source.asset_id)
                )
            if (
                sha256(self._store.get_bytes(descriptor.object_key)).hexdigest()
                != descriptor.sha256
            ):
                raise Conflict(
                    "creative source bytes do not match the accepted asset hash",
                    asset_id=str(source.asset_id),
                )
            rights = source.rights
            at = self._now()
            decision = RightsRegistry(self._db, self._clock, self._settings).evaluate(
                rights_route_id=rights.rights_route_id,
                subjects=[(rights.subject_kind, rights.subject_ref)],
                territories=rights.territories,
                at=at,
            )
            if not decision.eligible:
                raise Conflict(
                    "creative source rights are not currently eligible",
                    asset_id=str(source.asset_id),
                    blockers=decision.blockers,
                )
            rights_row = self._row(
                "SELECT id, rights_route_id, version, subject_kind, subject_ref, territories, "
                "commercial_use, output_release_allowed, required_disclosures, expires_at, "
                "evidence, status, created_at FROM rights_registry WHERE rights_route_id = %s "
                "AND subject_kind = %s AND subject_ref = %s AND current",
                (rights.rights_route_id, rights.subject_kind.value, rights.subject_ref),
            )
            evidence = rights_row["evidence"] if rights_row is not None else []
            current_record = (
                RightsRecord(
                    record_id=rights_row["id"],
                    rights_route_id=rights_row["rights_route_id"],
                    version=rights_row["version"],
                    subject_kind=rights_row["subject_kind"],
                    subject_ref=rights_row["subject_ref"],
                    territories=rights_row["territories"],
                    commercial_use=rights_row["commercial_use"],
                    output_release_allowed=rights_row["output_release_allowed"],
                    required_disclosures=rights_row["required_disclosures"],
                    expires_at=rights_row["expires_at"],
                    evidence=[EvidenceRef.model_validate(item) for item in evidence],
                    status=RightsStatus(rights_row["status"]),
                    recorded_at=rights_row["created_at"],
                )
                if rights_row is not None
                else None
            )
            try:
                validate_current_rights_grant(
                    rights,
                    lambda _route, _kind, _ref, record=current_record: record,
                    at=at,
                    territories=list(rights.territories),
                )
            except ValueError as exc:
                raise Conflict(
                    "creative source rights do not match current eligible registry evidence",
                    asset_id=str(source.asset_id),
                ) from exc
            current.append(descriptor)
        return current

    def _creative_records(self, episode_id: UUID) -> list[CreativeDerivativeRef]:
        records: list[CreativeDerivativeRef] = []
        for row in self._rows(
            "SELECT payload FROM domain_events WHERE aggregate_type = 'episode' "
            "AND aggregate_id = %s AND event_type = 'editing.creative_derivative_created' "
            "ORDER BY sequence",
            (episode_id,),
        ):
            payload = row["payload"]
            if isinstance(payload, dict) and "creative_derivative" in payload:
                records.append(CreativeDerivativeRef.model_validate(payload["creative_derivative"]))
        return records

    @staticmethod
    def _zone_text_box(box: Any) -> SafeZoneTextBox:
        return SafeZoneTextBox(
            x_bp=box.left,
            y_bp=box.top,
            width_bp=box.right - box.left,
            height_bp=box.bottom - box.top,
        )

    @staticmethod
    def _platform_zone(plan: Any, *, poster: bool) -> PlatformSafeZone:
        safe = plan.safe_zone
        return PlatformSafeZone(
            platform=plan.platform,
            top_bp=safe.top,
            right_bp=10_000 - safe.right,
            bottom_bp=10_000 - safe.bottom,
            left_bp=safe.left,
            title_box=VariantsService._zone_text_box(plan.title_box) if poster else None,
            cta_box=VariantsService._zone_text_box(plan.cta_box),
        )

    def derive_poster(self, plan: PosterPlan) -> CreativeDerivativeRef:
        """Render, verify, and persist the poster and its exact Gate 2 reference."""
        episode = self._episode_row(plan.episode_id)
        if int(episode["episode_number"]) < plan.approved_reveal_episode:
            raise SchemaInvalid("poster reveals story beyond this episode's approved boundary")
        if int(episode["episode_number"]) == 1 and plan.approved_reveal_episode != 1:
            raise SchemaInvalid("episode-one poster must use the episode-one approved reveal")
        sources = [
            DerivativeSourceRef(
                role="CHARACTER",
                asset_id=plan.character.asset.asset_id,
                asset_sha256=plan.character.asset.sha256,
                asset_version=plan.character.asset.version,
                rights=plan.character.rights,
            ),
            DerivativeSourceRef(
                role="TITLE",
                asset_id=plan.title.asset.asset_id,
                asset_sha256=plan.title.asset.sha256,
                asset_version=plan.title.asset.version,
                rights=plan.title.rights,
            ),
            DerivativeSourceRef(
                role="CTA",
                asset_id=plan.cta.asset.asset_id,
                asset_sha256=plan.cta.asset.sha256,
                asset_version=plan.cta.asset.version,
                rights=plan.cta.rights,
            ),
        ]
        self._creative_sources_current(sources)
        with TemporaryDirectory(prefix="md-poster-") as tmp:
            runner = FFmpegRunner(workdir=Path(tmp), timeout_ms=self._config.ffmpeg_timeout_ms)
            names: dict[UUID, str] = {}
            for source in sources:
                desc = self._asset(source.asset_id)
                name = f"{source.asset_id.hex}.png"
                stage_bytes(runner, name=name, data=self._store.get_bytes(desc.object_key))
                names[source.asset_id] = name
            run_poster_export(runner, source_names=names, plan=plan, output="poster.jpg")
            output = (runner.workdir / "poster.jpg").read_bytes()
        zone = self._platform_zone(plan, poster=True)
        return self._persist_creative_derivative(
            episode_id=plan.episode_id,
            derivative_type="POSTER",
            output=output,
            media=None,
            sources=sources,
            zones=[zone],
            title_text=plan.title_text,
            cta_text=plan.cta_text,
            approved_reveal_episode=plan.approved_reveal_episode,
            readability_evidence_sha256=plan.readability_evidence_sha256,
            derivation_manifest={
                "plan_sha256": plan.package_hash,
                "approved_reveal_episode": plan.approved_reveal_episode,
                "source_ranges_ms": [],
                "readability_check": plan.readability_check,
                "readability_evidence_sha256": plan.readability_evidence_sha256,
                "variant_key": plan.variant_key,
            },
        )

    def derive_episode_one_preview(self, plan: PreviewPlan) -> CreativeDerivativeRef:
        """Export accepted footage and persist its measured, optional preview reference."""
        episode = self._episode_row(plan.source_edl.episode_id)
        if int(episode["episode_number"]) != 1:
            raise SchemaInvalid("episode-one preview is permitted only for episode one")
        source_by_id = {source.asset.asset_id: source for source in plan.sources}
        if len(source_by_id) != len(plan.sources):
            raise SchemaInvalid("preview source descriptors must be unique by asset")
        if set(source_by_id) != {clip.source_asset_id for clip in plan.source_edl.clips}:
            raise SchemaInvalid("preview source descriptors must exactly cover every EDL input")
        sources: list[DerivativeSourceRef] = []
        for clip in plan.source_edl.clips:
            source = source_by_id[clip.source_asset_id]
            sources.append(
                DerivativeSourceRef(
                    role="FOOTAGE" if clip.track.value == "VIDEO" else "AUDIO",
                    asset_id=source.asset.asset_id,
                    asset_sha256=source.asset.sha256,
                    asset_version=source.asset.version,
                    source_in_ms=clip.source_in_ms,
                    source_out_ms=clip.source_out_ms,
                    rights=source.rights,
                )
            )
        self._creative_sources_current(sources)
        video_ids = {
            clip.source_asset_id for clip in plan.source_edl.clips if clip.track.value == "VIDEO"
        }
        if not video_ids:
            raise SchemaInvalid("episode-one preview requires at least one footage source")
        self._accepted_guard(video_ids, what="episode-one preview")
        all_ids = {clip.source_asset_id for clip in plan.source_edl.clips}
        for clip in plan.source_edl.clips:
            descriptor = self._asset(clip.source_asset_id)
            if descriptor.media is None or clip.source_out_ms > descriptor.media.duration_ms:
                raise SchemaInvalid(
                    "preview source range exceeds measured source media",
                    asset_id=str(clip.source_asset_id),
                    source_out_ms=clip.source_out_ms,
                    media_duration_ms=descriptor.media.duration_ms if descriptor.media else None,
                )
        with TemporaryDirectory(prefix="md-preview-") as tmp:
            runner = FFmpegRunner(workdir=Path(tmp), timeout_ms=self._config.ffmpeg_timeout_ms)
            names: dict[UUID, str] = {}
            for asset_id in sorted(all_ids):
                descriptor = self._asset(asset_id)
                suffix = _STAGE_SUFFIX.get(descriptor.asset_kind, ".bin")
                name = f"{asset_id.hex}{suffix}"
                stage_bytes(runner, name=name, data=self._store.get_bytes(descriptor.object_key))
                names[asset_id] = name
            run_preview_export(runner, source_names=names, plan=plan, output="preview.mp4")
            preview_path = runner.workdir / "preview.mp4"
            media = runner.probe(preview_path)
            if not media.has_video or media.duration_ms > 90_000:
                raise SchemaInvalid("preview output failed measured stream/duration checks")
            output = preview_path.read_bytes()
        zone = self._platform_zone(plan, poster=False)
        return self._persist_creative_derivative(
            episode_id=plan.source_edl.episode_id,
            derivative_type="EPISODE_ONE_PREVIEW",
            output=output,
            media=media,
            sources=sources,
            zones=[zone],
            title_text=None,
            cta_text=plan.cta_text,
            approved_reveal_episode=plan.approved_reveal_episode,
            duration_ms=media.duration_ms,
            reveal_boundary_ms=plan.reveal_boundary_ms,
            derivation_manifest={
                "plan_sha256": plan.package_hash,
                "source_edl": plan.source_edl.model_dump(mode="json"),
                "source_ranges_ms": plan.source_ranges_ms,
                "variant_key": plan.variant_key,
            },
        )

    def _persist_creative_derivative(
        self,
        *,
        episode_id: UUID | None,
        derivative_type: str,
        output: bytes,
        media: MediaInfo | None,
        sources: list[DerivativeSourceRef],
        zones: list[PlatformSafeZone],
        title_text: str | None,
        cta_text: str,
        approved_reveal_episode: int,
        readability_evidence_sha256: str | None = None,
        duration_ms: int | None = None,
        reveal_boundary_ms: int | None = None,
        derivation_manifest: dict[str, Any],
    ) -> CreativeDerivativeRef:
        if episode_id is None:
            raise SchemaInvalid("creative derivative source is not bound to an episode")
        self._creative_sources_current(sources)
        source_body = [source.model_dump(mode="json") for source in sources]
        digest = sha256(output).hexdigest()
        semantic_fields = {
            "type": derivative_type,
            "output_sha256": digest,
            "sources": source_body,
            "zones": [zone.model_dump(mode="json") for zone in zones],
            "title_text": title_text,
            "cta_text": cta_text,
            "duration_ms": duration_ms,
            "reveal_boundary_ms": reveal_boundary_ms,
            "approved_reveal_episode": approved_reveal_episode,
            "readability_evidence_sha256": readability_evidence_sha256,
            "derivation_manifest": derivation_manifest,
        }
        semantic_key = canonical_hash(semantic_fields)
        prior = self._creative_records(episode_id)
        manifests_by_id = {
            str(payload["creative_derivative"]["asset_id"]): payload.get("derivation_manifest")
            for row in self._rows(
                "SELECT payload FROM domain_events WHERE aggregate_type = 'episode' "
                "AND aggregate_id = %s AND event_type = 'editing.creative_derivative_created'",
                (episode_id,),
            )
            if isinstance((payload := row["payload"]), dict)
            and isinstance(payload.get("creative_derivative"), dict)
        }
        replay = next(
            (
                record
                for record in prior
                if canonical_hash(
                    {
                        "type": record.derivative_type,
                        "output_sha256": record.asset_sha256,
                        "sources": [source.model_dump(mode="json") for source in record.sources],
                        "zones": [
                            zone.model_dump(mode="json") for zone in record.platform_safe_zones
                        ],
                        "title_text": record.title_text,
                        "cta_text": record.cta_text,
                        "duration_ms": record.duration_ms,
                        "reveal_boundary_ms": record.reveal_boundary_ms,
                        "approved_reveal_episode": record.approved_reveal_episode,
                        "readability_evidence_sha256": record.readability_evidence_sha256,
                        "derivation_manifest": manifests_by_id.get(str(record.asset_id)),
                    }
                )
                == semantic_key
            ),
            None,
        )
        if replay is not None:
            if self._asset_state(replay.asset_id) == AssetState.ACCEPTED.value:
                return replay
        version = (
            max(
                (item.asset_version for item in prior if item.derivative_type == derivative_type),
                default=0,
            )
            + 1
        )
        asset_id = uuid5_name("creative-derivative", f"{semantic_key}:{version}")
        ref = CreativeDerivativeRef(
            derivative_type=derivative_type,
            asset_id=asset_id,
            asset_version=version,
            asset_sha256=digest,
            sources=sources,
            duration_ms=duration_ms,
            reveal_boundary_ms=reveal_boundary_ms,
            platform_safe_zones=zones,
            title_text=title_text,
            cta_text=cta_text,
            derivation_manifest_sha256=canonical_hash(derivation_manifest),
            approved_reveal_episode=approved_reveal_episode,
            readability_evidence_sha256=readability_evidence_sha256,
        )
        # Supersede only historical derivatives that depended on a source whose
        # exact accepted hash has changed. Unrelated derivatives remain accepted.
        for old in prior:
            if old.asset_id == asset_id:
                continue
            changed = False
            for old_source in old.sources:
                try:
                    now_source = self._asset(old_source.asset_id)
                except NotFound:
                    changed = True
                    break
                if (
                    now_source.sha256 != old_source.asset_sha256
                    or now_source.version != old_source.asset_version
                    or self._asset_state(old_source.asset_id) not in _ACCEPTED_ASSET_STATES
                ):
                    changed = True
                    break
            if not changed:
                try:
                    self._creative_sources_current(old.sources)
                except Conflict:
                    changed = True
            if changed:
                self._supersede_creative_asset(old.asset_id)
        now = self._now()
        media_type = "image/jpeg" if derivative_type == "POSTER" else "video/mp4"
        suffix = ".jpg" if derivative_type == "POSTER" else ".mp4"
        stored = self._store.put_bytes(
            f"edits/{episode_id}/creatives/{asset_id.hex}{suffix}", output, media_type=media_type
        )
        if stored.sha256 != digest:
            raise Conflict("creative derivative object store returned a different output hash")
        lineage = sorted({source.asset_id for source in sources}, key=str)
        descriptor = AssetDescriptor(
            asset_id=asset_id,
            asset_kind=AssetKind.IMAGE if derivative_type == "POSTER" else AssetKind.VIDEO,
            object_key=stored.key,
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            media_type=media_type,
            media=media,
            state=AssetState.ACCEPTED,
            provenance=Provenance.DERIVED_LOCAL,
            episode_id=episode_id,
            season_id=self._episode_row(episode_id)["season_id"],
            version=version,
            lineage=lineage,
            license_refs=sorted({source.rights.rights_route_id for source in sources}),
            created_at=now,
        )
        ref = ref.model_copy(update={"asset_sha256": stored.sha256})
        with self._db.transaction() as tx:
            register_asset(tx, descriptor)
            append_event(
                tx,
                aggregate_type="episode",
                aggregate_id=episode_id,
                event_type="editing.creative_derivative_created",
                payload={
                    "creative_derivative": ref.model_dump(mode="json"),
                    "derivation_manifest": derivation_manifest,
                },
                correlation_id=self._new_id(),
                occurred_at=now,
            )
        return ref

    def _supersede_creative_asset(self, asset_id: UUID) -> None:
        with self._db.transaction() as tx:
            row = tx.fetchone("SELECT state, revision FROM assets WHERE id = %s", (asset_id,))
            if row is None or row["state"] != AssetState.ACCEPTED.value:
                return
            update_with_revision(
                tx,
                "assets",
                asset_id,
                int(row["revision"]),
                {"state": AssetState.SUPERSEDED.value},
                now=self._now(),
            )

    def final_review_creatives(self, episode_id: UUID) -> list[CreativeDerivativeRef]:
        """Return current persisted derivatives for T044/T047's Gate 2 projection."""
        latest: dict[str, CreativeDerivativeRef] = {}
        records = sorted(self._creative_records(episode_id), key=lambda item: item.asset_version)
        manifest_by_asset = {
            str(payload["creative_derivative"]["asset_id"]): payload.get("derivation_manifest")
            for row in self._rows(
                "SELECT payload FROM domain_events WHERE aggregate_type = 'episode' "
                "AND aggregate_id = %s AND event_type = 'editing.creative_derivative_created'",
                (episode_id,),
            )
            if isinstance((payload := row["payload"]), dict)
            and isinstance(payload.get("creative_derivative"), dict)
        }
        for record in records:
            try:
                descriptor = self._asset(record.asset_id)
                manifest = manifest_by_asset.get(str(record.asset_id))
                if (
                    self._asset_state(record.asset_id) != AssetState.ACCEPTED.value
                    or descriptor.sha256 != record.asset_sha256
                    or descriptor.version != record.asset_version
                    or sha256(self._store.get_bytes(descriptor.object_key)).hexdigest()
                    != record.asset_sha256
                    or not isinstance(manifest, dict)
                    or canonical_hash(manifest) != record.derivation_manifest_sha256
                ):
                    raise Conflict("creative derivative bytes or state changed")
                self._creative_sources_current(record.sources)
            except (Conflict, NotFound):
                self._supersede_creative_asset(record.asset_id)
                continue
            previous = latest.get(record.derivative_type)
            if previous is None or record.asset_version > previous.asset_version:
                latest[record.derivative_type] = record
        return [latest[key] for key in sorted(latest)]

    def final_review_creative_manifests(self, episode_id: UUID) -> list[dict[str, Any]]:
        """Lineage and QA evidence not represented by the frozen Gate 2 derivative ref."""
        manifests: list[dict[str, Any]] = []
        valid_ids = {str(record.asset_id) for record in self.final_review_creatives(episode_id)}
        for row in self._rows(
            "SELECT payload FROM domain_events WHERE aggregate_type = 'episode' "
            "AND aggregate_id = %s AND event_type = 'editing.creative_derivative_created' "
            "ORDER BY sequence",
            (episode_id,),
        ):
            payload = row["payload"]
            manifest = payload.get("derivation_manifest") if isinstance(payload, dict) else None
            derivative = payload.get("creative_derivative") if isinstance(payload, dict) else None
            if (
                isinstance(manifest, dict)
                and isinstance(derivative, dict)
                and str(derivative.get("asset_id")) in valid_ids
            ):
                manifests.append(manifest)
        return manifests

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
        """Everything the ordinary final-review package embeds for this episode.

        Media refs are content-deduped by sha256 (first occurrence wins, so the
        role order master → burned → variant → hook → cover is stable): a variant
        whose crop is byte-identical to the master is the SAME content, and the
        package contract forbids duplicate media hashes (T030-02c — with the
        variants stage actually exporting, the 16:9 variant duplicated the master
        and Gate 2 rejected the package).
        """
        media: list[MediaRef] = []
        seen_sha: set[str] = set()

        def _add(ref: MediaRef) -> None:
            if ref.sha256 in seen_sha:
                return
            seen_sha.add(ref.sha256)
            media.append(ref)

        main_row = self._row(
            "SELECT output_asset_id FROM edit_manifests WHERE episode_id = %s "
            "AND variant_key = 'main' AND output_asset_id IS NOT NULL "
            "ORDER BY version DESC LIMIT 1",
            (episode_id,),
        )
        if main_row is not None:
            master = self._asset(main_row["output_asset_id"])
            _add(MediaRef(asset_id=master.asset_id, sha256=master.sha256, role="master"))
            burned = self._burned_derivative(master.asset_id)
            if burned is not None:
                _add(MediaRef(asset_id=burned.asset_id, sha256=burned.sha256, role="burned"))
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
                _add(MediaRef(asset_id=descriptor.asset_id, sha256=descriptor.sha256, role="hook"))
                hook_ids.append(row["variant_key"])
                continue
            _add(MediaRef(asset_id=descriptor.asset_id, sha256=descriptor.sha256, role="variant"))
            variant_keys.append(row["variant_key"])
            burned = self._burned_derivative(descriptor.asset_id)
            if burned is not None:
                _add(MediaRef(asset_id=burned.asset_id, sha256=burned.sha256, role="variant"))
        creative_derivatives = self.final_review_creatives(episode_id)
        for derivative in creative_derivatives:
            for source in derivative.sources:
                _add(
                    MediaRef(
                        asset_id=source.asset_id,
                        sha256=source.asset_sha256,
                        role="creative_source",
                    )
                )
            role = "poster" if derivative.derivative_type == "POSTER" else "preview"
            _add(
                MediaRef(
                    asset_id=derivative.asset_id,
                    sha256=derivative.asset_sha256,
                    role=role,
                )
            )
        for row in self._rows(
            "SELECT descriptor FROM assets WHERE episode_id = %s AND asset_kind = 'IMAGE' "
            "AND provenance = 'DERIVED_LOCAL' ORDER BY id",
            (episode_id,),
        ):
            descriptor = AssetDescriptor.model_validate(row["descriptor"])
            _add(MediaRef(asset_id=descriptor.asset_id, sha256=descriptor.sha256, role="cover"))
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
            creative_derivatives=creative_derivatives or None,
            creative_derivation_manifests=self.final_review_creative_manifests(episode_id),
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
