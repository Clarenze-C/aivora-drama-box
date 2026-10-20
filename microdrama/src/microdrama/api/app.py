"""API composition root (integrator-owned).

Module owners export ``build_router(...)`` factories; only this package includes
them. Cross-cutting HTTP concerns live here: contract-error → HTTP mapping,
request-validation → 422, health/readiness. Responses never include secrets.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from microdrama import __version__
from microdrama.config import Settings
from microdrama.contracts.errors import MicrodramaError
from microdrama.contracts.routes import ComponentState, ErrorBody, HealthView, ReadinessView

ReadinessProbe = Callable[[], ComponentState]


@dataclass
class AppComponents:
    """Everything the composition root needs; filled by ``microdrama.api.compose``."""

    settings: Settings
    routers: Sequence[APIRouter] = ()
    database_probe: ReadinessProbe | None = None
    queue_probe: ReadinessProbe | None = None
    object_store_probe: ReadinessProbe | None = None
    extra_setup: list[Callable[[FastAPI], None]] = field(default_factory=list)


def _error_response(
    status: int, code: str, message: str, details: dict | None = None
) -> JSONResponse:
    body = ErrorBody(code=code, message=message, details=details or {})
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(MicrodramaError)
    async def _contract_error(_: Request, exc: MicrodramaError) -> JSONResponse:
        details = {k: v for k, v in exc.details.items() if k not in {"sqlstate"}}
        return _error_response(exc.http_status, exc.code, exc.message, _jsonable(details))

    @app.exception_handler(RequestValidationError)
    async def _request_invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(
            422,
            "SCHEMA_INVALID",
            "request failed schema validation",
            {"errors": _jsonable(_safe_errors(exc.errors()))},
        )

    @app.exception_handler(ValidationError)
    async def _model_invalid(_: Request, exc: ValidationError) -> JSONResponse:
        return _error_response(
            422,
            "SCHEMA_INVALID",
            "payload failed schema validation",
            {"errors": _jsonable(_safe_errors(exc.errors()))},
        )


def _safe_errors(errors: Sequence[dict]) -> list[dict]:
    # Drop echoed input values: they may contain user text or tokens.
    return [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
        for e in errors
    ]


def _jsonable(value: object) -> object:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_jsonable(v) for v in value]
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)


def create_app(components: AppComponents) -> FastAPI:
    settings = components.settings
    app = FastAPI(
        title="microdrama", version=__version__, docs_url=None, redoc_url=None, openapi_url=None
    )
    install_error_handlers(app)

    @app.get("/health", response_model=HealthView)
    def health() -> HealthView:
        return HealthView(version=__version__, execution_mode=settings.execution_mode.value)

    @app.get("/ready", response_model=ReadinessView)
    def ready() -> JSONResponse:
        def probe(fn: ReadinessProbe | None) -> ComponentState:
            if fn is None:
                return ComponentState.NOT_CONFIGURED
            try:
                return fn()
            except Exception:
                return ComponentState.UNAVAILABLE

        view = ReadinessView(
            ready=False,
            database=probe(components.database_probe),
            queue=probe(components.queue_probe),
            config=ComponentState.OK,
            object_store=probe(components.object_store_probe),
        )
        is_ready = all(
            s is ComponentState.OK
            for s in (view.database, view.queue, view.config, view.object_store)
        )
        view = view.model_copy(update={"ready": is_ready})
        return JSONResponse(
            status_code=200 if is_ready else 503, content=view.model_dump(mode="json")
        )

    for router in components.routers:
        app.include_router(router)
    for setup in components.extra_setup:
        setup(app)
    return app
