"""Network guard: public destinations are refused, loopback keeps working, originals are restored."""

from __future__ import annotations

import http.server
import socket
import threading
from collections.abc import Iterator

import httpx
import pytest

from microdrama.testing.network_guard import NetworkBlocked, block_network, install


@pytest.fixture
def loopback_server() -> Iterator[int]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"local-ok")

        def log_message(self, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


def test_httpx_to_public_host_is_refused_before_any_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _PROXY_VARS:
        monkeypatch.delenv(name, raising=False)
    with block_network(), pytest.raises(NetworkBlocked) as info:
        httpx.get("https://api.example.com/v1/items", timeout=2)
    assert info.value.code == "NETWORK_BLOCKED"
    assert info.value.details["destination"] == "api.example.com"


def test_egress_through_a_configured_proxy_is_refused(
    monkeypatch: pytest.MonkeyPatch, loopback_server: int
) -> None:
    # A loopback proxy would otherwise be allowed and could forward to the internet.
    for name in _PROXY_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{loopback_server}")
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{loopback_server}")
    with block_network(), pytest.raises(NetworkBlocked) as info:
        httpx.get("https://api.example.com/", timeout=2)
    assert "proxy" in str(info.value)
    assert info.value.details["destination"] == f"127.0.0.1:{loopback_server}"


def test_raw_socket_to_public_ip_is_refused() -> None:
    with block_network(), socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(NetworkBlocked):
            sock.connect(("8.8.8.8", 53))
        with pytest.raises(NetworkBlocked):
            sock.connect_ex(("8.8.8.8", 53))


def test_hostname_connect_is_refused_without_dns() -> None:
    with block_network(), socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(NetworkBlocked):
            sock.connect(("example.com", 443))


def test_resolution_and_create_connection_of_public_names_are_refused() -> None:
    with block_network():
        with pytest.raises(NetworkBlocked):
            socket.getaddrinfo("api.example.com", 443)
        with pytest.raises(NetworkBlocked):
            socket.create_connection(("api.example.com", 443), timeout=1)


def test_loopback_http_still_works(loopback_server: int) -> None:
    with block_network():
        response = httpx.get(f"http://127.0.0.1:{loopback_server}/", timeout=5)
    assert response.status_code == 200
    assert response.text == "local-ok"


def test_loopback_raw_socket_pair_still_works() -> None:
    with block_network(), socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        with socket.create_connection(("localhost", port), timeout=5) as client:
            conn, _ = server.accept()
            with conn:
                client.sendall(b"ping")
                assert conn.recv(4) == b"ping"


def test_unix_socket_is_allowed(tmp_path) -> None:
    path = str(tmp_path / "guard.sock")
    with block_network(), socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(path)
        server.listen(1)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(path)


def test_allow_loopback_false_blocks_loopback(loopback_server: int) -> None:
    with block_network(allow_loopback=False), pytest.raises(NetworkBlocked):
        httpx.get(f"http://127.0.0.1:{loopback_server}/", timeout=5)


_UNSET = object()


def _dict_entry(owner: object, name: str) -> object:
    """The entry the class/module itself holds for ``name`` (inherited attributes are absent)."""
    return owner.__dict__.get(name, _UNSET)  # type: ignore[attr-defined]


def test_originals_are_restored_on_exit() -> None:
    # The global autouse guard in tests/conftest.py may already be active, so capture whatever
    # is installed now and require the block to restore exactly that, not "unpatched".
    prior_getaddrinfo = socket.getaddrinfo
    prior_create = socket.create_connection
    prior_connect = socket.socket.connect
    prior_connect_ex = socket.socket.connect_ex
    prior_connect_entry = _dict_entry(socket.socket, "connect")
    prior_connect_ex_entry = _dict_entry(socket.socket, "connect_ex")
    with block_network():
        assert socket.getaddrinfo is not prior_getaddrinfo
        assert socket.socket.connect is not prior_connect
    assert socket.getaddrinfo is prior_getaddrinfo
    assert socket.create_connection is prior_create
    assert socket.socket.connect is prior_connect
    assert socket.socket.connect_ex is prior_connect_ex
    assert _dict_entry(socket.socket, "connect") is prior_connect_entry
    assert _dict_entry(socket.socket, "connect_ex") is prior_connect_ex_entry


def test_originals_are_restored_when_the_block_raises() -> None:
    prior_connect_entry = _dict_entry(socket.socket, "connect")
    prior_getaddrinfo = socket.getaddrinfo
    with pytest.raises(RuntimeError), block_network():
        raise RuntimeError("body failed inside the guard")
    assert _dict_entry(socket.socket, "connect") is prior_connect_entry
    assert socket.getaddrinfo is prior_getaddrinfo


def test_install_applies_through_monkeypatch_and_undoes(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _PROXY_VARS:
        monkeypatch.delenv(name, raising=False)
    install(monkeypatch)
    with pytest.raises(NetworkBlocked):
        httpx.get("https://api.example.com", timeout=2)


def test_monkeypatch_undo_restores_the_prior_resolver() -> None:
    # Works with or without the global guard: undo must hand back exactly what was there before.
    prior = socket.getaddrinfo
    patcher = pytest.MonkeyPatch()
    try:
        install(patcher)
        assert socket.getaddrinfo is not prior
        with pytest.raises(NetworkBlocked):
            socket.getaddrinfo("api.example.com", 443)
    finally:
        patcher.undo()
    assert socket.getaddrinfo is prior
