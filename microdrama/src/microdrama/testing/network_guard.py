"""Offline network guard for tests (T007).

While a ``block_network()`` block is active, or after ``install(monkeypatch)``, every
Python-level attempt to reach a non-loopback destination raises ``NetworkBlocked``:

- ``socket.socket.connect`` and ``connect_ex`` (hostnames other than ``localhost`` are
  refused *without* any DNS lookup);
- ``socket.create_connection``;
- ``socket.getaddrinfo`` (name resolution of anything except loopback names/addresses).

Loopback (127.0.0.0/8, ::1, ``localhost``, IPv4-mapped loopback), unspecified bind
addresses (0.0.0.0, ::) and AF_UNIX sockets remain usable so local test servers work.
``allow_loopback=False`` blocks loopback as well.

Limits, stated plainly: the guard sees Python-level socket calls only. It does not
police subprocesses (ffmpeg/ffprobe are only ever given local file paths by this
harness) or C code that resolves names without these entry points.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any, Protocol
from urllib.parse import urlsplit

from microdrama.contracts.errors import EffectDenied


class NetworkBlocked(EffectDenied):
    """A test attempted network access that offline mode forbids."""

    code = "NETWORK_BLOCKED"


class _Patcher(Protocol):
    """The subset of ``pytest.MonkeyPatch`` used by ``install``."""

    def setattr(self, target: Any, name: str, value: Any, raising: bool = ...) -> None: ...


_MISSING = object()
_Patch = tuple[Any, str, Any]


def _host_allowed(host: object, *, allow_loopback: bool) -> bool:
    if host is None:  # passive lookups carry no destination
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", errors="replace")
    if not isinstance(host, str) or not allow_loopback:
        return False
    if host.lower() == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False  # a hostname we would have to resolve: refuse, never look it up
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_loopback or ip.is_unspecified


_PROXY_VARIABLES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def _proxy_endpoints() -> set[tuple[str, int]]:
    """(host, port) of every proxy named in the environment; egress through them is refused."""
    endpoints: set[tuple[str, int]] = set()
    for name in _PROXY_VARIABLES:
        raw = os.environ.get(name)
        if not raw:
            continue
        parts = urlsplit(raw if "://" in raw else f"http://{raw}")
        if parts.hostname is None:
            continue
        port = parts.port or (443 if parts.scheme == "https" else 80)
        endpoints.add((parts.hostname.lower(), port))
    return endpoints


def _check_proxy(host: object, port: object) -> None:
    if isinstance(host, str) and isinstance(port, int):
        if (host.lower(), port) in _proxy_endpoints():
            raise NetworkBlocked(
                "egress through a configured proxy is blocked during offline tests",
                operation="connect",
                destination=f"{host}:{port}",
            )


def _check_host(host: object, *, allow_loopback: bool, operation: str) -> None:
    if not _host_allowed(host, allow_loopback=allow_loopback):
        raise NetworkBlocked(
            f"network access blocked during offline tests: {operation} to {host!r}",
            operation=operation,
            destination=str(host),
        )


def _check_socket(sock: socket.socket, address: object, *, allow_loopback: bool) -> None:
    if sock.family == socket.AF_UNIX:
        return
    if sock.family in (socket.AF_INET, socket.AF_INET6) and isinstance(address, tuple):
        if address:
            _check_host(address[0], allow_loopback=allow_loopback, operation="connect")
            _check_proxy(address[0], address[1] if len(address) > 1 else None)
            return
    raise NetworkBlocked(
        "network access blocked during offline tests: unsupported socket destination",
        operation="connect",
        destination=str(address),
    )


def _patches(*, allow_loopback: bool) -> list[_Patch]:
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create_connection = socket.create_connection
    original_getaddrinfo = socket.getaddrinfo

    def connect(self: socket.socket, address: Any) -> None:
        _check_socket(self, address, allow_loopback=allow_loopback)
        return original_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        _check_socket(self, address, allow_loopback=allow_loopback)
        return original_connect_ex(self, address)

    def create_connection(address: Any, *args: Any, **kwargs: Any) -> socket.socket:
        _check_host(address[0], allow_loopback=allow_loopback, operation="create_connection")
        _check_proxy(address[0], address[1])
        return original_create_connection(address, *args, **kwargs)

    def getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
        _check_host(host, allow_loopback=allow_loopback, operation="getaddrinfo")
        return original_getaddrinfo(host, port, *args, **kwargs)

    return [
        (socket.socket, "connect", connect),
        (socket.socket, "connect_ex", connect_ex),
        (socket, "create_connection", create_connection),
        (socket, "getaddrinfo", getaddrinfo),
    ]


@contextmanager
def _patched(patches: Sequence[_Patch]) -> Iterator[None]:
    saved: list[tuple[Any, str, Any]] = []
    try:
        for target, name, replacement in patches:
            saved.append((target, name, target.__dict__.get(name, _MISSING)))
            setattr(target, name, replacement)
        yield
    finally:
        for target, name, old in reversed(saved):
            if old is _MISSING:
                delattr(target, name)
            else:
                setattr(target, name, old)


@contextmanager
def block_network(*, allow_loopback: bool = True) -> Iterator[None]:
    """Refuse non-loopback network access for the duration of the block."""
    with _patched(_patches(allow_loopback=allow_loopback)):
        yield


def install(monkeypatch: _Patcher, *, allow_loopback: bool = True) -> None:
    """Apply the same guard through a pytest ``monkeypatch``; pytest undoes it per test."""
    for target, name, replacement in _patches(allow_loopback=allow_loopback):
        monkeypatch.setattr(target, name, replacement)


__all__ = ["NetworkBlocked", "block_network", "install"]
