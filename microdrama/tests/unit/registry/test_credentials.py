"""Credential references: Secret cannot print or serialise, locators are names not values, mock mode
denies resolution, and missing, revoked or NONE references are unavailable."""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import pytest
from registry_support import live_settings, mock_settings

from microdrama.contracts.errors import (
    CapabilityUnavailable,
    DuplicateSemanticKey,
    EffectDenied,
    NotFound,
    PolicyDenied,
    SchemaInvalid,
)
from microdrama.core.registry import (
    CredentialStore,
    CredentialStoreKind,
    Secret,
    assert_no_secrets,
    redactor,
)
from microdrama.persistence import Database

VALUE = "mdtest-sup3r-secret-7f3a9c21d4e8b06a55c1"
SECOND = "mdtest-second-secret-0a1b2c3d4e5f"
REF = "credref:provider-voice-key"
ENV_NAME = "MICRODRAMA_TEST_PROVIDER_KEY"


# --- Secret ------------------------------------------------------------------------


def test_a_secret_never_shows_its_value_in_any_text_form() -> None:
    secret = Secret(VALUE)
    renderings = [
        repr(secret),
        str(secret),
        f"{secret}",
        f"{secret!r}",
        f"{secret:>40}",
        "%s" % secret,  # noqa: UP031  # percent formatting is one of the paths under test
        "{}".format(secret),  # noqa: UP032
        "{!r}".format(secret),  # noqa: UP032
        str([secret]),
        str({"key": secret}),
    ]
    for rendering in renderings:
        assert VALUE not in rendering
    assert repr(secret) == "Secret(***)"
    assert str(secret) == "Secret(***)"


def test_reveal_is_the_only_way_to_read_the_value() -> None:
    secret = Secret(VALUE)
    assert secret.reveal() == VALUE
    assert not hasattr(secret, "__dict__")  # __slots__: the value is not in vars()
    with pytest.raises(TypeError):
        vars(secret)


def test_a_secret_cannot_be_serialised_or_pickled() -> None:
    secret = Secret(VALUE)
    with pytest.raises(TypeError):
        json.dumps(secret)
    with pytest.raises(TypeError) as caught:
        pickle.dumps(secret)
    assert VALUE not in str(caught.value)


def test_copies_keep_the_value_and_stay_masked() -> None:
    import copy

    secret = Secret(VALUE)
    for clone in (copy.copy(secret), copy.deepcopy(secret)):
        assert clone.reveal() == VALUE
        assert repr(clone) == "Secret(***)"


def test_a_secret_must_be_text() -> None:
    with pytest.raises(SchemaInvalid):
        Secret(12345)  # type: ignore[arg-type]


def test_redactor_replaces_every_revealed_value_longest_first() -> None:
    redact = redactor(Secret(VALUE), Secret(SECOND))
    text = f"header {VALUE} body {SECOND} tail {VALUE}"
    cleaned = redact(text)
    assert VALUE not in cleaned and SECOND not in cleaned
    assert cleaned == "header *** body *** tail ***"
    # A partial prefix is not the secret, so it is left alone.
    assert redact(VALUE[:10]) == VALUE[:10]


def test_redactor_rejects_plain_strings() -> None:
    with pytest.raises(SchemaInvalid):
        redactor(VALUE)  # type: ignore[arg-type]


def test_assert_no_secrets_refuses_text_that_carries_a_value() -> None:
    assert_no_secrets("nothing sensitive here", [Secret(VALUE)])
    with pytest.raises(PolicyDenied) as caught:
        assert_no_secrets(f"leaked {VALUE}", [Secret(VALUE)])
    assert VALUE not in caught.value.message
    assert VALUE not in str(caught.value)


# --- register: locators are names, never values -------------------------------------------


@pytest.mark.db
def test_a_valid_environment_name_registers(db: Database) -> None:
    store = CredentialStore(db, mock_settings(), environ={})
    store.register(
        ref=REF, purpose="voice API", provider="fake-voice", store="ENV", locator=ENV_NAME
    )
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone("SELECT store, locator FROM credential_refs WHERE ref = %s", (REF,))
    assert row == {"store": "ENV", "locator": ENV_NAME}


@pytest.mark.db
@pytest.mark.parametrize(
    "locator",
    [
        "sk-live-9f8e7d6c5b4a3210fedcba98",  # a token shape, lower case
        "MICRODRAMA_KEY=abcdef",  # name=value
        "KEY:abcdef",  # colon
        "MY KEY",  # whitespace
        "lower_case_name",  # not an environment variable name
        "A" * 65,  # longer than 64 characters
        "SK_LIVE_0123456789ABCDEFGHIJKLMNOP",  # opaque upper-case token
        "",
    ],
)
def test_an_env_locator_that_looks_like_a_value_is_refused_without_echo(
    db: Database, locator: str
) -> None:
    store = CredentialStore(db, mock_settings(), environ={})
    with pytest.raises(SchemaInvalid) as caught:
        store.register(
            ref=REF, purpose="voice API", provider="fake-voice", store="ENV", locator=locator
        )
    if locator:
        assert locator not in caught.value.message
        assert locator not in str(caught.value.details)


@pytest.mark.db
@pytest.mark.parametrize(
    ("store_kind", "locator"),
    [
        ("FILE", "/run/secrets/microdrama/review.key"),
        ("VAULT", "secret/data/microdrama/voice"),
    ],
)
def test_path_locators_for_file_and_vault_register(
    db: Database, store_kind: str, locator: str
) -> None:
    store = CredentialStore(db, mock_settings(), environ={})
    store.register(ref=REF, purpose="p", provider="fake", store=store_kind, locator=locator)


@pytest.mark.db
@pytest.mark.parametrize(
    "locator",
    [
        "../../etc/passwd",
        "/run/secrets/a b",
        "kv/" + "Zq9rT2mW8xL4nB6vC1sD3fG5hJ7kM9pQ",  # opaque token segment
        "config=/run/secrets/key",
        "relative/review.key",  # a FILE locator must be absolute
    ],
)
def test_file_locators_that_are_not_names_or_paths_are_refused(db: Database, locator: str) -> None:
    store = CredentialStore(db, mock_settings(), environ={})
    with pytest.raises(SchemaInvalid) as caught:
        store.register(ref=REF, purpose="p", provider="fake", store="FILE", locator=locator)
    assert locator not in caught.value.message


@pytest.mark.db
def test_a_none_reference_carries_no_locator(db: Database) -> None:
    store = CredentialStore(db, mock_settings(), environ={})
    store.register(ref=REF, purpose="public feed", provider="fake", store="NONE", locator="")
    with pytest.raises(SchemaInvalid):
        store.register(
            ref="credref:other-public", purpose="p", provider="fake", store="NONE", locator="X"
        )


@pytest.mark.db
def test_bad_ref_store_and_duplicate_are_refused(db: Database) -> None:
    store = CredentialStore(db, mock_settings(), environ={})
    with pytest.raises(SchemaInvalid):
        store.register(ref="plain-name", purpose="p", provider="f", store="ENV", locator=ENV_NAME)
    with pytest.raises(SchemaInvalid):
        store.register(ref=REF, purpose="p", provider="f", store="KEYCHAIN", locator=ENV_NAME)
    store.register(ref=REF, purpose="p", provider="f", store="ENV", locator=ENV_NAME)
    with pytest.raises(DuplicateSemanticKey):
        store.register(ref=REF, purpose="p", provider="f", store="ENV", locator=ENV_NAME)


# --- resolve -------------------------------------------------------------------------------


@pytest.mark.db
@pytest.mark.parametrize(
    ("store_kind", "locator"),
    [("ENV", ENV_NAME), ("FILE", "/run/secrets/microdrama/review.key"), ("VAULT", "kv/data/voice")],
)
def test_resolution_is_denied_in_offline_mock_for_every_secret_store(
    db: Database, store_kind: str, locator: str
) -> None:
    store = CredentialStore(db, mock_settings(), environ={ENV_NAME: VALUE})
    store.register(ref=REF, purpose="p", provider="f", store=store_kind, locator=locator)
    with pytest.raises(EffectDenied) as caught:
        store.resolve_secret(REF)
    assert VALUE not in str(caught.value)
    with pytest.raises(EffectDenied):
        store.resolve(REF)


@pytest.mark.db
def test_a_live_environment_reference_resolves_to_a_masked_secret(db: Database) -> None:
    store = CredentialStore(db, live_settings(), environ={ENV_NAME: VALUE})
    store.register(ref=REF, purpose="p", provider="f", store="ENV", locator=ENV_NAME)
    secret = store.resolve_secret(REF)
    assert isinstance(secret, Secret)
    assert secret.reveal() == VALUE
    assert VALUE not in f"{secret}"
    assert store.resolve(REF) == VALUE


@pytest.mark.db
def test_a_missing_environment_variable_is_unavailable_and_names_only_the_variable(
    db: Database,
) -> None:
    store = CredentialStore(db, live_settings(), environ={})
    store.register(ref=REF, purpose="p", provider="f", store="ENV", locator=ENV_NAME)
    with pytest.raises(CapabilityUnavailable) as caught:
        store.resolve_secret(REF)
    assert ENV_NAME in caught.value.message


@pytest.mark.db
def test_an_empty_environment_variable_is_unavailable(db: Database) -> None:
    store = CredentialStore(db, live_settings(), environ={ENV_NAME: ""})
    store.register(ref=REF, purpose="p", provider="f", store="ENV", locator=ENV_NAME)
    with pytest.raises(CapabilityUnavailable):
        store.resolve_secret(REF)


@pytest.mark.db
def test_unregistered_and_revoked_references_are_unavailable(db: Database) -> None:
    store = CredentialStore(db, live_settings(), environ={ENV_NAME: VALUE})
    with pytest.raises(CapabilityUnavailable):
        store.resolve_secret("credref:never-registered")
    store.register(ref=REF, purpose="p", provider="f", store="ENV", locator=ENV_NAME)
    assert store.resolve(REF) == VALUE
    store.revoke(REF)
    store.revoke(REF)  # idempotent
    with pytest.raises(CapabilityUnavailable) as caught:
        store.resolve_secret(REF)
    assert "revoked" in caught.value.message
    assert VALUE not in caught.value.message


@pytest.mark.db
def test_revoking_an_unknown_reference_is_not_found(db: Database) -> None:
    with pytest.raises(NotFound):
        CredentialStore(db, mock_settings(), environ={}).revoke("credref:never-registered")


@pytest.mark.db
def test_a_none_reference_has_no_secret_to_resolve(db: Database) -> None:
    store = CredentialStore(db, live_settings(), environ={})
    store.register(ref=REF, purpose="public", provider="f", store="NONE", locator="")
    with pytest.raises(CapabilityUnavailable):
        store.resolve_secret(REF)


@pytest.mark.db
def test_a_vault_reference_is_unavailable_in_this_build(db: Database) -> None:
    store = CredentialStore(db, live_settings(), environ={})
    store.register(ref=REF, purpose="p", provider="f", store="VAULT", locator="kv/data/voice")
    with pytest.raises(CapabilityUnavailable):
        store.resolve_secret(REF)


@pytest.mark.db
def test_a_file_reference_reads_strips_only_the_line_end(db: Database, tmp_path: Path) -> None:
    key_file = tmp_path / "review.key"
    key_file.write_text(VALUE + "\n", encoding="utf-8")
    store = CredentialStore(db, live_settings(), environ={})
    store.register(ref=REF, purpose="p", provider="f", store="FILE", locator=str(key_file))
    assert store.resolve(REF) == VALUE


@pytest.mark.db
def test_an_unreadable_file_reference_never_echoes_its_bytes(db: Database, tmp_path: Path) -> None:
    key_file = tmp_path / "bad.key"
    key_file.write_bytes(b"\xff\xfe" + VALUE.encode("ascii"))  # not valid UTF-8
    store = CredentialStore(db, live_settings(), environ={})
    store.register(ref=REF, purpose="p", provider="f", store="FILE", locator=str(key_file))
    with pytest.raises(CapabilityUnavailable) as caught:
        store.resolve_secret(REF)
    assert VALUE not in caught.value.message
    assert VALUE not in str(caught.value.details)


@pytest.mark.db
def test_an_empty_file_reference_is_unavailable(db: Database, tmp_path: Path) -> None:
    key_file = tmp_path / "empty.key"
    key_file.write_text("\n", encoding="utf-8")
    store = CredentialStore(db, live_settings(), environ={})
    store.register(ref=REF, purpose="p", provider="f", store="FILE", locator=str(key_file))
    with pytest.raises(CapabilityUnavailable):
        store.resolve_secret(REF)


def test_the_store_kinds_are_the_four_database_values() -> None:
    assert {kind.value for kind in CredentialStoreKind} == {"ENV", "FILE", "VAULT", "NONE"}
