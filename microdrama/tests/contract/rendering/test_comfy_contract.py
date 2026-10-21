"""Contract pins for the ComfyUI adapter (T013).

These freeze the interfaces other lanes build against: the operation kind/provider named
by the frozen contract example, protocol conformance of the fake, the pinned template
hash (a stored ``RenderRequest.workflow_sha256`` must stay resolvable), and the bindability
of the canonical contract example through the mock template.
"""

from __future__ import annotations

from datetime import UTC, datetime

from microdrama.contracts.examples import provider_operation, render_request
from microdrama.contracts.providers import ComfyClient
from microdrama.rendering.comfy_graph import validate_api_graph
from microdrama.rendering.comfy_jobs import RENDER_OPERATION_KIND, mock_render_price
from microdrama.rendering.workflows import (
    MOCK_VIDEO_TEMPLATE,
    PRESET_TEMPLATES,
    bind_workflow,
    template_sha256,
)
from microdrama.testing.fakes import FakeClock, FakeComfyClient, FakeComfyServerState

#: Guardian-visible stability pin: bumping the template (new node classes, controls,
#: model file, version) changes this hash and invalidates every stored request that
#: pinned the old one. That is intentional and must be a conscious contract change.
PINNED_MOCK_VIDEO_TEMPLATE_SHA256 = (
    "af20bebe9b5c78b09cdff53abcc62ceb6337bfb22e1f80211f9d0e26940727d7"
)


def _client() -> FakeComfyClient:
    clock = FakeClock(datetime(2026, 10, 21, tzinfo=UTC))
    return FakeComfyClient(FakeComfyServerState(clock))


def test_operation_kind_and_provider_match_the_frozen_contract_example() -> None:
    example = provider_operation()
    assert RENDER_OPERATION_KIND == example.operation_kind == "comfy.queue_prompt"
    assert _client().provider_id == example.provider == "fake-comfy"
    assert example.external_id is not None  # prompt ids are persisted external ids


def test_the_fake_satisfies_the_comfyclient_protocol() -> None:
    assert isinstance(_client(), ComfyClient)


def test_mock_video_template_hash_is_pinned() -> None:
    assert template_sha256(MOCK_VIDEO_TEMPLATE) == PINNED_MOCK_VIDEO_TEMPLATE_SHA256
    # the presets the contract example may name map onto the pinned template
    assert PRESET_TEMPLATES["fake-quality-8step"] is MOCK_VIDEO_TEMPLATE


def test_the_canonical_contract_request_binds_and_validates() -> None:
    request = render_request().model_copy(
        update={"workflow_sha256": template_sha256(MOCK_VIDEO_TEMPLATE)}
    )
    bound = bind_workflow(MOCK_VIDEO_TEMPLATE, request)
    validate_api_graph(bound.graph, _client().object_info())


def test_mock_price_is_the_fake_synthetic_gpu_second_quote() -> None:
    price = mock_render_price()
    assert price.unit_price_micro_usd == 250
    assert price.currency == "USD"
    assert price.source.value == "FAKE_SYNTHETIC"
