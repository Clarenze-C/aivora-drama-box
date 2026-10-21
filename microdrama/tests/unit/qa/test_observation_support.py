"""Shared builders for the T018 observation-first lane tests.

Companion to T017's ``qa_support`` (imported, never edited): thin factories for the
two new services plus recording/mutating spies that prove what the seams actually
received. The basename keeps it inside this lane's claimed test paths; it contains
no test functions.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from qa_support import QAWorld

from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.media import MediaInfo
from microdrama.contracts.qa import ObservationReport
from microdrama.persistence import insert_row, jsonb
from microdrama.qa.comparison import (
    ComparisonService,
    MediaComparator,
    OfflineMediaComparator,
)
from microdrama.qa.config import QAConfig
from microdrama.qa.models import MediaObservation
from microdrama.qa.observation import ObservationService
from microdrama.story.models import BibleFact, SeasonBible
from microdrama.testing.media import (
    FixtureTruth,
    IdentityTruth,
    SpokenTruth,
)
from microdrama.testing.seed import seed_human_session, seed_owner

T018_T0 = datetime(2026, 10, 21, tzinfo=UTC)
_DEFAULT = object()  # sentinel: "the production default" vs an explicit override

# The pristine s1-l1 line (what the clean fixture actually speaks).
CLEAN_LINE_TH = "ลุงเล็ก หนี้ห้าหมื่นบาทนี่คืออะไรคะ"

# A canon fact used as a leaking intended answer in the screening tests.
CANON_STATEMENT = "The ledger hides a second family debt."


def observation_service(
    world: QAWorld, config: QAConfig | None = None, observer: Any = _DEFAULT
) -> ObservationService:
    resolved = world.observer() if observer is _DEFAULT else observer
    return ObservationService(
        world.db,
        world.clock,
        world.ids,
        world.settings,
        budget=world.budget,
        store=world.store,
        config=config,
        observer=resolved,
    )


def comparison_service(
    world: QAWorld, config: QAConfig | None = None, comparator: MediaComparator | Any = _DEFAULT
) -> ComparisonService:
    resolved = OfflineMediaComparator(config) if comparator is _DEFAULT else comparator
    return ComparisonService(
        world.db,
        world.clock,
        world.ids,
        world.settings,
        budget=world.budget,
        config=config,
        comparator=resolved,
    )


class SpyObserver:
    """Delegating observer that records the exact payload of every observe() call.

    ``probe`` (optional) runs at dispatch time — the reservation-before-dispatch
    proof snapshots the reservations table from inside the paid call.
    """

    def __init__(self, delegate, probe: Callable[[], Any] | None = None) -> None:
        self._delegate = delegate
        self._probe = probe
        self.calls = 0
        self.payloads: list[dict[str, Any]] = []
        self.snapshots: list[Any] = []

    def observe(
        self,
        *,
        asset_id: uuid.UUID,
        asset_sha256: str,
        media_path,
        duration_ms: int,
    ) -> MediaObservation:
        self.calls += 1
        self.payloads.append(
            {
                "asset_id": str(asset_id),
                "asset_sha256": asset_sha256,
                "media_path": str(media_path),
                "duration_ms": duration_ms,
            }
        )
        if self._probe is not None:
            self.snapshots.append(self._probe())
        return self._delegate.observe(
            asset_id=asset_id,
            asset_sha256=asset_sha256,
            media_path=media_path,
            duration_ms=duration_ms,
        )


class RaisingObserver:
    """An observer whose paid dispatch dies after being called."""

    def __init__(self) -> None:
        self.calls = 0

    def observe(self, **_kwargs: Any) -> MediaObservation:
        self.calls += 1
        raise RuntimeError("asr backend exploded during the blind call")


class RecordingComparator:
    """Pass B spy: records what it received; optionally mutates, probes or raises."""

    def __init__(
        self,
        *,
        delegate: MediaComparator | None = None,
        probe: Callable[[], Any] | None = None,
        raises: Exception | None = None,
        mutate: Callable[[ObservationReport], None] | None = None,
        config: QAConfig | None = None,
    ) -> None:
        self._delegate = delegate or OfflineMediaComparator(config)
        self._probe = probe
        self._raises = raises
        self._mutate = mutate
        self.calls = 0
        self.snapshots: list[Any] = []
        self.seen_report_shas: list[str] = []
        self.mutation_errors: list[str] = []

    def compare(self, *, report, intent, **kwargs: Any):
        from microdrama.contracts.hashing import canonical_hash as _ch

        self.calls += 1
        self.seen_report_shas.append(_ch(report))
        if self._probe is not None:
            self.snapshots.append(self._probe())
        if self._mutate is not None:
            try:
                self._mutate(report)
            except Exception as exc:  # pydantic freezes attribute assignment
                self.mutation_errors.append(f"{type(exc).__name__}: {exc}")
        if self._raises is not None:
            raise self._raises
        return self._delegate.compare(report=report, intent=intent, **kwargs)


# --- seeds ---------------------------------------------------------------------------------


def seed_canon(
    world: QAWorld,
    episode_id: uuid.UUID,
    *,
    version: int = 1,
    reveals: tuple[str, ...] = (),
) -> int:
    """A PLANNED canon row whose bible carries the given planned-reveal statements."""
    season = world.row("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))
    assert season is not None
    from microdrama.contracts.examples import season_scope
    from microdrama.contracts.season import ArcBeat, CharacterBrief

    facts: list[BibleFact] = [
        BibleFact(
            fact_key="premise",
            kind="PREMISE",
            statement="A family debt story.",
            source_field="premise",
        )
    ]
    for index, statement in enumerate(reveals):
        facts.append(
            BibleFact(
                fact_key=f"reveal-{index}",
                kind="PLANNED_REVEAL",
                statement=statement,
                source_field="arc.planned_reveals",
                episode_number=2,
            )
        )
    bible = SeasonBible(
        bible_id=uuid.uuid4(),
        season_id=season["season_id"],
        scope_version=1,
        approved_scope_hash=canonical_hash(season_scope()),
        canon_version=version,
        title_th="หนี้",
        title_en="The Debt",
        logline="A debt story.",
        premise="A debt story.",
        characters=[
            CharacterBrief(
                character_id="fon",
                name_th="ฟอน",
                name_en="Fon",
                role="lead",
                description="The daughter.",
                voice_direction="warm",
            )
        ],
        arc=[ArcBeat(episode_number=1, summary="The ledger is found.")],
        facts=facts,
        playbook_version="v1",
        compiled_at=T018_T0,
    )
    payload = {"bible": bible.model_dump(mode="json")}
    with world.db.transaction() as tx:
        insert_row(
            tx,
            "canon_versions",
            {
                "id": uuid.uuid4(),
                "season_id": season["season_id"],
                "kind": "PLANNED",
                "version": version,
                "facts": jsonb(payload),
                "facts_hash": canonical_hash(payload),
            },
        )
    return version


def seed_identity_lock(
    world: QAWorld,
    episode_id: uuid.UUID,
    asset_id: uuid.UUID,
    members: list[tuple[str, str]],
) -> uuid.UUID:
    """A minimal identity lock: one FACE member per (character_key, state)."""
    season = world.row("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))
    assert season is not None
    lock_id = uuid.uuid4()
    with world.db.transaction() as tx:
        owner = seed_owner(tx)
        session = seed_human_session(tx, owner)
        approval_id = uuid.uuid4()
        # A live human approval event the lock row can reference. Seeded directly as
        # test scaffolding: building a real Gate 2 APPROVE needs a full release
        # package, which is review-lane scope, not this lane's.
        insert_row(
            tx,
            "approval_events",
            {
                "id": approval_id,
                "gate_type": "SEASON_CONCEPT",
                "action": "APPROVE",
                "entity_type": "season",
                "entity_id": season["season_id"],
                "expected_revision": 9,  # past the Gate 1 seed's revision 0
                "package_hash": canonical_hash({"seed": str(lock_id)}),
                "actor_owner_id": owner,
                "actor_session_id": session,
                "idempotency_key": f"seed-lock-{lock_id.hex}",
                "command_hash": canonical_hash({"lock": str(lock_id)}),
            },
        )
        insert_row(
            tx,
            "identity_locks",
            {
                "id": lock_id,
                "season_id": season["season_id"],
                "source_episode_id": episode_id,
                "version": 1,
                "approval_event_id": approval_id,
                "release_package_hash": canonical_hash({"package": str(lock_id)}),
                "body": jsonb({"lock_id": str(lock_id)}),
            },
        )
        for character_key, state in members:
            ref_version_id = uuid.uuid4()
            insert_row(
                tx,
                "reference_versions",
                {
                    "id": ref_version_id,
                    "season_id": season["season_id"],
                    "ref_kind": "FACE",
                    "ref_key": f"face:{character_key}",
                    "version": 1,
                    "asset_id": asset_id,
                    "content_sha256": canonical_hash({"face": character_key}),
                    "cache_key": canonical_hash({"cache": str(ref_version_id)}),
                    "character_key": character_key,
                    "state": state,
                },
            )
            insert_row(
                tx,
                "identity_lock_assets",
                {
                    "lock_id": lock_id,
                    "reference_version_id": ref_version_id,
                    "asset_id": asset_id,
                    "content_sha256": canonical_hash({"face": character_key}),
                    "asset_kind": "FACE",
                },
            )
    return lock_id


def partial_coverage_truth() -> FixtureTruth:
    """Speech/identity observed only in [0, 2s) of a 5 s media: the rest is UNSAMPLED."""
    return FixtureTruth(
        fixture_id="t018-partial-coverage",
        duration_ms=5_000,
        has_audio=True,
        has_video=True,
        spoken=(SpokenTruth(start_ms=100, end_ms=2_000, text_th=CLEAN_LINE_TH, speaker_id="fon"),),
        identities=(IdentityTruth(start_ms=100, end_ms=2_000, character_id="fon"),),
        covered_ranges_ms=((0, 2_000),),
    )


def partial_media_info() -> MediaInfo:
    return MediaInfo(duration_ms=5_000, has_video=True, has_audio=True)


__all__ = [
    "CLEAN_LINE_TH",
    "RecordingComparator",
    "RaisingObserver",
    "SpyObserver",
    "comparison_service",
    "observation_service",
    "partial_coverage_truth",
    "partial_media_info",
    "seed_canon",
    "seed_identity_lock",
]
