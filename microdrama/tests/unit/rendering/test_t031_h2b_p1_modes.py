"""T031 H-2 build, package P1: world modes, provenance, EXPIRED reads (spec v3 §3, §8).

AT-4, AT-20, AT-23, AT-24. Red baselines are captured in the build report before
implementation; every test here drives public entry points (service execute /
reconcile / sweep / resume / resolve_sample and the CLI ``main``), never
``_advance`` directly.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from rendering_support import RenderWorld
from test_benchmark_experiments import _composed_world, prepare

from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode
from microdrama.contracts.errors import Conflict, EffectDenied
from microdrama.persistence import Database
from microdrama.persistence.object_store import FilesystemObjectStore
from microdrama.pipeline.benchmark import main
from microdrama.pipeline.benchmark_authorization import (
    BenchmarkAuthorization,
    BenchmarkSeal,
    load_benchmark_authorization,
)
from microdrama.pipeline.benchmark_service import BenchmarkService

pytestmark = pytest.mark.db

SCREEN_QUOTE_KEYS = (
    "maximum_runtime_ms",
    "gpu_type",
    "host_ram_gb",
    "max_storage_exposure_micro_usd",
)


def _screen_quote(world: RenderWorld) -> dict:
    return {
        "maximum_runtime_ms": 1800000,
        "gpu_type": world.config.allowed_gpu_types[0],
        "host_ram_gb": world.config.min_host_ram_gb,
        "max_storage_exposure_micro_usd": 1000,
    }


# ---------------------------------------------------------------------------
# Shared helpers (local copies of the pipeline fixture documents, dated against
# the rendering fixture clock so expiry is a knob the test turns deliberately).
# ---------------------------------------------------------------------------


def _bench_seal(plan, *, node_schema_sha256: str = "c" * 64) -> BenchmarkSeal:
    refs, ports = [], []
    for index, role in enumerate(("character_identity", "outfit", "location", "voice")):
        ref = {
            "role": role,
            "subject_id": "speaker-a",
            "asset_id": str(UUID(int=300 + index)),
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
    return BenchmarkSeal.model_validate(
        {
            "experiment_id": str(plan.experiment_id),
            "plan_sha256": plan.plan_sha256,
            "references": refs,
            "port_map": ports,
            "runtime_profile": {"profile": "fixture"},
            "image_ref": "registry.example/drama@sha256:" + "b" * 64,
            "node_schema_sha256": node_schema_sha256,
            "rights_evidence_hash": "d" * 64,
            "schema_evidence": "LIVE_PROVIDER",
            "schema_attestation_source": "INDEPENDENT_RUNTIME_CAPTURE",
            "territories": ["TH"],
            "eligible_until": "2026-10-21T00:00:00+00:00",
            "hard_stop_utc": "2026-10-20T04:00:00+00:00",
        }
    )


def _authorization_document(plan, seal, *, change="fixture-change-1"):
    return {
        "operator": "fixture-operator.invalid",
        "change_ref": change,
        "experiment_id": str(plan.experiment_id),
        "episode_id": str(plan.episode_id),
        "plan_sha256": plan.plan_sha256,
        "sealed_sha256": seal.sealed_sha256,
        "provider_account_ref": "acct:fixture",
        "max_new_exposure_micro_usd": 8_000_000,
        "max_gpu_ms": 14_400_000,
        "hard_stop_utc": "2026-10-20T03:00:00+00:00",
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


def _write_noncanonical(path: Path, document: dict) -> str:
    """Serialize with deliberately non-canonical formatting (indentation)."""
    raw = json.dumps(document, indent=3, ensure_ascii=False).encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _paid_settings() -> Settings:
    return Settings(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
    )


def _offline_settings(store_root: Path, db: Database | None = None) -> Settings:
    return Settings(
        execution_mode=ExecutionMode.OFFLINE_MOCK,
        object_store_root=store_root,
        database_url=db.dsn if db is not None else None,
    )


class _PatchedPolicy:
    """Neutralize only the live-eligibility validation layers for offline composition."""

    def __enter__(self):
        import microdrama.pipeline.experimental_world as world_module

        self._world_module = world_module
        self._policy_validate = world_module.ExperimentalPresetPolicy.validate
        self._auth_validate = BenchmarkAuthorization.validate_for
        world_module.ExperimentalPresetPolicy.validate = lambda *a, **k: None
        BenchmarkAuthorization.validate_for = lambda *a, **k: None
        return self

    def __exit__(self, *exc):
        self._world_module.ExperimentalPresetPolicy.validate = self._policy_validate
        BenchmarkAuthorization.validate_for = self._auth_validate
        return False


def _execute_service(db, comfy, ids, adapter, settings=None) -> BenchmarkService:
    def factory(**_kwargs):
        return adapter

    return BenchmarkService(
        db,
        settings or _paid_settings(),
        clock=comfy.clock,
        ids=ids,
        world_factory=factory,
    )


def _authorization_pair(world, plan, tmp_path, *, change="fixture-change-1"):
    seal = _bench_seal(plan)
    path = tmp_path / f"authorization-{change}.json"
    raw = json.dumps(
        _authorization_document(plan, seal, change=change), indent=3, ensure_ascii=False
    ).encode("utf-8")
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    authorization, loaded = load_benchmark_authorization(path)
    assert loaded == digest
    return seal, authorization, digest, raw


def _drive_resume(db, world, comfy, adapter, plan, authorization, digest, raw, *, phase, limit):
    """Loop public resume() (fresh service each step).

    §4.2: a fresh process continues work through resume - recovery polls the
    in-flight operation (U3p) before admission is allowed again, so plain
    execute() correctly refuses once anything is in flight.
    """
    last = None
    with _PatchedPolicy():
        for _ in range(limit):
            service = _execute_service(db, comfy, world.ids, adapter)
            last = service.resume(
                plan.experiment_id,
                authorization=authorization,
                quote=_screen_quote(world),
                expected_sha256=digest,
                phase=phase,
                source_bytes=raw,
            )
            comfy.clock.advance(seconds=1)
            if last["execution_state"] in (
                "SCREEN_REVIEW",
                "COMPUTE_COMPLETE",
                "FAILED",
                "NEEDS_RECONCILIATION",
            ):
                return last
    return last


def _drive_execute(db, world, comfy, adapter, plan, authorization, digest, raw, *, phase, limit):
    """Loop public execute() (fresh service each step) one dispatch step per call."""
    last = None
    with _PatchedPolicy():
        for _ in range(limit):
            service = _execute_service(db, comfy, world.ids, adapter)
            last = service.execute(
                plan.experiment_id,
                phase=phase,
                authorization=authorization,
                quote=_screen_quote(world),
                expected_sha256=digest,
                source_bytes=raw,
            )
            comfy.clock.advance(seconds=1)
            if last["execution_state"] in (
                "SCREEN_REVIEW",
                "COMPUTE_COMPLETE",
                "FAILED",
                "NEEDS_RECONCILIATION",
            ):
                return last
    return last


def _enter_submit_ambiguity(db, world, comfy, adapter, plan, tmp_path):
    """Drive public execute() until the first prompt POST times out after acceptance."""
    from microdrama.contracts.errors import NeedsReconciliation
    from microdrama.testing.fakes.comfy import FakeComfyClient

    class TimeoutOnceClient(FakeComfyClient):
        def __init__(self, state):
            super().__init__(state)
            self.timed_out = False

        def queue_prompt(self, graph, *, client_id):
            prompt_id = super().queue_prompt(graph, client_id=client_id)
            if not self.timed_out:
                self.timed_out = True
                raise NeedsReconciliation("synthetic submit timeout after acceptance")
            return prompt_id

    seal = _bench_seal(plan)
    BenchmarkService(world.db, world.settings, clock=comfy.clock, ids=world.ids).seal(
        plan.experiment_id, seal
    )
    _, authorization, digest, raw = _authorization_pair(world, plan, tmp_path)
    comfy.service._client = TimeoutOnceClient(comfy.server)
    state = _drive_execute(
        db, world, comfy, adapter, plan, authorization, digest, raw, phase="screen", limit=4
    )
    assert state["execution_state"] == "NEEDS_RECONCILIATION"
    return state


# ---------------------------------------------------------------------------
# AT-24 — no acquisition: reconcile/sweep/resume after expiry need no quote.
# ---------------------------------------------------------------------------


def test_at24_acquisitionless_experiment_recovers_without_quote_or_effects(
    db: Database, tmp_path: Path
):
    world = RenderWorld(db)
    ep, plan, service, budget, row = prepare(world)

    def forbidden(**kwargs):
        raise AssertionError("no world may be constructed for an empty experiment")

    service.world_factory = forbidden
    # Deadlines already passed: recovery still works and dispatches nothing.
    # (hard_stop is set-once, so the deadline passes by advancing the fixture clock.)
    world.clock.advance(seconds=5 * 3600)
    assert service.reconcile(plan.experiment_id)["execution_state"] == "PREPARED"
    assert service.sweep(plan.experiment_id)["execution_state"] == "PREPARED"
    resumed = service.resume(plan.experiment_id)
    assert resumed["execution_state"] == "PREPARED"
    assert resumed["admission"]["permitted"] is False
    assert any("deadline" in blocker for blocker in resumed["admission"]["blockers"])
    with world.db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT COUNT(*) FROM benchmark_acquisitions") == 0
        assert tx.fetchval("SELECT COUNT(*) FROM reservations") == 0
        assert tx.fetchval("SELECT COUNT(*) FROM provider_operations") == 0

    # The same commands through the CLI, with the store built by the CLI itself.
    settings = _offline_settings(tmp_path / "at24-store", db)
    for command in ("reconcile", "sweep", "resume"):
        assert (
            main(
                [command, "--experiment-id", str(plan.experiment_id)],
                _injection={"db": db, "settings": settings},
            )
            == 0
        ), command


# ---------------------------------------------------------------------------
# AT-23 — authorization provenance (SC-8): exact bytes, byte SHA, per acquisition.
# ---------------------------------------------------------------------------


def test_at23_provenance_bytes_sha_and_per_acquisition_recovery(db: Database, tmp_path: Path):
    from dataclasses import replace

    from comfy_support import ComfyWorld, _workflow_sha_for
    from test_benchmark_experiments import _OfflineFinalityWorld, prepare

    from microdrama.contracts.cost import RenderRequest
    from microdrama.contracts.enums import ControlKind, RenderTier
    from microdrama.pipeline.experimental_world import CanonicalExperimentWorld
    from microdrama.rendering.comfy_jobs import ComfyRenderConfig, render_id_for

    world = RenderWorld(db)
    ep, plan, service, budget, row = prepare(world)
    seal_a, authorization_a, digest_a, raw_a = _authorization_pair(
        world, plan, tmp_path, change="fixture-change-1"
    )
    _, authorization_b, digest_b, raw_b = _authorization_pair(
        world, plan, tmp_path, change="fixture-change-2"
    )
    assert digest_a != digest_b
    service.seal(plan.experiment_id, seal_a)

    comfy = ComfyWorld(
        world.db,
        tmp_path / "at23-output",
        config=replace(ComfyRenderConfig.for_mock(), lease_covered=True),
        execution_ms=0,
    )
    comfy.clock.set(world.clock.now())
    world.clock = comfy.clock
    world.leases._clock = comfy.clock
    world.provider.clock = comfy.clock
    world.manager._clock = comfy.clock
    service.clock = comfy.clock
    service.repo.clock = comfy.clock
    budget._clock = comfy.clock
    world.leases._budget = budget
    comfy.service._budget = budget
    # HB-13 (spec §9.1): the fake ComfyUI server lives only as long as its
    # pod - a cleaned-up pod's server is unreachable afterwards.
    from microdrama.testing.fakes.comfy import couple_server_to_pod_lifetime

    couple_server_to_pod_lifetime(comfy.server, world.manager)
    # HB-13/§9.1: runpod-addressed (the AT-13 pairing) so cleanups run the full
    # canonical terminate->verify->settle tail - the receipt is earned.
    from test_t045_timing import RunpodIdFakePods

    from microdrama.rendering.leases import durable_created_pod_recorder

    inner = RunpodIdFakePods(clock=comfy.clock, ids=world.ids)
    inner.created_pod_recorder = durable_created_pod_recorder(world.db, comfy.clock.now)
    world.provider = inner
    world.manager._provider = inner
    reference = UUID(int=4242)
    comfy._seed_reference_assets([reference])

    def request_factory(sample, acquisition, reservation_id):
        key = f"benchmark:{plan.experiment_id}:sample:{sample['sample_id']}:a1"
        return RenderRequest(
            render_id=render_id_for(key),
            semantic_key=key,
            episode_id=ep.episode_id,
            episode_number=1,
            shot_id=f"bench-{sample['sample_id'].lower()}",
            manifest_version=1,
            attempt_number=1,
            preset_id="fake-quality-8step",
            tier=RenderTier.QUALITY_EIGHT_STEP,
            required_controls=[ControlKind.CHARACTER_REFERENCE],
            reference_asset_ids=[reference],
            workflow_sha256=_workflow_sha_for("fake-quality-8step"),
            seed=sample["seed"],
            width=720,
            height=1280,
            fps=24,
            duration_ms=4000,
            reservation_id=reservation_id,
            prompt_text="Offline synthetic fixture.",
        )

    class OfflineWorld(_OfflineFinalityWorld, CanonicalExperimentWorld):
        pass

    adapter = OfflineWorld(
        db=world.db,
        jobs=comfy.jobs,
        leases=world.leases,
        comfy=comfy.service,
        budget=budget,
        request_factory=request_factory,
    )

    state = _drive_resume(
        db,
        world,
        comfy,
        adapter,
        plan,
        authorization_a,
        digest_a,
        raw_a,
        phase="screen",
        limit=12,
    )
    assert state["execution_state"] == "SCREEN_REVIEW", state["execution_state"]
    service.record_screening(
        plan.experiment_id,
        {
            "sealed_sha256": seal_a.sealed_sha256,
            "actor_ref": "offline-test-human",
            "output_hashes": {
                s["sample_id"]: s["output"]["sha256"]
                for s in state["samples"]
                if s["sample_id"] in ("S01-R1", "S03-R1", "S07-R1")
            },
            "decision": "PASS",
            "coverage": {"fixture-critical": "PASS"},
            "rubric_version": "offline-fixture",
        },
    )
    state = _drive_resume(
        db,
        world,
        comfy,
        adapter,
        plan,
        authorization_b,
        digest_b,
        raw_b,
        phase="full",
        limit=90,
    )
    assert state["execution_state"] == "COMPUTE_COMPLETE", state["execution_state"]

    with world.db.transaction(readonly=True) as tx:
        authorizations = tx.fetchall(
            "SELECT * FROM benchmark_authorizations WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
        acquisitions = tx.fetchall(
            "SELECT * FROM benchmark_acquisitions WHERE experiment_id=%s ORDER BY generation",
            (plan.experiment_id,),
        )
    by_sha = {row["authorization_sha256"]: row for row in authorizations}
    for digest in (digest_a, digest_b):
        stored = by_sha[digest]
        # The byte SHA is verified from the stored bytes, and parsing them yields
        # the stored payload exactly.
        assert hashlib.sha256(stored["source_bytes"]).hexdigest() == digest
        assert json.loads(stored["source_bytes"]) == stored["payload"]
    assert len(acquisitions) == 2
    assert acquisitions[0]["authorization_sha256"] == digest_a
    assert acquisitions[1]["authorization_sha256"] == digest_b

    # Per-acquisition recovery provenance: each acquisition recovers with its OWN
    # authorization - never "latest by timestamp" (B was authorized later than A).
    from microdrama.pipeline.experimental_world import load_recovery_authorization

    recovered_a = load_recovery_authorization(db, acquisitions[0]["acquisition_id"])
    recovered_b = load_recovery_authorization(db, acquisitions[1]["acquisition_id"])
    assert recovered_a.change_ref == authorization_a.change_ref
    assert recovered_b.change_ref == authorization_b.change_ref

    # A row whose stored bytes do not hash/parse to its payload is refused.
    forged_sha = hashlib.sha256(b"not-the-authorization-bytes").hexdigest()
    from microdrama.persistence.db import jsonb as _jsonb

    with world.db.transaction() as tx:
        tx.execute(
            "INSERT INTO benchmark_authorizations(experiment_id,authorization_sha256,"
            "payload,source_bytes,authorized_at) VALUES(%s,%s,%s,%s,%s)",
            (
                plan.experiment_id,
                forged_sha,
                _jsonb(_authorization_document(plan, seal_a)),
                b"not-the-authorization-bytes",
                world.clock.now() + timedelta(seconds=5),
            ),
        )
        tx.execute(
            "UPDATE benchmark_acquisitions SET authorization_sha256=%s WHERE "
            "experiment_id=%s AND generation=1",
            (forged_sha, plan.experiment_id),
        )
    with pytest.raises(Conflict):
        load_recovery_authorization(db, acquisitions[0]["acquisition_id"])


# ---------------------------------------------------------------------------
# AT-20 — expire_stale() during UNKNOWN recovery (SC-6): EXPIRED liability is
# retained in the projection, readable under §3.3, and settled canonically.
# ---------------------------------------------------------------------------


def test_at20_expired_liability_retained_readable_and_settled(db: Database, tmp_path):
    world = RenderWorld(db)
    ep, plan, service, budget, comfy, adapter = _composed_world(world, tmp_path)
    _enter_submit_ambiguity(db, world, comfy, adapter, plan, tmp_path)

    with world.db.transaction(readonly=True) as tx:
        slot = tx.fetchone(
            "SELECT s.* FROM benchmark_dispatch_slots d JOIN benchmark_samples s "
            "ON s.experiment_id=d.experiment_id AND s.sample_id=d.sample_id "
            "WHERE d.experiment_id=%s",
            (plan.experiment_id,),
        )
        operation = tx.fetchone(
            "SELECT * FROM provider_operations WHERE reservation_id=%s",
            (slot["reservation_id"],),
        )
    assert operation["state"] == "UNKNOWN"
    before = service.status(plan.experiment_id)["exposure"]

    # expire_stale() moves the prompt hold to EXPIRED with its exposure retained.
    comfy.clock.advance(seconds=601)
    budget.expire_stale()
    with world.db.transaction(readonly=True) as tx:
        reservation = tx.fetchone(
            "SELECT * FROM reservations WHERE id=%s", (slot["reservation_id"],)
        )
    assert reservation["state"] == "EXPIRED"
    after = service.status(plan.experiment_id)["exposure"]
    assert after["total"] == before["total"]  # liability is never discharged by expiry
    assert after["holds"] < before["holds"]  # the open remainder closed on expiry

    # §3.3 + R4: the EXPIRED reservation is readable for scoped recovery GETs only.
    from microdrama.pipeline.experimental_world import expired_recovery_read_allowed
    from microdrama.rendering.comfy_transport import ComfyRequestAuthorization

    auth = ComfyRequestAuthorization(
        reservation_id=slot["reservation_id"],
        episode_id=ep.episode_id,
        job_id=slot["job_id"],
        operation_id=operation["id"],
    )
    assert expired_recovery_read_allowed(
        world.db, plan.experiment_id, "RECOVERY", "/history", None, auth
    )
    assert not expired_recovery_read_allowed(
        world.db, plan.experiment_id, "RECOVERY", "/prompt", None, auth
    )
    assert not expired_recovery_read_allowed(
        world.db, plan.experiment_id, "EXECUTE", "/history", None, auth
    )
    assert not expired_recovery_read_allowed(
        world.db, plan.experiment_id, "CLEANUP", "/history", None, auth
    )
    foreign_job = ComfyRequestAuthorization(
        reservation_id=slot["reservation_id"],
        episode_id=ep.episode_id,
        job_id=UUID(int=999999),
        operation_id=operation["id"],
    )
    assert not expired_recovery_read_allowed(
        world.db, plan.experiment_id, "RECOVERY", "/history", None, foreign_job
    )

    # §5.1 keeps the pod alive through the submit ambiguity, so the cleanup the
    # resolution still owes runs through the sweep (§7.4: financial finalization
    # and cleanup continue to billing closure).
    # Terminal finalization settles the EXPIRED liability canonically, exactly once.
    resolved = service.resolve_sample(
        plan.experiment_id,
        sample_id=slot["sample_id"],
        actor_ref="operator-console",
        reason="provider console evidence for the expired hold",
        evidence_sha256="f" * 64,
        world=adapter,
    )
    assert {s["sample_id"]: s["state"] for s in resolved["samples"]}[slot["sample_id"]] == (
        "FAILED"
    )
    service.sweep(plan.experiment_id, world=adapter)
    with world.db.transaction(readonly=True) as tx:
        settled = tx.fetchone("SELECT * FROM reservations WHERE id=%s", (slot["reservation_id"],))
    assert settled["state"] == "SETTLED"
    final = service.status(plan.experiment_id)["exposure"]
    # §5.1 keeps the pod alive through the ambiguity, so its real compute usage
    # accrues until the post-resolution sweep. The expired prompt hold's
    # retained exposure closed exactly once at ZERO (lease-covered attempts
    # settle at zero: the pod lease's invoice is the only GPU cost) and nothing
    # stays open - the total is exactly the pod's accrued+settled compute.
    with world.db.transaction(readonly=True) as tx:
        prompt = tx.fetchone("SELECT * FROM reservations WHERE id=%s", (slot["reservation_id"],))
        compute = tx.fetchone(
            "SELECT r.accrued_micro_usd, r.settled_micro_usd FROM benchmark_reservation_links l "
            "JOIN reservations r ON r.id=l.reservation_id WHERE l.experiment_id=%s "
            "AND l.purpose='COMPUTE'",
            (plan.experiment_id,),
        )
    assert final["holds"] == 0
    assert prompt["state"] == "SETTLED" and prompt["settled_micro_usd"] == 0
    assert final["total"] == compute["accrued_micro_usd"] + compute["settled_micro_usd"]


# ---------------------------------------------------------------------------
# AT-4 — recovery after every deadline, through the CLI, with refusals at all
# three guard layers and zero sends (SC-7, §C).
# ---------------------------------------------------------------------------


class _RecordingComfyTransport:
    def __init__(self):
        self.calls = []

    def request(self, method, url, *, headers, body=None):
        self.calls.append((method, url))
        raise AssertionError("no ComfyUI call may leave a non-execute world")


class _RecordingRunpodTransport:
    def __init__(self, pod):
        self.pod = pod
        self.calls = []

    def request(self, method, url, *, headers, body=None):
        self.calls.append((method, url))
        if method == "GET" and url.startswith("https://api.runpod.io/v2/pods?"):
            return type("R", (), {"status": 200, "body": b'{"pods": [], "pagination": {}}'})()
        if method == "GET" and f"/pods/{self.pod['id']}" in url:
            return type("R", (), {"status": 200, "body": json.dumps(self.pod).encode()})()
        raise AssertionError(f"unexpected Runpod call: {method} {url}")


def _at4_quote(clock):
    from microdrama.pipeline.benchmark_authorization import AcquisitionQuote

    return AcquisitionQuote.model_validate(
        {
            "schema_version": 1,
            "quote_id": "at4-quote-1",
            "captured_at": clock.now() - timedelta(minutes=1),
            "expires_at": clock.now() + timedelta(minutes=30),
            "gpu_type": "NVIDIA A40",
            "host_ram_gb": 64,
            "compute_micro_usd_per_hour": 849_600,
            "container_disk_gb": 50,
            "persistent_volume_gb": 20,
            "container_storage_micro_usd_per_gb_month": 100_000,
            "persistent_storage_micro_usd_per_gb_month": 100_000,
            "max_storage_exposure_micro_usd": 1_000_000,
            "maximum_runtime_ms": 600_000,
            "source_evidence_sha256": "e" * 64,
        }
    )


def _compose_default_world(
    db, tmp_path, monkeypatch, mode, *, node_schema_sha256=None, comfy_transport=None
):
    from test_benchmark_experiments import plan_for

    from microdrama.budget import BudgetService
    from microdrama.contracts.hashing import canonical_hash
    from microdrama.contracts.season import CostPolicy
    from microdrama.persistence.db import jsonb
    from microdrama.rendering.benchmark_experiments import document
    from microdrama.rendering.leases import PodLeaseClaimRequest
    from microdrama.testing.fakes import FakeClock, SequentialIds
    from microdrama.testing.seed import seed_episode, seed_season

    monkeypatch.setattr(
        "microdrama.pipeline.experimental_world.ExperimentalPresetPolicy.validate",
        lambda *a, **k: None,
    )
    settings = _paid_settings()
    clock = FakeClock(RenderWorld(db).clock.now())
    ids = SequentialIds("at4-compose")
    budget = BudgetService(db, clock, ids, settings)
    with db.transaction() as tx:
        season_id = seed_season(tx)
        episode_id = seed_episode(tx, season_id, number=1)
        budget.open_episode_account(
            tx, season_id=season_id, episode_id=episode_id, policy=CostPolicy()
        )
    plan = plan_for(episode_id)
    service = BenchmarkService(db, settings, clock=clock, ids=ids)
    service.prepare(plan)
    seal = _bench_seal(plan, node_schema_sha256=node_schema_sha256 or "c" * 64)
    service.seal(plan.experiment_id, seal)
    authorization = BenchmarkAuthorization.model_validate(_authorization_document(plan, seal))

    def seed_credential(ref, value):
        import os

        path = tmp_path / f"{ref.replace(':', '_')}.secret"
        path.write_text(value, encoding="utf-8")
        os.chmod(path, 0o600)
        with db.transaction() as tx:
            tx.execute(
                "INSERT INTO credential_refs(ref, purpose, provider, store, locator) "
                "VALUES(%s, 'fixture', 'runpod', 'FILE', %s)",
                (ref, str(path)),
            )

    for ref in (authorization.runpod_credential_ref, authorization.comfy_credential_ref):
        seed_credential(ref, f"synthetic-{ref}")
    pod = {
        "id": "pod-at4-1",
        "name": "md-render-fixture",
        "image": seal.image_ref,
        "status": "RUNNING",
        "cost": "0.500000",
        "createdAt": clock.now().isoformat(),
        "gpu": {"id": "NVIDIA A40", "count": 1, "memory": 48, "vcpuCount": 16},
        "runtime": {"ports": [{"private": 8188, "public": 8188, "type": "http"}]},
    }
    runpod_transport = _RecordingRunpodTransport(pod)
    comfy_transport = comfy_transport or _RecordingComfyTransport()
    world = build_experiment_world_for_at4(
        settings,
        db,
        budget,
        FilesystemObjectStore(tmp_path / "at4-objects"),
        plan,
        seal,
        authorization,
        _at4_quote(clock),
        mode=mode,
        clock=clock,
        ids=ids,
        runpod_transport=runpod_transport,
        comfy_transport=comfy_transport,
    )
    # A durable acquisition + lease exists, for the recovery to act on.
    handle = world.leases.claim(
        PodLeaseClaimRequest(
            episode_id=plan.episode_id,
            semantic_key=f"benchmark:{plan.experiment_id}:acq:1",
            gpu_type="NVIDIA A40",
            host_ram_gb=64,
            lease_ttl_ms=600_000,
        )
    )
    quote = _at4_quote(clock)
    acquisition_id = UUID(int=9101)
    with world.db.transaction() as tx:
        row = tx.fetchone("SELECT * FROM pod_leases WHERE id=%s", (handle.lease.lease_id,))
        tx.execute(
            "INSERT INTO benchmark_acquisitions(acquisition_id,experiment_id,generation,"
            "quote,quote_sha256,intent,state,create_intent_at,lease_id,authorization_sha256) "
            "VALUES(%s,%s,1,%s,%s,%s,'ACTIVE',%s,%s,%s)",
            (
                acquisition_id,
                plan.experiment_id,
                jsonb(document(quote)),
                canonical_hash(document(quote)),
                jsonb({"claim": {}}),
                clock.now(),
                handle.lease.lease_id,
                authorization.authorization_sha256,
            ),
        )
        from microdrama.pipeline.benchmark_authorization import (
            canonical_document_bytes,
        )

        tx.execute(
            "INSERT INTO benchmark_authorizations(experiment_id,authorization_sha256,"
            "payload,source_bytes,authorized_at) VALUES(%s,%s,%s,%s,%s)",
            (
                plan.experiment_id,
                authorization.authorization_sha256,
                jsonb(document(authorization)),
                canonical_document_bytes(authorization),
                clock.now(),
            ),
        )
    return world, plan, authorization, runpod_transport, comfy_transport, clock, row


def build_experiment_world_for_at4(
    settings, db, budget, store, plan, seal, authorization, quote, **kwargs
):
    from microdrama.pipeline.experimental_world import build_experiment_world

    return build_experiment_world(
        settings,
        db,
        budget,
        store,
        experiment_id=plan.experiment_id,
        authorization=authorization,
        quote=quote,
        **kwargs,
    )


@pytest.mark.parametrize("mode", ["RECOVERY", "CLEANUP"])
def test_at4_non_execute_worlds_refuse_every_effect_at_three_layers(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
):
    world, plan, authorization, runpod_transport, comfy_transport, clock, lease_row = (
        _compose_default_world(db, tmp_path, monkeypatch, mode)
    )
    # Layer 1 (composition): staging/current work is refused for this mode.
    with pytest.raises(EffectDenied):
        world._native.current()

    # Layer 2 (request guard): a bound client still cannot POST a prompt.
    client = world.comfy._client
    client.bind_pod_endpoint("pod-at4-1", "https://pod-at4-1-8188.proxy.runpod.net")
    with client.authorization_scope(
        reservation_id=lease_row["reservation_id"],
        episode_id=plan.episode_id,
        job_id=UUID(int=777),
        operation_id=None,
    ):
        with pytest.raises(EffectDenied):
            client.queue_prompt({"graph": True}, client_id="at4")

    # Layer 3 (transport call): an unbound client never emits a request at all.
    from microdrama.rendering.pika_transport import PikaHttpClient

    fresh = PikaHttpClient(
        world._native.settings,
        credential_ref=authorization.comfy_credential_ref,
        credential_resolver=lambda _ref: "synthetic",
        request_guard=lambda *_a, **_k: None,
        dispatch_guard=lambda *_a, **_k: None,
        schema_sha256=seal_schema_sha(world),
        transport=_RecordingComfyTransport(),
    )
    with pytest.raises(EffectDenied):
        fresh.queue_prompt({"graph": True}, client_id="at4")

    # Create is refused before any POST leaves the process.
    with pytest.raises(EffectDenied):
        world.leases.ensure_pod(lease_row["id"])
    assert not any(method == "POST" for method, _ in runpod_transport.calls)
    assert comfy_transport.calls == []


def seal_schema_sha(world):
    with world.db.transaction(readonly=True) as tx:
        return tx.fetchval("SELECT sealed_sha256 FROM benchmark_seals LIMIT 1") or "c" * 64


def test_at4_cli_recovery_after_deadlines_returns_status_and_blocker(db: Database, tmp_path: Path):
    world = RenderWorld(db)
    ep, plan, service, budget, comfy, adapter = _composed_world(world, tmp_path)
    _enter_submit_ambiguity(db, world, comfy, adapter, plan, tmp_path)
    submissions_before = len(comfy.server.submissions)

    # Every deadline has passed: authorization, quote and rights are gone.
    # (hard_stop is set-once at seal time; the deadline passes via the clock.)
    comfy.clock.advance(seconds=6 * 3600)

    settings = _offline_settings(tmp_path / "at4-store", db)

    def offline_service_factory(db, settings, store, injection):
        return BenchmarkService(
            db,
            settings,
            store=store,
            clock=comfy.clock,
            ids=world.ids,
            world_factory=lambda **_kwargs: adapter,
        )

    import contextlib
    import io

    for command in ("reconcile", "sweep"):
        assert (
            main(
                [command, "--experiment-id", str(plan.experiment_id)],
                _injection={
                    "db": db,
                    "settings": settings,
                    "service_factory": offline_service_factory,
                },
            )
            == 0
        ), command
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(
            ["resume", "--experiment-id", str(plan.experiment_id)],
            _injection={
                "db": db,
                "settings": settings,
                "service_factory": offline_service_factory,
            },
        )
    assert code == 0
    payload = json.loads(buffer.getvalue())
    assert payload["admission"]["permitted"] is False
    assert payload["admission"]["blockers"]
    assert len(comfy.server.submissions) == submissions_before  # zero sends


# ---------------------------------------------------------------------------
# HB-10 (Codex P1-P3 review): CLI resume is fully recovery-first.
# ---------------------------------------------------------------------------


def test_hb10_expired_quote_returns_recovered_status_with_blocker(db: Database, tmp_path: Path):
    """HB-10: a well-formed but EXPIRED quote passes the presence-level
    admission check, and the execute step then refuses on eligibility (the
    EXECUTE world composition refuses the expired quote - modeled at the
    exact boundary the production policy raises it, since the harness's
    patched preset policy bypasses quote freshness). Resume must return the
    RECOVERED durable status with an admission blocker - not raise past the
    CLI as an error."""
    from datetime import datetime as _dt

    from test_t031_h2b_p3_ambiguity import (
        _base,
        _execute_service,
        _PatchedPolicy,
        _TimeoutOnNthClient,
    )

    from microdrama.contracts.errors import EffectDenied

    base = _base(db, tmp_path)
    world, ep, plan, service, comfy, adapter, authorization, digest, raw = base
    comfy.service._client = _TimeoutOnNthClient(comfy.server, on={1})
    first = _execute_service(db, comfy, world.ids, adapter)
    with _PatchedPolicy():
        first.execute(
            plan.experiment_id,
            phase="screen",
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            source_bytes=raw,
        )

    # The quote expires AFTER the ambiguity: recovery works from durable
    # records; the EXECUTE composition for new work refuses it.
    expired = dict(_screen_quote(world))
    expired["expires_at"] = (comfy.clock.now() - timedelta(seconds=1)).isoformat()

    def factory(**kwargs):
        quote_arg = kwargs.get("quote")
        if kwargs.get("mode", "EXECUTE") == "EXECUTE" and isinstance(quote_arg, dict):
            expires = quote_arg.get("expires_at")
            if expires is not None and _dt.fromisoformat(expires) <= comfy.clock.now():
                raise EffectDenied("the acquisition quote is expired")
        return adapter

    fresh = BenchmarkService(
        db,
        _paid_settings(),
        clock=comfy.clock,
        ids=world.ids,
        world_factory=factory,
    )
    with _PatchedPolicy():
        resumed = fresh.resume(
            plan.experiment_id,
            authorization=authorization,
            quote=expired,
            expected_sha256=digest,
            phase="screen",
            source_bytes=raw,
        )
    assert resumed["admission"]["permitted"] is False
    assert any("admission refused" in blocker for blocker in resumed["admission"]["blockers"])


def test_hb10_cleanup_only_resume_ignores_broken_generation_documents(db: Database, tmp_path: Path):
    """HB-10: --cleanup-only resume owes no generation inputs: an invalid,
    irrelevant authorization file (and a missing quote file) must not prevent
    the sweep; the command still exits 0 with the swept status."""
    import contextlib
    import io

    from test_t031_h2b_p3_ambiguity import (
        _base,
        _execute_service,
        _PatchedPolicy,
        _TimeoutOnNthClient,
    )

    from microdrama.pipeline.benchmark import main

    base = _base(db, tmp_path)
    world, ep, plan, service, comfy, adapter, authorization, digest, raw = base
    comfy.service._client = _TimeoutOnNthClient(comfy.server, on={1})
    first = _execute_service(db, comfy, world.ids, adapter)
    with _PatchedPolicy():
        first.execute(
            plan.experiment_id,
            phase="screen",
            authorization=authorization,
            quote=_screen_quote(world),
            expected_sha256=digest,
            source_bytes=raw,
        )
    broken = tmp_path / "broken-authorization.json"
    broken.write_text("{ not json at all", encoding="utf-8")
    settings = _offline_settings(tmp_path / "hb10-store", db)

    def offline_service_factory(broken_db, broken_settings, store, injection):
        return BenchmarkService(
            broken_db,
            broken_settings,
            store=store,
            clock=comfy.clock,
            ids=world.ids,
            world_factory=lambda **_kwargs: adapter,
        )

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(
            [
                "resume",
                "--experiment-id",
                str(plan.experiment_id),
                "--cleanup-only",
                "--authorization",
                str(broken),
                "--quote",
                str(tmp_path / "missing-quote.json"),
            ],
            _injection={
                "db": db,
                "settings": settings,
                "service_factory": offline_service_factory,
            },
        )
    assert code == 0
    payload = json.loads(buffer.getvalue())
    assert payload["execution_state"]  # the swept durable status, not an error


# ---------------------------------------------------------------------------
# HB-13 (Codex P1-P3 review): AT-4's third-layer probe used an unbound client
# with permissive guards - it proved the unbound refusal, not independent
# RECOVERY-mode transport denial. Each transport-layer guard is isolated below
# with otherwise VALID inputs.
# ---------------------------------------------------------------------------


class _SchemaServingTransport:
    """Serves only the schema attestation GET; a POST reaching this transport
    is the EXECUTE control's boundary (recorded, then refused loudly)."""

    def __init__(self, schema_bytes: bytes):
        self.schema_bytes = schema_bytes
        self.calls: list[tuple[str, str]] = []

    def request(self, method, url, *, headers, body=None):
        self.calls.append((method, url))
        if method == "GET" and url.endswith("/object_info"):
            return self.schema_bytes
        raise AssertionError(f"HB-13 probe transport reached {method} {url}")


def _hb13_guard_probe(db, tmp_path, monkeypatch, mode: str):
    """A composed AT-4 world whose durable rows are the FULL valid shape the
    request guard checks: a bound lease carrying the world's identity, an
    ACTIVE prompt hold, a job, a provider operation and a claimed sample
    linking them - plus a client bound to the pod and a verifiable schema."""

    from test_t031_h2b_p2_gate import _prompt_hold_request

    from microdrama.budget import BudgetService
    from microdrama.persistence.db import jsonb
    from microdrama.rendering.pika_transport import mapped_schema_sha256
    from microdrama.rendering.workflows.templates import PIKA_TEMPLATE
    from microdrama.testing.fakes import SequentialIds

    fixture = json.loads(
        (
            Path(__file__).parents[2]
            / "fixtures/pika_h3_flex_object_info_OFFLINE_FIXTURE_ONLY.json"
        ).read_text()
    )
    raw_schema = fixture["schemas"]
    schema_bytes = json.dumps(raw_schema).encode()
    schema_sha = mapped_schema_sha256(raw_schema, PIKA_TEMPLATE.node_classes)

    transport = _SchemaServingTransport(schema_bytes)
    world, plan, authorization, runpod_transport, _shared, clock, lease_row = (
        _compose_default_world(
            db,
            tmp_path,
            monkeypatch,
            mode,
            node_schema_sha256=schema_sha,
            comfy_transport=transport,
        )
    )
    budget = BudgetService(
        db, clock, SequentialIds("hb13-at4"), _offline_settings(tmp_path / "hb13-store", db)
    )
    hold = budget.reserve(_prompt_hold_request(world, plan.episode_id, plan, "S01-R1", clock))
    job_id = UUID(int=778)
    operation_id = UUID(int=779)
    owned_tag = f"microdrama-owned:{authorization.namespace}"
    with db.transaction() as tx:
        tx.execute(
            "UPDATE pod_leases SET pod_id='pod-at4-1', owned_tag=%s, "
            "provider_account_ref=%s WHERE id=%s",
            (owned_tag, authorization.provider_account_ref, lease_row["id"]),
        )
        tx.execute(
            "INSERT INTO jobs(id,job_type,queue,semantic_key,input_hash,input,status) "
            "VALUES(%s,'render.shot','production',%s,%s,%s,'WAITING_EXTERNAL')",
            (
                job_id,
                f"benchmark:{plan.experiment_id}:sample:S01-R1:a1",
                "a" * 64,
                jsonb({}),
            ),
        )
        tx.execute(
            "INSERT INTO provider_operations(id,provider,operation_kind,client_token,"
            "request_hash,state,reservation_id,job_id,deadline_at) "
            "VALUES(%s,'comfyui','comfy.queue_prompt','hb13-op',%s,"
            "'SUBMITTED',%s,%s,%s)",
            (
                operation_id,
                "e" * 64,
                hold.id,
                job_id,
                clock.now() + timedelta(minutes=30),
            ),
        )
        tx.execute(
            "UPDATE benchmark_samples SET state='CLAIMED',job_id=%s,reservation_id=%s,"
            "acquisition_id=%s,operation_id=%s WHERE experiment_id=%s AND sample_id='S01-R1'",
            (job_id, hold.id, UUID(int=9101), operation_id, plan.experiment_id),
        )
    client = world.comfy._client
    client.bind_pod_endpoint("pod-at4-1", "https://pod-at4-1-8188.proxy.runpod.net")
    return world, plan, client, transport, hold, job_id, operation_id


def test_hb13_at4_recovery_mode_denial_isolated_with_valid_inputs(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """HB-13 guard 1 (mode): every ownership input valid, the schema verifies -
    ONLY the world mode is RECOVERY. The prompt POST is refused by the mode
    rule itself, before any transport POST; guard 2 (ownership) refuses the
    same valid shape with a foreign job, independently of the mode rule."""

    from test_t031_h2b_p3_ambiguity import _valid_fake_graph

    world, plan, client, transport, hold, job_id, operation_id = _hb13_guard_probe(
        db, tmp_path, monkeypatch, "RECOVERY"
    )
    with client.authorization_scope(
        reservation_id=hold.id,
        episode_id=plan.episode_id,
        job_id=job_id,
        operation_id=operation_id,
    ):
        with pytest.raises(EffectDenied, match="recovery world cannot dispatch prompts"):
            client.queue_prompt(_valid_fake_graph(), client_id="hb13-mode")
    assert [method for method, _ in transport.calls] == ["GET"]  # attestation only
    assert not any(method == "POST" for method, _ in transport.calls)

    with client.authorization_scope(
        reservation_id=hold.id,
        episode_id=plan.episode_id,
        job_id=UUID(int=555),
        operation_id=operation_id,
    ):
        with pytest.raises(
            EffectDenied, match="differs from experiment sample/acquisition ownership"
        ):
            client.queue_prompt(_valid_fake_graph(), client_id="hb13-owner")


def test_hb13_at4_execute_control_reaches_the_transport(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """HB-13 control (EXECUTE): the same valid inputs pass every guard and the
    POST itself reaches the transport boundary - the RECOVERY denial is the
    mode rule's, not an artifact of invalid inputs."""

    from test_t031_h2b_p3_ambiguity import _valid_fake_graph

    world, plan, client, transport, hold, job_id, operation_id = _hb13_guard_probe(
        db, tmp_path, monkeypatch, "EXECUTE"
    )
    with client.authorization_scope(
        reservation_id=hold.id,
        episode_id=plan.episode_id,
        job_id=job_id,
        operation_id=operation_id,
    ):
        with pytest.raises(AssertionError, match="HB-13 probe transport"):
            client.queue_prompt(_valid_fake_graph(), client_id="hb13-execute")
    assert transport.calls[-1][0] == "POST"  # the POST reached the boundary
