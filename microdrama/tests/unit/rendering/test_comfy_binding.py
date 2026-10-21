"""Template binding: pinned hashes, no dropped controls, deterministic graphs."""

from __future__ import annotations

import pytest

from microdrama.contracts.enums import ControlKind
from microdrama.contracts.errors import SchemaInvalid, UnsupportedControl
from microdrama.contracts.examples import render_request
from microdrama.rendering.workflows import (
    MOCK_VIDEO_TEMPLATE,
    bind_workflow,
    template_sha256,
)


def _request(**overrides: object):
    base = render_request()
    updates = {"workflow_sha256": template_sha256(MOCK_VIDEO_TEMPLATE)}
    updates.update(overrides)
    return base.model_copy(update=updates)


def test_example_contract_request_binds_onto_the_mock_template() -> None:
    bound = bind_workflow(MOCK_VIDEO_TEMPLATE, _request())
    assert set(bound.graph) == {"checkpoint", "reference_0", "sampler", "combine"}
    assert bound.graph["sampler"]["inputs"]["frames"] == 96  # 4000ms * 24fps
    assert bound.graph["combine"]["inputs"]["filename_prefix"] == "md/ep1/sh1/a1"
    assert bound.workflow_sha256 == template_sha256(MOCK_VIDEO_TEMPLATE)


def test_a_stored_request_cannot_silently_render_a_different_workflow() -> None:
    request = _request(workflow_sha256="0" * 64)
    with pytest.raises(SchemaInvalid) as exc:
        bind_workflow(MOCK_VIDEO_TEMPLATE, request)
    assert exc.value.details["expected"] == template_sha256(MOCK_VIDEO_TEMPLATE)


def test_a_required_control_the_template_cannot_carry_is_refused_not_dropped() -> None:
    request = _request(
        required_controls=[ControlKind.TEXT_PROMPT, ControlKind.AUDIO_DRIVEN_LIPSYNC]
    )
    with pytest.raises(UnsupportedControl) as exc:
        bind_workflow(MOCK_VIDEO_TEMPLATE, request)
    assert exc.value.details["controls"] == ["AUDIO_DRIVEN_LIPSYNC"]


def test_reference_controls_without_assets_are_refused() -> None:
    request = _request(reference_asset_ids=[])
    with pytest.raises(SchemaInvalid, match="reference"):
        bind_workflow(MOCK_VIDEO_TEMPLATE, request)


def test_an_uncarried_negative_prompt_is_refused_not_discarded() -> None:
    request = _request(negative_prompt_text="blurry, distorted hands")
    with pytest.raises(UnsupportedControl, match="negative"):
        bind_workflow(MOCK_VIDEO_TEMPLATE, request)


def test_binding_is_deterministic_across_calls() -> None:
    first = bind_workflow(MOCK_VIDEO_TEMPLATE, _request())
    second = bind_workflow(MOCK_VIDEO_TEMPLATE, _request())
    assert first.graph == second.graph
    assert first.request_hash == second.request_hash


def test_frames_round_up_to_whole_frames() -> None:
    request = _request(duration_ms=4_001)
    bound = bind_workflow(MOCK_VIDEO_TEMPLATE, request)
    assert bound.graph["sampler"]["inputs"]["frames"] == 97


def test_first_and_last_frame_bind_distinct_reference_nodes() -> None:
    base = _request()
    request = _request(
        required_controls=[
            ControlKind.TEXT_PROMPT,
            ControlKind.FIRST_FRAME,
            ControlKind.LAST_FRAME,
        ],
        reference_asset_ids=base.reference_asset_ids * 2,
    )
    bound = bind_workflow(MOCK_VIDEO_TEMPLATE, request)
    inputs = bound.graph["sampler"]["inputs"]
    assert inputs["first_frame"] == ["reference_0", 0]
    assert inputs["last_frame"] == ["reference_1", 0]
    assert inputs["reference_images"] == [["reference_0", 0], ["reference_1", 0]]
