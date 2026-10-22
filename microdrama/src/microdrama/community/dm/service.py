"""Permitted inbound keyword DM delivery for the membership lane (T026, MD-018).

Scope and honesty rules this service enforces (each pinned by a test):

- **Configured keywords only.** An inbound event is answered only when it is a
  DIRECT_MESSAGE, COMMENT or REPLY whose text contains one of the policy's
  ``dm_keywords``. A public comment is NOT blanket permission: it earns at most
  one unlock message for the episode it asked about, and nothing else.
- **No cold outreach (MD-018).** The ONLY send path is ``handle_inbound`` with a
  provider-delivered event; the service has no initiate method, and the policy's
  ``cold_outbound_dms=False`` is enforced by the contract itself.
- **Messaging-window eligibility.** A DM is sent only while the recipient's
  messaging window (``dm_window_expires_at`` on the event) is still open at the
  injected clock's now; an expired or missing window suppresses the send. A
  comment alone never opens a DM conversation (public replies are T025's lane).
- **Recipient restrictions.** Blocked recipients and the account itself are never
  messaged; DM_SEND must be in the approved management policy's allowed actions.
- **Caps and dedupe.** Events dedupe by provider event id (at-least-once
  delivery); an EXECUTED unlock for the same (platform, account, author,
  episode) never repeats — duplicate comments never produce repeated unlock
  messages; the per-conversation EXECUTED-DM count is capped at
  ``policy.max_dms_per_conversation``. A transiently DEFERRED send keeps its
  reservation and dedupe key and is retried on the next inbound event.
- **Truthful content (MD-016/AT-11).** Content comes only from
  ``community.dm.messages`` built on current catalog facts + a provider
  entitlement decision: free continuation vs paid early access is distinguished
  BEFORE checkout; revoked/unverifiable entitlement yields NO member link.
- **Real metering.** Every provider call (the entitlement check inside, and the
  DM send itself) consumes METERED_MANAGEMENT through the real BudgetService —
  reserve before execute, settle with receipts. An insufficient metered
  allocation suppresses the optional action truthfully (SUPPRESSED, reason
  recorded, nothing claimed as delivered); it never borrows protected funds and
  never lies in a message.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from microdrama.budget.service import BudgetService
from microdrama.community.dm.messages import DmMessage, message_for
from microdrama.contracts.enums import (
    ActionDecision,
    CommunityEventKind,
    ManagementActionKind,
    PriceUnit,
)
from microdrama.contracts.errors import BudgetExhausted, SchemaInvalid
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.infra import Clock, IdGenerator
from microdrama.contracts.providers import CommunityEventIn, CommunityProvider
from microdrama.contracts.release import ManagementAction
from microdrama.contracts.season import ManagementPolicy
from microdrama.memberships.catalog import MembershipCatalogService
from microdrama.memberships.entitlements import EntitlementDecision, EntitlementService
from microdrama.memberships.metering import reserve_metered_request, settle_metered_request
from microdrama.persistence.db import Database, insert_row, jsonb
from microdrama.testing.fakes.common import priced

_DM_KINDS = frozenset(
    {CommunityEventKind.DIRECT_MESSAGE, CommunityEventKind.COMMENT, CommunityEventKind.REPLY}
)
_DM_SEND_OPERATION = "community.dm_send"
#: One unlock message per (platform, account, author, episode) — duplicates never repeat.
_UNLOCK_KEY = "dm-unlock:{platform}:{account}:{author}:{episode}"
_IGNORED_REASONS = frozenset({"NO_KEYWORD", "NOT_A_PERMITTED_EVENT"})


class DmStatus(StrEnum):
    SENT = "SENT"
    DEFERRED = "DEFERRED"  # transient provider state; reservation held for retry
    DUPLICATE_DELIVERY = "DUPLICATE_DELIVERY"  # same provider event id seen before
    IGNORED = "IGNORED"  # not a permitted interaction (no keyword / wrong kind)
    SUPPRESSED = "SUPPRESSED"  # policy truth: window, caps, recipient or budget


class DmReason(StrEnum):
    NOT_A_PERMITTED_EVENT = "NOT_A_PERMITTED_EVENT"
    NO_KEYWORD = "NO_KEYWORD"
    BLOCKED_RECIPIENT = "BLOCKED_RECIPIENT"
    NO_MESSAGING_WINDOW = "NO_MESSAGING_WINDOW"
    WINDOW_EXPIRED = "WINDOW_EXPIRED"
    DM_SEND_NOT_ALLOWED = "DM_SEND_NOT_ALLOWED"
    CONVERSATION_CAP = "CONVERSATION_CAP"
    UNLOCK_ALREADY_SENT = "UNLOCK_ALREADY_SENT"
    METERED_BUDGET_EXHAUSTED = "METERED_BUDGET_EXHAUSTED"


@dataclass(frozen=True)
class DmOutcome:
    status: DmStatus
    reason: DmReason | None = None
    provider_error: str | None = None  # transient/failed provider error code
    event_id: UUID | None = None  # persisted community_events row
    action: ManagementAction | None = None
    message_content: str | None = None
    message_kind: str | None = None
    entitlement: EntitlementDecision | None = None
    catalog_version: int = 0

    @property
    def sent(self) -> bool:
        return self.status is DmStatus.SENT


class DmDeliveryService:
    """Keyword/inbound DM delivery over one community provider (offline fixture)."""

    def __init__(
        self,
        db: Database,
        clock: Clock,
        ids: IdGenerator,
        community: CommunityProvider,
        catalog: MembershipCatalogService,
        entitlements: EntitlementService,
        budget: BudgetService,
        policy: ManagementPolicy,
        *,
        provider_id: str | None = None,
        blocked_recipient_refs: frozenset[str] = frozenset(),
    ) -> None:
        self._db = db
        self._clock = clock
        self._ids = ids
        self._community = community
        self._catalog = catalog
        self._entitlements = entitlements
        self._budget = budget
        self._policy = policy
        self._policy_hash = canonical_hash(policy)
        self._keywords = tuple(policy.dm_keywords)
        self._provider_id = provider_id or getattr(
            community, "provider_id", f"community-{community.platform.value.lower()}"
        )
        self._blocked = blocked_recipient_refs

    # --- the only send path -----------------------------------------------------------------

    def handle_inbound(self, event: CommunityEventIn, *, episode_id: UUID) -> DmOutcome:
        """Answer one inbound provider event. Nothing is ever sent without one."""
        if event.platform is not self._community.platform:
            raise SchemaInvalid(
                "event platform does not match the community provider",
                event_platform=event.platform.value,
            )
        with self._db.transaction() as tx:
            recorded = tx.fetchone(
                "INSERT INTO community_events (id, platform, account_ref, provider_event_id, "
                "kind, external_post_id, author_ref, text, received_at, dm_window_expires_at, "
                "classification, status, provenance) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, "
                "%s, %s, %s, 'RECEIVED', %s) "
                "ON CONFLICT (platform, account_ref, provider_event_id) DO NOTHING RETURNING id",
                (
                    self._ids.new_id(),
                    event.platform.value,
                    event.account_ref,
                    event.provider_event_id,
                    event.kind.value,
                    event.external_post_id,
                    event.author_ref,
                    event.text,
                    event.received_at,
                    event.dm_window_expires_at,
                    "membership_keyword_dm",
                    event.provenance.value,
                ),
            )
        if recorded is None:
            # At-least-once delivery: this exact event was handled before, so it
            # never earns a repeated message.
            return DmOutcome(status=DmStatus.DUPLICATE_DELIVERY)

        unlock_key = _UNLOCK_KEY.format(
            platform=event.platform.value,
            account=event.account_ref,
            author=event.author_ref,
            episode=str(episode_id),
        )
        reason = self._ineligibility_reason(event, unlock_key)
        if reason is not None:
            self._close_event(
                recorded["id"], "IGNORED" if reason.value in _IGNORED_REASONS else "SUPPRESSED"
            )
            return DmOutcome(
                status=DmStatus.IGNORED
                if reason.value in _IGNORED_REASONS
                else DmStatus.SUPPRESSED,
                reason=reason,
                event_id=recorded["id"],
            )

        # Retry path: a transiently DEFERRED unlock keeps its reservation and key.
        deferred = self._load_action(unlock_key, ActionDecision.DEFERRED)
        if deferred is not None:
            return self._retry_deferred(recorded["id"], deferred)

        facts = self._catalog.facts(episode_id)
        decision: EntitlementDecision | None = None
        if facts.entry is not None and facts.entry.member_provider is not None:
            # Metered provider check (reserves/settles internally); a suppressed
            # check returns could-not-verify, which never becomes access.
            decision = self._entitlements.check(member_ref=event.author_ref, episode_id=episode_id)
        message: DmMessage = message_for(facts, decision)

        try:
            reservation = reserve_metered_request(
                self._budget,
                self._clock,
                request_id=self._ids.new_id(),
                semantic_key=unlock_key,
                episode_id=episode_id,
                provider=self._provider_id,
                operation_kind=_DM_SEND_OPERATION,
            )
        except BudgetExhausted:
            # AT-11: insufficient metered-management budget suppresses the
            # optional send. No message goes out, nothing is claimed delivered,
            # and the catalog facts are untouched — that is the truthful state.
            self._close_event(recorded["id"], "SUPPRESSED")
            return DmOutcome(
                status=DmStatus.SUPPRESSED,
                reason=DmReason.METERED_BUDGET_EXHAUSTED,
                event_id=recorded["id"],
                message_kind=message.kind,
                catalog_version=facts.catalog_version,
                entitlement=decision,
            )

        action = ManagementAction(
            action_id=self._ids.new_id(),
            kind=ManagementActionKind.DM_SEND,
            platform=event.platform,
            account_ref=event.account_ref,
            community_event_id=recorded["id"],
            target_external_id=event.provider_event_id,
            content=message.content,
            catalog_version=max(facts.catalog_version, 1),
            management_policy_hash=self._policy_hash,
            dedupe_key=unlock_key,
            reservation_id=reservation.id,
            estimated_cost_micro_usd=priced(PriceUnit.REQUEST, 1),
            reason=f"keyword unlock dm ({message.kind})",
        )
        return self._execute(recorded["id"], action)

    # --- eligibility -------------------------------------------------------------------------

    def _ineligibility_reason(self, event: CommunityEventIn, unlock_key: str) -> DmReason | None:
        if ManagementActionKind.DM_SEND not in self._policy.allowed_actions:
            return DmReason.DM_SEND_NOT_ALLOWED
        if event.kind not in _DM_KINDS:
            return DmReason.NOT_A_PERMITTED_EVENT
        if not self._keyword_in(event.text):
            return DmReason.NO_KEYWORD
        if event.author_ref in self._blocked or event.author_ref == event.account_ref:
            return DmReason.BLOCKED_RECIPIENT
        if event.dm_window_expires_at is None:
            return DmReason.NO_MESSAGING_WINDOW
        if self._clock.now() >= event.dm_window_expires_at:
            return DmReason.WINDOW_EXPIRED
        if self._conversation_sent(event) >= self._policy.max_dms_per_conversation:
            return DmReason.CONVERSATION_CAP
        if self._load_action(unlock_key, ActionDecision.EXECUTED) is not None:
            return DmReason.UNLOCK_ALREADY_SENT
        return None

    def _keyword_in(self, text: str) -> bool:
        # Untrusted text is data: the only thing read from it is keyword containment.
        lowered = text.casefold()
        return any(keyword.casefold() in lowered for keyword in self._keywords)

    def _conversation_sent(self, event: CommunityEventIn) -> int:
        with self._db.transaction(readonly=True) as tx:
            row = tx.fetchone(
                "SELECT count(*) AS n FROM management_actions a JOIN community_events e "
                "ON e.id = a.community_event_id "
                "WHERE a.kind = 'DM_SEND' AND a.decision = 'EXECUTED' "
                "AND a.platform = %s AND a.account_ref = %s AND e.author_ref = %s",
                (event.platform.value, event.account_ref, event.author_ref),
            )
        return int(row["n"])

    def _load_action(self, dedupe_key: str, decision: ActionDecision):
        with self._db.transaction(readonly=True) as tx:
            return tx.fetchone(
                "SELECT * FROM management_actions WHERE dedupe_key = %s AND decision = %s",
                (dedupe_key, decision.value),
            )

    # --- execution ---------------------------------------------------------------------------

    def _execute(self, event_row_id: UUID, action: ManagementAction) -> DmOutcome:
        result = self._community.execute(action)
        if result.decision is ActionDecision.EXECUTED:
            self._settle(action.reservation_id, result.usage)
            final = action.model_copy(update={"decision": ActionDecision.EXECUTED})
            self._persist_action(final, result.external_id)
            self._close_event(event_row_id, "ACTIONED")
            return DmOutcome(
                status=DmStatus.SENT,
                event_id=event_row_id,
                action=final,
                message_content=final.content,
                message_kind=_message_kind_of(final),
                catalog_version=final.catalog_version,
            )
        if result.decision is ActionDecision.DEFERRED and result.transient:
            # Transient provider state: the reservation stays held; the retry
            # (next inbound event) reuses the same dedupe key and reservation.
            final = action.model_copy(
                update={
                    "decision": ActionDecision.DEFERRED,
                    "reason": result.error_code or "DEFERRED_BY_PROVIDER",
                }
            )
            self._persist_action(final, None)
            self._close_event(event_row_id, "DEFERRED")
            return DmOutcome(
                status=DmStatus.DEFERRED,
                provider_error=result.error_code,
                event_id=event_row_id,
                action=final,
                message_content=final.content,
                message_kind=_message_kind_of(final),
                catalog_version=final.catalog_version,
            )
        # Non-transient provider refusal: release the reservation (nothing ran)
        # and record the failure honestly.
        if action.reservation_id is not None:
            self._budget.release(
                action.reservation_id, reason=f"dm send refused: {result.error_code}"
            )
        final = action.model_copy(
            update={"decision": ActionDecision.FAILED, "reason": result.error_code or "FAILED"}
        )
        self._persist_action(final, None)
        self._close_event(event_row_id, "SUPPRESSED")
        return DmOutcome(
            status=DmStatus.SUPPRESSED,
            provider_error=result.error_code,
            event_id=event_row_id,
            action=final,
            catalog_version=final.catalog_version,
        )

    def _retry_deferred(self, event_row_id: UUID, deferred_row) -> DmOutcome:
        """Retry a DEFERRED unlock: same dedupe key, same reservation, no new reserve."""
        stored = ManagementAction.model_validate(deferred_row["body"])
        attempt = stored.model_copy(
            update={
                "community_event_id": event_row_id,
                "decision": ActionDecision.PROPOSED,  # providers execute PROPOSED actions
            }
        )
        result = self._community.execute(attempt)
        if result.decision is ActionDecision.EXECUTED:
            self._settle(stored.reservation_id, result.usage)
            final = stored.model_copy(update={"decision": ActionDecision.EXECUTED})
            self._mark_action_executed(final, result.external_id)
            self._close_event(event_row_id, "ACTIONED")
            return DmOutcome(
                status=DmStatus.SENT,
                event_id=event_row_id,
                action=final,
                message_content=stored.content,
                message_kind=_message_kind_of(stored),
                catalog_version=stored.catalog_version,
            )
        self._close_event(event_row_id, "DEFERRED")
        return DmOutcome(
            status=DmStatus.DEFERRED,
            provider_error=result.error_code,
            event_id=event_row_id,
            action=stored,
            message_content=stored.content,
            message_kind=_message_kind_of(stored),
            catalog_version=stored.catalog_version,
        )

    def _settle(self, reservation_id: UUID | None, usage) -> None:
        """Settle with the provider's own receipts, or a synthetic settlement."""
        if reservation_id is None:
            return
        if usage:
            for receipt in usage:
                self._budget.record_usage(receipt)
            return
        settle_metered_request(
            self._budget,
            self._clock,
            provider=self._provider_id,
            provider_receipt_id=f"dm-send:{reservation_id}",
            reservation_id=reservation_id,
        )

    # --- persistence ---------------------------------------------------------------------------

    def _persist_action(self, action: ManagementAction, external_id: str | None) -> None:
        with self._db.transaction() as tx:
            insert_row(
                tx,
                "management_actions",
                {
                    "id": action.action_id,
                    "kind": action.kind.value,
                    "platform": action.platform.value,
                    "account_ref": action.account_ref,
                    "community_event_id": action.community_event_id,
                    "dedupe_key": action.dedupe_key,
                    "body": jsonb(action),
                    "policy_hash": action.management_policy_hash,
                    "catalog_version": action.catalog_version,
                    "reservation_id": action.reservation_id,
                    "decision": action.decision.value,
                    "reason": action.reason,
                    "external_id": external_id,
                    "provenance": "FAKE_SYNTHETIC",
                    "executed_at": self._clock.now()
                    if action.decision is ActionDecision.EXECUTED
                    else None,
                },
            )

    def _mark_action_executed(self, action: ManagementAction, external_id: str | None) -> None:
        with self._db.transaction() as tx:
            tx.execute(
                "UPDATE management_actions SET decision = 'EXECUTED', external_id = %s, "
                "executed_at = %s, updated_at = now(), revision = revision + 1 "
                "WHERE dedupe_key = %s",
                (external_id, self._clock.now(), action.dedupe_key),
            )

    def _close_event(self, event_row_id: UUID, status: str) -> None:
        with self._db.transaction() as tx:
            tx.execute(
                "UPDATE community_events SET status = %s, updated_at = now() WHERE id = %s",
                (status, event_row_id),
            )


def _message_kind_of(action: ManagementAction) -> str | None:
    """The message kind recorded in the action reason (`keyword unlock dm (<kind>)`)."""
    if not action.reason or "(" not in action.reason:
        return None
    inner = action.reason.split("(", 1)[1]
    return inner.split(")", 1)[0] or None


__all__ = [
    "DmDeliveryService",
    "DmOutcome",
    "DmReason",
    "DmStatus",
]
