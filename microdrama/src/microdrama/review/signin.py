"""Server-side enforcement of the pre-session sign-in token (V-38).

The login page's double-submit token used to be purely stateless: any matching (cookie, form)
pair was accepted, so a replayed pair could mint further sessions and the 15-minute TTL lived
only in the cookie's Max-Age. ``SignInTokens`` stores the SHA-256 digest of every issued token
with a server-clock expiry; redemption burns the token atomically, whatever the sign-in attempt
then does (a wrong password consumes it exactly like a success), and the fresh token minted for
the failure page invalidates the one before it. Like every credential, the clear token is never
stored.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.infra import Clock, IdGenerator
from microdrama.core.auth import token_digest
from microdrama.persistence.db import Database, insert_row

TOKEN_BYTES = 32
SIGNIN_TOKEN_TTL_SECONDS = 900


class SignInTokens:
    """Issue and redeem the pre-session sign-in token. No state besides the database."""

    def __init__(self, db: Database, clock: Clock, ids: IdGenerator, *, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            raise SchemaInvalid("ttl_seconds must be positive")
        self._db = db
        self._clock = clock
        self._ids = ids
        self._ttl = timedelta(seconds=ttl_seconds)

    def issue(self) -> str:
        """Mint a fresh token, store its digest, return the clear value (shown once)."""
        token = secrets.token_urlsafe(TOKEN_BYTES)
        now = self._clock.now()
        with self._db.transaction() as tx:
            insert_row(
                tx,
                "login_tokens",
                {
                    "id": self._ids.new_id(),
                    "token_hash": token_digest(token),
                    "created_at": now,
                    "expires_at": now + self._ttl,
                },
                returning="id",
            )
        return token

    def redeem(self, token: str | None) -> bool:
        """Consume a stored, unconsumed, unexpired token atomically; anything else is False.

        The conditional claim-consume is the whole guarantee: a single row can be consumed
        exactly once even under racing replays, and expiry is judged against the server clock.
        """
        if not isinstance(token, str) or not token:
            return False
        now = self._clock.now()
        with self._db.transaction() as tx:
            consumed = tx.execute(
                "UPDATE login_tokens SET consumed_at = %s "
                "WHERE token_hash = %s AND consumed_at IS NULL AND expires_at > %s",
                (now, token_digest(token), now),
            )
        return consumed == 1


__all__ = ["SIGNIN_TOKEN_TTL_SECONDS", "SignInTokens"]
