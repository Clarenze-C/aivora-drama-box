"""T031 R5a (RR-T4, R5C-4): the provisioning flag travels the COMPOSED path.

``seal.runtime_profile.provision_models`` -> ``PodLeaseConfig`` ->
``acquisition_requests`` (the frozen intent) AND ``LeaseService._spec_for`` ->
``PodSpec.to_request`` -> ``PodCreateRequest`` -> the RunPod create payload env.
The benchmark create guard refuses any POST where the intent or the composed
request lacks ``True``; a Pika intent without the flag is refused at
benchmark-side intent validation.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from test_benchmark_authorization import plan_data, seal_data
from test_benchmark_world_composition import (
    _claim_and_link,
    _compose,
    _quote,
    _Response,
)

from microdrama.contracts.errors import EffectDenied, PolicyDenied
from microdrama.persistence import Database
from microdrama.pipeline.benchmark_authorization import (
    BenchmarkPlan,
    BenchmarkSeal,
)
from microdrama.pipeline.experimental_world import (
    CanonicalExperimentWorld,
    validate_provision_intent,
)
from microdrama.rendering.leases import PodLeaseClaimRequest
from microdrama.rendering.pods import PodSpec
from microdrama.rendering.runpod_transport import pod_name

T0 = datetime(2026, 11, 13, 9, tzinfo=UTC)
PROVISIONING_PROFILE = {"profile": "fixture", "provision_models": True}


class RecordingRunpodTransport:
    """In-memory Runpod API recording every request body."""

    def __init__(self, pod: dict[str, Any]) -> None:
        self.pod = pod
        self.calls: list[tuple[str, str, bytes | None]] = []

    def request(
        self, method: str, url: str, *, headers: Any, body: bytes | None = None
    ) -> _Response:
        self.calls.append((method, url, body))
        if method == "POST" and url.endswith("/pods"):
            return _Response(200, json.dumps(self.pod).encode())
        if method == "GET" and url.startswith("https://api.runpod.io/v2/pods?"):
            return _Response(
                200,
                json.dumps({"pods": [], "pagination": {"cursor": None, "more": False}}).encode(),
            )
        if method == "GET" and f"/pods/{self.pod['id']}" in url:
            return _Response(200, json.dumps(self.pod).encode())
        raise AssertionError(f"unexpected Runpod call: {method} {url}")

    def create_bodies(self) -> list[dict[str, Any]]:
        return [json.loads(body) for method, url, body in self.calls if method == "POST"]


class _NoComfy:
    def request(self, *args: Any, **kwargs: Any) -> bytes:
        raise AssertionError("comfy transport must not be called during acquire")


def _exp_row(world, plan) -> dict[str, Any]:
    """The experiment row with a durable hard stop (prepare leaves it NULL)."""
    with world.db.transaction() as tx:
        tx.execute(
            "UPDATE benchmark_experiments SET hard_stop=%s WHERE experiment_id=%s "
            "AND hard_stop IS NULL",
            (T0 + timedelta(hours=6), plan.experiment_id),
        )
    with world.db.transaction(readonly=True) as tx:
        return dict(
            tx.fetchone(
                "SELECT * FROM benchmark_experiments WHERE experiment_id=%s", (plan.experiment_id,)
            )
        )


def _pika_compose(
    db: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    intent_claim: dict[str, Any],
    break_config_bridge: bool = False,
):
    monkeypatch.setattr(
        "microdrama.pipeline.experimental_world.ExperimentalPresetPolicy.validate",
        lambda *args, **kwargs: None,
    )
    world, plan, authorization, budget, clock, account_id = _compose(
        db,
        tmp_path,
        comfy_transport=_NoComfy(),
        seal_overrides={
            "schema_evidence": "LIVE_PROVIDER",
            "schema_attestation_source": "INDEPENDENT_RUNTIME_CAPTURE",
            "eligible_until": (T0 + timedelta(hours=8)).isoformat(),
            "hard_stop_utc": (T0 + timedelta(hours=6)).isoformat(),
            "runtime_profile": PROVISIONING_PROFILE,
        },
    )
    assert world.leases._config.provision_models is True, (
        "the world's lease config must transfer seal.runtime_profile.provision_models"
    )
    if break_config_bridge:
        # Break ONLY the request-construction bridge (the regression R5C-4
        # fears): config no longer carries the flag the seal demands.
        from dataclasses import replace as _replace

        world.leases._config = _replace(world.leases._config, provision_models=False)
    acquisition_id, lease_row = _claim_and_link(
        world, plan, budget, clock, intent_claim=intent_claim
    )
    pod = {
        "id": "pod-r5a-1",
        "name": pod_name(authorization.namespace, lease_row["client_token"]),
        "image": BenchmarkSeal.model_validate(seal_data(plan)).image_ref,
        "status": "RUNNING",
        "cost": "0.500000",
        "createdAt": clock.now().isoformat(),
        "gpu": {"id": "NVIDIA A40", "count": 1, "memory": 48, "vcpuCount": 16},
        "runtime": {"ports": [{"private": 8188, "public": 8188, "type": "http"}]},
    }
    transport = RecordingRunpodTransport(pod)
    world._provider._transport = transport
    acquisition = {"acquisition_id": acquisition_id, "lease_id": lease_row["id"]}
    return world, plan, transport, acquisition


def test_rr_t4_composed_path_maps_the_flag_into_the_create_payload(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """provision_models=True must reach the create payload env through
    ``LeaseService._spec_for()`` -> ``PodSpec.to_request()`` -> transport —
    captured from the POST body the real composed acquisition path sends."""
    world, plan, transport, acquisition = _pika_compose(
        db,
        tmp_path,
        monkeypatch,
        intent_claim={"provision_models": True},
    )
    handle = world.acquire(acquisition)
    assert handle.lease.pod_id == "pod-r5a-1"
    bodies = transport.create_bodies()
    assert len(bodies) == 1, "exactly one create POST"
    env = bodies[0].get("env") or {}
    assert env.get("MICRODRAMA_PROVISION_MODELS") == "1"
    assert env.get("MICRODRAMA_COMFY_TOKEN"), "the gateway token env stays beside the flag"


def test_rr_t4_guard_refuses_post_when_the_intent_lacks_the_flag(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, _plan, transport, acquisition = _pika_compose(
        db,
        tmp_path,
        monkeypatch,
        intent_claim={},  # a Pika intent WITHOUT the frozen flag
    )
    with pytest.raises(EffectDenied, match="provision_models"):
        world.acquire(acquisition)
    assert transport.create_bodies() == [], "no POST may leave"


def test_rr_t4_guard_refuses_post_when_the_composed_request_lacks_true(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The R5C-4 trap: a default-False field would silently compose a False
    request while the intent says True — the guard must refuse before POST."""
    world, plan, transport, acquisition = _pika_compose(
        db,
        tmp_path,
        monkeypatch,
        intent_claim={"provision_models": True},
        break_config_bridge=True,
    )
    with pytest.raises(EffectDenied, match="provision_models"):
        world.acquire(acquisition)
    assert transport.create_bodies() == [], "a request carrying False never reaches POST"


def test_rr_t4_non_pika_composition_stays_flagless(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a provisioning runtime profile the default stays False and the
    intent carries no flag (the canary/offline shape is unchanged)."""
    monkeypatch.setattr(
        "microdrama.pipeline.experimental_world.ExperimentalPresetPolicy.validate",
        lambda *args, **kwargs: None,
    )
    world, plan, authorization, budget, clock, account_id = _compose(
        db, tmp_path, comfy_transport=_NoComfy()
    )
    assert world.leases._config.provision_models is False
    adapter = CanonicalExperimentWorld(
        db=world.db,
        jobs=None,
        leases=world.leases,
        comfy=None,
        budget=budget,
        request_factory=lambda *a: None,
    )
    exp = _exp_row(world, plan)
    intent = adapter.acquisition_requests(exp, _quote(), UUID(int=9002), 1, clock.now())
    assert intent["claim"].get("provision_models") is not True


def test_rr_t4_intent_freezes_the_flag_from_the_config(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``acquisition_requests`` records the flag in the frozen intent claim."""
    monkeypatch.setattr(
        "microdrama.pipeline.experimental_world.ExperimentalPresetPolicy.validate",
        lambda *args, **kwargs: None,
    )
    world, plan, authorization, budget, clock, account_id = _compose(
        db, tmp_path, comfy_transport=_NoComfy()
    )
    world.leases._config = replace(world.leases._config, provision_models=True)
    adapter = CanonicalExperimentWorld(
        db=world.db,
        jobs=None,
        leases=world.leases,
        comfy=None,
        budget=budget,
        request_factory=lambda *a: None,
    )
    exp = _exp_row(world, plan)
    intent = adapter.acquisition_requests(exp, _quote(), UUID(int=9003), 1, clock.now())
    assert intent["claim"].get("provision_models") is True
    # The claim stays constructible as the lease claim request (materialize path).
    claim = dict(intent["claim"])
    claim["episode_id"] = UUID(claim["episode_id"])
    assert PodLeaseClaimRequest(**claim).provision_models is True


def test_rr_t4_intent_validation_refuses_a_pika_intent_without_the_flag() -> None:
    plan = BenchmarkPlan.model_validate(plan_data())
    pika_seal = BenchmarkSeal.model_validate(
        seal_data(plan) | {"runtime_profile": PROVISIONING_PROFILE}
    )
    with pytest.raises(PolicyDenied, match="provision_models"):
        validate_provision_intent(pika_seal, {"claim": {}})
    # The compliant intent passes; a non-provisioning seal never demands it.
    validate_provision_intent(pika_seal, {"claim": {"provision_models": True}})
    plain_seal = BenchmarkSeal.model_validate(seal_data(plan))
    validate_provision_intent(plain_seal, {"claim": {}})


def test_pod_spec_and_request_carry_the_flag() -> None:
    spec = PodSpec(
        gpu_type_allowlist=("NVIDIA A40",),
        max_hourly_price_micro_usd=900_000,
        min_host_ram_gb=64,
        container_image="registry.example/x@sha256:" + "a" * 64,
        provision_models=True,
    )
    request = spec.to_request(name="n", client_token="t", owned_tag="tag")
    assert request.provision_models is True
    plain = replace(spec, provision_models=False).to_request(
        name="n", client_token="t", owned_tag="o"
    )
    assert plain.provision_models is False
