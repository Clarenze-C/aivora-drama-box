"""Fake ComfyUI server (T007): API-format graphs only, nothing is ever installed.

``FakeComfyServerState`` plays the server's memory: prompts, timings and rendered files. Several
``FakeComfyClient`` instances can share one state, which is how the RECONNECT scenario proves a
new client sees completed history without re-rendering.

Validation (``queue_prompt``):
- a UI-format workflow (top-level ``nodes``/``links`` lists) is rejected with SchemaInvalid;
- a node with an unknown ``class_type`` is rejected with UnsupportedControl and the fake
  registers nothing new (``object_info`` is unchanged);
- missing required inputs and links to absent nodes are SchemaInvalid.

Completion is clock-driven: a prompt is "in queue" until ``execution_ms`` of fake time pass.
``executed`` progress events are never treated as proof of output: check ``history``.

Scenarios: HAPPY, EXECUTED_WITHOUT_OUTPUT (executed, but history is incomplete with no
outputs), EXECUTION_ERROR (history error with a message), RECONNECT (a fresh client sees the
finished history from shared state), PARTIAL_FILE (the served file is truncated and does not
decode).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar

from microdrama.contracts.enums import Provenance
from microdrama.contracts.errors import NotFound, SchemaInvalid, UnsupportedControl
from microdrama.contracts.providers import (
    ComfyHistoryEntry,
    ComfyNodeInfo,
    ComfyOutputFile,
    ComfyProgressEvent,
)
from microdrama.testing.fakes.common import FakeBase, FakeClock, SequentialIds
from microdrama.testing.media import make_wav_bytes, render_clip_bytes

EXECUTION_MS = 3_000
VIDEO_OUTPUT_MS = 2_000
AUDIO_OUTPUT_MS = 1_000
SAMPLER_CLASSES = ("FakeVideoModelSampler", "KSampler")
OUTPUT_CLASSES: Mapping[str, tuple[str, str]] = MappingProxyType(
    {"VHS_VideoCombine": ("video", ".mp4"), "SaveAudio": ("audio", ".wav")}
)

FAKE_NODE_CLASSES: Mapping[str, ComfyNodeInfo] = MappingProxyType(
    {
        "LoadImage": ComfyNodeInfo(
            class_type="LoadImage", required_inputs=["image"], output_types=["IMAGE", "MASK"]
        ),
        "CheckpointLoaderSimple": ComfyNodeInfo(
            class_type="CheckpointLoaderSimple",
            required_inputs=["ckpt_name"],
            output_types=["MODEL", "CLIP", "VAE"],
        ),
        "KSampler": ComfyNodeInfo(
            class_type="KSampler",
            required_inputs=[
                "model",
                "seed",
                "steps",
                "cfg",
                "positive",
                "negative",
                "latent_image",
            ],
            optional_inputs=["sampler_name", "scheduler", "denoise"],
            output_types=["LATENT"],
        ),
        "FakeVideoModelSampler": ComfyNodeInfo(
            class_type="FakeVideoModelSampler",
            required_inputs=["model", "prompt", "frames"],
            output_types=["LATENT"],
        ),
        "VHS_VideoCombine": ComfyNodeInfo(
            class_type="VHS_VideoCombine",
            required_inputs=["images", "frame_rate", "filename_prefix", "format"],
        ),
        "SaveAudio": ComfyNodeInfo(
            class_type="SaveAudio", required_inputs=["audio", "filename_prefix"]
        ),
    }
)


class ComfyScenario(StrEnum):
    HAPPY = "HAPPY"
    EXECUTED_WITHOUT_OUTPUT = "EXECUTED_WITHOUT_OUTPUT"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    RECONNECT = "RECONNECT"
    PARTIAL_FILE = "PARTIAL_FILE"


def _is_link(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], str)
        and isinstance(value[1], int)
    )


def validate_api_graph(graph: Any) -> None:
    """Accept only the API-format prompt graph, and only with classes this fake knows."""
    if not isinstance(graph, dict) or not graph:
        raise SchemaInvalid("prompt graph must be a non-empty object")
    if isinstance(graph.get("nodes"), list) or isinstance(graph.get("links"), list):
        raise SchemaInvalid("UI-format workflow rejected: submit the API-format prompt graph")
    for node_id, node in graph.items():
        if (
            not isinstance(node, dict)
            or not isinstance(node.get("class_type"), str)
            or not isinstance(node.get("inputs"), dict)
        ):
            raise SchemaInvalid("malformed node: needs class_type and inputs", node_id=str(node_id))
        info = FAKE_NODE_CLASSES.get(node["class_type"])
        if info is None:
            raise UnsupportedControl(
                "unknown node class; this fake server installs nothing",
                node_id=str(node_id),
                class_type=node["class_type"],
            )
        missing = [name for name in info.required_inputs if name not in node["inputs"]]
        if missing:
            raise SchemaInvalid("required inputs missing", node_id=str(node_id), missing=missing)
        for name, value in node["inputs"].items():
            if _is_link(value) and value[0] not in graph:
                raise SchemaInvalid(
                    "link points at a missing node", node_id=str(node_id), input=name
                )


@dataclass
class _Prompt:
    prompt_id: str
    completes_at: datetime
    scenario: ComfyScenario
    first_node: str
    sampler_node: str | None
    outputs: list[ComfyOutputFile] = field(default_factory=list)


class FakeComfyServerState:
    """Server-side memory shared by every client attached to it."""

    def __init__(self, clock: FakeClock, *, execution_ms: int = EXECUTION_MS) -> None:
        self.clock = clock
        self.execution_ms = execution_ms
        self.prompts: dict[str, _Prompt] = {}
        self.submissions: list[str] = []
        self._files: dict[str, tuple[str, ComfyScenario]] = {}
        self._rendered: dict[str, bytes] = {}
        self._counter = 0

    def next_prompt_id(self) -> str:
        self._counter += 1
        return f"fake-prompt-{self._counter:04d}"

    def register_output(self, filename: str, media_kind: str, scenario: ComfyScenario) -> None:
        self._files[filename] = (media_kind, scenario)

    def serve(self, filename: str) -> bytes:
        if filename not in self._files:
            raise NotFound("fake comfy output not found", filename=filename)
        media_kind, scenario = self._files[filename]
        if media_kind not in self._rendered:
            if media_kind == "video":
                self._rendered[media_kind] = render_clip_bytes(VIDEO_OUTPUT_MS)
            else:
                self._rendered[media_kind] = make_wav_bytes(AUDIO_OUTPUT_MS)
        data = self._rendered[media_kind]
        if scenario is ComfyScenario.PARTIAL_FILE:
            return data[: len(data) // 2]
        return data


class FakeComfyClient(FakeBase):
    provider_id: str = "fake-comfy"
    default_scenario: ClassVar[ComfyScenario] = ComfyScenario.HAPPY

    def __init__(
        self,
        state: FakeComfyServerState,
        *,
        scenarios: tuple[ComfyScenario, ...] = (),
    ) -> None:
        super().__init__(clock=state.clock, ids=SequentialIds("comfy"), scenarios=scenarios)
        self.state = state
        self.provenance = Provenance.FAKE_SYNTHETIC

    def object_info(self) -> dict[str, ComfyNodeInfo]:
        self._note("object_info")
        return dict(FAKE_NODE_CLASSES)

    def queue_prompt(self, graph: dict[str, Any], *, client_id: str) -> str:
        validate_api_graph(graph)
        step = self._step("queue_prompt", key=client_id)
        prompt_id = self.state.next_prompt_id()
        sampler = next(
            (node_id for node_id, node in graph.items() if node["class_type"] in SAMPLER_CLASSES),
            None,
        )
        prompt = _Prompt(
            prompt_id=prompt_id,
            completes_at=self.clock.now() + timedelta(milliseconds=self.state.execution_ms),
            scenario=step,
            first_node=str(next(iter(graph))),
            sampler_node=sampler,
        )
        for node_id, node in graph.items():
            if node["class_type"] not in OUTPUT_CLASSES:
                continue
            media_kind, extension = OUTPUT_CLASSES[node["class_type"]]
            prefix = str(node["inputs"].get("filename_prefix", "output"))
            filename = f"{prefix}_{prompt_id[-4:]}_{len(prompt.outputs) + 1:02d}{extension}"
            prompt.outputs.append(
                ComfyOutputFile(
                    node_id=str(node_id),
                    filename=filename,
                    subfolder="",
                    folder_type="output",
                    media_kind=media_kind,
                )
            )
            self.state.register_output(filename, media_kind, step)
        self.state.prompts[prompt_id] = prompt
        self.state.submissions.append(prompt_id)
        return prompt_id

    def _prompt(self, prompt_id: str) -> _Prompt | None:
        return self.state.prompts.get(prompt_id)

    def _running(self, prompt: _Prompt) -> bool:
        return self.clock.now() < prompt.completes_at

    def in_queue(self, prompt_id: str) -> bool:
        self._note("in_queue", key=prompt_id)
        prompt = self._prompt(prompt_id)
        return prompt is not None and self._running(prompt)

    def history(self, prompt_id: str) -> ComfyHistoryEntry | None:
        self._note("history", key=prompt_id)
        prompt = self._prompt(prompt_id)
        if prompt is None or self._running(prompt):
            return None
        if prompt.scenario is ComfyScenario.EXECUTION_ERROR:
            return ComfyHistoryEntry(
                prompt_id=prompt_id,
                completed=True,
                status_str="error",
                error_message=f"fake execution error at node {prompt.sampler_node or prompt.first_node}",
                provenance=Provenance.FAKE_SYNTHETIC,
            )
        if prompt.scenario is ComfyScenario.EXECUTED_WITHOUT_OUTPUT:
            return ComfyHistoryEntry(
                prompt_id=prompt_id,
                completed=False,
                status_str="success",
                provenance=Provenance.FAKE_SYNTHETIC,
            )
        return ComfyHistoryEntry(
            prompt_id=prompt_id,
            completed=True,
            status_str="success",
            outputs=list(prompt.outputs),
            provenance=Provenance.FAKE_SYNTHETIC,
        )

    def progress_events(self, prompt_id: str) -> list[ComfyProgressEvent]:
        self._note("progress_events", key=prompt_id)
        prompt = self._prompt(prompt_id)
        if prompt is None:
            return []
        events = [
            ComfyProgressEvent(prompt_id=prompt_id, event="executing", node_id=prompt.first_node)
        ]
        if self._running(prompt):
            return events
        if prompt.sampler_node is not None:
            events.append(
                ComfyProgressEvent(
                    prompt_id=prompt_id,
                    event="progress",
                    node_id=prompt.sampler_node,
                    value=8,
                    maximum=8,
                )
            )
        if prompt.scenario is ComfyScenario.EXECUTION_ERROR:
            events.append(
                ComfyProgressEvent(
                    prompt_id=prompt_id,
                    event="execution_error",
                    node_id=prompt.sampler_node or prompt.first_node,
                )
            )
            return events
        for output in prompt.outputs:
            events.append(
                ComfyProgressEvent(prompt_id=prompt_id, event="executed", node_id=output.node_id)
            )
        events.append(ComfyProgressEvent(prompt_id=prompt_id, event="execution_success"))
        return events

    def fetch_output(self, output: ComfyOutputFile) -> bytes:
        self._note("fetch_output", key=output.filename)
        return self.state.serve(output.filename)


__all__ = [
    "EXECUTION_MS",
    "FAKE_NODE_CLASSES",
    "ComfyScenario",
    "FakeComfyClient",
    "FakeComfyServerState",
    "validate_api_graph",
]
