"""H-1 (2026-11-10, GLM harness review): the DEFAULT experiment composition.

``CanonicalExperimentWorld.acquire`` called ``bind_pod_endpoint(pod)`` with one
argument while the real ``ComfyHttpClient``/``PikaHttpClient`` signature is
``(pod_id, endpoint_url)``; a ``hasattr`` guard hid the drift from every
fixture-driven test, so every default live execution crashed with a TypeError
AFTER the paid pod was created. These tests compose the real default factory
(``build_experiment_world`` -> ``PikaHttpClient``) with scripted in-memory
transports, so the signature can never drift behind a guard again.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from test_benchmark_authorization import authorization_data, plan_data, seal_data

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode
from microdrama.persistence import Database
from microdrama.persistence.db import jsonb
from microdrama.persistence.object_store import FilesystemObjectStore
from microdrama.pipeline.benchmark_authorization import (
    AcquisitionQuote,
    BenchmarkAuthorization,
    BenchmarkPlan,
    BenchmarkSeal,
)
from microdrama.pipeline.benchmark_service import BenchmarkService
from microdrama.pipeline.experimental_world import (
    build_experiment_world,
)
from microdrama.rendering.leases import PodLeaseClaimRequest
from microdrama.rendering.runpod_transport import pod_name
from microdrama.testing.fakes import FakeClock, SequentialIds
from microdrama.testing.seed import seed_episode, seed_season

pytestmark = pytest.mark.db

T0 = datetime(2026, 11, 10, 12, tzinfo=UTC)


@dataclass
class _Response:
    status: int
    body: bytes


class ScriptedRunpodTransport:
    """In-memory Runpod API: one create POST plus its verification GETs."""

    def __init__(self, pod: dict[str, Any]) -> None:
        self.pod = pod
        self.calls: list[tuple[str, str]] = []

    def request(
        self, method: str, url: str, *, headers: Any, body: bytes | None = None
    ) -> _Response:
        self.calls.append((method, url))
        if method == "POST" and url.endswith("/pods"):
            return _Response(200, json.dumps(self.pod).encode())
        if method == "GET" and url.startswith("https://api.runpod.io/v2/pods?"):
            # reconcile_by_token's list pass before the create: nothing owned yet.
            return _Response(
                200,
                json.dumps({"pods": [], "pagination": {"cursor": None, "more": False}}).encode(),
            )
        if method == "GET" and f"/pods/{self.pod['id']}" in url:
            return _Response(200, json.dumps(self.pod).encode())
        raise AssertionError(f"unexpected Runpod call: {method} {url}")


class FailingComfyTransport:
    """acquire() must bind without any ComfyUI HTTP call."""

    def request(self, *args: Any, **kwargs: Any) -> bytes:
        raise AssertionError("comfy transport must not be called during acquire")


class ReadyServingComfyTransport:
    """T031 R5b: acquire() now runs the ready gate (GET /__drama/ready plus the
    boot-window /object_info) through the real client before it returns, so the
    composed H-1 tests script a gateway that is already provisioned."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, url: str, *, headers: Any, body: bytes | None = None) -> bytes:
        self.calls.append((method, url))
        if method == "GET" and url.endswith("/__drama/ready"):
            return json.dumps(
                {
                    "state": "PROVISIONED",
                    "provision": {
                        "state": "PROVISIONED",
                        "started_at": "2026-11-14T01:00:00Z",
                        "ended_at": "2026-11-14T01:05:00Z",
                        "exit_code": 0,
                    },
                }
            ).encode()
        if method == "GET" and url.endswith("/object_info"):
            return json.dumps({"UNETLoader": {}}).encode()
        raise AssertionError(f"unexpected comfy call: {method} {url}")


def _settings() -> Settings:
    return Settings(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
    )


def _quote() -> AcquisitionQuote:
    return AcquisitionQuote(
        schema_version=1,
        quote_id="fixture-quote-1",
        captured_at=T0 - timedelta(minutes=1),
        expires_at=T0 + timedelta(minutes=30),
        gpu_type="NVIDIA A40",
        host_ram_gb=64,
        compute_micro_usd_per_hour=849_600,
        container_disk_gb=50,
        persistent_volume_gb=20,
        container_storage_micro_usd_per_gb_month=100_000,
        persistent_storage_micro_usd_per_gb_month=100_000,
        max_storage_exposure_micro_usd=1_000_000,
        maximum_runtime_ms=600_000,
        source_evidence_sha256="e" * 64,
    )


def _seed_file_credential(db: Database, ref: str, tmp_path: Path, value: str) -> None:
    path = tmp_path / f"{ref.replace(':', '_')}.secret"
    path.write_text(value, encoding="utf-8")
    os.chmod(path, 0o600)
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO credential_refs(ref, purpose, provider, store, locator) "
            "VALUES(%s, 'fixture', 'runpod', 'FILE', %s)",
            (ref, str(path)),
        )


def _compose(
    db: Database,
    tmp_path: Path,
    *,
    comfy_transport: Any,
    seal_overrides: dict | None = None,
):
    """Episode+account, prepare+seal+authorize one experiment, default world.

    The caller monkeypatches ``ExperimentalPresetPolicy.validate``: this file
    tests the default factory's WIRING (real PikaHttpClient, real lease service,
    scripted transports), not the preset/rights policy, which the preflight and
    policy suites cover."""
    settings = _settings()
    clock = FakeClock(T0)
    ids = SequentialIds("bench-compose")
    budget = BudgetService(db, clock, ids, settings)
    with db.transaction() as tx:
        season_id = seed_season(tx)
        episode_id = seed_episode(tx, season_id, number=1)
        from microdrama.contracts.season import CostPolicy

        account_id = budget.open_episode_account(
            tx, season_id=season_id, episode_id=episode_id, policy=CostPolicy()
        )
    plan = BenchmarkPlan.model_validate(plan_data() | {"episode_id": str(episode_id)})
    seal = BenchmarkSeal.model_validate(seal_data(plan) | (seal_overrides or {}))
    authorization = BenchmarkAuthorization.model_validate(authorization_data(plan, seal))
    service = BenchmarkService(db, settings, clock=clock, ids=ids)
    service.prepare(plan)
    service.seal(plan.experiment_id, seal)
    for ref in (authorization.runpod_credential_ref, authorization.comfy_credential_ref):
        _seed_file_credential(db, ref, tmp_path, f"synthetic-{ref}")
    world = build_experiment_world(
        settings,
        db,
        budget,
        FilesystemObjectStore(tmp_path / "objects"),
        experiment_id=plan.experiment_id,
        authorization=authorization,
        quote=_quote(),
        clock=clock,
        ids=ids,
        runpod_transport=ScriptedRunpodTransport({}),  # replaced once the token is known
        comfy_transport=comfy_transport,
    )
    return world, plan, authorization, budget, clock, account_id


def _claim_and_link(
    world, plan, budget, clock, *, intent_claim: dict[str, Any] | None = None
) -> tuple[UUID, dict[str, Any]]:
    """Claim the acquisition lease and durably link it as the COMPUTE hold.

    ``intent_claim`` overrides the frozen acquisition intent's claim document
    (T031 R5a: the provisioning flag rides the intent)."""
    intent_claim = {"claim": dict(intent_claim or {})}
    from microdrama.contracts.hashing import canonical_hash
    from microdrama.rendering.benchmark_experiments import document

    handle = world.leases.claim(
        PodLeaseClaimRequest(
            episode_id=plan.episode_id,
            semantic_key=f"benchmark:{plan.experiment_id}:acq:1",
            gpu_type="NVIDIA A40",
            host_ram_gb=64,
            lease_ttl_ms=600_000,
        )
    )
    lease_id = handle.lease.lease_id
    with world.db.transaction() as tx:
        row = tx.fetchone("SELECT * FROM pod_leases WHERE id=%s", (lease_id,))
        quote = _quote()
        acquisition_id = UUID(int=9001)
        tx.execute(
            "INSERT INTO benchmark_acquisitions(acquisition_id,experiment_id,generation,"
            "quote,quote_sha256,intent,state,create_intent_at,lease_id,authorization_sha256) "
            "VALUES(%s,%s,1,%s,%s,%s,'ACTIVE',%s,%s,%s)",
            (
                acquisition_id,
                plan.experiment_id,
                jsonb(document(quote)),
                canonical_hash(document(quote)),
                jsonb(intent_claim),
                clock.now(),
                lease_id,
                "a" * 64,
            ),
        )
        tx.execute(
            "INSERT INTO benchmark_reservation_links(reservation_id,experiment_id,"
            "acquisition_id,purpose) VALUES(%s,%s,%s,'COMPUTE')",
            (row["reservation_id"], plan.experiment_id, acquisition_id),
        )
    return acquisition_id, row


def test_default_factory_acquire_binds_the_pika_client_with_the_real_signature(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H-1: acquire() on the DEFAULT composition (real PikaHttpClient) must bind
    the created pod endpoint through the real two-argument signature - the
    one-argument call crashed every default live execution after the paid pod
    was already created."""
    monkeypatch.setattr(
        "microdrama.pipeline.experimental_world.ExperimentalPresetPolicy.validate",
        lambda *args, **kwargs: None,
    )
    world, plan, authorization, budget, clock, account_id = _compose(
        db, tmp_path, comfy_transport=ReadyServingComfyTransport()
    )
    acquisition_id, lease_row = _claim_and_link(world, plan, budget, clock)
    pod = {
        "id": "pod-h1-1",
        "name": pod_name(authorization.namespace, lease_row["client_token"]),
        "image": BenchmarkSeal.model_validate(seal_data(plan)).image_ref,
        "status": "RUNNING",
        "cost": "0.500000",
        "createdAt": clock.now().isoformat(),
        "gpu": {"id": "NVIDIA A40", "count": 1, "memory": 48, "vcpuCount": 16},
        "runtime": {"ports": [{"private": 8188, "public": 8188, "type": "http"}]},
    }
    transport = ScriptedRunpodTransport(pod)
    world._provider._transport = transport
    handle = world.acquire(
        {
            "acquisition_id": acquisition_id,
            "lease_id": lease_row["id"],
            "experiment_id": plan.experiment_id,
        }
    )
    assert handle.lease.pod_id == "pod-h1-1"
    # The REAL PikaHttpClient bound the pod endpoint with the real signature.
    client = world.comfy._client
    assert client._bound_pod_id == "pod-h1-1"
    assert client._endpoint == "https://pod-h1-1-8188.proxy.runpod.net"
    assert any(call == ("POST", "https://api.runpod.io/v2/pods") for call in transport.calls)


def test_preflight_uses_the_same_policy_as_the_default_factory(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from microdrama.contracts.errors import PolicyDenied

    # L-3 (GLM Luna review): the shared seal fixture's schema evidence is
    # UNVERIFIED, so preflight's own _validate_authorization refused FIRST at
    # every revision and the monkeypatched policy was never reached - the test
    # passed vacuously at the parent commit. The authorization layer is stubbed
    # here (it has its own suite) so the POLICY is what decides readiness.
    monkeypatch.setattr(
        BenchmarkService,
        "_validate_authorization",
        lambda *args, **kwargs: None,
    )

    # Control: with the policy accepting, preflight is ready - nothing else
    # refuses, so only the policy layer can flip the verdict below. The seal
    # carries live schema evidence and a future hard stop so preflight's own
    # seal checks pass too.
    monkeypatch.setattr(
        "microdrama.pipeline.experimental_world.ExperimentalPresetPolicy.validate",
        lambda *args, **kwargs: None,
    )
    world, plan, authorization, _, clock, _ = _compose(
        db,
        tmp_path,
        comfy_transport=FailingComfyTransport(),
        seal_overrides={
            "schema_evidence": "LIVE_PROVIDER",
            "schema_attestation_source": "INDEPENDENT_RUNTIME_CAPTURE",
            "eligible_until": (T0 + timedelta(hours=6)).isoformat(),
            "hard_stop_utc": (T0 + timedelta(hours=4)).isoformat(),
        },
    )
    service = BenchmarkService(db, _settings(), clock=clock)
    result = service.preflight(plan.experiment_id, authorization, _quote())
    assert result["ready"] is True, result["reasons"]

    # Model a current preset/rights/account condition the factory rejects.
    def reject(*args: Any, **kwargs: Any) -> None:
        raise PolicyDenied("fixture policy refusal")

    monkeypatch.setattr(
        "microdrama.pipeline.experimental_world.ExperimentalPresetPolicy.validate", reject
    )
    result = service.preflight(plan.experiment_id, authorization, _quote())
    assert result["ready"] is False
    assert "authorization or sealed-manifest validation failed" in result["reasons"]


def test_acquire_fails_loudly_when_the_client_cannot_bind(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H-1: the hasattr escape hatch is gone - a comfy client without
    bind_pod_endpoint must fail loudly at acquire instead of silently skipping
    the endpoint binding that gates every later authenticated call.

    T031 R5b: acquire() now opens the boot window (a durable lease read)
    before it binds, so the loud-failure proof composes the real world and
    strips bind_pod_endpoint from the real client - the binding failure is
    still what must surface."""
    monkeypatch.setattr(
        "microdrama.pipeline.experimental_world.ExperimentalPresetPolicy.validate",
        lambda *args, **kwargs: None,
    )
    world, plan, authorization, budget, clock, account_id = _compose(
        db, tmp_path, comfy_transport=ReadyServingComfyTransport()
    )
    acquisition_id, lease_row = _claim_and_link(world, plan, budget, clock)
    pod = {
        "id": "pod-h1-2",
        "name": pod_name(authorization.namespace, lease_row["client_token"]),
        "image": BenchmarkSeal.model_validate(seal_data(plan)).image_ref,
        "status": "RUNNING",
        "cost": "0.500000",
        "createdAt": clock.now().isoformat(),
        "gpu": {"id": "NVIDIA A40", "count": 1, "memory": 48, "vcpuCount": 16},
        "runtime": {"ports": [{"private": 8188, "public": 8188, "type": "http"}]},
    }
    world._provider._transport = ScriptedRunpodTransport(pod)
    # Strip the binding from the class that actually defines it (the composed
    # client is a PikaHttpClient subclass; bind_pod_endpoint lives on the base).
    from microdrama.rendering.comfy_transport import ComfyHttpClient

    monkeypatch.delattr(ComfyHttpClient, "bind_pod_endpoint")
    with pytest.raises(AttributeError, match="bind_pod_endpoint"):
        world.acquire(
            {
                "acquisition_id": acquisition_id,
                "lease_id": lease_row["id"],
                "experiment_id": plan.experiment_id,
            }
        )
