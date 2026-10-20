"""Credential references and secret resolution. Secret values never enter a registry row.

The database stores only a ``credref:`` name, the store kind (ENV, FILE, VAULT or NONE) and a
locator: the NAME of an environment variable, a file path, or a vault path. A locator that looks
like a value is refused, and the refusal never echoes it. Resolution happens only at the edge,
outside OFFLINE_MOCK, and returns a ``Secret`` that refuses to print itself.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any, NoReturn

from microdrama.config import Settings
from microdrama.contracts.errors import (
    CapabilityUnavailable,
    EffectDenied,
    NotFound,
    PolicyDenied,
    SchemaInvalid,
)
from microdrama.persistence.db import Database

_REF = re.compile(r"^credref:[a-z0-9][a-z0-9._\-]{1,120}$")
# Every ENV locator is a variable NAME under this prefix. A value (a token, a password) cannot
# look like such a name, so a secret pasted into a locator field is refused.
ENV_LOCATOR_PREFIX = "MICRODRAMA_"
_MAX_ENV_LOCATOR = 64
_ENV_NAME = re.compile(rf"^{re.escape(ENV_LOCATOR_PREFIX)}[A-Z0-9_]+$")
_PATH = re.compile(r"^/?[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)*$")
_MAX_PATH_LOCATOR = 256
_MAX_TEXT = 200


class CredentialStoreKind(StrEnum):
    ENV = "ENV"
    FILE = "FILE"
    VAULT = "VAULT"
    NONE = "NONE"


class Secret:
    """A secret value that cannot be printed, formatted, serialised or dumped by accident.

    ``repr``, ``str`` and every format spec show ``Secret(***)``. ``reveal()`` is the only way to
    read the value. The class uses ``__slots__`` so the value is not in ``vars()``. Pickling is
    refused. This guards against accidental leaks; it is not a sandbox against deliberate access.
    """

    __slots__ = ("_value",)
    _MASK = "Secret(***)"

    def __init__(self, value: str) -> None:
        if not isinstance(value, str):
            raise SchemaInvalid("secret value must be text")
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return self._MASK

    def __str__(self) -> str:
        return self._MASK

    def __format__(self, format_spec: str) -> str:
        return self._MASK

    def __reduce_ex__(self, protocol: object) -> NoReturn:
        raise TypeError("Secret values cannot be serialised")

    def __copy__(self) -> Secret:
        return Secret(self._value)

    def __deepcopy__(self, memo: dict[int, Any]) -> Secret:
        return Secret(self._value)


class CredentialStore:
    """Registers credential references and resolves them at the edge (never in OFFLINE_MOCK)."""

    def __init__(
        self,
        db: Database,
        settings: Settings,
        environ: Mapping[str, str] = os.environ,
    ) -> None:
        self._db = db
        self._settings = settings
        self._environ = environ

    def register(
        self,
        *,
        ref: str,
        purpose: str,
        provider: str,
        store: CredentialStoreKind | str,
        locator: str,
    ) -> None:
        """Store a reference. The locator must be a name or path, never a value."""
        if not isinstance(ref, str) or not _REF.fullmatch(ref):
            raise SchemaInvalid("credential ref must match credref:<name>")
        for field, text in (("purpose", purpose), ("provider", provider)):
            if not isinstance(text, str) or not (1 <= len(text) <= _MAX_TEXT) or "\n" in text:
                raise SchemaInvalid(f"credential {field} must be 1..200 characters on one line")
        kind = _store_kind(store)
        _check_locator(kind, locator)
        # A second registration of the same ref raises DuplicateSemanticKey from the database.
        with self._db.transaction() as tx:
            tx.execute(
                "INSERT INTO credential_refs (ref, purpose, provider, store, locator) "
                "VALUES (%s, %s, %s, %s, %s)",
                (ref, purpose, provider, kind.value, locator),
            )

    def revoke(self, ref: str) -> None:
        """Mark a reference revoked. Revoked references never resolve again."""
        if not isinstance(ref, str) or not _REF.fullmatch(ref):
            raise SchemaInvalid("credential ref must match credref:<name>")
        with self._db.transaction() as tx:
            touched = tx.execute(
                "UPDATE credential_refs SET revoked_at = coalesce(revoked_at, now()) WHERE ref = %s",
                (ref,),
            )
        if touched == 0:
            raise NotFound(f"credential ref {ref} is not registered")

    def resolve_secret(self, ref: str) -> Secret:
        """Resolve a reference to a ``Secret``.

        Missing, revoked, or NONE references raise ``CapabilityUnavailable``. Any ENV, FILE or
        VAULT reference raises ``EffectDenied`` in OFFLINE_MOCK, where no real credential is ever
        read. Error messages name the reference and the variable or path, never the value.
        """
        if not isinstance(ref, str) or not _REF.fullmatch(ref):
            raise SchemaInvalid("credential ref must match credref:<name>")
        with self._db.transaction(readonly=True) as tx:
            row = tx.fetchone(
                "SELECT store, locator, revoked_at FROM credential_refs WHERE ref = %s", (ref,)
            )
        if row is None:
            raise CapabilityUnavailable(f"credential ref {ref} is not registered")
        if row["revoked_at"] is not None:
            raise CapabilityUnavailable(f"credential ref {ref} is revoked")
        kind = CredentialStoreKind(row["store"])
        if kind is CredentialStoreKind.NONE:
            raise CapabilityUnavailable(f"credential ref {ref} names no secret store")
        if self._settings.is_offline_mock:
            raise EffectDenied(
                f"credential resolution for {ref} is denied in OFFLINE_MOCK",
                credential_ref=ref,
                store=kind.value,
            )
        return Secret(self._read(ref, kind, row["locator"]))

    def resolve(self, ref: str) -> str:
        """``CredentialResolver`` protocol: the plain value, for edge code only. Never log it."""
        return self.resolve_secret(ref).reveal()

    def _read(self, ref: str, kind: CredentialStoreKind, locator: str) -> str:
        if kind is CredentialStoreKind.ENV:
            value = self._environ.get(locator)
            if not value:
                raise CapabilityUnavailable(
                    f"credential ref {ref}: environment variable {locator} is not set",
                    credential_ref=ref,
                )
            return value
        if kind is CredentialStoreKind.FILE:
            return _read_file(ref, locator)
        raise CapabilityUnavailable(
            f"credential ref {ref}: no VAULT resolver is configured in this build",
            credential_ref=ref,
        )


def redactor(*secrets: Secret) -> Callable[[str], str]:
    """Return a function that replaces every revealed secret value in text with ``***``."""
    for secret in secrets:
        if not isinstance(secret, Secret):
            raise SchemaInvalid("redactor accepts Secret values only")
    values = sorted({s.reveal() for s in secrets if s.reveal()}, key=len, reverse=True)

    def redact(text: str) -> str:
        out = text
        for value in values:
            out = out.replace(value, "***")
        return out

    return redact


def assert_no_secrets(text: str, secrets: Iterable[Secret]) -> None:
    """Refuse output that would carry a secret value. The error never repeats the value."""
    if not isinstance(text, str):
        raise SchemaInvalid("assert_no_secrets checks text only")
    for secret in secrets:
        if not isinstance(secret, Secret):
            raise SchemaInvalid("assert_no_secrets accepts Secret values only")
        value = secret.reveal()
        if value and value in text:
            raise PolicyDenied("secret material must not appear in this output")


# --- helpers ------------------------------------------------------------------------


def _store_kind(value: object) -> CredentialStoreKind:
    try:
        return CredentialStoreKind(value)
    except ValueError:
        raise SchemaInvalid("credential store must be ENV, FILE, VAULT or NONE") from None


def _looks_opaque(locator: str) -> bool:
    """Heuristic: long or mixed letter-and-digit runs look like a token rather than a name."""
    for part in re.split(r"[_/.\-]", locator):
        if len(part) >= 40:
            return True
        if len(part) >= 20 and re.search(r"[A-Za-z]", part) and re.search(r"[0-9]", part):
            return True
    return False


def _check_locator(kind: CredentialStoreKind, locator: object) -> None:
    if kind is CredentialStoreKind.NONE:
        if locator != "":
            raise SchemaInvalid("NONE credential refs carry no locator")
        return
    if not isinstance(locator, str) or not locator:
        raise SchemaInvalid("credential locator is required")
    # Messages below never repeat the locator: it may be the secret itself.
    if kind is CredentialStoreKind.ENV:
        if (
            not _ENV_NAME.fullmatch(locator)
            or len(locator) > _MAX_ENV_LOCATOR
            or _looks_opaque(locator)  # defence in depth: token-shaped names are refused too
        ):
            raise SchemaInvalid(
                f"ENV locator must be an environment variable NAME starting with "
                f"{ENV_LOCATOR_PREFIX} (A-Z, 0-9, underscore; max {_MAX_ENV_LOCATOR} characters), "
                "never a value"
            )
        return
    path_ok = (
        len(locator) <= _MAX_PATH_LOCATOR
        and bool(_PATH.fullmatch(locator))
        and ".." not in locator.split("/")
        # A secret file must not depend on the working directory of the process.
        and (kind is not CredentialStoreKind.FILE or locator.startswith("/"))
    )
    if not path_ok or _looks_opaque(locator):
        raise SchemaInvalid(
            f"{kind.value} locator must be a path-like reference (no whitespace, '=' or ':'; "
            f"max {_MAX_PATH_LOCATOR} characters), never a value"
        )


def _read_file(ref: str, locator: str) -> str:
    try:
        value = Path(locator).read_text(encoding="utf-8").rstrip("\r\n")
    except (OSError, UnicodeDecodeError):
        # The exception text is dropped on purpose: decode errors can quote file bytes.
        raise CapabilityUnavailable(
            f"credential ref {ref}: secret file is not readable", credential_ref=ref
        ) from None
    if not value:
        raise CapabilityUnavailable(
            f"credential ref {ref}: secret file is empty", credential_ref=ref
        )
    return value


__all__ = [
    "CredentialStore",
    "CredentialStoreKind",
    "Secret",
    "assert_no_secrets",
    "redactor",
]
