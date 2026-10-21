"""Shot prompts: deterministic, bounded, composed only from compiled story fields."""

from __future__ import annotations

from story_support import World

from microdrama.story import WriteStatus, build_shot_prompt, estimate_line_ms


def _ready(world: World):
    season_id, scope = world.season()
    world.service.compile_season(season_id)
    episode_id = world.episode(season_id, scope)
    return episode_id


def test_shot_prompt_carries_the_exact_thai_line_and_staging(world: World) -> None:
    episode_id = _ready(world)
    assert world.service.write_episode(episode_id).status is WriteStatus.CURRENT
    script = world.service.script(episode_id)
    manifest = world.service.manifest(episode_id)

    shot = next(s for s in manifest.shots if s.line_ids)
    lines = [ln for sc in script.scenes for ln in sc.lines if ln.line_id in shot.line_ids]
    prompt = build_shot_prompt(shot, lines, episode_number=1, title_th="ร้านข้าวมันไก่ของแม่")

    assert lines[0].text_th in prompt, "the exact Thai line is in the prompt"
    assert lines[0].speaker_character_id in prompt
    assert shot.framing in prompt
    assert "TEXT_PROMPT" in prompt
    assert any("spoken exactly as scripted" in c for c in shot.acceptance_criteria)
    assert str(shot.target_duration_ms) in prompt
    assert len(prompt) <= 4000, "fits RenderRequest.prompt_text"


def test_shot_prompt_for_a_dialogue_free_shot_names_no_lines(world: World) -> None:
    episode_id = _ready(world)
    assert world.service.write_episode(episode_id).status is WriteStatus.CURRENT
    manifest = world.service.manifest(episode_id)
    establishing = next(s for s in manifest.shots if not s.line_ids)
    prompt = build_shot_prompt(establishing, [], episode_number=1, title_th="ร้านข้าวมันไก่ของแม่")
    assert "(no dialogue)" in prompt
    assert establishing.purpose in prompt


def test_estimate_line_ms_is_deterministic_and_clamped() -> None:
    short = estimate_line_ms("ครบ")
    long = estimate_line_ms("ก" * 200)
    assert short == estimate_line_ms("ครบ")
    assert 1_000 <= short < long <= 14_000
    assert type(short) is int and type(long) is int
    # The estimate scales with the exact Thai text it is given.
    assert estimate_line_ms("สวัสดีครับ") < estimate_line_ms("สวัสดีครับ" + "ค่ะ" * 5)
