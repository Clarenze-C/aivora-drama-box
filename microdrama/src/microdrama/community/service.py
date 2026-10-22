"""Organic community management service (T025): ingest, classify, act, meter.

The service runs the episode's organic social presence offline-first, over the
frozen ``community_events``/``management_actions`` tables (migration 0005) and
the frozen contracts (``CommunityProvider``/``ManagementAction``/ActionResult``).
Policy truth this module owns (SPEC §10, task_breakdown §5 T025):

- **Untrusted text is data.** Classification is pure keyword rules; no code path
  parses comment text as instructions, and an INJECTION classification changes
  nothing anywhere (no privileged tool, no budget move, no reply).
- **Policy before execution** (MD-018): contracts, invented sponsorships,
  refunds, discounts, budget increases and cold outreach are SUPPRESSED with
  recorded reasons, before any reservation or provider call.
- **Uncertainty never destroys**: destructive moderation (hide/delete/report)
  executes only at ≥ ``DESTRUCTIVE_MIN_CONFIDENCE_BP``; below it the action is
  SUPPRESSED with ``classifier_confidence_bp`` recorded. Ordinary criticism is
  never moderated. There is no automatic account ban path at all.
- **Grounding**: replies, DM content and metadata text must pass
  ``grounding.validate_claims`` (released catalog / announced schedule /
  approved offers); violations are SUPPRESSED, never sent.
- **Duplicates**: provider events are ingested once per
  ``(platform, account_ref, provider_event_id)``; action ``dedupe_key`` rows
  never execute twice (an EXECUTED row is an idempotent replay).
- **Metered budget**: replies, DM sends and metadata optimization reserve
  ``METERED_MANAGEMENT`` on the ``community`` queue through the REAL
  ``BudgetService`` before dispatch, settle with the provider's receipts, and
  release on refusal. Exhaustion suppresses/defers optional actions — community
  can never steal another category (the budget service enforces ownership).
- **Backpressure**: provider rate limits map to DEFERRED with a retry-after
  window; ``retry_deferred`` re-executes the same dedupe key after the window.

DM keyword/eligibility logic is T026's lane: this service will execute a
handed-in ``DM_SEND`` action only inside the inbound DM's messaging window and
under the per-conversation cap (``execute_action``), and builds none of it.

Metadata versioning rides the T020 store (``publishing.metadata``): every edit
is a new immutable ``metadata_versions`` row; rollback is an ordinary new
version recording ``rollback_of``. Substantive edits obey the approved policy's
24h cooldown and the two-substantive-edits-in-first-7-days cap; rollbacks
restore previously-live content and are exempt from both (they cannot introduce
claims that were not already public), but are still versioned and audited.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from microdrama.budget import BudgetService
from microdrama.community import policy as community_policy
from microdrama.community.classification import (
    Classification,
    CommentClass,
    classify_comment,
)
from microdrama.community.grounding import GroundingFacts, load_facts, validate_claims
from microdrama.community.replies import grounded_reply
from microdrama.contracts.cost import BudgetReservationRequest, ExposureCeilings
from microdrama.contracts.enums import (
    ActionDecision,
    BudgetCategory,
    BudgetScopeKind,
    CommunityEventKind,
    ManagementActionKind,
    Platform,
    Provenance,
    QueueName,
)
from microdrama.contracts.errors import (
    BudgetExhausted,
    Conflict,
    NotFound,
    PolicyDenied,
    SchemaInvalid,
)
from microdrama.contracts.providers import ActionResult, CommunityProvider
from microdrama.contracts.release import ManagementAction, PostMetadata
from microdrama.contracts.season import ManagementPolicy
from microdrama.persistence import Database
from microdrama.persistence.db import Tx, insert_row, update_with_revision
from microdrama.publishing import metadata as meta

#: Flood control: at most this many actions one process() pass may take.
DEFAULT_MAX_ACTIONS_PER_RUN = 200
#: Synthetic worst-case cost of one metered management action (micro-USD).
METERED_ACTION_COST_MICRO_USD = 1_000
#: Ceilings bounding one metered action's exposure (one request, 30s timeout).
METERED_TIMEOUT_MS = 30_000
#: How long a metered reservation stays open before the stale sweep expires it.
RESERVATION_TTL = timedelta(minutes=10)

FAKE = Provenance.FAKE_SYNTHETIC

_METERED_KIND_COST_MICRO_USD: dict[ManagementActionKind, int] = {
    ManagementActionKind.PUBLIC_REPLY: METERED_ACTION_COST_MICRO_USD,
    ManagementActionKind.DM_SEND: METERED_ACTION_COST_MICRO_USD,
}

_ENGAGEMENT_CLASSES = frozenset(
    {CommentClass.QUESTION, CommentClass.PRAISE, CommentClass.CRITICISM}
)

#: Action decisions mapped onto the frozen community_events status ladder.
_EVENT_STATUS_OF_DECISION: dict[str, str] = {
    ActionDecision.EXECUTED.value: "ACTIONED",
    ActionDecision.SUPPRESSED.value: "SUPPRESSED",
    ActionDecision.DEFERRED.value: "DEFERRED",
    ActionDecision.FAILED.value: "CLASSIFIED",
    ActionDecision.NEEDS_RECONCILIATION.value: "DEFERRED",
}


@dataclass
class IngestReport:
    """Outcome of one fetch+dedupe pass. Re-delivered events are never reprocessed."""

    new_event_ids: list[UUID] = field(default_factory=list)
    duplicates: int = 0


@dataclass
class ProcessReport:
    """Outcome of one ingest+classify+act pass over an account."""

    ingested_new: int = 0
    duplicates: int = 0
    executed: int = 0
    suppressed: int = 0
    deferred: int = 0
    ignored: int = 0
    no_action: int = 0
    action_cap_reached: bool = False


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchemaInvalid(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def classification_to_text(classification: Classification) -> str:
    """Store a classification as compact JSON (class, confidence, evidence)."""
    return json.dumps(
        {
            "class": classification.comment_class.value,
            "confidence_bp": classification.confidence_bp,
            "matched": list(classification.matched_rules),
        },
        ensure_ascii=False,
    )


def classification_from_text(raw: str | None) -> Classification | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return Classification(
            comment_class=CommentClass(data["class"]),
            confidence_bp=int(data["confidence_bp"]),
            matched_rules=tuple(data.get("matched", ())),
        )
    except (ValueError, KeyError, TypeError):
        return None


class CommunityService:
    """Community management over registered fake (offline) community providers."""

    def __init__(
        self,
        db: Database,
        clock: Any,
        ids: Any,
        providers: Mapping[Platform, CommunityProvider],
        budget: BudgetService,
        *,
        max_actions_per_run: int = DEFAULT_MAX_ACTIONS_PER_RUN,
    ) -> None:
        self._db = db
        self._clock = clock
        self._ids = ids
        self._providers = dict(providers)
        self._budget = budget
        self._max_actions_per_run = max_actions_per_run

    # --- plumbing ------------------------------------------------------------------

    def _now(self) -> datetime:
        return _aware(self._clock.now(), "clock.now()")

    def _provider(self, platform: Platform) -> CommunityProvider:
        provider = self._providers.get(platform)
        if provider is None:
            raise PolicyDenied(
                "no community provider registered for this platform",
                platform=platform.value,
            )
        return provider

    def _policy(self, tx: Tx, season_id: UUID) -> tuple[ManagementPolicy, str]:
        """The approved season's management policy and its hash (Gate-2-bound scope)."""
        from microdrama.review.gate_conditions import approved_policy_hash

        policy_hash, policy = approved_policy_hash(tx, season_id)
        if policy is None or policy_hash is None:
            raise PolicyDenied(
                "season has no approved management policy; community actions are refused",
                season_id=str(season_id),
            )
        return policy, policy_hash

    def _event_row(self, tx: Tx, event_id: UUID) -> dict[str, Any]:
        row = tx.fetchone("SELECT * FROM community_events WHERE id = %s", (event_id,))
        if row is None:
            raise NotFound(f"community event {event_id} not found")
        return row

    def _action_row(self, tx: Tx, dedupe_key: str) -> dict[str, Any] | None:
        return tx.fetchone("SELECT * FROM management_actions WHERE dedupe_key = %s", (dedupe_key,))

    # --- ingest ----------------------------------------------------------------------

    def ingest(
        self, platform: Platform, account_ref: str, *, since: datetime | None = None
    ) -> IngestReport:
        """Fetch provider events and ingest each exactly once (at-least-once delivery).

        Duplicate ``(platform, account_ref, provider_event_id)`` deliveries count
        as duplicates and are never reprocessed. New events are classified
        immediately (status RECEIVED -> CLASSIFIED with the classification
        stored); their text is only ever matched, never executed.
        """
        provider = self._provider(platform)
        now = self._now()
        report = IngestReport()
        events = provider.fetch_events(account_ref, since=since)
        for event in events:
            if event.platform is not platform:
                raise SchemaInvalid("event platform does not match the fetching provider")
            with self._db.transaction() as tx:
                linked_post_id = None
                if event.external_post_id:
                    linked = tx.fetchone(
                        "SELECT id FROM platform_posts WHERE platform = %s "
                        "AND account_ref = %s AND external_id = %s",
                        (platform.value, account_ref, event.external_post_id),
                    )
                    linked_post_id = linked["id"] if linked is not None else None
                row = tx.fetchone(
                    "INSERT INTO community_events (id, platform, account_ref, provider_event_id, "
                    "kind, platform_post_id, external_post_id, author_ref, text, received_at, "
                    "dm_window_expires_at, classification, status, provenance) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, 'RECEIVED', %s) "
                    "ON CONFLICT (platform, account_ref, provider_event_id) DO NOTHING RETURNING *",
                    (
                        self._ids.new_id(),
                        platform.value,
                        account_ref,
                        event.provider_event_id,
                        event.kind.value,
                        linked_post_id,
                        event.external_post_id,
                        event.author_ref,
                        event.text,
                        event.received_at,
                        event.dm_window_expires_at,
                        event.provenance.value,
                    ),
                )
                if row is None:
                    report.duplicates += 1
                    continue
                classification = classify_comment(event.text)
                updated = update_with_revision(
                    tx,
                    "community_events",
                    row["id"],
                    int(row["revision"]),
                    {
                        "classification": classification_to_text(classification),
                        "status": "CLASSIFIED",
                    },
                    now=now,
                )
            report.new_event_ids.append(updated["id"])
        return report

    # --- process: classify, decide, act ------------------------------------------------

    def process(
        self,
        platform: Platform,
        account_ref: str,
        *,
        season_id: UUID,
        episode_id: UUID,
        since: datetime | None = None,
    ) -> ProcessReport:
        """One management pass: ingest, then decide and execute bounded actions.

        Runs inside the episode's management window: every metered action bills
        ``episode_id``'s METERED_MANAGEMENT allowance. The pass stops taking
        actions at ``max_actions_per_run`` (flood control); unprocessed events
        simply stay CLASSIFIED for the next pass.
        """
        report = ProcessReport()
        ingest = self.ingest(platform, account_ref, since=since)
        report.ingested_new = len(ingest.new_event_ids)
        report.duplicates = ingest.duplicates
        if not ingest.new_event_ids:
            return report
        now = self._now()
        with self._db.transaction(readonly=True) as tx:
            policy, _policy_hash = self._policy(tx, season_id)
            facts = load_facts(tx, season_id, now=now)
        actions_taken = 0
        for event_id in ingest.new_event_ids:
            if actions_taken >= self._max_actions_per_run:
                report.action_cap_reached = True
                break
            with self._db.transaction(readonly=True) as tx:
                event = self._event_row(tx, event_id)
            outcome = self._handle_event(
                event,
                platform=platform,
                account_ref=account_ref,
                season_id=season_id,
                episode_id=episode_id,
                policy=policy,
                facts=facts,
            )
            if outcome in ("EXECUTED", "SUPPRESSED", "DEFERRED"):
                actions_taken += 1
                if outcome == "EXECUTED":
                    report.executed += 1
                elif outcome == "SUPPRESSED":
                    report.suppressed += 1
                else:
                    report.deferred += 1
            elif outcome == "IGNORED":
                report.ignored += 1
            else:
                report.no_action += 1
        return report

    def _handle_event(
        self,
        event: dict[str, Any],
        *,
        platform: Platform,
        account_ref: str,
        season_id: UUID,
        episode_id: UUID,
        policy: ManagementPolicy,
        facts: GroundingFacts,
    ) -> str:
        """Decide and execute actions for one classified event. Returns the outcome."""
        classification = classification_from_text(event["classification"])
        if classification is None:
            raise Conflict(
                "event is not classified; classify before handling",
                event_id=str(event["id"]),
            )
        kind = CommunityEventKind(event["kind"])
        if kind in (CommunityEventKind.COMMENT, CommunityEventKind.REPLY):
            return self._handle_comment(
                event,
                classification=classification,
                platform=platform,
                account_ref=account_ref,
                season_id=season_id,
                episode_id=episode_id,
                policy=policy,
                facts=facts,
            )
        # DIRECT_MESSAGE handling (keyword DM replies) is T026's lane: the event
        # stays CLASSIFIED for it. MENTION/POST_STATUS have no organic reply yet.
        return "NO_ACTION"

    def _handle_comment(
        self,
        event: dict[str, Any],
        *,
        classification: Classification,
        platform: Platform,
        account_ref: str,
        season_id: UUID,
        episode_id: UUID,
        policy: ManagementPolicy,
        facts: GroundingFacts,
    ) -> str:
        if classification.comment_class is CommentClass.INJECTION_ATTEMPT:
            # Untrusted instruction text: labelled, ignored, zero effect. It can
            # never reach a privileged tool, change policy, or spend budget.
            self._set_event_status(event["id"], "IGNORED")
            return "IGNORED"
        if classification.moderation_class:
            action = self._build_action(
                kind=ManagementActionKind.MODERATE_HIDE,
                platform=platform,
                account_ref=account_ref,
                event_row=event,
                policy=policy,
                facts=facts,
                confidence_bp=classification.confidence_bp,
            )
            row = self.execute_action(
                action, season_id=season_id, episode_id=episode_id, event_row=event
            )
            self._set_event_status(event["id"], _EVENT_STATUS_OF_DECISION[row["decision"]])
            return row["decision"]
        if classification.comment_class in _ENGAGEMENT_CLASSES:
            reply, _violations = grounded_reply(
                classification.comment_class, facts, text=event["text"]
            )
            if reply is None:
                self._set_event_status(event["id"], "IGNORED")
                return "IGNORED"
            action = self._build_action(
                kind=ManagementActionKind.PUBLIC_REPLY,
                platform=platform,
                account_ref=account_ref,
                event_row=event,
                policy=policy,
                facts=facts,
                content=reply,
            )
            row = self.execute_action(
                action, season_id=season_id, episode_id=episode_id, event_row=event
            )
            self._set_event_status(event["id"], _EVENT_STATUS_OF_DECISION[row["decision"]])
            return row["decision"]
        self._set_event_status(event["id"], "IGNORED")
        return "IGNORED"

    def _set_event_status(self, event_id: UUID, status: str) -> None:
        now = self._now()
        with self._db.transaction() as tx:
            row = self._event_row(tx, event_id)
            if row["status"] == status:
                return
            update_with_revision(
                tx, "community_events", event_id, int(row["revision"]),
                {"status": status}, now=now,
            )  # fmt: skip

    # --- action construction -----------------------------------------------------------

    def _build_action(
        self,
        *,
        kind: ManagementActionKind,
        platform: Platform,
        account_ref: str,
        policy: ManagementPolicy,
        facts: GroundingFacts,
        policy_hash: str | None = None,
        event_row: dict[str, Any] | None = None,
        platform_post_id: UUID | None = None,
        content: str | None = None,
        confidence_bp: int | None = None,
        dedupe_key: str | None = None,
        estimated_cost_micro_usd: int = 0,
    ) -> ManagementAction:
        if dedupe_key is None:
            if event_row is not None:
                dedupe_key = f"{kind.value.lower()}:{platform.value}:{account_ref}:{event_row['provider_event_id']}"
            else:
                raise SchemaInvalid("a handed-in action needs an explicit dedupe_key")
        return ManagementAction(
            action_id=self._ids.new_id(),
            kind=kind,
            platform=platform,
            account_ref=account_ref,
            platform_post_id=platform_post_id
            or (event_row["platform_post_id"] if event_row else None),
            target_external_id=(event_row["external_post_id"] if event_row else None),
            community_event_id=(event_row["id"] if event_row else None),
            content=content,
            catalog_version=facts.catalog_version,
            management_policy_hash=policy_hash or _policy_hash_of(policy),
            dedupe_key=dedupe_key,
            estimated_cost_micro_usd=estimated_cost_micro_usd
            or _METERED_KIND_COST_MICRO_USD.get(kind, 0),
            classifier_confidence_bp=confidence_bp,
        )

    # --- execution ----------------------------------------------------------------------

    def execute_action(
        self,
        action: ManagementAction,
        *,
        season_id: UUID,
        episode_id: UUID,
        event_row: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Gate, reserve, execute and record one management action (idempotent).

        Returns the durable ``management_actions`` row. A stored EXECUTED row is
        returned as-is (duplicate action dedupe keys never execute twice); a
        stored DEFERRED row is returned as-is too — only ``retry_deferred``
        re-executes it, after the retry window. All policy checks run BEFORE any
        reservation or provider call.
        """
        now = self._now()
        with self._db.transaction(readonly=True) as tx:
            stored = self._action_row(tx, action.dedupe_key)
            if stored is not None:
                return dict(stored)
            policy, policy_hash = self._policy(tx, season_id)
            facts = load_facts(tx, season_id, now=now)
            linked_event = (
                event_row
                if event_row is not None
                else (
                    self._event_row(tx, action.community_event_id)
                    if action.community_event_id is not None
                    else None
                )
            )
            suppression = self._pre_execution_gates(
                action, policy=policy, facts=facts, linked_event=linked_event, now=now
            )
        if suppression is not None:
            return self._record_suppressed(action, suppression, policy_hash=policy_hash)
        action = (
            action.model_copy(update={"management_policy_hash": policy_hash})
            if action.management_policy_hash != policy_hash
            else action
        )

        reservation = None
        if action.estimated_cost_micro_usd > 0:
            try:
                reservation = self._reserve_for_action(action, episode_id=episode_id, now=now)
            except BudgetExhausted:
                # The metered allowance cannot fit this optional action: suppress
                # it, never borrow from another category (SPEC §6 community cap).
                return self._record_suppressed(action, "BUDGET_EXHAUSTED", policy_hash=policy_hash)
            action = action.model_copy(update={"reservation_id": reservation.id})

        with self._db.transaction() as tx:
            stored = self._action_row(tx, action.dedupe_key)
            if stored is not None:  # lost a race: never insert a second row
                if reservation is not None:
                    self._budget.release(reservation.id, reason="duplicate dispatch race")
                return dict(stored)
            insert_row(
                tx,
                "management_actions",
                {
                    "id": action.action_id,
                    "kind": action.kind.value,
                    "platform": action.platform.value,
                    "account_ref": action.account_ref,
                    "platform_post_id": action.platform_post_id,
                    "community_event_id": action.community_event_id,
                    "dedupe_key": action.dedupe_key,
                    "body": action,
                    "policy_hash": action.management_policy_hash,
                    "catalog_version": action.catalog_version,
                    "reservation_id": action.reservation_id,
                    "decision": action.decision.value,
                    "reason": action.reason,
                    "external_id": None,
                    "error_code": None,
                    "provenance": FAKE.value,
                    "executed_at": None,
                },
            )
        result = self._provider(action.platform).execute(action)
        return self._record_outcome(action, result, reservation=reservation, now=now)

    def _pre_execution_gates(
        self,
        action: ManagementAction,
        *,
        policy: ManagementPolicy,
        facts: GroundingFacts,
        linked_event: dict[str, Any] | None,
        now: datetime,
    ) -> str | None:
        """Every suppression reason, checked before any reservation or provider call."""
        if not community_policy.action_kind_allowed(policy, action.kind):
            return "NOT_ALLOWED_BY_POLICY"
        may_destroy, reason = community_policy.destructive_gate(
            action.kind, action.classifier_confidence_bp
        )
        if not may_destroy:
            return reason or "UNCERTAIN_DESTRUCTIVE"
        md018 = community_policy.md018_content_violation(action.content)
        if md018 is not None:
            return md018
        if action.kind in (ManagementActionKind.PUBLIC_REPLY, ManagementActionKind.DM_SEND):
            if action.content:
                violations = validate_claims(action.content, facts)
                if violations:
                    return "UNGROUNDED_CLAIM:" + ",".join(violations)
        if action.kind is ManagementActionKind.DM_SEND:
            reason = self._dm_gates(action, policy=policy, linked_event=linked_event, now=now)
            if reason is not None:
                return reason
        if action.kind is ManagementActionKind.PUBLIC_REPLY and linked_event is not None:
            reason = self._reply_cap_gate(linked_event, policy=policy, now=now)
            if reason is not None:
                return reason
        return None

    def _dm_gates(
        self,
        action: ManagementAction,
        *,
        policy: ManagementPolicy,
        linked_event: dict[str, Any] | None,
        now: datetime,
    ) -> str | None:
        """DM window + conversation-cap gates. Keyword/eligibility logic is T026's."""
        cold = community_policy.is_cold_outreach(
            kind=action.kind,
            linked_inbound_dm=linked_event is not None
            and linked_event["kind"] == CommunityEventKind.DIRECT_MESSAGE.value,
        )
        if cold is not None:
            return cold
        assert linked_event is not None  # guarded by is_cold_outreach above
        window = linked_event["dm_window_expires_at"]
        if window is None or _aware(window, "dm_window_expires_at") <= now:
            return "DM_WINDOW_CLOSED"
        executed_dms = self._count_executed(
            "SELECT count(*) FROM management_actions ma JOIN community_events ce "
            "ON ce.id = ma.community_event_id WHERE ma.kind = 'DM_SEND' "
            "AND ma.decision = 'EXECUTED' AND ce.platform = %s AND ce.account_ref = %s "
            "AND ce.author_ref = %s",
            (action.platform.value, action.account_ref, linked_event["author_ref"]),
        )
        return community_policy.dm_cap_reason(
            executed_dms_in_conversation=executed_dms, policy=policy
        )

    def _reply_cap_gate(
        self, linked_event: dict[str, Any], *, policy: ManagementPolicy, now: datetime
    ) -> str | None:
        executed_replies = self._count_executed(
            "SELECT count(*) FROM management_actions ma JOIN community_events ce "
            "ON ce.id = ma.community_event_id WHERE ma.kind = 'PUBLIC_REPLY' "
            "AND ma.decision = 'EXECUTED' AND ma.executed_at > %s "
            "AND ce.platform = %s AND ce.account_ref = %s AND ce.external_post_id = %s",
            (
                now - timedelta(hours=24),
                linked_event["platform"],
                linked_event["account_ref"],
                linked_event["external_post_id"],
            ),
        )
        return community_policy.reply_cap_reason(
            executed_replies_last_24h=executed_replies, policy=policy
        )

    def _count_executed(self, sql: str, params: tuple) -> int:
        with self._db.transaction(readonly=True) as tx:
            return int(tx.fetchval(sql, params) or 0)

    def _record_suppressed(
        self, action: ManagementAction, reason: str, *, policy_hash: str
    ) -> dict[str, Any]:
        suppressed = action.model_copy(
            update={
                "decision": ActionDecision.SUPPRESSED,
                "reason": reason,
                "management_policy_hash": policy_hash,
                "reservation_id": None,
            }
        )
        with self._db.transaction() as tx:
            stored = self._action_row(tx, suppressed.dedupe_key)
            if stored is not None:
                return dict(stored)
            insert_row(
                tx,
                "management_actions",
                self._action_values(suppressed, decision=ActionDecision.SUPPRESSED, reason=reason),
            )
            return dict(
                tx.fetchone("SELECT * FROM management_actions WHERE dedupe_key = %s",
                            (suppressed.dedupe_key,))
            )  # fmt: skip

    def _action_values(
        self,
        action: ManagementAction,
        *,
        decision: ActionDecision,
        reason: str | None = None,
        external_id: str | None = None,
        error_code: str | None = None,
        executed_at: datetime | None = None,
    ) -> dict[str, Any]:
        return {
            "id": action.action_id,
            "kind": action.kind.value,
            "platform": action.platform.value,
            "account_ref": action.account_ref,
            "platform_post_id": action.platform_post_id,
            "community_event_id": action.community_event_id,
            "dedupe_key": action.dedupe_key,
            "body": action,
            "policy_hash": action.management_policy_hash,
            "catalog_version": action.catalog_version,
            "reservation_id": action.reservation_id,
            "decision": decision.value,
            "reason": reason,
            "external_id": external_id,
            "error_code": error_code,
            "provenance": FAKE.value,
            "executed_at": executed_at,
        }

    def _record_outcome(
        self,
        action: ManagementAction,
        result: ActionResult,
        *,
        reservation: Any | None,
        now: datetime,
    ) -> dict[str, Any]:
        """Apply the provider outcome to the durable row and the budget."""
        if result.decision is ActionDecision.EXECUTED:
            for receipt in result.usage:
                self._budget.record_usage(receipt)
            with self._db.transaction() as tx:
                row = self._lock_action(tx, action.action_id)
                return dict(
                    update_with_revision(
                        tx,
                        "management_actions",
                        row["id"],
                        int(row["revision"]),
                        {
                            "decision": ActionDecision.EXECUTED.value,
                            "external_id": result.external_id,
                            "executed_at": now,
                        },
                        now=now,
                    )
                )
        # No usage was billed on the refusal path: free the reservation so the
        # allowance is not held by work that never happened.
        if reservation is not None:
            self._budget.release(
                reservation.id, reason=f"provider {result.decision.value}: no usage"
            )
        reason = result.error_code or result.decision.value
        if result.retry_after_ms is not None:
            reason = f"{reason}:retry_after_ms={result.retry_after_ms}"
        with self._db.transaction() as tx:
            row = self._lock_action(tx, action.action_id)
            return dict(
                update_with_revision(
                    tx,
                    "management_actions",
                    row["id"],
                    int(row["revision"]),
                    {
                        "decision": result.decision.value,
                        "reason": reason,
                        "error_code": result.error_code,
                    },
                    now=now,
                )
            )

    def _lock_action(self, tx: Tx, action_id: UUID) -> dict[str, Any]:
        row = tx.fetchone("SELECT * FROM management_actions WHERE id = %s FOR UPDATE", (action_id,))
        if row is None:
            raise NotFound(f"management action {action_id} not found")
        return row

    # --- budget ---------------------------------------------------------------------------

    def _reserve_for_action(
        self, action: ManagementAction, *, episode_id: UUID, now: datetime, attempt: int = 1
    ) -> Any:
        """Reserve METERED_MANAGEMENT on the community queue through the real budget service.

        Raises BudgetExhausted when the episode's metered allowance cannot fit the
        worst case (the caller suppresses the optional action); any other budget
        refusal is a configuration bug and propagates loudly.
        """
        from microdrama.contracts.enums import PriceUnit
        from microdrama.testing.fakes.common import fake_price_quote

        suffix = "" if attempt == 1 else f".r{attempt}"
        request = BudgetReservationRequest(
            request_id=self._ids.new_id(),
            semantic_key=f"community.{action.kind.value.lower()}:{action.dedupe_key}{suffix}",
            scope_kind=BudgetScopeKind.EPISODE,
            episode_id=episode_id,
            category=BudgetCategory.METERED_MANAGEMENT,
            queue=QueueName.COMMUNITY,
            provider=self._provider(action.platform).provider_id,
            operation_kind=f"community.{action.kind.value.lower()}",
            price=fake_price_quote(PriceUnit.REQUEST),
            ceilings=ExposureCeilings(timeout_ms=METERED_TIMEOUT_MS, max_units=1),
            worst_case_micro_usd=action.estimated_cost_micro_usd,
            expires_at=now + RESERVATION_TTL,
        )
        return self._budget.reserve(request)

    # --- retry (backpressure) ---------------------------------------------------------------

    def retry_deferred(
        self, dedupe_key: str, *, season_id: UUID, episode_id: UUID
    ) -> dict[str, Any]:
        """Re-execute a DEFERRED action after its retry window (same dedupe key)."""
        now = self._now()
        with self._db.transaction(readonly=True) as tx:
            row = self._action_row(tx, dedupe_key)
            if row is None:
                raise NotFound(f"management action {dedupe_key} not found")
            if row["decision"] != ActionDecision.DEFERRED.value:
                raise Conflict("only a DEFERRED action can be retried", decision=row["decision"])
        retry_after_ms = _retry_after_ms_of(row["reason"])
        if retry_after_ms is not None:
            due = row["updated_at"] + timedelta(milliseconds=retry_after_ms)
            if now < _aware(due, "updated_at"):
                raise Conflict(
                    "retry window has not elapsed yet",
                    retry_after_ms=retry_after_ms,
                    due_at=due.isoformat(),
                )
        action = ManagementAction.model_validate(row["body"])
        attempt = _attempt_of(row["reason"]) + 1
        try:
            reservation = self._reserve_for_action(
                action, episode_id=episode_id, now=now, attempt=attempt
            )
        except BudgetExhausted:
            with self._db.transaction() as tx:
                fresh = self._lock_action(tx, row["id"])
                return dict(
                    update_with_revision(
                        tx, "management_actions", fresh["id"], int(fresh["revision"]),
                        {"error_code": "BUDGET_EXHAUSTED"}, now=now,
                    )
                )  # fmt: skip
        action = action.model_copy(update={"reservation_id": reservation.id})
        result = self._provider(action.platform).execute(action)
        outcome = self._record_outcome(action, result, reservation=reservation, now=now)
        if action.community_event_id is not None:
            self._set_event_status(
                action.community_event_id, _EVENT_STATUS_OF_DECISION[outcome["decision"]]
            )
        if outcome["decision"] == ActionDecision.DEFERRED.value:
            with self._db.transaction() as tx:
                fresh = self._lock_action(tx, outcome["id"])
                return dict(
                    update_with_revision(
                        tx, "management_actions", fresh["id"], int(fresh["revision"]),
                        {"reason": _with_attempt(outcome["reason"], attempt)}, now=now,
                    )
                )  # fmt: skip
        return outcome

    # --- metadata versions --------------------------------------------------------------------

    def apply_metadata_edit(
        self, post_id: UUID, metadata: PostMetadata, *, rollback_of: UUID | None = None
    ) -> dict[str, Any]:
        """Apply one bounded metadata edit as a new immutable version row.

        Policy outcomes (cooldown, seven-day substantive-edit cap, disallowed
        kind, ungrounded content) are recorded as SUPPRESSED management actions
        — auditable refusals, not exceptions. Caller errors (post not live,
        unchanged metadata, bad rollback target) raise. Substantive forward
        edits are metered; rollbacks restore previously-live content and are
        unmetered and exempt from cooldown and edit cap.
        """
        now = self._now()
        plan = self._validate_metadata_edit(post_id, metadata, rollback_of=rollback_of, now=now)
        action = plan.build_action(self._ids.new_id())
        if plan.suppression_reason is not None:
            return self._record_suppressed(
                action, plan.suppression_reason, policy_hash=plan.policy_hash
            )

        reservation = None
        if plan.metered:
            try:
                reservation = self._reserve_for_action(action, episode_id=plan.episode_id, now=now)
            except BudgetExhausted:
                return self._record_suppressed(
                    action, "BUDGET_EXHAUSTED", policy_hash=plan.policy_hash
                )
            action = action.model_copy(update={"reservation_id": reservation.id})

        with self._db.transaction() as tx:
            stored = self._action_row(tx, action.dedupe_key)
            if stored is not None:
                if reservation is not None:
                    self._budget.release(reservation.id, reason="duplicate metadata edit")
                return dict(stored)
            meta.create_version(
                tx,
                post_id=post_id,
                version_id=action.action_id,
                metadata=metadata,
                policy_hash=plan.policy_hash,
                now=now,
                rollback_of=rollback_of,
            )
            insert_row(
                tx,
                "management_actions",
                self._action_values(action, decision=ActionDecision.PROPOSED),
            )
        result = self._provider(action.platform).execute(action)
        return self._record_outcome(action, result, reservation=reservation, now=now)

    def rollback_metadata(self, post_id: UUID, target_version_id: UUID) -> dict[str, Any]:
        """Roll the post back to a previous applied version (an ordinary new version)."""
        with self._db.transaction(readonly=True) as tx:
            target = tx.fetchone(
                "SELECT metadata FROM metadata_versions WHERE id = %s AND platform_post_id = %s",
                (target_version_id, post_id),
            )
            if target is None:
                raise NotFound(f"rollback target {target_version_id} is not a version of this post")
        metadata = PostMetadata.model_validate(target["metadata"])
        return self.apply_metadata_edit(post_id, metadata, rollback_of=target_version_id)

    def _validate_metadata_edit(
        self, post_id: UUID, metadata: PostMetadata, *, rollback_of: UUID | None, now: datetime
    ) -> _MetadataPlan:
        with self._db.transaction(readonly=True) as tx:
            post = tx.fetchone("SELECT * FROM platform_posts WHERE id = %s", (post_id,))
            if post is None:
                raise NotFound(f"platform post {post_id} not found")
            if post["state"] not in ("PUBLISHED_VERIFIED", "MANAGED"):
                raise PolicyDenied(
                    "metadata edits apply only to published posts",
                    state=post["state"],
                )
            policy, policy_hash = self._policy(tx, post["series_id"])
            facts = load_facts(tx, post["series_id"], now=now)
            current = meta.current_metadata(tx, post_id)
            if current is None:
                raise Conflict("post has no current metadata version", post_id=str(post_id))
            current_version_id, current_metadata = current
            latest = tx.fetchone(
                "SELECT version FROM metadata_versions WHERE platform_post_id = %s "
                "ORDER BY version DESC LIMIT 1",
                (post_id,),
            )
            next_version = 1 if latest is None else int(latest["version"]) + 1

            def plan(
                kind: ManagementActionKind,
                changed: list[str],
                *,
                metered: bool,
                suppression_reason: str | None,
            ) -> _MetadataPlan:
                return _MetadataPlan(
                    post=post,
                    kind=kind,
                    metadata=metadata,
                    content=_content_json(changed, metadata),
                    policy_hash=policy_hash,
                    facts=facts,
                    episode_id=post["episode_id"],
                    metered=metered,
                    suppression_reason=suppression_reason,
                    platform=Platform(post["platform"]),
                    next_version=next_version,
                )

            if rollback_of is not None:
                target = tx.fetchone(
                    "SELECT id, metadata FROM metadata_versions "
                    "WHERE id = %s AND platform_post_id = %s",
                    (rollback_of, post_id),
                )
                if target is None:
                    raise NotFound(f"rollback target {rollback_of} is not a version of this post")
                if target["id"] == current_version_id:
                    raise PolicyDenied("rollback target is already the current version")
                if metadata != PostMetadata.model_validate(target["metadata"]):
                    raise SchemaInvalid(
                        "a rollback must restore the target version's metadata exactly"
                    )
                changed = _changed_fields(current_metadata, metadata)
                kind = _representative_kind(changed)
                if kind is None:
                    raise PolicyDenied("rollback changes nothing against the current version")
                return plan(kind, changed, metered=False, suppression_reason=None)
            if metadata == current_metadata:
                raise PolicyDenied("metadata unchanged; nothing to apply")
            changed = _changed_fields(current_metadata, metadata)
            kind = _representative_kind(changed)
            assert kind is not None  # unequal metadata always changes a field
            substantive = meta.substantive_change(current_metadata, metadata)
            if substantive:
                disallowed = [
                    field
                    for field in changed
                    if _kind_for_field(field) is not None
                    and _kind_for_field(field) not in policy.allowed_actions
                ]
                if disallowed:
                    return plan(
                        kind, changed, metered=False,
                        suppression_reason="NOT_ALLOWED_BY_POLICY:" + ",".join(disallowed),
                    )  # fmt: skip
                violations: list[str] = []
                for text_field in ("title", "caption", "description"):
                    violations.extend(validate_claims(getattr(metadata, text_field), facts))
                if metadata.hashtags != current_metadata.hashtags:
                    unapproved = set(metadata.hashtags) - facts.approved_hashtags
                    if unapproved:
                        violations.append("HASHTAG_NOT_APPROVED:" + ",".join(sorted(unapproved)))
                if violations:
                    return plan(
                        kind, changed, metered=False,
                        suppression_reason="UNGROUNDED_CLAIM:" + ",".join(violations),
                    )  # fmt: skip
                reason = self._edit_window_gates(tx, post, policy=policy, now=now)
                if reason is not None:
                    return plan(kind, changed, metered=False, suppression_reason=reason)
            return plan(kind, changed, metered=True, suppression_reason=None)

    def _edit_window_gates(
        self, tx: Tx, post: dict[str, Any], *, policy: ManagementPolicy, now: datetime
    ) -> str | None:
        """24h cooldown between substantive edits; at most two in the first 7 days.

        The cooldown runs between EDITS (version 2 onward): version 1 is the
        initial publication, not an edit, so the first optimization may run
        immediately after publish. Rollback versions are exempt entirely (see
        apply_metadata_edit).
        """
        last_substantive = tx.fetchone(
            "SELECT applied_at FROM metadata_versions WHERE platform_post_id = %s "
            "AND substantive AND rollback_of IS NULL AND version >= 2 "
            "AND applied_at IS NOT NULL ORDER BY version DESC LIMIT 1",
            (post["id"],),
        )
        if last_substantive is not None:
            elapsed = now - _aware(last_substantive["applied_at"], "applied_at")
            if elapsed < timedelta(hours=policy.metadata_cooldown_hours):
                return "METADATA_COOLDOWN"
        anchor = post["submitted_at"] or post["verified_at"] or post["created_at"]
        window_end = _aware(anchor, "publish_anchor") + timedelta(days=7)
        if now <= window_end:
            edits_in_window = tx.fetchval(
                "SELECT count(*) FROM metadata_versions WHERE platform_post_id = %s "
                "AND substantive AND rollback_of IS NULL AND version >= 2 "
                "AND applied_at IS NOT NULL AND applied_at <= %s",
                (post["id"], window_end),
            )
            if int(edits_in_window or 0) >= policy.max_substantive_edits_first_7_days:
                return "SUBSTANTIVE_EDIT_CAP"
        return None


_FIELD_KIND_ORDER: tuple[tuple[str, ManagementActionKind], ...] = (
    ("title", ManagementActionKind.TITLE_EDIT),
    ("caption", ManagementActionKind.CAPTION_EDIT),
    ("description", ManagementActionKind.DESCRIPTION_EDIT),
    ("hashtags", ManagementActionKind.HASHTAG_EDIT),
    ("cover_asset_id", ManagementActionKind.COVER_CHANGE),
    ("links", ManagementActionKind.LINK_UPDATE),
)


def _kind_for_field(field_name: str) -> ManagementActionKind | None:
    for name, action_kind in _FIELD_KIND_ORDER:
        if name == field_name:
            return action_kind
    return None


def _changed_fields(old: PostMetadata, new: PostMetadata) -> list[str]:
    return [name for name, _kind in _FIELD_KIND_ORDER if getattr(old, name) != getattr(new, name)]


def _representative_kind(changed: list[str]) -> ManagementActionKind | None:
    for name, action_kind in _FIELD_KIND_ORDER:
        if name in changed:
            return action_kind
    return None


def _content_json(changed: list[str], metadata: PostMetadata) -> str:
    """Compact changed-fields JSON (the audit content; bounded well under 5000 chars)."""
    return json.dumps(
        {field: getattr(metadata, field) for field in changed},
        ensure_ascii=False,
        default=str,
    )


def _policy_hash_of(policy: ManagementPolicy) -> str:
    from microdrama.contracts.hashing import canonical_hash

    return canonical_hash(policy)


def _retry_after_ms_of(reason: str | None) -> int | None:
    if not reason or "retry_after_ms=" not in reason:
        return None
    try:
        return int(reason.split("retry_after_ms=")[1].split(":")[0].strip())
    except (ValueError, IndexError):
        return None


def _attempt_of(reason: str | None) -> int:
    if not reason or ".attempt=" not in reason:
        return 1
    try:
        return int(reason.split(".attempt=")[1].split(":")[0].strip())
    except (ValueError, IndexError):
        return 1


def _with_attempt(reason: str | None, attempt: int) -> str:
    return f"{reason or 'DEFERRED'}.attempt={attempt}"


@dataclass(frozen=True)
class _MetadataPlan:
    post: dict[str, Any]
    kind: ManagementActionKind
    metadata: PostMetadata
    content: str
    policy_hash: str
    facts: GroundingFacts
    episode_id: UUID
    metered: bool
    suppression_reason: str | None
    platform: Platform
    #: Version number the edit will occupy (dense per-post); part of the dedupe
    #: key so re-applying the same content later is a new logical edit, not a replay.
    next_version: int

    def build_action(self, action_id: UUID) -> ManagementAction:
        cost = METERED_ACTION_COST_MICRO_USD if self.metered else 0
        return ManagementAction(
            action_id=action_id,
            kind=self.kind,
            platform=self.platform,
            account_ref=self.post["account_ref"],
            platform_post_id=self.post["id"],
            community_event_id=None,
            content=self.content,
            catalog_version=self.facts.catalog_version,
            management_policy_hash=self.policy_hash,
            dedupe_key=f"meta:{self.post['id']}:v{self.next_version}:"
            f"{meta.metadata_hash(self.metadata)}",
            estimated_cost_micro_usd=cost,
        )


class LiveCommunityProvider:
    """Named refusal: no live community transport exists until the controlled
    account tests of T032 qualify one. Constructing this class is a PolicyDenied
    error by design — offline mocks are the only implemented route."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise PolicyDenied("live community actions disabled until T032")


def build_community_service(
    settings: Any,
    db: Database,
    clock: Any,
    ids: Any,
    providers: Mapping[Platform, CommunityProvider],
    budget: BudgetService,
    *,
    max_actions_per_run: int = DEFAULT_MAX_ACTIONS_PER_RUN,
) -> CommunityService:
    """Build the OFFLINE_MOCK community service (fake providers only, T007 fakes).

    Raises EffectDenied in any other execution mode: fake providers exist only
    offline, and the live route is the named refusal above until T032.
    """
    from microdrama.testing.fakes.common import ensure_mock_mode

    ensure_mock_mode(settings)
    return CommunityService(
        db,
        clock,
        ids,
        providers,
        budget,
        max_actions_per_run=max_actions_per_run,
    )


__all__ = [
    "DEFAULT_MAX_ACTIONS_PER_RUN",
    "METERED_ACTION_COST_MICRO_USD",
    "METERED_TIMEOUT_MS",
    "CommunityService",
    "IngestReport",
    "LiveCommunityProvider",
    "ProcessReport",
    "RESERVATION_TTL",
    "build_community_service",
    "classification_from_text",
    "classification_to_text",
]
