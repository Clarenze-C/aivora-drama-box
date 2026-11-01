"""Deterministic V2 episode-pack directing compiler (T041a).

Compilation is pure and validates the canonical directing contract before returning,
so malformed continuity is stopped before any provider reservation or paid work.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.primitives import ContractModel, Identifier, LongText
from microdrama.contracts.v2 import (
    DirectingManifest,
    DirectingSection,
    DirectingShot,
    EpisodePack,
    SceneWardrobeAssignment,
    SecretLedger,
    StateEvent,
    StateValue,
    WardrobeBible,
    validate_directing_manifest,
    verify_v2_record_hash,
)

_NS = uuid5(NAMESPACE_URL, "https://microdrama.invalid/story/directing/v2")
_MAX_SHOT_MS = 15_000
_SECTION_MS = 30_000


class BeatIntent(ContractModel):
    """Human/editorial intent required to make screen continuity explicit."""

    screen_axis: Identifier
    screen_direction: Literal["STATIC", "LEFT_TO_RIGHT", "RIGHT_TO_LEFT"]
    eyeline: LongText
    action_handoff: LongText
    sound_intent: LongText
    edit_intent: LongText
    framing: Identifier


def _stable(prefix: str, *parts: object) -> str:
    return f"{prefix}-{uuid5(_NS, ':'.join(str(x) for x in parts)).hex[:20]}"


def _states(values) -> dict[tuple[str, str], object]:
    return {(v.entity_id, v.field): v.value for v in values}


def _validate_state_values(values, known_entities: set[str], label: str) -> None:
    keys = [(item.entity_id, item.field) for item in values]
    if len(keys) != len(set(keys)):
        raise ValueError(f"contradictory duplicate {label} state")
    unknown = sorted({entity for entity, _ in keys} - known_entities)
    if unknown:
        raise ValueError(f"unknown {label} state entities: {unknown}")
    for item in values:
        if item.field == "holder" and item.value is not None and item.value not in known_entities:
            raise ValueError(f"unknown {label} prop holder: {item.value}")
        if (
            item.field == "hand"
            and item.value is not None
            and item.value not in {"left", "right", "both", "none", "unknown"}
        ):
            raise ValueError(f"invalid {label} hand state: {item.value}")


def _validate_secrets(pack: EpisodePack, ledger: SecretLedger | None) -> None:
    if ledger is None:
        raise ValueError(
            "secret ledger is required to validate reveal timing and future-secret leakage"
        )
    verify_v2_record_hash(ledger)
    if ledger.season_id != pack.season_id:
        raise ValueError("secret ledger belongs to a different season")
    entries = {secret.secret_id: secret for secret in ledger.secrets}
    for scene in pack.scenes:
        for beat in scene.beats:
            for secret_id in beat.reveal_ids:
                secret = entries.get(secret_id)
                if secret is None:
                    raise ValueError(f"unknown secret reveal id: {secret_id}")
                if pack.episode_number < secret.planned_reveal_episode:
                    raise ValueError("future secret reveal is scheduled before its planned episode")
            # A not-yet-known fact must not be copied into an earlier pack's visible action.
            for secret in ledger.secrets:
                known = any(
                    secret.secret_id in logic.knowledge_by_episode.get(str(pack.episode_number), [])
                    for logic in pack.character_logic
                )
                if pack.episode_number < secret.planned_reveal_episode and not known:
                    normalized = secret.fact.casefold()
                    if normalized and normalized in beat.visible_action.casefold():
                        raise ValueError("unrevealed secret fact appears in visible action")


def compile_episode_pack(
    pack: EpisodePack,
    *,
    approved_scope_hash: str,
    intents: Mapping[str, BeatIntent],
    state_events: Sequence[StateEvent] = (),
    secret_ledger: SecretLedger | None = None,
    wardrobe_bibles: Sequence[WardrobeBible] = (),
    wardrobe_assignments: Sequence[SceneWardrobeAssignment] = (),
    draft_mode: bool = False,
) -> DirectingManifest:
    """Compile an approved pack into deterministic short shots and ~30s sections.

    `intents` must contain each beat. Production compilation requires exact wardrobe
    assignments; `draft_mode=True` permits an unassigned pack for authoring and tests.
    """
    verify_v2_record_hash(pack)
    if pack.scoped_map_only:
        raise ValueError("a scoped episode map is not an approved renderable EpisodePack")
    if pack.approved_scope_hash != approved_scope_hash:
        raise ValueError("EpisodePack is bound to a different approved scope hash")
    _validate_secrets(pack, secret_ledger)

    characters = {logic.character_id for logic in pack.character_logic}
    prop_ids = {prop for scene in pack.scenes for prop in scene.prop_ids}
    location_ids = {scene.location_id for scene in pack.scenes}
    known_entities = characters | prop_ids | location_ids

    events_by_scene: dict[str, list[StateEvent]] = {}
    for event in state_events:
        verify_v2_record_hash(event)
        if event.episode_id != pack.episode_id:
            raise ValueError("state event belongs to a different episode")
        if event.entity_id not in known_entities:
            raise ValueError(f"unknown state event entity: {event.entity_id}")
        if event.scene_id not in {scene.scene_id for scene in pack.scenes}:
            raise ValueError(f"unknown state event scene: {event.scene_id}")
        for value in (event.before, event.after):
            if event.field == "holder" and value is not None and value not in known_entities:
                raise ValueError(f"unknown state event prop holder: {value}")
            if (
                event.field == "hand"
                and value is not None
                and value not in {"left", "right", "both", "none", "unknown"}
            ):
                raise ValueError(f"invalid state event hand state: {value}")
        events_by_scene.setdefault(event.scene_id, []).append(event)
    for rows in events_by_scene.values():
        rows.sort(key=lambda event: (event.effective_from_ms, event.sequence))
        if len({event.sequence for event in rows}) != len(rows):
            raise ValueError("duplicate state event sequence within scene")
        for previous, current in zip(rows, rows[1:], strict=False):
            if current.sequence <= previous.sequence:
                raise ValueError("state event sequences must increase with effective time")
            if (previous.entity_id, previous.field) == (
                current.entity_id,
                current.field,
            ) and previous.after != current.before:
                raise ValueError("contradictory state event chain")

    if not wardrobe_assignments and not draft_mode:
        raise ValueError("wardrobe assignments are required outside draft mode")
    if (
        draft_mode
        and not wardrobe_assignments
        and any(scene.wardrobe_assignment_ids for scene in pack.scenes)
    ):
        raise ValueError("draft mode cannot omit declared wardrobe assignments")
    if wardrobe_assignments:
        bibles = {b.record_id: b for b in wardrobe_bibles}
        for bible in bibles.values():
            verify_v2_record_hash(bible)
        assignment_map: dict[tuple[str, str], SceneWardrobeAssignment] = {}
        for assignment in wardrobe_assignments:
            verify_v2_record_hash(assignment)
            if assignment.episode_id != pack.episode_id:
                raise ValueError("wardrobe assignment belongs to a different episode")
            scene = next((s for s in pack.scenes if s.scene_id == assignment.scene_id), None)
            if scene is None or assignment.character_id not in scene.visible_character_ids:
                raise ValueError("wardrobe assignment does not match a visible character and scene")
            bible = bibles.get(assignment.wardrobe_bible_id)
            if (
                bible is None
                or bible.character_id != assignment.character_id
                or bible.version != assignment.wardrobe_bible_version
                or bible.season_id != pack.season_id
            ):
                raise ValueError(
                    "wardrobe assignment does not bind the exact character bible version"
                )
            outfit = next((o for o in bible.outfits if o.outfit_id == assignment.outfit_id), None)
            if outfit is None or (
                outfit.version,
                outfit.asset_id,
                outfit.asset_version,
                outfit.asset_sha256,
            ) != (
                assignment.outfit_version,
                assignment.asset_id,
                assignment.asset_version,
                assignment.asset_sha256,
            ):
                raise ValueError("wardrobe assignment does not bind the exact outfit asset")
            if not (
                outfit.story_day_from <= assignment.story_day
                and (
                    outfit.story_day_until is None or assignment.story_day <= outfit.story_day_until
                )
            ):
                raise ValueError("assigned outfit is outside its story-day validity interval")
            if (
                assignment.story_day != scene.story_time.story_day
                or assignment.setting != scene.story_time.setting
            ):
                raise ValueError("wardrobe assignment story day or setting differs from its scene")
            if assignment.setting not in outfit.setting_tags:
                raise ValueError("assigned outfit is not approved for the scene setting")
            if assignment.record_id not in scene.wardrobe_assignment_ids:
                raise ValueError("wardrobe assignment ID is not declared by its scene")
            key = (assignment.scene_id, assignment.character_id)
            if key in assignment_map:
                raise ValueError("conflicting duplicate wardrobe assignment")
            assignment_map[key] = assignment
        for scene in pack.scenes:
            declared_ids = set(scene.wardrobe_assignment_ids)
            resolved_ids = {
                row.record_id for row in assignment_map.values() if row.scene_id == scene.scene_id
            }
            if declared_ids != resolved_ids:
                raise ValueError("scene wardrobe assignment IDs do not resolve exactly")
            if any(
                (scene.scene_id, char) not in assignment_map for char in scene.visible_character_ids
            ):
                raise ValueError("visible cast is missing an exact wardrobe assignment")

    pack_hash = pack.calculated_content_sha256()
    rolling: dict[tuple[str, str], object] = {}
    shots: list[DirectingShot] = []
    all_beats = [(scene, beat) for scene in pack.scenes for beat in scene.beats]
    section_bins: list[list[DirectingShot]] = []
    current: list[DirectingShot] = []
    current_ms = 0
    shot_sequence = 0
    episode_elapsed_ms = 0
    base_duration, remainder = divmod(pack.duration_target_ms, max(1, len(all_beats)))
    for beat_index, (scene, beat) in enumerate(all_beats):
        previous_scene = all_beats[beat_index - 1][0] if beat_index else None
        next_scene = all_beats[beat_index + 1][0] if beat_index + 1 < len(all_beats) else None
        scene_start = previous_scene is None or previous_scene.scene_id != scene.scene_id
        scene_end = next_scene is None or next_scene.scene_id != scene.scene_id
        if beat.beat_id not in intents:
            raise ValueError(f"missing explicit directing intent for beat {beat.beat_id}")
        _validate_state_values(scene.state_in, known_entities, "scene input")
        _validate_state_values(scene.state_out, known_entities, "scene output")
        _validate_state_values(beat.state_in, known_entities, "beat input")
        _validate_state_values(beat.state_out, known_entities, "beat output")
        if scene_start:
            for value in scene.state_in:
                key = (value.entity_id, value.field)
                if key in rolling and rolling[key] != value.value:
                    raise ValueError(
                        "contradictory scene state-in relative to prior scene state-out"
                    )
                rolling[key] = value.value
        for entity in scene.visible_character_ids:
            if entity not in characters:
                raise ValueError(f"visible character missing from pack logic: {entity}")
        expected_in = _states(beat.state_in)
        for key, value in expected_in.items():
            if key in rolling and rolling[key] != value:
                raise ValueError("contradictory state-in relative to prior beat state-out")
            rolling[key] = value
        duration = max(1_000, base_duration + (beat_index < remainder))
        segments = [
            min(_MAX_SHOT_MS, duration - offset) for offset in range(0, duration, _MAX_SHOT_MS)
        ]
        beat_start_ms = episode_elapsed_ms
        beat_end_ms = beat_start_ms + duration
        beat_hash = canonical_hash(beat)
        scene_hash = canonical_hash(scene.model_copy(update={"beats": []}))
        beat_events = [
            e
            for e in events_by_scene.get(scene.scene_id, [])
            if beat_start_ms <= e.effective_from_ms < beat_end_ms
        ]
        beat_assignments = [a for a in wardrobe_assignments if a.scene_id == scene.scene_id]
        shot_sources = sorted(
            {
                beat_hash,
                scene_hash,
                *(e.content_sha256 for e in beat_events),
                *(a.content_sha256 for a in beat_assignments),
            }
        )
        # The final beat's visible action and each state transition happen on its final shot.
        for segment_index, segment_ms in enumerate(segments):
            shot_sequence += 1
            shot_id = _stable("shot", pack.episode_id, pack.record_id, beat.beat_id, segment_index)
            section_id = _stable("section", pack.episode_id, pack.record_id, len(section_bins))
            intent = intents[beat.beat_id]
            start = segment_index * _MAX_SHOT_MS
            end = start + segment_ms
            active_events = [
                e
                for e in beat_events
                if beat_start_ms + start <= e.effective_from_ms < beat_start_ms + end
            ]
            is_last = segment_index == len(segments) - 1
            event_rows = active_events
            before = dict(rolling)
            state_at_shot_start = dict(before)
            for event in event_rows:
                key = (event.entity_id, event.field)
                if key not in before:
                    before[key] = event.before
                if before[key] != event.before:
                    raise ValueError("state event before-value contradicts current state")
                state_at_shot_start.setdefault(key, event.before)
                before[key] = event.after
            if is_last:
                declared_out = list(beat.state_out)
                if scene_end:
                    declared_out.extend(scene.state_out)
                declared_map: dict[tuple[str, str], object] = {}
                for value in declared_out:
                    key = (value.entity_id, value.field)
                    if key in declared_map and declared_map[key] != value.value:
                        raise ValueError("contradictory beat and scene state-out")
                    declared_map[key] = value.value
                event_outputs = {
                    (event.entity_id, event.field): event.after for event in beat_events
                }
                for key, value in declared_map.items():
                    if key in event_outputs and event_outputs[key] != value:
                        raise ValueError("declared state-out contradicts state event output")
                    if key in before and before[key] != value and key not in event_outputs:
                        raise ValueError("state-out changes state without a matching state event")
                    before[key] = value
            state_in = [
                StateValue(entity_id=k[0], field=k[1], value=v)
                for k, v in sorted(state_at_shot_start.items())
            ]
            state_out = (
                [StateValue(entity_id=k[0], field=k[1], value=v) for k, v in sorted(before.items())]
                if is_last
                else []
            )
            shot = DirectingShot(
                shot_id=shot_id,
                scene_id=scene.scene_id,
                beat_id=beat.beat_id,
                sequence=shot_sequence,
                duration_ms=segment_ms,
                section_id=section_id,
                state_in=state_in,
                events=event_rows,
                state_out=state_out,
                screen_axis=intent.screen_axis,
                eyeline=intent.eyeline,
                screen_direction=intent.screen_direction,
                action_handoff=intent.action_handoff,
                sound_intent=intent.sound_intent,
                edit_intent=intent.edit_intent,
                framing=intent.framing,
                source_dependency_ids=[pack.record_id.hex, scene.scene_id, beat.beat_id],
                source_hashes=shot_sources,
            )
            shots.append(shot)
            current.append(shot)
            current_ms += segment_ms
            rolling = before
            if current_ms >= _SECTION_MS:
                section_bins.append(current)
                current, current_ms = [], 0
        episode_elapsed_ms = beat_end_ms
    if current:
        section_bins.append(current)
    assigned_event_ids = {event.record_id for shot in shots for event in shot.events}
    if assigned_event_ids != {event.record_id for event in state_events}:
        raise ValueError("state events fall outside the compiled episode timeline")
    sections = [
        DirectingSection(
            section_id=shots_group[0].section_id,
            sequence=i + 1,
            shot_ids=[shot.shot_id for shot in shots_group],
            duration_ms=sum(shot.duration_ms for shot in shots_group),
        )
        for i, shots_group in enumerate(section_bins)
    ]
    source_hashes = sorted(
        {
            pack_hash,
            *(event.content_sha256 for event in state_events),
            *(a.content_sha256 for a in wardrobe_assignments),
            *(source_hash for shot in shots for source_hash in shot.source_hashes),
        }
    )
    fields = {
        "record_id": uuid5(_NS, f"manifest:{pack.episode_id}:{pack.record_id}"),
        "version": pack.version,
        "created_at": pack.created_at,
        "updated_at": pack.updated_at,
        "valid_from": pack.valid_from,
        "episode_id": pack.episode_id,
        "pack_id": pack.record_id,
        "pack_version": pack.version,
        "pack_hash": pack_hash,
        "approved_scope_hash": approved_scope_hash,
        "shots": shots,
        "sections": sections,
        "source_hashes": source_hashes,
    }
    manifest = DirectingManifest.seal(**fields)
    validate_directing_manifest(manifest, pack, secret_ledger=secret_ledger)
    return manifest


def invalidated_shot_ids(manifest: DirectingManifest, changed_source_hashes: set[str]) -> list[str]:
    """Return only shots directly dependent on changed source hashes."""
    return [
        shot.shot_id for shot in manifest.shots if set(shot.source_hashes) & changed_source_hashes
    ]
