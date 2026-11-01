"""Fail-closed V2 semantic reference and rights preflight (T041b)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.registries import RightsRecord
from microdrama.contracts.v2 import (
    AssetSheet,
    DirectingManifest,
    EpisodePack,
    LocationLayout,
    PromptManifest,
    PropSheet,
    ReferenceRole,
    RightsGrant,
    SceneWardrobeAssignment,
    SecretLedger,
    ShotReferenceBinding,
    StyleBible,
    V2Record,
    WardrobeBible,
    validate_current_rights_grant,
    validate_directing_manifest,
    validate_wardrobe_assignment,
    verify_v2_record_hash,
)
from microdrama.references.v2_planning import (
    targeted_invalidation,
    validate_episode_reference_state,
)


@dataclass(frozen=True)
class ExpectedReference:
    asset_id: UUID
    asset_version: int
    asset_sha256: str
    rights: RightsGrant | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    source_hashes: tuple[str, ...] = ()


RightsResolver = Callable[[str, object, str], RightsRecord | None]
CurrentRecordCheck = Callable[[V2Record], None]


def resolve_shot_reference_expectations(
    episode_pack: EpisodePack,
    directing_manifest: DirectingManifest,
    *,
    secret_ledger: SecretLedger,
    shot_id: str,
    shot_prop_ids: Sequence[str],
    wardrobe_assignments: Sequence[SceneWardrobeAssignment],
    wardrobe_bibles: Sequence[WardrobeBible],
    style_bible: StyleBible,
    asset_sheets: Sequence[AssetSheet],
    prop_sheets: Sequence[PropSheet],
    location_layouts: Sequence[LocationLayout],
    state_events=(),
    explicit_frames: Sequence[ShotReferenceBinding] = (),
    required_frame_roles: frozenset[ReferenceRole] = frozenset(),
    style_subject_id: str,
    assert_current: CurrentRecordCheck | None = None,
) -> dict[tuple[ReferenceRole, str], ExpectedReference]:
    """Derive the exact role map from the approved pack, shot and current typed records."""
    verify_v2_record_hash(episode_pack)
    verify_v2_record_hash(secret_ledger)
    verify_v2_record_hash(style_bible)
    if assert_current is not None:
        for record in (episode_pack, directing_manifest, secret_ledger, style_bible):
            assert_current(record)
    if style_bible.season_id != episode_pack.season_id:
        raise SchemaInvalid("StyleBible belongs to a different season")
    validate_directing_manifest(directing_manifest, episode_pack, secret_ledger=secret_ledger)
    directed_events = [event for item in directing_manifest.shots for event in item.events]
    if state_events:
        provided_by_id = {event.record_id: event for event in state_events}
        for event in directed_events:
            provided = provided_by_id.get(event.record_id)
            if provided is not None and provided != event:
                raise SchemaInvalid("state event differs between directing and reference inputs")
        directed_events.extend(
            event for event in state_events if event.record_id not in provided_by_id
        )
    validate_episode_reference_state(episode_pack, prop_sheets, location_layouts, directed_events)
    shot = next((item for item in directing_manifest.shots if item.shot_id == shot_id), None)
    if shot is None:
        raise SchemaInvalid("directing manifest has no requested shot", shot_id=shot_id)
    scene = next((item for item in episode_pack.scenes if item.scene_id == shot.scene_id), None)
    beat = next(
        (
            beat
            for candidate in episode_pack.scenes
            for beat in candidate.beats
            if beat.beat_id == shot.beat_id
        ),
        None,
    )
    if scene is None or beat is None or scene.scene_id != shot.scene_id:
        raise SchemaInvalid("directing shot scene/beat does not resolve in approved pack")
    if not set(shot_prop_ids).issubset(set(scene.prop_ids)):
        raise SchemaInvalid("requested shot prop is unrelated to its episode scene")
    if not set(beat.proof_object_ids).issubset(set(shot_prop_ids)):
        raise SchemaInvalid("shot reference set omits an exact beat proof prop")
    if len(set(shot_prop_ids)) != len(shot_prop_ids):
        raise SchemaInvalid("duplicate requested shot prop")

    def one_sheet(role: str, subject: str) -> AssetSheet:
        found = [
            item for item in asset_sheets if item.asset_role == role and item.subject_id == subject
        ]
        if len(found) != 1:
            raise SchemaInvalid(
                "semantic asset sheet must resolve exactly once", role=role, subject=subject
            )
        item = found[0]
        verify_v2_record_hash(item)
        if assert_current is not None:
            assert_current(item)
        return item

    expected: dict[tuple[ReferenceRole, str], ExpectedReference] = {}
    for character_id in scene.visible_character_ids:
        identity = one_sheet("character_identity", character_id)
        expected[(ReferenceRole.CHARACTER_IDENTITY, character_id)] = ExpectedReference(
            identity.asset_id,
            identity.asset_version,
            identity.asset_sha256,
            identity.rights,
            max(identity.valid_from, identity.validity_from),
            min(filter(None, [identity.valid_until, identity.validity_until]), default=None),
            (identity.content_sha256, identity.asset_sha256),
        )
    assignments = [
        item
        for item in wardrobe_assignments
        if item.episode_id == episode_pack.episode_id and item.scene_id == scene.scene_id
    ]
    assignment_by_character = {item.character_id: item for item in assignments}
    if len(assignment_by_character) != len(assignments) or set(assignment_by_character) != set(
        scene.visible_character_ids
    ):
        raise SchemaInvalid("scene must have exactly one outfit assignment per visible character")
    bible_by_id = {item.record_id: item for item in wardrobe_bibles}
    if len(bible_by_id) != len(wardrobe_bibles):
        raise SchemaInvalid("duplicate WardrobeBible record ID in current reference set")
    for character_id in scene.visible_character_ids:
        assignment = assignment_by_character[character_id]
        if (assignment.story_day, assignment.setting) != (
            scene.story_time.story_day,
            scene.location_id,
        ):
            raise SchemaInvalid("wardrobe assignment day/setting differs from exact scene")
        bible = bible_by_id.get(assignment.wardrobe_bible_id)
        if bible is None:
            raise SchemaInvalid("wardrobe assignment has no current WardrobeBible")
        if assert_current is not None:
            assert_current(assignment)
            assert_current(bible)
        try:
            validate_wardrobe_assignment(assignment, bible)
        except ValueError as exc:
            raise SchemaInvalid("wardrobe assignment is stale or contradictory") from exc
        expected[(ReferenceRole.OUTFIT, character_id)] = ExpectedReference(
            assignment.asset_id,
            assignment.asset_version,
            assignment.asset_sha256,
            assignment.rights,
            assignment.valid_from,
            assignment.valid_until,
            (assignment.content_sha256, assignment.asset_sha256, bible.content_sha256),
        )
    location = one_sheet("location", scene.location_id)
    layout_matches = [item for item in location_layouts if item.location_id == scene.location_id]
    if len(layout_matches) != 1:
        raise SchemaInvalid("scene must resolve exactly one current LocationLayout")
    layout = layout_matches[0]
    verify_v2_record_hash(layout)
    if assert_current is not None:
        assert_current(layout)
    if location.rights != layout.rights:
        raise SchemaInvalid("location asset rights differ from its current LocationLayout")
    expected[(ReferenceRole.LOCATION, scene.location_id)] = ExpectedReference(
        location.asset_id,
        location.asset_version,
        location.asset_sha256,
        location.rights,
        max(location.valid_from, location.validity_from),
        min(filter(None, [location.valid_until, location.validity_until]), default=None),
        (location.content_sha256, location.asset_sha256, layout.content_sha256),
    )
    style = one_sheet("style", style_subject_id)
    if (style.asset_id, style.asset_sha256, style.rights) != (
        style_bible.moving_sample_asset_id,
        style_bible.moving_sample_sha256,
        style_bible.rights,
    ):
        raise SchemaInvalid("style sheet does not match the exact StyleBible moving sample")
    expected[(ReferenceRole.STYLE, style_subject_id)] = ExpectedReference(
        style.asset_id,
        style.asset_version,
        style.asset_sha256,
        style.rights,
        max(style.valid_from, style.validity_from),
        min(filter(None, [style.valid_until, style.validity_until]), default=None),
        (style.content_sha256, style.asset_sha256, style_bible.content_sha256),
    )
    props_by_id = {item.prop_id: item for item in prop_sheets}
    for prop_id in shot_prop_ids:
        prop = props_by_id.get(prop_id)
        if prop is None:
            raise SchemaInvalid("requested shot prop has no current PropSheet", prop_id=prop_id)
        verify_v2_record_hash(prop)
        if assert_current is not None:
            assert_current(prop)
        expected[(ReferenceRole.PROP, prop_id)] = ExpectedReference(
            prop.asset_id,
            prop.asset_version,
            prop.asset_sha256,
            prop.rights,
            prop.valid_from,
            min(filter(None, [prop.valid_until, prop.asset_valid_until]), default=None),
            (prop.content_sha256, prop.asset_sha256),
        )
    frame_roles = {
        ReferenceRole.FIRST_FRAME,
        ReferenceRole.LAST_FRAME,
        ReferenceRole.HANDOFF_FRAME,
    }
    if not required_frame_roles.issubset(frame_roles):
        raise SchemaInvalid("unsupported frame role requested")
    seen_frames: set[ReferenceRole] = set()
    for binding in explicit_frames:
        if (
            binding.role not in frame_roles
            or binding.role in seen_frames
            or binding.subject_id != shot_id
        ):
            raise SchemaInvalid("frame bindings must have unique explicit frame roles")
        if assert_current is not None:
            assert_current(binding)
        seen_frames.add(binding.role)
        expected[(binding.role, binding.subject_id)] = ExpectedReference(
            binding.asset_id,
            binding.asset_version,
            binding.asset_sha256,
            binding.rights,
            binding.valid_from,
            binding.valid_until,
            (binding.content_sha256, binding.asset_sha256),
        )
    if seen_frames != required_frame_roles:
        raise SchemaInvalid("explicit frame bindings do not satisfy required frame roles")
    return expected


def preflight_prompt_manifest(
    manifest: PromptManifest,
    *,
    expected: Mapping[tuple[ReferenceRole, str], ExpectedReference | tuple[UUID, int, str]],
    resolve_current_rights: RightsResolver,
    at: datetime,
    territories: list[str],
    forbidden_facts: tuple[str, ...] = (),
) -> tuple[ShotReferenceBinding, ...]:
    """Verify exact semantic bindings before any reservation/provider operation.

    ``expected`` is assembled from the current EpisodePack, scene wardrobe assignment,
    typed asset sheets and explicit frame assignment. It is keyed by role and subject;
    list order is never consulted.
    """
    verify_v2_record_hash(manifest)
    instant = at if at.tzinfo else at.replace(tzinfo=UTC)
    if manifest.valid_from > instant or (
        manifest.valid_until is not None and instant >= manifest.valid_until
    ):
        raise SchemaInvalid("PromptManifest is stale or not yet valid", shot_id=manifest.shot_id)
    if any(fact and fact.casefold() in manifest.prompt_text.casefold() for fact in forbidden_facts):
        raise SchemaInvalid("PromptManifest includes a forbidden unrevealed fact")

    actual: dict[tuple[ReferenceRole, str], ShotReferenceBinding] = {}
    for binding in manifest.bindings:
        key = (binding.role, binding.subject_id)
        if key in actual:
            raise SchemaInvalid(
                "duplicate semantic reference role/subject", role=key[0].value, subject=key[1]
            )
        actual[key] = binding
    if set(actual) != set(expected):
        raise SchemaInvalid(
            "PromptManifest semantic roles do not match current shot assignments",
            missing=sorted(f"{r.value}:{s}" for r, s in set(expected) - set(actual)),
            unrelated=sorted(f"{r.value}:{s}" for r, s in set(actual) - set(expected)),
        )

    for key, binding in actual.items():
        if not isinstance(binding, ShotReferenceBinding):
            raise SchemaInvalid("reference binding is not typed")
        item = expected[key]
        if isinstance(item, tuple):
            item = ExpectedReference(*item)
        if (binding.asset_id, binding.asset_version, binding.asset_sha256) != (
            item.asset_id,
            item.asset_version,
            item.asset_sha256,
        ):
            raise SchemaInvalid(
                "reference binding differs from exact current asset",
                role=key[0].value,
                subject=key[1],
            )
        if item.rights is not None and binding.rights != item.rights:
            raise SchemaInvalid("reference rights differ from exact typed source record")
        if item.valid_from is not None and item.valid_from > instant:
            raise SchemaInvalid("typed source asset is not yet valid", role=key[0].value)
        if item.valid_until is not None and instant >= item.valid_until:
            raise SchemaInvalid("typed source asset is retired", role=key[0].value)
        if not set(item.source_hashes).issubset(set(manifest.source_hashes)):
            raise SchemaInvalid(
                "PromptManifest omits exact typed source record hashes", role=key[0].value
            )
        if binding.valid_from > instant or (
            binding.valid_until is not None and instant >= binding.valid_until
        ):
            raise SchemaInvalid("reference binding is stale", role=key[0].value, subject=key[1])
        try:
            validate_current_rights_grant(
                binding.rights,
                resolve_current_rights,
                at=instant,
                territories=territories,
            )
        except (ValueError, TypeError) as exc:
            raise SchemaInvalid(
                "reference rights are not current and eligible",
                role=key[0].value,
                subject=key[1],
            ) from exc
    return tuple(actual[key] for key in sorted(actual, key=lambda item: (item[0].value, item[1])))


def dependent_shot_ids(
    source_sha256: str,
    shot_source_hashes: Mapping[str, set[str]],
) -> tuple[str, ...]:
    """Return only shots whose recorded source set includes a changed source."""
    return tuple(
        sorted(shot_id for shot_id, hashes in shot_source_hashes.items() if source_sha256 in hashes)
    )


def invalidated_artifact_ids(
    changed_source_sha256: str,
    *,
    dependency_ids_by_source_hash: Mapping[str, Sequence[str]],
    dependency_graph: Mapping[str, Sequence[str]],
) -> tuple[str, ...]:
    """Expand a changed source hash to only its transitive shot/derivative dependents."""
    roots = dependency_ids_by_source_hash.get(changed_source_sha256, ())
    return tuple(targeted_invalidation(roots, dependency_graph))


def compile_prompt_manifest(
    episode_pack: EpisodePack,
    directing_manifest: DirectingManifest,
    *,
    secret_ledger: SecretLedger,
    shot_id: str,
    expected: Mapping[tuple[ReferenceRole, str], ExpectedReference],
    resolve_current_rights: RightsResolver,
    at: datetime,
    territories: list[str],
    forbidden_facts: tuple[str, ...] = (),
) -> PromptManifest:
    """Compile a deterministic prompt manifest from an exact directed shot and references."""
    verify_v2_record_hash(episode_pack)
    verify_v2_record_hash(secret_ledger)
    validate_directing_manifest(directing_manifest, episode_pack, secret_ledger=secret_ledger)
    shot = next((item for item in directing_manifest.shots if item.shot_id == shot_id), None)
    if shot is None:
        raise SchemaInvalid("directing manifest has no requested shot", shot_id=shot_id)
    bindings: list[ShotReferenceBinding] = []
    for (role, subject), item in sorted(
        expected.items(), key=lambda pair: (pair[0][0].value, pair[0][1])
    ):
        if not isinstance(item, ExpectedReference) or item.rights is None:
            raise SchemaInvalid("prompt compilation requires source-typed rights for every role")
        bindings.append(
            ShotReferenceBinding.seal(
                record_id=uuid5(
                    NAMESPACE_URL,
                    f"t041b:{episode_pack.episode_id}:{shot_id}:{role.value}:{subject}:{item.asset_version}:{item.asset_sha256}",
                ),
                version=1,
                created_at=at,
                updated_at=at,
                valid_from=at,
                role=role,
                subject_id=subject,
                asset_id=item.asset_id,
                asset_version=item.asset_version,
                asset_sha256=item.asset_sha256,
                rights=item.rights,
                valid_until=item.valid_until,
            )
        )
    hashes = set(directing_manifest.source_hashes)
    for item in expected.values():
        hashes.update(item.source_hashes)
        hashes.add(item.asset_sha256)
    prompt_text = compose_prompt_text(episode_pack, directing_manifest, shot_id=shot_id)
    future_secret_facts = tuple(
        secret.fact
        for secret in secret_ledger.secrets
        if episode_pack.episode_number < secret.planned_reveal_episode
    )
    prompt = PromptManifest.seal(
        record_id=uuid5(
            NAMESPACE_URL,
            f"t041b-prompt:{episode_pack.episode_id}:{shot_id}:{directing_manifest.content_sha256}",
        ),
        version=1,
        created_at=at,
        updated_at=at,
        valid_from=at,
        episode_id=episode_pack.episode_id,
        shot_id=shot.shot_id,
        shot_sequence=shot.sequence,
        shot_duration_ms=shot.duration_ms,
        prompt_text=prompt_text,
        bindings=bindings,
        source_hashes=sorted(hashes | {secret_ledger.content_sha256}),
        downstream_invalidation_ids=[shot.shot_id],
    )
    preflight_prompt_manifest(
        prompt,
        expected=expected,
        resolve_current_rights=resolve_current_rights,
        at=at,
        territories=territories,
        forbidden_facts=(*forbidden_facts, *future_secret_facts),
    )
    return prompt


def compose_prompt_text(
    episode_pack: EpisodePack,
    directing_manifest: DirectingManifest,
    *,
    shot_id: str,
) -> str:
    """Build only from current approved beat, scene and directing intent fields."""
    shot = next((item for item in directing_manifest.shots if item.shot_id == shot_id), None)
    if shot is None:
        raise SchemaInvalid("directing manifest has no requested shot", shot_id=shot_id)
    scene = next((item for item in episode_pack.scenes if item.scene_id == shot.scene_id), None)
    beat = next(
        (
            item
            for candidate in episode_pack.scenes
            for item in candidate.beats
            if item.beat_id == shot.beat_id
        ),
        None,
    )
    if scene is None or beat is None:
        raise SchemaInvalid("directing shot cannot resolve its current scene and beat")
    state_lines = [
        f"{value.entity_id} {value.field}: {value.value}"
        for value in shot.state_in + shot.state_out
    ]
    event_lines = [
        f"{event.entity_id} {event.field}: {event.before} to {event.after}" for event in shot.events
    ]
    sections = [
        f"Visible action: {beat.visible_action}",
        f"Location: {scene.location_id} ({scene.story_time.setting}), story day "
        f"{scene.story_time.story_day} at {scene.story_time.local_time}.",
        f"Framing: {shot.framing}; screen axis: {shot.screen_axis}; "
        f"screen direction: {shot.screen_direction}.",
        f"Eyeline: {shot.eyeline}",
        f"Action handoff: {shot.action_handoff}",
        f"Sound intent: {shot.sound_intent}",
        f"Edit intent: {shot.edit_intent}",
    ]
    if state_lines:
        sections.append("State: " + "; ".join(state_lines))
    if event_lines:
        sections.append("State transitions: " + "; ".join(event_lines))
    return " ".join(sections)


__all__ = [
    "ExpectedReference",
    "RightsResolver",
    "compile_prompt_manifest",
    "compose_prompt_text",
    "dependent_shot_ids",
    "invalidated_artifact_ids",
    "preflight_prompt_manifest",
    "resolve_shot_reference_expectations",
]
