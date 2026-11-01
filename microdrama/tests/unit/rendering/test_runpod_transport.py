from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode, PodState
from microdrama.contracts.errors import (
    Conflict,
    EffectDenied,
    NeedsReconciliation,
    PolicyDenied,
    TransientProviderError,
)
from microdrama.contracts.providers import PodCreateRequest
from microdrama.persistence import Database
from microdrama.rendering.janitor import Janitor
from microdrama.rendering.leases import PodLeaseConfig
from microdrama.rendering.pods import PodManager, PodSpec
from microdrama.rendering.runpod_transport import (
    RunpodQuoteAttestation,
    RunpodRestProvider,
    pod_name,
)
from microdrama.testing.fakes import FakeClock, SequentialIds

NOW = datetime(2026, 10, 30, 12, tzinfo=UTC)
IMAGE = "registry.example/comfy@sha256:" + "a" * 64
NS = "a1b2c3d4"
TAG = f"microdrama-owned:{NS}"


@dataclass
class Response:
    status: int
    body: bytes


class ScriptedTransport:
    def __init__(self, handler: Any) -> None:
        self.handler = handler
        self.calls: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def request(
        self, method: str, url: str, *, headers: Any, body: bytes | None = None
    ) -> Response:
        self.calls.append((method, url, dict(headers), body))
        return self.handler(method, url, body)


def _pod(
    *, name: str | None = None, state: str = "RUNNING", cost: str = "0.900000", image: str = IMAGE
) -> dict[str, Any]:
    return {
        "id": "pod-123",
        "name": name or pod_name(NS, "token-1"),
        "image": image,
        "status": state,
        "cost": cost,
        "createdAt": NOW.isoformat(),
        "gpu": {"id": "NVIDIA A40", "count": 1, "memory": 48, "vcpuCount": 16},
        "runtime": {"ports": [{"private": 8188, "public": 8188, "type": "http"}]},
    }


def _attestation(*, enabled: bool = True, quote: int = 900_000) -> RunpodQuoteAttestation:
    return RunpodQuoteAttestation(
        namespace=NS,
        quote_micro_usd_per_hour=quote,
        quote_as_of=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=30),
        container_disk_gb=1,
        container_storage_micro_usd_per_gb_month=100_000,
        persistent_storage_micro_usd_per_gb_month=200_000,
        pinned_image=IMAGE,
        allowed_gpu_types=frozenset({"NVIDIA A40"}),
        host_ram_gb_by_gpu={"NVIDIA A40": 64},
        rights_evidence_id="rights-evidence-t031",
        preset_evidence_id="preset-evidence-t031",
        activation_enabled=enabled,
    )


def _provider(
    transport: ScriptedTransport,
    *,
    mode: ExecutionMode = ExecutionMode.PAID_BENCHMARK,
    enabled: bool = True,
    quote: int = 900_000,
    guard: Any = None,
    cleanup_guard: Any = None,
) -> RunpodRestProvider:
    settings = Settings(
        execution_mode=mode,
        paid_requests_enabled=mode is ExecutionMode.PAID_BENCHMARK,
        cloud_resources_enabled=mode is ExecutionMode.PAID_BENCHMARK,
    )
    return RunpodRestProvider(
        settings,
        credential_ref="credref:runpod-test",
        credential_resolver=lambda _ref: "fixture-secret",
        attestation=_attestation(enabled=enabled, quote=quote),
        now=lambda: NOW,
        reservation_guard=guard or (lambda _request, _attestation: None),
        cleanup_guard=cleanup_guard or (lambda _operation, _pod_id: None),
        transport=transport,
    )


def _request(token: str = "token-1") -> PodCreateRequest:
    return PodSpec(
        gpu_type_allowlist=("NVIDIA A40",),
        max_hourly_price_micro_usd=900_000,
        min_host_ram_gb=32,
        container_image=IMAGE,
        volume_gb=5,
    ).to_request(name="ignored", client_token=token, owned_tag=TAG)


def _json(status: int, value: Any) -> Response:
    return Response(status, json.dumps(value).encode())


def test_offline_mock_denies_before_transport_and_reservation_guard() -> None:
    transport = ScriptedTransport(lambda *_: pytest.fail("network must not be called"))
    guards: list[bool] = []
    provider = _provider(
        transport, mode=ExecutionMode.OFFLINE_MOCK, guard=lambda *_: guards.append(True)
    )
    with pytest.raises(EffectDenied):
        provider.create_pod(_request())
    assert transport.calls == []
    assert guards == []


def test_create_timeout_then_owned_list_match_recovers_without_second_post() -> None:
    created = _pod()
    list_calls = 0

    def handler(method: str, url: str, _body: bytes | None) -> Response:
        nonlocal list_calls
        if method == "POST":
            raise NeedsReconciliation("simulated response timeout after create")
        if url.endswith("/pods?limit=1000"):
            list_calls += 1
            if list_calls == 1:
                return _json(
                    200, {"pods": [], "pagination": {"hasNextPage": False, "nextCursor": None}}
                )
            return _json(
                200, {"pods": [created], "pagination": {"hasNextPage": False, "nextCursor": None}}
            )
        if url.endswith("/pods/pod-123"):
            return _json(200, created)
        raise AssertionError((method, url))

    transport = ScriptedTransport(handler)
    provider = _provider(transport)
    # The injected provider method reproduces POST timeout. Manager reconciles by list.
    manager = PodManager(
        provider,
        type("Clock", (), {"now": lambda self: NOW})(),
        type("Cfg", (), {"owned_tag": TAG, "stop_attempts": 1})(),
    )
    pod = manager.acquire_or_reconcile(
        PodSpec(("NVIDIA A40",), 900_000, 32, IMAGE, volume_gb=5),
        name="render",
        client_token="token-1",
    )
    assert pod.pod_id == "pod-123" and pod.owned_tag == TAG
    assert (
        len([call for call in transport.calls if call[0] == "POST" and call[1].endswith("/pods")])
        == 1
    )


def test_create_timeout_not_created_stays_unknown_without_retry() -> None:
    def handler(method: str, url: str, _body: bytes | None) -> Response:
        if method == "POST":
            raise NeedsReconciliation("timeout, create may or may not have happened")
        return _json(200, {"pods": [], "pagination": {"hasNextPage": False, "nextCursor": None}})

    transport = ScriptedTransport(handler)
    provider = _provider(transport)
    manager = PodManager(
        provider,
        type("Clock", (), {"now": lambda self: NOW})(),
        type("Cfg", (), {"owned_tag": TAG, "stop_attempts": 1})(),
    )
    with pytest.raises(NeedsReconciliation):
        manager.acquire_or_reconcile(
            PodSpec(("NVIDIA A40",), 900_000, 32, IMAGE, volume_gb=5),
            name="render",
            client_token="token-1",
        )
    assert (
        len([call for call in transport.calls if call[0] == "POST" and call[1].endswith("/pods")])
        == 1
    )


def test_create_timeout_with_incomplete_list_remains_unknown() -> None:
    def handler(method: str, url: str, _body: bytes | None) -> Response:
        if method == "POST":
            raise NeedsReconciliation("timeout")
        return Response(503, b"unavailable")

    provider = _provider(ScriptedTransport(handler))
    with pytest.raises(NeedsReconciliation):
        provider.create_pod(_request())


def test_same_name_collision_with_different_image_fails_closed() -> None:
    collision = _pod(image="registry.example/other@sha256:" + "c" * 64)

    def handler(method: str, url: str, _body: bytes | None) -> Response:
        if method == "POST":
            raise NeedsReconciliation("timeout")
        if url.endswith("/pods?limit=1000"):
            return _json(
                200, {"pods": [collision], "pagination": {"hasNextPage": False, "nextCursor": None}}
            )
        return _json(200, collision)

    provider = _provider(ScriptedTransport(handler))
    with pytest.raises(Conflict, match="mismatched pinned image"):
        provider.create_pod(_request())


def test_reported_price_change_stops_owned_pod_and_does_not_adopt() -> None:
    changed = _pod(cost="1.100000")
    status = "RUNNING"
    calls: list[str] = []

    def handler(method: str, url: str, body: bytes | None) -> Response:
        nonlocal status
        calls.append(f"{method} {url}")
        if method == "POST" and url.endswith("/pods"):
            return _json(201, changed)
        if method == "POST" and url.endswith("/pods/pod-123/action"):
            assert json.loads(body or b"{}") == {"action": "stop"}
            status = "EXITED"
            return _json(200, {**changed, "status": status})
        if method == "GET" and url.endswith("/pods/pod-123"):
            return _json(200, {**changed, "status": status})
        raise AssertionError((method, url))

    provider = _provider(ScriptedTransport(handler))
    with pytest.raises(PolicyDenied, match="differs from the operator quote"):
        provider.create_pod(_request())
    assert any("/action" in call for call in calls)


def test_stop_requires_owned_name_and_readback_confirms_stopped() -> None:
    pod = _pod()
    state = {"status": "RUNNING"}
    cleanup_checks: list[tuple[str, str]] = []

    def handler(method: str, url: str, body: bytes | None) -> Response:
        if method == "GET" and url.endswith("/pods/pod-123"):
            return _json(200, {**pod, **state})
        if method == "POST" and url.endswith("/pods/pod-123/action"):
            assert json.loads(body or b"{}") == {"action": "stop"}
            state["status"] = "EXITED"
            return _json(200, {**pod, **state})
        raise AssertionError((method, url))

    provider = _provider(
        ScriptedTransport(handler),
        cleanup_guard=lambda operation, pod_id: cleanup_checks.append((operation, pod_id)),
    )
    stopped = provider.stop_pod("pod-123")
    assert stopped.state is PodState.STOPPED
    assert cleanup_checks == [("pod.stop", "pod-123")]


def test_stop_failure_is_visible_and_foreign_pod_is_never_stopped() -> None:
    foreign = _pod(name="other-team-pod")
    transport = ScriptedTransport(
        lambda method, url, _body: (
            _json(200, foreign) if method == "GET" else pytest.fail("must not mutate foreign pod")
        )
    )
    provider = _provider(transport)
    with pytest.raises(PolicyDenied):
        provider.stop_pod("pod-123")
    assert len(transport.calls) == 1


def test_stop_failure_remains_visible_when_readback_is_still_running() -> None:
    running = _pod()

    def handler(method: str, url: str, _body: bytes | None) -> Response:
        if method == "GET" and url.endswith("/pods/pod-123"):
            return _json(200, running)
        if method == "POST" and url.endswith("/pods/pod-123/action"):
            return _json(200, running)
        raise AssertionError((method, url))

    provider = _provider(ScriptedTransport(handler))
    with pytest.raises(TransientProviderError, match="not verified"):
        provider.stop_pod("pod-123")


def test_provider_recreated_after_restart_reconciles_same_namespaced_token() -> None:
    existing = _pod()
    transport = ScriptedTransport(
        lambda method, url, _body: (
            _json(
                200,
                {"pods": [existing], "pagination": {"hasNextPage": False, "nextCursor": None}},
            )
            if method == "GET" and url.endswith("/pods?limit=1000")
            else pytest.fail("restart reconciliation must be read-only")
        )
    )
    restarted = _provider(transport)
    matches = restarted.find_pods(client_token="token-1")
    assert len(matches) == 1 and matches[0].pod_id == "pod-123"


def test_billing_history_keeps_provider_buckets_as_raw_evidence() -> None:
    record = {
        "startTime": "2026-10-30T12:00:00Z",
        "endTime": "2026-10-30T13:00:00Z",
        "podId": "pod-123",
        "totalAmount": "1.25",
        "gpuAmount": "1.10",
        "cpuAmount": "0.05",
        "diskAmount": "0.10",
    }

    def handler(method: str, url: str, _body: bytes | None) -> Response:
        if method == "GET" and url.endswith("/pods/pod-123"):
            return _json(200, _pod())
        if method == "GET" and url.startswith("https://api.runpod.io/v2/billing/pods?"):
            assert "bucketSize=hour" in url and "podId=pod-123" in url
            return _json(
                200,
                {
                    "records": [record],
                    "metadata": {
                        "query": {
                            "startTime": "2026-10-30T12:00:00Z",
                            "endTime": "2026-10-30T13:00:00Z",
                            "bucketSize": "hour",
                            "podId": "pod-123",
                        }
                    },
                },
            )
        raise AssertionError((method, url))

    provider = _provider(ScriptedTransport(handler))
    history = provider.billing_history("pod-123", since=NOW, until=NOW + timedelta(hours=1))
    assert history.records[0].total_micro_usd == 1_250_000
    assert history.records[0].gpu_micro_usd == 1_100_000
    assert history.resolved_start == NOW
    # This remains raw provider history because its hour bucket may span lease ownership.
    assert provider.usage("pod-123", since=NOW, until=NOW + timedelta(hours=1)) == []


def test_terminate_only_owned_pod_and_readback_absence_verifies_terminal() -> None:
    owned = _pod()

    def handler(method: str, url: str, _body: bytes | None) -> Response:
        if method == "GET" and url.endswith("/pods/pod-123"):
            return _json(200, owned)
        if method == "DELETE" and url.endswith("/pods/pod-123"):
            return Response(204, b"")
        if method == "GET" and url.endswith("/pods/pod-123"):
            return Response(404, b"")
        raise AssertionError((method, url))

    # First GET proves ownership. DELETE succeeds; following GET proves absence.
    get_count = 0

    def with_delete_readback(method: str, url: str, body: bytes | None) -> Response:
        nonlocal get_count
        if method == "GET" and url.endswith("/pods/pod-123"):
            get_count += 1
            return _json(200, owned) if get_count == 1 else Response(404, b"")
        return handler(method, url, body)

    provider = _provider(ScriptedTransport(with_delete_readback))
    ended = provider.terminate_pod("pod-123")
    assert ended.state is PodState.TERMINATED


def test_independent_janitor_stops_only_namespaced_orphan(db: Database) -> None:
    owned = _pod()
    foreign = _pod(name="foreign-render-pod")
    lifecycle = {"status": "RUNNING"}

    def handler(method: str, url: str, body: bytes | None) -> Response:
        if method == "GET" and url.endswith("/pods?limit=1000"):
            return _json(
                200,
                {
                    "pods": [owned, foreign],
                    "pagination": {"hasNextPage": False, "nextCursor": None},
                },
            )
        if method == "GET" and url.endswith("/pods/pod-123"):
            return _json(200, {**owned, **lifecycle})
        if method == "POST" and url.endswith("/pods/pod-123/action"):
            assert json.loads(body or b"{}") == {"action": "stop"}
            lifecycle["status"] = "EXITED"
            return _json(200, {**owned, **lifecycle})
        raise AssertionError((method, url))

    provider = _provider(ScriptedTransport(handler))
    config = replace(
        PodLeaseConfig.for_mock(),
        owned_tag=TAG,
        allowed_gpu_types=frozenset({"NVIDIA A40"}),
        container_image=IMAGE,
        max_hourly_price_micro_usd=900_000,
    )
    settings = Settings(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
    )
    janitor = Janitor(
        db,
        budget=None,
        provider=provider,
        clock=FakeClock(NOW),
        ids=SequentialIds("runpod-janitor"),
        settings=settings,
        config=config,
    )
    report = janitor.sweep()
    assert report.stopped_pods == ["pod-123"]
    assert lifecycle["status"] == "EXITED"


def test_activation_requires_t031_attestation_and_reservation_guard_runs() -> None:
    created = _pod(state="PROVISIONING")
    transport = ScriptedTransport(lambda *_: _json(201, created))
    disabled = _provider(transport, enabled=False)
    with pytest.raises(EffectDenied):
        disabled.create_pod(_request())
    assert not transport.calls

    guard_calls: list[bool] = []
    active = _provider(
        transport,
        guard=lambda req, att: guard_calls.append(
            req.client_token == "token-1" and bool(att.rights_evidence_id)
        ),
    )
    active.create_pod(_request())
    assert guard_calls == [True]


def test_expired_quote_blocks_before_external_effect() -> None:
    transport = ScriptedTransport(lambda *_: pytest.fail("stale quote must block"))
    stale = _attestation()
    provider = RunpodRestProvider(
        Settings(
            execution_mode=ExecutionMode.PAID_BENCHMARK,
            paid_requests_enabled=True,
            cloud_resources_enabled=True,
        ),
        credential_ref="credref:runpod-test",
        credential_resolver=lambda _ref: "fixture-secret",
        attestation=RunpodQuoteAttestation(
            **{**stale.__dict__, "expires_at": NOW - timedelta(seconds=1)}
        ),
        now=lambda: NOW,
        reservation_guard=lambda *_: None,
        cleanup_guard=lambda *_: None,
        transport=transport,
    )
    with pytest.raises(PolicyDenied):
        provider.create_pod(_request())
    assert not transport.calls
