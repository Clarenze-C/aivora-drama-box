"""Fake publisher adapter (T007): one platform, deterministic posts, fixture-only capability.

Submit is deduplicated by ``client_token``; a repeated token returns the same result and
creates nothing. Post state moves SUBMITTED -> PROCESSING -> PUBLISHED_VERIFIED, one step per
``status`` call. Scenarios (consumed by ``submit``):

- ACCEPTED: normal path.
- DENIED_PERMISSION: FAILED, error_code PERMISSION_DENIED, non-transient.
- TOKEN_EXPIRED: FAILED, error_code TOKEN_EXPIRED, non-transient.
- RATE_LIMITED: raises RateLimited with ``retry_after_ms`` in details; nothing created.
- TIMEOUT_CREATED: the post exists but submit raises NeedsReconciliation; ``reconcile`` finds it.
- TIMEOUT_NOT_CREATED: nothing exists; NeedsReconciliation; ``reconcile`` finds nothing.

Capability rules, independent of scenarios: AI_DISCLOSURE UNSUPPORTED or UNKNOWN makes submit
FAILED (UNSUPPORTED_DISCLOSURE / DISCLOSURE_UNVERIFIED) before anything is created. Capability
evidence is always FAKE_FIXTURE, so ``evidence_is_fake_only`` is True.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import ClassVar
from uuid import uuid5

from microdrama.contracts.enums import (
    CapabilityOperation,
    CapabilitySupport,
    DisclosureKind,
    EvidenceSource,
    Platform,
    Provenance,
    ReleaseState,
)
from microdrama.contracts.errors import NeedsReconciliation, NotFound, RateLimited
from microdrama.contracts.hashing import file_sha256
from microdrama.contracts.primitives import EvidenceRef
from microdrama.contracts.providers import PostReadback, ReconcileResult
from microdrama.contracts.release import (
    CapabilityLimits,
    CapabilityRecord,
    PostMetadata,
    PublicationCommand,
    PublishResult,
)
from microdrama.testing.fakes.common import (
    FAKE_NAMESPACE,
    FakeBase,
    FakeClock,
    SequentialIds,
    fake_https,
    stable_digest,
)

DEFAULT_OPERATIONS: dict[CapabilityOperation, CapabilitySupport] = {
    CapabilityOperation.UPLOAD_FULL_VIDEO: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.UPLOAD_SHORT: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.SCHEDULE: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.STATUS: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.READBACK: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.AI_DISCLOSURE: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.DM_SEND: CapabilitySupport.UNSUPPORTED,
}
DEFAULT_ACCOUNT = "acct:fake-main"
RETRY_AFTER_MS = 60_000


class PublishScenario(StrEnum):
    ACCEPTED = "ACCEPTED"
    DENIED_PERMISSION = "DENIED_PERMISSION"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT_CREATED = "TIMEOUT_CREATED"
    TIMEOUT_NOT_CREATED = "TIMEOUT_NOT_CREATED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"


@dataclass
class _Post:
    external_id: str
    client_token: str
    dedupe_key: str
    state: ReleaseState
    disclosures: tuple[DisclosureKind, ...]
    url: str | None = None


class FakePublisherAdapter(FakeBase):
    default_scenario: ClassVar[PublishScenario] = PublishScenario.ACCEPTED

    def __init__(
        self,
        platform: Platform,
        *,
        clock: FakeClock,
        ids: SequentialIds,
        operations: dict[CapabilityOperation, CapabilitySupport] | None = None,
        account_ref: str = DEFAULT_ACCOUNT,
        provider_route: str | None = None,
        version: int = 1,
        enabled: bool = True,
        scenarios: tuple[PublishScenario, ...] = (),
    ) -> None:
        super().__init__(clock=clock, ids=ids, scenarios=scenarios)
        self.platform = platform
        self.provider_route = provider_route or f"fake-{platform.value.lower()}-adapter"
        self.account_ref = account_ref
        self._operations = dict(operations if operations is not None else DEFAULT_OPERATIONS)
        self._version = version
        self._enabled = enabled
        self._posts: dict[str, _Post] = {}
        self._by_token: dict[str, str] = {}
        self._by_dedupe: dict[str, str] = {}
        self.metadata_versions: dict[str, list[PostMetadata]] = {}

    @property
    def _label(self) -> str:
        return self.platform.value.lower()

    def capability(self, account_ref: str) -> CapabilityRecord:
        self._note("capability", key=account_ref)
        ai = self._operations.get(CapabilityOperation.AI_DISCLOSURE, CapabilitySupport.UNKNOWN)
        supported: list[DisclosureKind] = []
        if ai is CapabilitySupport.SUPPORTED_DOCUMENTED or ai is CapabilitySupport.SUPPORTED_TESTED:
            supported = [DisclosureKind.AI_GENERATED_CONTENT, DisclosureKind.SYNTHETIC_VOICE]
        return CapabilityRecord(
            capability_id=uuid5(FAKE_NAMESPACE, f"capability:{self.platform.value}:{account_ref}"),
            version=self._version,
            platform=self.platform,
            provider_route=self.provider_route,
            account_ref=account_ref,
            account_type="fake-channel",
            operations=dict(self._operations),
            limits=CapabilityLimits(),
            supported_disclosures=supported,
            evidence=[
                EvidenceRef(
                    source=EvidenceSource.FAKE_FIXTURE, ref=f"fixture:fake-{self._label}-capability"
                )
            ],  # fmt: skip
            verified_at=self.clock.now(),
            enabled=self._enabled,
        )

    def _result(self, post: _Post) -> PublishResult:
        published = post.state is ReleaseState.PUBLISHED_VERIFIED
        return PublishResult(
            state=post.state,
            external_id=post.external_id,
            url=post.url,
            verified_fields=["title", "ai_disclosure"] if published else [],
            unverified_fields=["thumbnail"] if published else [],
            provenance=Provenance.FAKE_SYNTHETIC,
        )

    def submit(self, command: PublicationCommand, media_path: Path) -> PublishResult:
        if command.client_token in self._by_token:
            self._log_replay("submit", command.client_token)
            return self._result(self._posts[self._by_token[command.client_token]])
        step = self._step("submit", key=command.client_token)
        if step is PublishScenario.RATE_LIMITED:
            raise RateLimited(
                "fake publisher rate limit reached",
                retry_after_ms=RETRY_AFTER_MS,
                client_token=command.client_token,
            )
        if step is PublishScenario.TIMEOUT_NOT_CREATED:
            raise NeedsReconciliation(
                "fake publisher timed out; post not confirmed", client_token=command.client_token
            )
        if step is PublishScenario.DENIED_PERMISSION:
            return PublishResult(state=ReleaseState.FAILED, error_code="PERMISSION_DENIED",
                                 transient=False, provenance=Provenance.FAKE_SYNTHETIC)  # fmt: skip
        if step is PublishScenario.TOKEN_EXPIRED:
            return PublishResult(state=ReleaseState.FAILED, error_code="TOKEN_EXPIRED",
                                 transient=False, provenance=Provenance.FAKE_SYNTHETIC)  # fmt: skip

        ai_support = self._operations.get(
            CapabilityOperation.AI_DISCLOSURE, CapabilitySupport.UNKNOWN
        )
        if DisclosureKind.AI_GENERATED_CONTENT in command.metadata.disclosures:
            if ai_support is CapabilitySupport.UNSUPPORTED:
                return PublishResult(state=ReleaseState.FAILED, error_code="UNSUPPORTED_DISCLOSURE",
                                     transient=False, provenance=Provenance.FAKE_SYNTHETIC)  # fmt: skip
            if ai_support is CapabilitySupport.UNKNOWN:
                return PublishResult(state=ReleaseState.FAILED, error_code="DISCLOSURE_UNVERIFIED",
                                     transient=False, provenance=Provenance.FAKE_SYNTHETIC)  # fmt: skip

        if not Path(media_path).is_file():
            raise NotFound(
                "media file for publishing not found", command_id=str(command.command_id)
            )
        if file_sha256(str(media_path)) != command.asset_sha256:
            return PublishResult(state=ReleaseState.FAILED, error_code="ASSET_HASH_MISMATCH",
                                 transient=False, provenance=Provenance.FAKE_SYNTHETIC)  # fmt: skip

        external_id = f"fake-{self._label}-{stable_digest(command.client_token)}"
        post = _Post(
            external_id=external_id,
            client_token=command.client_token,
            dedupe_key=command.dedupe_key,
            state=ReleaseState.SUBMITTED,
            disclosures=tuple(command.metadata.disclosures),
        )
        self._posts[external_id] = post
        self._by_token[command.client_token] = external_id
        self._by_dedupe[command.dedupe_key] = external_id
        if step is PublishScenario.TIMEOUT_CREATED:
            raise NeedsReconciliation(
                "fake publisher created the post but the response timed out",
                client_token=command.client_token,
            )
        return self._result(post)

    def _require(self, external_id: str) -> _Post:
        post = self._posts.get(external_id)
        if post is None:
            raise NotFound("fake post not found", external_id=external_id)
        return post

    def status(self, command: PublicationCommand, external_id: str) -> PublishResult:
        self._note("status", key=external_id)
        post = self._require(external_id)
        if post.state is ReleaseState.SUBMITTED:
            post.state = ReleaseState.PROCESSING
        elif post.state is ReleaseState.PROCESSING:
            post.state = ReleaseState.PUBLISHED_VERIFIED
            post.url = fake_https(f"{self._label}.fake", f"video/{external_id}")
        return self._result(post)

    def reconcile(self, command: PublicationCommand) -> ReconcileResult:
        self._note("reconcile", key=command.client_token)
        external_id = self._by_token.get(command.client_token) or self._by_dedupe.get(
            command.dedupe_key
        )
        if external_id is None:
            return ReconcileResult(found=False, result=None)
        return ReconcileResult(found=True, result=self._result(self._posts[external_id]))

    def update_metadata(
        self, account_ref: str, external_id: str, metadata: PostMetadata
    ) -> PublishResult:
        self._note("update_metadata", key=external_id)
        post = self._require(external_id)
        self.metadata_versions.setdefault(external_id, []).append(metadata)
        return PublishResult(
            state=post.state,
            external_id=external_id,
            url=post.url,
            unverified_fields=["title"],
            provenance=Provenance.FAKE_SYNTHETIC,
        )

    def readback(self, account_ref: str, external_id: str) -> PostReadback:
        self._note("readback", key=external_id)
        post = self._require(external_id)
        published = post.state is ReleaseState.PUBLISHED_VERIFIED
        disclosures = list(post.disclosures) if published else []
        return PostReadback(
            external_id=external_id,
            visible=True if published else None,
            privacy=None,
            disclosures_visible=disclosures,
            subtitles_present=None,
            links=[post.url] if post.url else [],
            unverified_fields=["privacy", "subtitles_present", "thumbnail"],
            provenance=Provenance.FAKE_SYNTHETIC,
        )


def fake_post_id(platform: Platform, token: str) -> str:
    """The external id a fake post gets for a token (useful for assertions)."""
    return f"fake-{platform.value.lower()}-{stable_digest(token)}"


__all__ = [
    "DEFAULT_ACCOUNT",
    "DEFAULT_OPERATIONS",
    "FakePublisherAdapter",
    "PublishScenario",
    "fake_post_id",
]
