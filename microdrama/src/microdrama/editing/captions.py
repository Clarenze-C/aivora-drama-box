"""Actual-speech caption spotting and the no-fake-correction guard (T015).

Cue timing comes from where the EDL actually placed each line's measured audio, and
cue content is checked against what was OBSERVED in that audio before the intended
script line may be written:

- observation matches the intended line -> the cue carries the intended text;
- observation disagrees -> the cue carries what was ACTUALLY spoken and a
  ``caption.audio_content_mismatch`` finding is surfaced. Writing the intended words
  over wrong audio would conceal the defect, so it never happens (SPEC §9);
- no observation available (no ASR wired yet offline) -> the cue carries the intended
  text with a typed uncertainty note; the track is not silently claimed verified.

``SpeechObserver`` is the seam: OFFLINE_MOCK wires the T007 fixture-truth observer
(test support); T017 wires the ASR-backed one. The comparison lives here either way.

Invalidation: a caption track names the exact audio sha256s it was derived from, so
replacing one line's audio makes the old track's derivation stale. ``stale_cues``
maps each stale track to the precise cues (line ids) whose source changed — that
mapping is what the service uses to invalidate associated cues, never a blunt
whole-track wipe.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from microdrama.contracts.enums import CaptionTimingSource, Severity
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.media import CaptionCue, CaptionTrack, EditDecisionList
from microdrama.editing.edl import caption_track_id_for
from microdrama.editing.models import EditingFinding, ObservedSpeech

MISMATCH_CODE = "caption.audio_content_mismatch"
UNAVAILABLE_NOTE = "caption.observation_unavailable"


class SpeechObserver(Protocol):
    """Observes what one audio asset actually contains (ASR/fixture; never the script)."""

    def observe(self, audio_sha256: str) -> ObservedSpeech | None: ...


def _normalize(text: str) -> str:
    return " ".join(text.split())


def spot_caption_track(
    *,
    episode_id: UUID,
    locale: str,
    edl: EditDecisionList,
    line_sha256: dict[str, str],
    line_text: dict[str, str],
    line_spoken_text: dict[str, str],
    observer: SpeechObserver | None,
    tail_pad_ms: int,
    min_cue_ms: int,
) -> tuple[CaptionTrack, list[EditingFinding], list[str]]:
    """Build one locale's caption track from actual audio placement.

    ``line_text`` is this locale's display text; ``line_spoken_text`` is the canonical
    Thai line the audio was supposed to speak. The observation is compared against the
    SPOKEN text (a Thai observation can never match an English translation), and on
    mismatch every locale's cue carries what was actually spoken — inventing a
    translation of wrong audio is not this module's call.

    Returns the track, the findings (wrong-audio mismatches) and the uncertainty
    notes (lines with no observation available). Timing is always the measured audio
    placement from the EDL — never the script's estimates.
    """
    cues: list[CaptionCue] = []
    findings: list[EditingFinding] = []
    notes: list[str] = []
    dialogue = sorted((c for c in edl.clips if c.dialogue_line_ids), key=lambda c: c.timeline_in_ms)
    observed_cache: dict[str, ObservedSpeech | None] = {}
    for index, clip in enumerate(dialogue):
        line_id = clip.dialogue_line_ids[0]
        sha = line_sha256[line_id]
        intended = line_text[line_id]
        spoken = line_spoken_text[line_id]
        if sha not in observed_cache:
            observed_cache[sha] = observer.observe(sha) if observer is not None else None
        observed = observed_cache[sha]
        if observed is not None and _normalize(observed.text_th) != _normalize(spoken):
            # The audio does not speak the intended line. The cue reports what was
            # actually spoken and the mismatch surfaces as a finding — the caption
            # never silently "fixes" the audio by overlaying the intended words.
            text = observed.text_th
            findings.append(
                EditingFinding(
                    code=MISMATCH_CODE,
                    severity=Severity.CRITICAL,
                    detail=(
                        "observed speech does not match the intended line; the cue carries "
                        "what was actually spoken"
                    ),
                    line_id=line_id,
                )
            )
        else:
            text = intended
            if observed is None:
                notes.append(f"{UNAVAILABLE_NOTE}:{line_id}")
        start = clip.timeline_in_ms
        end = start + clip.duration_ms + tail_pad_ms
        end = max(end, start + min_cue_ms)
        if index + 1 < len(dialogue):
            next_start = dialogue[index + 1].timeline_in_ms
            end = min(end, next_start - 1)
        if end <= start:
            end = start + 1  # guard: a cue must exist even in the tightest layout
        slug = locale.lower().replace("-", "")
        cues.append(
            CaptionCue(
                cue_id=f"{line_id}.{slug}",
                start_ms=start,
                end_ms=end,
                text=text,
                line_id=line_id,
            )
        )
    body_hash = canonical_hash(
        {
            "locale": locale,
            "cues": [[c.cue_id, c.start_ms, c.end_ms, c.text] for c in cues],
            "audio": sorted(line_sha256.values()),
        }
    )
    track = CaptionTrack(
        track_id=caption_track_id_for(episode_id, locale, body_hash),
        episode_id=episode_id,
        version=1,
        locale=locale,
        timing_source=CaptionTimingSource.ACTUAL_AUDIO_ALIGNMENT,
        derived_from_audio_sha256=sorted(set(line_sha256.values())),
        cues=cues,
    )
    return track, findings, notes


def track_body_hash(track: CaptionTrack) -> str:
    return canonical_hash(
        {
            "locale": track.locale,
            "cues": [[c.cue_id, c.start_ms, c.end_ms, c.text] for c in track.cues],
            "audio": track.derived_from_audio_sha256,
        }
    )


def srt_bytes(track: CaptionTrack) -> bytes:
    """Deterministic UTF-8 SubRip serialization (content only; no shell surface)."""

    def stamp(ms: int) -> str:
        hours, rem = divmod(ms, 3_600_000)
        minutes, rem = divmod(rem, 60_000)
        seconds, millis = divmod(rem, 1_000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    blocks = [
        f"{i}\n{stamp(c.start_ms)} --> {stamp(c.end_ms)}\n{c.text}\n"
        for i, c in enumerate(track.cues, start=1)
    ]
    return "\n".join(blocks).encode("utf-8")


def stale_cues(stored: CaptionTrack, current_line_sha256: dict[str, str]) -> list[str]:
    """Cue ids of a stored track whose line audio was replaced (associated cues only).

    A cue is stale exactly when its line's CURRENT audio sha is absent from the sha
    list the track was derived from. Unchanged lines' cues are not collateral.
    """
    derived = set(stored.derived_from_audio_sha256)
    return [
        cue.cue_id
        for cue in stored.cues
        if cue.line_id is not None and current_line_sha256.get(cue.line_id) not in derived
    ]


__all__ = [
    "MISMATCH_CODE",
    "SpeechObserver",
    "UNAVAILABLE_NOTE",
    "srt_bytes",
    "spot_caption_track",
    "stale_cues",
    "track_body_hash",
]
