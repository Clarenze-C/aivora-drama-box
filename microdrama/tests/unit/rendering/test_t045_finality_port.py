"""T045 R8 (G7/G15): the required finality port, the pending result, the widened sweep.

Red-first: settle_reservation_for_lease released a Runpod hold whenever the recorded
total was 0 — but Runpod usage() returns [] (unknown, not zero), so a live lease freed
its hold while real cost was still outstanding.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from rendering_support import T0, RenderWorld

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode
from microdrama.contracts.errors import Conflict
from microdrama.persistence import Database
from microdrama.rendering import (
    PodManager,
    RunpodInvoiceFinality,
    SyntheticUsageFinality,
    build_janitor,
)
from microdrama.rendering.finality import FINALITY_BACKOFF_BASE
from microdrama.testing.fakes import FakeClock, SequentialIds
from microdrama.testing.seed import seed_episode, seed_season

pytestmark = pytest.mark.db


def _runpod_lease(db: Database, *, reservation_state: str = "ACTIVE"):
    """A runpod lease with real timing and an unsettled hold; no buckets, no invoice."""
    with db.transaction() as tx:
        season = seed_season(tx)
        episode = seed_episode(tx, season)
        account = uuid.uuid4()
        tx.execute(
            "INSERT INTO budget_accounts (id, scope_kind, season_id, episode_id, "
            "cap_micro_usd, reserved_outstanding_micro_usd) "
            "VALUES (%s, 'EPISODE', %s, %s, 10000000, 900000)",
            (account, season, episode),
        )
        for category in (
            "RESEARCH_SCRIPT_PROMPTS_METADATA",
            "REFERENCES_DIALOGUE",
            "QA_CAPTIONS",
            "CPU_STORAGE_TRANSFER",
            "RECOVERY_HEADROOM",
            "METERED_MANAGEMENT",
        ):
            tx.execute(
                "INSERT INTO budget_category_allocations (account_id, category, "
                "allocated_micro_usd, protected) VALUES (%s, %s, 0, %s)",
                (account, category, "false" if category == "METERED_MANAGEMENT" else "true"),
            )
        tx.execute(
            "INSERT INTO budget_category_allocations (account_id, category, "
            "allocated_micro_usd, reserved_outstanding_micro_usd, protected) "
            "VALUES (%s, 'GPU_GENERATION', 900000, 900000, true)",
            (account,),
        )
        reservation = uuid.uuid4()
        tx.execute(
            "INSERT INTO reservations (id, account_id, request_id, semantic_key, "
            "request_hash, category, queue, provider, operation_kind, price, ceilings, "
            "reserved_micro_usd, state, expires_at, closed_at, closed_reason) "
            "VALUES (%s, %s, %s, %s, %s, "
            "'GPU_GENERATION', 'production', 'runpod', 'pod.lease', '{}', '{}', 900000, "
            "%s, %s, %s, %s)",
            (
                reservation,
                account,
                uuid.uuid4(),
                f"t045port:{reservation}",
                "0" * 64,
                reservation_state,
                T0 + timedelta(hours=6),
                None if reservation_state == "ACTIVE" else T0 + timedelta(minutes=30),
                None
                if reservation_state == "ACTIVE"
                else "expired: past expires_at without settlement",
            ),
        )
        lease = uuid.uuid4()
        end = T0 + timedelta(minutes=30)
        tx.execute(
            "INSERT INTO pod_leases (id, provider, pod_id, owned_tag, client_token, "
            "owner_episode_id, reservation_id, lease_state, pod_state, gpu_type, "
            "hourly_price_micro_usd, lease_expires_at, create_requested_at, "
            "compute_window_start_at, compute_window_end_at, stop_verified_at) "
            "VALUES (%s, 'runpod', 'pod-port', 'microdrama-owned:t045', %s, %s, %s, "
            "'RELEASED', 'STOPPED', 'NVIDIA RTX A40', 263000, %s, %s, %s, %s, %s)",
            (
                lease,
                f"tok-{lease}",
                episode,
                reservation,
                T0 + timedelta(hours=6),
                T0,
                T0,
                end,
                end,
            ),
        )
    return lease, reservation


def _budget(db: Database, *, offline: bool = False) -> BudgetService:
    settings = (
        Settings(execution_mode=ExecutionMode.OFFLINE_MOCK)
        if offline
        else Settings(
            execution_mode=ExecutionMode.PAID_BENCHMARK,
            paid_requests_enabled=True,
            cloud_resources_enabled=True,
        )
    )
    return BudgetService(db, FakeClock(T0), SequentialIds("t045-port"), settings)


def test_runpod_usage_unknown_keeps_the_hold_through_the_finality_port(
    db: Database,
) -> None:
    """Runpod usage() returns [] (unknown): settle runs and the hold is not released."""
    lease, reservation = _runpod_lease(db)
    budget = _budget(db)
    finality = RunpodInvoiceFinality(db, budget_service=budget)
    outcome = finality.settle_lease(
        db, budget, budget._settings, lease_id=lease, context="t045 port"
    )
    assert outcome.pending is True
    assert outcome.settled_micro_usd == 0
    with db.transaction(readonly=True) as tx:
        state = tx.fetchval("SELECT state FROM reservations WHERE id=%s", (reservation,))
        backoff = tx.fetchval("SELECT next_finality_check_at FROM pod_leases WHERE id=%s", (lease,))
    assert state == "ACTIVE"  # the hold stays until BILLED
    assert backoff is not None


def test_constructor_pairing_check_refuses_a_mismatched_finality(db: Database) -> None:
    from microdrama.rendering import build_lease_service

    provider = RenderWorld(db).provider  # fake-runpod
    offline = Settings(execution_mode=ExecutionMode.OFFLINE_MOCK)
    budget = _budget(db, offline=True)
    with pytest.raises(Conflict, match="does not match"):
        build_lease_service(
            db,
            budget,
            PodManager(provider, FakeClock(T0), RenderWorld(db).config),
            FakeClock(T0),
            SequentialIds("pair"),
            offline,
            RenderWorld(db).config,
            SyntheticUsageFinality(offline, provider_id="runpod"),
        )


def test_synthetic_finality_refuses_construction_outside_offline_mock() -> None:
    paid = Settings(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
    )
    with pytest.raises(Conflict, match="OFFLINE_MOCK"):
        SyntheticUsageFinality(paid, provider_id="fake-runpod")


def test_shutdown_of_an_ambiguous_runpod_create_reports_billing_pending(
    db: Database,
) -> None:
    from test_t045_timing import RunpodIdFakePods

    from microdrama.testing.fakes import PodCreateScenario

    provider = RunpodIdFakePods(clock=FakeClock(T0), ids=SequentialIds("t045-port-amb"))
    world = RenderWorld(db, provider=provider)
    # The offline world pairs synthetic finality with the runpod-id fake only for the
    # lifecycle; rebuild the lease service with the invoice finality for the gate.
    world.finality = RunpodInvoiceFinality(db, budget_service=world.budget)
    from microdrama.rendering import build_lease_service

    world.leases = build_lease_service(
        world.db,
        world.budget,
        world.manager,
        world.clock,
        world.ids,
        world.settings,
        world.config,
        world.finality,
    )
    episode = world.episode()
    handle = world.claim(episode, "t045-ambiguous")
    world.provider.queue_scenarios(PodCreateScenario.CREATE_TIMEOUT_NOT_CREATED)
    from microdrama.contracts.errors import NeedsReconciliation

    with pytest.raises(NeedsReconciliation):
        world.leases.ensure_pod(handle.lease.lease_id)
    result = world.leases.shutdown(handle.lease.lease_id, reason="ambiguous create")
    assert result.billing_pending is True
    assert _reservation_state(db, handle) == "ACTIVE"


def test_sweep_retries_an_expired_pending_hold_without_error_or_hot_loop(
    db: Database,
) -> None:
    lease, reservation = _runpod_lease(db, reservation_state="EXPIRED")
    budget = _budget(db)
    from test_t045_timing import RunpodIdFakePods

    provider = RunpodIdFakePods(clock=FakeClock(T0), ids=SequentialIds("t045-sweep"))
    config = RenderWorld(db).config
    janitor = build_janitor(
        db,
        budget,
        provider,
        FakeClock(T0 + timedelta(hours=8)),
        SequentialIds("t045-sweep"),
        budget._settings,
        config,
        RunpodInvoiceFinality(db, budget_service=budget),
    )
    first = janitor.sweep()
    assert first.failures == []
    pending = [a for a in first.budget_holds if a.action == "settle_terminal"]
    assert len(pending) == 1
    assert pending[0].outcome == "PENDING"
    with db.transaction(readonly=True) as tx:
        backoff = tx.fetchval("SELECT next_finality_check_at FROM pod_leases WHERE id=%s", (lease,))
    assert backoff == T0 + timedelta(hours=8) + FINALITY_BACKOFF_BASE
    # A sweep before the backoff elapses does not retry (no hot loop, no error).
    early = build_janitor(
        db,
        budget,
        provider,
        FakeClock(T0 + timedelta(hours=8, minutes=1)),
        SequentialIds("t045-sweep"),
        budget._settings,
        config,
        RunpodInvoiceFinality(db, budget_service=budget),
    )
    second = early.sweep()
    assert second.failures == []
    assert [a for a in second.budget_holds if a.action == "settle_terminal"] == []
    with db.transaction(readonly=True) as tx:
        assert (
            tx.fetchval("SELECT state FROM reservations WHERE id=%s", (reservation,)) == "EXPIRED"
        )


def _reservation_state(db: Database, handle) -> str:
    with db.transaction(readonly=True) as tx:
        return tx.fetchval(
            "SELECT r.state FROM reservations r JOIN pod_leases l "
            "ON l.reservation_id = r.id WHERE l.id=%s",
            (handle.lease.lease_id,),
        )


# --- T045-FIX: A-S2 doubling backoff, A-N8 honest release report, A-N9 settle pairing ----


def _paid_settings() -> Settings:
    return Settings(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
    )


def _backoff_row(db: Database, lease):
    with db.transaction(readonly=True) as tx:
        return tx.fetchone(
            "SELECT next_finality_check_at, finality_attempts FROM pod_leases WHERE id=%s",
            (lease,),
        )


def test_finality_backoff_doubles_each_pending_sweep_and_caps_at_one_hour(
    db: Database,
) -> None:
    """T045-FIX A-S2: consecutive sweeps past each expiry double the delay (5, 10,
    20, 40 min...) up to the one-hour cap."""
    from microdrama.rendering.finality import FINALITY_BACKOFF_CAP

    lease, _reservation = _runpod_lease(db)
    budget = _budget(db)
    finality = RunpodInvoiceFinality(db, budget_service=budget)
    settings = _paid_settings()
    now = T0
    expected_minutes = [5, 10, 20, 40]
    for minutes in expected_minutes:
        outcome = finality.settle_lease(
            db, budget, settings, lease_id=lease, context="sweep", now=now
        )
        assert outcome.pending is True
        row = _backoff_row(db, lease)
        assert row["next_finality_check_at"] == now + timedelta(minutes=minutes)
        now = row["next_finality_check_at"]  # the sweep arrives when the backoff expires
    # The next doubling (80 min) is capped at 60.
    finality.settle_lease(db, budget, settings, lease_id=lease, context="sweep", now=now)
    assert _backoff_row(db, lease)["next_finality_check_at"] == now + FINALITY_BACKOFF_CAP


def test_finality_attempt_count_resets_once_billed(db: Database) -> None:
    """T045-FIX A-S2: a BILLED settlement resets the attempt counter."""
    from microdrama.budget.billing import BillingRepository

    with db.transaction() as tx:
        season = seed_season(tx)
        episode = seed_episode(tx, season)
        account = uuid.uuid4()
        tx.execute(
            "INSERT INTO budget_accounts (id, scope_kind, season_id, episode_id, cap_micro_usd, "
            "reserved_outstanding_micro_usd) VALUES (%s, 'EPISODE', %s, %s, 10000000, 100000)",
            (account, season, episode),
        )
        for category in (
            "RESEARCH_SCRIPT_PROMPTS_METADATA",
            "REFERENCES_DIALOGUE",
            "QA_CAPTIONS",
            "CPU_STORAGE_TRANSFER",
            "RECOVERY_HEADROOM",
            "METERED_MANAGEMENT",
        ):
            tx.execute(
                "INSERT INTO budget_category_allocations (account_id, category, "
                "allocated_micro_usd, protected) VALUES (%s, %s, 0, %s)",
                (account, category, "false" if category == "METERED_MANAGEMENT" else "true"),
            )
        tx.execute(
            "INSERT INTO budget_category_allocations (account_id, category, "
            "allocated_micro_usd, reserved_outstanding_micro_usd, protected) "
            "VALUES (%s, 'GPU_GENERATION', 900000, 100000, true)",
            (account,),
        )
        reservation = uuid.uuid4()
        tx.execute(
            "INSERT INTO reservations (id, account_id, request_id, semantic_key, "
            "request_hash, category, queue, provider, operation_kind, price, ceilings, "
            "reserved_micro_usd, state, expires_at) VALUES (%s, %s, %s, %s, %s, "
            "'GPU_GENERATION', 'production', 'runpod', 'pod.lease', '{}', '{}', 100000, "
            "'ACTIVE', %s)",
            (reservation, account, uuid.uuid4(), f"reset:{reservation}", "0" * 64, T0),
        )
        lease = uuid.uuid4()
        tx.execute(
            "INSERT INTO pod_leases (id, provider, pod_id, owned_tag, client_token, "
            "owner_episode_id, reservation_id, lease_state, pod_state, gpu_type, "
            "hourly_price_micro_usd, lease_expires_at, create_requested_at) "
            "VALUES (%s, 'runpod', NULL, 'microdrama-owned:t045', %s, %s, %s, 'RELEASED', "
            "'REQUESTED', 'NVIDIA RTX A40', 263000, %s, %s)",
            (lease, f"tok-{lease}", episode, reservation, T0 + timedelta(hours=6), T0),
        )
    budget = _budget(db)
    settings = _paid_settings()
    finality = RunpodInvoiceFinality(db, budget_service=budget)
    finality.settle_lease(db, budget, settings, lease_id=lease, context="sweep", now=T0)
    finality.settle_lease(
        db, budget, settings, lease_id=lease, context="sweep", now=T0 + timedelta(minutes=5)
    )
    assert _backoff_row(db, lease)["finality_attempts"] == 2
    BillingRepository(db, budget_service=budget).resolve_podless_create(
        lease, actor_ref="owner:test", reason="console shows no pod", evidence_sha256="a" * 64
    )
    outcome = finality.settle_lease(
        db, budget, settings, lease_id=lease, context="post-resolution", now=T0 + timedelta(hours=1)
    )
    assert outcome.settled_micro_usd == 0
    assert _backoff_row(db, lease)["finality_attempts"] == 0


def test_a_refused_release_reports_the_truth_not_released(db: Database) -> None:
    """T045-FIX A-N8: when BudgetService.release refuses, the settlement reports the
    reservation's real state instead of claiming released."""
    with db.transaction() as tx:
        season = seed_season(tx)
        episode = seed_episode(tx, season)
        account = uuid.uuid4()
        tx.execute(
            "INSERT INTO budget_accounts (id, scope_kind, season_id, episode_id, cap_micro_usd) "
            "VALUES (%s, 'EPISODE', %s, %s, 10000000)",
            (account, season, episode),
        )
        reservation = uuid.uuid4()
        tx.execute(
            "INSERT INTO reservations (id, account_id, request_id, semantic_key, "
            "request_hash, category, queue, provider, operation_kind, price, ceilings, "
            "reserved_micro_usd, settled_micro_usd, state, expires_at, closed_at, "
            "closed_reason) VALUES (%s, %s, %s, %s, %s, 'GPU_GENERATION', 'production', "
            "'runpod', 'pod.lease', '{}', '{}', 100000, 40000, 'SETTLED', %s, %s, 'settled')",
            (
                reservation,
                account,
                uuid.uuid4(),
                f"n8:{reservation}",
                "0" * 64,
                T0 + timedelta(hours=6),
                T0 + timedelta(minutes=30),
            ),
        )
        lease = uuid.uuid4()
        tx.execute(
            "INSERT INTO pod_leases (id, provider, pod_id, owned_tag, client_token, "
            "owner_episode_id, reservation_id, lease_state, pod_state, gpu_type, "
            "hourly_price_micro_usd, lease_expires_at) VALUES (%s, 'runpod', NULL, "
            "'microdrama-owned:t045', %s, %s, %s, 'RELEASED', 'REQUESTED', "
            "'NVIDIA RTX A40', 263000, %s)",
            (lease, f"tok-{lease}", episode, reservation, T0 + timedelta(hours=6)),
        )
    budget = _budget(db)
    finality = RunpodInvoiceFinality(db, budget_service=budget)
    outcome = finality.settle_lease(
        db, budget, _paid_settings(), lease_id=lease, context="replay", now=T0
    )
    assert outcome.released is False
    assert outcome.pending is False
    assert outcome.settled_micro_usd == 40000  # the earlier settlement stands


def test_settle_reservation_for_lease_checks_the_provider_pairing(db: Database) -> None:
    """T045-FIX A-N9: the settle helper itself refuses a finality whose provider does
    not match the lease, not only the constructors."""
    from microdrama.rendering.leases import settle_reservation_for_lease

    lease, _reservation = _runpod_lease(db)
    synthetic = SyntheticUsageFinality(
        Settings(execution_mode=ExecutionMode.OFFLINE_MOCK), provider_id="fake"
    )
    with pytest.raises(Conflict, match="finality"):
        settle_reservation_for_lease(
            db,
            _budget(db),
            Settings(execution_mode=ExecutionMode.OFFLINE_MOCK),
            finality=synthetic,
            lease_id=lease,
            context="mismatched pairing",
        )
