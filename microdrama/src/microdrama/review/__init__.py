"""Gate APIs/UI and scoped feedback/preference memory (T008: the two human approval gates).

Public surface:
- ``ReviewService``: Gate 1 (season concept) and Gate 2 (episode final) decisions and review views.
- ``build_router``: JSON gate routes, ``/ui`` review pages, owner-only media stream, ``/auth`` pages.
- ``gate2_blockers``: every reason Gate 2 APPROVE is disabled (empty list = enabled).
- ``store_release_package`` / ``current_package`` / ``PackageStatus``: release package storage used
  by the packaging step; the status machine itself is enforced by the database.
"""

from microdrama.review.api import build_router
from microdrama.review.gate_conditions import gate2_blockers, not_configured_release_conditions
from microdrama.review.packages import PackageStatus, current_package, store_release_package
from microdrama.review.service import ReviewService

__all__ = [
    "PackageStatus",
    "ReviewService",
    "build_router",
    "current_package",
    "gate2_blockers",
    "not_configured_release_conditions",
    "store_release_package",
]
