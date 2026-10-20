"""Pure core primitives (no database): clock, id generator, secret hashing, token digests."""

from __future__ import annotations

import base64
import uuid
from datetime import timedelta

import pytest

from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.infra import Clock, IdGenerator
from microdrama.core.auth import hash_secret, token_digest, verify_secret
from microdrama.core.clock import SystemClock, UuidIds
from microdrama.core.jobs import Failed, NeedsReconciliation, RetryLater, Succeeded, WaitExternal


def test_system_clock_is_aware_utc_and_conforms_to_protocol() -> None:
    clock = SystemClock()
    assert isinstance(clock, Clock)
    now = clock.now()
    assert now.utcoffset() == timedelta(0)


def test_uuid_ids_are_unique_uuid4_values() -> None:
    ids = UuidIds()
    assert isinstance(ids, IdGenerator)
    values = {ids.new_id() for _ in range(500)}
    assert len(values) == 500
    assert all(v.version == 4 for v in values)
    assert all(isinstance(v, uuid.UUID) for v in values)


def test_hash_secret_is_salted_and_verifies_only_the_right_secret() -> None:
    stored = hash_secret("correct horse battery staple")
    parts = stored.split("$")
    assert parts[0] == "scrypt" and len(parts) == 6
    assert verify_secret("correct horse battery staple", stored) is True
    assert verify_secret("correct horse battery stapl3", stored) is False
    assert verify_secret("", stored) is False
    # A fresh salt makes two hashes of one password differ, yet both verify.
    other = hash_secret("correct horse battery staple")
    assert other != stored
    assert verify_secret("correct horse battery staple", other) is True


@pytest.mark.parametrize(
    "malformed",
    [
        "",
        "plain-text-password",
        "md5$1$2$3$AAAA$BBBB",
        "scrypt$16384$8$1$%%%notb64%%%$AAAA",
        "scrypt$x$8$1$AAAA$AAAA",
        "scrypt$16384$8$1$AAAA",
    ],
)
def test_verify_secret_rejects_malformed_stored_hashes(malformed: str) -> None:
    assert verify_secret("anything at all", malformed) is False


def test_stored_hash_never_contains_the_plain_secret() -> None:
    secret = "plaintext-marker-9f3c1a"
    stored = hash_secret(secret)
    assert secret not in stored
    salt_b64, digest_b64 = stored.split("$")[4:6]
    assert base64.b64decode(salt_b64) and base64.b64decode(digest_b64)


def test_secret_hashing_refuses_empty_input() -> None:
    with pytest.raises(SchemaInvalid):
        hash_secret("")


def test_token_digest_is_sha256_hex_and_deterministic() -> None:
    digest = token_digest("token-abc")
    assert len(digest) == 64 and set(digest) <= set("0123456789abcdef")
    assert digest == token_digest("token-abc")
    assert digest != token_digest("token-abd")
    with pytest.raises(SchemaInvalid):
        token_digest("")


def test_outcome_types_are_frozen_value_objects() -> None:
    outcome = WaitExternal(external_id="prov-1", poll_after_ms=5_000)
    with pytest.raises(AttributeError):
        outcome.poll_after_ms = 1  # type: ignore[misc]
    assert Succeeded(result={"ok": 1}) == Succeeded(result={"ok": 1})
    assert RetryLater("RATE_LIMITED", 100).error_code == "RATE_LIMITED"
    assert Failed("BAD_INPUT").detail == ""
    assert NeedsReconciliation("timeout after submit").external_id is None
