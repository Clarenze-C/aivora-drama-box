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


def _request(server, method: str, path: str, *, token: str | None, body: bytes = b"") -> tuple[int, bytes]:
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
    status, payload = _request(
        server, "POST", "/prompt", token=TOKEN, body=b'{"prompt": {"a": 1}}'
    )
    assert status == 200
    assert json.loads(payload) == {"upstream": True}
    assert len(upstream.seen) == 1
    assert upstream.seen[0]["method"] == "POST"
    assert upstream.seen[0]["path"] == "/prompt"
    assert upstream.seen[0]["authorization"] is None  # the token is not forwarded
    assert upstream.seen[0]["body"] == b'{"prompt": {"a": 1}}'


def test_a_get_with_the_valid_token_forwards_the_query(gateway) -> None:
    _module, upstream, server = gateway
    status, _payload = _request(
        server, "GET", "/view?filename=out.mp4&type=output", token=TOKEN
    )
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
