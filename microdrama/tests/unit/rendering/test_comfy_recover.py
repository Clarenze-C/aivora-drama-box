"""Recovery: progress is not completion; reconnects never re-render; charges are kept."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from comfy_support import GPU_SECOND_MICRO, ComfyWorld, checksum

from microdrama.contracts.enums import AssetKind, Provenance, ProviderOperationState
from microdrama.contracts.errors import NeedsReconciliation
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
