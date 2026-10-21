"""Shared builders for the T016 tests (variants/covers/hooks). Not a test module.

- capability records: fake-evidence T006 records written through the REAL
  ``CapabilityRegistry`` so variant/cover planning consumes the same surface the
  publishing lanes will;
- the variants service: built on the same real database/store/budget the T015
  ``World`` exposes, so the two lanes share one fixture truth registry;
- a long-episode fixture: eight 4 s shots with one line each (~32 s of accepted
  footage), because IMP-07 hooks need 20-40 s of accepted material while the
  standard T015 fixture episode is only 6.5 s.
"""

from __future__ import annotations

import uuid

from editing_support import T0, World, build_script

from microdrama.contracts.enums import (
    CapabilityOperation,
    CapabilitySupport,
    DisclosureKind,
    EvidenceSource,
    Level,
    Platform,
    Provenance,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.primitives import EvidenceRef
from microdrama.contracts.release import CapabilityLimits, CapabilityRecord
from microdrama.contracts.season import Shot, ShotManifest
from microdrama.core.registry import CapabilityRegistry
from microdrama.editing.config import EditingConfig
from microdrama.editing.variants_service import VariantsService
from microdrama.persistence import insert_row, jsonb

TT_ACCOUNT = "acct:tiktok-main"
TT_ROUTE = "fake-tiktok-route"
FAKE_EVIDENCE = EvidenceRef(source=EvidenceSource.FAKE_FIXTURE, ref="fixture:t016")

TESTED_OPS: dict[CapabilityOperation, CapabilitySupport] = {
    CapabilityOperation.UPLOAD_FULL_VIDEO: CapabilitySupport.SUPPORTED_TESTED,
    CapabilityOperation.UPLOAD_SHORT: CapabilitySupport.SUPPORTED_TESTED,
    CapabilityOperation.SCHEDULE: CapabilitySupport.SUPPORTED_TESTED,
    CapabilityOperation.STATUS: CapabilitySupport.SUPPORTED_TESTED,
    CapabilityOperation.READBACK: CapabilitySupport.SUPPORTED_TESTED,
    CapabilityOperation.AI_DISCLOSURE: CapabilitySupport.SUPPORTED_TESTED,
}

# The long fixture: 8 shots x 4 s (one Thai line each) ~= 32 s of accepted footage.
# kl8 is the payoff beat (the only HIGH-importance shot, and the last in sequence).
LONG_LINES: list[tuple[str, str, str, int]] = [
    ("kl1", "fon", "ร้านข้าวมันไก่ของแม่พึ่งปิดไปเมื่อวานค่ะ", 1_400),
    ("kl2", "lek", "นั่นแหละหนู ทุกอย่างเริ่มจากหนี้ก้อนเดิม", 1_300),
    ("kl3", "fon", "แล้วลุงจะหาเงินที่ไหนมาชำระคะ", 1_200),
    ("kl4", "lek", "ขายรถ เฮียช่วยไว้แล้ว แต่ยังไม่พอ", 1_300),
    ("kl5", "fon", "หนูจะช่วยลุงได้ไหมคะ", 1_100),
    ("kl6", "lek", "หนูทำได้เพียงอย่างเดียว คืออย่าบอกใคร", 1_400),
    ("kl7", "fon", "ทำไมลุงถึงต้องการความลับขนาดนั้นคะ", 1_300),
    ("kl8", "lek", "เพราะคนที่ยึดร้านคือพ่อของหนูเอง", 1_500),
]
LONG_SHOT_MS = 4_000


def _long_shot(shot_id: str, sequence: int, line_id: str, speaker: str, importance: Level) -> Shot:
    return Shot(
        shot_id=shot_id,
        sequence=sequence,
        scene_id="sc1",
        shot_pattern_id="quiet_confession_v1",
        coverage_role="master",
        purpose=f"Beat {sequence} of the stall debt scene.",
        dramatic_importance=importance,
        dialogue_complexity="SINGLE_SPEAKER",
        temporal_risk="LOW",
        required_identity_controls=["TEXT_PROMPT", "CHARACTER_REFERENCE"],
        preferred_render_tier="quality_eight_step",
        fallback_edit="CUT_TO_REACTION",
        reference_lock_version=None,
        line_ids=[line_id],
        speaker_ids=[speaker],
        voice_ids=[f"voice-{speaker}.v1"],
        target_duration_ms=LONG_SHOT_MS,
        framing="medium single",
        eyelines="to camera",
        location_id="stall",
        outfit_ids=[],
        prop_ids=[],
        required_reference_asset_ids=[],
        sound="morning market",
        acceptance_criteria=["face consistent"],
        depends_on_shot_ids=[],
    )


def build_long_manifest(episode_id: uuid.UUID) -> ShotManifest:
    """Eight shots, one per line; the payoff shot (kl8) is the only HIGH one."""
    shots = [
        _long_shot(
            f"ksh{index + 1}",
            index + 1,
            line_id,
            speaker,
            Level.HIGH if line_id == "kl8" else Level.MEDIUM,
        )
        for index, (line_id, speaker, *_rest) in enumerate(LONG_LINES)
    ]
    return ShotManifest(
        manifest_id=uuid.uuid4(),
        episode_id=episode_id,
        episode_number=1,
        script_id=uuid.uuid4(),
        script_version=1,
        version=1,
        identity_lock_id=None,
        shots=shots,
    )


def capability_record(
    *,
    platform: Platform = Platform.TIKTOK,
    account: str = TT_ACCOUNT,
    route: str = TT_ROUTE,
    ratios: tuple[str, ...] = ("16:9",),
    max_duration_ms: int | None = 300_000,
    min_duration_ms: int | None = None,
) -> CapabilityRecord:
    return CapabilityRecord(
        capability_id=uuid.uuid5(uuid.NAMESPACE_URL, f"t016:{platform.value}:{account}:{route}"),
        version=1,
        platform=platform,
        provider_route=route,
        account_ref=account,
        account_type="creator",
        operations=dict(TESTED_OPS),
        limits=CapabilityLimits(
            aspect_ratios=list(ratios),
            max_duration_ms=max_duration_ms,
            min_duration_ms=min_duration_ms,
        ),
        supported_disclosures=[
            DisclosureKind.AI_GENERATED_CONTENT,
            DisclosureKind.SYNTHETIC_VOICE,
        ],
        evidence=[FAKE_EVIDENCE],
        verified_at=T0,
        enabled=True,
    )


def record_capability(world: World, record: CapabilityRecord) -> None:
    registry = CapabilityRegistry(world.db, world.clock, world.settings)
    registry.record(record, source_provenance=Provenance.FAKE_SYNTHETIC)


def variants_service(world: World, *, config: EditingConfig | None = None) -> VariantsService:
    from editing_support import FixtureSpeechObserver

    return VariantsService(
        world.db,
        world.clock,
        world.ids,
        world.settings,
        budget=world.budget,
        store=world.store,
        config=config,
        speech_observer=FixtureSpeechObserver(world.truth),
    )


def seed_long_episode(world: World) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    """Season + episode + 8-shot script/manifest + line audio + shot assets (~32 s)."""
    season_id, _scope = world.season()
    episode_id = world.episode(season_id, state="RENDERING")
    script = build_script(episode_id, LONG_LINES)
    manifest = build_long_manifest(episode_id)
    with world.db.transaction() as tx:
        insert_row(
            tx,
            "scripts",
            {
                "id": script.script_id,
                "episode_id": episode_id,
                "version": 1,
                "canon_version": 1,
                "body": jsonb(script),
                "body_hash": canonical_hash(script),
                "status": "CURRENT",
            },
        )
        insert_row(
            tx,
            "shot_manifests",
            {
                "id": manifest.manifest_id,
                "episode_id": episode_id,
                "script_id": script.script_id,
                "version": 1,
                "identity_lock_id": None,
                "body": jsonb(manifest),
                "body_hash": canonical_hash(manifest),
                "status": "CURRENT",
            },
        )
        tx.execute(
            "UPDATE episodes SET current_script_id = %s, current_manifest_id = %s WHERE id = %s",
            (script.script_id, manifest.manifest_id, episode_id),
        )
    assets: dict[str, uuid.UUID] = {}
    for index, (line_id, speaker, text, actual_ms) in enumerate(LONG_LINES):
        assets[line_id] = world._register_line_audio(  # noqa: SLF001
            episode_id, season_id, line_id, speaker, text, actual_ms, {}
        )
        assets[f"ksh{index + 1}"] = world._register_shot_asset(  # noqa: SLF001
            episode_id, season_id, f"ksh{index + 1}", LONG_SHOT_MS
        )
    return episode_id, assets


def assembled_long_episode(world: World) -> uuid.UUID:
    """The long fixture assembled through the real T015 service (episode in AI_REVIEW)."""
    episode_id, assets = seed_long_episode(world)
    shot_assets = {key: value for key, value in assets.items() if key.startswith("ksh")}
    world.service.assemble_episode(episode_id, shot_assets=shot_assets)
    return episode_id


__all__ = [
    "FAKE_EVIDENCE",
    "LONG_LINES",
    "LONG_SHOT_MS",
    "TESTED_OPS",
    "TT_ACCOUNT",
    "TT_ROUTE",
    "assembled_long_episode",
    "build_long_manifest",
    "capability_record",
    "record_capability",
    "seed_long_episode",
    "variants_service",
]
