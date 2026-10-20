"""Every fake satisfies the runtime-checkable Protocol it stands in for (contracts/providers, infra)."""

from __future__ import annotations

import inspect
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


# Each Protocol paired with the fake class that stands in for it. isinstance only checks method
# names; the signature test below also checks parameter names, kinds and order.
PROTOCOL_FAKES: tuple[tuple[type, type], ...] = (
    (SourceProvider, FakeSourceProvider),
    (LLMProvider, FakeLLMProvider),
    (GenerationProvider, FakeGenerationProvider),
    (PodProvider, FakePodProvider),
    (ComfyClient, FakeComfyClient),
    (ASRProvider, FakeASRProvider),
    (MediaReviewProvider, FakeMediaReviewProvider),
    (PublisherAdapter, FakePublisherAdapter),
    (CommunityProvider, FakeCommunityProvider),
    (MembershipProvider, FakeMembershipProvider),
    (WebhookVerifier, FakeWebhookVerifier),
    (QueueTransport, InMemoryQueueTransport),
    (RateLimiter, InMemoryRateLimiter),
    (Clock, FakeClock),
    (IdGenerator, SequentialIds),
)


def _protocol_methods(protocol: type) -> list[str]:
    """Public methods the Protocol itself declares (inherited object members excluded)."""
    return sorted(
        name
        for name, value in vars(protocol).items()
        if inspect.isfunction(value) and not name.startswith("_")
    )


def _shape(function: object) -> list[tuple[str, object]]:
    """Parameter names and kinds in declaration order; ``self`` is included on both sides."""
    return [(p.name, p.kind) for p in inspect.signature(function).parameters.values()]  # type: ignore[arg-type]


@pytest.mark.parametrize(("protocol", "fake"), PROTOCOL_FAKES, ids=lambda cls: cls.__name__)
def test_fake_method_signatures_match_the_protocol(protocol: type, fake: type) -> None:
    methods = _protocol_methods(protocol)
    assert methods, f"{protocol.__name__} declares no methods to compare"
    for name in methods:
        assert hasattr(fake, name), f"{fake.__name__} is missing {protocol.__name__}.{name}"
        expected = _shape(getattr(protocol, name))
        actual = _shape(getattr(fake, name))
        assert actual == expected, (
            f"{fake.__name__}.{name} drifted from {protocol.__name__}.{name}: "
            f"{actual} != {expected}"
        )


def test_signature_comparison_detects_parameter_drift() -> None:
    class Renamed:
        def submit(
            self, command: object, media: object
        ) -> None: ...  # `media_path` in the Protocol

    class Reordered:
        def submit(self, media_path: object, command: object) -> None: ...

    class Keyword:
        def submit(self, *, command: object, media_path: object) -> None: ...

    expected = _shape(PublisherAdapter.submit)
    assert _shape(Renamed.submit) != expected
    assert _shape(Reordered.submit) != expected
    assert _shape(Keyword.submit) != expected
