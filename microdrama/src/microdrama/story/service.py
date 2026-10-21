"""Bible/canon compilation and episode script writing (T010).

Two entry points:

- ``compile_season``: deterministically compiles the Gate-1-APPROVED scope into a
  ``SeasonBible`` and stores it as a PLANNED ``canon_versions`` row. No paid dispatch at
  all: the arc was approved by the human gate, so the bible is a hash-bound machine
  compilation inside it (SPEC §5), immune to later trend evidence — a newer PROPOSED
  proposal can never silently change it, and recompiles of the same approved scope replay.
  Planned, final-approved and published canon stay separate kinds; this module writes
  PLANNED only and refuses the others with a typed error.

- ``write_episode``: the paid writer/critic pipeline with bounded rewrite (IMP-02). Every
  model call goes through the configured LLM provider behind a real
  ``BudgetService.reserve()`` on the episode account (queue ``production``, category
  RESEARCH_SCRIPT_PROMPTS_METADATA), worst-case-checked prospectively before anything
  dispatches. Critic failures consume budget and terminate at the configured limit with
  the spend retained (MD-008); nothing refunds or relabels charges. Deterministic critics
  (canon, character knowledge, Thai critical terms, complexity) run on every round and
  cannot be waived by a green model score.

Idempotency follows the research house pattern: deterministic uuid5 ids, semantic budget
keys, replay of already-current scripts, and typed conflicts for concurrent writers (the
episode row lock serialises claims, so a racer refuses before any paid dispatch).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError

from microdrama.budget import BudgetService
from microdrama.budget.ledger import episode_account_id, lock_account
from microdrama.config import Settings
from microdrama.contracts.cost import BudgetReservationRequest, ExposureCeilings, PriceQuote
from microdrama.contracts.enums import (
    BudgetCategory,
    BudgetScopeKind,
    ControlKind,
    PriceUnit,
    PrincipalKind,
    QueueName,
    RuntimeRole,
)
from microdrama.contracts.errors import (
    BudgetExhausted,
    Conflict,
    IdentityLockRequired,
    InvalidTransition,
    MicrodramaError,
    NotFound,
    PolicyDenied,
    SchemaInvalid,
    TransientProviderError,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.infra import Clock, IdGenerator
from microdrama.contracts.primitives import DEFAULT_LIMITS
from microdrama.contracts.principals import Principal
from microdrama.contracts.providers import LLMProvider, LLMRequest, LLMResponse
from microdrama.contracts.season import Script, SeasonScope, ShotManifest
from microdrama.core.events import append_event
from microdrama.core.state_machine import transition_episode
from microdrama.persistence.db import Database, Tx, insert_row, jsonb, update_with_revision
from microdrama.story.compiler import compile_episode
from microdrama.story.critics import check_draft
from microdrama.story.models import (
    BibleFact,
    CompileResult,
    CriticSeverity,
    CriticVerdict,
    DraftFinding,
    FactKind,
    KnowledgeEntry,
    RawCriticalTerm,
    RawLine,
    RawScene,
    RawStaging,
    SeasonBible,
    StagingSimplification,
    WriteOutcome,
    WriterDraft,
    WriteStatus,
)
from microdrama.story.playbook import PLAYBOOK_VERSION
from microdrama.story.prompts import (
    CRITIC_INSTRUCTION,
    CRITIC_MODEL_CONFIG_REF,
    CRITIC_OUTPUT_SCHEMA,
    WRITER_INSTRUCTION,
    WRITER_MODEL_CONFIG_REF,
    WRITER_OUTPUT_SCHEMA,
    estimate_line_ms,
)

_NS = uuid5(NAMESPACE_URL, "https://microdrama.invalid/story/v1")
_RESEARCH = BudgetCategory.RESEARCH_SCRIPT_PROMPTS_METADATA
_INPUT_UNIT = PriceUnit.INPUT_TOKEN_1K

WRITER_OPERATION = "story.writer"
CRITIC_OPERATION = "story.critic"

# Canon kinds this module may write. FINAL_APPROVED belongs to the Gate 2 flow and
# PUBLISHED to the publishing lane; the story module refuses both (typed PolicyDenied).
WRITABLE_CANON_KINDS: frozenset[str] = frozenset({"PLANNED"})

# Controls the compiler may emit. Camera motion is NOT supported by the initial build
# (static compositions only): requesting it triggers the documented staging
# simplification instead of a silent drop. This is configuration, not a capability claim —
# the preset registry (T006/T014) owns measured support.
DEFAULT_SUPPORTED_CONTROLS: frozenset[ControlKind] = frozenset(
    c for c in ControlKind if c is not ControlKind.CAMERA_MOTION
)


def _deterministic_id(kind: str, key: str) -> UUID:
    return uuid5(_NS, f"{kind}:{key}")


def budget_key_prefix(episode_id: UUID, *, write_attempt: int = 1) -> str:
    """Budget semantic keys carry the episode and the write attempt (house pattern).

    ``write_attempt=1`` are the canonical keys: a crash mid-dispatch retries the same keys
    and the provider replays by client token (no double paid work). A content-changing
    retry after a terminal typed failure uses ``write_attempt=2`` — new keys, new paid
    calls, against the SAME allowance (nothing resets, MD-008).
    """
    if write_attempt < 1:
        raise SchemaInvalid("write_attempt must be >= 1")
    return f"story:{episode_id}" if write_attempt == 1 else f"story:{episode_id}:r{write_attempt}"


def writer_client_token(
    episode_id: UUID, round_index: int, attempt: int, *, write_attempt: int = 1
) -> str:
    return f"{budget_key_prefix(episode_id, write_attempt=write_attempt)}:w{round_index}:a{attempt}"


def critic_client_token(episode_id: UUID, round_index: int, *, write_attempt: int = 1) -> str:
    return f"{budget_key_prefix(episode_id, write_attempt=write_attempt)}:c{round_index}"


class CanonKind(StrEnum):
    PLANNED = "PLANNED"
    FINAL_APPROVED = "FINAL_APPROVED"
    PUBLISHED = "PUBLISHED"


@dataclass(frozen=True)
class StoryConfig:
    """Bounded knobs. Prices are configuration: a missing price means the step cannot
    dispatch (typed NOT_DISPATCHED outcome, zero spend), because an unknown price blocks
    paid dispatch (SPEC §6)."""

    writer_max_attempts: int = 2
    max_rewrite_rounds: int = 2
    transport_attempts: int = 2
    llm_max_input_tokens: int = 8_000
    llm_max_output_tokens: int = 4_000
    llm_timeout_ms: int = 60_000
    reservation_ttl_ms: int = 900_000
    supported_controls: frozenset[ControlKind] = DEFAULT_SUPPORTED_CONTROLS
    writer_input_price: PriceQuote | None = None
    writer_output_price: PriceQuote | None = None
    critic_input_price: PriceQuote | None = None
    critic_output_price: PriceQuote | None = None

    def __post_init__(self) -> None:
        if self.writer_max_attempts < 1 or self.max_rewrite_rounds < 0:
            raise ValueError("writer attempts >= 1 and rewrite rounds >= 0 are required")
        if self.transport_attempts < 1:
            raise ValueError("transport attempts >= 1 are required")
        if ControlKind.CAMERA_MOTION in self.supported_controls:
            raise ValueError("camera motion is not a supported control in the initial build")

    @property
    def prices_configured(self) -> bool:
        return (
            self.writer_input_price is not None
            and self.writer_output_price is not None
            and self.critic_input_price is not None
            and self.critic_output_price is not None
        )


@dataclass(frozen=True)
class _CallPlan:
    semantic_key: str
    provider_id: str
    operation_kind: str
    worst_case_micro_usd: int
    price: PriceQuote
    ceilings: ExposureCeilings


@dataclass
class _WriteState:
    """Mutable, call-scoped working state (never shared between calls)."""

    episode_id: UUID
    season_id: UUID
    episode_number: int
    write_attempt: int = 1
    settled: int = 0
    rounds_used: int = 0
    reservation_ids: list[UUID] = field(default_factory=list)


@dataclass(frozen=True)
class _Claim:
    replay: bool
    season_id: UUID
    episode_number: int
    identity_lock_id: UUID | None
    claim_token: UUID | None = None
    script_body: dict[str, Any] | None = None
    manifest_body: dict[str, Any] | None = None
    scope: SeasonScope | None = None
    bible: SeasonBible | None = None


def _json_safe(payload: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in payload.items():
        try:
            canonical_hash(value)
            safe[key] = value
        except (TypeError, ValueError):
            safe[key] = str(value)
    return safe


def parse_writer_draft(output: dict[str, Any]) -> WriterDraft:
    """Defensively parse untrusted model output into a typed draft.

    Anything malformed (missing scenes/lines, bad term kinds) is a typed ``SchemaInvalid``
    — the calling attempt is consumed, never coerced into a pass.
    """
    from microdrama.contracts.enums import CriticalTermKind

    scenes_raw = output.get("scenes")
    if not isinstance(scenes_raw, list) or not scenes_raw:
        raise SchemaInvalid("writer output has no scenes")
    scenes: list[RawScene] = []
    for scene_index, raw_scene in enumerate(scenes_raw):
        if not isinstance(raw_scene, dict):
            raise SchemaInvalid("writer scene is not an object")
        lines_raw = raw_scene.get("lines")
        if not isinstance(lines_raw, list) or not lines_raw:
            raise SchemaInvalid(f"scene {scene_index} has no lines")
        lines: list[RawLine] = []
        for line_index, raw_line in enumerate(lines_raw):
            if not isinstance(raw_line, dict):
                raise SchemaInvalid(f"scene {scene_index} line {line_index} is not an object")
            speaker = raw_line.get("speaker_character_id")
            text_th = raw_line.get("text_th")
            text_en = raw_line.get("text_en")
            if not isinstance(speaker, str) or not speaker.strip():
                raise SchemaInvalid(f"scene {scene_index} line {line_index} has no speaker")
            if not isinstance(text_th, str) or not text_th.strip():
                raise SchemaInvalid(f"scene {scene_index} line {line_index} has no Thai text")
            if not isinstance(text_en, str) or not text_en.strip():
                raise SchemaInvalid(f"scene {scene_index} line {line_index} has no translation")
            terms: list[RawCriticalTerm] = []
            terms_raw = raw_line.get("critical_terms", [])
            if isinstance(terms_raw, list):
                for term in terms_raw:
                    if not isinstance(term, dict):
                        continue
                    kind = term.get("kind")
                    value_th = term.get("value_th")
                    if not isinstance(kind, str) or not isinstance(value_th, str):
                        continue
                    try:
                        CriticalTermKind(kind)
                    except ValueError as exc:
                        raise SchemaInvalid(f"unknown critical term kind {kind!r}") from exc
                    value_en = term.get("value_en")
                    terms.append(
                        RawCriticalTerm(
                            kind=kind,
                            value_th=value_th,
                            value_en=value_en if isinstance(value_en, str) else None,
                        )
                    )
            staging_raw = raw_line.get("staging")
            if isinstance(staging_raw, dict):
                staging = _parse_staging(staging_raw)
            else:
                # The declared writer schema carries staging as line-level shorthand
                # (``controls``/``framing``); fold it into the same typed staging.
                staging = _parse_staging(raw_line)
            lines.append(
                RawLine(
                    speaker_character_id=speaker.strip(),
                    text_th=text_th,
                    text_en=text_en,
                    critical_terms=terms,
                    staging=staging,
                )
            )
        scene_staging_raw = raw_scene.get("staging")
        summary = raw_scene.get("summary")
        location = raw_scene.get("location_id")
        scenes.append(
            RawScene(
                summary=summary if isinstance(summary, str) else None,
                location_id=location if isinstance(location, str) else None,
                lines=lines,
                staging=(
                    _parse_staging(scene_staging_raw)
                    if isinstance(scene_staging_raw, dict)
                    else RawStaging()
                ),
            )
        )
    return WriterDraft(scenes=scenes)


def _parse_staging(raw: dict[str, Any]) -> RawStaging:
    def _str(key: str) -> str | None:
        value = raw.get(key)
        return value if isinstance(value, str) else None

    def _str_list(key: str) -> list[str]:
        value = raw.get(key)
        return [x for x in value if isinstance(x, str)] if isinstance(value, list) else []

    return RawStaging(
        pattern_id=_str("pattern_id"),
        controls=_str_list("controls"),
        framing=_str("framing"),
        eyelines=_str("eyelines"),
        sound=_str("sound"),
        prop_ids=_str_list("prop_ids"),
        fallback_edit=_str("fallback_edit"),
    )


def parse_critic_verdict(output: dict[str, Any]) -> CriticVerdict:
    """Parse the semantic critic's output; anything malformed is a typed failure."""
    if not isinstance(output, dict) or not isinstance(output.get("passed"), bool):
        raise SchemaInvalid("critic output has no boolean passed")
    findings: list[DraftFinding] = []
    raw_findings = output.get("findings", [])
    if isinstance(raw_findings, list):
        for item in raw_findings:
            if not isinstance(item, dict):
                continue
            code = item.get("code")
            severity = item.get("severity")
            detail = item.get("detail")
            if not (
                isinstance(code, str)
                and code.strip()
                and isinstance(detail, str)
                and detail.strip()
            ):
                continue
            try:
                typed_severity = CriticSeverity(severity)
            except ValueError:
                typed_severity = CriticSeverity.REPAIRABLE
            findings.append(
                DraftFinding(code=code.strip(), severity=typed_severity, detail=detail.strip())
            )
    return CriticVerdict(passed=output["passed"], findings=findings)


def estimated_runtime_ms(draft: WriterDraft) -> int:
    """Deterministic estimated runtime: exact Thai line estimates plus per-scene padding."""
    line_total = sum(
        estimate_line_ms(line.text_th) for scene in draft.scenes for line in scene.lines
    )
    return line_total + 1_500 * len(draft.scenes)


class StoryService:
    """Compiles approved scopes into bibles and writes episode scripts. Construct once."""

    def __init__(
        self,
        db: Database,
        clock: Clock,
        ids: IdGenerator,
        settings: Settings,
        *,
        budget: BudgetService,
        llm: LLMProvider | None = None,
        config: StoryConfig | None = None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._ids = ids
        self._settings = settings
        self._budget = budget
        self._llm = llm
        self._config = config or StoryConfig()
        self._id_lock = threading.Lock()
        self._principal = Principal(
            principal_id="svc:story-worker", kind=PrincipalKind.SERVICE_WORKER
        )

    # --- plumbing ------------------------------------------------------------------

    def _new_id(self) -> UUID:
        with self._id_lock:
            return self._ids.new_id()

    def _now(self) -> datetime:
        now = self._clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise SchemaInvalid("clock must return a timezone-aware instant")
        return now

    @property
    def config(self) -> StoryConfig:
        return self._config

    # --- reads ---------------------------------------------------------------------

    def bible(self, season_id: UUID) -> SeasonBible:
        """The latest PLANNED bible. NotFound until the approved scope is compiled."""
        with self._db.transaction(readonly=True) as tx:
            row = tx.fetchone(
                "SELECT * FROM canon_versions WHERE season_id = %s AND kind = 'PLANNED' "
                "ORDER BY version DESC LIMIT 1",
                (season_id,),
            )
        if row is None:
            raise NotFound("season has no compiled bible", season_id=str(season_id))
        return SeasonBible.model_validate(row["facts"]["bible"])

    def canon_facts(self, season_id: UUID, kind: CanonKind | str) -> list[dict[str, Any]]:
        """Canon facts of one kind. Planned/final/published stay separate by construction."""
        typed = CanonKind(kind)
        with self._db.transaction(readonly=True) as tx:
            rows = tx.fetchall(
                "SELECT version, facts FROM canon_versions WHERE season_id = %s AND kind = %s "
                "ORDER BY version",
                (season_id, typed.value),
            )
        return [dict(row["facts"]) for row in rows]

    def script(self, episode_id: UUID) -> Script:
        with self._db.transaction(readonly=True) as tx:
            row = tx.fetchone(
                "SELECT body FROM scripts WHERE episode_id = %s AND status = 'CURRENT'",
                (episode_id,),
            )
        if row is None:
            raise NotFound("episode has no current script", episode_id=str(episode_id))
        return Script.model_validate(row["body"])

    def manifest(self, episode_id: UUID) -> ShotManifest:
        with self._db.transaction(readonly=True) as tx:
            row = tx.fetchone(
                "SELECT body FROM shot_manifests WHERE episode_id = %s AND status = 'CURRENT'",
                (episode_id,),
            )
        if row is None:
            raise NotFound("episode has no current shot manifest", episode_id=str(episode_id))
        return ShotManifest.model_validate(row["body"])

    # --- season compilation (deterministic, no paid dispatch) -------------------------

    def compile_season(self, season_id: UUID, *, scope_version: int | None = None) -> CompileResult:
        """Compile the APPROVED scope version into a PLANNED canon row (idempotent).

        Binds the season's ``approved_scope_hash``: only the Gate-1-approved proposal can
        be compiled. A later proposal (e.g. fresh trend research produced scope_version 2,
        still PROPOSED) is refused with a typed error — later evidence can never silently
        change the approved arc. Recompiling the same approved scope replays the bible.
        """
        now = self._now()
        with self._db.transaction() as tx:
            season = tx.fetchone("SELECT * FROM seasons WHERE id = %s FOR UPDATE", (season_id,))
            if season is None:
                raise NotFound("season not found", season_id=str(season_id))
            if season["state"] == "PROPOSED":
                raise InvalidTransition(
                    "season is PROPOSED; the bible compiles only an approved scope",
                    state=season["state"],
                )
            target_version = scope_version or season["approved_scope_version"]
            if target_version is None:
                raise Conflict("season carries no approved scope version to compile")
            proposal = tx.fetchone(
                "SELECT * FROM season_proposals WHERE season_id = %s AND scope_version = %s",
                (season_id, target_version),
            )
            if proposal is None:
                raise NotFound(
                    "no proposal exists for the requested scope version",
                    season_id=str(season_id),
                    scope_version=target_version,
                )
            if proposal["status"] != "APPROVED":
                # A PROPOSED/SUPERSEDED/REJECTED proposal is not approved canon material.
                raise Conflict(
                    "only the Gate-1-APPROVED scope version can be compiled; later "
                    f"evidence (proposal status {proposal['status']}) cannot silently "
                    "change the approved arc",
                    scope_version=target_version,
                    proposal_status=proposal["status"],
                )
            if proposal["scope_hash"] != season["approved_scope_hash"]:
                raise Conflict(
                    "proposal scope hash does not match the season's approved scope hash",
                    proposal_scope_hash=proposal["scope_hash"],
                    approved_scope_hash=season["approved_scope_hash"],
                )
            existing = tx.fetchone(
                "SELECT * FROM canon_versions WHERE season_id = %s AND kind = 'PLANNED' "
                "ORDER BY version DESC LIMIT 1",
                (season_id,),
            )
            if existing is not None:
                stored = (existing["facts"].get("bible") or {}).get("approved_scope_hash")
                if stored == season["approved_scope_hash"]:
                    bible = SeasonBible.model_validate(existing["facts"]["bible"])
                    return CompileResult(
                        season_id=season_id,
                        scope_version=bible.scope_version,
                        canon_version=bible.canon_version,
                        replayed=True,
                        facts_hash=existing["facts_hash"],
                        bible=bible,
                    )

            scope = SeasonScope.model_validate(proposal["scope"])
            version = (existing["version"] if existing is not None else 0) + 1
            bible = self._build_bible(season_id, scope, now, version)
            facts: dict[str, Any] = {"bible": bible.model_dump(mode="json")}
            facts_hash = canonical_hash(facts)
            insert_row(
                tx,
                "canon_versions",
                {
                    "id": self._new_id(),
                    "season_id": season_id,
                    "kind": "PLANNED",
                    "version": version,
                    "facts": jsonb(facts),
                    "facts_hash": facts_hash,
                },
            )
            self._seed_characters(tx, season_id, scope)
            append_event(
                tx,
                aggregate_type="season",
                aggregate_id=season_id,
                event_type="story.season_compiled",
                payload={
                    "scope_version": scope.scope_version,
                    "canon_version": version,
                    "approved_scope_hash": bible.approved_scope_hash,
                    "facts_hash": facts_hash,
                    "fact_count": len(bible.facts),
                },
                correlation_id=self._new_id(),
                occurred_at=now,
            )
        return CompileResult(
            season_id=season_id,
            scope_version=scope.scope_version,
            canon_version=version,
            replayed=False,
            facts_hash=facts_hash,
            bible=bible,
        )

    def _build_bible(
        self, season_id: UUID, scope: SeasonScope, now: datetime, canon_version: int
    ) -> SeasonBible:
        """Deterministic bible: every fact names the scope field it was derived from."""
        facts: list[BibleFact] = [
            BibleFact(
                fact_key="premise",
                kind=FactKind.PREMISE,
                statement=scope.premise[:2000],
                source_field="premise",
            )
        ]
        for character in scope.characters:
            facts.append(
                BibleFact(
                    fact_key=f"character.{character.character_id}",
                    kind=FactKind.CHARACTER,
                    statement=(
                        f"{character.name_en} ({character.name_th}) — {character.role}: "
                        f"{character.description}"[:2000]
                    ),
                    source_field="characters",
                )
            )
        knowledge: list[KnowledgeEntry] = []
        for beat in scope.arc:
            facts.append(
                BibleFact(
                    fact_key=f"beat.{beat.episode_number}",
                    kind=FactKind.ARC_BEAT,
                    statement=beat.summary[:2000],
                    source_field="arc",
                    episode_number=beat.episode_number,
                )
            )
            for index, reveal in enumerate(beat.planned_reveals, start=1):
                fact_key = f"reveal.{beat.episode_number}.{index}"
                facts.append(
                    BibleFact(
                        fact_key=fact_key,
                        kind=FactKind.PLANNED_REVEAL,
                        statement=reveal,
                        source_field="arc.planned_reveals",
                        episode_number=beat.episode_number,
                    )
                )
                knowledge.append(
                    KnowledgeEntry(fact_key=fact_key, known_from_episode=beat.episode_number)
                )
            if beat.cliffhanger:
                facts.append(
                    BibleFact(
                        fact_key=f"cliffhanger.{beat.episode_number}",
                        kind=FactKind.CLIFFHANGER,
                        statement=beat.cliffhanger,
                        source_field="arc.cliffhanger",
                        episode_number=beat.episode_number,
                    )
                )
        return SeasonBible(
            bible_id=self._new_id(),
            season_id=season_id,
            scope_version=scope.scope_version,
            approved_scope_hash=canonical_hash(scope),
            canon_version=canon_version,
            title_th=scope.title_th,
            title_en=scope.title_en,
            logline=scope.logline,
            premise=scope.premise,
            characters=list(scope.characters),
            arc=list(scope.arc),
            facts=facts,
            knowledge=knowledge,
            playbook_version=PLAYBOOK_VERSION,
            compiled_at=now,
        )

    def _seed_characters(self, tx: Tx, season_id: UUID, scope: SeasonScope) -> None:
        """Approved scope characters become PROVISIONAL character rows (reusable identities)."""
        for character in scope.characters:
            tx.execute(
                "INSERT INTO characters (id, season_id, character_key, name_th, name_en, "
                "brief, state, first_episode_number) VALUES (%s, %s, %s, %s, %s, %s, "
                "'PROVISIONAL', 1) ON CONFLICT (season_id, character_key) DO NOTHING",
                (
                    self._new_id(),
                    season_id,
                    character.character_id,
                    character.name_th,
                    character.name_en,
                    jsonb(character.model_dump(mode="json")),
                ),
            )

    def write_canon(self, season_id: UUID, kind: str, facts: dict[str, Any]) -> None:
        """Refuse direct canon writes. PLANNED canon comes only from ``compile_season``;
        FINAL_APPROVED belongs to the Gate 2 flow and PUBLISHED to the publishing lane —
        the story module can mint neither."""
        del season_id, facts
        if kind not in WRITABLE_CANON_KINDS:
            raise PolicyDenied(
                "the story module writes PLANNED canon only; FINAL_APPROVED and PUBLISHED "
                "canon are owned by the review and publishing lanes",
                kind=kind,
            )
        raise PolicyDenied(
            "canon rows are produced by compile_season; direct writes are not accepted",
            kind=kind,
        )

    # --- episode writing (paid, bounded) ---------------------------------------------

    def write_episode(
        self, episode_id: UUID, *, trigger: str = "pipeline", write_attempt: int = 1
    ) -> WriteOutcome:
        """Write the episode's script + shot manifest through the bounded writer/critic loop.

        ``write_attempt`` > 1 marks a content-changing retry after a terminal typed
        failure: fresh budget keys and provider tokens against the SAME allowance.
        """
        del trigger  # the budget prefix is the episode; the trigger is audit-only
        if write_attempt < 1:
            raise SchemaInvalid("write_attempt must be >= 1")
        claim = self._claim_episode(episode_id, write_attempt=write_attempt)
        if claim.replay:
            script = Script.model_validate(claim.script_body)
            manifest = ShotManifest.model_validate(claim.manifest_body)
            return WriteOutcome(
                episode_id=episode_id,
                status=WriteStatus.REPLAYED,
                script_id=script.script_id,
                manifest_id=manifest.manifest_id,
                script_version=script.version,
                settled_micro_usd=0,
                uncertainty_notes=["current script replayed; no new paid work dispatched"],
            )
        assert claim.scope is not None and claim.bible is not None
        state = _WriteState(
            episode_id=episode_id,
            season_id=claim.season_id,
            episode_number=claim.episode_number,
            write_attempt=write_attempt,
        )
        try:
            outcome = self._write_rounds(state, claim, claim.scope, claim.bible)
        except MicrodramaError as exc:
            self._append_failure_event(state, "story.write_failed", exc.code, exc.message)
            self._release_write_claim(state)
            raise
        if outcome.status is not WriteStatus.CURRENT:
            # Terminal failure: free the claim so an ordinary retry (same allowance) may run.
            self._release_write_claim(state)
        return outcome

    def _claim_episode(self, episode_id: UUID, *, write_attempt: int = 1) -> _Claim:
        """Serialise on the episode row, transition to SCRIPTING, open/fit the budget.

        The episode row lock plus a write-claim token (``episodes.correlation_id``) make
        concurrent writers deterministic: the first claim commits PLANNED→SCRIPTING with
        its token; a racing writer sees the live token and refuses with a typed Conflict
        BEFORE any paid dispatch. A hard crash can leave a stale claim behind; clearing it
        is an explicit recovery action (``clear_write_claim``), mirroring the documented
        RUNNING-run recovery gap in T009.
        """
        with self._db.transaction() as tx:
            episode = tx.fetchone("SELECT * FROM episodes WHERE id = %s FOR UPDATE", (episode_id,))
            if episode is None:
                raise NotFound("episode not found", episode_id=str(episode_id))
            season = tx.fetchone(
                "SELECT * FROM seasons WHERE id = %s FOR UPDATE", (episode["season_id"],)
            )
            if season is None:
                raise NotFound("season not found", season_id=str(episode["season_id"]))
            if episode["state"] not in ("PLANNED", "SCRIPTING"):
                raise InvalidTransition(
                    f"episode is {episode['state']}; story writing needs PLANNED or SCRIPTING",
                    state=episode["state"],
                )
            if episode["approved_scope_hash"] != season["approved_scope_hash"]:
                raise Conflict(
                    "episode is bound to a different approved scope than its season",
                    episode_scope_hash=episode["approved_scope_hash"],
                    season_scope_hash=season["approved_scope_hash"],
                )
            current_script = tx.fetchone(
                "SELECT body FROM scripts WHERE episode_id = %s AND status = 'CURRENT'",
                (episode_id,),
            )
            current_manifest = tx.fetchone(
                "SELECT body FROM shot_manifests WHERE episode_id = %s AND status = 'CURRENT'",
                (episode_id,),
            )
            if current_script is not None and current_manifest is not None:
                return _Claim(
                    replay=True,
                    season_id=season["id"],
                    episode_number=episode["episode_number"],
                    identity_lock_id=episode["identity_lock_id"],
                    script_body=current_script["body"],
                    manifest_body=current_manifest["body"],
                )
            if episode["correlation_id"] is not None:
                raise Conflict(
                    "another story write already claimed this episode; wait for it to "
                    "finish or clear the claim with evidence",
                    episode_id=str(episode_id),
                    claim_id=str(episode["correlation_id"]),
                )
            if episode["episode_number"] > 1 and episode["identity_lock_id"] is None:
                # IMP-01: later-episode work waits for the episode-one identity lock —
                # refused before any paid dispatch.
                raise IdentityLockRequired(
                    "later-episode story writing requires the episode-one identity lock",
                    episode_id=str(episode_id),
                    episode_number=episode["episode_number"],
                )

            bible_row = tx.fetchone(
                "SELECT facts FROM canon_versions WHERE season_id = %s AND kind = 'PLANNED' "
                "ORDER BY version DESC LIMIT 1",
                (season["id"],),
            )
            if bible_row is None:
                raise Conflict(
                    "season bible is not compiled for the approved scope; compile_season "
                    "must run first",
                    season_id=str(season["id"]),
                )
            bible = SeasonBible.model_validate(bible_row["facts"]["bible"])
            if bible.approved_scope_hash != season["approved_scope_hash"]:
                raise Conflict(
                    "the compiled bible does not match the season's approved scope; "
                    "recompile before writing",
                    bible_scope_hash=bible.approved_scope_hash,
                    season_scope_hash=season["approved_scope_hash"],
                )
            proposal = tx.fetchone(
                "SELECT scope FROM season_proposals WHERE season_id = %s AND status = 'APPROVED'",
                (season["id"],),
            )
            if proposal is None:
                raise Conflict("season has no approved scope proposal to write from")
            scope = SeasonScope.model_validate(proposal["scope"])
            if canonical_hash(scope) != season["approved_scope_hash"]:
                raise Conflict("approved proposal scope hash drifted from the season row")

            # Episode budget account (idempotent) + prospective whole-call fit check.
            self._budget.open_episode_account(
                tx,
                season_id=season["id"],
                episode_id=episode_id,
                policy=scope.cost_policy,
            )
            account_id = episode_account_id(tx, episode_id)
            account = lock_account(tx, account_id)
            planned_worst = self._planned_worst_case(episode_id, write_attempt)
            if account.committed + planned_worst + account.shutdown_reserve > account.cap:
                raise BudgetExhausted(
                    "planned story-writing worst case does not fit the episode allowance; "
                    "nothing is dispatched",
                    account_id=str(account_id),
                    cap_micro_usd=account.cap,
                    committed_micro_usd=account.committed,
                    planned_worst_case_micro_usd=planned_worst,
                    shutdown_reserve_micro_usd=account.shutdown_reserve,
                )
            claim_token = self._new_id()
            if episode["state"] == "PLANNED":
                transition_episode(
                    tx,
                    episode_id=episode_id,
                    to="SCRIPTING",
                    expected_revision=episode["revision"],
                    actor=self._principal,
                    now=self._now(),
                    correlation_id=claim_token,
                )
                fresh = tx.fetchone("SELECT revision FROM episodes WHERE id = %s", (episode_id,))
                assert fresh is not None
                update_with_revision(
                    tx,
                    "episodes",
                    episode_id,
                    fresh["revision"],
                    {"correlation_id": claim_token},
                    now=self._now(),
                )
            else:
                update_with_revision(
                    tx,
                    "episodes",
                    episode_id,
                    episode["revision"],
                    {"correlation_id": claim_token},
                    now=self._now(),
                )
            return _Claim(
                replay=False,
                season_id=season["id"],
                episode_number=episode["episode_number"],
                identity_lock_id=episode["identity_lock_id"],
                scope=scope,
                bible=bible,
                claim_token=claim_token,
            )

    def _release_write_claim(self, state: _WriteState) -> None:
        """Clear this call's write claim (best effort; typed answers take precedence)."""
        try:
            with self._db.transaction() as tx:
                row = tx.fetchone(
                    "SELECT revision, correlation_id FROM episodes WHERE id = %s FOR UPDATE",
                    (state.episode_id,),
                )
                if row is None or row["correlation_id"] is None:
                    return
                update_with_revision(
                    tx,
                    "episodes",
                    state.episode_id,
                    row["revision"],
                    {"correlation_id": None},
                    now=self._now(),
                )
        except MicrodramaError:
            pass

    def clear_write_claim(self, episode_id: UUID, *, reason: str) -> None:
        """Recovery action: clear a stale write claim (e.g. after a hard crash).

        Requires a written reason and refuses while a current script exists (a finished
        episode needs no claim cleared).
        """
        if not reason.strip():
            raise SchemaInvalid("clearing a write claim requires a reason")
        with self._db.transaction() as tx:
            row = tx.fetchone(
                "SELECT revision, correlation_id FROM episodes WHERE id = %s FOR UPDATE",
                (episode_id,),
            )
            if row is None:
                raise NotFound("episode not found", episode_id=str(episode_id))
            current = tx.fetchone(
                "SELECT 1 FROM scripts WHERE episode_id = %s AND status = 'CURRENT' LIMIT 1",
                (episode_id,),
            )
            if current is not None:
                raise Conflict("episode has a current script; there is no claim to clear")
            if row["correlation_id"] is None:
                return
            update_with_revision(
                tx,
                "episodes",
                episode_id,
                row["revision"],
                {"correlation_id": None},
                now=self._now(),
            )

    # --- the bounded writer/critic loop -------------------------------------------------

    def _write_rounds(
        self, state: _WriteState, claim: _Claim, scope: SeasonScope, bible: SeasonBible
    ) -> WriteOutcome:
        cfg = self._config
        if self._llm is None or not cfg.prices_configured:
            # Unknown price blocks paid dispatch (SPEC §6): typed outcome, zero spend,
            # nothing invented. The episode stays claimable once prices are configured.
            return WriteOutcome(
                episode_id=state.episode_id,
                status=WriteStatus.NOT_DISPATCHED,
                settled_micro_usd=0,
                uncertainty_notes=[
                    "no configured writer/critic price; paid dispatch blocked (typed unknown)"
                ],
            )

        findings: list[DraftFinding] = []
        draft: WriterDraft | None = None
        for round_index in range(cfg.max_rewrite_rounds + 1):
            state.rounds_used = round_index + 1
            draft = self._writer_attempt(state, round_index, scope, bible, findings)
            if draft is None:
                outcome = WriteOutcome(
                    episode_id=state.episode_id,
                    status=WriteStatus.WRITER_FAILED,
                    settled_micro_usd=state.settled,
                    rounds_used=state.rounds_used,
                    findings=findings,
                    uncertainty_notes=[
                        "no valid writer output within the configured attempts; spend retained"
                    ],
                )
                self._append_outcome_event(state, outcome)
                return outcome

            deterministic = check_draft(
                draft,
                scope=scope,
                bible=bible,
                episode_number=state.episode_number,
                estimated_runtime_ms=estimated_runtime_ms(draft),
                limits=DEFAULT_LIMITS,
            )
            findings = deterministic
            if not findings:
                verdict = self._critic_attempt(state, round_index, draft, findings)
                if verdict is None:
                    findings = [
                        DraftFinding(
                            code="critic-output-invalid",
                            severity=CriticSeverity.REPAIRABLE,
                            detail="the semantic critic output could not be validated; "
                            "treated as not passed (never coerced to a pass)",
                        )
                    ]
                else:
                    findings = [*findings, *verdict.findings]
                    if verdict.passed and not verdict.findings:
                        # Strict pass: zero deterministic findings AND a passing critic
                        # with none of its own. Anything else consumes a rewrite round.
                        return self._persist_success(state, claim, scope, bible, draft)
            # else: deterministic findings — rewrite with the findings attached.
        # Rewrite limit reached: the spend stays, the failure is typed and persisted.
        outcome = WriteOutcome(
            episode_id=state.episode_id,
            status=WriteStatus.CRITIC_FAILED,
            settled_micro_usd=state.settled,
            rounds_used=state.rounds_used,
            findings=findings,
            uncertainty_notes=["bounded rewrite limit reached; spend retained (MD-008)"],
        )
        self._persist_critic_failure(state, scope, bible, draft, outcome)
        self._append_outcome_event(state, outcome)
        return outcome

    # --- paid dispatch helpers -----------------------------------------------------------

    def _plan_calls(self, episode_id: UUID, write_attempt: int = 1) -> list[_CallPlan]:
        """Every prospective paid step of the bounded loop (all rounds and attempts),
        with concrete budget semantic keys for this episode and write attempt."""
        cfg = self._config
        if self._llm is None or not cfg.prices_configured:
            return []
        assert (
            cfg.writer_input_price is not None
            and cfg.writer_output_price is not None
            and cfg.critic_input_price is not None
            and cfg.critic_output_price is not None
        )
        prefix = budget_key_prefix(episode_id, write_attempt=write_attempt)
        in_units = -(-cfg.llm_max_input_tokens // 1000) or 1
        out_units = -(-cfg.llm_max_output_tokens // 1000) or 1
        ceilings_kwargs = {
            "timeout_ms": cfg.llm_timeout_ms,
            "max_input_tokens": cfg.llm_max_input_tokens,
            "max_output_tokens": cfg.llm_max_output_tokens,
        }

        def plan(key: str, operation: str, price: PriceQuote, units: int) -> _CallPlan:
            return _CallPlan(
                semantic_key=key,
                provider_id=self._llm.provider_id,  # type: ignore[union-attr]
                operation_kind=operation,
                worst_case_micro_usd=price.unit_price_micro_usd * units,
                price=price,
                ceilings=ExposureCeilings(max_units=units, **ceilings_kwargs),
            )

        calls: list[_CallPlan] = []
        for round_index in range(cfg.max_rewrite_rounds + 1):
            for attempt in range(1, cfg.writer_max_attempts + 1):
                calls.append(
                    plan(
                        f"{prefix}:w{round_index}:a{attempt}:in",
                        WRITER_OPERATION,
                        cfg.writer_input_price,
                        in_units,
                    )
                )
                calls.append(
                    plan(
                        f"{prefix}:w{round_index}:a{attempt}:out",
                        WRITER_OPERATION,
                        cfg.writer_output_price,
                        out_units,
                    )
                )
            calls.append(
                plan(
                    f"{prefix}:c{round_index}:in",
                    CRITIC_OPERATION,
                    cfg.critic_input_price,
                    in_units,
                )
            )
            calls.append(
                plan(
                    f"{prefix}:c{round_index}:out",
                    CRITIC_OPERATION,
                    cfg.critic_output_price,
                    out_units,
                )
            )
        return calls

    def _planned_worst_case(self, episode_id: UUID, write_attempt: int = 1) -> int:
        return sum(
            step.worst_case_micro_usd for step in self._plan_calls(episode_id, write_attempt)
        )

    def _reserve(self, state: _WriteState, step: _CallPlan):
        request = BudgetReservationRequest(
            request_id=_deterministic_id("request", step.semantic_key),
            semantic_key=step.semantic_key,
            scope_kind=BudgetScopeKind.EPISODE,
            episode_id=state.episode_id,
            category=_RESEARCH,
            queue=QueueName.PRODUCTION,
            provider=step.provider_id,
            operation_kind=step.operation_kind,
            price=step.price,
            ceilings=step.ceilings,
            worst_case_micro_usd=step.worst_case_micro_usd,
            expires_at=self._now() + timedelta(milliseconds=self._config.reservation_ttl_ms),
        )
        reservation = self._budget.reserve(request)
        state.reservation_ids.append(reservation.id)
        return reservation

    def _call_llm(
        self,
        state: _WriteState,
        *,
        role: RuntimeRole,
        model_config_ref: str,
        instruction: str,
        output_schema: dict[str, object],
        untrusted_documents: list[str],
        client_token: str,
        in_step: _CallPlan,
        out_step: _CallPlan,
    ) -> LLMResponse | None:
        """One bounded model call: reserve both pricing sides, transport-retry, settle.

        Receipt attribution follows the research house pattern: the provider returns one
        input-token and one output-token SETTLEMENT per call while the ledger accepts a
        single SETTLEMENT per reservation, so each pricing side holds its own reservation
        and the non-input receipt is posted to the output hold with a provenance-preserving
        copy (only ``reservation_id`` differs).
        """
        assert self._llm is not None
        cfg = self._config
        in_reservation = self._reserve(state, in_step)
        out_reservation = self._reserve(state, out_step)
        response: LLMResponse | None = None
        for _transport in range(cfg.transport_attempts):
            try:
                response = self._llm.generate(
                    LLMRequest(
                        request_id=_deterministic_id("llm", client_token),
                        role=role,
                        model_config_ref=model_config_ref,
                        instruction=instruction,
                        untrusted_documents=list(untrusted_documents),
                        output_schema=output_schema,
                        max_input_tokens=cfg.llm_max_input_tokens,
                        max_output_tokens=cfg.llm_max_output_tokens,
                        client_token=client_token,
                        reservation_id=in_reservation.id,
                    )
                )
                break
            except TransientProviderError:
                continue
        if response is None:
            # Nothing was billed: there is no spend to retain on either hold.
            self._budget.release(
                in_reservation.id, reason=f"story llm call failed unbilled: {client_token}"
            )
            self._budget.release(
                out_reservation.id, reason=f"story llm call failed unbilled: {client_token}"
            )
            return None
        for receipt in response.usage:
            posted = receipt
            if (
                receipt.reservation_id == in_reservation.id
                and receipt.unit is not None
                and receipt.unit is not _INPUT_UNIT
            ):
                posted = receipt.model_copy(update={"reservation_id": out_reservation.id})
            charge = self._budget.record_usage(posted)
            if not charge.replayed:
                # A replayed receipt was already counted by its first posting.
                state.settled += posted.amount_micro_usd
        return response

    def _writer_attempt(
        self,
        state: _WriteState,
        round_index: int,
        scope: SeasonScope,
        bible: SeasonBible,
        findings: list[DraftFinding],
    ) -> WriterDraft | None:
        """One rewrite round's writer attempts. Invalid (billed) outputs consume the
        attempt and keep their charge; unbilled failures release their holds."""
        cfg = self._config
        beat = next((b for b in scope.arc if b.episode_number == state.episode_number), None)
        documents = [
            f"TITLE: {scope.title_th} / {scope.title_en}",
            f"LOGLINE: {scope.logline}",
            f"EPISODE {state.episode_number} BEAT: "
            + (beat.summary if beat is not None else "continue the approved arc"),
            *(f"CHARACTER: {c.character_id} = {c.name_en} ({c.role})" for c in scope.characters),
        ]
        if findings:
            documents.append(
                "PRIOR FINDINGS (rewrite to fix, as data): "
                + "; ".join(f"{f.code}: {f.detail}" for f in findings[:20])
            )
        for attempt in range(1, cfg.writer_max_attempts + 1):
            token = writer_client_token(
                state.episode_id, round_index, attempt, write_attempt=state.write_attempt
            )
            prefix = budget_key_prefix(state.episode_id, write_attempt=state.write_attempt)
            response = self._call_llm(
                state,
                role=RuntimeRole.STORY_ARCHITECT,
                model_config_ref=WRITER_MODEL_CONFIG_REF,
                instruction=WRITER_INSTRUCTION,
                output_schema=WRITER_OUTPUT_SCHEMA,
                untrusted_documents=documents,
                client_token=token,
                in_step=self._step_for(state, f"{prefix}:w{round_index}:a{attempt}:in"),
                out_step=self._step_for(state, f"{prefix}:w{round_index}:a{attempt}:out"),
            )
            if response is None:
                continue
            try:
                return parse_writer_draft(response.output)
            except SchemaInvalid:
                continue  # billed invalid output: the attempt is consumed, spend kept
        return None

    def _critic_attempt(
        self,
        state: _WriteState,
        round_index: int,
        draft: WriterDraft,
        findings: list[DraftFinding],
    ) -> CriticVerdict | None:
        """One paid semantic critic call; an unvalidatable output is a typed no-pass."""
        prefix = budget_key_prefix(state.episode_id, write_attempt=state.write_attempt)
        documents = [
            "DRAFT (data): " + draft.model_dump_json(),
            *(
                f"DETERMINISTIC FINDING: {f.code} [{f.severity.value}]: {f.detail}"
                for f in findings[:20]
            ),
        ]
        response = self._call_llm(
            state,
            role=RuntimeRole.CRITIC,
            model_config_ref=CRITIC_MODEL_CONFIG_REF,
            instruction=CRITIC_INSTRUCTION,
            output_schema=CRITIC_OUTPUT_SCHEMA,
            untrusted_documents=documents,
            client_token=critic_client_token(
                state.episode_id, round_index, write_attempt=state.write_attempt
            ),
            in_step=self._step_for(state, f"{prefix}:c{round_index}:in"),
            out_step=self._step_for(state, f"{prefix}:c{round_index}:out"),
        )
        if response is None:
            return None
        try:
            return parse_critic_verdict(response.output)
        except SchemaInvalid:
            return None

    def _step_for(self, state: _WriteState, semantic_key: str) -> _CallPlan:
        """The plan step for one concrete semantic key of this episode and write attempt."""
        for step in self._plan_calls(state.episode_id, state.write_attempt):
            if step.semantic_key == semantic_key:
                return step
        raise SchemaInvalid(f"no planned paid step for {semantic_key!r}")

    # --- persistence ----------------------------------------------------------------------

    def _persist_success(
        self,
        state: _WriteState,
        claim: _Claim,
        scope: SeasonScope,
        bible: SeasonBible,
        draft: WriterDraft,
    ) -> WriteOutcome:
        del claim
        simplifications: list[StagingSimplification] = []
        notes: list[str] = []
        now = self._now()
        with self._db.transaction() as tx:
            episode = tx.fetchone(
                "SELECT * FROM episodes WHERE id = %s FOR UPDATE", (state.episode_id,)
            )
            if episode is None:
                raise NotFound("episode vanished during writing", episode_id=str(state.episode_id))
            if episode["state"] != "SCRIPTING":
                raise Conflict(
                    f"episode moved to {episode['state']} while the writer ran; the "
                    "script cannot be attached (spend is retained)",
                    state=episode["state"],
                )
            script_version = int(
                tx.fetchval(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM scripts WHERE episode_id = %s",
                    (state.episode_id,),
                )
            )
            manifest_version = int(
                tx.fetchval(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM shot_manifests "
                    "WHERE episode_id = %s",
                    (state.episode_id,),
                )
            )
            script_id = _deterministic_id("script", f"{state.episode_id}:v{script_version}")
            manifest_id = _deterministic_id("manifest", f"{state.episode_id}:v{manifest_version}")
            plan, script, manifest, simplifications, notes = compile_episode(
                draft=draft,
                scope=scope,
                bible=bible,
                episode_id=state.episode_id,
                episode_number=state.episode_number,
                script_id=script_id,
                manifest_id=manifest_id,
                script_version=script_version,
                manifest_version=manifest_version,
                identity_lock_id=episode["identity_lock_id"],
                supported_controls=self._config.supported_controls,
            )
            tx.execute(
                "UPDATE scripts SET status = 'SUPERSEDED', revision = revision + 1 "
                "WHERE episode_id = %s AND status = 'CURRENT'",
                (state.episode_id,),
            )
            tx.execute(
                "UPDATE shot_manifests SET status = 'SUPERSEDED', revision = revision + 1 "
                "WHERE episode_id = %s AND status = 'CURRENT'",
                (state.episode_id,),
            )
            insert_row(
                tx,
                "scripts",
                {
                    "id": script_id,
                    "episode_id": state.episode_id,
                    "version": script_version,
                    "canon_version": script.canon_version,
                    "body": jsonb(script),
                    "body_hash": canonical_hash(script),
                    "status": "CURRENT",
                },
                returning="id",
            )
            insert_row(
                tx,
                "shot_manifests",
                {
                    "id": manifest_id,
                    "episode_id": state.episode_id,
                    "script_id": script_id,
                    "version": manifest_version,
                    "identity_lock_id": episode["identity_lock_id"],
                    "body": jsonb(manifest),
                    "body_hash": canonical_hash(manifest),
                    "status": "CURRENT",
                },
                returning="id",
            )
            update_with_revision(
                tx,
                "episodes",
                state.episode_id,
                episode["revision"],
                {
                    "plan": jsonb(plan),
                    "current_script_id": script_id,
                    "current_manifest_id": manifest_id,
                    "correlation_id": None,  # release the write claim on success
                },
                now=now,
            )
            outcome = WriteOutcome(
                episode_id=state.episode_id,
                status=WriteStatus.CURRENT,
                script_id=script_id,
                manifest_id=manifest_id,
                script_version=script_version,
                settled_micro_usd=state.settled,
                rounds_used=state.rounds_used,
                findings=[],
                simplifications=simplifications,
                uncertainty_notes=notes,
            )
            append_event(
                tx,
                aggregate_type="episode",
                aggregate_id=state.episode_id,
                event_type="story.script_written",
                payload={
                    "script_version": script_version,
                    "manifest_version": manifest_version,
                    "shots": len(manifest.shots),
                    "lines": sum(len(sc.lines) for sc in script.scenes),
                    "estimated_runtime_ms": script.estimated_runtime_ms,
                    "settled_micro_usd": state.settled,
                    "rounds_used": state.rounds_used,
                    "simplifications": [s.model_dump(mode="json") for s in simplifications[:20]],
                    "uncertainty_notes": notes[:8],
                },
                correlation_id=self._new_id(),
                occurred_at=now,
            )
        return outcome

    def _persist_critic_failure(
        self,
        state: _WriteState,
        scope: SeasonScope,
        bible: SeasonBible,
        draft: WriterDraft | None,
        outcome: WriteOutcome,
    ) -> None:
        """Persist the failing draft as a CRITIC_FAILED script row when it is constructible.

        A draft whose structure violates the frozen contracts (e.g. too many speakers)
        cannot produce a contract Script: for those the typed outcome event below is the
        persisted record. Spend is retained either way (MD-008).
        """
        if draft is None:
            return
        try:
            with self._db.transaction() as tx:
                episode = tx.fetchone(
                    "SELECT episode_number FROM episodes WHERE id = %s", (state.episode_id,)
                )
                if episode is None:
                    return
                script_version = int(
                    tx.fetchval(
                        "SELECT COALESCE(MAX(version), 0) + 1 FROM scripts WHERE episode_id = %s",
                        (state.episode_id,),
                    )
                )
                script_id = _deterministic_id("script", f"{state.episode_id}:v{script_version}")
                _plan, script, _manifest, _s, _n = compile_episode(
                    draft=draft,
                    scope=scope,
                    bible=bible,
                    episode_id=state.episode_id,
                    episode_number=episode["episode_number"],
                    script_id=script_id,
                    manifest_id=_deterministic_id("manifest", f"{state.episode_id}:fail"),
                    script_version=script_version,
                    manifest_version=1,
                    identity_lock_id=None,
                    supported_controls=self._config.supported_controls,
                )
                insert_row(
                    tx,
                    "scripts",
                    {
                        "id": script_id,
                        "episode_id": state.episode_id,
                        "version": script_version,
                        "canon_version": script.canon_version,
                        "body": jsonb(script),
                        "body_hash": canonical_hash(script),
                        "status": "CRITIC_FAILED",
                    },
                    returning="id",
                )
        except (MicrodramaError, ValidationError, ValueError):
            # Structure violates the contracts: the outcome event remains the record.
            pass

    # --- events ----------------------------------------------------------------------------

    def _append_outcome_event(self, state: _WriteState, outcome: WriteOutcome) -> None:
        payload = {
            "status": outcome.status.value,
            "settled_micro_usd": outcome.settled_micro_usd,
            "rounds_used": outcome.rounds_used,
            "findings": [f.model_dump(mode="json") for f in outcome.findings[:20]],
            "uncertainty_notes": list(outcome.uncertainty_notes[:8]),
        }
        self._append_event_best_effort(state.episode_id, "story.script_failed", payload)

    def _append_failure_event(
        self, state: _WriteState, event_type: str, code: str, message: str
    ) -> None:
        self._append_event_best_effort(
            state.episode_id,
            event_type,
            {"error_code": code, "message": message[:500]},
        )

    def _append_event_best_effort(
        self, episode_id: UUID, event_type: str, payload: dict[str, Any]
    ) -> None:
        """The typed error is the caller's answer; a persistence problem must not mask it."""
        try:
            with self._db.transaction() as tx:
                append_event(
                    tx,
                    aggregate_type="episode",
                    aggregate_id=episode_id,
                    event_type=event_type,
                    payload=_json_safe(payload),
                    correlation_id=self._new_id(),
                    occurred_at=self._now(),
                )
        except MicrodramaError:
            pass


def build_story_service(
    db: Database,
    clock: Clock,
    ids: IdGenerator,
    settings: Settings,
    *,
    budget: BudgetService,
    llm: LLMProvider | None = None,
    config: StoryConfig | None = None,
) -> StoryService:
    """Composition factory the integrator registers.

    Prices are configuration. When the integrator builds the OFFLINE_MOCK composition with
    the T007 fake providers, a default config may carry the labelled synthetic price table
    (composition-time only — the one place the mock wiring may reference the fakes' frozen
    price constants, matching the fake provider being passed in). In any other mode, or
    with an explicit ``config``, no synthetic price is ever set: a live deployment must
    configure real prices or nothing dispatches.
    """
    if config is None and settings.is_offline_mock:
        from microdrama.testing.fakes.common import fake_price_quote

        config = StoryConfig(
            writer_input_price=fake_price_quote(PriceUnit.INPUT_TOKEN_1K),
            writer_output_price=fake_price_quote(PriceUnit.OUTPUT_TOKEN_1K),
            critic_input_price=fake_price_quote(PriceUnit.INPUT_TOKEN_1K),
            critic_output_price=fake_price_quote(PriceUnit.OUTPUT_TOKEN_1K),
        )
    return StoryService(db, clock, ids, settings, budget=budget, llm=llm, config=config)


__all__ = [
    "CRITIC_OPERATION",
    "CanonKind",
    "DEFAULT_SUPPORTED_CONTROLS",
    "StoryConfig",
    "StoryService",
    "WRITABLE_CANON_KINDS",
    "WRITER_OPERATION",
    "budget_key_prefix",
    "build_story_service",
    "critic_client_token",
    "estimated_runtime_ms",
    "parse_critic_verdict",
    "parse_writer_draft",
    "writer_client_token",
]
