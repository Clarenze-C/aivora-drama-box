from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from microdrama.config import Settings
from microdrama.contracts.errors import PolicyDenied, SchemaInvalid
from microdrama.pipeline.benchmark import main
from microdrama.pipeline.benchmark_authorization import (
    AcquisitionQuote,
    BenchmarkAuthorization,
    BenchmarkPlan,
    BenchmarkSeal,
    document_sha256,
    load_benchmark_authorization,
    load_document,
)

NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)


def plan_data():
    return {
        "experiment_id": str(UUID(int=101)),
        "episode_id": str(UUID(int=102)),
        "runtime_profile_sha256": "a" * 64,
        "shots": [{"shot_id": f"S0{i}", "thai_line": "ฉันจะฟัง"} for i in range(1, 9)],
        "samples": [
            {"sample_id": f"S0{i}-R{r}", "shot_id": f"S0{i}", "repeat": r, "seed": i * 100 + r}
            for i in range(1, 9)
            for r in range(1, 4)
        ],
        "max_new_exposure_micro_usd": 8_000_000,
        "max_gpu_ms": 14_400_000,
    }


def seal_data(plan):
    refs, ports = [], []
    for index, role in enumerate(("character_identity", "outfit", "location", "voice")):
        ref = {
            "role": role,
            "subject_id": "speaker-a",
            "asset_id": str(UUID(int=200 + index)),
            "asset_version": 1,
            "asset_sha256": str(index + 1) * 64,
        }
        refs.append(ref)
        ports.append(
            ref
            | {
                "media_kind": "audio" if role == "voice" else "image",
                "destination_slot": "ref_audios.ref_audio_0"
                if role == "voice"
                else f"ref_images.ref_image_{index}",
            }
        )
    return {
        "experiment_id": str(plan.experiment_id),
        "plan_sha256": plan.plan_sha256,
        "references": refs,
        "port_map": ports,
        "runtime_profile": {"profile": "fixture"},
        "image_ref": "registry.example/drama@sha256:" + "b" * 64,
        "node_schema_sha256": "c" * 64,
        "rights_evidence_hash": "d" * 64,
        "territories": ["TH"],
        "eligible_until": NOW + timedelta(hours=6),
        "hard_stop_utc": NOW + timedelta(hours=4),
    }


def authorization_data(plan, seal):
    return {
        "operator": "fixture-operator.invalid",
        "change_ref": "fixture-only-not-approved",
        "experiment_id": str(plan.experiment_id),
        "episode_id": str(plan.episode_id),
        "plan_sha256": plan.plan_sha256,
        "sealed_sha256": seal.sealed_sha256,
        "provider_account_ref": "acct:fixture",
        "max_new_exposure_micro_usd": 8_000_000,
        "max_gpu_ms": 14_400_000,
        "hard_stop_utc": NOW + timedelta(hours=3),
        "allowed_gpu_types": ["NVIDIA A40"],
        "minimum_host_ram_gb": 64,
        "max_hourly_micro_usd": 850_000,
        "max_storage_exposure_micro_usd": 2_000_000,
        "container_disk_gb": 100,
        "persistent_volume_gb": 100,
        "shutdown_reserve_micro_usd": 500_000,
        "namespace": "benchx",
        "runpod_credential_ref": "credref:fixture-runpod",
        "comfy_credential_ref": "credref:fixture-comfy",
        "rights_evidence_hash": seal.rights_evidence_hash,
    }


def test_plan_identity_excludes_uuid_but_retains_nonce_and_work():
    plan = BenchmarkPlan.model_validate(plan_data())
    alias = plan.model_copy(update={"experiment_id": uuid4()})
    assert plan.plan_sha256 == alias.plan_sha256
    assert (
        plan.plan_sha256
        != plan.model_copy(update={"experiment_nonce": "intentional-repeat"}).plan_sha256
    )
    changed = plan_data()
    changed["shots"][0]["thai_line"] = "ฉันไม่ฟัง"
    assert plan.plan_sha256 != BenchmarkPlan.model_validate(changed).plan_sha256


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_new_exposure_micro_usd", 8_000_001),
        ("max_new_exposure_micro_usd", True),
        ("max_gpu_ms", 14_400_001),
        ("max_attempts_per_sample", True),
        ("schema_version", True),
    ],
)
def test_counts_and_money_are_strict_and_bounded(field, value):
    with pytest.raises(ValidationError):
        BenchmarkPlan.model_validate(plan_data() | {field: value})


def test_matrix_rejects_changed_screen_and_duplicate_seed():
    data = plan_data()
    with pytest.raises(ValidationError):
        BenchmarkPlan.model_validate(data | {"screen_sample_ids": ["S01-R1", "S02-R1", "S03-R1"]})
    data["samples"][1]["seed"] = data["samples"][0]["seed"]
    with pytest.raises(ValidationError):
        BenchmarkPlan.model_validate(data)


def test_seal_checks_exact_asset_version_and_media_port():
    plan = BenchmarkPlan.model_validate(plan_data())
    data = seal_data(plan)
    BenchmarkSeal.model_validate(data)
    changed = copy.deepcopy(data)
    changed["port_map"][0]["asset_version"] = 2
    with pytest.raises(ValidationError):
        BenchmarkSeal.model_validate(changed)


def test_shot_scoped_costume_ports_reuse_the_same_destination_per_shot():
    plan = BenchmarkPlan.model_validate(plan_data())
    data = seal_data(plan)
    outfit = next(item for item in data["references"] if item["role"] == "outfit")
    alternate = outfit | {
        "subject_id": "outfit-b",
        "asset_id": str(UUID(int=999)),
        "asset_sha256": "f" * 64,
    }
    data["references"].append(alternate)
    shared = [item for item in data["port_map"] if item["role"] != "outfit"]
    shot_ports = []
    for index in range(1, 9):
        shot_id = f"S0{index}"
        shot_ports.extend(item | {"shot_id": shot_id} for item in shared)
        selected = alternate if index == 8 else outfit
        shot_ports.append(
            selected
            | {
                "shot_id": shot_id,
                "media_kind": "image",
                "destination_slot": "ref_images.ref_image_1",
            }
        )
    data["port_map"] = shot_ports
    seal = BenchmarkSeal.model_validate(data)
    assert len(seal.port_map) == 32
    changed = copy.deepcopy(data)
    changed["port_map"][-1]["destination_slot"] = "ref_images.ref_image_3"
    with pytest.raises(ValidationError):
        BenchmarkSeal.model_validate(changed)


def test_fixture_schema_cannot_authorize_generation():
    plan = BenchmarkPlan.model_validate(plan_data())
    seal = BenchmarkSeal.model_validate(
        seal_data(plan) | {"schema_evidence": "OFFLINE_FIXTURE_ONLY"}
    )
    auth = BenchmarkAuthorization.model_validate(authorization_data(plan, seal))
    with pytest.raises(PolicyDenied, match="fixture|Fixture"):
        auth.validate_for(plan, seal, now=NOW)


def test_published_cpu_no_weights_hash_cannot_be_relabelled_live():
    plan = BenchmarkPlan.model_validate(plan_data())
    seal = BenchmarkSeal.model_validate(
        seal_data(plan)
        | {
            "schema_evidence": "LIVE_PROVIDER",
            "schema_attestation_source": "INDEPENDENT_RUNTIME_CAPTURE",
            "node_schema_sha256": "339021b1e3106ee0648b264f0ef1ddc8e1bb68c0374d8d6c7c1a6b0f375ba9ae",
        }
    )
    auth = BenchmarkAuthorization.model_validate(authorization_data(plan, seal))
    with pytest.raises(PolicyDenied, match="CPU/no-weights"):
        auth.validate_for(plan, seal, now=NOW)


def test_live_provider_label_without_independent_capture_is_denied():
    plan = BenchmarkPlan.model_validate(plan_data())
    seal = BenchmarkSeal.model_validate(seal_data(plan) | {"schema_evidence": "LIVE_PROVIDER"})
    auth = BenchmarkAuthorization.model_validate(authorization_data(plan, seal))
    with pytest.raises(PolicyDenied, match="self-asserted"):
        auth.validate_for(plan, seal, now=NOW)


def test_preflight_is_not_ready_when_factory_policy_refuses(monkeypatch: pytest.MonkeyPatch):
    from microdrama.config import Settings
    from microdrama.contracts.enums import ExecutionMode
    from microdrama.pipeline.benchmark_service import BenchmarkService
    from microdrama.testing.fakes import FakeClock

    plan = BenchmarkPlan.model_validate(plan_data())
    seal = BenchmarkSeal.model_validate(seal_data(plan))
    authorization = BenchmarkAuthorization.model_validate(authorization_data(plan, seal))
    status = {
        "plan": plan.model_dump(mode="json"),
        "seal": {"manifest": seal.model_dump(mode="json")},
        "hard_stop": NOW + timedelta(hours=1),
        "plan_sha256": plan.plan_sha256,
        "sealed_sha256": seal.sealed_sha256,
        "exposure": {},
        "gpu_ms": 0,
    }
    service = object.__new__(BenchmarkService)
    service.status = lambda _experiment_id: status
    service.clock = FakeClock(NOW)
    service.settings = Settings(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
    )
    service._validate_authorization = lambda *args: None

    def reject(*args, **kwargs):
        raise PolicyDenied("preset or rights refused")

    monkeypatch.setattr(
        "microdrama.pipeline.experimental_world.ExperimentalPresetPolicy.validate", reject
    )
    result = service.preflight(plan.experiment_id, authorization, object())
    assert result["ready"] is False
    assert "authorization or sealed-manifest validation failed" in result["reasons"]


# ---------------------------------------------------------------------------
# L-4 (GLM Luna review): preflight must not report ready in two more
# factory-refusing states - public actions enabled, and no budget headroom.
# ---------------------------------------------------------------------------


def _l4_preflight_service(status):
    from microdrama.config import Settings
    from microdrama.contracts.enums import ExecutionMode
    from microdrama.pipeline.benchmark_service import BenchmarkService
    from microdrama.testing.fakes import FakeClock

    service = object.__new__(BenchmarkService)
    service.status = lambda _experiment_id: status
    service.clock = FakeClock(NOW)
    service.settings = Settings(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
    )
    service._validate_authorization = lambda *args: None
    return service


def _l4_plan_seal_auth():
    """An otherwise-READY baseline: a LIVE seal with a future hard stop, so
    each L-4 test flips exactly one factory-refusing condition."""
    plan = BenchmarkPlan.model_validate(plan_data())
    seal = BenchmarkSeal.model_validate(
        seal_data(plan)
        | {
            "schema_evidence": "LIVE_PROVIDER",
            "schema_attestation_source": "INDEPENDENT_RUNTIME_CAPTURE",
            "eligible_until": (NOW + timedelta(hours=6)).isoformat(),
            "hard_stop_utc": (NOW + timedelta(hours=4)).isoformat(),
        }
    )
    authorization = BenchmarkAuthorization.model_validate(authorization_data(plan, seal))
    return plan, seal, authorization


def _l4_status(plan, seal, *, exposure_total=0, gpu_ms=0):
    return {
        "plan": plan.model_dump(mode="json"),
        "seal": {"manifest": seal.model_dump(mode="json")},
        "hard_stop": NOW + timedelta(hours=1),
        "plan_sha256": plan.plan_sha256,
        "sealed_sha256": seal.sealed_sha256,
        "exposure": {"total": exposure_total},
        "gpu_ms": gpu_ms,
    }


def test_l4_preflight_refuses_public_actions_enabled(monkeypatch: pytest.MonkeyPatch):
    """L-4(a): parity with the factory's own public-actions guard.

    Validated Settings refuse public_actions_enabled=True in PAID_BENCHMARK
    (the Settings model validator fires first), so this state is unreachable
    through normal construction - the factory AND preflight still defend
    against it independently, and the reason matches the factory's refusal."""
    from microdrama.config import Settings
    from microdrama.contracts.enums import ExecutionMode
    from microdrama.pipeline.benchmark_service import BenchmarkService
    from microdrama.testing.fakes import FakeClock

    plan, seal, authorization = _l4_plan_seal_auth()
    monkeypatch.setattr(
        "microdrama.pipeline.experimental_world.ExperimentalPresetPolicy.validate",
        lambda *args, **kwargs: None,
    )
    service = object.__new__(BenchmarkService)
    service.status = lambda _experiment_id: _l4_status(plan, seal)
    service.clock = FakeClock(NOW)
    service.settings = Settings.model_construct(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
        public_actions_enabled=True,
    )
    service._validate_authorization = lambda *args: None
    result = service.preflight(plan.experiment_id, authorization, object())
    assert result["ready"] is False
    assert any("public actions" in reason for reason in result["reasons"])


def test_l4_preflight_refuses_when_exposure_headroom_is_gone(monkeypatch: pytest.MonkeyPatch):
    plan, seal, authorization = _l4_plan_seal_auth()
    monkeypatch.setattr(
        "microdrama.pipeline.experimental_world.ExperimentalPresetPolicy.validate",
        lambda *args, **kwargs: None,
    )
    service = _l4_preflight_service(
        _l4_status(plan, seal, exposure_total=plan.max_new_exposure_micro_usd)
    )
    result = service.preflight(plan.experiment_id, authorization, object())
    assert result["ready"] is False
    assert any("exposure" in reason for reason in result["reasons"])


def test_l4_preflight_refuses_when_gpu_budget_is_exhausted(monkeypatch: pytest.MonkeyPatch):
    plan, seal, authorization = _l4_plan_seal_auth()
    monkeypatch.setattr(
        "microdrama.pipeline.experimental_world.ExperimentalPresetPolicy.validate",
        lambda *args, **kwargs: None,
    )
    service = _l4_preflight_service(_l4_status(plan, seal, gpu_ms=plan.max_gpu_ms))
    result = service.preflight(plan.experiment_id, authorization, object())
    assert result["ready"] is False
    assert any("GPU" in reason for reason in result["reasons"])


def test_operator_file_uses_actual_bytes_not_model_serialization(tmp_path):
    plan = BenchmarkPlan.model_validate(plan_data())
    seal = BenchmarkSeal.model_validate(seal_data(plan))
    auth = BenchmarkAuthorization.model_validate(authorization_data(plan, seal))
    raw = json.dumps(auth.model_dump(mode="json"), indent=4).encode()
    path = tmp_path / "authorization.json"
    path.write_bytes(raw)
    loaded, digest = load_benchmark_authorization(path)
    assert digest == hashlib.sha256(raw).hexdigest() == loaded.authorization_sha256
    assert digest != document_sha256(loaded)


@pytest.mark.parametrize("account", ["acct:UPPER", "acct:has:colon", "acct:a"])
def test_account_label_matches_actual_attestation_format(account):
    plan = BenchmarkPlan.model_validate(plan_data())
    seal = BenchmarkSeal.model_validate(seal_data(plan))
    with pytest.raises(ValidationError):
        BenchmarkAuthorization.model_validate(
            authorization_data(plan, seal) | {"provider_account_ref": account}
        )


def test_invalid_credential_input_is_not_reflected_in_loader_error(tmp_path):
    path = tmp_path / "invalid.json"
    marker = "SYNTHETIC_INPUT_NOT_A_REAL_SECRET"
    path.write_text(json.dumps({"runpod_credential_ref": marker}))
    with pytest.raises(SchemaInvalid) as caught:
        load_benchmark_authorization(path)
    assert marker not in str(caught.value)
    with pytest.raises(SchemaInvalid):
        load_document(path, BenchmarkPlan)


def test_quote_rejects_noncanonical_rate_and_stale_validity_shape():
    data = {
        "quote_id": "fixture",
        "captured_at": NOW,
        "expires_at": NOW + timedelta(hours=1),
        "host_ram_gb": 64,
        "compute_micro_usd_per_hour": 590_400,
        "container_disk_gb": 100,
        "persistent_volume_gb": 100,
        "container_storage_micro_usd_per_gb_month": 100_000,
        "persistent_storage_micro_usd_per_gb_month": 200_000,
        "max_storage_exposure_micro_usd": 2_000_000,
        "maximum_runtime_ms": 3_600_000,
        "source_evidence_sha256": "e" * 64,
    }
    AcquisitionQuote.model_validate(data)
    with pytest.raises(ValidationError):
        AcquisitionQuote.model_validate(data | {"compute_micro_usd_per_hour": 590_000})
    with pytest.raises(ValidationError):
        AcquisitionQuote.model_validate(data | {"expires_at": NOW + timedelta(hours=3)})


def test_cli_denies_generation_in_default_mode_before_db_or_provider(capsys):
    called = []
    result = main(
        ["execute", "--experiment-id", str(UUID(int=101))],
        _injection={"settings": Settings(), "service_factory": lambda *args: called.append(args)},
    )
    assert result == 2 and not called
    assert "PAID_BENCHMARK" in capsys.readouterr().err


def test_cli_resolve_requires_an_audited_attestation_and_one_target(capsys):
    """H-2: the operator resolution CLI refuses before any DB/provider work
    unless it names exactly one target and the full audited attestation."""
    called = []
    injection = {"settings": Settings(), "service_factory": lambda *args: called.append(args)}
    base = ["resolve", "--experiment-id", str(UUID(int=101))]
    for argv in (
        base + ["--acquisition-id", str(UUID(int=9001))],
        base
        + [
            "--acquisition-id",
            str(UUID(int=9001)),
            "--actor-ref",
            "operator",
            "--reason",
            "console evidence",
        ],
        base
        + [
            "--acquisition-id",
            str(UUID(int=9001)),
            "--sample-id",
            "S01-R1",
            "--actor-ref",
            "operator",
            "--reason",
            "console evidence",
            "--evidence-sha256",
            "a" * 64,
        ],
        base
        + [
            "--actor-ref",
            "operator",
            "--reason",
            "console evidence",
            "--evidence-sha256",
            "a" * 64,
        ],
    ):
        result = main(argv, _injection=injection)
        assert result == 2, argv
        assert not called, argv
        assert "resolve" in capsys.readouterr().err


def test_missing_model_rights_never_queries_registry():
    from types import SimpleNamespace

    from microdrama.pipeline.experimental_world import _validate_model_rights

    class RefusingDatabase:
        def transaction(self, **kwargs):
            raise AssertionError("missing pins must fail before SQL or provider access")

    with pytest.raises(PolicyDenied, match="model-output rights"):
        _validate_model_rights(
            RefusingDatabase(), Settings(), None, {}, SimpleNamespace(rights_route_id=None), ["TH"]
        )
