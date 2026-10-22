"""Patreon membership route (T026): the one selected verified backend, offline only.

The factory builds the OFFLINE_MOCK adapter over the T007 ``FakeMembershipProvider``
fixture transport (HMAC-SHA256 signed webhooks, scripted entitlement scenarios). It
refuses every other execution mode, and no live transport exists at all until T032
(``LivePatreonTransport`` is a named ``PolicyDenied`` refusal).
"""

from __future__ import annotations

from microdrama.config import Settings
from microdrama.contracts.enums import MembershipProviderKind
from microdrama.memberships.patreon.adapter import (
    LIVE_DISABLED_MESSAGE,
    PROVIDER_ID,
    LivePatreonTransport,
    MembershipTransport,
    PatreonMembershipAdapter,
)
from microdrama.memberships.patreon.capabilities import (
    BMC_ALTERNATE_NOTE,
    RESEARCH_EVIDENCE,
    RESEARCH_OPERATIONS,
    MembershipRouteSnapshot,
    fixture_snapshot,
    research_snapshot,
)
from microdrama.testing.fakes.common import FakeClock, SequentialIds, ensure_mock_mode
from microdrama.testing.fakes.membership import EntitlementScenario, FakeMembershipProvider

__all__ = [
    "BMC_ALTERNATE_NOTE",
    "EntitlementScenario",
    "LIVE_DISABLED_MESSAGE",
    "LivePatreonTransport",
    "MembershipRouteSnapshot",
    "MembershipTransport",
    "PROVIDER_ID",
    "PatreonMembershipAdapter",
    "RESEARCH_EVIDENCE",
    "RESEARCH_OPERATIONS",
    "build_patreon_adapter",
    "fixture_snapshot",
    "research_snapshot",
]


def build_patreon_adapter(
    settings: Settings,
    *,
    clock: FakeClock,
    ids: SequentialIds,
    scenarios: tuple[EntitlementScenario, ...] = (),
) -> tuple[PatreonMembershipAdapter, FakeMembershipProvider]:
    """Build the OFFLINE_MOCK Patreon adapter over the fixture transport.

    Returns the adapter and the underlying fake (for scenario scripting and call
    assertions). Raises ``EffectDenied`` in any other execution mode: fake
    transports exist only offline, and no live transport exists until T032.
    """
    ensure_mock_mode(settings)
    fake = FakeMembershipProvider(
        MembershipProviderKind.PATREON, clock=clock, ids=ids, scenarios=scenarios
    )
    return PatreonMembershipAdapter(fake), fake
