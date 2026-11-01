from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from microdrama.contracts import build
from microdrama.contracts.enums import RightsStatus, RightsSubjectKind
from microdrama.contracts.examples import (
    EXTRA_VALID,
    V2_VALID_BUILDERS,
    approval_gate1,
    creative_derivative_ref,
    h,
    publication_command,
    release_package,
    release_package_with_derivatives,
    rights_record,
    v1_manifest_readback,
    v2_directing_manifest,
    v2_episode_pack,
    v2_owner_approved_release_approval_manifest,
    v2_release_approval_manifest,
    v2_rights,
    v2_season_story_ledger,
    v2_state_event,
    v2_wardrobe_assignment,
    v2_wardrobe_bible,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.release import (
    CreativeDerivativeRef,
    PostMetadata,
    PublicationCommand,
    ReleasePackage,
)
from microdrama.contracts.season import ApprovalCommand
from microdrama.contracts.v2 import (
    ConceptCandidate,
    EpisodePack,
    PromptManifest,
    ReleaseApprovalManifest,
    read_v1_manifest,
    validate_current_rights_grant,
    validate_directing_manifest,
    validate_live_release_metadata,
    validate_season_story_ledger,
    validate_state_event_chain,
    validate_wardrobe_assignment,
    verify_v2_record_hash,
)


def _reseal(record, **updates):
    values = {name: getattr(record, name) for name in type(record).model_fields}
    values.update(updates)
    return type(record).seal(**values)


def test_every_v2_record_hash_is_reproducible() -> None:
    for name, builder in V2_VALID_BUILDERS.items():
        record = builder()
        if hasattr(record, "content_hash_matches"):
            assert record.content_hash_matches(), name
            assert record.calculated_content_sha256() == record.calculated_content_sha256()
            verify_v2_record_hash(record)


def test_stale_record_hash_is_rejected_before_storage() -> None:
    stale = v2_episode_pack().model_copy(update={"promise": "tampered"})
    with pytest.raises(ValueError, match="content_sha256"):
        verify_v2_record_hash(stale)


def test_v2_seal_normalizes_json_readback_values_before_hashing() -> None:
    payload = v2_episode_pack().model_dump(mode="json")
    sealed = type(v2_episode_pack()).seal(**payload)
    assert sealed.content_hash_matches()
    assert sealed.scenes[0].story_time.local_time == "09:30"


def test_v2_readback_and_generated_contract_validation_reject_stale_hash() -> None:
    payload = v2_episode_pack().model_dump(mode="json")
    payload["promise"] = "tampered without resealing"
    with pytest.raises(ValidationError, match="content_sha256"):
        type(v2_episode_pack()).model_validate(payload)
    files = build.render()
    path = "examples/v2/valid/ConceptIntake.json"
    valid = json.loads(files[path])
    valid["story_idea"] = "tampered without resealing"
    files[path] = json.dumps(valid)
    assert any(
        "invalid V2 content hash" in issue or "valid example rejected" in issue
        for issue in build.validate(files)
    )


def test_v1_manifest_readback_preserves_audit_identity_and_never_claims_ready() -> None:
    payload = v1_manifest_readback().manifest
    result = read_v1_manifest(payload)
    assert result.source_schema_version == "1.0"
    assert result.manifest_sha256 == canonical_hash(payload)
    assert result.v2_ready is False
    assert "audit readback only" in result.compatibility_note


def test_episode_pack_uses_v2_duration_and_typed_story_time() -> None:
    pack = v2_episode_pack()
    assert pack.schema_version == "2.0"
    assert 180_000 <= pack.duration_target_ms <= 300_000
    assert pack.scenes[0].story_time.story_day == 1
    assert pack.approved_scope_hash == h("approved-season-scope")


def test_episode_pack_readback_requires_gate1_approved_scope_hash() -> None:
    payload = v2_episode_pack().model_dump(mode="json")
    payload.pop("approved_scope_hash")
    payload.pop("content_sha256")
    with pytest.raises(ValidationError, match="approved_scope_hash"):
        EpisodePack.model_validate(payload)


def test_directing_manifest_binds_exact_pack_and_preserves_shot_local_invalidation() -> None:
    manifest = v2_directing_manifest()
    pack = v2_episode_pack()
    validate_directing_manifest(manifest, pack)
    shot = manifest.shots[0]
    assert shot.duration_ms <= 15_000
    assert manifest.pack_hash == pack.content_sha256
    assert manifest.pack_hash in manifest.source_hashes
    assert manifest.pack_hash not in shot.source_hashes
    assert set(shot.source_hashes).issubset(set(manifest.source_hashes))
    assert manifest.manifest_hash == manifest.content_sha256
    source_scene = pack.scenes[0]
    changed_beat = source_scene.beats[0].model_copy(
        update={"visible_action": "Changed local beat."}
    )
    changed_scene = source_scene.model_copy(update={"beats": [changed_beat]})
    source_scene_hash = canonical_hash(source_scene.model_copy(update={"beats": []}))
    assert source_scene_hash == canonical_hash(changed_scene.model_copy(update={"beats": []}))
    assert canonical_hash(source_scene.beats[0]) != canonical_hash(changed_beat)
    assert source_scene_hash in shot.source_hashes

    changed_pack = _reseal(pack, version=pack.version + 1)
    with pytest.raises(ValueError, match="exact approved EpisodePack"):
        validate_directing_manifest(manifest, changed_pack)

    unknown_beat = shot.model_copy(
        update={
            "beat_id": "unknown-beat",
            "source_dependency_ids": [pack.record_id.hex, shot.scene_id, "unknown-beat"],
        }
    )
    changed_manifest = _reseal(manifest, shots=[unknown_beat])
    with pytest.raises(ValueError, match="scene/beat does not resolve"):
        validate_directing_manifest(changed_manifest, pack)


def test_directing_manifest_sections_cover_ordered_shots_and_exact_duration() -> None:
    manifest = v2_directing_manifest()
    section = manifest.sections[0].model_copy(update={"duration_ms": 14_999})
    with pytest.raises(ValidationError, match="section duration must equal"):
        _reseal(manifest, sections=[section])


@pytest.mark.parametrize(
    ("case_name", "message"),
    [
        ("missing_beat_dependency", "beat dependencies must resolve"),
        ("cyclic_beat_dependencies", "cyclic beat dependencies"),
        ("unknown_proof_object", "proof_object_ids must reference props"),
        ("missing_scene_dependency", "scene dependencies must resolve"),
        ("cyclic_scene_dependencies", "cyclic scene dependencies"),
    ],
)
def test_episode_pack_rejects_invalid_proof_and_dependency_graphs(
    case_name: str, message: str
) -> None:
    files = build.render()
    payload = json.loads(files[f"examples/v2/invalid/EpisodePack__{case_name}.json"])
    with pytest.raises(ValidationError, match=message):
        EpisodePack.model_validate(payload)


def test_candidate_can_truthfully_report_pending_rights_without_granting_production_rights() -> (
    None
):
    candidate = EXTRA_VALID["ConceptCandidate__pending_rights"]()
    assert isinstance(candidate, ConceptCandidate)
    assert candidate.rights.status == "PENDING"
    assert "before production" in candidate.rights.note
    assert candidate.content_hash_matches()


def test_candidate_pending_rights_requires_explicit_uncertainty_status() -> None:
    candidate = V2_VALID_BUILDERS["ConceptCandidate"]()
    payload = candidate.model_dump(mode="json")
    payload["rights"] = {"note": "Rights need review."}
    payload.pop("content_sha256")
    payload["content_sha256"] = canonical_hash(payload)
    with pytest.raises(ValidationError):
        ConceptCandidate.model_validate(payload)


def test_season_story_ledger_binds_same_season_records_and_episode_bounds() -> None:
    ledger = v2_season_story_ledger()
    character = V2_VALID_BUILDERS["CharacterLogic"]()
    secrets = V2_VALID_BUILDERS["SecretLedger"]()
    validate_season_story_ledger(
        ledger,
        [character],
        secrets,
        approved_scope_hash=ledger.approved_scope_hash,
        episode_count=10,
    )
    with pytest.raises(ValueError, match="different or unbound season"):
        validate_season_story_ledger(
            ledger,
            [_reseal(character, season_id=h_uuid("other-season"))],
            secrets,
            approved_scope_hash=ledger.approved_scope_hash,
            episode_count=10,
        )
    with pytest.raises(ValueError, match="due episode exceeds"):
        validate_season_story_ledger(
            ledger,
            [character],
            secrets,
            approved_scope_hash=ledger.approved_scope_hash,
            episode_count=1,
        )


def test_stale_outfit_assignment_is_rejected() -> None:
    assignment = v2_wardrobe_assignment()
    bible = v2_wardrobe_bible()
    stale = _reseal(bible, version=bible.version + 1)
    with pytest.raises(ValueError, match="stale bible"):
        validate_wardrobe_assignment(assignment, stale)


def test_live_rights_resolution_requires_exact_current_subject_version_and_expiry() -> None:
    now = datetime(2026, 10, 30, tzinfo=UTC)
    row = rights_record().model_copy(
        update={
            "rights_route_id": "original-fiction",
            "subject_kind": RightsSubjectKind.MODEL_OUTPUT,
            "subject_ref": "original-fiction-output",
            "version": 1,
            "territories": ["TH"],
            "expires_at": now + timedelta(days=1),
        }
    )
    grant = v2_rights().model_copy(update={"expires_at": row.expires_at})
    assert (
        validate_current_rights_grant(
            grant, lambda route, kind, ref: row, at=now, territories=["TH"]
        )
        is row
    )

    cases = [
        (row.model_copy(update={"version": 2}), "exact current"),
        (row.model_copy(update={"status": RightsStatus.INELIGIBLE}), "not eligible"),
        (row.model_copy(update={"subject_ref": "different-subject"}), "exact current"),
        (row.model_copy(update={"expires_at": now}), "expired"),
    ]
    for current, message in cases:
        with pytest.raises(ValueError, match=message):
            validate_current_rights_grant(
                grant,
                lambda route, kind, ref, current=current: current,
                at=now,
                territories=["TH"],
            )


def test_outfit_assignment_must_match_bible_exact_asset_hash() -> None:
    current = v2_wardrobe_assignment()
    assignment = _reseal(current, asset_sha256=h("changed"))
    with pytest.raises(ValueError, match="stale against"):
        validate_wardrobe_assignment(assignment, v2_wardrobe_bible())


def test_contradictory_state_chain_is_rejected() -> None:
    first = v2_state_event()
    second = _reseal(
        first,
        sequence=2,
        before="unrelated",
        after="closed",
        effective_from_ms=first.effective_until_ms,
        effective_until_ms=first.effective_until_ms + 1000,
    )
    with pytest.raises(ValueError, match="contradicts previous state"):
        validate_state_event_chain([first, second])


def test_prompt_schema_requires_v2_and_semantic_bindings() -> None:
    manifest = V2_VALID_BUILDERS["PromptManifest"]()
    assert isinstance(manifest, PromptManifest)
    data = manifest.model_dump(mode="json")
    data["schema_version"] = "1.0"
    with pytest.raises(ValidationError):
        PromptManifest.model_validate(data)


def test_gate2_release_manifest_binds_slot_metadata_policy_and_media_hash() -> None:
    manifest = v2_release_approval_manifest()
    assert manifest.gate2_package_hash == manifest.compute_approval_hash()
    assert ReleaseApprovalManifest.seal(**manifest.model_dump(mode="json")) == manifest
    slot = manifest.slots[0]
    altered_slot = _reseal(slot, title="unapproved change")
    altered = manifest.model_copy(update={"slots": [altered_slot]})
    with pytest.raises(ValueError, match="approval manifest hash"):
        ReleaseApprovalManifest.model_validate(altered.model_dump(mode="python"))
    with pytest.raises(ValueError, match="owner-approved"):
        _validate_slot(manifest, slot)


def _validate_slot(manifest, slot, **updates):
    projection_values = {
        "locale": slot.locale,
        "title": slot.title,
        "caption": slot.caption,
        "description": slot.description,
        "hashtags": slot.hashtags,
        "links": slot.links,
        "disclosures": slot.disclosures,
        "catalog_version": slot.catalog_version,
        "cover_asset_id": slot.cover_asset_id,
        "cover_asset_version": slot.cover_asset_version,
        "cover_asset_sha256": slot.cover_asset_sha256,
        "cta_text": slot.cta_text,
    }
    values = {
        "slot_id": slot.slot_id,
        "metadata_id": slot.metadata_id,
        "metadata_version": slot.metadata_version,
        "metadata_sha256": slot.content_sha256,
    }
    for key, value in updates.items():
        if key in projection_values:
            projection_values[key] = value
        else:
            values[key] = value
    values["metadata_projection"] = PostMetadata(**projection_values)
    return validate_live_release_metadata(manifest, **values)


def test_owner_approved_slot_metadata_passes_exact_persisted_content_hash() -> None:
    manifest = v2_owner_approved_release_approval_manifest()
    slot = manifest.slots[0]
    assert _validate_slot(manifest, slot) == slot


def test_live_metadata_requires_disclosures_and_catalog_even_for_old_readback_shape() -> None:
    manifest = v2_owner_approved_release_approval_manifest()
    slot = manifest.slots[0]
    incomplete = _reseal(slot, disclosures=[], catalog_version=None)
    incomplete_manifest = ReleaseApprovalManifest.seal(
        **{**manifest.model_dump(mode="python"), "slots": [incomplete]}
    )
    with pytest.raises(ValueError, match="approved disclosures and catalog version"):
        _validate_slot(incomplete_manifest, slot)


def test_live_metadata_preserves_explicitly_absent_cover_and_cta_exactly() -> None:
    manifest = v2_owner_approved_release_approval_manifest()
    original = manifest.slots[0]
    absent = _reseal(
        original,
        cover_asset_id=None,
        cover_asset_version=None,
        cover_asset_sha256=None,
        cover_rights=None,
        cta_text=None,
    )
    absent_manifest = ReleaseApprovalManifest.seal(
        **{**manifest.model_dump(mode="python"), "slots": [absent]}
    )
    assert _validate_slot(absent_manifest, absent) == absent
    with pytest.raises(ValueError, match="provider metadata projection differs"):
        _validate_slot(
            absent_manifest,
            absent,
            cover_asset_id=original.cover_asset_id,
            cover_asset_version=original.cover_asset_version,
            cover_asset_sha256=original.cover_asset_sha256,
        )
    with pytest.raises(ValueError, match="provider metadata projection differs"):
        _validate_slot(absent_manifest, absent, cta_text="A later unapproved CTA")


def test_legacy_post_metadata_allows_cover_id_without_v2_content_binding() -> None:
    command = publication_command()
    legacy = PostMetadata.model_validate(
        {**command.metadata.model_dump(mode="python"), "cover_asset_id": h_uuid("legacy-cover")}
    )
    assert legacy.cover_asset_version is None
    assert legacy.cover_asset_sha256 is None


def test_gate2_command_carries_manifest_hash_separately_from_v1_package_hash() -> None:
    payload = approval_gate1().model_dump(mode="json")
    payload["release_manifest_hash"] = h("gate2-manifest")
    with pytest.raises(ValidationError, match="only valid on Gate 2 APPROVE"):
        ApprovalCommand.model_validate(payload)


def h_uuid(label: str):
    from uuid import NAMESPACE_URL, uuid5

    return uuid5(NAMESPACE_URL, label)


def test_publication_command_requires_complete_optional_v2_stale_queue_binding() -> None:
    command = publication_command()
    incomplete = command.model_dump(mode="json")
    incomplete["release_manifest_id"] = str(h_uuid("manifest-id"))
    with pytest.raises(ValidationError, match="V2 publication binding"):
        PublicationCommand.model_validate(incomplete)

    complete = command.model_dump(mode="json")
    complete.update(
        release_manifest_id=str(h_uuid("manifest-id")),
        release_manifest_version=1,
        release_manifest_sha256=h("manifest-hash"),
        approved_metadata_version=1,
        approved_metadata_sha256=h("metadata-hash"),
        metadata_policy_id="approved-slot-metadata",
        metadata_policy_version=1,
        metadata_policy_sha256=h("policy-hash"),
    )
    complete["metadata"].update(
        cover_asset_id=str(h_uuid("cover-id")),
        cover_asset_version=1,
        cover_asset_sha256=h("cover-hash"),
    )
    assert PublicationCommand.model_validate(complete).release_manifest_version == 1


def test_v2_publication_allows_manifest_approved_absent_cover_and_cta() -> None:
    command = EXTRA_VALID["PublicationCommand__v2_no_cover_no_cta"]()
    assert isinstance(command, PublicationCommand)
    assert command.release_manifest_sha256 is not None
    assert command.metadata.cover_asset_id is None
    assert command.metadata.cover_asset_version is None
    assert command.metadata.cover_asset_sha256 is None
    assert command.metadata.cta_text is None

    partial = command.model_dump(mode="json")
    partial["metadata"]["cover_asset_id"] = str(h_uuid("partial-cover"))
    with pytest.raises(ValidationError, match="fully bound or explicitly absent"):
        PublicationCommand.model_validate(partial)


def test_creative_derivatives_are_package_hash_bound_without_changing_legacy_readback() -> None:
    legacy = release_package()
    legacy_payload = legacy.model_dump(mode="json")
    legacy_payload.pop("creative_derivatives")
    assert ReleasePackage.model_validate(legacy_payload).package_hash == legacy.package_hash

    package = release_package_with_derivatives()
    assert package.package_hash == package.compute_hash()
    assert {item.derivative_type for item in package.creative_derivatives or []} == {
        "POSTER",
        "EPISODE_ONE_PREVIEW",
    }
    assert all(
        item.asset_id not in {plan.asset_id for plan in package.release_scope}
        for item in package.creative_derivatives or []
    )
    changed_derivative = package.creative_derivatives[0].model_copy(
        update={"asset_sha256": h("changed-derivative")}
    )
    changed = package.model_copy(
        update={"creative_derivatives": [changed_derivative, package.creative_derivatives[1]]}
    )
    assert changed.compute_hash() != package.package_hash
    tampered = changed.model_dump(mode="python")
    tampered["package_hash"] = package.package_hash
    with pytest.raises(ValidationError, match="package_hash does not match"):
        ReleasePackage.model_validate(tampered)

    wrong_reveal = package.creative_derivatives[0].model_copy(update={"approved_reveal_episode": 2})
    wrong_reveal_package = package.model_copy(
        update={"creative_derivatives": [wrong_reveal, package.creative_derivatives[1]]}
    )
    wrong_reveal_payload = wrong_reveal_package.model_dump(mode="python")
    wrong_reveal_payload["package_hash"] = wrong_reveal_package.compute_hash()
    with pytest.raises(ValidationError, match="approved reveal episode 1"):
        ReleasePackage.model_validate(wrong_reveal_payload)


def test_derivative_requires_source_rights_and_text_boxes_inside_platform_safe_zone() -> None:
    payload = creative_derivative_ref().model_dump(mode="json")
    assert {source["role"] for source in payload["sources"]} == {"FOOTAGE", "AUDIO"}
    assert all(source["asset_version"] == 1 for source in payload["sources"])
    assert payload["duration_ms"] == 5_000
    assert payload["reveal_boundary_ms"] == 40_000
    assert payload["sources"][0]["source_in_ms"] == 30_000
    assert payload["sources"][0]["source_out_ms"] == 35_000
    missing_rights = json.loads(json.dumps(payload))
    missing_rights["sources"][0].pop("rights")
    with pytest.raises(ValidationError, match="rights"):
        CreativeDerivativeRef.model_validate(missing_rights)

    unsafe_layout = json.loads(json.dumps(payload))
    unsafe_layout["platform_safe_zones"][0]["cta_box"]["x_bp"] = 4000
    with pytest.raises(ValidationError, match="falls outside its platform safe zone"):
        CreativeDerivativeRef.model_validate(unsafe_layout)

    audio_only = json.loads(json.dumps(payload))
    audio_only["sources"][0]["role"] = "AUDIO"
    with pytest.raises(ValidationError, match="at least one footage source"):
        CreativeDerivativeRef.model_validate(audio_only)

    outside_footage = json.loads(json.dumps(payload))
    outside_footage["sources"][0]["source_out_ms"] = 41_000
    with pytest.raises(ValidationError, match="approved reveal cutoff"):
        CreativeDerivativeRef.model_validate(outside_footage)

    missing_manifest = json.loads(json.dumps(payload))
    missing_manifest.pop("derivation_manifest_sha256")
    with pytest.raises(ValidationError, match="derivation_manifest_sha256"):
        CreativeDerivativeRef.model_validate(missing_manifest)

    poster = EXTRA_VALID["CreativeDerivativeRef__poster"]()
    poster_payload = poster.model_dump(mode="json")
    assert poster_payload["approved_reveal_episode"] == 1
    assert poster_payload["readability_evidence_sha256"]
    assert poster_payload["reveal_boundary_ms"] is None
    poster_payload.pop("readability_evidence_sha256")
    with pytest.raises(ValidationError, match="readability evidence hash"):
        CreativeDerivativeRef.model_validate(poster_payload)


def test_gate2_manifest_and_live_projection_allow_explicitly_absent_cover_and_cta() -> None:
    manifest = v2_owner_approved_release_approval_manifest()
    slot = manifest.slots[0]
    no_cover = _reseal(
        slot,
        cover_asset_id=None,
        cover_asset_version=None,
        cover_asset_sha256=None,
        cover_rights=None,
        cta_text=None,
    )
    no_cover_manifest = _reseal(manifest, slots=[no_cover])
    assert _validate_slot(no_cover_manifest, no_cover) == no_cover
    with pytest.raises(ValueError, match="projection differs"):
        _validate_slot(
            no_cover_manifest,
            no_cover,
            cta_text="Unapproved CTA",
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("metadata_version", 2, "version/content"),
        ("metadata_sha256", "0" * 64, "version/content"),
        ("cover_asset_id", None, "cover"),
        ("cover_asset_version", 9, "projection"),
        ("cover_asset_sha256", "0" * 64, "projection"),
        ("cta_text", "Different CTA", "projection"),
        ("links", ["https://attacker.invalid/changed"], "projection"),
        ("disclosures", ["SYNTHETIC_VOICE"], "projection"),
        ("catalog_version", 2, "projection"),
    ],
)
def test_live_metadata_tampering_is_rejected(field, value, message) -> None:
    manifest = v2_owner_approved_release_approval_manifest()
    with pytest.raises(ValueError, match=message):
        _validate_slot(manifest, manifest.slots[0], **{field: value})
