"""GPU pod acquisition filters, provider call discipline and the live-adapter gate (T012).

Everything here runs against an injected ``PodProvider`` (the T007 fake offline, a real
adapter only after T031 qualification). Rules implemented in this module:

- Acquisition filters (allowed hardware, price cap, host-RAM floor) are checked *before*
  any provider call: a typed ``PolicyDenied``/``UnknownPrice`` blocks dispatch, it is never
  assumed zero or silently narrowed.
- A create timeout is ambiguous: the caller must reconcile by ``client_token`` before any
  re-creation. ``reconcile_by_token`` finds only pods carrying this pipeline's ``owned_tag``.
- Stop is verified: after ``stop_pod``/``terminate_pod`` the pod is re-read and its state
  must be terminal. Transient stop failures are retried a bounded number of times and then
  escalated to termination.
- The live Runpod adapter is structurally disabled: without a configured credential
  reference every effectful call raises ``EffectDenied``, and even with one the real HTTP
  surface stays unimplemented until T031 records rights/cost/quality evidence. No network
  code exists in this build.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from microdrama.config import Settings
from microdrama.contracts.cost import PriceQuote, UsageReceipt
from microdrama.contracts.enums import EffectKind, PodState, Provenance
from microdrama.contracts.errors import (
    Conflict,
    EffectDenied,
    NeedsReconciliation,
    PolicyDenied,
    TransientProviderError,
    UnknownPrice,
)
from microdrama.contracts.providers import PodCreateRequest, PodInfo, PodProvider

if TYPE_CHECKING:
    from microdrama.contracts.infra import Clock
    from microdrama.rendering.leases import PodLeaseConfig

# Reservation operation kinds owned by this module. The janitor uses them to recognise
# budget holds that belong to the pod lifecycle (claim holds and shutdown-grant holds).
LEASE_OPERATION_KIND = "pod.lease"
STOP_OPERATION_KIND = "pod.stop"


@dataclass(frozen=True)
class PodSpec:
    """One acquisition's hard filter set, derived from a T006 preset record plus config."""

    gpu_type_allowlist: tuple[str, ...]
    max_hourly_price_micro_usd: int
    min_host_ram_gb: int
    container_image: str
    volume_gb: int = 0

    def to_request(self, *, name: str, client_token: str, owned_tag: str) -> PodCreateRequest:
        return PodCreateRequest(
            client_token=client_token,
            name=name,
            owned_tag=owned_tag,
            gpu_type_allowlist=list(self.gpu_type_allowlist),
            max_hourly_price_micro_usd=self.max_hourly_price_micro_usd,
            min_host_ram_gb=self.min_host_ram_gb,
            container_image=self.container_image,
            volume_gb=self.volume_gb,
        )


def check_acquisition_filters(
    spec: PodSpec,
    *,
    allowed_gpu_types: frozenset[str],
    min_host_ram_gb: int,
    price: PriceQuote | None,
) -> None:
    """Typed blocks before any dispatch (SPEC §8: unknown price/hardware never dispatches).

    - unknown price (None), non-USD price or a non-positive price is ``UnknownPrice``;
    - hardware outside the configured allowlist is ``PolicyDenied``;
    - a host-RAM request below the configured floor is ``PolicyDenied`` (the floor comes
      from the preset registry record the caller selected).
    """
    if price is None:
        raise UnknownPrice(
            "pod hourly price is unknown; paid dispatch blocked",
            operation_kind=LEASE_OPERATION_KIND,
        )
    if price.currency != "USD":
        raise UnknownPrice(
            "pod price is not in USD and no FX rate is available; paid dispatch blocked",
            currency=price.currency,
        )
    if price.unit_price_micro_usd <= 0:
        raise UnknownPrice("pod unit price is not a known positive price; paid dispatch blocked")
    outside = [gpu for gpu in spec.gpu_type_allowlist if gpu not in allowed_gpu_types]
    if outside:
        raise PolicyDenied(
            "gpu type outside the allowed hardware filter; dispatch blocked",
            requested=sorted(spec.gpu_type_allowlist),
            allowed=sorted(allowed_gpu_types),
        )
    if spec.min_host_ram_gb < min_host_ram_gb:
        raise PolicyDenied(
            "host RAM below the configured floor; dispatch blocked",
            requested_gb=spec.min_host_ram_gb,
            floor_gb=min_host_ram_gb,
        )
    if spec.max_hourly_price_micro_usd <= 0:
        raise UnknownPrice("price cap is not a positive bound; paid dispatch blocked")


class PodManager:
    """All provider calls for one pipeline-owned pod lifecycle.

    ``LeaseService`` and the independent ``Janitor`` both go through a ``PodManager`` so the
    reconcile-before-retry and verified-stop disciplines cannot diverge between them.
    """

    def __init__(
        self,
        provider: PodProvider,
        clock: Clock,
        config: PodLeaseConfig,
        *,
        stop_attempts: int = 2,
        create_attempts: int = 2,
    ) -> None:
        self._provider = provider
        self._clock = clock
        self._config = config
        self._stop_attempts = max(1, stop_attempts)
        self._create_attempts = max(1, create_attempts)

    @property
    def provider_id(self) -> str:
        return self._provider.provider_id

    # --- acquisition ------------------------------------------------------------------

    def create_request(self, spec: PodSpec, *, name: str, client_token: str) -> PodCreateRequest:
        return spec.to_request(
            name=name, client_token=client_token, owned_tag=self._config.owned_tag
        )

    def reconcile_by_token(self, client_token: str) -> PodInfo | None:
        """Find the pod a create may have left behind. Only pods carrying our owned tag.

        More than one match for a single create token is provider misbehaviour: it is a
        ``Conflict`` (never a blind pick), and the extra pods become janitor targets.
        """
        matches = [
            pod
            for pod in self._provider.find_pods(client_token=client_token)
            if pod.owned_tag == self._config.owned_tag
        ]
        if len(matches) > 1:
            raise Conflict(
                "provider reports multiple pods for one create token",
                client_token=client_token,
                pod_ids=[pod.pod_id for pod in matches],
            )
        return matches[0] if matches else None

    def acquire_or_reconcile(self, spec: PodSpec, *, name: str, client_token: str) -> PodInfo:
        """Create a pod, or adopt the one an ambiguous create already made.

        ``NeedsReconciliation`` from the provider triggers an immediate reconciliation by
        client token; only when that proves nothing exists is another create attempted with
        the *same* token (idempotent at the provider). A create that stays ambiguous after
        the bounded attempts raises ``NeedsReconciliation`` — never a blind re-create.
        """
        adopted = self.reconcile_by_token(client_token)
        if adopted is not None:
            return adopted
        attempts = 0
        while attempts < self._create_attempts:
            attempts += 1
            try:
                pod = self._provider.create_pod(
                    self.create_request(spec, name=name, client_token=client_token)
                )
            except NeedsReconciliation:
                found = self.reconcile_by_token(client_token)
                if found is not None:
                    return found
                continue
            return pod
        raise NeedsReconciliation(
            "pod create outcome is still ambiguous after bounded attempts; reconcile before retry",
            client_token=client_token,
        )

    # --- verification -----------------------------------------------------------------

    def verify(self, pod: PodInfo, spec: PodSpec, *, settings: Settings) -> PodInfo:
        """Health/pin verification on every adopted or created pod.

        Checks the observable contract: ownership tag, live state, allowed hardware, price
        within the cap and an endpoint. Pinned container/model/node schema beyond this is
        verified by the live adapter (T031); the fake carries the pinned image only in the
        create request.
        """
        if pod.owned_tag != self._config.owned_tag:
            raise PolicyDenied(
                "pod does not carry this pipeline's ownership tag",
                pod_id=pod.pod_id,
                owned_tag=pod.owned_tag,
            )
        if pod.state in (PodState.STOPPED, PodState.TERMINATED):
            raise Conflict("pod is already stopped", pod_id=pod.pod_id, state=pod.state.value)
        if pod.state is PodState.UNKNOWN:
            raise NeedsReconciliation("pod state is unknown", pod_id=pod.pod_id)
        if pod.state is not PodState.RUNNING:
            raise TransientProviderError(
                "pod is not running yet (warmup incomplete)", pod_id=pod.pod_id
            )
        if pod.gpu_type not in spec.gpu_type_allowlist:
            raise PolicyDenied(
                "created pod hardware outside the requested allowlist",
                pod_id=pod.pod_id,
                gpu_type=pod.gpu_type,
            )
        if pod.hourly_price_micro_usd > spec.max_hourly_price_micro_usd:
            raise PolicyDenied(
                "created pod price exceeds the acquisition cap",
                pod_id=pod.pod_id,
                hourly_price_micro_usd=pod.hourly_price_micro_usd,
                cap_micro_usd=spec.max_hourly_price_micro_usd,
            )
        if not pod.endpoint_url:
            raise Conflict("pod exposes no endpoint", pod_id=pod.pod_id)
        if settings.is_offline_mock and pod.provenance is not Provenance.FAKE_SYNTHETIC:
            raise PolicyDenied(
                "OFFLINE_MOCK may only use fake-synthetic pods",
                provenance=pod.provenance.value,
            )
        if not settings.is_offline_mock and pod.provenance is Provenance.FAKE_SYNTHETIC:
            raise PolicyDenied(
                "a fake-synthetic pod is not a real resource; live modes refuse it",
                provenance=pod.provenance.value,
            )
        return pod

    # --- teardown ---------------------------------------------------------------------

    def get(self, pod_id: str) -> PodInfo | None:
        return self._provider.get_pod(pod_id)

    def find_owned(self) -> list[PodInfo]:
        """Every pod the provider reports under our owned tag (and nothing else)."""
        return [
            pod for pod in self._provider.find_pods() if pod.owned_tag == self._config.owned_tag
        ]

    def stop(self, pod_id: str) -> PodState:
        """Stop (and verify), retrying transient failures, then escalating to terminate.

        Returns the verified terminal state. Raises ``TransientProviderError`` only when
        both stop and terminate keep failing; the caller must leave durable state recording
        the failure so the next sweep retries.
        """
        failure: TransientProviderError | None = None
        for _ in range(self._stop_attempts):
            try:
                self._provider.stop_pod(pod_id)
            except TransientProviderError as exc:
                failure = exc
                continue
            return self._verify_stopped(pod_id)
        try:
            self._provider.terminate_pod(pod_id)
        except TransientProviderError as exc:
            detail = f"last stop error: {failure}; terminate error: {exc}" if failure else str(exc)
            raise TransientProviderError(
                f"pod stop and terminate both failed ({detail})", pod_id=pod_id
            ) from exc
        return self._verify_stopped(pod_id)

    def _verify_stopped(self, pod_id: str) -> PodState:
        """Re-read the pod and confirm compute is really stopped (never trust the call).

        A pod the provider no longer lists is treated as terminated: compute is verifiably
        absent, which is the state we need.
        """
        pod = self._provider.get_pod(pod_id)
        if pod is None:
            return PodState.TERMINATED
        if pod.state not in (PodState.STOPPED, PodState.TERMINATED):
            raise Conflict(
                "compute is not verified stopped",
                pod_id=pod.pod_id,
                state=pod.state.value,
            )
        return pod.state

    def usage(self, pod_id: str, *, since: datetime, until: datetime) -> list[UsageReceipt]:
        return self._provider.usage(pod_id, since=since, until=until)


class RunpodLiveAdapter:
    """The real Runpod adapter slot — structurally disabled in this build (T031 owns it).

    Without a configured credential reference (a ``credref:`` name in
    ``MICRODRAMA_RUNPOD_CREDREF``) every effectful call raises ``EffectDenied``. With one,
    the settings must additionally allow ``CLOUD_RESOURCE`` effects — and even then the
    HTTP surface is deliberately unimplemented until T031 records rights/cost/quality
    evidence, so the call still refuses. There is no network code in this class.
    """

    provider_id = "runpod"

    def __init__(self, settings: Settings, *, credential_ref: str | None = None) -> None:
        self._settings = settings
        self._credential_ref = credential_ref

    def _require(self, what: str) -> None:
        if not self._credential_ref:
            raise EffectDenied(
                f"runpod adapter has no configured credential reference; {what} refused",
                adapter="runpod",
            )
        self._settings.require_effect(EffectKind.CLOUD_RESOURCE, what=what)
        raise EffectDenied(
            f"live runpod {what} is not implemented before T031 provider qualification",
            adapter="runpod",
        )

    def create_pod(self, request: PodCreateRequest) -> PodInfo:
        self._require("create_pod")
        raise AssertionError("unreachable")  # pragma: no cover

    def get_pod(self, pod_id: str) -> PodInfo | None:
        self._require("get_pod")
        raise AssertionError("unreachable")  # pragma: no cover

    def find_pods(
        self, *, owned_tag: str | None = None, client_token: str | None = None
    ) -> list[PodInfo]:
        self._require("find_pods")
        raise AssertionError("unreachable")  # pragma: no cover

    def stop_pod(self, pod_id: str) -> PodInfo:
        self._require("stop_pod")
        raise AssertionError("unreachable")  # pragma: no cover

    def terminate_pod(self, pod_id: str) -> PodInfo:
        self._require("terminate_pod")
        raise AssertionError("unreachable")  # pragma: no cover

    def usage(self, pod_id: str, *, since: datetime, until: datetime) -> list[UsageReceipt]:
        self._require("usage")
        raise AssertionError("unreachable")  # pragma: no cover


def resolve_pod_provider(settings: Settings, *, credential_ref: str | None = None) -> PodProvider:
    """The runtime provider is the (disabled) live adapter; the fake is test-only.

    Offline tests inject ``FakePodProvider`` directly; production wiring calls this and
    gets an adapter that cannot spend until T031 configures and qualifies it.
    """
    ref = (
        credential_ref
        if credential_ref is not None
        else os.environ.get("MICRODRAMA_RUNPOD_CREDREF")
    )
    return RunpodLiveAdapter(settings, credential_ref=ref)


__all__ = [
    "LEASE_OPERATION_KIND",
    "PodManager",
    "PodSpec",
    "RunpodLiveAdapter",
    "STOP_OPERATION_KIND",
    "check_acquisition_filters",
    "resolve_pod_provider",
]
