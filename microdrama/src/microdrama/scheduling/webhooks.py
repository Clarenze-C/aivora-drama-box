"""Inbound webhook routes (T029; the W10 surface, coded in-app).

Provider webhooks are UNTRUSTED input (AT-13): every route records the raw
event in the deduplicated ``webhook_events`` table before anything else, never
trusts payload claims, and hands verification to the owning service:

- membership provider webhooks (T026) go straight to
  ``EntitlementService.process_webhook`` — verify → dedupe → interpret, with an
  invalid signature stopping at verification (no row, no interpretation);
- platform/community webhooks are RECORDED ONLY in this build: the community
  lane ingests by provider polling, and verified inbound push handling is T032
  account qualification. Recording keeps the receipt auditable without acting
  on unverified content.

No secret, capability or business decision lives in a route.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from microdrama.contracts.enums import MembershipProviderKind
from microdrama.persistence.db import Tx, insert_row, jsonb


def build_webhook_router(db, *, memberships_service=None) -> APIRouter:
    """Routes for inbound provider webhooks. ``memberships_service`` is the T026
    ``MembershipServices`` bundle; without it membership webhooks 503 (not configured)."""
    router = APIRouter(tags=["webhooks"])

    @router.post("/webhooks/membership/{provider}", status_code=202)
    async def membership_webhook(provider: str, request: Request) -> dict[str, Any]:
        body = await request.body()
        headers = {k.lower(): v for k, v in request.headers.items()}
        if memberships_service is None:
            return {"status": "NOT_CONFIGURED", "mock": True}
        try:
            MembershipProviderKind(provider.upper())
        except ValueError:
            return {"status": "UNKNOWN_PROVIDER", "mock": True}
        outcome = memberships_service.entitlements.process_webhook(headers, body)
        return {
            "status": "PROCESSED" if outcome.valid else "INVALID_SIGNATURE",
            "duplicate": getattr(outcome, "duplicate", False),
            "mock": True,
        }

    @router.post("/webhooks/community/{platform}", status_code=202)
    async def community_webhook(platform: str, request: Request) -> dict[str, Any]:
        """Record the untrusted event; community ingest stays provider-pulled (T032 may
        wire verified push). The dedupe key is the provider's own event id."""
        body = await request.body()
        headers = {k.lower(): v for k, v in request.headers.items()}
        try:
            payload = jsonb(_bounded_json(body))
        except ValueError:
            return {"status": "UNPARSEABLE", "mock": True}
        provider_event_id = headers.get("x-provider-event-id") or ""
        if not provider_event_id:
            return {"status": "MISSING_EVENT_ID", "mock": True}
        with db.transaction() as tx:
            _record_webhook_event(
                tx,
                provider=f"community:{platform}",
                event_id=provider_event_id,
                signature_valid=False,  # unverified in this build; T032 verifies
                payload=payload,
            )
        return {"status": "RECORDED", "verified": False, "mock": True}

    return router


def _record_webhook_event(
    tx: Tx, *, provider: str, event_id: str, signature_valid: bool, payload
) -> bool:
    """Insert unless the (provider, event_id) pair exists. True when new."""
    existing = tx.fetchone(
        "SELECT id FROM webhook_events WHERE provider = %s AND event_id = %s",
        (provider, event_id),
    )
    if existing is not None:
        return False
    insert_row(
        tx,
        "webhook_events",
        {
            "id": _new_id(),
            "provider": provider,
            "event_id": event_id,
            "signature_valid": signature_valid,
            "payload": payload,
        },
    )
    return True


def _bounded_json(body: bytes):
    import json

    if len(body) > 65_536:
        raise ValueError("webhook body exceeds 64 KiB")
    return json.loads(body.decode("utf-8"))


def _new_id():
    from uuid import uuid4

    return uuid4()


__all__ = ["build_webhook_router"]
