"""Token-checking gateway for the exposed ComfyUI port (T031 CN-5, 2026-11-09).

ComfyUI itself binds 127.0.0.1 ONLY; this gateway owns the pod's exposed port
and refuses (401) every request - HTTP and websocket - that does not carry the
run's bearer token in the Authorization header. The token arrives via the
MICRODRAMA_COMFY_TOKEN pod env var, set at pod-create time from the pipeline's
credential ref: no secret is baked into the image, and nothing here logs
request bodies, headers or the token (log_message is a no-op). Fail closed - a
missing env token refuses everything.

Stdlib only: the pika image's locked runtime must not gain dependencies.
Keep byte-identical with the copy in the sibling image directory (guarded by
tests/unit/rendering/test_canary_gateway.py).
"""

from __future__ import annotations

import hmac
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request as UpstreamRequest
from urllib.request import urlopen

TOKEN_ENV = "MICRODRAMA_COMFY_TOKEN"
DEFAULT_LISTEN_HOST = "0.0.0.0"
DEFAULT_LISTEN_PORT = 8188
UPSTREAM = os.environ.get("MICRODRAMA_COMFY_UPSTREAM", "http://127.0.0.1:8189")
_UPSTREAM_TIMEOUT_SECONDS = 120
_FORWARDED_HEADERS = ("Content-Type", "Accept", "User-Agent")
_REFUSED_BODY = b'{"error":"unauthorized"}'
_UNAVAILABLE_BODY = b'{"error":"upstream unavailable"}'


class GatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "microdrama-gateway/1"

    def log_message(self, *args: object) -> None:
        """CN-5: never log requests - paths can carry query material."""

    # --- auth ------------------------------------------------------------------

    def _bearer_token(self) -> str:
        header = self.headers.get("Authorization") or ""
        scheme, _, value = header.partition(" ")
        if scheme.lower() != "bearer":
            return ""
        return value.strip()

    def _authorized(self) -> bool:
        expected = os.environ.get(TOKEN_ENV, "")
        if not expected:
            return False  # fail closed: no configured token means no access
        supplied = self._bearer_token()
        if not supplied:
            return False
        return hmac.compare_digest(supplied.encode(), expected.encode())

    def _refuse(self) -> None:
        self._respond(401, "application/json", _REFUSED_BODY)

    # --- proxying --------------------------------------------------------------

    def _handle(self) -> None:
        if not self._authorized():
            self._refuse()
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._respond(400, "application/json", b'{"error":"bad length"}')
            return
        payload = self.rfile.read(length) if length > 0 else None
        request = UpstreamRequest(UPSTREAM + self.path, data=payload, method=self.command)
        for header in _FORWARDED_HEADERS:
            if value := self.headers.get(header):
                request.add_header(header, value)
        try:
            with urlopen(request, timeout=_UPSTREAM_TIMEOUT_SECONDS) as response:
                self._respond(response.status, response.headers.get("Content-Type"), response.read())
        except HTTPError as exc:
            content_type = exc.headers.get("Content-Type") if exc.headers else None
            self._respond(exc.code, content_type, exc.read())
        except (OSError, ValueError):
            # URLError subclasses OSError; the upstream (ComfyUI on 127.0.0.1) is
            # still starting or gone - the canary's boot-window retry covers it.
            self._respond(502, "application/json", _UNAVAILABLE_BODY)

    def _respond(self, status: int, content_type: str | None, body: bytes) -> None:
        self.send_response(status)
        if content_type:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    do_GET = do_POST = do_PUT = do_DELETE = do_OPTIONS = do_PATCH = do_HEAD = _handle


def main() -> None:
    host = os.environ.get("MICRODRAMA_COMFY_GATEWAY_HOST", DEFAULT_LISTEN_HOST)
    port = int(os.environ.get("MICRODRAMA_COMFY_GATEWAY_PORT", DEFAULT_LISTEN_PORT))
    ThreadingHTTPServer((host, port), GatewayHandler).serve_forever()


if __name__ == "__main__":
    main()
