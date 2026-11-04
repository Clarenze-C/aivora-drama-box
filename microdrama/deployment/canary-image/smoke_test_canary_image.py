"""Smoke-test the canary image against the exact graph the canary submits.

Run with the container up (ports published locally):

    docker run -d --name canary-smoke -p 127.0.0.1:18188:8188 drama-canary:t031
    cd /root/AIVORA/drama-box/microdrama
    PYTHONPATH=src .venv/bin/python deployment/canary-image/smoke_test_canary_image.py

Verifies, against the running container:
  1. /object_info exposes all four mapped node classes;
  2. the repo binder's graph for the canary request is accepted by /prompt;
  3. execution completes and the VHS output is fetchable with a sha256.

Exit 0 = image good. Any failure prints why and exits non-zero.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, "src")

from microdrama.contracts.cost import RenderRequest  # noqa: E402
from microdrama.rendering.workflows.templates import (  # noqa: E402
    PRESET_TEMPLATES,
    template_sha256,
)
from microdrama.rendering.workflows.binding import bind_workflow  # noqa: E402

MAPPED_CLASSES = {"LoadImage", "CheckpointLoaderSimple", "FakeVideoModelSampler",
                  "VHS_VideoCombine"}
PROMPT_TEXT = (
    "FIXTURE PROMPT — canary smoke: a single wide shot of a night market stall "
    "in Bangkok, warm tungten light, static camera."
)


def _get(base: str, path: str) -> dict:
    with urllib.request.urlopen(base + path, timeout=30) as response:
        return json.loads(response.read())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18188")
    parser.add_argument("--timeout-s", type=int, default=600)
    args = parser.parse_args()

    # 1. wait for /object_info and check the mapped classes
    deadline = time.monotonic() + args.timeout_s
    catalog: dict = {}
    while time.monotonic() < deadline:
        try:
            catalog = _get(args.base, "/object_info")
            break
        except Exception:
            time.sleep(3)
    if not catalog:
        print("FAIL: /object_info never answered")
        return 1
    missing = sorted(MAPPED_CLASSES - set(catalog))
    if missing:
        print(f"FAIL: /object_info is missing node classes: {missing}")
        return 1
    combo = catalog["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
    if "fake-video-model.safetensors" not in combo:
        print(f"FAIL: stub loader override not active, ckpt combo = {combo!r}")
        return 1
    print(f"OK: all mapped node classes exposed ({sorted(MAPPED_CLASSES)})")

    # 2. build the exact canary graph with the repo binder
    template = PRESET_TEMPLATES["fake-quality-8step"]
    from microdrama.contracts.enums import ControlKind, RenderTier

    request = RenderRequest(
        render_id=uuid.uuid4(),
        reservation_id=uuid.uuid4(),
        semantic_key="canary:smoke:0",
        episode_id=uuid.UUID("1c0ffee0-0000-4000-8000-00000000cafe"),
        episode_number=1,
        shot_id="canary-smoke",
        manifest_version=1,
        attempt_number=1,
        preset_id="fake-quality-8step",
        tier=RenderTier.QUALITY_EIGHT_STEP,
        required_controls=[ControlKind.SEED, ControlKind.TEXT_PROMPT],
        reference_asset_ids=[],
        audio_asset_id=None,
        identity_lock_id=None,
        workflow_sha256=template_sha256(template),
        seed=20261102,
        width=720,
        height=1280,
        fps=24,
        duration_ms=4042,
        prompt_text=PROMPT_TEXT,
    )
    bound = bind_workflow(template, request)
    graph = bound.graph if hasattr(bound, "graph") else bound.nodes
    body = json.dumps({"prompt": graph, "client_id": "canary-smoke"}).encode()
    req = urllib.request.Request(
        args.base + "/prompt", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        accepted = json.loads(response.read())
    if "prompt_id" not in accepted:
        print(f"FAIL: /prompt rejected the graph: {accepted}")
        return 1
    prompt_id = accepted["prompt_id"]
    print(f"OK: /prompt accepted the canary graph ({prompt_id})")

    # 3. poll /history and fetch the output
    while time.monotonic() < deadline:
        history = _get(args.base, f"/history/{prompt_id}")
        if history:
            break
        time.sleep(5)
    if not history:
        print("FAIL: /history never reported the prompt")
        return 1
    entry = history[prompt_id]
    status = entry.get("status", {})
    if status.get("status_str") != "success":
        print(f"FAIL: execution not successful: {json.dumps(status)[:2000]}")
        return 1
    outputs = entry.get("outputs", {})
    files = [
        (node_id, key, item)
        for node_id, node_out in outputs.items()
        for key, items in node_out.items()
        for item in items
    ]
    if not files:
        print(f"FAIL: no outputs in history: {json.dumps(outputs)[:2000]}")
        return 1
    node_id, key, item = files[0]
    view = (
        f"/view?filename={urllib.request.quote(item['filename'])}"
        f"&subfolder={urllib.request.quote(item.get('subfolder', ''))}"
        f"&type={urllib.request.quote(item.get('type', 'output'))}"
    )
    with urllib.request.urlopen(args.base + view, timeout=120) as response:
        payload = response.read()
    digest = hashlib.sha256(payload).hexdigest()
    out_path = Path("out/canary-smoke-output").resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    (out_path / item["filename"]).write_bytes(payload)
    print(f"OK: output fetched via {key} from node {node_id}: "
          f"{len(payload)} bytes sha256={digest}")
    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
