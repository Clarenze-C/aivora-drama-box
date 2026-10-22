"""T020 scheduling: approved package -> slot rows, DAG shape, duplicate rejection."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from publishing_support import PublishingWorld

from microdrama.contracts.enums import EpisodeState, Platform, SlotKind
from microdrama.contracts.errors import Conflict, SchemaInvalid
from microdrama.contracts.primitives import ScheduleInstant
from microdrama.contracts.release import ReleaseSlotPlan


def test_approved_package_becomes_scheduled_slot_rows(world: PublishingWorld) -> None:
    season_id, episode_id, package, _approval = world.approved_episode()
    post_ids = world.schedule(episode_id)

    assert len(post_ids) == 1
    row = world.post_row(post_ids[0])
    assert row["state"] == "SCHEDULED"
    assert row["required"] is True
    assert row["external_id"] is None
    assert row["attempt"] == 0
    assert row["slot_kind"] == "FULL_EPISODE"
    assert row["approval_event_id"] is not None
    assert row["dedupe_key"] == package.release_scope[0].slot.dedupe_key
    assert row["client_token"] is not None and len(row["client_token"]) == 64
    assert world.episode_state(episode_id) == EpisodeState.SCHEDULED.value
    events = world.rows(
        "SELECT * FROM domain_events WHERE aggregate_type = 'platform_post' "
        "AND event_type = 'platform_post.scheduled'"
    )
    assert len(events) == 1


def test_schedule_is_idempotent_for_the_same_package(world: PublishingWorld) -> None:
    _season, episode_id, _pkg, _ap = world.approved_episode()
    first = world.schedule(episode_id)
    second = world.schedule(episode_id)
    assert first == second
    assert (
        world.rows("SELECT id FROM platform_posts WHERE episode_id = %s", (episode_id,))[0]["id"]
        == first[0]
    )


def test_schedule_for_an_episode_without_an_approved_package_is_refused(
    world: PublishingWorld,
) -> None:
    season_id = world.season()
    episode_id = world.episode(season_id, number=3)
    with pytest.raises(Conflict):
        world.schedule(episode_id)


def test_duplicate_slot_key_across_packages_is_rejected_by_the_database(
    world: PublishingWorld,
) -> None:
    """The dedupe-key UNIQUE constraint is the last line of defence (MD-014)."""
    season_id, episode_id, package, _ap = world.approved_episode()
    world.schedule(episode_id)
    plan = package.release_scope[0]
    from microdrama.persistence.db import insert_row, jsonb

    with pytest.raises(Exception):  # noqa: B017 - psycopg unique violation
        with world.db.transaction() as tx:
            insert_row(
                tx,
                "platform_posts",
                {
                    "id": uuid.uuid4(),
                    "series_id": plan.slot.series_id,
                    "episode_id": plan.slot.episode_id,
                    "part": plan.slot.part,
                    "locale": plan.slot.locale,
                    "platform": plan.slot.platform.value,
                    "account_ref": plan.slot.account_ref,
                    "release_slot": plan.slot.release_slot,
                    "dedupe_key": plan.slot.dedupe_key,  # the duplicate
                    "slot_kind": plan.slot_kind.value,
                    "required": True,
                    "release_package_id": world.package_row_id(package),
                    "approval_event_id": world.row(
                        "SELECT approval_event_id FROM release_packages WHERE package_hash = %s",
                        (package.package_hash,),
                    )["approval_event_id"],
                    "asset_id": plan.asset_id,
                    "asset_sha256": plan.asset_sha256,
                    "state": "SCHEDULED",
                    "iana_zone": "Asia/Bangkok",
                    "local_time": "2026-10-27T18:00:00",
                    "scheduled_utc": world.clock.now(),
                    "depends_on": jsonb([]),
                    "client_token": "dup-token-" + uuid.uuid4().hex,
                },
            )


def test_dependency_outside_the_scope_is_refused(world: PublishingWorld) -> None:
    _season, episode_id, _pkg, _ap = _approved_with_dep(world, depends_on=["f" * 64])
    with pytest.raises(Conflict):
        world.schedule(episode_id)


def _approved_with_dep(world: PublishingWorld, depends_on: list[str]):
    def scope(season_id, episode_id, master):
        plan = world.slot_plan(
            season_id=season_id, episode_id=episode_id, asset=master, depends_on=depends_on
        )
        return [plan]

    return world.approved_episode(scope_builder=scope)


def test_dependency_cycle_is_refused(world: PublishingWorld) -> None:
    def scope(season_id, episode_id, master):
        a = world.slot_plan(season_id=season_id, episode_id=episode_id, asset=master, slot="full")
        b = world.slot_plan(
            season_id=season_id,
            episode_id=episode_id,
            asset=master,
            slot="promo",
            slot_kind=SlotKind.PROMO_CUT,
            required=False,
            depends_on=[a.slot.dedupe_key],
        )
        cyclic_a = a.model_copy(update={"depends_on": [b.slot.dedupe_key]})
        return [cyclic_a, b]

    _season, episode_id, _pkg, _ap = world.approved_episode(scope_builder=scope)
    with pytest.raises(Conflict):
        world.schedule(episode_id)


def test_scope_without_a_required_slot_is_refused(world: PublishingWorld) -> None:
    def scope(season_id, episode_id, master):
        return [
            world.slot_plan(
                season_id=season_id,
                episode_id=episode_id,
                asset=master,
                required=False,
                slot_kind=SlotKind.PROMO_CUT,
                slot="promo",
            )
        ]

    _season, episode_id, _pkg, _ap = world.approved_episode(scope_builder=scope)
    with pytest.raises(SchemaInvalid):
        world.schedule(episode_id)


def test_episode_not_release_approved_is_refused(world: PublishingWorld) -> None:
    season_id = world.season()
    episode_id = world.episode(season_id)
    with pytest.raises(Conflict):
        world.schedule(episode_id)


def test_dst_gap_schedule_is_refused_at_contract_level() -> None:
    # 02:30 on 2026-03-08 does not exist in Asia/Bangkok... actually Bangkok has no DST;
    # use a zone with a spring-forward gap (Europe/Berlin 2026-03-29 02:30).
    with pytest.raises(ValueError):
        ScheduleInstant.from_local("Europe/Berlin", datetime(2026, 3, 29, 2, 30))


def test_dst_overlap_requires_explicit_fold() -> None:
    with pytest.raises(ValueError):
        ScheduleInstant.from_local("Europe/Berlin", datetime(2026, 10, 25, 2, 30))
    folded = ScheduleInstant.from_local("Europe/Berlin", datetime(2026, 10, 25, 2, 30), fold=1)
    assert folded.utc_instant.isoformat().endswith("+00:00")


def test_multi_slot_scope_schedules_all_rows(world: PublishingWorld) -> None:
    def scope(season_id, episode_id, master):
        full = world.slot_plan(
            season_id=season_id, episode_id=episode_id, asset=master, slot="full"
        )
        promo = world.slot_plan(
            season_id=season_id,
            episode_id=episode_id,
            asset=master,
            slot="promo",
            slot_kind=SlotKind.PROMO_CUT,
            required=False,
            platform=Platform.TIKTOK,
            account_ref="acct:tiktok-main",
            depends_on=[full.slot.dedupe_key],
        )
        return [full, promo]

    _season, episode_id, _pkg, _ap = world.approved_episode(scope_builder=scope)
    post_ids = world.schedule(episode_id)
    assert len(post_ids) == 2
    promo = world.post_by_slot("promo", episode_id)
    assert promo["depends_on"] == [world.post_by_slot("full", episode_id)["dedupe_key"]]
    assert world.episode_state(episode_id) == EpisodeState.SCHEDULED.value


def test_validate_scope_dag_rejects_self_dependency(world: PublishingWorld) -> None:
    season_id = world.season()
    episode_id = world.episode(season_id)
    master = world.asset(season_id, episode_id)
    plan = world.slot_plan(season_id=season_id, episode_id=episode_id, asset=master)
    # model_copy skips validators; a real construction with a self-dependency is refused
    # by the contract (a slot cannot depend on itself).
    payload = plan.model_dump(mode="json")
    payload["depends_on"] = [plan.slot.dedupe_key]
    with pytest.raises(ValueError):
        ReleaseSlotPlan.model_validate(payload)
