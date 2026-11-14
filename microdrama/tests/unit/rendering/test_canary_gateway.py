"""CN-5 (2026-11-09, canary-night review): the in-image ComfyUI gateway, offline.

The canary and pika-h3-flex images front ComfyUI (bound to 127.0.0.1 only)
with a token-checking gateway on the exposed port. These tests load the
deployment source directly - no docker build - and drive it over real loopback
HTTP against a stub upstream. Every token below is synthetic.
"""

from __future__ import annotations

import http.client
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
GATEWAY_COPIES = (
    ROOT / "deployment" / "canary-image" / "canary_gateway.py",
    ROOT / "deployment" / "pika-h3-flex" / "canary_gateway.py",
)
TOKEN = "synthetic-gateway-token"


def test_the_two_image_copies_are_byte_identical() -> None:
    """The gateway is one program shipped in two build contexts (COPY cannot
    reach outside its context); a drifted copy would gate one image but not
    the other."""
    assert GATEWAY_COPIES[0].read_bytes() == GATEWAY_COPIES[1].read_bytes()


class _Upstream:
    """A recording stub ComfyUI on an ephemeral loopback port."""

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self._record()

            def do_POST(self) -> None:
                self._record()

            def _record(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                upstream.seen.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                        "content_type": self.headers.get("Content-Type"),
                        "body": self.rfile.read(length) if length else b"",
                    }
                )
                body = b'{"upstream": true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                return None

        upstream = self
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> _Upstream:
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def gateway(monkeypatch: pytest.MonkeyPatch):
    """The gateway module bound to a stub upstream + a configured token."""
    spec = importlib.util.spec_from_file_location("canary_gateway_under_test", GATEWAY_COPIES[0])
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    with _Upstream() as upstream:
        monkeypatch.setenv("MICRODRAMA_COMFY_UPSTREAM", upstream.url)
        monkeypatch.setenv("MICRODRAMA_COMFY_TOKEN", TOKEN)
        spec.loader.exec_module(module)
        server = ThreadingHTTPServer(("127.0.0.1", 0), module.GatewayHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield module, upstream, server
        finally:
            server.shutdown()
            server.server_close()


def _request(
    server, method: str, path: str, *, token: str | None, body: bytes = b""
) -> tuple[int, bytes]:
    host, port = server.server_address[:2]
    connection = http.client.HTTPConnection(host, port, timeout=10)
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    payload = response.read()
    connection.close()
    return response.status, payload


# CN-5: every route the runner or an attacker could reach, including the
# websocket endpoint, refuses a missing or wrong token with 401.
ROUTES = [
    ("GET", "/object_info"),
    ("POST", "/prompt"),
    ("POST", "/upload/image?overwrite=1"),
    ("GET", "/view?filename=out.mp4&subfolder=&type=output"),
    ("GET", "/history/prompt-1"),
    ("GET", "/ws"),  # websocket upgrade requests are refused before proxying
    ("GET", "/queue"),
]


@pytest.mark.parametrize("method,path", ROUTES)
@pytest.mark.parametrize(
    "token",
    [None, "synthetic-wrong-token", ""],
    ids=["missing", "wrong", "empty"],
)
def test_every_route_refuses_missing_or_wrong_tokens(
    gateway, method: str, path: str, token: str | None
) -> None:
    _module, upstream, server = gateway
    body = b'{"prompt": {}}' if method == "POST" else b""
    status, payload = _request(server, method, path, token=token, body=body)
    assert status == 401
    assert json.loads(payload) == {"error": "unauthorized"}
    # Nothing reached the upstream: the refusal happens at the gate.
    assert upstream.seen == []


def test_valid_token_forwards_without_leaking_authorization(gateway) -> None:
    _module, upstream, server = gateway
    status, payload = _request(server, "POST", "/prompt", token=TOKEN, body=b'{"prompt": {"a": 1}}')
    assert status == 200
    assert json.loads(payload) == {"upstream": True}
    assert len(upstream.seen) == 1
    assert upstream.seen[0]["method"] == "POST"
    assert upstream.seen[0]["path"] == "/prompt"
    assert upstream.seen[0]["authorization"] is None  # the token is not forwarded
    assert upstream.seen[0]["body"] == b'{"prompt": {"a": 1}}'


def test_a_get_with_the_valid_token_forwards_the_query(gateway) -> None:
    _module, upstream, server = gateway
    status, _payload = _request(server, "GET", "/view?filename=out.mp4&type=output", token=TOKEN)
    assert status == 200
    assert upstream.seen[0]["path"] == "/view?filename=out.mp4&type=output"


def test_without_a_configured_token_the_gateway_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No env token (misconfigured pod): everything is refused, never open."""
    spec = importlib.util.spec_from_file_location("canary_gateway_closed", GATEWAY_COPIES[0])
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    with _Upstream() as upstream:
        monkeypatch.setenv("MICRODRAMA_COMFY_UPSTREAM", upstream.url)
        monkeypatch.delenv("MICRODRAMA_COMFY_TOKEN", raising=False)
        spec.loader.exec_module(module)
        server = ThreadingHTTPServer(("127.0.0.1", 0), module.GatewayHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, _payload = _request(server, "GET", "/object_info", token=TOKEN)
            assert status == 401
            assert upstream.seen == []
        finally:
            server.shutdown()
            server.server_close()


# ---------------------------------------------------------------------------
# T031 R5a (RR-T2): GET /__drama/ready reports the provisioning state file only.
# The gateway never probes ComfyUI; without a token it is as refused as everything
# else; the body carries no secret and no path outside /opt/pika.
# ---------------------------------------------------------------------------


def _ready_request(server, *, token: str | None = TOKEN) -> tuple[int, bytes]:
    return _request(server, "GET", "/__drama/ready", token=token)


def test_ready_refuses_missing_or_wrong_tokens(gateway) -> None:
    _module, upstream, server = gateway
    for token in (None, "synthetic-wrong-token", ""):
        status, payload = _ready_request(server, token=token or None)
        assert status == 401
        assert json.loads(payload) == {"error": "unauthorized"}
    assert upstream.seen == []


def test_ready_reports_no_provisioning_without_state_file(
    gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Flag absent (canary/CPU image): NO_PROVISIONING, provision null."""
    _module, upstream, server = gateway
    monkeypatch.delenv("MICRODRAMA_PROVISION_MODELS", raising=False)
    monkeypatch.delenv("MICRODRAMA_PROVISION_STATE_FILE", raising=False)
    status, payload = _ready_request(server)
    assert status == 200
    assert json.loads(payload) == {"state": "NO_PROVISIONING", "provision": None}
    # The gateway never proxies the ready read to ComfyUI.
    assert upstream.seen == []


def test_ready_reports_booting_when_the_flag_is_set_but_no_state_file(
    gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    _module, _upstream, server = gateway
    monkeypatch.setenv("MICRODRAMA_PROVISION_MODELS", "1")
    monkeypatch.delenv("MICRODRAMA_PROVISION_STATE_FILE", raising=False)
    status, payload = _ready_request(server)
    assert status == 200
    assert json.loads(payload) == {"state": "BOOTING", "provision": None}


@pytest.mark.parametrize("state", ["PROVISIONING", "PROVISIONED", "PROVISION_FAILED"], ids=str)
def test_ready_mirrors_the_state_file(gateway, monkeypatch: pytest.MonkeyPatch, state: str) -> None:
    _module, upstream, server = gateway
    # Point the gateway at an explicit state file (the env default is /opt/pika,
    # which only exists inside the image).
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "state.json"
        target.write_text(
            json.dumps(
                {
                    "state": state,
                    "started_at": "2026-11-13T01:02:03Z",
                    "ended_at": "2026-11-13T01:20:04Z",
                    "exit_code": 7,
                    # The state file may carry opaque diagnostics; only the
                    # whitelisted fields may reach the body.
                    "stderr_tail_hex": "626f6f6d2f6f70742f436f6d667955492f6d6f64656c73",
                    "secretish": "token-shaped-value",
                }
            )
        )
        monkeypatch.setenv("MICRODRAMA_PROVISION_STATE_FILE", str(target))
        status, payload = _ready_request(server)
    assert status == 200
    body = json.loads(payload)
    assert body["state"] == state
    assert body["provision"] == {
        "state": state,
        "started_at": "2026-11-13T01:02:03Z",
        "ended_at": "2026-11-13T01:20:04Z",
        "exit_code": 7,
    }
    # No secret values and no paths outside /opt/pika in the body: the raw
    # serialized body is checked, not just the parsed mirror.
    text = payload.decode()
    assert "secretish" not in text and "token-shaped-value" not in text
    assert "stderr_tail" not in text and "626f6f6d" not in text
    assert upstream.seen == []


def test_ready_survives_a_corrupt_state_file_without_probing_comfyui(
    gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A torn write is boot-window material, never a crash and never an upstream
    probe: the read is answered from the flag alone."""
    _module, upstream, server = gateway
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "state.json"
        target.write_text('{"state":"PROVISION')  # torn write
        monkeypatch.setenv("MICRODRAMA_PROVISION_MODELS", "1")
        monkeypatch.setenv("MICRODRAMA_PROVISION_STATE_FILE", str(target))
        status, payload = _ready_request(server)
    assert status == 200
    assert json.loads(payload)["state"] == "BOOTING"
    assert upstream.seen == []


def test_an_unreachable_upstream_is_a_boot_window_502(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authorized request while ComfyUI (127.0.0.1) is still starting: 502,
    which the canary's documented boot-window retry tolerates."""
    import socket

    # A port nothing listens on: connection refused, immediately.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        dead_port = probe.getsockname()[1]
    spec = importlib.util.spec_from_file_location("canary_gateway_502", GATEWAY_COPIES[0])
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    monkeypatch.setenv("MICRODRAMA_COMFY_UPSTREAM", f"http://127.0.0.1:{dead_port}")
    monkeypatch.setenv("MICRODRAMA_COMFY_TOKEN", TOKEN)
    spec.loader.exec_module(module)
    server = ThreadingHTTPServer(("127.0.0.1", 0), module.GatewayHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, payload = _request(server, "GET", "/object_info", token=TOKEN)
        assert status == 502
        assert json.loads(payload) == {"error": "upstream unavailable"}
    finally:
        server.shutdown()
        server.server_close()
