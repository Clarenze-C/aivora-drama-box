#!/usr/bin/env python
"""T031 R5c: predict the pinned image's runtime schema before any paid pod.

Runs the image's own ``schema_smoke.py`` inside the PINNED registry reference
(``--network none``) with five ZERO-BYTE placeholder files bind-mounted
read-only into the ComfyUI model folders (named exactly as ``models.json``
pins), so the model-name enums match a provisioned pod. The capture record
stores the REGISTRY MANIFEST DIGEST only - a local image ID is forbidden -
plus the placeholder names, tool version and UTC. The sealed
``PREDICTED_FROM_PINNED_IMAGE`` evidence this produces still requires the
guarded live schema comparison at readiness, which stays decisive before
every acquisition's first upload.

Offline tests cover the pure functions (layout, docker command shape, capture
record); the docker run itself is the orchestrator's step (spec §7 step 4)
against the pushed registry digest.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

TOOL_VERSION = "t031-schema-predict/1"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
MODELS_JSON = Path(__file__).resolve().parents[1] / "deployment" / "pika-h3-flex" / "models.json"


def load_manifest(path: Path = MODELS_JSON) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def placeholder_layout(manifest: dict) -> dict[str, list[str]]:
    """folder -> the exact pinned file names the placeholders must carry."""
    layout: dict[str, list[str]] = {}
    for record in manifest["files"]:
        folder, _, name = record["path"].rpartition("/")
        layout.setdefault(folder, []).append(name)
    return layout


def stage_placeholders(context: Path, manifest: dict) -> dict[str, Path]:
    """Write the zero-byte placeholder files into the build context."""
    layout = placeholder_layout(manifest)
    mounted: dict[str, Path] = {}
    for folder, names in layout.items():
        target = context / folder
        target.mkdir(parents=True, exist_ok=True)
        for name in names:
            (target / name).write_bytes(b"")
        mounted[folder] = target
    return mounted


def registry_manifest_digest(image_ref: str) -> str:
    """The digest a registry reference pins; a local image ID is refused."""
    if "@sha256:" not in image_ref:
        raise SystemExit(
            "refused: the prediction must run inside the pulled REGISTRY reference "
            "(ghcr.io/...@sha256:<manifest digest>); a local image ID proves nothing"
        )
    digest = image_ref.rsplit("@sha256:", 1)[-1]
    if not re.fullmatch(SHA256_PATTERN, digest):
        raise SystemExit("refused: the image reference does not carry a valid sha256 digest")
    return digest


def docker_command(image_ref: str, context: Path, output: Path) -> list[str]:
    """The documented offline smoke command (no network, read-only binds)."""
    manifest = load_manifest()
    mounted = stage_placeholders(context, manifest)
    command = ["docker", "run", "--rm", "--network", "none"]
    for folder in sorted(mounted):
        command += [
            "-v",
            f"{mounted[folder].resolve()}:/opt/ComfyUI/models/{folder}:ro",
        ]
    command += ["-v", f"{output.resolve()}:/tmp", "--entrypoint", "python"]
    command += [image_ref, "/opt/pika/schema_smoke.py"]
    return command


def capture_record(image_ref: str, smoke_payload: dict, *, now: datetime | None = None) -> dict:
    """Build the seal's capture record from one schema-smoke payload."""
    from microdrama.rendering.pika_transport import mapped_schema_sha256
    from microdrama.rendering.workflows.templates import PIKA_TEMPLATE

    raw = smoke_payload["schemas"]
    manifest = load_manifest()
    return {
        "manifest_digest": registry_manifest_digest(image_ref),
        "placeholder_names": placeholder_layout(manifest),
        "tool_version": TOOL_VERSION,
        "captured_at": (now or datetime.now(UTC)).isoformat(),
        "node_schema_sha256": mapped_schema_sha256(raw, PIKA_TEMPLATE.node_classes),
        "evidence_kind": smoke_payload.get("evidence_kind"),
        "inference_verified": bool(smoke_payload.get("inference_verified", False)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="pinned registry reference (with @sha256:)")
    parser.add_argument("--output", required=True, type=Path, help="capture artifact directory")
    parser.add_argument("--context", type=Path, help="placeholder context dir (default: fresh)")
    args = parser.parse_args(argv)

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    context = args.context or (output / "placeholders")
    digest = registry_manifest_digest(args.image)
    command = docker_command(args.image, context, output)
    print("predict: running the pinned image offline (no network):", " ".join(command[:6]), "…")
    completed = subprocess.run(command, check=False, capture_output=True, timeout=600)
    if completed.returncode != 0:
        sys.stderr.write(completed.stdout.decode()[-2000:] + completed.stderr.decode()[-2000:])
        raise SystemExit("refused: the offline schema smoke failed inside the pinned image")
    smoke_path = output / "schema-smoke.json"
    payload = json.loads(smoke_path.read_text(encoding="utf-8"))
    record = capture_record(args.image, payload)
    raw_bytes = json.dumps(
        payload["schemas"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    (output / "capture-record.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    (output / "raw_object_info.json").write_bytes(raw_bytes)
    print(
        json.dumps(
            {
                "manifest_digest": digest,
                "node_schema_sha256": record["node_schema_sha256"],
                "capture_record": str(output / "capture-record.json"),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
