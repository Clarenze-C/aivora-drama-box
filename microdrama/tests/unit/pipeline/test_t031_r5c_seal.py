"""T031 R5c (RR-T7, RR-T12): the predicted schema and its seal evidence.

The prediction's placeholders populate exactly the enums real files would
(per-folder membership; baked non-file entries exempt), the mapped hash is
denied when it is the published CPU schema, ``validate_for`` accepts the
PREDICTED pair only with all three machine checks, and a PREDICTED seal
passes ``benchmark preflight`` end-to-end.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from test_benchmark_authorization import plan_data, seal_data
from test_benchmark_world_composition import _compose, _quote

from microdrama.contracts.errors import PolicyDenied
from microdrama.pipeline.benchmark_authorization import (
    DENIED_LIVE_SCHEMA_SHA256,
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


def _predicted_raw() -> dict:
    """The offline fixture's schemas with the pinned placeholder names added
    to the four loader-node enums (what the bind-mounted zero-byte files make
    the image report)."""
    fixture = json.loads(
        (
            Path(__file__).parents[2]
            / "fixtures/pika_h3_flex_object_info_OFFLINE_FIXTURE_ONLY.json"
        ).read_text()
    )
    raw = json.loads(json.dumps(fixture["schemas"]))
    sys.path.insert(0, str(TOOLS))
    import t031_schema_predict as predict

    for folder, names in predict.placeholder_layout(predict.load_manifest()).items():
        from microdrama.pipeline.benchmark_authorization import SCHEMA_MODEL_FOLDERS

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


def _predicted_seal(image_ref: str = "registry.example/drama@sha256:" + "f" * 64):
    from uuid import uuid4

    from microdrama.pipeline.benchmark_authorization import BenchmarkPlan
    from microdrama.rendering.pika_transport import mapped_schema_sha256
    from microdrama.rendering.workflows.templates import PIKA_TEMPLATE

    plan = BenchmarkPlan.model_validate(plan_data() | {"episode_id": str(uuid4())})
    raw = _predicted_raw()
    seal = BenchmarkSeal.model_validate(
        seal_data(plan)
        | {
            **PREDICTED,
            "image_ref": image_ref,
            "raw_object_info": raw,
            "schema_capture": _capture_for(image_ref, raw),
            "node_schema_sha256": mapped_schema_sha256(raw, PIKA_TEMPLATE.node_classes),
        }
    )
    return plan, seal


def test_rr_t7_placeholders_populate_exactly_the_pinned_enums() -> None:
    raw = _predicted_raw()
    assert predicted_enums_match_manifest(raw), "placeholder enums must match models.json"
    # Wrong enum: drop one pinned name from the diffusion_models listing.
    broken = json.loads(json.dumps(raw))
    listing = broken["UNETLoader"]["input"]["required"]["unet_name"][0]
    broken["UNETLoader"]["input"]["required"]["unet_name"][0] = listing[1:]
    assert not predicted_enums_match_manifest(broken)
    # The empty weight-free fixture (no files listed) does NOT match.
    fixture = json.loads(
        (
            Path(__file__).parents[2]
            / "fixtures/pika_h3_flex_object_info_OFFLINE_FIXTURE_ONLY.json"
        ).read_text()
    )
    assert not predicted_enums_match_manifest(fixture["schemas"])


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
