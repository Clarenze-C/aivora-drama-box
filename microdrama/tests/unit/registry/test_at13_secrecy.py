"""AT-13 secrecy: a planted secret value never reaches registry rows, record or decision payloads,
raised errors, or captured logs. Row scans read the real database tables, not Python objects."""

from __future__ import annotations

import logging

import pytest
from registry_support import (
    ACCOUNT,
    POLICY_EXAMPLE,
    ROUTE,
    VOICE_REF,
    all_registry_rows_text,
    capability,
    fixed_clock,
    live_settings,
    mock_settings,
    preset,
    real_benchmark,
    real_license,
    rights,
)

from microdrama.contracts.enums import (
    CapabilityOperation,
    EvidenceSource,
    Platform,
    Provenance,
    RightsSubjectKind,
)
from microdrama.contracts.errors import EffectDenied, MicrodramaError, PolicyDenied, SchemaInvalid
from microdrama.contracts.primitives import EvidenceRef
from microdrama.core.registry import (
    CapabilityRegistry,
    CredentialStore,
    DestinationRequirement,
    PresetRegistry,
    RightsRegistry,
    Secret,
    assert_no_secrets,
    evaluate_release_conditions,
    import_policy,
    redactor,
)
from microdrama.persistence import Database

pytestmark = pytest.mark.db

# A planted value, not a real credential. It must never appear in any output checked below.
MARKER = "mdtest-AT13-planted-9e4b7c1d2a6f8031"
ENV_NAME = "MICRODRAMA_TEST_AT13_PROVIDER_KEY"
REF = "credref:at13-provider"


def _populate(db: Database, store: CredentialStore) -> None:
    """Every write and read path a release runs, with the secret loaded at the edge."""
    store.register(
        ref=REF, purpose="publish api", provider="fake-youtube", store="ENV", locator=ENV_NAME
    )
    assert store.resolve_secret(REF).reveal() == MARKER

    rights_registry = RightsRegistry(db, fixed_clock(), live_settings())
    rights_registry.record(
        rights(evidence=[real_license("licence:at13-voice")]),
        source_provenance=Provenance.LICENSED,
    )
    capability_registry = CapabilityRegistry(db, fixed_clock(), live_settings())
    capability_registry.record(
        capability(
            evidence=[
                EvidenceRef(source=EvidenceSource.CONTROLLED_ACCOUNT_TEST, ref="controlled-at13")
            ]
        ),
        source_provenance=Provenance.LIVE_PROVIDER,
    )
    PresetRegistry(db, live_settings()).record(
        preset(evidence=[real_benchmark("benchmark:at13")]),
        source_provenance=Provenance.LIVE_PROVIDER,
    )
    with db.transaction() as tx:
        import_policy(tx, POLICY_EXAMPLE)

    blockers = evaluate_release_conditions(
        rights=rights_registry,
        capabilities=capability_registry,
        rights_route_id=ROUTE,
        rights_subjects=[(RightsSubjectKind.VOICE.value, VOICE_REF)],
        territories=["TH"],
        destinations=[
            DestinationRequirement(
                platform=Platform.TIKTOK,
                account_ref=ACCOUNT,
                required_ops=frozenset({CapabilityOperation.SCHEDULE}),
                disclosures=frozenset(),
                required=True,
            )
        ],
        at=fixed_clock().now(),
        qa_all_green=True,
    )
    assert blockers == []


def test_the_planted_value_never_reaches_any_registry_row(db: Database) -> None:
    _populate(db, CredentialStore(db, live_settings(), environ={ENV_NAME: MARKER}))
    dump = all_registry_rows_text(db)
    assert ENV_NAME in dump  # the locator is a name and is stored as designed
    assert "credref:at13-provider" in dump
    assert MARKER not in dump


def test_a_value_shaped_locator_is_refused_and_never_stored(db: Database) -> None:
    store = CredentialStore(db, mock_settings(), environ={})
    with pytest.raises(SchemaInvalid) as caught:
        store.register(ref=REF, purpose="p", provider="f", store="ENV", locator=MARKER)
    assert MARKER not in caught.value.message
    assert MARKER not in str(caught.value.details)
    assert MARKER not in all_registry_rows_text(db)


def test_record_and_decision_payloads_do_not_carry_the_value(db: Database) -> None:
    _populate(db, CredentialStore(db, live_settings(), environ={ENV_NAME: MARKER}))
    capabilities = CapabilityRegistry(db, fixed_clock(), live_settings())
    current = capabilities.current(Platform.TIKTOK, ACCOUNT)
    assert current is not None and MARKER not in current.model_dump_json()

    decision = capabilities.evaluate(
        platform=Platform.TIKTOK,
        account_ref=ACCOUNT,
        required={CapabilityOperation.SCHEDULE},
    )
    assert MARKER not in decision.model_dump_json()

    rights_decision = RightsRegistry(db, fixed_clock(), live_settings()).evaluate(
        rights_route_id=ROUTE,
        subjects=[(RightsSubjectKind.VOICE, VOICE_REF)],
        territories=["TH"],
    )
    assert MARKER not in rights_decision.model_dump_json()


def test_error_messages_and_payloads_never_repeat_the_value(db: Database) -> None:
    raised: list[MicrodramaError] = []

    denied_store = CredentialStore(db, mock_settings(), environ={ENV_NAME: MARKER})
    denied_store.register(ref=REF, purpose="p", provider="f", store="ENV", locator=ENV_NAME)
    with pytest.raises(EffectDenied) as denied:
        denied_store.resolve_secret(REF)
    raised.append(denied.value)

    empty_store = CredentialStore(db, live_settings(), environ={})
    with pytest.raises(MicrodramaError) as missing:
        empty_store.resolve_secret(REF)
    raised.append(missing.value)

    with pytest.raises(PolicyDenied) as leak:
        assert_no_secrets(f"log line with {MARKER}", [Secret(MARKER)])
    raised.append(leak.value)

    for error in raised:
        assert MARKER not in error.message
        assert MARKER not in str(error)
        assert MARKER not in repr(error.to_dict())


def test_logs_captured_during_the_whole_flow_never_show_the_value(
    db: Database, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    store = CredentialStore(db, live_settings(), environ={ENV_NAME: MARKER})
    _populate(db, store)
    secret = store.resolve_secret(REF)
    log = logging.getLogger("microdrama.at13")
    log.warning("provider call with %s", secret)
    log.warning("formatted %s", f"{secret}")
    log.warning("repr %r", secret)
    assert MARKER not in caplog.text
    assert "Secret(***)" in caplog.text


def test_a_redacted_log_line_keeps_its_context_but_not_the_value() -> None:
    scrub = redactor(Secret(MARKER))
    assert scrub(f"sending header key={MARKER} to provider") == (
        "sending header key=*** to provider"
    )


def test_an_example_policy_import_adds_no_secret_material(db: Database) -> None:
    with db.transaction() as tx:
        import_policy(tx, POLICY_EXAMPLE)
    assert "credential_store_reference" in all_registry_rows_text(db)
    assert MARKER not in all_registry_rows_text(db)


def test_the_row_scan_detects_a_value_planted_past_validation(db: Database) -> None:
    """Negative control: the scans above are only meaningful if they can see a planted value.
    The row is written with raw SQL, bypassing the registry's validation on purpose."""
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO credential_refs (ref, purpose, provider, store, locator) "
            "VALUES (%s, %s, %s, %s, %s)",
            (REF, "control", "control", "ENV", MARKER),
        )
    assert MARKER in all_registry_rows_text(db)
