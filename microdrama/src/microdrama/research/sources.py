"""Bounded source adapters and the config-driven provider registry (T009).

Every adapter is a thin wrapper over the frozen ``SourceProvider`` protocol (contracts/
providers.py). This module never performs HTTP: a live source adapter is intentionally a
stub that stays disabled until credentials are configured AND a real implementation exists
(T031+). A disabled or unknown provider is a typed UNKNOWN outcome in the run, never a
silent drop and never a crash.

Registry rules (T006 patterns):
- Providers whose id starts with ``fake-`` are the T007 fakes: enabled only while the process
  runs in OFFLINE_MOCK. Outside mock mode they are disabled (synthetic data must not feed a
  paid/live pipeline).
- Any other provider id is treated as live: it needs configured credential references and a
  non-mock execution mode with paid requests enabled. No live implementation exists in this
  lane, so live records are always disabled with an explicit reason.
"""

from __future__ import annotations

from dataclasses import dataclass

from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode
from microdrama.contracts.providers import SourceProvider

_FAKE_PREFIX = "fake-"
_LIVE_DISABLED_REASON = (
    "live source adapter not implemented in this lane; configure credentials and implement the "
    "adapter in T031+ before enabling"
)
_FAKE_OUTSIDE_MOCK_REASON = "fake providers are disabled outside OFFLINE_MOCK"


@dataclass(frozen=True)
class SourceAdapterRecord:
    """One registered source provider and whether the run may dispatch to it."""

    provider_id: str
    provider: SourceProvider
    enabled: bool
    credential_refs: tuple[str, ...] = ()
    disabled_reason: str | None = None


def _record_for(settings: Settings, provider: SourceProvider) -> SourceAdapterRecord:
    provider_id = provider.provider_id
    if provider_id.startswith(_FAKE_PREFIX):
        if settings.execution_mode is ExecutionMode.OFFLINE_MOCK:
            return SourceAdapterRecord(provider_id=provider_id, provider=provider, enabled=True)
        return SourceAdapterRecord(
            provider_id=provider_id,
            provider=provider,
            enabled=False,
            disabled_reason=_FAKE_OUTSIDE_MOCK_REASON,
        )
    # A live provider: registry/config-driven, disabled without configured credentials. No
    # real HTTP exists here by design (see the module docstring).
    return SourceAdapterRecord(
        provider_id=provider_id,
        provider=provider,
        enabled=False,
        disabled_reason=_LIVE_DISABLED_REASON,
    )


def build_source_registry(
    settings: Settings, providers: dict[str, SourceProvider]
) -> dict[str, SourceAdapterRecord]:
    """Register source providers with their enabled/disabled state for these settings."""
    registry: dict[str, SourceAdapterRecord] = {}
    for provider_id, provider in providers.items():
        if provider.provider_id != provider_id:
            raise ValueError(
                f"provider registry key {provider_id!r} does not match provider id "
                f"{provider.provider_id!r}"
            )
        registry[provider_id] = _record_for(settings, provider)
    return registry


__all__ = ["SourceAdapterRecord", "build_source_registry"]
