"""Deterministic fake providers for offline tests (T007). Test-only; never imported by runtime code.

Every fake is labelled FAKE_SYNTHETIC / SYNTHETIC_FAKE and only emits ``*.invalid`` URLs. Build them with
``build_fake_providers(settings, clock, ids)`` so the OFFLINE_MOCK gate applies.
"""

from microdrama.testing.fakes.comfy import (
    FAKE_NODE_CLASSES,
    ComfyScenario,
    FakeComfyClient,
    FakeComfyServerState,
    validate_api_graph,
)
from microdrama.testing.fakes.common import (
    FAKE_PRICE_TABLE,
    FAKE_PRICE_TABLE_VERSION,
    FakeBase,
    FakeClock,
    SequentialIds,
    ensure_mock_mode,
    fake_https,
    fake_price_quote,
    synthetic_receipt,
)
from microdrama.testing.fakes.community import CommunityScenario, FakeCommunityProvider
from microdrama.testing.fakes.factory import FakeProviders, build_fake_providers
from microdrama.testing.fakes.generation import (
    FakeGenerationProvider,
    GenerationScenario,
    voice_duration_ms,
)
from microdrama.testing.fakes.infra import InMemoryQueueTransport, InMemoryRateLimiter
from microdrama.testing.fakes.llm import FakeLLMProvider, LLMScenario
from microdrama.testing.fakes.media_review import (
    FakeASRProvider,
    FakeMediaReviewProvider,
    ReviewScenario,
)
from microdrama.testing.fakes.membership import (
    FAKE_WEBHOOK_SECRET,
    EntitlementScenario,
    FakeMembershipProvider,
    FakeWebhookVerifier,
    fake_signature,
)
from microdrama.testing.fakes.pods import (
    FakePodProvider,
    ForeignPodSeed,
    PodCreateScenario,
    PodStopScenario,
)
from microdrama.testing.fakes.publishing import FakePublisherAdapter, PublishScenario
from microdrama.testing.fakes.sources import FakeSourceProvider, SourceScenario

__all__ = [
    "FAKE_NODE_CLASSES",
    "FAKE_PRICE_TABLE",
    "FAKE_PRICE_TABLE_VERSION",
    "FAKE_WEBHOOK_SECRET",
    "CommunityScenario",
    "ComfyScenario",
    "EntitlementScenario",
    "FakeASRProvider",
    "FakeBase",
    "FakeClock",
    "FakeComfyClient",
    "FakeComfyServerState",
    "FakeCommunityProvider",
    "FakeGenerationProvider",
    "FakeLLMProvider",
    "FakeMediaReviewProvider",
    "FakeMembershipProvider",
    "FakePodProvider",
    "FakeProviders",
    "FakePublisherAdapter",
    "FakeSourceProvider",
    "FakeWebhookVerifier",
    "ForeignPodSeed",
    "GenerationScenario",
    "InMemoryQueueTransport",
    "InMemoryRateLimiter",
    "LLMScenario",
    "PodCreateScenario",
    "PodStopScenario",
    "PublishScenario",
    "ReviewScenario",
    "SequentialIds",
    "SourceScenario",
    "build_fake_providers",
    "ensure_mock_mode",
    "fake_https",
    "fake_price_quote",
    "fake_signature",
    "synthetic_receipt",
    "validate_api_graph",
    "voice_duration_ms",
]
