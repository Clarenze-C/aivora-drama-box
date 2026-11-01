"""Publication command construction from durable slot state (build-review F01).

The single builder every submitter uses — the runner and the scheduler both
derive the ``PublicationCommand`` from the post row and its approved package,
never from in-memory demo constants, so a scheduler-driven release submits
exactly what Gate 2 approved.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from microdrama.contracts.enums import DisclosureKind
from microdrama.contracts.errors import Conflict
from microdrama.contracts.release import (
    PostMetadata,
    PublicationCommand,
    ReleasePackage,
)
from microdrama.contracts.v2 import (
    ApprovedSlotMetadata,
    ReleaseApprovalManifest,
    validate_live_release_metadata,
)
from microdrama.persistence.db import Tx

from .metadata import has_mock_label, initial_metadata_version_id
from .service import command_id_for
from .slots import publish_client_token


def publication_command_for_post(
    tx: Tx,
    *,
    post: dict[str, Any],
    package_body: dict[str, Any],
    approval_event_id: UUID,
    metadata: PostMetadata | None = None,
    metadata_version_id: UUID | None = None,
    allow_mock_metadata: bool = False,
    release_manifest: ReleaseApprovalManifest | None = None,
    approved_slot_metadata: ApprovedSlotMetadata | None = None,
) -> PublicationCommand:
    """The submit command for one scheduled post row (deterministic, idempotent).

    Callers must supply the current persisted metadata for rearmed submissions.
    Synthetic first-submit metadata is available only when the caller explicitly
    identifies the OFFLINE_MOCK path. Live callers fail closed until approved
    metadata is represented in the release contract.
    """
    del tx  # reads happen through the caller's transaction-free helpers today
    package = ReleasePackage.model_validate(package_body)
    # release_scope entries are already ReleaseSlotPlan models after validation.
    # The plan is resolved by dedupe key, never by slot name: release_slot
    # names repeat across platforms/accounts inside one scope, and a
    # name-matched command would submit some OTHER slot's post (its dedupe
    # key locks that row) while this slot waited forever.
    plan = next(
        (
            candidate
            for candidate in package.release_scope
            if candidate.slot.dedupe_key == post["dedupe_key"]
        ),
        None,
    )
    if plan is None:
        raise LookupError(
            f"no slot plan for dedupe key {post['dedupe_key']} "
            f"(release_slot {post['release_slot']})"
        )
    if not allow_mock_metadata and (
        release_manifest is not None or approved_slot_metadata is not None
    ):
        if release_manifest is None or approved_slot_metadata is None:
            raise Conflict(
                "V2 Gate 2 manifest and canonical slot metadata must be supplied together"
            )
    if metadata is None and approved_slot_metadata is not None and not allow_mock_metadata:
        # A first submit has no legacy metadata_versions row yet. Project the exact
        # immutable Gate2 record and let PublishingService create/check its deterministic
        # initial version inside the durable intent transaction before transport.
        use_metadata = PostMetadata(
            locale=approved_slot_metadata.locale,
            title=approved_slot_metadata.title,
            caption=approved_slot_metadata.caption,
            description=approved_slot_metadata.description,
            hashtags=approved_slot_metadata.hashtags,
            links=approved_slot_metadata.links,
            disclosures=approved_slot_metadata.disclosures,
            catalog_version=approved_slot_metadata.catalog_version,
            cover_asset_id=approved_slot_metadata.cover_asset_id,
            cover_asset_version=approved_slot_metadata.cover_asset_version,
            cover_asset_sha256=approved_slot_metadata.cover_asset_sha256,
            cta_text=approved_slot_metadata.cta_text,
        )
    elif metadata is not None:
        use_metadata = metadata
    elif allow_mock_metadata:
        use_metadata = PostMetadata(
            locale="th-TH",
            title="ตอนที่ ๑ – หนี้เล็กๆ ของแม่ (จำลอง)",
            caption="ฤดูกาลนำร่อง (mock)",
            description="Pilot mock episode.",
            hashtags=["#thaidrama", "#shortseries"],
            disclosures=[DisclosureKind.AI_GENERATED_CONTENT],
            catalog_version=1,
        )
    else:
        raise Conflict("approved slot metadata is missing; refusing to build a publication command")
    if not allow_mock_metadata and has_mock_label(use_metadata):
        raise Conflict("mock-labeled publication metadata is forbidden outside OFFLINE_MOCK")
    binding: dict[str, Any] = {}
    if (
        not allow_mock_metadata
        and release_manifest is not None
        and approved_slot_metadata is not None
    ):
        try:
            approved = validate_live_release_metadata(
                release_manifest,
                slot_id=f"slot-{plan.slot.dedupe_key}",
                metadata_id=approved_slot_metadata.metadata_id,
                metadata_version=approved_slot_metadata.metadata_version,
                metadata_sha256=approved_slot_metadata.content_sha256,
                metadata_projection=use_metadata,
            )
        except ValueError as exc:
            raise Conflict(f"approved live metadata does not match Gate 2: {exc}") from exc
        if approved != approved_slot_metadata:
            raise Conflict("slot metadata does not match the manifest record")
        binding = {
            "release_manifest_id": release_manifest.manifest_id,
            "release_manifest_version": release_manifest.version,
            "release_manifest_sha256": release_manifest.approval_manifest_sha256,
            "approved_metadata_version": approved_slot_metadata.metadata_version,
            "approved_metadata_sha256": approved_slot_metadata.content_sha256,
            "metadata_policy_id": release_manifest.metadata_policy.policy_id,
            "metadata_policy_version": release_manifest.metadata_policy.version,
            "metadata_policy_sha256": release_manifest.metadata_policy.policy_sha256,
        }
    return PublicationCommand(
        command_id=command_id_for(plan.slot.dedupe_key),
        release_package_id=package.package_id,
        release_package_hash=package.package_hash,
        approval_event_id=approval_event_id,
        slot=plan.slot,
        slot_kind=plan.slot_kind,
        asset_id=plan.asset_id,
        asset_sha256=plan.asset_sha256,
        metadata=use_metadata,
        metadata_version_id=metadata_version_id
        or initial_metadata_version_id(plan.slot.dedupe_key),
        schedule=plan.schedule,
        capability_id=plan.capability_id,
        capability_version=plan.capability_version,
        client_token=publish_client_token(plan.slot.dedupe_key, package.package_hash),
        **binding,
    )


__all__ = ["publication_command_for_post"]
