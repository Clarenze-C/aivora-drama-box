"""Fake membership provider and webhook verifier (T007).

Webhooks are signed with HMAC-SHA256 over the raw body using ``FAKE_WEBHOOK_SECRET``, a constant named
for what it is. Verification rules, in order:

1. no ``x-fake-signature`` header -> invalid (MISSING_SIGNATURE);
2. signature mismatch (constant-time compare) -> invalid (SIGNATURE_MISMATCH);
3. body is not a JSON object with a string ``id`` -> invalid (MALFORMED_BODY / MISSING_EVENT_ID).

An invalid webhook never carries its payload on. Valid duplicates are returned as valid: dedupe belongs
to the consumer.

Entitlement scenarios: ACTIVE, REVOKED, UNVERIFIABLE (``active=None``, which must never be treated as
entitled). Early-access publication is only accepted for ``EARLY_ACCESS_MEMBERS`` catalog entries.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

from microdrama.contracts.catalog import MembershipCatalogEntry
from microdrama.contracts.enums import CatalogPublicState, MembershipProviderKind, Provenance
from microdrama.contracts.errors import NotFound, PolicyDenied
from microdrama.contracts.providers import EntitlementCheck, MemberPostResult, WebhookVerification
from microdrama.testing.fakes.common import (
    FakeBase,
    FakeClock,
    SequentialIds,
    fake_https,
    stable_digest,
)

FAKE_WEBHOOK_SECRET = b"fake-test-only-secret-not-for-production"
SIGNATURE_HEADER = "x-fake-signature"
FAKE_TIER = "fake-supporter"


class EntitlementScenario(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    UNVERIFIABLE = "UNVERIFIABLE"


def fake_signature(body: bytes) -> str:
    """The signature a genuine (fake) sender would attach to ``body``."""
    return hmac.new(FAKE_WEBHOOK_SECRET, body, hashlib.sha256).hexdigest()


class FakeWebhookVerifier:
    """Signature-checking verifier. Does not dedupe; every valid delivery is reported."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        self.calls: list[str] = []

    def _invalid(self, reason: str) -> WebhookVerification:
        return WebhookVerification(valid=False, provider=self.provider, failure_reason=reason)

    def verify(self, headers: Mapping[str, str], body: bytes) -> WebhookVerification:
        self.calls.append(f"verify:{len(body)}")
        lowered = {key.lower(): value for key, value in headers.items()}
        signature = lowered.get(SIGNATURE_HEADER)
        if signature is None:
            return self._invalid("MISSING_SIGNATURE")
        if not hmac.compare_digest(signature, fake_signature(body)):
            return self._invalid("SIGNATURE_MISMATCH")
        try:
            payload = json.loads(body)
        except ValueError:
            return self._invalid("MALFORMED_BODY")
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("id"), str)
            or not payload["id"]
        ):
            return self._invalid("MISSING_EVENT_ID")
        event_type = payload.get("type")
        return WebhookVerification(
            valid=True,
            provider=self.provider,
            event_id=payload["id"],
            event_type=event_type if isinstance(event_type, str) and event_type else None,
            payload=payload,
        )


class FakeMembershipProvider(FakeBase):
    default_scenario: ClassVar[EntitlementScenario] = EntitlementScenario.ACTIVE

    def __init__(
        self,
        kind: MembershipProviderKind,
        *,
        clock: FakeClock,
        ids: SequentialIds,
        scenarios: tuple[EntitlementScenario, ...] = (),
    ) -> None:
        super().__init__(clock=clock, ids=ids, scenarios=scenarios)
        self.kind = kind
        self.verifier = FakeWebhookVerifier(f"fake-{kind.value.lower()}")
        self._posts: dict[str, MemberPostResult] = {}

    def publish_early_access(
        self, entry: MembershipCatalogEntry, media_path: Path
    ) -> MemberPostResult:
        if entry.public_state is not CatalogPublicState.EARLY_ACCESS_MEMBERS:
            raise PolicyDenied(
                "only EARLY_ACCESS_MEMBERS catalog entries can be published to members",
                public_state=entry.public_state.value,
            )
        key = str(entry.entry_id)
        if key in self._posts:
            self._log_replay("publish_early_access", key)
            return self._posts[key]
        if not Path(media_path).is_file():
            raise NotFound("media file for member post not found", entry_id=key)
        self._note("publish_early_access", key=key)
        post_id = f"fake-member-{stable_digest(key)}"
        result = MemberPostResult(
            member_post_id=post_id,
            member_url=fake_https("members.fake", f"posts/{entry.episode_number}/{post_id}"),
            provenance=Provenance.FAKE_SYNTHETIC,
        )
        self._posts[key] = result
        return result

    def check_entitlement(self, member_ref: str, entry: MembershipCatalogEntry) -> EntitlementCheck:
        step = self._step("check_entitlement", key=member_ref)
        now = self.clock.now()
        if step is EntitlementScenario.ACTIVE:
            active: bool | None = True
            tier: str | None = FAKE_TIER
        elif step is EntitlementScenario.REVOKED:
            active, tier = False, None
        else:
            active, tier = None, None  # could not verify: never treated as entitled
        return EntitlementCheck(
            member_ref=member_ref,
            active=active,
            tier=tier,
            verified_at=now,
            provenance=Provenance.FAKE_SYNTHETIC,
        )

    def verify_webhook(self, headers: Mapping[str, str], body: bytes) -> WebhookVerification:
        return self.verifier.verify(headers, body)


__all__ = [
    "EntitlementScenario",
    "FAKE_TIER",
    "FAKE_WEBHOOK_SECRET",
    "FakeMembershipProvider",
    "FakeWebhookVerifier",
    "SIGNATURE_HEADER",
    "fake_signature",
]
