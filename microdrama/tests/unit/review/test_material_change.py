"""Material changes need a new Gate 2; bounded metadata inside the approved policy does not."""

import uuid

import pytest
from review_support import World

from microdrama.contracts.enums import AssetKind, ManagementActionKind
from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.release import MediaRef
from microdrama.contracts.season import ManagementPolicy
from microdrama.review.render import timecode, usd
from microdrama.review.service import (
    is_material_change,
    metadata_within_policy,
    parse_timecode,
)

pytestmark = pytest.mark.db


def _package(world: World, **changes):
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    return (
        season_id,
        episode_id,
        world.package(season_id=season_id, episode_id=episode_id, master=master, **changes),
    )


def test_an_identical_package_is_not_a_material_change(world: World) -> None:
    _s, _e, package = _package(world)
    assert is_material_change(package, package) is False


def test_a_different_master_hash_is_a_material_change(world: World) -> None:
    season_id, episode_id, original = _package(world)
    recut_id, recut_sha = world.asset(
        season_id=season_id, episode_id=episode_id, data=b"recut video bytes"
    )
    recut = world.package(
        season_id=season_id, episode_id=episode_id, version=2, master=(recut_id, recut_sha)
    )
    assert is_material_change(original, recut) is True


def test_a_caption_track_change_is_material(world: World) -> None:
    season_id, episode_id, original = _package(world)
    new_track = world.caption(episode_id, locale="en-US")
    changed = original.model_copy(update={"caption_track_ids": [new_track]})
    assert is_material_change(original, changed) is True


def test_an_overlay_cover_or_hook_change_is_material(world: World) -> None:
    season_id, episode_id, original = _package(world)
    cover_id, cover_sha = world.asset(
        season_id=season_id,
        episode_id=episode_id,
        kind=AssetKind.IMAGE,
        data=b"cover-png",
        media_type="image/png",
    )
    with_cover = original.model_copy(
        update={
            "media": [*original.media, MediaRef(asset_id=cover_id, sha256=cover_sha, role="cover")]
        }
    )
    assert is_material_change(original, with_cover) is True
    rehooked = original.model_copy(update={"hook_experiment_id": uuid.uuid4()})
    assert is_material_change(original, rehooked) is True


def test_a_release_scope_or_policy_hash_change_is_material(world: World) -> None:
    _s, _e, original = _package(world)
    assert is_material_change(original, original) is False
    other_policy = original.model_copy(update={"management_policy_hash": "5" * 64})
    assert is_material_change(original, other_policy) is True
    same_content = original.model_copy(update={"gate_blockers": ["noted"], "version": 2})
    assert is_material_change(original, same_content) is False


@pytest.mark.parametrize(
    "kind",
    [
        ManagementActionKind.TITLE_EDIT,
        ManagementActionKind.CAPTION_EDIT,
        ManagementActionKind.DESCRIPTION_EDIT,
        ManagementActionKind.HASHTAG_EDIT,
        ManagementActionKind.PUBLIC_REPLY,
    ],
)
def test_bounded_metadata_inside_the_approved_policy_needs_no_new_gate(kind) -> None:
    approved = ManagementPolicy(
        allowed_actions=frozenset(
            {
                ManagementActionKind.TITLE_EDIT,
                ManagementActionKind.CAPTION_EDIT,
                ManagementActionKind.DESCRIPTION_EDIT,
                ManagementActionKind.HASHTAG_EDIT,
                ManagementActionKind.PUBLIC_REPLY,
            }
        )
    )
    assert metadata_within_policy(approved, kind) is True


@pytest.mark.parametrize(
    "kind",
    [
        ManagementActionKind.COVER_CHANGE,  # a visual change, so media
        ManagementActionKind.LINK_UPDATE,  # offers and disclosures stay human-reviewed
        ManagementActionKind.DM_SEND,
        ManagementActionKind.MODERATE_DELETE,
        ManagementActionKind.MODERATE_HIDE,
        ManagementActionKind.NO_ACTION,
    ],
)
def test_other_changes_are_not_metadata_within_policy(kind) -> None:
    everything = ManagementPolicy(allowed_actions=frozenset(ManagementActionKind))
    assert metadata_within_policy(everything, kind) is False


def test_metadata_outside_the_allowed_actions_is_not_within_policy() -> None:
    narrow = ManagementPolicy(allowed_actions=frozenset({ManagementActionKind.HASHTAG_EDIT}))
    assert metadata_within_policy(narrow, ManagementActionKind.HASHTAG_EDIT) is True
    assert metadata_within_policy(narrow, ManagementActionKind.TITLE_EDIT) is False


def test_timecodes_parse_to_integer_milliseconds() -> None:
    assert parse_timecode("12500") == 12_500
    assert parse_timecode("00:12.5") == 12_500
    assert parse_timecode("01:02.345") == 62_345
    assert parse_timecode("1:02:03.004") == 3_723_004
    assert parse_timecode(" 00:00 ") == 0
    for bad in ["", "12:61", "1:99:00", "abc", "-5", "1.5", "00:12:345"]:
        with pytest.raises(SchemaInvalid):
            parse_timecode(bad)


def test_timecode_and_money_rendering_use_integers_only() -> None:
    assert timecode(3_723_004) == "01:02:03.004"
    assert timecode(None) == "unknown"
    assert usd(10_000_000) == "US$10.0000"
    assert usd(20_000) == "US$0.0200"
    assert usd(-1_500_000) == "-US$1.5000"
    assert usd(None) == "unknown"
