"""Early-access catalog, entitlement/provider adapters and permitted DM delivery (T026).

Lane composition root (offline only). The exported factories wire the REAL
services over the frozen contracts/tables and the T007 fakes; nothing here
registers routes or jobs — integration belongs to the orchestrator.

- ``build_membership_services`` — the selected Patreon route (the fake transport
  behind the common ``MembershipProvider`` interface), the truthful catalog
  service, the entitlement/webhook service, and the permitted DM delivery service
  beneath ``community/dm``.
- Buy Me a Coffee stays the documented optional alternate (SPEC §10); it is NOT
  built here. Live membership is a named refusal until T032.
"""

from __future__ import annotations

from pathlib import Path

from microdrama.budget.service import BudgetService
from microdrama.config import Settings
from microdrama.memberships.catalog import (
    CatalogFacts,
    FreeDateOwnerDecision,
    MembershipCatalogService,
    member_ref_hash,
    price_text,
)
from microdrama.memberships.entitlements import (
    EntitlementDecision,
    EntitlementService,
    WebhookOutcome,
)
from microdrama.memberships.patreon import (
    BMC_ALTERNATE_NOTE,
    LIVE_DISABLED_MESSAGE,
    PROVIDER_ID,
    RESEARCH_EVIDENCE,
    RESEARCH_OPERATIONS,
    LivePatreonTransport,
    MembershipRouteSnapshot,
    PatreonMembershipAdapter,
    build_patreon_adapter,
    fixture_snapshot,
    research_snapshot,
)
from microdrama.persistence import Database
from microdrama.testing.fakes.common import FakeClock, SequentialIds
from microdrama.testing.fakes.membership import EntitlementScenario, FakeMembershipProvider

__all__ = [
    "BMC_ALTERNATE_NOTE",
    "CatalogFacts",
    "EntitlementDecision",
    "EntitlementScenario",
    "EntitlementService",
    "FakeMembershipProvider",
    "FreeDateOwnerDecision",
    "LIVE_DISABLED_MESSAGE",
    "LivePatreonTransport",
    "MembershipCatalogService",
    "MembershipRouteSnapshot",
    "PROVIDER_ID",
    "PatreonMembershipAdapter",
    "RESEARCH_EVIDENCE",
    "RESEARCH_OPERATIONS",
    "WebhookOutcome",
    "build_membership_services",
    "build_patreon_adapter",
    "fixture_snapshot",
    "member_ref_hash",
    "price_text",
    "research_snapshot",
]


class MembershipServices:
    """The wired T026 services (offline fixture route only)."""

    def __init__(
        self,
        *,
        adapter: PatreonMembershipAdapter,
        fake_provider: FakeMembershipProvider,
        catalog: MembershipCatalogService,
        entitlements: EntitlementService,
    ) -> None:
        self.adapter = adapter
        self.fake_provider = fake_provider
        self.catalog = catalog
        self.entitlements = entitlements


def build_membership_services(
    settings: Settings,
    *,
    db: Database,
    clock: FakeClock,
    ids: SequentialIds,
    budget: BudgetService,
    scenarios: tuple[EntitlementScenario, ...] = (),
) -> MembershipServices:
    """Build the offline membership stack (catalog + entitlements over Patreon).

    The DM delivery service is built by ``microdrama.community.dm`` (it owns the
    community seam); this factory provides everything the membership side needs.
    Raises ``EffectDenied`` outside OFFLINE_MOCK.
    """
    adapter, fake_provider = build_patreon_adapter(
        settings, clock=clock, ids=ids, scenarios=scenarios
    )
    catalog = MembershipCatalogService(db, clock, ids)
    entitlements = EntitlementService(db, clock, ids, adapter, catalog, budget)
    return MembershipServices(
        adapter=adapter,
        fake_provider=fake_provider,
        catalog=catalog,
        entitlements=entitlements,
    )


def member_media_file(tmp: Path, episode_number: int) -> Path:
    """A small synthetic media file the fixture provider accepts (labelled fake)."""
    path = tmp / f"member-episode-{episode_number}.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"fake-member-media-" * 32)
    return path
