"""Lane-scoped worker deployments for the composed runtime (build-review F04/F05).

One deployment per lane — production, publication, community — so each lane's
worker capacity is structurally separate: a slow FFmpeg/model call inside the
production lane, or a stuck community handler, can never consume the slot a due
publication needs, and the janitors never queue behind either (they stay
independent timer actions in the scheduler). Each deployment binds its
provider-bound job types to the shared per-account limiter key, and a limiter
configured without those bindings refuses to build.

Bindings derive trusted keys from durable state, never from untrusted input
alone: publication keys come from the slot's platform and account (submit) or
the stored post row (poll/reconcile), community keys from the stored community
event or the management action's own platform/account fields.
"""

from __future__ import annotations

from typing import Any

from microdrama.contracts.enums import QueueName
from microdrama.core.jobs import Job
from microdrama.workers.limiter import limiter_key
from microdrama.workers.runtime import QueueSlots, WorkerDeployment

#: Declared isolation bound: a blocked lane must not delay another lane's cycle
#: beyond this. Enforced by the isolation test, not by a timer.
LANE_ISOLATION_BOUND_MS = 10_000


def _post_key(world) -> Any:
    def resolve(job: Job) -> str:
        with world.db.transaction(readonly=True) as tx:
            post = tx.fetchone(
                "SELECT platform, account_ref FROM platform_posts WHERE id = %s",
                (job.input.get("platform_post_id"),),
            )
        if post is None:
            raise LookupError(
                f"limiter binding: post {job.input.get('platform_post_id')} not found"
            )
        return limiter_key(str(post["platform"]), str(post["account_ref"]))

    return resolve


def _submit_slot_key(job: Job) -> str:
    slot = job.input.get("slot") or {}
    return limiter_key(str(slot.get("platform")), str(slot.get("account_ref")))


def _community_event_key(world) -> Any:
    def resolve(job: Job) -> str:
        with world.db.transaction(readonly=True) as tx:
            event = tx.fetchone(
                "SELECT platform, account_ref FROM community_events WHERE id = %s",
                (job.input.get("community_event_id"),),
            )
        if event is None:
            raise LookupError(
                f"limiter binding: community event {job.input.get('community_event_id')} not found"
            )
        return limiter_key(str(event["platform"]), str(event["account_ref"]))

    return resolve


def _management_action_key(job: Job) -> str:
    return limiter_key(str(job.input.get("platform")), str(job.input.get("account_ref")))


def lane_bindings(world) -> dict[str, Any]:
    """Shared-bucket bindings for every provider-bound job type (F04)."""
    return {
        "publish.submit_slot": _submit_slot_key,
        "publish.poll_status": _post_key(world),
        "publish.reconcile_slot": _post_key(world),
        "community.ingest_event": _community_event_key(world),
        "community.respond": _management_action_key,
        "community.deliver_dm": _management_action_key,
        "community.optimize_metadata": _post_key(world),
    }


def lane_deployments(world, handlers) -> dict[str, WorkerDeployment]:
    """One deployment per lane, each with its own reserved slots and the shared limiter.

    ``world.runtime_for(deployment)`` builds each lane's runtime; the lanes run
    as separate worker processes (each ``run_cycle`` here is that process's
    loop body), sharing one durable limiter and one job store.
    """
    bindings = lane_bindings(world)
    return {
        "production": WorkerDeployment(
            name="worker-production",
            slots=(QueueSlots(QueueName.PRODUCTION, 1),),
            handlers=handlers,
            # No limiter on the production lane: its provider spend is bounded
            # per attempt by budget reservations, not by shared per-account
            # quotas — those guard the publication/community surfaces (F04).
        ),
        "publication": WorkerDeployment(
            name="worker-publication",
            slots=(QueueSlots(QueueName.PUBLICATION, 1),),
            handlers=handlers,
            limiter=world.limiter,
            bindings=bindings,
        ),
        "community": WorkerDeployment(
            name="worker-community",
            slots=(QueueSlots(QueueName.COMMUNITY, 2),),
            handlers=handlers,
            limiter=world.limiter,
            bindings=bindings,
        ),
    }


__all__ = [
    "LANE_ISOLATION_BOUND_MS",
    "lane_bindings",
    "lane_deployments",
]
