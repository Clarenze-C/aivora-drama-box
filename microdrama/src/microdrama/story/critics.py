"""Deterministic canon / character-knowledge / complexity critics (T010).

These checks run in-process on every draft, before and alongside the paid semantic critic
(SPEC §7): canon and character knowledge, Thai critical terms (names/money/negations/
relationship terms), translation presence, and bounded complexity (speakers, locations,
runtime). Findings are typed (BLOCKED vs REPAIRABLE) and drive the bounded rewrite loop in
``service.py``; nothing here can be waived by a green model score and no unknown is coerced
into a pass.
"""

from __future__ import annotations

from collections.abc import Sequence

from microdrama.contracts.primitives import ProductionLimits
from microdrama.contracts.season import SeasonScope
from microdrama.story.models import (
    CriticSeverity,
    DraftFinding,
    FactKind,
    SeasonBible,
    WriterDraft,
)


def check_draft(
    draft: WriterDraft,
    *,
    scope: SeasonScope,
    bible: SeasonBible,
    episode_number: int,
    estimated_runtime_ms: int,
    limits: ProductionLimits,
) -> list[DraftFinding]:
    """All deterministic findings for one draft. Order is stable (round-robin by scene)."""
    findings: list[DraftFinding] = []
    known_characters = {c.character_id for c in scope.characters}

    for scene_index, scene in enumerate(draft.scenes):
        for line_index, line in enumerate(scene.lines):
            if line.speaker_character_id not in known_characters:
                findings.append(
                    DraftFinding(
                        code="unknown-speaker",
                        severity=CriticSeverity.BLOCKED,
                        detail=(
                            f"speaker {line.speaker_character_id!r} is not an approved "
                            "season character"
                        ),
                        scene_index=scene_index,
                        line_index=line_index,
                    )
                )
            if not line.text_en.strip() or line.text_en.strip() == line.text_th.strip():
                findings.append(
                    DraftFinding(
                        code="translation-missing",
                        severity=CriticSeverity.BLOCKED,
                        detail="every exact Thai line needs a distinct English translation",
                        scene_index=scene_index,
                        line_index=line_index,
                    )
                )
            for term in line.critical_terms:
                if term.value_th.strip() not in line.text_th:
                    findings.append(
                        DraftFinding(
                            code="critical-term-missing",
                            severity=CriticSeverity.BLOCKED,
                            detail=(
                                f"critical term {term.kind}:{term.value_th!r} does not "
                                "appear verbatim in the Thai line"
                            ),
                            scene_index=scene_index,
                            line_index=line_index,
                        )
                    )
            premature = _premature_reveals(line.text_th, bible, episode_number)
            for fact_key, statement in premature:
                findings.append(
                    DraftFinding(
                        code="premature-reveal",
                        severity=CriticSeverity.BLOCKED,
                        detail=(
                            f"line reveals {fact_key} ({statement!r}) scheduled for a later "
                            "episode; a planned reveal is not yet character knowledge"
                        ),
                        scene_index=scene_index,
                        line_index=line_index,
                    )
                )

    speakers = {line.speaker_character_id for scene in draft.scenes for line in scene.lines}
    if len(speakers) > limits.max_featured_speaking_characters:
        findings.append(
            DraftFinding(
                code="complexity-speakers",
                severity=CriticSeverity.REPAIRABLE,
                detail=(
                    f"{len(speakers)} distinct speakers exceed the approved maximum of "
                    f"{limits.max_featured_speaking_characters}"
                ),
            )
        )
    locations = _distinct_locations(draft)
    max_locations = min(
        limits.max_active_locations,
        scope.creative_constraints.max_active_locations_per_episode,
    )
    if len(locations) > max_locations:
        findings.append(
            DraftFinding(
                code="complexity-locations",
                severity=CriticSeverity.REPAIRABLE,
                detail=(
                    f"{len(locations)} distinct locations exceed the approved maximum of "
                    f"{max_locations}"
                ),
            )
        )
    if not scope.episode_min_duration_ms <= estimated_runtime_ms <= scope.episode_max_duration_ms:
        findings.append(
            DraftFinding(
                code="complexity-runtime",
                severity=CriticSeverity.REPAIRABLE,
                detail=(
                    f"estimated runtime {estimated_runtime_ms} ms outside the approved "
                    f"{scope.episode_min_duration_ms}-{scope.episode_max_duration_ms} ms band"
                ),
            )
        )
    return findings


def _distinct_locations(draft: WriterDraft) -> set[str]:
    locations: set[str] = set()
    for scene in draft.scenes:
        raw = (scene.location_id or "").strip().lower() or "loc-1"
        locations.add(raw)
    return locations


def _premature_reveals(
    text_th: str, bible: SeasonBible, episode_number: int
) -> list[tuple[str, str]]:
    """Planned reveals scheduled AFTER this episode must not appear in its dialogue."""
    premature: list[tuple[str, str]] = []
    for fact in bible.facts:
        if fact.kind is not FactKind.PLANNED_REVEAL:
            continue
        if fact.episode_number is not None and fact.episode_number > episode_number:
            if fact.statement in text_th:
                premature.append((fact.fact_key, fact.statement))
    return premature


def blocked(findings: Sequence[DraftFinding]) -> list[DraftFinding]:
    return [f for f in findings if f.severity is CriticSeverity.BLOCKED]


__all__ = ["blocked", "check_draft"]
