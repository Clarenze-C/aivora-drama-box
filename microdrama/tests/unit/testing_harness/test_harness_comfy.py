"""ComfyUI fake: API-format graphs only, completion evidence, reconnect and partial files."""

from __future__ import annotations

import pytest

from microdrama.contracts.errors import SchemaInvalid, UnsupportedControl
from microdrama.contracts.providers import ComfyClient
from microdrama.testing.fakes import (
    ComfyScenario,
    FakeClock,
    FakeComfyClient,
    FakeComfyServerState,
)
from microdrama.testing.fakes.comfy import EXECUTION_MS, FAKE_NODE_CLASSES

API_GRAPH = {
    "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "fake.safetensors"}},
    "2": {
        "class_type": "FakeVideoModelSampler",
        "inputs": {"model": ["1", 0], "prompt": "fixture prompt", "frames": 48},
    },
    "3": {
        "class_type": "VHS_VideoCombine",
        "inputs": {
            "images": ["2", 0],
            "frame_rate": 24,
            "filename_prefix": "sh1",
            "format": "video/h264-mp4",
        },
    },
}
UI_GRAPH = {"nodes": [{"id": 1, "type": "CheckpointLoaderSimple"}], "links": []}


def _client(
    clock: FakeClock, *steps: ComfyScenario
) -> tuple[FakeComfyClient, FakeComfyServerState]:
    state = FakeComfyServerState(clock)
    return FakeComfyClient(state, scenarios=steps), state


def test_client_satisfies_protocol(clock: FakeClock) -> None:
    client, _ = _client(clock)
    assert isinstance(client, ComfyClient)


def test_object_info_is_a_fixed_documented_set(clock: FakeClock) -> None:
    client, _ = _client(clock)
    info = client.object_info()
    assert set(info) == {
        "LoadImage",
        "CheckpointLoaderSimple",
        "KSampler",
        "FakeVideoModelSampler",
        "VHS_VideoCombine",
        "SaveAudio",
    }
    assert info["VHS_VideoCombine"].required_inputs == [
        "images",
        "frame_rate",
        "filename_prefix",
        "format",
    ]


def test_ui_format_workflow_is_rejected_and_nothing_is_queued(clock: FakeClock) -> None:
    client, state = _client(clock)
    with pytest.raises(SchemaInvalid, match="UI-format"):
        client.queue_prompt(UI_GRAPH, client_id="c1")
    assert state.submissions == []


def test_unknown_class_is_refused_and_installs_nothing(clock: FakeClock) -> None:
    client, _ = _client(clock)
    before = set(client.object_info())
    graph = {"1": {"class_type": "InstallMeNode", "inputs": {}}}
    with pytest.raises(UnsupportedControl) as info:
        client.queue_prompt(graph, client_id="c1")
    assert info.value.details["class_type"] == "InstallMeNode"
    assert set(client.object_info()) == before == set(FAKE_NODE_CLASSES)


def test_missing_required_input_and_dangling_link_are_schema_errors(clock: FakeClock) -> None:
    client, _ = _client(clock)
    missing = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {}}}
    with pytest.raises(SchemaInvalid):
        client.queue_prompt(missing, client_id="c1")
    dangling = {"1": {"class_type": "FakeVideoModelSampler",
                      "inputs": {"model": ["404", 0], "prompt": "x", "frames": 8}}}  # fmt: skip
    with pytest.raises(SchemaInvalid):
        client.queue_prompt(dangling, client_id="c1")


def test_history_is_none_while_running_then_completes_with_outputs(clock: FakeClock) -> None:
    client, _ = _client(clock)
    prompt_id = client.queue_prompt(API_GRAPH, client_id="c1")
    assert client.in_queue(prompt_id) is True
    assert client.history(prompt_id) is None
    assert [e.event for e in client.progress_events(prompt_id)] == ["executing"]
    clock.advance(ms=EXECUTION_MS)
    entry = client.history(prompt_id)
    assert entry is not None and entry.completed is True and entry.status_str == "success"
    assert [o.media_kind for o in entry.outputs] == ["video"]
    assert client.in_queue(prompt_id) is False


def test_output_bytes_are_an_mp4_container(clock: FakeClock) -> None:
    client, _ = _client(clock)
    prompt_id = client.queue_prompt(API_GRAPH, client_id="c1")
    clock.advance(ms=EXECUTION_MS)
    output = client.history(prompt_id).outputs[0]  # type: ignore[union-attr]
    data = client.fetch_output(output)
    assert data[4:8] == b"ftyp"


def test_executed_event_alone_is_not_completion(clock: FakeClock) -> None:
    client, _ = _client(clock, ComfyScenario.EXECUTED_WITHOUT_OUTPUT)
    prompt_id = client.queue_prompt(API_GRAPH, client_id="c1")
    clock.advance(ms=EXECUTION_MS)
    events = [e.event for e in client.progress_events(prompt_id)]
    assert "executed" in events
    entry = client.history(prompt_id)
    assert entry is not None
    assert entry.completed is False
    assert entry.outputs == []


def test_execution_error_reports_error_status_and_message(clock: FakeClock) -> None:
    client, _ = _client(clock, ComfyScenario.EXECUTION_ERROR)
    prompt_id = client.queue_prompt(API_GRAPH, client_id="c1")
    clock.advance(ms=EXECUTION_MS)
    entry = client.history(prompt_id)
    assert entry is not None
    assert entry.status_str == "error"
    assert entry.error_message and "KSampler" not in entry.error_message
    assert "execution_error" in [e.event for e in client.progress_events(prompt_id)]


def test_reconnect_sees_completed_history_without_requeueing(clock: FakeClock) -> None:
    first, state = _client(clock, ComfyScenario.RECONNECT)
    prompt_id = first.queue_prompt(API_GRAPH, client_id="c1")
    clock.advance(ms=EXECUTION_MS)
    second = FakeComfyClient(state)  # a new client attached to the same server state
    entry = second.history(prompt_id)
    assert entry is not None and entry.completed is True
    assert second.fetch_output(entry.outputs[0]) == first.fetch_output(entry.outputs[0])
    assert state.submissions == [prompt_id]  # nothing was rendered twice


def test_partial_file_is_served_truncated(clock: FakeClock) -> None:
    complete, _ = _client(clock)
    full_prompt = complete.queue_prompt(API_GRAPH, client_id="c1")
    clock.advance(ms=EXECUTION_MS)
    full = complete.fetch_output(complete.history(full_prompt).outputs[0])  # type: ignore[union-attr]

    partial_clock = FakeClock(clock.now().replace(year=2026, month=10, day=21))
    partial, _ = _client(partial_clock, ComfyScenario.PARTIAL_FILE)
    partial_prompt = partial.queue_prompt(API_GRAPH, client_id="c2")
    partial_clock.advance(ms=EXECUTION_MS)
    served = partial.fetch_output(partial.history(partial_prompt).outputs[0])  # type: ignore[union-attr]
    assert 0 < len(served) < len(full)
