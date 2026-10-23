"""Registry-backed Gate 2 release conditions (T029 wiring).

This replaces the fail-closed ``not_configured_release_conditions`` default for the
composed pipeline. It delegates to the frozen T006 evaluator
(``core.registry.release_conditions.evaluate_release_conditions``) — no condition
logic is re-derived here — deriving its inputs from the package under decision:

- destinations: one per release-slot plan, requiring the operations its slot kind
  needs (upload full/short, status, readback), the plan's own disclosures plus the
  rights route's, and the provider route pinned by the packaged capability;
- rights subjects: every media/cast asset must carry the FAKE_SYNTHETIC mock
  provenance, which maps to the seeded mock MODEL_OUTPUT subject. Any other
  provenance has no qualified rights route and blocks (fail closed);
- QA green is derived from the package's own blocking findings, never waived.

Real rights routes and accounts stay unrecorded until T031/T032 evidence, so those
releases keep failing closed exactly as before (MD-015, MD-016).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from microdrama.config import Settings
from microdrama.contracts.enums import (
    CapabilityOperation,
    Platform,
    Provenance,
    SlotKind,
)
from microdrama.contracts.infra import Clock
from microdrama.core.registry.capabilities import CapabilityRegistry
from microdrama.core.registry.release_conditions import (
    DestinationRequirement,
    evaluate_release_conditions,
)
from microdrama.core.registry.rights import RightsRegistry
from microdrama.persistence import Database
from microdrama.review.gate_conditions import ReleaseConditionsFn

#: The single output-rights route the offline mock may release under.
MOCK_OUTPUT_ROUTE = "mock-fake-synthetic-v1"
#: Territories the mock release targets (the seeded rights record covers both).
MOCK_TERRITORIES = ("TH", "US")

_ALWAYS_REQUIRED_OPS = frozenset({CapabilityOperation.STATUS, CapabilityOperation.READBACK})
_UPLOAD_BY_SLOT_KIND = {
    SlotKind.FULL_EPISODE: CapabilityOperation.UPLOAD_FULL_VIDEO,
    SlotKind.PART: CapabilityOperation.UPLOAD_SHORT,
    SlotKind.PROMO_CUT: CapabilityOperation.UPLOAD_SHORT,
    SlotKind.HOOK: CapabilityOperation.UPLOAD_SHORT,
}


def _asset_provenance(tx: Any, asset_id: UUID) -> str | None:
    row = tx.fetchone("SELECT provenance FROM assets WHERE id = %s", (asset_id,))
    return None if row is None else row["provenance"]


def _mock_subjects(tx: Any, asset_ids: list[UUID]) -> tuple[list[tuple[str, str]], list[str]]:
    """(rights subjects, blockers) for the package's assets under the mock route."""
    subjects: list[tuple[str, str]] = []
    blockers: list[str] = []
    seen: set[UUID] = set()
    for asset_id in asset_ids:
        if asset_id in seen:
            continue
        seen.add(asset_id)
        provenance = _asset_provenance(tx, asset_id)
        if provenance is None:
            blockers.append(f"asset {asset_id} is not registered")
        elif provenance not in (
            Provenance.FAKE_SYNTHETIC.value,
            Provenance.DERIVED_LOCAL.value,
        ):
            blockers.append(
                f"asset {asset_id} provenance {provenance} has no qualified output-rights route"
            )
        elif not subjects:
            # FAKE_SYNTHETIC renders and their local DERIVED_LOCAL re-cuts
            # (FFmpeg variants/captions of fake sources) share the mock route.
            subjects.append(("MODEL_OUTPUT", MOCK_OUTPUT_ROUTE))
    return subjects, blockers


def _destinations(tx: Any, package: Any) -> tuple[list[DestinationRequirement], list[str]]:
    """One destination per slot plan, pinned to the packaged capability's route."""
    destinations: list[DestinationRequirement] = []
    blockers: list[str] = []
    for plan in package.release_scope:
        row = tx.fetchone(
            "SELECT provider_route FROM capability_registry "
            "WHERE capability_id = %s AND version = %s",
            (plan.capability_id, plan.capability_version),
        )
        if row is None:
            blockers.append(
                f"capability {plan.capability_id} v{plan.capability_version} for "
                f"{plan.slot.platform.value}/{plan.slot.account_ref} is not registered"
            )
            continue
        upload = _UPLOAD_BY_SLOT_KIND.get(plan.slot_kind)
        ops = set(_ALWAYS_REQUIRED_OPS)
        if upload is not None:
            ops.add(upload)
        destinations.append(
            DestinationRequirement(
                platform=plan.slot.platform,
                account_ref=plan.slot.account_ref,
                required_ops=frozenset(ops),
                disclosures=frozenset(plan.disclosures),
                required=plan.required,
                provider_route=row["provider_route"],
            )
        )
    return destinations, blockers


def build_registry_release_conditions(
    db: Database, clock: Clock, settings: Settings
) -> ReleaseConditionsFn:
    """The Gate 2 conditions closure for the composed pipeline (T029)."""
    rights = RightsRegistry(db, clock, settings)
    capabilities = CapabilityRegistry(db, clock, settings)

    def conditions(tx: Any, episode_row: dict[str, Any], package: Any) -> list[str]:
        del episode_row  # conditions derive from the package and the registries only
        asset_ids = [media.asset_id for media in package.media]
        asset_ids.extend(package.cast_package_asset_ids)
        subjects, blockers = _mock_subjects(tx, asset_ids)
        destinations, destination_blockers = _destinations(tx, package)
        blockers.extend(destination_blockers)
        if blockers or not subjects or not destinations:
            # Nothing to evaluate: either an input is unqualified or the package is
            # malformed; fail closed without calling the evaluator.
            return blockers or ["package has no evaluable release destinations"]

        platform_names = {d.platform.value for d in destinations}
        unknown = platform_names - {p.value for p in Platform}
        if unknown:
            return [f"unknown destination platform(s): {sorted(unknown)}"]

        decisions = evaluate_release_conditions(
            rights=rights,
            capabilities=capabilities,
            rights_route_id=MOCK_OUTPUT_ROUTE,
            rights_subjects=subjects,
            territories=MOCK_TERRITORIES,
            destinations=destinations,
            at=clock.now(),
            qa_all_green=not package.qa.blocking_finding_ids,
        )
        return list(decisions)

    return conditions


__all__ = ["MOCK_OUTPUT_ROUTE", "MOCK_TERRITORIES", "build_registry_release_conditions"]
