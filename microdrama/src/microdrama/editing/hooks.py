"""Three distinct 20-40s hook candidates re-cut from accepted footage (T016, IMP-07).

Hooks are EDL RE-CUTS: every candidate is built exclusively from assets the
assembled master already used (accepted shot videos, measured line audio, the
continuous room bed). This module plans them purely — no FFmpeg, no jobs, no
provider, no budget — and the service layer (``variants_service``) exports them
with the same local, free discipline T015 established. There is no code path from
here to the T013 render dispatch, and generation never creates release slots,
platform posts or publishing obligations: three candidates are review material,
not three posts.

Selection rules (deterministic, typed):

- ``payoff_window`` finds the episode's payoff beat: the shot with dialogue that
  has the highest dramatic importance (ties broken by later sequence — the climax
  comes last), windowed to that shot's first..last dialogue clip.
- Every treatment MUST include the payoff window in full. A meaningful hook
  preserves the payoff; dropping it is a typed ``SchemaInvalid``, never a silent
  trim (packet acceptance: "meaningful parts preserve payoff").
- ``reading_load`` measures what the re-cut does to caption reading: cues kept,
  characters per second versus the master's, and any line sliced at a window
  boundary and therefore dropped. A shorter cut changes how long captions are on
  screen — that is logged on the candidate (``reading_load_note``), not implied.

Treatments: ``payoff_first_cold_open`` (payoff, then the run-up into it),
``chronological_tease`` (opening, then the payoff flash), ``punch_in_reaction``
(centered beat plus payoff, every clip re-framed by a center punch-in crop —
``changed_framing`` True, and the crop is logged).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from statistics import median
from uuid import UUID

from pydantic import Field

from microdrama.contracts.enums import Level, SlotKind, TrackKind
from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.media import CropSpec, EditDecisionList, EdlClip, HookCandidate
from microdrama.contracts.primitives import ContractModel, Count, Identifier, ShortText
from microdrama.contracts.season import Script, ShotManifest
from microdrama.editing.variants import (
    punch_in_crop,
    variant_edl_id,
    variant_semantic_hash,
)

HOOK_MIN_MS = 20_000
HOOK_MAX_MS = 40_000
TREATMENTS: tuple[str, ...] = (
    "payoff_first_cold_open",
    "chronological_tease",
    "punch_in_reaction",
)

_IMPORTANCE_RANK: dict[Level, int] = {
    Level.LOW: 1,
    Level.MEDIUM: 2,
    Level.HIGH: 3,
    Level.CRITICAL: 4,
}


class PayoffWindow(ContractModel):
    """The episode's payoff beat on the assembled timeline (must survive every hook)."""

    shot_id: Identifier
    start_ms: int
    end_ms: int
    line_ids: list[Identifier] = Field(min_length=1)

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


class ReadingLoad(ContractModel):
    """Measured caption load of one candidate versus its master (logged, not implied)."""

    cue_count: Count
    characters: Count
    duration_ms: int
    chars_per_second: int = Field(description="Rounded; comparison-only, never a gate")
    master_chars_per_second: int
    dropped_boundary_lines: Count
    note: ShortText


class HookCandidatePlan(ContractModel):
    """One planned candidate: the frozen contract payload plus its EDL and evidence."""

    candidate: HookCandidate
    edl: EditDecisionList
    reading: ReadingLoad


class HookPlan(ContractModel):
    candidates: list[HookCandidatePlan] = Field(min_length=3, max_length=3)
    payoff: PayoffWindow
    notes: list[ShortText] = Field(default_factory=list)


# --- payoff -----------------------------------------------------------------------------


def payoff_window(manifest: ShotManifest, main_edl: EditDecisionList) -> PayoffWindow:
    """The payoff beat: highest-importance shot WITH dialogue; ties -> later sequence."""
    shot_of_line: dict[str, str] = {}
    importance_of_shot: dict[str, Level] = {}
    for shot in manifest.shots:
        importance_of_shot[shot.shot_id] = shot.dramatic_importance
        for line_id in shot.line_ids:
            shot_of_line[line_id] = shot.shot_id
    order_of_shot = {shot.shot_id: shot.sequence for shot in manifest.shots}
    dialogue = sorted(
        (c for c in main_edl.clips if c.dialogue_line_ids), key=lambda c: c.timeline_in_ms
    )
    by_shot: dict[str, list[EdlClip]] = {}
    for clip in dialogue:
        line_id = clip.dialogue_line_ids[0]
        shot_id = shot_of_line.get(line_id)
        if shot_id is not None:
            by_shot.setdefault(shot_id, []).append(clip)
    if not by_shot:
        raise SchemaInvalid("the manifest maps no dialogue to any shot; no payoff to preserve")
    best = max(
        by_shot,
        key=lambda shot_id: (
            _IMPORTANCE_RANK.get(importance_of_shot.get(shot_id, Level.MEDIUM), 2),
            order_of_shot.get(shot_id, 0),
        ),
    )
    clips = by_shot[best]
    return PayoffWindow(
        shot_id=best,
        start_ms=clips[0].timeline_in_ms,
        end_ms=clips[-1].timeline_out_ms,
        line_ids=[clip.dialogue_line_ids[0] for clip in clips],
    )


# --- window strategies --------------------------------------------------------------------


def _cold_open(timeline_ms: int, payoff: PayoffWindow, target_ms: int) -> list[tuple[int, int]]:
    windows = [(payoff.start_ms, min(payoff.end_ms, payoff.start_ms + target_ms))]
    remaining = target_ms - (windows[0][1] - windows[0][0])
    if remaining > 0 and payoff.start_ms > 0:
        take = min(remaining, payoff.start_ms)
        windows.append((payoff.start_ms - take, payoff.start_ms))
        remaining -= take
    if remaining > 0 and payoff.end_ms < timeline_ms:
        take = min(remaining, timeline_ms - payoff.end_ms)
        windows.append((payoff.end_ms, payoff.end_ms + take))
    return windows


def _chronological(timeline_ms: int, payoff: PayoffWindow, target_ms: int) -> list[tuple[int, int]]:
    head_len = max(0, min(target_ms - payoff.duration_ms, payoff.start_ms))
    windows = [(0, head_len)] if head_len > 0 else []
    windows.append((payoff.start_ms, payoff.end_ms))
    total = head_len + payoff.duration_ms
    if total < HOOK_MIN_MS:
        need = HOOK_MIN_MS - total
        new_start = max(0, payoff.start_ms - need)
        got_left = payoff.start_ms - new_start
        new_end = min(timeline_ms, payoff.end_ms + (need - got_left))
        windows = [(new_start, new_end)]
    return windows


def _punch_in(
    timeline_ms: int, payoff: PayoffWindow, target_ms: int, anchor_ms: int
) -> list[tuple[int, int]]:
    center_len = max(1_000, target_ms - payoff.duration_ms)
    start = max(0, min(anchor_ms - center_len // 2, timeline_ms - center_len))
    end = min(timeline_ms, start + center_len)
    if end > payoff.start_ms and start < payoff.end_ms:
        if payoff.start_ms > 0:
            end = payoff.start_ms
            start = max(0, end - center_len)
        else:
            start = payoff.end_ms
            end = min(timeline_ms, start + center_len)
    if end <= start:  # degenerate after shifting: the payoff alone carries the hook
        return [(payoff.start_ms, min(payoff.end_ms, payoff.start_ms + target_ms))]
    windows = [(start, end), (payoff.start_ms, payoff.end_ms)]
    total = (end - start) + payoff.duration_ms
    if total < HOOK_MIN_MS:
        need = HOOK_MIN_MS - total
        new_start = max(0, start - need)
        got_left = start - new_start
        new_end = min(timeline_ms, end + (need - got_left))
        windows = [(new_start, new_end), (payoff.start_ms, payoff.end_ms)]
    return windows


def select_windows(
    treatment: str,
    *,
    timeline_ms: int,
    payoff: PayoffWindow,
    target_ms: int,
    anchor_ms: int | None = None,
) -> list[tuple[int, int]]:
    """Windows (main-timeline ranges, playback order) for one treatment."""
    if timeline_ms < HOOK_MIN_MS:
        raise SchemaInvalid(
            "accepted footage is shorter than the 20 s hook floor",
            timeline_ms=timeline_ms,
            floor_ms=HOOK_MIN_MS,
        )
    if payoff.duration_ms > HOOK_MAX_MS:
        raise SchemaInvalid(
            "the payoff beat alone exceeds the 40 s hook ceiling; refusing to split it",
            payoff_ms=payoff.duration_ms,
            ceiling_ms=HOOK_MAX_MS,
        )
    target = min(max(target_ms, HOOK_MIN_MS), HOOK_MAX_MS)
    if treatment == "payoff_first_cold_open":
        return _cold_open(timeline_ms, payoff, target)
    if treatment == "chronological_tease":
        return _chronological(timeline_ms, payoff, target)
    if treatment == "punch_in_reaction":
        return _punch_in(timeline_ms, payoff, target, anchor_ms or timeline_ms // 2)
    raise SchemaInvalid("unknown hook treatment", treatment=treatment)


# --- hook EDL construction ----------------------------------------------------------------


def _room_clips(main_edl: EditDecisionList) -> list[EdlClip]:
    return sorted(
        (c for c in main_edl.clips if c.track is TrackKind.AMBIENCE), key=lambda c: c.timeline_in_ms
    )


def build_hook_edl(
    *,
    main_edl: EditDecisionList,
    windows: Sequence[tuple[int, int]],
    candidate_id: str,
    punch_in: bool,
    source_dims: Mapping[UUID, tuple[int, int]],
) -> tuple[EditDecisionList, int]:
    """Slice the main timeline's windows into one hook EDL (a genuine re-cut).

    Video clips are sliced exactly at the window edges (partial shots allowed — a
    re-cut's cuts are the treatment). Dialogue clips must be FULLY inside a window:
    a line sliced at a boundary loses half a sentence, so it is dropped and counted
    in the reading load instead of played half-spoken. Ambience is one continuous
    room clip over the whole hook duration, exactly like the master's bed.
    """
    room = _room_clips(main_edl)
    if not room:
        raise SchemaInvalid("the main EDL has no room bed to carry the hook")
    video = sorted(
        (c for c in main_edl.clips if c.track is TrackKind.VIDEO), key=lambda c: c.timeline_in_ms
    )
    dialogue = sorted(
        (c for c in main_edl.clips if c.dialogue_line_ids), key=lambda c: c.timeline_in_ms
    )
    clips: list[EdlClip] = []
    dropped = 0
    position = 0
    for index, (win_start, win_end) in enumerate(windows):
        if win_end <= win_start:
            raise SchemaInvalid("empty hook window", window=(win_start, win_end))
        for clip in video:
            clip_start, clip_end = clip.timeline_in_ms, clip.timeline_out_ms
            if clip_end <= win_start or clip_start >= win_end:
                continue
            cut_start = max(clip_start, win_start)
            cut_end = min(clip_end, win_end)
            crop: CropSpec | None = clip.crop
            if punch_in:
                dims = source_dims.get(clip.source_asset_id)
                if dims is None:
                    raise SchemaInvalid(
                        "hook planning needs measured dimensions for every video source",
                        asset_id=str(clip.source_asset_id),
                    )
                crop = punch_in_crop(dims[0], dims[1])
            clips.append(
                EdlClip(
                    clip_id=f"w{index}.{clip.clip_id}",
                    track=TrackKind.VIDEO,
                    source_asset_id=clip.source_asset_id,
                    source_in_ms=clip.source_in_ms + (cut_start - clip_start),
                    source_out_ms=clip.source_in_ms + (cut_end - clip_start),
                    timeline_in_ms=position + (cut_start - win_start),
                    crop=crop,
                )
            )
        for clip in dialogue:
            clip_start, clip_end = clip.timeline_in_ms, clip.timeline_out_ms
            if clip_start >= win_start and clip_end <= win_end:
                clips.append(
                    EdlClip(
                        clip_id=f"w{index}.{clip.clip_id}",
                        track=TrackKind.DIALOGUE,
                        source_asset_id=clip.source_asset_id,
                        source_in_ms=clip.source_in_ms,
                        source_out_ms=clip.source_out_ms,
                        timeline_in_ms=position + (clip_start - win_start),
                        gain_millibel=clip.gain_millibel,
                        dialogue_line_ids=list(clip.dialogue_line_ids),
                    )
                )
            elif clip_start < win_end and clip_end > win_start:
                dropped += 1
        position += win_end - win_start
    total_ms = position
    if total_ms <= 0:
        raise SchemaInvalid("hook windows produced an empty timeline")
    clips.append(
        EdlClip(
            clip_id=f"room.{candidate_id}",
            track=TrackKind.AMBIENCE,
            source_asset_id=room[0].source_asset_id,
            source_in_ms=0,
            source_out_ms=total_ms,
            timeline_in_ms=0,
            gain_millibel=room[0].gain_millibel,
        )
    )
    edl = EditDecisionList(
        edl_id=main_edl.edl_id,  # placeholder; re-id'd below from the hook's own hash
        episode_id=main_edl.episode_id,
        version=1,
        purpose=SlotKind.HOOK,
        output=main_edl.output.model_copy(),
        clips=clips,
    )
    hhash = variant_semantic_hash(edl, variant_key=candidate_id)
    final = edl.model_copy(update={"edl_id": variant_edl_id(main_edl.episode_id, hhash)})
    return final, dropped


# --- reading load --------------------------------------------------------------------------


def reading_load(
    *,
    script: Script,
    main_edl: EditDecisionList,
    hook_edl: EditDecisionList,
    dropped_boundary_lines: int,
) -> ReadingLoad:
    """Caption reading load of the hook versus its master.

    Characters are the intended Thai line texts actually included in the hook; the
    master's rate uses every line over the full episode duration. Rounded ints —
    this is a logged comparison for the review package, never a gate.
    """
    text_of_line = {line.line_id: line.text_th for scene in script.scenes for line in scene.lines}
    master_chars = sum(
        len(text_of_line.get(clip.dialogue_line_ids[0], ""))
        for clip in main_edl.clips
        if clip.dialogue_line_ids
    )
    hook_lines = [clip.dialogue_line_ids[0] for clip in hook_edl.clips if clip.dialogue_line_ids]
    hook_chars = sum(len(text_of_line.get(line_id, "")) for line_id in hook_lines)
    duration = hook_edl.duration_ms
    master_rate = round(master_chars / max(1, main_edl.duration_ms / 1000))
    rate = round(hook_chars / max(1, duration / 1000))
    note = (
        f"{len(hook_lines)} cues over {duration / 1000:.1f}s = {rate} chars/s "
        f"(master {master_rate}); {dropped_boundary_lines} boundary line(s) dropped"
    )
    return ReadingLoad(
        cue_count=len(hook_lines),
        characters=hook_chars,
        duration_ms=duration,
        chars_per_second=rate,
        master_chars_per_second=master_rate,
        dropped_boundary_lines=dropped_boundary_lines,
        note=note[:500],
    )


# --- the three candidates -------------------------------------------------------------------


def plan_hook_candidates(
    *,
    main_edl: EditDecisionList,
    manifest: ShotManifest,
    script: Script,
    target_durations_ms: Sequence[int],
    source_dims: Mapping[UUID, tuple[int, int]],
) -> HookPlan:
    """Plan exactly three distinct candidates from the accepted main EDL."""
    if len(target_durations_ms) != 3:
        raise SchemaInvalid(
            "IMP-07 needs exactly three target durations (one per treatment)",
            given=len(target_durations_ms),
        )
    timeline_ms = main_edl.duration_ms
    payoff = payoff_window(manifest, main_edl)
    dialogue_starts = [clip.timeline_in_ms for clip in main_edl.clips if clip.dialogue_line_ids]
    anchor = int(median(dialogue_starts)) if dialogue_starts else timeline_ms // 2
    plans: list[HookCandidatePlan] = []
    notes: list[str] = [
        f"payoff beat: shot {payoff.shot_id} [{payoff.start_ms}, {payoff.end_ms}] ms, "
        f"lines {','.join(payoff.line_ids)}"
    ]
    for index, (treatment, target_ms) in enumerate(
        zip(TREATMENTS, target_durations_ms, strict=True)
    ):
        punch_in = treatment == "punch_in_reaction"
        windows = select_windows(
            treatment,
            timeline_ms=timeline_ms,
            payoff=payoff,
            target_ms=target_ms,
            anchor_ms=anchor,
        )
        candidate_id = f"hook-{chr(ord('a') + index)}"
        edl, dropped = build_hook_edl(
            main_edl=main_edl,
            windows=windows,
            candidate_id=candidate_id,
            punch_in=punch_in,
            source_dims=source_dims,
        )
        included = {clip.dialogue_line_ids[0] for clip in edl.clips if clip.dialogue_line_ids}
        missing = [line_id for line_id in payoff.line_ids if line_id not in included]
        if missing:
            raise SchemaInvalid(
                "hook treatment dropped the payoff; refusing the candidate",
                treatment=treatment,
                dropped_lines=missing,
            )
        reading = reading_load(
            script=script,
            main_edl=main_edl,
            hook_edl=edl,
            dropped_boundary_lines=dropped,
        )
        candidate = HookCandidate(
            candidate_id=candidate_id,
            edl_id=edl.edl_id,
            duration_ms=edl.duration_ms,
            source_asset_ids=sorted({clip.source_asset_id for clip in edl.clips}),
            treatment=treatment,
            changed_framing=punch_in,
            reading_load_note=reading.note,
        )
        plans.append(HookCandidatePlan(candidate=candidate, edl=edl, reading=reading))
    return HookPlan(candidates=plans, payoff=payoff, notes=notes)


__all__ = [
    "HOOK_MAX_MS",
    "HOOK_MIN_MS",
    "HookCandidatePlan",
    "HookPlan",
    "PayoffWindow",
    "ReadingLoad",
    "TREATMENTS",
    "build_hook_edl",
    "payoff_window",
    "plan_hook_candidates",
    "reading_load",
    "select_windows",
]
