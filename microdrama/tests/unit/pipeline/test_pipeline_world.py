"""Unit tests for the composed pipeline world and handler registry (T029)."""

from __future__ import annotations

import uuid

import pytest

from microdrama.contracts.enums import ExecutionMode, Platform, SlotKind
from microdrama.contracts.jobs import JOB_SPECS_BY_TYPE
from microdrama.pipeline.handlers import build_handlers
from microdrama.pipeline.registry_seed import mock_account

pytestmark = [pytest.mark.db]


def test_every_job_spec_has_exactly_one_handler(world) -> None:
    handlers = build_handlers(world)
    assert set(handlers) == set(JOB_SPECS_BY_TYPE), (
        "the handler registry must cover every frozen job type exactly — a new "
        "job type without a handler runs NO_HANDLER"
    )


def test_world_refuses_non_offline_settings(db, tmp_path) -> None:
    from microdrama.contracts.errors import EffectDenied
    from microdrama.pipeline.world import build_pipeline_world

    live = type(
        "S",
        (),
        {
            "execution_mode": ExecutionMode.PRODUCTION,
            "object_store_root": tmp_path / "objects",
            "is_offline_mock": False,
        },
    )()
    with pytest.raises(EffectDenied):
        build_pipeline_world(live, db)  # type: ignore[arg-type]


def test_world_seeds_registries_and_catalog(world) -> None:
    with world.db.transaction(readonly=True) as tx:
        presets = tx.fetchall("SELECT preset_id, enabled FROM preset_registry WHERE current")
        capabilities = tx.fetchall(
            "SELECT platform, account_ref, enabled FROM capability_registry WHERE current"
        )
        rights = tx.fetchall(
            "SELECT rights_route_id, subject_kind, status FROM rights_registry WHERE current"
        )
    assert {row["preset_id"] for row in presets} == {
        "fake-fast-4step",
        "fake-quality-8step",
    }
    assert all(row["enabled"] for row in presets)
    assert len(capabilities) == 4, "one capability per platform"
    assert {row["rights_route_id"] for row in rights} == {
        "mock-fake-synthetic-v1",
        "route-ref-image",
        "route-ref-voice-th",
    }


def test_world_creates_real_principals(world) -> None:
    principal = world.human_owner("pilot-unit", "not-a-real-password")
    assert principal.kind.value == "HUMAN_OWNER"
    token = world.operator_token()
    service = world.auth.authenticate_service(token)
    assert service.kind.value == "SCHEDULER"


def test_release_conditions_block_on_a_disabled_capability(world) -> None:
    """Gate 2 conditions read live registry state: a disabled capability blocks.

    The registry is append-only, so "disabling" is recording a new disabled
    version — exactly how a live operator would retire a route.
    """
    from microdrama.contracts.enums import Provenance
    from microdrama.contracts.release import ReleaseSlotKey
    from microdrama.core.registry.capabilities import CapabilityRegistry
    from microdrama.pipeline.conditions import build_registry_release_conditions

    account = mock_account(Platform.YOUTUBE)
    with world.db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT capability_id, version FROM capability_registry "
            "WHERE platform = %s AND account_ref = %s AND current",
            (Platform.YOUTUBE.value, account),
        )
    assert row is not None, "world seeding must record the YOUTUBE capability"

    key = ReleaseSlotKey(
        series_id=uuid.uuid4(),
        episode_id=uuid.uuid4(),
        part=0,
        locale="th-TH",
        platform=Platform.YOUTUBE,
        account_ref=account,
        release_slot="full",
    )

    class _Plan:
        slot = key
        slot_kind = SlotKind.FULL_EPISODE
        required = True
        disclosures = ["AI_GENERATED_CONTENT"]
        capability_id = row["capability_id"]
        capability_version = row["version"]

    class _Media:
        asset_id = uuid.uuid4()

    class _QA:
        blocking_finding_ids: list = []

    class _Package:
        release_scope = [_Plan()]
        media = [_Media()]
        cast_package_asset_ids: list = []
        qa = _QA()

    adapter = world.fakes.publishers[Platform.YOUTUBE]
    record = adapter.capability(account).model_copy(
        update={"version": row["version"] + 1, "enabled": False}
    )
    CapabilityRegistry(world.db, world.fakes.clock, world.settings).record(
        record, source_provenance=Provenance.FAKE_SYNTHETIC
    )

    conditions = build_registry_release_conditions(world.db, world.fakes.clock, world.settings)
    with world.db.transaction(readonly=True) as tx:
        blockers = conditions(tx, {}, _Package())
    assert blockers, "a disabled current capability must block Gate 2"
