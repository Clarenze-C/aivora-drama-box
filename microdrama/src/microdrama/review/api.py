"""HTTP surface of the review module (T008). Exported factory only; the integrator registers it.

JSON (SPEC §4.3): ``GET /seasons/proposals``, ``GET /seasons/{id}``, ``POST /seasons/{id}/approval``,
``GET /episodes/{id}/review``, ``POST /episodes/{id}/review``.

Pages: ``/ui`` (proposals, season decision, episode review with the owner-only media stream
``/ui/media/{asset_id}``) and ``/auth`` (login and logout, which set and clear the ``md_session``
cookie). Every human-only route refuses a request that presents a bearer credential: the bearer
is authenticated as that service principal and refused with 403 before the request body is even
read (a route-level guard; see ``_refuse_non_human_route``), so workers, models and schedulers
can never read review data or decide, and their malformed bodies are 403, not 422. Unsafe
requests need the CSRF token.

The sign-in form's pre-session token (``md_login_csrf``, V-28) is enforced server-side (V-38):
single-use with a server-clock TTL, so a replayed pair signs in exactly once and the renewal
after a failed attempt invalidates the token before it (``review.signin.SignInTokens``).

Status codes: 202 for a queued or recorded decision, 200 with ``status="REPLAYED"`` for a replayed
idempotency key, 409 for stale or conflicting decisions, 422 for invalid input, 403 for refused
principals and CSRF failures, 401 without a session.
"""

import hmac
from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.routing import APIRoute
from pydantic import ValidationError

from microdrama.contracts.enums import FeedbackCategory, SeasonState
from microdrama.contracts.errors import MicrodramaError, Unauthenticated, Unauthorized
from microdrama.contracts.principals import Principal
from microdrama.contracts.routes import EpisodeReviewView, SeasonProposalSummary, SeasonView
from microdrama.contracts.season import ApprovalCommand
from microdrama.core.auth import AuthService, require_human_owner
from microdrama.core.http import SESSION_COOKIE, Dependency, service_dependency
from microdrama.core.idempotency import CommandResult
from microdrama.review.forms import (
    FEEDBACK_ROWS,
    command_from_form,
    new_idempotency_key,
    validation_message,
)
from microdrama.review.render import render
from microdrama.review.service import EpisodePage, QaFindingRow, ReviewService
from microdrama.review.signin import SIGNIN_TOKEN_TTL_SECONDS

CSRF_COOKIE = "md_csrf"
# Pre-session double-submit token for the sign-in form (V-28): the cookie and the form field carry
# the same random value, so a cross-site form cannot log the owner into an attacker's account.
# Since V-38 the pair is also single-use with a server-clock TTL (``review.signin.SignInTokens``):
# any sign-in attempt consumes it, and the fresh token minted for a failure page invalidates the
# one before it.
LOGIN_CSRF_COOKIE = "md_login_csrf"
_SECURITY_HEADERS = {
    "Cache-Control": "no-store, private",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; media-src 'self'; style-src 'self' 'unsafe-inline'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
}
CsrfTokenFor = Callable[[Request], str | None]


def csrf_cookie_token(request: Request) -> str | None:
    """The CSRF token the login page stored next to the session (HttpOnly, rendered server-side)."""
    return request.cookies.get(CSRF_COOKIE) or None


def _html(body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(body, status_code=status, headers=dict(_SECURITY_HEADERS))


def _command_response(result: CommandResult) -> JSONResponse:
    body = dict(result.body)
    if result.replayed:
        body["status"] = "REPLAYED"
        return JSONResponse(status_code=200, content=body)
    return JSONResponse(status_code=result.status_code, content=body)


def _review_principal(human_session: Dependency, auth: AuthService) -> Dependency:
    """Cookie session for humans; a bearer credential is read as a service principal (then 403).

    On the guarded routes (``_refuse_non_human_route``) this branch never fires for a body
    request: the guard already refused the non-human bearer before the body was read. The
    dependency keeps the check as a backstop so any route that skips the guard still refuses
    after body parsing.
    """
    service_principal = service_dependency(auth)

    async def review_principal(request: Request) -> Principal:
        if request.headers.get("authorization") is not None:
            principal = await service_principal(request)
            if not principal.is_human_owner:
                raise Unauthorized("only a human owner may use the review API")
            return principal
        return await human_session(request)

    return review_principal


def _page_principal(human_session: Dependency) -> Dependency:
    """Pages send an unauthenticated browser to the login page instead of a JSON 401."""

    async def page_principal(request: Request) -> Principal:
        try:
            return await human_session(request)
        except Unauthenticated as exc:
            raise HTTPException(status_code=303, headers={"Location": "/auth/login"}) from exc

    return page_principal


def _set_session_cookies(response: Response, tokens: Any, *, secure: bool) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        tokens.session_token,
        httponly=True,
        samesite="strict",
        secure=secure,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        tokens.csrf_token,
        httponly=True,
        samesite="strict",
        secure=secure,
        path="/",
    )


def _login_page(
    token: str,
    *,
    secure: bool,
    error: dict[str, str] | None = None,
    username: str = "",
    status: int = 200,
) -> HTMLResponse:
    """The sign-in page: the form carries ``token`` and the cookie holds the same value."""
    response = _html(
        render(
            "login.html",
            title="Sign in",
            heading="Sign in",
            signed_in=False,
            csrf=None,
            error=error,
            username=username,
            login_csrf=token,
        ),
        status=status,
    )
    response.set_cookie(
        LOGIN_CSRF_COOKIE,
        token,
        max_age=SIGNIN_TOKEN_TTL_SECONDS,
        httponly=True,
        samesite="strict",
        secure=secure,
        path="/auth",
    )
    return response


def _page_context(
    request: Request, csrf_for: CsrfTokenFor, principal: Principal | None, **extra: Any
):
    csrf = csrf_for(request) if principal is not None else None
    return {"signed_in": principal is not None, "csrf": csrf, **extra}


def _refuse_non_human_route(auth: AuthService) -> type[APIRoute]:
    """Route class whose handler refuses a non-human bearer before any body handling (V-37).

    FastAPI reads and JSON-decodes a request body before route dependencies run, so a refusal
    that lives only in a dependency buffers any body first and answers a worker's malformed
    JSON with 422 instead of 403. Routes built from this class look at the ``Authorization``
    header first — headers only, the body stream is never touched — and reuse the service
    channel's parsing: a live non-human credential is refused with the same 403, a junk bearer
    stays 401 (so it still dominates any session cookie), all before the body is touched.
    """
    service_principal = service_dependency(auth)  # core's bearer parsing; no credential logic here

    class BearerRefusalRoute(APIRoute):
        def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
            original = super().get_route_handler()
            # Endpoints that inject ``principal`` require a human owner in this module; /auth and
            # the /ui redirect stay open to anonymous browsers (and to their request bodies).
            human_route = any(d.name == "principal" for d in self.dependant.dependencies)

            async def refuse_bearer_first(request: Request) -> Response:
                if human_route and request.headers.get("authorization") is not None:
                    principal = await service_principal(request)
                    if not principal.is_human_owner:
                        raise Unauthorized("only a human owner may use the review API")
                return await original(request)

            return refuse_bearer_first

    return BearerRefusalRoute


def build_router(
    service: ReviewService,
    *,
    human_session: Dependency,
    auth: AuthService,
    csrf_token_for: CsrfTokenFor | None = None,
    cookie_secure: bool = True,
) -> APIRouter:
    """Review routes. ``human_session`` is core's cookie dependency (CSRF checked on unsafe methods)."""
    csrf_for: CsrfTokenFor = csrf_token_for or csrf_cookie_token
    router = APIRouter(route_class=_refuse_non_human_route(auth), tags=["review"])
    review_principal = _review_principal(human_session, auth)
    page_principal = _page_principal(human_session)

    # --- JSON gate routes ------------------------------------------------------------

    @router.get("/seasons/proposals", response_model=list[SeasonProposalSummary])
    def season_proposals(
        principal: Annotated[Principal, Depends(review_principal)],
    ) -> list[SeasonProposalSummary]:
        require_human_owner(principal)
        return service.season_proposals()

    @router.get("/seasons/{season_id}", response_model=SeasonView)
    def season_view(
        season_id: UUID,
        principal: Annotated[Principal, Depends(review_principal)],
    ) -> SeasonView:
        require_human_owner(principal)
        return service.season_view(season_id)

    @router.post("/seasons/{season_id}/approval", response_model=None)
    def season_approval(
        season_id: UUID,
        command: ApprovalCommand,
        principal: Annotated[Principal, Depends(review_principal)],
    ) -> JSONResponse:
        require_human_owner(principal)
        return _command_response(service.decide_season(principal, season_id, command))

    @router.get("/episodes/{episode_id}/review", response_model=EpisodeReviewView)
    def episode_review(
        episode_id: UUID,
        principal: Annotated[Principal, Depends(review_principal)],
    ) -> EpisodeReviewView:
        require_human_owner(principal)
        return service.episode_review(episode_id)

    @router.post("/episodes/{episode_id}/review", response_model=None)
    def episode_decision(
        episode_id: UUID,
        command: ApprovalCommand,
        principal: Annotated[Principal, Depends(review_principal)],
    ) -> JSONResponse:
        require_human_owner(principal)
        return _command_response(service.decide_episode(principal, episode_id, command))

    # --- authentication pages ----------------------------------------------------------

    @router.get("/auth/login", response_class=HTMLResponse)
    def login_page() -> HTMLResponse:
        # Every page view mints a stored token (digest only); the browser gets the clear value.
        return _login_page(service.signin_tokens.issue(), secure=cookie_secure)

    @router.post("/auth/login", response_model=None)
    def login_submit(
        request: Request,
        username: Annotated[str, Form(max_length=64)],
        password: Annotated[str, Form(max_length=512)],
        login_csrf: Annotated[str | None, Form(max_length=128)] = None,
    ) -> Response:
        cookie_token = request.cookies.get(LOGIN_CSRF_COOKIE)
        if not cookie_token or not login_csrf or not hmac.compare_digest(cookie_token, login_csrf):
            # Checked before any password is verified: a forged or missing token never reaches
            # auth, and the browser's real token is not consumed by a mismatched pair.
            raise Unauthorized(
                "sign-in form token is missing or does not match; open the page again"
            )
        if not service.signin_tokens.redeem(cookie_token):
            # Server-side token state (V-38), still before any password is verified: a token the
            # server never issued, has expired on the server clock, or has already consumed (any
            # attempt consumes it) never reaches auth.
            raise Unauthorized(
                "sign-in form token is expired or was already used; open the page again"
            )
        try:
            tokens = auth.login(username, password)
        except Unauthenticated:
            return _login_page(
                service.signin_tokens.issue(),  # fresh token; the failed pair is consumed
                secure=cookie_secure,
                error={"code": "UNAUTHENTICATED", "message": "Invalid username or password."},
                username=username,
                status=401,
            )
        response = RedirectResponse("/ui/seasons", status_code=303, headers=dict(_SECURITY_HEADERS))
        _set_session_cookies(response, tokens, secure=cookie_secure)
        response.delete_cookie(
            LOGIN_CSRF_COOKIE, path="/auth", secure=cookie_secure, httponly=True, samesite="strict"
        )
        return response

    @router.post("/auth/logout", response_model=None)
    def logout(principal: Annotated[Principal, Depends(page_principal)]) -> Response:
        auth.revoke_session(principal.session_id)  # type: ignore[arg-type]
        response = RedirectResponse("/auth/login", status_code=303, headers=dict(_SECURITY_HEADERS))
        response.delete_cookie(
            SESSION_COOKIE, path="/", secure=cookie_secure, httponly=True, samesite="strict"
        )
        response.delete_cookie(
            CSRF_COOKIE, path="/", secure=cookie_secure, httponly=True, samesite="strict"
        )
        return response

    # --- review pages ------------------------------------------------------------------

    @router.get("/ui", response_model=None)
    def ui_root() -> Response:
        return RedirectResponse("/ui/seasons", status_code=303)

    @router.get("/ui/seasons", response_class=HTMLResponse)
    def proposals_page(request: Request, principal: Annotated[Principal, Depends(page_principal)]):
        require_human_owner(principal)
        rows = service.season_proposals()
        context = _page_context(
            request, csrf_for, principal, title="Season proposals", rows=rows, error=None
        )
        return _html(render("proposals.html", **context))

    @router.get("/ui/seasons/{season_id}", response_class=HTMLResponse)
    def season_page(
        season_id: UUID, request: Request, principal: Annotated[Principal, Depends(page_principal)]
    ):
        require_human_owner(principal)
        view = service.season_view(season_id)
        context = _page_context(
            request,
            csrf_for,
            principal,
            title="Season concept",
            view=view,
            error=None,
            can_decide=view.summary.state is SeasonState.PROPOSED,
            keys={"approve": new_idempotency_key(), "reject": new_idempotency_key()},
        )
        return _html(render("season.html", heading=view.scope.title_en, **context))

    @router.post("/ui/seasons/{season_id}/approval", response_model=None)
    async def season_form(
        season_id: UUID, request: Request, principal: Annotated[Principal, Depends(page_principal)]
    ) -> Response:
        require_human_owner(principal)
        sid = season_id
        form = await request.form()
        try:
            command = command_from_form(form)
            await run_in_threadpool(service.decide_season, principal, sid, command)
        except (MicrodramaError, ValidationError) as exc:
            error = _error_dict(exc)
            view = await run_in_threadpool(service.season_view, sid)
            context = _page_context(
                request,
                csrf_for,
                principal,
                title="Season concept",
                view=view,
                error=error,
                can_decide=view.summary.state is SeasonState.PROPOSED,
                keys={"approve": new_idempotency_key(), "reject": new_idempotency_key()},
            )
            status = exc.http_status if isinstance(exc, MicrodramaError) else 422
            return _html(render("season.html", heading=view.scope.title_en, **context), status)
        return RedirectResponse(
            f"/ui/seasons/{sid}", status_code=303, headers=dict(_SECURITY_HEADERS)
        )

    @router.get("/ui/episodes/{episode_id}", response_class=HTMLResponse)
    def episode_page(
        episode_id: UUID, request: Request, principal: Annotated[Principal, Depends(page_principal)]
    ):
        require_human_owner(principal)
        page = service.episode_page(episode_id)
        return _html(_render_episode(request, csrf_for, principal, page, error=None))

    @router.post("/ui/episodes/{episode_id}/review", response_model=None)
    async def episode_form(
        episode_id: UUID, request: Request, principal: Annotated[Principal, Depends(page_principal)]
    ) -> Response:
        require_human_owner(principal)
        eid = episode_id
        form = await request.form()
        try:
            command = command_from_form(form)
            await run_in_threadpool(service.decide_episode, principal, eid, command)
        except (MicrodramaError, ValidationError) as exc:
            page = await run_in_threadpool(service.episode_page, eid)
            status = exc.http_status if isinstance(exc, MicrodramaError) else 422
            body = _render_episode(request, csrf_for, principal, page, error=_error_dict(exc))
            return _html(body, status)
        return RedirectResponse(
            f"/ui/episodes/{eid}", status_code=303, headers=dict(_SECURITY_HEADERS)
        )

    @router.get("/ui/episodes/{episode_id}/qa-findings", response_model=list[QaFindingRow])
    def episode_qa_findings(
        episode_id: UUID, principal: Annotated[Principal, Depends(review_principal)]
    ) -> list[QaFindingRow]:
        """Every QA finding of the episode with its QA cycle; the same rows as the review page."""
        require_human_owner(principal)
        return service.qa_finding_rows(episode_id)

    @router.get("/ui/media/{asset_id}", response_model=None)
    def media(
        asset_id: UUID, principal: Annotated[Principal, Depends(review_principal)]
    ) -> FileResponse:
        require_human_owner(principal)
        file = service.media_file(asset_id)
        return FileResponse(
            file.path,
            media_type=file.media_type,
            headers={**_SECURITY_HEADERS, "Content-Disposition": "inline"},
        )

    return router


def _render_episode(
    request: Request,
    csrf_for: CsrfTokenFor,
    principal: Principal,
    page: EpisodePage,
    *,
    error: dict[str, str] | None,
) -> str:
    view = page.view
    context = _page_context(
        request,
        csrf_for,
        principal,
        title=f"Episode {view.episode_number}",
        heading=f"Episode {view.episode_number} final review",
        page=page,
        error=error,
        can_decide=page.can_decide,
        categories=[c.value for c in FeedbackCategory],
        feedback_rows=FEEDBACK_ROWS,
        keys={
            "approve": new_idempotency_key(),
            "revise": new_idempotency_key(),
            "reject": new_idempotency_key(),
        },
    )
    return render("episode.html", **context)


def _error_dict(exc: Exception) -> dict[str, str]:
    if isinstance(exc, MicrodramaError):
        return {"code": exc.code, "message": exc.message}
    if isinstance(exc, ValidationError):
        return {"code": "SCHEMA_INVALID", "message": validation_message(exc)}
    return {"code": "INTERNAL_ERROR", "message": "the decision could not be recorded"}


__all__ = ["CSRF_COOKIE", "build_router", "csrf_cookie_token"]
