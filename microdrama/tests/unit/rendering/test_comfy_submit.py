"""Submission: paid before dispatch, prompt id persisted, replays never re-queue."""

from __future__ import annotations

import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from comfy_support import DEFAULT_ATTEMPT_MS, GPU_SECOND_MICRO, ComfyWorld

from microdrama.contracts.cost import BudgetReservationRequest, ExposureCeilings
from microdrama.contracts.enums import (
    BudgetCategory,
    BudgetScopeKind,
    ControlKind,
    ProviderOperationState,
    QueueName,
)
from microdrama.contracts.errors import (
    Conflict,
    IdempotencyConflict,
    NotFound,
    UnknownPrice,
    UnsupportedControl,
)
from microdrama.persistence import Database
from microdrama.rendering.comfy_jobs import (
    RENDER_OPERATION_KIND,
    ComfyRenderConfig,
)
from microdrama.rendering.leases import LEASE_OPERATION_KIND
from microdrama.testing.fakes.comfy import FAKE_NODE_CLASSES

pytestmark = [pytest.mark.db, pytest.mark.ffmpeg]


@pytest.fixture
def world(db: Database, tmp_path: Path) -> ComfyWorld:
    return ComfyWorld(db, tmp_path / "store")


def test_submit_persists_the_prompt_id_and_links_the_attempt(world: ComfyWorld) -> None:
    ep = world.episode()
    attempt = world.attempt(ep)
    status = world.service.submit(attempt.request, job_id=attempt.job_id)
    assert status.state is ProviderOperationState.SUBMITTED
    assert status.prompt_id == "fake-prompt-0001"
    assert world.server.submissions == [status.prompt_id]
    (op,) = world.op_rows()
    assert op["operation_kind"] == RENDER_OPERATION_KIND
    assert op["external_id"] == status.prompt_id
    assert op["job_id"] == attempt.job_id
    assert op["reservation_id"] == attempt.request.reservation_id
    assert op["state"] == "SUBMITTED"
    assert op["request_hash"]  # the bound graph identity is durable


def test_every_attempt_is_paid_before_dispatch(world: ComfyWorld) -> None:
    ep = world.episode()
    attempt = world.attempt(ep)
    reservation = world.reservation_row(attempt.request.reservation_id)
    assert reservation["operation_kind"] == RENDER_OPERATION_KIND
    assert reservation["state"] == "ACTIVE"
    assert reservation["reserved_micro_usd"] == GPU_SECOND_MICRO * (DEFAULT_ATTEMPT_MS // 1000)
    assert world.counters(ep.account_id)["reserved"] == reservation["reserved_micro_usd"]
    world.service.submit(attempt.request, job_id=attempt.job_id)
    # the hold stays outstanding while the prompt runs
    assert world.counters(ep.account_id)["reserved"] == reservation["reserved_micro_usd"]


def test_unknown_price_blocks_every_dispatch(db: Database, tmp_path: Path) -> None:
    world = ComfyWorld(db, tmp_path / "store", config=ComfyRenderConfig(price=None))
    ep = world.episode()
    with pytest.raises(UnknownPrice):
        world.service.reserve_attempt(
            episode_id=ep.episode_id, semantic_key="render.shot:ep1:sh3:attempt1"
        )
    assert world.client.calls == []  # no provider call of any kind


def test_reserve_attempt_is_idempotent_across_a_crash_retry(world: ComfyWorld) -> None:
    ep = world.episode()
    key = "render.shot:ep1:sh3:attempt1"
    first = world.service.reserve_attempt(episode_id=ep.episode_id, semantic_key=key)
    world.clock.advance(seconds=5)  # expiry drift on the retry
    second = world.service.reserve_attempt(episode_id=ep.episode_id, semantic_key=key)
    assert second.id == first.id
    assert second.replayed
    assert world.reservation_row(first.id)["state"] == "ACTIVE"


def test_a_foreign_reservation_cannot_pay_the_attempt(world: ComfyWorld) -> None:
    ep = world.episode()
    price = world.config.price
    assert price is not None
    lease_hold = world.budget.reserve(
        BudgetReservationRequest(
            request_id=uuid.uuid5(uuid.NAMESPACE_URL, "lease-hold"),
            semantic_key="pod.lease:ep1:render-1",
            scope_kind=BudgetScopeKind.EPISODE,
            episode_id=ep.episode_id,
            season_id=None,
            category=BudgetCategory.GPU_GENERATION,
            queue=QueueName.PRODUCTION,
            job_id=None,
            provider=world.client.provider_id,
            operation_kind=LEASE_OPERATION_KIND,
            price=price,
            ceilings=ExposureCeilings(timeout_ms=600_000, max_units=600),
            worst_case_micro_usd=GPU_SECOND_MICRO * 600,
            is_shutdown_or_cleanup=False,
            expires_at=world.clock.now() + timedelta(milliseconds=600_000),
        )
    )
    attempt = world.attempt(ep)
    request = attempt.request.model_copy(update={"reservation_id": lease_hold.id})
    with pytest.raises(Conflict):
        world.service.submit(request, job_id=attempt.job_id)
    assert world.server.submissions == []


def test_missing_reservation_is_a_typed_refusal(world: ComfyWorld) -> None:
    ep = world.episode()
    attempt = world.attempt(ep, reservation_id=uuid.uuid4())
    with pytest.raises(NotFound):
        world.service.submit(attempt.request, job_id=attempt.job_id)
    assert world.server.submissions == []


def test_job_input_mismatch_is_an_idempotency_conflict(world: ComfyWorld) -> None:
    ep = world.episode()
    attempt = world.attempt(ep)
    altered = attempt.request.model_copy(update={"prompt_text": "a different shot"})
    with pytest.raises(IdempotencyConflict):
        world.service.submit(altered, job_id=attempt.job_id)
    assert world.server.submissions == []


def test_bind_refusal_releases_the_unused_hold(world: ComfyWorld) -> None:
    ep = world.episode()
    key = "render.shot:ep1:sh9:attempt1"
    attempt = world.attempt(ep, key=key, controls=(ControlKind.AUDIO_DRIVEN_LIPSYNC,))
    with pytest.raises(UnsupportedControl):
        world.service.submit(attempt.request, job_id=attempt.job_id)
    assert world.server.submissions == []
    assert world.op_rows() == []
    assert world.reservation_row(attempt.request.reservation_id)["state"] == "RELEASED"
    assert world.counters(ep.account_id)["reserved"] == 0


def test_server_catalog_gap_blocks_submission_without_installation(
    world: ComfyWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    ep = world.episode()
    attempt = world.attempt(ep)
    reduced = {name: info for name, info in FAKE_NODE_CLASSES.items() if name != "VHS_VideoCombine"}
    monkeypatch.setattr(world.client, "object_info", lambda: reduced)
    with pytest.raises(UnsupportedControl) as exc:
        world.service.submit(attempt.request, job_id=attempt.job_id)
    assert exc.value.details["class_type"] == "VHS_VideoCombine"
    assert world.server.submissions == []
    assert world.reservation_row(attempt.request.reservation_id)["state"] == "RELEASED"


def test_submit_replay_never_dispatches_a_second_prompt(world: ComfyWorld) -> None:
    ep = world.episode()
    attempt = world.attempt(ep)
    first = world.service.submit(attempt.request, job_id=attempt.job_id)
    world.clock.advance(ms=100)
    second = world.service.submit(attempt.request, job_id=attempt.job_id)
    assert world.server.submissions == [first.prompt_id]
    # reattach: the replay reports live progress (RUNNING) or the queued state, never
    # a second dispatch
    assert second.state in (ProviderOperationState.SUBMITTED, ProviderOperationState.RUNNING)
    assert second.prompt_id == first.prompt_id
    assert len(world.op_rows()) == 1


def test_status_is_a_pure_durable_read(world: ComfyWorld) -> None:
    ep = world.episode()
    attempt = world.attempt(ep)
    world.service.submit(attempt.request, job_id=attempt.job_id)
    calls_before = len(world.client.calls)
    (op,) = world.op_rows()
    status = world.service.status(op["id"])
    assert status.prompt_id == "fake-prompt-0001"
    assert len(world.client.calls) == calls_before  # no provider call on a status read
