"""HTTP transport for the documented ComfyUI server API.

The transport is deliberately injectable: unit tests use a fixture transport and the
default urllib transport is only reachable through an explicitly configured live client.
ComfyUI does not document prompt-submit idempotency. If a POST times out before a prompt
ID is received, callers must retain UNKNOWN/PENDING_SUBMIT and reconcile; this client
never retries a submit.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID

from microdrama.config import Settings
from microdrama.contracts.enums import EffectKind, Provenance
from microdrama.contracts.errors import EffectDenied, NeedsReconciliation, ProviderError
from microdrama.contracts.providers import (
    ComfyHistoryEntry,
    ComfyNodeInfo,
    ComfyOutputFile,
    ComfyProgressEvent,
)


class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None = None,
    ) -> bytes: ...


@dataclass(frozen=True)
class ComfyRequestAuthorization:
    reservation_id: UUID
    episode_id: UUID
    job_id: UUID
    operation_id: UUID | None


class UrllibTransport:
    """Small stdlib transport; no retries and no response bodies in raised errors."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None = None,
    ) -> bytes:
        request = Request(url, data=body, headers=dict(headers), method=method)
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310 - configured endpoint
                return response.read()
        except HTTPError as exc:
            raise ProviderError("ComfyUI returned an HTTP error", status=exc.code) from exc
        except (TimeoutError, URLError) as exc:
            raise NeedsReconciliation(
                "ComfyUI transport outcome is uncertain; reconcile by durable prompt ID"
            ) from exc


class ComfyHttpClient:
    """ComfyClient implementation for `/prompt`, `/history`, `/queue`, `/view` etc."""

    provider_id = "comfyui"

    def __init__(
        self,
        settings: Settings,
        *,
        endpoint: str | None = None,
        credential_ref: str | None,
        credential_resolver: Callable[[str], str | None],
        request_guard: Callable[[str, str | None, ComfyRequestAuthorization], None],
        dispatch_guard: Callable[[ComfyRequestAuthorization], None],
        transport: HttpTransport | None = None,
    ) -> None:
        self._settings = settings
        self._endpoint = endpoint.rstrip("/") if endpoint else None
        self._bound_pod_id: str | None = None
        self._credential_ref = credential_ref
        self._credential_resolver = credential_resolver
        self._request_guard = request_guard
        self._dispatch_guard = dispatch_guard
        self._transport = transport or UrllibTransport()
        self._authorization: ContextVar[ComfyRequestAuthorization | None] = ContextVar(
            f"comfy_auth_{id(self)}", default=None
        )

    def bind_pod_endpoint(self, pod_id: str, endpoint_url: str | None) -> None:
        """T045-FIX B-B2: bind the Comfy base URL from the created Pod, exactly once.

        The only accepted value is the leased Pod's own proxy URL,
        ``https://<pod_id>-8188.proxy.runpod.net`` (what ``PodInfo.endpoint_url``
        carries). A Pod that reports anything else — or no exposed 8188 port at all —
        refuses here, before any ComfyUI call can send the bearer token to a host the
        pipeline never validated. No config value or CLI flag can set the endpoint.
        """
        expected = f"https://{pod_id}-8188.proxy.runpod.net"
        if endpoint_url != expected:
            raise EffectDenied(
                "the leased Pod's Comfy endpoint does not match its own proxy URL",
                pod_id=pod_id,
                endpoint_url=endpoint_url,
                expected=expected,
            )
        if self._bound_pod_id is not None:
            if self._bound_pod_id != pod_id:
                raise EffectDenied(
                    "the Comfy client is already bound to another leased Pod",
                    bound_pod_id=self._bound_pod_id,
                    pod_id=pod_id,
                )
            return
        self._endpoint = expected
        self._bound_pod_id = pod_id

    @contextmanager
    def authorization_scope(
        self,
        *,
        reservation_id: UUID,
        episode_id: UUID,
        job_id: UUID,
        operation_id: UUID | None,
    ):
        """Bind durable caller state to all live HTTP calls made in this scope."""
        auth = ComfyRequestAuthorization(
            reservation_id=reservation_id,
            episode_id=episode_id,
            job_id=job_id,
            operation_id=operation_id,
        )
        token = self._authorization.set(auth)
        try:
            yield auth
        finally:
            self._authorization.reset(token)

    def _headers(self) -> dict[str, str]:
        if self._settings.is_offline_mock:
            raise EffectDenied("OFFLINE_MOCK refuses live ComfyUI network effects")
        if not self._credential_ref or not self._credential_ref.startswith("credref:"):
            raise EffectDenied("ComfyUI requires a configured credential reference name")
        # The resolver is injected by composition; only the reference name crosses here.
        secret = self._credential_resolver(self._credential_ref)
        if not secret:
            raise EffectDenied("ComfyUI credential reference did not resolve")
        return {"Authorization": f"Bearer {secret}", "Accept": "application/json"}

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] = (),
        body: Any = None,
        authorization_key: str | None = None,
    ) -> bytes:
        # Every route is a live effect boundary. Refuse the effect and check the caller's
        # reservation/operation context before resolving a credential or touching HTTP.
        self._settings.require_effect(EffectKind.PAID_REQUEST, what=f"ComfyUI {method} {path}")
        if self._endpoint is None:
            # T045-FIX B-B2: the endpoint is derived from the created Pod and bound
            # explicitly; an unbound client must never emit a request anywhere.
            raise EffectDenied("the Comfy endpoint is not bound; it is derived from the leased Pod")
        authorization = self._authorization.get()
        if authorization is None:
            raise EffectDenied("ComfyUI request has no scoped durable reservation/operation")
        self._request_guard(path, authorization_key, authorization)
        headers = self._headers()
        if body is not None:
            headers["Content-Type"] = "application/json"
        url = f"{self._endpoint}{path}"
        if query:
            url += "?" + urlencode(query)
        payload = None if body is None else json.dumps(body, separators=(",", ":")).encode()
        return self._transport.request(method, url, headers=headers, body=payload)

    def object_info(self) -> dict[str, ComfyNodeInfo]:
        data = json.loads(self._request("GET", "/object_info"))
        result: dict[str, ComfyNodeInfo] = {}
        for name, item in data.items():
            inputs = item.get("input", {})
            required = list(inputs.get("required", {}))
            optional = list(inputs.get("optional", {}))
            result[name] = ComfyNodeInfo(
                class_type=name,
                required_inputs=required,
                optional_inputs=optional,
                output_types=item.get("output", []),
            )
        return result

    def queue_prompt(self, graph: dict[str, Any], *, client_id: str) -> str:
        self._settings.require_effect(EffectKind.PAID_REQUEST, what="ComfyUI prompt submission")
        # Composition must check a live reservation, rights route, and pinned qualified
        # workflow immediately before the paid boundary. There is no permissive default.
        authorization = self._authorization.get()
        if authorization is None:
            raise EffectDenied("ComfyUI prompt has no scoped durable reservation/operation")
        self._dispatch_guard(authorization)
        # One post only. POST timeout is ambiguous; never blindly submit again.
        try:
            data = json.loads(
                self._request(
                    "POST",
                    "/prompt",
                    body={"prompt": graph, "client_id": client_id},
                    authorization_key=client_id,
                )
            )
        except NeedsReconciliation:
            raise
        except (ValueError, ProviderError) as exc:
            raise NeedsReconciliation("ComfyUI submit response was not safely understood") from exc
        if data.get("error") or data.get("node_errors"):
            raise ProviderError(
                "ComfyUI rejected prompt validation",
                error=bool(data.get("error")),
                node_errors=bool(data.get("node_errors")),
            )
        prompt_id = data.get("prompt_id")
        if not isinstance(prompt_id, str) or not prompt_id:
            raise NeedsReconciliation("ComfyUI accepted/denied prompt without a durable prompt ID")
        return prompt_id

    def history(self, prompt_id: str) -> ComfyHistoryEntry | None:
        data = json.loads(
            self._request("GET", f"/history/{prompt_id}", authorization_key=prompt_id)
        )
        entry = data.get(prompt_id)
        if entry is None:
            return None
        status = entry.get("status", {})
        outputs = []
        for node_id, node in entry.get("outputs", {}).items():
            for kind, files in node.items():
                if not isinstance(files, list):
                    continue
                for file in files:
                    outputs.append(
                        ComfyOutputFile(
                            node_id=str(node_id),
                            filename=file["filename"],
                            subfolder=file.get("subfolder", ""),
                            folder_type=file.get("type", "output"),
                            media_kind=kind,
                        )
                    )
        return ComfyHistoryEntry(
            prompt_id=prompt_id,
            completed=bool(status.get("completed")),
            status_str=str(status.get("status_str", "unknown")),
            outputs=outputs,
            provenance=Provenance.LIVE_PROVIDER,
        )

    def in_queue(self, prompt_id: str) -> bool:
        data = json.loads(self._request("GET", "/queue", authorization_key=prompt_id))
        return any(
            str(item[1]) == prompt_id
            for group in ("queue_running", "queue_pending")
            for item in data.get(group, [])
        )

    def progress_events(self, prompt_id: str) -> list[ComfyProgressEvent]:
        # HTTP API has no durable progress history route; the service polls queue/history.
        return []

    def fetch_output(self, output: ComfyOutputFile) -> bytes:
        query = {
            "filename": output.filename,
            "subfolder": output.subfolder,
            "type": output.folder_type,
        }
        return self._request(
            "GET",
            "/view",
            query=query,
            authorization_key=f"{output.node_id}:{output.filename}",
        )


__all__ = [
    "ComfyHttpClient",
    "ComfyRequestAuthorization",
    "HttpTransport",
    "UrllibTransport",
]
