"""Gate 2 readiness: every reason a final approval must be refused, recomputed at decision time.

``gate2_blockers`` returns human-readable blockers; Gate 2 APPROVE is enabled only when the list is
empty. Blockers are derived state: ``package_hash`` does not cover them (contract 1.2.1), so they
are recomputed from the database on every view and every decision, never trusted from the package.

Checked (SPEC §5 rule 2, MD-005, §11):
- episode is AWAITING_FINAL_REVIEW with no recorded outcome;
- the package is the current one and READY; its own gate blockers and blocking findings are listed;
- no open CRITICAL / BLOCKED QA finding for the episode's current QA cycle (PASS never blocks);
- rights/capability release conditions from the injected function (optional destinations do not);
- every media and episode-one cast asset is registered with the package's hash and persisted
  (re-hashed against the private object store);
- the approved management-policy hash matches the approved season scope;
- no live GPU lease (CLAIMED, ACTIVE or TRANSFERRING) for the episode;
- every caption track in the package is CURRENT and ACTUAL_AUDIO_ALIGNMENT (estimated captions are
  never releasable, V-22), and no CURRENT track of the episode is estimated.

Unknown QA coverage is shown to the reviewer but blocks only when the package lists it in its own
``gate_blockers`` (T008 rule). A green aggregate never clears a blocker.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from microdrama.contracts.enums import CaptionTimingSource, EpisodeState, LeaseState
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.infra import Clock, ObjectStore
from microdrama.contracts.release import ReleasePackage
from microdrama.contracts.season import ManagementPolicy, SeasonScope
from microdrama.persistence.assets import verify_persisted
from microdrama.persistence.db import Tx
from microdrama.review.packages import PackageStatus, StoredPackage, current_package

ReleaseConditionsFn = Callable[[Tx, dict[str, Any], ReleasePackage], list[str]]

OPTIONAL_PREFIX = "optional:"
# Only these resolutions release a finding. OPEN and ACCEPTED_UNKNOWN keep blocking the gate.
RELEASING_RESOLUTIONS = frozenset({"RESOLVED", "SUPERSEDED"})
_LIVE_LEASES = (LeaseState.CLAIMED.value, LeaseState.ACTIVE.value, LeaseState.TRANSFERRING.value)
# A lease that lost its owner can still have a running, billing pod. It blocks Gate 2 until its stop
# is verified (SPEC §5 rule 8: no GPU during a human wait; §6 orphan cleanup).
_UNVERIFIED_STOP_LEASES = (LeaseState.ORPHANED.value, LeaseState.EXPIRED.value)
_ACTUAL = CaptionTimingSource.ACTUAL_AUDIO_ALIGNMENT.value


def finding_blocks(severity: str, outcome: str, resolution: str) -> bool:
    """Whether a QA finding blocks Gate 2, whatever QA cycle it was raised in (V-26).

    Mirrors ``QAFinding.blocks_release``: a PASS never blocks, a CRITICAL severity or a BLOCKED
    outcome does. Only a RESOLVED or SUPERSEDED resolution releases the finding.
    """
    if resolution in RELEASING_RESOLUTIONS or outcome == "PASS":
        return False
    return severity == "CRITICAL" or outcome == "BLOCKED"


def episode_findings(tx: Tx, episode_id: UUID) -> list[dict[str, Any]]:
    """Every QA finding of the episode across all QA cycles, oldest cycle first."""
    return tx.fetchall(
        "SELECT id, qa_cycle, check_id, severity, outcome, resolution, body, created_at "
        "FROM qa_findings WHERE episode_id = %s ORDER BY qa_cycle, created_at, id",
        (episode_id,),
    )


def not_configured_release_conditions(
    tx: Tx, episode_row: dict[str, Any], package: ReleasePackage
) -> list[str]:
    """Fail-closed default: until rights/capability conditions are wired, nothing is releasable."""
    return ["rights and capability release conditions are not configured"]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _asset_checks(package: ReleasePackage) -> list[tuple[UUID, str, str | None]]:
    """(asset id, role, expected sha256 or None) for every asset the approval depends on."""
    checks: dict[UUID, tuple[str, str | None]] = {}
    for media in package.media:
        checks.setdefault(media.asset_id, (media.role, media.sha256))
    for asset_id in package.cast_package_asset_ids:
        checks.setdefault(asset_id, ("cast_package", None))
    return [(asset_id, role, sha) for asset_id, (role, sha) in checks.items()]


def approved_scope(tx: Tx, season_id: UUID) -> SeasonScope | None:
    """The season scope the Gate 1 approval bound (the proposal whose hash the season approved)."""
    season = tx.fetchone("SELECT approved_scope_hash FROM seasons WHERE id = %s", (season_id,))
    if season is None or season["approved_scope_hash"] is None:
        return None
    proposal = tx.fetchone(
        "SELECT scope FROM season_proposals WHERE season_id = %s AND scope_hash = %s "
        "ORDER BY scope_version DESC LIMIT 1",
        (season_id, season["approved_scope_hash"]),
    )
    return None if proposal is None else SeasonScope.model_validate(proposal["scope"])


def approved_policy_hash(tx: Tx, season_id: UUID) -> tuple[str | None, ManagementPolicy | None]:
    """Hash and model of the approved season's management policy, or (None, None)."""
    scope = approved_scope(tx, season_id)
    if scope is None:
        return None, None
    return canonical_hash(scope.management_policy), scope.management_policy


def gate2_blockers(
    tx: Tx,
    *,
    episode_row: dict[str, Any],
    package: StoredPackage | None,
    store: ObjectStore,
    release_conditions_fn: ReleaseConditionsFn,
    clock: Clock,
) -> list[str]:
    """Every reason Gate 2 APPROVE is disabled for this episode and package (empty = enabled)."""
    blockers: list[str] = []
    episode_id = episode_row["id"]

    if episode_row["state"] != EpisodeState.AWAITING_FINAL_REVIEW.value:
        blockers.append(f"episode is {episode_row['state']}, not AWAITING_FINAL_REVIEW")
    if episode_row["outcome"] is not None:
        blockers.append(f"episode has recorded outcome {episode_row['outcome']}")
    if package is None:
        blockers.append("no release package is prepared for this episode")
        return _dedupe(blockers)

    current = current_package(tx, episode_id)
    if current is None or current.row_id != package.row_id:
        blockers.append(f"package v{package.version} is not the current release package")
    if package.status is not PackageStatus.READY:
        blockers.append(f"package v{package.version} is {package.status.value}, not READY")
    blockers.extend(package.gate_blockers)

    content = package.package
    if content.qa.blocking_finding_ids:
        blockers.append(
            f"{len(content.qa.blocking_finding_ids)} blocking QA finding(s) in the package"
        )
    for finding in episode_findings(tx, episode_id):
        if finding_blocks(finding["severity"], finding["outcome"], finding["resolution"]):
            state = "open" if finding["resolution"] == "OPEN" else "unreleased"
            suffix = (
                "" if finding["resolution"] == "OPEN" else f" (resolution {finding['resolution']})"
            )
            blockers.append(
                f"{state} {finding['severity']} {finding['outcome']} QA finding "
                f"{finding['check_id']} ({finding['id']}) from QA cycle {finding['qa_cycle']}{suffix}"
            )

    for text in release_conditions_fn(tx, dict(episode_row), content):
        if not text.startswith(OPTIONAL_PREFIX):
            blockers.append(text)

    for asset_id, role, expected_sha in _asset_checks(content):
        row = tx.fetchone("SELECT sha256 FROM assets WHERE id = %s", (asset_id,))
        if row is None:
            blockers.append(f"{role} asset {asset_id} is not registered")
            continue
        if expected_sha is not None and row["sha256"] != expected_sha:
            blockers.append(f"{role} asset {asset_id} hash differs from the package")
            continue
        if not verify_persisted(tx, store, asset_id, now=clock.now()):
            blockers.append(f"{role} asset {asset_id} failed persisted-object verification")

    policy_hash, _policy = approved_policy_hash(tx, package.package.season_id)
    if policy_hash is None:
        blockers.append("approved season scope is not available to check the management policy")
    elif policy_hash != content.management_policy_hash:
        blockers.append("management policy hash differs from the approved season scope")

    for lease in tx.fetchall(
        "SELECT id, lease_state, stop_verified_at FROM pod_leases WHERE owner_episode_id = %s "
        "AND (lease_state = ANY(%s) OR (lease_state = ANY(%s) AND stop_verified_at IS NULL)) "
        "ORDER BY created_at, id",
        (episode_id, list(_LIVE_LEASES), list(_UNVERIFIED_STOP_LEASES)),
    ):
        if lease["lease_state"] in _LIVE_LEASES:
            blockers.append(
                f"GPU pod lease {lease['id']} is {lease['lease_state']}; "
                "the GPU must be released before Gate 2"
            )
        else:
            blockers.append(
                f"GPU pod lease {lease['id']} is {lease['lease_state']} and its stop is not "
                "verified; the GPU must be confirmed off before Gate 2"
            )

    for track_id in content.caption_track_ids:
        track = tx.fetchone(
            "SELECT episode_id, state, timing_source FROM caption_tracks WHERE id = %s",
            (track_id,),
        )
        if track is None:
            blockers.append(f"caption track {track_id} is missing")
        elif track["episode_id"] != episode_id:
            blockers.append(f"caption track {track_id} belongs to another episode")
        elif track["state"] != "CURRENT":
            blockers.append(f"caption track {track_id} is {track['state']}, not CURRENT")
        elif track["timing_source"] != _ACTUAL:
            blockers.append(
                f"caption track {track_id} is estimated from script; only actual-audio captions "
                "are releasable"
            )
    for track in tx.fetchall(
        "SELECT id, locale FROM caption_tracks WHERE episode_id = %s AND state = 'CURRENT' "
        "AND timing_source <> %s ORDER BY locale, id",
        (episode_id, _ACTUAL),
    ):
        blockers.append(
            f"current {track['locale']} caption track {track['id']} is not aligned to actual audio"
        )

    return _dedupe(blockers)


__all__ = [
    "OPTIONAL_PREFIX",
    "RELEASING_RESOLUTIONS",
    "episode_findings",
    "finding_blocks",
    "ReleaseConditionsFn",
    "approved_policy_hash",
    "approved_scope",
    "gate2_blockers",
    "not_configured_release_conditions",
]
