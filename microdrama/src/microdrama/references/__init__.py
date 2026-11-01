"""Image/voice generation, reuse and identity locks (T011).

Public surface:
- ``ReferencesService`` / ``build_references_service``: the paid
  ``references.prepare_episode`` step (anchors via the full-key cache, dialogue audio
  with measured actual durations, filled script/manifest versions) plus the
  identity-lock surface: ``identity_lock_hook`` (the ``ApprovalHook`` T008 calls
  inside the episode-one Gate 2 approval), ``attach_identity_lock``,
  ``render_request_bindings`` (the IMP-1 render gate for later episodes),
  ``mark_reviewed_in_package`` / ``cast_package_assets`` (packaging step inputs) and
  ``explicit_change`` (versions references; rides the ordinary final gate).
- ``IdentityLockHook`` / ``IdentityLocks``: lock creation and queries (append-only
  tables; an invalidated member breaks the lock and blocks later-episode renders).
- ``ReferencesConfig``: bounded knobs; missing prices block paid dispatch typed.
- Module-local payloads (models) are promotion candidates like the story lane's.
"""

from microdrama.references.anchors import (
    REFERENCES_NAMESPACE,
    face_key,
    location_key,
    style_key,
    voice_id_for,
    voice_key,
    wardrobe_key,
)
from microdrama.references.config import ReferencesConfig
from microdrama.references.generation import (
    IMAGE_OPERATION,
    VOICE_ANCHOR_OPERATION,
    VOICE_LINE_OPERATION,
)
from microdrama.references.identity_lock import IdentityLockHook, IdentityLocks
from microdrama.references.models import (
    AnchorSpec,
    AnchorView,
    ChangeOutcome,
    LineAudio,
    LockMember,
    LockView,
    PrepareOutcome,
    PrepareStatus,
    RefKind,
    RenderBindings,
)
from microdrama.references.service import ReferencesService, build_references_service
from microdrama.references.v2_binding import (
    ExpectedReference,
    compile_prompt_manifest,
    compose_prompt_text,
    dependent_shot_ids,
    invalidated_artifact_ids,
    preflight_prompt_manifest,
    resolve_shot_reference_expectations,
)
from microdrama.references.v2_planning import (
    AssetDemand,
    MockAsset,
    PersistedDemandAsset,
    PreparedReferenceSet,
    V2ReferenceRepository,
    assign_scene_wardrobes,
    demand_key,
    generate_offline_missing,
    make_offline_style_video,
    outfit_for_scene_time,
    plan_reference_demands,
    seal_reference_record,
    targeted_invalidation,
    validate_episode_reference_state,
    validate_pack_scope,
)

__all__ = [
    "IMAGE_OPERATION",
    "REFERENCES_NAMESPACE",
    "AnchorSpec",
    "AnchorView",
    "AssetDemand",
    "ChangeOutcome",
    "IdentityLockHook",
    "IdentityLocks",
    "LineAudio",
    "LockMember",
    "LockView",
    "MockAsset",
    "PersistedDemandAsset",
    "PrepareOutcome",
    "PreparedReferenceSet",
    "PrepareStatus",
    "RefKind",
    "ReferencesConfig",
    "ReferencesService",
    "RenderBindings",
    "V2ReferenceRepository",
    "VOICE_ANCHOR_OPERATION",
    "VOICE_LINE_OPERATION",
    "build_references_service",
    "assign_scene_wardrobes",
    "demand_key",
    "ExpectedReference",
    "compile_prompt_manifest",
    "compose_prompt_text",
    "dependent_shot_ids",
    "invalidated_artifact_ids",
    "face_key",
    "location_key",
    "generate_offline_missing",
    "make_offline_style_video",
    "outfit_for_scene_time",
    "plan_reference_demands",
    "preflight_prompt_manifest",
    "resolve_shot_reference_expectations",
    "seal_reference_record",
    "style_key",
    "targeted_invalidation",
    "validate_episode_reference_state",
    "validate_pack_scope",
    "voice_id_for",
    "voice_key",
    "wardrobe_key",
]
