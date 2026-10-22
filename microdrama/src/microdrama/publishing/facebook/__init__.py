"""Facebook Page publishing lane (T024): explicit full-video / short-Reel routes.

The adapter (``adapter.py``) implements the frozen ``PublisherAdapter`` protocol as
documented platform rules over a transport (``transport.py``); the capability truth
lives in ``capabilities.py`` as a frozen OFFICIAL_DOCUMENTATION snapshot. Live
publishing stays disabled until T032 — outside OFFLINE_MOCK every transport call
refuses and the default capability record is ``enabled=False``.
"""

from __future__ import annotations

from microdrama.config import Settings
from microdrama.contracts.enums import CapabilityOperation, CapabilitySupport
from microdrama.publishing.facebook.adapter import FacebookPageAdapter
from microdrama.publishing.facebook.capabilities import (
    FB_PAGE_ACCOUNT,
    facebook_page_capability_record,
)
from microdrama.publishing.facebook.transport import (
    FacebookScenario,
    FacebookTransport,
    FixtureFacebookTransport,
    RefusingFacebookTransport,
)
from microdrama.testing.fakes.common import FakeClock, SequentialIds, ensure_mock_mode

__all__ = [
    "FacebookPageAdapter",
    "FacebookScenario",
    "FacebookTransport",
    "FixtureFacebookTransport",
    "RefusingFacebookTransport",
    "facebook_page_adapter",
    "facebook_page_capability_record",
]


def facebook_page_adapter(
    *,
    clock: FakeClock,
    ids: SequentialIds,
    settings: Settings,
    scenarios: tuple[FacebookScenario, ...] = (),
    operations: dict[CapabilityOperation, CapabilitySupport] | None = None,
    page_accounts: dict[str, str] | None = None,
    version: int = 1,
) -> FacebookPageAdapter:
    """The Facebook Page adapter for the current execution mode.

    - OFFLINE_MOCK (guarded by ``ensure_mock_mode``): the fixture transport plus an
      enabled fixture record (FAKE_FIXTURE evidence, mock Page account
      ``acct:facebook-main``) so the service runs end to end offline. The platform
      rules — routes, schedule truth, disclosure truth — are the SAME snapshot as
      the live record; only the evidence label and enabled flag differ.
    - Any other mode: the refusing live placeholder (no HTTP surface exists in this
      packet) plus the disabled documentation snapshot — ``enabled=False`` until
      T032 supplies CONTROLLED_ACCOUNT_TEST evidence.
    """
    if settings.is_offline_mock:
        ensure_mock_mode(settings)
        transport: FacebookTransport = FixtureFacebookTransport(
            clock=clock, ids=ids, scenarios=scenarios
        )
        return FacebookPageAdapter(
            clock=clock,
            transport=transport,
            operations=operations,
            page_accounts=page_accounts or {FB_PAGE_ACCOUNT: "Facebook Page (fixture)"},
            version=version,
            fixture=True,
        )
    return FacebookPageAdapter(
        clock=clock,
        transport=RefusingFacebookTransport(),
        operations=operations,
        page_accounts=page_accounts or {FB_PAGE_ACCOUNT: "Facebook Page"},
        version=version,
        fixture=False,
    )
