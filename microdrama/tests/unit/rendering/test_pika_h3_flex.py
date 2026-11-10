"""OFFLINE_FIXTURE_ONLY: graph/transport counterexamples, never paid qualification."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from uuid import uuid4

import pytest

from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode
from microdrama.contracts.errors import EffectDenied, NeedsReconciliation, SchemaInvalid
from microdrama.contracts.examples import (
    render_request,
    rights_record,
    v2_binding_example,
    v2_prompt_manifest,
)
from microdrama.contracts.hashing import canonical_hash, sha256_hex
from microdrama.contracts.v2 import ReferenceRole
from microdrama.references.v2_binding import ExpectedReference
from microdrama.rendering.pika_transport import PikaHttpClient, mapped_schema_sha256, upload_key_for
from microdrama.rendering.workflows.pika_h3_flex import (
    PIKA_CONFIG,
    PikaBindingContext,
    PikaPortMap,
    PikaUploadReceipt,
)
from microdrama.rendering.workflows.templates import (
    MOCK_VIDEO_TEMPLATE,
    PIKA_TEMPLATE,
    semantic_template_sha256,
    template_sha256,
)
from microdrama.rendering.workflows.v2_binding import bind_v2_workflow, verify_bound_v2_workflow


def rehash(record, **updates):
    data = record.model_dump(mode="python")
    data.update(updates)
    data["content_sha256"] = canonical_hash(
        {k: v for k, v in data.items() if k != "content_sha256"}
    )
    return type(record).model_validate(data)


def schema_fixture():
    return {
        kind: {
            "input": {
                "required": {"value": ["INT", {"min": 0, "max": 1.5, "tooltip": "UI only"}]},
                "optional": {},
            },
            "output": ["ANY"],
            "output_is_list": [False],
        }
        for kind in PIKA_TEMPLATE.node_classes
    }


def setup_native():
    voice = rehash(
        v2_binding_example(), role=ReferenceRole.VOICE, subject_id="fon", asset_id=uuid4()
    )
    m = rehash(
        v2_prompt_manifest(),
        bindings=v2_prompt_manifest().bindings + [voice],
        shot_duration_ms=5000,
        source_hashes=[
            *v2_prompt_manifest().source_hashes,
            *(b.asset_sha256 for b in v2_prompt_manifest().bindings),
            voice.asset_sha256,
        ],
    )
    request = render_request().model_copy(
        update={
            "episode_id": m.episode_id,
            "shot_id": m.shot_id,
            "duration_ms": 5000,
            "prompt_text": m.prompt_text,
            "required_controls": list(PIKA_TEMPLATE.supported_controls),
            "reference_asset_ids": [b.asset_id for b in m.bindings],
            "audio_asset_id": None,
            "width": 480,
            "height": 832,
            "preset_id": PIKA_TEMPLATE.template_id,
            "workflow_sha256": template_sha256(PIKA_TEMPLATE),
            "semantic_workflow_sha256": semantic_template_sha256(PIKA_TEMPLATE),
            "prompt_manifest_id": m.record_id,
            "prompt_manifest_sha256": m.content_sha256,
        }
    )
    exp, acq = uuid4(), uuid4()
    ports = []
    uploads = []
    ordinals = {"image": 0, "audio": 0}
    for b in m.bindings:
        kind = "audio" if b.role is ReferenceRole.VOICE else "image"
        n = ordinals[kind]
        ordinals[kind] += 1
        slot = f"ref_{'audios.ref_audio' if kind == 'audio' else 'images.ref_image'}_{n}"
        ports.append(
            PikaPortMap(
                b.role, b.subject_id, b.asset_id, b.asset_version, b.asset_sha256, kind, slot
            )
        )
        key = upload_key_for(exp, acq, b.asset_sha256, kind)
        uploads.append(
            PikaUploadReceipt(
                exp,
                acq,
                "owned",
                b.asset_sha256,
                kind,
                b.role,
                b.subject_id,
                slot,
                key,
                key,
                "VERIFIED",
                b.asset_sha256,
            )
        )
    grant = m.bindings[0].rights
    row = rights_record().model_copy(
        update={
            "rights_route_id": grant.rights_route_id,
            "subject_kind": grant.subject_kind,
            "subject_ref": grant.subject_ref,
            "version": grant.rights_version,
            "territories": grant.territories,
            "expires_at": grant.expires_at,
        }
    )
    raw = schema_fixture()
    context = PikaBindingContext(
        exp,
        acq,
        "owned",
        tuple(ports),
        tuple(uploads),
        {
            (b.role, b.subject_id): ExpectedReference(b.asset_id, b.asset_version, b.asset_sha256)
            for b in m.bindings
        },
        lambda *_: row,
        m.valid_from,
        ("TH",),
        raw,
        mapped_schema_sha256(raw, PIKA_TEMPLATE.node_classes),
    )
    return m, request, context


def test_native_graph_preserves_stereo_decode_and_ordered_voice():
    m, r, c = setup_native()
    b = bind_v2_workflow(PIKA_TEMPLATE, r, m, pika_context=c)
    verify_bound_v2_workflow(PIKA_TEMPLATE, r, m, b)
    assert b.graph["reference"]["inputs"]["ref_audios.ref_audio_0"] == ["input_3", 0]
    assert b.graph["create_video"]["inputs"]["audio"] == ["decode_audio", 0]
    assert b.graph["reference"]["inputs"]["length"] == 124
    assert b.graph["sampler_select"]["inputs"]["sampler_name"] == "lcm"
    assert b.graph["save_video"]["inputs"]["format.codec"] == "h264"
    assert PIKA_CONFIG.sha256 == PIKA_TEMPLATE.configuration_sha256


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_audio",
        "sampler",
        "role",
        "unknown",
        "foreign",
        "port",
        "schema",
        "rights",
        "source",
        "duplicate",
    ],
)
def test_corruption_refuses_before_prompt(mutation):
    m, r, c = setup_native()
    if mutation in {"missing_audio", "sampler"}:
        b = bind_v2_workflow(PIKA_TEMPLATE, r, m, pika_context=c)
        if mutation == "missing_audio":
            b.graph["create_video"]["inputs"].pop("audio")
        else:
            b.graph["sampler_select"]["inputs"]["sampler_name"] = "euler"
        with pytest.raises(SchemaInvalid):
            verify_bound_v2_workflow(PIKA_TEMPLATE, r, m, b)
        return
    if mutation == "role":
        c = replace(c, ports=(*c.ports[:-1], replace(c.ports[-1], role=ReferenceRole.OUTFIT)))
    if mutation == "unknown":
        c = replace(c, uploads=(*c.uploads[:-1], replace(c.uploads[-1], state="UNKNOWN")))
    if mutation == "foreign":
        c = replace(c, uploads=(*c.uploads[:-1], replace(c.uploads[-1], acquisition_id=uuid4())))
    if mutation == "port":
        c = replace(
            c, ports=(replace(c.ports[0], destination_slot="ref_images.ref_image_4"), *c.ports[1:])
        )
    if mutation == "schema":
        raw = copy.deepcopy(c.raw_object_info)
        raw["CreateVideo"]["input"]["required"]["value"][1]["max"] = 2
        c = replace(c, raw_object_info=raw)
    if mutation == "rights":
        c = replace(c, resolve_current_rights=lambda *_: None)
    if mutation == "source":
        c = replace(c, ports=(replace(c.ports[0], asset_sha256="0" * 64), *c.ports[1:]))
    if mutation == "duplicate":
        c = replace(c, ports=(c.ports[0], *c.ports[:-1]))
    with pytest.raises(SchemaInvalid):
        bind_v2_workflow(PIKA_TEMPLATE, r, m, pika_context=c)


def test_voice_requires_single_anchor_per_speaker():
    m, _, _ = setup_native()
    with pytest.raises(ValueError, match="one voice anchor"):
        rehash(m, bindings=m.bindings + [m.bindings[-1]])


def test_legacy_template_hash_omits_absent_config():
    t = MOCK_VIDEO_TEMPLATE
    payload = {
        "template_id": t.template_id,
        "version": t.version,
        "family": t.family,
        "supported_controls": sorted(c.value for c in t.supported_controls),
        "produced_media_kinds": list(t.produced_media_kinds),
        "node_classes": sorted(t.node_classes),
        "sampler_class": t.sampler_class,
        "model_checkpoint": t.model_checkpoint,
        "binds_negative_prompt": t.binds_negative_prompt,
    }
    assert template_sha256(t) == canonical_hash(payload)
    assert template_sha256(replace(t, configuration_sha256="1" * 64)) != template_sha256(t)


def test_raw_schema_ui_excluded_but_order_dynamic_constraints_outputs_pinned():
    raw = schema_fixture()
    h = mapped_schema_sha256(raw, PIKA_TEMPLATE.node_classes)
    raw["unrelated"] = {}
    raw["CreateVideo"]["input"]["required"]["value"][1]["tooltip"] = "changed"
    assert mapped_schema_sha256(raw, PIKA_TEMPLATE.node_classes) == h
    raw["CreateVideo"]["output_is_list"] = [True]
    assert mapped_schema_sha256(raw, PIKA_TEMPLATE.node_classes) != h
    raw["CreateVideo"]["input"]["optional"]["dynamic"] = [
        "AUTOGROW",
        {"template": {"min": 0, "max": 3}},
    ]
    assert mapped_schema_sha256(raw, PIKA_TEMPLATE.node_classes) != h
    raw["CreateVideo"]["input"]["required"]["value"][1]["max"] = float("nan")
    with pytest.raises(SchemaInvalid):
        mapped_schema_sha256(raw, PIKA_TEMPLATE.node_classes)


class ScriptedTransport:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def request(self, method, url, *, headers, body=None):
        self.calls.append((method, url, headers, body))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def client(transport, **options):
    return PikaHttpClient(
        Settings(execution_mode=ExecutionMode.PAID_BENCHMARK, paid_requests_enabled=True),
        credential_ref="credref:test",
        credential_resolver=lambda _: "SYNTHETIC_SECRET",
        request_guard=lambda *_: None,
        dispatch_guard=lambda *_: None,
        transport=transport,
        schema_sha256=mapped_schema_sha256(schema_fixture(), PIKA_TEMPLATE.node_classes),
        **options,
    )


def png():
    import struct
    import zlib

    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00" + b"\x00" * 6 + b"\x00" + b"\x00" * 6))
        + chunk(b"IEND", b"")
    )


def test_multipart_exact_bytes_guarded_readback_and_unknown_reconcile():
    data = png()
    digest = sha256_hex(data)
    key = upload_key_for(uuid4(), uuid4(), digest, "image")
    sub, name = key.rsplit("/", 1)
    tx = ScriptedTransport(
        [
            json.dumps(schema_fixture()).encode(),
            json.dumps({"name": name, "subfolder": sub, "type": "input"}).encode(),
            data,
        ]
    )
    c = client(tx)
    c.bind_pod_endpoint("owned", "https://owned-8188.proxy.runpod.net")
    with c.authorization_scope(
        reservation_id=uuid4(), episode_id=uuid4(), job_id=uuid4(), operation_id=None
    ):
        assert c.upload_input(data, "image", digest, key) == key
    assert data in tx.calls[1][3]
    assert tx.calls[1][2]["Content-Type"].startswith("multipart/form-data; boundary=")
    assert "type=input" in tx.calls[2][1]
    tx = ScriptedTransport([json.dumps(schema_fixture()).encode(), TimeoutError()])
    c = client(tx)
    c.bind_pod_endpoint("owned", "https://owned-8188.proxy.runpod.net")
    with c.authorization_scope(
        reservation_id=uuid4(), episode_id=uuid4(), job_id=uuid4(), operation_id=None
    ):
        with pytest.raises(NeedsReconciliation, match="UNKNOWN"):
            c.upload_input(data, "image", digest, key)
    assert len(tx.calls) == 2


def test_schema_change_and_invalid_input_prevent_upload():
    data = png()
    digest = sha256_hex(data)
    key = upload_key_for(uuid4(), uuid4(), digest, "image")
    raw = schema_fixture()
    raw["CreateVideo"]["output"] = ["WRONG"]
    tx = ScriptedTransport([json.dumps(raw).encode()])
    c = client(tx)
    c.bind_pod_endpoint("owned", "https://owned-8188.proxy.runpod.net")
    with c.authorization_scope(
        reservation_id=uuid4(), episode_id=uuid4(), job_id=uuid4(), operation_id=None
    ):
        with pytest.raises(SchemaInvalid):
            c.upload_input(data, "image", digest, key)
    assert len(tx.calls) == 1
    with pytest.raises(SchemaInvalid):
        c.upload_input(b"bad", "audio", sha256_hex(b"bad"), key)
    assert len(tx.calls) == 1


def test_unscoped_upload_has_no_network():
    tx = ScriptedTransport([])
    c = client(tx)
    data = png()
    digest = sha256_hex(data)
    with pytest.raises(EffectDenied):
        c.upload_input(data, "image", digest, upload_key_for(uuid4(), uuid4(), digest, "image"))
    assert tx.calls == []


def test_pinned_actual_cpu_schema_fixture_maps_real_dynamic_ports():
    from pathlib import Path

    fixture = json.loads(
        (
            Path(__file__).parents[2]
            / "fixtures/pika_h3_flex_object_info_OFFLINE_FIXTURE_ONLY.json"
        ).read_text()
    )
    raw = fixture["schemas"]
    assert fixture["evidence_kind"] == "OFFLINE_FIXTURE_ONLY"
    assert fixture["inference_verified"] is False
    digest = mapped_schema_sha256(raw, PIKA_TEMPLATE.node_classes)
    ref = raw["MiniMaxH3ReferenceToVideo"]["input"]["optional"]
    assert ref["ref_images"][1]["template"]["max"] == 9
    assert ref["ref_audios"][1]["template"]["prefix"] == "ref_audio_"
    assert "minimax" in raw["CLIPLoader"]["input"]["required"]["type"][0]
    ref["ref_audios"][1]["template"]["max"] = 2
    assert mapped_schema_sha256(raw, PIKA_TEMPLATE.node_classes) != digest


@pytest.mark.parametrize("audio_mode", ["native", "silent", "mono", "missing"])
def test_actual_mp4_native_stream_evidence(tmp_path, audio_mode):
    import subprocess

    from microdrama.rendering.pika_transport import verify_native_output

    path = tmp_path / "native.mp4"
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=480x832:r=24:d=5.166667",
    ]
    if audio_mode != "missing":
        source = (
            "anullsrc=r=32000:cl=stereo"
            if audio_mode == "silent"
            else "sine=frequency=440:sample_rate=32000"
        )
        command += [
            "-f",
            "lavfi",
            "-i",
            source,
            "-ac",
            "1" if audio_mode == "mono" else "2",
            "-c:a",
            "aac",
        ]
    command += [
        "-t",
        "5.166667",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-y",
        str(path),
    ]
    subprocess.run(command, check=True, capture_output=True, timeout=30)
    if audio_mode == "native":
        media = verify_native_output(path.read_bytes())
        assert media.sample_rate_hz == 32000
        assert media.channels == 2
    else:
        with pytest.raises(SchemaInvalid):
            verify_native_output(path.read_bytes())


def test_native_savevideo_history_handles_actual_previewvideo_metadata():
    tx = ScriptedTransport(
        [
            json.dumps(
                {
                    "prompt": {
                        "status": {"completed": True, "status_str": "success"},
                        "outputs": {
                            "save_video": {
                                "images": [
                                    {
                                        "filename": "native.mp4",
                                        "subfolder": "video",
                                        "type": "output",
                                    }
                                ],
                                "animated": [True],
                            }
                        },
                    }
                }
            ).encode()
        ]
    )
    c = client(tx)
    c.bind_pod_endpoint("owned", "https://owned-8188.proxy.runpod.net")
    with c.authorization_scope(
        reservation_id=uuid4(), episode_id=uuid4(), job_id=uuid4(), operation_id=uuid4()
    ):
        entry = c.history("prompt")
    assert entry.completed
    assert entry.outputs[0].media_kind == "video"
    assert entry.outputs[0].node_id == "save_video"
