"""T031 durability/money regressions against isolated actual PostgreSQL."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from rendering_support import RenderWorld
from test_t045_timing import RunpodIdFakePods

from microdrama.contracts.cost import BudgetReservationRequest, ExposureCeilings
from microdrama.contracts.enums import BudgetCategory, BudgetScopeKind, QueueName
from microdrama.contracts.errors import BudgetExhausted, Conflict, EffectDenied
from microdrama.persistence.db import jsonb
from microdrama.pipeline.benchmark_authorization import BenchmarkPlan
from microdrama.pipeline.benchmark_service import BenchmarkService
from microdrama.rendering.benchmark_experiments import ExperimentBudgetService
from microdrama.rendering.leases import (
    PodLeaseClaimRequest,
    durable_created_pod_recorder,
    mock_pod_price,
)

pytestmark = pytest.mark.db


def plan_for(episode_id, **changes):
    return BenchmarkPlan.model_validate(
        {
            "experiment_id": str(uuid4()),
            "episode_id": str(episode_id),
            "runtime_profile_sha256": "a" * 64,
            "shots": [
                {"shot_id": f"S0{i}", "thai_line": "สวัสดี", "english_line": "Hello"}
                for i in range(1, 9)
            ],
            "samples": [
                {
                    "sample_id": f"S0{i}-R{r}",
                    "shot_id": f"S0{i}",
                    "repeat": r,
                    "seed": 310000 + i * 100 + r,
                }
                for i in range(1, 9)
                for r in range(1, 4)
            ],
            "max_new_exposure_micro_usd": 8_000_000,
            "max_gpu_ms": 14_400_000,
            **changes,
        }
    )


def prepare(world, episode_number: int = 1, **changes):
    ep = world.episode(number=episode_number)
    plan = plan_for(ep.episode_id, **changes)
    service = BenchmarkService(world.db, world.settings, clock=world.clock, ids=world.ids)
    row = service.prepare(plan)
    # Budget tests bind only the immutable hard stop; seal/binder tests separately
    # validate actual sealed references. No executable readiness is fabricated.
    import hashlib
    import json as _json

    provenance = _json.dumps(
        {"synthetic": "offline-fixture", "experiment_id": str(plan.experiment_id)}
    ).encode()
    with world.db.transaction() as tx:
        tx.execute(
            "UPDATE benchmark_experiments SET hard_stop=%s WHERE experiment_id=%s",
            (world.clock.now() + timedelta(hours=4), plan.experiment_id),
        )
        # Offline-composed admission still records its provenance row (0026:
        # every acquisition carries the authorization accepted for it).
        tx.execute(
            "INSERT INTO benchmark_authorizations(experiment_id,authorization_sha256,"
            "payload,source_bytes,authorized_at) VALUES(%s,%s,%s,%s,%s) "
            "ON CONFLICT DO NOTHING",
            (
                plan.experiment_id,
                hashlib.sha256(provenance).hexdigest(),
                jsonb(_json.loads(provenance.decode())),
                provenance,
                world.clock.now(),
            ),
        )
    budget = ExperimentBudgetService(
        world.db, world.clock, world.ids, world.settings, experiment_id=plan.experiment_id
    )
    return ep, plan, service, budget, row


def hold(world, episode_id, key, worst=1000):
    price = mock_pod_price().model_copy(update={"unit_price_micro_usd": 1})
    return BudgetReservationRequest(
        request_id=uuid4(),
        semantic_key=key,
        scope_kind=BudgetScopeKind.EPISODE,
        episode_id=episode_id,
        season_id=None,
        category=BudgetCategory.GPU_GENERATION,
        queue=QueueName.PRODUCTION,
        provider="fake-runpod",
        operation_kind="comfy.queue_prompt",
        price=price,
        ceilings=ExposureCeilings(timeout_ms=1000, max_units=1),
        worst_case_micro_usd=worst,
        expires_at=world.clock.now() + timedelta(hours=1),
    )


def test_prepare_replay_conflict_and_uuid_alias_without_new_budget(world: RenderWorld):
    ep, plan, service, budget, row = prepare(world)
    assert row["plan_sha256"] == plan.plan_sha256
    assert service.prepare(plan)["experiment_id"] == plan.experiment_id
    alias = plan.model_copy(update={"experiment_id": uuid4()})
    assert service.prepare(alias)["experiment_id"] == plan.experiment_id
    changed = plan.model_copy(update={"experiment_nonce": "intentional repeat"})
    with pytest.raises(Conflict):
        service.prepare(changed)
    repeated = changed.model_copy(update={"experiment_id": uuid4()})
    service.prepare(repeated)
    with world.db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT COUNT(*) FROM benchmark_samples") == 48
        assert tx.fetchval("SELECT COUNT(*) FROM budget_accounts") == 1
        assert tx.fetchval("SELECT COUNT(*) FROM reservations") == 0
        assert tx.fetchval("SELECT COUNT(*) FROM jobs") == 0
    assert service.status(plan.experiment_id)["execution_state"] == "PREPARED"


def test_candidate_counted_once_and_replay_linked_once(world: RenderWorld):
    ep, plan, service, budget, row = prepare(world, max_new_exposure_micro_usd=251_000)
    request = hold(world, ep.episode_id, "benchmark-exact-boundary", 1000)
    first = budget.reserve(request)
    second = budget.reserve(request)
    assert first.id == second.id
    assert service.status(plan.experiment_id)["exposure"]["total"] == 1000
    with world.db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT COUNT(*) FROM benchmark_reservation_links") == 1
    with pytest.raises(BudgetExhausted):
        budget.reserve(hold(world, ep.episode_id, "one-too-many", 1))
    with world.db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT COUNT(*) FROM reservations") == 1
        assert tx.fetchval("SELECT COUNT(*) FROM benchmark_reservation_links") == 1


def test_two_workers_final_affordable_boundary_is_atomic(world: RenderWorld):
    ep, plan, service, budget, row = prepare(world, max_new_exposure_micro_usd=251_000)

    def reserve(index):
        try:
            return budget.reserve(hold(world, ep.episode_id, f"race-{index}", 1000)).id
        except BudgetExhausted:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, range(2)))
    assert sum(result is not None for result in results) == 1
    assert service.status(plan.experiment_id)["exposure"]["total"] == 1000


def test_shared_account_ordinary_reservation_still_keeps_ten_dollar_cap(world: RenderWorld):
    ep, plan, service, budget, row = prepare(world)
    budget.reserve(hold(world, ep.episode_id, "experiment-first", 1000))
    with pytest.raises(BudgetExhausted):
        world.budget.reserve(hold(world, ep.episode_id, "ordinary-cap", 10_000_000))
    with world.db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT COUNT(*) FROM reservations") == 1


def test_local_preflight_and_denied_execution_never_construct_provider_world(world: RenderWorld):
    ep, plan, service, budget, row = prepare(world)

    def forbidden(**kwargs):
        raise AssertionError("provider world must not be constructed")

    service.world_factory = forbidden
    assert service.preflight(plan.experiment_id)["ready"] is False
    assert len(service.status(plan.experiment_id)["samples"]) == 24
    with pytest.raises(EffectDenied):
        service.execute(
            plan.experiment_id,
            phase="screen",
            authorization=None,
            quote=None,
            expected_sha256="a" * 64,
        )
    assert all(s["quality"] == "UNKNOWN" for s in service.export(plan.experiment_id)["samples"])
    assert service.export(plan.experiment_id)["billed_micro_usd"] is None


def test_pre_reserved_lease_adoption_never_takes_second_hold(world: RenderWorld):
    ep = world.episode()
    request = PodLeaseClaimRequest(
        episode_id=ep.episode_id,
        semantic_key="benchmark:adopt",
        gpu_type=world.config.allowed_gpu_types[0],
        host_ram_gb=world.config.min_host_ram_gb,
    )
    reservation, _ = world.leases._reserve_for_lease(request, world.config.lease_ttl_ms)
    first = world.leases.claim_pre_reserved(request, reservation.id)
    second = world.leases.claim_pre_reserved(request, reservation.id)
    assert first.lease.lease_id == second.lease.lease_id
    with world.db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT COUNT(*) FROM reservations") == 1
        assert tx.fetchval("SELECT COUNT(*) FROM pod_leases") == 1
    wrong = PodLeaseClaimRequest(
        episode_id=ep.episode_id,
        semantic_key="benchmark:wrong",
        gpu_type=request.gpu_type,
        host_ram_gb=request.host_ram_gb,
    )
    with pytest.raises(Conflict):
        world.leases.claim_pre_reserved(wrong, reservation.id)


def test_canonical_accrual_settlement_credit_adjustment_projection(world: RenderWorld):
    from microdrama.contracts.cost import UsageReceipt
    from microdrama.contracts.enums import CostBasis, PriceUnit, Provenance, ReceiptKind

    ep, plan, service, budget, row = prepare(world)
    reservation = budget.reserve(hold(world, ep.episode_id, "projection", 1000))

    def receipt(kind, amount, key):
        return UsageReceipt(
            receipt_id=uuid4(),
            provider="fake-runpod",
            provider_receipt_id=key,
            kind=kind,
            cost_basis=CostBasis.SYNTHETIC_FAKE,
            reservation_id=reservation.id,
            episode_id=ep.episode_id,
            season_id=None,
            category=BudgetCategory.GPU_GENERATION,
            amount_micro_usd=amount,
            units=1,
            unit=PriceUnit.GPU_SECOND,
            observed_at=world.clock.now(),
            provenance=Provenance.FAKE_SYNTHETIC,
        )

    world.budget.record_usage(receipt(ReceiptKind.ACCRUAL, 300, "accrual"))
    assert service.status(plan.experiment_id)["exposure"]["total"] == 1000
    world.budget.record_usage(receipt(ReceiptKind.SETTLEMENT, 400, "settlement"))
    assert service.status(plan.experiment_id)["exposure"]["total"] == 400
    world.budget.record_usage(receipt(ReceiptKind.CREDIT, 100, "credit"))
    assert service.status(plan.experiment_id)["exposure"]["total"] == 400
    adjustment = receipt(ReceiptKind.ADJUSTMENT, 50, "adjustment")
    world.budget.record_usage(adjustment)
    world.budget.record_usage(adjustment)
    assert service.status(plan.experiment_id)["exposure"]["total"] == 450


def test_failed_outcome_survives_later_cleanup_and_closure(world: RenderWorld):
    ep, plan, service, budget, row = prepare(world)
    service.repo.outcome(plan.experiment_id, "FAILED")
    with pytest.raises(BudgetExhausted):
        budget.reserve(hold(world, ep.episode_id, "after-failure"))
    with world.db.transaction() as tx:
        tx.execute(
            "UPDATE benchmark_experiments SET cleanup_state='VERIFIED',billing_state='BILLED' WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
    assert service.status(plan.experiment_id)["execution_outcome"] == "FAILED"
    assert service.export(plan.experiment_id)["cleanup_state"] == "VERIFIED"


class _OfflineFinalityWorld:
    """Mixin translating the actual synthetic lease stop receipt for offline tests.

    Production adapter still requires durable termination + provider invoice finality.
    This fixture does not attest a live schema, approve an episode or call execute.
    """

    def cleanup(self, acquisition):
        # §9.1/HB-13 restored strictness: only a VERIFIED TERMINATION is cleanup
        # evidence. The two unconditional assertions H-2 dropped are back (every
        # pod-bound cleanup stopped compute and holds durable stop evidence, or
        # the fixture fails loudly), and a verified stop ALONE no longer
        # fabricates a VERIFIED/BILLED/storage-final receipt - the offline close
        # through the default synthetic provider stops without terminating, so
        # it reports unverified/pending exactly like production until the
        # terminate->verify tail (the runpod-addressed pairing, or the janitor)
        # completes it.
        result = self.leases.shutdown(
            acquisition["lease_id"], reason="offline benchmark phase boundary"
        )
        with self.db.transaction(readonly=True) as tx:
            row = tx.fetchone("SELECT * FROM pod_leases WHERE id=%s", (acquisition["lease_id"],))
        terminated = row["terminate_verified_at"] is not None
        if row["pod_id"] is not None:
            assert result.compute_stopped
            assert row["stop_verified_at"] is not None
        return {
            "verified": terminated,
            "compute_window_end": row["compute_window_end_at"],
            "billing_state": (
                "BILLED"
                if terminated and not result.billing_pending
                else "PENDING_PROVIDER_FINALITY"
            ),
            "storage_final": terminated,
        }


def test_composed_24_samples_use_actual_jobs_holds_leases_and_comfy_recovery(
    world: RenderWorld, tmp_path
):
    from dataclasses import replace

    from comfy_support import ComfyWorld, _workflow_sha_for

    from microdrama.contracts.cost import RenderRequest
    from microdrama.contracts.enums import ControlKind, RenderTier
    from microdrama.pipeline.experimental_world import CanonicalExperimentWorld
    from microdrama.rendering.comfy_jobs import ComfyRenderConfig, render_id_for

    ep, plan, service, budget, row = prepare(world)
    comfy = ComfyWorld(
        world.db,
        tmp_path / "composed-output",
        config=replace(ComfyRenderConfig.for_mock(), lease_covered=True),
        execution_ms=0,
    )
    # One injected clock is shared by actual services/provider fixtures.
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
    # HB-13/§9.1: the composed benchmark world is runpod-addressed (the AT-13
    # pairing) so every pod cleanup runs the canonical stop->terminate->verify->
    # settle tail offline - a VERIFIED/BILLED cleanup receipt is EARNED through
    # the real tail, never synthesized from a mere verified stop. A provider the
    # test already made runpod-addressed (its own scenarios/recorder) is kept.
    if world.manager._provider.provider_id != "runpod":
        inner = RunpodIdFakePods(clock=comfy.clock, ids=world.ids)
        inner.created_pod_recorder = durable_created_pod_recorder(world.db, comfy.clock.now)
        world.provider = inner
        world.manager._provider = inner
    reference = uuid4()
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
    quote = {
        "maximum_runtime_ms": 1800000,
        "gpu_type": world.config.allowed_gpu_types[0],
        "host_ram_gb": world.config.min_host_ram_gb,
        "max_storage_exposure_micro_usd": 1000,
    }
    for _ in range(8):
        state = service._advance(plan.experiment_id, adapter, "screen", quote)
        if state["execution_state"] == "SCREEN_REVIEW":
            break
        comfy.clock.advance(seconds=1)
    assert state["execution_state"] == "SCREEN_REVIEW"
    assert len(comfy.server.submissions) == 3
    assert all(a["state"] == "CLOSED" for a in state["acquisitions"])
    assert {s["sample_id"] for s in state["samples"] if s["state"] == "SUCCEEDED"} == {
        "S01-R1",
        "S03-R1",
        "S07-R1",
    }
    # Only the actual experimental screening record permits continuation. Bind
    # exact durable hashes; quality claims remain UNKNOWN on the sample exports.
    with world.db.transaction() as tx:
        tx.execute(
            "UPDATE benchmark_experiments SET sealed_sha256=%s WHERE experiment_id=%s",
            ("b" * 64, plan.experiment_id),
        )
    service.record_screening(
        plan.experiment_id,
        {
            "sealed_sha256": "b" * 64,
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
    with world.db.transaction() as tx:
        tx.execute(
            "UPDATE benchmark_experiments SET execution_state='FULL_RUNNING' WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
    for _ in range(30):
        # New process/coordinator object over the same durable SQL each time.
        service = BenchmarkService(world.db, world.settings, clock=comfy.clock, ids=world.ids)
        state = service._advance(plan.experiment_id, adapter, "full", quote)
        assert state["execution_outcome"] in (None, "SUCCEEDED"), {
            "state": state["execution_state"],
            "samples": [sample for sample in state["samples"] if sample["state"] == "FAILED"],
        }
        if state["execution_state"] == "COMPUTE_COMPLETE":
            break
        comfy.clock.advance(seconds=1)
    assert state["execution_state"] == "COMPUTE_COMPLETE"
    assert state["execution_outcome"] == "SUCCEEDED"
    assert len(comfy.server.submissions) == 24
    assert all(s["state"] == "SUCCEEDED" for s in state["samples"])
    assert all(s["quality"] == "UNKNOWN" for s in service.export(plan.experiment_id)["samples"])
    with world.db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT COUNT(*) FROM jobs") == 24
        # Both acquisitions also reserve their ordinary canonical cleanup grant.
        # Assert each purpose rather than overlooking those protective holds.
        purposes = tx.fetchall(
            "SELECT purpose,COUNT(*) AS count FROM benchmark_reservation_links GROUP BY purpose"
        )
        assert {row["purpose"]: row["count"] for row in purposes} == {
            "PROMPT": 24,
            "COMPUTE": 2,
            "STORAGE": 2,
            "CLEANUP": 2,
        }
        assert tx.fetchval("SELECT COUNT(*) FROM benchmark_reservation_links") == 30
        assert (
            tx.fetchval("SELECT COUNT(DISTINCT reservation_id) FROM benchmark_reservation_links")
            == 30
        )
        assert (
            tx.fetchval("SELECT COUNT(*) FROM reservations WHERE semantic_key LIKE '%:sample:%'")
            == 24
        )


class _LaggingCreatePods(RunpodIdFakePods):
    """H-2 fixture: the timed-out create POST actually landed at the provider,
    but the pod listing lags - the pod only becomes visible on the THIRD
    reconciliation pass (create-time, the manager's immediate retry, then the
    sweep's shutdown reconciliation)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.last_request = None
        self.find_calls = 0

    def create_pod(self, request):
        self.last_request = request
        return super().create_pod(request)

    def find_pods(self, *, owned_tag=None, client_token=None):
        self.find_calls += 1
        found = super().find_pods(owned_tag=owned_tag, client_token=client_token)
        if (
            not found
            and client_token is not None
            and self.find_calls >= 3
            and self.last_request is not None
            and self.last_request.client_token == client_token
        ):
            # the list lag resolved: the pod from the timed-out POST is visible now
            return [self.create_pod(self.last_request)]
        return found


def _composed_world(
    world: RenderWorld,
    tmp_path,
    *,
    episode_number: int = 1,
    plan_changes: dict | None = None,
    **kwargs,
):
    """The composed screen harness from the 24-sample test, parameterized.

    ``plan_changes`` override plan-document fields (e.g. max_gpu_ms) so a
    limit can be made decisively tight for a test."""
    from dataclasses import replace

    from comfy_support import ComfyWorld, _workflow_sha_for

    from microdrama.contracts.cost import RenderRequest
    from microdrama.contracts.enums import ControlKind, RenderTier
    from microdrama.pipeline.experimental_world import CanonicalExperimentWorld
    from microdrama.rendering.comfy_jobs import ComfyRenderConfig, render_id_for

    ep, plan, service, budget, row = prepare(
        world, episode_number=episode_number, **(plan_changes or {})
    )
    comfy = ComfyWorld(
        world.db,
        tmp_path / "composed-h2-output",
        config=replace(ComfyRenderConfig.for_mock(), lease_covered=True),
        execution_ms=0,
        **kwargs,
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
    # HB-13/§9.1: the composed benchmark world is runpod-addressed (the AT-13
    # pairing) so every pod cleanup runs the canonical stop->terminate->verify->
    # settle tail offline - a VERIFIED/BILLED cleanup receipt is EARNED through
    # the real tail, never synthesized from a mere verified stop. A provider the
    # test already made runpod-addressed (its own scenarios/recorder) is kept.
    if world.manager._provider.provider_id != "runpod":
        inner = RunpodIdFakePods(clock=comfy.clock, ids=world.ids)
        inner.created_pod_recorder = durable_created_pod_recorder(world.db, comfy.clock.now)
        world.provider = inner
        world.manager._provider = inner
    reference = uuid4()
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
    return ep, plan, service, budget, comfy, adapter


def _screen_quote(world: RenderWorld) -> dict:
    return {
        "maximum_runtime_ms": 1800000,
        "gpu_type": world.config.allowed_gpu_types[0],
        "host_ram_gb": world.config.min_host_ram_gb,
        "max_storage_exposure_micro_usd": 1000,
    }


def test_unknown_create_with_late_pod_is_found_and_the_experiment_resumes(
    world: RenderWorld, tmp_path
) -> None:
    """H-2: an ambiguous create whose Pod appears later (list lag) is FOUND - the
    sweep's shutdown reconciliation adopts it, the acquisition closes (never
    UNKNOWN-forever), and reconcile + a restarted coordinator resume the screen."""
    from test_t045_timing import T0 as TIMING_T0

    from microdrama.testing.fakes import FakeClock, SequentialIds
    from microdrama.testing.fakes.pods import PodCreateScenario

    world.provider = _LaggingCreatePods(
        clock=FakeClock(TIMING_T0), ids=SequentialIds("t031-h2-lag")
    )
    world.provider.queue_scenarios(PodCreateScenario.CREATE_TIMEOUT_NOT_CREATED)
    world.provider.created_pod_recorder = durable_created_pod_recorder(world.db, world.clock.now)
    world.manager._provider = world.provider
    ep, plan, service, budget, comfy, adapter = _composed_world(world, tmp_path)
    state = service._advance(plan.experiment_id, adapter, "screen", _screen_quote(world))
    # The create timed out: the experiment enters NEEDS_RECONCILIATION...
    assert state["execution_state"] == "NEEDS_RECONCILIATION"
    acquisition = state["acquisitions"][0]
    # ...but the sweep's shutdown reconciliation FOUND the late pod: the lease is
    # bound and released with it, and the acquisition is NOT stuck UNKNOWN.
    assert acquisition["state"] != "UNKNOWN"
    with world.db.transaction(readonly=True) as tx:
        lease = tx.fetchone("SELECT * FROM pod_leases WHERE id=%s", (acquisition["lease_id"],))
    assert lease["pod_id"] is not None
    assert lease["terminate_verified_at"] is not None
    # Reconcile (a fresh coordinator over the same durable state) resumes.
    fresh = BenchmarkService(world.db, world.settings, clock=comfy.clock, ids=world.ids)
    resumed = fresh.reconcile(plan.experiment_id, world=adapter)
    assert resumed["execution_state"] == "SCREEN_RUNNING"
    for _ in range(8):
        state = fresh._advance(plan.experiment_id, adapter, "screen", _screen_quote(world))
        if state["execution_state"] == "SCREEN_REVIEW":
            break
        comfy.clock.advance(seconds=1)
    assert state["execution_state"] == "SCREEN_REVIEW"
    assert len(comfy.server.submissions) == 3
    # Exactly one pod was ever created for the whole screen: no second create.
    assert world.provider.find_calls >= 3
    with world.db.transaction(readonly=True) as tx:
        owns = tx.fetchall("SELECT * FROM pod_storage_ownership")
    assert owns and all(row["valid_until"] is not None for row in owns)


def test_unknown_create_without_pod_is_operator_resolved_and_resumes(
    world: RenderWorld, tmp_path
) -> None:
    """H-2: a create that stays podless keeps its UNKNOWN marker and slot; the
    audited operator CLI (resolve --acquisition-id) posts the podless resolution,
    sets NO_CREATE_PROVEN, frees the partial-index slot, and the experiment
    resumes on a NEW acquisition generation."""
    from test_t045_timing import T0 as TIMING_T0

    from microdrama.testing.fakes import FakeClock, SequentialIds
    from microdrama.testing.fakes.pods import PodCreateScenario

    world.provider = RunpodIdFakePods(
        clock=FakeClock(TIMING_T0), ids=SequentialIds("t031-h2-podless")
    )
    world.provider.queue_scenarios(PodCreateScenario.CREATE_TIMEOUT_NOT_CREATED)
    world.provider.created_pod_recorder = durable_created_pod_recorder(world.db, world.clock.now)
    world.manager._provider = world.provider
    ep, plan, service, budget, comfy, adapter = _composed_world(world, tmp_path)
    state = service._advance(plan.experiment_id, adapter, "screen", _screen_quote(world))
    assert state["execution_state"] == "NEEDS_RECONCILIATION"
    acquisition = state["acquisitions"][0]
    assert acquisition["state"] == "UNKNOWN"
    # Automatic reconcile cannot resolve absence - it stays UNKNOWN.
    still = service.reconcile(plan.experiment_id, world=adapter)
    assert still["execution_state"] == "NEEDS_RECONCILIATION"
    assert still["acquisitions"][0]["state"] == "UNKNOWN"
    # The audited operator resolution (actor, reason, sha256 evidence) closes it.
    resolved = service.resolve_create(
        plan.experiment_id,
        acquisition_id=acquisition["acquisition_id"],
        actor_ref="operator-console",
        reason="provider console shows no Pod and no charge for the owned name",
        evidence_sha256="d" * 64,
    )
    first = [a for a in resolved["acquisitions"] if a["generation"] == 1][0]
    assert first["state"] == "NO_CREATE_PROVEN"
    # §4.2: resolve no longer shortcuts NEEDS_RECONCILIATION -> running; the
    # sweep finalizes the resolution's cleanup debt (R1) and reconcile is the
    # only writer back to a running state.
    assert resolved["execution_state"] == "NEEDS_RECONCILIATION"
    service.sweep(plan.experiment_id, world=adapter)
    reconciled = service.reconcile(plan.experiment_id, world=adapter)
    assert reconciled["execution_state"] == "SCREEN_RUNNING"
    with world.db.transaction(readonly=True) as tx:
        resolutions = tx.fetchall("SELECT * FROM runpod_podless_create_resolutions")
        assert len(resolutions) == 1
        assert resolutions[0]["actor_ref"] == "operator-console"
    # A restarted coordinator admits a NEW acquisition generation and finishes.
    fresh = BenchmarkService(world.db, world.settings, clock=comfy.clock, ids=world.ids)
    for _ in range(8):
        state = fresh._advance(plan.experiment_id, adapter, "screen", _screen_quote(world))
        if state["execution_state"] == "SCREEN_REVIEW":
            break
        comfy.clock.advance(seconds=1)
    assert state["execution_state"] == "SCREEN_REVIEW"
    generations = {a["generation"]: a["state"] for a in state["acquisitions"]}
    assert generations[1] == "NO_CREATE_PROVEN"
    assert len(comfy.server.submissions) == 3


def test_prompt_submit_timeout_is_reconciled_by_client_id_without_resubmit(
    world: RenderWorld, tmp_path
) -> None:
    """H-2: a prompt POST that times out after acceptance leaves the sample's
    operation UNKNOWN with the dispatch slot occupied; the sweep keeps the
    acquisition UNKNOWN only while podless, and reconcile adopts the prompt by
    deterministic client id - the sample completes from history, the slot frees,
    and a restarted coordinator resumes without a second POST."""
    from microdrama.contracts.errors import NeedsReconciliation
    from microdrama.testing.fakes.comfy import FakeComfyClient

    class TimeoutOnceClient(FakeComfyClient):
        """The server accepts the first prompt; its response is lost to a timeout."""

        def __init__(self, state) -> None:
            super().__init__(state)
            self.timed_out = False

        def queue_prompt(self, graph, *, client_id):
            prompt_id = super().queue_prompt(graph, client_id=client_id)
            if not self.timed_out:
                self.timed_out = True
                raise NeedsReconciliation("synthetic submit timeout after acceptance")
            return prompt_id

    ep, plan, service, budget, comfy, adapter = _composed_world(world, tmp_path)
    comfy.service._client = TimeoutOnceClient(comfy.server)
    state = service._advance(plan.experiment_id, adapter, "screen", _screen_quote(world))
    assert state["execution_state"] == "NEEDS_RECONCILIATION"
    with world.db.transaction(readonly=True) as tx:
        slot = tx.fetchone(
            "SELECT sample_id FROM benchmark_dispatch_slots WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
        operation = tx.fetchone(
            "SELECT o.state FROM benchmark_samples s JOIN provider_operations o "
            "ON o.reservation_id=s.reservation_id WHERE s.experiment_id=%s AND s.sample_id=%s",
            (plan.experiment_id, slot["sample_id"]),
        )
    assert slot["sample_id"] is not None  # the slot is held while UNKNOWN
    assert operation["state"] == "UNKNOWN"
    # Reconcile adopts the prompt id by deterministic client id and completes it.
    comfy.clock.advance(seconds=1)
    resumed = service.reconcile(plan.experiment_id, world=adapter)
    assert resumed["execution_state"] == "SCREEN_RUNNING"
    assert {s["sample_id"]: s["state"] for s in resumed["samples"]}[slot["sample_id"]] == (
        "SUCCEEDED"
    )
    # A restarted coordinator finishes the screen with no second submission.
    fresh = BenchmarkService(world.db, world.settings, clock=comfy.clock, ids=world.ids)
    for _ in range(8):
        state = fresh._advance(plan.experiment_id, adapter, "screen", _screen_quote(world))
        if state["execution_state"] == "SCREEN_REVIEW":
            break
        comfy.clock.advance(seconds=1)
    assert state["execution_state"] == "SCREEN_REVIEW"
    assert len(comfy.server.submissions) == 3  # exactly one POST per screen sample


def test_operator_resolves_an_unfindable_prompt_and_frees_the_slot(
    world: RenderWorld, tmp_path
) -> None:
    """H-2: a prompt the reconciler cannot find stays UNKNOWN - never resubmitted -
    until the audited operator resolution records its terminal outcome and frees
    the dispatch slot."""
    from microdrama.contracts.errors import NeedsReconciliation
    from microdrama.testing.fakes.comfy import FakeComfyClient

    class TimeoutOnceClient(FakeComfyClient):
        def __init__(self, state) -> None:
            super().__init__(state)
            self.timed_out = False

        def queue_prompt(self, graph, *, client_id):
            prompt_id = super().queue_prompt(graph, client_id=client_id)
            if not self.timed_out:
                self.timed_out = True
                # The server never actually queued it: evict so no scan can find it.
                self.state.prompts.pop(prompt_id)
                self.state.submissions.pop()
                raise NeedsReconciliation("synthetic submit timeout, never accepted")
            return prompt_id

    ep, plan, service, budget, comfy, adapter = _composed_world(world, tmp_path)
    comfy.service._client = TimeoutOnceClient(comfy.server)
    state = service._advance(plan.experiment_id, adapter, "screen", _screen_quote(world))
    assert state["execution_state"] == "NEEDS_RECONCILIATION"
    still = service.reconcile(plan.experiment_id, world=adapter)
    assert still["execution_state"] == "NEEDS_RECONCILIATION"
    with world.db.transaction(readonly=True) as tx:
        slot = tx.fetchone(
            "SELECT sample_id FROM benchmark_dispatch_slots WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
    assert slot["sample_id"] is not None
    resolved = service.resolve_sample(
        plan.experiment_id,
        sample_id=slot["sample_id"],
        actor_ref="operator-console",
        reason="provider console shows no prompt and no charge for this attempt",
        evidence_sha256="e" * 64,
        # P5/§7.3 (R7): the live pod's history never shows the prompt -
        # reachable-but-unrecoverable, so the resolution carries the recorded
        # force override.
        force_unrecoverable=True,
        world=adapter,
    )
    sample = {s["sample_id"]: s["state"] for s in resolved["samples"]}[slot["sample_id"]]
    assert sample == "FAILED"
    with world.db.transaction(readonly=True) as tx:
        freed = tx.fetchone(
            "SELECT sample_id FROM benchmark_dispatch_slots WHERE experiment_id=%s",
            (plan.experiment_id,),
        )
    assert freed["sample_id"] is None  # the slot no longer held forever
    # §7.4 fail-fast: the operator-observed sample failure sets the outcome
    # once; reconcile completes financial finalization and cleanup, and no new
    # generation starts (the experiment stays FAILED, never re-running).
    resumed = service.reconcile(plan.experiment_id, world=adapter)
    assert resumed["execution_outcome"] == "FAILED"
    assert resumed["execution_state"] == "FAILED"
