"""Authentication: owner passwords, review sessions, CSRF tokens and service credentials.

- Passwords: ``hashlib.scrypt`` with a random per-password salt. Stored form:
  ``scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>``.
- Session and service tokens are high-entropy (``secrets.token_urlsafe(32)``); only their
  SHA-256 digests are stored (``token_digest``). Digests are looked up, never printed.
- Human sessions are the only principals that can produce approval events. Service credentials
  (workers, runtime models, webhooks, schedulers) can never be human owners or sessions.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import cache
from uuid import UUID

from pydantic import ValidationError

from microdrama.contracts.enums import PrincipalKind, RuntimeRole
from microdrama.contracts.errors import (
    MicrodramaError,
    NotFound,
    SchemaInvalid,
    Unauthenticated,
    Unauthorized,
)
from microdrama.contracts.infra import Clock, IdGenerator
from microdrama.contracts.principals import Principal
from microdrama.persistence.db import Database, Tx, insert_row

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SCRYPT_MAXMEM = 64 * 1024 * 1024
_MIN_PASSWORD_LENGTH = 12
_USERNAME = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")
_TOKEN_BYTES = 32
_INVALID = "invalid credentials"

# Human-only principal classes; service credentials may not be any of these.
_SERVICE_KINDS = frozenset(
    {
        PrincipalKind.SERVICE_WORKER,
        PrincipalKind.RUNTIME_MODEL,
        PrincipalKind.PROVIDER_WEBHOOK,
        PrincipalKind.SCHEDULER,
    }
)


# --- secrets -----------------------------------------------------------------------------


def hash_secret(secret: str) -> str:
    """Salted scrypt hash of a password (or other low-entropy secret)."""
    if not isinstance(secret, str) or not secret:
        raise SchemaInvalid("secret must be a non-empty string")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        secret.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
        maxmem=_SCRYPT_MAXMEM,
    )
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N,
        _SCRYPT_R,
        _SCRYPT_P,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_secret(secret: str, stored: str) -> bool:
    """True only if ``secret`` matches the stored scrypt hash. Malformed input is False."""
    if not isinstance(secret, str) or not isinstance(stored, str):
        return False
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return False
    try:
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt = base64.b64decode(parts[4], validate=True)
        expected = base64.b64decode(parts[5], validate=True)
        candidate = hashlib.scrypt(
            secret.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
            maxmem=_SCRYPT_MAXMEM,
        )
    except (ValueError, binascii.Error):
        return False
    return hmac.compare_digest(candidate, expected)


def token_digest(token: str) -> str:
    """SHA-256 hex digest of a high-entropy token; the only form that is stored."""
    if not isinstance(token, str) or not token:
        raise SchemaInvalid("token must be a non-empty string")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@cache
def _dummy_hash() -> str:
    """Equalises the cost of an unknown-user login with a wrong-password login."""
    return hash_secret("dummy-password-for-timing-only")


# --- principals --------------------------------------------------------------------------


def require_human_owner(principal: Principal) -> None:
    """Raise ``Unauthorized`` unless the principal is a human owner with a session."""
    if not isinstance(principal, Principal) or not principal.is_human_owner:
        raise Unauthorized("only an authenticated human owner may perform this action")
    if principal.session_id is None:  # pragma: no cover - Principal validation forbids it
        raise Unauthorized("human owner principal has no session")


# --- kind allow-lists (one definition each; every writer and route uses these) -----------

# Automated operators: the deterministic workers and the scheduler. Only these may enqueue jobs or
# read job status through the service channel.
OPERATOR_KINDS: frozenset[PrincipalKind] = frozenset(
    {PrincipalKind.SERVICE_WORKER, PrincipalKind.SCHEDULER}
)
# Who may change season/episode state, outcomes, or read the event outbox. Runtime models only
# propose and provider webhooks are untrusted input until a verified worker handles them, so
# neither kind appears here.
OWNER_OR_OPERATOR_KINDS: frozenset[PrincipalKind] = OPERATOR_KINDS | {PrincipalKind.HUMAN_OWNER}


def require_principal_kind(
    principal: Principal,
    allowed: frozenset[PrincipalKind],
    *,
    action: str,
    error: type[MicrodramaError] = Unauthorized,
) -> None:
    """Raise ``error`` unless the principal's kind is in ``allowed``. Used before any write or read."""
    if not isinstance(principal, Principal) or principal.kind not in allowed:
        kind = principal.kind.value if isinstance(principal, Principal) else "UNKNOWN"
        raise error(f"principal kind {kind} may not {action}", kind=kind)


def require_state_actor(principal: Principal) -> None:
    """Gate for every season/episode state and outcome writer.

    Refuses RUNTIME_MODEL and PROVIDER_WEBHOOK principals with ``Unauthorized``. Human-only moves
    still need their approval on top of this check.
    """
    require_principal_kind(
        principal,
        OWNER_OR_OPERATOR_KINDS,
        action="change season or episode state or outcomes",
        error=Unauthorized,
    )


def owner_id_in_tx(tx: Tx, principal: Principal) -> UUID:
    """The owner behind a human principal's session (read inside the caller's transaction)."""
    require_human_owner(principal)
    row = tx.fetchone(
        "SELECT owner_id FROM human_sessions WHERE id = %s",
        (principal.session_id,),
    )
    if row is None or principal.principal_id != f"owner:{row['owner_id']}":
        raise Unauthorized("human principal does not match its review session")
    return row["owner_id"]


# --- services ----------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionTokens:
    """Returned once by ``AuthService.login``. Tokens are never logged or stored in clear."""

    session_id: UUID
    session_token: str = field(repr=False)
    csrf_token: str = field(repr=False)
    expires_at: datetime


class AuthService:
    """Owner accounts, review sessions and service credentials."""

    def __init__(
        self,
        db: Database,
        clock: Clock,
        ids: IdGenerator,
        *,
        session_ttl: timedelta = timedelta(hours=8),
    ) -> None:
        if session_ttl <= timedelta(0):
            raise SchemaInvalid("session_ttl must be positive")
        self._db = db
        self._clock = clock
        self._ids = ids
        self._ttl = session_ttl

    # -- owners and sessions ----------------------------------------------------------

    def create_owner(self, username: str, password: str) -> UUID:
        if not isinstance(username, str) or not _USERNAME.fullmatch(username):
            raise SchemaInvalid("username must be 1..64 letters, digits, '.', '_' or '-'")
        if not isinstance(password, str) or len(password) < _MIN_PASSWORD_LENGTH:
            raise SchemaInvalid(f"password must be at least {_MIN_PASSWORD_LENGTH} characters")
        owner_id: UUID = self._ids.new_id()
        now = self._clock.now()
        stored = hash_secret(password)  # CPU work stays outside the database transaction
        with self._db.transaction() as tx:
            insert_row(
                tx,
                "owners",
                {
                    "id": owner_id,
                    "username": username,
                    "password_hash": stored,
                    "active": True,
                    "created_at": now,
                    "updated_at": now,
                },
                returning="id",
            )
        return owner_id

    def login(self, username: str, password: str) -> SessionTokens:
        """Open a review session. Unknown user, wrong password and inactive owner look identical."""
        with self._db.transaction(readonly=True) as tx:
            owner = (
                tx.fetchone(
                    "SELECT id, password_hash, active FROM owners WHERE username = %s",
                    (username,),
                )
                if isinstance(username, str)
                else None
            )
        # Verify outside the transaction; an unknown user spends the same scrypt cost.
        if owner is None:
            verify_secret(password if isinstance(password, str) else "", _dummy_hash())
            raise Unauthenticated(_INVALID)
        password_ok = verify_secret(password, owner["password_hash"])
        if not password_ok or not owner["active"]:
            raise Unauthenticated(_INVALID)
        with self._db.transaction() as tx:
            return self._create_session(tx, owner["id"])

    def _create_session(self, tx: Tx, owner_id: UUID) -> SessionTokens:
        session_id: UUID = self._ids.new_id()
        session_token = secrets.token_urlsafe(_TOKEN_BYTES)
        csrf_token = secrets.token_urlsafe(_TOKEN_BYTES)
        created = self._clock.now()
        expires = created + self._ttl
        insert_row(
            tx,
            "human_sessions",
            {
                "id": session_id,
                "owner_id": owner_id,
                "token_hash": token_digest(session_token),
                "csrf_token_hash": token_digest(csrf_token),
                "created_at": created,
                "expires_at": expires,
            },
            returning="id",
        )
        return SessionTokens(
            session_id=session_id,
            session_token=session_token,
            csrf_token=csrf_token,
            expires_at=expires,
        )

    def authenticate_session(self, session_token: str) -> Principal:
        """Principal for a live session cookie; anything else is ``Unauthenticated``."""
        if not isinstance(session_token, str) or not session_token:
            raise Unauthenticated("human session required")
        now = self._clock.now()
        with self._db.transaction() as tx:
            found = tx.fetchone(
                "SELECT hs.id, hs.owner_id, hs.expires_at, hs.revoked_at, o.active "
                "FROM human_sessions hs JOIN owners o ON o.id = hs.owner_id "
                "WHERE hs.token_hash = %s",
                (token_digest(session_token),),
            )
        if (
            found is None
            or found["revoked_at"] is not None
            or found["expires_at"] <= now
            or not found["active"]
        ):
            raise Unauthenticated("human session required")
        return Principal(
            principal_id=f"owner:{found['owner_id']}",
            kind=PrincipalKind.HUMAN_OWNER,
            session_id=found["id"],
        )

    def verify_csrf(self, principal: Principal, csrf_token: str | None) -> None:
        """Unsafe requests must echo the session's CSRF token; mismatch is ``Unauthorized``."""
        require_human_owner(principal)
        now = self._clock.now()
        with self._db.transaction() as tx:
            row = tx.fetchone(
                "SELECT csrf_token_hash, expires_at, revoked_at FROM human_sessions WHERE id = %s",
                (principal.session_id,),
            )
        if row is None or row["revoked_at"] is not None or row["expires_at"] <= now:
            raise Unauthenticated("human session required")
        if not csrf_token or not hmac.compare_digest(
            token_digest(csrf_token), row["csrf_token_hash"]
        ):
            raise Unauthorized("CSRF token missing or does not match the session")

    def revoke_session(self, session_id: UUID) -> None:
        now = self._clock.now()
        with self._db.transaction() as tx:
            row = tx.fetchone("SELECT revoked_at FROM human_sessions WHERE id = %s", (session_id,))
            if row is None:
                raise NotFound("review session not found")
            if row["revoked_at"] is None:
                tx.execute(
                    "UPDATE human_sessions SET revoked_at = %s WHERE id = %s",
                    (now, session_id),
                )

    def owner_id_of(self, principal: Principal) -> UUID:
        with self._db.transaction() as tx:
            return owner_id_in_tx(tx, principal)

    # -- service credentials -----------------------------------------------------------

    def issue_service_credential(
        self,
        principal_id: str,
        kind: PrincipalKind | str,
        *,
        runtime_role: RuntimeRole | str | None = None,
        scopes: tuple[str, ...] | frozenset[str] = (),
    ) -> str:
        """Create a non-human credential. Returns the token once; only its digest is stored."""
        try:
            kind_value = PrincipalKind(kind)
        except ValueError as exc:
            raise SchemaInvalid(f"unknown principal kind {kind!r}") from exc
        if kind_value is PrincipalKind.HUMAN_OWNER:
            raise Unauthorized("human owners cannot hold service credentials")
        try:
            principal = Principal(
                principal_id=principal_id,
                kind=kind_value,
                runtime_role=RuntimeRole(runtime_role) if runtime_role is not None else None,
                scopes=frozenset(scopes),
            )
        except (ValidationError, ValueError) as exc:
            raise SchemaInvalid(f"invalid service credential: {exc}") from exc
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        with self._db.transaction() as tx:
            # Explicit SQL: ``scopes`` is a text[] column, which the jsonb-adapting insert_row
            # helper would not bind correctly.
            tx.execute(
                "INSERT INTO service_credentials (id, principal_id, kind, runtime_role, token_hash, "
                "scopes, active, created_at) VALUES (%s, %s, %s, %s, %s, %s::text[], true, %s)",
                (
                    self._ids.new_id(),
                    principal.principal_id,
                    principal.kind.value,
                    principal.runtime_role.value if principal.runtime_role is not None else None,
                    token_digest(token),
                    sorted(principal.scopes),
                    self._clock.now(),
                ),
            )
        return token

    def authenticate_service(self, token: str) -> Principal:
        """Principal for a live service token. Human sessions never authenticate here."""
        if not isinstance(token, str) or not token:
            raise Unauthenticated("service credential required")
        with self._db.transaction() as tx:
            row = tx.fetchone(
                "SELECT principal_id, kind, runtime_role, scopes, active, revoked_at "
                "FROM service_credentials WHERE token_hash = %s",
                (token_digest(token),),
            )
        if row is None or not row["active"] or row["revoked_at"] is not None:
            raise Unauthenticated("service credential required")
        kind = PrincipalKind(row["kind"])
        if kind not in _SERVICE_KINDS:  # pragma: no cover - the table CHECK forbids it
            raise Unauthenticated("service credential required")
        return Principal(
            principal_id=row["principal_id"],
            kind=kind,
            runtime_role=RuntimeRole(row["runtime_role"]) if row["runtime_role"] else None,
            scopes=frozenset(row["scopes"] or []),
        )

    def revoke_service_credential(self, principal_id: str) -> None:
        now = self._clock.now()
        with self._db.transaction() as tx:
            row = tx.fetchone(
                "SELECT revoked_at FROM service_credentials WHERE principal_id = %s",
                (principal_id,),
            )
            if row is None:
                raise NotFound("service credential not found")
            if row["revoked_at"] is None:
                tx.execute(
                    "UPDATE service_credentials SET revoked_at = %s, active = false "
                    "WHERE principal_id = %s",
                    (now, principal_id),
                )


__all__ = [
    "OPERATOR_KINDS",
    "OWNER_OR_OPERATOR_KINDS",
    "AuthService",
    "SessionTokens",
    "require_principal_kind",
    "require_state_actor",
    "hash_secret",
    "owner_id_in_tx",
    "require_human_owner",
    "token_digest",
    "verify_secret",
]
