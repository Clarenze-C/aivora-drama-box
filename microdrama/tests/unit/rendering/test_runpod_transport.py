from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode, PodState
from microdrama.contracts.errors import (
    Conflict,
    EffectDenied,
    NeedsReconciliation,
    PolicyDenied,
    ProviderError,
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
        quote_id="quote-t031-current",
        currency="USD",
        provider_account_ref="acct:runpod-t031",
        quote_micro_usd_per_hour=quote,
        quote_as_of=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=30),
        container_disk_gb=1,
        container_storage_micro_usd_per_gb_month=100_000,
        persistent_volume_gb=5,
        persistent_storage_micro_usd_per_gb_month=200_000,
        max_storage_exposure_micro_usd=1_200_000,
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
    comfy_token_provider: Any = None,
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
        comfy_token_provider=comfy_token_provider,
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


def test_rejected_request_carries_provider_status_and_body() -> None:
    """T031 run3 (2026-11-04): three consecutive create refusals were diagnosed
    blind because the adapter discarded the provider's error body and status from
    the message. A rejection must carry both so the operator's record and the CLI
    line state what Runpod actually said."""

    def handler(method: str, url: str, _body: bytes | None) -> Response:
        if method == "POST":
            return Response(
                422,
                json.dumps({"detail": "gpu type not available in cloud"}).encode(),
            )
        raise AssertionError(f"unexpected provider call: {method} {url}")

    provider = _provider(ScriptedTransport(handler))
    with pytest.raises(ProviderError, match="422.*gpu type not available in cloud"):
        provider.create_pod(_request())


def test_create_pod_declares_the_comfy_http_port() -> None:
    """T031 prep (2026-11-04): Runpod only serves https://<pod>-8188.proxy.runpod.net
    when the create request declares the HTTP port at creation - ports cannot be added
    to a running pod. Without ports=["8188/http"] the canary can never reach its own
    Comfy endpoint and runs to the deadline. The fixture _pod() fabricates the runtime
    port either way, so only the create body proves the declaration."""
    bodies: list[dict[str, Any]] = []

    def handler(method: str, url: str, body: bytes | None) -> Response:
        if method == "POST":
            bodies.append(json.loads(body or b"{}"))
            return _json(200, _pod())
        if method == "GET" and url.endswith("/pods/pod-123"):
            return _json(200, _pod())
        raise AssertionError(f"unexpected provider call: {method} {url}")

    provider = _provider(ScriptedTransport(handler))
    provider.create_pod(_request())
    assert bodies, "create_pod must POST once"
    assert bodies[0].get("ports") == ["8188/http"]


def test_create_pod_sets_the_gateway_token_env_from_the_credential_ref(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CN-5 (2026-11-09, canary-night review): the pod's exposed ComfyUI port is
    a token-checking gateway inside the image, so the create request must set
    its token as a pod env var - resolved from the same credential ref the
    ComfyUI client authenticates with. The token never enters the image and is
    never printed."""

    def handler(method: str, url: str, body: bytes | None) -> Response:
        if method == "POST":
            return _json(200, _pod())
        if method == "GET" and url.endswith("/pods/pod-123"):
            return _json(200, _pod())
        raise AssertionError(f"unexpected provider call: {method} {url}")

    provider = _provider(
        ScriptedTransport(handler), comfy_token_provider=lambda: "synthetic-gateway-token"
    )
    seen: list[dict[str, Any]] = []
    original = provider._transport.request

    def recording(method: str, url: str, *, headers: Any, body: bytes | None = None) -> Any:
        if method == "POST":
            seen.append(json.loads(body or b"{}"))
        return original(method, url, headers=headers, body=body)

    provider._transport.request = recording  # type: ignore[method-assign]
    provider.create_pod(_request())
    assert seen[0].get("env") == {"MICRODRAMA_COMFY_TOKEN": "synthetic-gateway-token"}
    captured = capsys.readouterr()
    assert "synthetic-gateway-token" not in captured.out + captured.err


def test_create_refuses_when_the_gateway_token_does_not_resolve() -> None:
    """CN-5: fail closed - a configured gateway token that does not resolve
    means the pod's ComfyUI endpoint would be unreachable by the runner, so no
    pod may be created."""
    transport = ScriptedTransport(lambda *_: pytest.fail("create must be refused pre-POST"))
    provider = _provider(transport, comfy_token_provider=lambda: None)
    with pytest.raises(EffectDenied, match="gateway token did not resolve"):
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


def test_declared_http_port_exposes_the_endpoint_before_runtime_lags() -> None:
    """T031 run8 (2026-11-05): the proxy route exists from creation, but the
    pod API's runtime.ports mapping lagged by 8+ minutes (observed live while
    the proxy already answered 200) - the runner sat in warmup polling until
    its deadline. The declared create-time port ("8188/http", top-level on the
    v2 pod payload) is the contract the pod was created with: it must expose
    the deterministic proxy endpoint without waiting for runtime."""
    declared_only = _pod()
    declared_only["runtime"] = None
    declared_only["ports"] = ["8188/http"]

    def handler(method: str, url: str, _body: bytes | None) -> Response:
        if method == "POST":
            return _json(200, declared_only)
        if method == "GET" and url.endswith("/pods/pod-123"):
            return _json(200, declared_only)
        raise AssertionError(f"unexpected provider call: {method} {url}")

    provider = _provider(ScriptedTransport(handler))
    pod = provider.create_pod(_request())
    assert pod.endpoint_url == "https://pod-123-8188.proxy.runpod.net"


def test_reported_price_at_or_below_the_quote_ceiling_is_accepted() -> None:
    """T031 run5 (2026-11-05): the runtime price check demanded EXACT equality with
    the attested quote, but the quote must be a whole number of micro-USD per
    GPU-second (the ledger price rule), so a real $0.59/h rate (590,000) can never
    equal the smallest admissible ceiling above it (590,400). The quote is the
    operator's ceiling: a pod reporting at or below it must run; only exceeding it
    stops the pod."""
    pod = _pod(cost="0.590000")

    def handler(method: str, url: str, body: bytes | None) -> Response:
        if method == "POST":
            return _json(200, pod)
        if method == "GET" and url.endswith("/pods/pod-123"):
            return _json(200, pod)
        if method == "POST" and url.endswith("/pods/pod-123/action"):
            raise AssertionError("a pod at/below the ceiling must not be stopped")
        raise AssertionError(f"unexpected provider call: {method} {url}")

    provider = _provider(ScriptedTransport(handler))
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
    with pytest.raises(PolicyDenied, match="exceeds the operator quote"):
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
    from microdrama.rendering.finality import RunpodInvoiceFinality

    janitor = Janitor(
        db,
        budget=None,
        provider=provider,
        clock=FakeClock(NOW),
        ids=SequentialIds("runpod-janitor"),
        settings=settings,
        config=config,
        finality=RunpodInvoiceFinality(
            db,
            budget_service=BudgetService(
                db, FakeClock(NOW), SequentialIds("runpod-janitor"), settings
            ),
        ),
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


def test_billing_amounts_round_up_to_the_microcent_atom() -> None:
    """T031 (2026-11-05, post-run sweep): Runpod's live billing floats carry
    sub-microcent precision (pod xykul8kobl1e6s: gpuAmount
    0.03517432510852814, disk 0.0005787037080153823) and the parser demanded
    exact whole micro-USD, rejecting the real response as malformed and
    blocking the canary's settlement. The micro-USD is the ledger's atom.

    CN-1 (2026-11-09, canary-night review): half-up rounded every fractional
    atom below 0.5 µUSD DOWN, under-recording cost on each bucket. The house
    rule is conservative - never under-record - so amounts now round UP
    (ceiling); the run-14 observed gpuAmount 0.03517432510852814 USD is
    35174.325… µUSD and converts to 35_175, not 35_174."""
    from microdrama.rendering.runpod_transport import _amount_micro

    assert _amount_micro(0.03517432510852814) == 35_175  # CN-1: ceiling, was 35_174
    assert _amount_micro(0.0005787037080153823) == 579
    assert _amount_micro(0.0000014) == 2  # CN-1: 1.4 µUSD must not become 1
    assert _amount_micro(0) == 0
    assert _amount_micro("1.25") == 1_250_000
    with pytest.raises(ValueError):
        _amount_micro(-0.01)


def test_billing_fractional_buckets_accumulate_without_under_recording() -> None:
    """CN-1 (2026-11-09, canary-night review): a 24-sample canary run of
    fractional buckets must never under-record. With half-up totals each
    0.0000014-USD bucket recorded 1 µUSD instead of 1.4, leaking 0.4 µUSD per
    bucket (9.6 µUSD across the run) with no retained remainder."""
    from decimal import Decimal

    from microdrama.rendering.runpod_transport import _billing_record

    rows = [
        {
            "podId": "pod-123",
            "startTime": NOW.isoformat(),
            "endTime": (NOW + timedelta(hours=1)).isoformat(),
            "totalAmount": "0.0000014",
            "gpuAmount": "0.0000014",
            "cpuAmount": "0",
            "diskAmount": "0",
        }
        for _ in range(24)
    ]
    records = [_billing_record(row) for row in rows]
    exact_micro = Decimal("0.0000014") * 1_000_000 * 24
    # Every bucket records at least its exact amount, so the sum does too.
    for record in records:
        assert Decimal(record.total_micro_usd) >= Decimal("0.0000014") * 1_000_000
    assert Decimal(sum(record.total_micro_usd for record in records)) >= exact_micro


def test_billing_consistent_fractional_projection_is_not_disputed() -> None:
    """CN-1 (2026-11-09, canary-night review): GPU 0.6 µUSD + disk 0.6 µUSD
    with total 1.2 µUSD is consistent provider data. Independent per-field
    rounding manufactured GPU=1, disk=1, total=1 and a DISPUTED bucket that
    blocked invoice finalization; the consistency check must run on the exact
    provider Decimals before any rounding."""
    from microdrama.rendering.runpod_transport import _billing_record

    record = _billing_record(
        {
            "podId": "pod-123",
            "startTime": NOW.isoformat(),
            "endTime": (NOW + timedelta(hours=1)).isoformat(),
            "totalAmount": "0.0000012",
            "gpuAmount": "0.0000006",
            "cpuAmount": "0",
            "diskAmount": "0.0000006",
        }
    )
    assert record.raw_components_match
    atoms = (record.gpu_micro_usd, record.cpu_micro_usd, record.disk_micro_usd)
    assert sum(atoms) == record.total_micro_usd


@pytest.mark.parametrize(
    "total,gpu,cpu,disk,expected",
    [
        # CN-1 (2026-11-09): the total rounds UP (ceiling) and the floored
        # components are topped up by largest fractional remainder, ties to GPU.
        ("0.0357532", "0.0351746", "0", "0.0005786", (35175, 0, 579)),
        ("0.0000008", "0.0000004", "0", "0.0000004", (1, 0, 0)),
        ("0.0000015", "0.0000005", "0.0000005", "0.0000005", (1, 1, 0)),
        ("0.0000012", "0.0000004", "0.0000004", "0.0000004", (1, 1, 0)),
        ("0", "0", "0", "0", (0, 0, 0)),
        # CN-1 (2026-11-09): the run-14 observed amounts convert per the
        # ceiling rule - gpu 35174.325 µUSD tops up to 35175, disk 578.704 µUSD
        # to 579, totalling the ceiling of 35753.029 µUSD = 35754.
        (
            "0.03575302881654352",
            "0.03517432510852814",
            "0",
            "0.0005787037080153823",
            (35175, 0, 579),
        ),
        ("0.000001000001", "0.000001", "0", "0", (2, 0, 0)),
        ("0.000000999999", "0.000001", "0", "0", (1, 0, 0)),
    ],
)
def test_billing_allocation_conserves_total_and_raw_evidence(
    total: str,
    gpu: str,
    cpu: str,
    disk: str,
    expected: tuple[int, int, int],
) -> None:
    from microdrama.rendering.runpod_transport import _amount_micro, _billing_record

    record = _billing_record(
        {
            "podId": "pod-123",
            "startTime": NOW.isoformat(),
            "endTime": (NOW + timedelta(hours=1)).isoformat(),
            "totalAmount": total,
            "gpuAmount": gpu,
            "cpuAmount": cpu,
            "diskAmount": disk,
        }
    )
    atoms = (record.gpu_micro_usd, record.cpu_micro_usd, record.disk_micro_usd)
    assert atoms == expected
    assert sum(atoms) == record.total_micro_usd == _amount_micro(total)
    assert record.raw_amounts == (total, gpu, cpu, disk)
    assert record.raw_components_match
    assert "tolerance-usd=1e-12" in record.normalization_policy


@pytest.mark.parametrize("bad", ["NaN", "sNaN", "Infinity", "-Infinity", "-0.1", "bad"])
def test_billing_invalid_money_is_refused(bad: str) -> None:
    from decimal import InvalidOperation

    from microdrama.rendering.runpod_transport import _billing_record

    for field in ("totalAmount", "gpuAmount", "cpuAmount", "diskAmount"):
        row = {
            "podId": "p",
            "startTime": NOW.isoformat(),
            "endTime": (NOW + timedelta(hours=1)).isoformat(),
            "totalAmount": "0",
            "gpuAmount": "0",
            "cpuAmount": "0",
            "diskAmount": "0",
        }
        row[field] = bad
        with pytest.raises((ValueError, InvalidOperation)):
            _billing_record(row)


@pytest.mark.parametrize("total", ["0.0000010000011", "0.0000009999989", "0.1"])
def test_billing_real_mismatch_is_not_normalized(total: str) -> None:
    from microdrama.rendering.runpod_transport import _billing_record

    record = _billing_record(
        {
            "podId": "p",
            "startTime": NOW.isoformat(),
            "endTime": (NOW + timedelta(hours=1)).isoformat(),
            "totalAmount": total,
            "gpuAmount": "0.000001",
            "cpuAmount": "0",
            "diskAmount": "0",
        }
    )
    assert not record.raw_components_match
    assert record.gpu_micro_usd == 1


def test_billing_tolerance_crossing_an_integer_boundary_conserves_the_ceiling() -> None:
    """CN2-1 (2026-11-10, re-review round 2): the discrepancy 4e-13 USD is inside
    the declared 1e-12 tolerance, but the ceiling total is 4 micro-USD while all
    three component floors are zero. The old single-pass top-up visited each
    component once, produced a sum of 3 and raised AssertionError - aborting
    billing ingestion instead of reaching settlement. The whole residual must be
    allocated deterministically (cycling largest-fractional-remainder order, ties
    GPU > CPU > disk), with no assert backing the money path."""
    from microdrama.rendering.runpod_transport import _amount_micro, _billing_record

    row = {
        "podId": "p",
        "startTime": NOW.isoformat(),
        "endTime": (NOW + timedelta(hours=1)).isoformat(),
        "totalAmount": "0.0000030000001",
        "gpuAmount": "0.0000009999999",
        "cpuAmount": "0.0000009999999",
        "diskAmount": "0.0000009999999",
    }
    record = _billing_record(row)
    assert _amount_micro("0.0000030000001") == 4
    assert record.raw_components_match
    assert (
        record.gpu_micro_usd,
        record.cpu_micro_usd,
        record.disk_micro_usd,
    ) == (2, 1, 1)
    assert (
        record.gpu_micro_usd + record.cpu_micro_usd + record.disk_micro_usd
        == record.total_micro_usd
        == 4
    )


def test_billing_residual_allocation_conserves_the_ceiling_for_every_case() -> None:
    """CN2-1: property-style conservation. For every tolerated combination the
    component atoms sum to exactly the ceiling total - never more (a fake
    dispute), never less (an under-recorded leak)."""
    from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

    from microdrama.rendering.runpod_transport import _BILLING_TOLERANCE_USD, _billing_record

    tolerance = _BILLING_TOLERANCE_USD
    grid = [Decimal("0.00000") + Decimal(i) * Decimal("0.0000004") for i in range(0, 13)]
    checked = 0
    for total in grid:
        for gpu in grid:
            for cpu in grid:
                disk_exact = total - gpu - cpu
                if disk_exact < 0:
                    continue
                # Split tolerated noise across the fields so the exact Decimals
                # stay consistent within the declared tolerance.
                noise = tolerance / Decimal(4)
                fields = (total + noise, gpu - noise / 2, cpu - noise / 4, disk_exact - noise / 4)
                if any(value < 0 for value in fields):
                    continue
                row = {
                    "podId": "p",
                    "startTime": NOW.isoformat(),
                    "endTime": (NOW + timedelta(hours=1)).isoformat(),
                    "totalAmount": str(fields[0]),
                    "gpuAmount": str(fields[1]),
                    "cpuAmount": str(fields[2]),
                    "diskAmount": str(fields[3]),
                }
                record = _billing_record(row)
                assert record.raw_components_match
                expected_total = int(
                    (fields[0] * Decimal(1_000_000)).to_integral_value(rounding=ROUND_CEILING)
                )
                assert record.total_micro_usd == expected_total
                assert (
                    record.gpu_micro_usd + record.cpu_micro_usd + record.disk_micro_usd
                    == record.total_micro_usd
                )
                # Never under-record a component relative to its exact amount.
                for amount, atom in zip(
                    fields[1:], (record.gpu_micro_usd, record.cpu_micro_usd, record.disk_micro_usd)
                ):
                    exact_atom = (amount * Decimal(1_000_000)).to_integral_value(
                        rounding=ROUND_FLOOR
                    )
                    assert atom >= exact_atom
                checked += 1
    assert checked > 200  # a genuine grid, not a handful of hand-picked cases


def test_billing_boundary_noise_needs_a_negative_residual_and_still_conserves() -> None:
    """CN2-1: tolerated noise the other side of the boundary - components whose
    floors already exceed the ceiling total - must remove atoms deterministically
    and still conserve, again without an assert on the money path."""
    from microdrama.rendering.runpod_transport import _billing_record

    row = {
        "podId": "p",
        "startTime": NOW.isoformat(),
        "endTime": (NOW + timedelta(hours=1)).isoformat(),
        # total 2.9999999999996 micro-USD -> ceiling 3; components floor to 1 each.
        "totalAmount": "0.0000029999999999996",
        "gpuAmount": "0.0000010000000000001",
        "cpuAmount": "0.0000010000000000001",
        "diskAmount": "0.0000009999999999996",
    }
    record = _billing_record(row)
    assert record.raw_components_match
    assert record.total_micro_usd == 3
    assert (
        record.gpu_micro_usd + record.cpu_micro_usd + record.disk_micro_usd
        == record.total_micro_usd
    )


@pytest.mark.parametrize(
    "body",
    [
        b"GPU A40 unavailable; reflected fixture-secret",
        b'{"aUtHoRiZaTiOn": "bEaReR synthetic-other-secret", "detail": "GPU unavailable"}',
        b"X-Api-Key: synthetic-other-secret\nGPU unavailable",
    ],
)
def test_runpod_error_redacts_credentials_preserves_gpu(body: bytes) -> None:
    provider = _provider(ScriptedTransport(lambda *_: Response(401, body)))
    with pytest.raises(ProviderError) as caught:
        provider._call("GET", "/pods")
    message = str(caught.value)
    assert "fixture-secret" not in message
    assert "synthetic-other-secret" not in message
    assert "GPU" in message
    assert len(message) < 600


def test_runpod_error_body_read_and_uncertain_cause_are_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io
    import traceback

    from microdrama.rendering import runpod_transport as rt
    from microdrama.rendering.diagnostics import DIAGNOSTIC_READ_LIMIT

    class BoundedBody(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            assert size == DIAGNOSTIC_READ_LIMIT
            return super().read(size)

    def refuses(*args: Any, **kwargs: Any) -> Any:
        raise rt.HTTPError(
            "https://runpod.invalid",
            401,
            "no",
            {},
            BoundedBody(b"GPU unavailable\nAuthorization: Bearer hidden-token\n" + b"x" * 10000),
        )

    monkeypatch.setattr(rt, "urlopen", refuses)
    response = rt.UrllibRunpodTransport().request("GET", "https://runpod.invalid", headers={})
    assert len(response.body) <= 500
    assert b"hidden-token" not in response.body
    assert b"GPU unavailable" in response.body

    def uncertain(*args: Any, **kwargs: Any) -> Any:
        raise rt.URLError("fixture-secret connection reset; Authorization: Bearer hidden-token")

    monkeypatch.setattr(rt, "urlopen", uncertain)
    headers = {"Authorization": "Bearer fixture-secret"}
    with pytest.raises(NeedsReconciliation) as caught:
        rt.UrllibRunpodTransport().request("POST", "https://runpod.invalid", headers=headers)
    rendered = "".join(traceback.format_exception(caught.value))
    assert "fixture-secret" not in rendered and "hidden-token" not in rendered
    # CN-3 (2026-11-09): the cause is the exception type plus a sanitised
    # category; the raw exception text never reaches the message or traceback.
    assert "URLError/transport-error" in str(caught.value)
    assert "connection reset" not in str(caught.value)
    assert "connection reset" not in rendered


@pytest.mark.parametrize(
    "sensitive",
    [
        "Cookie: theme=dark; sessionid=synthetic-session-secret",
        "Authorization: Bearer\n synthetic-continuation-secret",
        '"Authorization": "Bearer synthetic-prefix,synthetic-secret-tail"',
        '"Authorization": "Bearer synthetic-prefix;synthetic-secret-tail"',
    ],
)
@pytest.mark.parametrize("uncertain", [False, True])
def test_complete_unknown_sensitive_values_are_redacted(
    monkeypatch: pytest.MonkeyPatch,
    sensitive: str,
    uncertain: bool,
) -> None:
    import io
    import traceback

    from microdrama.rendering import runpod_transport as transport_module

    # No reflected value is present in request headers or the credential resolver.
    body = ("GPU unavailable\n" + sensitive + '\n{"detail":"schema mismatch"}').encode()

    def fails(*args: Any, **kwargs: Any) -> Any:
        if uncertain:
            raise transport_module.URLError(body.decode())
        raise transport_module.HTTPError(
            "https://provider.invalid", 401, "no", {}, io.BytesIO(body)
        )

    monkeypatch.setattr(transport_module, "urlopen", fails)
    expected = NeedsReconciliation if uncertain else ProviderError
    with pytest.raises(expected) as caught:
        _provider(transport_module.UrllibRunpodTransport())._call("POST", "/pods")
    rendered = "".join(traceback.format_exception(caught.value))
    for marker in (
        "synthetic-session-secret",
        "synthetic-continuation-secret",
        "synthetic-prefix",
        "synthetic-secret-tail",
    ):
        assert marker not in rendered
    if uncertain:
        # CN-3 (2026-11-09): an uncertainty cause is the exception type plus a
        # sanitised category only - never sanitized-but-raw body text.
        assert "URLError/transport-error" in str(caught.value)
    else:
        assert "GPU unavailable" in str(caught.value)
        assert "schema mismatch" in str(caught.value)
