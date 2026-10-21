"""Canon/character-knowledge checks and bounded complexity rewrite (T010)."""

from __future__ import annotations

import copy

from story_support import EP2_REVEAL_TH, World, canonical_writer_output, thai_reveal_scope

from microdrama.contracts.enums import RuntimeRole
from microdrama.story import WriteStatus


def _ready(world: World, *, scope=None):
    season_id, use_scope = world.season(scope=scope)
    world.service.compile_season(season_id)
    episode_id = world.episode(season_id, use_scope)
    return episode_id


def _writer_output_with(mutator) -> dict:
    output = copy.deepcopy(canonical_writer_output())
    mutator(output)
    return output


def test_premature_reveal_is_blocked_every_round(world: World) -> None:
    """A planned reveal scheduled for episode 2 must not leak into episode 1 dialogue."""
    episode_id = _ready(world, scope=thai_reveal_scope())

    def leak(output: dict) -> None:
        output["scenes"][1]["lines"][2]["text_th"] = f"หนูรู้แล้วว่า{EP2_REVEAL_TH}จริงไหมคะ"

    world.llm.script_role(RuntimeRole.STORY_ARCHITECT, _writer_output_with(leak))
    outcome = world.service.write_episode(episode_id)

    assert outcome.status is WriteStatus.CRITIC_FAILED
    assert any(f.code == "premature-reveal" for f in outcome.findings)
    assert any("not yet character knowledge" in f.detail for f in outcome.findings)


def test_same_episode_reveal_is_allowed(world: World) -> None:
    """The reveal scheduled for THIS episode may appear (that is the reveal itself)."""
    scope = thai_reveal_scope()
    # Move the Thai reveal onto episode 1's beat and clear it from episode 2.
    scope = scope.model_copy(
        update={
            "arc": [
                scope.arc[0].model_copy(update={"planned_reveals": [EP2_REVEAL_TH]}),
                scope.arc[1].model_copy(update={"planned_reveals": []}),
            ]
        }
    )
    episode_id = _ready(world, scope=scope)

    def reveal_now(output: dict) -> None:
        output["scenes"][1]["lines"][2]["text_th"] = f"หนูรู้แล้วว่า{EP2_REVEAL_TH}จริงไหมคะ"

    world.llm.script_role(RuntimeRole.STORY_ARCHITECT, _writer_output_with(reveal_now))
    outcome = world.service.write_episode(episode_id)
    assert outcome.status is WriteStatus.CURRENT
    script = world.service.script(episode_id)
    assert any(EP2_REVEAL_TH in ln.text_th for sc in script.scenes for ln in sc.lines)


def test_critical_term_missing_from_thai_line_is_blocked(world: World) -> None:
    episode_id = _ready(world)

    def bad_term(output: dict) -> None:
        output["scenes"][0]["lines"][10]["critical_terms"] = [
            {"kind": "MONEY", "value_th": "หนึ่งแสนบาท"}  # not the spoken amount
        ]

    world.llm.script_role(RuntimeRole.STORY_ARCHITECT, _writer_output_with(bad_term))
    outcome = world.service.write_episode(episode_id)
    assert outcome.status is WriteStatus.CRITIC_FAILED
    assert any(f.code == "critical-term-missing" for f in outcome.findings)


def test_missing_translation_is_blocked(world: World) -> None:
    episode_id = _ready(world)

    def no_translation(output: dict) -> None:
        output["scenes"][0]["lines"][3]["text_en"] = output["scenes"][0]["lines"][3]["text_th"]

    world.llm.script_role(RuntimeRole.STORY_ARCHITECT, _writer_output_with(no_translation))
    outcome = world.service.write_episode(episode_id)
    assert outcome.status is WriteStatus.CRITIC_FAILED
    assert any(f.code == "translation-missing" for f in outcome.findings)


def test_complexity_rewrite_rescues_too_many_speakers(world: World) -> None:
    """Four speakers breach the approved cap; the bounded rewrite fixes it in round 1."""
    from microdrama.story import writer_client_token

    episode_id = _ready(world)
    extra = {
        "speaker_character_id": "stranger",
        "text_th": "ขอเป็นลูกค้าคนแรกของร้านได้ไหมครับ",
        "text_en": "May I be the stall's first customer?",
    }
    four = _writer_output_with(lambda o: o["scenes"][0]["lines"].insert(3, dict(extra)))

    # Only round 0's first writer attempt produces the over-complex draft; every later
    # call falls back to the role scripting (the canonical, compliant draft).
    world.llm.script_token(writer_client_token(episode_id, 0, 1), four)
    outcome = world.service.write_episode(episode_id)

    assert outcome.status is WriteStatus.CURRENT, [f.code for f in outcome.findings]
    assert outcome.rounds_used == 2, "the complexity finding consumed a rewrite round"
    assert outcome.settled_micro_usd > 0


def test_complexity_locations_blocked_at_limit(world: World) -> None:
    episode_id = _ready(world)

    def third_location(output: dict) -> None:
        output["scenes"].append(
            {
                "location_id": "river-pier",
                "summary": "Fon waits at the pier.",
                "lines": [
                    {
                        "speaker_character_id": "fon",
                        "text_th": "หนูจะรอข่าวจากบริษัทให้กู้ยืมที่ท่าน้ำนี่แหละ",
                        "text_en": "I will wait for the lender's news here at the pier.",
                    }
                ],
            }
        )

    world.llm.script_role(RuntimeRole.STORY_ARCHITECT, _writer_output_with(third_location))
    outcome = world.service.write_episode(episode_id)
    assert outcome.status is WriteStatus.CRITIC_FAILED
    assert any(f.code == "complexity-locations" for f in outcome.findings)


def test_complexity_runtime_band_enforced(world: World) -> None:
    """A one-line draft is far below the approved 180-second minimum: typed failure."""
    episode_id = _ready(world)
    world.llm.script_role(
        RuntimeRole.STORY_ARCHITECT,
        {
            "scenes": [
                {
                    "location_id": "stall",
                    "lines": [
                        {
                            "speaker_character_id": "fon",
                            "text_th": "ครบแล้วค่ะ",
                            "text_en": "It is all paid off.",
                        }
                    ],
                }
            ]
        },
    )
    outcome = world.service.write_episode(episode_id)
    assert outcome.status is WriteStatus.CRITIC_FAILED
    assert any(f.code == "complexity-runtime" for f in outcome.findings)
