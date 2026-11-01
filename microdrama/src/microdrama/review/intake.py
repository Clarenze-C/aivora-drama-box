"""The three-step owner Script Maker intake and the owner workbench reads (T044b2).

The owner wizard asks exactly three questions — original story idea, genre/tone,
episode count (1–10) — and nothing else. Every advanced value (original Thai
fiction, the 180–300 s episode band, destinations, rights and budget policy)
comes from the integrator's configured scope template, never from the browser:
the form parser reads a closed field set and rejects any other posted name, so a
browser cannot submit a ``SeasonScope`` or alter the approved default policy.

Durability and money rules this module honors:

- One wizard submission is one idempotent command (``IdempotencyService``): the
  season row, the creator link (``review.scope.link_season_creator``), the
  sealed ``ConceptIntake`` with its exact content hash and the configured
  pre-Gate-1 research envelope commit in ONE transaction, before any candidate
  work. A retried or double-submitted wizard key replays the same season; a
  refresh mid-wizard is stateless (the answers live in the form, not a session).
- The research envelope is opened only from configuration; with no configured
  envelope (or model/prices/live-paid authorization missing) the submission is
  recorded, a typed blocker is reported and NO job is dispatched — there is no
  default positive spend in any live mode. Commercial RIGHTS at candidate stage
  are PENDING by frozen contract design (`PendingRightsAssessment`: "not
  assessed during candidate generation"); the rights-shaped dispatch blocker is
  the live mode's paid-request authorization, which is the operator's confirmed
  right to spend.
- Candidate work runs behind the frozen ``research.collect_and_propose`` job
  (semantic-key idempotent): the handler reuses ``ScriptMakerService`` and
  ``ResearchService`` unchanged, persists the hash-sealed ``ConceptCandidate``
  documents, and lets the bounded research run persist the current Gate 1
  proposal. The owner then SELECTS one candidate; a different selection
  dispatches one more bounded run restricted to that candidate, so the scope
  hash the existing Gate 1 page binds is always the owner's chosen candidate's.
  Silence never approves: Gate 1 stays the only human concept decision.
- The workbench reads are owner-scoped projections of current typed V2
  documents (hash-verified, fail-closed on ambiguity) with honest
  unknown/missing markers; media is streamed only through ``/ui/media``. No new
  asset ledger and no stored progress counter exist here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, ValidationError

from microdrama.config import Settings
from microdrama.contracts.enums import JobStatus, SeasonState
from microdrama.contracts.errors import (
    Conflict,
    GateNotReady,
    InvalidTransition,
    NotFound,
    SchemaInvalid,
    StaleRevision,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.infra import Clock, IdGenerator
from microdrama.contracts.jobs import SeasonStepInput
from microdrama.contracts.primitives import ContractModel
from microdrama.contracts.season import SeasonScope
from microdrama.contracts.v2 import (
    AssetSheet,
    CharacterLogic,
    ConceptCandidate,
    ConceptIntake,
    DirectingManifest,
    EpisodePack,
    LocationLayout,
    PromptManifest,
    PropSheet,
    SceneWardrobeAssignment,
    SeasonStoryLedger,
    SecretLedger,
    StyleBible,
    WardrobeBible,
    verify_v2_record_hash,
)
from microdrama.core.idempotency import CommandResult, IdempotencyService
from microdrama.core.jobs import Failed, JobContext, JobOutcome, Succeeded
from microdrama.persistence.db import Database, Tx, insert_row, jsonb
from microdrama.research.models import ComparatorCorpus, ConceptDraft, ResearchRequest
from microdrama.research.script_maker import (
    CandidateGenerationResult,
    ScriptMakerService,
)
from microdrama.research.service import ResearchService
from microdrama.review.scope import (
    link_season_creator,
    require_season_access,
    scoped_owner_id,
    season_is_owned_by,
)

_NS = uuid5(NAMESPACE_URL, "https://microdrama.invalid/review/intake/v1")

#: The frozen job type the intake dispatches behind (queue ``production``).
INTAKE_JOB_TYPE = "research.collect_and_propose"
#: ``SeasonStepInput.trigger`` values that route a job to this module's handler.
INTAKE_TRIGGER = "owner_intake"
SELECTION_TRIGGER_PREFIX = "owner_selection."  # dot: Identifier forbids ":"
#: One stable generation idempotency key per season: repeats replay, never re-spend.
INTAKE_GENERATION_KEY = "owner-intake"

#: Job statuses a queued selection still runs under (a durable retry intent).
_NON_TERMINAL_JOB_STATUSES = frozenset(
    {
        JobStatus.QUEUED.value,
        JobStatus.RUNNING.value,
        JobStatus.WAITING_EXTERNAL.value,
        JobStatus.RETRY_WAIT.value,
    }
)


def selection_trigger(revision: int, candidate_id: UUID) -> str:
    """A selection job trigger naming its durable revision and candidate."""
    return f"{SELECTION_TRIGGER_PREFIX}{revision}.{candidate_id}"


def parse_selection_trigger(trigger: str) -> tuple[int, UUID] | None:
    """``(revision, candidate)`` for a selection trigger, or None when malformed."""
    if not trigger.startswith(SELECTION_TRIGGER_PREFIX):
        return None
    revision_text, _, candidate_text = trigger[len(SELECTION_TRIGGER_PREFIX) :].partition(".")
    try:
        return int(revision_text), UUID(candidate_text)
    except ValueError:
        return None


_WIZARD_FIELDS = frozenset(
    {"csrf_token", "step", "wizard_key", "story_idea", "genre_tags", "tone", "episode_count"}
)
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,119}$")
_MAX_IDEA = 20_000  # LongText bound of the frozen ConceptIntake contract
_MAX_TONE = 500  # ShortText bound


def intake_record_id(season_id: UUID) -> UUID:
    """Deterministic one-intake-per-season identity (the durable intake→season link)."""
    return uuid5(_NS, f"intake:{season_id}")


# --- configuration -------------------------------------------------------------------------


@dataclass(frozen=True)
class IntakeConfig:
    """Configured intake bounds. Anything left ``None``/empty is a typed blocker.

    Exactly like the price tables in ``build_script_maker_service``: the
    OFFLINE_MOCK composition may wire the labelled mock defaults (fake sources,
    the mock comparator, the example scope template and a mock envelope); any
    live deployment must configure its own values or nothing dispatches.
    """

    research_envelope_micro_usd: int | None = None
    allowed_source_ids: tuple[str, ...] = ()
    source_provider_id: str = "fake-sources"
    comparator_corpus: ComparatorCorpus | None = None
    scope_template: SeasonScope | None = None


# --- the three answers ----------------------------------------------------------------------


@dataclass(frozen=True)
class IntakeAnswers:
    """Exactly what the browser may choose. There is no scope or policy here."""

    story_idea: str
    genre_tags: tuple[str, ...]
    tone: str
    episode_count: int


def _episode_count(raw: str) -> int:
    text = raw.strip()
    if not re.fullmatch(r"[0-9]{1,2}", text):
        raise SchemaInvalid("episode count must be a whole number between 1 and 10")
    value = int(text)
    if not 1 <= value <= 10:
        raise SchemaInvalid("episode count must be between 1 and 10")
    return value


def _genre_tags(raw: str) -> tuple[str, ...]:
    tags: list[str] = []
    for tag in re.split(r"[\s,]+", raw.strip()):
        if not tag:
            continue
        if len(tags) >= 8:
            raise SchemaInvalid("at most 8 genre tags are accepted")
        if not _IDENTIFIER.fullmatch(tag):
            raise SchemaInvalid(
                f"genre tag {tag!r} must use lowercase letters, digits, dots, dashes or underscores"
            )
        if tag not in tags:
            tags.append(tag)
    if not tags:
        raise SchemaInvalid("at least one genre tag is required")
    return tuple(tags)


def _story_idea(raw: str) -> str:
    idea = raw.strip()
    if not idea:
        raise SchemaInvalid("the story idea must contain non-whitespace text")
    if len(idea) > _MAX_IDEA:
        raise SchemaInvalid(f"the story idea is longer than {_MAX_IDEA} characters")
    return idea


def _tone(raw: str) -> str:
    tone = raw.strip()
    if not tone:
        raise SchemaInvalid("the tone must contain non-whitespace text")
    if len(tone) > _MAX_TONE:
        raise SchemaInvalid(f"the tone is longer than {_MAX_TONE} characters")
    return tone


def wizard_step(form: Any) -> int:
    """The step a posted wizard form names (1, 2, 3 or 0 for the final submit)."""
    raw = form.get("step")
    if not isinstance(raw, str) or raw not in ("1", "2", "3", "submit"):
        raise SchemaInvalid("the wizard step is missing or unknown")
    return int(raw) if raw != "submit" else 0


def check_form_fields(form: Any) -> None:
    """Reject any posted field outside the wizard's closed set — loudly.

    A browser that posts a ``scope``, ``cost_policy``, ``destinations`` or any
    other name is told the form accepts only the three intake answers; nothing
    is silently dropped, so no submitted policy can pose as accepted.
    """
    names = set(form.keys())
    unknown = names - _WIZARD_FIELDS
    if unknown:
        raise SchemaInvalid(
            "this form accepts only the three intake answers (story idea, genre/tone, "
            f"episode count); unknown field(s): {', '.join(sorted(unknown))}"
        )


def answers_from_form(form: Any) -> IntakeAnswers:
    """All three answers, validated. Used by the final submit (and tests)."""
    for name in ("story_idea", "genre_tags", "tone", "episode_count"):
        if not isinstance(form.get(name), str):
            raise SchemaInvalid(f"form field {name} is required")
    return IntakeAnswers(
        story_idea=_story_idea(form.get("story_idea", "")),
        genre_tags=_genre_tags(form.get("genre_tags", "")),
        tone=_tone(form.get("tone", "")),
        episode_count=_episode_count(form.get("episode_count", "")),
    )


def wizard_key(form: Any) -> str:
    """The one-time key minted when the wizard opened; the submit is idempotent on it."""
    raw = form.get("wizard_key")
    if not isinstance(raw, str) or not re.fullmatch(r"[0-9a-f]{32}", raw.strip()):
        raise SchemaInvalid("the wizard key is missing; open the Script Maker again")
    return raw.strip()


def step_answers(form: Any, step: int) -> IntakeAnswers | None:
    """Validate the answers a step's POST must carry; None for step 1 (none yet)."""
    if step == 1:
        return None
    if not isinstance(form.get("story_idea"), str):
        raise SchemaInvalid("form field story_idea is required")
    idea = _story_idea(form.get("story_idea", ""))
    if step == 2:
        return IntakeAnswers(idea, (), "", 0)
    if not isinstance(form.get("genre_tags"), str) or not isinstance(form.get("tone"), str):
        raise SchemaInvalid("form fields genre_tags and tone are required")
    return IntakeAnswers(
        story_idea=idea,
        genre_tags=_genre_tags(form.get("genre_tags", "")),
        tone=_tone(form.get("tone", "")),
        episode_count=0,
    )


# --- module-local views ----------------------------------------------------------------------


class CandidateCard(ContractModel):
    """One generated candidate as the owner sees it, with research verdict and rights."""

    record_id: UUID
    title_th: str
    title_en: str
    logline: str
    promise: str
    payoff_debt: list[str] = Field(default_factory=list)
    escalation: list[str] = Field(default_factory=list)
    episode_count: int
    scope_sha256: str
    rights_status: str
    rights_note: str
    version: int
    # Research provenance/uncertainty for this candidate (absent until a run covers it).
    originality_status: str | None = None
    originality_note: str | None = None
    rank: int | None = None
    theme_support_bp: int | None = None
    is_current_proposal: bool = False


class IntakeJobView(ContractModel):
    job_id: UUID
    status: str
    trigger: str
    error_code: str | None = None
    selected_candidate_id: UUID | None = None


class IntakeView(ContractModel):
    """Everything the intake status page shows; projected from current rows."""

    season_id: UUID
    season_state: str
    intake_id: UUID
    intake_sha256: str
    story_idea: str
    genre_tags: list[str]
    tone: str
    requested_episode_count: int
    phase: str  # BLOCKED | QUEUED | GENERATING | CANDIDATES_READY | GENERATION_FAILED | DECIDED
    blockers: list[str] = Field(default_factory=list)
    jobs: list[IntakeJobView] = Field(default_factory=list)
    candidates: list[CandidateCard] = Field(default_factory=list)
    research_uncertainty: list[str] = Field(default_factory=list)
    research_evidence: list[str] = Field(default_factory=list)
    proposal_id: UUID | None = None
    proposal_scope_hash: str | None = None
    proposal_status: str | None = None
    research_spend_micro_usd: int = 0


class DocRef(ContractModel):
    """One current typed V2 document (or the honest absence of one).

    ``media_asset_id`` names an asset the summary cites; the workbench links it
    through the existing owner-scoped stream ``/ui/media/{asset_id}`` and never
    through a raw object URL.
    """

    contract_type: str
    record_id: UUID | None = None
    version: int | None = None
    content_sha256: str | None = None
    summary: str = ""
    note: str | None = None  # why nothing could be shown, when record_id is None
    media_asset_id: UUID | None = None


@dataclass(frozen=True)
class _SeasonDocs:
    """Season-level V2 document refs gathered before the frozen view is built."""

    story_ledger: DocRef
    secret_ledger: DocRef
    style_bible: DocRef
    character_logic: list[DocRef]
    wardrobe_bibles: list[DocRef]


class SectionCard(ContractModel):
    section_id: str
    sequence: int
    duration_ms: int
    shot_ids: list[str] = Field(default_factory=list)


class ShotCard(ContractModel):
    shot_id: str
    sequence: int
    duration_ms: int
    scene_id: str
    beat_id: str
    section_id: str


class EpisodeWorkbench(ContractModel):
    episode_id: UUID
    episode_number: int
    state: str
    outcome: str | None = None
    pack: DocRef = Field(default_factory=lambda: DocRef(contract_type="EpisodePack"))
    directing_manifest: DocRef = Field(
        default_factory=lambda: DocRef(contract_type="DirectingManifest")
    )
    sections: list[SectionCard] = Field(default_factory=list)
    shots: list[ShotCard] = Field(default_factory=list)
    wardrobe_assignments: list[DocRef] = Field(default_factory=list)
    prompt_manifests: list[DocRef] = Field(default_factory=list)
    unknown_notes: list[str] = Field(default_factory=list)


class SeasonWorkbench(ContractModel):
    """The owner workbench: approved canon and current typed V2 documents."""

    season_id: UUID
    season_state: str
    title_th: str = ""
    title_en: str = ""
    arc: list[dict[str, Any]] = Field(default_factory=list)
    characters: list[dict[str, Any]] = Field(default_factory=list)
    scope_doc: DocRef = Field(default_factory=lambda: DocRef(contract_type="SeasonScope"))
    story_ledger: DocRef = Field(default_factory=lambda: DocRef(contract_type="SeasonStoryLedger"))
    character_logic: list[DocRef] = Field(default_factory=list)
    secret_ledger: DocRef = Field(default_factory=lambda: DocRef(contract_type="SecretLedger"))
    style_bible: DocRef = Field(default_factory=lambda: DocRef(contract_type="StyleBible"))
    wardrobe_bibles: list[DocRef] = Field(default_factory=list)
    prop_sheets: list[DocRef] = Field(default_factory=list)
    location_layouts: list[DocRef] = Field(default_factory=list)
    asset_sheets: list[DocRef] = Field(default_factory=list)
    episodes: list[EpisodeWorkbench] = Field(default_factory=list)
    unknown_notes: list[str] = Field(default_factory=list)


# --- V2 document helpers (tx-scoped append; hash-verified reads) -----------------------------


def _append_doc(tx: Tx, record: Any) -> None:
    """Append one V2 record version inside the caller's transaction (replay-tolerant).

    Same durable semantics as the references lane's repository: an identical
    current revision replays silently; changed content becomes the next
    consecutive version; the previous current row is superseded.
    """
    verify_v2_record_hash(record)
    contract_type = type(record).__name__
    tx.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"review-intake:{contract_type}:{record.record_id}",),
    )
    current = tx.fetchone(
        "SELECT version, payload, payload_sha256 FROM v2_contract_documents "
        "WHERE contract_type = %s AND record_id = %s AND current FOR UPDATE",
        (contract_type, record.record_id),
    )
    sealed = record
    if current is not None:
        saved = None
        try:
            saved = type(record).model_validate(current["payload"])
        except ValidationError:
            saved = None
        if saved == record:
            return
        fields = record.model_dump(mode="python", exclude={"content_sha256"})
        fields.update(version=int(current["version"]) + 1)
        sealed = type(record).seal(**fields)
        tx.execute(
            "UPDATE v2_contract_documents SET current = false "
            "WHERE contract_type = %s AND record_id = %s AND current",
            (contract_type, record.record_id),
        )
    rights = getattr(sealed, "rights", None)
    insert_row(
        tx,
        "v2_contract_documents",
        {
            "contract_type": contract_type,
            "record_id": sealed.record_id,
            "version": sealed.version,
            "payload": jsonb(sealed),
            "payload_sha256": canonical_hash(sealed),
            "rights_route_id": getattr(rights, "rights_route_id", None),
            "rights_version": getattr(rights, "rights_version", None),
            "valid_from": sealed.valid_from,
            "valid_until": sealed.valid_until,
            "current": True,
            "created_at": sealed.created_at,
        },
    )


class _DocRow:
    __slots__ = ("record_id", "version", "payload", "payload_sha256")

    def __init__(self, row: dict[str, Any]) -> None:
        self.record_id = row["record_id"]
        self.version = int(row["version"])
        self.payload = dict(row["payload"])
        self.payload_sha256 = row["payload_sha256"]


def _current_docs_by(tx: Tx, contract_type: str, *, key: str, value: str) -> list[_DocRow]:
    return [
        _DocRow(row)
        for row in tx.fetchall(
            "SELECT record_id, version, payload, payload_sha256 FROM v2_contract_documents "
            "WHERE contract_type = %s AND current AND payload->>%s = %s "
            "ORDER BY record_id, version",
            (contract_type, key, value),
        )
    ]


def _verified(record: Any, row: _DocRow) -> bool:
    """A current document must re-validate and match its stored hash, else it is unreadable."""
    try:
        verify_v2_record_hash(record)
    except (ValidationError, ValueError):
        return False
    return canonical_hash(record) == row.payload_sha256


def _verified_model(model: type, doc: _DocRow) -> Any | None:
    """A current document re-validated AND hash-matched, or None (unreadable)."""
    try:
        record = model.model_validate(doc.payload)
    except ValidationError:
        return None
    return record if _verified(record, doc) else None


def _season_asset_ids(tx: Tx, season_id: UUID) -> set[str]:
    """Ids of the season's asset rows — the durable provenance for typed sheets.

    PropSheet/LocationLayout/AssetSheet records carry no season field (their ids
    are shared identifiers like ``ledger`` or ``stall``), so a workbench may only
    show a sheet whose asset provably belongs to THIS season.
    """
    return {
        str(row["id"])
        for row in tx.fetchall("SELECT id FROM assets WHERE season_id = %s", (season_id,))
    }


def _absent(contract_type: str, why: str) -> DocRef:
    return DocRef(contract_type=contract_type, note=why)


def _candidate_fingerprint(candidate: ConceptCandidate) -> str:
    """Content identity of a candidate, independent of versioning metadata."""
    return canonical_hash(
        candidate.model_dump(mode="python", exclude={"content_sha256", "version", "updated_at"})
    )


# --- the service ------------------------------------------------------------------------------


class IntakeService:
    """Owner intake, candidate selection and the workbench projections. Construct once."""

    def __init__(
        self,
        db: Database,
        clock: Clock,
        ids: IdGenerator,
        settings: Settings,
        *,
        jobs: Any,
        idempotency: IdempotencyService,
        budget: Any,
        script_maker: ScriptMakerService,
        research: ResearchService,
        config: IntakeConfig,
    ) -> None:
        self._db = db
        self._clock = clock
        self._ids = ids
        self._settings = settings
        self._jobs = jobs
        self._idempotency = idempotency
        self._budget = budget
        self._script_maker = script_maker
        self._research = research
        self._config = config

    # --- configuration blockers -----------------------------------------------------

    def _blockers(self) -> list[str]:
        blockers: list[str] = []
        if self._config.research_envelope_micro_usd is None:
            blockers.append("pre-Gate-1 research envelope is not configured")
        if self._config.scope_template is None:
            blockers.append("default season scope template is not configured")
        if not self._config.allowed_source_ids:
            blockers.append("research source lane is not configured")
        blockers.extend(self._research_blockers())
        blockers.extend(self._script_maker.dispatch_blockers())
        return blockers

    def _research_blockers(self) -> list[str]:
        """Why a dispatched run could not actually search sources or compare.

        A missing or disabled source provider, or missing research prices, would
        otherwise be noticed only AFTER candidate generation spent money: the
        research plan silently skips those steps and the run completes without
        evidence. These checks read the composed services' live registry and
        configuration — the same state the run would consult — so an intake that
        cannot research records typed blockers and dispatches nothing.
        """
        blockers: list[str] = []
        record = self._research.registry.get(self._config.source_provider_id)
        if record is None:
            blockers.append(
                f"research source provider '{self._config.source_provider_id}' is not registered"
            )
        elif not record.enabled:
            reason = f": {record.disabled_reason}" if record.disabled_reason else ""
            blockers.append(
                f"research source provider '{self._config.source_provider_id}' is disabled{reason}"
            )
        config = self._research.config
        if config.search_price is None:
            blockers.append("research search price is not configured")
        if self._research.llm is None:
            blockers.append("research model provider is not configured")
        if config.llm_input_price is None or config.llm_output_price is None:
            blockers.append("research model token prices are not configured")
        return blockers

    def defaults_brief(self) -> dict[str, Any]:
        """The locked advanced defaults the wizard shows (from server configuration).

        The browser can neither view nor change these values through the form;
        this summary is display-only transparency for the owner.
        """
        template = self._config.scope_template
        if template is None:
            return {"configured": False, "note": "default scope template is not configured"}
        return {
            "configured": True,
            "language": "th",
            "episode_min_duration_ms": template.episode_min_duration_ms,
            "episode_max_duration_ms": template.episode_max_duration_ms,
            "original_fiction_only": template.creative_constraints.original_fiction_only,
            "retain_thai_performances": template.creative_constraints.retain_thai_performances,
            "destinations": [
                f"{d.platform.value}/{d.account_ref} ({d.slot_kind.value})"
                for d in template.destinations
            ],
            "episode_cap_micro_usd": template.cost_policy.episode_cap_micro_usd,
            "paid_advertising_budget_micro_usd": template.cost_policy.paid_advertising_budget_micro_usd,
        }

    # --- wizard submit ----------------------------------------------------------------

    def submit(
        self,
        principal: Any,
        *,
        answers: IntakeAnswers,
        key: str,
    ) -> CommandResult:
        """One wizard submission: season + intake + link + envelope, then one job.

        The whole creation is a single idempotent transaction; candidate work is
        dispatched behind the frozen research job only when no blocker exists.
        """
        from microdrama.core.auth import require_human_owner

        require_human_owner(principal)
        request_hash = canonical_hash(
            {
                "story_idea": answers.story_idea,
                "genre_tags": list(answers.genre_tags),
                "tone": answers.tone,
                "requested_episode_count": answers.episode_count,
            }
        )
        return self._idempotency.execute(
            scope="POST /ui/intake",
            key=key,
            principal_id=principal.principal_id,
            request_hash=request_hash,
            action=lambda tx: self._create_intake(tx, principal, answers),
        )

    def _create_intake(
        self, tx: Tx, principal: Any, answers: IntakeAnswers
    ) -> tuple[int, dict[str, Any]]:
        now = self._now()
        season_id = self._ids.new_id()
        insert_row(
            tx,
            "seasons",
            {
                "id": season_id,
                "state": SeasonState.PROPOSED.value,
                # Honest placeholders until bounded research writes the real titles.
                "title_th": answers.story_idea[:200],
                "title_en": "awaiting concept generation",
                "expected_episode_count": answers.episode_count,
            },
            returning="id",
        )
        link_season_creator(tx, season_id, principal)
        intake = ConceptIntake.seal(
            record_id=intake_record_id(season_id),
            version=1,
            created_at=now,
            updated_at=now,
            valid_from=now,
            story_idea=answers.story_idea,
            genre_tags=list(answers.genre_tags),
            tone=answers.tone,
            requested_episode_count=answers.episode_count,
        )
        _append_doc(tx, intake)
        blockers = self._blockers()
        if self._config.research_envelope_micro_usd is not None:
            self._budget.open_research_account(
                tx,
                season_id=season_id,
                envelope_micro_usd=self._config.research_envelope_micro_usd,
            )
        job_id: UUID | None = None
        if not blockers:
            enqueued = self._jobs.enqueue(
                tx,
                job_type=INTAKE_JOB_TYPE,
                semantic_key=f"intake:{season_id}",
                payload=SeasonStepInput(season_id=season_id, trigger=INTAKE_TRIGGER),
                season_id=season_id,
            )
            job_id = enqueued.job_id
        body: dict[str, Any] = {
            "status": "QUEUED" if job_id is not None else "BLOCKED",
            "season_id": str(season_id),
            "intake_id": str(intake.record_id),
            "intake_sha256": intake.content_sha256,
            "job_id": str(job_id) if job_id is not None else None,
            "blockers": blockers,
        }
        return (202 if job_id is not None else 200), body

    # --- owner selection ----------------------------------------------------------------

    def select(
        self,
        principal: Any,
        season_id: UUID,
        candidate_id: UUID,
        *,
        intake_sha256: str,
    ) -> CommandResult:
        """The owner's candidate selection: one more bounded research job, nothing else.

        Selecting the candidate the current proposal already binds is a replay
        no-op (no job, no spend). Any other selection enqueues the frozen
        research job restricted to that candidate, which persists the next
        proposal version — the scope hash the existing Gate 1 page then binds.
        No approval is recorded here.
        """
        from microdrama.core.auth import require_human_owner

        require_human_owner(principal)
        if not isinstance(intake_sha256, str) or len(intake_sha256) != 64:
            raise SchemaInvalid("the intake hash binding is required")
        with self._db.transaction() as tx:
            season = tx.fetchone("SELECT * FROM seasons WHERE id = %s FOR UPDATE", (season_id,))
            if season is None or not season_is_owned_by(
                tx, season_id, scoped_owner_id(tx, principal)
            ):
                raise NotFound(f"season {season_id} not found")
            if season["state"] != SeasonState.PROPOSED.value:
                raise InvalidTransition(
                    f"season is {season['state']}; candidates can only be selected while "
                    "the season is PROPOSED",
                    state=season["state"],
                )
            intake = self._load_intake(tx, season_id)
            if intake is None:
                raise GateNotReady("this season has no intake to select from")
            if intake.content_sha256 != intake_sha256:
                raise StaleRevision(
                    "the intake changed since this page was prepared",
                    current_scope_hash=intake.content_sha256,
                )
            candidate = self._candidate_doc(tx, intake.record_id, candidate_id)
            if candidate is None:
                raise SchemaInvalid("the selected candidate is not one of this intake's")
            # Every selection job ever enqueued for this season. The season row
            # lock taken above serializes competing selections, so the count is a
            # durable revision: no selection intent can ever collide with an OLD
            # completed job's semantic key (selecting B, then A, then B again
            # must re-run B — not replay B's first completed job). The latest
            # intent is the row whose trigger names the HIGHEST revision: job ids
            # and created_at are not reliable order evidence under a frozen clock.
            selection_rows = tx.fetchall(
                "SELECT id, status, input->>'trigger' AS trigger FROM jobs "
                "WHERE season_id = %s AND job_type = %s "
                "AND starts_with(input->>'trigger', %s)",
                (season_id, INTAKE_JOB_TYPE, SELECTION_TRIGGER_PREFIX),
            )
            latest: tuple[int, UUID] | None = None
            latest_row: dict[str, Any] | None = None
            for row in selection_rows:
                parsed = parse_selection_trigger(str(row["trigger"] or ""))
                if parsed is not None and (latest is None or parsed[0] > latest[0]):
                    latest, latest_row = parsed, row
            if (
                latest is not None
                and latest_row is not None
                and latest[1] == candidate_id
                and str(latest_row["status"]) in _NON_TERMINAL_JOB_STATUSES
            ):
                # A double-click on the same candidate while its run is still in
                # flight: the already-queued job IS this intent; enqueue nothing.
                body = {
                    "status": "QUEUED",
                    "season_id": str(season_id),
                    "candidate_id": str(candidate_id),
                    "job_id": str(latest_row["id"]),
                }
                return CommandResult(200, body, replayed=True)
            proposal = self._current_proposal(tx, season_id)
            if (
                proposal is not None
                and proposal["scope_hash"] == candidate.scope_sha256
                and self._proposal_binds_candidate(tx, proposal, candidate)
            ):
                body = {
                    "status": "REPLAYED",
                    "season_id": str(season_id),
                    "candidate_id": str(candidate_id),
                    "job_id": None,
                }
                return CommandResult(200, body, replayed=True)
            revision = len(selection_rows) + 1
            enqueued = self._jobs.enqueue(
                tx,
                job_type=INTAKE_JOB_TYPE,
                semantic_key=f"intake-selection:{season_id}:{revision}",
                payload=SeasonStepInput(
                    season_id=season_id,
                    trigger=selection_trigger(revision, candidate_id),
                ),
                season_id=season_id,
            )
            body = {
                "status": "QUEUED",
                "season_id": str(season_id),
                "candidate_id": str(candidate_id),
                "job_id": str(enqueued.job_id),
            }
            return CommandResult(202, body, replayed=False)

    # --- status projection ---------------------------------------------------------------

    def status(self, principal: Any, season_id: UUID) -> IntakeView:
        from microdrama.core.auth import require_human_owner

        require_human_owner(principal)
        with self._db.transaction(readonly=True) as tx:
            require_season_access(tx, principal, season_id)
            return self._status(tx, season_id)

    def _status(self, tx: Tx, season_id: UUID) -> IntakeView:
        season = tx.fetchone("SELECT * FROM seasons WHERE id = %s", (season_id,))
        assert season is not None  # require_season_access raised otherwise
        intake = self._load_intake(tx, season_id)
        if intake is None:
            raise NotFound(f"season {season_id} has no intake")
        job_rows = tx.fetchall(
            "SELECT * FROM jobs WHERE season_id = %s AND job_type = %s "
            "AND starts_with(input->>'trigger', 'owner_') ORDER BY created_at, id",
            (season_id, INTAKE_JOB_TYPE),
        )
        jobs = [self._job_view(row) for row in job_rows]
        run = tx.fetchone(
            "SELECT outcome FROM research_runs WHERE season_id = %s AND state = 'COMPLETED' "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (season_id,),
        )
        ranked: dict[str, dict[str, Any]] = {}
        uncertainty: list[str] = []
        if run is not None and run["outcome"]:
            outcome = run["outcome"]
            uncertainty = [str(note) for note in (outcome.get("uncertainty_notes") or [])]
            ranked = {str(item.get("concept_id")): item for item in (outcome.get("ranked") or [])}
        proposal = self._current_proposal(tx, season_id)
        proposal_hash = proposal["scope_hash"] if proposal is not None else None
        candidates = [
            card.model_copy(
                update={
                    **(
                        {
                            "originality_status": str(
                                (ranked[str(card.record_id)].get("verdict") or {}).get("status")
                            ),
                            "originality_note": (
                                str(inner["note"])
                                if (inner := ranked[str(card.record_id)].get("verdict") or {}).get(
                                    "note"
                                )
                                is not None
                                else None
                            ),
                            "theme_support_bp": ranked[str(card.record_id)].get("theme_support_bp"),
                            "rank": ranked[str(card.record_id)].get("rank"),
                        }
                        if str(card.record_id) in ranked
                        else {}
                    ),
                    "is_current_proposal": (
                        proposal_hash is not None and proposal_hash == card.scope_sha256
                    ),
                }
            )
            for card in self._candidate_cards(tx, intake.record_id)
        ]
        spend = tx.fetchval(
            "SELECT COALESCE(SUM(settled_micro_usd + accrued_micro_usd), 0)::bigint "
            "FROM budget_accounts WHERE scope_kind = 'SEASON_RESEARCH' AND season_id = %s",
            (season_id,),
        )
        evidence: list[str] = []
        if proposal is not None:
            try:
                scope = SeasonScope.model_validate(proposal["scope"])
                evidence = list(scope.research_evidence_refs)
                uncertainty = list(dict.fromkeys([*scope.uncertainty_notes, *uncertainty]))
            except ValidationError:
                evidence = []
        return IntakeView(
            season_id=season_id,
            season_state=season["state"],
            intake_id=intake.record_id,
            intake_sha256=intake.content_sha256,
            story_idea=intake.story_idea,
            genre_tags=list(intake.genre_tags),
            tone=intake.tone,
            requested_episode_count=intake.requested_episode_count,
            phase=self._phase(season, jobs, candidates),
            # Always the CURRENT configuration blockers: with no job they explain
            # why nothing dispatched; with jobs in flight they surface a
            # configuration that broke after dispatch (the run will fail typed).
            blockers=self._blockers(),
            jobs=jobs,
            candidates=candidates,
            research_uncertainty=uncertainty,
            research_evidence=evidence,
            proposal_id=proposal["id"] if proposal is not None else None,
            proposal_scope_hash=proposal["scope_hash"] if proposal is not None else None,
            proposal_status=proposal["status"] if proposal is not None else None,
            research_spend_micro_usd=int(spend or 0),
        )

    def _phase(
        self, season: dict[str, Any], jobs: list[IntakeJobView], candidates: list[CandidateCard]
    ) -> str:
        if season["state"] in (
            SeasonState.SEASON_APPROVED.value,
            SeasonState.REJECTED.value,
            SeasonState.ACTIVE.value,
            SeasonState.COMPLETE.value,
            SeasonState.CANCELLED.value,
        ):
            return "DECIDED"
        if not jobs:
            return "BLOCKED"
        latest = jobs[-1]
        if latest.status == JobStatus.SUCCEEDED.value:
            return "CANDIDATES_READY" if candidates else "GENERATION_FAILED"
        if latest.status == JobStatus.FAILED.value:
            return "GENERATION_FAILED"
        if latest.status == JobStatus.NEEDS_RECONCILIATION.value:
            return "GENERATION_FAILED"
        if candidates:
            return "CANDIDATES_READY"
        return "GENERATING" if latest.status == JobStatus.RUNNING.value else "QUEUED"

    @staticmethod
    def _job_view(row: dict[str, Any]) -> IntakeJobView:
        trigger = str((row.get("input") or {}).get("trigger") or "")
        selected: UUID | None = None
        parsed = parse_selection_trigger(trigger)
        if parsed is not None:
            selected = parsed[1]
        return IntakeJobView(
            job_id=row["id"],
            status=str(row["status"]),
            trigger=trigger or INTAKE_TRIGGER,
            error_code=row["error_code"],
            selected_candidate_id=selected,
        )

    # --- the background job ----------------------------------------------------------------

    def handle_research_job(self, ctx: JobContext) -> JobOutcome | None:
        """The intake half of ``research.collect_and_propose``; None when not an intake job.

        Runs the existing bounded candidate+research path (unchanged services)
        for the persisted intake: candidates are generated behind the research
        envelope, persisted as hash-sealed ``ConceptCandidate`` documents, and
        one bounded research run writes the current Gate 1 proposal. A selection
        job replays the generation (no new spend) and restricts the run to the
        owner's chosen candidate, so the persisted proposal is that candidate's
        exact scope.
        """
        if not isinstance(ctx.payload, SeasonStepInput):
            return None
        season_id = ctx.payload.season_id
        trigger = ctx.payload.trigger
        selected_id: UUID | None = None
        revision: int | None = None
        if trigger == INTAKE_TRIGGER:
            pass
        elif trigger.startswith(SELECTION_TRIGGER_PREFIX):
            parsed = parse_selection_trigger(trigger)
            if parsed is None:
                return Failed("INTAKE_TRIGGER_INVALID", detail=str(trigger))
            revision, selected_id = parsed
        else:
            return None
        with self._db.transaction(readonly=True) as tx:
            season = tx.fetchone("SELECT id, state FROM seasons WHERE id = %s", (season_id,))
            if season is None:
                return Failed("INTAKE_SEASON_MISSING", detail=str(season_id))
            if season["state"] != SeasonState.PROPOSED.value:
                return Failed(
                    "INTAKE_SEASON_NOT_PROPOSED",
                    detail=f"season is {season['state']}; research proposes only on PROPOSED",
                )
            intake = self._load_intake(tx, season_id)
        if intake is None:
            return Failed("INTAKE_MISSING", detail=f"season {season_id} has no intake record")
        blockers = self._blockers()
        if blockers:
            return Failed("INTAKE_NOT_CONFIGURED", detail="; ".join(blockers))
        defaults = self._config.scope_template.model_copy(
            update={
                "season_id": season_id,
                "expected_episode_count": intake.requested_episode_count,
            }
        )
        generated = self._script_maker.generate_candidates(
            season_id,
            intake,
            scope_defaults=defaults,
            idempotency_key=INTAKE_GENERATION_KEY,
        )
        if generated.status == "NOT_DISPATCHED":
            return Failed(
                "INTAKE_NOT_CONFIGURED",
                detail="; ".join(self._script_maker.dispatch_blockers()),
            )
        if generated.status != "COMPLETED":
            return Failed(
                "CANDIDATE_GENERATION_FAILED",
                detail=f"status {generated.status}; settled {generated.settled_micro_usd}",
            )
        if not generated.candidates or not getattr(generated, "scopes", ()):
            return Failed(
                "CANDIDATE_GENERATION_EMPTY",
                detail=f"status {generated.status} produced no candidate scopes",
            )
        if selected_id is not None and not any(
            candidate.record_id == selected_id for candidate in generated.candidates
        ):
            return Failed("INTAKE_CANDIDATE_UNKNOWN", detail=str(selected_id))
        request = self._research_request(intake, generated, selected_id, revision=revision)
        result = self._research.run_research(season_id, request)
        if result.state != "COMPLETED":
            return Failed(
                "RESEARCH_FAILED",
                detail=result.failure_code or result.state,
            )
        bound = generated
        chosen_id: UUID | None = None
        if result.proposal_id is not None and result.outcome is not None:
            chosen = result.outcome.chosen_concept_id
            bound = generated.bind_gate1_proposal(result, self._research)
            chosen_id = next(
                (
                    candidate.record_id
                    for candidate in generated.candidates
                    if str(candidate.record_id) == chosen
                ),
                None,
            )
        self._persist_candidates(generated, season_id)  # ensure the raw history exists
        if chosen_id is not None:
            self._persist_candidates(bound, season_id, only_bound=chosen_id)
        proposal_hash = None
        if result.proposal_id is not None:
            proposal_hash = canonical_hash(self._research.proposal_scope(result.proposal_id))
        return Succeeded(
            {
                "season_id": str(season_id),
                "intake_id": str(intake.record_id),
                "candidates": len(bound.candidates),
                "selected_candidate_id": str(selected_id) if selected_id else None,
                "research_run_id": str(result.run_id),
                "proposal_id": str(result.proposal_id) if result.proposal_id else None,
                "proposal_scope_hash": proposal_hash,
                "settled_micro_usd": (
                    generated.settled_micro_usd
                    + (result.outcome.settled_micro_usd if result.outcome else 0)
                ),
            }
        )

    def _research_request(
        self,
        intake: ConceptIntake,
        generated: CandidateGenerationResult,
        selected_id: UUID | None,
        *,
        revision: int | None = None,
    ) -> ResearchRequest:
        trigger_key = (
            f"script-maker.select:{intake.record_id}:{selected_id}:{revision}"
            if selected_id is not None
            else f"script-maker.intake:{intake.record_id}"
        )
        template = ResearchRequest(
            trigger="MANUAL",
            trigger_key=trigger_key,
            source_provider_id=self._config.source_provider_id,
            allowed_source_ids=list(self._config.allowed_source_ids),
            query_texts=[intake.story_idea[:500]],
            comparator_corpus=self._config.comparator_corpus or ComparatorCorpus(),
            candidate_concepts=[ConceptDraft(concept_id="placeholder", scope=generated.scopes[0])],
        )
        return generated.research_request(
            template,
            candidate_ids={selected_id} if selected_id is not None else None,
        )

    def _persist_candidates(
        self,
        generated: CandidateGenerationResult,
        season_id: UUID,
        *,
        only_bound: UUID | None = None,
    ) -> None:
        """Persist the generated candidates' durable documents.

        Every candidate is ensured present once (its generated raw version is
        append-only history). Only the candidate a run actually BOUND to a
        persisted proposal is ever re-versioned afterwards — so a replay of an
        older job can never rewrite another job's newer binding, and repeated
        identical runs append nothing.
        """
        now = self._now()
        with self._db.transaction() as tx:
            proposal = self._current_proposal(tx, season_id)
            live_hash = proposal["scope_hash"] if proposal is not None else None
            for candidate in generated.candidates:
                if only_bound is not None and candidate.record_id == only_bound:
                    self._persist_bound_candidate(tx, candidate, now, live_hash)
                else:
                    self._ensure_candidate(tx, candidate)

    def _ensure_candidate(self, tx: Tx, candidate: ConceptCandidate) -> None:
        """Insert the generated candidate only when no version exists yet."""
        present = tx.fetchone(
            "SELECT 1 FROM v2_contract_documents "
            "WHERE contract_type = 'ConceptCandidate' AND record_id = %s LIMIT 1",
            (candidate.record_id,),
        )
        if present is None:
            _append_doc(tx, candidate)

    def _persist_bound_candidate(
        self, tx: Tx, candidate: ConceptCandidate, now: datetime, live_proposal_hash: str | None
    ) -> None:
        """Append the proposal-bound candidate version only when its CONTENT changed.

        ``bind_gate1_proposal`` seals the rebound candidate with its original
        version number, so the version field alone must never decide whether a
        new row is appended: comparison is over the content fingerprint
        (everything except version/updated_at/content hash). An identical
        replay — including a retry after the selection job already rebound this
        candidate — therefore persists nothing and cannot grow versions; a real
        content change (a new proposal hash) becomes the next consecutive
        version. The candidate the CURRENT proposal is bound to is never
        un-bound by content that does not carry the live proposal hash (a later
        selection outranks an older job's replay).
        """
        row = tx.fetchone(
            "SELECT version, payload FROM v2_contract_documents "
            "WHERE contract_type = 'ConceptCandidate' AND record_id = %s "
            "ORDER BY version DESC LIMIT 1",
            (candidate.record_id,),
        )
        if row is None:
            _append_doc(tx, candidate)
            return
        try:
            stored = ConceptCandidate.model_validate(row["payload"])
        except ValidationError:
            stored = None  # an unreadable row cannot prove identity; append the next version
        if stored is not None:
            if _candidate_fingerprint(stored) == _candidate_fingerprint(candidate):
                return
            if (
                live_proposal_hash is not None
                and stored.scope_sha256 == live_proposal_hash
                and candidate.scope_sha256 != live_proposal_hash
            ):
                return  # the live Gate 1 binding outranks a stale job's content
        fields = candidate.model_dump(mode="python", exclude={"content_sha256"})
        fields.update(version=int(row["version"]) + 1, updated_at=now)
        _append_doc(tx, ConceptCandidate.seal(**fields))

    # --- reads -------------------------------------------------------------------------------

    def _now(self) -> datetime:
        now = self._clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise SchemaInvalid("clock must return a timezone-aware instant")
        return now

    def _load_intake(self, tx: Tx, season_id: UUID) -> ConceptIntake | None:
        row = tx.fetchone(
            "SELECT payload, payload_sha256 FROM v2_contract_documents "
            "WHERE contract_type = 'ConceptIntake' AND record_id = %s AND current",
            (intake_record_id(season_id),),
        )
        if row is None:
            return None
        intake = ConceptIntake.model_validate(row["payload"])
        if canonical_hash(intake) != row["payload_sha256"]:
            raise Conflict("stored ConceptIntake payload hash is invalid", season_id=str(season_id))
        return intake

    @staticmethod
    def _current_proposal(tx: Tx, season_id: UUID) -> dict[str, Any] | None:
        return tx.fetchone(
            "SELECT * FROM season_proposals WHERE season_id = %s "
            "ORDER BY scope_version DESC LIMIT 1",
            (season_id,),
        )

    @staticmethod
    def _proposal_binds_candidate(
        tx: Tx, proposal: dict[str, Any], candidate: ConceptCandidate
    ) -> bool:
        """True when the current proposal row IS this candidate's exact scope."""
        try:
            scope = SeasonScope.model_validate(proposal["scope"])
        except ValidationError:
            return False
        if canonical_hash(scope) != candidate.scope_sha256:
            return False
        return (
            scope.title_th == candidate.title_th
            and scope.title_en == candidate.title_en
            and scope.expected_episode_count == candidate.episode_count
        )

    def _candidate_doc(
        self, tx: Tx, intake_id: UUID, candidate_id: UUID
    ) -> ConceptCandidate | None:
        row = tx.fetchone(
            "SELECT payload, payload_sha256 FROM v2_contract_documents "
            "WHERE contract_type = 'ConceptCandidate' AND record_id = %s AND current",
            (candidate_id,),
        )
        if row is None:
            return None
        candidate = ConceptCandidate.model_validate(row["payload"])
        if candidate.intake_id != intake_id:
            return None
        if canonical_hash(candidate) != row["payload_sha256"]:
            raise Conflict("stored ConceptCandidate payload hash is invalid")
        return candidate

    def _candidate_cards(self, tx: Tx, intake_id: UUID) -> list[CandidateCard]:
        cards: list[CandidateCard] = []
        for doc in _current_docs_by(tx, "ConceptCandidate", key="intake_id", value=str(intake_id)):
            try:
                candidate = ConceptCandidate.model_validate(doc.payload)
            except ValidationError:
                cards.append(
                    CandidateCard(
                        record_id=doc.record_id,
                        title_th="(unreadable)",
                        title_en="(unreadable)",
                        logline="the stored candidate document failed validation",
                        promise="",
                        episode_count=0,
                        scope_sha256="0" * 64,
                        rights_status="UNKNOWN",
                        rights_note="the stored document could not be verified",
                        version=doc.version,
                    )
                )
                continue
            if not _verified(candidate, doc):
                cards.append(
                    CandidateCard(
                        record_id=doc.record_id,
                        title_th="(unreadable)",
                        title_en="(unreadable)",
                        logline="the stored candidate document failed hash verification",
                        promise="",
                        episode_count=0,
                        scope_sha256="0" * 64,
                        rights_status="UNKNOWN",
                        rights_note="content hash does not match the stored payload hash",
                        version=doc.version,
                    )
                )
                continue
            rights = candidate.rights
            cards.append(
                CandidateCard(
                    record_id=candidate.record_id,
                    title_th=candidate.title_th,
                    title_en=candidate.title_en,
                    logline=candidate.logline,
                    promise=candidate.promise,
                    payoff_debt=list(candidate.payoff_debt),
                    escalation=list(candidate.escalation),
                    episode_count=candidate.episode_count,
                    scope_sha256=candidate.scope_sha256,
                    rights_status=str(getattr(rights, "status", "UNKNOWN")),
                    rights_note=str(getattr(rights, "note", "")),
                    version=candidate.version,
                )
            )
        cards.sort(key=lambda card: (card.version, str(card.record_id)))
        return cards

    # --- the workbench projection -------------------------------------------------------------

    def workbench(self, principal: Any, season_id: UUID) -> SeasonWorkbench:
        """Current typed V2 documents for the owner's season, honestly labelled."""
        from microdrama.core.auth import require_human_owner

        require_human_owner(principal)
        with self._db.transaction(readonly=True) as tx:
            require_season_access(tx, principal, season_id)
            season = tx.fetchone("SELECT * FROM seasons WHERE id = %s", (season_id,))
            assert season is not None
            view = self._workbench(tx, dict(season))
        return view

    def _workbench(self, tx: Tx, season: dict[str, Any]) -> SeasonWorkbench:
        season_id = season["id"]
        unknown: list[str] = []
        proposal = tx.fetchone(
            "SELECT * FROM season_proposals WHERE season_id = %s AND status = 'APPROVED' "
            "ORDER BY scope_version DESC LIMIT 1",
            (season_id,),
        ) or self._current_proposal(tx, season_id)
        scope: SeasonScope | None = None
        scope_doc = _absent("SeasonScope", "no proposal scope exists for this season yet")
        if proposal is not None:
            try:
                candidate_scope = SeasonScope.model_validate(proposal["scope"])
                if canonical_hash(candidate_scope) != proposal["scope_hash"]:
                    # Content that does not match the hash Gate 1 actually approved
                    # is not canon, whatever the row claims: show nothing for it.
                    scope = None
                    scope_doc = _absent(
                        "SeasonScope", "the stored scope content does not match its hash"
                    )
                    unknown.append("the current proposal's scope failed hash verification")
                else:
                    scope = candidate_scope
                    scope_doc = DocRef(
                        contract_type="SeasonScope",
                        record_id=proposal["id"],
                        version=int(proposal["scope_version"]),
                        content_sha256=proposal["scope_hash"],
                        summary=(
                            "approved" if proposal["status"] == "APPROVED" else proposal["status"]
                        ),
                    )
            except ValidationError:
                scope_doc = _absent("SeasonScope", "the stored proposal scope failed validation")
        episodes = tx.fetchall(
            "SELECT * FROM episodes WHERE season_id = %s ORDER BY episode_number, id",
            (season_id,),
        )
        season_docs = self._season_level_docs(tx, season_id, unknown)
        season_assets = _season_asset_ids(tx, season_id)
        subjects, prop_sheets, location_layouts = self._season_subjects(
            tx, season_id, season_assets, scope, season_docs.wardrobe_bibles, episodes
        )
        asset_sheets = self._asset_sheets(tx, subjects, season_assets)
        episode_cards = [self._episode_workbench(tx, dict(row), unknown) for row in episodes]
        if not episodes:
            unknown.append("no episodes exist for this season yet")
        return SeasonWorkbench(
            season_id=season_id,
            season_state=season["state"],
            title_th=scope.title_th if scope else season["title_th"],
            title_en=scope.title_en if scope else season["title_en"],
            arc=[beat.model_dump(mode="json") for beat in scope.arc] if scope else [],
            characters=[c.model_dump(mode="json") for c in scope.characters] if scope else [],
            scope_doc=scope_doc,
            story_ledger=season_docs.story_ledger,
            character_logic=season_docs.character_logic,
            secret_ledger=season_docs.secret_ledger,
            style_bible=season_docs.style_bible,
            wardrobe_bibles=season_docs.wardrobe_bibles,
            prop_sheets=prop_sheets,
            location_layouts=location_layouts,
            asset_sheets=asset_sheets,
            episodes=episode_cards,
            unknown_notes=unknown,
        )

    def _season_level_docs(self, tx: Tx, season_id: UUID, unknown: list[str]) -> _SeasonDocs:
        def one(contract_type: str, model: type, summary_of: Any) -> DocRef:
            rows = _current_docs_by(tx, contract_type, key="season_id", value=str(season_id))
            if len(rows) > 1:
                unknown.append(f"multiple current {contract_type} documents; refusing to pick one")
                return _absent(contract_type, "ambiguous current documents")
            if not rows:
                return _absent(contract_type, f"no current {contract_type} is recorded yet")
            doc = rows[0]
            try:
                record = model.model_validate(doc.payload)
            except ValidationError:
                unknown.append(f"a current {contract_type} failed validation")
                return _absent(contract_type, "stored document failed validation")
            if not _verified(record, doc):
                unknown.append(f"a current {contract_type} failed hash verification")
                return _absent(contract_type, "content hash does not match the stored payload")
            return DocRef(
                contract_type=contract_type,
                record_id=doc.record_id,
                version=doc.version,
                content_sha256=doc.payload_sha256,
                summary=summary_of(record)[:200],
            )

        character_logic: list[DocRef] = []
        for doc in _current_docs_by(tx, "CharacterLogic", key="season_id", value=str(season_id)):
            try:
                record = CharacterLogic.model_validate(doc.payload)
            except ValidationError:
                unknown.append("a current CharacterLogic document failed validation")
                character_logic.append(_absent("CharacterLogic", "unreadable document"))
                continue
            if not _verified(record, doc):
                unknown.append("a current CharacterLogic document failed hash verification")
                character_logic.append(_absent("CharacterLogic", "hash mismatch"))
                continue
            character_logic.append(
                DocRef(
                    contract_type="CharacterLogic",
                    record_id=doc.record_id,
                    version=doc.version,
                    content_sha256=doc.payload_sha256,
                    summary=f"{record.character_id}: {record.observable_goal}",
                )
            )
        wardrobe_bibles: list[DocRef] = []
        for doc in _current_docs_by(tx, "WardrobeBible", key="season_id", value=str(season_id)):
            try:
                record = WardrobeBible.model_validate(doc.payload)
            except ValidationError:
                unknown.append("a current WardrobeBible document failed validation")
                wardrobe_bibles.append(_absent("WardrobeBible", "unreadable document"))
                continue
            if not _verified(record, doc):
                unknown.append("a current WardrobeBible document failed hash verification")
                wardrobe_bibles.append(_absent("WardrobeBible", "hash mismatch"))
                continue
            wardrobe_bibles.append(
                DocRef(
                    contract_type="WardrobeBible",
                    record_id=doc.record_id,
                    version=doc.version,
                    content_sha256=doc.payload_sha256,
                    summary=f"{record.character_id}: {len(record.outfits)} outfit(s)",
                )
            )
        return _SeasonDocs(
            story_ledger=one("SeasonStoryLedger", SeasonStoryLedger, lambda record: record.promise),
            secret_ledger=one(
                "SecretLedger", SecretLedger, lambda record: f"{len(record.secrets)} secret(s)"
            ),
            style_bible=one("StyleBible", StyleBible, lambda record: record.medium),
            character_logic=character_logic,
            wardrobe_bibles=wardrobe_bibles,
        )

    def _season_subjects(
        self,
        tx: Tx,
        season_id: UUID,
        season_assets: set[str],
        scope: SeasonScope | None,
        wardrobe_bibles: list[DocRef],
        episodes: list[dict[str, Any]],
    ) -> tuple[set[str], list[DocRef], list[DocRef]]:
        """Subject ids this season's typed sheets may be scoped to (characters, props…).

        Only VERIFIED episode packs contribute prop/location ids: an unverified
        pack (validation or hash failure) must not steer which sheets display.
        """
        subjects: set[str] = set()
        if scope is not None:
            subjects.update(character.character_id for character in scope.characters)
        for doc in wardrobe_bibles:
            if doc.record_id is None:
                continue
            row = tx.fetchone(
                "SELECT record_id, version, payload, payload_sha256 FROM v2_contract_documents "
                "WHERE contract_type = 'WardrobeBible' AND record_id = %s AND current",
                (doc.record_id,),
            )
            if row is not None:
                bible = _verified_model(WardrobeBible, _DocRow(dict(row)))
                if bible is not None:
                    subjects.update(outfit.outfit_id for outfit in bible.outfits)
        prop_ids: set[str] = set()
        location_ids: set[str] = set()
        for episode in episodes:
            for doc in _current_docs_by(
                tx, "EpisodePack", key="episode_id", value=str(episode["id"])
            ):
                pack = _verified_model(EpisodePack, doc)
                if pack is None:
                    continue  # the episode card reports the verification failure
                for scene in pack.scenes:
                    prop_ids.update(scene.prop_ids)
                    if scene.location_id:
                        location_ids.add(scene.location_id)
        return (
            subjects | prop_ids | location_ids | {"style"},
            self._prop_sheets(tx, prop_ids, season_assets),
            self._location_layouts(tx, location_ids, season_assets),
        )

    def _prop_sheets(self, tx: Tx, prop_ids: set[str], season_assets: set[str]) -> list[DocRef]:
        """Sheets for this season's props only, proven by their asset rows.

        A prop id is a shared identifier (any season may have a ``ledger``), so a
        matching sheet is displayable only when its ``asset_id`` is one of THIS
        season's assets and the document verifies; several proven matches are an
        honest unknown, never a guess.
        """
        refs: list[DocRef] = []
        for prop_id in sorted(prop_ids):
            proven: list[tuple[PropSheet, _DocRow]] = []
            for doc in _current_docs_by(tx, "PropSheet", key="prop_id", value=prop_id):
                sheet = _verified_model(PropSheet, doc)
                if sheet is not None and str(sheet.asset_id) in season_assets:
                    proven.append((sheet, doc))
            if len(proven) == 1:
                sheet, doc = proven[0]
                refs.append(
                    DocRef(
                        contract_type="PropSheet",
                        record_id=doc.record_id,
                        version=doc.version,
                        content_sha256=doc.payload_sha256,
                        summary=prop_id,
                    )
                )
            elif len(proven) > 1:
                refs.append(
                    _absent("PropSheet", f"prop {prop_id}: ambiguous proven current sheets")
                )
            else:
                refs.append(_absent("PropSheet", f"prop {prop_id}: no proven current sheet"))
        return refs

    def _location_layouts(
        self, tx: Tx, location_ids: set[str], season_assets: set[str]
    ) -> list[DocRef]:
        """Layouts proven through this season's location plate assets.

        A LocationLayout record carries no asset reference; it is minted from the
        same empty-plate asset as the season's location AssetSheet, so
        ``geometry_sha256`` equality against a proven plate's asset hash is the
        provenance chain. Shared plate bytes across seasons are an honest unknown.
        """
        plate_shas: set[str] = set()
        for doc in _current_docs_by(tx, "AssetSheet", key="asset_role", value="location"):
            sheet = _verified_model(AssetSheet, doc)
            if sheet is not None and str(sheet.asset_id) in season_assets:
                plate_shas.add(sheet.asset_sha256)
        refs: list[DocRef] = []
        for location_id in sorted(location_ids):
            proven = [
                doc
                for doc in _current_docs_by(
                    tx, "LocationLayout", key="location_id", value=location_id
                )
                if (layout := _verified_model(LocationLayout, doc)) is not None
                and layout.geometry_sha256 in plate_shas
            ]
            if len(proven) == 1:
                doc = proven[0]
                refs.append(
                    DocRef(
                        contract_type="LocationLayout",
                        record_id=doc.record_id,
                        version=doc.version,
                        content_sha256=doc.payload_sha256,
                        summary=location_id,
                    )
                )
            elif len(proven) > 1:
                refs.append(
                    _absent("LocationLayout", f"location {location_id}: ambiguous proven layouts")
                )
            else:
                refs.append(
                    _absent("LocationLayout", f"location {location_id}: no proven current layout")
                )
        return refs

    def _asset_sheets(self, tx: Tx, subjects: set[str], season_assets: set[str]) -> list[DocRef]:
        """Asset sheets for this season's subjects only, proven by their asset rows."""
        refs: list[DocRef] = []
        for subject in sorted(subjects):
            for doc in _current_docs_by(tx, "AssetSheet", key="subject_id", value=subject):
                sheet = _verified_model(AssetSheet, doc)
                if sheet is None or str(sheet.asset_id) not in season_assets:
                    continue
                refs.append(
                    DocRef(
                        contract_type="AssetSheet",
                        record_id=doc.record_id,
                        version=doc.version,
                        content_sha256=doc.payload_sha256,
                        summary=f"{sheet.asset_role}/{subject} asset {sheet.asset_id}",
                    )
                )
        if refs:
            refs.sort(key=lambda ref: (ref.summary, str(ref.record_id)))
        return refs

    def _episode_workbench(
        self, tx: Tx, episode: dict[str, Any], unknown: list[str]
    ) -> EpisodeWorkbench:
        episode_id = episode["id"]
        label = episode["episode_number"]
        pack_doc = _absent("EpisodePack", "no current episode pack is recorded yet")
        packs = _current_docs_by(tx, "EpisodePack", key="episode_id", value=str(episode_id))
        if len(packs) > 1:
            unknown.append(f"episode {label}: multiple current EpisodePack documents")
            pack_doc = _absent("EpisodePack", "ambiguous current documents")
        elif packs:
            doc = packs[0]
            try:
                pack = EpisodePack.model_validate(doc.payload)
                if not _verified(pack, doc):
                    raise ValueError("hash mismatch")
                pack_doc = DocRef(
                    contract_type="EpisodePack",
                    record_id=doc.record_id,
                    version=doc.version,
                    content_sha256=doc.payload_sha256,
                    summary=(
                        f"{len(pack.scenes)} scene(s), target {pack.duration_target_ms // 1000}s"
                    ),
                )
            except (ValidationError, ValueError):
                unknown.append(f"episode {label}: current EpisodePack failed verification")
                pack_doc = _absent("EpisodePack", "stored document failed verification")
        directing_doc = _absent("DirectingManifest", "no current directing plan is recorded yet")
        sections: list[SectionCard] = []
        shots: list[ShotCard] = []
        manifests = _current_docs_by(
            tx, "DirectingManifest", key="episode_id", value=str(episode_id)
        )
        if len(manifests) > 1:
            unknown.append(f"episode {label}: multiple current DirectingManifest documents")
            directing_doc = _absent("DirectingManifest", "ambiguous current documents")
        elif manifests:
            doc = manifests[0]
            try:
                manifest = DirectingManifest.model_validate(doc.payload)
                if not _verified(manifest, doc):
                    raise ValueError("hash mismatch")
                directing_doc = DocRef(
                    contract_type="DirectingManifest",
                    record_id=doc.record_id,
                    version=doc.version,
                    content_sha256=doc.payload_sha256,
                    summary=(
                        f"{len(manifest.shots)} shot(s) in {len(manifest.sections)} section(s)"
                    ),
                )
                sections = [
                    SectionCard(
                        section_id=section.section_id,
                        sequence=section.sequence,
                        duration_ms=section.duration_ms,
                        shot_ids=list(section.shot_ids),
                    )
                    for section in manifest.sections
                ]
                shots = [
                    ShotCard(
                        shot_id=shot.shot_id,
                        sequence=shot.sequence,
                        duration_ms=shot.duration_ms,
                        scene_id=shot.scene_id,
                        beat_id=shot.beat_id,
                        section_id=shot.section_id,
                    )
                    for shot in sorted(manifest.shots, key=lambda item: item.sequence)
                ]
            except (ValidationError, ValueError):
                unknown.append(f"episode {label}: current DirectingManifest failed verification")
                directing_doc = _absent("DirectingManifest", "stored document failed verification")
        wardrobe: list[DocRef] = []
        for doc in _current_docs_by(
            tx, "SceneWardrobeAssignment", key="episode_id", value=str(episode_id)
        ):
            assignment = _verified_model(SceneWardrobeAssignment, doc)
            if assignment is None:
                unknown.append(f"episode {label}: a wardrobe assignment failed verification")
                wardrobe.append(
                    _absent("SceneWardrobeAssignment", "stored document failed verification")
                )
                continue
            wardrobe.append(
                DocRef(
                    contract_type="SceneWardrobeAssignment",
                    record_id=doc.record_id,
                    version=doc.version,
                    content_sha256=doc.payload_sha256,
                    summary=(
                        f"{assignment.scene_id}/{assignment.character_id}"
                        f" -> outfit {assignment.outfit_id}"
                    ),
                    media_asset_id=assignment.asset_id,
                )
            )
        prompts: list[DocRef] = []
        for doc in _current_docs_by(tx, "PromptManifest", key="episode_id", value=str(episode_id)):
            manifest = _verified_model(PromptManifest, doc)
            if manifest is None:
                unknown.append(f"episode {label}: a prompt manifest failed verification")
                prompts.append(_absent("PromptManifest", "stored document failed verification"))
                continue
            prompts.append(
                DocRef(
                    contract_type="PromptManifest",
                    record_id=doc.record_id,
                    version=doc.version,
                    content_sha256=doc.payload_sha256,
                    summary=(
                        f"shot {manifest.shot_id}"
                        f" ({manifest.shot_duration_ms // 1000}s,"
                        f" {len(manifest.bindings)} reference binding(s))"
                    ),
                )
            )
        return EpisodeWorkbench(
            episode_id=episode_id,
            episode_number=int(episode["episode_number"]),
            state=str(episode["state"]),
            outcome=episode["outcome"],
            pack=pack_doc,
            directing_manifest=directing_doc,
            sections=sections,
            shots=shots,
            wardrobe_assignments=wardrobe,
            prompt_manifests=prompts,
        )


__all__ = [
    "INTAKE_GENERATION_KEY",
    "INTAKE_JOB_TYPE",
    "INTAKE_TRIGGER",
    "IntakeAnswers",
    "IntakeConfig",
    "IntakeService",
    "IntakeView",
    "SELECTION_TRIGGER_PREFIX",
    "answers_from_form",
    "check_form_fields",
    "intake_record_id",
    "step_answers",
    "wizard_key",
    "wizard_step",
]
