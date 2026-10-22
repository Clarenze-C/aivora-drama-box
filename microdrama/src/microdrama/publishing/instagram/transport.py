"""Instagram Graph API transport surface (T023): documented edges + ONE offline fixture.

The :class:`InstagramTransport` protocol abstracts the documented Instagram
content-publishing surface for professional accounts (Business/Creator linked to a
Facebook Page; personal accounts cannot use the publishing API):

- ``GET /{ig-user-id}?fields=account_type,username``   — account facts
- ``POST /{ig-user-id}/media``                         — media container create
- ``GET /{container-id}?fields=status_code``           — container processing status
  (documented values: ``in_progress`` / ``finished`` / ``error`` / ``expired``)
- ``POST /{ig-user-id}/media_publish``                 — publish a finished container
- ``GET /{ig-media-id}?fields=id,caption,...,permalink`` — published media readback
- ``POST /{ig-media-id}``                              — caption update (images only)
- ``GET /{ig-media-id}/insights``                      — media metrics

ONE offline implementation ships here: :class:`FixtureInstagramTransport`, a
deterministic fixture transport driven by a scenario queue (mirrors the T007
``FakeBase``/``ScenarioQueue`` machinery — ``FAKE_SYNTHETIC`` provenance, URLs only
under ``https://*.invalid`` via ``fake_https``, deterministic external ids via
``stable_digest``). No live HTTP transport ships in this lane:
:class:`RefusingInstagramTransport` raises ``PolicyDenied`` ("live publishing
disabled until T032") on every documented edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, Protocol, runtime_checkable
from uuid import UUID

from microdrama.contracts.errors import (
    MicrodramaError,
    NeedsReconciliation,
    NotFound,
    PolicyDenied,
    RateLimited,
)
from microdrama.testing.fakes.common import (
    FakeBase,
    FakeClock,
    SequentialIds,
    fake_https,
    stable_digest,
)

LIVE_DISABLED_MESSAGE = "live publishing disabled until T032"

#: Documented Graph API error codes this lane maps (official error reference).
GRAPH_CODE_PERMISSION_DENIED = 10  # permission denied / not a professional account
GRAPH_CODE_TOKEN_INVALID = 190  # access token invalid or expired
GRAPH_CODE_THROTTLED = 4  # application request limit reached


class InstagramScenario(StrEnum):
    """Scripted platform outcomes (the frozen T020 scenario matrix + container ends)."""

    ACCEPTED = "ACCEPTED"
    DENIED_PERMISSION = "DENIED_PERMISSION"  # Graph error code 10
    TOKEN_EXPIRED = "TOKEN_EXPIRED"  # Graph error code 190
    RATE_LIMITED = "RATE_LIMITED"  # Graph error code 4 (throttled)
    TIMEOUT_CREATED = "TIMEOUT_CREATED"  # container created, response timed out
    TIMEOUT_NOT_CREATED = "TIMEOUT_NOT_CREATED"  # nothing created, timed out
    CONTAINER_ERROR = "CONTAINER_ERROR"  # container status_code -> error
    CONTAINER_EXPIRED = "CONTAINER_EXPIRED"  # container status_code -> expired


class ContainerKind(StrEnum):
    """Documented ``media_type`` values of the container-create edge this lane uses."""

    VIDEO = "VIDEO"  # feed video container
    REELS = "REELS"  # reels container


class InstagramAccountType(StrEnum):
    """Documented ``account_type`` values on the Instagram user node."""

    PERSONAL = "PERSONAL"  # not a professional account: the publishing API refuses
    BUSINESS = "BUSINESS"  # professional
    MEDIA_CREATOR = "MEDIA_CREATOR"  # professional (Creator)


PROFESSIONAL_ACCOUNT_TYPES = frozenset(
    {InstagramAccountType.BUSINESS, InstagramAccountType.MEDIA_CREATOR}
)

#: Documented metric names on the media insights edge (fixture stand-in values).
DOCUMENTED_INSIGHT_METRICS: tuple[str, ...] = (
    "impressions",
    "reach",
    "likes",
    "comments",
    "saved",
    "shares",
    "video_views",
)

#: Fixture stand-in for the documented throttle response (code 4 / usage headers).
FIXTURE_RETRY_AFTER_MS = 60_000


class GraphApiError(MicrodramaError):
    """A documented Graph API error payload (``code`` / ``error_subcode`` / message)."""

    code = "GRAPH_API_ERROR"

    def __init__(self, *, graph_code: int, message: str, subcode: int | None = None) -> None:
        super().__init__(message, graph_code=graph_code, error_subcode=subcode)
        self.graph_code = graph_code
        self.subcode = subcode


@dataclass(frozen=True)
class InstagramAccount:
    account_ref: str
    account_type: InstagramAccountType
    username: str = ""

    @property
    def is_professional(self) -> bool:
        return self.account_type in PROFESSIONAL_ACCOUNT_TYPES


#: Default mock account the offline factory registers (professional Business fixture).
DEFAULT_ACCOUNT_REF = "acct:instagram-main"

DEFAULT_FIXTURE_ACCOUNTS: dict[str, InstagramAccount] = {
    DEFAULT_ACCOUNT_REF: InstagramAccount(
        account_ref=DEFAULT_ACCOUNT_REF,
        account_type=InstagramAccountType.BUSINESS,
        username="microdrama.fixture",
    )
}

#: A personal-account fixture entry (the documented refusal case), off by default.
PERSONAL_ACCOUNT_REF = "acct:instagram-personal"
PERSONAL_FIXTURE_ACCOUNT = InstagramAccount(
    account_ref=PERSONAL_ACCOUNT_REF,
    account_type=InstagramAccountType.PERSONAL,
    username="microdrama.personal",
)


@dataclass(frozen=True)
class ContainerCreateRequest:
    """What the adapter sends to ``POST /{ig-user-id}/media`` (documented fields)."""

    media_type: ContainerKind
    video_url: str
    caption: str
    client_token: str
    cover_url: str | None = None
    share_to_feed: bool | None = None
    asset_id: UUID | None = None


class ContainerStatusCode(StrEnum):
    """Documented ``status_code`` values of the container status edge."""

    IN_PROGRESS = "in_progress"
    FINISHED = "finished"
    ERROR = "error"
    EXPIRED = "expired"


@dataclass(frozen=True)
class ContainerState:
    container_id: str
    status_code: ContainerStatusCode


@dataclass(frozen=True)
class MediaReadback:
    """Fields read back from the documented media node (no disclosure field exists)."""

    media_id: str
    caption: str
    media_type: ContainerKind
    permalink: str
    username: str


@dataclass(frozen=True)
class InsightsSummary:
    metric_names: tuple[str, ...]


def instagram_container_id(client_token: str) -> str:
    """Deterministic fixture container id for a client token (assertion helper)."""
    return f"igc-{stable_digest('container', client_token)}"


def instagram_media_id(client_token: str) -> str:
    """Deterministic fixture media id for a client token (assertion helper)."""
    return f"igm-{stable_digest('media', client_token)}"


@runtime_checkable
class InstagramTransport(Protocol):
    """The documented Graph surface this lane speaks. A transport never approves,
    budgets or gates anything; it only speaks the platform."""

    def account(self, account_ref: str) -> InstagramAccount: ...

    def create_container(
        self, account_ref: str, request: ContainerCreateRequest
    ) -> ContainerState: ...

    def container_status(self, container_id: str) -> ContainerState: ...

    def publish_container(self, container_id: str) -> str:
        """Publish a container whose status was observed ``finished``; returns media id."""
        ...

    def media(self, media_id: str) -> MediaReadback: ...

    def update_caption(self, media_id: str, caption: str) -> None: ...

    def insights(self, media_id: str) -> InsightsSummary: ...


class RefusingInstagramTransport:
    """The only non-fixture transport in this lane: every documented edge refuses.

    T031/T032 replace this with a real authenticated transport after controlled
    account tests; until then there is deliberately no live HTTP path.
    """

    def account(self, account_ref: str) -> InstagramAccount:
        raise PolicyDenied(LIVE_DISABLED_MESSAGE, edge="account")

    def create_container(self, account_ref: str, request: ContainerCreateRequest) -> ContainerState:
        raise PolicyDenied(LIVE_DISABLED_MESSAGE, edge="create_container")

    def container_status(self, container_id: str) -> ContainerState:
        raise PolicyDenied(LIVE_DISABLED_MESSAGE, edge="container_status")

    def publish_container(self, container_id: str) -> str:
        raise PolicyDenied(LIVE_DISABLED_MESSAGE, edge="publish_container")

    def media(self, media_id: str) -> MediaReadback:
        raise PolicyDenied(LIVE_DISABLED_MESSAGE, edge="media")

    def update_caption(self, media_id: str, caption: str) -> None:
        raise PolicyDenied(LIVE_DISABLED_MESSAGE, edge="update_caption")

    def insights(self, media_id: str) -> InsightsSummary:
        raise PolicyDenied(LIVE_DISABLED_MESSAGE, edge="insights")


@dataclass
class _ContainerFixture:
    request: ContainerCreateRequest
    username: str
    status_code: ContainerStatusCode = ContainerStatusCode.IN_PROGRESS


@dataclass
class _MediaFixture:
    media_id: str
    container_id: str
    caption: str
    media_type: ContainerKind
    username: str
    permalink: str


class FixtureInstagramTransport(FakeBase):
    """Deterministic offline stand-in for the documented Graph surface.

    Behaviour mirrors the T007 fake publisher: one scripted scenario step per
    mutating call (``create_container`` consumes the submit scenarios,
    ``container_status`` consumes the container-end scenarios; both fall back to
    ACCEPTED once the script is exhausted); reads only record a call. Container
    processing advances asynchronously-in-fiction: the first status observation of
    an ``in_progress`` container flips it to ``finished`` behind the scenes, so the
    documented flow needs submit -> poll (still processing) -> poll (finished) ->
    publish. External ids are deterministic hashes of the client token; every URL
    lives under ``https://*.invalid``.
    """

    default_scenario: ClassVar[InstagramScenario] = InstagramScenario.ACCEPTED

    def __init__(
        self,
        *,
        clock: FakeClock,
        ids: SequentialIds,
        scenarios: tuple[InstagramScenario, ...] = (),
        accounts: dict[str, InstagramAccount] | None = None,
    ) -> None:
        super().__init__(clock=clock, ids=ids, scenarios=scenarios)
        self.accounts: dict[str, InstagramAccount] = dict(
            accounts if accounts is not None else DEFAULT_FIXTURE_ACCOUNTS
        )
        self.containers: dict[str, _ContainerFixture] = {}
        self.media_by_id: dict[str, _MediaFixture] = {}
        self.create_container_calls = 0
        self.publish_calls = 0

    # --- account edge -------------------------------------------------------------------

    def account(self, account_ref: str) -> InstagramAccount:
        """Unknown accounts are modelled as the default professional mock account."""
        self._note("account", key=account_ref)
        known = self.accounts.get(account_ref)
        if known is not None:
            return known
        return InstagramAccount(
            account_ref=account_ref,
            account_type=InstagramAccountType.BUSINESS,
            username="microdrama.fixture",
        )

    # --- container create / status / publish --------------------------------------------

    def create_container(self, account_ref: str, request: ContainerCreateRequest) -> ContainerState:
        step = self._step("create_container", key=request.client_token)
        if step is InstagramScenario.RATE_LIMITED:
            raise RateLimited(
                "fixture throttle: documented code 4 application request limit",
                retry_after_ms=FIXTURE_RETRY_AFTER_MS,
                client_token=request.client_token,
            )
        if step is InstagramScenario.TIMEOUT_NOT_CREATED:
            raise NeedsReconciliation(
                "fixture timeout before the container was created",
                client_token=request.client_token,
            )
        if step is InstagramScenario.DENIED_PERMISSION:
            raise GraphApiError(
                graph_code=GRAPH_CODE_PERMISSION_DENIED,
                message=(
                    "fixture refusal: (#10) permission denied — the app lacks "
                    "instagram_content_publish or the account is not professional"
                ),
            )
        if step is InstagramScenario.TOKEN_EXPIRED:
            raise GraphApiError(
                graph_code=GRAPH_CODE_TOKEN_INVALID,
                message="fixture refusal: (#190) access token invalid or expired",
            )

        container_id = instagram_container_id(request.client_token)
        self.containers[container_id] = _ContainerFixture(
            request=request, username=self.account(account_ref).username
        )
        self.create_container_calls += 1
        if step is InstagramScenario.TIMEOUT_CREATED:
            # The creation is knowable afterwards by inspecting the account: the
            # fixture carries the container id in the exception details.
            raise NeedsReconciliation(
                "fixture timeout after the container was created",
                client_token=request.client_token,
                container_id=container_id,
            )
        return ContainerState(container_id, ContainerStatusCode.IN_PROGRESS)

    def container_status(self, container_id: str) -> ContainerState:
        step = self._step("container_status", key=container_id)
        fixture = self._require_container(container_id)
        if step is InstagramScenario.CONTAINER_ERROR:
            fixture.status_code = ContainerStatusCode.ERROR
        elif step is InstagramScenario.CONTAINER_EXPIRED:
            fixture.status_code = ContainerStatusCode.EXPIRED
        elif fixture.status_code is ContainerStatusCode.IN_PROGRESS:
            # Processing completes right AFTER this observation (deterministic:
            # this call observes in_progress, the NEXT one observes finished).
            fixture.status_code = ContainerStatusCode.FINISHED
            return ContainerState(container_id, ContainerStatusCode.IN_PROGRESS)
        return ContainerState(container_id, fixture.status_code)

    def publish_container(self, container_id: str) -> str:
        self._note("publish_container", key=container_id)
        fixture = self._require_container(container_id)
        for existing in self.media_by_id.values():
            if existing.container_id == container_id:
                raise GraphApiError(
                    graph_code=0,
                    message="fixture refusal: this container was already published",
                )
        if fixture.status_code is not ContainerStatusCode.FINISHED:
            raise GraphApiError(
                graph_code=0,
                message=(
                    "fixture refusal: media_publish before the container status was "
                    "observed finished; poll status_code first"
                ),
            )
        media_id = instagram_media_id(fixture.request.client_token)
        self.media_by_id[media_id] = _MediaFixture(
            media_id=media_id,
            container_id=container_id,
            caption=fixture.request.caption,
            media_type=fixture.request.media_type,
            username=fixture.username,
            permalink=fake_https("instagram", f"p/{media_id}"),
        )
        self.publish_calls += 1
        return media_id

    # --- media edges --------------------------------------------------------------------

    def media(self, media_id: str) -> MediaReadback:
        self._note("media", key=media_id)
        fixture = self.media_by_id.get(media_id)
        if fixture is None:
            raise NotFound("fixture media not found", media_id=media_id)
        return MediaReadback(
            media_id=fixture.media_id,
            caption=fixture.caption,
            media_type=fixture.media_type,
            permalink=fixture.permalink,
            username=fixture.username,
        )

    def update_caption(self, media_id: str, caption: str) -> None:
        self._note("update_caption", key=media_id)
        if media_id not in self.media_by_id:
            raise NotFound("fixture media not found", media_id=media_id)
        # Documented constraint: caption update is available for image media only;
        # every container this lane publishes is video (VIDEO or REELS).
        raise GraphApiError(
            graph_code=0,
            message="fixture refusal: caption update is documented for image media only",
        )

    def insights(self, media_id: str) -> InsightsSummary:
        self._note("insights", key=media_id)
        if media_id not in self.media_by_id:
            raise NotFound("fixture media not found", media_id=media_id)
        return InsightsSummary(metric_names=DOCUMENTED_INSIGHT_METRICS)

    # --- helpers ------------------------------------------------------------------------

    def _require_container(self, container_id: str) -> _ContainerFixture:
        fixture = self.containers.get(container_id)
        if fixture is None:
            raise NotFound("fixture container not found", container_id=container_id)
        return fixture


__all__ = [
    "DEFAULT_ACCOUNT_REF",
    "DEFAULT_FIXTURE_ACCOUNTS",
    "DOCUMENTED_INSIGHT_METRICS",
    "FIXTURE_RETRY_AFTER_MS",
    "FixtureInstagramTransport",
    "GRAPH_CODE_PERMISSION_DENIED",
    "GRAPH_CODE_THROTTLED",
    "GRAPH_CODE_TOKEN_INVALID",
    "GraphApiError",
    "InstagramAccount",
    "InstagramAccountType",
    "InstagramScenario",
    "InstagramTransport",
    "LIVE_DISABLED_MESSAGE",
    "PERSONAL_ACCOUNT_REF",
    "PERSONAL_FIXTURE_ACCOUNT",
    "PROFESSIONAL_ACCOUNT_TYPES",
    "RefusingInstagramTransport",
    "instagram_container_id",
    "instagram_media_id",
]
