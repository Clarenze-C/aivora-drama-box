"""Gate 2 (episode final review): approve, revise and reject, with every binding and gate check."""

import uuid

import pytest
from review_support import IdentityLockHook, World

from microdrama.contracts.enums import (
    ApprovalAction,
    CaptionTimingSource,
    EpisodeState,
    FeedbackCategory,
    PrincipalKind,
    Severity,
)
from microdrama.contracts.errors import (
    Conflict,
    GateNotReady,
    StaleRevision,
    Unauthorized,
)
from microdrama.contracts.errors import Unauthorized as DbUnauthorized
from microdrama.core.state_machine import transition_episode
from microdrama.review.service import repair_stage_for

pytestmark = pytest.mark.db

APPROVE = ApprovalAction.APPROVE
REVISE = ApprovalAction.REVISE
REJECT = ApprovalAction.REJECT


def advance(world: World, episode_id, *targets: EpisodeState) -> None:
    """Walk an episode along non-human transitions (the pipeline's job, not a gate decision)."""
    worker = world.service_principal(PrincipalKind.SERVICE_WORKER)
    for target in targets:
        with world.db.transaction() as tx:
            revision = tx.fetchval("SELECT revision FROM episodes WHERE id = %s", (episode_id,))
            transition_episode(
                tx,
                episode_id=episode_id,
                to=target,
                expected_revision=revision,
                actor=worker,
                now=world.clock.now(),
                correlation_id=uuid.uuid4(),
            )


def package_row(world: World, package) -> dict:
    return world.row("SELECT * FROM release_packages WHERE id = %s", (package.package_id,))


# --- approve -------------------------------------------------------------------------------


def test_approve_releases_the_episode_and_queues_scheduling_in_one_step(world: World) -> None:
    _season, episode_id, package = world.ready_episode()
    human = world.human()
    command = world.gate2_command(episode_id, package)

    result = world.service.decide_episode(human, episode_id, command)

    assert result.status_code == 202
    assert result.body["status"] == "QUEUED"
    state, outcome, revision = world.episode_state(episode_id)
    assert (state, outcome) == ("RELEASE_APPROVED", None)
    assert revision == result.body["revision"]
    row = package_row(world, package)
    assert row["status"] == "APPROVED"
    approval = world.approvals(episode_id)
    assert len(approval) == 1
    assert row["approval_event_id"] == approval[0]["id"] == uuid.UUID(result.body["event_id"])
    assert approval[0]["media_hashes"] == package.media_hashes
    assert approval[0]["management_policy_hash"] == package.management_policy_hash
    assert approval[0]["release_scope_hash"] == package.release_scope_hash
    jobs = world.jobs_of("publish.schedule_release")
    assert len(jobs) == 1
    assert (
        jobs[0]["semantic_key"] == f"publish.schedule_release:{episode_id}:{package.package_hash}"
    )
    assert jobs[0]["episode_id"] == episode_id


def test_the_identity_lock_for_episode_one_is_created_inside_the_approval(world: World) -> None:
    _season, episode_id, package = world.ready_episode(number=1)
    assert world.identity_lock_hook is not None
    result = world.service.decide_episode(
        world.human(), episode_id, world.gate2_command(episode_id, package)
    )
    assert result.status_code == 202
    locks = world.row("SELECT * FROM identity_locks WHERE source_episode_id = %s", (episode_id,))
    assert locks is not None
    assert locks["approval_event_id"] == uuid.UUID(result.body["event_id"])
    assert world.identity_lock_hook.calls == [uuid.UUID(result.body["event_id"])]


def test_replaying_the_same_approval_returns_the_stored_answer_once(world: World) -> None:
    _season, episode_id, package = world.ready_episode()
    human = world.human()
    command = world.gate2_command(episode_id, package)
    first = world.service.decide_episode(human, episode_id, command)
    second = world.service.decide_episode(human, episode_id, command)

    assert second.replayed is True
    assert second.body == first.body  # the stored answer; the HTTP layer labels it REPLAYED
    assert second.body["job_id"] == first.body["job_id"]
    assert len(world.approvals(episode_id)) == 1
    assert len(world.jobs_of("publish.schedule_release")) == 1


def test_a_second_approval_with_a_new_key_is_refused(world: World) -> None:
    """A stale replay (new key, the revision it was prepared at) is 409, never a second approval."""
    _season, episode_id, package = world.ready_episode()
    human = world.human()
    world.service.decide_episode(human, episode_id, world.gate2_command(episode_id, package))
    prepared_before = world.gate2_command(episode_id, package, revision=1)
    with pytest.raises(StaleRevision):
        world.service.decide_episode(human, episode_id, prepared_before)
    # Same package, current revision, new key: the episode is already released, so the gate refuses.
    with pytest.raises(GateNotReady):
        world.service.decide_episode(
            human, episode_id, world.gate2_command(episode_id, package, revision=2)
        )
    assert len(world.approvals(episode_id)) == 1


def test_same_key_with_a_different_body_is_a_conflict(world: World) -> None:
    from microdrama.contracts.errors import IdempotencyConflict

    _season, episode_id, package = world.ready_episode()
    human = world.human()
    key = "gate2-same-key-0001"
    world.service.decide_episode(
        human, episode_id, world.gate2_command(episode_id, package, idempotency_key=key)
    )
    with pytest.raises(IdempotencyConflict):
        world.service.decide_episode(
            human,
            episode_id,
            world.gate2_command(episode_id, package, idempotency_key=key, reason="changed"),
        )


# --- binding mismatches (every hash the reviewer saw must still be current) ----------------


@pytest.mark.parametrize(
    "override",
    [
        {"package_hash": "1" * 64},
        {"media_hashes": ["2" * 64]},
        {"management_policy_hash": "3" * 64},
        {"release_scope_hash": "4" * 64},
        {"expected_revision": 99},
    ],
    ids=["package_hash", "media_hashes", "policy_hash", "scope_hash", "revision"],
)
def test_each_binding_mismatch_is_stale_and_writes_nothing(world: World, override) -> None:
    _season, episode_id, package = world.ready_episode()
    before = world.episode_state(episode_id)
    command = world.gate2_command(episode_id, package, **override)
    with pytest.raises(StaleRevision):
        world.service.decide_episode(world.human(), episode_id, command)
    assert world.episode_state(episode_id) == before
    assert world.approvals(episode_id) == []
    assert package_row(world, package)["status"] == "READY"
    assert world.jobs_of("publish.schedule_release") == []


def test_media_hashes_are_compared_as_a_set_not_by_order(world: World) -> None:
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    variant = world.asset(season_id=season_id, episode_id=episode_id, data=b"variant-bytes")
    package = world.package(
        season_id=season_id,
        episode_id=episode_id,
        master=master,
        extra_media=[(variant[0], variant[1], "variant")],
    )
    world.store_package(package)
    reversed_order = world.gate2_command(
        episode_id, package, media_hashes=list(reversed(package.media_hashes))
    )
    result = world.service.decide_episode(world.human(), episode_id, reversed_order)
    assert result.status_code == 202


# --- blocked gates ------------------------------------------------------------------------


def _blocked_scenarios(world: World):
    def open_critical(episode_id, package):
        world.qa_finding(episode_id, severity=Severity.CRITICAL)

    def rights_blocker(episode_id, package):
        world.release_conditions = lambda tx, row, pkg: [
            "rights route ep1-music: no ELIGIBLE record"
        ]

    def tampered_asset(episode_id, package):
        row = world.row("SELECT object_key FROM assets WHERE id = %s", (package.media[0].asset_id,))
        world.store.local_path(row["object_key"]).write_bytes(b"tampered")

    def live_lease(episode_id, package):
        world.open_gpu_lease(episode_id, package.season_id, state="ACTIVE")

    def orphaned_unverified_lease(episode_id, package):
        world.open_gpu_lease(episode_id, package.season_id, state="ORPHANED", stop_verified=False)

    def estimated_caption(episode_id, package):
        world.caption(episode_id, timing=CaptionTimingSource.ESTIMATED_FROM_SCRIPT, locale="en-US")

    return {
        "open_critical_finding": open_critical,
        "rights_blocker": rights_blocker,
        "tampered_asset": tampered_asset,
        "live_gpu_lease": live_lease,
        "orphaned_unverified_lease": orphaned_unverified_lease,
        "estimated_caption": estimated_caption,
    }


@pytest.mark.parametrize(
    "scenario",
    [
        "open_critical_finding",
        "rights_blocker",
        "tampered_asset",
        "live_gpu_lease",
        "orphaned_unverified_lease",
        "estimated_caption",
    ],
)
def test_a_blocked_gate_refuses_approve_and_keeps_the_preview(world: World, scenario: str) -> None:
    _season, episode_id, package = world.ready_episode()
    _blocked_scenarios(world)[scenario](episode_id, package)
    before = world.episode_state(episode_id)
    command = world.gate2_command(episode_id, package)
    with pytest.raises(GateNotReady) as info:
        world.service.decide_episode(world.human(), episode_id, command)
    assert info.value.details["blockers"]
    assert world.episode_state(episode_id) == before
    assert world.approvals(episode_id) == []
    assert world.jobs_of("publish.schedule_release") == []
    view = world.service.episode_review(episode_id)
    assert view.gate_enabled is False
    assert view.media, "the preview stays visible even when blocked"


def test_episode_not_awaiting_final_review_refuses_approve(world: World) -> None:
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id, state="AI_REVIEW")
    master = world.asset(season_id=season_id, episode_id=episode_id)
    package = world.package(season_id=season_id, episode_id=episode_id, master=master)
    world.store_package(package)
    with pytest.raises(GateNotReady, match="AI_REVIEW"):
        world.service.decide_episode(
            world.human(), episode_id, world.gate2_command(episode_id, package)
        )


def test_a_blocked_package_still_takes_revise_and_reject(world: World) -> None:
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    package = world.package(
        season_id=season_id,
        episode_id=episode_id,
        master=master,
        gate_blockers=["unknown lip-sync coverage on a dialogue cut"],
    )
    world.store_package(package, status="BLOCKED")
    human = world.human()
    with pytest.raises(GateNotReady):
        world.service.decide_episode(human, episode_id, world.gate2_command(episode_id, package))
    revised = world.service.decide_episode(
        human, episode_id, world.gate2_command(episode_id, package, REVISE)
    )
    assert revised.status_code == 202
    assert package_row(world, package)["status"] == "REVISED"


# --- identity lock (episode one) ----------------------------------------------------------


def test_episode_one_without_an_identity_lock_service_is_refused(world: World) -> None:
    _season, episode_id, package = world.ready_episode(number=1)
    world.identity_lock_hook = None
    with pytest.raises(GateNotReady, match="identity lock service not configured"):
        world.service.decide_episode(
            world.human(), episode_id, world.gate2_command(episode_id, package)
        )
    assert world.approvals(episode_id) == []
    assert world.episode_state(episode_id)[0] == "AWAITING_FINAL_REVIEW"


def test_a_failing_identity_lock_rolls_the_whole_approval_back(world: World) -> None:
    _season, episode_id, package = world.ready_episode(number=1)
    world.identity_lock_hook = IdentityLockHook(fail=Conflict("identity lock write refused"))
    before = world.episode_state(episode_id)
    with pytest.raises(Conflict, match="identity lock write refused"):
        world.service.decide_episode(
            world.human(), episode_id, world.gate2_command(episode_id, package)
        )
    assert len(world.identity_lock_hook.calls) == 1, "the hook ran inside the approval"
    assert world.approvals(episode_id) == []
    assert world.episode_state(episode_id) == before
    assert package_row(world, package)["status"] == "READY"
    assert package_row(world, package)["approval_event_id"] is None
    assert world.count("SELECT COUNT(*) FROM identity_locks") == 0
    assert world.jobs_of("publish.schedule_release") == []
    assert (
        world.count(
            "SELECT COUNT(*) FROM idempotency_records WHERE scope LIKE %s",
            (f"POST /episodes/{episode_id}/review",),
        )
        == 0
    )


def test_later_episodes_do_not_need_the_identity_lock_hook(world: World) -> None:
    _season, episode_id, package = world.ready_episode(number=2)
    world.identity_lock_hook = None
    result = world.service.decide_episode(
        world.human(), episode_id, world.gate2_command(episode_id, package)
    )
    assert result.status_code == 202
    assert world.episode_state(episode_id)[0] == "RELEASE_APPROVED"


# --- revise -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("category", "stage"),
    [
        (FeedbackCategory.MOTIVATION, EpisodeState.SCRIPTING),
        (FeedbackCategory.THAI_DIALOGUE, EpisodeState.REFERENCES),
        (FeedbackCategory.IDENTITY_VOICE, EpisodeState.REFERENCES),
        (FeedbackCategory.CONTINUITY_PROPS, EpisodeState.RENDERING),
        (FeedbackCategory.SUBTITLES, EpisodeState.ASSEMBLING),
        (FeedbackCategory.PACING, EpisodeState.ASSEMBLING),
        (FeedbackCategory.SOUND, EpisodeState.ASSEMBLING),
        (FeedbackCategory.OTHER, EpisodeState.ASSEMBLING),
    ],
)
def test_revise_moves_the_episode_to_the_stage_its_feedback_implies(
    world: World, category: FeedbackCategory, stage: EpisodeState
) -> None:
    from microdrama.contracts.season import TimecodedFeedback

    _season, episode_id, package = world.ready_episode()
    command = world.gate2_command(
        episode_id,
        package,
        REVISE,
        feedback=[
            TimecodedFeedback(
                category=category, start_ms=2_000, end_ms=4_500, comment="fix this beat"
            )
        ],
    )
    before_revision = world.episode_revision(episode_id)
    result = world.service.decide_episode(world.human(), episode_id, command)

    assert result.status_code == 202
    assert result.body["status"] == "QUEUED"
    state, outcome, revision = world.episode_state(episode_id)
    assert state == stage.value and outcome is None
    assert revision == before_revision + 2  # transition, then the QA cycle bump
    assert world.row("SELECT qa_cycle FROM episodes WHERE id = %s", (episode_id,))["qa_cycle"] == 2
    assert package_row(world, package)["status"] == "REVISED"
    feedback = world.row_all("SELECT * FROM feedback_events WHERE episode_id = %s", (episode_id,))
    assert len(feedback) == 1
    assert feedback[0]["category"] == category.value
    assert (feedback[0]["start_ms"], feedback[0]["end_ms"]) == (2_000, 4_500)
    plan = world.jobs_of("qa.plan_repairs")
    assert len(plan) == 1
    assert plan[0]["input"]["trigger"] == "human_feedback"
    assert plan[0]["input"]["expected_revision"] == revision
    assert plan[0]["semantic_key"].startswith(f"qa.plan_repairs:{episode_id}:")


def test_revise_returns_to_the_smallest_affected_stage_across_categories() -> None:
    from microdrama.contracts.season import TimecodedFeedback

    items = [
        TimecodedFeedback(category=FeedbackCategory.SUBTITLES, start_ms=0, end_ms=1, comment="a"),
        TimecodedFeedback(category=FeedbackCategory.MOTIVATION, start_ms=5, end_ms=9, comment="b"),
    ]
    assert repair_stage_for(items) is EpisodeState.SCRIPTING
    assert repair_stage_for(items[:1]) is EpisodeState.ASSEMBLING


def test_the_revised_episode_returns_to_this_gate_with_a_new_package_and_is_approved_there(
    world: World,
) -> None:
    from microdrama.contracts.season import TimecodedFeedback

    season_id, episode_id, first = world.ready_episode()
    human = world.human()
    world.service.decide_episode(
        human,
        episode_id,
        world.gate2_command(
            episode_id,
            first,
            REVISE,
            feedback=[
                TimecodedFeedback(
                    category=FeedbackCategory.THAI_DIALOGUE,
                    start_ms=1_000,
                    end_ms=2_000,
                    comment="line reads stiff",
                )
            ],
        ),
    )
    # THAI_DIALOGUE returns the episode to REFERENCES; the pipeline then runs the rest of the way.
    assert world.episode_state(episode_id)[0] == "REFERENCES"
    advance(
        world,
        episode_id,
        EpisodeState.RENDERING,
        EpisodeState.ASSEMBLING,
        EpisodeState.AI_REVIEW,
        EpisodeState.AWAITING_FINAL_REVIEW,
    )

    recut = world.asset(season_id=season_id, episode_id=episode_id, data=b"revised recut")
    second = world.package(season_id=season_id, episode_id=episode_id, master=recut, version=2)
    world.store_package(second)

    assert package_row(world, first)["status"] == "REVISED", "a REVISED decision stays terminal"
    stale = world.gate2_command(episode_id, first)  # bound to v1, the new content differs
    with pytest.raises(StaleRevision):
        world.service.decide_episode(human, episode_id, stale)

    result = world.service.decide_episode(
        human, episode_id, world.gate2_command(episode_id, second)
    )
    assert result.status_code == 202
    assert world.episode_state(episode_id)[0] == "RELEASE_APPROVED"
    assert package_row(world, second)["status"] == "APPROVED"


def test_a_command_bound_to_an_old_package_is_stale_after_a_new_version(world: World) -> None:
    season_id, episode_id, first = world.ready_episode()
    prepared = world.gate2_command(episode_id, first)  # the reviewer's open form
    second = world.package(
        season_id=season_id,
        episode_id=episode_id,
        master=world.asset(season_id=season_id, episode_id=episode_id, data=b"new master"),
        version=2,
    )
    world.store_package(second)
    current_revision = world.episode_revision(episode_id)
    with pytest.raises(StaleRevision, match="not the current package"):
        world.service.decide_episode(
            world.human(),
            episode_id,
            world.gate2_command(episode_id, first, revision=current_revision),
        )
    with pytest.raises(StaleRevision):
        world.service.decide_episode(world.human(), episode_id, prepared)
    assert world.approvals(episode_id) == []


# --- reject -------------------------------------------------------------------------------


def test_reject_ends_the_episode_and_nothing_can_approve_it_afterwards(world: World) -> None:
    _season, episode_id, package = world.ready_episode()
    human = world.human()
    result = world.service.decide_episode(
        human, episode_id, world.gate2_command(episode_id, package, REJECT)
    )
    assert result.status_code == 202
    assert result.body["status"] == "RECORDED"
    state, outcome, _revision = world.episode_state(episode_id)
    assert (state, outcome) == ("AWAITING_FINAL_REVIEW", "REJECTED")
    assert package_row(world, package)["status"] == "REJECTED"
    with pytest.raises((GateNotReady, StaleRevision)):
        world.service.decide_episode(human, episode_id, world.gate2_command(episode_id, package))


# --- no timers, no shortcuts --------------------------------------------------------------


def test_silence_never_approves_even_after_days(world: World) -> None:
    _season, episode_id, package = world.ready_episode()
    world.clock.advance(seconds=30 * 24 * 3600)
    assert world.episode_state(episode_id)[0] == "AWAITING_FINAL_REVIEW"
    assert world.service.episode_review(episode_id).state is EpisodeState.AWAITING_FINAL_REVIEW
    assert world.approvals(episode_id) == []
    assert package_row(world, package)["status"] == "READY"


@pytest.mark.parametrize(
    "kind",
    [
        PrincipalKind.SERVICE_WORKER,
        PrincipalKind.SCHEDULER,
        PrincipalKind.RUNTIME_MODEL,
        PrincipalKind.PROVIDER_WEBHOOK,
    ],
)
def test_no_worker_model_or_scheduler_can_approve(world: World, kind: PrincipalKind) -> None:
    _season, episode_id, package = world.ready_episode()
    with pytest.raises(Unauthorized):
        world.service.decide_episode(
            world.service_principal(kind), episode_id, world.gate2_command(episode_id, package)
        )
    assert world.approvals(episode_id) == []
    assert world.episode_state(episode_id)[0] == "AWAITING_FINAL_REVIEW"


def test_revise_on_an_episode_outside_the_gate_is_refused(world: World) -> None:
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id, state="ASSEMBLING")
    master = world.asset(season_id=season_id, episode_id=episode_id)
    package = world.package(season_id=season_id, episode_id=episode_id, master=master)
    world.store_package(package)
    with pytest.raises(GateNotReady, match="need AWAITING_FINAL_REVIEW"):
        world.service.decide_episode(
            world.human(), episode_id, world.gate2_command(episode_id, package, REVISE)
        )


def test_the_database_refuses_an_approval_for_a_blocked_package_even_without_the_service(
    world: World,
) -> None:
    """Defence in depth: APPROVE needs a READY package with no blockers, enforced by the database."""
    from microdrama.core.approvals import record_approval_event

    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    package = world.package(
        season_id=season_id,
        episode_id=episode_id,
        master=master,
        gate_blockers=["open rights question"],
    )
    world.store_package(package, status="BLOCKED")
    command = world.gate2_command(episode_id, package)
    with (
        pytest.raises(DbUnauthorized, match="requires a READY package"),
        world.db.transaction() as tx,
    ):
        record_approval_event(
            tx,
            principal=world.human(),
            command=command,
            now=world.clock.now(),
            correlation_id=uuid.uuid4(),
        )
    assert world.approvals(episode_id) == []


def test_the_database_refuses_an_approval_over_an_estimated_caption(world: World) -> None:
    from microdrama.core.approvals import record_approval_event

    _season, episode_id, package = world.ready_episode()
    world.caption(episode_id, timing=CaptionTimingSource.ESTIMATED_FROM_SCRIPT, locale="en-US")
    command = world.gate2_command(episode_id, package)
    with (
        pytest.raises(DbUnauthorized, match="aligned to actual audio"),
        world.db.transaction() as tx,
    ):
        record_approval_event(
            tx,
            principal=world.human(),
            command=command,
            now=world.clock.now(),
            correlation_id=uuid.uuid4(),
        )
    assert world.approvals(episode_id) == []


def test_an_unresolved_critical_from_cycle_one_refuses_the_cycle_two_approval(world: World) -> None:
    """V-26 probe: CRITICAL at cycle 1 -> REVISE -> cycle-2 package READY -> APPROVE is refused
    until the finding is resolved, and then the approval goes through."""
    from microdrama.contracts.season import TimecodedFeedback

    season_id, episode_id, first = world.ready_episode()
    finding = world.qa_finding(episode_id, severity=Severity.CRITICAL, qa_cycle=1)
    human = world.human()

    # REVISE is allowed while the CRITICAL is open (a blocked preview can still be revised).
    world.service.decide_episode(
        human,
        episode_id,
        world.gate2_command(
            episode_id,
            first,
            REVISE,
            feedback=[
                TimecodedFeedback(
                    category=FeedbackCategory.SUBTITLES,
                    start_ms=1_000,
                    end_ms=2_000,
                    comment="caption term is wrong",
                )
            ],
        ),
    )
    assert world.row("SELECT qa_cycle FROM episodes WHERE id = %s", (episode_id,))["qa_cycle"] == 2
    advance(world, episode_id, EpisodeState.AI_REVIEW, EpisodeState.AWAITING_FINAL_REVIEW)

    recut = world.asset(season_id=season_id, episode_id=episode_id, data=b"cycle two cut")
    second = world.package(season_id=season_id, episode_id=episode_id, master=recut, version=2)
    world.store_package(second)

    with pytest.raises(GateNotReady) as refused:
        world.service.decide_episode(human, episode_id, world.gate2_command(episode_id, second))
    assert any(
        f"({finding}) from QA cycle 1" in blocker for blocker in refused.value.details["blockers"]
    )
    assert world.episode_state(episode_id)[0] == "AWAITING_FINAL_REVIEW"
    assert world.approvals(episode_id) and all(
        row["action"] == "REVISE" for row in world.approvals(episode_id)
    ), "only the earlier REVISE was recorded"

    world.row_exec("UPDATE qa_findings SET resolution = 'RESOLVED' WHERE id = %s", (finding,))
    result = world.service.decide_episode(
        human, episode_id, world.gate2_command(episode_id, second)
    )
    assert result.status_code == 202
    assert world.episode_state(episode_id)[0] == "RELEASE_APPROVED"
