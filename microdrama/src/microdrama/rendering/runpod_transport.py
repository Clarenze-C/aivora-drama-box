"""Runpod REST v2 PodProvider with namespace/token reconciliation.

The public Pod API has no idempotency-key field. We encode a namespace and a stable hash
of the client token in the Pod name, then reconcile only exact namespace matches. A POST
timeout followed by no matching Pod is still UNKNOWN (the list may be eventually
consistent); it is never retried by this provider.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from microdrama.config import Settings
from microdrama.contracts.cost import UsageReceipt
from microdrama.contracts.enums import EffectKind, PodState, Provenance
from microdrama.contracts.errors import (
    Conflict,
    EffectDenied,
    MicrodramaError,
    NeedsReconciliation,
    PolicyDenied,
    ProviderError,
    TransientProviderError,
)
from microdrama.contracts.providers import PodCreateRequest, PodInfo


@dataclass(frozen=True)
class RunpodQuoteAttestation:
    """Operator supplied current quote and T031 gating evidence (no provider default)."""

    namespace: str
    quote_micro_usd_per_hour: int
    quote_as_of: datetime
    expires_at: datetime
    container_disk_gb: int
    container_storage_micro_usd_per_gb_month: int
    persistent_storage_micro_usd_per_gb_month: int
    pinned_image: str
    allowed_gpu_types: frozenset[str]
    host_ram_gb_by_gpu: Mapping[str, int]
    rights_evidence_id: str
    preset_evidence_id: str
    activation_enabled: bool = False

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9]{4,12}", self.namespace):
            raise ValueError("Runpod ownership namespace must be 4-12 lowercase alphanumerics")
        if (
            self.quote_micro_usd_per_hour <= 0
            or self.container_disk_gb <= 0
            or self.container_storage_micro_usd_per_gb_month <= 0
            or self.persistent_storage_micro_usd_per_gb_month <= 0
        ):
            raise ValueError("Runpod compute/storage quote and disk bounds are invalid")
        if (
            not self.pinned_image
            or "@sha256:" not in self.pinned_image
            or not self.allowed_gpu_types
            or not self.host_ram_gb_by_gpu
        ):
            raise ValueError("Runpod attestation needs a digest-pinned image and GPU allowlist")
        if self.quote_as_of.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("Runpod quote timestamps must be timezone aware")
        if not self.rights_evidence_id or not self.preset_evidence_id:
            raise ValueError("rights and preset evidence IDs are required")

    def check_current(self, now: datetime) -> None:
        if not self.activation_enabled:
            raise EffectDenied("Runpod live activation is disabled pending T031 evidence")
        if now.tzinfo is None or now.utcoffset() is None:
            raise PolicyDenied("Runpod attestation check needs an aware clock")
        if not self.quote_as_of <= now < self.expires_at:
            raise PolicyDenied("Runpod operator quote is stale or not yet valid")


@dataclass(frozen=True)
class RunpodBillingRecord:
    """Unmodified provider billing bucket, not a per-second lease receipt."""

    pod_id: str
    interval_start: datetime
    interval_end: datetime
    total_micro_usd: int
    gpu_micro_usd: int
    cpu_micro_usd: int
    disk_micro_usd: int


@dataclass(frozen=True)
class RunpodBillingHistory:
    observed_at: datetime
    requested_start: datetime
    requested_end: datetime
    resolved_start: datetime
    resolved_end: datetime
    records: tuple[RunpodBillingRecord, ...]


class RunpodResponse(Protocol):
    status: int
    body: bytes


class RunpodTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None = None,
    ) -> RunpodResponse: ...


@dataclass(frozen=True)
class _Response:
    status: int
    body: bytes


class UrllibRunpodTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None = None,
    ) -> RunpodResponse:
        request = Request(url, data=body, headers=dict(headers), method=method)
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed Runpod origin
                return _Response(response.status, response.read())
        except HTTPError as exc:
            return _Response(exc.code, exc.read())
        except (TimeoutError, URLError) as exc:
            raise NeedsReconciliation("Runpod request timed out; Pod outcome is unknown") from exc


def pod_name(namespace: str, client_token: str) -> str:
    """A deterministic, compact name that identifies our ownership namespace/token."""
    token_hash = sha256(client_token.encode("utf-8")).hexdigest()[:32]
    return f"md-{namespace}-{token_hash}"


def _state(raw: str) -> PodState:
    return {
        "PROVISIONING": PodState.CREATING,
        "STARTING": PodState.CREATING,
        "RUNNING": PodState.RUNNING,
        "EXITED": PodState.STOPPED,
        "TERMINATED": PodState.TERMINATED,
    }.get(raw, PodState.UNKNOWN)


class RunpodRestProvider:
    """Live PodProvider. All effects require mode, quote, and reservation guards."""

    provider_id = "runpod"

    def __init__(
        self,
        settings: Settings,
        *,
        credential_ref: str | None,
        credential_resolver: Callable[[str], str | None],
        attestation: RunpodQuoteAttestation,
        now: Callable[[], datetime],
        reservation_guard: Callable[[PodCreateRequest, RunpodQuoteAttestation], None],
        cleanup_guard: Callable[[str, str], None],
        transport: RunpodTransport | None = None,
    ) -> None:
        self._settings = settings
        self._credential_ref = credential_ref
        self._credential_resolver = credential_resolver
        self._attestation = attestation
        self._now = now
        self._reservation_guard = reservation_guard
        self._cleanup_guard = cleanup_guard
        self._transport = transport or UrllibRunpodTransport()
        self._owned_tag = f"microdrama-owned:{attestation.namespace}"

    def _headers(self, *, json_body: bool = False) -> dict[str, str]:
        if self._settings.is_offline_mock:
            raise EffectDenied("OFFLINE_MOCK refuses all Runpod effects")
        if not self._credential_ref or not self._credential_ref.startswith("credref:"):
            raise EffectDenied("Runpod requires a configured credential reference name")
        secret = self._credential_resolver(self._credential_ref)
        if not secret:
            raise EffectDenied("Runpod credential reference did not resolve")
        headers = {"Authorization": f"Bearer {secret}", "Accept": "application/json"}
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _call(
        self, method: str, path: str, *, body: Any = None, query: Mapping[str, str] = ()
    ) -> Any:
        headers = self._headers(json_body=body is not None)
        url = "https://api.runpod.io/v2" + path
        if query:
            url += "?" + urlencode(query)
        raw_body = None if body is None else json.dumps(body, separators=(",", ":")).encode()
        response = self._transport.request(method, url, headers=headers, body=raw_body)
        if response.status == 404:
            return None
        if response.status >= 500 or response.status == 429:
            if method in {"POST", "DELETE"}:
                raise NeedsReconciliation(
                    "Runpod effect response is ambiguous", status=response.status
                )
            raise TransientProviderError(
                "Runpod API temporarily unavailable", status=response.status
            )
        if response.status < 200 or response.status >= 300:
            raise ProviderError("Runpod rejected request", status=response.status)
        if not response.body:
            return {}
        try:
            return json.loads(response.body, parse_float=Decimal)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("Runpod returned invalid JSON", status=response.status) from exc

    def _to_info(self, data: Mapping[str, Any]) -> PodInfo:
        try:
            pod_id = str(data["id"])
            name = str(data["name"])
            gpu = data["gpu"]
            gpu_type = str(gpu["id"])
            rate = Decimal(str(data["cost"]))
            scaled_rate = rate * Decimal(1_000_000)
            if scaled_rate != scaled_rate.to_integral_value():
                raise ValueError("provider hourly rate exceeds micro-USD precision")
            hourly_micro = int(scaled_rate)
            created = datetime.fromisoformat(str(data["createdAt"]).replace("Z", "+00:00"))
            gpu_memory_gb = int(gpu["memory"])
            status = _state(str(data["status"]))
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise ProviderError("Runpod Pod response omitted required contract fields") from exc
        owned = bool(
            re.fullmatch(rf"md-{re.escape(self._attestation.namespace)}-[0-9a-f]{{32}}", name)
        )
        endpoint = _comfy_endpoint(pod_id, data.get("runtime"))
        # Runpod's returned `gpu.memory` is GPU memory, not host RAM. Host RAM is checked
        # against the attested GPU profile before create; do not conflate the two.
        if gpu_memory_gb <= 0:
            raise ProviderError("Runpod reported invalid GPU memory")
        return PodInfo(
            pod_id=pod_id,
            name=name,
            owned_tag=self._owned_tag if owned else None,
            client_token=None,
            state=status,
            gpu_type=gpu_type,
            hourly_price_micro_usd=hourly_micro,
            created_at=created,
            endpoint_url=endpoint,
            provenance=Provenance.LIVE_PROVIDER,
        )

    def create_pod(self, request: PodCreateRequest) -> PodInfo:
        self._settings.require_effect(EffectKind.CLOUD_RESOURCE, what="Runpod Pod create")
        self._settings.require_effect(EffectKind.PAID_REQUEST, what="Runpod paid Pod create")
        self._attestation.check_current(self._now())
        self._reservation_guard(request, self._attestation)
        if request.owned_tag != self._owned_tag:
            raise PolicyDenied("Pod lease ownership tag differs from the operator namespace")
        if self._attestation.quote_micro_usd_per_hour > request.max_hourly_price_micro_usd:
            raise PolicyDenied("operator quote exceeds the lease price ceiling")
        if request.container_image != self._attestation.pinned_image:
            raise PolicyDenied("Pod image is not pinned by current T031 attestation")
        if not request.gpu_type_allowlist or any(
            g not in self._attestation.allowed_gpu_types for g in request.gpu_type_allowlist
        ):
            raise PolicyDenied("Pod GPU is outside the T031 attested allowlist")
        if any(
            self._attestation.host_ram_gb_by_gpu.get(g, 0) < request.min_host_ram_gb
            for g in request.gpu_type_allowlist
        ):
            raise PolicyDenied("Runpod GPU profile has no attested host RAM meeting the request")
        if request.volume_gb < 0:
            raise PolicyDenied("Pod persistent volume cannot be negative")
        name = pod_name(self._attestation.namespace, request.client_token)
        # The owner namespace and token-derived name are the only externally visible
        # ownership fields documented by Runpod REST v2.
        payload: dict[str, Any] = {
            "name": name,
            "image": request.container_image,
            "gpu": {"id": request.gpu_type_allowlist[0], "count": 1},
            "disk": self._attestation.container_disk_gb,
        }
        if request.volume_gb:
            payload["mounts"] = {"persistent": {"size": request.volume_gb, "path": "/workspace"}}
        try:
            created = self._call("POST", "/pods", body=payload)
        except NeedsReconciliation as exc:
            # One bounded list pass may positively identify a created pod. Absence does not
            # prove non-creation, so preserve ambiguity for the lease/janitor/operator.
            try:
                matches = self.find_pods(client_token=request.client_token)
            except Conflict:
                raise
            except MicrodramaError as exc:
                raise NeedsReconciliation(
                    "Runpod create outcome is unknown and ownership scan failed"
                ) from exc
            if len(matches) == 1:
                self._verify_existing_match(matches[0], request, name)
                return matches[0]
            if len(matches) > 1:
                raise Conflict("multiple owned Pods match one create token") from exc
            raise NeedsReconciliation(
                "Runpod create remains ambiguous after owned-name reconciliation"
            ) from exc
        if not isinstance(created, Mapping):
            raise NeedsReconciliation("Runpod create response did not identify a Pod")
        info = self._to_info(created)
        if info.name != name or info.owned_tag != self._owned_tag:
            raise Conflict("Runpod create returned a Pod outside the expected ownership name")
        self._verify_existing_match(info, request, name)
        self._verify_attested_price(info)
        return info

    def _verify_existing_match(
        self, info: PodInfo, request: PodCreateRequest, expected_name: str
    ) -> None:
        if info.name != expected_name or info.gpu_type not in request.gpu_type_allowlist:
            raise Conflict("Runpod name collision has mismatched GPU or ownership token")
        data = self._call("GET", f"/pods/{quote(info.pod_id, safe='')}")
        if not isinstance(data, Mapping) or data.get("image") != self._attestation.pinned_image:
            raise Conflict("Runpod name collision has mismatched pinned image")

    def _verify_attested_price(self, pod: PodInfo) -> None:
        if pod.hourly_price_micro_usd != self._attestation.quote_micro_usd_per_hour:
            # Provider actual rate changed after quote: stop only this verified owned Pod.
            if pod.owned_tag == self._owned_tag:
                try:
                    self.stop_pod(pod.pod_id)
                except Exception as exc:
                    raise NeedsReconciliation(
                        "Runpod price changed and immediate shutdown failed",
                        pod_id=pod.pod_id,
                    ) from exc
            raise PolicyDenied("Runpod reported compute rate differs from the operator quote")

    def get_pod(self, pod_id: str) -> PodInfo | None:
        encoded = quote(pod_id, safe="")
        data = self._call("GET", f"/pods/{encoded}")
        if data is None:
            return None
        return self._to_info(data)

    def find_pods(
        self, *, owned_tag: str | None = None, client_token: str | None = None
    ) -> list[PodInfo]:
        if owned_tag is not None and owned_tag != self._owned_tag:
            return []
        token_name = pod_name(self._attestation.namespace, client_token) if client_token else None
        pods: list[PodInfo] = []
        cursor: str | None = None
        while True:
            query = {"limit": "1000"}
            if cursor:
                query["cursor"] = cursor
            payload = self._call("GET", "/pods", query=query)
            if not isinstance(payload, Mapping) or not isinstance(payload.get("pods"), list):
                raise ProviderError("Runpod list response is missing the documented pods array")
            for item in payload["pods"]:
                if not isinstance(item, Mapping):
                    raise ProviderError("Runpod list contains an unreadable Pod record")
                info = self._to_info(item)
                if info.owned_tag == self._owned_tag and (
                    token_name is None or info.name == token_name
                ):
                    if token_name is not None:
                        if item.get("image") != self._attestation.pinned_image:
                            raise Conflict("Runpod name collision has mismatched pinned image")
                        gpu = item.get("gpu")
                        if (
                            not isinstance(gpu, Mapping)
                            or gpu.get("id") not in self._attestation.allowed_gpu_types
                        ):
                            raise Conflict("Runpod name collision has mismatched GPU")
                        self._verify_attested_price(info)
                    pods.append(info)
            page = payload.get("pagination")
            if not isinstance(page, Mapping):
                raise ProviderError("Runpod list response omitted pagination proof")
            if not page.get("hasNextPage"):
                break
            cursor = page.get("nextCursor")
            if not isinstance(cursor, str) or not cursor:
                raise NeedsReconciliation(
                    "Runpod list pagination cannot prove complete ownership scan"
                )
        return pods

    def stop_pod(self, pod_id: str) -> PodInfo:
        self._settings.require_effect(EffectKind.CLOUD_RESOURCE, what="Runpod Pod stop")
        pod = self.get_pod(pod_id)
        if pod is None:
            return _terminated_placeholder(pod_id, self._owned_tag)
        self._require_owned(pod)
        if pod.state in (PodState.STOPPED, PodState.TERMINATED):
            return pod
        self._cleanup_guard("pod.stop", pod_id)
        self._call("POST", f"/pods/{quote(pod_id, safe='')}/action", body={"action": "stop"})
        observed = self.get_pod(pod_id)
        if observed is None:
            return _terminated_placeholder(pod_id, self._owned_tag)
        if observed.state not in (PodState.STOPPED, PodState.TERMINATED):
            raise TransientProviderError("Runpod stop is not verified by readback", pod_id=pod_id)
        return observed

    def terminate_pod(self, pod_id: str) -> PodInfo:
        self._settings.require_effect(EffectKind.CLOUD_RESOURCE, what="Runpod Pod terminate")
        pod = self.get_pod(pod_id)
        if pod is None:
            return _terminated_placeholder(pod_id, self._owned_tag)
        self._require_owned(pod)
        self._cleanup_guard("pod.terminate", pod_id)
        self._call("DELETE", f"/pods/{quote(pod_id, safe='')}")
        observed = self.get_pod(pod_id)
        if observed is not None and observed.state is not PodState.TERMINATED:
            raise TransientProviderError(
                "Runpod termination is not verified by readback", pod_id=pod_id
            )
        return observed or _terminated_placeholder(pod_id, self._owned_tag)

    def usage(self, pod_id: str, *, since: datetime, until: datetime) -> list[UsageReceipt]:
        # Billing history is not translated here: no source fields have yet been mapped
        # to the canonical UsageReceipt. An empty list is unknown usage, never zero-cost.
        self._settings.require_effect(EffectKind.CLOUD_RESOURCE, what="Runpod usage query")
        pod = self.get_pod(pod_id)
        if pod is not None:
            self._require_owned(pod)
        return []

    def billing_history(
        self, pod_id: str, *, since: datetime, until: datetime
    ) -> RunpodBillingHistory:
        """Read documented time-bucketed billing without inventing lease intervals.

        The provider may snap requested bounds to hourly buckets. Those records are useful
        as actual provider-reported cost evidence, but are not returned as UsageReceipt
        objects for accrue_lease_usage because a bucket can overlap adjacent leases.
        """
        if since.tzinfo is None or until.tzinfo is None or until <= since:
            raise PolicyDenied("billing history needs a positive timezone-aware interval")
        pod = self.get_pod(pod_id)
        if pod is None:
            raise PolicyDenied("billing history Pod is absent; ownership cannot be verified")
        self._require_owned(pod)
        payload = self._call(
            "GET",
            "/billing/pods",
            query={
                "podId": pod_id,
                "startTime": since.isoformat().replace("+00:00", "Z"),
                "endTime": until.isoformat().replace("+00:00", "Z"),
                "bucketSize": "hour",
            },
        )
        if not isinstance(payload, Mapping) or not isinstance(payload.get("records"), list):
            raise ProviderError("Runpod billing response is missing its documented records list")
        metadata = payload.get("metadata")
        query = metadata.get("query") if isinstance(metadata, Mapping) else None
        if not isinstance(query, Mapping):
            raise ProviderError("Runpod billing response is missing resolved query metadata")
        try:
            resolved_start = _parse_time(query["startTime"])
            resolved_end = _parse_time(query["endTime"])
            records = tuple(_billing_record(row) for row in payload["records"])
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise ProviderError("Runpod billing response fields are malformed") from exc
        if any(record.pod_id != pod_id for record in records):
            raise ProviderError("Runpod billing response included a different Pod")
        return RunpodBillingHistory(
            observed_at=self._now(),
            requested_start=since,
            requested_end=until,
            resolved_start=resolved_start,
            resolved_end=resolved_end,
            records=records,
        )

    def _require_owned(self, pod: PodInfo) -> None:
        if pod.owned_tag != self._owned_tag:
            raise PolicyDenied("refusing Runpod action on a Pod outside the owned namespace")


def _comfy_endpoint(pod_id: str, runtime: Any) -> str | None:
    ports = runtime.get("ports", []) if isinstance(runtime, Mapping) else []
    port = next((p for p in ports if isinstance(p, Mapping) and p.get("private") == 8188), None)
    if port is None:
        return None
    public = port.get("public")
    if not isinstance(public, int) or public <= 0:
        return None
    return f"https://{pod_id}-8188.proxy.runpod.net"


def _terminated_placeholder(pod_id: str, owned_tag: str) -> PodInfo:
    return PodInfo(
        pod_id=pod_id,
        name=f"deleted-{pod_id}",
        owned_tag=owned_tag,
        client_token=None,
        state=PodState.TERMINATED,
        gpu_type="unknown",
        hourly_price_micro_usd=0,
        created_at=datetime.now(UTC),
        endpoint_url=None,
        provenance=Provenance.LIVE_PROVIDER,
    )


def _parse_time(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("provider time must be timezone-aware")
    return parsed


def _amount_micro(value: Any) -> int:
    scaled = Decimal(str(value)) * Decimal(1_000_000)
    if scaled != scaled.to_integral_value() or scaled < 0:
        raise ValueError("provider amount is not non-negative micro-USD precision")
    return int(scaled)


def _billing_record(value: Any) -> RunpodBillingRecord:
    if not isinstance(value, Mapping):
        raise ValueError("billing row is not an object")
    record = RunpodBillingRecord(
        pod_id=str(value["podId"]),
        interval_start=_parse_time(value["startTime"]),
        interval_end=_parse_time(value["endTime"]),
        total_micro_usd=_amount_micro(value["totalAmount"]),
        gpu_micro_usd=_amount_micro(value["gpuAmount"]),
        cpu_micro_usd=_amount_micro(value["cpuAmount"]),
        disk_micro_usd=_amount_micro(value["diskAmount"]),
    )
    if record.total_micro_usd != (
        record.gpu_micro_usd + record.cpu_micro_usd + record.disk_micro_usd
    ):
        raise ValueError("provider billing total does not equal its documented cost components")
    if record.interval_end <= record.interval_start:
        raise ValueError("provider billing bucket has an empty or reversed interval")
    return record


__all__ = [
    "RunpodBillingHistory",
    "RunpodBillingRecord",
    "RunpodQuoteAttestation",
    "RunpodRestProvider",
    "RunpodTransport",
    "pod_name",
]
