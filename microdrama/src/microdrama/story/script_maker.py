"""V2 Script Maker orchestration helpers (T039).

This module deliberately does not own approval persistence or provider spending. The
research service remains the bounded proposal/budget authority, and StoryService remains
the Gate-1 compiler. These helpers validate the hand-off between them and build episode
pack payloads from structured writer output.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, TypeVar
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, ValidationError

from microdrama.budget import BudgetService, ReservationState
from microdrama.config import Settings
from microdrama.contracts.cost import BudgetReservationRequest, ExposureCeilings
from microdrama.contracts.enums import (
    BudgetCategory,
    BudgetScopeKind,
    EffectKind,
    PriceUnit,
    QueueName,
    RuntimeRole,
)
from microdrama.contracts.errors import Conflict, TransientProviderError
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.infra import Clock
from microdrama.contracts.primitives import ContractModel
from microdrama.contracts.providers import LLMProvider, LLMRequest, LLMResponse
from microdrama.contracts.season import SeasonScope
from microdrama.contracts.v2 import (
    CharacterLogic,
    ConceptCandidate,
    ConceptIntake,
    EpisodePack,
    PackBeat,
    PayoffDebt,
    PendingRightsAssessment,
    SeasonEscalation,
    SeasonStoryLedger,
    SecretEntry,
    SecretLedger,
    StoryTime,
    validate_season_story_ledger,
)
from microdrama.persistence.db import Database
from microdrama.story.models import SeasonBible
from microdrama.story.prompts import (
    V2_BIBLE_INSTRUCTION,
    V2_BIBLE_MODEL_CONFIG_REF,
    V2_BIBLE_OUTPUT_SCHEMA,
    V2_EPISODE_PACK_INSTRUCTION,
    V2_EPISODE_PACK_OUTPUT_SCHEMA,
    V2_PACK_MODEL_CONFIG_REF,
)
from microdrama.story.service import StoryConfig
from microdrama.story.v2_store import StoryV2Store

_NS = uuid5(NAMESPACE_URL, "https://microdrama.invalid/story/script-maker/v2")
_INPUT_UNIT = PriceUnit.INPUT_TOKEN_1K
_T = TypeVar("_T")


def _character_logic_id(season_id: UUID, character_id: str) -> UUID:
    """Stable full-bible identity; revisions advance the version, not the ID."""
    return uuid5(_NS, f"logic:{season_id}:{character_id}")


def _episode_character_logic_id(episode_id: UUID, source_logic_id: UUID) -> UUID:
    """Stable episode snapshot identity derived from the exact source record ID."""
    return uuid5(_NS, f"episode-character:{episode_id}:{source_logic_id}")


def _secret_ledger_id(season_id: UUID) -> UUID:
    return uuid5(_NS, f"secrets:{season_id}")


def _season_story_ledger_id(season_id: UUID) -> UUID:
    return uuid5(_NS, f"season-ledger:{season_id}")


@dataclass(frozen=True)
class CandidateScopeBinding:
    """Selected candidate identity bound to the exact scope hash Gate 1 receives."""

    intake_id: UUID
    candidate_id: UUID
    scope_hash: str
    scope: SeasonScope

    @classmethod
    def bind(
        cls, intake: ConceptIntake, candidate_id: UUID, scope: SeasonScope
    ) -> CandidateScopeBinding:
        if scope.expected_episode_count != intake.requested_episode_count:
            raise ValueError("candidate scope episode count differs from the intake")
        if not scope.creative_constraints.original_fiction_only:
            raise ValueError("Script Maker candidates must remain original fiction")
        return cls(
            intake_id=intake.record_id,
            candidate_id=candidate_id,
            scope_hash=canonical_hash(scope),
            scope=scope,
        )

    def verify_gate1_scope(self, approved_scope: SeasonScope) -> None:
        """Reject altered/stale scope before handing it to the existing Gate 1 flow."""
        if canonical_hash(approved_scope) != self.scope_hash:
            raise ValueError("Gate 1 scope does not match the selected candidate hash")

    @classmethod
    def from_candidate(
        cls, intake: ConceptIntake, candidate: ConceptCandidate, scope: SeasonScope
    ) -> CandidateScopeBinding:
        if candidate.intake_id != intake.record_id:
            raise ValueError("candidate belongs to a different intake")
        if candidate.scope_sha256 != canonical_hash(scope):
            raise ValueError("candidate scope hash does not match the Gate 1 scope")
        if candidate.episode_count != scope.expected_episode_count:
            raise ValueError("candidate episode count differs from its Gate 1 scope")
        return cls(intake.record_id, candidate.record_id, candidate.scope_sha256, scope)


def build_candidate(
    intake: ConceptIntake,
    scope: SeasonScope,
    *,
    record_id: UUID,
    now,
    rights_note: str = "Commercial output rights have not been verified for this proposal.",
) -> ConceptCandidate:
    """Adapt a proposed Gate 1 scope to the frozen V2 candidate payload.

    Candidate generation and research dispatch remain the caller's bounded, configured
    work. This adapter never upgrades pending rights or claims evidence.
    """
    if scope.expected_episode_count != intake.requested_episode_count:
        raise ValueError("candidate scope episode count differs from the intake")
    return ConceptCandidate.seal(
        record_id=record_id,
        version=1,
        created_at=now,
        updated_at=now,
        valid_from=now,
        intake_id=intake.record_id,
        title_th=scope.title_th,
        title_en=scope.title_en,
        logline=scope.logline,
        promise=scope.arc[0].summary,
        payoff_debt=[beat.summary for beat in scope.arc if beat.planned_reveals]
        or [scope.arc[-1].summary],
        escalation=[beat.summary for beat in scope.arc],
        episode_count=scope.expected_episode_count,
        scope_sha256=canonical_hash(scope),
        rights=PendingRightsAssessment(status="PENDING", note=rights_note),
    )


def rebind_candidate_to_proposal(
    candidate: ConceptCandidate, proposal_scope: SeasonScope
) -> ConceptCandidate:
    """Replace a draft scope hash with the exact persisted, provenance-stamped Gate 1 scope."""
    if candidate.episode_count != proposal_scope.expected_episode_count:
        raise ValueError("proposal episode count differs from the candidate")
    if (
        candidate.title_th != proposal_scope.title_th
        or candidate.title_en != proposal_scope.title_en
    ):
        raise ValueError("proposal title differs from the selected candidate")
    fields = candidate.model_dump(mode="python", exclude={"content_sha256"})
    fields["scope_sha256"] = canonical_hash(proposal_scope)
    return ConceptCandidate.seal(**fields)


@dataclass(frozen=True)
class EpisodePackDraft:
    """Structured V2 episode-pack content from a configured writer, before sealing."""

    episode_id: UUID
    episode_number: int
    duration_target_ms: int
    promise: str
    payoff_debt: list[str]
    escalation: str
    scenes: list[dict[str, object]]
    story_time_by_scene: dict[str, StoryTime | dict[str, object]]
    character_logic: list[CharacterLogic]


class _EpisodePackOutput(ContractModel):
    episode_number: int = Field(ge=1, le=10)
    duration_target_ms: int = Field(ge=180_000, le=300_000)
    promise: str = Field(min_length=1)
    payoff_debt: list[str] = Field(min_length=1)
    escalation: str = Field(min_length=1)
    scenes: list[dict[str, object]] = Field(min_length=1)


@dataclass(frozen=True)
class RichBible:
    """Hash-bound versioned season ledger, character logic, and secret ledger."""

    character_logic: tuple[CharacterLogic, ...]
    secret_ledger: SecretLedger
    season_story_ledger: SeasonStoryLedger


@dataclass(frozen=True)
class ScriptMakerStoryResult:
    status: str
    rich_bible: RichBible | None = None
    episode_pack: EpisodePack | None = None
    settled_micro_usd: int = 0
    replay_key: str | None = None


class _RichCharacterLogic(ContractModel):
    character_id: str
    observable_goal: str
    strategy: str
    flaw: str
    secret_id: str | None = None
    relationship_pressures: list[str] = Field(default_factory=list)
    knowledge_by_episode: dict[str, list[str]] = Field(default_factory=dict)


class _RichSecret(ContractModel):
    secret_id: str
    held_by_character_id: str
    fact: str
    planned_reveal_episode: int = Field(ge=1)
    known_by_character_ids: list[str] = Field(default_factory=list)


class _RichBibleOutput(ContractModel):
    characters: list[_RichCharacterLogic] = Field(min_length=1)
    secrets: list[_RichSecret] = Field(min_length=1)
    promise: str = Field(min_length=1)
    payoff_debts: list[PayoffDebt] = Field(min_length=1)
    escalations: list[SeasonEscalation] = Field(min_length=1)


def build_rich_bible(
    output: dict[str, object],
    *,
    bible: SeasonBible,
    episode_count: int,
    now,
    version: int = 1,
) -> RichBible:
    """Validate and seal V2 character logic and the planned secret ledger.

    Episode keys in ``knowledge_by_episode`` are decimal episode numbers. Planned secret
    facts remain in SecretLedger and are not copied into character prompts before reveal.
    """
    try:
        raw = _RichBibleOutput.model_validate(output)
    except ValidationError as exc:
        raise ValueError("invalid rich bible writer output") from exc
    character_ids = {character.character_id for character in bible.characters}
    draft_ids = {entry.character_id for entry in raw.characters}
    if draft_ids != character_ids or len(raw.characters) != len(character_ids):
        raise ValueError("rich bible must include every approved character exactly once")
    secret_ids = {secret.secret_id for secret in raw.secrets}
    if len(secret_ids) != len(raw.secrets):
        raise ValueError("duplicate secret id")
    for secret in raw.secrets:
        if secret.held_by_character_id not in character_ids:
            raise ValueError("secret holder is outside the approved cast")
        if secret.planned_reveal_episode > episode_count:
            raise ValueError("secret reveal is outside the approved season arc")
        if not set(secret.known_by_character_ids).issubset(character_ids):
            raise ValueError("secret knowledge names a character outside the approved cast")
    character_logic: list[CharacterLogic] = []
    for draft in raw.characters:
        if draft.secret_id is not None and draft.secret_id not in secret_ids:
            raise ValueError("character logic references an unknown secret")
        for episode_key, known_ids in draft.knowledge_by_episode.items():
            try:
                episode_number = int(episode_key)
            except ValueError as exc:
                raise ValueError(
                    "knowledge_by_episode keys must be decimal episode numbers"
                ) from exc
            if not 1 <= episode_number <= episode_count:
                raise ValueError("character knowledge is outside the approved season arc")
            for secret_id in known_ids:
                secret = next((item for item in raw.secrets if item.secret_id == secret_id), None)
                if secret is None:
                    raise ValueError("character knowledge references an unknown secret")
                if episode_number < secret.planned_reveal_episode:
                    raise ValueError("planned secret is known before its reveal episode")
                if draft.character_id not in secret.known_by_character_ids:
                    raise ValueError("secret knowledge is assigned to an unauthorized character")
        character_logic.append(
            CharacterLogic.seal(
                record_id=_character_logic_id(bible.season_id, draft.character_id),
                version=version,
                created_at=now,
                updated_at=now,
                valid_from=now,
                character_id=draft.character_id,
                season_id=bible.season_id,
                observable_goal=draft.observable_goal,
                strategy=draft.strategy,
                flaw=draft.flaw,
                secret_id=draft.secret_id,
                relationship_pressures=draft.relationship_pressures,
                knowledge_by_episode=draft.knowledge_by_episode,
            )
        )
    secret_ledger = SecretLedger.seal(
        record_id=_secret_ledger_id(bible.season_id),
        version=version,
        created_at=now,
        updated_at=now,
        valid_from=now,
        season_id=bible.season_id,
        secrets=[SecretEntry.model_validate(secret.model_dump()) for secret in raw.secrets],
    )
    story_ledger = SeasonStoryLedger.seal(
        record_id=_season_story_ledger_id(bible.season_id),
        version=version,
        created_at=now,
        updated_at=now,
        valid_from=now,
        season_id=bible.season_id,
        approved_scope_hash=bible.approved_scope_hash,
        promise=raw.promise,
        payoff_debts=raw.payoff_debts,
        escalations=raw.escalations,
        character_logic_record_ids=[record.record_id for record in character_logic],
        secret_ledger_id=secret_ledger.record_id,
    )
    validate_season_story_ledger(
        story_ledger,
        character_logic,
        secret_ledger,
        approved_scope_hash=bible.approved_scope_hash,
        episode_count=episode_count,
    )
    return RichBible(
        character_logic=tuple(character_logic),
        secret_ledger=secret_ledger,
        season_story_ledger=story_ledger,
    )


def _as_uuids(values: Sequence[object]) -> set[UUID]:
    """Writer output carries asset ids as strings; availability sets are UUIDs.

    An unparseable id is simply absent from the coerced set: callers treat "every
    named id must parse and exist" as availability (the frozen EpisodePack contract
    would reject a malformed id at seal time anyway).
    """
    out: set[UUID] = set()
    for value in values:
        try:
            out.add(value if isinstance(value, UUID) else UUID(str(value)))
        except (ValueError, TypeError):
            continue
    return out


def _ids_available(values: Sequence[object], available: set[UUID]) -> bool:
    """True when every named id parses as a UUID and exists in ``available``."""
    named = {str(value) for value in values}
    coerced = _as_uuids(values)
    return len(coerced) == len(named) and coerced.issubset(available)


def build_episode_pack(
    draft: EpisodePackDraft,
    *,
    bible: SeasonBible,
    secret_ledger: SecretLedger,
    candidate_binding: CandidateScopeBinding,
    record_id: UUID,
    now,
    version: int = 1,
    scoped_map_only: bool = False,
    available_asset_ids: set[UUID] | None = None,
    available_prop_ids: set[str] | None = None,
    available_location_ids: set[str] | None = None,
    available_wardrobe_assignment_ids: set[UUID] | None = None,
) -> EpisodePack:
    """Validate a detailed pack against the approved, hash-bound bible.

    The caller supplies concrete IDs and story-time values; this helper never invents
    asset, character, prop, or location identities. Future reveals are omitted from the
    pack's character knowledge until their planned episode.
    """
    if (
        draft.episode_number < 1
        or draft.episode_number > candidate_binding.scope.expected_episode_count
    ):
        raise ValueError("episode number is outside the approved season arc")
    if not any(beat.episode_number == draft.episode_number for beat in bible.arc):
        raise ValueError("episode has no beat in the approved season arc")
    if not (
        candidate_binding.scope.episode_min_duration_ms
        <= draft.duration_target_ms
        <= candidate_binding.scope.episode_max_duration_ms
    ):
        raise ValueError("episode duration is outside the approved season scope")
    if candidate_binding.scope_hash != bible.approved_scope_hash:
        raise ValueError("approved bible is not bound to the selected candidate scope")
    candidate_binding.verify_gate1_scope(candidate_binding.scope)
    allowed_characters = {c.character_id for c in bible.characters}
    secrets = {entry.secret_id: entry for entry in secret_ledger.secrets}
    if secret_ledger.season_id != bible.season_id:
        raise ValueError("secret ledger belongs to a different season")
    logic_ids = {item.character_id for item in draft.character_logic}
    if logic_ids != allowed_characters:
        raise ValueError("episode pack must carry logic for every approved character")
    safe_logic: list[CharacterLogic] = []
    for logic in draft.character_logic:
        if logic.season_id != bible.season_id:
            raise ValueError("character logic is not bound to the approved season")
        if logic.secret_id is not None and logic.secret_id not in secrets:
            raise ValueError("character logic references an unknown secret")
        for episode_key, known_ids in logic.knowledge_by_episode.items():
            if int(episode_key) > draft.episode_number:
                continue
            for secret_id in known_ids:
                secret = secrets.get(secret_id)
                if secret is None:
                    raise ValueError("character knowledge references an unknown secret")
                if draft.episode_number < secret.planned_reveal_episode:
                    raise ValueError("planned secret is exposed before its reveal episode")
                if logic.character_id not in secret.known_by_character_ids:
                    raise ValueError("secret knowledge is assigned to an unauthorized character")
        for known_ids in logic.knowledge_by_episode.values():
            if not set(known_ids).issubset(secrets):
                raise ValueError("character knowledge references an unknown secret")
        visible_knowledge = {
            episode_key: [
                secret_id
                for secret_id in known_ids
                if secrets[secret_id].planned_reveal_episode <= draft.episode_number
                and logic.character_id in secrets[secret_id].known_by_character_ids
            ]
            for episode_key, known_ids in logic.knowledge_by_episode.items()
            if int(episode_key) <= draft.episode_number
        }
        visible_secret_id = (
            logic.secret_id
            if logic.secret_id is not None
            and secrets[logic.secret_id].planned_reveal_episode <= draft.episode_number
            else None
        )
        safe_logic.append(
            CharacterLogic.seal(
                record_id=_episode_character_logic_id(draft.episode_id, logic.record_id),
                version=version,
                created_at=logic.created_at,
                updated_at=logic.updated_at,
                valid_from=logic.valid_from,
                valid_until=logic.valid_until,
                character_id=logic.character_id,
                season_id=logic.season_id,
                observable_goal=logic.observable_goal,
                strategy=logic.strategy,
                flaw=logic.flaw,
                secret_id=visible_secret_id,
                relationship_pressures=logic.relationship_pressures,
                knowledge_by_episode=visible_knowledge,
            )
        )
    scenes = []
    for raw in draft.scenes:
        scene_id = str(raw.get("scene_id", ""))
        story_time_value = raw.get("story_time", draft.story_time_by_scene.get(scene_id))
        if story_time_value is None:
            raise ValueError(f"missing story time for scene {scene_id!r}")
        if not isinstance(story_time_value, StoryTime):
            if not isinstance(story_time_value, dict):
                raise ValueError(f"invalid story time for scene {scene_id!r}")
            story_time_value = StoryTime.seal(
                record_id=uuid5(_NS, f"story-time:{draft.episode_id}:{scene_id}"),
                version=version,
                created_at=now,
                updated_at=now,
                valid_from=now,
                **story_time_value,
            )
        visible = raw.get("visible_character_ids")
        if not isinstance(visible, list) or not visible:
            raise ValueError("every scene must list all visible characters")
        if not set(visible).issubset(allowed_characters):
            raise ValueError("scene references a character outside the approved bible")
        if available_prop_ids is not None and not set(raw.get("prop_ids", [])).issubset(
            available_prop_ids
        ):
            raise ValueError("scene references a missing prop id")
        if (
            available_location_ids is not None
            and raw.get("location_id") not in available_location_ids
        ):
            raise ValueError("scene references a missing location id")
        if available_wardrobe_assignment_ids is not None and not _ids_available(
            raw.get("wardrobe_assignment_ids", []), available_wardrobe_assignment_ids
        ):
            raise ValueError("scene references a missing wardrobe assignment id")
        for beat in raw.get("beats", []):
            required = (
                beat.required_asset_ids
                if isinstance(beat, PackBeat)
                else beat.get("required_asset_ids", [])
            )
            if available_asset_ids is not None and not _ids_available(
                required, available_asset_ids
            ):
                raise ValueError("beat references a missing required asset id")
        scenes.append({**raw, "story_time": story_time_value})
    pack = EpisodePack.seal(
        record_id=record_id,
        version=version,
        created_at=now,
        updated_at=now,
        valid_from=now,
        episode_id=draft.episode_id,
        season_id=bible.season_id,
        approved_scope_hash=candidate_binding.scope_hash,
        episode_number=draft.episode_number,
        duration_target_ms=draft.duration_target_ms,
        character_logic=safe_logic,
        promise=draft.promise,
        payoff_debt=draft.payoff_debt,
        escalation=draft.escalation,
        scenes=scenes,
        scoped_map_only=scoped_map_only,
    )
    packed_text = _normalized_text(pack.model_dump_json())
    for secret in secret_ledger.secrets:
        if secret.planned_reveal_episode > draft.episode_number:
            normalized_fact = _normalized_text(secret.fact)
            if len(normalized_fact) >= 20 and normalized_fact in packed_text:
                raise ValueError("unrevealed secret fact appears in the episode pack")
    return pack


def _episode_pack_context(
    episode_number: int,
    scope: SeasonScope,
    bible: SeasonBible,
    rich: RichBible,
    *,
    available_asset_ids: set[UUID],
    available_prop_ids: set[str],
    available_location_ids: set[str],
    available_wardrobe_assignment_ids: set[UUID],
) -> str:
    """Serialize only current-episode canon and available IDs, withholding future secrets."""
    visible_secret_ids = {
        entry.secret_id
        for entry in rich.secret_ledger.secrets
        if entry.planned_reveal_episode <= episode_number
    }
    character_logic = []
    for record in rich.character_logic:
        logic = record.model_dump(mode="json")
        logic["secret_id"] = (
            logic["secret_id"] if logic["secret_id"] in visible_secret_ids else None
        )
        logic["knowledge_by_episode"] = {
            key: [secret_id for secret_id in ids if secret_id in visible_secret_ids]
            for key, ids in logic["knowledge_by_episode"].items()
            if int(key) <= episode_number
        }
        character_logic.append(logic)
    context = {
        "approved_scope_hash": bible.approved_scope_hash,
        "episode_number": episode_number,
        "episode_count": scope.expected_episode_count,
        "episode_duration_ms": {
            "min": scope.episode_min_duration_ms,
            "max": scope.episode_max_duration_ms,
        },
        "title_th": scope.title_th,
        "title_en": scope.title_en,
        "genre_tags": scope.genre_tags,
        "creative_constraints": scope.creative_constraints.model_dump(mode="json"),
        "current_arc_beat": next(
            beat.model_dump(mode="json")
            for beat in bible.arc
            if beat.episode_number == episode_number
        ),
        "cast": [
            {
                "character_id": char.character_id,
                "name_th": char.name_th,
                "name_en": char.name_en,
                "role": char.role,
            }
            for char in scope.characters
        ],
        "character_logic": character_logic,
        "revealed_or_current_secrets": [
            entry.model_dump(mode="json")
            for entry in rich.secret_ledger.secrets
            if entry.planned_reveal_episode <= episode_number
        ],
        "story_ledger": {
            "promise": rich.season_story_ledger.promise,
            "payoff_debts": [
                debt.model_dump(mode="json")
                for debt in rich.season_story_ledger.payoff_debts
                if debt.due_episode <= episode_number
            ],
            "escalations": [
                item.model_dump(mode="json")
                for item in rich.season_story_ledger.escalations
                if item.episode_number <= episode_number
            ],
        },
        "available_ids": {
            "assets": sorted(map(str, available_asset_ids)),
            "props": sorted(available_prop_ids),
            "locations": sorted(available_location_ids),
            "wardrobe_assignments": sorted(map(str, available_wardrobe_assignment_ids)),
        },
        # Do not send the full planned bible: later arc beats and unrevealed secret facts
        # remain outside this prompt by construction.
    }
    future_facts = [
        entry.fact
        for entry in rich.secret_ledger.secrets
        if entry.planned_reveal_episode > episode_number and len(_normalized_text(entry.fact)) >= 20
    ]
    return json.dumps(_redact_text(context, future_facts), ensure_ascii=False, sort_keys=True)


def _normalized_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _redact_text(value: Any, phrases: Sequence[str]) -> Any:
    if isinstance(value, str):
        result = value
        for phrase in phrases:
            if phrase:
                result = result.replace(phrase, "[planned secret withheld]")
        return result
    if isinstance(value, list):
        return [_redact_text(item, phrases) for item in value]
    if isinstance(value, dict):
        return {key: _redact_text(item, phrases) for key, item in value.items()}
    return value


class ScriptMakerStoryService:
    """Budgeted post-Gate-1 V2 bible and episode-pack writer.

    Each call reserves its configured maximum against an episode account before dispatch.
    The service persists sealed records in the append-only V2 document store and replays
    verified records after restart; it does not create another owner approval step.
    Deterministic budget keys and client tokens make
    a repeated call with identical reservation requests a replay: reservations, responses
    and charges all replay, no hold is released twice and no spend is counted twice.
    """

    def __init__(
        self,
        db: Database,
        clock: Clock,
        settings: Settings,
        *,
        budget: BudgetService,
        llm: LLMProvider | None,
        config: StoryConfig | None = None,
    ) -> None:
        self._clock = clock
        self._settings = settings
        self._budget = budget
        self._llm = llm
        self._config = config or StoryConfig()
        self._store = StoryV2Store(db)

    def generate_rich_bible(
        self,
        episode_id: UUID,
        *,
        bible: SeasonBible,
        episode_count: int,
        version: int = 1,
    ) -> ScriptMakerStoryResult:
        now = self._now()
        if version < 1 or episode_count < 1:
            raise ValueError("bible version and episode count must be positive")
        existing = self._load_rich_bible(bible, version=version, episode_count=episode_count)
        if existing is not None:
            return ScriptMakerStoryResult(
                status="REPLAYED",
                rich_bible=existing,
                settled_micro_usd=0,
                replay_key=f"script-maker:rich-bible:{bible.season_id}:v{version}",
            )

        def parse(output: dict[str, Any]) -> RichBible:
            return build_rich_bible(
                output, bible=bible, episode_count=episode_count, now=now, version=version
            )

        data, spend, key = self._invoke(
            episode_id,
            artifact_key=f"rich-bible:{bible.season_id}:v{version}",
            instruction=V2_BIBLE_INSTRUCTION,
            model_ref=V2_BIBLE_MODEL_CONFIG_REF,
            output_schema=V2_BIBLE_OUTPUT_SCHEMA,
            untrusted_documents=[bible.model_dump_json()],
            parse=parse,
        )
        if data is not None:
            self._store.save_bundle(
                [*data.character_logic, data.secret_ledger, data.season_story_ledger]
            )
        return ScriptMakerStoryResult(
            status="COMPLETED" if data is not None else "FAILED",
            rich_bible=data,
            settled_micro_usd=spend,
            replay_key=key,
        )

    def generate_episode_pack(
        self,
        episode_id: UUID,
        *,
        candidate_binding: CandidateScopeBinding,
        episode_number: int,
        season_scope: SeasonScope,
        bible: SeasonBible,
        rich_bible: RichBible,
        available_asset_ids: set[UUID],
        available_prop_ids: set[str],
        available_location_ids: set[str],
        available_wardrobe_assignment_ids: set[UUID],
        version: int = 1,
    ) -> ScriptMakerStoryResult:
        now = self._now()
        if not 1 <= episode_number <= season_scope.expected_episode_count:
            raise ValueError("episode number is outside the approved scope")
        if canonical_hash(season_scope) != bible.approved_scope_hash:
            raise ValueError("pack writer requires the exact Gate-1-approved scope")
        if rich_bible.season_story_ledger.approved_scope_hash != bible.approved_scope_hash:
            raise ValueError("rich bible is bound to a different approved scope")
        if rich_bible != self._load_rich_bible(
            bible,
            version=rich_bible.secret_ledger.version,
            episode_count=season_scope.expected_episode_count,
        ):
            raise Conflict("episode pack writer requires the durably stored approved bible")
        candidate_binding.verify_gate1_scope(season_scope)
        pack_id = uuid5(_NS, f"episode-pack:{episode_id}")
        existing_pack = self._store.read(EpisodePack, pack_id, version=version)
        if existing_pack is not None:
            self._verify_episode_pack_readback(
                existing_pack,
                episode_id=episode_id,
                episode_number=episode_number,
                scope=season_scope,
                rich_bible=rich_bible,
            )
            return ScriptMakerStoryResult(
                status="REPLAYED",
                episode_pack=existing_pack,
                settled_micro_usd=0,
                replay_key=f"script-maker:episode-pack:{episode_id}:v{version}",
            )
        current_pack = self._store.read(EpisodePack, pack_id)
        latest_version = current_pack.version if current_pack is not None else 0
        if version != latest_version + 1:
            raise Conflict(
                "requested episode-pack version is not the next durable revision",
                latest_version=latest_version,
                requested_version=version,
            )
        pack_input = _episode_pack_context(
            episode_number,
            season_scope,
            bible,
            rich_bible,
            available_asset_ids=available_asset_ids,
            available_prop_ids=available_prop_ids,
            available_location_ids=available_location_ids,
            available_wardrobe_assignment_ids=available_wardrobe_assignment_ids,
        )

        def parse(output: dict[str, Any]) -> EpisodePack:
            raw = _EpisodePackOutput.model_validate(output)
            if raw.episode_number != episode_number:
                raise ValueError("writer returned the wrong episode number")
            draft = EpisodePackDraft(
                episode_id=episode_id,
                episode_number=raw.episode_number,
                duration_target_ms=raw.duration_target_ms,
                promise=raw.promise,
                payoff_debt=raw.payoff_debt,
                escalation=raw.escalation,
                scenes=raw.scenes,
                story_time_by_scene={},
                character_logic=list(rich_bible.character_logic),
            )
            return build_episode_pack(
                draft,
                bible=bible,
                secret_ledger=rich_bible.secret_ledger,
                candidate_binding=candidate_binding,
                record_id=pack_id,
                now=now,
                version=version,
                scoped_map_only=episode_number > 3,
                available_asset_ids=available_asset_ids,
                available_prop_ids=available_prop_ids,
                available_location_ids=available_location_ids,
                available_wardrobe_assignment_ids=available_wardrobe_assignment_ids,
            )

        instruction = V2_EPISODE_PACK_INSTRUCTION
        if episode_number > 3:
            instruction += (
                " This is a scoped later-episode map: use a compact outline and the least "
                "scene detail needed to bind cast, props, story time, state, and assets."
            )
        data, spend, key = self._invoke(
            episode_id,
            artifact_key=f"episode-pack:{episode_number}:v{version}",
            instruction=instruction,
            model_ref=V2_PACK_MODEL_CONFIG_REF,
            output_schema=V2_EPISODE_PACK_OUTPUT_SCHEMA,
            untrusted_documents=[pack_input],
            parse=parse,
        )
        if data is not None:
            self._store.save_bundle(
                [data, *data.character_logic, *(scene.story_time for scene in data.scenes)]
            )
        return ScriptMakerStoryResult(
            status="COMPLETED" if data is not None else "FAILED",
            episode_pack=data,
            settled_micro_usd=spend,
            replay_key=key,
        )

    def _load_rich_bible(
        self, bible: SeasonBible, *, version: int, episode_count: int
    ) -> RichBible | None:
        from microdrama.contracts.v2 import CharacterLogic

        logic_ids = [
            _character_logic_id(bible.season_id, character.character_id)
            for character in bible.characters
        ]
        ledger_id = _secret_ledger_id(bible.season_id)
        season_ledger_id = _season_story_ledger_id(bible.season_id)
        logic = [
            self._store.read(CharacterLogic, record_id, version=version) for record_id in logic_ids
        ]
        secret_ledger = self._store.read(SecretLedger, ledger_id, version=version)
        story_ledger = self._store.read(SeasonStoryLedger, season_ledger_id, version=version)
        loaded = [*logic, secret_ledger, story_ledger]
        if all(record is None for record in loaded):
            latest = self._store.read(SecretLedger, ledger_id)
            latest_version = latest.version if latest is not None else 0
            if version != latest_version + 1:
                raise Conflict(
                    "requested rich-bible version is not the next durable revision",
                    latest_version=latest_version,
                    requested_version=version,
                )
            return None
        if any(record is None for record in loaded):
            raise Conflict("durable rich bible is incomplete; refusing another provider call")
        records = [record for record in logic if record is not None]
        assert secret_ledger is not None and story_ledger is not None
        validate_season_story_ledger(
            story_ledger,
            records,
            secret_ledger,
            approved_scope_hash=bible.approved_scope_hash,
            episode_count=episode_count,
        )
        return RichBible(
            character_logic=tuple(records),
            secret_ledger=secret_ledger,
            season_story_ledger=story_ledger,
        )

    def _verify_episode_pack_readback(
        self,
        pack: EpisodePack,
        *,
        episode_id: UUID,
        episode_number: int,
        scope: SeasonScope,
        rich_bible: RichBible,
    ) -> None:
        if (
            pack.episode_id != episode_id
            or pack.episode_number != episode_number
            or pack.season_id != scope.season_id
            or pack.approved_scope_hash != canonical_hash(scope)
        ):
            raise Conflict("stored episode pack is stale or has a different Gate-1 scope")
        from microdrama.contracts.v2 import CharacterLogic

        secret_reveal = {
            secret.secret_id: secret.planned_reveal_episode
            for secret in rich_bible.secret_ledger.secrets
        }
        logic_by_character = {logic.character_id: logic for logic in rich_bible.character_logic}
        if set(logic_by_character) != {logic.character_id for logic in pack.character_logic}:
            raise Conflict("stored episode pack cast differs from the durable character bible")
        for logic in pack.character_logic:
            source = logic_by_character[logic.character_id]
            allowed_secret_ids = {
                secret_id
                for secret_id, reveal_episode in secret_reveal.items()
                if reveal_episode <= episode_number
            }
            expected_knowledge = {
                key: [secret_id for secret_id in ids if secret_id in allowed_secret_ids]
                for key, ids in source.knowledge_by_episode.items()
                if int(key) <= episode_number
            }
            expected_secret_id = (
                source.secret_id if source.secret_id in allowed_secret_ids else None
            )
            if (
                logic.season_id != source.season_id
                or logic.observable_goal != source.observable_goal
                or logic.strategy != source.strategy
                or logic.flaw != source.flaw
                or logic.relationship_pressures != source.relationship_pressures
                or logic.secret_id != expected_secret_id
                or logic.knowledge_by_episode != expected_knowledge
            ):
                raise Conflict(
                    "stored episode pack character logic is stale against the durable bible"
                )
            stored_logic = self._store.read(CharacterLogic, logic.record_id, version=logic.version)
            if stored_logic != logic:
                raise Conflict(
                    "stored episode pack character-logic snapshot is missing or mismatched"
                )
        for scene in pack.scenes:
            stored_time = self._store.read(
                StoryTime, scene.story_time.record_id, version=scene.story_time.version
            )
            if stored_time != scene.story_time:
                raise Conflict("stored episode pack story-time record is missing or mismatched")

    def _now(self) -> datetime:
        now = self._clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware instant")
        return now

    def _invoke(
        self,
        episode_id: UUID,
        *,
        artifact_key: str,
        instruction: str,
        model_ref: str,
        output_schema: dict[str, object],
        untrusted_documents: list[str],
        parse: Callable[[dict[str, Any]], _T],
    ) -> tuple[_T | None, int, str | None]:
        cfg = self._config
        if self._llm is None or cfg.writer_input_price is None or cfg.writer_output_price is None:
            return None, 0, None
        if self._settings.is_offline_mock and self._llm.provider_id != "fake-llm":
            return None, 0, None
        if not self._settings.is_offline_mock and not self._settings.effect_allowed(
            EffectKind.PAID_REQUEST
        ):
            return None, 0, None
        if (
            cfg.writer_input_price.unit is not PriceUnit.INPUT_TOKEN_1K
            or cfg.writer_output_price.unit is not PriceUnit.OUTPUT_TOKEN_1K
        ):
            raise ValueError("Script Maker requires configured input/output token price quotes")
        now = self._now()
        deadline = now + timedelta(milliseconds=cfg.reservation_ttl_ms)
        base = f"script-maker:{episode_id}:{artifact_key}"
        in_units = -(-cfg.llm_max_input_tokens // 1000) or 1
        out_units = -(-cfg.llm_max_output_tokens // 1000) or 1
        in_ceilings = ExposureCeilings(
            timeout_ms=cfg.llm_timeout_ms,
            max_units=in_units,
            max_input_tokens=cfg.llm_max_input_tokens,
            max_output_tokens=cfg.llm_max_output_tokens,
        )
        out_ceilings = in_ceilings.model_copy(update={"max_units": out_units})
        holds: list[tuple[int, str, Any]] = []
        try:
            for attempt in range(1, cfg.writer_max_attempts + 1):
                suffix = "" if attempt == 1 else f":a{attempt}"
                for side, price, ceilings, units in (
                    ("in", cfg.writer_input_price, in_ceilings, in_units),
                    ("out", cfg.writer_output_price, out_ceilings, out_units),
                ):
                    key = f"{base}{suffix}:{side}"
                    hold = self._budget.reserve(
                        BudgetReservationRequest(
                            request_id=uuid5(_NS, f"reservation:{key}"),
                            semantic_key=key,
                            scope_kind=BudgetScopeKind.EPISODE,
                            episode_id=episode_id,
                            category=BudgetCategory.RESEARCH_SCRIPT_PROMPTS_METADATA,
                            queue=QueueName.PRODUCTION,
                            provider=self._llm.provider_id,
                            operation_kind="story.script_maker_v2",
                            price=price,
                            ceilings=ceilings,
                            worst_case_micro_usd=price.unit_price_micro_usd * units,
                            expires_at=deadline,
                        )
                    )
                    holds.append((attempt, side, hold))
        except Exception:
            for _attempt, _side, hold in holds:
                self._budget.release(hold.id, reason="V2 story writer envelope not fully reserved")
            raise

        used: set[tuple[int, str]] = set()
        settled = 0
        selected: _T | None = None
        for attempt in range(1, cfg.writer_max_attempts + 1):
            input_hold = next(h for a, side, h in holds if a == attempt and side == "in")
            output_hold = next(h for a, side, h in holds if a == attempt and side == "out")
            token = f"{base}:t{attempt}"
            response: LLMResponse | None = None
            for _transport in range(cfg.transport_attempts):
                try:
                    response = self._llm.generate(
                        LLMRequest(
                            request_id=uuid5(_NS, f"llm:{token}"),
                            role=RuntimeRole.STORY_ARCHITECT,
                            model_config_ref=model_ref,
                            instruction=instruction,
                            untrusted_documents=untrusted_documents,
                            output_schema=output_schema,
                            max_input_tokens=cfg.llm_max_input_tokens,
                            max_output_tokens=cfg.llm_max_output_tokens,
                            client_token=token,
                            reservation_id=input_hold.id,
                        )
                    )
                    break
                except TransientProviderError:
                    continue
            if response is None or not response.usage:
                continue
            for receipt in response.usage:
                target = input_hold if receipt.unit is PriceUnit.INPUT_TOKEN_1K else output_hold
                side = "in" if receipt.unit is PriceUnit.INPUT_TOKEN_1K else "out"
                used.add((attempt, side))
                posted = (
                    receipt
                    if receipt.reservation_id == target.id
                    else receipt.model_copy(update={"reservation_id": target.id})
                )
                charge = self._budget.record_usage(posted)
                if not charge.replayed:
                    settled += posted.amount_micro_usd
            try:
                selected = parse(response.output)
                break
            except (ValidationError, ValueError):
                selected = None
        for attempt, side, hold in holds:
            if (attempt, side) in used:
                continue
            if hold.state is not ReservationState.ACTIVE:
                # A replayed hold was already settled or released by the first call;
                # release() is terminal and must not be repeated.
                continue
            self._budget.release(hold.id, reason="unused V2 story writer exposure")
        return selected, settled, base


def first_three_and_later_map(
    packs: Sequence[EpisodePack],
) -> tuple[list[EpisodePack], list[EpisodePack]]:
    """Separate detailed opening packs from scoped later-episode map entries."""
    detailed = sorted((p for p in packs if p.episode_number <= 3), key=lambda p: p.episode_number)
    later = sorted((p for p in packs if p.episode_number > 3), key=lambda p: p.episode_number)
    if len({p.episode_number for p in packs}) != len(packs):
        raise ValueError("duplicate episode pack number")
    if any(pack.scoped_map_only for pack in detailed):
        raise ValueError("the first three episodes require detailed packs")
    if any(not pack.scoped_map_only for pack in later):
        raise ValueError("episodes after the first three must remain scoped map entries")
    return detailed, later


def build_script_maker_story_service(
    db: Database,
    clock: Clock,
    settings: Settings,
    *,
    budget: BudgetService,
    llm: LLMProvider | None = None,
    config: StoryConfig | None = None,
) -> ScriptMakerStoryService:
    """Composition-root factory; route and job registration stay with T044/T047.

    Prices are configuration, exactly like ``build_story_service``: with no explicit
    config in OFFLINE_MOCK the labelled synthetic price table is wired in; in any other
    mode, or with an explicit ``config``, a live deployment must configure real prices
    or nothing dispatches.
    """
    if config is None and settings.is_offline_mock:
        from microdrama.testing.fakes.common import fake_price_quote

        config = StoryConfig(
            writer_input_price=fake_price_quote(PriceUnit.INPUT_TOKEN_1K),
            writer_output_price=fake_price_quote(PriceUnit.OUTPUT_TOKEN_1K),
        )
    return ScriptMakerStoryService(db, clock, settings, budget=budget, llm=llm, config=config)
