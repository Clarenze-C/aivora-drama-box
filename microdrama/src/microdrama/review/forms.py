"""Turn submitted review forms into contract values (identity comes from the session).

Gate 1/Gate 2 decisions become ``ApprovalCommand`` values; the owner Gate 2 metadata
form (T044b) becomes the sealed ``ApprovedMetadataPolicy`` and per-slot
``ApprovedSlotMetadata`` records ``ReviewService.prepare_release_approval_manifest``
persists. Every identity the owner must not choose — package id/hash, slot ids,
cover asset versions/hashes, catalog version, policy id/version — arrives in the
server-loaded :class:`Gate2MetadataForm` context; only editable values are read
from the posted fields, and anything the current rows do not back is rejected
before the service is called.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from microdrama.contracts.enums import (
    ApprovalAction,
    DisclosureKind,
    FeedbackCategory,
    FeedbackScope,
    GateType,
)
from microdrama.contracts.errors import GateNotReady, SchemaInvalid, StaleRevision
from microdrama.contracts.season import ApprovalCommand, TimecodedFeedback
from microdrama.contracts.v2 import ApprovedMetadataPolicy, ApprovedSlotMetadata, RightsGrant
from microdrama.review.service import parse_timecode

FEEDBACK_ROWS = 4
_NON_EMPTY = re.compile(r"\S")

# Owner-checkable "metadata may later change within policy" fields (the contract literal set).
POLICY_MUTABLE_FIELDS = ("title", "caption", "description", "hashtags", "cover", "cta")


def new_idempotency_key() -> str:
    return uuid.uuid4().hex


def _text(form: Mapping[str, Any], name: str) -> str:
    value = form.get(name)
    if not isinstance(value, str):
        raise SchemaInvalid(f"form field {name} is required")
    return value


def _optional(form: Mapping[str, Any], name: str) -> str | None:
    value = form.get(name)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def command_from_form(form: Any) -> ApprovalCommand:
    """Build the command a review form describes. Raises SchemaInvalid / pydantic errors."""
    try:
        gate = GateType(_text(form, "gate"))
        action = ApprovalAction(_text(form, "action"))
        entity_id = UUID(_text(form, "entity_id"))
        expected_revision = int(_text(form, "expected_revision"))
    except (ValueError, TypeError) as exc:
        raise SchemaInvalid("form values are malformed") from exc

    feedback: list[TimecodedFeedback] = []
    categories = form.getlist("feedback_category")
    starts = form.getlist("feedback_start")
    ends = form.getlist("feedback_end")
    comments = form.getlist("feedback_comment")
    for category, start, end, comment in zip(categories, starts, ends, comments, strict=False):
        if not (_NON_EMPTY.search(start) or _NON_EMPTY.search(end) or _NON_EMPTY.search(comment)):
            continue
        try:
            category_value = FeedbackCategory(category)
        except ValueError as exc:
            raise SchemaInvalid("unknown feedback category") from exc
        feedback.append(
            TimecodedFeedback(
                category=category_value,
                start_ms=parse_timecode(start),
                end_ms=parse_timecode(end),
                comment=comment.strip() or "-",
                scope=FeedbackScope.EPISODE,
            )
        )
    return ApprovalCommand(
        gate=gate,
        action=action,
        entity_id=entity_id,
        expected_revision=expected_revision,
        package_hash=_text(form, "package_hash"),
        release_manifest_hash=_optional(form, "release_manifest_hash"),
        media_hashes=[value for value in form.getlist("media_hash") if isinstance(value, str)],
        management_policy_hash=_optional(form, "management_policy_hash"),
        release_scope_hash=_optional(form, "release_scope_hash"),
        idempotency_key=_text(form, "idempotency_key"),
        feedback=feedback,
        reason=_optional(form, "reason"),
    )


@dataclass(frozen=True)
class Gate2CoverChoice:
    """One cover option: exact asset id/version/hash and rights loaded from current rows.

    ``rights`` is the grant the sealed metadata will bind; it is ``None`` when the
    rights registry cannot back this cover (not eligible, expired, ambiguous or
    missing route), in which case ``blocked_reason`` says why and the cover is not
    selectable — a submitted choice for it is rejected.
    """

    asset_id: UUID
    version: int
    sha256: str
    rights: RightsGrant | None = None
    blocked_reason: str | None = None


@dataclass(frozen=True)
class Gate2SlotForm:
    """One exact current release slot with the server-derived choices for its metadata."""

    slot_id: str
    platform: str
    account_ref: str
    slot_kind: str
    locale: str
    disclosures: tuple[str, ...]
    covers: tuple[Gate2CoverChoice, ...]
    next_metadata_version: int
    capability_blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class Gate2MetadataForm:
    """The owner Gate 2 metadata form state, loaded server-side from current rows.

    ``release_package_id``/``package_hash``/``policy_id``/``next_policy_version``/
    ``catalog_version`` are identities and versions the page binds and the POST
    re-checks; they are never taken from editable form fields. ``open`` is true
    exactly while the episode is at Gate 2 with a current undecided package.
    """

    episode_id: UUID
    release_package_id: UUID
    package_hash: str
    package_version: int
    slots: tuple[Gate2SlotForm, ...]
    catalog_version: int | None
    catalog_links: tuple[str, ...]
    policy_id: str
    next_policy_version: int
    open: bool
    blockers: tuple[str, ...]


def _required_short(form: Mapping[str, Any], name: str, *, label: str) -> str:
    value = _optional(form, name)
    if value is None:
        raise SchemaInvalid(f"{label} is required for every current release slot")
    if len(value) > 500:
        raise SchemaInvalid(f"{label} is longer than 500 characters")
    return value


def _bounded(form: Mapping[str, Any], name: str, limit: int) -> str:
    value = _optional(form, name)
    if value is None:
        return ""
    if len(value) > limit:
        raise SchemaInvalid(f"form field {name} is longer than {limit} characters")
    return value


def _int_field(form: Mapping[str, Any], name: str, *, minimum: int, maximum: int) -> int:
    raw = _text(form, name).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise SchemaInvalid(f"form field {name} must be a whole number") from exc
    if not minimum <= value <= maximum:
        raise SchemaInvalid(f"form field {name} must be between {minimum} and {maximum}")
    return value


def _hashtags(raw: Any) -> list[str]:
    if not isinstance(raw, str):
        return []
    tags = [tag for tag in re.split(r"[\s,]+", raw.strip()) if tag]
    if len(tags) > 30:
        raise SchemaInvalid("a release slot may carry at most 30 hashtags")
    for tag in tags:
        if len(tag) > 500:
            raise SchemaInvalid("a hashtag is longer than 500 characters")
    return tags


def _https_link(link: str) -> bool:
    """Absolute https with a bare host — the review module parses no URLs itself
    (the contracts layer owns URL provenance; this is the form's first gate)."""
    if not link.startswith("https://"):
        return False
    host = link[len("https://") :].split("/", 1)[0]
    return bool(host) and "@" not in host and "?" not in host and "#" not in host


def _links(raw: Any, allowed: Sequence[str]) -> list[str]:
    if not isinstance(raw, str):
        return []
    links = [link for link in re.split(r"\s+", raw.strip()) if link]
    for link in links:
        if not _https_link(link):
            raise SchemaInvalid("links must be absolute https URLs")
        if link not in allowed:
            raise SchemaInvalid(
                "a link is not one of the episode's current catalog URLs; "
                "links outside the catalog cannot be published"
            )
    return links


def _disclosures(values: Any, declared: Sequence[str]) -> list[DisclosureKind]:
    kinds: list[DisclosureKind] = []
    for value in values if isinstance(values, list) else []:
        try:
            kind = DisclosureKind(value)
        except ValueError as exc:
            raise SchemaInvalid(f"unknown disclosure {value!r}") from exc
        if kind in kinds:
            raise SchemaInvalid("a disclosure was submitted twice for one slot")
        kinds.append(kind)
    if sorted(kind.value for kind in kinds) != sorted(declared):
        raise SchemaInvalid(
            "slot disclosures must be exactly the package's declared set "
            f"({', '.join(sorted(declared))}); the owner confirms them, not changes them"
        )
    return kinds


def _cover(raw: Any, slot_form: Gate2SlotForm) -> tuple[UUID, int, str, RightsGrant]:
    """The chosen cover's exact binding, or the explicitly-absent cover (None ids).

    The posted value only *selects*; id, version, hash and rights all come from the
    server-loaded choice set, and a cover the rows do not back is rejected.
    """
    value = raw.strip() if isinstance(raw, str) else ""
    if not value:
        return None, None, None, None
    try:
        asset_id = UUID(value)
    except ValueError as exc:
        raise SchemaInvalid("the selected cover is not a valid asset id") from exc
    choice = next((c for c in slot_form.covers if c.asset_id == asset_id), None)
    if choice is None:
        raise SchemaInvalid("the selected cover is not one of the package's current covers")
    if choice.rights is None:
        raise SchemaInvalid(
            f"the selected cover cannot be used: {choice.blocked_reason or 'rights are not available'}"
        )
    return choice.asset_id, choice.version, choice.sha256, choice.rights


def _metadata_policy_from_form(
    form: Mapping[str, Any], meta: Gate2MetadataForm
) -> ApprovedMetadataPolicy:
    mutable: list[str] = []
    values = form.getlist("policy_mutable_fields")
    for value in values if isinstance(values, list) else []:
        if value not in POLICY_MUTABLE_FIELDS:
            raise SchemaInvalid(f"unknown metadata policy field {value!r}")
        if value not in mutable:
            mutable.append(value)
    return ApprovedMetadataPolicy.seal(
        policy_id=meta.policy_id,
        version=meta.next_policy_version,
        mutable_fields=sorted(mutable),
        cooldown_hours=_int_field(form, "policy_cooldown_hours", minimum=24, maximum=24 * 30),
        max_substantive_edits_first_7_days=_int_field(
            form, "policy_max_substantive_edits", minimum=0, maximum=2
        ),
    )


def _slot_metadata_from_form(
    form: Mapping[str, Any],
    slot_form: Gate2SlotForm,
    meta: Gate2MetadataForm,
    policy: ApprovedMetadataPolicy,
    *,
    new_id: Callable[[], UUID],
    now: datetime,
) -> ApprovedSlotMetadata:
    sid = slot_form.slot_id
    cover_id, cover_version, cover_sha, cover_rights = _cover(
        form.get(f"md_{sid}_cover"), slot_form
    )
    return ApprovedSlotMetadata.seal(
        record_id=new_id(),
        version=slot_form.next_metadata_version,
        created_at=now,
        updated_at=now,
        valid_from=now,
        release_package_id=meta.release_package_id,
        release_package_hash=meta.package_hash,
        slot_id=sid,
        metadata_id=new_id(),
        metadata_version=slot_form.next_metadata_version,
        locale=slot_form.locale,
        title=_required_short(form, f"md_{sid}_title", label="title"),
        caption=_bounded(form, f"md_{sid}_caption", 5000),
        description=_bounded(form, f"md_{sid}_description", 5000),
        hashtags=_hashtags(form.get(f"md_{sid}_hashtags")),
        links=_links(form.get(f"md_{sid}_links"), meta.catalog_links),
        disclosures=_disclosures(form.getlist(f"md_{sid}_disclosures"), slot_form.disclosures),
        catalog_version=meta.catalog_version,
        cover_asset_id=cover_id,
        cover_asset_version=cover_version,
        cover_asset_sha256=cover_sha,
        cover_rights=cover_rights,
        cta_text=_optional(form, f"md_{sid}_cta"),
        metadata_policy_id=policy.policy_id,
        metadata_policy_version=policy.version,
        metadata_policy_sha256=policy.policy_sha256,
        source="OWNER_APPROVED",
    )


def owner_metadata_from_form(
    form: Any,
    meta: Gate2MetadataForm,
    *,
    new_id: Callable[[], UUID],
    now: datetime,
) -> tuple[ApprovedMetadataPolicy, list[ApprovedSlotMetadata]]:
    """Build the exact owner metadata and policy a Gate 2 metadata form describes.

    The submitted form may only carry editable values and the package binding it
    was prepared against. Everything else — slot identities, cover bindings, the
    disclosures each route declared, the catalog version, the policy identity —
    comes from ``meta`` (loaded from current rows by the service). Missing,
    duplicated, foreign or stale slots, a stale package, covers/links/disclosures/
    policy the current rows do not allow, and malformed values are rejected here,
    before ``prepare_release_approval_manifest`` is called. Raises
    ``SchemaInvalid``/``StaleRevision``/``GateNotReady``/pydantic errors.
    """
    if not isinstance(meta, Gate2MetadataForm):
        raise SchemaInvalid("a server-prepared Gate 2 metadata context is required")
    if not meta.open:
        raise GateNotReady(
            "metadata can only be prepared while the episode is at Gate 2 with a "
            f"current undecided package ({'; '.join(meta.blockers) or 'gate closed'})"
        )
    posted_hash = _text(form, "package_hash")
    if posted_hash != meta.package_hash:
        raise StaleRevision(
            "the release package changed since this metadata form was prepared",
            current_package_hash=meta.package_hash,
        )
    posted_slots = [value for value in form.getlist("md_slot") if isinstance(value, str)]
    expected = {slot_form.slot_id for slot_form in meta.slots}
    if len(set(posted_slots)) != len(posted_slots):
        raise SchemaInvalid("a release slot's metadata was submitted more than once")
    foreign = [value for value in posted_slots if value not in expected]
    if foreign:
        raise SchemaInvalid(
            "metadata was submitted for a slot that is not in the current release package"
        )
    if set(posted_slots) != expected:
        raise SchemaInvalid("metadata is missing for at least one current release slot")
    capability = [
        f"{slot_form.platform}/{slot_form.account_ref}: {reason}"
        for slot_form in meta.slots
        for reason in slot_form.capability_blockers
    ]
    if capability:
        raise GateNotReady(
            "a release slot's capability binding is not usable for metadata: "
            + "; ".join(capability[:3])
        )
    policy = _metadata_policy_from_form(form, meta)
    slots = [
        _slot_metadata_from_form(form, slot_form, meta, policy, new_id=new_id, now=now)
        for slot_form in meta.slots
    ]
    return policy, slots


def validation_message(exc: ValidationError) -> str:
    """The first pydantic message only; input values are never echoed back into the page."""
    errors = exc.errors()
    return str(errors[0]["msg"]) if errors else "the decision is not valid"


__all__ = [
    "FEEDBACK_ROWS",
    "POLICY_MUTABLE_FIELDS",
    "Gate2CoverChoice",
    "Gate2MetadataForm",
    "Gate2SlotForm",
    "command_from_form",
    "new_idempotency_key",
    "owner_metadata_from_form",
    "validation_message",
]
