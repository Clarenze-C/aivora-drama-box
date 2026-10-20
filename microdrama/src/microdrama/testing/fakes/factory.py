"""One fake of every external boundary, built only in OFFLINE_MOCK (T007).

``build_fake_providers`` calls ``ensure_mock_mode`` first, so a non-offline ``Settings`` raises
``EffectDenied`` before any fake exists. Fakes share one ``FakeClock`` and one ``SequentialIds``;
replaying the same calls in the same order therefore yields the same ids, receipts and outputs.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from microdrama.config import Settings
from microdrama.contracts.enums import MembershipProviderKind, Platform
from microdrama.testing.fakes.comfy import FakeComfyClient, FakeComfyServerState
from microdrama.testing.fakes.common import FakeClock, SequentialIds, ensure_mock_mode
from microdrama.testing.fakes.community import FakeCommunityProvider
from microdrama.testing.fakes.generation import FakeGenerationProvider
from microdrama.testing.fakes.infra import InMemoryQueueTransport, InMemoryRateLimiter
from microdrama.testing.fakes.llm import FakeLLMProvider
from microdrama.testing.fakes.media_review import FakeASRProvider, FakeMediaReviewProvider
from microdrama.testing.fakes.membership import FakeMembershipProvider
from microdrama.testing.fakes.pods import FakePodProvider
from microdrama.testing.fakes.publishing import FakePublisherAdapter
from microdrama.testing.fakes.sources import FakeSourceProvider
from microdrama.testing.media import FixtureTruthRegistry

MEMBERSHIP_KINDS = tuple(MembershipProviderKind)


@dataclass(frozen=True)
class FakeProviders:
    clock: FakeClock
    ids: SequentialIds
    truth: FixtureTruthRegistry
    sources: FakeSourceProvider
    llm: FakeLLMProvider
    generation: FakeGenerationProvider
    pods: FakePodProvider
    comfy_state: FakeComfyServerState
    comfy: FakeComfyClient
    asr: FakeASRProvider
    media_review: FakeMediaReviewProvider
    publishers: Mapping[Platform, FakePublisherAdapter]
    community: Mapping[Platform, FakeCommunityProvider]
    memberships: Mapping[MembershipProviderKind, FakeMembershipProvider]
    queue: InMemoryQueueTransport
    rate_limiter: InMemoryRateLimiter


def build_fake_providers(
    settings: Settings,
    clock: FakeClock,
    ids: SequentialIds,
    *,
    truth: FixtureTruthRegistry | None = None,
    unreleased_claim_phrases: tuple[str, ...] = (),
) -> FakeProviders:
    """Build every fake. Raises ``EffectDenied`` unless ``settings`` is OFFLINE_MOCK."""
    ensure_mock_mode(settings)
    registry = truth if truth is not None else FixtureTruthRegistry()
    comfy_state = FakeComfyServerState(clock)
    return FakeProviders(
        clock=clock,
        ids=ids,
        truth=registry,
        sources=FakeSourceProvider(clock=clock, ids=ids),
        llm=FakeLLMProvider(clock=clock, ids=ids),
        generation=FakeGenerationProvider(clock=clock, ids=ids),
        pods=FakePodProvider(clock=clock, ids=ids),
        comfy_state=comfy_state,
        comfy=FakeComfyClient(comfy_state),
        asr=FakeASRProvider(clock=clock, ids=ids, truth=registry),
        media_review=FakeMediaReviewProvider(
            clock=clock,
            ids=ids,
            truth=registry,
            unreleased_claim_phrases=unreleased_claim_phrases,
        ),
        publishers={p: FakePublisherAdapter(p, clock=clock, ids=ids) for p in Platform},
        community={p: FakeCommunityProvider(p, clock=clock, ids=ids) for p in Platform},
        memberships={k: FakeMembershipProvider(k, clock=clock, ids=ids) for k in MEMBERSHIP_KINDS},
        queue=InMemoryQueueTransport(),
        rate_limiter=InMemoryRateLimiter(clock),
    )


__all__ = ["FakeProviders", "MEMBERSHIP_KINDS", "build_fake_providers"]
