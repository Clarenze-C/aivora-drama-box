"""Mock registry seeding for the composed offline pipeline (T029).

Records, through the REAL registries and with FAKE_SYNTHETIC provenance:

- one capability row per platform, taken verbatim from the composed publishing
  adapter's own ``capability()`` snapshot so the DB registry, the adapter checks
  and the Gate 2 release conditions agree by construction (one source of truth);
- one ELIGIBLE ``MODEL_OUTPUT`` rights record for the mock output route the
  release conditions require (``pipeline.conditions.MOCK_OUTPUT_ROUTE``).

Real accounts/rights stay unrecorded until T031/T032 evidence. Nothing here
claims live readiness; every row carries fake-fixture evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from microdrama.config import Settings
from microdrama.contracts.enums import EvidenceSource, Platform, Provenance
from microdrama.contracts.infra import IdGenerator
from microdrama.contracts.primitives import EvidenceRef
from microdrama.contracts.registries import RightsRecord
from microdrama.core.registry.capabilities import CapabilityRegistry
from microdrama.core.registry.rights import RightsRegistry
from microdrama.persistence import Database
from microdrama.testing.fakes import FakeClock

#: The mock account per platform (Facebook requires a Page-scoped account).
MOCK_ACCOUNT = "acct:fake-main"
MOCK_ACCOUNTS = {
    Platform.YOUTUBE: MOCK_ACCOUNT,
    Platform.TIKTOK: MOCK_ACCOUNT,
    Platform.INSTAGRAM: MOCK_ACCOUNT,
    Platform.FACEBOOK: "acct:facebook-main",  # FB_PAGE_ACCOUNT (page-scoped route only)
}

MOCK_PLATFORMS = (Platform.YOUTUBE, Platform.TIKTOK, Platform.INSTAGRAM, Platform.FACEBOOK)


def mock_account(platform: Platform) -> str:
    return MOCK_ACCOUNTS[platform]


def _record_provenance(record) -> Provenance:
    """FAKE_SYNTHETIC unless the adapter's evidence names a real source (D3, V-9).

    Some fixture adapters document real account-truth limits from provider docs
    (OFFICIAL_DOCUMENTATION). Recording those as FAKE_SYNTHETIC would mislabel real
    evidence; they are recorded as LIVE_PROVIDER-sourced documentation truth, still
    constrained by the adapter's own enabled flag and the offline effect switches.
    """
    from microdrama.contracts.enums import EvidenceSource

    real = {
        EvidenceSource.OFFICIAL_DOCUMENTATION,
        EvidenceSource.CONTROLLED_ACCOUNT_TEST,
        EvidenceSource.MEASURED_BENCHMARK,
        EvidenceSource.LICENSE_DOCUMENT,
    }
    for ref in record.evidence:
        if ref.source in real:
            return Provenance.LIVE_PROVIDER
    return Provenance.FAKE_SYNTHETIC


def _reference_model_rights(ids: IdGenerator, clock: FakeClock) -> list:
    """ELIGIBLE MODEL + MODEL_OUTPUT records for the mock reference routes (T011).

    The same subjects/territories the references lane's tests seed: the mock
    image/voice model configs under their fixture routes, worldwide, commercial
    output release allowed. Real model rights are T031 evidence.
    """
    from datetime import UTC, datetime

    from microdrama.contracts.enums import DisclosureKind, RightsStatus
    from microdrama.contracts.registries import RightsRecord

    routes = (
        ("route-ref-image", "ref-anchor-image-v1"),
        ("route-ref-voice-th", "ref-voice-th-v1"),
    )
    records: list[RightsRecord] = []
    for route, model in routes:
        for kind in ("MODEL", "MODEL_OUTPUT"):
            records.append(
                RightsRecord(
                    record_id=ids.new_id(),
                    rights_route_id=route,
                    version=1,
                    subject_kind=kind,
                    subject_ref=model,
                    territories=["WORLDWIDE"],
                    commercial_use=True,
                    output_release_allowed=True,
                    required_disclosures=[DisclosureKind.SYNTHETIC_VOICE],
                    expires_at=datetime(2027, 10, 27, tzinfo=UTC),
                    evidence=[
                        EvidenceRef(
                            source=EvidenceSource.FAKE_FIXTURE,
                            ref=f"fixture:mock-ref-rights:{route}",
                        )
                    ],
                    status=RightsStatus.ELIGIBLE,
                    recorded_at=datetime(2026, 10, 20, tzinfo=UTC),
                )
            )
    del clock
    return records


def seed_mock_registries(
    db: Database,
    adapters: Mapping[Platform, object],
    clock: FakeClock,
    ids: IdGenerator,
    settings: Settings,
    *,
    account: str | None = None,
) -> None:
    """Idempotent mock seeding: capabilities from the adapters, the mock rights route."""
    from .conditions import MOCK_OUTPUT_ROUTE

    capability_registry = CapabilityRegistry(db, clock, settings)
    for platform in MOCK_PLATFORMS:
        record = adapters[platform].capability(account or mock_account(platform))
        capability_registry.record(record, source_provenance=_record_provenance(record))

    rights = RightsRegistry(db, clock, settings)
    rights.record(
        RightsRecord(
            record_id=ids.new_id(),
            rights_route_id=MOCK_OUTPUT_ROUTE,
            version=1,
            subject_kind="MODEL_OUTPUT",
            subject_ref=MOCK_OUTPUT_ROUTE,
            territories=["TH", "US"],
            commercial_use=True,
            output_release_allowed=True,
            required_disclosures=["AI_GENERATED_CONTENT"],
            evidence=[
                EvidenceRef(source=EvidenceSource.FAKE_FIXTURE, ref="fixture:mock-output-rights")
            ],
            status="ELIGIBLE",
            recorded_at=datetime(2026, 10, 21, 0, 0, tzinfo=UTC),
        ),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    for record in _reference_model_rights(ids, clock):
        rights.record(record, source_provenance=Provenance.FAKE_SYNTHETIC)


__all__ = [
    "MOCK_ACCOUNT",
    "MOCK_ACCOUNTS",
    "MOCK_PLATFORMS",
    "mock_account",
    "seed_mock_registries",
]
