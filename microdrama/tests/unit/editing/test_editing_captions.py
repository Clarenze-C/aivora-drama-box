"""Caption spotting tests (T015): actual-audio timing, the no-fake-correction guard.

The wrong-audio defect is simulated honestly: the audio ASSET's registered speech is
changed (different recorded content), so the observer reports what the file actually
contains — the caption must never silently write the intended line over it.
"""

from __future__ import annotations

import pytest
from editing_support import LINES, World

from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.media import CaptionTrack
from microdrama.editing import MISMATCH_CODE, UNAVAILABLE_NOTE, srt_bytes
from microdrama.editing.models import AssemblyStatus
from microdrama.references.anchors import ref_id_for

pytestmark = pytest.mark.ffmpeg

WRONG_AMOUNT = "หนี้ห้าพันบาทนี่คืออะไรคะ"  # seeded money-term swap (T007 style)


def _assemble(world: World, **kwargs):
    episode_id, _season, assets = world.seed_prepared_episode(**kwargs)
    outcome = world.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    return episode_id, outcome


def _track(world: World, episode_id, locale: str = "th-TH") -> CaptionTrack:
    row = world.row(
        "SELECT body, timing_source FROM caption_tracks WHERE episode_id = %s "
        "AND locale = %s AND state = 'CURRENT'",
        (episode_id, locale),
    )
    assert row is not None, f"no CURRENT {locale} track"
    return CaptionTrack.model_validate(row["body"])


def _line_shas(world: World, episode_id) -> set[str]:
    script = world.service.script(episode_id)
    shas: set[str] = set()
    for scene in script.scenes:
        for line in scene.lines:
            row = world.row(
                "SELECT sha256 FROM assets WHERE id = %s",
                (
                    ref_id_for(
                        "line-audio",
                        f"{episode_id}:{line.line_id}:{canonical_hash(line.text_th)[:12]}",
                    ),
                ),
            )
            shas.add(row["sha256"])
    return shas


def test_cues_are_spotted_on_the_actual_audio_placement(world: World) -> None:
    episode_id, outcome = _assemble(world)
    track = _track(world, episode_id)
    by_line = {cue.line_id: cue for cue in track.cues}
    # Cue start equals the EDL dialogue placement (shot start + lead-in), never a
    # script estimate; cue length covers the MEASURED audio duration.
    assert by_line["sc1-l1"].start_ms == world.service.config.dialogue_lead_in_ms
    actual = {line_id: ms for line_id, _s, _t, ms in LINES}
    for line_id, cue in by_line.items():
        assert cue.end_ms - cue.start_ms >= actual[line_id]
    assert outcome.status is AssemblyStatus.ASSEMBLED


def test_thai_and_english_tracks_carry_exact_texts(world: World) -> None:
    episode_id, _outcome = _assemble(world)
    thai = _track(world, episode_id, "th-TH")
    english = _track(world, episode_id, "en-US")
    thai_text = {cue.line_id: cue.text for cue in thai.cues}
    english_text = {cue.line_id: cue.text for cue in english.cues}
    for line_id, _speaker, text, _ms in LINES:
        assert thai_text[line_id] == text
        assert english_text[line_id] == f"EN({line_id})"


def test_tracks_are_actual_audio_aligned_and_name_their_audio(world: World) -> None:
    episode_id, _outcome = _assemble(world)
    shas = _line_shas(world, episode_id)
    for locale in ("th-TH", "en-US"):
        row = world.row(
            "SELECT body, timing_source FROM caption_tracks WHERE episode_id = %s "
            "AND locale = %s AND state = 'CURRENT'",
            (episode_id, locale),
        )
        track = CaptionTrack.model_validate(row["body"])
        assert row["timing_source"] == "ACTUAL_AUDIO_ALIGNMENT"
        assert track.releasable is True
        # The derivation names exactly the measured audio it was aligned to.
        assert set(track.derived_from_audio_sha256) == shas


def test_wrong_audio_surfaces_as_a_finding_never_a_silent_fix(world: World) -> None:
    # The asset's REGISTERED SPEECH is the wrong amount: the defect lives in the
    # audio, and the pipeline must report it instead of papering over it.
    episode_id, outcome = _assemble(world, spoken_text={"sc1-l2": WRONG_AMOUNT})
    mismatches = [f for f in outcome.findings if f.code == MISMATCH_CODE]
    assert len(mismatches) == 2  # one per locale track, same line
    assert {f.line_id for f in mismatches} == {"sc1-l2"}
    assert mismatches[0].severity == "CRITICAL"
    for locale in ("th-TH", "en-US"):
        track = _track(world, episode_id, locale)
        cue = next(c for c in track.cues if c.line_id == "sc1-l2")
        # The cue carries what was ACTUALLY spoken — never the intended line.
        assert cue.text == WRONG_AMOUNT
        intended = next(t for lid, _s, t, _m in LINES if lid == "sc1-l2")
        assert cue.text != intended
    # And the finding is recorded in the event stream, not just the return value.
    events = world.events(episode_id, "editing.assembled")
    assert MISMATCH_CODE in events[-1]["finding_codes"]


def test_missing_observer_is_a_typed_unknown_not_a_claim(world: World) -> None:
    world.service._observer = None  # exact runtime shape: ASR not wired yet
    episode_id, outcome = _assemble(world)
    assert episode_id is not None
    assert not outcome.findings
    unavailable = [n for n in outcome.uncertainty_notes if UNAVAILABLE_NOTE in n]
    assert unavailable, "no observation must stay a typed unknown, never a PASS"
    assert len(unavailable) == len(LINES) * len(world.service.config.caption_locales)


def test_cue_timing_stays_inside_the_media(world: World) -> None:
    episode_id, outcome = _assemble(world)
    track = _track(world, episode_id)
    for cue in track.cues:
        assert 0 <= cue.start_ms < cue.end_ms <= outcome.duration_ms
    ends = [cue.end_ms for cue in track.cues]
    assert ends == sorted(ends)


def test_srt_serialization_is_deterministic_and_thai_safe(world: World) -> None:
    episode_id, _outcome = _assemble(world)
    track = _track(world, episode_id)
    first = srt_bytes(track)
    assert first == srt_bytes(track)
    text = first.decode("utf-8")
    assert "ลุงเล็ก" in text
    assert "-->" in text
    # Cue content lives in the file surface; no argv can carry it.
    assert b"\x00" not in first
