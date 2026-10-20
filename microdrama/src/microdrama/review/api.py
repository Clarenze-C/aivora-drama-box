"""HTTP surface of the review module (T008). Exported factory only; the integrator registers it.

JSON (SPEC §4.3): ``GET /seasons/proposals``, ``GET /seasons/{id}``, ``POST /seasons/{id}/approval``,
``GET /episodes/{id}/review``, ``POST /episodes/{id}/review``.

Pages: ``/ui`` (proposals, season decision, episode review with the owner-only media stream
``/ui/media/{asset_id}``) and ``/auth`` (login and logout, which set and clear the ``md_session``
cookie). Every route needs a live human owner session; a request that presents a bearer credential
is authenticated as that service principal and then refused with 403, so workers, models and
schedulers can never read review data or decide. Unsafe requests need the CSRF token.

Status codes: 202 for a queued or recorded decision, 200 with ``status="REPLAYED"`` for a replayed
idempotency key, 409 for stale or conflicting decisions, 422 for invalid input, 403 for refused
principals and CSRF failures, 401 without a session.
"""

from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import ValidationError

from microdrama.contracts.enums import FeedbackCategory, SeasonState
from microdrama.contracts.errors import MicrodramaError, Unauthenticated
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
from microdrama.review.service import EpisodePage, ReviewService

CSRF_COOKIE = "md_csrf"
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
    """Cookie session for humans; a bearer credential is read as a service principal (then 403)."""
    service_principal = service_dependency(auth)

    async def review_principal(request: Request) -> Principal:
        if request.headers.get("authorization") is not None:
            return await service_principal(request)
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


def _page_context(
    request: Request, csrf_for: CsrfTokenFor, principal: Principal | None, **extra: Any
):
    csrf = csrf_for(request) if principal is not None else None
    return {"signed_in": principal is not None, "csrf": csrf, **extra}


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
    router = APIRouter(tags=["review"])
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
        return _html(
            render(
                "login.html",
                title="Sign in",
                heading="Sign in",
                signed_in=False,
                csrf=None,
                error=None,
                username="",
            )
        )

    @router.post("/auth/login", response_model=None)
    def login_submit(
        username: Annotated[str, Form(max_length=64)],
        password: Annotated[str, Form(max_length=512)],
    ) -> Response:
        try:
            tokens = auth.login(username, password)
        except Unauthenticated:
            body = render(
                "login.html",
                title="Sign in",
                heading="Sign in",
                signed_in=False,
                csrf=None,
                error={"code": "UNAUTHENTICATED", "message": "Invalid username or password."},
                username=username,
            )
            return _html(body, status=401)
        response = RedirectResponse("/ui/seasons", status_code=303, headers=dict(_SECURITY_HEADERS))
        _set_session_cookies(response, tokens, secure=cookie_secure)
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
