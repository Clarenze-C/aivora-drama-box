"""GPU pod fake: idempotent create, reconciliation, janitor scope, billing arithmetic."""

from __future__ import annotations

from datetime import timedelta

import pytest

from microdrama.contracts.enums import PodState, ReceiptKind
from microdrama.contracts.errors import (
    NeedsReconciliation,
    PolicyDenied,
    SchemaInvalid,
    TransientProviderError,
)
from microdrama.contracts.providers import PodCreateRequest, PodProvider
from microdrama.testing.fakes import (
    FakeClock,
    FakePodProvider,
    PodCreateScenario,
    PodStopScenario,
    SequentialIds,
)
from microdrama.testing.fakes.pods import FAKE_POD_HOURLY_MICRO_USD, LATE_EXTRA_MS

OWNED = "microdrama-owned:env-test"


def _request(token: str = "lease-1-create", cap: int = 900_000) -> PodCreateRequest:
    return PodCreateRequest(
        client_token=token,
        name="render-sh1",
        owned_tag=OWNED,
        gpu_type_allowlist=["FAKE-GPU-24GB"],
        max_hourly_price_micro_usd=cap,
        min_host_ram_gb=32,
        container_image="registry.fake.invalid/render@sha256:" + "a" * 64,
    )


def _pods(clock: FakeClock, ids: SequentialIds, *steps: object) -> FakePodProvider:
    return FakePodProvider(clock=clock, ids=ids, scenarios=tuple(steps))  # type: ignore[arg-type]


def _janitor(provider: FakePodProvider, owned_tag: str) -> list[str]:
    """Stop only pods the pipeline owns, exactly as the independent janitor must."""
    stopped = []
    for pod in provider.find_pods(owned_tag=owned_tag):
        provider.stop_pod(pod.pod_id)
        stopped.append(pod.pod_id)
    return stopped


def test_fake_satisfies_pod_protocol(clock: FakeClock, ids: SequentialIds) -> None:
    assert isinstance(_pods(clock, ids), PodProvider)


def test_create_is_idempotent_by_client_token(clock: FakeClock, ids: SequentialIds) -> None:
    provider = _pods(clock, ids)
    first = provider.create_pod(_request())
    second = provider.create_pod(_request())
    assert first == second
    assert len(provider.find_pods(client_token="lease-1-create")) == 1


def test_pods_carry_invalid_tld_endpoints(clock: FakeClock, ids: SequentialIds) -> None:
    pod = _pods(clock, ids).create_pod(_request())
    assert pod.endpoint_url is not None
    assert pod.endpoint_url.startswith("https://") and ".invalid/" in pod.endpoint_url
    assert pod.provenance.value == "FAKE_SYNTHETIC"


def test_janitor_scope_never_touches_foreign_pods(clock: FakeClock, ids: SequentialIds) -> None:
    provider = _pods(clock, ids)
    provider.create_pod(_request("lease-a"))
    provider.create_pod(_request("lease-b"))
    stopped = _janitor(provider, OWNED)
    assert len(stopped) == 2
    assert provider.foreign_touches == []
    foreign = {p.pod_id: p for p in provider.find_pods() if p.owned_tag != OWNED}
    assert set(foreign) == {"foreign-pod-0001", "foreign-pod-0002"}
    assert all(p.state is PodState.RUNNING for p in foreign.values())


def test_a_wrong_janitor_is_caught_by_the_foreign_touch_record(
    clock: FakeClock, ids: SequentialIds
) -> None:
    provider = _pods(clock, ids)
    provider.stop_pod("foreign-pod-0001")  # what a broken janitor would do
    assert provider.foreign_touches == ["foreign-pod-0001"]


def test_create_timeout_that_created_is_found_by_token_and_not_duplicated(
    clock: FakeClock, ids: SequentialIds
) -> None:
    provider = _pods(clock, ids, PodCreateScenario.CREATE_TIMEOUT_BUT_CREATED)
    with pytest.raises(NeedsReconciliation):
        provider.create_pod(_request("lease-timeout"))
    found = provider.find_pods(client_token="lease-timeout")
    assert len(found) == 1
    assert provider.create_pod(_request("lease-timeout")).pod_id == found[0].pod_id
    assert len(provider.find_pods(client_token="lease-timeout")) == 1


def test_create_timeout_that_did_not_create_leaves_nothing_behind(
    clock: FakeClock, ids: SequentialIds
) -> None:
    provider = _pods(clock, ids, PodCreateScenario.CREATE_TIMEOUT_NOT_CREATED)
    with pytest.raises(NeedsReconciliation):
        provider.create_pod(_request("lease-gone"))
    assert provider.find_pods(client_token="lease-gone") == []
    assert provider.create_pod(_request("lease-gone")).client_token == "lease-gone"


def test_no_capacity_is_transient(clock: FakeClock, ids: SequentialIds) -> None:
    provider = _pods(clock, ids, PodCreateScenario.NO_CAPACITY)
    with pytest.raises(TransientProviderError):
        provider.create_pod(_request("lease-cap"))
    assert provider.find_pods(client_token="lease-cap") == []


def test_price_cap_below_offer_is_denied_before_creation(
    clock: FakeClock, ids: SequentialIds
) -> None:
    provider = _pods(clock, ids)
    with pytest.raises(PolicyDenied):
        provider.create_pod(_request("lease-cheap", cap=FAKE_POD_HOURLY_MICRO_USD - 1))
    assert provider.find_pods(client_token="lease-cheap") == []


def test_first_stop_fails_then_retry_succeeds(clock: FakeClock, ids: SequentialIds) -> None:
    provider = _pods(clock, ids)
    pod = provider.create_pod(_request("lease-stop"))
    provider.queue_scenarios(PodStopScenario.STOP_FAILS_ONCE)
    with pytest.raises(TransientProviderError):
        provider.stop_pod(pod.pod_id)
    assert provider.get_pod(pod.pod_id).state is PodState.RUNNING  # type: ignore[union-attr]
    assert provider.stop_pod(pod.pod_id).state is PodState.STOPPED


def test_usage_rounds_up_to_whole_micro_usd_in_integer_arithmetic(
    clock: FakeClock, ids: SequentialIds
) -> None:
    provider = _pods(clock, ids)
    pod = provider.create_pod(_request("lease-usage"))
    one_minute = provider.usage(
        pod.pod_id, since=clock.now(), until=clock.now() + timedelta(minutes=1)
    )
    assert len(one_minute) == 1
    assert one_minute[0].units == 60
    assert one_minute[0].amount_micro_usd == 15_000  # 900_000 micro/h for 60 s
    one_ms = provider.usage(
        pod.pod_id, since=clock.now(), until=clock.now() + timedelta(milliseconds=1)
    )
    assert one_ms[0].amount_micro_usd == 1  # ceil(900_000 / 3_600_000) rounds up to 1
    assert one_ms[0].units == 1


def test_usage_is_clamped_to_pod_lifetime_and_ledger_dedupes_repeats(
    clock: FakeClock, ids: SequentialIds
) -> None:
    provider = _pods(clock, ids)
    pod = provider.create_pod(_request("lease-clamp"))
    since = clock.now() - timedelta(hours=1)  # before the pod existed
    until = clock.now() + timedelta(seconds=30)
    first = provider.usage(pod.pod_id, since=since, until=until)
    again = provider.usage(pod.pod_id, since=since, until=until)
    assert first == again
    assert first[0].interval_start == clock.now()
    assert first[0].units == 30
    assert len(provider.ledger) == 1


def test_late_billing_adds_an_adjustment_on_the_next_usage_call(
    clock: FakeClock, ids: SequentialIds
) -> None:
    provider = _pods(clock, ids, PodCreateScenario.LATE_BILLING)
    pod = provider.create_pod(_request("lease-late"))
    clock.advance(seconds=120)  # run for two minutes before stopping
    provider.stop_pod(pod.pod_id)
    stopped_at = clock.now()
    first = provider.usage(
        pod.pod_id, since=stopped_at - timedelta(minutes=1), until=stopped_at + timedelta(minutes=5)
    )
    assert {r.kind for r in first} == {ReceiptKind.ACCRUAL}
    second = provider.usage(
        pod.pod_id, since=stopped_at - timedelta(minutes=1), until=stopped_at + timedelta(minutes=5)
    )
    adjustments = [r for r in second if r.kind is ReceiptKind.ADJUSTMENT]
    assert len(adjustments) == 1
    assert adjustments[0].amount_micro_usd == -(
        -FAKE_POD_HOURLY_MICRO_USD * LATE_EXTRA_MS // 3_600_000
    )
    assert adjustments[0].interval_start == stopped_at
    assert (
        provider.usage(pod.pod_id, since=stopped_at - timedelta(minutes=1), until=stopped_at) != []
    )
    assert sum(1 for r in provider.ledger if r.kind is ReceiptKind.ADJUSTMENT) == 1


def test_invalid_usage_interval_is_rejected(clock: FakeClock, ids: SequentialIds) -> None:
    provider = _pods(clock, ids)
    pod = provider.create_pod(_request("lease-bad"))
    with pytest.raises(SchemaInvalid):
        provider.usage(pod.pod_id, since=clock.now(), until=clock.now())
