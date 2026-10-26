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
from microdrama.contracts.release import (
    PostMetadata,
    PublicationCommand,
    ReleasePackage,
    ReleaseSlotPlan,
)
from microdrama.persistence.db import Tx

from .metadata import initial_metadata_version_id
from .service import command_id_for
from .slots import publish_client_token


def publication_command_for_post(
    tx: Tx,
    *,
    post: dict[str, Any],
    package_body: dict[str, Any],
    approval_event_id: UUID,
    metadata: PostMetadata | None = None,
) -> PublicationCommand:
    """The submit command for one scheduled post row (deterministic, idempotent).

    ``metadata`` defaults to the offline mock caption — the composed runtime's
    honest fake, labeled by the adapters' provenance at submit time.
    """
    del tx  # reads happen through the caller's transaction-free helpers today
    package = ReleasePackage.model_validate(package_body)
    plan = next(
        (
            ReleaseSlotPlan.model_validate(p)
            for p in package.release_scope
            if p["slot"]["release_slot"] == post["release_slot"]
        ),
        None,
    )
    if plan is None:
        raise LookupError(f"no slot plan for release_slot {post['release_slot']}")
    use_metadata = metadata or PostMetadata(
        locale="th-TH",
        title="ตอนที่ ๑ – หนี้เล็กๆ ของแม่ (จำลอง)",
        caption="ฤดูกาลนำร่อง (mock)",
        description="Pilot mock episode.",
        hashtags=["#thaidrama", "#shortseries"],
        disclosures=[DisclosureKind.AI_GENERATED_CONTENT],
        catalog_version=1,
    )
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
        metadata_version_id=initial_metadata_version_id(plan.slot.dedupe_key),
        schedule=plan.schedule,
        capability_id=plan.capability_id,
        capability_version=plan.capability_version,
        client_token=publish_client_token(plan.slot.dedupe_key, package.package_hash),
    )


__all__ = ["publication_command_for_post"]
