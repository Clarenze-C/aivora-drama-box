"""Authentication against the real database: owners, review sessions, CSRF and service credentials."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from microdrama.contracts.enums import PrincipalKind, RuntimeRole
from microdrama.contracts.errors import (
    DuplicateSemanticKey,
    NotFound,
    SchemaInvalid,
    Unauthenticated,
    Unauthorized,
)
from microdrama.contracts.principals import Principal
from microdrama.core.auth import AuthService, require_human_owner
from microdrama.persistence import Database

pytestmark = pytest.mark.db
PASSWORD = "a-long-review-password"


@pytest.fixture
def auth(db: Database, clock, ids) -> AuthService:
    return AuthService(db, clock, ids, session_ttl=timedelta(hours=8))


@pytest.fixture
def owner_login(auth: AuthService) -> tuple[object, str]:
    owner_id = auth.create_owner("reviewer.one", PASSWORD)
    return owner_id, "reviewer.one"


def test_login_issues_a_session_that_authenticates_as_that_human(auth, owner_login, clock) -> None:
    owner_id, username = owner_login
    tokens = auth.login(username, PASSWORD)
    principal = auth.authenticate_session(tokens.session_token)
    assert principal.kind is PrincipalKind.HUMAN_OWNER
    assert principal.principal_id == f"owner:{owner_id}"
    assert principal.session_id == tokens.session_id
    assert auth.owner_id_of(principal) == owner_id
    assert tokens.expires_at == clock.now() + timedelta(hours=8)


def test_stored_secrets_are_digests_not_the_tokens(auth, owner_login, db) -> None:
    _, username = owner_login
    tokens = auth.login(username, PASSWORD)
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT token_hash, csrf_token_hash FROM human_sessions WHERE id = %s",
            (tokens.session_id,),
        )
        owner = tx.fetchone("SELECT password_hash FROM owners WHERE username = %s", (username,))
    assert row["token_hash"] != tokens.session_token
    assert row["csrf_token_hash"] != tokens.csrf_token
    assert len(row["token_hash"]) == 64 and len(row["csrf_token_hash"]) == 64
    assert PASSWORD not in owner["password_hash"]
    assert owner["password_hash"].startswith("scrypt$")


def test_tokens_are_not_shown_in_repr(auth, owner_login) -> None:
    _, username = owner_login
    tokens = auth.login(username, PASSWORD)
    text = repr(tokens)
    assert tokens.session_token not in text and tokens.csrf_token not in text


@pytest.mark.parametrize(
    "username, password",
    [
        ("reviewer.one", "wrong-password-entirely"),
        ("no-such-owner", PASSWORD),
        ("no-such-owner", "wrong-password-entirely"),
    ],
)
def test_bad_credentials_get_one_indistinguishable_error(
    auth, owner_login, username, password
) -> None:
    with pytest.raises(Unauthenticated) as err:
        auth.login(username, password)
    assert err.value.message == "invalid credentials"


def test_inactive_owner_cannot_log_in(auth, owner_login, db) -> None:
    _, username = owner_login
    with db.transaction() as tx:
        tx.execute("UPDATE owners SET active = false WHERE username = %s", (username,))
    with pytest.raises(Unauthenticated):
        auth.login(username, PASSWORD)


def test_password_policy_and_duplicate_usernames(auth, owner_login) -> None:
    with pytest.raises(SchemaInvalid):
        auth.create_owner("short.pw", "tiny")
    with pytest.raises(SchemaInvalid):
        auth.create_owner("has spaces", PASSWORD)
    with pytest.raises(DuplicateSemanticKey):
        auth.create_owner("reviewer.one", PASSWORD)


def test_unknown_or_forged_session_tokens_are_unauthenticated(auth) -> None:
    for bogus in ("", "not-a-real-session-token", "x" * 43):
        with pytest.raises(Unauthenticated):
            auth.authenticate_session(bogus)


def test_session_expires_on_the_injected_clock(auth, owner_login, clock) -> None:
    _, username = owner_login
    tokens = auth.login(username, PASSWORD)
    clock.advance(seconds=8 * 3600 - 1)
    assert auth.authenticate_session(tokens.session_token).session_id == tokens.session_id
    clock.advance(seconds=2)
    with pytest.raises(Unauthenticated):
        auth.authenticate_session(tokens.session_token)


def test_revoked_session_is_refused_and_revoking_twice_is_harmless(auth, owner_login) -> None:
    _, username = owner_login
    tokens = auth.login(username, PASSWORD)
    auth.revoke_session(tokens.session_id)
    auth.revoke_session(tokens.session_id)
    with pytest.raises(Unauthenticated):
        auth.authenticate_session(tokens.session_token)
    with pytest.raises(NotFound):
        auth.revoke_session(uuid.uuid4())


def test_deactivating_an_owner_locks_out_existing_sessions(auth, owner_login, db) -> None:
    _, username = owner_login
    tokens = auth.login(username, PASSWORD)
    with db.transaction() as tx:
        tx.execute("UPDATE owners SET active = false WHERE username = %s", (username,))
    with pytest.raises(Unauthenticated):
        auth.authenticate_session(tokens.session_token)


def test_csrf_token_must_match_the_session(auth, owner_login) -> None:
    _, username = owner_login
    tokens = auth.login(username, PASSWORD)
    principal = auth.authenticate_session(tokens.session_token)
    auth.verify_csrf(principal, tokens.csrf_token)
    with pytest.raises(Unauthorized):
        auth.verify_csrf(principal, None)
    with pytest.raises(Unauthorized):
        auth.verify_csrf(principal, "forged-csrf-token")
    with pytest.raises(Unauthorized):
        auth.verify_csrf(principal, tokens.session_token)  # the cookie is not the CSRF token


def test_service_credential_cannot_authenticate_as_a_human(auth, owner_login) -> None:
    token = auth.issue_service_credential("worker:ingest-01", PrincipalKind.SERVICE_WORKER)
    with pytest.raises(Unauthenticated):
        auth.authenticate_session(token)


def test_human_session_cannot_authenticate_as_a_service(auth, owner_login) -> None:
    _, username = owner_login
    tokens = auth.login(username, PASSWORD)
    with pytest.raises(Unauthenticated):
        auth.authenticate_service(tokens.session_token)


def test_humans_cannot_be_issued_service_credentials(auth) -> None:
    with pytest.raises(Unauthorized):
        auth.issue_service_credential("owner:anyone", PrincipalKind.HUMAN_OWNER)


def test_service_credentials_carry_their_kind_and_scopes(auth) -> None:
    token = auth.issue_service_credential(
        "model:critic-01",
        PrincipalKind.RUNTIME_MODEL,
        runtime_role=RuntimeRole.CRITIC,
        scopes=("read:episodes",),
    )
    principal = auth.authenticate_service(token)
    assert principal.kind is PrincipalKind.RUNTIME_MODEL
    assert principal.runtime_role is RuntimeRole.CRITIC
    assert principal.scopes == frozenset({"read:episodes"})
    assert not principal.is_human_owner and principal.session_id is None


def test_runtime_model_credential_requires_a_role(auth) -> None:
    with pytest.raises(SchemaInvalid):
        auth.issue_service_credential("model:no-role", PrincipalKind.RUNTIME_MODEL)


@pytest.mark.parametrize("scope", ["approve:episode", "gate_2", "reject-all", "revise"])
def test_service_credentials_cannot_hold_human_only_scopes(auth, scope: str) -> None:
    with pytest.raises(SchemaInvalid):
        auth.issue_service_credential("worker:x", PrincipalKind.SERVICE_WORKER, scopes=(scope,))


def test_revoked_service_credential_is_refused(auth) -> None:
    token = auth.issue_service_credential("scheduler:cron-02", PrincipalKind.SCHEDULER)
    assert auth.authenticate_service(token).principal_id == "scheduler:cron-02"
    auth.revoke_service_credential("scheduler:cron-02")
    with pytest.raises(Unauthenticated):
        auth.authenticate_service(token)


def test_require_human_owner_rejects_every_non_human_principal() -> None:
    for principal in (
        Principal(principal_id="worker:a", kind=PrincipalKind.SERVICE_WORKER),
        Principal(
            principal_id="model:b",
            kind=PrincipalKind.RUNTIME_MODEL,
            runtime_role=RuntimeRole.OBSERVER,
        ),
        Principal(principal_id="webhook:c", kind=PrincipalKind.PROVIDER_WEBHOOK),
        Principal(principal_id="scheduler:d", kind=PrincipalKind.SCHEDULER),
    ):
        with pytest.raises(Unauthorized):
            require_human_owner(principal)
