"""Acquisition filters, verification, stop discipline and the disabled live adapter.

No database: these pin the typed blocks and provider-call discipline in isolation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode, PodState, PriceUnit, Provenance
from microdrama.contracts.errors import (
    Conflict,
    EffectDenied,
    NeedsReconciliation,
    PolicyDenied,
    TransientProviderError,
    UnknownPrice,
)
from microdrama.contracts.providers import PodCreateRequest
from microdrama.rendering import (
    PodLeaseConfig,
    PodManager,
    PodSpec,
    RunpodLiveAdapter,
    check_acquisition_filters,
    mock_pod_price,
    resolve_pod_provider,
)
from microdrama.testing.fakes import (
    FakeClock,
    FakePodProvider,
    PodCreateScenario,
    PodStopScenario,
    SequentialIds,
)
from microdrama.testing.fakes.pods import FAKE_GPU_TYPE

T0 = datetime(2026, 10, 20, tzinfo=UTC)
OWNED = "microdrama-owned:mock"


def _config() -> PodLeaseConfig:
    return PodLeaseConfig.for_mock()


def _spec(
    *,
    gpu: str = FAKE_GPU_TYPE,
    ram: int = 32,
    cap: int = 900_000,
) -> PodSpec:
    return PodSpec(
        gpu_type_allowlist=(gpu,),
        max_hourly_price_micro_usd=cap,
        min_host_ram_gb=ram,
        container_image="registry.invalid/render@sha256:" + "b" * 64,
    )


def _manager(provider: FakePodProvider, config: PodLeaseConfig | None = None) -> PodManager:
    return PodManager(provider, provider.clock, config or _config())


def _provider(*steps: object) -> FakePodProvider:
    return FakePodProvider(clock=FakeClock(T0), ids=SequentialIds("pods"), scenarios=tuple(steps))  # type: ignore[arg-type]


def _request(token: str = "pod-1") -> PodCreateRequest:
    return PodCreateRequest(
        client_token=token,
        name="render",
        owned_tag=OWNED,
        gpu_type_allowlist=[FAKE_GPU_TYPE],
        max_hourly_price_micro_usd=900_000,
        min_host_ram_gb=32,
        container_image="registry.invalid/render@sha256:" + "b" * 64,
    )


# --- acquisition filters (typed blocks, no dispatch) -------------------------------------------


def test_unknown_price_blocks_dispatch_before_any_call() -> None:
    provider = _provider()
    with pytest.raises(UnknownPrice):
        check_acquisition_filters(
            _spec(), allowed_gpu_types=frozenset({FAKE_GPU_TYPE}), min_host_ram_gb=32, price=None
        )
    assert provider.calls == []


def test_non_usd_price_blocks_dispatch() -> None:
    price = mock_pod_price().model_copy(update={"currency": "THB"})
    with pytest.raises(UnknownPrice):
        check_acquisition_filters(
            _spec(), allowed_gpu_types=frozenset({FAKE_GPU_TYPE}), min_host_ram_gb=32, price=price
        )


def test_zero_price_is_not_a_known_price() -> None:
    price = mock_pod_price().model_copy(update={"unit_price_micro_usd": 0})
    with pytest.raises(UnknownPrice):
        check_acquisition_filters(
            _spec(), allowed_gpu_types=frozenset({FAKE_GPU_TYPE}), min_host_ram_gb=32, price=price
        )


def test_hardware_outside_allowlist_blocks_dispatch() -> None:
    with pytest.raises(PolicyDenied) as exc:
        check_acquisition_filters(
            _spec(gpu="RTX-UNLISTED"),
            allowed_gpu_types=frozenset({FAKE_GPU_TYPE}),
            min_host_ram_gb=32,
            price=mock_pod_price(),
        )
    assert "hardware" in str(exc.value.message)
    assert exc.value.details["requested"] == ["RTX-UNLISTED"]


def test_ram_below_floor_blocks_dispatch() -> None:
    with pytest.raises(PolicyDenied) as exc:
        check_acquisition_filters(
            _spec(ram=16),
            allowed_gpu_types=frozenset({FAKE_GPU_TYPE}),
            min_host_ram_gb=32,
            price=mock_pod_price(),
        )
    assert exc.value.details["floor_gb"] == 32


def test_price_cap_must_be_positive() -> None:
    with pytest.raises(UnknownPrice):
        check_acquisition_filters(
            _spec(cap=0),
            allowed_gpu_types=frozenset({FAKE_GPU_TYPE}),
            min_host_ram_gb=32,
            price=mock_pod_price(),
        )


# --- reconcile-before-retry discipline ---------------------------------------------------------


def test_reconcile_by_token_only_sees_owned_pods() -> None:
    provider = _provider()
    manager = _manager(provider)
    pod = provider.create_pod(_request("token-a"))
    provider.create_pod(_request("token-b").model_copy(update={"owned_tag": "other-team:farm"}))
    found = manager.reconcile_by_token("token-a")
    assert found is not None and found.pod_id == pod.pod_id
    assert manager.reconcile_by_token("token-b") is None  # foreign tag: invisible
    assert manager.reconcile_by_token("never-created") is None


def test_reconcile_by_token_refuses_ambiguous_duplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider()
    manager = _manager(provider)
    pod = provider.create_pod(_request("dup"))

    def _two(*args: object, **kwargs: object):
        return [pod, pod]

    monkeypatch.setattr(provider, "find_pods", _two)
    with pytest.raises(Conflict) as exc:
        manager.reconcile_by_token("dup")
    assert "multiple pods" in str(exc.value.message)


def test_ambiguous_create_that_created_adopts_without_second_create() -> None:
    provider = _provider(PodCreateScenario.CREATE_TIMEOUT_BUT_CREATED)
    manager = _manager(provider)
    pod = manager.acquire_or_reconcile(_spec(), name="render", client_token="t-adopt")
    assert pod.pod_id.startswith("fake-pod-")
    creates = [c for c in provider.calls if c.method == "create_pod"]
    assert len(creates) == 1  # no blind re-create: reconciliation adopted it
    assert len(manager.find_owned()) == 1


def test_ambiguous_create_that_did_not_create_retries_same_token() -> None:
    provider = _provider(PodCreateScenario.CREATE_TIMEOUT_NOT_CREATED)
    manager = _manager(provider)
    pod = manager.acquire_or_reconcile(_spec(), name="render", client_token="t-retry")
    assert pod.client_token == "t-retry"
    creates = [c for c in provider.calls if c.method == "create_pod"]
    assert len(creates) == 2  # one ambiguous attempt, one retry after reconcile found nothing
    assert len(manager.find_owned()) == 1


def test_persistently_ambiguous_create_stays_needs_reconciliation() -> None:
    provider = _provider(
        PodCreateScenario.CREATE_TIMEOUT_NOT_CREATED,
        PodCreateScenario.CREATE_TIMEOUT_NOT_CREATED,
        PodCreateScenario.CREATE_TIMEOUT_NOT_CREATED,
    )
    manager = _manager(provider)
    with pytest.raises(NeedsReconciliation):
        manager.acquire_or_reconcile(_spec(), name="render", client_token="t-stuck")
    creates = [c for c in provider.calls if c.method == "create_pod"]
    assert len(creates) == 2  # bounded attempts, then an honest ambiguous outcome


# --- verification --------------------------------------------------------------------------------


def test_verify_rejects_foreign_tag_price_hardware_and_state() -> None:
    provider = _provider()
    manager = _manager(provider)
    settings = Settings(execution_mode=ExecutionMode.OFFLINE_MOCK)
    pod = provider.create_pod(_request("v1"))

    bad_tag = pod.model_copy(update={"owned_tag": "someone-else"})
    with pytest.raises(PolicyDenied):
        manager.verify(bad_tag, _spec(), settings=settings)

    bad_price = pod.model_copy(update={"hourly_price_micro_usd": 900_001})
    with pytest.raises(PolicyDenied):
        manager.verify(bad_price, _spec(), settings=settings)

    bad_gpu = pod.model_copy(update={"gpu_type": "MYSTERY-GPU"})
    with pytest.raises(PolicyDenied):
        manager.verify(bad_gpu, _spec(), settings=settings)

    stopped = pod.model_copy(update={"state": PodState.STOPPED})
    with pytest.raises(Conflict):
        manager.verify(stopped, _spec(), settings=settings)

    unknown = pod.model_copy(update={"state": PodState.UNKNOWN})
    with pytest.raises(NeedsReconciliation):
        manager.verify(unknown, _spec(), settings=settings)

    no_endpoint = pod.model_copy(update={"endpoint_url": None})
    with pytest.raises(Conflict):
        manager.verify(no_endpoint, _spec(), settings=settings)


def test_verify_separates_mock_and_live_provenance() -> None:
    provider = _provider()
    manager = _manager(provider)
    pod = provider.create_pod(_request("v2"))
    live_pod = pod.model_copy(update={"provenance": Provenance.LIVE_PROVIDER})
    with pytest.raises(PolicyDenied):
        manager.verify(
            live_pod, _spec(), settings=Settings(execution_mode=ExecutionMode.OFFLINE_MOCK)
        )
    paid = Settings(execution_mode=ExecutionMode.PAID_BENCHMARK)
    with pytest.raises(PolicyDenied):
        manager.verify(pod, _spec(), settings=paid)  # fake pod refused outside mock
    assert manager.verify(live_pod, _spec(), settings=paid) is live_pod


# --- stop discipline -----------------------------------------------------------------------------


def test_stop_verifies_terminal_state_by_rereading() -> None:
    provider = _provider()
    manager = _manager(provider)
    pod = provider.create_pod(_request("s1"))
    state = manager.stop(pod.pod_id)
    assert state is PodState.STOPPED
    assert provider.get_pod(pod.pod_id).state is PodState.STOPPED  # type: ignore[union-attr]


def test_stop_retries_transient_failure_then_succeeds() -> None:
    provider = _provider()
    manager = _manager(provider)
    pod = provider.create_pod(_request("s2"))
    provider.queue_scenarios(PodStopScenario.STOP_FAILS_ONCE)
    assert manager.stop(pod.pod_id) is PodState.STOPPED


def test_stop_escalates_to_terminate_when_stop_keeps_failing() -> None:
    provider = _provider()
    manager = _manager(provider)
    pod = provider.create_pod(_request("s3"))
    provider.queue_scenarios(PodStopScenario.STOP_FAILS_ONCE, PodStopScenario.STOP_FAILS_ONCE)
    assert manager.stop(pod.pod_id) is PodState.TERMINATED
    assert provider.get_pod(pod.pod_id).state is PodState.TERMINATED  # type: ignore[union-attr]


def test_stop_reports_failure_when_stop_and_terminate_both_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()
    manager = _manager(provider)
    pod = provider.create_pod(_request("s4"))

    def _always_fails(pod_id: str) -> object:
        raise TransientProviderError("nope", pod_id=pod_id)

    monkeypatch.setattr(provider, "stop_pod", _always_fails)
    monkeypatch.setattr(provider, "terminate_pod", _always_fails)
    with pytest.raises(TransientProviderError):
        manager.stop(pod.pod_id)
    assert provider.get_pod(pod.pod_id).state is PodState.RUNNING  # type: ignore[union-attr]


# --- the structurally disabled live adapter ------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "credref"),
    [
        (ExecutionMode.OFFLINE_MOCK, None),
        (ExecutionMode.OFFLINE_MOCK, "credref:runpod-main"),
        (ExecutionMode.PAID_BENCHMARK, None),
        (ExecutionMode.PRODUCTION, "credref:runpod-main"),
    ],
)
def test_live_adapter_is_structurally_disabled(mode: ExecutionMode, credref: str | None) -> None:
    settings = Settings(execution_mode=mode)
    adapter = RunpodLiveAdapter(settings, credential_ref=credref)
    for call in (
        lambda: adapter.create_pod(_request()),
        lambda: adapter.get_pod("x"),
        lambda: adapter.find_pods(),
        lambda: adapter.stop_pod("x"),
        lambda: adapter.terminate_pod("x"),
        lambda: adapter.usage("x", since=T0, until=T0 + timedelta(seconds=1)),
    ):
        with pytest.raises(EffectDenied):
            call()


def test_resolve_pod_provider_reads_the_credential_reference_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(execution_mode=ExecutionMode.OFFLINE_MOCK)
    monkeypatch.delenv("MICRODRAMA_RUNPOD_CREDREF", raising=False)
    adapter = resolve_pod_provider(settings)
    assert isinstance(adapter, RunpodLiveAdapter)
    with pytest.raises(EffectDenied):
        adapter.find_pods()
    monkeypatch.setenv("MICRODRAMA_RUNPOD_CREDREF", "credref:runpod-main")
    enabled = resolve_pod_provider(settings)
    with pytest.raises(EffectDenied):  # still disabled: not implemented before T031
        enabled.find_pods()


def test_mock_price_matches_the_fake_pod_billing() -> None:
    price = mock_pod_price()
    assert price.unit is PriceUnit.GPU_SECOND
    assert price.unit_price_micro_usd * 3600 == 900_000
