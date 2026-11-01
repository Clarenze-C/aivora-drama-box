"""Gate APIs/UI and scoped feedback/preference memory (T008: the two human approval gates).

Public surface:
- ``ReviewService``: owner-scoped Gate 1 (season concept) and Gate 2 (episode final)
  decisions, review views and progress projections (T044a).
- ``build_router``: JSON gate routes, ``/ui`` review pages, owner-only media stream,
  owner-scoped progress routes and ``/auth`` pages.
- ``gate2_blockers``: every reason Gate 2 APPROVE is disabled (empty list = enabled).
- ``store_release_package`` / ``current_package`` / ``PackageStatus``: release package storage used
  by the packaging step; the status machine itself is enforced by the database.
- ``scope``: the season-to-owner relation helpers every review read is limited by.
- ``progress``: the read-only durable progress projection (no second store).
- ``intake``/``IntakeService``: the three-step owner Script Maker intake, candidate
  selection and the workbench V2 document projections (T044b2).
"""

from microdrama.review import intake, progress, scope
from microdrama.review.api import build_router
from microdrama.review.gate_conditions import gate2_blockers, not_configured_release_conditions
from microdrama.review.intake import IntakeConfig, IntakeService
from microdrama.review.packages import PackageStatus, current_package, store_release_package
from microdrama.review.progress import (
    EpisodeProgressView,
    ProgressProjection,
    SeasonProgressView,
)
from microdrama.review.service import ReviewService

__all__ = [
    "EpisodeProgressView",
    "IntakeConfig",
    "IntakeService",
    "PackageStatus",
    "ProgressProjection",
    "ReviewService",
    "SeasonProgressView",
    "build_router",
    "current_package",
    "gate2_blockers",
    "intake",
    "not_configured_release_conditions",
    "progress",
    "scope",
    "store_release_package",
]
