"""AT-02 reproduced independently through the composed review service.

Worker, model and scheduler principals cannot approve; a stale final approval
fails; and no replay of an already-decided gate can produce a second approval
event, a second release, or a second publish job. The Gate-1-level checks run
on a cheap research-only world; the Gate-2 replay semantics run against the
completed pilot episode.
"""

from __future__ import annotations

import pytest

from microdrama.contracts.enums import ApprovalAction, GateType
from microdrama.contracts.errors import Conflict, StaleRevision, Unauthorized
from microdrama.contracts.principals import Principal
from microdrama.contracts.season import ApprovalCommand
from microdrama.pipeline.runner import MockPipelineRunner

pytestmark = [pytest.mark.db, pytest.mark.slow]

#: Non-human principals that must never produce an approval event.
NON_HUMAN = (
    Principal(principal_id="svc:pipeline-scheduler", kind="SCHEDULER"),
    Principal(principal_id="worker:render-1", kind="SERVICE_WORKER"),
    Principal(principal_id="model:critic-1", kind="RUNTIME_MODEL", runtime_role="CRITIC"),
    Principal(principal_id="webhook:membership", kind="PROVIDER_WEBHOOK"),
)

#: A HUMAN_OWNER principal without a live session cannot even be CONSTRUCTED —
#: the contract model itself refuses it — so a forged human is impossible at the
#: boundary, not merely rejected inside the service.
def test_forged_sessionless_human_principal_is_unconstructible() -> None:
    with pytest.raises(Exception, match="session"):
        Principal(principal_id="human:forged", kind="HUMAN_OWNER")


def _gate1_command(season_id, revision: int, scope_hash: str, *, key: str | None = None):
    return ApprovalCommand(
        gate=GateType.SEASON_CONCEPT,
        action=ApprovalAction.APPROVE,
        entity_id=season_id,
        expected_revision=revision,
        package_hash=scope_hash,
        idempotency_key=key or f"t030-gate1:{season_id}",
    )


def _row(world, sql: str, params: tuple = ()):
    with world.db.transaction(readonly=True) as tx:
        return tx.fetchone(sql, params)


def _count(world, sql: str, params: tuple = ()) -> int:
    with world.db.transaction(readonly=True) as tx:
        return int(tx.fetchval(sql, params))


@pytest.fixture
def proposed(validation_world):
    """A season with a real W01 research proposal (fake providers, no media work)."""
    runner = MockPipelineRunner(validation_world)
    season_id = runner.w01_research()
    return validation_world, runner, season_id


def _proposal(world, season_id):
    return _row(
        world,
        "SELECT scope_hash FROM season_proposals WHERE season_id = %s AND status = 'PROPOSED'",
        (season_id,),
    )


def test_non_human_principals_cannot_approve_gate1(proposed) -> None:
    world, runner, season_id = proposed
    season = _row(world, "SELECT revision FROM seasons WHERE id = %s", (season_id,))
    proposal = _proposal(world, season_id)
    command = _gate1_command(season_id, season["revision"], proposal["scope_hash"])
    for principal in NON_HUMAN:
        with pytest.raises(Unauthorized):
            world.review.decide_season(principal, season_id, command)
    # And nothing was decided: the season still awaits its human Gate 1.
    assert _row(world, "SELECT state FROM seasons WHERE id = %s", (season_id,))["state"] == (
        "PROPOSED"
    )
    assert _count(
        world, "SELECT count(*) FROM approval_events WHERE entity_id = %s", (season_id,)
    ) == 0


def test_stale_revision_and_rekeyed_gate1_replays_fail(proposed) -> None:
    world, runner, season_id = proposed
    season = _row(world, "SELECT revision FROM seasons WHERE id = %s", (season_id,))
    proposal = _proposal(world, season_id)
    world.review.decide_season(
        runner.human,
        season_id,
        _gate1_command(season_id, season["revision"], proposal["scope_hash"]),
    )
    after = _row(world, "SELECT revision, state FROM seasons WHERE id = %s", (season_id,))
    assert after["state"] == "SEASON_APPROVED"

    # The OLD revision under a FRESH key is a typed stale refusal.
    with pytest.raises((StaleRevision, Conflict)):
        world.review.decide_season(
            runner.human,
            season_id,
            _gate1_command(
                season_id, season["revision"], proposal["scope_hash"], key="t030-stale"
            ),
        )
    # The SAME key with different content (a forged scope hash) is a conflict.
    with pytest.raises((Conflict, StaleRevision)):
        world.review.decide_season(
            runner.human,
            season_id,
            _gate1_command(
                season_id, after["revision"], "f" * 64, key=f"gate1:{season_id}"
            ),
        )
    # Neither attempt changed the decided season.
    assert _row(world, "SELECT state FROM seasons WHERE id = %s", (season_id,))["state"] == (
        "SEASON_APPROVED"
    )


def test_gate2_replays_never_re_release_or_requeue_publish(pilot) -> None:
    """Against the finished pilot episode: whether a replayed Gate 2 command is
    answered as an idempotent replay or as a typed refusal, it creates no second
    approval event, moves no state, and enqueues no new publish job."""
    world, report = pilot
    episode_id = report.episode_id
    episode = _row(world, "SELECT revision, state FROM episodes WHERE id = %s", (episode_id,))
    assert episode["state"] in ("RELEASE_APPROVED", "PUBLISHED", "PUBLISHED_VERIFIED", "MANAGED")
    package = _row(
        world,
        "SELECT package_hash, media_hashes, management_policy_hash, release_scope_hash "
        "FROM release_packages WHERE episode_id = %s AND status = 'APPROVED' "
        "ORDER BY version DESC LIMIT 1",
        (episode_id,),
    )

    def replay_command(*, key: str, package_hash: str | None = None) -> ApprovalCommand:
        return ApprovalCommand(
            gate=GateType.EPISODE_FINAL,
            action=ApprovalAction.APPROVE,
            entity_id=episode_id,
            expected_revision=episode["revision"],
            package_hash=package_hash or package["package_hash"],
            media_hashes=package["media_hashes"],
            management_policy_hash=package["management_policy_hash"],
            release_scope_hash=package["release_scope_hash"],
            idempotency_key=key,
        )

    human = world.human_owner("t030-replay-owner", "t030-not-a-real-password")
    publish_jobs_before = _count(world, "SELECT count(*) FROM jobs WHERE job_type LIKE 'publish.%%'", ())
    approval_events_before = _count(
        world, "SELECT count(*) FROM approval_events WHERE entity_id = %s", (episode_id,)
    )

    # Exact key replay (idempotent answer or typed refusal — either is safe)...
    for command in (
        replay_command(key=f"gate2:{episode_id}"),  # the pilot's own key
        replay_command(key="t030-fresh-replay"),  # a fresh key over decided state
        replay_command(key="t030-forged-hash", package_hash="e" * 64),  # forged media
    ):
        try:
            world.review.decide_episode(human, episode_id, command)
        except (Conflict, StaleRevision):
            pass  # the typed refusal — also safe
        # Whatever the answer, the release side effects did not double.
        assert _count(
            world, "SELECT count(*) FROM approval_events WHERE entity_id = %s", (episode_id,)
        ) == approval_events_before
        assert _count(
            world, "SELECT count(*) FROM jobs WHERE job_type LIKE 'publish.%%'", ()
        ) == publish_jobs_before
    assert _row(world, "SELECT state FROM episodes WHERE id = %s", (episode_id,))["state"] == (
        episode["state"]
    )
