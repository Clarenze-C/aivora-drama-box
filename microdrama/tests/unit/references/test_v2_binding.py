from __future__ import annotations

import pytest

from microdrama.contracts.enums import ControlKind
from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.examples import v2_prompt_manifest
from microdrama.contracts.v2 import PromptManifest, ReferenceRole
from microdrama.references.v2_binding import (
    ExpectedReference,
    dependent_shot_ids,
    invalidated_artifact_ids,
    preflight_prompt_manifest,
)
from microdrama.rendering.v2_preflight import validate_v2_prompt_preflight
from microdrama.rendering.workflows.templates import (
    MOCK_VIDEO_TEMPLATE,
    semantic_template_sha256,
    template_sha256,
)


def test_preflight_uses_exact_semantic_keys_and_current_rights():
    manifest = v2_prompt_manifest()
    manifest = PromptManifest.seal(
        **{
            **manifest.model_dump(mode="python", exclude={"content_sha256"}),
            "source_hashes": sorted(
                set(manifest.source_hashes) | {item.asset_sha256 for item in manifest.bindings}
            ),
        }
    )
    at = manifest.valid_from
    expected = {
        (binding.role, binding.subject_id): (
            binding.asset_id,
            binding.asset_version,
            binding.asset_sha256,
        )
        for binding in manifest.bindings
    }
    rows = {
        (
            binding.rights.rights_route_id,
            binding.rights.subject_kind,
            binding.rights.subject_ref,
        ): binding.rights
        for binding in manifest.bindings
    }

    def current(route, kind, subject):
        grant = rows.get((route, kind, subject))
        if grant is None:
            return None
        from uuid import uuid4

        from microdrama.contracts.enums import EvidenceSource, RightsStatus
        from microdrama.contracts.primitives import EvidenceRef
        from microdrama.contracts.registries import RightsRecord

        return RightsRecord(
            record_id=uuid4(),
            rights_route_id=grant.rights_route_id,
            version=grant.rights_version,
            subject_kind=grant.subject_kind,
            subject_ref=grant.subject_ref,
            territories=grant.territories,
            commercial_use=True,
            output_release_allowed=True,
            expires_at=grant.expires_at,
            evidence=[EvidenceRef(source=EvidenceSource.FAKE_FIXTURE, ref="fixture:rights")],
            status=RightsStatus.ELIGIBLE,
            recorded_at=at,
        )

    bindings = preflight_prompt_manifest(
        manifest,
        expected=expected,
        resolve_current_rights=current,
        at=at,
        territories=["TH"],
    )
    assert {(item.role, item.subject_id) for item in bindings} == set(expected)
    validate_v2_prompt_preflight(
        manifest,
        prompt_manifest_id=manifest.record_id,
        prompt_manifest_sha256=manifest.content_sha256,
        expected=expected,
        resolve_current_rights=current,
        at=at,
        territories=["TH"],
        template=MOCK_VIDEO_TEMPLATE,
        workflow_sha256=template_sha256(MOCK_VIDEO_TEMPLATE),
        semantic_workflow_sha256=semantic_template_sha256(MOCK_VIDEO_TEMPLATE),
        required_controls={
            ControlKind.CHARACTER_REFERENCE,
            ControlKind.WARDROBE_REFERENCE,
            ControlKind.LOCATION_REFERENCE,
        },
    )

    with pytest.raises(SchemaInvalid, match="pin the exact PromptManifest"):
        validate_v2_prompt_preflight(
            manifest,
            prompt_manifest_id=manifest.record_id,
            prompt_manifest_sha256="0" * 64,
            expected=expected,
            resolve_current_rights=current,
            at=at,
            territories=["TH"],
            template=MOCK_VIDEO_TEMPLATE,
            workflow_sha256=template_sha256(MOCK_VIDEO_TEMPLATE),
            semantic_workflow_sha256=semantic_template_sha256(MOCK_VIDEO_TEMPLATE),
            required_controls={ControlKind.CHARACTER_REFERENCE},
        )

    stale_expected = {
        key: ExpectedReference(
            asset_id=value[0],
            asset_version=value[1],
            asset_sha256=value[2],
            rights=manifest.bindings[index].rights,
            valid_from=at,
            valid_until=at,
        )
        for index, (key, value) in enumerate(expected.items())
    }
    with pytest.raises(SchemaInvalid, match="typed source asset is retired"):
        preflight_prompt_manifest(
            manifest,
            expected=stale_expected,
            resolve_current_rights=current,
            at=at,
            territories=["TH"],
        )

    with pytest.raises(SchemaInvalid, match="do not match"):
        preflight_prompt_manifest(
            manifest,
            expected={**expected, (ReferenceRole.PROP, "unrelated"): next(iter(expected.values()))},
            resolve_current_rights=current,
            at=at,
            territories=["TH"],
        )

    def revoked(*_args):
        record = current(*_args)
        from microdrama.contracts.enums import RightsStatus

        return record.model_copy(update={"status": RightsStatus.INELIGIBLE})

    with pytest.raises(SchemaInvalid, match="rights are not current"):
        preflight_prompt_manifest(
            manifest,
            expected=expected,
            resolve_current_rights=revoked,
            at=at,
            territories=["TH"],
        )

    def expired(*args):
        from datetime import UTC, datetime

        record = current(*args)
        return record.model_copy(update={"expires_at": datetime(2026, 10, 30, tzinfo=UTC)})

    with pytest.raises(SchemaInvalid, match="rights are not current"):
        preflight_prompt_manifest(
            manifest,
            expected=expected,
            resolve_current_rights=expired,
            at=at,
            territories=["TH"],
        )

    leaked = PromptManifest.seal(
        **{
            **manifest.model_dump(mode="python", exclude={"content_sha256"}),
            "prompt_text": manifest.prompt_text + " Lek co-signed the loan.",
        }
    )
    with pytest.raises(SchemaInvalid, match="forbidden unrevealed fact"):
        preflight_prompt_manifest(
            leaked,
            expected=expected,
            resolve_current_rights=current,
            at=at,
            territories=["TH"],
            forbidden_facts=("Lek co-signed the loan.",),
        )


def test_changed_source_invalidates_only_dependent_shots():
    assert dependent_shot_ids("outfit-hash", {"s1": {"outfit-hash"}, "s2": {"other"}}) == ("s1",)
    assert invalidated_artifact_ids(
        "outfit-hash",
        dependency_ids_by_source_hash={"outfit-hash": ["asset:outfit-v2"]},
        dependency_graph={
            "shot-a": ["asset:outfit-v2"],
            "prompt-a": ["shot-a"],
            "render-a": ["prompt-a"],
            "shot-b": ["asset:other"],
        },
    ) == ("prompt-a", "render-a", "shot-a")
