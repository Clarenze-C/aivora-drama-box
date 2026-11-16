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
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import urlsplit
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

# T031 R5a: the provisioning readiness endpoint. The gateway reports ONLY the
# state file start.sh owns - it never probes ComfyUI (that is the client's
# boot-window /object_info retry). The mirrored provision object is
# field-whitelisted: the state file may carry a stderr tail, which must never
# reach the body (no secrets, no paths outside /opt/pika).
PROVISION_FLAG_ENV = "MICRODRAMA_PROVISION_MODELS"
STATE_FILE_ENV = "MICRODRAMA_PROVISION_STATE_FILE"
DEFAULT_STATE_FILE = "/opt/pika/state.json"
READY_PATH = "/__drama/ready"
_MIRROR_KEYS = ("state", "started_at", "ended_at", "exit_code")


def _ready_body() -> dict:
    state_file = os.environ.get(STATE_FILE_ENV, DEFAULT_STATE_FILE)
    try:
        with open(state_file, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            data = None
    except (OSError, ValueError):
        # No state file yet (or a torn write): boot-window material, answered
        # from the flag alone.
        data = None
    if data is None:
        flag_set = os.environ.get(PROVISION_FLAG_ENV, "") == "1"
        return {"state": "BOOTING" if flag_set else "NO_PROVISIONING", "provision": None}
    mirror = {key: data[key] for key in _MIRROR_KEYS if key in data}
    return {"state": str(data.get("state", "PROVISIONING")), "provision": mirror}


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
        if self.command in ("GET", "HEAD") and urlsplit(self.path).path == READY_PATH:
            # Read-only provisioning state; never proxied, never an upstream probe.
            body = json.dumps(_ready_body(), sort_keys=True).encode()
            self._respond(200, "application/json", body)
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
                self._respond(
                    response.status, response.headers.get("Content-Type"), response.read()
                )
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
