"""Release scheduling (T020): an approved package becomes durable publication slots.

``schedule_release`` is the whole of the ``publish.schedule_release`` job: it locks the
episode, loads its APPROVED package, validates the release-scope DAG once more and writes
one ``platform_posts`` row per ``ReleaseSlotPlan`` (state SCHEDULED). The episode moves
RELEASE_APPROVED -> SCHEDULED in the same transaction, so no slot can exist for an episode
that is not scheduled, and no schedule can name a package other than the approved one.

Slot identity rules (MD-014, AT-09):

- The slot key (series, episode, part, locale, platform, account, release_slot) is unique
  across the database. A replay of the same package for the same episode is idempotent; a
  second schedule that would reuse a key for a different package — or borrow another
  episode's key — is a Conflict, never an overwrite.
- ``depends_on`` entries must name other slots of the same scope and form no cycle. A
  dependency is only satisfied at submit time by a PUBLISHED_VERIFIED target with a real
  external id (the service enforces that; the DAG here is shape-only).
- At least one slot must be required: an all-optional scope could never qualify the
  episode's full release.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

from microdrama.contracts.enums import EpisodeState
from microdrama.contracts.errors import Conflict, NotFound, SchemaInvalid
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.principals import Principal
from microdrama.contracts.release import ReleasePackage, ReleaseSlotPlan
from microdrama.core.events import append_event
from microdrama.core.state_machine import transition_episode
from microdrama.persistence.db import Tx, insert_row, jsonb

SCHEDULED_STATE = "SCHEDULED"

# Stable ids: the same slot of the same package always maps to the same post row id and
# client token, so a replayed job or a rebuilt command reconstructs them exactly.
POST_NAMESPACE = uuid5(UUID(int=0), "microdrama:platform-posts")


def platform_post_id(dedupe_key: str) -> UUID:
    return uuid5(POST_NAMESPACE, f"post:{dedupe_key}")


def publish_client_token(dedupe_key: str, package_hash: str) -> str:
    """The provider dedupe token for a slot: deterministic, unique per package version."""
    return canonical_hash({"dedupe_key": dedupe_key, "package_hash": package_hash})


def validate_scope_dag(plans: list[ReleaseSlotPlan]) -> None:
    """Shape checks a scope must pass before any row is written."""
    if not plans:
        raise SchemaInvalid("release scope needs at least one slot")
    keys = [plan.slot.dedupe_key for plan in plans]
    if len(set(keys)) != len(keys):
        raise Conflict("duplicate slot key in release scope")
    known = set(keys)
    for plan in plans:
        missing = [dep for dep in plan.depends_on if dep not in known]
        if missing:
            raise Conflict(
                "slot dependency is not part of this release scope",
                slot=plan.slot.release_slot,
                missing=missing,
            )
    if not any(plan.required for plan in plans):
        raise SchemaInvalid("release scope needs at least one required slot")
    _require_acyclic(plans)


def _require_acyclic(plans: list[ReleaseSlotPlan]) -> None:
    """Kahn's algorithm over dedupe keys; a cycle is a Conflict, never a silent skip."""
    dependents: dict[str, list[str]] = {plan.slot.dedupe_key: [] for plan in plans}
    indegree: dict[str, int] = {plan.slot.dedupe_key: 0 for plan in plans}
    for plan in plans:
        for dep in plan.depends_on:
            dependents[dep].append(plan.slot.dedupe_key)
            indegree[plan.slot.dedupe_key] += 1
    ready = [key for key, degree in indegree.items() if degree == 0]
    seen = 0
    while ready:
        key = ready.pop()
        seen += 1
        for follower in dependents[key]:
            indegree[follower] -= 1
            if indegree[follower] == 0:
                ready.append(follower)
    if seen != len(plans):
        cyclic = sorted(key for key, degree in indegree.items() if degree > 0)
        raise Conflict("release scope dependency cycle", cyclic_slots=cyclic)


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchemaInvalid(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _approved_package(tx: Tx, episode_id: UUID) -> dict[str, Any]:
    row = tx.fetchone(
        "SELECT * FROM release_packages WHERE episode_id = %s AND status = 'APPROVED'",
        (episode_id,),
    )
    if row is None:
        raise Conflict(
            "episode has no APPROVED release package; nothing to schedule",
            episode_id=str(episode_id),
        )
    if row["approval_event_id"] is None:
        raise Conflict("approved package is not bound to an approval event")
    return row


def schedule_release(
    tx: Tx,
    *,
    episode_id: UUID,
    actor: Principal,
    now: datetime,
    correlation_id: UUID,
) -> list[UUID]:
    """Expand the episode's APPROVED package into slot rows; idempotent per package.

    Returns the platform_post ids (deterministic). Raises Conflict for a duplicate slot
    key, a schedule that names a different package, or an episode not at RELEASE_APPROVED.
    """
    instant = _aware(now, "now")
    episode = tx.fetchone(
        "SELECT id, state, revision FROM episodes WHERE id = %s FOR UPDATE", (episode_id,)
    )
    if episode is None:
        raise NotFound(f"episode {episode_id} not found")
    package_row = _approved_package(tx, episode_id)
    package = ReleasePackage.model_validate(package_row["body"])
    validate_scope_dag(package.release_scope)

    existing = tx.fetchall(
        "SELECT id, release_package_id FROM platform_posts WHERE episode_id = %s "
        "ORDER BY created_at, id",
        (episode_id,),
    )
    if existing:
        if existing[0]["release_package_id"] != package_row["id"]:
            raise Conflict(
                "episode slots already exist for a different package",
                scheduled_package=str(existing[0]["release_package_id"]),
                requested_package=str(package_row["id"]),
            )
        return [row["id"] for row in existing]  # replay of the same schedule job
    if EpisodeState(episode["state"]) is not EpisodeState.RELEASE_APPROVED:
        state = EpisodeState(episode["state"])
        if state is EpisodeState.SCHEDULED:
            # The episode moved but its rows vanished — impossible by construction; refuse
            # rather than guess.
            raise Conflict("episode is SCHEDULED but has no slot rows; operator review needed")
        raise Conflict(
            f"episode is {state.value}; only RELEASE_APPROVED episodes are scheduled",
            state=state.value,
        )

    post_ids: list[UUID] = []
    for plan in package.release_scope:
        post_id = platform_post_id(plan.slot.dedupe_key)
        insert_row(
            tx,
            "platform_posts",
            {
                "id": post_id,
                "series_id": plan.slot.series_id,
                "episode_id": plan.slot.episode_id,
                "part": plan.slot.part,
                "locale": plan.slot.locale,
                "platform": plan.slot.platform.value,
                "account_ref": plan.slot.account_ref,
                "release_slot": plan.slot.release_slot,
                "dedupe_key": plan.slot.dedupe_key,
                "slot_kind": plan.slot_kind.value,
                "required": plan.required,
                "release_package_id": package_row["id"],
                "approval_event_id": package_row["approval_event_id"],
                "asset_id": plan.asset_id,
                "asset_sha256": plan.asset_sha256,
                "capability_id": plan.capability_id,
                "capability_version": plan.capability_version,
                "state": SCHEDULED_STATE,
                "iana_zone": plan.schedule.iana_zone,
                "local_time": plan.schedule.local_time,
                "scheduled_utc": plan.schedule.utc_instant,
                "depends_on": jsonb(list(plan.depends_on)),
                "client_token": publish_client_token(plan.slot.dedupe_key, package.package_hash),
                "created_at": instant,
                "updated_at": instant,
            },
        )
        post_ids.append(post_id)
        append_event(
            tx,
            aggregate_type="platform_post",
            aggregate_id=post_id,
            event_type="platform_post.scheduled",
            payload={
                "slot": plan.slot.release_slot,
                "platform": plan.slot.platform.value,
                "required": plan.required,
                "scheduled_utc": plan.schedule.utc_instant.isoformat(),
                "depends_on": list(plan.depends_on),
            },
            correlation_id=correlation_id,
            occurred_at=instant,
        )
    transition_episode(
        tx,
        episode_id=episode_id,
        to=EpisodeState.SCHEDULED,
        expected_revision=int(episode["revision"]),
        actor=actor,
        now=instant,
        correlation_id=correlation_id,
    )
    return post_ids
