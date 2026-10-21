"""The six directing patterns (IMP-02), compiled from the shared accepted example.

The accepted example at ``deliverables/thai-microdrama-research-2026-10-19/
directing-playbook.example.json`` is an INACTIVE DESIGN EXAMPLE: this module reads it as
an INPUT (``load_playbook_example``) and never writes it. The embedded copy below carries
the example's purpose/coverage/continuity/payoff verbatim plus the routing defaults this
module adds (fallback edit and render tier per pattern); a contract test pins the embedded
copy against the shared file so the two cannot drift silently.

Per shot (SPEC §7) the playbook contributes pattern/purpose, dramatic importance defaults,
dialogue/temporal risk guidance, identity controls, compatible tier, fallback edit,
reference-lock version and acceptance criteria — every field the frozen ``Shot`` contract
requires is filled from here or simplified from writer staging (see ``compiler.py``).
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field, ValidationError

from microdrama.contracts.enums import FallbackEdit, RenderTier, ShotPattern
from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.primitives import ContractModel, Identifier, ShortText

PLAYBOOK_VERSION = "directing-playbook-v1"
EXAMPLE_DOCUMENT_KIND = "INACTIVE_DESIGN_EXAMPLE"


class DirectingPattern(ContractModel):
    """One reusable directing pattern: distinct plots/performance shapes share a spine."""

    pattern_id: ShotPattern
    purpose: ShortText
    coverage: list[Identifier] = Field(min_length=1)
    continuity: list[ShortText] = Field(min_length=1)
    payoff: ShortText
    default_fallback: FallbackEdit
    default_tier: RenderTier


# Embedded from the accepted example (read as input; see module docstring). The routing
# defaults are this module's: dialogue/emotional patterns take the quality tier, practical
# inserts may use the compatible baseline, comic beats may use the fast tier.
DIRECTING_PLAYBOOK: tuple[DirectingPattern, ...] = (
    DirectingPattern(
        pattern_id=ShotPattern.CONFRONTATION,
        purpose="Make competing wants clear through an exchange and reaction.",
        coverage=["initiator", "respondent", "reaction_or_shared_space"],
        continuity=[
            "preserve_action_axis",
            "match_eyelines",
            "consistent_prop_positions",
        ],
        payoff="A choice, refusal or changed leverage.",
        default_fallback=FallbackEdit.CUT_TO_REACTION,
        default_tier=RenderTier.QUALITY_EIGHT_STEP,
    ),
    DirectingPattern(
        pattern_id=ShotPattern.REVELATION,
        purpose="Show evidence that changes a character belief.",
        coverage=["evidence_or_action", "character_comprehension", "consequence"],
        continuity=[
            "key_evidence_readable",
            "reaction_after_evidence",
            "no_premature_subtitle_spoiler",
        ],
        payoff="The audience understands what changed.",
        default_fallback=FallbackEdit.COMPOSITE_TEXT_INSERT,
        default_tier=RenderTier.QUALITY_EIGHT_STEP,
    ),
    DirectingPattern(
        pattern_id=ShotPattern.QUIET_CONFESSION,
        purpose="Expose a vulnerable motive with room for silence.",
        coverage=["speaker", "listener", "optional_shared_silence"],
        continuity=[
            "preserve_voice_identity",
            "no_unmotivated_camera_change",
            "continuous_room_tone",
        ],
        payoff="A relationship changes, even without a plot twist.",
        default_fallback=FallbackEdit.WIDE_SHOT_OVER_DIALOGUE,
        default_tier=RenderTier.QUALITY_EIGHT_STEP,
    ),
    DirectingPattern(
        pattern_id=ShotPattern.COMIC_REACTION,
        purpose="Release tension through a character-specific response.",
        coverage=["setup", "response", "reaction_if_needed"],
        continuity=[
            "joke_meaning_survives_subtitles",
            "preserve_timing",
            "no_repetitive_stock_gag",
        ],
        payoff="Humor reveals character or changes the interaction.",
        default_fallback=FallbackEdit.CUT_TO_REACTION,
        default_tier=RenderTier.FAST_FOUR_STEP,
    ),
    DirectingPattern(
        pattern_id=ShotPattern.PRACTICAL_PROP_ACTION,
        purpose="Make a practical objective or money/repair detail legible.",
        coverage=["objective", "controlled_action_or_insert", "result"],
        continuity=[
            "same_prop_id",
            "correct_hand_state",
            "composite_critical_text_in_post",
        ],
        payoff="A visible result affects the decision.",
        default_fallback=FallbackEdit.INSERT_STILL_WITH_AUDIO,
        default_tier=RenderTier.COMPATIBLE_BASELINE,
    ),
    DirectingPattern(
        pattern_id=ShotPattern.CLIFFHANGER,
        purpose="Leave a consequential next question after paying off a current beat.",
        coverage=["earned_consequence", "reaction_or_decision", "clear_next_episode_path"],
        continuity=[
            "no_misleading_reversal",
            "match_published_canon",
            "truthful_episode_availability",
        ],
        payoff="A real unresolved decision or consequence, not withheld basic context.",
        default_fallback=FallbackEdit.HOLD_PREVIOUS_FRAME,
        default_tier=RenderTier.QUALITY_EIGHT_STEP,
    ),
)

PATTERN_BY_ID: dict[ShotPattern, DirectingPattern] = {p.pattern_id: p for p in DIRECTING_PLAYBOOK}

assert set(PATTERN_BY_ID) == set(ShotPattern), "the playbook must cover all six patterns exactly"


def pattern_for(pattern_id: ShotPattern) -> DirectingPattern:
    return PATTERN_BY_ID[ShotPattern(pattern_id)]


def default_playbook_path() -> Path:
    """Locate the shared accepted example relative to this module (read-only input)."""
    # .../microdrama/src/microdrama/story/playbook.py -> repo root is parents[4]
    root = Path(__file__).resolve().parents[4]
    return (
        root
        / "deliverables"
        / "thai-microdrama-research-2026-10-19"
        / ("directing-playbook.example.json")
    )


def load_playbook_example(path: Path) -> tuple[DirectingPattern, ...]:
    """Read and validate the shared example as INPUT; never write it back.

    The example is a design document (``INACTIVE_DESIGN_EXAMPLE`` with ``runtime_enabled``
    false): loading proves the embedded patterns track it; it does not make the example a
    writable runtime library. Validation fails closed on any drift in identity (version,
    pattern ids, document kind) so a changed example surfaces as a typed error, not a
    silent behavioural change.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaInvalid(
            f"directing playbook example unreadable: {exc}", path=str(path)
        ) from exc
    if document.get("document_kind") != EXAMPLE_DOCUMENT_KIND:
        raise SchemaInvalid(
            "unexpected directing playbook document_kind",
            path=str(path),
            document_kind=str(document.get("document_kind")),
        )
    if document.get("version") != PLAYBOOK_VERSION:
        raise SchemaInvalid(
            "directing playbook example version drift",
            path=str(path),
            expected=PLAYBOOK_VERSION,
            found=str(document.get("version")),
        )
    if document.get("runtime_enabled") is not False:
        raise SchemaInvalid(
            "the directing playbook example must stay runtime_enabled=false",
            path=str(path),
        )
    patterns = []
    try:
        for raw in document.get("patterns", []):
            pattern_id = ShotPattern(raw["id"])
            embedded = PATTERN_BY_ID[pattern_id]
            patterns.append(
                embedded.model_copy(
                    update={
                        "purpose": raw["purpose"],
                        "coverage": list(raw["coverage"]),
                        "continuity": list(raw["continuity"]),
                        "payoff": raw["payoff"],
                    }
                )
            )
    except (KeyError, ValueError, ValidationError) as exc:
        raise SchemaInvalid(f"directing playbook example malformed: {exc}", path=str(path)) from exc
    if {p.pattern_id for p in patterns} != set(ShotPattern):
        raise SchemaInvalid(
            "the example must define exactly the six accepted patterns",
            path=str(path),
        )
    return tuple(patterns)


__all__ = [
    "DIRECTING_PLAYBOOK",
    "DirectingPattern",
    "EXAMPLE_DOCUMENT_KIND",
    "PLAYBOOK_VERSION",
    "PATTERN_BY_ID",
    "default_playbook_path",
    "load_playbook_example",
    "pattern_for",
]
