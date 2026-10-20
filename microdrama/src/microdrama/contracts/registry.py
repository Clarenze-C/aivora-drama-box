"""Registry of every published contract model (drives ``make contracts``)."""

from __future__ import annotations

from pydantic import BaseModel

from microdrama.contracts import (
    catalog,
    cost,
    events,
    jobs,
    media,
    providers,
    qa,
    release,
    routes,
    season,
)
from microdrama.contracts.principals import Principal
from microdrama.contracts.registries import PresetMeasurements, PresetRecord, RightsRecord

# SPEC §4.2 cross-module payloads (each has valid and invalid examples).
CORE_PAYLOADS: dict[str, type[BaseModel]] = {
    "SeasonScope": season.SeasonScope,
    "ApprovalCommand": season.ApprovalCommand,
    "EpisodePlan": season.EpisodePlan,
    "Script": season.Script,
    "ShotManifest": season.ShotManifest,
    "IdentityLock": season.IdentityLock,
    "BudgetReservationRequest": cost.BudgetReservationRequest,
    "UsageReceipt": cost.UsageReceipt,
    "PodLease": cost.PodLease,
    "RenderRequest": cost.RenderRequest,
    "ProviderOperation": cost.ProviderOperation,
    "ProviderOperationResult": cost.ProviderOperationResult,
    "AssetDescriptor": media.AssetDescriptor,
    "EditDecisionList": media.EditDecisionList,
    "CaptionTrack": media.CaptionTrack,
    "HookExperiment": media.HookExperiment,
    "ObservationRequest": qa.ObservationRequest,
    "ObservationReport": qa.ObservationReport,
    "ComparisonRequest": qa.ComparisonRequest,
    "QAFinding": qa.QAFinding,
    "RepairPlan": qa.RepairPlan,
    "ReleasePackage": release.ReleasePackage,
    "PublicationCommand": release.PublicationCommand,
    "CapabilityRecord": release.CapabilityRecord,
    "ManagementAction": release.ManagementAction,
    "MembershipCatalogEntry": catalog.MembershipCatalogEntry,
    "MetricSnapshot": catalog.MetricSnapshot,
    "QualificationResult": catalog.QualificationResult,
    "DomainEvent": events.DomainEvent,
}

# Supporting payloads: provider boundaries, job inputs and API views.
SUPPORTING_PAYLOADS: dict[str, type[BaseModel]] = {
    "Principal": Principal,
    "RightsRecord": RightsRecord,
    "PresetRecord": PresetRecord,
    "PresetMeasurements": PresetMeasurements,
    "PublishResult": release.PublishResult,
    "PostMetadata": release.PostMetadata,
    "SourceQuery": providers.SourceQuery,
    "SourceSearchResult": providers.SourceSearchResult,
    "LLMRequest": providers.LLMRequest,
    "LLMResponse": providers.LLMResponse,
    "ImageRequest": providers.ImageRequest,
    "VoiceRequest": providers.VoiceRequest,
    "PodCreateRequest": providers.PodCreateRequest,
    "ASRRequest": providers.ASRRequest,
    "ASRResult": providers.ASRResult,
    "ObservationResult": providers.ObservationResult,
    "ComparisonResult": providers.ComparisonResult,
    "PostReadback": providers.PostReadback,
    "ReconcileResult": providers.ReconcileResult,
    "CommunityEventIn": providers.CommunityEventIn,
    "ActionResult": providers.ActionResult,
    "WebhookVerification": providers.WebhookVerification,
    "MemberPostResult": providers.MemberPostResult,
    "EntitlementCheck": providers.EntitlementCheck,
    "SeasonStepInput": jobs.SeasonStepInput,
    "EpisodeStepInput": jobs.EpisodeStepInput,
    "PlatformPostRef": jobs.PlatformPostRef,
    "CommunityEventRef": jobs.CommunityEventRef,
    "MetricWindowInput": jobs.MetricWindowInput,
    "CommandAccepted": routes.CommandAccepted,
    "ErrorBody": routes.ErrorBody,
    "HealthView": routes.HealthView,
    "ReadinessView": routes.ReadinessView,
    "SeasonProposalSummary": routes.SeasonProposalSummary,
    "SeasonView": routes.SeasonView,
    "EpisodeReviewView": routes.EpisodeReviewView,
    "EventsView": routes.EventsView,
    "CostView": routes.CostView,
    "ReleasesView": routes.ReleasesView,
    "JobEnqueueRequest": routes.JobEnqueueRequest,
    "JobStatusView": routes.JobStatusView,
}

ALL_MODELS: dict[str, type[BaseModel]] = {**CORE_PAYLOADS, **SUPPORTING_PAYLOADS}
