"""T031 R5c (RR-T7, RR-T12): the predicted schema and its seal evidence.

The prediction's placeholders populate exactly the enums real files would
(per-folder membership; baked non-file entries exempt), the mapped hash is
denied when it is the published CPU schema, ``validate_for`` accepts the
PREDICTED pair only with all three machine checks, and a PREDICTED seal
passes ``benchmark preflight`` end-to-end.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_benchmark_authorization import plan_data, seal_data
from test_benchmark_world_composition import _compose, _quote

from microdrama.contracts.errors import PolicyDenied
from microdrama.pipeline.benchmark_authorization import (
    DENIED_LIVE_SCHEMA_SHA256,
    SCHEMA_MODEL_FOLDERS,
    BenchmarkAuthorization,
    BenchmarkSeal,
    predicted_enums_match_manifest,
)
from microdrama.pipeline.benchmark_service import BenchmarkService

pytestmark = pytest.mark.db

TOOLS = Path(__file__).resolve().parents[3] / "tools"
PREDICTED = {
    "schema_evidence": "PREDICTED_FROM_PINNED_IMAGE",
    "schema_attestation_source": "MANIFEST_PLACEHOLDER_CAPTURE",
}

#: R5V-4: a stand-in for the pinned image's schema_smoke.py - the same shape
#: of discovery ComfyUI's folder-listing loaders perform (the baked enum plus
#: every FILE the mounted model folder actually contains), run as a REAL
#: subprocess against the placeholders the tool staged.
_STANDIN_SMOKE = """
import json
import sys
from pathlib import Path

FOLDERS = %r

root = Path(sys.argv[1])
raw = json.loads(Path(sys.argv[2]).read_text())["schemas"]
for folder, (node, field) in FOLDERS.items():
    discovered = sorted(p.name for p in (root / folder).iterdir() if p.is_file())
    spec = raw[node]["input"]["required"][field]
    spec[0] = sorted(set(spec[0]) | set(discovered))
payload = {
    "evidence_kind": "PREDICTED_SCHEMA_PLACEHOLDERS",
    "inference_verified": False,
    "schemas": raw,
}
Path(sys.argv[3]).write_text(json.dumps(payload))
"""


def _run_stand_in_smoke(tmp_path: Path, context: Path) -> dict:
    fixture = (
        Path(__file__).parents[2] / "fixtures/pika_h3_flex_object_info_OFFLINE_FIXTURE_ONLY.json"
    )
    script = tmp_path / "standin_schema_smoke.py"
    script.write_text(_STANDIN_SMOKE % (dict(SCHEMA_MODEL_FOLDERS),))
    out = tmp_path / "schema-smoke.json"
    subprocess.run(
        [sys.executable, str(script), str(context), str(fixture), str(out)],
        check=True,
        timeout=60,
    )
    return json.loads(out.read_text(encoding="utf-8"))


def _predicted_raw() -> dict:
    """The offline fixture's schemas with the pinned placeholder names added
    to the four loader-node enums (what the bind-mounted zero-byte files make
    the image report)."""
    fixture = (
        Path(__file__).parents[2] / "fixtures/pika_h3_flex_object_info_OFFLINE_FIXTURE_ONLY.json"
    )
    raw = json.loads(json.dumps(json.loads(fixture.read_text())["schemas"]))
    sys.path.insert(0, str(TOOLS))
    import t031_schema_predict as predict

    for folder, names in predict.placeholder_layout(predict.load_manifest()).items():
        node, field = SCHEMA_MODEL_FOLDERS[folder]
        spec = raw[node]["input"]["required"][field]
        spec[0] = sorted(set(spec[0]) | set(names))
    return raw


def _capture_for(image_ref: str, raw: dict) -> dict:
    sys.path.insert(0, str(TOOLS))
    import t031_schema_predict as predict

    from microdrama.rendering.pika_transport import mapped_schema_sha256
    from microdrama.rendering.workflows.templates import PIKA_TEMPLATE

    return {
        "manifest_digest": image_ref.rsplit("@sha256:", 1)[-1],
        "placeholder_names": predict.placeholder_layout(predict.load_manifest()),
        "tool_version": predict.TOOL_VERSION,
        "captured_at": "2026-11-14T00:00:00+00:00",
        "node_schema_sha256": mapped_schema_sha256(raw, PIKA_TEMPLATE.node_classes),
    }


def _predicted_seal(
    image_ref: str = "registry.example/drama@sha256:" + "f" * 64,
    *,
    raw: dict | None = None,
    capture: dict | None = None,
):
    from uuid import uuid4

    from microdrama.pipeline.benchmark_authorization import BenchmarkPlan
    from microdrama.rendering.pika_transport import mapped_schema_sha256
    from microdrama.rendering.workflows.templates import PIKA_TEMPLATE

    plan = BenchmarkPlan.model_validate(plan_data() | {"episode_id": str(uuid4())})
    raw = _predicted_raw() if raw is None else raw
    seal = BenchmarkSeal.model_validate(
        seal_data(plan)
        | {
            **PREDICTED,
            "image_ref": image_ref,
            "raw_object_info": raw,
            "schema_capture": capture or _capture_for(image_ref, raw),
            "node_schema_sha256": mapped_schema_sha256(raw, PIKA_TEMPLATE.node_classes),
        }
    )
    return plan, seal


def test_rr_t7_placeholders_populate_exactly_the_pinned_enums(tmp_path) -> None:
    """R5V-4: the enums come from DISCOVERY, not from the manifest. The tool
    stages real zero-byte placeholders; a stand-in schema smoke (the same
    folder-listing discovery ComfyUI's loaders perform) runs as a subprocess
    and reports what it FINDS on disk; the capture record is built from that
    discovered payload - and is REFUSED when discovery diverges."""
    sys.path.insert(0, str(TOOLS))
    import t031_schema_predict as predict

    manifest = predict.load_manifest()
    layout = predict.placeholder_layout(manifest)

    # Real staging: zero-byte files, exactly the pinned names per folder.
    context = tmp_path / "context"
    mounted = predict.stage_placeholders(context, manifest)
    for folder, names in layout.items():
        on_disk = sorted(p.name for p in mounted[folder].iterdir() if p.is_file())
        assert on_disk == sorted(names), (folder, on_disk)
        assert all((mounted[folder] / name).stat().st_size == 0 for name in names)

    # Discovery through the stand-in pinned-runtime smoke (real subprocess,
    # real filesystem reads of the staged mounts).
    payload = _run_stand_in_smoke(tmp_path, context)
    raw = payload["schemas"]
    for folder, (node, field) in SCHEMA_MODEL_FOLDERS.items():
        listed = raw[node]["input"]["required"][field][0]
        for name in layout[folder]:
            assert name in listed, f"discovery missed {folder}/{name}"
    assert predicted_enums_match_manifest(raw), "discovered enums must match models.json"
    # The empty weight-free fixture (no files listed) does NOT match.
    fixture = json.loads(
        (
            Path(__file__).parents[2]
            / "fixtures/pika_h3_flex_object_info_OFFLINE_FIXTURE_ONLY.json"
        ).read_text()
    )
    assert not predicted_enums_match_manifest(fixture["schemas"])

    # The capture record builds from the DISCOVERED payload.
    from datetime import UTC, datetime

    from test_benchmark_authorization import NOW, authorization_data

    record = predict.capture_record(
        "ghcr.io/clarenze-c/drama-pika-h3-flex@sha256:" + "ab" * 32,
        payload,
        now=datetime(2026, 11, 15, tzinfo=UTC),
    )
    assert record["placeholder_names"] == layout
    assert record["node_schema_sha256"] not in DENIED_LIVE_SCHEMA_SHA256
    # And the seal evidence built from the discovery is accepted end-to-end.
    plan, seal = _predicted_seal(
        image_ref="ghcr.io/clarenze-c/drama-pika-h3-flex@sha256:" + "ab" * 32,
        raw=raw,
        capture=record,
    )
    authorization = BenchmarkAuthorization.model_validate(authorization_data(plan, seal))
    authorization.validate_for(plan, seal, now=NOW)

    # Divergent discovery (a placeholder missing from the mount the smoke
    # read) can never yield a capture record: the capture-time check refuses.
    divergent_context = tmp_path / "divergent"
    predict.stage_placeholders(divergent_context, manifest)
    sorted((divergent_context / "loras").iterdir())[0].unlink()
    divergent_payload = _run_stand_in_smoke(tmp_path, divergent_context)
    assert not predicted_enums_match_manifest(divergent_payload["schemas"])
    with pytest.raises(SystemExit, match="do not match the pinned models.json"):
        predict.capture_record(
            "ghcr.io/clarenze-c/drama-pika-h3-flex@sha256:" + "ab" * 32, divergent_payload
        )


def test_rr_t7_predicted_pair_accepted_only_with_all_three_checks() -> None:
    from test_benchmark_authorization import NOW, authorization_data

    plan, seal = _predicted_seal()
    authorization = BenchmarkAuthorization.model_validate(authorization_data(plan, seal))
    now = NOW

    def _authorize(mutated):
        return BenchmarkAuthorization.model_validate(authorization_data(plan, mutated))

    # All three checks hold: accepted.
    authorization.validate_for(plan, seal, now=now)

    # (1) the deny-set hash: relabel the capture with the published CPU hash.
    denied = seal.model_copy(update={"node_schema_sha256": next(iter(DENIED_LIVE_SCHEMA_SHA256))})
    with pytest.raises(PolicyDenied, match="CPU/no-weights"):
        _authorize(denied).validate_for(plan, denied, now=now)

    # (2) the seal's image digest differs from the capture record's digest.
    other_image = "registry.example/drama@sha256:" + "e" * 64
    drifted = seal.model_copy(update={"image_ref": other_image})
    with pytest.raises(PolicyDenied, match="different image"):
        _authorize(drifted).validate_for(plan, drifted, now=now)
    stale_capture = seal.model_copy(
        update={"schema_capture": {**seal.schema_capture, "manifest_digest": "d" * 64}}
    )
    with pytest.raises(PolicyDenied, match="different image|manifest digest"):
        _authorize(stale_capture).validate_for(plan, stale_capture, now=now)

    # (3) the enums differ from models.json.
    wrong_enums = json.loads(json.dumps(seal.raw_object_info))
    wrong_enums["VAELoader"]["input"]["required"]["vae_name"][0] = [
        name
        for name in wrong_enums["VAELoader"]["input"]["required"]["vae_name"][0]
        if not name.endswith(".safetensors")
    ]
    wrong = seal.model_copy(update={"raw_object_info": wrong_enums})
    with pytest.raises(PolicyDenied, match="enums differ"):
        _authorize(wrong).validate_for(plan, wrong, now=now)

    # Wrong source label refused; SELF_ASSERTED stays refused.
    bad_source = seal.model_copy(update={"schema_attestation_source": "SELF_ASSERTED"})
    with pytest.raises(PolicyDenied, match="placeholder capture source"):
        _authorize(bad_source).validate_for(plan, bad_source, now=now)


def test_rr_t7_local_image_id_capture_is_refused() -> None:
    sys.path.insert(0, str(TOOLS))
    import t031_schema_predict as predict

    with pytest.raises(SystemExit, match="REGISTRY reference"):
        predict.registry_manifest_digest("drama-pika-h3-flex:t031-native")
    assert predict.registry_manifest_digest("ghcr.io/x/y@sha256:" + "a" * 64) == "a" * 64


def test_rr_t12_predicted_seal_passes_preflight_end_to_end(
    db, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "microdrama.pipeline.experimental_world.ExperimentalPresetPolicy.validate",
        lambda *args, **kwargs: None,
    )
    # The fixture authorization's hard stop predates the composition clock;
    # the authorization layer has its own suite (T7 drives validate_for
    # directly) - here the PREFLIGHT gate is what must accept the PREDICTED
    # seal.
    monkeypatch.setattr(BenchmarkService, "_validate_authorization", lambda *args, **kwargs: None)

    class _NoComfy:
        def request(self, *args, **kwargs):
            raise AssertionError("no comfy call during preflight")

    from test_benchmark_world_composition import _settings

    from microdrama.rendering.pika_transport import mapped_schema_sha256
    from microdrama.rendering.workflows.templates import PIKA_TEMPLATE

    raw = _predicted_raw()
    image_ref = "registry.example/drama@sha256:" + "f" * 64
    overrides = {
        **PREDICTED,
        "image_ref": image_ref,
        "raw_object_info": raw,
        "schema_capture": _capture_for(image_ref, raw),
        "node_schema_sha256": mapped_schema_sha256(raw, PIKA_TEMPLATE.node_classes),
        "eligible_until": "2026-11-20T00:00:00+00:00",
        "hard_stop_utc": "2026-11-19T04:00:00+00:00",
    }
    world, plan, authorization, budget, clock, account_id = _compose(
        db, tmp_path, comfy_transport=_NoComfy(), seal_overrides=overrides
    )
    service = BenchmarkService(db, _settings(), clock=clock)
    result = service.preflight(plan.experiment_id, authorization, _quote())
    assert result["ready"] is True, result["reasons"]
