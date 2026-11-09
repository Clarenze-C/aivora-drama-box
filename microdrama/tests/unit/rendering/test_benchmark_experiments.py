"""T031 durability/money regressions against isolated actual PostgreSQL."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from rendering_support import RenderWorld

from microdrama.contracts.cost import BudgetReservationRequest, ExposureCeilings
from microdrama.contracts.enums import BudgetCategory, BudgetScopeKind, QueueName
from microdrama.contracts.errors import BudgetExhausted, Conflict, EffectDenied
from microdrama.pipeline.benchmark_authorization import BenchmarkPlan
from microdrama.pipeline.benchmark_service import BenchmarkService
from microdrama.rendering.benchmark_experiments import ExperimentBudgetService
from microdrama.rendering.leases import PodLeaseClaimRequest, mock_pod_price

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


def prepare(world, **changes):
    ep = world.episode()
    plan = plan_for(ep.episode_id, **changes)
    service = BenchmarkService(world.db, world.settings, clock=world.clock, ids=world.ids)
    row = service.prepare(plan)
    # Budget tests bind only the immutable hard stop; seal/binder tests separately
    # validate actual sealed references. No executable readiness is fabricated.
    with world.db.transaction() as tx:
        tx.execute(
            "UPDATE benchmark_experiments SET hard_stop=%s WHERE experiment_id=%s",
            (world.clock.now() + timedelta(hours=4), plan.experiment_id),
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
        result = self.leases.shutdown(
            acquisition["lease_id"], reason="offline benchmark phase boundary"
        )
        assert result.compute_stopped
        with self.db.transaction(readonly=True) as tx:
            row = tx.fetchone("SELECT * FROM pod_leases WHERE id=%s", (acquisition["lease_id"],))
        assert row["stop_verified_at"] is not None
        return {
            "verified": True,
            "compute_window_end": row["compute_window_end_at"],
            "billing_state": "BILLED",
            "storage_final": True,
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
