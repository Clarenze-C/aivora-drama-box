#!/usr/bin/env python
"""T031 R5d: author and register the benchmark run's real rows and documents.

Offline, against the dedicated loopback paid DB (``tools/canary_db.py``).
Every subcommand is idempotent and refuses on drift - drift means the named
frozen-field set per row type differs from what is already stored - and none
prints a credential value. Boundary: ``prepare_run`` authors and registers;
the benchmark CLI stays the only enforcement entry.

  register  real episode/account/assets/rights/preset/credential rows
  author    plan.json + seal.json + authorization.draft.json (+ both hashes)
  quote     quote.json from the operator's console quote fields
  verify    benchmark preflight against the authored documents (PASS / refusal)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

#: The R5d role table (DECISIONS "T031 benchmark inputs"; A2/B2 canonical).
#: ref_id names the pick inside the references manifests; A2 and B2 feed TWO
#: semantic bindings each (the R5C-5 office reuse). Unpicked candidates
#: (A1, A3, B1, B3) are NOT registered.
ROLE_TABLE: tuple[tuple[str, str, str], ...] = (
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
)

#: The three frozen screening samples (spec §3 R5d; fixed by the plan schema).
SCREEN_IDS: tuple[str, ...] = ("S01-R1", "S03-R1", "S07-R1")

BENCHMARK_EPISODE_ID = uuid.uuid5(uuid.NAMESPACE_URL, "t031-benchmark-episode")
MODEL_OUTPUT_ROUTE = "t031-minimax-h3-community-private-benchmark"
MODEL_OUTPUT_SUBJECT = "minimax-h3:community-license-private-benchmark"
PRESET_ID = "pika-flex-ref2va-480p-candidate"
TERRITORIES = ["SG", "TH"]
#: The frozen episode account cap ($10.00, spec §3 R5d): one value the
#: creation INSERT writes and the replay gate enforces (R5V-9).
EPISODE_CAP_MICRO_USD = 10_000_000
#: S05/S06 expression text is frozen here (spec §3 R5d).
EXPRESSION_FREEZE = {
    "S05": (
        "A speaks softly, holding back grief; his breath catches once before "
        "the last word; no tears, no sobbing."
    ),
    "S06": (
        "B speaks low and controlled with restrained anger, jaw tight, no "
        "shouting; her voice softens on 'แต่ฉันจะฟัง'."
    ),
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _canonical(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def _canonical_sha(value) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _db(dsn: str):
    from microdrama.persistence import Database

    return Database(dsn, min_size=1, max_size=5).open()


def _load_pick_manifests(refs_r1: Path, refs_r2: Path, voices: Path) -> dict[str, dict]:
    """ref_id -> the generation record (file, sha256, provenance, kind)."""
    records: dict[str, dict] = {}
    for path in (refs_r1, refs_r2):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            record["media_kind"] = "image"
            records[record["ref_id"]] = record
    for record in json.loads(voices.read_text(encoding="utf-8")):
        record = dict(record)
        record["media_kind"] = "audio"
        records[record["ref_id"]] = record
    missing = [ref_id for _, _, ref_id in ROLE_TABLE if ref_id not in records]
    if missing:
        raise SystemExit(f"refused: the manifests lack the picked references {sorted(missing)}")
    return records


def _credential_check(db, ref: str) -> None:
    """Validate the credential row and its file's mode/owner - never content."""
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone("SELECT store, locator FROM credential_refs WHERE ref=%s", (ref,))
    if row is None or row["store"] != "FILE":
        raise SystemExit(f"refused: credential {ref} is not a FILE-store row")
    path = Path(row["locator"])
    mode = path.stat().st_mode & 0o777
    if mode != 0o600:
        raise SystemExit(f"refused: credential {ref} file mode is {oct(mode)}, need 0600")
    if path.owner() != "root":
        raise SystemExit(f"refused: credential {ref} file owner is not root")


def _rights_evidence(record) -> str:
    """The exact stored form RightsRegistry.record fingerprints (its row id and
    the R5d ``_validate_model_rights`` pin both re-derive this hash)."""
    from microdrama.core.registry._common import canonical_document

    payload = {
        "status": record.status.value,
        "territories": canonical_document(list(record.territories)),
        "commercial_use": record.commercial_use,
        "output_release_allowed": record.output_release_allowed,
        "required_disclosures": canonical_document(
            [item.value for item in record.required_disclosures]
        ),
        "expires_at": record.expires_at,
        "evidence": canonical_document(record.evidence),
    }
    from microdrama.contracts.hashing import canonical_hash

    return canonical_hash(payload)


def _wav_media_info(data: bytes):
    """R5V-10: MediaInfo derived (and validated) from the ACTUAL WAV bytes.

    Parses the RIFF/WAVE header chunks; refuses anything that is not an
    uncompressed PCM WAV (compressed fmt, truncated chunks, foreign magic).
    Fictional fixture metadata (H.264/AAC video fields) never describes a
    PCM voice reference.
    """
    import struct

    from microdrama.contracts.media import MediaInfo

    def _refused(detail: str):
        raise SystemExit(f"refused: the voice reference is not a PCM WAV ({detail})")

    if len(data) < 12 or data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        _refused("not a RIFF/WAVE container")
    fmt = None
    data_size = None
    offset = 12
    while offset + 8 <= len(data):
        chunk_id = data[offset : offset + 4]
        (chunk_size,) = struct.unpack_from("<I", data, offset + 4)
        body = data[offset + 8 : offset + 8 + chunk_size]
        if chunk_id == b"fmt ":
            if chunk_size < 16:
                _refused("truncated fmt chunk")
            fmt = struct.unpack_from("<HHIIHH", body)
        elif chunk_id == b"data":
            data_size = chunk_size
        offset += 8 + chunk_size + (chunk_size & 1)
    if fmt is None or data_size is None:
        _refused("missing fmt/data chunk")
    audio_format, channels, sample_rate, _byte_rate, _block_align, bits = fmt
    if audio_format != 1:
        _refused(f"audio format {audio_format} is not uncompressed PCM")
    if channels < 1 or sample_rate < 1 or bits % 8:
        _refused("implausible PCM framing")
    frame_bytes = channels * bits // 8
    duration_ms = int(round((data_size / frame_bytes) / sample_rate * 1000))
    return MediaInfo(
        duration_ms=duration_ms,
        has_audio=True,
        has_video=False,
        audio_codec=f"pcm_s{bits}le",
        sample_rate_hz=sample_rate,
        channels=channels,
    )


#: R5V-9: the frozen content the replay gate compares, per row type. The
#: register path constructs its records FROM these same values, so author and
#: gate can never drift apart. Keyed by the ROLE_TABLE row (role, subject),
#: since A2/B2 legitimately appear in TWO rows with distinct routes.
def _expected_binding_grant(role: str, subject: str, ref_id: str) -> dict:
    from microdrama.contracts.enums import EvidenceSource, RightsSubjectKind

    is_voice = ref_id in ("A-NEUTRAL", "B-NEUTRAL")
    return {
        "route": f"t031-rights-{role.replace('_', '-')}-{subject}".lower(),
        "subject_kind": (
            RightsSubjectKind.VOICE.value if is_voice else RightsSubjectKind.REFERENCE.value
        ),
        "subject_ref": subject,
        "version": 1,
        "territories": TERRITORIES,
        "commercial_use": True,
        "output_release_allowed": True,
        "evidence": [
            {
                "source": (
                    EvidenceSource.LICENSE_DOCUMENT.value
                    if is_voice
                    else EvidenceSource.CONTROLLED_ACCOUNT_TEST.value
                ),
                "ref": (
                    "botnoi-studio-v4:operator-attested-o11"
                    if is_voice
                    else f"vertex-nano-banana-generation-manifest:{subject}"
                ),
            }
        ],
    }


def _expected_model_output_grant() -> dict:
    from microdrama.contracts.enums import EvidenceSource, RightsSubjectKind

    return {
        "route": MODEL_OUTPUT_ROUTE,
        "subject_kind": RightsSubjectKind.MODEL_OUTPUT.value,
        "subject_ref": MODEL_OUTPUT_SUBJECT,
        "version": 1,
        "territories": TERRITORIES,
        "commercial_use": True,
        "output_release_allowed": True,
        "evidence": [
            {
                "source": EvidenceSource.LICENSE_DOCUMENT.value,
                "ref": "minimax-h3-community-license:operator-attested-2026-11-12",
            }
        ],
    }


def _expected_preset_pins() -> dict:
    from microdrama.rendering.workflows.templates import PIKA_TEMPLATE
    from microdrama.rendering.workflows.templates import (
        template_sha256 as _template_sha256,
    )

    return {
        "version": 1,
        "workflow_sha256": _template_sha256(PIKA_TEMPLATE),
        "rights_route_id": MODEL_OUTPUT_ROUTE,
        "enabled": False,
        "record": {
            "tier": "quality_eight_step",
            "model_mode": "native",
            "gpu_type": "NVIDIA A40",
            "min_vram_gb": 24,
            "host_ram_gb": 64,
            "precision": "bf16",
            "width": 480,
            "height": 832,
            "frames": 124,
            "fps": 24,
            "steps": 8,
            "attention_backend": "sdpa",
        },
    }


def _assert_rights_frozen(rows: list) -> None:
    """R5V-9: every benchmark rights row matches its exact frozen content -
    named identities, version, territories, commercial/output-release terms
    and evidence - not merely a count of ELIGIBLE rows (a replacement current
    version with drifted content keeps the count)."""
    expected = {
        grant["route"]: grant
        for grant in (
            _expected_binding_grant(role, subject, ref) for role, subject, ref in ROLE_TABLE
        )
    }
    expected[_expected_model_output_grant()["route"]] = _expected_model_output_grant()
    stored = {row["rights_route_id"]: row for row in rows}
    if set(stored) != set(expected) or len(rows) != len(expected):
        raise SystemExit(
            f"refused: the benchmark rights routes drifted ({sorted(stored)} != {sorted(expected)})"
        )
    for route, grant in expected.items():
        row = stored[route]
        if (
            row["subject_kind"] != grant["subject_kind"]
            or row["subject_ref"] != grant["subject_ref"]
            or int(row["version"]) != grant["version"]
            or list(row["territories"] or []) != grant["territories"]
            or bool(row["commercial_use"]) != grant["commercial_use"]
            or bool(row["output_release_allowed"]) != grant["output_release_allowed"]
            or [item["source"] for item in row["evidence"] or []]
            != [item["source"] for item in grant["evidence"]]
            or [item["ref"] for item in row["evidence"] or []]
            != [item["ref"] for item in grant["evidence"]]
        ):
            raise SystemExit(f"refused: the benchmark rights content drifted ({route})")


def _assert_preset_frozen(row) -> None:
    """R5V-9: the CURRENT preset row carries the exact registered pins (a
    replacement current version with different pins is drift). The row
    columns pin version/workflow/enabled; the ``record`` jsonb pins the rest."""
    pins = _expected_preset_pins()
    if row is None:
        raise SystemExit("refused: the benchmark preset row drifted (no current row)")
    record = row["record"] or {}
    if (
        int(row["version"]) != pins["version"]
        or row["workflow_sha256"] != pins["workflow_sha256"]
        or bool(row["enabled"]) != pins["enabled"]
        or record.get("rights_route_id") != pins["rights_route_id"]
        or any(record.get(key) != value for key, value in pins["record"].items())
    ):
        raise SystemExit("refused: the benchmark preset pins drifted")


# --- register -------------------------------------------------------------------


def cmd_register(args: argparse.Namespace) -> int:
    from microdrama.config import Settings
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
    from microdrama.contracts.hashing import sha256_hex
    from microdrama.contracts.media import AssetDescriptor
    from microdrama.contracts.primitives import EvidenceRef
    from microdrama.contracts.registries import PresetRecord, RightsRecord
    from microdrama.contracts.v2 import ShotReferenceBinding
    from microdrama.core.clock import SystemClock
    from microdrama.core.registry.presets import PresetRegistry
    from microdrama.core.registry.rights import RightsRegistry
    from microdrama.persistence import register_asset
    from microdrama.persistence.object_store import FilesystemObjectStore
    from microdrama.testing.seed import seed_episode, seed_season

    picks = _load_pick_manifests(args.refs_r1, args.refs_r2, args.voices)
    db = _db(args.dsn)
    try:
        settings = Settings()
        store = FilesystemObjectStore(Path(args.store_root))
        clock = SystemClock()
        now = _utcnow()

        # R5W-2: EVERY input is validated BEFORE any registration write -
        # the sha256 gate for all picks, container/PCM validation for the
        # voices - so a malformed first voice leaves nothing registered and
        # the corrected retry starts from a clean slate (no entombed drift).
        prepared: dict[str, bytes] = {}
        for _, _, ref_id in ROLE_TABLE:
            if ref_id in prepared:
                continue
            pick = picks[ref_id]
            data = Path(pick["file"]).read_bytes()
            if sha256_hex(data) != pick["sha256"]:
                raise SystemExit(f"refused: {ref_id} bytes do not hash to the manifest sha256")
            if pick["media_kind"] == "audio":
                _wav_media_info(data)
            prepared[ref_id] = data

        # Frozen-field drift check when the episode already exists (the named
        # frozen set: the episode's EPISODE account, the picked asset bytes,
        # their state/provenance, the current rights records, the preset row
        # and both credential rows).
        with db.transaction(readonly=True) as tx:
            existing = tx.fetchone(
                "SELECT e.id, a.cap_micro_usd FROM episodes e JOIN budget_accounts a "
                "ON a.episode_id = e.id AND a.scope_kind='EPISODE' WHERE e.id=%s",
                (BENCHMARK_EPISODE_ID,),
            )
            assets = tx.fetchall(
                "SELECT sha256, asset_kind, state, provenance FROM assets WHERE episode_id=%s",
                (BENCHMARK_EPISODE_ID,),
            )
            canary_spend = tx.fetchval(
                "SELECT COALESCE(SUM(ch.amount_micro_usd),0) FROM charges ch "
                "JOIN budget_accounts a ON a.id=ch.account_id "
                "JOIN episodes e ON e.id=a.episode_id WHERE e.episode_number=1 "
                "AND e.id <> %s AND a.scope_kind='EPISODE'",
                (BENCHMARK_EPISODE_ID,),
            )
            rights_rows = tx.fetchall(
                "SELECT rights_route_id, subject_kind, subject_ref, version, territories, "
                "commercial_use, output_release_allowed, evidence FROM rights_registry "
                "WHERE current AND status='ELIGIBLE' "
                "AND (rights_route_id=%s OR rights_route_id LIKE 't031-rights-%%')",
                (MODEL_OUTPUT_ROUTE,),
            )
            preset_row = tx.fetchone(
                "SELECT version, workflow_sha256, enabled, record "
                "FROM preset_registry WHERE preset_id=%s AND current",
                (PRESET_ID,),
            )
        # Credentials are validated on every run, first use and replay alike.
        for ref in (args.runpod_credential, args.comfy_credential):
            _credential_check(db, ref)
        if existing is not None:
            # R5V-9: the replay gate enforces the NAMED frozen fields per row
            # type - identities, the account cap, exact asset fields, the
            # exact rights versions/content and the preset pins - not just
            # digest sets, broad state/provenance and counts.
            if int(existing["cap_micro_usd"]) != EPISODE_CAP_MICRO_USD:
                raise SystemExit(
                    "refused: the benchmark episode account cap drifted "
                    f"({existing['cap_micro_usd']} != {EPISODE_CAP_MICRO_USD})"
                )
            expected_shas = {picks[ref_id]["sha256"] for _, _, ref_id in ROLE_TABLE}
            if {row["sha256"] for row in assets} != expected_shas:
                raise SystemExit("refused: stored asset bytes drifted from the picked manifests")
            expected_kinds = {
                picks[ref_id]["sha256"]: (
                    "AUDIO" if ref_id in ("A-NEUTRAL", "B-NEUTRAL") else "IMAGE"
                )
                for _, _, ref_id in ROLE_TABLE
            }
            for row in assets:
                want = expected_kinds[row["sha256"]]
                if (
                    row["asset_kind"] != want
                    or row["state"] != AssetState.ACCEPTED.value
                    or row["provenance"] != Provenance.LIVE_PROVIDER.value
                ):
                    raise SystemExit(
                        "refused: stored asset fields drifted "
                        f"({row['sha256'][:12]}: kind {row['asset_kind']} != {want}, "
                        f"state {row['state']}, provenance {row['provenance']})"
                    )
            _assert_rights_frozen(rights_rows)
            _assert_preset_frozen(preset_row)
            print(
                json.dumps(
                    {
                        "register": "replayed",
                        "episode_id": str(BENCHMARK_EPISODE_ID),
                        "assets": len(assets),
                        "prior_canary_spend_micro_usd": int(canary_spend or 0),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        # Episode + EPISODE account (cap $10.00); prior canary spend is
        # reported, never moved.
        with db.transaction() as tx:
            season = seed_season(tx)
            seeded = seed_episode(tx, season, number=2)
            tx.execute("UPDATE episodes SET id=%s WHERE id=%s", (BENCHMARK_EPISODE_ID, seeded))
            account = uuid.uuid4()
            tx.execute(
                "INSERT INTO budget_accounts (id, scope_kind, season_id, episode_id, "
                "cap_micro_usd) VALUES (%s,'EPISODE',%s,%s,%s)",
                (account, season, BENCHMARK_EPISODE_ID, EPISODE_CAP_MICRO_USD),
            )
            for category, allocated, protected in (
                *(
                    (category, 0, True)
                    for category in (
                        "RESEARCH_SCRIPT_PROMPTS_METADATA",
                        "REFERENCES_DIALOGUE",
                        "QA_CAPTIONS",
                        "CPU_STORAGE_TRANSFER",
                        "RECOVERY_HEADROOM",
                    )
                ),
                ("GPU_GENERATION", 9_000_000, True),
                ("METERED_MANAGEMENT", 0, False),
            ):
                tx.execute(
                    "INSERT INTO budget_category_allocations (account_id, category, "
                    "allocated_micro_usd, protected) VALUES (%s,%s,%s,%s)",
                    (account, category, allocated, protected),
                )

        # Assets (real bytes, ACCEPTED, real provenance; never FAKE_SYNTHETIC).
        bindings: list[dict] = []
        asset_ids: dict[str, str] = {}
        for role, subject, ref_id in ROLE_TABLE:
            pick = picks[ref_id]
            data = prepared[ref_id]
            digest = sha256_hex(data)
            audio = pick["media_kind"] == "audio"
            if ref_id not in asset_ids:
                asset_id = uuid.uuid5(uuid.NAMESPACE_URL, f"t031-asset:{ref_id}")
                key = f"t031/inputs/{asset_id}.{'wav' if audio else 'png'}"
                store.put_bytes(
                    key,
                    data,
                    media_type=f"{'audio' if audio else 'image'}/{'wav' if audio else 'png'}",
                )
                descriptor = AssetDescriptor(
                    asset_id=asset_id,
                    asset_kind=AssetKind.AUDIO if audio else AssetKind.IMAGE,
                    object_key=key,
                    sha256=digest,
                    size_bytes=len(data),
                    media_type=f"{'audio' if audio else 'image'}/{'wav' if audio else 'png'}",
                    # R5V-10: validated metadata derived from the ACTUAL WAV
                    # bytes - never the fixture's fictional H.264/AAC fields.
                    media=_wav_media_info(data) if audio else None,
                    state=AssetState.ACCEPTED,
                    # Real provenance: Nano Banana via Vertex for PNGs (billed
                    # to ARISA's project, recorded in the manifests), Botnoi
                    # Studio V4 for the voices.
                    provenance=Provenance.LIVE_PROVIDER,
                    episode_id=BENCHMARK_EPISODE_ID,
                    season_id=None,
                    created_at=now,
                )
                with db.transaction() as tx:
                    register_asset(tx, descriptor)
                asset_ids[ref_id] = str(asset_id)
            route = f"t031-rights-{role.replace('_', '-')}-{subject}".lower()
            expected = _expected_binding_grant(role, subject, ref_id)
            grant = {
                "rights_route_id": route,
                "subject_kind": expected["subject_kind"],
                "subject_ref": subject,
                "rights_version": 1,
                "status": "ELIGIBLE",
                "territories": TERRITORIES,
                "commercial_use": True,
                "output_release_allowed": True,
                "expires_at": None,
                "evidence_sha256": [_canonical_sha({"ref_id": ref_id})],
            }
            bindings.append(
                ShotReferenceBinding.seal(
                    record_id=uuid.uuid5(uuid.NAMESPACE_URL, f"t031-binding:{role}:{subject}"),
                    version=1,
                    created_at=now,
                    updated_at=now,
                    valid_from=now,
                    valid_until=None,
                    role=role,
                    subject_id=subject,
                    asset_id=uuid.UUID(asset_ids[ref_id]),
                    asset_version=1,
                    asset_sha256=picks[ref_id]["sha256"],
                    rights=grant,
                ).model_dump(mode="json")
            )

        rights = RightsRegistry(db, clock, settings)
        # Model-output route: MiniMax H3 Community License, private benchmark.
        # ELIGIBLE records require confirmed output release by the contract
        # model; release here is the private benchmark's own use recorded
        # under the license, with the operator attestation as the license
        # document evidence.
        expected_model = _expected_model_output_grant()
        model_output = RightsRecord(
            record_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "t031-rights-model-output")),
            rights_route_id=expected_model["route"],
            version=expected_model["version"],
            subject_kind=RightsSubjectKind(expected_model["subject_kind"]),
            subject_ref=expected_model["subject_ref"],
            territories=expected_model["territories"],
            commercial_use=expected_model["commercial_use"],
            output_release_allowed=expected_model["output_release_allowed"],
            required_disclosures=[],
            expires_at=None,
            evidence=[
                EvidenceRef(
                    source=EvidenceSource(item["source"]),
                    ref=item["ref"],
                )
                for item in expected_model["evidence"]
            ],
            status=RightsStatus.ELIGIBLE,
            recorded_at=now,
        )
        rights.record(model_output, source_provenance=Provenance.LIVE_PROVIDER)
        for role, subject, ref_id in ROLE_TABLE:
            expected = _expected_binding_grant(role, subject, ref_id)
            # Real evidence sources only (PAID_BENCHMARK evaluation refuses
            # records without one): the Botnoi service license carries the
            # operator's O-11 attestation for voices; the Vertex generation
            # manifests on ARISA's controlled account evidence the reference
            # PNGs (original fictional, Nano Banana generated).
            rights.record(
                RightsRecord(
                    record_id=str(
                        uuid.uuid5(uuid.NAMESPACE_URL, f"t031-record:{expected['route']}")
                    ),
                    rights_route_id=expected["route"],
                    version=expected["version"],
                    subject_kind=RightsSubjectKind(expected["subject_kind"]),
                    subject_ref=expected["subject_ref"],
                    territories=expected["territories"],
                    commercial_use=expected["commercial_use"],
                    output_release_allowed=expected["output_release_allowed"],
                    required_disclosures=[],
                    expires_at=None,
                    evidence=[
                        EvidenceRef(
                            source=EvidenceSource(item["source"]),
                            ref=item["ref"],
                        )
                        for item in expected["evidence"]
                    ],
                    status=RightsStatus.ELIGIBLE,
                    recorded_at=now,
                ),
                source_provenance=Provenance.LIVE_PROVIDER,
            )

        # The preset row: disabled and unmeasured (FM §4).
        pins = _expected_preset_pins()
        PresetRegistry(db, settings).record(
            PresetRecord(
                preset_id=PRESET_ID,
                version=pins["version"],
                tier=RenderTier(pins["record"]["tier"]),
                workflow_sha256=pins["workflow_sha256"],
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
                supported_controls=[
                    ControlKind.TEXT_PROMPT,
                    ControlKind.SEED,
                    ControlKind.CHARACTER_REFERENCE,
                    ControlKind.WARDROBE_REFERENCE,
                    ControlKind.LOCATION_REFERENCE,
                ],
                supports_thai_dialogue=None,
                rights_route_id=pins["rights_route_id"],
                measured=None,
                evidence=[],
                enabled=pins["enabled"],
            ),
            source_provenance=Provenance.LIVE_PROVIDER,
        )

        Path(args.out).mkdir(parents=True, exist_ok=True)
        (Path(args.out) / "registered-bindings.json").write_text(
            json.dumps(
                {
                    "episode_id": str(BENCHMARK_EPISODE_ID),
                    "bindings": bindings,
                    "model_rights": {
                        "subject_kind": "MODEL_OUTPUT",
                        "subject_ref": MODEL_OUTPUT_SUBJECT,
                        "rights_route_id": MODEL_OUTPUT_ROUTE,
                        "version": 1,
                        "evidence_sha256": _rights_evidence(model_output),
                    },
                },
                indent=2,
            )
        )
        print(
            json.dumps(
                {
                    "register": "created",
                    "episode_id": str(BENCHMARK_EPISODE_ID),
                    "assets": len(asset_ids),
                    "bindings": len(bindings),
                    "preset": PRESET_ID,
                    "prior_canary_spend_micro_usd": int(canary_spend or 0),
                    "bindings_file": str(Path(args.out) / "registered-bindings.json"),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    finally:
        db.close()


# --- author ---------------------------------------------------------------------


def _port_map() -> list[dict]:
    """Shot-scoped ports: S01-S07 the office, S08 the home (costume change)."""
    ports = []
    for shot_index in range(1, 9):
        home = shot_index == 8
        slots = [
            ("character_identity", "a", "A2", "ref_images.ref_image_0"),
            (
                "outfit",
                "a-home" if home else "a-office",
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
        for role, subject, ref_id, slot in slots:
            ports.append(
                {
                    "role": role,
                    "subject_id": subject,
                    "ref_id": ref_id,
                    "destination_slot": slot,
                    "media_kind": "audio" if role == "voice" else "image",
                    "shot_id": f"S0{shot_index}",
                }
            )
    return ports


def _frozen_prompt(shot: dict, ports: list[dict]) -> str:
    """English direction with one-based <Picture N>/<Audio N> labels in the
    port-map order, the speaker labels and the Thai line."""
    shot_ports = [p for p in ports if p["shot_id"] == shot["shot_id"]]
    pictures = [
        f"<Picture {n}> {p['role']}:{p['subject_id']}"
        for n, p in enumerate([p for p in shot_ports if p["media_kind"] == "image"], start=1)
    ]
    audios = [
        f"<Audio {n}> voice:{p['subject_id']}"
        for n, p in enumerate([p for p in shot_ports if p["media_kind"] == "audio"], start=1)
    ]
    expression = EXPRESSION_FREEZE.get(shot["shot_id"])
    parts = [
        shot["action"].strip(),
        "Critical: " + shot["critical_observations"].strip(),
        "References in order: " + "; ".join(pictures + audios),
        f"Speaker: {shot['speaker']}. Thai line: {shot['thai_line'].strip()}",
    ]
    if expression:
        parts.append(f"Expression: {expression}")
    return "\n".join(parts)


def cmd_author(args: argparse.Namespace) -> int:
    from pydantic import ValidationError

    from microdrama.pipeline.benchmark_authorization import (
        BenchmarkAuthorization,
        BenchmarkPlan,
        BenchmarkSeal,
        canonical_document_bytes,
        document_sha256,
    )
    from microdrama.rendering.workflows.pika_h3_flex import PikaGraphConfig
    from microdrama.rendering.workflows.templates import PIKA_TEMPLATE
    from microdrama.rendering.workflows.templates import (
        template_sha256 as _template_sha256,
    )

    bindings_document = json.loads(Path(args.bindings).read_text())
    bindings = bindings_document["bindings"]
    model_rights = bindings_document.get("model_rights") or {}
    shots = list(csv.DictReader(Path(args.shots).read_text(encoding="utf-8").splitlines()))
    trials = list(csv.DictReader(Path(args.trials).read_text(encoding="utf-8").splitlines()))
    capture = json.loads(Path(args.capture_record).read_text())
    if len(shots) != 8 or len(trials) != 24:
        raise SystemExit("refused: author needs exactly 8 shots and 24 trials")
    image_digest = args.image_ref.rsplit("@sha256:", 1)[-1]
    if "@sha256:" not in args.image_ref or capture.get("manifest_digest") != image_digest:
        raise SystemExit(
            "refused: the seal's image digest and the capture record's manifest "
            "digest must be the same registry reference"
        )
    if not model_rights.get("subject_ref") or not model_rights.get("evidence_sha256"):
        raise SystemExit(
            "refused: the bindings file lacks the model-output rights pins (run register first)"
        )
    experiment_id = str(uuid.UUID(args.experiment_id))
    episode_id = str(uuid.UUID(args.episode_id))
    ports = _port_map()
    by_binding = {(b["role"], b["subject_id"]): b for b in bindings}

    plan_document = {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "episode_id": episode_id,
        "experiment_nonce": "t031-benchmark-2026-11",
        "configuration_id": PRESET_ID,
        "runtime_profile_sha256": None,  # bound to the seal's profile below
        "shots": [
            {
                "shot_id": shot["shot_id"],
                "thai_line": shot["thai_line"],
                "english_line": shot["english_meaning"],
                "english_prompt": _frozen_prompt(shot, ports),
                "speaker_subject_ids": ["a", "b"],
                "class": shot["class"],
                "speaker": shot["speaker"],
                "action": shot["action"],
                "critical_observations": shot["critical_observations"],
            }
            for shot in shots
        ],
        "samples": [
            {
                "sample_id": trial["sample_id"],
                "shot_id": trial["shot_id"],
                "repeat": int(trial["repeat"]),
                "seed": int(trial["seed"]),
            }
            for trial in trials
        ],
        "screen_sample_ids": list(SCREEN_IDS),
        "logical_reference_slots": [
            {"role": role, "subject_id": subject} for role, subject, _ in ROLE_TABLE
        ],
        "max_new_exposure_micro_usd": 8_000_000,
        "max_gpu_ms": 14_400_000,
    }
    runtime_profile = {
        "preset_id": PRESET_ID,
        "preset_version": 1,
        "workflow_sha256": _template_sha256(PIKA_TEMPLATE),
        "configuration_sha256": PikaGraphConfig().sha256,
        "rights_route_id": MODEL_OUTPUT_ROUTE,
        "boot_budget_ms": int(args.boot_budget_ms),
        "provision_models": True,
        "model_rights_subject_kind": "MODEL_OUTPUT",
        "model_rights_subject_ref": model_rights["subject_ref"],
        "model_rights_version": int(model_rights.get("version", 1)),
        "model_rights_evidence_sha256": model_rights["evidence_sha256"],
    }
    plan_document["runtime_profile_sha256"] = document_sha256(runtime_profile)
    try:
        plan = BenchmarkPlan.model_validate(plan_document)
        plan_document = json.loads(canonical_document_bytes(plan))
        seal = BenchmarkSeal.model_validate(
            {
                "schema_version": 1,
                "experiment_id": experiment_id,
                "plan_sha256": plan.plan_sha256,
                "references": bindings,
                "port_map": [
                    {
                        "role": p["role"],
                        "subject_id": p["subject_id"],
                        "asset_id": by_binding[(p["role"], p["subject_id"])]["asset_id"],
                        "asset_version": 1,
                        "asset_sha256": by_binding[(p["role"], p["subject_id"])]["asset_sha256"],
                        "media_kind": p["media_kind"],
                        "destination_slot": p["destination_slot"],
                        "shot_id": p["shot_id"],
                    }
                    for p in ports
                ],
                "runtime_profile": runtime_profile,
                "image_ref": args.image_ref,
                "node_schema_sha256": capture["node_schema_sha256"],
                "schema_evidence": "PREDICTED_FROM_PINNED_IMAGE",
                "schema_attestation_source": "MANIFEST_PLACEHOLDER_CAPTURE",
                "schema_capture": capture,
                "raw_object_info": json.loads(Path(args.prediction_raw).read_text()),
                "width": 480,
                "height": 832,
                "frames": 124,
                "fps": 24,
                # The exact shape _validated_sources recomputes from the
                # sealed references (R5d: grants + territories, nothing else).
                "rights_evidence_hash": document_sha256(
                    {"rights": [b["rights"] for b in bindings], "territories": TERRITORIES}
                ),
                "territories": TERRITORIES,
                "eligible_until": args.eligible_until,
                "hard_stop_utc": args.hard_stop_utc,
            }
        )
        authorization = BenchmarkAuthorization.model_validate(
            {
                "operator": args.operator,
                "change_ref": args.change_ref,
                "experiment_id": experiment_id,
                "plan_sha256": plan.plan_sha256,
                "sealed_sha256": seal.sealed_sha256,
                "episode_id": episode_id,
                "provider_account_ref": args.provider_account_ref,
                "max_new_exposure_micro_usd": 8_000_000,
                "max_gpu_ms": 14_400_000,
                "hard_stop_utc": args.hard_stop_utc,
                "allowed_gpu_types": ["NVIDIA A40"],
                "minimum_host_ram_gb": 64,
                "max_hourly_micro_usd": 860_000,
                "max_storage_exposure_micro_usd": 2_000_000,
                "container_disk_gb": 100,
                "persistent_volume_gb": 0,
                "shutdown_reserve_micro_usd": 500_000,
                "namespace": args.namespace,
                "runpod_credential_ref": args.runpod_credential,
                "comfy_credential_ref": args.comfy_credential,
                "rights_evidence_hash": seal.rights_evidence_hash,
            }
        )
    except ValidationError:
        # Never echo document values: an operator may have pasted a secret.
        raise SystemExit(
            "refused: the authored documents do not satisfy the benchmark "
            "plan/seal/authorization schemas"
        ) from None

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    # The canonical sha printed for each document is the value the
    # authorization binds: the plan's experiment-id-free identity
    # (plan_sha256) and the seal's full-document sealed_sha256; the
    # authorization's own canonical form is printed the same way, while its
    # FILE sha is the byte hash the operator signs (§7 step 10).
    canonical_hashes = {
        "plan.json": plan.plan_sha256,
        "seal.json": seal.sealed_sha256,
        "authorization.draft.json": document_sha256(authorization),
    }
    for name, model in (
        ("plan.json", plan),
        ("seal.json", seal),
        ("authorization.draft.json", authorization),
    ):
        raw = canonical_document_bytes(model)
        target = out / name
        target.write_bytes(raw + b"\n")
        print(
            json.dumps(
                {
                    "document": name,
                    "canonical_sha256": canonical_hashes[name],
                    "file_sha256": hashlib.sha256(raw + b"\n").hexdigest(),
                }
            )
        )
    return 0


# --- quote / verify ---------------------------------------------------------------


def cmd_quote(args: argparse.Namespace) -> int:
    from pydantic import ValidationError

    from microdrama.pipeline.benchmark_authorization import (
        AcquisitionQuote,
        canonical_document_bytes,
        load_document,
    )

    fields = json.loads(Path(args.fields).read_text())
    fields.setdefault("schema_version", 1)
    try:
        quote = AcquisitionQuote.model_validate(fields)
    except ValidationError:
        # The model enforces the <= 2 h window, the exact GPU catalog ids
        # (bare "A40" refused) and whole micro-USD per GPU-second.
        raise SystemExit(
            "refused: the console quote fields do not satisfy AcquisitionQuote "
            "(exact GPU catalog id, <= 2 h validity window, whole micro-USD per "
            "GPU-second)"
        ) from None
    raw = canonical_document_bytes(quote)
    Path(args.out).write_bytes(raw + b"\n")
    # Shape parity through the loader the benchmark CLI itself uses.
    load_document(args.out, AcquisitionQuote)
    print(
        json.dumps(
            {
                "quote": str(Path(args.out)),
                "canonical_sha256": quote.quote_sha256,
                "file_sha256": hashlib.sha256(raw + b"\n").hexdigest(),
            }
        )
    )
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    from microdrama.config import Settings
    from microdrama.pipeline.benchmark import main as benchmark_main

    output = Path(args.output)
    command = [
        "preflight",
        "--experiment-id",
        args.experiment_id,
        "--authorization",
        args.authorization,
        "--output",
        str(output),
    ]
    if args.quote:
        command += ["--quote", args.quote]
    settings = Settings.from_env().model_copy(update={"database_url": args.dsn})
    db = _db(args.dsn)
    try:
        code = benchmark_main(command, _injection={"settings": settings, "db": db})
    finally:
        db.close()
    if code != 0:
        return code  # the CLI already printed its refusal
    result = json.loads(output.read_text())
    if result.get("ready"):
        print(
            json.dumps(
                {
                    "verify": "PASS",
                    "experiment_id": result.get("experiment_id"),
                    "plan_sha256": result.get("plan_sha256"),
                    "sealed_sha256": result.get("sealed_sha256"),
                    "authorization_sha256": result.get("authorization_sha256"),
                },
                sort_keys=True,
            )
        )
        return 0
    reasons = result.get("reasons") or ["preflight reported not ready"]
    print(f"verify: REFUSED: {reasons[0]}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    register = sub.add_parser("register")
    register.add_argument("--dsn", required=True)
    register.add_argument("--refs-r1", required=True, type=Path)
    register.add_argument("--refs-r2", required=True, type=Path)
    register.add_argument("--voices", required=True, type=Path)
    register.add_argument("--store-root", required=True, type=Path)
    register.add_argument("--out", required=True, type=Path)
    register.add_argument("--runpod-credential", default="credref:runpod-drama-box-canary")
    register.add_argument("--comfy-credential", default="credref:comfy-drama-box-canary")
    register.set_defaults(func=cmd_register)

    author = sub.add_parser("author")
    author.add_argument("--experiment-id", required=True)
    author.add_argument("--episode-id", required=True)
    author.add_argument("--bindings", required=True, type=Path)
    author.add_argument("--shots", required=True, type=Path)
    author.add_argument("--trials", required=True, type=Path)
    author.add_argument("--capture-record", required=True, type=Path)
    author.add_argument("--prediction-raw", required=True, type=Path)
    author.add_argument("--image-ref", required=True)
    author.add_argument("--eligible-until", required=True)
    author.add_argument("--hard-stop-utc", required=True)
    author.add_argument("--operator", default="operator@aivora")
    author.add_argument("--change-ref", required=True)
    author.add_argument("--provider-account-ref", default="acct:drama-box-t031")
    author.add_argument("--namespace", default="t031bench")
    author.add_argument("--runpod-credential", default="credref:runpod-drama-box-canary")
    author.add_argument("--comfy-credential", default="credref:comfy-drama-box-canary")
    author.add_argument("--boot-budget-ms", type=int, default=25 * 60 * 1000)
    author.add_argument("--out", required=True, type=Path)
    author.set_defaults(func=cmd_author)

    quote = sub.add_parser("quote")
    quote.add_argument("--fields", required=True, type=Path)
    quote.add_argument("--out", required=True, type=Path)
    quote.set_defaults(func=cmd_quote)

    verify = sub.add_parser("verify")
    verify.add_argument("--dsn", required=True)
    verify.add_argument("--experiment-id", required=True)
    verify.add_argument("--authorization", required=True)
    verify.add_argument("--quote", required=False)
    verify.add_argument("--output", default="preflight.json")
    verify.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
