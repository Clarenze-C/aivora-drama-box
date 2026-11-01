from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest

from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode
from microdrama.contracts.errors import EffectDenied, NeedsReconciliation
from microdrama.contracts.providers import ComfyOutputFile
from microdrama.rendering.comfy_transport import ComfyHttpClient


class FixtureTransport:
    def __init__(self, responses: list[bytes]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def request(self, method: str, url: str, *, headers: Any, body: bytes | None = None) -> bytes:
        self.calls.append((method, url, dict(headers), body))
        if not self.responses:
            raise NeedsReconciliation("fixture exhausted")
        return self.responses.pop(0)


def _client(
    settings: Settings,
    fixture: FixtureTransport,
    guard: Any = lambda _authorization: None,
    *,
    request_guard: Any = lambda _path, _key, _authorization: None,
    credential_calls: list[str] | None = None,
) -> ComfyHttpClient:
    return ComfyHttpClient(
        settings,
        endpoint="https://comfy.example",
        credential_ref="credref:comfy-proxy",
        credential_resolver=lambda name: (
            (credential_calls.append(name) if credential_calls is not None else None)
            or "fixture-secret"
        ),
        request_guard=request_guard,
        dispatch_guard=guard,
        transport=fixture,
    )


def test_offline_mock_refuses_prompt_before_transport_or_guard() -> None:
    fixture = FixtureTransport([])
    called = False
    credentials: list[str] = []

    def guard(_authorization: Any) -> None:
        nonlocal called
        called = True

    client = _client(Settings(), fixture, guard, credential_calls=credentials)
    with pytest.raises(EffectDenied):
        client.queue_prompt({"1": {}}, client_id="client")
    assert not fixture.calls
    assert not called
    assert credentials == []


def test_object_info_respects_paid_effect_flag_before_credential_resolution() -> None:
    fixture = FixtureTransport([])
    credentials: list[str] = []
    client = _client(
        Settings(execution_mode=ExecutionMode.PAID_BENCHMARK, paid_requests_enabled=False),
        fixture,
        credential_calls=credentials,
    )
    with pytest.raises(EffectDenied):
        client.object_info()
    assert fixture.calls == []
    assert credentials == []


def test_live_request_without_reservation_scope_never_resolves_credentials() -> None:
    fixture = FixtureTransport([])
    credentials: list[str] = []
    client = _client(
        Settings(execution_mode=ExecutionMode.PAID_BENCHMARK, paid_requests_enabled=True),
        fixture,
        credential_calls=credentials,
    )
    with pytest.raises(EffectDenied, match="no scoped durable"):
        client.object_info()
    assert fixture.calls == []
    assert credentials == []


def test_read_routes_require_reservation_or_operation_guard_before_credentials() -> None:
    fixture = FixtureTransport([])
    credentials: list[str] = []

    def missing_authorization(_path: str, _key: str | None, _authorization: Any) -> None:
        raise EffectDenied("no active reservation or provider operation")

    client = _client(
        Settings(execution_mode=ExecutionMode.PAID_BENCHMARK, paid_requests_enabled=True),
        fixture,
        request_guard=missing_authorization,
        credential_calls=credentials,
    )
    output = ComfyOutputFile(node_id="7", filename="out.mp4", media_kind="video")
    with client.authorization_scope(
        reservation_id=uuid4(),
        episode_id=uuid4(),
        job_id=uuid4(),
        operation_id=uuid4(),
    ):
        calls = (
            client.object_info,
            lambda: client.history("prompt-1"),
            lambda: client.in_queue("prompt-1"),
            lambda: client.fetch_output(output),
        )
        for call in calls:
            with pytest.raises(EffectDenied, match="no active reservation"):
                call()
    assert fixture.calls == []
    assert credentials == []


def test_paid_prompt_uses_documented_body_and_dispatch_guard() -> None:
    fixture = FixtureTransport([b'{"prompt_id":"pid-1","number":1}'])
    guard_calls: list[Any] = []
    client = _client(
        Settings(
            execution_mode=ExecutionMode.PAID_BENCHMARK,
            paid_requests_enabled=True,
        ),
        fixture,
        lambda authorization: guard_calls.append(authorization),
    )
    auth = {
        "reservation_id": uuid4(),
        "episode_id": uuid4(),
        "job_id": uuid4(),
        "operation_id": uuid4(),
    }
    with client.authorization_scope(**auth):
        assert (
            client.queue_prompt({"1": {"class_type": "CheckpointLoaderSimple"}}, client_id="md-1")
            == "pid-1"
        )
    assert len(guard_calls) == 1
    assert guard_calls[0].reservation_id == auth["reservation_id"]
    method, url, headers, raw = fixture.calls[0]
    assert method == "POST" and url == "https://comfy.example/prompt"
    assert headers["Authorization"] == "Bearer fixture-secret"
    assert json.loads(raw or b"{}") == {
        "prompt": {"1": {"class_type": "CheckpointLoaderSimple"}},
        "client_id": "md-1",
    }


def test_missing_prompt_id_is_ambiguous_and_never_retried() -> None:
    fixture = FixtureTransport([b'{"number":1}'])
    client = _client(
        Settings(execution_mode=ExecutionMode.PAID_BENCHMARK, paid_requests_enabled=True),
        fixture,
    )
    with client.authorization_scope(
        reservation_id=uuid4(),
        episode_id=uuid4(),
        job_id=uuid4(),
        operation_id=uuid4(),
    ):
        with pytest.raises(NeedsReconciliation):
            client.queue_prompt({"1": {}}, client_id="md-1")
    assert len(fixture.calls) == 1
