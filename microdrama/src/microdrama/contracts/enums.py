"""Closed enumerations shared across modules. Contract-guardian owned.

Every enum is closed: an unknown value is a schema error (422), never silently
dropped or mapped to a default. Add members only through a contract version
change.
"""

from __future__ import annotations

from enum import StrEnum

# --- Execution / effects --------------------------------------------------------


class ExecutionMode(StrEnum):
    OFFLINE_MOCK = "OFFLINE_MOCK"
    PAID_BENCHMARK = "PAID_BENCHMARK"
    CONTROLLED_ACCOUNT_TEST = "CONTROLLED_ACCOUNT_TEST"
    PRODUCTION = "PRODUCTION"


class EffectKind(StrEnum):
    PAID_REQUEST = "PAID_REQUEST"
    CLOUD_RESOURCE = "CLOUD_RESOURCE"
    PUBLIC_ACTION = "PUBLIC_ACTION"


class Provenance(StrEnum):
    """Where data/media came from. Fakes are always FAKE_SYNTHETIC."""

    FAKE_SYNTHETIC = "FAKE_SYNTHETIC"
    LIVE_PROVIDER = "LIVE_PROVIDER"
    DERIVED_LOCAL = "DERIVED_LOCAL"  # produced locally (FFmpeg) from other assets
    ORIGINAL_FIXTURE = "ORIGINAL_FIXTURE"  # synthetic test media generated locally
    LICENSED = "LICENSED"


# --- Principals -------------------------------------------------------------------


class PrincipalKind(StrEnum):
    HUMAN_OWNER = "HUMAN_OWNER"
    SERVICE_WORKER = "SERVICE_WORKER"
    RUNTIME_MODEL = "RUNTIME_MODEL"
    PROVIDER_WEBHOOK = "PROVIDER_WEBHOOK"
    SCHEDULER = "SCHEDULER"


class RuntimeRole(StrEnum):
    """Runtime application model roles (not development agents)."""

    STORY_ARCHITECT = "STORY_ARCHITECT"
    RESEARCHER = "RESEARCHER"
    CRITIC = "CRITIC"
    CLASSIFIER = "CLASSIFIER"
    OBSERVER = "OBSERVER"  # QA Pass A
    COMPARATOR = "COMPARATOR"  # QA Pass B
    COMMUNITY_RESPONDER = "COMMUNITY_RESPONDER"
    METADATA_WRITER = "METADATA_WRITER"


# --- Lifecycle states -------------------------------------------------------------


class SeasonState(StrEnum):
    PROPOSED = "PROPOSED"
    SEASON_APPROVED = "SEASON_APPROVED"
    ACTIVE = "ACTIVE"
    COMPLETE = "COMPLETE"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class EpisodeState(StrEnum):
    PLANNED = "PLANNED"
    SCRIPTING = "SCRIPTING"
    REFERENCES = "REFERENCES"
    RENDERING = "RENDERING"
    ASSEMBLING = "ASSEMBLING"
    AI_REVIEW = "AI_REVIEW"
    AWAITING_FINAL_REVIEW = "AWAITING_FINAL_REVIEW"
    RELEASE_APPROVED = "RELEASE_APPROVED"
    SCHEDULED = "SCHEDULED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED_VERIFIED = "PUBLISHED_VERIFIED"
    MANAGED = "MANAGED"


class EpisodeOutcome(StrEnum):
    """Typed failure outcome recorded alongside the last valid stage (SPEC §5)."""

    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    FAILED_QA = "FAILED_QA"
    FAILED_INFRA = "FAILED_INFRA"
    RIGHTS_UNCLEARED = "RIGHTS_UNCLEARED"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ReleaseState(StrEnum):
    RELEASE_APPROVED = "RELEASE_APPROVED"
    SCHEDULED = "SCHEDULED"
    SUBMITTED = "SUBMITTED"
    PROCESSING = "PROCESSING"
    PUBLISHED_VERIFIED = "PUBLISHED_VERIFIED"
    RETRY_WAIT = "RETRY_WAIT"
    NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"
    HELD = "HELD"  # destination blocked by capability/rights; not a failure of the episode
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_EXTERNAL = "WAITING_EXTERNAL"  # submitted to provider; poll/reconcile later
    RETRY_WAIT = "RETRY_WAIT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"
    CANCELLED = "CANCELLED"


class ProviderOperationState(StrEnum):
    PENDING_SUBMIT = "PENDING_SUBMIT"
    SUBMITTED = "SUBMITTED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"  # ambiguous: reconcile before any resubmission
    NOT_FOUND = "NOT_FOUND"  # reconcile proved the provider never accepted it


class PodState(StrEnum):
    REQUESTED = "REQUESTED"
    CREATING = "CREATING"
    RUNNING = "RUNNING"
    RELEASING = "RELEASING"
    STOPPED = "STOPPED"
    TERMINATED = "TERMINATED"
    UNKNOWN = "UNKNOWN"


class LeaseState(StrEnum):
    CLAIMED = "CLAIMED"
    ACTIVE = "ACTIVE"
    TRANSFERRING = "TRANSFERRING"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    ORPHANED = "ORPHANED"


# --- Gates / review ---------------------------------------------------------------


class GateType(StrEnum):
    SEASON_CONCEPT = "SEASON_CONCEPT"  # Gate 1
    EPISODE_FINAL = "EPISODE_FINAL"  # Gate 2


class ApprovalAction(StrEnum):
    APPROVE = "APPROVE"
    REVISE = "REVISE"
    REJECT = "REJECT"


class FeedbackCategory(StrEnum):
    IDENTITY_VOICE = "identity_voice"
    THAI_DIALOGUE = "thai_dialogue"
    SUBTITLES = "subtitles"
    MOTIVATION = "motivation"
    CONTINUITY_PROPS = "continuity_props"
    PACING = "pacing"
    SOUND = "sound"
    OTHER = "other"


class FeedbackScope(StrEnum):
    SHOT = "SHOT"
    EPISODE = "EPISODE"
    SERIES = "SERIES"  # only with explicit recurring instruction


# --- Budget -----------------------------------------------------------------------


class BudgetCategory(StrEnum):
    RESEARCH_SCRIPT_PROMPTS_METADATA = "RESEARCH_SCRIPT_PROMPTS_METADATA"
    REFERENCES_DIALOGUE = "REFERENCES_DIALOGUE"
    GPU_GENERATION = "GPU_GENERATION"
    QA_CAPTIONS = "QA_CAPTIONS"
    CPU_STORAGE_TRANSFER = "CPU_STORAGE_TRANSFER"
    METERED_MANAGEMENT = "METERED_MANAGEMENT"
    RECOVERY_HEADROOM = "RECOVERY_HEADROOM"


class BudgetScopeKind(StrEnum):
    EPISODE = "EPISODE"
    SEASON_RESEARCH = "SEASON_RESEARCH"  # prospective pre-Gate-1 research envelope


class CostBasis(StrEnum):
    """How an amount was established. Only PROVIDER_REPORTED/BILLED are measured."""

    SYNTHETIC_FAKE = "SYNTHETIC_FAKE"  # fake provider; exercises accounting, not real money
    ESTIMATED = "ESTIMATED"
    PROVIDER_REPORTED = "PROVIDER_REPORTED"
    BILLED = "BILLED"


class ReceiptKind(StrEnum):
    ACCRUAL = "ACCRUAL"  # interim usage; may be superseded by settlement
    SETTLEMENT = "SETTLEMENT"  # final amount for a reservation/operation
    CREDIT = "CREDIT"  # recorded; never restores episode allowance
    ADJUSTMENT = "ADJUSTMENT"  # late billing difference (may reveal overrun)


class PriceUnit(StrEnum):
    REQUEST = "REQUEST"
    INPUT_TOKEN_1K = "INPUT_TOKEN_1K"
    OUTPUT_TOKEN_1K = "OUTPUT_TOKEN_1K"
    AUDIO_SECOND = "AUDIO_SECOND"
    VIDEO_SECOND = "VIDEO_SECOND"
    GPU_SECOND = "GPU_SECOND"
    IMAGE = "IMAGE"
    CHARACTER_1K = "CHARACTER_1K"
    GIGABYTE = "GIGABYTE"


class PriceSource(StrEnum):
    CONFIG_PRICE_TABLE = "CONFIG_PRICE_TABLE"
    PROVIDER_QUOTE = "PROVIDER_QUOTE"
    FAKE_SYNTHETIC = "FAKE_SYNTHETIC"


# --- Queues / jobs ----------------------------------------------------------------


class QueueName(StrEnum):
    PRODUCTION = "production"
    PUBLICATION = "publication"
    COMMUNITY = "community"


# --- Story / shots ----------------------------------------------------------------


class ShotPattern(StrEnum):
    CONFRONTATION = "confrontation_v1"
    REVELATION = "revelation_v1"
    QUIET_CONFESSION = "quiet_confession_v1"
    COMIC_REACTION = "comic_reaction_v1"
    PRACTICAL_PROP_ACTION = "practical_prop_action_v1"
    CLIFFHANGER = "cliffhanger_v1"


class Level(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DialogueComplexity(StrEnum):
    NONE = "NONE"
    SINGLE_SPEAKER = "SINGLE_SPEAKER"
    TWO_SPEAKER = "TWO_SPEAKER"


class RenderTier(StrEnum):
    FAST_FOUR_STEP = "fast_four_step"
    QUALITY_EIGHT_STEP = "quality_eight_step"
    COMPATIBLE_BASELINE = "compatible_baseline"


class ControlKind(StrEnum):
    """Generation controls. Required controls can never be silently dropped."""

    TEXT_PROMPT = "TEXT_PROMPT"
    FIRST_FRAME = "FIRST_FRAME"
    LAST_FRAME = "LAST_FRAME"
    CHARACTER_REFERENCE = "CHARACTER_REFERENCE"
    WARDROBE_REFERENCE = "WARDROBE_REFERENCE"
    LOCATION_REFERENCE = "LOCATION_REFERENCE"
    STYLE_REFERENCE = "STYLE_REFERENCE"
    VOICE_REFERENCE = "VOICE_REFERENCE"
    AUDIO_DRIVEN_LIPSYNC = "AUDIO_DRIVEN_LIPSYNC"
    CAMERA_MOTION = "CAMERA_MOTION"
    SEED = "SEED"


class FallbackEdit(StrEnum):
    CUT_TO_REACTION = "CUT_TO_REACTION"
    HOLD_PREVIOUS_FRAME = "HOLD_PREVIOUS_FRAME"
    INSERT_STILL_WITH_AUDIO = "INSERT_STILL_WITH_AUDIO"
    WIDE_SHOT_OVER_DIALOGUE = "WIDE_SHOT_OVER_DIALOGUE"
    COMPOSITE_TEXT_INSERT = "COMPOSITE_TEXT_INSERT"


class CriticalTermKind(StrEnum):
    NAME = "NAME"
    MONEY = "MONEY"
    NUMBER = "NUMBER"
    NEGATION = "NEGATION"
    RELATIONSHIP_TERM = "RELATIONSHIP_TERM"
    DATE_TIME = "DATE_TIME"


class IdentityAssetKind(StrEnum):
    FACE = "FACE"
    VOICE = "VOICE"
    WARDROBE = "WARDROBE"
    LOCATION = "LOCATION"
    STYLE = "STYLE"


# --- Assets / media ---------------------------------------------------------------


class AssetKind(StrEnum):
    VIDEO = "VIDEO"
    AUDIO = "AUDIO"
    IMAGE = "IMAGE"
    CAPTION = "CAPTION"
    EDL = "EDL"
    TRANSCRIPT = "TRANSCRIPT"
    REPORT = "REPORT"
    CONTACT_SHEET = "CONTACT_SHEET"
    OTHER = "OTHER"


class AssetState(StrEnum):
    PROVISIONAL = "PROVISIONAL"
    ACCEPTED = "ACCEPTED"
    FAILED = "FAILED"
    LOCKED = "LOCKED"  # part of an identity lock
    SUPERSEDED = "SUPERSEDED"


class TrackKind(StrEnum):
    VIDEO = "VIDEO"
    DIALOGUE = "DIALOGUE"
    AMBIENCE = "AMBIENCE"
    MUSIC = "MUSIC"
    EFFECTS = "EFFECTS"


class TransitionKind(StrEnum):
    CUT = "CUT"
    CROSSFADE = "CROSSFADE"
    FADE_FROM_BLACK = "FADE_FROM_BLACK"
    FADE_TO_BLACK = "FADE_TO_BLACK"


class CaptionTimingSource(StrEnum):
    ACTUAL_AUDIO_ALIGNMENT = "ACTUAL_AUDIO_ALIGNMENT"
    ESTIMATED_FROM_SCRIPT = "ESTIMATED_FROM_SCRIPT"  # never releasable


# --- QA ---------------------------------------------------------------------------


class QAOutcome(StrEnum):
    PASS = "PASS"
    REPAIRABLE = "REPAIRABLE"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    INFO = "INFO"


class CoverageStatus(StrEnum):
    CHECKED = "CHECKED"
    PARTIAL = "PARTIAL"
    UNSAMPLED = "UNSAMPLED"
    UNAVAILABLE = "UNAVAILABLE"


class CheckFamily(StrEnum):
    TECHNICAL = "TECHNICAL"
    AUDIO = "AUDIO"
    ASR = "ASR"
    CAPTION = "CAPTION"
    VISUAL_IDENTITY = "VISUAL_IDENTITY"
    TEMPORAL = "TEMPORAL"
    NARRATIVE = "NARRATIVE"
    LOCALIZATION = "LOCALIZATION"
    POLICY = "POLICY"


class QAPass(StrEnum):
    TECHNICAL = "TECHNICAL"
    PASS_A_OBSERVATION = "PASS_A_OBSERVATION"
    PASS_B_COMPARISON = "PASS_B_COMPARISON"
    HUMAN_FEEDBACK = "HUMAN_FEEDBACK"


class RepairTarget(StrEnum):
    CAPTION = "CAPTION"
    LINE = "LINE"  # replace a dialogue line's audio (and derived cues)
    SHOT = "SHOT"  # re-render one shot (consumes an ordinary attempt)
    EDIT = "EDIT"  # re-cut from accepted footage
    AUDIO_MIX = "AUDIO_MIX"
    SCRIPT = "SCRIPT"


class RepairTrigger(StrEnum):
    QA_FINDING = "QA_FINDING"
    HUMAN_FEEDBACK = "HUMAN_FEEDBACK"


# --- Release / platforms ----------------------------------------------------------


class Platform(StrEnum):
    TIKTOK = "TIKTOK"
    YOUTUBE = "YOUTUBE"
    FACEBOOK = "FACEBOOK"
    INSTAGRAM = "INSTAGRAM"


class SlotKind(StrEnum):
    FULL_EPISODE = "FULL_EPISODE"
    PART = "PART"
    PROMO_CUT = "PROMO_CUT"
    HOOK = "HOOK"


class DisclosureKind(StrEnum):
    AI_GENERATED_CONTENT = "AI_GENERATED_CONTENT"
    SYNTHETIC_VOICE = "SYNTHETIC_VOICE"
    SPONSORED = "SPONSORED"
    MEMBER_OFFER = "MEMBER_OFFER"


class CapabilityOperation(StrEnum):
    UPLOAD_FULL_VIDEO = "UPLOAD_FULL_VIDEO"
    UPLOAD_SHORT = "UPLOAD_SHORT"
    SCHEDULE = "SCHEDULE"
    STATUS = "STATUS"
    READBACK = "READBACK"
    AI_DISCLOSURE = "AI_DISCLOSURE"
    SPONSOR_DISCLOSURE = "SPONSOR_DISCLOSURE"
    CAPTIONS_UPLOAD = "CAPTIONS_UPLOAD"
    LOCALIZED_METADATA = "LOCALIZED_METADATA"
    METADATA_UPDATE = "METADATA_UPDATE"
    COVER_UPDATE = "COVER_UPDATE"
    INSIGHTS = "INSIGHTS"
    COMMENT_READ = "COMMENT_READ"
    COMMENT_REPLY = "COMMENT_REPLY"
    COMMENT_MODERATE = "COMMENT_MODERATE"
    DM_SEND = "DM_SEND"
    WEBHOOKS = "WEBHOOKS"


class CapabilitySupport(StrEnum):
    SUPPORTED_TESTED = "SUPPORTED_TESTED"  # verified by controlled authorized account test
    SUPPORTED_DOCUMENTED = "SUPPORTED_DOCUMENTED"  # official docs only; not yet tested
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


class EvidenceSource(StrEnum):
    FAKE_FIXTURE = "FAKE_FIXTURE"
    OFFICIAL_DOCUMENTATION = "OFFICIAL_DOCUMENTATION"
    CONTROLLED_ACCOUNT_TEST = "CONTROLLED_ACCOUNT_TEST"
    MEASURED_BENCHMARK = "MEASURED_BENCHMARK"
    LICENSE_DOCUMENT = "LICENSE_DOCUMENT"


class ManagementActionKind(StrEnum):
    TITLE_EDIT = "TITLE_EDIT"
    CAPTION_EDIT = "CAPTION_EDIT"
    DESCRIPTION_EDIT = "DESCRIPTION_EDIT"
    HASHTAG_EDIT = "HASHTAG_EDIT"
    COVER_CHANGE = "COVER_CHANGE"
    LINK_UPDATE = "LINK_UPDATE"
    PUBLIC_REPLY = "PUBLIC_REPLY"
    DM_SEND = "DM_SEND"
    MODERATE_HIDE = "MODERATE_HIDE"
    MODERATE_DELETE = "MODERATE_DELETE"
    MODERATE_REPORT = "MODERATE_REPORT"
    NO_ACTION = "NO_ACTION"


class ActionDecision(StrEnum):
    PROPOSED = "PROPOSED"
    EXECUTED = "EXECUTED"
    SUPPRESSED = "SUPPRESSED"
    DEFERRED = "DEFERRED"
    FAILED = "FAILED"
    NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"


class CommunityEventKind(StrEnum):
    COMMENT = "COMMENT"
    REPLY = "REPLY"
    DIRECT_MESSAGE = "DIRECT_MESSAGE"
    MENTION = "MENTION"
    POST_STATUS = "POST_STATUS"


# --- Membership / analytics -------------------------------------------------------


class MembershipProviderKind(StrEnum):
    PATREON = "PATREON"
    BUY_ME_A_COFFEE = "BUY_ME_A_COFFEE"


class CatalogPublicState(StrEnum):
    NOT_RELEASED = "NOT_RELEASED"
    EARLY_ACCESS_MEMBERS = "EARLY_ACCESS_MEMBERS"
    PUBLIC_FREE = "PUBLIC_FREE"
    WITHDRAWN = "WITHDRAWN"


class SnapshotWindow(StrEnum):
    H24 = "H24"
    H72 = "H72"
    D7 = "D7"


class TrafficKind(StrEnum):
    ORGANIC = "ORGANIC"
    PAID = "PAID"
    UNKNOWN = "UNKNOWN"


class QualificationStatus(StrEnum):
    QUALIFIED = "QUALIFIED"
    NOT_QUALIFIED = "NOT_QUALIFIED"
    PENDING = "PENDING"


class SourceQuality(StrEnum):
    PRIMARY_OFFICIAL = "PRIMARY_OFFICIAL"
    REPUTABLE_SECONDARY = "REPUTABLE_SECONDARY"
    PUBLIC_COMMENTS = "PUBLIC_COMMENTS"  # qualitative clues only
    UNVERIFIED = "UNVERIFIED"
    FIXTURE = "FIXTURE"  # mock citation; not a real source
