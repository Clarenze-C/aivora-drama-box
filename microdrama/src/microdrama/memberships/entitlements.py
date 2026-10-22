"""Provider entitlements and signature-verified webhooks (T026).

Access decisions flow ONLY from ``EntitlementCheck`` results tied to the CURRENT
catalog entry: ``active=True`` grants, ``active=False`` (revoked) and
``active=None`` (could not verify) always deny — an unlisted link is never
entitlement enforcement and there is no fallback link. Raw member identifiers are
never persisted: only ``member_ref_hash`` (SHA-256) reaches ``entitlement_links``.

Webhook payload contract (offline fixture shape, interpreted only AFTER signature
verification; the live Patreon payload mapping is a T032 concern)::

    {"id": "evt-1", "type": "members:pledge:create" | "members:pledge:delete",
     "member_ref": "member-123", "episode_id": "<uuid>"}

Dedupe: every VALID webhook is recorded in ``webhook_events`` keyed by
``(provider, event_id)`` before interpretation; a duplicate delivery is reported
as such and never repeats its effect. INVALID webhooks are rejected before any
record: they carry no event id, and the ``WebhookVerification`` contract already
guarantees their payload is never passed on. A webhook updates entitlement rows
for bookkeeping only — it never sends messages and never grants access by itself.

Metering: each provider entitlement check consumes one metered-management REQUEST
through the REAL BudgetService (reserve before the provider call, settle with a
receipt after). An exhausted metered allocation suppresses the optional check
truthfully: the decision stays "could not verify" (never entitled) and is flagged
``metered_suppressed`` — AT-11.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from microdrama.budget.service import BudgetService
from microdrama.contracts.enums import CatalogPublicState
from microdrama.contracts.errors import BudgetExhausted, SchemaInvalid
from microdrama.contracts.infra import Clock, IdGenerator
from microdrama.contracts.primitives import ShortText
from microdrama.contracts.providers import MembershipProvider
from microdrama.core.events import append_event
from microdrama.memberships.catalog import MembershipCatalogService, member_ref_hash
from microdrama.memberships.metering import reserve_metered_request, settle_metered_request
from microdrama.persistence.db import Database, Tx, jsonb

#: Fixture webhook event types the service interprets (documented shape above).
PLEDGE_CREATE_TYPES = frozenset({"members:pledge:create", "members:subscription:create"})
PLEDGE_END_TYPES = frozenset(
    {"members:pledge:delete", "members:pledge:update:cancelled", "members:subscription:delete"}
)

_CHECK_OPERATION = "membership.check_entitlement"


def _sanitized_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Privacy before persistence: raw member identifiers are hashed in stored payloads.

    Dedupe is unaffected (it keys on ``event_id``); every other field is stored
    verbatim for audit.
    """
    stored = dict(payload)
    ref = stored.get("member_ref")
    if isinstance(ref, str) and ref:
        stored["member_ref_hash"] = member_ref_hash(ref)
        del stored["member_ref"]
    return stored


@dataclass(frozen=True)
class EntitlementDecision:
    """The only shape access decisions may come from."""

    entitled: bool
    active: bool | None  # None = could not verify; never treated as entitled
    tier: ShortText | None = None
    reason: str = ""
    reservation_id: UUID | None = None
    metered_suppressed: bool = False

    @property
    def never_entitled(self) -> bool:
        return not self.entitled


@dataclass(frozen=True)
class WebhookOutcome:
    valid: bool
    duplicate: bool = False
    applied: bool = False
    event_id: str | None = None
    event_type: str | None = None
    active: bool | None = None
    failure_reason: str | None = None
    reason: str | None = None


class EntitlementService:
    """Provider checks + verified webhook bookkeeping over the frozen tables."""

    def __init__(
        self,
        db: Database,
        clock: Clock,
        ids: IdGenerator,
        provider: MembershipProvider,
        catalog: MembershipCatalogService,
        budget: BudgetService,
    ) -> None:
        self._db = db
        self._clock = clock
        self._ids = ids
        self._provider = provider
        self._catalog = catalog
        self._budget = budget
        self._provider_id = getattr(provider, "provider_id", provider.kind.value.lower())

    # --- entitlement checks ----------------------------------------------------------------

    def check(self, *, member_ref: str, episode_id: UUID) -> EntitlementDecision:
        """One metered provider entitlement check against the CURRENT entry."""
        if not member_ref or not member_ref.strip():
            raise SchemaInvalid("member_ref is required")
        entry = self._catalog.current_entry(episode_id)
        if entry is None or entry.member_provider is None:
            # No gated member route exists for this episode: nothing to check or
            # grant. Public-free access flows from the catalog, never from here.
            return EntitlementDecision(
                entitled=False,
                active=None,
                reason="no member-gated catalog entry for this episode",
            )
        if entry.member_provider is not self._provider.kind:
            return EntitlementDecision(
                entitled=False,
                active=None,
                reason="catalog entry uses a different membership provider",
            )

        try:
            request_id = self._ids.new_id()
            reservation = reserve_metered_request(
                self._budget,
                self._clock,
                request_id=request_id,
                # One logical paid step per verification: the request id makes the
                # semantic key unique per check while staying a valid SemanticKey.
                semantic_key=f"entitlement:{self._provider_id}:"
                f"{member_ref_hash(member_ref)[:16]}:{entry.catalog_version}:{request_id}",
                episode_id=episode_id,
                provider=self._provider_id,
                operation_kind=_CHECK_OPERATION,
            )
        except BudgetExhausted:
            # AT-11: insufficient metered-management budget suppresses the optional
            # check. "Could not verify" is the truthful answer; it never becomes an
            # entitlement and never borrows another category's funds.
            return EntitlementDecision(
                entitled=False,
                active=None,
                reason="metered-management budget exhausted; entitlement could not be "
                "verified (never treated as entitled)",
                metered_suppressed=True,
            )

        try:
            result = self._provider.check_entitlement(member_ref, entry)
        except Exception:
            # The provider failed after reservation: settle what was held (the
            # worst case was reserved for exactly this call), then surface the
            # failure as unverifiable — never as success.
            settle_metered_request(
                self._budget,
                self._clock,
                provider=self._provider_id,
                provider_receipt_id=f"entitlement-failed:{reservation.id}",
                reservation_id=reservation.id,
            )
            raise
        settle_metered_request(
            self._budget,
            self._clock,
            provider=self._provider_id,
            provider_receipt_id=f"entitlement:{reservation.id}",
            reservation_id=reservation.id,
        )
        self._upsert_link(
            entry=entry,
            member_ref=member_ref,
            active=result.active,
            verification_method="provider_api",
            verified_at=result.verified_at,
            last_webhook_event=None,
        )
        entitled = (
            result.active is True and entry.public_state is CatalogPublicState.EARLY_ACCESS_MEMBERS
        )
        reason = {
            True: "active member entitlement verified against the current entry",
            False: "entitlement revoked by the provider",
            None: "provider could not verify entitlement; never treated as entitled",
        }[result.active]
        return EntitlementDecision(
            entitled=entitled,
            active=result.active,
            tier=result.tier,
            reason=reason,
            reservation_id=reservation.id,
        )

    # --- webhooks ---------------------------------------------------------------------------

    def process_webhook(self, headers: dict[str, str], body: bytes) -> WebhookOutcome:
        """Verify → dedupe → interpret. Invalid webhooks stop at verification."""
        verification = self._provider.verify_webhook(headers, body)
        if not verification.valid:
            # No row, no interpretation, no payload passed on (the contract keeps
            # WebhookVerification.payload empty for invalid verifications).
            return WebhookOutcome(valid=False, failure_reason=verification.failure_reason)

        provider_name = self._provider.kind.value
        with self._db.transaction() as tx:
            row = tx.fetchone(
                "INSERT INTO webhook_events (id, provider, event_id, event_type, "
                "signature_valid, payload, received_at) VALUES (%s, %s, %s, %s, true, %s, %s) "
                "ON CONFLICT (provider, event_id) DO NOTHING RETURNING id",
                (
                    self._ids.new_id(),
                    provider_name,
                    verification.event_id,
                    verification.event_type,
                    jsonb(_sanitized_payload(verification.payload)),
                    self._clock.now(),
                ),
            )
            if row is None:
                # Duplicate delivery of a known event id: already deduped, never a
                # repeated effect (in particular never a repeated unlock message).
                return WebhookOutcome(
                    valid=True,
                    duplicate=True,
                    applied=False,
                    event_id=verification.event_id,
                    event_type=verification.event_type,
                    reason="duplicate webhook event id",
                )
            outcome = self._interpret(
                tx, row["id"], verification.event_id, verification.event_type, verification.payload
            )
            tx.execute(
                "UPDATE webhook_events SET processed_at = %s WHERE id = %s",
                (self._clock.now(), row["id"]),
            )
        return outcome

    def _interpret(
        self,
        tx: Tx,
        webhook_row_id: UUID,
        event_id: str,
        event_type: str | None,
        payload: dict[str, Any],
    ) -> WebhookOutcome:
        base = WebhookOutcome(valid=True, applied=False, event_id=event_id, event_type=event_type)
        if event_type in PLEDGE_CREATE_TYPES:
            active: bool | None = True
        elif event_type in PLEDGE_END_TYPES:
            active = False
        else:
            return replace(base, reason="unknown webhook event type recorded without effect")
        member_ref = payload.get("member_ref")
        episode_raw = payload.get("episode_id")
        if not isinstance(member_ref, str) or not member_ref.strip():
            return replace(
                base, active=active, reason="webhook payload carries no usable member_ref"
            )
        try:
            episode_id = UUID(str(episode_raw))
        except (TypeError, ValueError):
            return replace(
                base, active=active, reason="webhook payload carries no usable episode_id"
            )
        entry = self._catalog.current_entry(episode_id)
        if entry is None or entry.member_provider is not self._provider.kind:
            return replace(
                base,
                active=active,
                reason="no member-gated current catalog entry for the webhook target",
            )
        self._upsert_link(
            entry=entry,
            member_ref=member_ref,
            active=active,
            verification_method="webhook_signature",
            verified_at=self._clock.now(),
            last_webhook_event=webhook_row_id,
            tx=tx,  # same transaction as the webhook row (FK visibility)
        )
        append_event(
            tx,
            aggregate_type="membership_entitlement",
            aggregate_id=webhook_row_id,  # one aggregate per verified webhook event
            event_type="membership.entitlement_webhook",
            payload={
                "event_id": event_id,
                "event_type": event_type or "",
                "active": active,
                "member_ref_hash": member_ref_hash(member_ref),
            },
            correlation_id=self._ids.new_id(),
            occurred_at=self._clock.now(),
        )
        return WebhookOutcome(
            valid=True,
            applied=True,
            event_id=event_id,
            event_type=event_type,
            active=active,
        )

    # --- link rows --------------------------------------------------------------------------

    def _upsert_link(
        self,
        *,
        entry,
        member_ref: str,
        active: bool | None,
        verification_method: str,
        verified_at,
        last_webhook_event: UUID | None,
        tx: Tx | None = None,
    ) -> None:
        """Upsert one entitlement_link row. ONLY the hash of member_ref is stored.

        ``tx`` lets a caller keep the upsert in the same transaction as the
        webhook row that justifies it (the FK to ``webhook_events`` must see it).
        """

        def run(tx: Tx) -> None:
            hashed = member_ref_hash(member_ref)  # raw member identifiers never persist
            tx.execute(
                "INSERT INTO entitlement_links (id, provider, member_ref_hash, "
                "catalog_entry_id, member_post_id, active, verification_method, verified_at, "
                "last_webhook_event) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (provider, member_ref_hash, catalog_entry_id) DO UPDATE SET "
                "active = EXCLUDED.active, "
                "verification_method = EXCLUDED.verification_method, "
                "verified_at = EXCLUDED.verified_at, member_post_id = EXCLUDED.member_post_id, "
                "last_webhook_event = COALESCE(EXCLUDED.last_webhook_event, "
                "entitlement_links.last_webhook_event), "
                "updated_at = now(), revision = entitlement_links.revision + 1",
                (
                    self._ids.new_id(),
                    self._provider.kind.value,
                    hashed,
                    entry.entry_id,
                    entry.member_post_id,
                    active,
                    verification_method,
                    verified_at,
                    last_webhook_event,
                ),
            )

        if tx is not None:
            run(tx)
            return
        with self._db.transaction() as fresh:
            run(fresh)

    # --- reads for tests/diagnostics ---------------------------------------------------------

    def link_row(self, *, member_ref: str, entry_id: UUID):
        hashed = member_ref_hash(member_ref)
        with self._db.transaction(readonly=True) as tx:
            return tx.fetchone(
                "SELECT * FROM entitlement_links WHERE provider = %s AND member_ref_hash = %s "
                "AND catalog_entry_id = %s",
                (self._provider.kind.value, hashed, entry_id),
            )


__all__ = [
    "EntitlementDecision",
    "EntitlementService",
    "WebhookOutcome",
    "PLEDGE_CREATE_TYPES",
    "PLEDGE_END_TYPES",
]
