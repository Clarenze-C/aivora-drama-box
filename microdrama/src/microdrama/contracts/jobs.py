"""Job type signatures. Module owners export handlers; the integrator registers them.

Handler signature (implemented in owning modules, registered in ``workers``)::

    def handle(ctx: JobContext, payload: <input_model>) -> JobOutcome

``JobContext``/``JobOutcome`` are defined by core (T004). A job is a short,
durable step: long provider work uses submit → WAITING_EXTERNAL → poll/reconcile,
never a worker held open across a human wait. Semantic keys make jobs unique;
retries reuse the same key and the same budget allowance.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from microdrama.contracts.cost import RenderRequest
from microdrama.contracts.enums import QueueName, SnapshotWindow
from microdrama.contracts.primitives import (
    ContractModel,
    Count,
    Identifier,
    Revision,
    VersionedPayload,
)
from microdrama.contracts.qa import ComparisonRequest, ObservationRequest
from microdrama.contracts.release import ManagementAction, PublicationCommand


class SeasonStepInput(VersionedPayload):
    season_id: UUID
    scope_version: Count | None = None
    trigger: Identifier = "scheduled"


class EpisodeStepInput(VersionedPayload):
    episode_id: UUID
    expected_revision: Revision | None = None
    trigger: Identifier = "pipeline"


class PlatformPostRef(VersionedPayload):
    platform_post_id: UUID


class CommunityEventRef(VersionedPayload):
    community_event_id: UUID


class MetricWindowInput(VersionedPayload):
    platform_post_id: UUID
    window: SnapshotWindow


@dataclass(frozen=True)
class JobSpec:
    job_type: str
    queue: QueueName
    owner_module: str
    input_model: type[ContractModel]
    paid: bool
    version: int = 1
    description: str = ""


P, U, C = QueueName.PRODUCTION, QueueName.PUBLICATION, QueueName.COMMUNITY

JOB_SPECS: tuple[JobSpec, ...] = (
    # production
    JobSpec(
        "research.collect_and_propose",
        P,
        "research",
        SeasonStepInput,
        True,
        description="Bounded source research → original season proposals (pre-Gate-1 envelope)",
    ),
    JobSpec(
        "story.compile_season",
        P,
        "story",
        SeasonStepInput,
        True,
        description="Approved scope → bible/arc/canon (no second story approval)",
    ),
    JobSpec(
        "story.write_episode",
        P,
        "story",
        EpisodeStepInput,
        True,
        description="Script + Thai lines + shot manifest; critics with bounded rewrite",
    ),
    JobSpec(
        "references.prepare_episode",
        P,
        "references",
        EpisodeStepInput,
        True,
        description="Reuse/generate references and voice lines; actual durations",
    ),
    JobSpec(
        "render.shot",
        P,
        "rendering",
        RenderRequest,
        True,
        description="One paid shot attempt via pod lease + ComfyUI",
    ),
    JobSpec(
        "edit.assemble_episode",
        P,
        "editing",
        EpisodeStepInput,
        True,
        description="EDL → FFmpeg master, mix, caption tracks",
    ),
    JobSpec(
        "edit.variants_and_hooks",
        P,
        "editing",
        EpisodeStepInput,
        True,
        description="Platform variants, covers, three hook candidates from accepted footage",
    ),
    JobSpec(
        "qa.technical",
        P,
        "qa",
        EpisodeStepInput,
        True,
        description="Decode/streams/black/freeze/silence/peak/caption checks + ASR",
    ),
    JobSpec(
        "qa.observe",
        P,
        "qa",
        ObservationRequest,
        True,
        description="Pass A: actual media + neutral questions only",
    ),
    JobSpec(
        "qa.compare",
        P,
        "qa",
        ComparisonRequest,
        True,
        description="Pass B: frozen observations vs script/canon/anchors",
    ),
    JobSpec(
        "qa.plan_repairs",
        P,
        "qa",
        EpisodeStepInput,
        False,
        description="Smallest-scope priced repair plan from findings/feedback",
    ),
    JobSpec(
        "review.prepare_package",
        P,
        "review",
        EpisodeStepInput,
        False,
        description="Assemble Gate 2 package; GPU must already be off",
    ),
    # publication
    JobSpec(
        "publish.schedule_release",
        U,
        "publishing",
        EpisodeStepInput,
        False,
        description="Approved package → release DAG slots",
    ),
    JobSpec(
        "publish.submit_slot",
        U,
        "publishing",
        PublicationCommand,
        False,
        description="Submit one slot; persist external id before next step",
    ),
    JobSpec(
        "publish.poll_status",
        U,
        "publishing",
        PlatformPostRef,
        False,
        description="Processing status + readback verification",
    ),
    JobSpec(
        "publish.reconcile_slot",
        U,
        "publishing",
        PlatformPostRef,
        False,
        description="Resolve ambiguous upload/schedule without blind resubmit",
    ),
    # community
    JobSpec(
        "community.ingest_event",
        C,
        "community",
        CommunityEventRef,
        False,
        description="Dedupe and classify an inbound comment/DM/event",
    ),
    JobSpec(
        "community.respond",
        C,
        "community",
        ManagementAction,
        True,
        description="Bounded reply/moderation under policy and metered budget",
    ),
    JobSpec(
        "community.optimize_metadata",
        C,
        "community",
        PlatformPostRef,
        True,
        description="Bounded title/caption/hashtag optimization with cooldown",
    ),
    JobSpec(
        "community.deliver_dm",
        C,
        "community",
        ManagementAction,
        True,
        description="Permitted keyword/inbound DM inside the messaging window",
    ),
    JobSpec(
        "membership.sync_catalog",
        C,
        "memberships",
        EpisodeStepInput,
        False,
        description="Truthful early-access/public catalog transitions",
    ),
    JobSpec(
        "analytics.snapshot",
        C,
        "analytics",
        MetricWindowInput,
        False,
        description="24h/72h/7d metric snapshot with definitions and missingness",
    ),
    JobSpec(
        "analytics.qualification",
        C,
        "analytics",
        SeasonStepInput,
        False,
        description="Rolling ten-episode qualification and effective cost",
    ),
)

JOB_SPECS_BY_TYPE: dict[str, JobSpec] = {spec.job_type: spec for spec in JOB_SPECS}

# The janitor is an independently scheduled process, not a queue job, so a blocked
# queue/worker can never stop orphan-GPU cleanup (SPEC §6, §8).
# Job types an operator (scheduler/worker credential) may enqueue directly through
# ``POST /internal/jobs``: schedules, webhook ingestion, status polling and analytics. Every
# other type (story compilation, rendering, QA, packaging and above all publication) is enqueued
# only in-process by the service that owns its precondition (a gate approval, a repair plan, a
# release DAG), so a credential can never start it out of order (V-22).
API_ENQUEUEABLE_JOB_TYPES: frozenset[str] = frozenset(
    {
        "research.collect_and_propose",
        "publish.poll_status",
        "publish.reconcile_slot",
        "community.ingest_event",
        "membership.sync_catalog",
        "analytics.snapshot",
        "analytics.qualification",
    }
)

JANITOR_ENTRYPOINT = "microdrama.rendering.janitor:main"
