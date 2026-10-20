"""Assets, edit decision lists, caption tracks and hook experiments."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, model_validator

from microdrama.contracts.enums import (
    AssetKind,
    AssetState,
    CaptionTimingSource,
    Platform,
    Provenance,
    SlotKind,
    TrackKind,
    TrafficKind,
    TransitionKind,
)
from microdrama.contracts.primitives import (
    AccountRef,
    ContractModel,
    Count,
    DurationMs,
    Identifier,
    LocaleTag,
    ObjectKey,
    PositiveInt,
    PositiveMs,
    Sha256Hex,
    ShortText,
    SignedMicroUSD,
    UtcDateTime,
    VersionedPayload,
)


class MediaInfo(ContractModel):
    """Facts measured from the actual file (ffprobe), not from what was requested."""

    duration_ms: DurationMs
    has_video: bool
    has_audio: bool
    width: PositiveInt | None = None
    height: PositiveInt | None = None
    fps_num: PositiveInt | None = None
    fps_den: PositiveInt | None = None
    video_codec: ShortText | None = None
    audio_codec: ShortText | None = None
    sample_rate_hz: PositiveInt | None = None
    channels: PositiveInt | None = None


class AssetDescriptor(VersionedPayload):
    asset_id: UUID
    asset_kind: AssetKind
    object_key: ObjectKey
    sha256: Sha256Hex
    size_bytes: Count
    media_type: ShortText
    media: MediaInfo | None = None
    state: AssetState
    provenance: Provenance
    episode_id: UUID | None = None
    season_id: UUID | None = None
    version: PositiveInt = 1
    lineage: list[UUID] = Field(default_factory=list, description="Source asset IDs")
    license_refs: list[ShortText] = Field(default_factory=list)
    created_at: UtcDateTime

    @model_validator(mode="after")
    def _media_kinds(self) -> AssetDescriptor:
        if self.asset_kind in (AssetKind.VIDEO, AssetKind.AUDIO) and self.media is None:
            raise ValueError("video/audio assets must carry measured media info")
        if self.asset_id in self.lineage:
            raise ValueError("an asset cannot be its own source")
        return self


class CropSpec(ContractModel):
    x: Count
    y: Count
    width: PositiveInt
    height: PositiveInt


class EdlClip(ContractModel):
    clip_id: Identifier
    track: TrackKind
    source_asset_id: UUID
    source_in_ms: DurationMs
    source_out_ms: PositiveMs
    timeline_in_ms: DurationMs
    crop: CropSpec | None = None
    gain_millibel: int = Field(default=0, ge=-6000, le=1200, strict=True)
    dialogue_line_ids: list[Identifier] = Field(default_factory=list)
    transition_in: TransitionKind = TransitionKind.CUT
    transition_ms: DurationMs = 0

    @model_validator(mode="after")
    def _bounds(self) -> EdlClip:
        if self.source_out_ms <= self.source_in_ms:
            raise ValueError("source_out_ms must be greater than source_in_ms")
        if self.transition_in is TransitionKind.CUT and self.transition_ms != 0:
            raise ValueError("a cut has no transition duration")
        if self.transition_ms > self.duration_ms:
            raise ValueError("transition longer than clip")
        return self

    @property
    def duration_ms(self) -> int:
        return self.source_out_ms - self.source_in_ms

    @property
    def timeline_out_ms(self) -> int:
        return self.timeline_in_ms + self.duration_ms


class OutputFormat(ContractModel):
    width: PositiveInt
    height: PositiveInt
    fps_num: PositiveInt
    fps_den: PositiveInt = 1
    sample_rate_hz: PositiveInt = 48_000
    channels: PositiveInt = 2


class EditDecisionList(VersionedPayload):
    """Explicit source/timeline cuts. Script text is never turned into shell commands."""

    edl_id: UUID
    episode_id: UUID
    version: PositiveInt
    purpose: SlotKind
    output: OutputFormat
    clips: list[EdlClip] = Field(min_length=1)
    caption_track_ids: list[UUID] = Field(default_factory=list)
    burn_in_caption_track_id: UUID | None = None

    @model_validator(mode="after")
    def _timeline(self) -> EditDecisionList:
        ids = [c.clip_id for c in self.clips]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate clip_id")
        video = sorted(
            (c for c in self.clips if c.track is TrackKind.VIDEO), key=lambda c: c.timeline_in_ms
        )
        if not video:
            raise ValueError("an EDL needs at least one video clip")
        for prev, nxt in zip(video, video[1:], strict=False):
            overlap_allowed = (
                nxt.transition_ms if nxt.transition_in is TransitionKind.CROSSFADE else 0
            )
            if nxt.timeline_in_ms < prev.timeline_out_ms - overlap_allowed:
                raise ValueError(f"video clips {prev.clip_id}/{nxt.clip_id} overlap")
        if (
            self.burn_in_caption_track_id
            and self.burn_in_caption_track_id not in self.caption_track_ids
        ):
            raise ValueError("burn-in track must be one of caption_track_ids")
        return self

    @property
    def duration_ms(self) -> int:
        return max(c.timeline_out_ms for c in self.clips)


class CaptionCue(ContractModel):
    cue_id: Identifier
    start_ms: DurationMs
    end_ms: PositiveMs
    text: str = Field(min_length=1, max_length=500)
    line_id: Identifier | None = None

    @model_validator(mode="after")
    def _ordered(self) -> CaptionCue:
        if self.end_ms <= self.start_ms:
            raise ValueError("cue end must be after start")
        return self


class CaptionTrack(VersionedPayload):
    track_id: UUID
    episode_id: UUID
    version: PositiveInt
    locale: LocaleTag
    timing_source: CaptionTimingSource
    derived_from_audio_sha256: list[Sha256Hex] = Field(
        default_factory=list, description="Actual audio the timing was aligned to"
    )
    cues: list[CaptionCue] = Field(min_length=1)

    @model_validator(mode="after")
    def _cues(self) -> CaptionTrack:
        ids = [c.cue_id for c in self.cues]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate cue_id")
        for prev, nxt in zip(self.cues, self.cues[1:], strict=False):
            if nxt.start_ms < prev.end_ms:
                raise ValueError(f"cues {prev.cue_id}/{nxt.cue_id} overlap or are unordered")
        if (
            self.timing_source is CaptionTimingSource.ACTUAL_AUDIO_ALIGNMENT
            and not self.derived_from_audio_sha256
        ):
            raise ValueError("actual-audio timing must name the audio it was aligned to")
        return self

    @property
    def releasable(self) -> bool:
        return self.timing_source is CaptionTimingSource.ACTUAL_AUDIO_ALIGNMENT


class HookCandidate(ContractModel):
    candidate_id: Identifier
    edl_id: UUID
    duration_ms: PositiveMs
    source_asset_ids: list[UUID] = Field(min_length=1, description="Existing accepted footage only")
    treatment: ShortText
    changed_framing: bool
    reading_load_note: ShortText

    @model_validator(mode="after")
    def _duration(self) -> HookCandidate:
        if not 20_000 <= self.duration_ms <= 40_000:
            raise ValueError("IMP-07: hook candidates must be 20-40 seconds")
        return self


class HookAssignment(ContractModel):
    """Planned/actual exposure of a candidate in an eligible slot (ledger row)."""

    candidate_id: Identifier
    platform: Platform
    account_ref: AccountRef
    release_slot: Identifier
    cohort: Identifier
    scheduled_utc: UtcDateTime
    subtitle_locale: LocaleTag | None = None
    offer_ref: ShortText | None = None
    traffic: TrafficKind = TrafficKind.ORGANIC
    paid_spend_micro_usd: SignedMicroUSD = 0

    @model_validator(mode="after")
    def _organic(self) -> HookAssignment:
        if self.traffic is TrafficKind.PAID or self.paid_spend_micro_usd != 0:
            raise ValueError("MD-018: initial paid-ad budget is zero")
        return self


class HookExperiment(VersionedPayload):
    """Three candidates from accepted footage; no fresh video renders (IMP-07)."""

    experiment_id: UUID
    episode_id: UUID
    candidates: list[HookCandidate] = Field(min_length=3, max_length=3)
    new_video_render_job_ids: list[UUID] = Field(
        default_factory=list, max_length=0, description="Must stay empty"
    )
    assignments: list[HookAssignment] = Field(default_factory=list)
    primary_outcome: Identifier = "engaged_viewing_and_next_episode_continuation"
    observational_only: bool = Field(default=True, description="Organic comparisons are not causal")

    @model_validator(mode="after")
    def _distinct(self) -> HookExperiment:
        ids = [c.candidate_id for c in self.candidates]
        if len(set(ids)) != 3:
            raise ValueError("three distinct hook candidates required")
        edls = [c.edl_id for c in self.candidates]
        if len(set(edls)) != 3:
            raise ValueError("each candidate needs its own EDL")
        known = set(ids)
        if any(a.candidate_id not in known for a in self.assignments):
            raise ValueError("assignment references unknown candidate")
        if not self.observational_only:
            raise ValueError("organic matched comparisons are observational, not causal proof")
        return self
