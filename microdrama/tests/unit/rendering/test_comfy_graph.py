"""Graph validation: UI-format never passes; node capability comes from the catalog."""

from __future__ import annotations

import pytest

from microdrama.contracts.errors import SchemaInvalid, UnsupportedControl
from microdrama.rendering.comfy_graph import is_ui_format, validate_api_graph
from microdrama.testing.fakes.comfy import FAKE_NODE_CLASSES


def valid_graph() -> dict:
    """A fresh API-format graph per test (mutations never leak between tests)."""
    return {
        "checkpoint": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "fake-video-model.safetensors"},
        },
        "sampler": {
            "class_type": "FakeVideoModelSampler",
            "inputs": {
                "model": ["checkpoint", 0],
                "prompt": "a test prompt",
                "frames": 96,
            },
        },
        "combine": {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "images": ["sampler", 0],
                "frame_rate": 24,
                "filename_prefix": "md/ep1/sh1/a1",
                "format": "video/h264-mp4",
            },
        },
    }


UI_GRAPH = {
    "nodes": [{"id": 1, "type": "KSampler", "inputs": [], "outputs": [], "pos": [0, 0]}],
    "links": [[1, 0, 0, 1, 0, "MODEL"]],
}


def test_valid_api_graph_passes_the_catalog_check() -> None:
    validate_api_graph(valid_graph(), FAKE_NODE_CLASSES)  # no raise


def test_ui_format_workflow_is_never_a_runnable_api_payload() -> None:
    assert is_ui_format(UI_GRAPH)
    with pytest.raises(SchemaInvalid, match="UI-format"):
        validate_api_graph(UI_GRAPH, FAKE_NODE_CLASSES)


def test_ui_format_detection_is_about_lists_not_mere_presence() -> None:
    graph = valid_graph()
    graph["nodes"] = "not-a-list"
    assert not is_ui_format(graph)
    # a non-node top-level key is a malformed node for the server, typed the same
    # way as any other malformed node (the fake rejects it identically)
    with pytest.raises(SchemaInvalid) as exc:
        validate_api_graph(graph, FAKE_NODE_CLASSES)
    assert exc.value.details["node_id"] == "nodes"


def test_non_object_and_empty_graphs_are_refused() -> None:
    with pytest.raises(SchemaInvalid):
        validate_api_graph(["not", "an", "object"], FAKE_NODE_CLASSES)
    with pytest.raises(SchemaInvalid):
        validate_api_graph({}, FAKE_NODE_CLASSES)


def test_malformed_node_names_the_node() -> None:
    graph = valid_graph()
    graph["sampler"] = {"no_class_type": True}
    with pytest.raises(SchemaInvalid) as exc:
        validate_api_graph(graph, FAKE_NODE_CLASSES)
    assert exc.value.details["node_id"] == "sampler"


def test_unknown_node_class_is_typed_and_nothing_is_installed() -> None:
    graph = valid_graph()
    graph["sampler"] = {
        "class_type": "WanCameraStabilizer",
        "inputs": {"model": ["checkpoint", 0], "prompt": "p", "frames": 8},
    }
    with pytest.raises(UnsupportedControl) as exc:
        validate_api_graph(graph, FAKE_NODE_CLASSES)
    assert exc.value.details["class_type"] == "WanCameraStabilizer"
    # Nothing was installed to satisfy the missing class: the catalog is unchanged.
    assert "WanCameraStabilizer" not in FAKE_NODE_CLASSES


def test_missing_required_inputs_are_listed() -> None:
    graph = valid_graph()
    graph["sampler"] = {
        "class_type": "FakeVideoModelSampler",
        "inputs": {"model": ["checkpoint", 0], "prompt": "p"},  # frames missing
    }
    with pytest.raises(SchemaInvalid) as exc:
        validate_api_graph(graph, FAKE_NODE_CLASSES)
    assert exc.value.details["missing"] == ["frames"]


def test_link_to_an_absent_node_is_refused() -> None:
    graph = valid_graph()
    graph["combine"]["inputs"]["images"] = ["ghost", 0]
    with pytest.raises(SchemaInvalid) as exc:
        validate_api_graph(graph, FAKE_NODE_CLASSES)
    assert exc.value.details["input"] == "images"
    assert exc.value.details["target"] == "ghost"


def test_link_slot_beyond_the_target_declared_outputs_is_refused() -> None:
    graph = valid_graph()
    graph["sampler"]["inputs"]["model"] = ["checkpoint", 9]  # MODEL,CLIP,VAE = slots 0..2
    with pytest.raises(SchemaInvalid) as exc:
        validate_api_graph(graph, FAKE_NODE_CLASSES)
    assert exc.value.details["slot"] == 9
    assert exc.value.details["declared_outputs"] == ["MODEL", "CLIP", "VAE"]


def test_capability_is_checked_against_the_reported_catalog_not_a_hardcoded_list() -> None:
    """A server that lacks a node rejects the graph even though our templates use it."""
    reduced = {name: info for name, info in FAKE_NODE_CLASSES.items() if name != "VHS_VideoCombine"}
    with pytest.raises(UnsupportedControl) as exc:
        validate_api_graph(valid_graph(), reduced)
    assert exc.value.details["class_type"] == "VHS_VideoCombine"
