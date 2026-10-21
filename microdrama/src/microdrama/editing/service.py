"""Editing service (T015): EDL assembly, exports, captions and invalidation.

``assemble_episode`` is the step behind the frozen ``editing.assemble`` production
step. For the episode's current script/manifest it:

1. reads the CURRENT script/manifest (the frozen T010 shape, with T011's measured
   ``actual_duration_ms``/``voice_id`` filled) and resolves every line's persisted
   dialogue audio asset plus the caller's accepted shot video assets;
2. claims the episode row (the house ``episodes.correlation_id`` claim) and moves
   RENDERING -> ASSEMBLING;
3. deterministically builds the EDL (explicit cuts, continuous room bed) and, when a
   paid storage/transfer price is configured, holds a real CPU_STORAGE_TRANSFER
   reservation before any export — with the default (local, free) config nothing is
   reserved and nothing is claimed as billed;
4. exports the clean master through argument-safe FFmpeg (normalization + mix), spots
   caption tracks from the actual audio placement with the no-fake-correction guard,
   and burns the primary-locale captions through libass with the resolved Thai font;
5. persists edit manifests, caption tracks and DERIVED_LOCAL assets with lineage,
   invalidates stale outputs — a replaced line's audio invalidates exactly its cues —
   and moves ASSEMBLING -> AI_REVIEW.

Idempotency follows the house pattern: deterministic uuid5 ids, content-addressed
export assets and a replay path that returns the existing outputs without re-running
FFmpeg. Determinism: the same script/manifest/assets/config produce the same EDL and
byte-identical exports on one FFmpeg build.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID, uuid5

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.cost import BudgetReservationRequest, ExposureCeilings
from microdrama.contracts.enums import (
    AssetKind,
    AssetState,
    BudgetCategory,
    BudgetScopeKind,
    EpisodeState,
    PrincipalKind,
    Provenance,
    QueueName,
    Severity,
)
from microdrama.contracts.errors import (
    Conflict,
    InvalidTransition,
    MicrodramaError,
    NotFound,
    SchemaInvalid,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.infra import Clock, IdGenerator, ObjectStore
from microdrama.contracts.media import AssetDescriptor, CaptionTrack, EditDecisionList, MediaInfo
from microdrama.contracts.principals import Principal
from microdrama.contracts.season import Script, SeasonScope, ShotManifest
from microdrama.core.events import append_event
from microdrama.core.state_machine import transition_episode
from microdrama.editing.captions import (
    SpeechObserver,
    spot_caption_track,
    srt_bytes,
    stale_cues,
    track_body_hash,
)
from microdrama.editing.config import EditingConfig
from microdrama.editing.edl import (
    EDITING_NAMESPACE,
    LineSource,
    ShotSource,
    ambience_covers_timeline,
    build_edl,
    burned_asset_id_for,
    caption_asset_id_for,
    edl_semantic_hash,
    master_asset_id_for,
    room_asset_id_for,
    shot_prompt_digest,
    video_gap_ranges,
)
from microdrama.editing.export import render_room_tone, run_burned_export, run_master_export
from microdrama.editing.ffmpeg import FFmpegRunner, stage_bytes, stage_file
from microdrama.editing.fonts import resolve_caption_font
from microdrama.editing.models import (
    AssemblyOutcome,
    AssemblyStatus,
    EditingFinding,
    TechnicalCheck,
)
from microdrama.persistence.assets import register_asset
from microdrama.persistence.db import Database, Tx, insert_row, jsonb, update_with_revision
from microdrama.references.anchors import ref_id_for

TRANSFER_OPERATION = "editing.export_transfer"
ASSEMBLE_STATES = (EpisodeState.RENDERING.value, EpisodeState.ASSEMBLING.value)
_ACCEPTED_ASSET_STATES = (AssetState.ACCEPTED.value, AssetState.LOCKED.value)


def _deterministic_id(kind: str, key: str) -> UUID:
    return uuid5(EDITING_NAMESPACE, f"{kind}:{key}")


@dataclass
class _Claim:
    episode_id: UUID
    season_id: UUID
    episode_number: int
    title_th: str
    claim_token: UUID
    script: Script
    manifest: ShotManifest


class EditingService:
    """EDL assembly, exports and caption invalidation. Construct once per process."""

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
        self._id_lock = threading.Lock()
        self._principal = Principal(
            principal_id="svc:editing-worker", kind=PrincipalKind.SERVICE_WORKER
        )

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
        """The episode's CURRENT script (same reader shape as the story lane's)."""
        row = self._row(
            "SELECT body FROM scripts WHERE episode_id = %s AND status = 'CURRENT'", (episode_id,)
        )
        if row is None:
            raise NotFound("episode has no current script", episode_id=str(episode_id))
        return Script.model_validate(row["body"])

    def manifest(self, episode_id: UUID) -> ShotManifest:
        """The episode's CURRENT shot manifest (same reader shape as the story lane's)."""
        row = self._row(
            "SELECT body FROM shot_manifests WHERE episode_id = %s AND status = 'CURRENT'",
            (episode_id,),
        )
        if row is None:
            raise NotFound("episode has no current shot manifest", episode_id=str(episode_id))
        return ShotManifest.model_validate(row["body"])

    def captions(self, episode_id: UUID) -> list[CaptionTrack]:
        rows = self._rows(
            "SELECT body FROM caption_tracks WHERE episode_id = %s AND state = 'CURRENT'",
            (episode_id,),
        )
        return [CaptionTrack.model_validate(row["body"]) for row in rows]

    def edit_manifest(self, episode_id: UUID) -> EditDecisionList | None:
        row = self._row(
            "SELECT edl FROM edit_manifests WHERE episode_id = %s AND variant_key = 'main' "
            "ORDER BY version DESC LIMIT 1",
            (episode_id,),
        )
        return EditDecisionList.model_validate(row["edl"]) if row is not None else None

    def stale_caption_cues(self, episode_id: UUID) -> list[str]:
        """Cue ids whose line audio changed since their CURRENT track was derived (T019 hook)."""
        line_sha = {
            ls.line_id: ls.asset_sha256
            for ls in self._line_sources(episode_id, self.script(episode_id)).values()
        }
        stale: list[str] = []
        for track in self.captions(episode_id):
            stale.extend(stale_cues(track, line_sha))
        return sorted(stale)

    # --- source resolution --------------------------------------------------------------

    def _line_sources(self, episode_id: UUID, script: Script) -> dict[str, LineSource]:
        sources: dict[str, LineSource] = {}
        for scene in script.scenes:
            for line in scene.lines:
                if line.actual_duration_ms is None:
                    raise Conflict(
                        "line audio has no measured duration; the references step must run "
                        "before assembly",
                        line_id=line.line_id,
                    )
                asset_id = ref_id_for(
                    "line-audio",
                    f"{episode_id}:{line.line_id}:{canonical_hash(line.text_th)[:12]}",
                )
                row = self._row("SELECT descriptor FROM assets WHERE id = %s", (asset_id,))
                if row is None:
                    raise Conflict(
                        "line audio asset is missing; the references step must complete first",
                        line_id=line.line_id,
                    )
                descriptor = AssetDescriptor.model_validate(row["descriptor"])
                if descriptor.media is None or descriptor.media.duration_ms <= 0:
                    raise Conflict(
                        "line audio asset carries no measured duration", line_id=line.line_id
                    )
                sources[line.line_id] = LineSource(
                    line_id=line.line_id,
                    asset_id=asset_id,
                    asset_sha256=descriptor.sha256,
                    duration_ms=descriptor.media.duration_ms,
                )
        return sources

    def _shot_sources(self, shot_assets: Mapping[str, UUID]) -> dict[str, ShotSource]:
        sources: dict[str, ShotSource] = {}
        for shot_id, asset_id in shot_assets.items():
            row = self._row("SELECT state, descriptor FROM assets WHERE id = %s", (asset_id,))
            if row is None:
                raise NotFound(
                    "shot video asset not found", shot_id=shot_id, asset_id=str(asset_id)
                )
            descriptor = AssetDescriptor.model_validate(row["descriptor"])
            if descriptor.asset_kind is not AssetKind.VIDEO:
                raise SchemaInvalid("shot source asset is not a video", shot_id=shot_id)
            if row["state"] not in _ACCEPTED_ASSET_STATES:
                raise Conflict(
                    "shot source asset is not accepted", shot_id=shot_id, state=row["state"]
                )
            if descriptor.media is None or descriptor.media.duration_ms <= 0:
                raise Conflict("shot source has no measured duration", shot_id=shot_id)
            sources[shot_id] = ShotSource(
                shot_id=shot_id,
                asset_id=asset_id,
                asset_sha256=descriptor.sha256,
                duration_ms=descriptor.media.duration_ms,
            )
        return sources

    # --- assembly -----------------------------------------------------------------------

    def assemble_episode(
        self, episode_id: UUID, *, shot_assets: Mapping[str, UUID]
    ) -> AssemblyOutcome:
        """Assemble the current script/manifest into exports (idempotent, typed)."""
        script = self.script(episode_id)
        manifest = self.manifest(episode_id)
        line_sources = self._line_sources(episode_id, script)
        shot_sources = self._shot_sources(shot_assets)
        episode_row = self._row(
            "SELECT e.*, s.title_th AS season_title FROM episodes e "
            "JOIN seasons s ON s.id = e.season_id WHERE e.id = %s",
            (episode_id,),
        )
        if episode_row is None:
            raise NotFound("episode not found", episode_id=str(episode_id))
        prompt_digest = shot_prompt_digest(
            manifest,
            script,
            episode_number=episode_row["episode_number"],
            title_th=episode_row["season_title"],
        )
        room_asset_id = room_asset_id_for(episode_id, prompt_digest)
        edl = build_edl(
            episode_id=episode_id,
            manifest=manifest,
            script=script,
            shot_sources=shot_sources,
            line_sources=line_sources,
            room_asset_id=room_asset_id,
            config=self._config,
            prompt_digest=prompt_digest,
        )
        edl_hash = edl_semantic_hash(edl)
        if edl.duration_ms > self._config.max_export_duration_ms:
            raise SchemaInvalid(
                "EDL duration exceeds the configured export ceiling (CPU bound)",
                duration_ms=edl.duration_ms,
                ceiling_ms=self._config.max_export_duration_ms,
            )
        line_sha = {ls.line_id: ls.asset_sha256 for ls in line_sources.values()}
        replay = self._replay_outcome(episode_id, edl_hash, line_sha)
        if replay is not None:
            return replay
        claim = self._claim(episode_id, script, manifest, episode_row)
        reservation_ids: list[UUID] = []
        try:
            if self._config.transfer_price is not None:
                reservation_ids = [self._reserve_transfer(claim, edl)]
            return self._execute(
                claim, edl, edl_hash, line_sources, shot_sources, room_asset_id, reservation_ids
            )
        except BaseException:
            self._release_claim(claim)
            raise

    def _claim(
        self,
        episode_id: UUID,
        script: Script,
        manifest: ShotManifest,
        episode_row: dict[str, Any],
    ) -> _Claim:
        now = self._now()
        claim_token = self._new_id()
        with self._db.transaction() as tx:
            row = tx.fetchone("SELECT * FROM episodes WHERE id = %s FOR UPDATE", (episode_id,))
            if row is None:
                raise NotFound("episode vanished during assembly claim")
            if row["state"] not in ASSEMBLE_STATES:
                raise InvalidTransition(
                    "assembly accepts RENDERING (first pass) or ASSEMBLING (repair) only",
                    state=row["state"],
                )
            if row["correlation_id"] is not None:
                raise Conflict(
                    "another production step already claimed this episode",
                    claim_id=str(row["correlation_id"]),
                )
            revision = row["revision"]
            if row["state"] == EpisodeState.RENDERING.value:
                revision = transition_episode(
                    tx,
                    episode_id=episode_id,
                    to=EpisodeState.ASSEMBLING,
                    expected_revision=revision,
                    actor=self._principal,
                    now=now,
                    correlation_id=claim_token,
                )
            update_with_revision(
                tx, "episodes", episode_id, revision, {"correlation_id": claim_token}, now=now
            )
        return _Claim(
            episode_id=episode_id,
            season_id=episode_row["season_id"],
            episode_number=episode_row["episode_number"],
            title_th=episode_row["season_title"],
            claim_token=claim_token,
            script=script,
            manifest=manifest,
        )

    def _release_claim(self, claim: _Claim) -> None:
        """Clear this call's claim when it is still ours (typed answers take precedence)."""
        try:
            with self._db.transaction() as tx:
                row = tx.fetchone(
                    "SELECT revision, correlation_id FROM episodes WHERE id = %s FOR UPDATE",
                    (claim.episode_id,),
                )
                if row is None or row["correlation_id"] != claim.claim_token:
                    return
                update_with_revision(
                    tx,
                    "episodes",
                    claim.episode_id,
                    row["revision"],
                    {"correlation_id": None},
                    now=self._now(),
                )
        except MicrodramaError:
            pass

    # --- paid-step hook (CPU/storage/transfer) ------------------------------------------

    def _reserve_transfer(self, claim: _Claim, edl: EditDecisionList) -> UUID:
        """Hold a real CPU_STORAGE_TRANSFER reservation before a paid transfer runs.

        The local FFmpeg export itself is free, so nothing is reserved by default
        (``transfer_price`` None). When a price IS configured, the pipeline plays the
        full budget discipline: account opened from the approved policy, worst case
        derived from the EDL duration, reservation held before dispatch and released
        (with reason) when the local export finishes unbilled.
        """
        price = self._config.transfer_price
        if price is None:
            raise SchemaInvalid("transfer price disappeared between plan and dispatch")
        seconds = max(1, -(-edl.duration_ms // 1000))
        worst = price.unit_price_micro_usd * seconds
        semantic_key = f"edit:{claim.episode_id}:transfer:v1"
        now = self._now()
        with self._db.transaction() as tx:
            scope_row = tx.fetchone(
                "SELECT scope FROM season_proposals WHERE season_id = %s AND status = 'APPROVED'",
                (claim.season_id,),
            )
            if scope_row is None:
                raise Conflict("season has no approved scope; a paid export step cannot reserve")
            scope = SeasonScope.model_validate(scope_row["scope"])
            self._budget.open_episode_account(
                tx,
                season_id=claim.season_id,
                episode_id=claim.episode_id,
                policy=scope.cost_policy,
            )
        reservation = self._budget.reserve(
            BudgetReservationRequest(
                request_id=_deterministic_id("editreq", semantic_key),
                semantic_key=semantic_key,
                scope_kind=BudgetScopeKind.EPISODE,
                episode_id=claim.episode_id,
                category=BudgetCategory.CPU_STORAGE_TRANSFER,
                queue=QueueName.PRODUCTION,
                provider="local-ffmpeg",
                operation_kind=TRANSFER_OPERATION,
                price=price,
                ceilings=ExposureCeilings(
                    timeout_ms=self._config.ffmpeg_timeout_ms,
                    max_units=seconds,
                    max_duration_ms=edl.duration_ms,
                ),
                worst_case_micro_usd=worst,
                expires_at=now + timedelta(milliseconds=self._config.reservation_ttl_ms),
            )
        )
        return reservation.id

    def _release_reservation(self, reservation_id: UUID, *, reason: str) -> None:
        try:
            self._budget.release(reservation_id, reason=reason)
        except MicrodramaError:
            pass

    # --- the export pipeline --------------------------------------------------------------

    def _execute(
        self,
        claim: _Claim,
        edl: EditDecisionList,
        edl_hash: str,
        line_sources: dict[str, LineSource],
        shot_sources: dict[str, ShotSource],
        room_asset_id: UUID,
        reservation_ids: list[UUID],
    ) -> AssemblyOutcome:
        findings: list[EditingFinding] = []
        notes: list[str] = (
            [] if reservation_ids else ["export pipeline is local ffmpeg; no paid step configured"]
        )
        line_sha = {ls.line_id: ls.asset_sha256 for ls in line_sources.values()}
        line_text_th = {
            line.line_id: line.text_th for scene in claim.script.scenes for line in scene.lines
        }
        line_text_en = {
            line.line_id: line.text_en for scene in claim.script.scenes for line in scene.lines
        }
        tracks: dict[str, CaptionTrack] = {}
        for locale in self._config.caption_locales:
            track, track_findings, track_notes = spot_caption_track(
                episode_id=claim.episode_id,
                locale=locale,
                edl=edl,
                line_sha256=line_sha,
                line_text=line_text_th if locale.startswith("th") else line_text_en,
                line_spoken_text=line_text_th,
                observer=self._observer,
                tail_pad_ms=self._config.cue_tail_pad_ms,
                min_cue_ms=self._config.min_cue_ms,
            )
            tracks[locale] = track
            findings.extend(track_findings)
            notes.extend(f"{locale}:{note}" for note in track_notes)
        with TemporaryDirectory(prefix="md-edit-") as tmp:
            runner = FFmpegRunner(workdir=Path(tmp), timeout_ms=self._config.ffmpeg_timeout_ms)
            names: dict[UUID, str] = self._stage_sources(runner, shot_sources, line_sources)
            room_name = "room.wav"
            render_room_tone(
                runner, output=room_name, duration_ms=edl.duration_ms, config=self._config
            )
            names[room_asset_id] = room_name
            room_media = runner.probe(runner.workdir / room_name)
            master_name = "master.mp4"
            run_master_export(runner, edl=edl, config=self._config, names=names, output=master_name)
            master_path = runner.workdir / master_name
            master_media = runner.probe(master_path)
            master_decodes = runner.decodes_cleanly(master_path)
            srt_names = {locale: f"captions-{locale}.srt" for locale in tracks}
            for locale, track in tracks.items():
                (runner.workdir / srt_names[locale]).write_bytes(srt_bytes(track))
            font = resolve_caption_font(
                self._config, [cue.text for track in tracks.values() for cue in track.cues]
            )
            burned_path: Path | None = None
            burned_media: MediaInfo | None = None
            if font.path is not None and font.coverage_ok:
                stage_file(runner, name="caption-font.otf", source=Path(font.path))
                burned_path = run_burned_export(
                    runner,
                    master_name=master_name,
                    srt_name=srt_names[self._config.burn_locale],
                    font_family=font.family,
                    config=self._config,
                    output="burned.mp4",
                )
                burned_media = runner.probe(burned_path)
            else:
                findings.append(
                    EditingFinding(
                        code="font.thai_unavailable",
                        severity=Severity.MAJOR,
                        detail=(
                            "no installed font covers the caption text; the burn is skipped "
                            "rather than rendered as tofu"
                        ),
                    )
                )
            checks = self._checks(
                edl, tracks, master_media, master_decodes, font, burned_media, burned_path
            )
            outcome = self._persist(
                claim=claim,
                edl=edl,
                edl_hash=edl_hash,
                line_sources=line_sources,
                shot_sources=shot_sources,
                room_asset_id=room_asset_id,
                room_media=room_media,
                master_media=master_media,
                burned_media=burned_media,
                runner=runner,
                master_name=master_name,
                burned_name="burned.mp4" if burned_path is not None else None,
                room_name=room_name,
                srt_names=srt_names,
                tracks=tracks,
                font_ok=font.coverage_ok and font.path is not None,
                findings=findings,
                notes=notes,
                checks=checks,
                reservation_ids=reservation_ids,
            )
        for reservation_id in reservation_ids:
            self._release_reservation(
                reservation_id, reason="local export completed; no billed transfer"
            )
        return outcome

    def _stage_sources(
        self,
        runner: FFmpegRunner,
        shot_sources: dict[str, ShotSource],
        line_sources: dict[str, LineSource],
    ) -> dict[UUID, str]:
        names: dict[UUID, str] = {}
        for index, source in enumerate(sorted(shot_sources.values(), key=lambda s: s.asset_id)):
            names[source.asset_id] = f"shot-{index}.mp4"
            self._stage_asset(runner, names[source.asset_id], source.asset_id)
        for index, source in enumerate(sorted(line_sources.values(), key=lambda s: s.asset_id)):
            names[source.asset_id] = f"line-{index}.wav"
            self._stage_asset(runner, names[source.asset_id], source.asset_id)
        return names

    def _stage_asset(self, runner: FFmpegRunner, name: str, asset_id: UUID) -> None:
        row = self._row("SELECT object_key FROM assets WHERE id = %s", (asset_id,))
        if row is None:
            raise NotFound("source asset vanished before staging", asset_id=str(asset_id))
        stage_bytes(runner, name=name, data=self._store.get_bytes(row["object_key"]))

    # --- technical checks -----------------------------------------------------------------

    def _checks(
        self,
        edl: EditDecisionList,
        tracks: dict[str, CaptionTrack],
        master_media: MediaInfo,
        master_decodes: bool,
        font: Any,
        burned_media: MediaInfo | None,
        burned_path: Path | None,
    ) -> list[TechnicalCheck]:
        config = self._config
        gaps = video_gap_ranges(edl)
        room_ok = ambience_covers_timeline(edl)
        cues = [cue for track in tracks.values() for cue in track.cues]
        bounds_ok = all(0 <= cue.start_ms < cue.end_ms <= edl.duration_ms for cue in cues)
        drift = abs(master_media.duration_ms - edl.duration_ms)
        streams_ok = (
            master_media.has_video
            and master_media.has_audio
            and master_media.width == config.output_width
            and master_media.height == config.output_height
            and master_media.sample_rate_hz == config.sample_rate_hz
            and master_media.channels == config.channels
        )
        checks = [
            TechnicalCheck(
                check_id="edit.video_tiling",
                outcome="PASS" if not gaps else "FAIL",
                detail=(
                    "video clips tile the timeline exactly"
                    if not gaps
                    else f"timeline gaps at {gaps[:4]}"
                ),
            ),
            TechnicalCheck(
                check_id="edit.room_continuity",
                outcome="PASS" if room_ok else "FAIL",
                detail=(
                    "ambience spans the whole timeline"
                    if room_ok
                    else "the room-tone bed has holes"
                ),
            ),
            TechnicalCheck(
                check_id="caption.cue_bounds",
                outcome="PASS" if bounds_ok else "FAIL",
                detail=f"{len(cues)} cues inside [0, {edl.duration_ms} ms] and ordered",
            ),
            TechnicalCheck(
                check_id="export.duration",
                outcome="PASS" if drift <= config.duration_tolerance_ms else "FAIL",
                detail=f"probed {master_media.duration_ms} ms vs EDL {edl.duration_ms} ms",
            ),
            TechnicalCheck(
                check_id="export.streams",
                outcome="PASS" if streams_ok else "FAIL",
                detail=(
                    f"{master_media.width}x{master_media.height}@{master_media.fps_num}/"
                    f"{master_media.fps_den}, {master_media.sample_rate_hz} Hz "
                    f"{master_media.channels}ch, audio={master_media.has_audio}"
                ),
            ),
            TechnicalCheck(
                check_id="export.decode",
                outcome="PASS" if master_decodes else "FAIL",
                detail="clean master decoded end-to-end with no error output",
            ),
        ]
        if burned_media is not None and burned_path is not None:
            checks.append(
                TechnicalCheck(
                    check_id="burn.rendered",
                    outcome="PASS",
                    detail=(
                        f"Thai captions burned through libass with {font.family}; "
                        f"{burned_media.duration_ms} ms"
                    ),
                )
            )
        else:
            checks.append(
                TechnicalCheck(
                    check_id="burn.rendered",
                    outcome="UNKNOWN",
                    detail=f"burn skipped: no Thai-safe font ({font.searched} candidates)",
                )
            )
        return checks

    # --- persistence ----------------------------------------------------------------------

    def _persist(  # noqa: PLR0912, PLR0915
        self,
        *,
        claim: _Claim,
        edl: EditDecisionList,
        edl_hash: str,
        line_sources: dict[str, LineSource],
        shot_sources: dict[str, ShotSource],
        room_asset_id: UUID,
        room_media: MediaInfo,
        master_media: MediaInfo,
        burned_media: MediaInfo | None,
        runner: FFmpegRunner,
        master_name: str,
        burned_name: str | None,
        room_name: str,
        srt_names: dict[str, str],
        tracks: dict[str, CaptionTrack],
        font_ok: bool,
        findings: list[EditingFinding],
        notes: list[str],
        checks: list[TechnicalCheck],
        reservation_ids: list[UUID],
    ) -> AssemblyOutcome:
        now = self._now()
        episode_id = claim.episode_id
        master_id = master_asset_id_for(edl_hash)
        source_ids = sorted(
            {s.asset_id for s in shot_sources.values()}
            | {s.asset_id for s in line_sources.values()}
        )
        burn_track = tracks[self._config.burn_locale]
        burned_id = (
            burned_asset_id_for(edl_hash, track_body_hash(burn_track))
            if burned_name is not None
            else None
        )
        invalidated_cue_ids: list[str] = []
        current_line_sha = {ls.line_id: ls.asset_sha256 for ls in line_sources.values()}
        master_bytes = (runner.workdir / master_name).read_bytes()
        burned_bytes = (
            (runner.workdir / burned_name).read_bytes() if burned_name is not None else None
        )
        room_bytes = (runner.workdir / room_name).read_bytes()
        with self._db.transaction() as tx:
            episode = tx.fetchone("SELECT * FROM episodes WHERE id = %s FOR UPDATE", (episode_id,))
            if episode is None:
                raise NotFound("episode vanished during assembly")
            if episode["correlation_id"] != claim.claim_token:
                raise Conflict("the assembly claim was taken over by another step")
            # The room asset id is story-derived; its object key must be too, so a
            # re-assembly with identical room bytes replays the same asset row.
            stored_room = self._store.put_bytes(
                f"edits/{episode_id}/room/{room_asset_id.hex}.wav",
                room_bytes,
                media_type="audio/wav",
            )
            register_asset(
                tx,
                AssetDescriptor(
                    asset_id=room_asset_id,
                    asset_kind=AssetKind.AUDIO,
                    object_key=stored_room.key,
                    sha256=stored_room.sha256,
                    size_bytes=stored_room.size_bytes,
                    media_type="audio/wav",
                    media=room_media,
                    state=AssetState.ACCEPTED,
                    provenance=Provenance.DERIVED_LOCAL,
                    episode_id=episode_id,
                    season_id=claim.season_id,
                    lineage=[],
                    created_at=now,
                ),
            )
            stored_master = self._store.put_bytes(
                f"edits/{episode_id}/master/{edl_hash[:32]}.mp4",
                master_bytes,
                media_type="video/mp4",
            )
            register_asset(
                tx,
                AssetDescriptor(
                    asset_id=master_id,
                    asset_kind=AssetKind.VIDEO,
                    object_key=stored_master.key,
                    sha256=stored_master.sha256,
                    size_bytes=stored_master.size_bytes,
                    media_type="video/mp4",
                    media=master_media,
                    state=AssetState.ACCEPTED,
                    provenance=Provenance.DERIVED_LOCAL,
                    episode_id=episode_id,
                    season_id=claim.season_id,
                    lineage=[room_asset_id, *source_ids],
                    created_at=now,
                ),
            )
            stored_burned = None
            if burned_id is not None and burned_bytes is not None and burned_media is not None:
                stored_burned = self._store.put_bytes(
                    f"edits/{episode_id}/burned/{edl_hash[:32]}.mp4",
                    burned_bytes,
                    media_type="video/mp4",
                )
                register_asset(
                    tx,
                    AssetDescriptor(
                        asset_id=burned_id,
                        asset_kind=AssetKind.VIDEO,
                        object_key=stored_burned.key,
                        sha256=stored_burned.sha256,
                        size_bytes=stored_burned.size_bytes,
                        media_type="video/mp4",
                        media=burned_media,
                        state=AssetState.ACCEPTED,
                        provenance=Provenance.DERIVED_LOCAL,
                        episode_id=episode_id,
                        season_id=claim.season_id,
                        lineage=[master_id],
                        created_at=now,
                    ),
                )
            caption_file_ids: dict[str, UUID] = {}
            for locale, track in tracks.items():
                caption_file_ids[locale] = caption_asset_id_for(track.track_id)
                stored_srt = self._store.put_bytes(
                    f"edits/{episode_id}/captions/{locale}/{track_body_hash(track)[:32]}.srt",
                    (runner.workdir / srt_names[locale]).read_bytes(),
                    media_type="application/x-subrip",
                )
                register_asset(
                    tx,
                    AssetDescriptor(
                        asset_id=caption_file_ids[locale],
                        asset_kind=AssetKind.CAPTION,
                        object_key=stored_srt.key,
                        sha256=stored_srt.sha256,
                        size_bytes=stored_srt.size_bytes,
                        media_type="application/x-subrip",
                        media=None,
                        state=AssetState.ACCEPTED,
                        provenance=Provenance.DERIVED_LOCAL,
                        episode_id=episode_id,
                        season_id=claim.season_id,
                        lineage=sorted({ls.asset_id for ls in line_sources.values()}),
                        created_at=now,
                    ),
                )
                self._write_caption_row(
                    tx,
                    episode_id=episode_id,
                    locale=locale,
                    track=track,
                    caption_asset_id=caption_file_ids[locale],
                    now=now,
                    invalidated_cue_ids=invalidated_cue_ids,
                    current_line_sha=current_line_sha,
                )
            # A replace-back re-produces a previously invalidated EDL bit-for-bit:
            # re-promote that row instead of colliding with its primary key.
            existing_edl = tx.fetchone(
                "SELECT id, version FROM edit_manifests WHERE id = %s", (edl.edl_id,)
            )
            previous = tx.fetchall(
                "SELECT id, edl_hash FROM edit_manifests WHERE episode_id = %s "
                "AND purpose = 'FULL_EPISODE' AND variant_key = 'main' AND state = 'RENDERED' "
                "AND id <> %s",
                (episode_id, edl.edl_id),
            )
            for row in previous:
                tx.execute(
                    "UPDATE edit_manifests SET state = %s, revision = revision + 1, "
                    "updated_at = %s WHERE id = %s",
                    (
                        "INVALIDATED" if row["edl_hash"] != edl_hash else "SUPERSEDED",
                        now,
                        row["id"],
                    ),
                )
            if existing_edl is not None:
                edl_version = existing_edl["version"]
                tx.execute(
                    "UPDATE edit_manifests SET state = 'RENDERED', output_asset_id = %s, "
                    "revision = revision + 1, updated_at = %s WHERE id = %s",
                    (master_id, now, edl.edl_id),
                )
            else:
                edl_version = int(
                    tx.fetchval(
                        "SELECT COALESCE(MAX(version), 0) + 1 FROM edit_manifests "
                        "WHERE episode_id = %s AND purpose = 'FULL_EPISODE' "
                        "AND variant_key = 'main'",
                        (episode_id,),
                    )
                )
                insert_row(
                    tx,
                    "edit_manifests",
                    {
                        "id": edl.edl_id,
                        "episode_id": episode_id,
                        "purpose": "FULL_EPISODE",
                        "variant_key": "main",
                        "version": edl_version,
                        "edl": jsonb(edl),
                        "edl_hash": edl_hash,
                        "output_asset_id": master_id,
                        "state": "RENDERED",
                    },
                    returning="id",
                )
            revision = episode["revision"]
            if episode["state"] == EpisodeState.ASSEMBLING.value:
                revision = transition_episode(
                    tx,
                    episode_id=episode_id,
                    to=EpisodeState.AI_REVIEW,
                    expected_revision=revision,
                    actor=self._principal,
                    now=now,
                    correlation_id=claim.claim_token,
                )
            update_with_revision(
                tx, "episodes", episode_id, revision, {"correlation_id": None}, now=now
            )
            append_event(
                tx,
                aggregate_type="episode",
                aggregate_id=episode_id,
                event_type="editing.assembled",
                payload={
                    "edl_id": str(edl.edl_id),
                    "edl_version": edl_version,
                    "edl_hash": edl_hash[:16],
                    "duration_ms": edl.duration_ms,
                    "clean_asset_id": str(master_id),
                    "burned_asset_id": str(burned_id) if burned_id else None,
                    "caption_track_ids": [str(t.track_id) for t in tracks.values()],
                    "finding_codes": sorted({f.code for f in findings}),
                    "invalidated_cue_ids": sorted(invalidated_cue_ids)[:50],
                    "check_failures": [c.check_id for c in checks if c.outcome == "FAIL"],
                    "font_ok": font_ok,
                },
                correlation_id=claim.claim_token,
                occurred_at=now,
            )
            if invalidated_cue_ids:
                append_event(
                    tx,
                    aggregate_type="episode",
                    aggregate_id=episode_id,
                    event_type="editing.captions_invalidated",
                    payload={"cue_ids": sorted(invalidated_cue_ids)[:50]},
                    correlation_id=claim.claim_token,
                    occurred_at=now,
                )
        return AssemblyOutcome(
            episode_id=episode_id,
            edl_id=edl.edl_id,
            edl_version=edl_version,
            status=AssemblyStatus.ASSEMBLED,
            duration_ms=edl.duration_ms,
            clean_asset_id=master_id,
            clean_sha256=stored_master.sha256,
            burned_asset_id=burned_id,
            burned_sha256=stored_burned.sha256 if stored_burned is not None else None,
            caption_track_ids=sorted(t.track_id for t in tracks.values()),
            burned_caption_track_id=burn_track.track_id,
            findings=findings,
            checks=checks,
            invalidated_cue_ids=sorted(invalidated_cue_ids),
            settled_micro_usd=0,
            reservation_ids=reservation_ids,
            uncertainty_notes=notes,
        )

    def _write_caption_row(
        self,
        tx: Tx,
        *,
        episode_id: UUID,
        locale: str,
        track: CaptionTrack,
        caption_asset_id: UUID,
        now: datetime,
        invalidated_cue_ids: list[str],
        current_line_sha: dict[str, str],
    ) -> None:
        existing = tx.fetchone(
            "SELECT id, state, body_hash FROM caption_tracks WHERE id = %s", (track.track_id,)
        )
        identical_replay = existing is not None and existing["body_hash"] == track_body_hash(track)
        # Flip every OTHER current row first (a replace-back must invalidate the
        # stale replacement track even though the new body replays an old row id).
        stale_rows = tx.fetchall(
            "SELECT id, body FROM caption_tracks WHERE episode_id = %s AND locale = %s "
            "AND state = 'CURRENT' AND id <> %s",
            (episode_id, locale, track.track_id),
        )
        for row in stale_rows:
            old_track = CaptionTrack.model_validate(row["body"])
            stale_ids = stale_cues(old_track, current_line_sha)
            invalidated_cue_ids.extend(stale_ids)
            tx.execute(
                "UPDATE caption_tracks SET state = %s, revision = revision + 1, "
                "updated_at = %s WHERE id = %s",
                ("INVALIDATED" if stale_ids else "SUPERSEDED", now, row["id"]),
            )
        if identical_replay:
            # The identical track exists (possibly INVALIDATED by an earlier
            # replacement). Promote it back; the one-current index is safe because
            # every other current row was just flipped.
            if existing["state"] != "CURRENT":  # type: ignore[index]
                tx.execute(
                    "UPDATE caption_tracks SET state = 'CURRENT', revision = revision + 1, "
                    "updated_at = %s WHERE id = %s",
                    (now, track.track_id),
                )
            return  # exact replay of this track's content: nothing new to write
        version = int(
            tx.fetchval(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM caption_tracks "
                "WHERE episode_id = %s AND locale = %s",
                (episode_id, locale),
            )
        )
        insert_row(
            tx,
            "caption_tracks",
            {
                "id": track.track_id,
                "episode_id": episode_id,
                "locale": locale,
                "version": version,
                "timing_source": track.timing_source.value,
                "body": jsonb(track),
                "body_hash": track_body_hash(track),
                "asset_id": caption_asset_id,
                "state": "CURRENT",
            },
            returning="id",
        )

    # --- replay ---------------------------------------------------------------------------

    def _replay_outcome(
        self,
        episode_id: UUID,
        edl_hash: str,
        line_sha: dict[str, str],
    ) -> AssemblyOutcome | None:
        """An identical, complete assembly already exists: return it without re-export."""
        row = self._row(
            "SELECT * FROM edit_manifests WHERE episode_id = %s AND purpose = 'FULL_EPISODE' "
            "AND variant_key = 'main' AND state = 'RENDERED' AND edl_hash = %s "
            "ORDER BY version DESC LIMIT 1",
            (episode_id, edl_hash),
        )
        if row is None or row["output_asset_id"] is None:
            return None
        master = self._row("SELECT descriptor FROM assets WHERE id = %s", (row["output_asset_id"],))
        if master is None:
            return None
        track_rows = self._rows(
            "SELECT body FROM caption_tracks WHERE episode_id = %s AND state = 'CURRENT'",
            (episode_id,),
        )
        if not track_rows:
            return None
        parsed = [CaptionTrack.model_validate(t["body"]) for t in track_rows]
        if any(stale_cues(track, line_sha) for track in parsed):
            return None  # a line's audio changed since: this is a repair, not a replay
        stored_edl = EditDecisionList.model_validate(row["edl"])
        master_descriptor = AssetDescriptor.model_validate(master["descriptor"])
        burned_descriptor = None
        for asset_row in self._rows(
            "SELECT descriptor FROM assets WHERE episode_id = %s AND asset_kind = 'VIDEO' "
            "AND provenance = 'DERIVED_LOCAL'",
            (episode_id,),
        ):
            descriptor = AssetDescriptor.model_validate(asset_row["descriptor"])
            if master_descriptor.asset_id in descriptor.lineage:
                burned_descriptor = descriptor
        return AssemblyOutcome(
            episode_id=episode_id,
            edl_id=row["id"],
            edl_version=row["version"],
            status=AssemblyStatus.REPLAYED,
            duration_ms=stored_edl.duration_ms,
            clean_asset_id=master_descriptor.asset_id,
            clean_sha256=master_descriptor.sha256,
            burned_asset_id=burned_descriptor.asset_id if burned_descriptor else None,
            burned_sha256=burned_descriptor.sha256 if burned_descriptor else None,
            caption_track_ids=sorted(track.track_id for track in parsed),
            burned_caption_track_id=None,
            findings=[],
            checks=[],
            invalidated_cue_ids=[],
            settled_micro_usd=0,
            reservation_ids=[],
            uncertainty_notes=["identical EDL and outputs already exist; nothing re-exported"],
        )


def build_editing_service(
    db: Database,
    clock: Clock,
    ids: IdGenerator,
    settings: Settings,
    *,
    budget: BudgetService,
    store: ObjectStore,
    config: EditingConfig | None = None,
    speech_observer: SpeechObserver | None = None,
) -> EditingService:
    """Composition-time factory (the integrator registers routes/jobs, not this module)."""
    return EditingService(
        db,
        clock,
        ids,
        settings,
        budget=budget,
        store=store,
        config=config,
        speech_observer=speech_observer,
    )


__all__ = ["ASSEMBLE_STATES", "TRANSFER_OPERATION", "EditingService", "build_editing_service"]
