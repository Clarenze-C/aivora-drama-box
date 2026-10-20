"""Turn submitted review forms into ``ApprovalCommand`` values (identity comes from the session)."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from microdrama.contracts.enums import ApprovalAction, FeedbackCategory, FeedbackScope, GateType
from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.season import ApprovalCommand, TimecodedFeedback
from microdrama.review.service import parse_timecode

FEEDBACK_ROWS = 4
_NON_EMPTY = re.compile(r"\S")


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
        media_hashes=[value for value in form.getlist("media_hash") if isinstance(value, str)],
        management_policy_hash=_optional(form, "management_policy_hash"),
        release_scope_hash=_optional(form, "release_scope_hash"),
        idempotency_key=_text(form, "idempotency_key"),
        feedback=feedback,
        reason=_optional(form, "reason"),
    )


def validation_message(exc: ValidationError) -> str:
    """The first pydantic message only; input values are never echoed back into the page."""
    errors = exc.errors()
    return str(errors[0]["msg"]) if errors else "the decision is not valid"


__all__ = [
    "FEEDBACK_ROWS",
    "command_from_form",
    "new_idempotency_key",
    "validation_message",
]
