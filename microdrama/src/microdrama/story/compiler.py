"""Compile an accepted writer draft into the frozen story contracts (T010).

Deterministic, in-process and free: the draft is data, and the compiled EpisodePlan /
Script / ShotManifest carry exact Thai lines + translations, estimated timings (actual
timings stay ``None`` until the voice lane measures them), and every shot gets its full
directing-playbook and routing field set from ``playbook.DIRECTING_PLAYBOOK``.

Unsupported staging is simplified automatically (SPEC §7): requested generation controls
outside the configured supported set are dropped, the shot keeps a static composition and
its pattern's fallback edit, and the simplification is recorded — while the dramatic change
(pattern, purpose/payoff, dialogue bindings, importance) is preserved.
"""

from __future__ import annotations

import re
from uuid import UUID

from microdrama.contracts.enums import (
    ControlKind,
    CriticalTermKind,
    DialogueComplexity,
    FallbackEdit,
    Level,
    RenderTier,
    ShotPattern,
)
from microdrama.contracts.primitives import Identifier
from microdrama.contracts.season import (
    ArcBeat,
    CriticalTerm,
    DialogueLine,
    EpisodePlan,
    Scene,
    Script,
    SeasonScope,
    Shot,
    ShotManifest,
)
from microdrama.story.models import (
    FactKind,
    SeasonBible,
    StagingSimplification,
    WriterDraft,
)
from microdrama.story.playbook import pattern_for
from microdrama.story.prompts import estimate_line_ms

_IDENT_RE = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,119}$")
_SCENE_PAD_MS = 1_500
_SHOT_PAD_MS = 400
_ESTABLISHING_MS = 2_000
_MAX_SHOT_MS = 15_000


def _identifier(raw: object, fallback: str) -> Identifier:
    """Writer-supplied ids are data: kept only when already valid identifiers."""
    if isinstance(raw, str) and _IDENT_RE.fullmatch(raw.strip().lower()):
        return raw.strip().lower()
    return fallback


def _identifiers(raw_list: object) -> list[Identifier]:
    if not isinstance(raw_list, list):
        return []
    return sorted({item for item in (_identifier(x, "") for x in raw_list) if item})


def _control(raw: object) -> ControlKind | None:
    if not isinstance(raw, str):
        return None
    try:
        return ControlKind(raw.strip())
    except ValueError:
        return None


def _fallback(raw: object) -> FallbackEdit | None:
    if not isinstance(raw, str):
        return None
    try:
        return FallbackEdit(raw.strip())
    except ValueError:
        return None


def _pattern(raw: object) -> ShotPattern | None:
    if not isinstance(raw, str):
        return None
    try:
        return ShotPattern(raw.strip())
    except ValueError:
        return None


def choose_pattern(
    *,
    is_final_line: bool,
    has_cliffhanger: bool,
    reveals_now: bool,
    has_critical_terms: bool,
    is_reply: bool,
    quiet_opener: bool,
) -> ShotPattern:
    """Deterministic pattern choice for one dialogue shot from the six-pattern playbook."""
    if is_final_line and has_cliffhanger:
        return ShotPattern.CLIFFHANGER
    if reveals_now:
        return ShotPattern.REVELATION
    if has_critical_terms:
        return ShotPattern.PRACTICAL_PROP_ACTION
    if is_reply:
        return ShotPattern.CONFRONTATION
    if quiet_opener:
        return ShotPattern.QUIET_CONFESSION
    return ShotPattern.COMIC_REACTION


def _simplify_staging(
    *,
    shot_id: str,
    requested_controls: list[ControlKind],
    supported: frozenset[ControlKind],
    pattern_fallback: FallbackEdit,
    writer_fallback: FallbackEdit | None,
    purpose: str,
) -> tuple[list[ControlKind], FallbackEdit, StagingSimplification | None]:
    """Keep supported controls; replace unsupported staging while preserving the change."""
    removed = [c for c in requested_controls if c not in supported]
    kept = [c for c in requested_controls if c in supported]
    if not removed:
        return kept, writer_fallback or pattern_fallback, None
    # Simplified staging: the pattern's own fallback edit replaces the unsupported staging.
    # The dramatic change (purpose + payoff + dialogue bindings) is untouched.
    simplification = StagingSimplification(
        shot_id=shot_id,
        removed_controls=[c.value for c in removed],
        fallback_applied=pattern_fallback,
        preserved_change=purpose,
    )
    return kept, pattern_fallback, simplification


def compile_episode(
    *,
    draft: WriterDraft,
    scope: SeasonScope,
    bible: SeasonBible,
    episode_id: UUID,
    episode_number: int,
    script_id: UUID,
    manifest_id: UUID,
    script_version: int,
    manifest_version: int,
    identity_lock_id: UUID | None,
    supported_controls: frozenset[ControlKind],
    uncertainty_notes: list[str] | None = None,
) -> tuple[EpisodePlan, Script, ShotManifest, list[StagingSimplification], list[str]]:
    """Build (plan, script, manifest, simplifications, notes) from an accepted draft.

    The draft has already passed both critic layers; every structure the frozen contracts
    enforce (speaker/location caps, unique ids, dependency closure, 15-second units) is
    produced deterministically here.
    """
    notes = list(uncertainty_notes or [])
    beat: ArcBeat | None = next((b for b in scope.arc if b.episode_number == episode_number), None)
    if beat is None:
        notes.append(
            f"no approved arc beat for episode {episode_number}; plan derived from the "
            "approved scope"
        )

    # --- scenes and exact Thai lines ----------------------------------------------------
    scenes: list[Scene] = []
    compiled_lines: list[list[DialogueLine]] = []
    for scene_index, raw_scene in enumerate(draft.scenes, start=1):
        location_id = _identifier(raw_scene.location_id, f"loc-{scene_index}")
        lines = [
            DialogueLine(
                line_id=f"sc{scene_index}-l{line_index}",
                speaker_character_id=raw_line.speaker_character_id,
                voice_id=None,  # assigned by the voice lane (T011)
                text_th=raw_line.text_th,
                text_en=raw_line.text_en,
                estimated_duration_ms=estimate_line_ms(raw_line.text_th),
                actual_duration_ms=None,  # unknown until the actual audio is measured
                critical_terms=[
                    CriticalTerm(
                        kind=CriticalTermKind(term.kind),
                        value_th=term.value_th.strip(),
                        value_en=(term.value_en or "").strip() or None,
                    )
                    for term in raw_line.critical_terms
                ],
            )
            for line_index, raw_line in enumerate(raw_scene.lines, start=1)
        ]
        scenes.append(
            Scene(
                scene_id=f"sc{scene_index}",
                location_id=location_id,
                summary=(raw_scene.summary or f"Scene {scene_index}").strip()[:500],
                lines=lines,
            )
        )
        compiled_lines.append(lines)

    estimated_runtime = sum(
        ln.estimated_duration_ms for lines in compiled_lines for ln in lines
    ) + _SCENE_PAD_MS * len(scenes)
    speakers = sorted({ln.speaker_character_id for lines in compiled_lines for ln in lines})
    locations = sorted({sc.location_id for sc in scenes})
    target = int(
        max(scope.episode_min_duration_ms, min(scope.episode_max_duration_ms, estimated_runtime))
    )

    plan = EpisodePlan(
        episode_id=episode_id,
        season_id=scope.season_id,
        approved_scope_hash=bible.approved_scope_hash,
        episode_number=episode_number,
        title_th=f"ตอนที่ {episode_number}",
        title_en=f"Episode {episode_number}",
        synopsis=(
            beat.summary
            if beat is not None
            else "Continue the approved arc inside the approved season scope."
        ),
        target_duration_ms=target,
        featured_character_ids=speakers,
        location_ids=locations,
        planned_beats=[beat.summary] if beat is not None else ["Continue the approved arc"],
        planned_reveals=list(beat.planned_reveals) if beat is not None else [],
        cliffhanger=beat.cliffhanger if beat is not None else None,
        canon_version=bible.canon_version,
    )
    script = Script(
        script_id=script_id,
        episode_id=episode_id,
        version=script_version,
        approved_scope_hash=bible.approved_scope_hash,
        canon_version=bible.canon_version,
        scenes=scenes,
        estimated_runtime_ms=estimated_runtime,
    )

    # --- shot manifest -------------------------------------------------------------------
    reveal_statements_now = {
        fact.statement
        for fact in bible.facts
        if fact.kind is FactKind.PLANNED_REVEAL and fact.episode_number == episode_number
    }
    shots: list[Shot] = []
    simplifications: list[StagingSimplification] = []
    state = {"sequence": 0, "index": 0}

    def _emit(shot: Shot) -> None:
        if shots:
            shot = shot.model_copy(update={"depends_on_shot_ids": [shots[-1].shot_id]})
        shots.append(shot)

    for scene, lines, raw_scene in zip(scenes, compiled_lines, draft.scenes, strict=True):
        # An establishing/objective shot opens any multi-line scene (no dialogue).
        if len(lines) >= 2:
            state["sequence"] += 1
            state["index"] += 1
            shot_id = f"shot-{state['index']}"
            pattern = pattern_for(ShotPattern.PRACTICAL_PROP_ACTION)
            purpose = f"Establish {scene.summary}"
            base = [ControlKind.LOCATION_REFERENCE, ControlKind.CHARACTER_REFERENCE]
            requested = [
                *base,
                *(c for c in (_control(x) for x in raw_scene.staging.controls) if c is not None),
            ]
            kept, fallback, simplification = _simplify_staging(
                shot_id=shot_id,
                requested_controls=requested,
                supported=supported_controls,
                pattern_fallback=pattern.default_fallback,
                writer_fallback=_fallback(raw_scene.staging.fallback_edit),
                purpose=purpose,
            )
            if simplification is not None:
                simplifications.append(simplification)
            _emit(
                Shot(
                    shot_id=shot_id,
                    sequence=state["sequence"],
                    scene_id=scene.scene_id,
                    shot_pattern_id=pattern.pattern_id,
                    coverage_role=pattern.coverage[0],
                    purpose=purpose,
                    dramatic_importance=Level.LOW,
                    dialogue_complexity=DialogueComplexity.NONE,
                    temporal_risk=Level.LOW,
                    required_identity_controls=sorted({ControlKind.TEXT_PROMPT, *kept}),
                    preferred_render_tier=RenderTier.FAST_FOUR_STEP,
                    fallback_edit=fallback,
                    reference_lock_version=None,
                    line_ids=[],
                    speaker_ids=[],
                    voice_ids=[],
                    target_duration_ms=_ESTABLISHING_MS,
                    framing="wide static establishing composition",
                    eyelines="camera surveys the scene",
                    location_id=scene.location_id,
                    outfit_ids=[],
                    prop_ids=_identifiers(raw_scene.staging.prop_ids),
                    required_reference_asset_ids=[],
                    sound=raw_scene.staging.sound or "room tone",
                    acceptance_criteria=list(pattern.continuity),
                    depends_on_shot_ids=[],
                )
            )

        for line_index, (line, raw_line) in enumerate(zip(lines, raw_scene.lines, strict=True)):
            state["sequence"] += 1
            state["index"] += 1
            shot_id = f"shot-{state['index']}"
            reveals_now = any(s in line.text_th for s in reveal_statements_now)
            previous_speaker = lines[line_index - 1].speaker_character_id if line_index else None
            is_final_line = scene is scenes[-1] and line_index == len(lines) - 1
            pattern_id = _pattern(raw_line.staging.pattern_id) or choose_pattern(
                is_final_line=is_final_line,
                has_cliffhanger=bool(beat is not None and beat.cliffhanger),
                reveals_now=reveals_now,
                has_critical_terms=bool(line.critical_terms),
                is_reply=previous_speaker is not None
                and previous_speaker != line.speaker_character_id,
                quiet_opener=len(lines) <= 2 and line_index == 0,
            )
            pattern = pattern_for(pattern_id)
            purpose = f"{pattern.payoff} — {line.text_en.strip()[:160]}"
            base = [
                ControlKind.CHARACTER_REFERENCE,
                ControlKind.VOICE_REFERENCE,
                ControlKind.LOCATION_REFERENCE,
            ]
            requested = [
                *base,
                *(c for c in (_control(x) for x in raw_line.staging.controls) if c is not None),
            ]
            kept, fallback, simplification = _simplify_staging(
                shot_id=shot_id,
                requested_controls=requested,
                supported=supported_controls,
                pattern_fallback=pattern.default_fallback,
                writer_fallback=_fallback(raw_line.staging.fallback_edit),
                purpose=purpose,
            )
            if simplification is not None:
                simplifications.append(simplification)
            importance = (
                Level.CRITICAL
                if is_final_line and beat is not None and beat.cliffhanger
                else Level.HIGH
                if line.critical_terms
                else Level.MEDIUM
            )
            duration = int(max(1_000, min(_MAX_SHOT_MS, line.estimated_duration_ms + _SHOT_PAD_MS)))
            _emit(
                Shot(
                    shot_id=shot_id,
                    sequence=state["sequence"],
                    scene_id=scene.scene_id,
                    shot_pattern_id=pattern.pattern_id,
                    coverage_role=pattern.coverage[min(line_index, len(pattern.coverage) - 1)],
                    purpose=purpose,
                    dramatic_importance=importance,
                    dialogue_complexity=DialogueComplexity.SINGLE_SPEAKER,
                    temporal_risk=Level.HIGH if line.critical_terms else Level.MEDIUM,
                    required_identity_controls=sorted({ControlKind.TEXT_PROMPT, *kept}),
                    preferred_render_tier=pattern.default_tier,
                    fallback_edit=fallback,
                    reference_lock_version=None,  # provisional until the identity lock (T011)
                    line_ids=[line.line_id],
                    speaker_ids=[line.speaker_character_id],
                    voice_ids=[],
                    target_duration_ms=duration,
                    framing=raw_line.staging.framing or "medium shot, static composition",
                    eyelines=raw_line.staging.eyelines or "speaker faces the listener",
                    location_id=scene.location_id,
                    outfit_ids=_identifiers(raw_line.staging.prop_ids),
                    prop_ids=[],
                    required_reference_asset_ids=[],
                    sound=raw_line.staging.sound or "room tone",
                    acceptance_criteria=[
                        *pattern.continuity,
                        f"Thai line {line.line_id} spoken exactly as scripted",
                    ],
                    depends_on_shot_ids=[],
                )
            )

    manifest = ShotManifest(
        manifest_id=manifest_id,
        episode_id=episode_id,
        episode_number=episode_number,
        script_id=script_id,
        script_version=script_version,
        version=manifest_version,
        identity_lock_id=identity_lock_id,
        shots=shots,
    )
    return plan, script, manifest, simplifications, notes


__all__ = ["choose_pattern", "compile_episode"]
