"""Contract-level behaviour of the references module (T011).

Pure tests pin the frozen surfaces this lane consumes and produces — the
``references.prepare_episode`` job spec, the ``ApprovalHook`` protocol T008 calls,
closed module payloads, the full-key cache function, byte verification, and the
frozen-contract round-trip of the filled Script/ShotManifest and the IdentityLock
body (AT-03/IMP-01 at the contract level).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from microdrama.contracts.enums import AssetKind, EpisodeState, QueueName
from microdrama.contracts.errors import ProviderError
from microdrama.contracts.examples import identity_lock
from microdrama.contracts.jobs import JOB_SPECS_BY_TYPE
from microdrama.contracts.providers import GenerationProvider
from microdrama.contracts.season import IdentityLock, Script, ShotManifest
from microdrama.core.hooks import ApprovalHook
from microdrama.references import (
    IMAGE_OPERATION,
    VOICE_ANCHOR_OPERATION,
    VOICE_LINE_OPERATION,
    AnchorSpec,
    ChangeOutcome,
    LineAudio,
    LockMember,
    LockView,
    PrepareOutcome,
    PrepareStatus,
    ReferencesConfig,
    RefKind,
    RenderBindings,
)
from microdrama.references import anchors as A
from microdrama.references.media import verify_generated, wav_media_info
from microdrama.testing.fakes import FakeClock, FakeGenerationProvider, SequentialIds
from microdrama.testing.media import make_png_bytes, make_wav_bytes

_T0 = datetime(2026, 10, 21, tzinfo=UTC)


# --- the frozen job surface is consumed, never redefined -------------------------------


def test_the_frozen_job_spec_exists_and_is_owned_by_references() -> None:
    spec = JOB_SPECS_BY_TYPE["references.prepare_episode"]
    assert spec.owner_module == "references"
    assert spec.queue is QueueName.PRODUCTION
    assert spec.paid is True
    assert spec.input_model.__name__ == "EpisodeStepInput"


def test_operation_kinds_are_namespaced_under_references() -> None:
    for kind in (IMAGE_OPERATION, VOICE_ANCHOR_OPERATION, VOICE_LINE_OPERATION):
        assert kind.startswith("references.")


# --- module payloads are closed and strict ----------------------------------------------


def test_module_payloads_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        AnchorSpec(
            ref_kind=RefKind.FACE,
            ref_key="face.fon",
            prompt="p",
            width=64,
            height=64,
            seed=1,
            surprise=True,
        )
    with pytest.raises(ValidationError):
        PrepareOutcome(
            episode_id=uuid.uuid4(),
            season_id=uuid.uuid4(),
            status=PrepareStatus.CURRENT,
            bogus=1,
        )
    with pytest.raises(ValidationError):
        LineAudio(
            line_id="sc1-l1",
            speaker_character_id="fon",
            voice_id="voice-fon-v1",
            asset_id=uuid.uuid4(),
            sha256="0" * 64,
            actual_duration_ms=0,  # measured durations are strictly positive
        )
    # The config dataclass bounds its knobs the same way the story lane's does.
    with pytest.raises(ValueError):
        ReferencesConfig(generation_timeout_ms=0)
    with pytest.raises(ValueError):
        ReferencesConfig(outfits_per_character=9)
    with pytest.raises(ValueError):
        ReferencesConfig(max_line_characters=2000)


def test_prepare_status_is_a_closed_enum_of_typed_outcomes() -> None:
    assert {s.value for s in PrepareStatus} == {"CURRENT", "REPLAYED", "NOT_DISPATCHED"}


# --- the hook implements the frozen protocol ---------------------------------------------


def test_the_exported_hook_satisfies_the_approval_hook_protocol() -> None:
    from microdrama.references import IdentityLockHook, IdentityLocks

    hook = IdentityLockHook(IdentityLocks(FakeClock(_T0)))
    assert isinstance(hook, ApprovalHook)


def test_the_adapter_targets_the_frozen_generation_provider_protocol() -> None:
    provider = FakeGenerationProvider(clock=FakeClock(_T0), ids=SequentialIds("contract"))
    assert isinstance(provider, GenerationProvider)


# --- cache keys and byte verification are pure and total ---------------------------------


def test_cache_key_is_deterministic_and_covers_the_full_input() -> None:
    spec = AnchorSpec(
        ref_kind=RefKind.FACE,
        ref_key="face.fon",
        prompt="face anchor",
        width=64,
        height=64,
        seed=3,
    )
    one = A.anchor_cache_key(spec, model_config_ref="m", rights_route_id="r")
    two = A.anchor_cache_key(spec, model_config_ref="m", rights_route_id="r")
    assert one == two and len(one) == 64
    changed = spec.model_copy(update={"seed": 4})
    assert A.anchor_cache_key(changed, model_config_ref="m", rights_route_id="r") != one


def test_generated_bytes_verify_or_refuse_typed() -> None:
    verify_generated(make_png_bytes(8, 8), kind=AssetKind.IMAGE)
    info = verify_generated(make_wav_bytes(1_500), kind=AssetKind.AUDIO)
    assert info.duration_ms == 1_500 and info.has_audio and not info.has_video
    with pytest.raises(ProviderError):
        verify_generated(make_png_bytes(8, 8)[:32], kind=AssetKind.IMAGE)  # truncated PNG
    with pytest.raises(ProviderError):
        verify_generated(make_wav_bytes(1_000)[:200], kind=AssetKind.AUDIO)  # torn RIFF
    with pytest.raises(ProviderError):
        verify_generated(b"not media at all", kind=AssetKind.IMAGE)


def test_wav_duration_is_measured_not_estimated() -> None:
    for ms in (200, 640, 4_000):
        assert wav_media_info(make_wav_bytes(ms)).duration_ms == ms


# --- the contract example for the lock still validates (guardian surface untouched) ------


def test_the_contract_identity_lock_example_validates() -> None:
    lock = identity_lock()
    assert isinstance(lock, IdentityLock)
    assert all(
        a.asset_kind.value in {"FACE", "VOICE", "WARDROBE", "LOCATION", "STYLE"}
        for a in lock.locked_assets
    )


# --- DB-backed frozen-contract round-trips (filled payloads validate) ---------------------


def test_filled_script_manifest_and_lock_body_validate_against_frozen_contracts(
    db, object_store, offline_settings
):
    from references_support import World

    world = World(db, object_store, offline_settings)
    season_id, scope, ep1, outcome = world.prepared_episode()
    script = Script.model_validate(
        world.row("SELECT body FROM scripts WHERE episode_id = %s AND status = 'CURRENT'", (ep1,))[
            "body"
        ]
    )
    manifest = ShotManifest.model_validate(
        world.row(
            "SELECT body FROM shot_manifests WHERE episode_id = %s AND status = 'CURRENT'",
            (ep1,),
        )["body"]
    )
    assert all(line.voice_id is not None for scene in script.scenes for line in scene.lines)
    assert all(
        line.actual_duration_ms is not None for scene in script.scenes for line in scene.lines
    )
    assert all(shot.voice_ids or not shot.speaker_ids for shot in manifest.shots)
    assert manifest.identity_lock_id is None  # episode one: provisional until Gate 2

    world.to_awaiting_review(ep1)
    package = world.store_review_package(season_id=season_id, scope=scope, episode_id=ep1)
    world.service.mark_reviewed_in_package(ep1)
    world.approve_episode(ep1, package)
    lock_row = world.row(
        "SELECT body FROM identity_locks WHERE season_id = %s ORDER BY version DESC",
        (season_id,),
    )
    lock = IdentityLock.model_validate(lock_row["body"])
    assert lock.source_episode_id == ep1
    assert lock.release_package_hash == package.package_hash
    assert len(lock.locked_assets) == 12
    # The episode moved through the frozen state machine only.
    assert world.episode_state(ep1) == EpisodeState.RELEASE_APPROVED.value


def test_later_episode_manifest_round_trips_with_the_lock_bound(db, object_store, offline_settings):
    from references_support import World

    world = World(db, object_store, offline_settings)
    season_id, scope, ep1, _outcome = world.prepared_episode()
    world.to_awaiting_review(ep1)
    package = world.store_review_package(season_id=season_id, scope=scope, episode_id=ep1)
    world.service.mark_reviewed_in_package(ep1)
    world.approve_episode(ep1, package)
    lock = world.service.current_lock(season_id)
    assert lock is not None and isinstance(lock, LockView)
    assert all(isinstance(m, LockMember) for m in lock.members)

    ep2 = world.episode(
        season_id, scope, number=2, state="SCRIPTING", identity_lock_id=lock.lock_id
    )
    world.seed_script_and_manifest(
        episode_id=ep2, scope=scope, number=2, identity_lock_id=lock.lock_id
    )
    world.service.prepare_episode(ep2)
    manifest = ShotManifest.model_validate(
        world.row(
            "SELECT body FROM shot_manifests WHERE episode_id = %s AND status = 'CURRENT'",
            (ep2,),
        )["body"]
    )
    assert manifest.identity_lock_id == lock.lock_id
    assert all(shot.reference_lock_version == 1 for shot in manifest.shots)
    bindings = world.service.render_request_bindings(ep2)
    assert isinstance(bindings, RenderBindings) and bindings.lock_version == 1


def test_change_outcome_and_lock_view_are_closed_models(db, object_store, offline_settings):
    from references_support import World

    world = World(db, object_store, offline_settings)
    season_id, scope, ep1, _outcome = world.prepared_episode()
    changed = world.service.explicit_change(
        ep1,
        RefKind.STYLE,
        "style.season",
        new_prompt="style anchor: warmer palette",
        reason="contract test",
    )
    assert isinstance(changed, ChangeOutcome)
    assert changed.superseded_version == 1 and changed.new_version == 2
