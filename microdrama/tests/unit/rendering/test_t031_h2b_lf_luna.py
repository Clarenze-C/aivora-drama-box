"""LF (GLM review of Luna's 82135d4): shot-scoped costume-change seals must
actually stage and bind.

L-1 (BLOCKING): the binder counts per-media-kind ordinals in LIST order while
the seal validator only requires the per-shot destination SET to be contiguous
- validator-legal seals (including the review's S08 costume-change shape)
raised SchemaInvalid inside native.bind AFTER pod acquisition.

L-2 (BLOCKING): bind's upload lookup keyed (role, subject_id) alone, so the
same subject wearing outfit A and outfit B collapsed to one receipt row and
the wrong shot's bind failed the strict receipt check.

The seal here is the ruling's acceptance shape: S01-S07 wear outfit A, S08
wears outfit B (same role AND subject), and every shot's port list is
deliberately non-ordinal (character@0, location@2, voice@0, outfit@1).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from microdrama.persistence import Database

pytestmark = pytest.mark.db


def _lf_compose(db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from test_benchmark_experiments import plan_for
    from test_t031_h2b_p1_modes import _at4_quote, _paid_settings
    from test_t031_h2b_p3_ambiguity import (
        _at17_png,
        _At17ComfyServer,
        _At17PodComfyTransport,
        _At17RunpodTransport,
    )

    from microdrama.budget import BudgetService
    from microdrama.contracts.enums import (
        AssetKind,
        AssetState,
        ControlKind,
        EvidenceSource,
        Provenance,
        RenderTier,
        RightsStatus,
        RightsSubjectKind,
    )
    from microdrama.contracts.examples import media_info
    from microdrama.contracts.hashing import sha256_hex
    from microdrama.contracts.media import AssetDescriptor
    from microdrama.contracts.primitives import EvidenceRef
    from microdrama.contracts.registries import PresetRecord, RightsRecord
    from microdrama.contracts.season import CostPolicy
    from microdrama.contracts.v2 import ShotReferenceBinding
    from microdrama.core.registry.rights import RightsRegistry
    from microdrama.persistence import register_asset
    from microdrama.persistence.object_store import FilesystemObjectStore
    from microdrama.pipeline.benchmark_authorization import (
        BenchmarkAuthorization,
        BenchmarkSeal,
        document_sha256,
    )
    from microdrama.pipeline.benchmark_service import BenchmarkService
    from microdrama.pipeline.experimental_world import build_experiment_world
    from microdrama.rendering.pika_transport import mapped_schema_sha256
    from microdrama.rendering.workflows.templates import PIKA_TEMPLATE
    from microdrama.rendering.workflows.templates import (
        template_sha256 as _template_sha256,
    )
    from microdrama.testing.fakes import FakeClock, SequentialIds
    from microdrama.testing.media import make_wav_bytes
    from microdrama.testing.seed import seed_episode, seed_season

    preset = PresetRecord(
        preset_id="pika-h3-flex-ref2va-benchmark-v1",
        version=1,
        tier=RenderTier.QUALITY_EIGHT_STEP,
        workflow_sha256=_template_sha256(PIKA_TEMPLATE),
        model_mode="fixture",
        gpu_type="NVIDIA A40",
        min_vram_gb=24,
        host_ram_gb=64,
        precision="fp16",
        width=480,
        height=832,
        frames=124,
        fps=24,
        steps=8,
        attention_backend="fixture",
        supported_controls=[
            ControlKind.TEXT_PROMPT,
            ControlKind.SEED,
            ControlKind.CHARACTER_REFERENCE,
            ControlKind.WARDROBE_REFERENCE,
            ControlKind.LOCATION_REFERENCE,
        ],
        supports_thai_dialogue=None,
        rights_route_id=None,
        measured=None,
        evidence=[],
        enabled=False,
    )
    monkeypatch.setattr(
        "microdrama.pipeline.experimental_world.ExperimentalPresetPolicy.validate",
        lambda *a, **k: preset,
    )
    monkeypatch.setattr(
        "microdrama.pipeline.benchmark_authorization.BenchmarkAuthorization.validate_for",
        lambda *a, **k: None,
    )

    t0 = datetime(2026, 11, 10, 12, tzinfo=UTC)
    clock = FakeClock(t0)
    ids = SequentialIds("lf-luna")
    settings = _paid_settings()
    store = FilesystemObjectStore(tmp_path / "lf-objects")
    budget = BudgetService(db, clock, ids, settings)
    with db.transaction() as tx:
        season_id = seed_season(tx)
        episode_id = seed_episode(tx, season_id, number=1)
        budget.open_episode_account(
            tx, season_id=season_id, episode_id=episode_id, policy=CostPolicy()
        )

    # Five canonical assets: the at17 roles plus the costume-change pair -
    # outfit A and outfit B share (role=outfit, subject_id=wardrobe) and differ
    # only in asset identity (the L-2 shape). spec name -> (binding role,
    # subject, distinct png index, media kind)
    specs = [
        ("character_identity", "character_identity", "speaker-a", 0, "image"),
        ("outfit_a", "outfit", "wardrobe", 1, "image"),
        ("outfit_b", "outfit", "wardrobe", 2, "image"),
        ("location", "location", "speaker-a", 3, "image"),
        ("voice", "voice", "speaker-a", 4, "audio"),
    ]
    references, asset_shas, asset_meta = [], {}, {}
    for index, (name, role, subject, slot_index, kind) in enumerate(specs):
        data = make_wav_bytes(1500) if kind == "audio" else _at17_png(slot_index)
        digest = sha256_hex(data)
        asset_id = UUID(int=2100 + index)
        key = f"lf-inputs/{asset_id}.{'wav' if kind == 'audio' else 'png'}"
        stored = store.put_bytes(
            key, data, media_type="audio/wav" if kind == "audio" else "image/png"
        )
        assert stored.sha256 == digest
        descriptor = AssetDescriptor(
            asset_id=asset_id,
            asset_kind=AssetKind.AUDIO if kind == "audio" else AssetKind.IMAGE,
            object_key=key,
            sha256=digest,
            size_bytes=stored.size_bytes,
            media_type="audio/wav" if kind == "audio" else "image/png",
            media=media_info() if kind == "audio" else None,
            state=AssetState.ACCEPTED,
            provenance=Provenance.ORIGINAL_FIXTURE,
            episode_id=episode_id,
            season_id=season_id,
            created_at=t0,
        )
        with db.transaction() as tx:
            register_asset(tx, descriptor)
        route = f"lf-rights-{name}"
        grant = {
            "rights_route_id": route,
            "subject_kind": (
                RightsSubjectKind.VOICE if kind == "audio" else RightsSubjectKind.REFERENCE
            ).value,
            "subject_ref": subject,
            "rights_version": 1,
            "status": "ELIGIBLE",
            "territories": ["TH"],
            "commercial_use": True,
            "output_release_allowed": True,
            "expires_at": None,
            "evidence_sha256": ["e" * 64],
        }
        RightsRegistry(db, clock, settings).record(
            RightsRecord(
                record_id=UUID(int=2200 + index),
                rights_route_id=route,
                version=1,
                subject_kind=(
                    RightsSubjectKind.VOICE if kind == "audio" else RightsSubjectKind.REFERENCE
                ),
                subject_ref=subject,
                territories=["WORLDWIDE"],
                commercial_use=True,
                output_release_allowed=True,
                required_disclosures=[],
                expires_at=None,
                evidence=[
                    EvidenceRef(
                        source=EvidenceSource.OFFICIAL_DOCUMENTATION, ref=f"fixture:lf-{role}"
                    )
                ],
                status=RightsStatus.ELIGIBLE,
                recorded_at=t0,
            ),
            source_provenance=Provenance.LIVE_PROVIDER,
        )
        binding = ShotReferenceBinding.seal(
            record_id=UUID(int=2300 + index),
            version=1,
            created_at=t0 - timedelta(hours=1),
            updated_at=t0 - timedelta(hours=1),
            valid_from=t0 - timedelta(hours=1),
            valid_until=None,
            role=role,
            subject_id=subject,
            asset_id=asset_id,
            asset_version=1,
            asset_sha256=digest,
            rights=grant,
        )
        references.append(binding.model_dump(mode="json"))
        asset_shas[name] = digest
        asset_meta[name] = {
            "role": role,
            "subject_id": subject,
            "asset_id": str(asset_id),
            "asset_version": 1,
            "asset_sha256": digest,
            "media_kind": kind,
        }

    rights_hash = document_sha256(
        {
            "rights": [
                ShotReferenceBinding.model_validate(item).rights.model_dump(mode="json")
                for item in references
            ],
            "territories": ["TH"],
        }
    )
    fixture = json.loads(
        (
            Path(__file__).parents[2]
            / "fixtures/pika_h3_flex_object_info_OFFLINE_FIXTURE_ONLY.json"
        ).read_text()
    )
    raw_schema = fixture["schemas"]
    schema_bytes = json.dumps(raw_schema).encode()

    plan = plan_for(
        episode_id,
        shots=[
            {
                "shot_id": f"S0{i}",
                "thai_line": "สวัสดี",
                "english_line": "Hello",
                "english_prompt": "A street food stall at dusk, warm practical light.",
                "speaker_subject_ids": ["speaker-a"],
            }
            for i in range(1, 9)
        ],
    )

    # The shot-scoped costume-change port map: S01-S07 wear outfit A, S08 wears
    # outfit B (SAME role and subject - L-2), and every shot lists its ports in
    # a deliberately non-ordinal order (character@0, location@2, voice@0,
    # outfit@1 - L-1): the per-shot destination SET is contiguous, exactly what
    # the seal validator accepts.
    def ports_for_shot(shot_id: str) -> list[dict]:
        outfit = "outfit_a" if shot_id != "S08" else "outfit_b"
        slots = [
            ("character_identity", "ref_images.ref_image_0"),
            ("location", "ref_images.ref_image_2"),
            ("voice", "ref_audios.ref_audio_0"),
            (outfit, "ref_images.ref_image_1"),
        ]
        return [
            {**asset_meta[name], "destination_slot": slot, "shot_id": shot_id}
            for name, slot in slots
        ]

    port_map: list[dict] = []
    for index in range(1, 9):
        port_map.extend(ports_for_shot(f"S0{index}"))
    seal = BenchmarkSeal.model_validate(
        {
            "experiment_id": str(plan.experiment_id),
            "plan_sha256": plan.plan_sha256,
            "references": references,
            "port_map": port_map,
            "runtime_profile": {"profile": "fixture"},
            "image_ref": "registry.example/drama@sha256:" + "b" * 64,
            "node_schema_sha256": mapped_schema_sha256(raw_schema, PIKA_TEMPLATE.node_classes),
            "rights_evidence_hash": rights_hash,
            "schema_evidence": "LIVE_PROVIDER",
            "schema_attestation_source": "INDEPENDENT_RUNTIME_CAPTURE",
            "territories": ["TH"],
            "eligible_until": (t0 + timedelta(days=365)).isoformat(),
            "hard_stop_utc": (t0 + timedelta(hours=4)).isoformat(),
        }
    )
    service = BenchmarkService(db, settings, clock=clock, ids=ids)
    service.prepare(plan)
    service.seal(plan.experiment_id, seal)
    authorization = BenchmarkAuthorization.model_validate(
        {
            "operator": "fixture-operator.invalid",
            "change_ref": "lf-costume-change",
            "experiment_id": str(plan.experiment_id),
            "episode_id": str(plan.episode_id),
            "plan_sha256": plan.plan_sha256,
            "sealed_sha256": seal.sealed_sha256,
            "provider_account_ref": "acct:fixture",
            "max_new_exposure_micro_usd": 8_000_000,
            "max_gpu_ms": 14_400_000,
            "hard_stop_utc": (t0 + timedelta(hours=4)).isoformat(),
            "allowed_gpu_types": ["NVIDIA A40"],
            "minimum_host_ram_gb": 64,
            "max_hourly_micro_usd": 850_000,
            "max_storage_exposure_micro_usd": 2_000_000,
            "container_disk_gb": 100,
            "persistent_volume_gb": 100,
            "shutdown_reserve_micro_usd": 500_000,
            "namespace": "benchx",
            "runpod_credential_ref": "credref:fixture-runpod",
            "comfy_credential_ref": "credref:fixture-comfy",
            "rights_evidence_hash": seal.rights_evidence_hash,
        }
    )
    for ref in (authorization.runpod_credential_ref, authorization.comfy_credential_ref):
        import os as _os

        path = tmp_path / f"{ref.replace(':', '_')}.secret"
        path.write_text(f"synthetic-{ref}", encoding="utf-8")
        _os.chmod(path, 0o600)
        with db.transaction() as tx:
            tx.execute(
                "INSERT INTO credential_refs(ref, purpose, provider, store, locator) "
                "VALUES(%s, 'fixture', 'runpod', 'FILE', %s)",
                (ref, str(path)),
            )
    server = _At17ComfyServer(schema_bytes)
    runpod = _At17RunpodTransport(clock.now, server)
    comfy = _At17PodComfyTransport(server, upload_timeout=False, prompt_timeouts=0)

    def factory(
        *,
        experiment_id,
        budget,
        authorization=None,
        quote=None,
        mode="EXECUTE",
        acquisition_id=None,
    ):
        return build_experiment_world(
            settings,
            db,
            budget,
            store,
            experiment_id=experiment_id,
            authorization=authorization,
            quote=quote,
            mode=mode,
            acquisition_id=acquisition_id,
            clock=clock,
            ids=ids,
            runpod_transport=runpod,
            comfy_transport=comfy,
        )

    class _Harness:
        pass

    harness = _Harness()
    harness.db = db
    harness.settings = settings
    harness.store = store
    harness.clock = clock
    harness.ids = ids
    harness.plan = plan
    harness.seal = seal
    harness.authorization = authorization
    harness.quote = _at4_quote(clock)
    harness.asset_shas = asset_shas
    harness.runpod = runpod
    harness.server = server
    harness.comfy = comfy
    harness.factory = factory
    harness.service = BenchmarkService(db, settings, clock=clock, ids=ids, world_factory=factory)
    return harness


def test_l1_l2_shot_scoped_costume_change_stages_and_binds(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """L-1 + L-2 (BLOCKING): a validator-legal shot-scoped costume-change seal
    (S01-S07 outfit A, S08 outfit B, same role and subject, non-ordinal port
    lists) must stage every asset once and bind EVERY shot - the binder accepts
    the maps the validator accepts, and the same-subject outfits never collapse
    into one receipt."""
    from test_t031_h2b_p3_ambiguity import _at17_resume

    harness = _lf_compose(db, tmp_path, monkeypatch)
    plan = harness.plan

    first = harness.service.execute(
        plan.experiment_id,
        phase="screen",
        authorization=harness.authorization,
        quote=harness.quote,
        expected_sha256=harness.authorization.authorization_sha256,
    )
    assert first["execution_state"] != "FAILED"  # L-1/L-2 failed the run at HEAD
    last = _at17_resume(harness)
    assert last is not None and last["execution_state"] != "FAILED"
    with db.transaction(readonly=True) as tx:
        operation = tx.fetchone(
            "SELECT o.state FROM provider_operations o JOIN benchmark_samples s "
            "ON s.reservation_id=o.reservation_id WHERE s.experiment_id=%s",
            (plan.experiment_id,),
        )
        uploads = tx.fetchall(
            "SELECT asset_sha256, media_kind, role, subject_id, state FROM benchmark_uploads"
        )
    assert operation is not None, "the dispatch never reached a prompt operation"

    # L-2: outfit A AND outfit B staged as their own rows (same role/subject),
    # all verified - never collapsed to one receipt.
    outfit_rows = [row for row in uploads if row["role"] == "outfit"]
    assert {row["asset_sha256"] for row in outfit_rows} == {
        harness.asset_shas["outfit_a"],
        harness.asset_shas["outfit_b"],
    }
    assert all(row["state"] == "VERIFIED" for row in uploads)
    assert harness.comfy.upload_posts == 5  # one POST per asset, exactly once

    # L-1: the bound manifests carry the right costume per shot - S01-S07 wear
    # outfit A, S08 wears outfit B (through _SealedNativeInputs.manifest, the
    # same per-shot derivation bind uses).
    from microdrama.rendering.benchmark_experiments import ExperimentBudgetService

    world = harness.factory(
        experiment_id=plan.experiment_id,
        budget=ExperimentBudgetService(
            db, harness.clock, harness.ids, harness.settings, experiment_id=plan.experiment_id
        ),
        authorization=harness.authorization,
        quote=harness.quote,
    )
    for shot_id, expected_outfit in (("S01", "outfit_a"), ("S08", "outfit_b")):
        with db.transaction(readonly=True) as tx:
            sample = tx.fetchone(
                "SELECT * FROM benchmark_samples WHERE experiment_id=%s AND sample_id=%s",
                (plan.experiment_id, f"{shot_id}-R1"),
            )
        manifest, _, _, _ = world._native.manifest(sample)
        outfits = [b for b in manifest.bindings if b.role.value == "outfit"]
        assert [b.asset_sha256 for b in outfits] == [harness.asset_shas[expected_outfit]], shot_id
