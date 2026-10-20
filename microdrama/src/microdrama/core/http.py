"""FastAPI dependencies for the two authentication channels.

- ``human_session_dependency``: the ``md_session`` cookie, plus a CSRF token on unsafe methods
  (``X-CSRF-Token`` header, or a ``csrf_token`` form field). Missing or invalid session is 401;
  a missing or wrong CSRF token is 403.
- ``service_dependency``: ``Authorization: Bearer <token>`` for workers, runtime models, webhooks
  and schedulers. A human session can never authenticate here.
- ``human_or_service_dependency``: a bearer header selects the service channel (and is never
  silently ignored); otherwise the human session channel is used.

Blocking auth calls run in a thread so the event loop is not held. Contract errors raised here are
mapped to HTTP by the integrator's app.
"""

from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from microdrama.contracts.errors import Unauthenticated, Unauthorized
from microdrama.contracts.principals import Principal
from microdrama.core.auth import AuthService

SESSION_COOKIE = "md_session"
CSRF_HEADER = "X-CSRF-Token"
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

Dependency = Callable[[Request], Awaitable[Principal]]


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header is None:
        return None
    scheme, _, token = header.strip().partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


async def _form_csrf(request: Request) -> str | None:
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
        return None
    form = await request.form()
    value = form.get("csrf_token")
    return value if isinstance(value, str) else None


def human_session_dependency(auth: AuthService) -> Dependency:
    async def human_session(request: Request) -> Principal:
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            raise Unauthenticated("human session required")
        principal = await run_in_threadpool(auth.authenticate_session, token)
        if request.method.upper() in _UNSAFE_METHODS:
            csrf = request.headers.get(CSRF_HEADER) or await _form_csrf(request)
            if not csrf:
                raise Unauthorized("CSRF token missing")
            await run_in_threadpool(auth.verify_csrf, principal, csrf)
        return principal

    return human_session


def service_dependency(auth: AuthService) -> Dependency:
    async def service(request: Request) -> Principal:
        token = _bearer(request)
        if token is None:
            raise Unauthenticated("service credential required")
        return await run_in_threadpool(auth.authenticate_service, token)

    return service


def human_or_service_dependency(auth: AuthService) -> Dependency:
    human = human_session_dependency(auth)
    service = service_dependency(auth)

    async def human_or_service(request: Request) -> Principal:
        if request.headers.get("authorization") is not None:
            return await service(request)
        return await human(request)

    return human_or_service


__all__ = [
    "CSRF_HEADER",
    "SESSION_COOKIE",
    "human_or_service_dependency",
    "human_session_dependency",
    "service_dependency",
]
