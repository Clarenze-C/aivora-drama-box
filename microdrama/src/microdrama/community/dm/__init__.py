"""Permitted DM delivery beneath the community lane (T026).

Explicitly assigned to the membership lane: the parallel T025 social lane owns the
REST of ``community/`` and does not touch this subpackage. The exported factory
wires the DM delivery service over the real catalog/entitlement/budget services
and one community provider (offline fixture). No routes or jobs are registered
here — integration is the orchestrator's.

Seam contract with T025 (community service): this service consumes
``CommunityProvider.fetch_events`` output (``CommunityEventIn``) and executes
``DM_SEND`` ``ManagementAction``s through ``CommunityProvider.execute`` — the same
frozen protocol T025's organic service uses — plus the shared ``community_events``
(event dedupe by provider event id) and ``management_actions`` (action dedupe by
``dedupe_key``) tables. T025's reply/metadata actions and this lane's unlock DMs
therefore never double-send: both dedupe through the same unique keys, and this
service classifies its events with ``classification='membership_keyword_dm'``.
"""

from __future__ import annotations

from microdrama.budget.service import BudgetService
from microdrama.community.dm.messages import (
    DmMessage,
    early_access_offer,
    free_unlock,
    member_unlock,
    message_for,
    not_available,
    verification_unavailable,
    withdrawn,
)
from microdrama.community.dm.service import (
    DmDeliveryService,
    DmOutcome,
    DmReason,
    DmStatus,
)
from microdrama.contracts.enums import ManagementActionKind
from microdrama.contracts.errors import PolicyDenied
from microdrama.contracts.infra import Clock, IdGenerator
from microdrama.contracts.providers import CommunityProvider
from microdrama.contracts.season import ManagementPolicy
from microdrama.memberships.catalog import MembershipCatalogService
from microdrama.memberships.entitlements import EntitlementService
from microdrama.persistence import Database

__all__ = [
    "DmDeliveryService",
    "DmMessage",
    "DmOutcome",
    "DmReason",
    "DmStatus",
    "build_dm_delivery_service",
    "early_access_offer",
    "free_unlock",
    "member_unlock",
    "message_for",
    "not_available",
    "verification_unavailable",
    "withdrawn",
]


def build_dm_delivery_service(
    *,
    db: Database,
    clock: Clock,
    ids: IdGenerator,
    community: CommunityProvider,
    catalog: MembershipCatalogService,
    entitlements: EntitlementService,
    budget: BudgetService,
    policy: ManagementPolicy,
    blocked_recipient_refs: frozenset[str] = frozenset(),
) -> DmDeliveryService:
    """Wire the permitted DM delivery service (offline community fixture route).

    The provider id used for metered reservations/receipts is taken from the
    community provider when it exposes one (the T007 fake does) so provider-side
    receipts settle against their own reservation. ``PolicyDenied`` if the bound
    policy does not allow DM_SEND — a policy without the action must silence the
    lane, not bypass it.
    """
    if ManagementActionKind.DM_SEND not in policy.allowed_actions:
        raise PolicyDenied(
            "the bound management policy does not allow DM_SEND; the DM lane stays silent",
            allowed_actions=sorted(a.value for a in policy.allowed_actions),
        )
    return DmDeliveryService(
        db,
        clock,
        ids,
        community,
        catalog,
        entitlements,
        budget,
        policy,
        provider_id=getattr(community, "provider_id", None),
        blocked_recipient_refs=blocked_recipient_refs,
    )
