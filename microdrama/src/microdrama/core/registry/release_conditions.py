"""Release conditions: every blocker that keeps a package from a destination (AT-13).

``evaluate_release_conditions`` returns all blockers together. An empty list means the rights and
capability conditions are clear. ``qa_all_green`` is an input, not a waiver: green QA adds no
clearance, so rights and capability blockers survive it. Optional destinations contribute
blockers prefixed ``optional:``, which hold only that destination.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from microdrama.contracts.enums import CapabilityOperation, DisclosureKind, Platform
from microdrama.contracts.errors import SchemaInvalid
from microdrama.core.registry._common import clean_account, clean_route
from microdrama.core.registry.capabilities import CapabilityRegistry
from microdrama.core.registry.rights import RightsRegistry

QA_BLOCKER = "qa: not all checks are green"


@dataclass(frozen=True)
class DestinationRequirement:
    """One publication destination and what its route must support.

    ``provider_route`` is optional: an account with several current routes is ambiguous (fail
    closed) unless the destination names one; ``None`` keeps that ambiguity blocker.
    """

    platform: Platform
    account_ref: str
    required_ops: frozenset[CapabilityOperation]
    disclosures: frozenset[DisclosureKind]
    required: bool
    provider_route: str | None = None

    def __post_init__(self) -> None:
        try:
            platform = Platform(self.platform)
            ops = frozenset(CapabilityOperation(op) for op in self.required_ops)
            disclosures = frozenset(DisclosureKind(d) for d in self.disclosures)
        except ValueError:
            raise SchemaInvalid(
                "destination names an unknown platform, operation or disclosure"
            ) from None
        if not isinstance(self.required, bool):
            raise SchemaInvalid("destination required flag must be a boolean")
        object.__setattr__(self, "platform", platform)
        object.__setattr__(self, "account_ref", clean_account(self.account_ref))
        object.__setattr__(self, "required_ops", ops)
        object.__setattr__(self, "disclosures", disclosures)
        # V-34: a named route must be as clean as every other registry identifier; None (the
        # default) leaves multi-route accounts ambiguous rather than guessed.
        object.__setattr__(
            self,
            "provider_route",
            None if self.provider_route is None else clean_route(self.provider_route),
        )


def evaluate_release_conditions(
    *,
    rights: RightsRegistry,
    capabilities: CapabilityRegistry,
    rights_route_id: str,
    rights_subjects: Iterable[tuple[str, str]],
    territories: Iterable[str],
    destinations: list[DestinationRequirement],
    at: datetime,
    qa_all_green: bool,
) -> list[str]:
    """Every blocker for a release, in a stable order: rights, destinations, then QA.

    A release must name at least one required destination. Optional destinations hold only
    themselves, so a release made only of optional destinations would clear with nothing
    required; that is refused as a schema error rather than returned as an empty list.
    """
    if not destinations:
        raise SchemaInvalid("a release names at least one destination")
    if not any(destination.required for destination in destinations):
        raise SchemaInvalid(
            "a release needs at least one required destination; optional destinations "
            "cannot clear a release on their own"
        )
    if not isinstance(qa_all_green, bool):
        raise SchemaInvalid("qa_all_green must be a boolean")
    subjects = list(rights_subjects)
    blockers: list[str] = []
    rights_decision = rights.evaluate(
        rights_route_id=rights_route_id,
        subjects=subjects,
        territories=territories,
        at=at,
    )
    blockers.extend(rights_decision.blockers)
    # MD-015: the route's required synthetic/sponsor disclosures must be made by every destination.
    route_disclosures = rights.required_disclosures(
        rights_route_id=rights_route_id, subjects=subjects
    )
    for destination in destinations:
        decision = capabilities.evaluate(
            platform=destination.platform,
            account_ref=destination.account_ref,
            required=destination.required_ops,
            disclosures=destination.disclosures | route_disclosures,
            provider_route=destination.provider_route,
        )
        prefix = "" if destination.required else "optional: "
        blockers.extend(f"{prefix}{blocker}" for blocker in decision.blockers)
    if not qa_all_green:
        blockers.append(QA_BLOCKER)
    return blockers


__all__ = ["QA_BLOCKER", "DestinationRequirement", "evaluate_release_conditions"]
