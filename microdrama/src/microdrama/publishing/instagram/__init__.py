"""Instagram publishing lane (T023): an OFFLINE PublisherAdapter over a Transport.

The adapter (``adapter.py``) encodes the documented platform rules — the
professional-account requirement, REELS-vs-feed-VIDEO routing from slot kinds,
documented duration ceilings and caption limits, the container/process/publish
state mapping and the image-only caption-update refusal — over the Transport
surface (``transport.py``). Capability truth (``capabilities.py``) is a frozen
2026-10 documentation snapshot: SUPPORTED_DOCUMENTED at most, never
SUPPORTED_TESTED (that is T032), and the declaration truth that no documented API
field sets or reads back a synthetic-media/AI label, so ``supported_disclosures``
is empty and MD-015 slots hold with UNSUPPORTED_DISCLOSURE through the service.

The factory is the registration entry point for the integrator:

>>> adapter = build_instagram_adapter(settings)

``OFFLINE_MOCK`` returns the fixture variant (enabled record, FAKE_FIXTURE
evidence, mock account ``acct:instagram-main``) so the publishing service runs
end-to-end offline; every other execution mode returns the live-refusing adapter
until T032.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from microdrama.config import Settings
from microdrama.contracts.errors import PolicyDenied
from microdrama.publishing.instagram.adapter import InstagramAdapter
from microdrama.publishing.instagram.capabilities import PROVIDER_ROUTE, RESEARCH_AS_OF
from microdrama.publishing.instagram.transport import (
    DEFAULT_ACCOUNT_REF,
    FixtureInstagramTransport,
    InstagramScenario,
    InstagramTransport,
    RefusingInstagramTransport,
)
from microdrama.testing.fakes.common import FakeClock, SequentialIds, ensure_mock_mode

#: Deterministic start for the factory-built fixture clock (matches the T020 world).
FACTORY_CLOCK_START = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def build_instagram_adapter(
    settings: Settings,
    *,
    transport: InstagramTransport | None = None,
    duration_lookup: Callable[[UUID], int | None] | None = None,
    scenarios: tuple[InstagramScenario, ...] = (),
) -> InstagramAdapter:
    """The Instagram adapter for this process's execution mode.

    OFFLINE_MOCK: the fixture variant, guarded by ``ensure_mock_mode`` — an enabled
    capability record with FAKE_FIXTURE evidence over the deterministic fixture
    transport. Any other mode: the live-refusing adapter (every documented edge
    raises PolicyDenied "live publishing disabled until T032"); a custom transport
    or scenario script cannot be smuggled into a non-mock process.
    """
    if settings.is_offline_mock:
        ensure_mock_mode(settings)
        fixture = (
            transport
            if transport is not None
            else FixtureInstagramTransport(
                clock=FakeClock(FACTORY_CLOCK_START),
                ids=SequentialIds("instagram"),
                scenarios=tuple(scenarios),
            )
        )
        return InstagramAdapter(fixture, duration_lookup=duration_lookup)
    if transport is not None or scenarios:
        raise PolicyDenied(
            "custom transports and scenario scripts are fixture-only; "
            "live publishing is disabled until T032"
        )
    return InstagramAdapter(RefusingInstagramTransport(), duration_lookup=duration_lookup)


__all__ = [
    "DEFAULT_ACCOUNT_REF",
    "FACTORY_CLOCK_START",
    "PROVIDER_ROUTE",
    "RESEARCH_AS_OF",
    "FixtureInstagramTransport",
    "InstagramAdapter",
    "InstagramScenario",
    "InstagramTransport",
    "RefusingInstagramTransport",
    "build_instagram_adapter",
]
