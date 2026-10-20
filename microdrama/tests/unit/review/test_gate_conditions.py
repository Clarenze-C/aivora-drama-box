"""Every reason Gate 2 APPROVE is disabled, recomputed from the database at decision time."""

import uuid

import pytest
from review_support import World

from microdrama.contracts.enums import CaptionTimingSource, CoverageStatus, QAOutcome, Severity
from microdrama.contracts.errors import NotFound
from microdrama.review.gate_conditions import gate2_blockers, not_configured_release_conditions
from microdrama.review.packages import PackageStatus, StoredPackage, current_package

pytestmark = pytest.mark.db


def blockers_of(world: World, episode_id) -> list[str]:
    """The public path (review view) and the function itself must agree; both are asserted."""
    view = world.service.episode_review(episode_id)
    with world.db.transaction() as tx:
        episode = tx.fetchone("SELECT * FROM episodes WHERE id = %s", (episode_id,))
        stored = current_package(tx, episode_id)
        direct = gate2_blockers(
            tx,
            episode_row=episode,
            package=stored,
            store=world.store,
            release_conditions_fn=world.release_conditions,
            clock=world.clock,
        )
    assert view.gate_blockers == direct
    assert view.gate_enabled == (not direct)
    return direct


def test_a_ready_package_with_everything_in_place_has_no_blockers(world: World) -> None:
    _season_id, episode_id, _package = world.ready_episode()
    assert blockers_of(world, episode_id) == []


def test_the_fail_closed_default_blocks_until_release_conditions_are_wired(world: World) -> None:
    _season_id, episode_id, _package = world.ready_episode()
    world.release_conditions = not_configured_release_conditions
    blockers = blockers_of(world, episode_id)
    assert blockers == ["rights and capability release conditions are not configured"]


def test_release_condition_blockers_block_but_optional_destinations_do_not(world: World) -> None:
    _season_id, episode_id, _package = world.ready_episode()
    world.release_conditions = lambda tx, row, pkg: [
        "rights route ep1-music: no ELIGIBLE record",
        "optional: capability TIKTOK acct:tt-main lacks SCHEDULE",
    ]
    blockers = blockers_of(world, episode_id)
    assert blockers == ["rights route ep1-music: no ELIGIBLE record"]


def test_episode_must_be_awaiting_final_review_and_have_no_outcome(world: World) -> None:
    season_id, _scope = world.season(approved=True)
    planned = world.episode_with_budget(season_id, state="AI_REVIEW")
    master = world.asset(season_id=season_id, episode_id=planned)
    world.store_package(world.package(season_id=season_id, episode_id=planned, master=master))
    assert any("AI_REVIEW, not AWAITING_FINAL_REVIEW" in b for b in blockers_of(world, planned))

    _s, episode_id, _package = world.ready_episode()
    world.row_exec(
        "UPDATE episodes SET outcome = 'FAILED_QA', outcome_detail = 'x' WHERE id = %s",
        (episode_id,),
    )
    assert any("recorded outcome FAILED_QA" in b for b in blockers_of(world, episode_id))


def test_no_package_means_no_gate(world: World) -> None:
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    assert blockers_of(world, episode_id) == ["no release package is prepared for this episode"]


def test_a_superseded_package_is_not_the_current_one(world: World) -> None:
    season_id, episode_id, first = world.ready_episode()
    second = world.package(
        season_id=season_id,
        episode_id=episode_id,
        master=world.asset(season_id=season_id, episode_id=episode_id, data=b"second-cut"),
        version=2,
    )
    world.store_package(second)
    with world.db.transaction() as tx:
        old = tx.fetchone("SELECT * FROM release_packages WHERE id = %s", (first.package_id,))
    assert old["status"] == "SUPERSEDED"
    # Evaluate the superseded package directly: the gate must refuse it even though it was READY.
    stale = StoredPackage(
        row_id=first.package_id,
        episode_id=episode_id,
        version=1,
        status=PackageStatus.READY,
        revision=old["revision"],
        approval_event_id=None,
        gate_blockers=(),
        package=first,
    )
    with world.db.transaction() as tx:
        episode = tx.fetchone("SELECT * FROM episodes WHERE id = %s", (episode_id,))
        blockers = gate2_blockers(
            tx,
            episode_row=episode,
            package=stale,
            store=world.store,
            release_conditions_fn=world.release_conditions,
            clock=world.clock,
        )
    assert "package v1 is not the current release package" in blockers


def test_open_critical_finding_blocks_while_passing_or_closed_findings_do_not(world: World) -> None:
    _season_id, episode_id, _package = world.ready_episode()
    world.qa_finding(episode_id, severity=Severity.CRITICAL, outcome=QAOutcome.REPAIRABLE)
    assert any("open CRITICAL REPAIRABLE QA finding" in b for b in blockers_of(world, episode_id))


def test_blocked_outcome_blocks_even_at_minor_severity(world: World) -> None:
    _season_id, episode_id, _package = world.ready_episode()
    world.qa_finding(episode_id, severity=Severity.MINOR, outcome=QAOutcome.BLOCKED)
    assert any("open MINOR BLOCKED QA finding" in b for b in blockers_of(world, episode_id))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"severity": Severity.CRITICAL, "outcome": QAOutcome.PASS},  # a pass never blocks
        {"severity": Severity.CRITICAL, "outcome": QAOutcome.REPAIRABLE, "resolution": "RESOLVED"},
        {"severity": Severity.MAJOR, "outcome": QAOutcome.REPAIRABLE},  # not critical
        {
            "severity": Severity.MAJOR,
            "outcome": QAOutcome.UNKNOWN,
            "coverage": CoverageStatus.UNSAMPLED,
        },  # unknown is shown, not a blocker by itself
    ],
)
def test_findings_that_do_not_block(world: World, kwargs) -> None:
    _season_id, episode_id, _package = world.ready_episode()
    world.qa_finding(episode_id, **kwargs)
    assert blockers_of(world, episode_id) == []


def test_an_unresolved_critical_from_an_earlier_cycle_still_blocks(world: World) -> None:
    """V-26: a REVISE moves the QA cycle on, but the open CRITICAL it raised does not lapse."""
    _season, episode_id, _package = world.ready_episode()
    finding = world.qa_finding(episode_id, severity=Severity.CRITICAL, qa_cycle=1)
    world.row_exec("UPDATE episodes SET qa_cycle = 2 WHERE id = %s", (episode_id,))
    assert blockers_of(world, episode_id) == [
        f"open CRITICAL REPAIRABLE QA finding caption.critical_term_match ({finding}) "
        "from QA cycle 1"
    ]


@pytest.mark.parametrize("resolution", ["RESOLVED", "SUPERSEDED"])
def test_only_resolved_or_superseded_releases_an_earlier_cycle_finding(
    world: World, resolution: str
) -> None:
    _season, episode_id, _package = world.ready_episode()
    finding = world.qa_finding(episode_id, severity=Severity.CRITICAL, qa_cycle=1)
    world.row_exec("UPDATE episodes SET qa_cycle = 2 WHERE id = %s", (episode_id,))
    world.row_exec("UPDATE qa_findings SET resolution = %s WHERE id = %s", (resolution, finding))
    assert blockers_of(world, episode_id) == []


def test_accepted_unknown_does_not_release_a_critical(world: World) -> None:
    _season, episode_id, _package = world.ready_episode()
    finding = world.qa_finding(episode_id, severity=Severity.CRITICAL, qa_cycle=1)
    world.row_exec(
        "UPDATE qa_findings SET resolution = 'ACCEPTED_UNKNOWN' WHERE id = %s", (finding,)
    )
    blockers = blockers_of(world, episode_id)
    assert len(blockers) == 1
    assert "unreleased CRITICAL REPAIRABLE QA finding" in blockers[0]
    assert "(resolution ACCEPTED_UNKNOWN)" in blockers[0]


def test_a_finding_resolved_in_cycle_one_does_not_hide_a_new_cycle_two_critical(
    world: World,
) -> None:
    _season, episode_id, _package = world.ready_episode()
    old = world.qa_finding(episode_id, severity=Severity.CRITICAL, qa_cycle=1)
    world.row_exec("UPDATE qa_findings SET resolution = 'RESOLVED' WHERE id = %s", (old,))
    world.row_exec("UPDATE episodes SET qa_cycle = 2 WHERE id = %s", (episode_id,))
    new = world.qa_finding(episode_id, severity=Severity.CRITICAL, qa_cycle=2)
    assert blockers_of(world, episode_id) == [
        f"open CRITICAL REPAIRABLE QA finding caption.critical_term_match ({new}) from QA cycle 2"
    ]


def test_unregistered_asset_in_the_package_blocks(world: World) -> None:
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    package = world.package(
        season_id=season_id,
        episode_id=episode_id,
        master=master,
        extra_media=[(uuid.uuid4(), "a" * 64, "variant")],
    )
    world.store_package(package)
    assert any(
        "variant asset" in b and "is not registered" in b for b in blockers_of(world, episode_id)
    )


def test_tampered_object_fails_persisted_verification(world: World) -> None:
    _season_id, episode_id, package = world.ready_episode()
    master_id = package.media[0].asset_id
    row = world.row("SELECT object_key FROM assets WHERE id = %s", (master_id,))
    world.store.local_path(row["object_key"]).write_bytes(b"tampered after packaging")
    blockers = blockers_of(world, episode_id)
    assert any("failed persisted-object verification" in b for b in blockers)


def test_missing_object_fails_persisted_verification(world: World) -> None:
    _season_id, episode_id, package = world.ready_episode()
    row = world.row("SELECT object_key FROM assets WHERE id = %s", (package.media[0].asset_id,))
    world.store.local_path(row["object_key"]).unlink()
    assert any("failed persisted-object verification" in b for b in blockers_of(world, episode_id))


def test_asset_whose_registered_hash_differs_from_the_package_blocks(world: World) -> None:
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    variant_id, _sha = world.asset(season_id=season_id, episode_id=episode_id, data=b"variant-cut")
    package = world.package(
        season_id=season_id,
        episode_id=episode_id,
        master=master,
        extra_media=[(variant_id, "e" * 64, "variant")],  # the package names another hash
    )
    world.store_package(package)
    assert any("hash differs from the package" in b for b in blockers_of(world, episode_id))


@pytest.mark.parametrize("stop_verified", [False, True])
@pytest.mark.parametrize("lease_state", ["CLAIMED", "ACTIVE", "TRANSFERRING"])
def test_a_live_gpu_lease_blocks_whether_or_not_a_stop_was_recorded(
    world: World, lease_state: str, stop_verified: bool
) -> None:
    season_id, episode_id, _package = world.ready_episode()
    lease = world.open_gpu_lease(
        episode_id, season_id, state=lease_state, stop_verified=stop_verified
    )
    assert blockers_of(world, episode_id) == [
        f"GPU pod lease {lease} is {lease_state}; the GPU must be released before Gate 2"
    ]


@pytest.mark.parametrize("lease_state", ["ORPHANED", "EXPIRED"])
def test_an_orphaned_or_expired_lease_with_an_unverified_stop_blocks(
    world: World, lease_state: str
) -> None:
    """A lease that lost its owner may still have a running, billing pod (SPEC §5 rule 8)."""
    season_id, episode_id, _package = world.ready_episode()
    lease = world.open_gpu_lease(episode_id, season_id, state=lease_state, stop_verified=False)
    assert blockers_of(world, episode_id) == [
        f"GPU pod lease {lease} is {lease_state} and its stop is not verified; "
        "the GPU must be confirmed off before Gate 2"
    ]


@pytest.mark.parametrize("lease_state", ["ORPHANED", "EXPIRED"])
def test_an_orphaned_or_expired_lease_with_a_verified_stop_does_not_block(
    world: World, lease_state: str
) -> None:
    season_id, episode_id, _package = world.ready_episode()
    world.open_gpu_lease(episode_id, season_id, state=lease_state, stop_verified=True)
    assert blockers_of(world, episode_id) == []


def test_only_the_unverified_orphaned_lease_blocks_when_both_kinds_exist(world: World) -> None:
    season_id, episode_id, _package = world.ready_episode()
    stopped = world.open_gpu_lease(episode_id, season_id, state="ORPHANED", stop_verified=True)
    unstopped = world.open_gpu_lease(episode_id, season_id, state="EXPIRED", stop_verified=False)
    blockers = blockers_of(world, episode_id)
    assert blockers == [
        f"GPU pod lease {unstopped} is EXPIRED and its stop is not verified; "
        "the GPU must be confirmed off before Gate 2"
    ]
    assert str(stopped) not in " ".join(blockers)


@pytest.mark.parametrize("stop_verified", [False, True])
def test_a_released_lease_never_blocks(world: World, stop_verified: bool) -> None:
    season_id, episode_id, _package = world.ready_episode()
    world.open_gpu_lease(episode_id, season_id, state="RELEASED", stop_verified=stop_verified)
    assert blockers_of(world, episode_id) == []


def test_estimated_caption_in_the_package_blocks(world: World) -> None:
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    estimated = world.caption(episode_id, timing=CaptionTimingSource.ESTIMATED_FROM_SCRIPT)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    world.store_package(
        world.package(
            season_id=season_id, episode_id=episode_id, master=master, captions=[estimated]
        )
    )
    blockers = blockers_of(world, episode_id)
    assert any("estimated from script" in b for b in blockers)


def test_any_current_estimated_caption_of_the_episode_blocks_even_if_unlisted(world: World) -> None:
    _season_id, episode_id, _package = world.ready_episode()
    world.caption(episode_id, timing=CaptionTimingSource.ESTIMATED_FROM_SCRIPT, locale="en-US")
    assert any("not aligned to actual audio" in b for b in blockers_of(world, episode_id))


def test_a_listed_caption_track_that_is_not_current_blocks(world: World) -> None:
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    superseded = world.caption(episode_id, state="SUPERSEDED", locale="th-TH")
    master = world.asset(season_id=season_id, episode_id=episode_id)
    world.store_package(
        world.package(
            season_id=season_id, episode_id=episode_id, master=master, captions=[superseded]
        )
    )
    assert any("is SUPERSEDED, not CURRENT" in b for b in blockers_of(world, episode_id))


def test_a_missing_caption_track_blocks(world: World) -> None:
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    world.store_package(
        world.package(
            season_id=season_id, episode_id=episode_id, master=master, captions=[uuid.uuid4()]
        )
    )
    assert any("is missing" in b for b in blockers_of(world, episode_id))


def test_unknown_coverage_is_shown_but_blocks_only_when_the_package_lists_it(world: World) -> None:
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    world.store_package(
        world.package(
            season_id=season_id,
            episode_id=episode_id,
            master=master,
            unknown_checks=["temporal.lip_sync"],
        )
    )
    view = world.service.episode_review(episode_id)
    assert view.gate_enabled is True
    assert view.package.qa.unknown_coverage_check_ids == ["temporal.lip_sync"]


def test_a_package_gate_blocker_stops_the_gate_even_for_unknown_coverage(world: World) -> None:
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    world.store_package(
        world.package(
            season_id=season_id,
            episode_id=episode_id,
            master=master,
            unknown_checks=["temporal.lip_sync"],
            gate_blockers=["unknown lip-sync coverage on a dialogue cut"],
        ),
        status="BLOCKED",
    )
    assert "unknown lip-sync coverage on a dialogue cut" in blockers_of(world, episode_id)


def test_management_policy_must_match_the_approved_season_scope(world: World) -> None:
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    world.store_package(
        world.package(
            season_id=season_id, episode_id=episode_id, master=master, policy_hash="a" * 64
        )
    )
    assert any("management policy hash differs" in b for b in blockers_of(world, episode_id))


def test_findings_and_coverage_are_visible_even_when_blocked(world: World) -> None:
    _season_id, episode_id, _package = world.ready_episode()
    world.qa_finding(episode_id, severity=Severity.CRITICAL)
    view = world.service.episode_review(episode_id)
    assert view.gate_enabled is False
    assert len(view.findings) == 1 and view.findings[0].severity is Severity.CRITICAL


def test_unknown_episode_is_not_found(world: World) -> None:
    with pytest.raises(NotFound):
        world.service.episode_review(uuid.uuid4())
