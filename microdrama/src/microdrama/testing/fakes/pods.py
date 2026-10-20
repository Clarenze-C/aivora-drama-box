"""Fake GPU pod provider (T007).

Pods carry the pipeline's ``owned_tag``; ``find_pods(owned_tag=...)`` is how the janitor
finds only pipeline-owned resources. The fake also pre-seeds FOREIGN pods (another team's tag,
and an untagged one). Any stop or terminate of a foreign pod is recorded in
``foreign_touches`` so tests can assert the janitor never touched them.

Billing: ``usage`` reports ACCRUAL receipts in GPU seconds. Amount is integer micro-USD computed as
``ceil(hourly_price_micro_usd * duration_ms / 3_600_000)`` (rounded UP to whole micro-USD); units
are ``ceil(duration_ms / 1000)`` GPU seconds. The clamped interval is [max(since, created),
min(until, stopped or until)].

Scenarios:
- create: CREATE_TIMEOUT_BUT_CREATED (pod exists; NeedsReconciliation), CREATE_TIMEOUT_NOT_CREATED
  (nothing exists; NeedsReconciliation), NO_CAPACITY (TransientProviderError), LATE_BILLING (the
  next usage call also reports an ADJUSTMENT for 60 s of unseen runtime).
- stop: STOP_FAILS_ONCE (the first stop raises TransientProviderError).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, ClassVar

from microdrama.contracts.cost import UsageReceipt
from microdrama.contracts.enums import (
    BudgetCategory,
    PodState,
    PriceUnit,
    Provenance,
    ReceiptKind,
)
from microdrama.contracts.errors import (
    NeedsReconciliation,
    NotFound,
    PolicyDenied,
    SchemaInvalid,
    TransientProviderError,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.providers import PodCreateRequest, PodInfo
from microdrama.testing.fakes.common import (
    CallRecord,
    FakeBase,
    FakeClock,
    ScenarioQueue,
    SequentialIds,
    fake_https,
    synthetic_receipt,
)

PROVIDER_ID = "fake-runpod"
FAKE_POD_HOURLY_MICRO_USD = 900_000  # 250 micro-USD per GPU second
FAKE_GPU_TYPE = "FAKE-GPU-24GB"
LATE_EXTRA_MS = 60_000
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class PodCreateScenario(StrEnum):
    HAPPY = "HAPPY"
    CREATE_TIMEOUT_BUT_CREATED = "CREATE_TIMEOUT_BUT_CREATED"
    CREATE_TIMEOUT_NOT_CREATED = "CREATE_TIMEOUT_NOT_CREATED"
    NO_CAPACITY = "NO_CAPACITY"
    LATE_BILLING = "LATE_BILLING"


class PodStopScenario(StrEnum):
    HAPPY = "HAPPY"
    STOP_FAILS_ONCE = "STOP_FAILS_ONCE"


@dataclass(frozen=True)
class ForeignPodSeed:
    pod_id: str
    name: str
    owned_tag: str | None
    gpu_type: str = FAKE_GPU_TYPE
    hourly_price_micro_usd: int = FAKE_POD_HOURLY_MICRO_USD


DEFAULT_FOREIGN_PODS = (
    ForeignPodSeed("foreign-pod-0001", "customer-render-farm", "other-team:render-farm"),
    ForeignPodSeed("foreign-pod-0002", "untagged-experiment", None),
)


@dataclass
class _Pod:
    pod_id: str
    name: str
    owned_tag: str | None
    client_token: str | None
    gpu_type: str
    hourly_price_micro_usd: int
    created_at: datetime
    endpoint_url: str
    pipeline_owned: bool
    state: PodState = PodState.RUNNING
    stopped_at: datetime | None = None
    late_billing: bool = False
    late_pending: bool = False
    late_emitted: bool = False


def _ms_between(start: datetime, end: datetime) -> int:
    return (end - start) // timedelta(milliseconds=1)


def _epoch_ms(instant: datetime) -> int:
    return (instant - _EPOCH) // timedelta(milliseconds=1)


class FakePodProvider(FakeBase):
    provider_id: str = PROVIDER_ID
    default_scenario: ClassVar[PodCreateScenario] = PodCreateScenario.HAPPY

    def __init__(
        self,
        *,
        clock: FakeClock,
        ids: SequentialIds,
        foreign_pods: tuple[ForeignPodSeed, ...] = DEFAULT_FOREIGN_PODS,
        scenarios: tuple[PodCreateScenario, ...] = (),
    ) -> None:
        super().__init__(clock=clock, ids=ids, scenarios=())
        self._create_steps = ScenarioQueue(PodCreateScenario.HAPPY, scenarios)
        self._stop_steps = ScenarioQueue(PodStopScenario.HAPPY)
        self._pods: dict[str, _Pod] = {}
        self._counter = 0
        self.foreign_touches: list[str] = []
        for seed in foreign_pods:
            self._pods[seed.pod_id] = _Pod(
                pod_id=seed.pod_id,
                name=seed.name,
                owned_tag=seed.owned_tag,
                client_token=None,
                gpu_type=seed.gpu_type,
                hourly_price_micro_usd=seed.hourly_price_micro_usd,
                created_at=clock.now(),
                endpoint_url=fake_https(f"{seed.pod_id}.pods.fake", ""),
                pipeline_owned=False,
            )

    def queue_scenarios(self, *steps: Any) -> None:
        for step in steps:
            if isinstance(step, PodStopScenario):
                self._stop_steps.push(step)
            else:
                self._create_steps.push(step)

    def _info(self, pod: _Pod) -> PodInfo:
        return PodInfo(
            pod_id=pod.pod_id,
            name=pod.name,
            owned_tag=pod.owned_tag,
            client_token=pod.client_token,
            state=pod.state,
            gpu_type=pod.gpu_type,
            hourly_price_micro_usd=pod.hourly_price_micro_usd,
            created_at=pod.created_at,
            endpoint_url=pod.endpoint_url,
            provenance=Provenance.FAKE_SYNTHETIC,
        )

    def _record(self, method: str, step: str, key: str = "") -> None:
        self.calls.append(CallRecord(method=method, scenario=step, key=key))

    def create_pod(self, request: PodCreateRequest) -> PodInfo:
        for pod in self._pods.values():
            if pod.pipeline_owned and pod.client_token == request.client_token:
                self._log_replay("create_pod", request.client_token)
                return self._info(pod)
        step = self._create_steps.next()
        self._record("create_pod", step.value, request.client_token)
        if step is PodCreateScenario.NO_CAPACITY:
            raise TransientProviderError(
                "fake pod capacity unavailable for requested GPU types",
                client_token=request.client_token,
            )
        if step is PodCreateScenario.CREATE_TIMEOUT_NOT_CREATED:
            raise NeedsReconciliation(
                "fake pod create timed out; creation not confirmed",
                client_token=request.client_token,
            )
        if request.max_hourly_price_micro_usd < FAKE_POD_HOURLY_MICRO_USD:
            raise PolicyDenied(
                "price cap is below the fake pod offer", client_token=request.client_token
            )

        self._counter += 1
        pod_id = f"fake-pod-{self._counter:04d}"
        pod = _Pod(
            pod_id=pod_id,
            name=request.name,
            owned_tag=request.owned_tag,
            client_token=request.client_token,
            gpu_type=request.gpu_type_allowlist[0],
            hourly_price_micro_usd=FAKE_POD_HOURLY_MICRO_USD,
            created_at=self.clock.now(),
            endpoint_url=fake_https(f"{pod_id}.pods.fake", ""),
            pipeline_owned=True,
            late_billing=step is PodCreateScenario.LATE_BILLING,
        )
        self._pods[pod_id] = pod
        if step is PodCreateScenario.CREATE_TIMEOUT_BUT_CREATED:
            raise NeedsReconciliation(
                "fake pod create timed out after the pod was accepted",
                client_token=request.client_token,
            )
        return self._info(pod)

    def _require(self, pod_id: str) -> _Pod:
        pod = self._pods.get(pod_id)
        if pod is None:
            raise NotFound("fake pod not found", pod_id=pod_id)
        return pod

    def get_pod(self, pod_id: str) -> PodInfo | None:
        self._record("get_pod", "-", pod_id)
        pod = self._pods.get(pod_id)
        return None if pod is None else self._info(pod)

    def find_pods(
        self, *, owned_tag: str | None = None, client_token: str | None = None
    ) -> list[PodInfo]:
        self._record("find_pods", "-", f"{owned_tag}|{client_token}")
        return [
            self._info(pod)
            for pod in self._pods.values()
            if (owned_tag is None or pod.owned_tag == owned_tag)
            and (client_token is None or pod.client_token == client_token)
        ]

    def _touch(self, pod: _Pod, method: str) -> None:
        if not pod.pipeline_owned:
            self.foreign_touches.append(pod.pod_id)
        self._record(method, "-", pod.pod_id)

    def stop_pod(self, pod_id: str) -> PodInfo:
        pod = self._require(pod_id)
        self._touch(pod, "stop_pod")
        step = self._stop_steps.next()
        if step is PodStopScenario.STOP_FAILS_ONCE:
            raise TransientProviderError("fake pod stop failed transiently", pod_id=pod_id)
        pod.state = PodState.STOPPED
        pod.stopped_at = pod.stopped_at or self.clock.now()
        return self._info(pod)

    def terminate_pod(self, pod_id: str) -> PodInfo:
        pod = self._require(pod_id)
        self._touch(pod, "terminate_pod")
        pod.state = PodState.TERMINATED
        pod.stopped_at = pod.stopped_at or self.clock.now()
        return self._info(pod)

    def usage(self, pod_id: str, *, since: datetime, until: datetime) -> list[UsageReceipt]:
        if since >= until:
            raise SchemaInvalid("usage interval must satisfy since < until")
        pod = self._require(pod_id)
        self._record("usage", "-", pod_id)
        start = max(since, pod.created_at)
        end = min(until, pod.stopped_at or until)
        receipts: list[UsageReceipt] = []
        if end > start:
            ms = _ms_between(start, end)
            receipts.append(
                synthetic_receipt(
                    provider=self.provider_id,
                    provider_receipt_id=f"pod-usage:{pod_id}:{_epoch_ms(start)}:{_epoch_ms(end)}",
                    kind=ReceiptKind.ACCRUAL,
                    category=BudgetCategory.GPU_GENERATION,
                    unit=PriceUnit.GPU_SECOND,
                    units=-(-ms // 1000),
                    amount_micro_usd=-(-(pod.hourly_price_micro_usd * ms) // 3_600_000),
                    observed_at=self.clock.now(),
                    interval=(start, end),
                )
            )
        if pod.late_billing:
            if pod.late_pending and not pod.late_emitted:
                anchor = pod.stopped_at or end
                receipts.append(
                    synthetic_receipt(
                        provider=self.provider_id,
                        provider_receipt_id=f"pod-late:{pod_id}",
                        kind=ReceiptKind.ADJUSTMENT,
                        category=BudgetCategory.GPU_GENERATION,
                        unit=PriceUnit.GPU_SECOND,
                        units=LATE_EXTRA_MS // 1000,
                        amount_micro_usd=-(
                            -(pod.hourly_price_micro_usd * LATE_EXTRA_MS) // 3_600_000
                        ),
                        observed_at=self.clock.now(),
                        interval=(anchor, anchor + timedelta(milliseconds=LATE_EXTRA_MS)),
                    )
                )
                pod.late_emitted = True
                pod.late_pending = False
            elif not pod.late_emitted:
                pod.late_pending = True
        self._bill(receipts)
        return receipts

    def pipeline_fingerprint(self) -> str:
        """Digest of every pod's observable state; used by replay tests."""
        return canonical_hash(
            [(p.pod_id, p.state.value, p.owned_tag, p.client_token) for p in self._pods.values()]
        )


__all__ = [
    "DEFAULT_FOREIGN_PODS",
    "FAKE_GPU_TYPE",
    "FAKE_POD_HOURLY_MICRO_USD",
    "FakePodProvider",
    "ForeignPodSeed",
    "LATE_EXTRA_MS",
    "PodCreateScenario",
    "PodStopScenario",
]
