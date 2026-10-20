"""Queue and rate-limiter doubles, and replay reproducibility of scripted scenarios."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from microdrama.config import Settings
from microdrama.contracts.cost import ProviderOperation
from microdrama.contracts.enums import (
    ExecutionMode,
    Platform,
    PodState,
    ProviderOperationState,
    QueueName,
    RuntimeRole,
)
from microdrama.contracts.errors import NotFound, SchemaInvalid
from microdrama.contracts.examples import management_action, publication_command
from microdrama.contracts.hashing import canonical_hash, file_sha256
from microdrama.contracts.providers import ImageRequest, LLMRequest, PodCreateRequest
from microdrama.contracts.release import PublicationCommand
from microdrama.testing.fakes import (
    FakeClock,
    FakeComfyClient,
    FakeProviders,
    GenerationScenario,
    InMemoryQueueTransport,
    InMemoryRateLimiter,
    LLMScenario,
    PublishScenario,
    SequentialIds,
    build_fake_providers,
)
from microdrama.testing.fakes.comfy import EXECUTION_MS
from microdrama.testing.media import FixtureTruthRegistry, seeded_defect_suite

OFFLINE = Settings(execution_mode=ExecutionMode.OFFLINE_MOCK)
T0 = datetime(2026, 10, 20, tzinfo=UTC)


def test_queue_is_at_least_once_and_ack_is_checked() -> None:
    queue = InMemoryQueueTransport()
    first, second = uuid.UUID(int=1), uuid.UUID(int=2)
    queue.enqueue(QueueName.PRODUCTION, first)
    queue.enqueue(QueueName.PRODUCTION, second)
    assert queue.depth(QueueName.PRODUCTION) == 2
    assert queue.dequeue(QueueName.PRODUCTION, timeout_ms=0) == first
    with pytest.raises(NotFound):
        queue.ack(QueueName.PRODUCTION, second)  # never dequeued, so not in flight
    queue.ack(QueueName.PRODUCTION, first)
    assert queue.dequeue(QueueName.PRODUCTION, timeout_ms=0) == second
    # Consumer crashes before acking: the job comes back, so consumers must be idempotent.
    assert queue.redeliver_unacked() == [second]
    assert queue.dequeue(QueueName.PRODUCTION, timeout_ms=0) == second
    assert queue.dequeue(QueueName.PRODUCTION, timeout_ms=0) is None
    assert queue.dequeue(QueueName.COMMUNITY, timeout_ms=0) is None


def test_queues_are_isolated_by_name() -> None:
    queue = InMemoryQueueTransport()
    queue.enqueue(QueueName.PUBLICATION, uuid.UUID(int=3))
    assert queue.depth(QueueName.PRODUCTION) == 0
    assert queue.depth(QueueName.PUBLICATION) == 1


def test_rate_limiter_is_a_clock_driven_token_bucket(clock: FakeClock) -> None:
    limiter = InMemoryRateLimiter(clock)
    limiter.set_limit("tiktok:acct", capacity=2, refill_per_second=1)
    assert limiter.try_acquire("tiktok:acct").allowed is True
    assert limiter.try_acquire("tiktok:acct").allowed is True
    denied = limiter.try_acquire("tiktok:acct")
    assert denied.allowed is False
    assert denied.retry_after_ms == 1_000
    clock.advance(ms=1_000)
    assert limiter.try_acquire("tiktok:acct").allowed is True


def test_rate_limiter_keys_are_independent_and_cost_is_checked(clock: FakeClock) -> None:
    limiter = InMemoryRateLimiter(clock, default_capacity=1, default_refill_per_second=1)
    assert limiter.try_acquire("a").allowed is True
    assert limiter.try_acquire("b").allowed is True
    assert limiter.try_acquire("a").allowed is False
    with pytest.raises(SchemaInvalid):
        limiter.try_acquire("a", cost=0)


def _image(token: str) -> ImageRequest:
    return ImageRequest(
        request_id=uuid.UUID(int=101),
        model_config_ref="fake-image-profile",
        rights_route_id="rights-fixture",
        prompt_text="Fixture still of a market stall.",
        width=512,
        height=512,
        seed=7,
        client_token=token,
        reservation_id=uuid.UUID(int=102),
    )


def _run(
    scenario_steps: tuple[object, ...], suite: dict, registry: FixtureTruthRegistry
) -> dict[str, str]:
    clock = FakeClock(T0)
    providers: FakeProviders = build_fake_providers(
        OFFLINE, clock, SequentialIds("replay"), truth=registry
    )
    providers.generation.queue_scenarios(
        *[s for s in scenario_steps if isinstance(s, GenerationScenario)]
    )
    providers.llm.queue_scenarios(*[s for s in scenario_steps if isinstance(s, LLMScenario)])
    out: dict[str, str] = {}

    request = _image("replay-image")
    op = ProviderOperation(
        operation_id=uuid.UUID(int=201),
        provider="fake-generation",
        operation_kind="generation.image",
        client_token=request.client_token,
        request_sha256=canonical_hash(request),
        state=ProviderOperationState.PENDING_SUBMIT,
        deadline_at=T0 + timedelta(hours=1),
    )
    submitted = providers.generation.submit(op, request)
    status = providers.generation.status(op)
    done = providers.generation.status(op)
    out["generation"] = canonical_hash([submitted, status, done])
    out["bytes"] = hashlib.sha256(providers.generation.fetch_output(done.outputs[0])).hexdigest()

    llm_request = LLMRequest(
        request_id=uuid.UUID(int=301),
        role=RuntimeRole.RESEARCHER,
        model_config_ref="fake-research-profile",
        instruction="Return the fixture budget as JSON.",
        output_schema={
            "type": "object",
            "required": ["budget_micro_usd"],
            "properties": {"budget_micro_usd": {"type": "integer"}},
        },  # fmt: skip
        max_input_tokens=2_000,
        max_output_tokens=200,
        client_token="replay-llm",
    )
    try:
        out["llm"] = canonical_hash(providers.llm.generate(llm_request))
    except Exception as exc:  # the scripted failure is part of the replayed behaviour
        out["llm"] = f"raised:{type(exc).__name__}"

    pod_request = PodCreateRequest(
        client_token="replay-pod",
        name="replay",
        owned_tag="microdrama-owned:replay",
        gpu_type_allowlist=["FAKE-GPU-24GB"],
        max_hourly_price_micro_usd=900_000,
        min_host_ram_gb=16,
        container_image="registry.fake.invalid/render@sha256:" + "b" * 64,
    )
    pod = providers.pods.create_pod(pod_request)
    clock.advance(seconds=90)
    out["pod"] = canonical_hash(providers.pods.usage(pod.pod_id, since=T0, until=clock.now()))

    client = FakeComfyClient(providers.comfy_state)
    graph = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "fake.safetensors"}},
             "2": {"class_type": "FakeVideoModelSampler", "inputs": {"model": ["1", 0], "prompt": "p", "frames": 8}},  # fmt: skip
             "3": {"class_type": "VHS_VideoCombine", "inputs": {"images": ["2", 0], "frame_rate": 24, "filename_prefix": "replay", "format": "video/h264-mp4"}}}  # fmt: skip
    prompt_id = client.queue_prompt(graph, client_id="replay")
    clock.advance(ms=EXECUTION_MS)
    out["comfy"] = canonical_hash(client.history(prompt_id))

    media = suite["clean"]
    base = publication_command().model_dump(mode="python")
    base.update(asset_sha256=media.sha256, client_token="replay-publish")
    publish = PublicationCommand(**base)
    adapter = providers.publishers[Platform.YOUTUBE]
    adapter.queue_scenarios(PublishScenario.ACCEPTED)
    submitted_post = adapter.submit(publish, media.path)
    adapter.status(publish, submitted_post.external_id)  # type: ignore[arg-type]
    out["publish"] = canonical_hash(adapter.status(publish, submitted_post.external_id))  # type: ignore[arg-type]

    event = providers.community[Platform.TIKTOK].execute(management_action())
    out["community"] = canonical_hash(event)
    out["ledger"] = canonical_hash(
        [providers.generation.ledger, providers.llm.ledger, providers.pods.ledger]
    )
    out["truth_sha"] = file_sha256(str(media.path))
    return out


@pytest.fixture(scope="module")
def replay_suite(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict, FixtureTruthRegistry]:
    registry = FixtureTruthRegistry()
    suite = seeded_defect_suite(tmp_path_factory.mktemp("replay-suite"), registry)
    return suite, registry


def test_same_scripted_scenario_replays_identically(replay_suite) -> None:
    suite, registry = replay_suite
    steps = (GenerationScenario.LATE_BILLING, LLMScenario.HAPPY)
    assert _run(steps, suite, registry) == _run(steps, suite, registry)


def test_a_different_script_produces_different_recorded_behaviour(replay_suite) -> None:
    suite, registry = replay_suite
    happy = _run((), suite, registry)
    partial = _run((GenerationScenario.PARTIAL_OUTPUT,), suite, registry)
    assert happy["generation"] != partial["generation"]
    assert happy["bytes"] != partial["bytes"]
    assert happy["truth_sha"] == partial["truth_sha"]  # the fixture file itself did not change


def test_pod_state_is_observable_for_janitor_replays(clock: FakeClock, ids: SequentialIds) -> None:
    providers = build_fake_providers(OFFLINE, clock, ids, truth=FixtureTruthRegistry())
    assert {p.state for p in providers.pods.find_pods()} == {PodState.RUNNING}


def test_fake_call_paths_open_no_sockets(replay_suite) -> None:
    """Strict offline mode: the whole scripted run completes with every non-loopback socket refused."""
    from microdrama.testing.network_guard import block_network

    suite, registry = replay_suite
    with block_network(allow_loopback=False):
        out = _run((GenerationScenario.HAPPY, LLMScenario.HAPPY), suite, registry)
    assert set(out) >= {"generation", "bytes", "llm", "pod", "comfy", "publish", "community"}
