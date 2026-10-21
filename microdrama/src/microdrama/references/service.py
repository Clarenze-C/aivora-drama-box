"""Reference/voice pipeline service (T011): anchors, dialogue audio, identity locks.

``prepare_episode`` is the paid pipeline step behind the frozen
``references.prepare_episode`` job (production queue, ``EpisodeStepInput``). For the
episode's current script/manifest it:

1. claims the episode row (``episodes.correlation_id``, the house claim column) and
   moves SCRIPTING → REFERENCES;
2. refuses, typed and before any paid dispatch, when a later episode has no
   episode-one identity lock (IMP-01/AT-03);
3. checks the whole plan's worst case against the episode allowance before anything
   dispatches (SPEC §6);
4. ensures every anchor through the full-key cache — lock-bound keys resolve to the
   LOCKED version first, then the season cache, then a paid generation with a real
   reservation per call;
5. synthesizes each dialogue line through the voice provider, measuring
   ``actual_duration_ms`` from the actual WAV bytes;
6. writes a NEW script version (``voice_id`` + ``actual_duration_ms`` filled — the
   fields T010 deliberately left None) and a NEW manifest version (``voice_ids``,
   ``required_reference_asset_ids``, ``reference_lock_version`` filled), then moves
   REFERENCES → RENDERING.

Everything is idempotent: anchors cache, line assets are content-keyed, budget keys
and provider tokens are deterministic — a replay dispatches nothing paid.

Identity-lock surface (consumed by T008's Gate 2, T014's render dispatch, T015's
edit step): ``identity_lock_hook``, ``attach_identity_lock``,
``render_request_bindings``, ``mark_reviewed_in_package``, ``cast_package_assets``,
``explicit_change``. Explicit changes version references and ride the ordinary final
gate: new anchor assets change the cast package, and cast assets are material to
``review.is_material_change``, so the changed episode needs its ordinary Gate 2.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from microdrama.budget import BudgetService
from microdrama.budget.ledger import episode_account_id, lock_account
from microdrama.config import Settings
from microdrama.contracts.enums import (
    AssetKind,
    AssetState,
    EpisodeState,
    PriceUnit,
    PrincipalKind,
)
from microdrama.contracts.errors import (
    BudgetExhausted,
    Conflict,
    DuplicateSemanticKey,
    IdentityLockRequired,
    InvalidTransition,
    MicrodramaError,
    NotFound,
    SchemaInvalid,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.infra import Clock, IdGenerator, ObjectStore
from microdrama.contracts.media import AssetDescriptor
from microdrama.contracts.principals import Principal
from microdrama.contracts.providers import GenerationProvider
from microdrama.contracts.season import DialogueLine, Script, SeasonScope, ShotManifest
from microdrama.core.events import append_event
from microdrama.core.registry.rights import RightsRegistry
from microdrama.core.state_machine import transition_episode
from microdrama.persistence import register_asset
from microdrama.persistence.db import Database, Tx, insert_row, jsonb, update_with_revision
from microdrama.references import anchors as A
from microdrama.references.config import ReferencesConfig
from microdrama.references.generation import (
    VOICE_ANCHOR_OPERATION,
    CallPlan,
    GeneratedBytes,
    GenerationAdapter,
    build_image_request,
    build_voice_request,
    check_rights,
    image_call_plan,
    voice_call_plan,
)
from microdrama.references.identity_lock import (
    IdentityLockHook,
    IdentityLocks,
    mark_reviewed,
)
from microdrama.references.media import verify_generated
from microdrama.references.models import (
    AnchorSpec,
    AnchorView,
    ChangeOutcome,
    LineAudio,
    LockMember,
    LockView,
    PrepareOutcome,
    PrepareStatus,
    RefKind,
    RenderBindings,
)

_PREPARE_STATES = (EpisodeState.SCRIPTING.value, EpisodeState.REFERENCES.value)
_CHANGEABLE_STATES = (
    EpisodeState.PLANNED.value,
    EpisodeState.SCRIPTING.value,
    EpisodeState.REFERENCES.value,
    EpisodeState.RENDERING.value,
    EpisodeState.ASSEMBLING.value,
    EpisodeState.AI_REVIEW.value,
    EpisodeState.AWAITING_FINAL_REVIEW.value,
)


def _json_safe(payload: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in payload.items():
        try:
            canonical_hash(value)
            safe[key] = value
        except (TypeError, ValueError):
            safe[key] = str(value)
    return safe


@dataclass
class _Claim:
    episode_id: UUID
    season_id: UUID
    episode_number: int
    revision: int
    identity_lock_id: UUID | None
    lock_version: int | None
    scope: SeasonScope
    script: Script
    manifest: ShotManifest
    claim_token: UUID


@dataclass(frozen=True)
class _AnchorPlan:
    spec: AnchorSpec
    plan: CallPlan


@dataclass(frozen=True)
class _LinePlan:
    semantic_key: str
    plan: CallPlan


class ReferencesService:
    """Anchors, dialogue audio and identity locks. Construct once per process."""

    def __init__(
        self,
        db: Database,
        clock: Clock,
        ids: IdGenerator,
        settings: Settings,
        *,
        budget: BudgetService,
        store: ObjectStore,
        image_provider: GenerationProvider | None = None,
        voice_provider: GenerationProvider | None = None,
        rights: RightsRegistry | None = None,
        config: ReferencesConfig | None = None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._ids = ids
        self._settings = settings
        self._budget = budget
        self._store = store
        self._image = image_provider
        self._voice = voice_provider
        self._rights = rights
        self._config = config or ReferencesConfig()
        self._adapter = GenerationAdapter(
            budget=budget, clock=clock, settings=settings, config=self._config
        )
        self._locks = IdentityLocks(clock)
        self._id_lock = threading.Lock()
        self._principal = Principal(
            principal_id="svc:references-worker", kind=PrincipalKind.SERVICE_WORKER
        )

    # --- plumbing -------------------------------------------------------------------------

    def _new_id(self) -> UUID:
        with self._id_lock:
            return self._ids.new_id()

    def _now(self) -> datetime:
        now = self._clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise SchemaInvalid("clock must return a timezone-aware instant")
        return now

    @property
    def config(self) -> ReferencesConfig:
        return self._config

    # --- identity-lock surface ------------------------------------------------------------

    def identity_lock_hook(self) -> IdentityLockHook:
        """The real ``ApprovalHook`` the integrator passes to ``ReviewService``."""
        return IdentityLockHook(self._locks)

    def current_lock(self, season_id: UUID) -> LockView | None:
        with self._db.transaction(readonly=True) as tx:
            row = IdentityLocks.current_lock_row(tx, season_id)
            if row is None:
                return None
            members = IdentityLocks.members(tx, row["id"])
        return LockView(
            lock_id=row["id"],
            season_id=row["season_id"],
            source_episode_id=row["source_episode_id"],
            version=row["version"],
            approval_event_id=row["approval_event_id"],
            release_package_hash=row["release_package_hash"],
            created_at=str(row["created_at"]),
            members=[
                LockMember(
                    ref_kind=RefKind(m["ref_kind"]),
                    ref_key=m["ref_key"],
                    version=m["version"],
                    asset_id=m["asset_id"],
                    content_sha256=m["content_sha256"],
                    state=m["state"],
                    character_key=m["character_key"],
                )
                for m in members
            ],
        )

    def mark_reviewed_in_package(self, episode_id: UUID) -> int:
        """Mark the current package's cast reference versions reviewed (packaging step).

        The integrator's packaging flow calls this when it stores a release package:
        PROVISIONAL cast versions become ACCEPTED with ``reviewed_in_package_id`` set,
        which is exactly what the lock hook requires — versions never reviewed in a
        package never become lockable.
        """
        from microdrama.review.packages import current_package

        now = self._now()
        with self._db.transaction() as tx:
            stored = current_package(tx, episode_id)
            if stored is None:
                raise NotFound("episode has no current release package", episode_id=str(episode_id))
            episode = tx.fetchone("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))
            if episode is None:
                raise NotFound("episode not found", episode_id=str(episode_id))
            return mark_reviewed(
                tx,
                season_id=episode["season_id"],
                package_row_id=stored.row_id,
                cast_asset_ids=list(stored.package.cast_package_asset_ids),
                now=now,
            )

    def cast_package_assets(self, episode_id: UUID) -> list[UUID]:
        """Anchor asset ids the packaging step should include in the cast package.

        The episode-one cast package reviews the WHOLE cast — every live reference
        version of the season (faces, wardrobes, sets, style, voice anchors), not
        only the assets this episode's shots happen to require. New cast reviewed
        here becomes lockable; anything left out stays provisional.
        """
        with self._db.transaction(readonly=True) as tx:
            episode = tx.fetchone("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))
            if episode is None:
                raise NotFound("episode not found", episode_id=str(episode_id))
            rows = tx.fetchall(
                "SELECT asset_id FROM reference_versions WHERE season_id = %s "
                "AND state = ANY(%s) ORDER BY asset_id",
                (episode["season_id"], ["PROVISIONAL", "ACCEPTED", "LOCKED"]),
            )
        return [row["asset_id"] for row in rows]

    def attach_identity_lock(self, episode_id: UUID) -> UUID:
        """Adopt the season's current lock onto a later episode created after the lock."""
        with self._db.transaction() as tx:
            episode = tx.fetchone("SELECT * FROM episodes WHERE id = %s FOR UPDATE", (episode_id,))
            if episode is None:
                raise NotFound("episode not found", episode_id=str(episode_id))
            if episode["identity_lock_id"] is not None:
                return episode["identity_lock_id"]
            lock = IdentityLocks.current_lock_row(tx, episode["season_id"])
            if lock is None:
                raise IdentityLockRequired(
                    "the season has no identity lock to attach",
                    episode_id=str(episode_id),
                    episode_number=episode["episode_number"],
                )
            update_with_revision(
                tx,
                "episodes",
                episode_id,
                episode["revision"],
                {"identity_lock_id": lock["id"]},
                now=self._now(),
            )
            return lock["id"]

    def render_request_bindings(self, episode_id: UUID) -> RenderBindings:
        """What a render dispatch for this episode must use (the IMP-01 render gate).

        Episode one renders before its own Gate 2 and is exempt. Every later episode
        needs the episode-one identity lock — refused typed *before* any dispatch —
        and a lock whose members are all still LOCKED (a member superseded after the
        lock breaks it; renders refuse rather than silently change identity).
        """
        with self._db.transaction(readonly=True) as tx:
            episode = tx.fetchone("SELECT * FROM episodes WHERE id = %s", (episode_id,))
            if episode is None:
                raise NotFound("episode not found", episode_id=str(episode_id))
            # The lock gate comes FIRST: a later episode without the lock has no valid
            # manifest at all (the frozen contract refuses one), so the typed refusal
            # must never surface as a missing manifest.
            lock_id = episode["identity_lock_id"]
            lock_version: int | None = None
            locked_keys: list[str] = []
            if episode["episode_number"] > 1:
                if lock_id is None:
                    season_lock = IdentityLocks.current_lock_row(tx, episode["season_id"])
                    hint = (
                        "the season has a lock this episode has not adopted (attach_identity_lock)"
                        if season_lock is not None
                        else "episode one has not been approved at Gate 2 yet"
                    )
                    raise IdentityLockRequired(
                        "later-episode render dispatch requires the episode-one identity lock",
                        episode_id=str(episode_id),
                        episode_number=episode["episode_number"],
                        hint=hint,
                    )
                lock = tx.fetchone("SELECT * FROM identity_locks WHERE id = %s", (lock_id,))
                if lock is None:
                    raise Conflict(
                        "episode names an identity lock that no longer exists",
                        lock_id=str(lock_id),
                    )
                broken = IdentityLocks.broken_member_keys(tx, lock_id)
                if broken:
                    raise Conflict(
                        "the identity lock names superseded versions; later-episode renders "
                        "refuse until a new Gate 2 approval creates a new lock version",
                        broken=broken[:10],
                    )
                lock_version = lock["version"]
                locked_keys = sorted(
                    f"{m['ref_kind']}:{m['ref_key']}" for m in IdentityLocks.members(tx, lock_id)
                )
            manifest_row = self._current_manifest_row(tx, episode_id)
            manifest = ShotManifest.model_validate(manifest_row["body"])
            unfilled = [
                shot.shot_id for shot in manifest.shots if not shot.required_reference_asset_ids
            ]
            if unfilled:
                raise Conflict(
                    "references are not prepared for this episode; the manifest carries no "
                    "required reference assets",
                    shots=unfilled[:10],
                )
            used_assets = sorted(
                {a for shot in manifest.shots for a in shot.required_reference_asset_ids}
            )
            used_keys = {
                f"{kind.value}:{key}"
                for kind, key in self._ref_keys_of_assets(tx, episode["season_id"], used_assets)
            }
            return RenderBindings(
                episode_id=episode_id,
                episode_number=episode["episode_number"],
                lock_id=lock_id,
                lock_version=lock_version,
                manifest_id=manifest_row["id"],
                reference_asset_ids=used_assets,
                locked_ref_keys=sorted(set(locked_keys) & used_keys) if locked_keys else [],
                provisional_ref_keys=sorted(used_keys - set(locked_keys)) if locked_keys else [],
            )

    @staticmethod
    def _ref_keys_of_assets(
        tx: Tx, season_id: UUID, asset_ids: list[UUID]
    ) -> list[tuple[RefKind, str]]:
        rows = tx.fetchall(
            "SELECT ref_kind, ref_key FROM reference_versions WHERE season_id = %s "
            "AND asset_id = ANY(%s)",
            (season_id, asset_ids),
        )
        return [(RefKind(r["ref_kind"]), r["ref_key"]) for r in rows]

    # --- prepare (the paid pipeline step) ---------------------------------------------------

    def prepare_episode(self, episode_id: UUID, *, trigger: str = "pipeline") -> PrepareOutcome:
        """Ensure anchors and dialogue audio, then fill the script/manifest (idempotent)."""
        del trigger  # audit-only; the budget keys are the episode and the content
        claim = self._claim(episode_id)
        if claim is None:
            return self._replay_outcome(episode_id)
        try:
            return self._execute(claim)
        except MicrodramaError as exc:
            self._fail(claim, exc)
            raise

    def _claim(self, episode_id: UUID) -> _Claim | None:
        """Lock the episode, refuse typed blockers, open/fit the budget, claim the row.

        Returns None when the current script/manifest are already filled (a replay —
        detected before the state gate, so re-invoking the step after a successful
        run, whatever stage the episode has reached since, dispatches nothing).
        """
        now = self._now()
        with self._db.transaction() as tx:
            episode = tx.fetchone("SELECT * FROM episodes WHERE id = %s FOR UPDATE", (episode_id,))
            if episode is None:
                raise NotFound("episode not found", episode_id=str(episode_id))
            if episode["outcome"] is not None:
                raise InvalidTransition(
                    f"episode carries outcome {episode['outcome']}", outcome=episode["outcome"]
                )
            # IMP-01/AT-03: the lock gate comes FIRST — a later episode without the
            # lock can hold no valid manifest (the frozen contract refuses one), and
            # the typed refusal must precede every read, hold and dispatch.
            identity_lock_id = episode["identity_lock_id"]
            lock_version: int | None = None
            if episode["episode_number"] > 1:
                if identity_lock_id is None:
                    raise IdentityLockRequired(
                        "later-episode references require the episode-one identity lock",
                        episode_id=str(episode_id),
                        episode_number=episode["episode_number"],
                    )
                lock = tx.fetchone(
                    "SELECT version FROM identity_locks WHERE id = %s", (identity_lock_id,)
                )
                if lock is None:
                    raise Conflict("episode names a missing identity lock")
                lock_version = lock["version"]
            if episode["state"] not in _PREPARE_STATES and not self._already_prepared(
                tx, episode_id
            ):
                # A filled manifest anywhere past REFERENCES is a replay, not a refusal.
                raise InvalidTransition(
                    f"episode is {episode['state']}; references need SCRIPTING or REFERENCES",
                    state=episode["state"],
                )
            script = Script.model_validate(self._current_script_row(tx, episode_id)["body"])
            manifest = ShotManifest.model_validate(
                self._current_manifest_row(tx, episode_id)["body"]
            )
            if self._filled(script, manifest):
                return None
            if episode["correlation_id"] is not None:
                raise Conflict(
                    "another production step already claimed this episode; wait for it to "
                    "finish or clear the claim with evidence",
                    episode_id=str(episode_id),
                    claim_id=str(episode["correlation_id"]),
                )
            season = tx.fetchone(
                "SELECT * FROM seasons WHERE id = %s FOR UPDATE", (episode["season_id"],)
            )
            if season is None:
                raise NotFound("season not found", season_id=str(episode["season_id"]))
            proposal = tx.fetchone(
                "SELECT scope FROM season_proposals WHERE season_id = %s AND status = 'APPROVED'",
                (season["id"],),
            )
            if proposal is None:
                raise Conflict("season has no approved scope; references run inside it")
            scope = SeasonScope.model_validate(proposal["scope"])

            self._budget.open_episode_account(
                tx,
                season_id=season["id"],
                episode_id=episode_id,
                policy=scope.cost_policy,
            )
            account_id = episode_account_id(tx, episode_id)
            account = lock_account(tx, account_id)
            planned = self._plan(
                episode_id, season["id"], script, manifest, scope, identity_lock_id
            )
            planned_worst = sum(step.plan.worst_case_micro_usd for step in planned)
            if account.committed + planned_worst + account.shutdown_reserve > account.cap:
                raise BudgetExhausted(
                    "planned references worst case does not fit the episode allowance; "
                    "nothing is dispatched",
                    account_id=str(account_id),
                    cap_micro_usd=account.cap,
                    committed_micro_usd=account.committed,
                    planned_worst_case_micro_usd=planned_worst,
                    shutdown_reserve_micro_usd=account.shutdown_reserve,
                )
            claim_token = self._new_id()
            revision = episode["revision"]
            if episode["state"] == EpisodeState.SCRIPTING.value:
                revision = transition_episode(
                    tx,
                    episode_id=episode_id,
                    to=EpisodeState.REFERENCES,
                    expected_revision=episode["revision"],
                    actor=self._principal,
                    now=now,
                    correlation_id=claim_token,
                )
            update_with_revision(
                tx, "episodes", episode_id, revision, {"correlation_id": claim_token}, now=now
            )
            return _Claim(
                episode_id=episode_id,
                season_id=season["id"],
                episode_number=episode["episode_number"],
                revision=revision + 1,
                identity_lock_id=identity_lock_id,
                lock_version=lock_version,
                scope=scope,
                script=script,
                manifest=manifest,
                claim_token=claim_token,
            )

    # --- planning ---------------------------------------------------------------------------

    def _anchor_routes(self, spec: AnchorSpec) -> tuple[str, str]:
        if spec.is_voice:
            return self._config.voice_model_config_ref, self._config.voice_rights_route_id
        return self._config.image_model_config_ref, self._config.image_rights_route_id

    def _attempt_key(self, base: str) -> str:
        """Suffix the semantic key with this attempt's number when earlier attempts exist.

        A provider FAILED job is terminal per client token, so a retry is a NEW paid
        step. The attempt count is derived durably from the reservations table (a1 is
        the bare key), keeping crash-retries idempotent: the same committed attempt
        count yields the same key and the same provider token.
        """
        with self._db.transaction(readonly=True) as tx:
            used = tx.fetchval(
                "SELECT COUNT(*) FROM reservations WHERE semantic_key = %s OR semantic_key LIKE %s",
                (base, base + ":a%"),
            )
        attempt = int(used or 0)
        return base if attempt == 0 else f"{base}:a{attempt + 1}"

    def _anchor_semantic_key(self, season_id: UUID, spec: AnchorSpec, version: int) -> str:
        # The version is part of the key: a regenerated version is a NEW paid step
        # with its own provider token — it must never replay the old job's bytes.
        return f"refs:{season_id}:anchor:{spec.ref_kind.value}:{spec.ref_key}:v{version}"

    def _line_semantic_key(self, episode_id: UUID, line_id: str) -> str:
        return f"refs:{episode_id}:line:{line_id}"

    def _plan(
        self,
        episode_id: UUID,
        season_id: UUID,
        script: Script,
        manifest: ShotManifest,
        scope: SeasonScope,
        identity_lock_id: UUID | None,
    ) -> list[_AnchorPlan | _LinePlan]:
        """Every prospective paid step of this preparation (cache misses only)."""
        plans: list[_AnchorPlan | _LinePlan] = []
        for spec in A.plan_anchors(script, manifest, scope, self._config):
            if self._lookup_anchor(season_id, spec, identity_lock_id) is not None:
                continue  # lock-bound or cached: no paid step
            with self._db.transaction(readonly=True) as tx:
                version = A.next_version(tx, season_id, spec.ref_kind, spec.ref_key)
            if spec.is_voice:
                if self._voice is None or self._config.voice_price is None:
                    continue
                plan = voice_call_plan(
                    self._anchor_semantic_key(season_id, spec, version),
                    self._voice.provider_id,
                    self._config,
                    characters=len(spec.prompt),
                    operation_kind=VOICE_ANCHOR_OPERATION,
                )
            else:
                if self._image is None or self._config.image_price is None:
                    continue
                plan = image_call_plan(
                    self._anchor_semantic_key(season_id, spec, version),
                    self._image.provider_id,
                    self._config,
                )
            if plan is not None:
                plans.append(_AnchorPlan(spec=spec, plan=plan))
        if self._voice is not None and self._config.voice_price is not None:
            for scene in script.scenes:
                for line in scene.lines:
                    if self._line_asset_exists(episode_id, line.line_id, line.text_th):
                        continue
                    plan = voice_call_plan(
                        self._line_semantic_key(episode_id, line.line_id),
                        self._voice.provider_id,
                        self._config,
                        characters=len(line.text_th),
                    )
                    if plan is not None:
                        plans.append(
                            _LinePlan(
                                semantic_key=self._line_semantic_key(episode_id, line.line_id),
                                plan=plan,
                            )
                        )
        return plans

    def _lookup_anchor(
        self, season_id: UUID, spec: AnchorSpec, identity_lock_id: UUID | None
    ) -> dict[str, Any] | None:
        """Lock-bound → season cache → newest live version (None = paid generation)."""
        with self._db.transaction(readonly=True) as tx:
            if identity_lock_id is not None:
                locked = A.locked_member(tx, identity_lock_id, spec.ref_kind, spec.ref_key)
                if locked is not None:
                    if locked["state"] != "LOCKED":
                        raise Conflict(
                            "the identity lock names a non-LOCKED version for this anchor; "
                            "later episodes refuse to silently change identity",
                            ref_key=spec.ref_key,
                            state=locked["state"],
                        )
                    return locked
            model, route = self._anchor_routes(spec)
            cache_key = A.anchor_cache_key(spec, model_config_ref=model, rights_route_id=route)
            row = A.by_cache_key(tx, season_id, cache_key)
            if row is not None:
                return row
            return A.live_version(tx, season_id, spec.ref_kind, spec.ref_key)

    # --- execution --------------------------------------------------------------------------

    def _execute(self, claim: _Claim) -> PrepareOutcome:
        specs = A.plan_anchors(claim.script, claim.manifest, claim.scope, self._config)
        # Unknown price (or a missing provider) blocks paid dispatch typed: zero
        # spend, nothing invented; the episode stays claimable once configured.
        blockers = self._unpriced_blockers(claim, specs)
        if blockers:
            self._release_claim(claim)
            return PrepareOutcome(
                episode_id=claim.episode_id,
                season_id=claim.season_id,
                status=PrepareStatus.NOT_DISPATCHED,
                settled_micro_usd=0,
                uncertainty_notes=blockers,
            )
        settled = 0
        anchor_rows: dict[tuple[str, str], dict[str, Any]] = {}
        style_asset: UUID | None = None
        for spec in specs:
            row = self._lookup_anchor(claim.season_id, spec, claim.identity_lock_id)
            if row is None:
                row, spent = self._generate_anchor(claim, spec, style_asset)
                settled += spent
            anchor_rows[(spec.ref_kind.value, spec.ref_key)] = row
            if spec.ref_kind is RefKind.STYLE:
                style_asset = row["asset_id"]
        voice_of_speaker: dict[str, dict[str, Any]] = {
            row["character_key"]: row
            for row in anchor_rows.values()
            if row["ref_kind"] == RefKind.VOICE.value and row["character_key"]
        }
        lines: list[LineAudio] = []
        for scene in claim.script.scenes:
            for line in scene.lines:
                voice_row = voice_of_speaker.get(line.speaker_character_id)
                if voice_row is None:
                    raise Conflict(
                        "speaker has no voice anchor version",
                        speaker=line.speaker_character_id,
                    )
                voice_id = A.voice_id_for(line.speaker_character_id, voice_row["version"])
                audio, spent = self._synthesize_line(claim, line, voice_id, voice_row)
                settled += spent
                lines.append(audio)
        return self._persist(claim, anchor_rows, lines, settled)

    def _unpriced_blockers(self, claim: _Claim, specs: list[AnchorSpec]) -> list[str]:
        blockers: list[str] = []
        need_image = need_voice = False
        for spec in specs:
            if self._lookup_anchor(claim.season_id, spec, claim.identity_lock_id) is not None:
                continue
            if spec.is_voice:
                need_voice = True
            else:
                need_image = True
        if any(
            not self._line_asset_exists(claim.episode_id, line.line_id, line.text_th)
            for scene in claim.script.scenes
            for line in scene.lines
        ):
            need_voice = True
        if need_image and (self._image is None or self._config.image_price is None):
            blockers.append(
                "no configured image-anchor price; paid dispatch blocked (typed unknown)"
            )
        if need_voice and (self._voice is None or self._config.voice_price is None):
            blockers.append("no configured voice price; paid dispatch blocked (typed unknown)")
        return blockers

    def _release_claim(self, claim: _Claim) -> None:
        """Clear this call's claim when it is still ours (typed answers take precedence)."""
        try:
            with self._db.transaction() as tx:
                row = tx.fetchone(
                    "SELECT revision, correlation_id FROM episodes WHERE id = %s FOR UPDATE",
                    (claim.episode_id,),
                )
                if row is None or row["correlation_id"] != claim.claim_token:
                    return
                update_with_revision(
                    tx,
                    "episodes",
                    claim.episode_id,
                    row["revision"],
                    {"correlation_id": None},
                    now=self._now(),
                )
        except MicrodramaError:
            pass

    def _generate_anchor(
        self, claim: _Claim, spec: AnchorSpec, style_asset: UUID | None
    ) -> tuple[dict[str, Any], int]:
        """One paid anchor generation (a cache miss): rights, reserve, dispatch, persist."""
        now = self._now()
        version = self._next_version(claim.season_id, spec.ref_kind, spec.ref_key)
        if spec.is_voice:
            if self._voice is None or self._config.voice_price is None:
                raise Conflict("voice anchor needs a configured provider and price")
            license_hash = check_rights(
                self._rights,
                rights_route_id=self._config.voice_rights_route_id,
                model_config_ref=self._config.voice_model_config_ref,
                now=now,
            )
            plan = voice_call_plan(
                self._attempt_key(self._anchor_semantic_key(claim.season_id, spec, version)),
                self._voice.provider_id,
                self._config,
                characters=len(spec.prompt),
                operation_kind=VOICE_ANCHOR_OPERATION,
            )
            assert plan is not None
            generated = self._adapter.generate(
                self._voice,
                plan,
                lambda reservation_id: build_voice_request(
                    voice_id=f"voice-{spec.character_key}",
                    line_id=f"anchor.{spec.character_key}",
                    text_th=spec.prompt,
                    config=self._config,
                    rights_route_id=self._config.voice_rights_route_id,
                    reservation_id=reservation_id,
                    client_token=plan.semantic_key,
                ),
                asset_kind=AssetKind.AUDIO,
                episode_id=claim.episode_id,
            )
            asset_id = self._anchor_asset_id(claim.season_id, spec, version)
            descriptor = self._register(
                generated,
                asset_id,
                AssetKind.AUDIO,
                "audio/wav",
                claim.episode_id,
                [],  # voice anchors derive from text + voice model, not the style image
                plan.semantic_key,
                now,
                object_key=(f"references/{claim.season_id}/VOICE/{spec.ref_key}/v{version}.wav"),
            )
            row = self._insert_reference(
                claim.season_id, spec, version, descriptor, license_hash, now
            )
            self._insert_voice(
                claim, spec, version, descriptor, generated.external_id, license_hash, now
            )
            return row, generated.settled_micro_usd
        if self._image is None or self._config.image_price is None:
            raise Conflict("image anchor needs a configured provider and price")
        license_hash = check_rights(
            self._rights,
            rights_route_id=self._config.image_rights_route_id,
            model_config_ref=self._config.image_model_config_ref,
            now=now,
        )
        plan = image_call_plan(
            self._attempt_key(self._anchor_semantic_key(claim.season_id, spec, version)),
            self._image.provider_id,
            self._config,
        )
        assert plan is not None
        lineage = [style_asset] if (style_asset and spec.ref_kind is not RefKind.STYLE) else []
        generated = self._adapter.generate(
            self._image,
            plan,
            lambda reservation_id: build_image_request(
                spec.model_copy(update={"lineage_asset_ids": lineage}),
                config=self._config,
                rights_route_id=self._config.image_rights_route_id,
                reservation_id=reservation_id,
                client_token=plan.semantic_key,
            ),
            asset_kind=AssetKind.IMAGE,
            episode_id=claim.episode_id,
        )
        asset_id = self._anchor_asset_id(claim.season_id, spec, version)
        descriptor = self._register(
            generated,
            asset_id,
            AssetKind.IMAGE,
            "image/png",
            claim.episode_id,
            lineage,
            plan.semantic_key,
            now,
            object_key=(
                f"references/{claim.season_id}/{spec.ref_kind.value}/{spec.ref_key}/v{version}.png"
            ),
        )
        row = self._insert_reference(claim.season_id, spec, version, descriptor, license_hash, now)
        return row, generated.settled_micro_usd

    @staticmethod
    def _anchor_asset_id(season_id: UUID, spec: AnchorSpec, version: int) -> UUID:
        return A.ref_id_for(
            "anchor-asset", f"{season_id}:{spec.ref_kind.value}:{spec.ref_key}:v{version}"
        )

    def _next_version(self, season_id: UUID, ref_kind: RefKind, ref_key: str) -> int:
        with self._db.transaction(readonly=True) as tx:
            return A.next_version(tx, season_id, ref_kind, ref_key)

    def _register(
        self,
        generated: GeneratedBytes,
        asset_id: UUID,
        asset_kind: AssetKind,
        media_type: str,
        episode_id: UUID,
        lineage: list[UUID],
        generation_key: str,
        now: datetime,
        *,
        object_key: str,
    ) -> AssetDescriptor:
        verify_generated(generated.data, kind=asset_kind)  # verified pre-fetch; defence in depth
        # The assets table requires a 64-hex generation key (full input/settings hash):
        # store the digest of the semantic key, which covers the same inputs.
        from microdrama.contracts.hashing import sha256_hex

        generation_digest = sha256_hex(generation_key.encode("utf-8"))
        stored = self._store.put_bytes(object_key, generated.data, media_type=media_type)
        descriptor = AssetDescriptor(
            asset_id=asset_id,
            asset_kind=asset_kind,
            object_key=stored.key,
            sha256=generated.sha256,
            size_bytes=len(generated.data),
            media_type=media_type,
            media=generated.media,
            state=AssetState.PROVISIONAL,
            provenance=self._adapter.provenance,
            episode_id=episode_id,
            season_id=None,
            version=1,
            lineage=[a for a in lineage if a is not None],
            license_refs=[],
            created_at=now,
        )
        with self._db.transaction() as tx:
            register_asset(tx, descriptor, generation_key=generation_digest)
        return descriptor

    def _insert_reference(
        self,
        season_id: UUID,
        spec: AnchorSpec,
        version: int,
        descriptor: AssetDescriptor,
        license_hash: str | None,
        now: datetime,
    ) -> dict[str, Any]:
        model, route = self._anchor_routes(spec)
        keyed = spec.model_copy(update={"lineage_asset_ids": descriptor.lineage})
        cache_key = A.anchor_cache_key(keyed, model_config_ref=model, rights_route_id=route)
        source_hash = A.cache_inputs_hash(keyed, model_config_ref=model, rights_route_id=route)
        try:
            with self._db.transaction() as tx:
                return A.insert_reference_version(
                    tx,
                    season_id=season_id,
                    spec=spec,
                    version=version,
                    asset_id=descriptor.asset_id,
                    content_sha256=descriptor.sha256,
                    cache_key=cache_key,
                    source_hash=source_hash,
                    license_hash=license_hash,
                    now=now,
                )
        except DuplicateSemanticKey as exc:
            if "reference_versions" not in str(exc.details.get("constraint") or ""):
                raise
            # A racer registered identical content first: the cache adopts their version.
            with self._db.transaction(readonly=True) as tx:
                winner = A.by_cache_key(tx, season_id, cache_key)
            if winner is None:
                raise
            return winner

    def _insert_voice(
        self,
        claim: _Claim,
        spec: AnchorSpec,
        version: int,
        descriptor: AssetDescriptor,
        external_id: str,
        license_hash: str | None,
        now: datetime,
    ) -> None:
        with self._db.transaction() as tx:
            character = tx.fetchone(
                "SELECT id FROM characters WHERE season_id = %s AND character_key = %s",
                (claim.season_id, spec.character_key),
            )
            if character is None:
                raise NotFound(
                    "speaker has no character row (compile_season seeds them)",
                    character_key=spec.character_key,
                )
            try:
                A.insert_voice_row(
                    tx,
                    season_id=claim.season_id,
                    character_id=character["id"],
                    character_key=spec.character_key or "unknown",
                    version=version,
                    provider=self._voice.provider_id if self._voice else "unknown",
                    provider_voice_ref=external_id or f"{spec.ref_key}:v{version}",
                    rights_route_id=self._config.voice_rights_route_id,
                    license_hash=license_hash,
                    anchor_asset_id=descriptor.asset_id,
                    now=now,
                )
            except DuplicateSemanticKey as exc:
                if "voices" not in str(exc.details.get("constraint") or ""):
                    raise

    def _line_asset_id(self, episode_id: UUID, line_id: str, text_th: str) -> UUID:
        return A.ref_id_for("line-audio", f"{episode_id}:{line_id}:{canonical_hash(text_th)[:12]}")

    def _line_asset_exists(self, episode_id: UUID, line_id: str, text_th: str) -> bool:
        with self._db.transaction(readonly=True) as tx:
            return (
                tx.fetchone(
                    "SELECT id FROM assets WHERE id = %s",
                    (self._line_asset_id(episode_id, line_id, text_th),),
                )
                is not None
            )

    def _synthesize_line(
        self, claim: _Claim, line: DialogueLine, voice_id: str, voice_row: dict[str, Any]
    ) -> tuple[LineAudio, int]:
        if self._voice is None:
            raise Conflict("no voice provider configured for dialogue synthesis")
        asset_id = self._line_asset_id(claim.episode_id, line.line_id, line.text_th)
        with self._db.transaction(readonly=True) as tx:
            existing = tx.fetchone("SELECT descriptor FROM assets WHERE id = %s", (asset_id,))
        if existing is not None:
            descriptor = AssetDescriptor.model_validate(existing["descriptor"])
            duration = (
                descriptor.media.duration_ms
                if descriptor.media is not None
                else line.estimated_duration_ms
            )
            return (
                LineAudio(
                    line_id=line.line_id,
                    speaker_character_id=line.speaker_character_id,
                    voice_id=voice_id,
                    asset_id=asset_id,
                    sha256=descriptor.sha256,
                    actual_duration_ms=duration,
                ),
                0,
            )
        now = self._now()
        check_rights(
            self._rights,
            rights_route_id=self._config.voice_rights_route_id,
            model_config_ref=self._config.voice_model_config_ref,
            now=now,
        )
        if self._config.voice_price is None:
            raise Conflict("no voice price configured")
        plan = voice_call_plan(
            self._line_semantic_key(claim.episode_id, line.line_id),
            self._voice.provider_id,
            self._config,
            characters=len(line.text_th),
        )
        assert plan is not None
        generated = self._adapter.generate(
            self._voice,
            plan,
            lambda reservation_id: build_voice_request(
                voice_id=voice_id,
                line_id=line.line_id,
                text_th=line.text_th,
                config=self._config,
                rights_route_id=self._config.voice_rights_route_id,
                reservation_id=reservation_id,
                client_token=plan.semantic_key,
            ),
            asset_kind=AssetKind.AUDIO,
            episode_id=claim.episode_id,
        )
        if generated.media is None or generated.media.duration_ms <= 0:
            raise Conflict("voice output measured no duration")
        descriptor = self._register(
            generated,
            asset_id,
            AssetKind.AUDIO,
            "audio/wav",
            claim.episode_id,
            [voice_row["asset_id"]],
            plan.semantic_key,
            now,
            object_key=(
                f"episodes/{claim.episode_id}/dialogue/{line.line_id}-"
                f"{canonical_hash(line.text_th)[:12]}.wav"
            ),
        )
        return (
            LineAudio(
                line_id=line.line_id,
                speaker_character_id=line.speaker_character_id,
                voice_id=voice_id,
                asset_id=asset_id,
                sha256=descriptor.sha256,
                actual_duration_ms=generated.media.duration_ms,
            ),
            generated.settled_micro_usd,
        )

    # --- persistence of the filled script/manifest ------------------------------------------

    def _persist(
        self,
        claim: _Claim,
        anchor_rows: dict[tuple[str, str], dict[str, Any]],
        lines: list[LineAudio],
        settled: int,
    ) -> PrepareOutcome:
        now = self._now()
        line_by_id = {audio.line_id: audio for audio in lines}
        outfits = range(1, self._config.outfits_per_character + 1)
        with self._db.transaction() as tx:
            episode = tx.fetchone(
                "SELECT * FROM episodes WHERE id = %s FOR UPDATE", (claim.episode_id,)
            )
            if episode is None:
                raise NotFound("episode vanished during references preparation")
            if episode["correlation_id"] != claim.claim_token:
                raise Conflict("the references claim was taken over by another step")
            script_version = int(
                tx.fetchval(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM scripts WHERE episode_id = %s",
                    (claim.episode_id,),
                )
            )
            manifest_version = int(
                tx.fetchval(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM shot_manifests "
                    "WHERE episode_id = %s",
                    (claim.episode_id,),
                )
            )
            script = claim.script.model_copy(
                update={
                    "version": script_version,
                    "scenes": [
                        scene.model_copy(
                            update={
                                "lines": [
                                    ln.model_copy(
                                        update={
                                            "voice_id": line_by_id[ln.line_id].voice_id,
                                            "actual_duration_ms": line_by_id[
                                                ln.line_id
                                            ].actual_duration_ms,
                                        }
                                    )
                                    for ln in scene.lines
                                ]
                            }
                        )
                        for scene in claim.script.scenes
                    ],
                }
            )
            shots = []
            for shot in claim.manifest.shots:
                voice_ids = set()
                required: set[UUID] = set()
                style = anchor_rows.get((RefKind.STYLE.value, A.style_key()))
                if style is not None:
                    required.add(style["asset_id"])
                for speaker in shot.speaker_ids:
                    voice = anchor_rows.get((RefKind.VOICE.value, A.voice_key(speaker)))
                    if voice is not None:
                        voice_ids.add(A.voice_id_for(speaker, voice["version"]))
                    face = anchor_rows.get((RefKind.FACE.value, A.face_key(speaker)))
                    if face is not None:
                        required.add(face["asset_id"])
                    for outfit in outfits:
                        wardrobe = anchor_rows.get(
                            (RefKind.WARDROBE.value, A.wardrobe_key(speaker, outfit))
                        )
                        if wardrobe is not None:
                            required.add(wardrobe["asset_id"])
                location = anchor_rows.get(
                    (RefKind.LOCATION.value, A.location_key(shot.location_id))
                )
                if location is not None:
                    required.add(location["asset_id"])
                shots.append(
                    shot.model_copy(
                        update={
                            "voice_ids": sorted(voice_ids),
                            "required_reference_asset_ids": sorted(required),
                            "reference_lock_version": claim.lock_version,
                        }
                    )
                )
            manifest = claim.manifest.model_copy(
                update={
                    "version": manifest_version,
                    "identity_lock_id": claim.identity_lock_id,
                    "script_version": script_version,
                    "shots": shots,
                }
            )
            script_id = A.ref_id_for("script", f"{claim.episode_id}:v{script_version}")
            manifest_id = A.ref_id_for("manifest", f"{claim.episode_id}:v{manifest_version}")
            tx.execute(
                "UPDATE scripts SET status = 'SUPERSEDED', revision = revision + 1 "
                "WHERE episode_id = %s AND status = 'CURRENT'",
                (claim.episode_id,),
            )
            tx.execute(
                "UPDATE shot_manifests SET status = 'SUPERSEDED', revision = revision + 1 "
                "WHERE episode_id = %s AND status = 'CURRENT'",
                (claim.episode_id,),
            )
            insert_row(
                tx,
                "scripts",
                {
                    "id": script_id,
                    "episode_id": claim.episode_id,
                    "version": script_version,
                    "canon_version": claim.script.canon_version,
                    "body": jsonb(script),
                    "body_hash": canonical_hash(script),
                    "status": "CURRENT",
                    "created_at": now,
                    "updated_at": now,
                },
                returning="id",
            )
            insert_row(
                tx,
                "shot_manifests",
                {
                    "id": manifest_id,
                    "episode_id": claim.episode_id,
                    "script_id": script_id,
                    "version": manifest_version,
                    "identity_lock_id": claim.identity_lock_id,
                    "body": jsonb(manifest),
                    "body_hash": canonical_hash(manifest),
                    "status": "CURRENT",
                    "created_at": now,
                    "updated_at": now,
                },
                returning="id",
            )
            revision = transition_episode(
                tx,
                episode_id=claim.episode_id,
                to=EpisodeState.RENDERING,
                expected_revision=episode["revision"],
                actor=self._principal,
                now=now,
                correlation_id=claim.claim_token,
            )
            update_with_revision(
                tx,
                "episodes",
                claim.episode_id,
                revision,
                {
                    "current_script_id": script_id,
                    "current_manifest_id": manifest_id,
                    "correlation_id": None,
                },
                now=now,
            )
            outcome = PrepareOutcome(
                episode_id=claim.episode_id,
                season_id=claim.season_id,
                status=PrepareStatus.CURRENT,
                settled_micro_usd=settled,
                anchors=[self._anchor_view(row) for row in anchor_rows.values()],
                lines=list(lines),
                script_version=script_version,
                manifest_version=manifest_version,
                reference_lock_version=claim.lock_version,
                identity_lock_id=claim.identity_lock_id,
            )
            append_event(
                tx,
                aggregate_type="episode",
                aggregate_id=claim.episode_id,
                event_type="references.prepared",
                payload=_json_safe(
                    {
                        "script_version": script_version,
                        "manifest_version": manifest_version,
                        "anchors": len(anchor_rows),
                        "lines": len(lines),
                        "settled_micro_usd": settled,
                        "reference_lock_version": claim.lock_version,
                    }
                ),
                correlation_id=claim.claim_token,
                occurred_at=now,
            )
        return outcome

    @staticmethod
    def _anchor_view(row: dict[str, Any]) -> AnchorView:
        return AnchorView(
            ref_kind=RefKind(row["ref_kind"]),
            ref_key=row["ref_key"],
            version=row["version"],
            asset_id=row["asset_id"],
            content_sha256=row["content_sha256"],
            state=row["state"],
            cache_key=row["cache_key"],
            reused=True,
            voice_id=(
                A.voice_id_for(row["character_key"], row["version"])
                if row["character_key"] and row["ref_kind"] == RefKind.VOICE.value
                else None
            ),
        )

    # --- replay / failure -------------------------------------------------------------------

    @staticmethod
    def _filled(script: Script, manifest: ShotManifest) -> bool:
        lines_filled = all(
            line.voice_id is not None and line.actual_duration_ms is not None
            for scene in script.scenes
            for line in scene.lines
        )
        shots_filled = all(
            shot.required_reference_asset_ids and (not shot.speaker_ids or shot.voice_ids)
            for shot in manifest.shots
        )
        return lines_filled and shots_filled

    @classmethod
    def _already_prepared(cls, tx: Tx, episode_id: UUID) -> bool:
        """True when the current manifest already carries reference bindings (a replay)."""
        row = tx.fetchone(
            "SELECT body FROM shot_manifests WHERE episode_id = %s AND status = 'CURRENT'",
            (episode_id,),
        )
        if row is None:
            return False
        try:
            manifest = ShotManifest.model_validate(row["body"])
        except Exception:  # noqa: BLE001 - an unreadable manifest is simply not prepared
            return False
        return all(shot.required_reference_asset_ids for shot in manifest.shots)

    def _replay_outcome(self, episode_id: UUID) -> PrepareOutcome:
        with self._db.transaction(readonly=True) as tx:
            episode = tx.fetchone("SELECT * FROM episodes WHERE id = %s", (episode_id,))
            assert episode is not None
            script = Script.model_validate(self._current_script_row(tx, episode_id)["body"])
            manifest = ShotManifest.model_validate(
                self._current_manifest_row(tx, episode_id)["body"]
            )
        return PrepareOutcome(
            episode_id=episode_id,
            season_id=episode["season_id"],
            status=PrepareStatus.REPLAYED,
            settled_micro_usd=0,
            script_version=script.version,
            manifest_version=manifest.version,
            reference_lock_version=next(
                (s.reference_lock_version for s in manifest.shots if s.reference_lock_version),
                None,
            ),
            identity_lock_id=episode["identity_lock_id"],
            uncertainty_notes=[
                "current script/manifest already carry references; nothing dispatched"
            ],
        )

    def _fail(self, claim: _Claim, exc: MicrodramaError) -> None:
        """Persist the typed failure and release the claim (settled spend is never touched)."""
        try:
            with self._db.transaction() as tx:
                row = tx.fetchone(
                    "SELECT revision, correlation_id FROM episodes WHERE id = %s FOR UPDATE",
                    (claim.episode_id,),
                )
                if row is None:
                    return
                append_event(
                    tx,
                    aggregate_type="episode",
                    aggregate_id=claim.episode_id,
                    event_type="references.prepare_failed",
                    payload=_json_safe({"error_code": exc.code, "message": exc.message[:500]}),
                    correlation_id=claim.claim_token,
                    occurred_at=self._now(),
                )
                if row["correlation_id"] == claim.claim_token:
                    update_with_revision(
                        tx,
                        "episodes",
                        claim.episode_id,
                        row["revision"],
                        {"correlation_id": None},
                        now=self._now(),
                    )
        except MicrodramaError:
            pass  # the typed error is the caller's answer

    # --- helpers ----------------------------------------------------------------------------

    @staticmethod
    def _current_script_row(tx: Tx, episode_id: UUID) -> dict[str, Any]:
        row = tx.fetchone(
            "SELECT * FROM scripts WHERE episode_id = %s AND status = 'CURRENT'",
            (episode_id,),
        )
        if row is None:
            raise NotFound("episode has no current script; story.write_episode must run first")
        return row

    @staticmethod
    def _current_manifest_row(tx: Tx, episode_id: UUID) -> dict[str, Any]:
        row = tx.fetchone(
            "SELECT * FROM shot_manifests WHERE episode_id = %s AND status = 'CURRENT'",
            (episode_id,),
        )
        if row is None:
            raise NotFound("episode has no current shot manifest")
        return row

    # --- explicit changes -------------------------------------------------------------------

    def explicit_change(
        self,
        episode_id: UUID,
        ref_kind: RefKind,
        ref_key: str,
        *,
        new_prompt: str,
        reason: str,
    ) -> ChangeOutcome:
        """Version a reference explicitly. The change is NOT a new approval type: the
        new version's asset enters the next cast package, cast assets are material to
        the release-package hash, and the changed episode uses its ordinary final gate.
        """
        if not reason.strip():
            raise SchemaInvalid("an explicit change requires a reason")
        if not new_prompt.strip():
            raise SchemaInvalid("an explicit change requires new prompt content")
        claim = self._change_claim(episode_id)
        try:
            return self._execute_change(claim, ref_kind, ref_key, new_prompt, reason)
        except MicrodramaError as exc:
            self._fail(claim, exc)
            raise

    def _change_claim(self, episode_id: UUID) -> _Claim:
        now = self._now()
        with self._db.transaction() as tx:
            episode = tx.fetchone("SELECT * FROM episodes WHERE id = %s FOR UPDATE", (episode_id,))
            if episode is None:
                raise NotFound("episode not found", episode_id=str(episode_id))
            if episode["state"] not in _CHANGEABLE_STATES:
                raise InvalidTransition(
                    f"episode is {episode['state']}; an explicit reference change needs a "
                    "pre-approval episode (the ordinary final gate reviews it)",
                    state=episode["state"],
                )
            if episode["correlation_id"] is not None:
                raise Conflict("another production step already claimed this episode")
            scope_row = tx.fetchone(
                "SELECT scope FROM season_proposals WHERE season_id = %s AND status = 'APPROVED'",
                (episode["season_id"],),
            )
            if scope_row is None:
                raise Conflict("season has no approved scope")
            scope = SeasonScope.model_validate(scope_row["scope"])
            self._budget.open_episode_account(
                tx,
                season_id=episode["season_id"],
                episode_id=episode_id,
                policy=scope.cost_policy,
            )
            claim_token = self._new_id()
            update_with_revision(
                tx,
                "episodes",
                episode_id,
                episode["revision"],
                {"correlation_id": claim_token},
                now=now,
            )
            return _Claim(
                episode_id=episode_id,
                season_id=episode["season_id"],
                episode_number=episode["episode_number"],
                revision=episode["revision"] + 1,
                identity_lock_id=episode["identity_lock_id"],
                lock_version=None,
                scope=scope,
                script=Script.model_validate(self._current_script_row(tx, episode_id)["body"]),
                manifest=ShotManifest.model_validate(
                    self._current_manifest_row(tx, episode_id)["body"]
                ),
                claim_token=claim_token,
            )

    def _execute_change(
        self,
        claim: _Claim,
        ref_kind: RefKind,
        ref_key: str,
        new_prompt: str,
        reason: str,
    ) -> ChangeOutcome:
        now = self._now()
        with self._db.transaction() as tx:
            current = A.live_version(tx, claim.season_id, ref_kind, ref_key)
            if current is None:
                raise NotFound(
                    "no live reference version to change",
                    ref_kind=ref_kind.value,
                    ref_key=ref_key,
                )
            # Supersede the current version and every dependent derived from it.
            invalidated_keys: list[str] = []
            invalidated_assets: list[UUID] = []
            dependents = A.dependents_of(tx, claim.season_id, current["asset_id"])
            for dep in dependents:
                update_with_revision(
                    tx,
                    "reference_versions",
                    dep["id"],
                    dep["revision"],
                    {"state": "SUPERSEDED"},
                    now=now,
                )
                invalidated_keys.append(f"{dep['ref_kind']}:{dep['ref_key']}")
                invalidated_assets.append(dep["asset_id"])
            update_with_revision(
                tx,
                "reference_versions",
                current["id"],
                current["revision"],
                {"state": "SUPERSEDED"},
                now=now,
            )
            append_event(
                tx,
                aggregate_type="season",
                aggregate_id=claim.season_id,
                event_type="references.explicit_change",
                payload=_json_safe(
                    {
                        "ref_kind": ref_kind.value,
                        "ref_key": ref_key,
                        "superseded_version": current["version"],
                        "reason": reason[:500],
                        "invalidated": invalidated_keys[:20],
                    }
                ),
                correlation_id=claim.claim_token,
                occurred_at=now,
            )
        # Generate the replacement version as this episode's paid step.
        spec = AnchorSpec(
            ref_kind=ref_kind,
            ref_key=ref_key,
            character_key=current["character_key"],
            location_id=None,
            prompt=new_prompt,
            width=self._config.anchor_width,
            height=self._config.anchor_height,
            seed=A.deterministic_seed(f"{ref_key}:change:{canonical_hash(new_prompt)[:12]}"),
            lineage_asset_ids=[],
        )
        row, _spent = self._generate_anchor(claim, spec, None)
        with self._db.transaction() as tx:
            final = tx.fetchone(
                "SELECT revision, correlation_id FROM episodes WHERE id = %s FOR UPDATE",
                (claim.episode_id,),
            )
            if final is not None and final["correlation_id"] == claim.claim_token:
                update_with_revision(
                    tx,
                    "episodes",
                    claim.episode_id,
                    final["revision"],
                    {"correlation_id": None},
                    now=self._now(),
                )
        return ChangeOutcome(
            season_id=claim.season_id,
            episode_id=claim.episode_id,
            ref_kind=ref_kind,
            ref_key=ref_key,
            superseded_version=current["version"],
            new_version=row["version"],
            new_asset_id=row["asset_id"],
            invalidated_ref_keys=invalidated_keys,
            invalidated_asset_ids=invalidated_assets,
        )


def build_references_service(
    db: Database,
    clock: Clock,
    ids: IdGenerator,
    settings: Settings,
    *,
    budget: BudgetService,
    store: ObjectStore,
    image_provider: GenerationProvider | None = None,
    voice_provider: GenerationProvider | None = None,
    rights: RightsRegistry | None = None,
    config: ReferencesConfig | None = None,
) -> ReferencesService:
    """Composition factory for the integrator (route/job registration stays with them).

    In OFFLINE_MOCK with no explicit config the labelled synthetic price table prices
    the steps (image anchors GPU-second-bounded, voice per 1k characters) — matching
    the T007 fake provider passed in, exactly like the story lane's factory. In any
    other mode, or with an explicit config, no synthetic price is ever set: a live
    deployment configures real prices or nothing dispatches.
    """
    if config is None and settings.is_offline_mock:
        from microdrama.testing.fakes.common import fake_price_quote

        config = ReferencesConfig(
            image_price=fake_price_quote(PriceUnit.GPU_SECOND),
            voice_price=fake_price_quote(PriceUnit.CHARACTER_1K),
        )
    return ReferencesService(
        db,
        clock,
        ids,
        settings,
        budget=budget,
        store=store,
        image_provider=image_provider,
        voice_provider=voice_provider,
        rights=rights,
        config=config,
    )


__all__ = [
    "ReferencesService",
    "build_references_service",
]
