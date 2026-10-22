"""TikTok publisher adapter lane (T022): documented platform rules + offline transport.

An ELIGIBLE route means direct-post via an audited app/provider holding the
``video.publish`` grant. This packet ships the platform rules (``adapter``), the frozen
capability research snapshot (``capabilities``) and a transport abstraction with ONE
offline implementation (``transport``). Live publishing stays disabled until T032: the
live transport is a refusing stub and the default capability records are disabled.

Factories:
- ``fixture_tiktok_adapter`` — OFFLINE_MOCK only (guarded by ``ensure_mock_mode``):
  fixture transport + enabled FAKE_FIXTURE capability so the service runs e2e offline.
- ``documented_tiktok_adapter`` — documentation-only, disabled records, refusing
  transport: the honest state of this route until controlled account tests (T032).
- ``build_tiktok_adapter`` — dispatch on ``Settings.execution_mode``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from microdrama.config import Settings
from microdrama.contracts.enums import CapabilityOperation, CapabilitySupport
from microdrama.publishing.tiktok.adapter import (
    DurationProbe,
    FixtureDurationProbe,
    TikTokPublisherAdapter,
)
from microdrama.publishing.tiktok.capabilities import (
    DIRECT_POST_DOCUMENTED_OPERATIONS,
    DOCUMENTED_MAX_DURATION_MS,
    DOCUMENTED_MIN_DURATION_MS,
    INBOX_DOCUMENTED_OPERATIONS,
    ROUTE_IDENTIFIERS,
    TikTokRoute,
    build_capability_record,
    capability_id_for,
)
from microdrama.publishing.tiktok.transport import (
    DEFAULT_ACCOUNT_SETTINGS,
    FIXTURE_CHUNK_SIZE_BYTES,
    RETRY_AFTER_MS,
    DirectPostInitRequest,
    DirectPostInitResult,
    FixtureTikTokTransport,
    LiveTikTokTransport,
    TikTokAccountSettings,
    TikTokPublishPhase,
    TikTokPublishStatus,
    TikTokScenario,
    TikTokTimeoutError,
    TikTokTransport,
    TikTokTransportError,
    fixture_publish_id,
)
from microdrama.testing.fakes.common import FakeClock, SequentialIds, ensure_mock_mode


def fixture_tiktok_adapter(
    settings: Settings,
    *,
    clock: FakeClock,
    ids: SequentialIds,
    route: TikTokRoute = TikTokRoute.DIRECT_POST,
    scenarios: tuple[TikTokScenario, ...] = (),
    account_settings: Mapping[str, TikTokAccountSettings] | None = None,
    operations_override: Mapping[CapabilityOperation, CapabilitySupport] | None = None,
    duration_probe: DurationProbe | None = None,
    enabled: bool = True,
    version: int = 1,
) -> TikTokPublisherAdapter:
    """The OFFLINE_MOCK adapter: fixture transport, enabled FAKE_FIXTURE capability."""
    ensure_mock_mode(settings)
    transport = FixtureTikTokTransport(
        clock=clock, ids=ids, scenarios=scenarios, account_settings=account_settings
    )
    return TikTokPublisherAdapter(
        transport=transport,
        route=route,
        duration_probe=duration_probe or FixtureDurationProbe(),
        operations_override=operations_override,
        enabled=enabled,
        fixture=True,
        version=version,
        clock=clock,
    )


def documented_tiktok_adapter(
    *, route: TikTokRoute = TikTokRoute.DIRECT_POST
) -> TikTokPublisherAdapter:
    """Documentation-only adapter: disabled records, refusing live transport (until T032)."""
    return TikTokPublisherAdapter(
        transport=LiveTikTokTransport(),
        route=route,
        enabled=False,
        fixture=False,
    )


def build_tiktok_adapter(
    settings: Settings,
    *,
    clock: FakeClock | None = None,
    ids: SequentialIds | None = None,
    route: TikTokRoute = TikTokRoute.DIRECT_POST,
    scenarios: tuple[TikTokScenario, ...] = (),
    account_settings: Mapping[str, TikTokAccountSettings]
    | Callable[[str], TikTokAccountSettings | None]
    | None = None,
    operations_override: Mapping[CapabilityOperation, CapabilitySupport] | None = None,
    duration_probe: DurationProbe | None = None,
) -> TikTokPublisherAdapter:
    """Dispatch on the execution mode: fixture adapter in OFFLINE_MOCK, refusing otherwise."""
    if settings.is_offline_mock:
        if clock is None or ids is None:
            raise ValueError("the fixture adapter needs a clock and an id generator")
        mapping: Mapping[str, TikTokAccountSettings] | None = None
        if account_settings is not None and not callable(account_settings):
            mapping = account_settings
        return fixture_tiktok_adapter(
            settings,
            clock=clock,
            ids=ids,
            route=route,
            scenarios=scenarios,
            account_settings=mapping,
            operations_override=operations_override,
            duration_probe=duration_probe,
        )
    return documented_tiktok_adapter(route=route)


__all__ = [
    "DEFAULT_ACCOUNT_SETTINGS",
    "DIRECT_POST_DOCUMENTED_OPERATIONS",
    "DOCUMENTED_MAX_DURATION_MS",
    "DOCUMENTED_MIN_DURATION_MS",
    "DirectPostInitRequest",
    "DirectPostInitResult",
    "FIXTURE_CHUNK_SIZE_BYTES",
    "FixtureDurationProbe",
    "FixtureTikTokTransport",
    "INBOX_DOCUMENTED_OPERATIONS",
    "LiveTikTokTransport",
    "RETRY_AFTER_MS",
    "ROUTE_IDENTIFIERS",
    "TikTokAccountSettings",
    "TikTokPublishPhase",
    "TikTokPublishStatus",
    "TikTokPublisherAdapter",
    "TikTokRoute",
    "TikTokScenario",
    "TikTokTimeoutError",
    "TikTokTransport",
    "TikTokTransportError",
    "build_capability_record",
    "build_tiktok_adapter",
    "capability_id_for",
    "documented_tiktok_adapter",
    "fixture_publish_id",
    "fixture_tiktok_adapter",
]
