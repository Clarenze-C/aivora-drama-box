"""YouTube publisher adapter (T021): platform rules + documented transport surface.

OFFLINE_MOCK only. The factory refuses every other execution mode, and the live
transport is a named ``PolicyDenied`` refusal until the controlled account tests
of T032 qualify one — the shipped research snapshot is documentation-sourced and
``enabled=False``. The capability snapshot itself lives in ``capabilities``
(support values, documented limits, disclosure mapping); ``transport`` holds the
documented Data API v3 surface and its deterministic fixture; ``adapter`` applies
the platform rules to implement the frozen ``PublisherAdapter`` protocol.
"""

from __future__ import annotations

from microdrama.config import Settings
from microdrama.publishing.youtube.adapter import YouTubeAdapter
from microdrama.publishing.youtube.capabilities import (
    PROVIDER_ROUTE,
    RESEARCH_OPERATIONS,
    fixture_capability_record,
    research_capability_record,
)
from microdrama.publishing.youtube.transport import (
    CaptionUploadRequest,
    FixtureYouTubeTransport,
    LiveYouTubeTransport,
    YouTubeScenario,
    YouTubeTransport,
    youtube_external_id,
)
from microdrama.testing.fakes.common import FakeClock, SequentialIds, ensure_mock_mode

#: Mock channel for the offline world; matches ``contracts.examples.ACCOUNT_YT``.
DEFAULT_ACCOUNT = "acct:youtube-main"


def build_youtube_adapter(
    settings: Settings,
    *,
    clock: FakeClock,
    ids: SequentialIds,
    scenarios: tuple[YouTubeScenario, ...] = (),
    version: int = 1,
    enabled: bool = True,
    operations: dict | None = None,
) -> YouTubeAdapter:
    """Build the OFFLINE_MOCK adapter over the fixture transport.

    Raises ``EffectDenied`` in any other execution mode: fake transports exist
    only offline (the ``ensure_mock_mode`` guard), and no live transport exists
    at all until T032.
    """
    ensure_mock_mode(settings)
    transport = FixtureYouTubeTransport(clock=clock, ids=ids, scenarios=scenarios)
    return YouTubeAdapter(
        transport=transport, clock=clock, version=version, enabled=enabled, operations=operations
    )


__all__ = [
    "DEFAULT_ACCOUNT",
    "PROVIDER_ROUTE",
    "CaptionUploadRequest",
    "FixtureYouTubeTransport",
    "LiveYouTubeTransport",
    "RESEARCH_OPERATIONS",
    "YouTubeAdapter",
    "YouTubeScenario",
    "YouTubeTransport",
    "build_youtube_adapter",
    "fixture_capability_record",
    "research_capability_record",
    "youtube_external_id",
]
