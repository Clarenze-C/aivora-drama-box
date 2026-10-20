"""Typed error taxonomy shared by every module (SPEC §4.3).

Each error carries a stable ``code`` and the HTTP status the API layer maps it
to. Modules raise these types instead of inventing their own; the API
composition root translates them into responses. Never convert one of these
into a success response.
"""

from __future__ import annotations

from typing import Any, ClassVar


class MicrodramaError(Exception):
    """Base class. ``code`` is stable and safe to show in the review UI."""

    code: ClassVar[str] = "INTERNAL_ERROR"
    http_status: ClassVar[int] = 500

    def __init__(self, message: str = "", **details: Any) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


# --- 4xx: caller/command problems -------------------------------------------


class SchemaInvalid(MicrodramaError):
    code = "SCHEMA_INVALID"
    http_status = 422


class UnsupportedSchemaVersion(SchemaInvalid):
    code = "UNSUPPORTED_SCHEMA_VERSION"


class UnsupportedControl(SchemaInvalid):
    """A required control cannot be honoured; it must never be silently dropped."""

    code = "UNSUPPORTED_CONTROL"


class Unauthenticated(MicrodramaError):
    code = "UNAUTHENTICATED"
    http_status = 401


class Unauthorized(MicrodramaError):
    """Authenticated principal lacks permission (e.g. a worker trying to approve)."""

    code = "UNAUTHORIZED"
    http_status = 403


class PolicyDenied(MicrodramaError):
    code = "POLICY_DENIED"
    http_status = 403


class EffectDenied(PolicyDenied):
    """A paid/cloud/public effect was attempted while disabled (offline mock mode)."""

    code = "EFFECT_DENIED"


class RightsUncleared(PolicyDenied):
    code = "RIGHTS_UNCLEARED"


class CapabilityUnavailable(PolicyDenied):
    code = "CAPABILITY_UNAVAILABLE"


class IdentityLockRequired(PolicyDenied):
    """Later-episode render dispatch attempted before the episode-one identity lock."""

    code = "IDENTITY_LOCK_REQUIRED"


class NotFound(MicrodramaError):
    code = "NOT_FOUND"
    http_status = 404


class Conflict(MicrodramaError):
    code = "CONFLICT"
    http_status = 409


class StaleRevision(Conflict):
    """Expected revision/package hash no longer matches the current entity."""

    code = "STALE_REVISION"


class IdempotencyConflict(Conflict):
    """Idempotency key reused with different request content."""

    code = "IDEMPOTENCY_CONFLICT"


class DuplicateSemanticKey(Conflict):
    code = "DUPLICATE_SEMANTIC_KEY"


class InvalidTransition(Conflict):
    code = "INVALID_TRANSITION"


class GateNotReady(Conflict):
    """Gate 2 requested for a package whose release conditions are not satisfied."""

    code = "GATE_NOT_READY"


# --- Budget ------------------------------------------------------------------


class BudgetError(MicrodramaError):
    code = "BUDGET_ERROR"
    http_status = 409


class BudgetExhausted(BudgetError):
    code = "BUDGET_EXHAUSTED"


class UnknownPrice(BudgetError):
    """Unknown price/currency/FX or unbounded exposure blocks paid dispatch."""

    code = "UNKNOWN_PRICE"


class ProtectedReserveViolation(BudgetError):
    code = "PROTECTED_RESERVE_VIOLATION"


# --- External/provider outcomes ----------------------------------------------


class ProviderError(MicrodramaError):
    code = "PROVIDER_ERROR"
    http_status = 502
    transient: ClassVar[bool] = False


class TransientProviderError(ProviderError):
    code = "PROVIDER_TRANSIENT"
    transient = True


class RateLimited(TransientProviderError):
    code = "RATE_LIMITED"
    http_status = 429


class NeedsReconciliation(ProviderError):
    """Outcome of an external side effect is ambiguous; reconcile, never blindly resubmit."""

    code = "NEEDS_RECONCILIATION"


class ServiceUnavailable(MicrodramaError):
    code = "SERVICE_UNAVAILABLE"
    http_status = 503


ERROR_TYPES: tuple[type[MicrodramaError], ...] = (
    MicrodramaError,
    SchemaInvalid,
    UnsupportedSchemaVersion,
    UnsupportedControl,
    Unauthenticated,
    Unauthorized,
    PolicyDenied,
    EffectDenied,
    RightsUncleared,
    CapabilityUnavailable,
    IdentityLockRequired,
    NotFound,
    Conflict,
    StaleRevision,
    IdempotencyConflict,
    DuplicateSemanticKey,
    InvalidTransition,
    GateNotReady,
    BudgetError,
    BudgetExhausted,
    UnknownPrice,
    ProtectedReserveViolation,
    ProviderError,
    TransientProviderError,
    RateLimited,
    NeedsReconciliation,
    ServiceUnavailable,
)
