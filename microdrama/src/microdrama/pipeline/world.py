"""The composed pipeline world (T029 integrator composition root).

One process, every accepted module service, every T007 fake external boundary.
This is what a worker deployment (and the offline demo) runs: real PostgreSQL,
real budget/idempotency/jobs, real local FFmpeg, fake providers. Construction
refuses non-OFFLINE_MOCK settings (``build_fake_providers`` raises EffectDenied),
so the composed world can never reach a paid or public boundary.

The world never registers HTTP routers itself; ``api.compose`` owns that. Module
owners exported factories; only this package imports them all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from microdrama.analytics import AnalyticsService, build_analytics_service
from microdrama.budget import BudgetService
from microdrama.community import build_community_service
from microdrama.community.dm import build_dm_delivery_service
from microdrama.config import Settings
from microdrama.contracts.enums import (
    CapabilityOperation,
    CapabilitySupport,
    Platform,
    PrincipalKind,
    QueueName,
)
from microdrama.contracts.infra import IdGenerator, ObjectStore
from microdrama.contracts.season import ManagementPolicy
from microdrama.core.auth import AuthService
from microdrama.core.idempotency import IdempotencyService
from microdrama.core.jobs import JobService
from microdrama.core.registry.presets import PresetRegistry
from microdrama.core.registry.rights import RightsRegistry
from microdrama.editing import EditingService, build_editing_service
from microdrama.editing.variants_service import VariantsService, build_variants_service
from microdrama.memberships import MembershipServices, build_membership_services
from microdrama.persistence import Database
from microdrama.persistence.object_store import FilesystemObjectStore
from microdrama.publishing.facebook import facebook_page_adapter
from microdrama.publishing.instagram import build_instagram_adapter
from microdrama.publishing.service import PublishingService
from microdrama.publishing.tiktok import build_tiktok_adapter
from microdrama.publishing.youtube import build_youtube_adapter
from microdrama.qa.audio import OfflineMediaObserver, as_speech_observer
from microdrama.qa.comparison import build_comparison_service
from microdrama.qa.observation import build_observation_service
from microdrama.qa.repairs import build_repair_service
from microdrama.qa.service import build_technical_qa_service
from microdrama.references import ReferencesService, build_references_service
from microdrama.rendering.comfy_jobs import ComfyRenderService, build_comfy_render_service
from microdrama.rendering.janitor import Janitor as GpuJanitor
from microdrama.rendering.janitor import build_janitor as build_gpu_janitor
from microdrama.rendering.leases import LeaseService, PodLeaseConfig, build_lease_service
from microdrama.rendering.pods import PodManager
from microdrama.rendering.presets import PresetCatalog
from microdrama.rendering.routing import ShotRouter
from microdrama.research import ResearchService, build_research_service
from microdrama.review import ReviewService
from microdrama.story import StoryService, build_story_service
from microdrama.testing.fakes import (
    FakeClock,
    FakeProviders,
    SequentialIds,
    build_fake_providers,
)
from microdrama.testing.media import FixtureTruthRegistry
from microdrama.workers import SharedRateLimiter, WorkerRuntime
from microdrama.workers.janitor import WorkersJanitor
from microdrama.workers.janitor import build_janitor as build_workers_janitor
from microdrama.workers.runtime import QueueSlots, WorkerDeployment

from .catalog import seed_mock_catalog
from .conditions import build_registry_release_conditions
from .mocks import script_story_fakes
from .registry_seed import seed_mock_registries

#: After every fixture adapter's internal clock (the Instagram adapter stamps
#: verified_at at its own fixed 2026-10-27T12:00Z; registry recording refuses a
#: future verification), and before the pilot's evening release window.
T0 = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)

_PLATFORMS = (Platform.YOUTUBE, Platform.TIKTOK, Platform.INSTAGRAM, Platform.FACEBOOK)


@dataclass
class PipelineWorld:
    """Every constructed service for one offline pipeline process."""

    settings: Settings
    db: Database
    store: ObjectStore
    fakes: FakeProviders
    budget: BudgetService
    jobs: JobService
    idempotency: IdempotencyService
    auth: AuthService
    research: ResearchService
    story: StoryService
    references: ReferencesService
    review: ReviewService
    leases: LeaseService
    comfy: ComfyRenderService
    router: ShotRouter
    catalog: PresetCatalog
    editing: EditingService
    variants: VariantsService
    qa_technical: object
    qa_observation: object
    qa_comparison: object
    qa_repairs: object
    publishing: PublishingService
    community: object
    memberships: MembershipServices
    analytics: AnalyticsService
    limiter: SharedRateLimiter
    workers_janitor: WorkersJanitor
    gpu_janitor: GpuJanitor
    speech_observer: object

    # --- principals / auth (the real path; no test seeding in runtime code) -------------

    def human_owner(self, username: str, password: str):
        """Create a real owner + session through AuthService; returns the Principal."""
        self.auth.create_owner(username, password)
        tokens = self.auth.login(username, password)
        return self.auth.authenticate_session(tokens.session_token)

    def operator_token(self, principal_id: str = "svc:pipeline-scheduler") -> str:
        """A real scheduler credential (what n8n and the demo enqueue jobs with)."""
        return self.auth.issue_service_credential(
            principal_id, PrincipalKind.SCHEDULER, scopes=("jobs",)
        )

    # --- per-run lazies ------------------------------------------------------------------

    def dm_delivery(self, platform: Platform, policy: ManagementPolicy):
        """DM delivery for one platform's community provider under the approved policy."""
        return build_dm_delivery_service(
            db=self.db,
            clock=self.fakes.clock,
            ids=self.fakes.ids,
            community=self.fakes.community[platform],
            catalog=self.memberships.catalog,
            entitlements=self.memberships.entitlements,
            budget=self.budget,
            policy=policy,
        )

    def runtime_for(self, deployment: WorkerDeployment) -> WorkerRuntime:
        """A worker runtime over an integrator-built deployment."""
        return WorkerRuntime(self.jobs, self.db, self.fakes.clock, deployment)

    def runtime(self, handlers, *, name: str = "pipeline-worker") -> WorkerRuntime:
        """The composed worker runtime: one reserved slot per queue (T028 semantics)."""
        deployment = WorkerDeployment(
            name=name,
            slots=(
                QueueSlots(QueueName.PRODUCTION, 1),
                QueueSlots(QueueName.PUBLICATION, 1),
                QueueSlots(QueueName.COMMUNITY, 2),
            ),
            handlers=handlers,
            limiter=self.limiter,
        )
        return WorkerRuntime(self.jobs, self.db, self.fakes.clock, deployment)


def _bytes_for_sha(world_store: ObjectStore, db: Database):
    def resolve(sha256: str) -> bytes:
        with db.transaction(readonly=True) as tx:
            key = tx.fetchone("SELECT object_key FROM assets WHERE sha256 = %s", (sha256,))
        if key is None:
            raise LookupError(f"no asset registered for sha256 {sha256[:12]}")
        return world_store.get_bytes(key["object_key"])

    return resolve


def _mock_story_config():
    """The OFFLINE_MOCK story config, constrained to the mock render catalog.

    Same fake price table the factory default would set, plus
    ``supported_controls`` = the mock video template's controls: the compiler
    then records VOICE_REFERENCE staging as a simplification (voices are
    separate reference-lane audio assets in this pipeline, mixed in W06) instead
    of emitting shots no preset can ever route.
    """
    from microdrama.contracts.enums import PriceUnit
    from microdrama.rendering.workflows import PRESET_TEMPLATES
    from microdrama.story import StoryConfig
    from microdrama.testing.fakes.common import fake_price_quote

    template = PRESET_TEMPLATES["fake-quality-8step"]
    return StoryConfig(
        writer_input_price=fake_price_quote(PriceUnit.INPUT_TOKEN_1K),
        writer_output_price=fake_price_quote(PriceUnit.OUTPUT_TOKEN_1K),
        critic_input_price=fake_price_quote(PriceUnit.INPUT_TOKEN_1K),
        critic_output_price=fake_price_quote(PriceUnit.OUTPUT_TOKEN_1K),
        supported_controls=template.supported_controls,
    )


#: Operations the YouTube/TikTok mock adapters declare SUPPORTED_TESTED: every
#: one is actually exercised against the T007 fixture transport in this
#: composition's tests (submit/status/readback round trips). Instagram and
#: Facebook pin their declaration truth — TESTED is reserved for T032 controlled
#: account tests — so their slots hold at submit until then, which the pilot
#: demonstrates honestly (optional destinations, HELD not failed).
FIXTURE_TESTED_OPS = {
    CapabilityOperation.UPLOAD_FULL_VIDEO: CapabilitySupport.SUPPORTED_TESTED,
    CapabilityOperation.UPLOAD_SHORT: CapabilitySupport.SUPPORTED_TESTED,
    CapabilityOperation.SCHEDULE: CapabilitySupport.SUPPORTED_TESTED,
    CapabilityOperation.STATUS: CapabilitySupport.SUPPORTED_TESTED,
    CapabilityOperation.READBACK: CapabilitySupport.SUPPORTED_TESTED,
    CapabilityOperation.AI_DISCLOSURE: CapabilitySupport.SUPPORTED_TESTED,
}


def _build_adapter(platform: Platform, settings: Settings, fakes: FakeProviders):
    if platform is Platform.YOUTUBE:
        return build_youtube_adapter(
            settings, clock=fakes.clock, ids=fakes.ids, operations=dict(FIXTURE_TESTED_OPS)
        )
    if platform is Platform.TIKTOK:
        return build_tiktok_adapter(
            settings,
            clock=fakes.clock,
            ids=fakes.ids,
            operations_override=dict(FIXTURE_TESTED_OPS),
        )
    if platform is Platform.INSTAGRAM:
        return build_instagram_adapter(settings)
    return facebook_page_adapter(clock=fakes.clock, ids=fakes.ids, settings=settings)


def build_pipeline_world(
    settings: Settings,
    db: Database,
    *,
    clock: FakeClock | None = None,
    ids: IdGenerator | None = None,
    store: ObjectStore | None = None,
    truth: FixtureTruthRegistry | None = None,
    seed_registries: bool = True,
) -> PipelineWorld:
    """Construct every accepted service once (OFFLINE_MOCK only)."""
    fake_clock = clock or FakeClock(T0)
    fake_ids = ids or SequentialIds("pipeline")
    if store is None:
        if settings.object_store_root is None:
            raise ValueError("the pipeline needs an object store root")
        store = FilesystemObjectStore(settings.object_store_root)
    fakes = build_fake_providers(settings, fake_clock, fake_ids, truth=truth)
    script_story_fakes(fakes.llm)

    budget = BudgetService(db, fake_clock, fake_ids, settings)
    jobs = JobService(db, fake_clock, fake_ids)
    idempotency = IdempotencyService(db)
    auth = AuthService(db, fake_clock, fake_ids)

    research = build_research_service(
        db,
        fake_clock,
        fake_ids,
        settings,
        budget=budget,
        source_providers={"fake-sources": fakes.sources},
        llm=fakes.llm,
    )
    story = build_story_service(
        db,
        fake_clock,
        fake_ids,
        settings,
        budget=budget,
        llm=fakes.llm,
        config=_mock_story_config(),
    )
    rights = RightsRegistry(db, fake_clock, settings)
    references = build_references_service(
        db,
        fake_clock,
        fake_ids,
        settings,
        budget=budget,
        store=store,
        image_provider=fakes.generation,
        voice_provider=fakes.generation,
        rights=rights,
    )
    review = ReviewService(
        db,
        fake_clock,
        fake_ids,
        jobs=jobs,
        idempotency=idempotency,
        budget=budget,
        store=store,
        release_conditions_fn=build_registry_release_conditions(db, fake_clock, settings),
        approval_hooks=(),
        identity_lock_hook=references.identity_lock_hook(),
    )

    pod_config = PodLeaseConfig.for_mock()
    manager = PodManager(fakes.pods, fake_clock, pod_config)
    leases = build_lease_service(db, budget, manager, fake_clock, fake_ids, settings, pod_config)
    comfy = build_comfy_render_service(
        db, budget, fakes.comfy, fake_clock, fake_ids, settings, None, store
    )
    preset_registry = PresetRegistry(db, settings)
    catalog = PresetCatalog(db, preset_registry)
    router = ShotRouter(db, catalog, fake_clock)

    observer = OfflineMediaObserver(truth or fakes.truth, settings)
    speech_observer = as_speech_observer(observer, _bytes_for_sha(store, db))
    editing = build_editing_service(
        db,
        fake_clock,
        fake_ids,
        settings,
        budget=budget,
        store=store,
        speech_observer=speech_observer,
    )
    variants = build_variants_service(
        db,
        fake_clock,
        fake_ids,
        settings,
        budget=budget,
        store=store,
        speech_observer=speech_observer,
    )

    qa_technical = build_technical_qa_service(
        db, fake_clock, fake_ids, settings, budget=budget, store=store, observer=observer
    )
    qa_observation = build_observation_service(
        db, fake_clock, fake_ids, settings, budget=budget, store=store, observer=observer
    )
    qa_comparison = build_comparison_service(db, fake_clock, fake_ids, settings, budget=budget)
    qa_repairs = build_repair_service(db, fake_clock, fake_ids, settings, budget=budget, jobs=jobs)

    adapters = {platform: _build_adapter(platform, settings, fakes) for platform in _PLATFORMS}
    publishing = PublishingService(db, fake_clock, fake_ids, adapters, store)

    community = build_community_service(settings, db, fake_clock, fake_ids, fakes.community, budget)
    memberships = build_membership_services(
        settings, db=db, clock=fake_clock, ids=fake_ids, budget=budget
    )
    analytics = build_analytics_service(db, fake_clock, fake_ids)

    limiter = SharedRateLimiter(fake_clock)
    workers_janitor = build_workers_janitor(db, jobs, budget, fake_clock, fake_ids)
    gpu_janitor = build_gpu_janitor(
        db,
        BudgetService(db, fake_clock, fake_ids, settings),
        fakes.pods,
        fake_clock,
        fake_ids,
        settings,
        pod_config,
    )

    if seed_registries:
        seed_mock_catalog(preset_registry)
        seed_mock_registries(db, adapters, fake_clock, fake_ids, settings)

    return PipelineWorld(
        settings=settings,
        db=db,
        store=store,
        fakes=fakes,
        budget=budget,
        jobs=jobs,
        idempotency=idempotency,
        auth=auth,
        research=research,
        story=story,
        references=references,
        review=review,
        leases=leases,
        comfy=comfy,
        router=router,
        catalog=catalog,
        editing=editing,
        variants=variants,
        qa_technical=qa_technical,
        qa_observation=qa_observation,
        qa_comparison=qa_comparison,
        qa_repairs=qa_repairs,
        publishing=publishing,
        community=community,
        memberships=memberships,
        analytics=analytics,
        limiter=limiter,
        workers_janitor=workers_janitor,
        gpu_janitor=gpu_janitor,
        speech_observer=speech_observer,
    )


__all__ = ["PipelineWorld", "build_pipeline_world", "T0"]
