"""Every fake satisfies the runtime-checkable Protocol it stands in for (contracts/providers, infra)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from microdrama.contracts.enums import MembershipProviderKind, Platform
from microdrama.contracts.infra import Clock, IdGenerator, QueueTransport, RateLimiter
from microdrama.contracts.providers import (
    ASRProvider,
    ComfyClient,
    CommunityProvider,
    GenerationProvider,
    LLMProvider,
    MediaReviewProvider,
    MembershipProvider,
    PodProvider,
    PublisherAdapter,
    SourceProvider,
    WebhookVerifier,
)
from microdrama.testing.fakes import (
    FakeASRProvider,
    FakeClock,
    FakeComfyClient,
    FakeComfyServerState,
    FakeCommunityProvider,
    FakeGenerationProvider,
    FakeLLMProvider,
    FakeMediaReviewProvider,
    FakeMembershipProvider,
    FakePodProvider,
    FakePublisherAdapter,
    FakeSourceProvider,
    FakeWebhookVerifier,
    InMemoryQueueTransport,
    InMemoryRateLimiter,
    SequentialIds,
)
from microdrama.testing.media import FixtureTruthRegistry

T0 = datetime(2026, 10, 20, tzinfo=UTC)


@pytest.fixture
def parts() -> dict[str, object]:
    clock = FakeClock(T0)
    ids = SequentialIds("protocols")
    registry = FixtureTruthRegistry()
    state = FakeComfyServerState(clock)
    return {
        "clock": clock,
        "ids": ids,
        "source": FakeSourceProvider(clock=clock, ids=ids),
        "llm": FakeLLMProvider(clock=clock, ids=ids),
        "generation": FakeGenerationProvider(clock=clock, ids=ids),
        "pods": FakePodProvider(clock=clock, ids=ids),
        "comfy": FakeComfyClient(state),
        "asr": FakeASRProvider(clock=clock, ids=ids, truth=registry),
        "review": FakeMediaReviewProvider(clock=clock, ids=ids, truth=registry),
        "publisher": FakePublisherAdapter(Platform.YOUTUBE, clock=clock, ids=ids),
        "community": FakeCommunityProvider(Platform.TIKTOK, clock=clock, ids=ids),
        "membership": FakeMembershipProvider(MembershipProviderKind.PATREON, clock=clock, ids=ids),
        "verifier": FakeWebhookVerifier("fake-patreon"),
        "queue": InMemoryQueueTransport(),
        "limiter": InMemoryRateLimiter(clock),
    }


@pytest.mark.parametrize(
    ("name", "protocol"),
    [
        ("source", SourceProvider),
        ("llm", LLMProvider),
        ("generation", GenerationProvider),
        ("pods", PodProvider),
        ("comfy", ComfyClient),
        ("asr", ASRProvider),
        ("review", MediaReviewProvider),
        ("publisher", PublisherAdapter),
        ("community", CommunityProvider),
        ("membership", MembershipProvider),
        ("verifier", WebhookVerifier),
        ("queue", QueueTransport),
        ("limiter", RateLimiter),
        ("clock", Clock),
        ("ids", IdGenerator),
    ],
)
def test_fake_satisfies_its_protocol(parts: dict[str, object], name: str, protocol: type) -> None:
    assert isinstance(parts[name], protocol), f"{name} does not satisfy {protocol.__name__}"
