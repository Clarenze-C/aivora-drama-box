"""Frozen route research snapshot for the Patreon membership backend (T026).

Patreon is the ONE selected verified backend behind the frozen ``MembershipProvider``
protocol (SPEC §10: "an explicitly selected verified Patreon or Buy Me a Coffee route …
Alternate membership backend can remain optional after one working route"). Buy Me a
Coffee stays the documented optional alternate (``BMC_ALTERNATE_NOTE``); it is not
implemented, enabled or half-claimed here.

Every support value below is sourced from OFFICIAL_DOCUMENTATION only, snapshotted
**from the implementer's knowledge as of 2026-10 and NOT re-fetched during this task**
(the offline network guard is active by design). T032 must re-verify every ref and
figure against the live documentation before any live route is enabled. No controlled
account test has run, so no operation is SUPPORTED_TESTED and the research snapshot
ships ``enabled=False``: a documentation claim is not a live account fact. The
OFFLINE_MOCK factory builds a FAKE_FIXTURE variant from the same snapshot so the
membership service runs end-to-end offline over the T007 fake.

Honest unknowns encoded here:

- ``early_access_publish`` is UNKNOWN: creating member posts through a public Patreon
  API is not documented. Member early-access delivery is a creator-tool surface, so
  the OFFLINE fixture models the member post (the T007 fake) while any live route
  must first be qualified at T032 — the adapter's live transport is a named refusal
  until then.
- The webhook signature scheme below is the documented ``X-Patreon-Signature`` header
  (an HMAC digest of the raw body with the creator's webhook secret). The exact
  digest algorithm has changed across Patreon API versions; the offline fixture uses
  HMAC-SHA256 per the T007 fake, and the live mapping must be re-verified at T032.
- The recurring price shown to buyers comes from the configured tier/campaign
  definition. The adapter reports it truthfully and never invents or rounds a price.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import Field, model_validator

from microdrama.contracts.enums import CapabilitySupport, EvidenceSource, MembershipProviderKind
from microdrama.contracts.primitives import (
    ContractModel,
    EvidenceRef,
    Identifier,
    ShortText,
    UtcDateTime,
)

PROVIDER_ROUTE = "patreon-api-v3"
#: Snapshot date of every documentation claim below (mirrored in each ref string).
RESEARCH_AS_OF = datetime(2026, 10, 22, tzinfo=UTC)
_AS_OF = "as of 2026-10"

#: Buy Me a Coffee is the documented OPTIONAL alternate backend (SPEC §10). One
#: working route is required; enabling BMC is a T032 owner decision, never implied.
BMC_ALTERNATE_NOTE = (
    "Buy Me a Coffee remains the documented optional alternate membership backend. "
    "It is not implemented by T026: the original requirement is Patreon and/or BMC, "
    "and exactly one working route (Patreon) is selected. Enabling BMC requires its "
    "own T032 controlled test evidence; nothing here claims anything about BMC "
    "capabilities."
)

#: Route-level operation ids (local to this lane; ``CapabilityOperation`` is a
#: publishing/platform enum and has no membership entries — deliberately not extended).
OP_ENTITLEMENT_CHECK = "membership.entitlement_check"
OP_WEBHOOK_VERIFY = "membership.webhook_verify"
OP_EARLY_ACCESS_PUBLISH = "membership.early_access_publish"


def _doc_ref(path: str, note: str) -> EvidenceRef:
    return EvidenceRef(
        source=EvidenceSource.OFFICIAL_DOCUMENTATION, ref=f"https://{path} ({_AS_OF})", note=note
    )


RESEARCH_EVIDENCE: tuple[EvidenceRef, ...] = (
    _doc_ref(
        "docs.patreon.com/api/oauth2/v3",
        "Patreon API v3 (OAuth2) is the documented surface for campaign/member lookups; "
        "member identity and currently-entitled tiers back ENTITLEMENT_CHECK",
    ),
    _doc_ref(
        "docs.patreon.com/api/webhooks",
        "creator webhooks (member pledge create/update/delete among others) delivered "
        "with an HMAC signature header over the raw body; the documented header is "
        "X-Patreon-Signature and the digest algorithm must be re-verified at T032",
    ),
    _doc_ref(
        "docs.patreon.com/api/webhooks",
        "webhook payloads carry a documented event id usable for at-least-once dedupe; "
        "payloads are untrusted until the signature verifies",
    ),
    _doc_ref(
        "www.patreon.com/create/post",
        "member posts (early-access media) are created through creator tools; a public "
        "API for post creation is not documented, so early-access publishing is UNKNOWN "
        "on the API route and any live route needs T032 controlled-test evidence",
    ),
    _doc_ref(
        "www.patreon.com/setup-tier-pricing",
        "the recurring price buyers see comes from the configured tier definition; the "
        "adapter reports the configured price truthfully and never invents one",
    ),
)

#: Documentation-sourced support only. SUPPORTED_TESTED is absent by construction
#: (no controlled account test has run — T032).
RESEARCH_OPERATIONS: dict[str, CapabilitySupport] = {
    OP_ENTITLEMENT_CHECK: CapabilitySupport.SUPPORTED_DOCUMENTED,
    OP_WEBHOOK_VERIFY: CapabilitySupport.SUPPORTED_DOCUMENTED,
    OP_EARLY_ACCESS_PUBLISH: CapabilitySupport.UNKNOWN,
}


class MembershipRouteSnapshot(ContractModel):
    """Per-route capability snapshot. Research-date claims are not live evidence.

    Local to the memberships lane: ``CapabilityRecord`` is pinned to the publishing
    ``Platform`` enum (which has no Patreon value), so this smaller frozen snapshot
    carries the same evidence discipline without a contract change.
    """

    route_id: Identifier
    kind: MembershipProviderKind
    operations: dict[Identifier, CapabilitySupport]
    evidence: list[EvidenceRef]
    verified_at: UtcDateTime | None = None
    enabled: bool = False
    account_type: ShortText = "creator-campaign-unverified"
    notes: list[ShortText] = Field(default_factory=list)

    @model_validator(mode="after")
    def _enabled_needs_evidence(self) -> MembershipRouteSnapshot:
        if self.enabled:
            if not self.evidence or self.verified_at is None:
                raise ValueError("an enabled route snapshot needs evidence and verified_at")
        tested = any(s is CapabilitySupport.SUPPORTED_TESTED for s in self.operations.values())
        if tested and not any(
            e.source is EvidenceSource.CONTROLLED_ACCOUNT_TEST for e in self.evidence
        ):
            raise ValueError("SUPPORTED_TESTED needs CONTROLLED_ACCOUNT_TEST evidence")
        return self


def research_snapshot() -> MembershipRouteSnapshot:
    """The disabled documentation snapshot (the shipped default).

    ``enabled=False``: the live membership route stays off until a controlled test
    (T032) produces evidence that can enable it. Nothing offline may flip this.
    """
    return MembershipRouteSnapshot(
        route_id=PROVIDER_ROUTE,
        kind=MembershipProviderKind.PATREON,
        operations=dict(RESEARCH_OPERATIONS),
        evidence=list(RESEARCH_EVIDENCE),
        verified_at=RESEARCH_AS_OF,
        enabled=False,
        notes=[
            "snapshot from implementer knowledge as of 2026-10; refs NOT re-fetched offline",
            BMC_ALTERNATE_NOTE,
        ],
    )


def fixture_snapshot(*, verified_at: datetime, enabled: bool = True) -> MembershipRouteSnapshot:
    """The OFFLINE_MOCK variant: FAKE_FIXTURE evidence only, fixture operations.

    Fixture data may not carry real evidence sources: outside OFFLINE_MOCK a
    fake-only snapshot is unknown/disabled. Operations stay SUPPORTED_DOCUMENTED at
    most — a fixture run is not a controlled account test.
    """
    return MembershipRouteSnapshot(
        route_id=PROVIDER_ROUTE,
        kind=MembershipProviderKind.PATREON,
        operations=dict(RESEARCH_OPERATIONS),
        evidence=[
            EvidenceRef(
                source=EvidenceSource.FAKE_FIXTURE, ref=f"fixture:patreon-route:{PROVIDER_ROUTE}"
            )
        ],
        verified_at=verified_at,
        enabled=enabled,
        account_type="fixture-creator-campaign",
        notes=[BMC_ALTERNATE_NOTE],
    )


__all__ = [
    "BMC_ALTERNATE_NOTE",
    "MembershipRouteSnapshot",
    "OP_EARLY_ACCESS_PUBLISH",
    "OP_ENTITLEMENT_CHECK",
    "OP_WEBHOOK_VERIFY",
    "PROVIDER_ROUTE",
    "RESEARCH_AS_OF",
    "RESEARCH_EVIDENCE",
    "RESEARCH_OPERATIONS",
    "fixture_snapshot",
    "research_snapshot",
]
