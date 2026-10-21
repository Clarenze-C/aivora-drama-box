"""Thai-safe font handling tests (T015): coverage verification, typed fallback.

Burned captions need a font whose cmap actually covers the Thai text (combining
marks included) and a shaping engine (libass), never plain drawtext. A missing font
is a typed finding with the burn skipped — tofu is not an option.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from editing_support import World

from microdrama.editing import EditingConfig, resolve_caption_font
from microdrama.editing.fonts import (
    THAI_REQUIRED_CODEPOINTS,
    FontFileError,
    covers_text,
    font_codepoints,
)

pytestmark = pytest.mark.ffmpeg

THAI_SAMPLE = "หนี้ห้าหมื่นบาท คำบรรยายทดสอบ"


def test_resolves_a_thai_safe_font_deterministically() -> None:
    config = EditingConfig()
    first = resolve_caption_font(config, [THAI_SAMPLE])
    second = resolve_caption_font(config, [THAI_SAMPLE])
    assert first.coverage_ok and first.path is not None
    assert first == second
    assert first.searched >= 1
    # The family is read from the font's own name table (what libass must be told).
    data = Path(first.path).read_bytes()
    assert THAI_REQUIRED_CODEPOINTS <= font_codepoints(data)
    assert covers_text(font_codepoints(data), [THAI_SAMPLE])


def test_coverage_rejects_a_font_missing_combining_marks() -> None:
    partial = (THAI_REQUIRED_CODEPOINTS | {ord(c) for c in THAI_SAMPLE if not c.isspace()}) - {
        0x0E49  # ้ mai tho, a combining mark every real cue uses here
    }
    assert covers_text(partial, [THAI_SAMPLE]) is False
    assert covers_text(partial | {0x0E49}, [THAI_SAMPLE]) is True


def test_non_font_files_are_skipped_typed(tmp_path: Path) -> None:
    (tmp_path / "Loma.otf").write_bytes(b"this is not a font at all")
    config = EditingConfig(font_dirs=(str(tmp_path),))
    resolution = resolve_caption_font(config, [THAI_SAMPLE])
    # The broken candidate is skipped and the system fallback chain still resolves.
    assert resolution.coverage_ok
    assert Path(resolution.path).is_absolute()
    with pytest.raises(FontFileError):
        font_codepoints(b"still not a font")


def test_no_thai_font_skips_the_burn_with_a_typed_finding(world: World, tmp_path: Path) -> None:
    empty = EditingConfig(
        font_dirs=(str(tmp_path / "no-fonts-here"),),
        font_candidates=("NoSuchFamily",),
    )
    resolution = resolve_caption_font(empty, [THAI_SAMPLE])
    assert resolution.coverage_ok is False and resolution.path is None
    from editing_support import World as WorldCls

    narrow = WorldCls(world.db, world.store, world.settings, world.clips, world.truth, config=empty)
    episode_id, _season, assets = narrow.seed_prepared_episode()
    outcome = narrow.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    # Clean master and captions still complete; only the burn is skipped, typed.
    assert outcome.burned_asset_id is None and outcome.burned_sha256 is None
    codes = [f.code for f in outcome.findings]
    assert "font.thai_unavailable" in codes
    burn = next(c for c in outcome.checks if c.check_id == "burn.rendered")
    assert burn.outcome == "UNKNOWN"
    assert narrow.episode_state(episode_id) == "AI_REVIEW"


def test_burn_uses_libass_subtitles_filter_not_drawtext(world: World) -> None:
    episode_id, _season, assets = world.seed_prepared_episode()
    outcome = world.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    assert outcome.burned_asset_id is not None
    # The burned export is a re-encode of the clean master (audio copied bit-exact):
    # its lineage names the master, proving it burned on top of the approved cut.
    row = world.row("SELECT descriptor FROM assets WHERE id = %s", (outcome.burned_asset_id,))
    assert str(outcome.clean_asset_id) in row["descriptor"]["lineage"]
    assert row["descriptor"]["media"]["has_video"] is True
