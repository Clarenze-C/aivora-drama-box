"""Patreon membership adapter (T026): route rules over the offline fixture transport.

This is the OFFLINE adapter behind the frozen ``MembershipProvider`` protocol
(``publish_early_access`` / ``check_entitlement`` / ``verify_webhook``). It contains
no local approval, catalog or budget logic — those gates stay in the membership
services — and it adds exactly the route rules:

- Route ownership: only ``PATREON`` catalog entries ride this adapter. An entry
  carrying another provider kind (or a transport of the wrong kind) is refused, so
  the optional BMC alternate can never be half-wired by accident.
- Publishing is accepted only for ``EARLY_ACCESS_MEMBERS`` entries; the
  "cannot sell unfinished/unapproved media" truth lives in the catalog service and
  the contract validator, and the transport enforces the state a second time.
- Entitlement results pass through untouched: ``active=None`` (could not verify)
  is never rewritten into an entitlement — the consuming service denies on it.
- Webhook verification is delegated to the transport's verifier; the
  ``WebhookVerification`` contract already guarantees that an invalid webhook never
  carries its payload on and a valid one always names an event id for dedupe.

The transport is the T007 ``FakeMembershipProvider`` (HMAC-SHA256 signed webhooks,
scripted entitlement scenarios). A live transport is a NAMED REFUSAL until the
controlled account tests of T032 qualify the route: constructing
``LivePatreonTransport`` raises ``PolicyDenied("live membership disabled until T032")``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from microdrama.contracts.catalog import MembershipCatalogEntry
from microdrama.contracts.enums import CatalogPublicState, MembershipProviderKind, Provenance
from microdrama.contracts.errors import PolicyDenied
from microdrama.contracts.providers import (
    EntitlementCheck,
    MemberPostResult,
    WebhookVerification,
)
from microdrama.memberships.patreon.capabilities import (
    BMC_ALTERNATE_NOTE,
    OP_EARLY_ACCESS_PUBLISH,
    OP_ENTITLEMENT_CHECK,
    OP_WEBHOOK_VERIFY,
    PROVIDER_ROUTE,
    RESEARCH_OPERATIONS,
    MembershipRouteSnapshot,
    fixture_snapshot,
    research_snapshot,
)

#: Stable provider id for budget reservations and receipts on this route.
PROVIDER_ID = PROVIDER_ROUTE

LIVE_DISABLED_MESSAGE = "live membership disabled until T032"


class MembershipTransport(Protocol):
    """What the adapter needs from a transport (the T007 fake satisfies this)."""

    kind: MembershipProviderKind

    def publish_early_access(
        self, entry: MembershipCatalogEntry, media_path: Path
    ) -> MemberPostResult: ...

    def check_entitlement(
        self, member_ref: str, entry: MembershipCatalogEntry
    ) -> EntitlementCheck: ...

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> WebhookVerification: ...


class LivePatreonTransport:
    """Named refusal: no live Patreon transport exists until T032.

    Constructing this class raises. T032 (controlled real membership tests) is the
    only route to a live transport, and until then every result this lane produces
    is ``Provenance.FAKE_SYNTHETIC`` over ``*.invalid`` URLs.
    """

    def __init__(self) -> None:
        raise PolicyDenied(LIVE_DISABLED_MESSAGE, route=PROVIDER_ROUTE)


class PatreonMembershipAdapter:
    """``MembershipProvider`` for the selected Patreon route (offline fixture only)."""

    kind = MembershipProviderKind.PATREON
    provider_id = PROVIDER_ID
    provider_route = PROVIDER_ROUTE

    def __init__(self, transport: MembershipTransport) -> None:
        if transport.kind is not MembershipProviderKind.PATREON:
            raise PolicyDenied(
                "the patreon adapter only wraps a PATREON transport",
                transport_kind=transport.kind.value,
            )
        self.transport = transport

    def capability(self, *, verified_at, enabled: bool = True) -> MembershipRouteSnapshot:
        """The OFFLINE_MOCK route snapshot (FAKE_FIXTURE variant of the frozen research)."""
        return fixture_snapshot(verified_at=verified_at, enabled=enabled)

    @staticmethod
    def research_capability() -> MembershipRouteSnapshot:
        """The disabled documentation snapshot shipped with the lane."""
        return research_snapshot()

    # --- MembershipProvider ----------------------------------------------------------------

    def publish_early_access(
        self, entry: MembershipCatalogEntry, media_path: Path
    ) -> MemberPostResult:
        self._require_owned(entry)
        if entry.public_state is not CatalogPublicState.EARLY_ACCESS_MEMBERS:
            raise PolicyDenied(
                "only EARLY_ACCESS_MEMBERS catalog entries can be published to members",
                public_state=entry.public_state.value,
            )
        result = self.transport.publish_early_access(entry, media_path)
        if result.provenance is not Provenance.FAKE_SYNTHETIC:
            # An offline transport may never report live results; a live transport
            # does not exist yet (LivePatreonTransport).
            raise PolicyDenied(
                "offline membership transport reported non-fake provenance",
                provenance=result.provenance.value,
            )
        return result

    def check_entitlement(self, member_ref: str, entry: MembershipCatalogEntry) -> EntitlementCheck:
        self._require_owned(entry)
        check = self.transport.check_entitlement(member_ref, entry)
        # active=None (unverifiable) is passed through untouched: the caller must
        # deny on it, and rewriting it here would hide an unknown as a decision.
        if check.member_ref != member_ref:
            raise PolicyDenied("entitlement check returned a different member ref")
        return check

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> WebhookVerification:
        return self.transport.verify_webhook(headers, body)

    # --- helpers -----------------------------------------------------------------------------

    def _require_owned(self, entry: MembershipCatalogEntry) -> None:
        if entry.member_provider is not MembershipProviderKind.PATREON:
            raise PolicyDenied(
                "this catalog entry belongs to another membership provider",
                entry_provider=(entry.member_provider.value if entry.member_provider else "none"),
                route=PROVIDER_ROUTE,
            )


#: Operations snapshot for evidence/diagnostics. The route-level support values are
#: frozen in ``capabilities.RESEARCH_OPERATIONS``; early-access publishing stays
#: UNKNOWN on the API route (creator-tool surface) until T032 qualifies a live path.
ROUTE_OPERATION_IDS = (OP_ENTITLEMENT_CHECK, OP_WEBHOOK_VERIFY, OP_EARLY_ACCESS_PUBLISH)

__all__ = [
    "BMC_ALTERNATE_NOTE",
    "LIVE_DISABLED_MESSAGE",
    "LivePatreonTransport",
    "MembershipTransport",
    "OP_EARLY_ACCESS_PUBLISH",
    "OP_ENTITLEMENT_CHECK",
    "OP_WEBHOOK_VERIFY",
    "PROVIDER_ID",
    "PROVIDER_ROUTE",
    "PatreonMembershipAdapter",
    "RESEARCH_OPERATIONS",
    "ROUTE_OPERATION_IDS",
    "MembershipRouteSnapshot",
]
