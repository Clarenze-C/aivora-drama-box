"""Community management (T025): metadata/replies/moderation and action policy.

OFFLINE_MOCK only: the factory refuses every other execution mode, and the live
route is the named ``PolicyDenied`` refusal ``LiveCommunityProvider`` until the
controlled account tests of T032 qualify one. The lane exports factories; the
integrator registers jobs/routes (no self-registration here).

The ``community/dm/`` subpackage is T026's membership lane and does not exist
yet; ``CommunityService.execute_action`` is the seam it will call for handed-in
DM_SEND actions (strict messaging-window and conversation-cap checks inside).
"""

from __future__ import annotations

from microdrama.community.classification import (
    Classification,
    CommentClass,
    classify_comment,
)
from microdrama.community.grounding import (
    GroundingFacts,
    load_facts,
    thai_date,
    validate_claims,
)
from microdrama.community.metadata_worker import (
    cover_assets_for_post,
    propose_cover_change,
    propose_hashtag_optimization,
)
from microdrama.community.policy import (
    CONFIDENCE_GATED_KINDS,
    DESTRUCTIVE_MIN_CONFIDENCE_BP,
    action_kind_allowed,
    destructive_gate,
    md018_content_violation,
)
from microdrama.community.replies import REPLY_MAX_CHARS, draft_reply, grounded_reply
from microdrama.community.service import (
    DEFAULT_MAX_ACTIONS_PER_RUN,
    METERED_ACTION_COST_MICRO_USD,
    METERED_TIMEOUT_MS,
    RESERVATION_TTL,
    CommunityService,
    IngestReport,
    LiveCommunityProvider,
    ProcessReport,
    build_community_service,
)

__all__ = [
    "CONFIDENCE_GATED_KINDS",
    "DEFAULT_MAX_ACTIONS_PER_RUN",
    "DESTRUCTIVE_MIN_CONFIDENCE_BP",
    "GroundingFacts",
    "IngestReport",
    "LiveCommunityProvider",
    "METERED_ACTION_COST_MICRO_USD",
    "METERED_TIMEOUT_MS",
    "ProcessReport",
    "REPLY_MAX_CHARS",
    "RESERVATION_TTL",
    "Classification",
    "CommentClass",
    "CommunityService",
    "action_kind_allowed",
    "build_community_service",
    "destructive_gate",
    "classify_comment",
    "cover_assets_for_post",
    "draft_reply",
    "grounded_reply",
    "load_facts",
    "md018_content_violation",
    "propose_cover_change",
    "propose_hashtag_optimization",
    "thai_date",
    "validate_claims",
]
