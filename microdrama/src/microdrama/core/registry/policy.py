"""Accepted automation policy and directing playbook: imported as settings, never as readiness.

The policy files are INACTIVE_DESIGN_EXAMPLE documents (``runtime_enabled: false``, every
``setup_required_before_execution`` value null). Loading one maps its USD figures into contract
types exactly (integer micro-USD), refuses flipped safety flags, and lists what is still missing.
Importing a policy stores its bytes for audit; it does not make a rights route, an account
capability or a preset ready (SPEC: "import accepted policy as settings, not proof of provider
readiness").
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from microdrama.contracts.enums import BudgetCategory, ManagementActionKind, ShotPattern
from microdrama.contracts.errors import Conflict, NotFound, PolicyDenied, SchemaInvalid
from microdrama.contracts.primitives import (
    DEFAULT_LIMITS,
    EPISODE_CAP_MICRO_USD,
    ProductionLimits,
    Sha256Hex,
)
from microdrama.contracts.season import CostPolicy, ManagementPolicy, Shot
from microdrama.core.registry._common import deterministic_uuid
from microdrama.persistence.db import Tx

MAX_FINAL_EPISODE_SECONDS = 300

# Every setup item the accepted policy requires before execution. A missing or unknown name is
# refused, so readiness can never pass silently because an item was dropped from the file.
SETUP_KEYS: frozenset[str] = frozenset(
    {
        "approved_season_id",
        "approved_season_scope_sha256",
        "rights_route_id",
        "comfy_api_workflow_sha256",
        "model_and_node_version_registry",
        "voice_and_music_license_registry",
        "gpu_profile_and_actual_hourly_ceiling",
        "destination_account_capability_registry",
        "approved_schedule_windows",
        "credential_store_reference",
        "shared_research_spend_reservation",
        "management_policy_sha256",
    }
)

# JSON allocation key (policy v2) -> budget category. Every key must appear exactly once.
ALLOCATION_KEYS: Mapping[str, BudgetCategory] = {
    "research_script_prompts_metadata": BudgetCategory.RESEARCH_SCRIPT_PROMPTS_METADATA,
    "references_and_dialogue": BudgetCategory.REFERENCES_DIALOGUE,
    "gpu_generation_warmup_retries": BudgetCategory.GPU_GENERATION,
    "ai_qa_asr_captions": BudgetCategory.QA_CAPTIONS,
    "cpu_edit_storage_transfer": BudgetCategory.CPU_STORAGE_TRANSFER,
    "metered_post_management": BudgetCategory.METERED_MANAGEMENT,
    "uncommitted_recovery_and_billing_exposure_headroom": BudgetCategory.RECOVERY_HEADROOM,
}

FlagPath = tuple[str, ...]

# Safety flags the accepted policy fixes. A flipped value is refused (PolicyDenied).
_MUST_EQUAL: tuple[tuple[FlagPath, object], ...] = (
    (("budget_policy", "automatic_cap_increase"), False),
    (("budget_policy", "reserve_atomically_before_paid_dispatch"), True),
    (("budget_policy", "include_settled_accrued_inflight_and_exposure"), True),
    (("budget_policy", "failed_and_rejected_jobs_remain_chargeable"), True),
    (("budget_policy", "human_requested_revisions_use_same_episode_cap"), True),
    (("budget_policy", "unknown_price_action"), "BLOCK_PAID_DISPATCH"),
    (
        (
            "requirements_confirmed_by_user",
            "intermediate_script_prompt_reference_audio_edit_approvals",
        ),
        False,
    ),
    (("quality_policy", "human_approval_on_timeout"), False),
    (("quality_policy", "missing_critical_coverage_is_pass"), False),
    (("quality_policy", "writer_cannot_self_certify_final_footage"), True),
    (("quality_policy", "review_actual_final_media"), True),
    (("quality_policy", "critical_unresolved_defect"), "BLOCK_PUBLICATION"),
    (
        (
            "quality_policy",
            "observation_first_review",
            "cannot_treat_unsampled_interval_as_checked",
        ),
        True,
    ),
    (("approval_policy", "routine_manual_upload_fallback"), False),
    (("approval_policy", "unsupported_required_platform_capability"), "HOLD_DESTINATION"),
    (("proposed_community_policy", "cold_outbound_dm_campaigns"), False),
    (("proposed_community_policy", "remove_ordinary_criticism"), False),
    (("proposed_community_policy", "automatic_account_bans"), False),
    (
        (
            "proposed_community_policy",
            "automatic_contract_acceptance_sponsor_commitments_or_refunds",
        ),
        False,
    ),
    (("production_identity_policy", "render_later_episodes_before_first_lock"), False),
    (("production_identity_policy", "unseen_or_unreviewed_assets_already_locked"), False),
    (("hook_experiment_policy", "new_video_generation_for_hook_tests"), False),
    (("hook_experiment_policy", "release_all_candidates_without_eligible_slots"), False),
    (
        (
            "reliability_qualification_policy",
            "increase_unattended_production_volume_before_qualification",
        ),
        False,
    ),
    (("reliability_qualification_policy", "additional_human_approval_gate"), False),
)


class PolicySafetyFlags(BaseModel):
    """The boolean safety flags the accepted policy fixes. The Literal types make a flipped value
    unrepresentable, so a consumer can read these without re-checking the file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    human_approval_on_timeout: Literal[False] = False
    missing_critical_coverage_is_pass: Literal[False] = False
    automatic_cap_increase: Literal[False] = False
    review_actual_final_media: Literal[True] = True
    writer_cannot_self_certify_final_footage: Literal[True] = True
    cold_outbound_dm_campaigns: Literal[False] = False
    automatic_account_bans: Literal[False] = False
    remove_ordinary_criticism: Literal[False] = False


class AutomationPolicySettings(BaseModel):
    """Policy values mapped into contract types. Holds settings only: see ``readiness_blockers``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(min_length=1, max_length=200)
    document_kind: str = Field(min_length=1, max_length=200)
    runtime_enabled: bool
    source_sha256: Sha256Hex
    cost_policy: CostPolicy
    limits: ProductionLimits
    management_defaults: ManagementPolicy
    safety: PolicySafetyFlags
    setup_required_before_execution: dict[str, str | None]

    def readiness_blockers(self) -> list[str]:
        """Everything that still prevents execution. Importing the policy never clears these."""
        blockers: list[str] = []
        if not self.runtime_enabled:
            blockers.append("policy:runtime_enabled is false")
        for key in sorted(self.setup_required_before_execution):
            value = self.setup_required_before_execution[key]
            if value is None or not value.strip():
                blockers.append(f"setup:{key} missing")
        return blockers


class PlaybookLimits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    active_locations_per_episode: int = Field(ge=1)
    featured_speaking_characters_per_episode: int = Field(ge=1)
    speakers_per_shot: int = Field(ge=1)


class DirectingPlaybook(BaseModel):
    """Directing playbook settings: the six shot patterns and the required shot fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(min_length=1, max_length=200)
    runtime_enabled: bool
    source_sha256: Sha256Hex
    limits: PlaybookLimits
    pattern_ids: frozenset[ShotPattern]
    required_shot_fields: tuple[str, ...]


# --- JSON reading -------------------------------------------------------------------


def _reject_constant(name: str) -> None:
    raise ValueError(f"non-finite JSON number {name} is not allowed")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key in policy document")
        out[key] = value
    return out


def _read(path: Path | str) -> tuple[dict[str, Any], bytes]:
    target = Path(path)
    try:
        raw = target.read_bytes()
    except OSError:
        raise NotFound(f"policy document not found: {target.name}") from None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise SchemaInvalid("policy document is not UTF-8") from None
    try:
        # parse_float=Decimal keeps every JSON fraction exact; a binary float would silently
        # round an amount such as 2.0000000000000001 to 2.0. Integers stay int.
        doc = json.loads(
            text,
            parse_constant=_reject_constant,
            object_pairs_hook=_no_duplicate_keys,
            parse_float=Decimal,
        )
    except ValueError:
        raise SchemaInvalid("policy document is not valid JSON") from None
    if not isinstance(doc, dict):
        raise SchemaInvalid("policy document must be a JSON object")
    return doc, raw


_MAX_MICRO_SHIFT = 40  # 10**40 micro-USD is far beyond any amount; refuse before big maths


def usd_to_micro(value: int | Decimal, *, what: str) -> int:
    """Exact conversion of a USD amount (``int`` or ``Decimal``) to integer micro-USD.

    The arithmetic is done on the decimal digits as Python integers, so no context precision
    can round an amount: ``Decimal("1.005")`` gives 1_005_000 and
    ``Decimal("2.00000000000000000000000000000001")`` is refused. A binary ``float`` is refused
    because it has already lost the digits the file wrote.
    """
    if isinstance(value, bool) or not isinstance(value, int | Decimal):
        raise SchemaInvalid(f"{what} must be an exact JSON number (not a binary float)")
    amount = Decimal(value)
    if not amount.is_finite():
        raise SchemaInvalid(f"{what} is not a finite amount")
    sign, digits, exponent = amount.as_tuple()
    mantissa = int("".join(str(digit) for digit in digits))
    if mantissa == 0:
        return 0
    # value * 10**6 == mantissa * 10**(exponent + 6), an exact integer expression.
    shift = exponent + 6
    if shift > _MAX_MICRO_SHIFT:
        raise SchemaInvalid(f"{what} is out of range")
    if shift >= 0:
        micro = mantissa * 10**shift
    else:
        # More fractional micro-digits than the mantissa has digits: never a whole number.
        if -shift > len(digits) or mantissa % 10**-shift:
            raise SchemaInvalid(f"{what} is not a whole number of micro-USD")
        micro = mantissa // 10**-shift
    return -micro if sign else micro


def _get(doc: Mapping[str, Any], path: FlagPath) -> Any:
    node: Any = doc
    for key in path:
        if not isinstance(node, Mapping) or key not in node:
            raise SchemaInvalid(f"policy is missing {'.'.join(path)}")
        node = node[key]
    return node


def _int(doc: Mapping[str, Any], path: FlagPath) -> int:
    value = _get(doc, path)
    if type(value) is not int:  # bool is refused here too
        raise SchemaInvalid(f"{'.'.join(path)} must be an integer")
    return value


def _str(doc: Mapping[str, Any], path: FlagPath) -> str:
    value = _get(doc, path)
    if not isinstance(value, str) or not value:
        raise SchemaInvalid(f"{'.'.join(path)} must be a non-empty string")
    return value


def _bool(doc: Mapping[str, Any], path: FlagPath) -> bool:
    value = _get(doc, path)
    if type(value) is not bool:
        raise SchemaInvalid(f"{'.'.join(path)} must be a boolean")
    return value


# --- safety -------------------------------------------------------------------------


def _same(actual: object, expected: object) -> bool:
    if isinstance(expected, bool):
        return actual is expected
    return type(actual) is type(expected) and actual == expected


def _check_safety(doc: Mapping[str, Any]) -> None:
    for path, expected in _MUST_EQUAL:
        if not _same(_get(doc, path), expected):
            raise PolicyDenied(f"policy safety flag {'.'.join(path)} must be {expected!r}")
    paid = usd_to_micro(
        _get(doc, ("budget_policy", "paid_advertising_budget_usd")),
        what="paid_advertising_budget_usd",
    )
    if paid != 0:
        raise PolicyDenied("MD-018: the initial paid-advertising budget must be zero")
    cap = usd_to_micro(
        _get(doc, ("requirements_confirmed_by_user", "variable_cost_limit_usd_per_episode")),
        what="variable_cost_limit_usd_per_episode",
    )
    if cap > EPISODE_CAP_MICRO_USD:
        raise PolicyDenied("variable cost limit per episode may not exceed US$10")
    seconds = _int(
        doc, ("requirements_confirmed_by_user", "maximum_final_episode_duration_seconds")
    )
    if seconds > MAX_FINAL_EPISODE_SECONDS:
        raise PolicyDenied("MD-002: final episodes may not exceed 300 seconds")


# --- mapping ------------------------------------------------------------------------


def _cost_policy(doc: Mapping[str, Any]) -> CostPolicy:
    allocation_doc = _get(doc, ("proposed_budget_allocation_usd",))
    if not isinstance(allocation_doc, Mapping):
        raise SchemaInvalid("proposed_budget_allocation_usd must be an object")
    unknown = sorted(set(allocation_doc) - set(ALLOCATION_KEYS))
    missing = sorted(set(ALLOCATION_KEYS) - set(allocation_doc))
    if unknown or missing:
        raise SchemaInvalid("proposed_budget_allocation_usd must name every category exactly once")
    allocation = {
        ALLOCATION_KEYS[key]: usd_to_micro(allocation_doc[key], what=f"allocation {key}")
        for key in ALLOCATION_KEYS
    }
    cap = usd_to_micro(
        _get(doc, ("requirements_confirmed_by_user", "variable_cost_limit_usd_per_episode")),
        what="variable_cost_limit_usd_per_episode",
    )
    try:
        return CostPolicy(
            episode_cap_micro_usd=cap,
            allocation_micro_usd=allocation,
            max_attempts_per_shot=_int(
                doc, ("proposed_retry_settings", "maximum_total_attempts_per_shot")
            ),
            max_final_repair_rounds=_int(
                doc, ("proposed_retry_settings", "maximum_automated_final_qa_repair_rounds")
            ),
            max_transport_attempts=_int(
                doc, ("proposed_retry_settings", "maximum_transient_transport_attempts")
            ),
            paid_advertising_budget_micro_usd=0,
            automatic_cap_increase=False,
        )
    except ValidationError:
        raise SchemaInvalid("policy cost settings violate the contract bounds") from None


def _limits(doc: Mapping[str, Any]) -> ProductionLimits:
    qualification = _int(
        doc, ("reliability_qualification_policy", "consecutive_qualifying_episodes_required")
    )
    window = _int(doc, ("reliability_qualification_policy", "initial_management_window_days"))
    if qualification != DEFAULT_LIMITS.qualification_streak_required:
        raise SchemaInvalid("consecutive qualifying episodes must be 10 in this contract")
    if window != DEFAULT_LIMITS.management_window_days:
        raise SchemaInvalid("initial management window must be 7 days in this contract")
    try:
        return ProductionLimits(
            max_attempts_per_shot=_int(
                doc, ("proposed_retry_settings", "maximum_total_attempts_per_shot")
            ),
            max_final_repair_rounds=_int(
                doc, ("proposed_retry_settings", "maximum_automated_final_qa_repair_rounds")
            ),
            max_transport_attempts=_int(
                doc, ("proposed_retry_settings", "maximum_transient_transport_attempts")
            ),
            max_active_locations=_int(
                doc, ("directing_playbook_policy", "proposed_maximum_active_locations_per_episode")
            ),
            max_featured_speaking_characters=_int(
                doc,
                (
                    "directing_playbook_policy",
                    "proposed_maximum_featured_speaking_characters_per_episode",
                ),
            ),
            max_speakers_per_shot=_int(
                doc, ("directing_playbook_policy", "proposed_maximum_speakers_per_shot")
            ),
            episode_max_duration_ms=_int(
                doc, ("requirements_confirmed_by_user", "maximum_final_episode_duration_seconds")
            )
            * 1000,
            metadata_cooldown_hours=_int(
                doc, ("proposed_community_policy", "metadata_optimization_cooldown_hours")
            ),
            max_substantive_metadata_edits_first_7_days=_int(
                doc,
                (
                    "proposed_community_policy",
                    "maximum_substantive_metadata_optimizations_per_post_first_7_days",
                ),
            ),
        )
    except ValidationError:
        raise SchemaInvalid("policy production limits violate the contract bounds") from None


def _management(doc: Mapping[str, Any]) -> ManagementPolicy:
    social_doc = _get(doc, ("requirements_confirmed_by_user", "social_management"))
    if not isinstance(social_doc, list) or not all(isinstance(item, str) for item in social_doc):
        raise SchemaInvalid("social_management must be a list of names")
    social = set(social_doc)
    moderate = _bool(
        doc, ("proposed_community_policy", "moderate_clear_spam_scams_threats_where_supported")
    )
    replies = _bool(
        doc, ("proposed_community_policy", "routine_replies_grounded_in_released_catalog")
    )
    actions: set[ManagementActionKind] = {ManagementActionKind.NO_ACTION}
    if "titles_captions_descriptions" in social:
        actions |= {
            ManagementActionKind.TITLE_EDIT,
            ManagementActionKind.CAPTION_EDIT,
            ManagementActionKind.DESCRIPTION_EDIT,
        }
    if "keyword_hashtag_optimization" in social:
        actions.add(ManagementActionKind.HASHTAG_EDIT)
    if "covers_thumbnails" in social:
        actions.add(ManagementActionKind.COVER_CHANGE)
    if "link_and_catalog_maintenance" in social:
        actions.add(ManagementActionKind.LINK_UPDATE)
    if "public_comment_replies" in social and replies:
        actions.add(ManagementActionKind.PUBLIC_REPLY)
    if "permitted_keyword_and_inbound_dms" in social:
        actions.add(ManagementActionKind.DM_SEND)
    if "comment_moderation" in social and moderate:
        actions |= {
            ManagementActionKind.MODERATE_HIDE,
            ManagementActionKind.MODERATE_DELETE,
            ManagementActionKind.MODERATE_REPORT,
        }
    try:
        return ManagementPolicy(
            allowed_actions=frozenset(actions),
            metadata_cooldown_hours=_int(
                doc, ("proposed_community_policy", "metadata_optimization_cooldown_hours")
            ),
            max_substantive_edits_first_7_days=_int(
                doc,
                (
                    "proposed_community_policy",
                    "maximum_substantive_metadata_optimizations_per_post_first_7_days",
                ),
            ),
            automatic_account_bans=False,
            remove_ordinary_criticism=False,
            cold_outbound_dms=False,
            accept_contracts_sponsors_refunds=False,
        )
    except ValidationError:
        raise SchemaInvalid("policy management settings violate the contract bounds") from None


def _setup(doc: Mapping[str, Any]) -> dict[str, str | None]:
    raw = _get(doc, ("setup_required_before_execution",))
    if not isinstance(raw, Mapping):
        raise SchemaInvalid("setup_required_before_execution must be an object")
    if set(raw) != SETUP_KEYS:
        raise SchemaInvalid("setup_required_before_execution must name exactly the policy's items")
    setup: dict[str, str | None] = {}
    for key, value in raw.items():
        if value is not None and not isinstance(value, str):
            raise SchemaInvalid(f"setup item {key} must be a string or null")
        setup[str(key)] = value
    return setup


def _load(path: Path | str) -> tuple[AutomationPolicySettings, bytes]:
    doc, raw = _read(path)
    _check_safety(doc)
    try:
        settings = AutomationPolicySettings(
            version=_str(doc, ("version",)),
            document_kind=_str(doc, ("document_kind",)),
            runtime_enabled=_bool(doc, ("runtime_enabled",)),
            source_sha256=hashlib.sha256(raw).hexdigest(),
            cost_policy=_cost_policy(doc),
            limits=_limits(doc),
            management_defaults=_management(doc),
            safety=PolicySafetyFlags(
                human_approval_on_timeout=_bool(
                    doc, ("quality_policy", "human_approval_on_timeout")
                ),
                missing_critical_coverage_is_pass=_bool(
                    doc, ("quality_policy", "missing_critical_coverage_is_pass")
                ),
                automatic_cap_increase=_bool(doc, ("budget_policy", "automatic_cap_increase")),
                review_actual_final_media=_bool(
                    doc, ("quality_policy", "review_actual_final_media")
                ),
                writer_cannot_self_certify_final_footage=_bool(
                    doc, ("quality_policy", "writer_cannot_self_certify_final_footage")
                ),
                cold_outbound_dm_campaigns=_bool(
                    doc, ("proposed_community_policy", "cold_outbound_dm_campaigns")
                ),
                automatic_account_bans=_bool(
                    doc, ("proposed_community_policy", "automatic_account_bans")
                ),
                remove_ordinary_criticism=_bool(
                    doc, ("proposed_community_policy", "remove_ordinary_criticism")
                ),
            ),
            setup_required_before_execution=_setup(doc),
        )
    except ValidationError:
        raise SchemaInvalid("policy safety flags are not in their accepted state") from None
    return settings, raw


def load_automation_policy(path: Path | str) -> AutomationPolicySettings:
    """Map policy v2 into contract settings. Refuses flipped safety flags and inexact money."""
    settings, _ = _load(path)
    return settings


def load_directing_playbook(path: Path | str) -> DirectingPlaybook:
    """Validate the six shot patterns against ``ShotPattern`` and the required shot fields."""
    doc, raw = _read(path)
    patterns_doc = _get(doc, ("patterns",))
    if not isinstance(patterns_doc, list):
        raise SchemaInvalid("playbook patterns must be a list")
    ids = [pattern.get("id") if isinstance(pattern, Mapping) else None for pattern in patterns_doc]
    if not all(isinstance(value, str) for value in ids) or len(set(ids)) != len(ids):
        raise SchemaInvalid("playbook pattern ids must be present and unique")
    try:
        pattern_ids = frozenset(ShotPattern(value) for value in ids)
    except ValueError:
        raise SchemaInvalid("playbook names a pattern unknown to the contract") from None
    if pattern_ids != frozenset(ShotPattern):
        raise SchemaInvalid("playbook patterns must equal the contract's six ShotPattern values")

    limits_doc = _get(doc, ("limits",))
    if not isinstance(limits_doc, Mapping):
        raise SchemaInvalid("playbook limits must be an object")
    limits = PlaybookLimits(
        active_locations_per_episode=_int(doc, ("limits", "active_locations_per_episode")),
        featured_speaking_characters_per_episode=_int(
            doc, ("limits", "featured_speaking_characters_per_episode")
        ),
        speakers_per_shot=_int(doc, ("limits", "speakers_per_shot")),
    )
    if (
        limits.active_locations_per_episode > DEFAULT_LIMITS.max_active_locations
        or limits.featured_speaking_characters_per_episode
        > DEFAULT_LIMITS.max_featured_speaking_characters
        or limits.speakers_per_shot > DEFAULT_LIMITS.max_speakers_per_shot
    ):
        raise SchemaInvalid("playbook limits exceed the contract's hard limits")

    fields = _get(doc, ("required_shot_fields",))
    if not isinstance(fields, list) or not all(isinstance(name, str) for name in fields):
        raise SchemaInvalid("required_shot_fields must be a list of field names")
    unknown = sorted(set(fields) - set(Shot.model_fields))
    if unknown:
        raise SchemaInvalid("required_shot_fields names fields the Shot contract does not have")

    return DirectingPlaybook(
        version=_str(doc, ("version",)),
        runtime_enabled=_bool(doc, ("runtime_enabled",)),
        source_sha256=hashlib.sha256(raw).hexdigest(),
        limits=limits,
        pattern_ids=pattern_ids,
        required_shot_fields=tuple(fields),
    )


def import_policy(tx: Tx, path: Path | str) -> UUID:
    """Store the policy document in ``policy_versions`` and return its row id.

    The original bytes are kept as JSON text (``body``) and hashed as raw bytes (``body_hash``).
    Idempotent on ``version``: the same bytes return the existing row; different bytes under the
    same version are refused, because a policy version is immutable.
    """
    settings, raw = _load(path)
    body_hash = hashlib.sha256(raw).hexdigest()
    existing = tx.fetchone(
        "SELECT id, body_hash FROM policy_versions WHERE version = %s", (settings.version,)
    )
    if existing is not None:
        if existing["body_hash"] != body_hash:
            raise Conflict(
                f"policy version {settings.version} is already imported with different content",
                version=settings.version,
            )
        return existing["id"]
    policy_row_id = deterministic_uuid("policy", settings.version, body_hash)
    tx.execute(
        "INSERT INTO policy_versions (id, version, document_kind, body, body_hash) "
        "VALUES (%s, %s, %s, %s::jsonb, %s)",
        (policy_row_id, settings.version, settings.document_kind, raw.decode("utf-8"), body_hash),
    )
    return policy_row_id


__all__ = [
    "ALLOCATION_KEYS",
    "AutomationPolicySettings",
    "DirectingPlaybook",
    "PlaybookLimits",
    "PolicySafetyFlags",
    "import_policy",
    "load_automation_policy",
    "load_directing_playbook",
    "usd_to_micro",
]
