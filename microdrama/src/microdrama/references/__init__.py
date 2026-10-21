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

__all__ = [
    "IMAGE_OPERATION",
    "REFERENCES_NAMESPACE",
    "AnchorSpec",
    "AnchorView",
    "ChangeOutcome",
    "IdentityLockHook",
    "IdentityLocks",
    "LineAudio",
    "LockMember",
    "LockView",
    "PrepareOutcome",
    "PrepareStatus",
    "RefKind",
    "ReferencesConfig",
    "ReferencesService",
    "RenderBindings",
    "VOICE_ANCHOR_OPERATION",
    "VOICE_LINE_OPERATION",
    "build_references_service",
    "face_key",
    "location_key",
    "style_key",
    "voice_id_for",
    "voice_key",
    "wardrobe_key",
]
