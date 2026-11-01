"""Frozen V2 creative, continuity, reference and progress payloads (T038).

These models are intentionally separate from the V1 runtime contracts. They use
UUID identities, exact versions, SHA-256 source hashes and explicit rights and
validity; production-kit labels/statuses are not imported as authority.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Literal
from uuid import UUID

from pydantic import Field, Strict, ValidationInfo, model_validator

from microdrama.contracts.enums import DisclosureKind, RightsSubjectKind
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.primitives import (
    ContractModel,
    Identifier,
    LongText,
    PositiveInt,
    Sha256Hex,
    ShortText,
    UtcDateTime,
    V2VersionedPayload,
)
from microdrama.contracts.registries import RightsRecord

if TYPE_CHECKING:
    from microdrama.contracts.release import PostMetadata

_V2_HASH_SEAL_TOKEN = object()
_RELEASE_MANIFEST_SEAL_TOKEN = object()


class RightsStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    UNKNOWN = "UNKNOWN"
    EXPIRED = "EXPIRED"


class V2Record(V2VersionedPayload):
    record_id: UUID
    version: PositiveInt
    content_sha256: Sha256Hex
    created_at: UtcDateTime
    updated_at: UtcDateTime
    valid_from: UtcDateTime
    valid_until: UtcDateTime | None = None

    @model_validator(mode="after")
    def _interval(self, info: ValidationInfo):
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be later than valid_from")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if (info.context or {}).get(
            "v2_hash_seal"
        ) is not _V2_HASH_SEAL_TOKEN and not self.content_hash_matches():
            raise ValueError("V2 content_sha256 does not match canonical record content")
        return self

    def calculated_content_sha256(self) -> str:
        """Canonical hash of this payload excluding its declared source hash."""
        return canonical_hash(self.model_dump(mode="python", exclude={"content_sha256"}))

    def content_hash_matches(self) -> bool:
        return self.content_sha256 == self.calculated_content_sha256()

    @classmethod
    def seal(cls, **fields: object):
        """Compute the canonical content hash and return a fully validated record."""
        fields.pop("content_sha256", None)
        draft = cls.model_validate(
            {**fields, "content_sha256": "0" * 64},
            context={"v2_hash_seal": _V2_HASH_SEAL_TOKEN},
        )
        fields["content_sha256"] = draft.calculated_content_sha256()
        return cls(**fields)


def verify_v2_record_hash(record: V2Record) -> None:
    """Fail a write/readback when a record's declared canonical hash is stale."""
    if not record.content_hash_matches():
        raise ValueError("V2 content_sha256 does not match canonical record content")


class RightsGrant(ContractModel):
    rights_route_id: Identifier
    subject_kind: RightsSubjectKind
    subject_ref: ShortText
    rights_version: PositiveInt
    status: RightsStatus
    territories: list[Annotated[str, Field(pattern=r"^[A-Z]{2}$")]] = Field(min_length=1)
    commercial_use: bool
    output_release_allowed: bool
    expires_at: UtcDateTime | None = None
    evidence_sha256: list[Sha256Hex] = Field(min_length=1)

    @model_validator(mode="after")
    def _eligible(self):
        if self.status is not RightsStatus.ELIGIBLE:
            raise ValueError("V2 production payloads require ELIGIBLE rights")
        if not self.commercial_use or not self.output_release_allowed:
            raise ValueError("rights do not permit commercial output release")
        return self


class PendingRightsAssessment(ContractModel):
    """Candidate-stage rights status when eligibility has not been established."""

    status: Literal["PENDING", "UNKNOWN"]
    note: ShortText = Field(
        description="Known limitation or unresolved question; this is not production rights evidence"
    )


def _ensure_rights_current(rights: RightsGrant, instant: UtcDateTime, label: str) -> None:
    if rights.expires_at is not None and instant >= rights.expires_at:
        raise ValueError(f"{label} rights have expired")


def validate_current_rights_grant(
    grant: RightsGrant,
    resolve_current: Callable[[str, RightsSubjectKind, str], RightsRecord | None],
    *,
    at: UtcDateTime,
    territories: list[str],
) -> RightsRecord:
    """Resolve a grant against the live registry immediately before dispatch.

    Payload validation cannot establish currentness: callers must supply the authoritative
    registry resolver at the dispatch boundary. Missing, superseded, mismatched, revoked,
    uncovered, or expired records fail closed.
    """
    row = resolve_current(grant.rights_route_id, grant.subject_kind, grant.subject_ref)
    if row is None:
        raise ValueError("no current rights registry record for grant subject")
    if (
        row.rights_route_id != grant.rights_route_id
        or row.subject_kind is not grant.subject_kind
        or row.subject_ref != grant.subject_ref
        or row.version != grant.rights_version
    ):
        raise ValueError("rights grant does not match the exact current registry subject/version")
    if row.status.value != "ELIGIBLE":
        raise ValueError("current rights registry record is not eligible")
    if not row.commercial_use or not row.output_release_allowed:
        raise ValueError("current rights registry record does not permit commercial output release")
    if row.expires_at is not None and at >= row.expires_at:
        raise ValueError("current rights registry record has expired")
    if not all(
        "WORLDWIDE" in row.territories or territory in row.territories for territory in territories
    ):
        raise ValueError("current rights registry record does not cover requested territories")
    if "WORLDWIDE" not in row.territories and set(grant.territories) != set(row.territories):
        raise ValueError("rights grant territories differ from the current registry record")
    if row.expires_at != grant.expires_at:
        raise ValueError("rights grant expiry differs from the current registry record")
    return row


class ConceptIntake(V2Record):
    story_idea: LongText
    genre_tags: list[Identifier] = Field(min_length=1)
    tone: ShortText
    requested_episode_count: Annotated[int, Strict(), Field(ge=1, le=10)] = 10
    language: Literal["th"] = "th"
    original_fiction: Literal[True] = True


class ConceptCandidate(V2Record):
    intake_id: UUID
    title_th: ShortText
    title_en: ShortText
    logline: LongText
    promise: LongText
    payoff_debt: list[LongText] = Field(min_length=1)
    escalation: list[LongText] = Field(min_length=1)
    episode_count: Annotated[int, Strict(), Field(ge=1, le=10)]
    scope_sha256: Sha256Hex
    rights: RightsGrant | PendingRightsAssessment = Field(
        description="Candidate assessment may be pending/unknown; production bindings require RightsGrant"
    )


class CharacterLogic(V2Record):
    character_id: Identifier
    season_id: UUID | None = None
    observable_goal: LongText
    strategy: LongText
    flaw: LongText
    secret_id: Identifier | None = None
    relationship_pressures: list[ShortText] = Field(default_factory=list)
    knowledge_by_episode: dict[Identifier, list[Identifier]] = Field(default_factory=dict)


class SecretLedger(V2Record):
    season_id: UUID
    secrets: list[SecretEntry] = Field(min_length=1)


class PayoffDebt(ContractModel):
    debt_id: Identifier
    description: LongText
    due_episode: PositiveInt
    status: Literal["OPEN", "PAID_OFF"] = "OPEN"


class SeasonEscalation(ContractModel):
    episode_number: PositiveInt
    description: LongText


class SeasonStoryLedger(V2Record):
    season_id: UUID
    approved_scope_hash: Sha256Hex
    promise: LongText
    payoff_debts: list[PayoffDebt] = Field(min_length=1)
    escalations: list[SeasonEscalation] = Field(min_length=1)
    character_logic_record_ids: list[UUID] = Field(min_length=1)
    secret_ledger_id: UUID

    @model_validator(mode="after")
    def _ordered_episode_entries(self):
        if len({debt.debt_id for debt in self.payoff_debts}) != len(self.payoff_debts):
            raise ValueError("duplicate payoff debt id")
        due_episodes = [debt.due_episode for debt in self.payoff_debts]
        if due_episodes != sorted(due_episodes):
            raise ValueError("payoff debts must be ordered by due episode")
        escalation_episodes = [item.episode_number for item in self.escalations]
        if escalation_episodes != sorted(set(escalation_episodes)):
            raise ValueError("escalations must have unique ascending episode numbers")
        if len(set(self.character_logic_record_ids)) != len(self.character_logic_record_ids):
            raise ValueError("duplicate character logic record id")
        return self


def validate_season_story_ledger(
    ledger: SeasonStoryLedger,
    character_logic: list[CharacterLogic],
    secret_ledger: SecretLedger,
    *,
    approved_scope_hash: str,
    episode_count: PositiveInt,
) -> None:
    """Bind ledger references to the exact approved season and its episode bounds."""
    if type(episode_count) is not int or episode_count < 1:
        raise ValueError("approved episode count must be a positive integer")
    verify_v2_record_hash(ledger)
    verify_v2_record_hash(secret_ledger)
    if ledger.approved_scope_hash != approved_scope_hash:
        raise ValueError("season story ledger is bound to a different approved scope")
    if secret_ledger.record_id != ledger.secret_ledger_id:
        raise ValueError("season story ledger references a different secret ledger")
    if secret_ledger.season_id != ledger.season_id:
        raise ValueError("secret ledger belongs to a different season")
    for record in character_logic:
        verify_v2_record_hash(record)
    character_records = {record.record_id: record for record in character_logic}
    if len(character_records) != len(character_logic):
        raise ValueError("duplicate character logic record")
    if set(character_records) != set(ledger.character_logic_record_ids):
        raise ValueError("season story ledger character logic references do not resolve exactly")
    if any(record.season_id != ledger.season_id for record in character_records.values()):
        raise ValueError("character logic belongs to a different or unbound season")
    if any(debt.due_episode > episode_count for debt in ledger.payoff_debts):
        raise ValueError("payoff debt due episode exceeds approved season episode count")
    if any(item.episode_number > episode_count for item in ledger.escalations):
        raise ValueError("escalation episode exceeds approved season episode count")


class SecretEntry(ContractModel):
    secret_id: Identifier
    held_by_character_id: Identifier
    fact: LongText
    planned_reveal_episode: PositiveInt
    known_by_character_ids: list[Identifier] = Field(default_factory=list)


class StoryTime(V2Record):
    story_day: PositiveInt
    local_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    setting: ShortText
    timezone: str = "Asia/Bangkok"


class StateValue(ContractModel):
    entity_id: Identifier
    field: Identifier
    value: str | int | bool | None


class PackBeat(ContractModel):
    beat_id: Identifier
    function: ShortText
    visible_action: LongText
    proof_object_ids: list[Identifier] = Field(default_factory=list)
    dependency_beat_ids: list[Identifier] = Field(default_factory=list)
    state_in: list[StateValue] = Field(default_factory=list)
    state_out: list[StateValue] = Field(default_factory=list)
    required_asset_ids: list[UUID] = Field(default_factory=list)
    reveal_ids: list[Identifier] = Field(default_factory=list)


class EpisodeScene(ContractModel):
    scene_id: Identifier
    scene_number: PositiveInt
    story_time: StoryTime
    location_id: Identifier
    visible_character_ids: list[Identifier] = Field(min_length=1)
    prop_ids: list[Identifier] = Field(default_factory=list)
    dependency_scene_ids: list[Identifier] = Field(default_factory=list)
    wardrobe_assignment_ids: list[UUID] = Field(default_factory=list)
    beats: list[PackBeat] = Field(min_length=1)
    state_in: list[StateValue] = Field(default_factory=list)
    state_out: list[StateValue] = Field(default_factory=list)


def _validate_dependency_graph(graph: dict[str, list[str]], label: str) -> None:
    nodes = set(graph)
    for node, dependencies in graph.items():
        if len(dependencies) != len(set(dependencies)):
            raise ValueError(f"duplicate {label} dependency")
        if node in dependencies:
            raise ValueError(f"{label} cannot depend on itself")
        if unknown := set(dependencies) - nodes:
            raise ValueError(
                f"{label} dependencies must resolve inside this pack: {sorted(unknown)}"
            )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ValueError(f"cyclic {label} dependencies")
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)


class EpisodePack(V2Record):
    episode_id: UUID
    season_id: UUID
    approved_scope_hash: Sha256Hex
    episode_number: PositiveInt
    duration_target_ms: Annotated[int, Strict(), Field(ge=180_000, le=300_000)]
    character_logic: list[CharacterLogic] = Field(min_length=1)
    promise: LongText
    payoff_debt: list[LongText] = Field(default_factory=list)
    escalation: LongText
    scenes: list[EpisodeScene] = Field(min_length=1)
    scoped_map_only: bool = False

    @model_validator(mode="after")
    def _coherent(self):
        if len({s.scene_id for s in self.scenes}) != len(self.scenes):
            raise ValueError("duplicate scene_id")
        if len({c.character_id for c in self.character_logic}) != len(self.character_logic):
            raise ValueError("duplicate character logic")
        scene_dependencies = {scene.scene_id: scene.dependency_scene_ids for scene in self.scenes}
        _validate_dependency_graph(scene_dependencies, "scene")
        beat_dependencies: dict[str, list[str]] = {}
        all_beat_ids = [beat.beat_id for scene in self.scenes for beat in scene.beats]
        if len(set(all_beat_ids)) != len(all_beat_ids):
            raise ValueError("duplicate beat_id")
        for scene in self.scenes:
            prop_ids = set(scene.prop_ids)
            for beat in scene.beats:
                unknown_proofs = set(beat.proof_object_ids) - prop_ids
                if unknown_proofs:
                    raise ValueError(
                        "proof_object_ids must reference props in the containing scene"
                    )
                beat_dependencies[beat.beat_id] = beat.dependency_beat_ids
            keys = [(x.entity_id, x.field) for x in scene.state_in]
            if len(keys) != len(set(keys)):
                raise ValueError("contradictory duplicate state_in")
            keys = [(x.entity_id, x.field) for x in scene.state_out]
            if len(keys) != len(set(keys)):
                raise ValueError("contradictory duplicate state_out")
        _validate_dependency_graph(beat_dependencies, "beat")
        return self


class WardrobeBible(V2Record):
    season_id: UUID
    character_id: Identifier
    outfits: list[OutfitDefinition] = Field(min_length=1)


class OutfitDefinition(ContractModel):
    outfit_id: Identifier
    version: PositiveInt
    asset_id: UUID
    asset_version: PositiveInt
    asset_sha256: Sha256Hex
    story_day_from: PositiveInt
    story_day_until: PositiveInt | None = None
    setting_tags: list[Identifier] = Field(min_length=1)
    rights: RightsGrant

    @model_validator(mode="after")
    def _days(self):
        if self.story_day_until is not None and self.story_day_until < self.story_day_from:
            raise ValueError("outfit validity ends before it starts")
        return self


class SceneWardrobeAssignment(V2Record):
    episode_id: UUID
    scene_id: Identifier
    character_id: Identifier
    story_day: PositiveInt
    setting: Identifier
    wardrobe_bible_id: UUID
    wardrobe_bible_version: PositiveInt
    outfit_id: Identifier
    outfit_version: PositiveInt
    asset_id: UUID
    asset_version: PositiveInt
    asset_sha256: Sha256Hex
    reuse_reason: ShortText | None = None
    rights: RightsGrant


class StateEvent(V2Record):
    episode_id: UUID
    sequence: PositiveInt
    entity_id: Identifier
    field: Identifier
    before: str | int | bool | None
    after: str | int | bool | None
    scene_id: Identifier
    effective_from_ms: Annotated[int, Strict(), Field(ge=0)]
    effective_until_ms: Annotated[int, Strict(), Field(gt=0)]
    evidence_sha256: Sha256Hex

    @model_validator(mode="after")
    def _state_interval(self):
        if self.effective_until_ms <= self.effective_from_ms:
            raise ValueError("state event interval must be non-empty")
        if self.before == self.after:
            raise ValueError("state event must change state")
        return self


class DirectingShot(ContractModel):
    shot_id: Identifier
    scene_id: Identifier
    beat_id: Identifier
    sequence: PositiveInt
    duration_ms: Annotated[int, Strict(), Field(gt=0, le=15_000)]
    section_id: Identifier
    state_in: list[StateValue] = Field(default_factory=list)
    events: list[StateEvent] = Field(default_factory=list)
    state_out: list[StateValue] = Field(default_factory=list)
    screen_axis: Identifier
    screen_direction: Literal["STATIC", "LEFT_TO_RIGHT", "RIGHT_TO_LEFT"]
    eyeline: LongText
    action_handoff: LongText
    sound_intent: LongText
    edit_intent: LongText
    framing: Identifier
    source_dependency_ids: list[Identifier] = Field(min_length=1)
    source_hashes: list[Sha256Hex] = Field(min_length=1)

    @model_validator(mode="after")
    def _state_and_sources(self):
        if len(set(self.source_dependency_ids)) != len(self.source_dependency_ids):
            raise ValueError("duplicate directing source dependency ID")
        if len(set(self.source_hashes)) != len(self.source_hashes):
            raise ValueError("duplicate directing source hash")
        for values, label in ((self.state_in, "input"), (self.state_out, "output")):
            keys = [(item.entity_id, item.field) for item in values]
            if len(set(keys)) != len(keys):
                raise ValueError(f"contradictory duplicate directing state {label}")
        if len({event.record_id for event in self.events}) != len(self.events):
            raise ValueError("duplicate directing state event")
        events = sorted(self.events, key=lambda event: (event.effective_from_ms, event.sequence))
        state = {(item.entity_id, item.field): item.value for item in self.state_in}
        for event in events:
            key = (event.entity_id, event.field)
            if key in state and state[key] != event.before:
                raise ValueError("directing state event contradicts shot state-in")
            state[key] = event.after
        for value in self.state_out:
            key = (value.entity_id, value.field)
            if key in state and state[key] != value.value:
                raise ValueError("directing state-out contradicts shot events")
        return self


class DirectingSection(ContractModel):
    section_id: Identifier
    sequence: PositiveInt
    shot_ids: list[Identifier] = Field(min_length=1)
    duration_ms: Annotated[int, Strict(), Field(gt=0, le=45_000)]


class DirectingManifest(V2Record):
    episode_id: UUID
    pack_id: UUID
    pack_version: PositiveInt
    pack_hash: Sha256Hex
    approved_scope_hash: Sha256Hex
    shots: list[DirectingShot] = Field(min_length=1)
    sections: list[DirectingSection] = Field(min_length=1)
    source_hashes: list[Sha256Hex] = Field(min_length=1)

    @model_validator(mode="after")
    def _coherent(self):
        shot_ids = [shot.shot_id for shot in self.shots]
        section_ids = [section.section_id for section in self.sections]
        if len(set(shot_ids)) != len(shot_ids):
            raise ValueError("duplicate directing shot ID")
        if len(set(section_ids)) != len(section_ids):
            raise ValueError("duplicate directing section ID")
        if [shot.sequence for shot in self.shots] != list(range(1, len(self.shots) + 1)):
            raise ValueError("directing shot sequences must be ordered and contiguous")
        if [section.sequence for section in self.sections] != list(
            range(1, len(self.sections) + 1)
        ):
            raise ValueError("directing section sequences must be ordered and contiguous")
        if len(set(self.source_hashes)) != len(self.source_hashes):
            raise ValueError("duplicate directing manifest source hash")
        if self.pack_hash not in self.source_hashes:
            raise ValueError("directing manifest source hashes must include the episode pack")
        if (
            not set()
            .union(*(set(shot.source_hashes) for shot in self.shots))
            .issubset(set(self.source_hashes))
        ):
            raise ValueError("shot source hashes must be included in manifest source hashes")
        by_id = {shot.shot_id: shot for shot in self.shots}
        assigned: list[str] = []
        event_ids: set[UUID] = set()
        for section in self.sections:
            if len(set(section.shot_ids)) != len(section.shot_ids):
                raise ValueError("duplicate shot ID within directing section")
            if any(shot_id not in by_id for shot_id in section.shot_ids):
                raise ValueError("directing section references an unknown shot")
            section_shots = [by_id[shot_id] for shot_id in section.shot_ids]
            if any(shot.section_id != section.section_id for shot in section_shots):
                raise ValueError("directing shot section membership does not match section")
            if [shot.sequence for shot in section_shots] != sorted(
                shot.sequence for shot in section_shots
            ):
                raise ValueError("shots within a directing section must be ordered")
            if sum(shot.duration_ms for shot in section_shots) != section.duration_ms:
                raise ValueError("directing section duration must equal its shot durations")
            assigned.extend(section.shot_ids)
        if len(assigned) != len(set(assigned)) or set(assigned) != set(shot_ids):
            raise ValueError("each directing shot must belong to exactly one section")
        for shot in self.shots:
            for event in shot.events:
                if event.episode_id != self.episode_id or event.scene_id != shot.scene_id:
                    raise ValueError("directing state event episode/scene does not match its shot")
                if event.record_id in event_ids:
                    raise ValueError("state event is assigned to multiple directing shots")
                event_ids.add(event.record_id)
        return self

    @property
    def manifest_hash(self) -> str:
        """Compatibility alias for consumers that call the canonical hash a manifest hash."""
        return self.content_sha256


def validate_directing_manifest(
    manifest: DirectingManifest,
    episode_pack: EpisodePack,
    *,
    secret_ledger: SecretLedger | None = None,
) -> None:
    """Validate a directing output against its exact approved episode-pack input."""
    verify_v2_record_hash(manifest)
    verify_v2_record_hash(episode_pack)
    if (
        manifest.episode_id != episode_pack.episode_id
        or manifest.pack_id != episode_pack.record_id
        or manifest.pack_version != episode_pack.version
        or manifest.pack_hash != episode_pack.content_sha256
        or manifest.approved_scope_hash != episode_pack.approved_scope_hash
    ):
        raise ValueError("directing manifest does not bind the exact approved EpisodePack")
    scenes = {scene.scene_id: scene for scene in episode_pack.scenes}
    beats = {beat.beat_id: (scene, beat) for scene in episode_pack.scenes for beat in scene.beats}
    known_entities = {logic.character_id for logic in episode_pack.character_logic}
    known_entities.update(scene.location_id for scene in episode_pack.scenes)
    known_entities.update(prop for scene in episode_pack.scenes for prop in scene.prop_ids)
    for scene in episode_pack.scenes:
        known_entities.update(value.entity_id for value in scene.state_in + scene.state_out)
        for beat in scene.beats:
            known_entities.update(value.entity_id for value in beat.state_in + beat.state_out)
    if secret_ledger is not None:
        verify_v2_record_hash(secret_ledger)
        if secret_ledger.season_id != episode_pack.season_id:
            raise ValueError("directing secret ledger belongs to a different season")
        secret_entries = {item.secret_id: item for item in secret_ledger.secrets}
    else:
        secret_entries = {}
    for shot in manifest.shots:
        scene = scenes.get(shot.scene_id)
        beat_ref = beats.get(shot.beat_id)
        if scene is None or beat_ref is None or beat_ref[0].scene_id != shot.scene_id:
            raise ValueError("directing shot scene/beat does not resolve in its EpisodePack")
        required_dependencies = {episode_pack.record_id.hex, shot.scene_id, shot.beat_id}
        if not required_dependencies.issubset(set(shot.source_dependency_ids)):
            raise ValueError("directing shot source dependency IDs omit pack, scene or beat")
        required_hashes = {
            canonical_hash(scene.model_copy(update={"beats": []})),
            canonical_hash(beat_ref[1]),
            *(event.content_sha256 for event in shot.events),
        }
        if not required_hashes.issubset(set(shot.source_hashes)):
            raise ValueError("directing shot source hashes omit pack, scene, beat or event inputs")
        for value in shot.state_in + shot.state_out:
            if value.entity_id not in known_entities:
                raise ValueError("directing state references an unknown EpisodePack entity")
        for event in shot.events:
            verify_v2_record_hash(event)
            if event.entity_id not in known_entities:
                raise ValueError("directing state event references an unknown EpisodePack entity")
        if secret_ledger is not None:
            for reveal_id in beat_ref[1].reveal_ids:
                secret = secret_entries.get(reveal_id)
                if secret is None or episode_pack.episode_number < secret.planned_reveal_episode:
                    raise ValueError("directing beat exposes an unknown or future secret")
            for secret in secret_ledger.secrets:
                known = any(
                    secret.secret_id
                    in logic.knowledge_by_episode.get(str(episode_pack.episode_number), [])
                    for logic in episode_pack.character_logic
                )
                if (
                    episode_pack.episode_number < secret.planned_reveal_episode
                    and not known
                    and secret.fact.casefold()
                    and secret.fact.casefold() in beat_ref[1].visible_action.casefold()
                ):
                    raise ValueError("directing beat repeats a future secret fact")


class AssetSheet(V2Record):
    asset_role: Literal["character_identity", "outfit", "prop", "location", "style", "voice"]
    subject_id: Identifier
    asset_id: UUID
    asset_version: PositiveInt
    asset_sha256: Sha256Hex
    view_name: Identifier
    rights: RightsGrant
    validity_from: UtcDateTime
    validity_until: UtcDateTime | None = None

    @model_validator(mode="after")
    def _validity(self):
        if self.validity_until is not None and self.validity_until <= self.validity_from:
            raise ValueError("asset validity interval must be non-empty")
        if (
            self.valid_until is not None
            and self.validity_until is not None
            and self.valid_until > self.validity_until
        ):
            raise ValueError("record validity cannot outlive asset validity")
        _ensure_rights_current(self.rights, self.validity_from, "asset")
        return self


class PropSheet(V2Record):
    prop_id: Identifier
    purpose: LongText
    visual_anchor: LongText
    owner_character_id: Identifier | None = None
    dimensions: ShortText
    known_states: list[Identifier] = Field(min_length=1)
    text_layer_sha256: Sha256Hex | None = None
    asset_id: UUID
    asset_version: PositiveInt
    asset_sha256: Sha256Hex
    rights: RightsGrant
    asset_valid_until: UtcDateTime | None = None

    @model_validator(mode="after")
    def _validity(self):
        if self.asset_valid_until is not None and self.asset_valid_until <= self.valid_from:
            raise ValueError("prop sheet asset is expired at record validity start")
        _ensure_rights_current(self.rights, self.valid_from, "prop")
        return self


class StyleBible(V2Record):
    season_id: UUID
    medium: ShortText
    realism: ShortText
    palette: list[ShortText] = Field(min_length=2)
    lighting_language: LongText
    lens_and_movement: LongText
    material_rules: list[ShortText] = Field(min_length=1)
    typography_rules: list[ShortText] = Field(min_length=1)
    subtitle_safe_top_bp: Annotated[int, Strict(), Field(ge=0, le=4000)]
    subtitle_safe_bottom_bp: Annotated[int, Strict(), Field(ge=0, le=4000)]
    sound_motifs: list[ShortText] = Field(min_length=1)
    exclusions: list[ShortText] = Field(min_length=1)
    moving_sample_asset_id: UUID
    moving_sample_sha256: Sha256Hex
    rights: RightsGrant

    @model_validator(mode="after")
    def _safe_area(self):
        if self.subtitle_safe_top_bp + self.subtitle_safe_bottom_bp >= 8000:
            raise ValueError("subtitle-safe margins leave no usable picture area")
        _ensure_rights_current(self.rights, self.valid_from, "style")
        return self


class LocationLayout(V2Record):
    location_id: Identifier
    geometry_sha256: Sha256Hex
    entrance_ids: list[Identifier] = Field(min_length=1)
    camera_zones: list[Identifier] = Field(min_length=1)
    light_states: list[Identifier] = Field(min_length=1)
    prop_ownership: dict[Identifier, Identifier] = Field(default_factory=dict)
    rights: RightsGrant

    @model_validator(mode="after")
    def _rights_validity(self):
        _ensure_rights_current(self.rights, self.valid_from, "location")
        return self


class ReferenceRole(StrEnum):
    CHARACTER_IDENTITY = "character_identity"
    OUTFIT = "outfit"
    LOCATION = "location"
    PROP = "prop"
    STYLE = "style"
    FIRST_FRAME = "first_frame"
    LAST_FRAME = "last_frame"
    HANDOFF_FRAME = "handoff_frame"


class ShotReferenceBinding(V2Record):
    role: ReferenceRole
    subject_id: Identifier
    asset_id: UUID
    asset_version: PositiveInt
    asset_sha256: Sha256Hex
    rights: RightsGrant
    valid_from: UtcDateTime
    valid_until: UtcDateTime | None = None

    @model_validator(mode="after")
    def _validity(self):
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("reference validity interval must be non-empty")
        if self.rights.expires_at is not None and self.rights.expires_at <= self.valid_from:
            raise ValueError("reference rights are expired at binding start")
        return self


class PromptManifest(V2Record):
    episode_id: UUID
    shot_id: Identifier
    shot_sequence: PositiveInt
    shot_duration_ms: Annotated[int, Strict(), Field(gt=0, le=15_000)]
    prompt_text: LongText
    bindings: list[ShotReferenceBinding] = Field(min_length=1)
    source_hashes: list[Sha256Hex] = Field(min_length=1)
    downstream_invalidation_ids: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def _bindings(self):
        roles: dict[tuple[ReferenceRole, str], ShotReferenceBinding] = {}
        for binding in self.bindings:
            key = (binding.role, binding.subject_id)
            old = roles.get(key)
            if old is not None and (old.asset_id, old.asset_version, old.asset_sha256) != (
                binding.asset_id,
                binding.asset_version,
                binding.asset_sha256,
            ):
                raise ValueError("conflicting references for the same semantic role and subject")
            roles[key] = binding
            if binding.rights.status is not RightsStatus.ELIGIBLE:
                raise ValueError("non-eligible reference rights block dispatch")
            if binding.valid_from > self.valid_from or (
                binding.valid_until is not None and self.valid_from >= binding.valid_until
            ):
                raise ValueError("reference is stale or not yet valid for this prompt")
            if (
                binding.rights.expires_at is not None
                and self.valid_from >= binding.rights.expires_at
            ):
                raise ValueError("reference rights have expired for this prompt")
        if not any(b.role is ReferenceRole.CHARACTER_IDENTITY for b in self.bindings):
            raise ValueError("visible character identity binding is required")
        if not any(b.role is ReferenceRole.OUTFIT for b in self.bindings):
            raise ValueError("assigned outfit binding is required")
        if not any(b.role is ReferenceRole.LOCATION for b in self.bindings):
            raise ValueError("location binding is required")
        return self


class ApprovedMetadataPolicy(ContractModel):
    policy_id: Identifier
    version: PositiveInt
    policy_sha256: Sha256Hex
    mutable_fields: list[Literal["title", "caption", "description", "hashtags", "cover", "cta"]] = (
        Field(default_factory=list)
    )
    cooldown_hours: Annotated[int, Strict(), Field(ge=24)] = 24
    max_substantive_edits_first_7_days: Annotated[int, Strict(), Field(ge=0, le=2)] = 2
    allow_unapproved_content_changes: Literal[False] = False

    @model_validator(mode="after")
    def _policy_hash(self):
        if self.policy_sha256 != self.compute_policy_hash():
            raise ValueError("metadata policy hash does not match policy content")
        return self

    def compute_policy_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="python", exclude={"policy_sha256"}))

    @classmethod
    def seal(cls, **fields: object) -> ApprovedMetadataPolicy:
        fields.pop("policy_sha256", None)
        probe = cls.model_construct(**fields, policy_sha256="0" * 64)
        return cls(**fields, policy_sha256=probe.compute_policy_hash())


class ApprovedSlotMetadata(V2Record):
    release_package_id: UUID
    release_package_hash: Sha256Hex
    slot_id: Identifier
    metadata_id: UUID
    metadata_version: PositiveInt
    locale: str = Field(pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$")
    title: ShortText
    caption: str = Field(default="", max_length=5000)
    description: str = Field(default="", max_length=5000)
    hashtags: list[ShortText] = Field(default_factory=list, max_length=30)
    links: list[ShortText] = Field(default_factory=list)
    disclosures: list[DisclosureKind] = Field(default_factory=list)
    catalog_version: PositiveInt | None = None
    cover_asset_id: UUID | None = None
    cover_asset_version: PositiveInt | None = None
    cover_asset_sha256: Sha256Hex | None = None
    cover_rights: RightsGrant | None = None
    cta_text: ShortText | None = None
    metadata_policy_id: Identifier
    metadata_policy_version: PositiveInt
    metadata_policy_sha256: Sha256Hex
    source: Literal["OWNER_APPROVED", "OFFLINE_MOCK", "EXAMPLE"]

    @model_validator(mode="after")
    def _cover_and_rights(self):
        cover_fields = (self.cover_asset_id, self.cover_asset_version, self.cover_asset_sha256)
        if any(value is not None for value in cover_fields) and any(
            value is None for value in cover_fields
        ):
            raise ValueError("cover binding needs exact asset id, version and hash")
        if self.cover_asset_id is not None and self.cover_rights is None:
            raise ValueError("cover asset needs eligible rights")
        if self.cover_rights is not None:
            _ensure_rights_current(self.cover_rights, self.valid_from, "cover")
        return self


class ReleaseApprovalManifest(V2VersionedPayload):
    """V2 Gate-2 binding for immutable slot metadata, policy and V1 media package."""

    manifest_id: UUID
    version: PositiveInt
    created_at: UtcDateTime
    release_package_id: UUID
    release_package_hash: Sha256Hex
    metadata_policy: ApprovedMetadataPolicy
    slots: list[ApprovedSlotMetadata] = Field(min_length=1)
    approval_manifest_sha256: Sha256Hex

    @model_validator(mode="after")
    def _approval_hash(self, info: ValidationInfo):
        if len({slot.slot_id for slot in self.slots}) != len(self.slots):
            raise ValueError("duplicate metadata slot")
        for slot in self.slots:
            if (slot.release_package_id, slot.release_package_hash) != (
                self.release_package_id,
                self.release_package_hash,
            ):
                raise ValueError("slot metadata is bound to a different release package")
            if (
                slot.metadata_policy_id,
                slot.metadata_policy_version,
                slot.metadata_policy_sha256,
            ) != (
                self.metadata_policy.policy_id,
                self.metadata_policy.version,
                self.metadata_policy.policy_sha256,
            ):
                raise ValueError("slot metadata is bound to a different metadata policy")
        if (info.context or {}).get(
            "release_manifest_seal"
        ) is not _RELEASE_MANIFEST_SEAL_TOKEN and (
            self.approval_manifest_sha256 != self.compute_approval_hash()
        ):
            raise ValueError("approval manifest hash does not cover its exact slots and policy")
        return self

    def compute_approval_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="python", exclude={"approval_manifest_sha256"}))

    @classmethod
    def seal(cls, **fields: object) -> ReleaseApprovalManifest:
        fields.pop("approval_manifest_sha256", None)
        draft = cls.model_validate(
            {**fields, "approval_manifest_sha256": "0" * 64},
            context={"release_manifest_seal": _RELEASE_MANIFEST_SEAL_TOKEN},
        )
        fields["approval_manifest_sha256"] = draft.compute_approval_hash()
        return cls(**fields)

    @property
    def gate2_package_hash(self) -> str:
        """Hash value the Gate-2 event must bind when this manifest is in force."""
        return self.approval_manifest_sha256


def validate_live_release_metadata(
    manifest: ReleaseApprovalManifest,
    *,
    slot_id: str,
    metadata_id: UUID,
    metadata_version: int,
    metadata_sha256: str,
    metadata_projection: PostMetadata,
) -> ApprovedSlotMetadata:
    """Fail closed unless a live submit exactly matches the Gate-2 manifest.

    ``metadata_sha256`` is the persisted ``ApprovedSlotMetadata.content_sha256``:
    canonical JSON of that typed record with only its own hash field excluded.
    It is not ``model_hash()`` and not a hash of an unversioned PostMetadata row.
    """
    if manifest.compute_approval_hash() != manifest.approval_manifest_sha256:
        raise ValueError("Gate-2 approval manifest hash is stale")
    if manifest.metadata_policy.compute_policy_hash() != manifest.metadata_policy.policy_sha256:
        raise ValueError("Gate-2 metadata policy hash is stale")
    for item in manifest.slots:
        verify_v2_record_hash(item)
    approved = next((item for item in manifest.slots if item.slot_id == slot_id), None)
    if approved is None:
        raise ValueError("slot is not in the Gate-2 approval manifest")
    if approved.source != "OWNER_APPROVED":
        raise ValueError("only owner-approved metadata can be submitted live")
    if not approved.disclosures or approved.catalog_version is None:
        raise ValueError("live metadata needs approved disclosures and catalog version")
    verify_v2_record_hash(approved)
    if (approved.metadata_id, approved.metadata_version, approved.content_sha256) != (
        metadata_id,
        metadata_version,
        metadata_sha256,
    ):
        raise ValueError("live metadata version/content differs from Gate-2 approval")
    approved_projection = {
        "locale": approved.locale,
        "title": approved.title,
        "caption": approved.caption,
        "description": approved.description,
        "hashtags": approved.hashtags,
        "links": approved.links,
        "disclosures": approved.disclosures,
        "catalog_version": approved.catalog_version,
        "cover_asset_id": approved.cover_asset_id,
        "cover_asset_version": approved.cover_asset_version,
        "cover_asset_sha256": approved.cover_asset_sha256,
        "cta_text": approved.cta_text,
    }
    if metadata_projection.model_dump(mode="python") != approved_projection:
        raise ValueError("provider metadata projection differs from Gate-2 approval")
    return approved


class ProgressStage(StrEnum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"
    COMPLETE = "COMPLETE"


class ProgressSnapshot(V2Record):
    aggregate_id: UUID
    projection_revision: PositiveInt
    source_event_ids: list[UUID] = Field(min_length=1)
    source_job_ids: list[UUID] = Field(default_factory=list)
    source_asset_ids: list[UUID] = Field(default_factory=list)
    production_stage: ProgressStage
    release_stage: ProgressStage
    accepted_work: Annotated[int, Strict(), Field(ge=0)]
    required_work: Annotated[int, Strict(), Field(ge=0)]
    blocker_ids: list[Identifier] = Field(default_factory=list)
    next_action: ShortText | None = None
    progress_bp: Annotated[int, Strict(), Field(ge=0, le=10_000)] | None = None

    @model_validator(mode="after")
    def _projection(self):
        if self.required_work == 0 and self.progress_bp is not None:
            raise ValueError("zero denominator requires indeterminate progress")
        if self.required_work and self.progress_bp != min(
            10_000, self.accepted_work * 10_000 // self.required_work
        ):
            raise ValueError("progress must be derived from accepted/required persisted work")
        if self.accepted_work > self.required_work:
            raise ValueError("accepted work cannot exceed required work")
        return self


class V1ManifestReadback(ContractModel):
    """Audit wrapper: accepts a V1 manifest as data, never attests V2 readiness."""

    source_schema_version: Literal["1.0"]
    manifest_sha256: Sha256Hex
    manifest: dict[str, object]
    v2_ready: Literal[False] = False
    compatibility_note: Literal["V1 audit readback only; recompile to satisfy V2 bindings"] = (
        "V1 audit readback only; recompile to satisfy V2 bindings"
    )


def read_v1_manifest(payload: dict[str, object]) -> V1ManifestReadback:
    """Validate a legacy manifest using its V1 model and label it audit-only."""
    from microdrama.contracts.season import ShotManifest

    parsed = ShotManifest.model_validate(payload)
    legacy = parsed.model_dump(mode="json")
    return V1ManifestReadback(
        source_schema_version="1.0",
        manifest_sha256=canonical_hash(legacy),
        manifest=legacy,
        v2_ready=False,
    )


def validate_wardrobe_assignment(assignment: SceneWardrobeAssignment, bible: WardrobeBible) -> None:
    """Reject stale or mismatched scene outfit bindings before paid dispatch."""
    verify_v2_record_hash(assignment)
    verify_v2_record_hash(bible)
    if (assignment.wardrobe_bible_id, assignment.wardrobe_bible_version) != (
        bible.record_id,
        bible.version,
    ):
        raise ValueError("wardrobe assignment references a stale bible version")
    if assignment.character_id != bible.character_id:
        raise ValueError("wardrobe assignment character does not match bible owner")
    outfit = next((item for item in bible.outfits if item.outfit_id == assignment.outfit_id), None)
    if outfit is None:
        raise ValueError("wardrobe assignment outfit is absent from the exact bible")
    if (
        assignment.outfit_version,
        assignment.asset_id,
        assignment.asset_version,
        assignment.asset_sha256,
    ) != (outfit.version, outfit.asset_id, outfit.asset_version, outfit.asset_sha256):
        raise ValueError("wardrobe assignment is stale against the selected outfit version")
    if assignment.story_day < outfit.story_day_from or (
        outfit.story_day_until is not None and assignment.story_day > outfit.story_day_until
    ):
        raise ValueError("outfit is not valid on the assigned story day")
    if assignment.setting not in outfit.setting_tags:
        raise ValueError("outfit is not approved for the assigned setting")
    if assignment.rights != outfit.rights:
        raise ValueError("wardrobe assignment rights differ from the outfit rights")
    _ensure_rights_current(assignment.rights, assignment.valid_from, "outfit")


def validate_state_event_chain(events: list[StateEvent]) -> None:
    """Reject duplicate sequence numbers and contradictory overlapping transitions."""
    for event in events:
        verify_v2_record_hash(event)
    if len({event.sequence for event in events}) != len(events):
        raise ValueError("duplicate state event sequence")
    ordered = sorted(events, key=lambda item: item.sequence)
    previous: dict[tuple[str, str], StateEvent] = {}
    for event in ordered:
        key = (event.entity_id, event.field)
        prior = previous.get(key)
        if prior is not None:
            if event.effective_from_ms < prior.effective_until_ms:
                raise ValueError("contradictory overlapping state events")
            if event.before != prior.after:
                raise ValueError("state event chain contradicts previous state")
        previous[key] = event


V2_CORE_PAYLOADS = {
    "ConceptIntake": ConceptIntake,
    "ConceptCandidate": ConceptCandidate,
    "CharacterLogic": CharacterLogic,
    "SecretLedger": SecretLedger,
    "SeasonStoryLedger": SeasonStoryLedger,
    "EpisodePack": EpisodePack,
    "DirectingManifest": DirectingManifest,
    "StoryTime": StoryTime,
    "WardrobeBible": WardrobeBible,
    "SceneWardrobeAssignment": SceneWardrobeAssignment,
    "StateEvent": StateEvent,
    "AssetSheet": AssetSheet,
    "PropSheet": PropSheet,
    "StyleBible": StyleBible,
    "LocationLayout": LocationLayout,
    "ShotReferenceBinding": ShotReferenceBinding,
    "PromptManifest": PromptManifest,
    "ProgressSnapshot": ProgressSnapshot,
    "ReleaseApprovalManifest": ReleaseApprovalManifest,
}

V2_SUPPORTING_PAYLOADS = {
    "RightsGrant": RightsGrant,
    "DirectingShot": DirectingShot,
    "DirectingSection": DirectingSection,
    "OutfitDefinition": OutfitDefinition,
    "EpisodeScene": EpisodeScene,
    "PackBeat": PackBeat,
    "StateValue": StateValue,
    "V1ManifestReadback": V1ManifestReadback,
    "ApprovedMetadataPolicy": ApprovedMetadataPolicy,
    "ApprovedSlotMetadata": ApprovedSlotMetadata,
}
