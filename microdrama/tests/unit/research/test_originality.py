"""Originality / resemblance screening and proposal-level enforcement (T009, MD-001)."""

from __future__ import annotations

from research_support import (
    COMPARATOR_SCENE,
    World,
    default_concepts,
    default_corpus,
    request,
)

from microdrama.research import (
    ComparatorCorpus,
    OriginalityStatus,
)
from microdrama.research.originality import OriginalityConfig, screen_concept


def _concept_with(premise: str | None = None, logline: str | None = None, characters=None):
    concepts = default_concepts()
    updates: dict = {}
    if premise is not None:
        updates["premise"] = premise
    if logline is not None:
        updates["logline"] = logline
    if characters is not None:
        updates["characters"] = characters
    return concepts[0].model_copy(update={"scope": concepts[0].scope.model_copy(update=updates)})


def test_clean_concept_is_clear() -> None:
    verdict = screen_concept(default_concepts()[0], default_corpus(), OriginalityConfig())
    assert verdict.status is OriginalityStatus.CLEAR
    assert verdict.findings == []


def test_verbatim_scene_copy_is_blocked(world: World) -> None:
    concept = _concept_with(premise=f"Stolen beat: {COMPARATOR_SCENE} Then it continues.")
    season = world.season()
    result = world.service.run_research(season, request(concepts=[concept]))
    outcome = result.outcome
    assert outcome is not None
    assert outcome.ranked[0].verdict.status is OriginalityStatus.BLOCKED
    scene_findings = [f for f in outcome.ranked[0].verdict.findings if f.kind.value == "SCENE"]
    assert scene_findings and all(f.severity.value == "BLOCKED" for f in scene_findings)
    assert outcome.chosen_concept_id is None
    assert world.proposals(season) == []


def test_persona_copy_is_blocked(world: World) -> None:
    from microdrama.contracts.season import CharacterBrief

    thief = CharacterBrief(
        character_id="somchai",
        name_th="สมชาย",
        name_en="Detective Somchai",
        role="supporting",
        description="A stubborn, lonely, relentless detective who cannot let a case rest.",
        voice_direction="gravelly, tired",
    )
    concept = _concept_with(characters=[thief])
    season = world.season()
    result = world.service.run_research(season, request(concepts=[concept]))
    outcome = result.outcome
    assert outcome is not None
    assert outcome.ranked[0].verdict.status is OriginalityStatus.BLOCKED
    persona_findings = [f for f in outcome.ranked[0].verdict.findings if f.kind.value == "PERSONA"]
    assert persona_findings and persona_findings[0].severity.value == "BLOCKED"
    assert outcome.chosen_concept_id is None


def test_persona_name_reuse_with_different_traits_is_flagged_but_proposable(world: World) -> None:
    from microdrama.contracts.season import CharacterBrief

    namesake = CharacterBrief(
        character_id="somchai2",
        name_th="สมชาย",
        name_en="Detective Somchai",
        role="supporting",
        description="A cheerful teenage baker who loves rain and writes letters.",
        voice_direction="bright",
    )
    concept = _concept_with(characters=[namesake])
    season = world.season()
    result = world.service.run_research(season, request(concepts=[concept]))
    outcome = result.outcome
    assert outcome is not None
    verdict = outcome.ranked[0].verdict
    assert verdict.status is OriginalityStatus.FLAGGED
    assert any(f.kind.value == "PERSONA" and f.severity.value == "FLAG" for f in verdict.findings)
    # Flagged concepts stay eligible and the proposal carries the explicit uncertainty.
    assert outcome.chosen_concept_id == "concept-a"
    assert result.proposal_id is not None
    proposal = world.row("SELECT * FROM season_proposals WHERE id = %s", (result.proposal_id,))
    assert "originality flagged" in " ".join(proposal["scope"]["uncertainty_notes"])


def test_short_overlap_flags_without_blocking() -> None:
    concept = _concept_with(
        logline="A quiet cook hunts a kidnapping syndicate through the flooded lanes of memory."
    )
    verdict = screen_concept(concept, default_corpus(), OriginalityConfig())
    assert verdict.status is OriginalityStatus.FLAGGED
    assert verdict.findings and all(f.severity.value == "FLAG" for f in verdict.findings)


def test_unavailable_comparator_corpus_is_unknown_never_clear(world: World) -> None:
    concept = _concept_with(premise=f"Stolen: {COMPARATOR_SCENE}")
    season = world.season()
    result = world.service.run_research(
        season, request(corpus=ComparatorCorpus(), concepts=[concept])
    )
    outcome = result.outcome
    assert outcome is not None
    assert outcome.ranked[0].verdict.status is OriginalityStatus.UNKNOWN
    assert "originality unverified" in (outcome.ranked[0].verdict.note or "")
    # UNKNOWN remains proposable, but only with the explicit uncertainty note.
    assert outcome.chosen_concept_id == "concept-a"
    assert result.proposal_id is not None
    proposal = world.row("SELECT * FROM season_proposals WHERE id = %s", (result.proposal_id,))
    notes = " ".join(proposal["scope"]["uncertainty_notes"])
    assert "comparator corpus unavailable" in notes


def test_ranking_prefers_clear_then_support(world: World) -> None:
    concepts = default_concepts()
    # concept-b copies a scene (blocked); concept-a is clean and wins by elimination.
    stolen = concepts[1].scope.model_copy(
        update={"premise": f"Copy: {COMPARATOR_SCENE} The rest differs."}
    )
    season = world.season()
    result = world.service.run_research(
        season,
        request(concepts=[concepts[0], concepts[1].model_copy(update={"scope": stolen})]),
    )
    outcome = result.outcome
    assert outcome is not None
    by_id = {ranked.concept_id: ranked for ranked in outcome.ranked}
    assert by_id["concept-a"].rank == 1
    assert by_id["concept-b"].rank is None
    assert outcome.chosen_concept_id == "concept-a"
