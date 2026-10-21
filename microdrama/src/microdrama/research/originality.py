"""Originality / resemblance screening for season concepts (T009, MD-001).

Comparator material (supplied comparables and their personas) is DATA: it is only ever
compared against concept text, never merged into prompts or instructions. All checks are
deterministic token statistics:

- PERSONA: a concept character whose name matches a comparator persona and whose description
  overlaps that persona's traits at/above the threshold is BLOCKED (copying a persona);
  a name match with weaker trait overlap is FLAGGED.
- SCENE: a contiguous shared word n-gram between concept narrative text and a comparator
  scene of length >= the block threshold is BLOCKED (copying a scene); length >= the flag
  threshold is FLAGGED.
- An unavailable comparator corpus yields UNKNOWN — originality is unverified, never CLEAR.

Blocked concepts are never proposed; UNKNOWN/FLAGGED concepts may be proposed only with an
explicit uncertainty note (see the service).
"""

from __future__ import annotations

from dataclasses import dataclass

from microdrama.contracts.season import SeasonScope
from microdrama.research.dedupe import normalize_text, token_set, word_tokens
from microdrama.research.models import (
    ComparatorCorpus,
    ConceptDraft,
    OriginalityVerdict,
    ResemblanceFinding,
    ResemblanceKind,
    ResemblanceSeverity,
)

_UNKNOWN_NOTE = "comparator corpus unavailable; originality unverified"


@dataclass(frozen=True)
class OriginalityConfig:
    persona_trait_overlap_bp: int = 5_000
    scene_block_ngram: int = 8
    scene_flag_ngram: int = 5
    max_findings: int = 20


def _longest_common_run(a: list[str], b: list[str]) -> int:
    """Length (in words) of the longest contiguous run shared by two token lists."""
    if not a or not b:
        return 0
    previous = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        current = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                current[j] = previous[j - 1] + 1
                best = max(best, current[j])
        previous = current
    return best


def _excerpt(tokens: list[str], other: list[str], length: int) -> str:
    """A human-readable excerpt of the shared run of the given length (deterministic)."""
    wanted = None
    for i in range(len(tokens) - length + 1):
        window = tokens[i : i + length]
        for j in range(len(other) - length + 1):
            if other[j : j + length] == window:
                wanted = window
                break
        if wanted is not None:
            break
    return " ".join(wanted) if wanted is not None else ""


def _concept_texts(scope: SeasonScope) -> list[tuple[str, list[str]]]:
    """(field label, tokens) for every narrative field screening examines."""
    fields: list[tuple[str, str]] = [
        ("logline", scope.logline),
        ("premise", scope.premise),
        ("title_en", scope.title_en),
    ]
    fields.extend((f"arc.{beat.episode_number}", beat.summary) for beat in scope.arc)
    fields.extend(
        (f"character:{c.character_id}", f"{c.name_en} {c.name_th} {c.description}")
        for c in scope.characters
    )
    return [(label, word_tokens(text, keep_short=True)) for label, text in fields]


def _persona_findings(
    scope: SeasonScope, corpus: ComparatorCorpus, config: OriginalityConfig
) -> list[ResemblanceFinding]:
    findings: list[ResemblanceFinding] = []
    for character in scope.characters:
        name = normalize_text(character.name_en)
        name_tokens = set(word_tokens(character.name_en, keep_short=True))
        description = token_set(character.description)
        for index, persona in enumerate(corpus.personas):
            persona_name = normalize_text(persona.name)
            persona_name_tokens = set(word_tokens(persona.name, keep_short=True))
            name_match = bool(name) and (
                name == persona_name or (bool(name_tokens) and name_tokens == persona_name_tokens)
            )
            if not name_match:
                continue
            traits = token_set(" ".join(persona.traits))
            # Coverage: the fraction of the comparator persona's traits the concept
            # character's description also carries (embodying the persona = copying it).
            overlap_bp = round(10_000 * len(traits & description) / len(traits)) if traits else 0
            matched = f"{character.name_en} ~ {persona.name}"
            if traits and overlap_bp >= config.persona_trait_overlap_bp:
                findings.append(
                    ResemblanceFinding(
                        kind=ResemblanceKind.PERSONA,
                        severity=ResemblanceSeverity.BLOCKED,
                        comparator_ref=f"persona[{index}]",
                        matched_excerpt=matched[:2000],
                        matched_in=f"character.{character.character_id}",
                        detail=(
                            "comparator persona name reused with strongly overlapping traits "
                            f"({overlap_bp}bp)"
                        ),
                    )
                )
            else:
                findings.append(
                    ResemblanceFinding(
                        kind=ResemblanceKind.PERSONA,
                        severity=ResemblanceSeverity.FLAG,
                        comparator_ref=f"persona[{index}]",
                        matched_excerpt=matched[:2000],
                        matched_in=f"character.{character.character_id}",
                        detail=(
                            "comparator persona name reused; trait overlap below the block "
                            f"threshold ({overlap_bp}bp)"
                            if traits
                            else "comparator persona name reused; no traits recorded to compare"
                        ),
                    )
                )
    return findings


def _scene_findings(
    scope: SeasonScope, corpus: ComparatorCorpus, config: OriginalityConfig
) -> list[ResemblanceFinding]:
    findings: list[ResemblanceFinding] = []
    scenes = [
        (index, word_tokens(scene, keep_short=True)) for index, scene in enumerate(corpus.scenes)
    ]
    for label, field_tokens in _concept_texts(scope):
        if len(field_tokens) < config.scene_flag_ngram:
            continue
        for index, scene_tokens in scenes:
            if len(scene_tokens) < config.scene_flag_ngram:
                continue
            run = _longest_common_run(field_tokens, scene_tokens)
            if run < config.scene_flag_ngram:
                continue
            severity = (
                ResemblanceSeverity.BLOCKED
                if run >= config.scene_block_ngram
                else ResemblanceSeverity.FLAG
            )
            excerpt = _excerpt(field_tokens, scene_tokens, min(run, 24))
            findings.append(
                ResemblanceFinding(
                    kind=ResemblanceKind.SCENE,
                    severity=severity,
                    comparator_ref=f"scene[{index}]",
                    matched_excerpt=(excerpt or f"shared {run}-word run")[:2000],
                    matched_in=label,
                    detail=f"longest shared word run with a comparator scene: {run}",
                )
            )
    return findings


def screen_concept(
    concept: ConceptDraft, corpus: ComparatorCorpus, config: OriginalityConfig
) -> OriginalityVerdict:
    """Screen one candidate concept against the comparator corpus (pure, deterministic)."""
    if not corpus.available:
        return OriginalityVerdict(status="UNKNOWN", note=_UNKNOWN_NOTE)
    findings = _persona_findings(concept.scope, corpus, config)
    findings.extend(_scene_findings(concept.scope, corpus, config))
    # Deterministic order: severity, kind, comparator, field.
    findings.sort(key=lambda f: (f.severity.value, f.kind.value, f.comparator_ref, f.matched_in))
    findings = findings[: config.max_findings]
    if any(f.severity is ResemblanceSeverity.BLOCKED for f in findings):
        status = "BLOCKED"
        note = "concept copies comparator scenes or personas; it cannot be proposed"
    elif findings:
        status = "FLAGGED"
        note = "concept resembles comparator material; proposed with an explicit uncertainty note"
    else:
        status = "CLEAR"
        note = None
    return OriginalityVerdict(status=status, findings=findings, note=note)


def uncertainty_note_for(verdict: OriginalityVerdict) -> str | None:
    """The extra note a proposal must carry when its concept was not CLEAR."""
    if verdict.status == "CLEAR":
        return None
    if verdict.status == "UNKNOWN":
        return _UNKNOWN_NOTE
    counted = {
        severity.value: sum(1 for f in verdict.findings if f.severity.value == severity.value)
        for severity in ResemblanceSeverity
    }
    return (
        f"originality {verdict.status.value.lower()} against comparator material "
        f"(blocked findings: {counted['BLOCKED']}, flags: {counted['FLAG']})"
    )


__all__ = [
    "OriginalityConfig",
    "OriginalityVerdict",
    "screen_concept",
    "uncertainty_note_for",
]
