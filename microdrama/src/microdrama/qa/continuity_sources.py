"""The production typed-continuity-expectations reader (T047).

Composes ``EpisodeContinuityExpectations`` for an episode from durable truth
only: windows from the episode's current FULL_EPISODE edit manifest (video-track
clip spans on the exported timeline), and every expected field from the
episode's current hash-verified V2 records plus the current script and the
approved scope's character voices. Nothing is guessed: a record that is
missing, unreadable, hash-stale or ambiguous leaves its dimensions honestly
undefined, and an episode without a current edit manifest has no expectations
at all (the QA run stays UNKNOWN, never wrong).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError

from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.media import EditDecisionList, TrackKind, video_overlap_allowed_ms
from microdrama.contracts.season import Script
from microdrama.contracts.v2 import (
    DirectingManifest,
    EpisodePack,
    LocationLayout,
    PropSheet,
    SceneWardrobeAssignment,
    StyleBible,
)
from microdrama.persistence.db import Database, Tx
from microdrama.qa.continuity import (
    EpisodeContinuityExpectations,
    ExpectedContinuityWindow,
)


def _verified_doc(tx: Tx, model: type, *, key: str, value: str) -> Any | None:
    """The single current record for a payload key, validated and hash-verified.

    None when absent or ambiguous; a record whose stored hash does not match
    its content is treated as absent too (the comparison must never run on
    content that fails its own seal).
    """
    rows = tx.fetchall(
        "SELECT payload, payload_sha256 FROM v2_contract_documents "
        "WHERE contract_type = %s AND current AND payload->>%s = %s",
        (model.__name__, key, value),
    )
    if len(rows) != 1:
        return None
    try:
        record = model.model_validate(rows[0]["payload"])
    except ValidationError:
        return None
    return record if canonical_hash(record) == rows[0]["payload_sha256"] else None


def _verified_docs(tx: Tx, model: type, *, key: str, value: str) -> list[Any]:
    rows = tx.fetchall(
        "SELECT payload, payload_sha256 FROM v2_contract_documents "
        "WHERE contract_type = %s AND current AND payload->>%s = %s",
        (model.__name__, key, value),
    )
    records = []
    for row in rows:
        try:
            record = model.model_validate(row["payload"])
        except ValidationError:
            continue
        if canonical_hash(record) == row["payload_sha256"]:
            records.append(record)
    return records


def _current_script(tx: Tx, episode_id: UUID) -> Script | None:
    row = tx.fetchone(
        "SELECT body FROM scripts WHERE episode_id = %s AND status = 'CURRENT'",
        (episode_id,),
    )
    if row is None:
        return None
    try:
        return Script.model_validate(row["body"])
    except ValidationError:
        return None


def _approved_voices(tx: Tx, season_id: UUID) -> dict[str, str]:
    """character_id -> voice direction from the season's approved scope."""
    from microdrama.contracts.season import SeasonScope

    proposal = tx.fetchone(
        "SELECT scope FROM season_proposals WHERE season_id = %s AND status = 'APPROVED' "
        "ORDER BY scope_version DESC LIMIT 1",
        (season_id,),
    )
    if proposal is None:
        return {}
    try:
        scope = SeasonScope.model_validate(proposal["scope"])
    except ValidationError:
        return {}
    return {c.character_id: c.voice_direction for c in scope.characters}


class V2RecordContinuityExpectations:
    """Read-only seam implementation over current rows (construct once)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def continuity_expectations(self, episode_id: UUID) -> EpisodeContinuityExpectations | None:
        with self._db.transaction(readonly=True) as tx:
            episode = tx.fetchone("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))
            if episode is None:
                return None
            # DB-4: the timeline lane is variant_key='main'; the NEWEST main row
            # governs regardless of state, and anything but PLANNED/RENDERED
            # means no usable timeline — never a fallback to an older row.
            manifest_row = tx.fetchone(
                "SELECT edl, state FROM edit_manifests WHERE episode_id = %s"
                " AND purpose = 'FULL_EPISODE' AND variant_key = 'main'"
                " ORDER BY version DESC LIMIT 1",
                (episode_id,),
            )
            if manifest_row is None or str(manifest_row["state"]) not in ("PLANNED", "RENDERED"):
                return None  # no usable main timeline: expectations stay unknown
            try:
                edl = EditDecisionList.model_validate(manifest_row["edl"])
            except ValidationError:
                return None
            pack = _verified_doc(tx, EpisodePack, key="episode_id", value=str(episode_id))
            directing = _verified_doc(
                tx, DirectingManifest, key="episode_id", value=str(episode_id)
            )
            if pack is None or directing is None:
                return None
            script = _current_script(tx, episode_id)
            voices = _approved_voices(tx, episode["season_id"])
            assignments = _verified_docs(
                tx, SceneWardrobeAssignment, key="episode_id", value=str(episode_id)
            )
            style = _verified_doc(tx, StyleBible, key="season_id", value=str(episode["season_id"]))
            shots = {shot.shot_id: shot for shot in directing.shots}
            scenes = {scene.scene_id: scene for scene in pack.scenes}
            windows: list[ExpectedContinuityWindow] = []
            for clip in sorted(
                (c for c in edl.clips if c.track is TrackKind.VIDEO),
                key=lambda c: c.timeline_in_ms,
            ):
                shot_id = clip.clip_id.rsplit(".", 1)[0]
                shot = shots.get(shot_id)
                if shot is None:
                    # DB-3: a VIDEO clip the records cannot map makes the whole
                    # expectations set incomplete — a partial window list would
                    # silently shrink QA coverage.
                    return None
                scene = scenes.get(shot.scene_id)
                if scene is None:
                    return None
                start = int(clip.timeline_in_ms)
                end = start + int(clip.source_out_ms - clip.source_in_ms)
                # DBR-2: mirror EditDecisionList._timeline exactly — a clip
                # arriving with a CROSSFADE may start transition_ms inside the
                # previous window (the shared video_overlap_allowed_ms rule).
                # An empty window, or an overlap beyond that allowance, is
                # dropped evidence (DB-3), never silently skipped.
                overlap_allowed = video_overlap_allowed_ms(clip) if windows else 0
                if end <= start or (windows and start < windows[-1].end_ms - overlap_allowed):
                    return None
                if windows and start < windows[-1].end_ms:
                    # The crossfade interval itself stays with the outgoing
                    # shot's window: the incoming shot's expectations are
                    # asserted from the moment it fully owns the timeline —
                    # EpisodeContinuityExpectations requires non-overlapping
                    # ordered windows.
                    start = windows[-1].end_ms
                    if end <= start:
                        # The clip lives entirely inside the crossfade and never
                        # fully owns the timeline: dropped evidence, never
                        # silently skipped.
                        return None
                outfit_by_character = {
                    a.character_id: a.outfit_id for a in assignments if a.scene_id == scene.scene_id
                }
                layout = _verified_doc(
                    tx, LocationLayout, key="location_id", value=scene.location_id
                )
                holder_by_prop: dict[str, str] = {}
                proof_sha: dict[str, str] = {}
                for prop_id in scene.prop_ids:
                    if layout is not None and prop_id in layout.prop_ownership:
                        holder_by_prop[prop_id] = layout.prop_ownership[prop_id]
                    sheet = _verified_doc(tx, PropSheet, key="prop_id", value=prop_id)
                    if sheet is not None and sheet.text_layer_sha256:
                        proof_sha[prop_id] = sheet.text_layer_sha256
                visible = frozenset(scene.visible_character_ids)
                speaking = frozenset()
                if script is not None:
                    speaking = frozenset(
                        line.speaker_character_id
                        for script_scene in script.scenes
                        if script_scene.scene_id == scene.scene_id
                        for line in script_scene.lines
                    )
                windows.append(
                    ExpectedContinuityWindow(
                        start_ms=start,
                        end_ms=end,
                        scene_id=scene.scene_id,
                        visible_character_ids=visible,
                        outfit_by_character=outfit_by_character,
                        holder_by_prop=holder_by_prop,
                        location_id=scene.location_id,
                        geometry_token=(layout.geometry_sha256 if layout is not None else ""),
                        eyeline=shot.eyeline,
                        action_handoff=shot.action_handoff,
                        proof_text_sha256_by_prop=proof_sha,
                        speaking_character_ids=speaking,
                        # the full cast voice map rides every window (the
                        # THAI_VOICE dimension applies where speakers exist)
                        voice_by_character=dict(voices),
                        expects_subtitles=style is not None,
                        shot_class=shot.framing,
                        shot_id=shot.shot_id,
                    )
                )
            if not windows:
                return None
            return EpisodeContinuityExpectations(episode_id=episode_id, windows=tuple(windows))


__all__ = ["V2RecordContinuityExpectations"]
