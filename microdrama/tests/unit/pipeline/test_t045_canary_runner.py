"""T045 R11 (G12): the canary runner — authorization, preflight, execute refusals.

Red-first: no runnable PAID_BENCHMARK/canary command existed. These tests pin the
authorization schema (exactly the R11 list), preflight's no-network/no-resolution
guarantee, every execute refusal — each before any transport call — and the invoice
entrypoint's wiring into ``verify_invoice_period``.

The composed end-to-end canary (execute through fixture Runpod/Comfy transports on
real PostgreSQL) lives in ``tests/integration/pipeline/test_t045_canary_composed.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode
from microdrama.contracts.errors import PolicyDenied, SchemaInvalid
from microdrama.persistence import Database
from microdrama.pipeline.canary import load_prompts, run_execute, run_invoice, run_preflight
from microdrama.pipeline.canary_authorization import (
    CanaryAuthorization,
    load_canary_authorization,
    prompt_pin,
)
from microdrama.testing.fakes import FakeClock, SequentialIds

pytestmark = pytest.mark.db

T0 = datetime(2026, 11, 2, 12, tzinfo=UTC)


class _FailingTransport:
    """Any HTTP call fails the test: refusals and preflight stay offline."""

    def __init__(self) -> None:
        self.calls = 0

    def request(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        raise AssertionError("transport must not be called by preflight or refusals")


def _real_pins() -> dict[str, Any]:
    """Pins that match the seeded registries, exactly as preflight recomputes them."""
    from microdrama.contracts.hashing import canonical_hash
    from microdrama.rendering.workflows import MOCK_VIDEO_TEMPLATE, template_sha256

    required = ("TEXT_PROMPT", "SEED")
    supported = sorted(control.value for control in MOCK_VIDEO_TEMPLATE.supported_controls)
    return {
        "image_ref": "registry.example/microdrama/drama-canary@sha256:" + "a" * 64,
        "workflow_sha256": template_sha256(MOCK_VIDEO_TEMPLATE),
        "node_schema_sha256": canonical_hash(
            {
                "template_id": MOCK_VIDEO_TEMPLATE.template_id,
                "template_sha256": template_sha256(MOCK_VIDEO_TEMPLATE),
                "node_classes": sorted(MOCK_VIDEO_TEMPLATE.node_classes),
            }
        ),
        "output_controls_sha256": canonical_hash(
            {
                "required_controls": sorted(required),
                "supported_controls": supported,
                "control_ports": dict(MOCK_VIDEO_TEMPLATE.control_ports),
            }
        ),
        "preset_id": "fake-quality-8step",
        "preset_version": 1,
        "required_controls": list(required),
    }


def _authorization_document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "operator": "operator@example.invalid",
        "change_ref": "change-fixture-1",
        "hard_stop_utc": (T0 + timedelta(hours=2)).isoformat(),
        "max_wall_seconds": 1800,
        "quote": {
            "quote_id": "quote-canary-1",
            "currency": "USD",
            "captured_at": (T0 - timedelta(minutes=5)).isoformat(),
            "expires_at": (T0 + timedelta(hours=4)).isoformat(),
            "compute_micro_usd_per_hour": 504_000,
            "container_disk_gb": 20,
            "container_storage_micro_usd_per_gb_month": 100_000,
            "persistent_volume_gb": 5,
            "persistent_storage_micro_usd_per_gb_month": 200_000,
            "max_storage_exposure_micro_usd": 1_200_000,
            "allowed_gpu_types": ["A40"],
            "host_ram_gb_by_gpu": {"A40": 64},
            "maximum_runtime_ms": 600_000,
            "maximum_exposure_micro_usd": 2_000_000,
        },
        "caps": {
            "max_spend_micro_usd": 2_000_000,
            "max_storage_gb": 5,
            "max_prompts": 2,
            "max_attempts": 2,
        },
        "rights": {
            "rights_route_id": "route-video-fake",
            "rights_subject_ref": "model-output:qualified",
            "rights_subject_kind": "MODEL_OUTPUT",
            "rights_version": 1,
            "territories": ["TH"],
            "rights_evidence_id": "rights-evidence-canary",
            "eligible_until": (T0 + timedelta(hours=2)).isoformat(),
        },
        "pins": _real_pins(),
        "runpod_credential_ref": "credref:runpod-canary",
        "comfy_credential_ref": "credref:comfy-canary",
        "namespace": "canary1",
        "provider_account_ref": "acct:runpod-canary",
        "prompt_sha256": [_fixture_prompt_pin()],
        "reference_sha256": [],
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(document.get(key), dict):
            document[key] = {**document[key], **value}
        else:
            document[key] = value
    return document


def _fixture_prompt() -> dict[str, Any]:
    return {
        "text": "FIXTURE PROMPT canary: one wide night-market shot, static camera.",
        "seed": 20261102,
        "negative": "",
    }


def _fixture_prompt_pin() -> str:
    return prompt_pin(_fixture_prompt())


def _write(tmp_path: Path, document: dict[str, Any], name: str = "canary.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(document, indent=2))
    return path


def _live_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = dict(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
        object_store_root=None,
    )
    values.update(overrides)
    return Settings(**values)


def _seeded_world(db: Database):
    from test_live_world import _seed_registries

    _seed_registries(
        db, _live_settings(), recorded_at=T0 - timedelta(minutes=1), live_evidence=True
    )


# --- the authorization schema is exactly the R11 list ---------------------------------


def test_the_example_authorization_file_is_valid() -> None:
    example = Path(__file__).resolve().parents[3] / "runbooks" / "canary-authorization.example.json"
    authorization, digest = load_canary_authorization(example)
    assert isinstance(authorization, CanaryAuthorization)
    assert len(digest) == 64
    assert authorization.runpod_credential_ref.startswith("credref:")


@pytest.mark.parametrize(
    ("override", "match"),
    [
        ({"quote": {"currency": "EUR"}}, "USD"),
        ({"runpod_credential_ref": "sk-live-secret"}, "credref"),
        ({"provider_account_ref": "not-a-label"}, "acct"),
        ({"namespace": "UPPER"}, "namespace"),
        ({"caps": {"max_spend_micro_usd": 9_999_999}}, "exposure"),
        ({"caps": {"max_attempts": 5}}, "three"),
        ({"prompt_sha256": ["zz"]}, "sha256"),
        ({"max_wall_seconds": 0}, "max_wall_seconds"),
    ],
)
def test_invalid_authorizations_are_refused(
    tmp_path: Path, override: dict[str, Any], match: str
) -> None:
    path = _write(tmp_path, _authorization_document(**override))
    with pytest.raises(SchemaInvalid, match=match):
        load_canary_authorization(path)


def test_a_missing_field_is_refused(tmp_path: Path) -> None:
    document = _authorization_document()
    del document["hard_stop_utc"]
    with pytest.raises(SchemaInvalid):
        load_canary_authorization(_write(tmp_path, document))


# --- preflight: every gate, no network, no credential resolution -----------------------


def test_preflight_validates_every_gate_and_prints_the_plan_and_sha(
    db: Database, tmp_path: Path
) -> None:
    _seeded_world(db)
    path = _write(tmp_path, _authorization_document())
    plan = run_preflight(
        path,
        settings=_live_settings(),
        db=db,
        store=_NullStore(),
        clock=FakeClock(T0),
        ids=SequentialIds("preflight"),
    )
    assert plan.splitlines()[0] == "canary preflight OK"
    assert "authorization_sha256=" in plan
    assert "credref:runpod-canary" in plan and "secret" not in plan
    _, digest = load_canary_authorization(path)
    assert f"authorization_sha256={digest}" in plan


def test_preflight_refuses_when_the_preset_or_rights_pins_do_not_resolve(
    db: Database, tmp_path: Path
) -> None:
    # No registries seeded: the registry evidence gate must refuse.
    path = _write(tmp_path, _authorization_document())
    with pytest.raises(PolicyDenied):
        run_preflight(
            path,
            settings=_live_settings(),
            db=db,
            store=_NullStore(),
            clock=FakeClock(T0),
            ids=SequentialIds("preflight"),
        )


# --- execute refusals: typed, before any transport call --------------------------------


def _run_execute_refused(
    db: Database,
    tmp_path: Path,
    *,
    document: dict[str, Any],
    settings: Settings,
    expected_sha: str | None = None,
    now: datetime = T0,
) -> None:
    path = _write(tmp_path, document)
    _, digest = load_canary_authorization(path)
    prompts = tmp_path / "prompts.json"
    prompts.write_text(json.dumps([_fixture_prompt()]))
    run_execute(
        path,
        expected_sha256=expected_sha or digest,
        settings=settings,
        db=db,
        store=_NullStore(),
        prompts_path=prompts,
        clock=FakeClock(now),
        ids=SequentialIds("refuse"),
        runpod_transport=_FailingTransport(),
        comfy_transport=_FailingTransport(),
        credential_resolver=lambda _ref: "fixture-dummy-value",
        evidence_dir=tmp_path / "records",
    )


def test_execute_refuses_a_sha_mismatch(db: Database, tmp_path: Path) -> None:
    with pytest.raises(PolicyDenied, match="sha256 mismatch"):
        _run_execute_refused(
            db,
            tmp_path,
            document=_authorization_document(),
            settings=_live_settings(),
            expected_sha="0" * 64,
        )


def test_execute_refuses_when_the_hard_stop_has_passed(db: Database, tmp_path: Path) -> None:
    document = _authorization_document(hard_stop_utc=(T0 - timedelta(minutes=1)).isoformat())
    with pytest.raises(PolicyDenied, match="hard stop"):
        _run_execute_refused(db, tmp_path, document=document, settings=_live_settings())


def test_execute_refuses_an_expired_quote(db: Database, tmp_path: Path) -> None:
    quote = {
        "captured_at": (T0 - timedelta(hours=5)).isoformat(),
        "expires_at": (T0 - timedelta(hours=1)).isoformat(),
    }
    with pytest.raises(PolicyDenied, match="expired"):
        _run_execute_refused(
            db,
            tmp_path,
            document=_authorization_document(quote=quote),
            settings=_live_settings(),
        )


def test_execute_refuses_any_mode_other_than_paid_benchmark(db: Database, tmp_path: Path) -> None:
    with pytest.raises(PolicyDenied, match="PAID_BENCHMARK|paid"):
        _run_execute_refused(
            db,
            tmp_path,
            document=_authorization_document(),
            settings=_live_settings(
                execution_mode=ExecutionMode.OFFLINE_MOCK,
                paid_requests_enabled=False,
                cloud_resources_enabled=False,
            ),
        )
    with pytest.raises(PolicyDenied, match="PAID_BENCHMARK|paid"):
        _run_execute_refused(
            db,
            tmp_path,
            document=_authorization_document(),
            settings=_live_settings(paid_requests_enabled=False),
        )


def test_execute_refuses_a_cap_above_the_episode_cap(db: Database, tmp_path: Path) -> None:
    document = _authorization_document(
        quote={"maximum_exposure_micro_usd": 12_000_000},
        caps={"max_spend_micro_usd": 11_000_000},
    )
    with pytest.raises(PolicyDenied, match="episode cap"):
        _run_execute_refused(db, tmp_path, document=document, settings=_live_settings())


# --- prompts and the invoice entrypoint ------------------------------------------------


def test_prompts_must_match_their_pinned_content_hashes(tmp_path: Path) -> None:
    authorization = CanaryAuthorization.model_validate(_authorization_document())
    good = tmp_path / "prompts.json"
    good.write_text(json.dumps([_fixture_prompt()]))
    assert load_prompts(authorization, good) == [_fixture_prompt()]
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps([_fixture_prompt() | {"text": "a different prompt"}]))
    with pytest.raises(PolicyDenied, match="pinned content hash"):
        load_prompts(authorization, tampered)
    two = tmp_path / "two.json"
    two.write_text(json.dumps([_fixture_prompt(), _fixture_prompt()]))
    over_cap = CanaryAuthorization.model_validate(_authorization_document(caps={"max_prompts": 1}))
    with pytest.raises(PolicyDenied, match="prompt cap"):
        load_prompts(over_cap, two)


def test_invoice_entrypoint_stores_only_the_evidence_hash(db: Database, tmp_path: Path) -> None:
    """canary invoice wraps verify_invoice_period from operator evidence (R5)."""
    import sys

    # The budget lane's T045 fixture builders (real-PG bucket/lease helpers).
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "budget"))
    from t045_support import (
        ACCOUNT_REF,
        closed_bucket,
        insert_runpod_lease,
        open_episode_account,
    )

    from microdrama.contracts.hashing import sha256_hex
    from microdrama.rendering.finality import RunpodInvoiceFinality

    with db.transaction() as tx:
        season, episode, account = open_episode_account(tx)
        insert_runpod_lease(
            tx,
            episode,
            pod_id="pod-canary-inv",
            lease_state="RELEASED",
            pod_state="TERMINATED",
            create_requested_at=T0,
            compute_window_start_at=T0,
            compute_window_end_at=T0 + timedelta(hours=1),
            stop_verified_at=T0 + timedelta(hours=1),
            terminate_verified_at=T0 + timedelta(hours=1),
            provider_account_ref=ACCOUNT_REF,
        )
    start, end = T0, T0 + timedelta(hours=1)
    query, bucket = closed_bucket(
        pod_id="pod-canary-inv", start=start, end=end, gpu=400_000, cpu=50_000, disk=50_000
    )
    RunpodInvoiceFinality(db).ingest(query, [bucket])
    evidence = tmp_path / "invoice.pdf"
    evidence.write_bytes(b"fixture invoice bytes")
    summary = run_invoice(
        settings=_live_settings(),
        db=db,
        provider_account_ref=ACCOUNT_REF,
        pod_id="pod-canary-inv",
        period_start=start,
        period_end=end,
        amount_micro_usd=500_000,
        evidence_path=evidence,
        source="INVOICE",
        observed_at=end + timedelta(hours=2),
    )
    assert "invoice MATCHED" in summary
    assert sha256_hex(b"fixture invoice bytes") in summary
    # Only the hash is stored, never the file contents.
    with db.transaction(readonly=True) as tx:
        stored = tx.fetchval(
            "SELECT count(*) FROM runpod_billing_period_evidence WHERE evidence_sha256 = %s",
            (sha256_hex(b"fixture invoice bytes"),),
        )
    assert stored == 1


@dataclass
class _NullStore:
    """Preflight/refusals never touch the object store either."""

    def put_bytes(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        raise AssertionError("the store must not be written by preflight or refusals")


def test_no_cli_flag_can_set_the_comfy_endpoint(tmp_path: Any) -> None:
    """T045-FIX B-B2: the Comfy base URL is derived from the created Pod only - the
    flag is gone from the CLI entirely (argparse refuses unknown options)."""
    import pytest as _pytest

    from microdrama.pipeline.canary import main

    with _pytest.raises(SystemExit) as exc:
        main(
            [
                "execute",
                "--authorization",
                str(tmp_path / "absent.json"),
                "--authorization-sha256",
                "0" * 64,
                "--prompts",
                str(tmp_path / "absent.json"),
                "--comfy-endpoint",
                "https://attacker.example",
            ]
        )
    assert exc.value.code == 2
