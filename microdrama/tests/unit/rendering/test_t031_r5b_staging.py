"""T031 R5b (RR-T15, RR-T16): office-reuse staging and bounded phase drives.

RR-T15 (R5C-5): one verified byte upload reused by distinct semantic bindings
(A2 as identity:A AND outfit:A-office; B2 likewise) through REAL
staging/binding with exact per-role/per-subject receipts and checksum
readback; the key-only guard lookup is gone (scoped by acquisition + key +
role + subject). S08's home outfit stages and binds.

RR-T16 (R5C-6): execute returns at the first SUBMITTED observation; the
bounded resume drive then reaches SCREEN_REVIEW with verified cleanup before
Pass A, and full reaches COMPUTE_COMPLETE.

Real composition (build_experiment_world + real guards) over scripted
transports, exactly like the Luna LF harness.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from test_benchmark_experiments import plan_for
from test_t031_h2b_p1_modes import _at4_quote, _paid_settings
from test_t031_h2b_p3_ambiguity import (
    _at17_png,
    _At17ComfyServer,
    _At17PodComfyTransport,
    _At17RunpodTransport,
)

from microdrama.persistence import Database

pytestmark = pytest.mark.db

T0 = datetime(2026, 11, 13, 15, tzinfo=UTC)


def _office_compose(db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The authored R5d role table through the real composed world.

    A2.png is BOTH character_identity:A and outfit:A-office (the R5C-5 byte
    reuse); B2.png likewise for B. S08 swaps to the home outfit/location.
    """
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
    clock = FakeClock(T0)
    ids = SequentialIds("r5-office")
    settings = _paid_settings()
    store = FilesystemObjectStore(tmp_path / "office-objects")
    budget = BudgetService(db, clock, ids, settings)
    with db.transaction() as tx:
        season_id = seed_season(tx)
        episode_id = seed_episode(tx, season_id, number=1)
        budget.open_episode_account(
            tx, season_id=season_id, episode_id=episode_id, policy=CostPolicy()
        )

    # One asset row per authored file. A2/B2 feed TWO ports each.
    files = [
        ("A2", 0, "image"),
        ("B2", 1, "image"),
        ("A-home", 2, "image"),
        ("SET-office", 3, "image"),
        ("SET-home", 4, "image"),
        ("PROP-envelope-01", 5, "image"),
        ("A-NEUTRAL", None, "audio"),
        ("B-NEUTRAL", None, "audio2"),
    ]
    asset_meta: dict[str, dict] = {}
    for index, (name, slot, kind) in enumerate(files):
        audio = kind.startswith("audio")
        # The two voice WAVs differ in length (distinct bytes -> distinct keys).
        data = make_wav_bytes(1500 if name == "A-NEUTRAL" else 1700) if audio else _at17_png(slot)
        digest = sha256_hex(data)
        asset_id = UUID(int=4100 + index)
        media_kind = "audio" if audio else "image"
        key = f"office-inputs/{asset_id}.{'wav' if audio else 'png'}"
        store.put_bytes(key, data, media_type=f"{media_kind}/{'wav' if audio else 'png'}")
        descriptor = AssetDescriptor(
            asset_id=asset_id,
            asset_kind=AssetKind.AUDIO if audio else AssetKind.IMAGE,
            object_key=key,
            sha256=digest,
            size_bytes=len(data),
            media_type=f"{media_kind}/{'wav' if audio else 'png'}",
            media=media_info() if audio else None,
            state=AssetState.ACCEPTED,
            provenance=Provenance.ORIGINAL_FIXTURE,
            episode_id=episode_id,
            season_id=season_id,
            created_at=T0,
        )
        with db.transaction() as tx:
            register_asset(tx, descriptor)
        asset_meta[name] = {
            "asset_id": str(asset_id),
            "asset_version": 1,
            "asset_sha256": digest,
            "media_kind": media_kind,
        }

    # The authored bindings (R5d table). Two ShotReferenceBindings share A2's
    # asset; two share B2's.
    binding_specs = [
        ("character_identity", "a", "A2"),
        ("outfit", "a-office", "A2"),
        ("outfit", "a-home", "A-home"),
        ("character_identity", "b", "B2"),
        ("outfit", "b-office", "B2"),
        ("location", "office", "SET-office"),
        ("location", "home", "SET-home"),
        ("prop", "envelope-01", "PROP-envelope-01"),
        ("voice", "a", "A-NEUTRAL"),
        ("voice", "b", "B-NEUTRAL"),
    ]
    references = []
    for index, (role, subject, name) in enumerate(binding_specs):
        kind = asset_meta[name]["media_kind"]
        route = f"office-rights-{index:02d}-{role.replace('_', '-')}".lower()
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
                record_id=UUID(int=4200 + index),
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
                        source=EvidenceSource.OFFICIAL_DOCUMENTATION,
                        ref=f"fixture:office-{role}",
                    )
                ],
                status=RightsStatus.ELIGIBLE,
                recorded_at=T0,
            ),
            source_provenance=Provenance.LIVE_PROVIDER,
        )
        references.append(
            ShotReferenceBinding.seal(
                record_id=UUID(int=4300 + index),
                version=1,
                created_at=T0 - timedelta(hours=1),
                updated_at=T0 - timedelta(hours=1),
                valid_from=T0 - timedelta(hours=1),
                valid_until=None,
                role=role,
                subject_id=subject,
                asset_id=UUID(asset_meta[name]["asset_id"]),
                asset_version=1,
                asset_sha256=asset_meta[name]["asset_sha256"],
                rights=grant,
            ).model_dump(mode="json")
        )

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

    plan = plan_for(
        episode_id,
        shots=[
            {
                "shot_id": f"S0{i}",
                "thai_line": "สวัสดี",
                "english_line": "Hello",
                "english_prompt": "An office corridor, late afternoon light.",
                "speaker_subject_ids": ["a", "b"],
            }
            for i in range(1, 9)
        ],
    )

    def ports_for_shot(shot_id: str) -> list[dict]:
        home = shot_id == "S08"
        slots = [
            ("character_identity", "a", "A2", "ref_images.ref_image_0"),
            (
                "outfit",
                "a-office" if not home else "a-home",
                "A-home" if home else "A2",
                "ref_images.ref_image_1",
            ),
            ("character_identity", "b", "B2", "ref_images.ref_image_2"),
            ("outfit", "b-office", "B2", "ref_images.ref_image_3"),
            (
                "location",
                "home" if home else "office",
                "SET-home" if home else "SET-office",
                "ref_images.ref_image_4",
            ),
            ("prop", "envelope-01", "PROP-envelope-01", "ref_images.ref_image_5"),
            ("voice", "a", "A-NEUTRAL", "ref_audios.ref_audio_0"),
            ("voice", "b", "B-NEUTRAL", "ref_audios.ref_audio_1"),
        ]
        return [
            {
                **asset_meta[name],
                "role": role,
                "subject_id": subject,
                "destination_slot": slot,
                "shot_id": shot_id,
            }
            for role, subject, name, slot in slots
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
            "eligible_until": (T0 + timedelta(days=365)).isoformat(),
            "hard_stop_utc": (T0 + timedelta(hours=4)).isoformat(),
        }
    )
    service = BenchmarkService(db, settings, clock=clock, ids=ids)
    service.prepare(plan)
    service.seal(plan.experiment_id, seal)
    authorization = BenchmarkAuthorization.model_validate(
        {
            "operator": "fixture-operator.invalid",
            "change_ref": "r5-office-reuse",
            "experiment_id": str(plan.experiment_id),
            "episode_id": str(plan.episode_id),
            "plan_sha256": plan.plan_sha256,
            "sealed_sha256": seal.sealed_sha256,
            "provider_account_ref": "acct:fixture",
            "max_new_exposure_micro_usd": 8_000_000,
            "max_gpu_ms": 14_400_000,
            "hard_stop_utc": (T0 + timedelta(hours=4)).isoformat(),
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
    server = _At17ComfyServer(json.dumps(raw_schema).encode())
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
    harness.asset_meta = asset_meta
    harness.runpod = runpod
    harness.server = server
    harness.comfy = comfy
    harness.factory = factory
    harness.service = BenchmarkService(db, settings, clock=clock, ids=ids, world_factory=factory)
    return harness


def test_rr_t15_office_reuse_stages_and_binds_with_per_role_receipts(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """R5C-5: A2 is uploaded ONCE yet binds as identity:a and outfit:a-office
    (B2 likewise); every role row keeps its own VERIFIED receipt with checksum
    readback; S08's home outfit stages and binds through the same world."""
    harness = _office_compose(db, tmp_path, monkeypatch)
    plan = harness.plan
    first = harness.service.execute(
        plan.experiment_id,
        phase="screen",
        authorization=harness.authorization,
        quote=harness.quote,
        expected_sha256=harness.authorization.authorization_sha256,
    )
    assert first["execution_state"] != "FAILED", first
    last = first
    for _ in range(24):
        if last["execution_state"] == "SCREEN_REVIEW":
            break
        last = harness.service.resume(
            plan.experiment_id,
            authorization=harness.authorization,
            quote=harness.quote,
            expected_sha256=harness.authorization.authorization_sha256,
            phase="screen",
        )
        harness.clock.advance(seconds=1)
    assert last["execution_state"] == "SCREEN_REVIEW", last["execution_state"]

    with db.transaction(readonly=True) as tx:
        rows = tx.fetchall("SELECT * FROM benchmark_uploads ORDER BY role, subject_id")
        by_identity = {(r["role"], r["subject_id"], r["asset_sha256"]): r for r in rows}
        a2 = harness.asset_meta["A2"]["asset_sha256"]
        b2 = harness.asset_meta["B2"]["asset_sha256"]
        identity_a = by_identity[("character_identity", "a", a2)]
        outfit_a_office = by_identity[("outfit", "a-office", a2)]
        identity_b = by_identity[("character_identity", "b", b2)]
        outfit_b_office = by_identity[("outfit", "b-office", b2)]
        for row in (identity_a, outfit_a_office, identity_b, outfit_b_office):
            assert row["state"] == "VERIFIED", (row["role"], row["subject_id"], row["state"])
            assert row["verified_readback_sha256"] == row["asset_sha256"]
        # One byte upload reused: the reused ports share the upload key, and
        # the pod saw each distinct BYTES file exactly once.
        assert identity_a["upload_key"] == outfit_a_office["upload_key"]
        assert identity_b["upload_key"] == outfit_b_office["upload_key"]
        # S08's home outfit staged as its own role row.
        home = by_identity[("outfit", "a-home", harness.asset_meta["A-home"]["asset_sha256"])]
        assert home["state"] == "VERIFIED"
    # One byte upload per distinct FILE: 8 distinct digests across the 10
    # role rows (A2 and B2 each carry two rows, one shared upload key).
    distinct_keys = {row["upload_key"] for row in rows}
    assert len(distinct_keys) == 8, sorted(distinct_keys)
    assert len(rows) == 10, [(r["role"], r["subject_id"]) for r in rows]


def test_rr_t16_bounded_resume_reaches_screen_review_then_compute_complete(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """R5C-6: one execute returns at the FIRST observation (SUBMITTED) — that
    is not phase completion; the bounded resume loop drives screen to
    SCREEN_REVIEW with verified cleanup, Pass A, then full to
    COMPUTE_COMPLETE."""
    harness = _office_compose(db, tmp_path, monkeypatch)
    plan = harness.plan
    first = harness.service.execute(
        plan.experiment_id,
        phase="screen",
        authorization=harness.authorization,
        quote=harness.quote,
        expected_sha256=harness.authorization.authorization_sha256,
    )
    # The first execute stops at the first observation - samples are still
    # mid-flight, the phase is NOT complete.
    assert first["execution_state"] == "SCREEN_RUNNING", first["execution_state"]
    assert all(s["state"] != "SUCCEEDED" for s in first["samples"]), first["samples"]

    last = first
    for _ in range(24):
        if last["execution_state"] == "SCREEN_REVIEW":
            break
        last = harness.service.resume(
            plan.experiment_id,
            authorization=harness.authorization,
            quote=harness.quote,
            expected_sha256=harness.authorization.authorization_sha256,
            phase="screen",
        )
        harness.clock.advance(seconds=1)
    assert last["execution_state"] == "SCREEN_REVIEW"
    assert last["cleanup_state"] == "VERIFIED", last["cleanup_state"]

    harness.service.record_screening(
        plan.experiment_id,
        {
            "sealed_sha256": harness.seal.sealed_sha256,
            "actor_ref": "offline-test-human",
            "output_hashes": {
                s["sample_id"]: (s["output"] or {}).get("sha256")
                for s in last["samples"]
                if s["sample_id"] in ("S01-R1", "S03-R1", "S07-R1")
            },
            "decision": "PASS",
            "coverage": {"fixture": "PASS"},
            "rubric_version": "offline-fixture",
        },
    )
    # The full phase needs the screen pod's invoice tail cleared first - the
    # bounded loop stops on the admission blocker, runs the per-pod billing
    # procedure (R5f's offline shape: bill the lease to BILLED + sweep), then
    # continues on the full phase's own acquisition (the AT-06 two-phase shape).
    from test_t031_hcf_f3_finality import _bill_lease_to_billed

    last = None
    for _ in range(48):
        last = harness.service.resume(
            plan.experiment_id,
            authorization=harness.authorization,
            quote=harness.quote,
            expected_sha256=harness.authorization.authorization_sha256,
            phase="full",
        )
        if last["execution_state"] == "COMPUTE_COMPLETE":
            break
        blockers = (last.get("admission") or {}).get("blockers") or []
        if any("cleanup pending" in blocker for blocker in blockers):
            with db.transaction(readonly=True) as tx:
                pending = tx.fetchone(
                    "SELECT a.lease_id FROM benchmark_acquisitions a "
                    "WHERE a.experiment_id=%s AND a.state='CLEANUP_PENDING' "
                    "AND a.lease_id IS NOT NULL ORDER BY a.generation LIMIT 1",
                    (plan.experiment_id,),
                )
            if pending is not None:
                readiness = _bill_lease_to_billed(
                    db, harness, lease_id=pending["lease_id"], amount_micro_usd=900_250
                )
                assert readiness == "BILLED"
                harness.service.sweep(plan.experiment_id)
                # The cleaned-up generation's pod took its pod-side ComfyUI
                # with it; the full phase's new pod boots a fresh one.
                harness.server.alive = True
                harness.server.inputs.clear()
                harness.server.outputs.clear()
                harness.server.prompts.clear()
        harness.clock.advance(seconds=1)
    assert last is not None and last["execution_state"] == "COMPUTE_COMPLETE", last
    assert last["execution_outcome"] == "SUCCEEDED"
