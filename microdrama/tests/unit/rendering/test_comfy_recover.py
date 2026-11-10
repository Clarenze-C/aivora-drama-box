"""Recovery: progress is not completion; reconnects never re-render; charges are kept."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from comfy_support import GPU_SECOND_MICRO, ComfyWorld, checksum

from microdrama.contracts.enums import AssetKind, Provenance, ProviderOperationState
from microdrama.contracts.errors import NeedsReconciliation, SchemaInvalid
from microdrama.persistence import Database
from microdrama.rendering.comfy_jobs import (
    RENDER_OPERATION_KIND,
    ComfyRenderConfig,
    render_client_id,
    render_client_token,
)
from microdrama.rendering.workflows import bind_workflow
from microdrama.testing.fakes.comfy import EXECUTION_MS, ComfyScenario

pytestmark = [pytest.mark.db, pytest.mark.ffmpeg]

EXECUTION_MICRO = GPU_SECOND_MICRO * (EXECUTION_MS // 1000)  # 3 GPU-seconds = 750 micro-USD


@pytest.fixture
def world(db: Database, tmp_path: Path) -> ComfyWorld:
    return ComfyWorld(db, tmp_path / "store")


@pytest.fixture
def submitted(world: ComfyWorld):
    ep = world.episode()
    attempt = world.attempt(ep)
    status = world.service.submit(attempt.request, job_id=attempt.job_id)
    return world, ep, attempt, status


def _poll(world: ComfyWorld, status) -> object:
    return world.service.poll(status.operation_id)


# --- happy path --------------------------------------------------------------------------


def test_happy_path_completes_with_a_verified_durable_asset(submitted) -> None:
    world, ep, attempt, status = submitted
    mid = _poll(world, status)
    assert mid.state is ProviderOperationState.RUNNING  # progress observed, not completion
    assert mid.assets == ()
    world.clock.advance(ms=EXECUTION_MS)
    done = _poll(world, status)
    assert done.state is ProviderOperationState.SUCCEEDED
    (asset,) = done.assets
    served = world.served_bytes(f"md/ep1/sh1/a1_{status.prompt_id[-4:]}_01.mp4")
    assert asset.asset_kind is AssetKind.VIDEO
    assert asset.sha256 == checksum(served)
    assert asset.media is not None and asset.media.has_video and asset.media.has_audio
    assert asset.provenance is Provenance.FAKE_SYNTHETIC
    assert world.store.verify(asset.object_key, asset.sha256)
    row = world.reservation_row(attempt.request.reservation_id)
    assert row["state"] == "SETTLED"
    assert done.settled_micro_usd == EXECUTION_MICRO
    assert world.counters(ep.account_id) == {
        "reserved": 0,
        "accrued": 0,
        "settled": EXECUTION_MICRO,
        "committed": EXECUTION_MICRO,
    }


# --- progress is not output ----------------------------------------------------------------


def test_executed_events_are_not_complete_saved_output(db: Database, tmp_path: Path) -> None:
    world = ComfyWorld(db, tmp_path / "store", scenarios=(ComfyScenario.EXECUTED_WITHOUT_OUTPUT,))
    ep = world.episode()
    attempt = world.attempt(ep)
    status = world.service.submit(attempt.request, job_id=attempt.job_id)
    world.clock.advance(ms=EXECUTION_MS)
    # The server already emitted full sampler progress, `executed` nodes and
    # execution_success — none of that is a saved output file.
    events = world.client.progress_events(status.prompt_id)
    assert any(e.event == "progress" and e.value == e.maximum for e in events)
    assert any(e.event == "executed" for e in events)
    assert any(e.event == "execution_success" for e in events)
    done = world.service.poll(status.operation_id)
    assert done.state is ProviderOperationState.FAILED
    assert done.error_code == "NO_COMPLETE_OUTPUT"
    assert done.assets == ()
    # the attempt ran on the GPU: the charge is kept
    assert done.settled_micro_usd == EXECUTION_MICRO
    assert world.reservation_row(attempt.request.reservation_id)["state"] == "SETTLED"


def test_partial_file_fails_verification_and_keeps_its_charge(db: Database, tmp_path: Path) -> None:
    world = ComfyWorld(db, tmp_path / "store", scenarios=(ComfyScenario.PARTIAL_FILE,))
    ep = world.episode()
    attempt = world.attempt(ep)
    status = world.service.submit(attempt.request, job_id=attempt.job_id)
    world.clock.advance(ms=EXECUTION_MS)
    done = world.service.poll(status.operation_id)
    assert done.state is ProviderOperationState.FAILED
    assert done.error_code == "OUTPUT_INCOMPLETE"
    assert done.assets == ()
    assert world.render_asset_rows() == []  # a truncated file is never registered
    assert done.settled_micro_usd == EXECUTION_MICRO
    assert world.reservation_row(attempt.request.reservation_id)["state"] == "SETTLED"


def test_execution_error_surfaces_the_server_message(db: Database, tmp_path: Path) -> None:
    world = ComfyWorld(db, tmp_path / "store", scenarios=(ComfyScenario.EXECUTION_ERROR,))
    ep = world.episode()
    attempt = world.attempt(ep)
    status = world.service.submit(attempt.request, job_id=attempt.job_id)
    world.clock.advance(ms=EXECUTION_MS)
    done = world.service.poll(status.operation_id)
    assert done.state is ProviderOperationState.FAILED
    assert done.error_code == "COMFY_EXECUTION_ERROR"
    (op,) = world.op_rows()
    assert op["last_result"]["error_code"] == "COMFY_EXECUTION_ERROR"
    assert done.settled_micro_usd == EXECUTION_MICRO


# --- reconnect / AT-04 boundaries ------------------------------------------------------------


def test_reconnect_does_not_rerender_an_existing_completed_job(submitted) -> None:
    world, ep, attempt, status = submitted
    world.clock.advance(ms=EXECUTION_MS)
    reconnected = world.reconnect()  # fresh connection, same server memory
    done = reconnected.poll(status.operation_id)
    assert done.state is ProviderOperationState.SUCCEEDED
    assert len(done.assets) == 1
    assert world.server.submissions == [status.prompt_id]  # exactly one render, ever
    # and a worker retry of submit() on the reconnected service still never re-queues
    replay = reconnected.submit(attempt.request, job_id=attempt.job_id)
    assert replay.state is ProviderOperationState.SUCCEEDED
    assert replay.replayed
    assert replay.assets == done.assets
    assert world.server.submissions == [status.prompt_id]
    assert len(world.op_rows()) == 1
    charges = world.charges(attempt.request.reservation_id)
    assert len([c for c in charges if c["kind"] == "SETTLEMENT"]) == 1


def test_crash_between_queue_and_persist_is_never_blindly_resubmitted(
    submitted,
) -> None:
    world, ep, attempt, status = submitted
    # Simulate the submit-boundary crash: the server accepted a prompt whose id was
    # never persisted, by dispatching out-of-band without recording SUBMITTED.
    from microdrama.core.provider_ops import begin
    from microdrama.rendering.workflows import MOCK_VIDEO_TEMPLATE

    key = "render.shot:ep1:sh2:attempt1"
    reservation = world.service.reserve_attempt(episode_id=ep.episode_id, semantic_key=key)
    attempt2 = world.attempt(ep, key=key)
    assert attempt2.request.reservation_id == reservation.id
    bound = bind_workflow(MOCK_VIDEO_TEMPLATE, attempt2.request)
    with world.db.transaction() as tx:
        operation = begin(
            tx,
            provider=world.client.provider_id,
            operation_kind=RENDER_OPERATION_KIND,
            client_token=render_client_token(key),
            request_hash=bound.request_hash,
            deadline_at=world.clock.now() + timedelta(milliseconds=600_000),
            job_id=attempt2.job_id,
            now=world.clock.now(),
            reservation_id=reservation.id,
            episode_id=ep.episode_id,
        )
    lost_prompt = world.client.queue_prompt(
        bound.graph, client_id=render_client_id(key)
    )  # crash: prompt id never persisted
    world.clock.advance(ms=700_000)  # past the attempt deadline
    with pytest.raises(NeedsReconciliation):
        world.service.poll(operation.operation_id)
    (op,) = [row for row in world.op_rows() if row["id"] == operation.operation_id]
    assert op["state"] == "UNKNOWN"
    # resubmission of the same attempt is refused; the orphan prompt is not re-run
    with pytest.raises(NeedsReconciliation):
        world.service.submit(attempt2.request, job_id=attempt2.job_id)
    assert world.server.submissions == [status.prompt_id, lost_prompt]
    assert (
        len([row for row in world.op_rows() if row["client_token"] == render_client_token(key)])
        == 1
    )


def test_deadline_while_running_needs_reconciliation_and_holds_exposure(
    db: Database, tmp_path: Path
) -> None:
    world = ComfyWorld(
        db,
        tmp_path / "store",
        config=ComfyRenderConfig(price=ComfyRenderConfig.for_mock().price, timeout_ms=2_000),
        execution_ms=10_000,
    )
    ep = world.episode()
    attempt = world.attempt(ep)
    status = world.service.submit(attempt.request, job_id=attempt.job_id)
    world.clock.advance(ms=2_500)  # past the 2s deadline, execution needs 10s
    with pytest.raises(NeedsReconciliation):
        world.service.poll(status.operation_id)
    (op,) = world.op_rows()
    assert op["state"] == "UNKNOWN"
    # exposure stays held until a human/operator reconciliation settles it
    assert world.reservation_row(attempt.request.reservation_id)["state"] == "ACTIVE"
    assert world.counters(ep.account_id)["reserved"] == GPU_SECOND_MICRO * 2


def test_settlement_replays_after_a_crash_between_success_and_settle(
    submitted, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, ep, attempt, status = submitted
    world.clock.advance(ms=EXECUTION_MS)

    def exploding_record_usage(receipt):
        raise RuntimeError("simulated crash after SUCCEEDED was recorded")

    # First poll completes the attempt durably but dies before settling.
    from microdrama.budget import BudgetService

    crashed_service = type(world.service)(
        world.db,
        BudgetService(world.db, world.clock, world.ids, world.settings),
        world.client,
        world.clock,
        world.ids,
        world.settings,
        world.config,
        world.store,
    )
    monkeypatch.setattr(
        crashed_service._budget,
        "record_usage",
        exploding_record_usage,  # noqa: SLF001
    )
    with pytest.raises(RuntimeError):
        crashed_service.poll(status.operation_id)
    (op,) = world.op_rows()
    assert op["state"] == "SUCCEEDED"  # terminal state survived the crash
    assert world.reservation_row(attempt.request.reservation_id)["state"] == "ACTIVE"

    # Recovery (any later poll, any process) finishes the settlement idempotently.
    done = world.service.poll(status.operation_id)
    assert done.replayed
    assert done.settled_micro_usd == EXECUTION_MICRO
    assert world.reservation_row(attempt.request.reservation_id)["state"] == "SETTLED"
    settlements = [
        c for c in world.charges(attempt.request.reservation_id) if c["kind"] == "SETTLEMENT"
    ]
    assert len(settlements) == 1
    assert settlements[0]["amount_micro_usd"] == EXECUTION_MICRO


# --- HB-1 (Codex P1-P3 review): EXPIRED settlements -------------------------------------


def test_hb1_an_expired_non_lease_covered_render_settles_at_its_measured_cost(
    db: Database, tmp_path: Path
) -> None:
    """HB-1: a render that finishes after its hold expired settles through the
    SAME canonical calculation as an ACTIVE one - the measured seconds at the
    configured price. No pod lease carries this cost, so a zero settlement
    silently forgives it (the review's probe settled a 60 GPU-second
    non-lease-covered attempt at amount 0 and units 0).
    """
    world = ComfyWorld(db, tmp_path / "store")  # non-lease-covered, mock price
    ep = world.episode()
    attempt = world.attempt(ep)
    status = world.service.submit(attempt.request, job_id=attempt.job_id)

    # The hold expires while the prompt runs; expire_stale keeps its exposure.
    world.clock.advance(seconds=601)
    assert world.budget.expire_stale() == 1
    assert world.reservation_row(attempt.request.reservation_id)["state"] == "EXPIRED"

    world.clock.advance(ms=EXECUTION_MS)
    done = _poll(world, status)
    assert done.state is ProviderOperationState.SUCCEEDED

    row = world.reservation_row(attempt.request.reservation_id)
    assert row["state"] == "SETTLED"
    assert row["closed_reason"] == "settled after expiry"
    # submitted at T0, terminal at T0+601 s+3 s: 604 billed GPU-seconds at the
    # mock 250 micro-USD price - the canonical calculation, not a write-off.
    assert row["settled_micro_usd"] == 604 * GPU_SECOND_MICRO
    assert done.settled_micro_usd == 604 * GPU_SECOND_MICRO
    (settlement,) = [
        c for c in world.charges(attempt.request.reservation_id) if c["kind"] == "SETTLEMENT"
    ]
    assert settlement["units"] == 604
    assert settlement["amount_micro_usd"] == 604 * GPU_SECOND_MICRO
    assert world.counters(ep.account_id)["settled"] == 604 * GPU_SECOND_MICRO


def test_asset_save_boundary_recovery_registers_exactly_one_asset(submitted) -> None:
    world, ep, attempt, status = submitted
    world.clock.advance(ms=EXECUTION_MS)
    first = world.service.poll(status.operation_id)
    again = world.service.poll(status.operation_id)  # crash-and-retry of the whole step
    assert again.replayed
    assert again.assets == first.assets
    assert len(world.render_asset_rows()) == 1
    (asset_row,) = world.render_asset_rows()
    assert asset_row["verified_at"] is not None
    # one settlement only, even after three polls
    assert again.settled_micro_usd == EXECUTION_MICRO
    assert len([c for c in world.charges(attempt.request.reservation_id)]) == 1


def test_terminal_status_replay_does_not_touch_the_server(submitted) -> None:
    world, ep, attempt, status = submitted
    world.clock.advance(ms=EXECUTION_MS)
    world.service.poll(status.operation_id)
    calls_before = len(world.client.calls)
    replay = world.service.poll(status.operation_id)
    assert replay.replayed
    assert len(world.client.calls) == calls_before


# --- T045-FIX F-4: production lease-covered FAILED attempts settle their own hold ----


def test_a_failed_lease_covered_production_attempt_settles_its_own_hold(
    db: Database, tmp_path: Path
) -> None:
    """T045-FIX F-4: production routing gives every attempt its own hold, so a FAILED
    lease-covered attempt settles it at once - at zero charge (B-B1) - and the hold is
    never left ACTIVE. Only the canary defers a FAILED settlement for a retry
    (retry_reuses_hold) and it settles the hold at prompt end; that deferral must not
    leak into production."""
    from datetime import UTC as _UTC
    from datetime import datetime

    from microdrama.config import Settings
    from microdrama.contracts.cost import PriceQuote
    from microdrama.contracts.enums import ExecutionMode, PriceSource, PriceUnit

    world = ComfyWorld(
        db,
        tmp_path / "store",
        scenarios=(ComfyScenario.EXECUTED_WITHOUT_OUTPUT,),
        # The lease-covered settle path is a live-path concept (B-B1): it posts a
        # BILLED receipt, which offline-mock provenance forbids, and the synthetic
        # mock price is offline-only. The transports stay fakes; only the settings
        # mark the world non-mock and the price is a real provider quote, as in the
        # canary (_gpu_second_price).
        settings=Settings(
            execution_mode=ExecutionMode.PAID_BENCHMARK,
            paid_requests_enabled=True,
            cloud_resources_enabled=True,
        ),
        config=ComfyRenderConfig(
            price=PriceQuote(
                currency="USD",
                unit=PriceUnit.GPU_SECOND,
                unit_price_micro_usd=250,
                source=PriceSource.PROVIDER_QUOTE,
                price_table_version="f4-prod-quote",
                as_of=datetime(2026, 11, 3, tzinfo=_UTC),
            ),
            lease_covered=True,
        ),
    )
    ep = world.episode()
    attempt = world.attempt(ep)
    status = world.service.submit(attempt.request, job_id=attempt.job_id)
    world.clock.advance(ms=EXECUTION_MS)
    done = world.service.poll(status.operation_id)
    assert done.state is ProviderOperationState.FAILED
    assert done.settled_micro_usd == 0  # lease-covered: zero charge (B-B1)
    reservation = world.reservation_row(attempt.request.reservation_id)
    assert reservation["state"] == "SETTLED"  # F-4: production settles FAILED at once
    assert world.counters(ep.account_id)["reserved"] == 0  # nothing stays reserved


def _unknown_submit_without_prompt_id(world: ComfyWorld, ep, key: str):
    """H-2 fixture: the POST timed out after the server accepted the prompt, so
    the operation is UNKNOWN with no durable prompt id (the deterministic client
    id is the only recovery handle)."""
    from microdrama.core.provider_ops import begin
    from microdrama.rendering.workflows import MOCK_VIDEO_TEMPLATE

    reservation = world.service.reserve_attempt(episode_id=ep.episode_id, semantic_key=key)
    attempt = world.attempt(ep, key=key, reservation_id=reservation.id)
    bound = bind_workflow(MOCK_VIDEO_TEMPLATE, attempt.request)
    with world.db.transaction() as tx:
        operation = begin(
            tx,
            provider=world.client.provider_id,
            operation_kind=RENDER_OPERATION_KIND,
            client_token=render_client_token(key),
            request_hash=bound.request_hash,
            deadline_at=world.clock.now() + timedelta(milliseconds=600_000),
            job_id=attempt.job_id,
            now=world.clock.now(),
            reservation_id=reservation.id,
            episode_id=ep.episode_id,
        )
    # The server accepted the prompt (registered under the deterministic client
    # id); the response was lost to the timeout. The id is never persisted.
    world.client.queue_prompt(bound.graph, client_id=render_client_id(key))
    world.clock.advance(ms=700_000)  # past the attempt deadline
    with pytest.raises(NeedsReconciliation):
        world.service.poll(operation.operation_id)
    (op,) = [row for row in world.op_rows() if row["id"] == operation.operation_id]
    assert op["state"] == "UNKNOWN" and op["external_id"] is None
    return attempt, operation, reservation


def test_reconcile_unknown_adopts_the_prompt_by_deterministic_client_id(
    db: Database, tmp_path: Path
) -> None:
    """H-2 (2026-11-10, GLM harness review): a prompt POST that timed out may
    still have been accepted server-side. The reconciler scans queue/history by
    the DETERMINISTIC client id, adopts the durable prompt id, and recovers the
    outcome through the guarded poll - it NEVER resubmits."""
    world = ComfyWorld(db, tmp_path / "store")
    ep = world.episode()
    key = "render.shot:ep1:sh10:attempt1"
    attempt, operation, reservation = _unknown_submit_without_prompt_id(world, ep, key)
    assert len(world.server.submissions) == 1
    # Reconciliation adopts the prompt id and completes from history.
    world.clock.advance(ms=EXECUTION_MS)
    status = world.service.reconcile_unknown(operation.operation_id)
    assert status.state is ProviderOperationState.SUCCEEDED
    (op,) = [row for row in world.op_rows() if row["id"] == operation.operation_id]
    assert op["state"] == "SUCCEEDED" and op["external_id"] is not None
    # No second POST ever left the client - exactly one submission.
    assert len(world.server.submissions) == 1


def test_reconcile_unknown_stays_ambiguous_when_nothing_is_visible(
    db: Database, tmp_path: Path
) -> None:
    """H-2: absence on the queue AND in history is not proof the prompt never
    ran - the operation stays UNKNOWN + NeedsReconciliation for the operator."""
    world = ComfyWorld(db, tmp_path / "store")
    ep = world.episode()
    key = "render.shot:ep1:sh11:attempt1"
    attempt, operation, reservation = _unknown_submit_without_prompt_id(world, ep, key)
    # The server never actually received it (nothing registered): evict the prompt.
    lost = world.server.submissions.pop()
    world.server.prompts.pop(lost)
    with pytest.raises(NeedsReconciliation):
        world.service.reconcile_unknown(operation.operation_id)
    (op,) = [row for row in world.op_rows() if row["id"] == operation.operation_id]
    assert op["state"] == "UNKNOWN"


def test_poll_unknown_with_durable_prompt_id_recovers_from_history(
    db: Database, tmp_path: Path
) -> None:
    """H-2: an UNKNOWN row that already carries its prompt id re-polls through
    the guarded history path instead of raising forever - the prompt completed
    server-side while the outcome was marked unknown."""
    world = ComfyWorld(
        db,
        tmp_path / "store",
        config=ComfyRenderConfig(price=ComfyRenderConfig.for_mock().price, timeout_ms=2_000),
        execution_ms=10_000,
    )
    ep = world.episode()
    attempt = world.attempt(ep)
    status = world.service.submit(attempt.request, job_id=attempt.job_id)
    world.clock.advance(ms=2_500)  # past the deadline while still executing
    with pytest.raises(NeedsReconciliation):
        world.service.poll(status.operation_id)
    (op,) = world.op_rows()
    assert op["state"] == "UNKNOWN" and op["external_id"] == status.prompt_id
    world.clock.advance(ms=10_000)  # the prompt completes server-side
    done = world.service.poll(status.operation_id)
    assert done.state is ProviderOperationState.SUCCEEDED
    assert len(world.server.submissions) == 1


def test_operator_resolution_records_terminal_failure_and_settles(
    db: Database, tmp_path: Path
) -> None:
    """H-2: the audited operator resolution (actor, reason, sha256 evidence)
    records the terminal FAILED outcome for an unresolvable UNKNOWN prompt,
    settles the attempt like a provider-reported failure, and appends the
    resolution evidence event."""
    from microdrama.contracts.errors import Conflict

    world = ComfyWorld(db, tmp_path / "store")
    ep = world.episode()
    key = "render.shot:ep1:sh12:attempt1"
    attempt, operation, reservation = _unknown_submit_without_prompt_id(world, ep, key)
    lost = world.server.submissions.pop()
    world.server.prompts.pop(lost)
    with pytest.raises(NeedsReconciliation):
        world.service.reconcile_unknown(operation.operation_id)
    done = world.service.resolve_unknown_operation(
        operation.operation_id,
        actor_ref="operator-console",
        reason="provider console shows no prompt and no charge for this attempt",
        evidence_sha256="a" * 64,
    )
    assert done.state is ProviderOperationState.FAILED
    with world.db.transaction(readonly=True) as tx:
        events = tx.fetchall(
            "SELECT payload FROM domain_events WHERE event_type="
            "'provider_operation.operator_resolved'"
        )
    assert len(events) == 1
    assert events[0]["payload"]["actor_ref"] == "operator-console"
    # A second resolution of the same operation is refused.
    with pytest.raises(Conflict):
        world.service.resolve_unknown_operation(
            operation.operation_id,
            actor_ref="operator-console",
            reason="again",
            evidence_sha256="b" * 64,
        )
    # Malformed attestations are refused without any durable write.
    with pytest.raises(SchemaInvalid):
        world.service.resolve_unknown_operation(
            operation.operation_id,
            actor_ref="",
            reason="x",
            evidence_sha256="c" * 64,
        )
