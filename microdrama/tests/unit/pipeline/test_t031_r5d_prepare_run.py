"""T031 R5d (RR-T9): the run-assembly tool ``tools/t031_prepare_run.py``.

``register``/``author``/``quote``/``verify`` against a real test database:
real episode/account/asset/rights/preset/credential rows (never
FAKE_SYNTHETIC), the authored plan/seal/authorization draft, the quote built
through ``load_document(AcquisitionQuote)``, and a preflight PASS on the
authored set through the REAL ``ExperimentalPresetPolicy`` (no monkeypatch -
the registered rows are what must satisfy it). Any semantic edit changes the
printed canonical sha, any byte edit the file-byte sha, and no credential
value ever reaches the output.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_t031_r5c_seal import _predicted_raw

TOOLS = Path(__file__).resolve().parents[3] / "tools"
sys.path.insert(0, str(TOOLS))

import t031_prepare_run as prepare_run  # noqa: E402

from microdrama.config import Settings  # noqa: E402
from microdrama.contracts.enums import ExecutionMode  # noqa: E402
from microdrama.contracts.hashing import sha256_hex  # noqa: E402
from microdrama.persistence.db import jsonb  # noqa: E402
from microdrama.pipeline.benchmark import main as benchmark_main  # noqa: E402
from microdrama.pipeline.benchmark_authorization import (  # noqa: E402
    AcquisitionQuote,
    BenchmarkAuthorization,
    BenchmarkPlan,
    BenchmarkSeal,
    document_sha256,
    load_document,
)

pytestmark = pytest.mark.db

IMAGE_REF = "ghcr.io/clarenze-c/drama-pika-h3-flex@sha256:" + "ab" * 32
RUNPOD_CRED = "credref:runpod-t031-test"
COMFY_CRED = "credref:comfy-t031-test"
CRED_SENTINELS = ("runpod-secret-value-r5d", "comfy-secret-value-r5d")
IMAGE_REF_IDS = ("A2", "A-home", "B2", "SET-office", "SET-home", "PROP-envelope-01")
VOICE_REF_IDS = ("A-NEUTRAL", "B-NEUTRAL")
ALL_REF_IDS = IMAGE_REF_IDS + VOICE_REF_IDS
UNPICKED = ("A1", "A3", "B1", "B3")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _wav_bytes(sample_rate_hz: int = 24_000, channels: int = 1, ms: int = 1_500) -> bytes:
    """A real minimal PCM WAV (16-bit), distinct durations per voice."""
    import struct

    bits = 16
    frames = int(sample_rate_hz * channels * ms / 1000)
    data = b"\x00\x01" * frames
    byte_rate = sample_rate_hz * channels * bits // 8
    block_align = channels * bits // 8
    fmt = struct.pack("<HHIIHH", 1, channels, sample_rate_hz, byte_rate, block_align, bits)
    return (
        b"RIFF"
        + struct.pack("<I", 36 + len(data))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", len(fmt))
        + fmt
        + b"data"
        + struct.pack("<I", len(data))
        + data
    )


#: The voice fixtures' actual PCM facts (R5V-10): 24 kHz mono 16-bit.
VOICE_WAV_MS = {"A-NEUTRAL": 1_500, "B-NEUTRAL": 2_500}


def _pick_files(tmp_path: Path) -> dict[str, bytes]:
    return {
        **{ref: f"png-bytes-{ref}-r5d".encode() for ref in IMAGE_REF_IDS},
        **{ref: _wav_bytes(ms=VOICE_WAV_MS[ref]) for ref in VOICE_REF_IDS},
    }


def _write_manifests(tmp_path: Path, files: dict[str, bytes]) -> tuple[Path, Path, Path]:
    def _record(ref: str, suffix: str) -> dict:
        target = tmp_path / f"{ref}{suffix}"
        target.write_bytes(files[ref])
        return {"ref_id": ref, "file": str(target), "sha256": sha256_hex(files[ref])}

    r1 = tmp_path / "refs-r1.jsonl"
    r1.write_text(
        "\n".join(json.dumps(_record(ref, ".png")) for ref in ("A2", "B2")) + "\n",
        encoding="utf-8",
    )
    r2 = tmp_path / "refs-r2.jsonl"
    r2.write_text(
        "\n".join(
            json.dumps(_record(ref, ".png"))
            for ref in ("A-home", "SET-office", "SET-home", "PROP-envelope-01")
        )
        + "\n",
        encoding="utf-8",
    )
    voices = tmp_path / "voices.json"
    voices.write_text(json.dumps([_record(ref, ".wav") for ref in VOICE_REF_IDS]))
    return r1, r2, voices


def _write_shots_and_trials(tmp_path: Path) -> tuple[Path, Path]:
    shots = tmp_path / "shots.csv"
    rows = [
        {
            "shot_id": f"S0{index}",
            "thai_line": f"ฉันจะฟัง บรรทัด {index}",
            "english_meaning": f"I will listen, line {index}",
            "class": "two_shot" if index % 2 else "single",
            "speaker": "A" if index % 2 else "B",
            "action": f"A and B face each other in beat {index}",
            "critical_observations": f"envelope visible in beat {index}",
        }
        for index in range(1, 9)
    ]
    with shots.open("w", encoding="utf-8", newline="") as handle:
        csv.DictWriter(handle, fieldnames=list(rows[0])).writeheader()
        csv.DictWriter(handle, fieldnames=list(rows[0])).writerows(rows)
    trials = tmp_path / "trials.csv"
    trial_rows = [
        {
            "sample_id": f"S0{shot}-R{repeat}",
            "shot_id": f"S0{shot}",
            "repeat": str(repeat),
            "seed": str(1000 + shot * 3 + repeat),
            "phase": "screen" if f"S0{shot}-R{repeat}" in prepare_run.SCREEN_IDS else "full",
        }
        for shot in range(1, 9)
        for repeat in range(1, 4)
    ]
    with trials.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(trial_rows[0]))
        writer.writeheader()
        writer.writerows(trial_rows)
    return shots, trials


def _capture_files(tmp_path: Path) -> tuple[Path, Path]:
    import t031_schema_predict as predict

    from microdrama.rendering.pika_transport import mapped_schema_sha256
    from microdrama.rendering.workflows.templates import PIKA_TEMPLATE

    raw = _predicted_raw()
    capture = {
        "manifest_digest": IMAGE_REF.rsplit("@sha256:", 1)[-1],
        "placeholder_names": predict.placeholder_layout(predict.load_manifest()),
        "tool_version": predict.TOOL_VERSION,
        "captured_at": "2026-11-14T00:00:00+00:00",
        "node_schema_sha256": mapped_schema_sha256(raw, PIKA_TEMPLATE.node_classes),
        "evidence_kind": "PREDICTED_SCHEMA_PLACEHOLDERS",
        "inference_verified": False,
    }
    record = tmp_path / "capture-record.json"
    record.write_text(json.dumps(capture, indent=2, sort_keys=True))
    raw_path = tmp_path / "raw_object_info.json"
    raw_path.write_text(json.dumps(raw, sort_keys=True))
    return record, raw_path


def _seed_credentials(db, tmp_path: Path) -> None:
    for ref, sentinel in zip((RUNPOD_CRED, COMFY_CRED), CRED_SENTINELS, strict=True):
        path = tmp_path / f"{ref.replace(':', '_')}.secret"
        path.write_text(sentinel, encoding="utf-8")
        path.chmod(0o600)
        with db.transaction() as tx:
            tx.execute(
                "INSERT INTO credential_refs(ref, purpose, provider, store, locator) "
                "VALUES(%s, 't031-benchmark', 'runpod', 'FILE', %s)",
                (ref, str(path)),
            )


def _register(db_dsn: str, tmp_path: Path, out: Path) -> None:
    _register_files(db_dsn, tmp_path, out, _pick_files(tmp_path))


def _register_files(db_dsn: str, tmp_path: Path, out: Path, files: dict[str, bytes]) -> None:
    r1, r2, voices = _write_manifests(tmp_path, files)
    assert (
        prepare_run.main(
            [
                "register",
                "--dsn",
                db_dsn,
                "--refs-r1",
                str(r1),
                "--refs-r2",
                str(r2),
                "--voices",
                str(voices),
                "--store-root",
                str(tmp_path / "store"),
                "--out",
                str(out),
                "--runpod-credential",
                RUNPOD_CRED,
                "--comfy-credential",
                COMFY_CRED,
            ]
        )
        == 0
    )


def _author(
    tmp_path: Path, out: Path, experiment_id: str, *, regenerate_inputs: bool = True
) -> Path:
    if regenerate_inputs:
        shots, trials = _write_shots_and_trials(tmp_path)
    else:
        # Keep the caller's edited CSVs on disk (the semantic-edit re-run).
        shots = tmp_path / "shots.csv"
        trials = tmp_path / "trials.csv"
    capture, raw = _capture_files(tmp_path)
    now = _utcnow()
    assert (
        prepare_run.main(
            [
                "author",
                "--experiment-id",
                experiment_id,
                "--episode-id",
                str(prepare_run.BENCHMARK_EPISODE_ID),
                "--bindings",
                str(out / "registered-bindings.json"),
                "--shots",
                str(shots),
                "--trials",
                str(trials),
                "--capture-record",
                str(capture),
                "--prediction-raw",
                str(raw),
                "--image-ref",
                IMAGE_REF,
                "--eligible-until",
                (now + timedelta(days=3)).isoformat(),
                "--hard-stop-utc",
                (now + timedelta(days=2)).isoformat(),
                "--change-ref",
                "t031-r5d-test",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    return trials


def _quote_fields() -> dict:
    now = _utcnow()
    return {
        "quote_id": "console-quote-r5d-1",
        "captured_at": (now - timedelta(minutes=30)).isoformat(),
        "expires_at": (now + timedelta(minutes=30)).isoformat(),
        "gpu_type": "NVIDIA A40",
        "host_ram_gb": 64,
        "compute_micro_usd_per_hour": 849_600,
        "container_disk_gb": 100,
        "persistent_volume_gb": 0,
        "container_storage_micro_usd_per_gb_month": 100_000,
        "persistent_storage_micro_usd_per_gb_month": 100_000,
        "max_storage_exposure_micro_usd": 60_000,
        "maximum_runtime_ms": 600_000,
        "source_evidence_sha256": "e" * 64,
    }


def _write_quote(tmp_path: Path) -> Path:
    fields = tmp_path / "quote-fields.json"
    fields.write_text(json.dumps(_quote_fields()))
    quote = tmp_path / "quote.json"
    assert prepare_run.main(["quote", "--fields", str(fields), "--out", str(quote)]) == 0
    return quote


def _settings(db_dsn: str) -> Settings:
    return Settings(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
        database_url=db_dsn,
    )


def _assert_no_credential_value(text: str) -> None:
    for sentinel in CRED_SENTINELS:
        assert sentinel not in text


def test_rr_t9_register_creates_real_rows_and_reports_canary_spend(
    db, db_dsn, tmp_path, capsys
) -> None:
    _seed_credentials(db, tmp_path)
    out = tmp_path / "out"
    _register(db_dsn, tmp_path, out)
    printed = capsys.readouterr().out
    _assert_no_credential_value(printed)
    report = json.loads(printed)
    assert report["register"] == "created"
    assert report["episode_id"] == str(prepare_run.BENCHMARK_EPISODE_ID)
    assert report["prior_canary_spend_micro_usd"] == 0
    bindings = json.loads((out / "registered-bindings.json").read_text())
    _assert_no_credential_value((out / "registered-bindings.json").read_text())
    assert len(bindings["bindings"]) == 10  # the role table, one binding each

    with db.transaction(readonly=True) as tx:
        episode = tx.fetchone(
            "SELECT e.season_id, a.cap_micro_usd FROM episodes e "
            "JOIN budget_accounts a ON a.episode_id=e.id AND a.scope_kind='EPISODE' "
            "WHERE e.id=%s",
            (prepare_run.BENCHMARK_EPISODE_ID,),
        )
        assets = tx.fetchall(
            "SELECT sha256, asset_kind, state, provenance FROM assets WHERE episode_id=%s",
            (prepare_run.BENCHMARK_EPISODE_ID,),
        )
        rights = tx.fetchall(
            "SELECT rights_route_id, subject_kind, status FROM rights_registry WHERE current"
        )
        preset = tx.fetchone(
            "SELECT enabled FROM preset_registry WHERE preset_id=%s AND current",
            (prepare_run.PRESET_ID,),
        )
    assert episode is not None and episode["cap_micro_usd"] == 10_000_000
    # One byte upload reused by two semantic bindings: 8 distinct digests, 10
    # bindings, unpicked candidates never registered.
    assert len(assets) == 8
    assert {row["asset_kind"] for row in assets} == {"IMAGE", "AUDIO"}
    assert all(row["state"] == "ACCEPTED" for row in assets)
    assert all(row["provenance"] != "FAKE_SYNTHETIC" for row in assets)
    assert all(row["status"] == "ELIGIBLE" for row in rights)
    assert len(rights) == 11  # 10 reference/voice subjects + the model-output route
    assert preset is not None and preset["enabled"] is False
    digests = {row["sha256"] for row in assets}
    files = _pick_files(tmp_path)
    assert digests == {sha256_hex(files[ref]) for ref in ALL_REF_IDS}

    # Idempotent replay: nothing new, and the drift gate stays closed.
    _register(db_dsn, tmp_path, out)
    replay = json.loads(capsys.readouterr().out)
    assert replay["register"] == "replayed"
    with db.transaction(readonly=True) as tx:
        assert (
            tx.fetchval(
                "SELECT count(*) FROM assets WHERE episode_id=%s",
                (prepare_run.BENCHMARK_EPISODE_ID,),
            )
            == 8
        )


def test_r5v10_voice_media_derived_from_the_actual_wav_bytes(db, db_dsn, tmp_path) -> None:
    """R5V-10: the registered voice rows carry metadata derived from the ACTUAL
    WAV bytes (24 kHz mono PCM, the files' real durations) - never the
    fixture's fictional four-second H.264/AAC video fields; a non-PCM 'wav'
    is refused."""
    out = tmp_path / "out"
    _seed_credentials(db, tmp_path)
    _register(db_dsn, tmp_path, out)
    with db.transaction(readonly=True) as tx:
        rows = tx.fetchall(
            "SELECT sha256, descriptor FROM assets WHERE episode_id=%s",
            (prepare_run.BENCHMARK_EPISODE_ID,),
        )
    files = _pick_files(tmp_path)
    by_sha = {row["sha256"]: row["descriptor"] for row in rows}
    for ref in VOICE_REF_IDS:
        media = by_sha[sha256_hex(files[ref])]["media"]
        assert media["duration_ms"] == VOICE_WAV_MS[ref], media
        assert media["sample_rate_hz"] == 24_000
        assert media["channels"] == 1
        assert media["has_audio"] is True and media["has_video"] is False
        assert media["audio_codec"] == "pcm_s16le"
        assert "video_codec" not in media or media.get("video_codec") is None
    for ref in IMAGE_REF_IDS:
        assert by_sha[sha256_hex(files[ref])].get("media") is None

    # Garbage 'wav' bytes (the old fictional fixtures) never validate: the
    # parser refuses them before any row is written.
    with pytest.raises(SystemExit, match="not a PCM WAV"):
        prepare_run._wav_media_info(b"wav-bytes-A-NEUTRAL-r5d")
    # A RIFF container with a compressed fmt is equally refused.
    import struct

    fmt = struct.pack("<HHIIHH", 0x55, 2, 44_100, 44_100 * 4, 4, 16)  # MP3 fmt tag
    mp3_wav = (
        b"RIFF"
        + struct.pack("<I", 36 + 4)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", len(fmt))
        + fmt
        + b"data"
        + struct.pack("<I", 4)
        + b"\x00\x00\x00\x00"
    )
    with pytest.raises(SystemExit, match="not uncompressed PCM"):
        prepare_run._wav_media_info(mp3_wav)


def test_r5w2_malformed_first_voice_registers_nothing_and_retry_succeeds(
    db, db_dsn, tmp_path
) -> None:
    """R5W-2: ALL inputs (the WAVs included) are validated BEFORE any
    registration write. A malformed first voice leaves NOTHING registered -
    no episode, no account, no partial assets - so correcting the input and
    retrying registers the full set cleanly instead of being refused as
    "stored asset bytes drifted"."""
    out = tmp_path / "out"
    _seed_credentials(db, tmp_path)
    files = _pick_files(tmp_path)
    files["A-NEUTRAL"] = b"wav-bytes-A-NEUTRAL-r5d"  # the malformed first voice
    with pytest.raises(SystemExit, match="not a PCM WAV"):
        _register_files(db_dsn, tmp_path, out, files)

    # Nothing was written: the malformed voice is caught BEFORE the episode,
    # the EPISODE account and the six image assets are registered.
    with db.transaction(readonly=True) as tx:
        assert (
            tx.fetchval(
                "SELECT count(*) FROM episodes WHERE id=%s",
                (prepare_run.BENCHMARK_EPISODE_ID,),
            )
            == 0
        )
        assert (
            tx.fetchval(
                "SELECT count(*) FROM budget_accounts WHERE episode_id=%s",
                (prepare_run.BENCHMARK_EPISODE_ID,),
            )
            == 0
        )
        assert (
            tx.fetchval(
                "SELECT count(*) FROM assets WHERE episode_id=%s",
                (prepare_run.BENCHMARK_EPISODE_ID,),
            )
            == 0
        )

    # Correcting the input and retrying registers the FULL set (the old
    # behaviour entombed the partial registration and refused the retry).
    files["A-NEUTRAL"] = _wav_bytes(ms=VOICE_WAV_MS["A-NEUTRAL"])
    _register_files(db_dsn, tmp_path, out, files)
    with db.transaction(readonly=True) as tx:
        assert (
            tx.fetchval(
                "SELECT count(*) FROM assets WHERE episode_id=%s",
                (prepare_run.BENCHMARK_EPISODE_ID,),
            )
            == len(ALL_REF_IDS)
        )
    # A further run replays the now-complete registration without drift.
    _register(db_dsn, tmp_path, out)


def test_r5v9_replay_enforces_the_named_frozen_fields(db, db_dsn, tmp_path, monkeypatch) -> None:
    """R5V-9: replay drift beyond asset hashes is refused - the episode
    account cap, exact asset fields (kind under the picked sha), the exact
    rights versions/content (a replacement current version), and the preset
    pins (a replacement current preset row)."""
    out = tmp_path / "out"
    _seed_credentials(db, tmp_path)
    _register(db_dsn, tmp_path, out)

    def _register_again() -> None:
        _register(db_dsn, tmp_path, out)

    files = _pick_files(tmp_path)
    image_sha = sha256_hex(files["A2"])

    # (a) The account cap drifted (the review's one-uSD probe): the DB column
    # is trigger-immutable, so the drift is author-side - a tool build whose
    # frozen cap differs from the stored account must refuse to replay.
    monkeypatch.setattr(prepare_run, "EPISODE_CAP_MICRO_USD", 1)
    with pytest.raises(SystemExit, match="account cap drifted"):
        _register_again()
    monkeypatch.setattr(prepare_run, "EPISODE_CAP_MICRO_USD", 10_000_000)

    # (b) A replacement current rights version with drifted content (v2
    # current flips v1; the count stays 11).
    from microdrama.config import Settings as _Settings
    from microdrama.contracts.enums import EvidenceSource as _EvidenceSource
    from microdrama.contracts.enums import Provenance as _Provenance
    from microdrama.contracts.enums import RightsStatus as _RightsStatus
    from microdrama.contracts.enums import RightsSubjectKind as _RightsSubjectKind
    from microdrama.contracts.primitives import EvidenceRef as _EvidenceRef
    from microdrama.contracts.registries import RightsRecord as _RightsRecord
    from microdrama.core.clock import SystemClock as _SystemClock
    from microdrama.core.registry.rights import RightsRegistry as _RightsRegistry

    grant = prepare_run._expected_binding_grant("character_identity", "a", "A2")
    drifted = _RightsRecord(
        record_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "t031-record-v2:A2")),
        rights_route_id=grant["route"],
        version=2,
        subject_kind=_RightsSubjectKind(grant["subject_kind"]),
        subject_ref=grant["subject_ref"],
        territories=["SG"],
        commercial_use=True,
        output_release_allowed=True,
        required_disclosures=[],
        expires_at=None,
        evidence=[
            _EvidenceRef(
                source=_EvidenceSource.LICENSE_DOCUMENT,
                ref="attacker-replaced-evidence",
            )
        ],
        status=_RightsStatus.ELIGIBLE,
        recorded_at=_utcnow(),
    )
    _RightsRegistry(db, _SystemClock(), _Settings()).record(
        drifted, source_provenance=_Provenance.LIVE_PROVIDER
    )
    with pytest.raises(SystemExit, match="rights content drifted|rights routes drifted"):
        _register_again()

    # (c) Wrong asset kind under a picked sha (a decoy row carrying the same
    # digest with the wrong kind) - LAST: assets are append-only, so the decoy
    # stays for the rest of this test.
    with db.transaction() as tx:
        decoy = uuid.uuid4()
        descriptor = {
            "asset_id": str(decoy),
            "asset_kind": "AUDIO",
            "object_key": f"t031/inputs/decoy-{decoy}.wav",
            "sha256": image_sha,
            "size_bytes": 4,
            "media_type": "audio/wav",
            "media": None,
            "state": "ACCEPTED",
            "provenance": "LIVE_PROVIDER",
            "version": 1,
        }
        tx.execute(
            "INSERT INTO assets (id, asset_kind, object_key, sha256, size_bytes, media_type, "
            "media, descriptor, state, provenance, episode_id, created_at) VALUES "
            "(%s,'AUDIO',%s,%s,4,'audio/wav',%s,%s,'ACCEPTED','LIVE_PROVIDER',%s,now())",
            (
                decoy,
                descriptor["object_key"],
                image_sha,
                jsonb({"duration_ms": 4, "has_audio": True, "has_video": False}),
                jsonb(descriptor),
                prepare_run.BENCHMARK_EPISODE_ID,
            ),
        )
    with pytest.raises(SystemExit, match="asset bytes drifted|asset fields drifted"):
        _register_again()


def test_r5v9_preset_replacement_current_row_is_drift(db, db_dsn, tmp_path) -> None:
    """R5V-9: a replacement CURRENT preset row (v2) with different pins is
    drift even though 'a current disabled row' still exists."""
    out = tmp_path / "out"
    _seed_credentials(db, tmp_path)
    _register(db_dsn, tmp_path, out)
    pins = prepare_run._expected_preset_pins()
    from microdrama.config import Settings as _Settings
    from microdrama.contracts.enums import ControlKind as _ControlKind
    from microdrama.contracts.enums import Provenance as _Provenance
    from microdrama.contracts.enums import RenderTier as _RenderTier
    from microdrama.contracts.registries import PresetRecord as _PresetRecord
    from microdrama.core.registry.presets import PresetRegistry as _PresetRegistry

    _PresetRegistry(db, _Settings()).record(
        _PresetRecord(
            preset_id=prepare_run.PRESET_ID,
            version=2,
            tier=_RenderTier(pins["record"]["tier"]),
            workflow_sha256="f" * 64,  # drifted workflow pin
            model_mode=pins["record"]["model_mode"],
            gpu_type=pins["record"]["gpu_type"],
            min_vram_gb=pins["record"]["min_vram_gb"],
            host_ram_gb=pins["record"]["host_ram_gb"],
            precision=pins["record"]["precision"],
            width=pins["record"]["width"],
            height=pins["record"]["height"],
            frames=pins["record"]["frames"],
            fps=pins["record"]["fps"],
            steps=pins["record"]["steps"],
            attention_backend=pins["record"]["attention_backend"],
            supported_controls=[_ControlKind.TEXT_PROMPT, _ControlKind.SEED],
            supports_thai_dialogue=None,
            rights_route_id=pins["rights_route_id"],
            measured=None,
            evidence=[],
            enabled=False,
        ),
        source_provenance=_Provenance.LIVE_PROVIDER,
    )
    with pytest.raises(SystemExit, match="preset pins drifted"):
        _register(db_dsn, tmp_path, out)


def test_rr_t9_register_refuses_on_asset_drift(db, db_dsn, tmp_path) -> None:
    _seed_credentials(db, tmp_path)
    out = tmp_path / "out"
    _register(db_dsn, tmp_path, out)
    # Same ref ids, different bytes: the stored set no longer matches the picks.
    files = _pick_files(tmp_path)
    files["A2"] = b"png-bytes-A2-drifted-r5d"
    r1, r2, voices = _write_manifests(tmp_path, files)
    with pytest.raises(SystemExit, match="drifted"):
        prepare_run.main(
            [
                "register",
                "--dsn",
                db_dsn,
                "--refs-r1",
                str(r1),
                "--refs-r2",
                str(r2),
                "--voices",
                str(voices),
                "--store-root",
                str(tmp_path / "store"),
                "--out",
                str(out),
                "--runpod-credential",
                RUNPOD_CRED,
                "--comfy-credential",
                COMFY_CRED,
            ]
        )


def test_rr_t9_author_documents_and_hashes(db, db_dsn, tmp_path, capsys) -> None:
    _seed_credentials(db, tmp_path)
    out = tmp_path / "out"
    _register(db_dsn, tmp_path, out)
    capsys.readouterr()
    experiment_id = "11111111-2222-3333-4444-555555555555"
    _author(tmp_path, out, experiment_id)
    printed = capsys.readouterr().out
    _assert_no_credential_value(printed)
    lines = [json.loads(line) for line in printed.splitlines() if line.startswith("{")]
    hashes = {entry["document"]: entry for entry in lines}

    plan = load_document(out / "plan.json", BenchmarkPlan)
    seal = load_document(out / "seal.json", BenchmarkSeal)
    authorization = load_document(out / "authorization.draft.json", BenchmarkAuthorization)
    # The printed canonical sha is the canonical-JSON sha of the loaded model;
    # the file sha is the sha of the file bytes (what the operator signs).
    assert hashes["plan.json"]["canonical_sha256"] == plan.plan_sha256
    assert hashes["seal.json"]["canonical_sha256"] == seal.sealed_sha256
    for name in ("plan.json", "seal.json", "authorization.draft.json"):
        raw = (out / name).read_bytes()
        assert hashes[name]["file_sha256"] == hashlib.sha256(raw).hexdigest()

    # The authored shape: 8 shots, 24 seeded samples, the three screen ids, the
    # frozen S05/S06 expression text, and the office-reuse port map.
    assert plan.configuration_id == prepare_run.PRESET_ID
    assert [s["shot_id"] for s in plan.shots] == [f"S0{i}" for i in range(1, 9)]
    assert len(plan.samples) == 24
    assert set(plan.screen_sample_ids) == {"S01-R1", "S03-R1", "S07-R1"}
    assert prepare_run.EXPRESSION_FREEZE["S05"] in plan.shots[4]["english_prompt"]
    assert prepare_run.EXPRESSION_FREEZE["S06"] in plan.shots[5]["english_prompt"]
    assert seal.schema_evidence == "PREDICTED_FROM_PINNED_IMAGE"
    assert seal.schema_attestation_source == "MANIFEST_PLACEHOLDER_CAPTURE"
    assert seal.image_ref == IMAGE_REF
    assert seal.schema_capture["manifest_digest"] == IMAGE_REF.rsplit("@sha256:", 1)[-1]
    identity_assets = {
        (p["role"], p["subject_id"]): p["asset_id"] for p in seal.port_map if p["shot_id"] == "S01"
    }
    home_assets = {
        (p["role"], p["subject_id"]): p["asset_id"] for p in seal.port_map if p["shot_id"] == "S08"
    }
    # R5C-5: identity:A and outfit:A-office share ONE verified byte upload.
    assert identity_assets[("character_identity", "a")] == identity_assets[("outfit", "a-office")]
    # S08 is the home costume change: a different outfit and location asset.
    assert home_assets[("outfit", "a-home")] != identity_assets[("outfit", "a-office")]
    assert home_assets[("location", "home")] != identity_assets[("location", "office")]
    # The rights evidence hash binds exactly the sealed grants and territories.
    assert seal.rights_evidence_hash == document_sha256(
        {"rights": [b["rights"] for b in _bindings(out)], "territories": ["SG", "TH"]}
    )
    assert authorization.plan_sha256 == plan.plan_sha256
    assert authorization.sealed_sha256 == seal.sealed_sha256

    # A semantic edit changes the canonical sha; a byte edit changes the file
    # sha while the canonical document stays the same.
    trials = _author(tmp_path, out, experiment_id)
    rows = list(csv.DictReader(trials.read_text(encoding="utf-8").splitlines()))
    rows[0]["seed"] = str(int(rows[0]["seed"]) + 1000)  # stay distinct from the other 23
    with trials.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _author(tmp_path, out, experiment_id, regenerate_inputs=False)
    reprinted = [
        json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")
    ]
    rehashes = {entry["document"]: entry for entry in reprinted}
    assert rehashes["plan.json"]["canonical_sha256"] != hashes["plan.json"]["canonical_sha256"]
    original_bytes = (out / "plan.json").read_bytes()
    assert rehashes["plan.json"]["file_sha256"] == hashlib.sha256(original_bytes).hexdigest()
    (out / "plan.json").write_bytes(original_bytes + b"\n")
    assert (
        hashlib.sha256((out / "plan.json").read_bytes()).hexdigest()
        != rehashes["plan.json"]["file_sha256"]
    )
    assert (
        load_document(out / "plan.json", BenchmarkPlan).plan_sha256
        == rehashes["plan.json"]["canonical_sha256"]
    )


def _bindings(out: Path) -> list[dict]:
    return json.loads((out / "registered-bindings.json").read_text())["bindings"]


def test_rr_t9_quote_builds_and_refuses(db, db_dsn, tmp_path) -> None:
    _seed_credentials(db, tmp_path)
    out = tmp_path / "out"
    _register(db_dsn, tmp_path, out)
    quote = _write_quote(tmp_path)
    loaded = load_document(quote, AcquisitionQuote)
    assert loaded.gpu_type == "NVIDIA A40"
    assert loaded.compute_micro_usd_per_hour % 3600 == 0

    for mutate in ("gpu", "rate"):
        fields = _quote_fields()
        if mutate == "gpu":
            fields["gpu_type"] = "A40"  # the bare alias can never quote
        else:
            fields["compute_micro_usd_per_hour"] = 849_601  # not whole µUSD/s
        path = tmp_path / f"quote-fields-{mutate}.json"
        path.write_text(json.dumps(fields))
        with pytest.raises(SystemExit, match="refused"):
            prepare_run.main(["quote", "--fields", str(path), "--out", str(tmp_path / "q.json")])


def test_rr_t9_verify_preflight_pass_on_the_authored_set(
    db, db_dsn, tmp_path, monkeypatch, capsys
) -> None:
    _seed_credentials(db, tmp_path)
    out = tmp_path / "out"
    _register(db_dsn, tmp_path, out)
    experiment_id = "11111111-2222-3333-4444-555555555555"
    _author(tmp_path, out, experiment_id)
    capsys.readouterr()
    quote = _write_quote(tmp_path)
    capsys.readouterr()

    settings = _settings(db_dsn)
    assert (
        benchmark_main(
            ["prepare", "--experiment-id", experiment_id, "--plan", str(out / "plan.json")],
            _injection={"db": db, "settings": settings},
        )
        == 0
    )
    assert (
        benchmark_main(
            [
                "seal",
                "--experiment-id",
                experiment_id,
                "--manifest",
                str(out / "seal.json"),
            ],
            _injection={"db": db, "settings": settings},
        )
        == 0
    )

    # The runbook environment: the tool reads the DSN and the paid flags from
    # the environment like the benchmark CLI does.
    monkeypatch.setenv("MICRODRAMA_DATABASE_URL", db_dsn)
    monkeypatch.setenv("MICRODRAMA_EXECUTION_MODE", "PAID_BENCHMARK")
    monkeypatch.setenv("MICRODRAMA_PAID_REQUESTS_ENABLED", "true")
    monkeypatch.setenv("MICRODRAMA_CLOUD_RESOURCES_ENABLED", "true")
    monkeypatch.setenv("MICRODRAMA_PUBLIC_ACTIONS_ENABLED", "false")
    assert (
        prepare_run.main(
            [
                "verify",
                "--dsn",
                db_dsn,
                "--experiment-id",
                experiment_id,
                "--authorization",
                str(out / "authorization.draft.json"),
                "--quote",
                str(quote),
                "--output",
                str(tmp_path / "preflight.json"),
            ]
        )
        == 0
    )
    verify_out = capsys.readouterr().out
    _assert_no_credential_value(verify_out)
    assert "PASS" in verify_out, verify_out
