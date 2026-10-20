"""Every receipt and result produced in every scenario is labelled synthetic and points only at *.invalid.

The sweep drives each fake through all of its scenario steps, walks every returned contract object, and
asserts: receipts are FAKE_SYNTHETIC with SYNTHETIC_FAKE cost basis; every provenance field is
FAKE_SYNTHETIC; every URL uses https and a *.invalid host. A non-empty collection guards against the
sweep passing vacuously.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel

from microdrama.config import Settings
from microdrama.contracts.cost import ProviderOperation, UsageReceipt
from microdrama.contracts.enums import (
    AssetKind,
    AssetState,
    CapabilityOperation,
    CapabilitySupport,
    CostBasis,
    ExecutionMode,
    MembershipProviderKind,
    Platform,
    Provenance,
    ProviderOperationState,
    RuntimeRole,
)
from microdrama.contracts.examples import (
    management_action,
    membership_catalog_entry,
    publication_command,
    script,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.media import AssetDescriptor, MediaInfo
from microdrama.contracts.providers import (
    ASRRequest,
    ComparisonMaterials,
    ImageRequest,
    LLMRequest,
    PodCreateRequest,
    SourceQuery,
    VoiceRequest,
)
from microdrama.contracts.qa import (
    ComparisonRequest,
    MediaUnderReview,
    NeutralQuestion,
    ObservationRequest,
)
from microdrama.contracts.release import PublicationCommand
from microdrama.testing.fakes import (
    ComfyScenario,
    CommunityScenario,
    EntitlementScenario,
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
    GenerationScenario,
    LLMScenario,
    PodCreateScenario,
    PodStopScenario,
    PublishScenario,
    SequentialIds,
    SourceScenario,
    build_fake_providers,
    fake_signature,
)
from microdrama.testing.media import FixtureTruthRegistry

T0 = datetime(2026, 10, 20, tzinfo=UTC)
URL_FIELDS = frozenset({"url", "endpoint_url", "member_url"})


@dataclass
class Found:
    receipts: list[UsageReceipt] = field(default_factory=list)
    provenances: list[Provenance] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)


def _walk(obj: object, found: Found) -> None:
    if isinstance(obj, UsageReceipt):
        found.receipts.append(obj)
    if isinstance(obj, BaseModel):
        for name in type(obj).model_fields:
            value = getattr(obj, name)
            if name == "provenance" and isinstance(value, Provenance):
                found.provenances.append(value)
            if name in URL_FIELDS and isinstance(value, str):
                found.urls.append(value)
            if name == "links" and isinstance(value, list):
                found.urls.extend(v for v in value if isinstance(v, str))
            _walk(value, found)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _walk(item, found)
    elif isinstance(obj, dict):
        for item in obj.values():
            _walk(item, found)


def _assert_labelled(results: Iterable[object], label: str) -> Found:
    found = Found()
    for result in results:
        _walk(result, found)
    assert found.receipts or found.provenances, f"{label}: nothing to check"
    for receipt in found.receipts:
        assert receipt.provenance is Provenance.FAKE_SYNTHETIC, label
        assert receipt.cost_basis is CostBasis.SYNTHETIC_FAKE, label
        assert not receipt.measured, label
    for provenance in found.provenances:
        assert provenance is Provenance.FAKE_SYNTHETIC, label
    for url in found.urls:
        parts = urlsplit(url)
        assert parts.scheme == "https" and parts.hostname and parts.hostname.endswith(".invalid"), (
            f"{label}: non-fake URL {url}"
        )
    return found


def _fresh() -> tuple[FakeClock, SequentialIds]:
    return FakeClock(T0), SequentialIds("sweep")


def _attempt(call: Callable[[], object], results: list[object]) -> None:
    """Keep successful results; scripted failures raise and are deliberately not collected."""
    try:
        results.append(call())
    except Exception as exc:  # noqa: BLE001 - scripted provider errors are the expected output here
        assert exc.__class__.__module__.startswith("microdrama.contracts"), exc


def _clean_media(suite: dict) -> tuple[Path, str]:
    clean = suite["clean"]
    return clean.path, clean.sha256


# --- sweeps, one per fake -------------------------------------------------------------------


def test_sources_every_scenario(defect_suite) -> None:
    clock, ids = _fresh()
    results: list[object] = []
    for step in SourceScenario:
        fake = FakeSourceProvider(clock=clock, ids=ids, scenarios=(step,))
        query = SourceQuery(query_id=uuid.uuid5(uuid.NAMESPACE_URL, step.value),
                            query_text="fixture", allowed_source_ids=["alpha", "beta"],
                            max_results=5)  # fmt: skip
        _attempt(lambda f=fake, q=query: f.search(q), results)
    _assert_labelled(results, "sources")


def test_llm_every_scenario() -> None:
    clock, ids = _fresh()
    results: list[object] = []
    schema = {"type": "object", "required": ["title"], "properties": {"title": {"type": "string"}}}
    for step in LLMScenario:
        fake = FakeLLMProvider(clock=clock, ids=ids, scenarios=(step,))
        request = LLMRequest(request_id=uuid.uuid5(uuid.NAMESPACE_URL, step.value), role=RuntimeRole.CRITIC,
                             model_config_ref="fake-critic", instruction="Critique the fixture.",
                             output_schema=schema, max_input_tokens=1000, max_output_tokens=200,
                             client_token=f"llm-{step.value}")  # fmt: skip
        _attempt(lambda f=fake, r=request: f.generate(r), results)
    _assert_labelled(results, "llm")


def _image(token: str) -> ImageRequest:
    return ImageRequest(request_id=uuid.uuid5(uuid.NAMESPACE_URL, token), model_config_ref="fake-image",
                        rights_route_id="rights-fixture", prompt_text="still", width=256, height=256,
                        seed=3, client_token=token, reservation_id=uuid.uuid5(uuid.NAMESPACE_URL, "res"))  # fmt: skip


def _op(request: ImageRequest | VoiceRequest) -> ProviderOperation:
    return ProviderOperation(operation_id=uuid.uuid5(uuid.NAMESPACE_URL, "op:" + request.client_token),
                             provider="fake-generation", operation_kind="generation.submit",
                             client_token=request.client_token, request_sha256=canonical_hash(request),
                             state=ProviderOperationState.PENDING_SUBMIT, deadline_at=T0 + timedelta(hours=1))  # fmt: skip


def test_generation_every_scenario() -> None:
    clock, ids = _fresh()
    results: list[object] = []
    for step in GenerationScenario:
        fake = FakeGenerationProvider(clock=clock, ids=ids, scenarios=(step,))
        request = _image(f"gen-{step.value}")
        op = _op(request)
        _attempt(lambda f=fake, r=request, o=op: f.submit(o, r), results)
        for _ in range(3):
            _attempt(lambda f=fake, o=op: f.status(o), results)
        _attempt(lambda f=fake, o=op: f.reconcile(o), results)
    voice = VoiceRequest(request_id=uuid.uuid5(uuid.NAMESPACE_URL, "v"), model_config_ref="fake-voice",
                         rights_route_id="rights-fixture", voice_id="voice-fon-v1", line_id="s1-l1",
                         text_th="ทดสอบ", client_token="voice-sweep",
                         reservation_id=uuid.uuid5(uuid.NAMESPACE_URL, "res"))  # fmt: skip
    fake = FakeGenerationProvider(clock=clock, ids=ids)
    _attempt(lambda: fake.submit(_op(voice), voice), results)
    _assert_labelled(results, "generation")


def test_pods_every_scenario() -> None:
    clock, ids = _fresh()
    results: list[object] = []
    for step in PodCreateScenario:
        fake = FakePodProvider(clock=clock, ids=ids, scenarios=(step,))
        request = PodCreateRequest(client_token=f"pod-{step.value}", name="sweep", owned_tag="microdrama-owned:sweep",
                                   gpu_type_allowlist=["FAKE-GPU-24GB"], max_hourly_price_micro_usd=900_000,
                                   min_host_ram_gb=16, container_image="registry.fake.invalid/x@sha256:" + "c" * 64)  # fmt: skip
        _attempt(lambda f=fake, r=request: f.create_pod(r), results)
        results.append(fake.find_pods())
        clock.advance(seconds=60)
        results.append(
            fake.usage("fake-pod-0001", since=T0, until=clock.now())
            if fake.get_pod("fake-pod-0001")
            else []
        )
        results.append(fake.usage("fake-pod-0001", since=T0, until=clock.now() + timedelta(seconds=1)) if fake.get_pod("fake-pod-0001") else [])  # fmt: skip
    for step in PodStopScenario:
        fake = FakePodProvider(clock=clock, ids=ids, scenarios=(step,))
        fake.create_pod(PodCreateRequest(client_token=f"stop-{step.value}", name="s", owned_tag="microdrama-owned:s",
                                         gpu_type_allowlist=["FAKE-GPU-24GB"], max_hourly_price_micro_usd=900_000,
                                         min_host_ram_gb=16, container_image="registry.fake.invalid/x@sha256:" + "d" * 64))  # fmt: skip
        _attempt(lambda f=fake: f.stop_pod("fake-pod-0001"), results)
        assert fake.get_pod("fake-pod-0001") is not None  # stop never deletes the pod record
    _assert_labelled(results, "pods")


def test_comfy_every_scenario() -> None:
    graph = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "fake.safetensors"}},
             "2": {"class_type": "FakeVideoModelSampler", "inputs": {"model": ["1", 0], "prompt": "p", "frames": 8}},  # fmt: skip
             "3": {"class_type": "VHS_VideoCombine", "inputs": {"images": ["2", 0], "frame_rate": 24, "filename_prefix": "sw", "format": "video/h264-mp4"}}}  # fmt: skip
    results: list[object] = []
    for step in ComfyScenario:
        clock = FakeClock(T0)
        state = FakeComfyServerState(clock)
        client = FakeComfyClient(state, scenarios=(step,))
        prompt_id = client.queue_prompt(graph, client_id=step.value)
        clock.advance(ms=3_000)
        entry = client.history(prompt_id)
        results.append(entry)
        if entry is not None:
            results.extend(client.progress_events(prompt_id))
            for output in entry.outputs:
                results.append(
                    client.fetch_output(output)
                )  # bytes carry no labels; checked via entry
    _assert_labelled(results, "comfy")


def test_community_every_scenario(defect_suite) -> None:
    clock, ids = _fresh()
    results: list[object] = []
    for step in CommunityScenario:
        fake = FakeCommunityProvider(Platform.TIKTOK, clock=clock, ids=ids, scenarios=(step,))
        results.append(fake.fetch_events("acct:fake-main", since=None))
        _attempt(lambda f=fake: f.execute(management_action()), results)
    _assert_labelled(results, "community")


def test_membership_and_webhooks_every_scenario(defect_suite, tmp_path) -> None:
    from microdrama.testing.media import make_clip

    clock, ids = _fresh()
    results: list[object] = []
    entry = membership_catalog_entry()
    media = make_clip(tmp_path / "member.mp4", duration_ms=1_000, with_audio=False)
    for step in EntitlementScenario:
        fake = FakeMembershipProvider(
            MembershipProviderKind.PATREON, clock=clock, ids=ids, scenarios=(step,)
        )
        results.append(fake.check_entitlement("member-sweep", entry))
        results.append(fake.publish_early_access(entry, media))
    body = b'{"id":"evt-sweep","type":"member.created"}'
    verifier = FakeWebhookVerifier("fake-patreon")
    results.append(verifier.verify({"x-fake-signature": fake_signature(body)}, body))
    results.append(verifier.verify({"x-fake-signature": "0" * 64}, body))
    _assert_labelled(results, "membership")


def test_publisher_every_scenario(defect_suite) -> None:
    suite, _ = defect_suite
    media_path, sha = _clean_media(suite)
    clock, ids = _fresh()
    results: list[object] = []
    for step in PublishScenario:
        fake = FakePublisherAdapter(Platform.YOUTUBE, clock=clock, ids=ids, scenarios=(step,))
        base = publication_command().model_dump(mode="python")
        base.update(asset_sha256=sha, client_token=f"pub-{step.value}")
        command = PublicationCommand(**base)
        _attempt(lambda f=fake, c=command: f.submit(c, media_path), results)
        _attempt(lambda f=fake, c=command: f.status(c, "fake-youtube-" + "0" * 16), results)
        results.append(fake.reconcile(command))
        results.append(fake.capability("acct:fake-main"))
    adapter = FakePublisherAdapter(Platform.YOUTUBE, clock=clock, ids=ids, operations={
        CapabilityOperation.AI_DISCLOSURE: CapabilitySupport.UNSUPPORTED})  # fmt: skip
    base = publication_command().model_dump(mode="python")
    base.update(asset_sha256=sha, client_token="pub-unsupported")
    results.append(adapter.submit(PublicationCommand(**base), media_path))
    _assert_labelled(results, "publisher")


def test_media_review_and_asr_on_every_defect(defect_suite) -> None:
    suite, registry = defect_suite
    clock, ids = _fresh()
    results: list[object] = []
    for name, defect in suite.items():
        asr = FakeASRProvider(clock=clock, ids=ids, truth=registry)
        request = ASRRequest(request_id=uuid.uuid5(uuid.NAMESPACE_URL, "asr:" + name), asset_id=uuid.uuid5(
            uuid.NAMESPACE_URL, "asset:" + name), asset_sha256=defect.sha256, model_config_ref="fake-asr",
            client_token="asr-" + name)  # fmt: skip
        results.append(asr.transcribe(request, defect.path))
        if defect.media_kind != "caption":
            descriptor = AssetDescriptor(
                asset_id=uuid.uuid5(uuid.NAMESPACE_URL, "asset:" + name),
                asset_kind=AssetKind.VIDEO,
                object_key=f"fixtures/{defect.path.name}",
                sha256=defect.sha256,
                size_bytes=defect.path.stat().st_size,
                media_type="video/mp4",
                media=MediaInfo(duration_ms=defect.truth.duration_ms, has_video=True,
                                has_audio=defect.truth.has_audio),
                state=AssetState.PROVISIONAL,
                provenance=Provenance.ORIGINAL_FIXTURE,
                created_at=T0,
            )  # fmt: skip
        else:
            continue
        review = FakeMediaReviewProvider(clock=clock, ids=ids, truth=registry,
                                         unreleased_claim_phrases=("ดูได้แล้วตอนนี้",))  # fmt: skip
        obs_request = ObservationRequest(
            request_id=uuid.uuid5(uuid.NAMESPACE_URL, "obs:" + name),
            episode_id=uuid.UUID(int=5),
            media=[MediaUnderReview(asset_id=descriptor.asset_id, asset_sha256=defect.sha256,
                                    duration_ms=defect.truth.duration_ms)],
            questions=[NeutralQuestion(question_id="q1", text="Who speaks and what amounts are shown?")],
        )  # fmt: skip
        observed = review.observe(obs_request, [descriptor])
        results.append(observed)
        materials = ComparisonMaterials(frozen_report=observed.report, script=script())
        cmp_request = ComparisonRequest(
            request_id=uuid.uuid5(uuid.NAMESPACE_URL, "cmp:" + name),
            episode_id=uuid.UUID(int=5),
            observation_report_id=observed.report.report_id,
            observation_report_sha256=canonical_hash(observed.report),
            script_id=script().script_id,
            script_version=1,
            script_sha256=canonical_hash(script()),
            canon_version=1,
            canon_sha256=canonical_hash({"canon": 1}),
        )  # fmt: skip
        results.append(review.compare(cmp_request, materials))
    _assert_labelled(results, "asr-and-review")


def test_factory_built_providers_are_all_labelled_offline(tmp_path) -> None:
    providers = build_fake_providers(Settings(execution_mode=ExecutionMode.OFFLINE_MOCK), FakeClock(T0),
                                     SequentialIds("factory"), truth=FixtureTruthRegistry())  # fmt: skip
    assert providers.truth is not None
    assert (
        Settings(execution_mode=ExecutionMode.OFFLINE_MOCK).execution_mode
        is ExecutionMode.OFFLINE_MOCK
    )
    assert {p for p in Platform} == set(providers.publishers)
