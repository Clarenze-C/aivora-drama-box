"""The Pika H3 Flex image recipe stays buildable: every file the Dockerfile COPYs is staged by build.sh.

Regression (12 Nov 2026): CN-5 added ``COPY canary_gateway.py`` to the Dockerfile but not to build.sh's
context copy, so ``build.sh`` failed with ``"/canary_gateway.py": not found``.
"""

import re
from pathlib import Path

RECIPE = Path(__file__).resolve().parents[3] / "deployment" / "pika-h3-flex"
DOWNLOADED = {"comfyui.tar.gz"}  # fetched by build.sh with a pinned sha256, not copied


def _dockerfile_copy_sources() -> set[str]:
    sources: set[str] = set()
    for line in (RECIPE / "Dockerfile").read_text().splitlines():
        parts = line.split()
        if not parts or parts[0] != "COPY" or any(p.startswith("--from") for p in parts[1:]):
            continue
        args = [p for p in parts[1:] if not p.startswith("--")]
        sources.update(args[:-1])
    return sources


def _build_sh_staged() -> set[str]:
    text = (RECIPE / "build.sh").read_text()
    match = re.search(r'cp "\$here"/\{([^}]*)\} "\$context/"', text)
    assert match, "build.sh must stage the recipe files with one brace-list cp"
    return set(match.group(1).split(","))


def test_every_dockerfile_copy_source_is_staged_by_build_sh():
    missing = _dockerfile_copy_sources() - _build_sh_staged() - DOWNLOADED
    assert not missing, f"build.sh does not stage {sorted(missing)}"


def test_entrypoint_is_the_provisioning_start_script():
    """T031 R5a: the image boots through start.sh, which owns the gateway
    start, the optional MICRODRAMA_PROVISION_MODELS provisioning and the
    ComfyUI exec (never on PROVISION_FAILED)."""
    text = (RECIPE / "Dockerfile").read_text()
    assert 'ENTRYPOINT ["/opt/pika/start.sh"]' in text
    assert "COPY start.sh /opt/pika/start.sh" in text
    start = (RECIPE / "start.sh").read_text()
    assert start.startswith("#!/bin/sh")
    assert "MICRODRAMA_PROVISION_MODELS" in start
    assert "PROVISION_FAILED" in start
    # ComfyUI's exec line stays exactly the pinned base's argument line.
    assert "--listen 127.0.0.1 --port 8189 --disable-api-nodes --disable-all-custom-nodes" in start


def test_downloaded_sources_are_fetched_and_hash_checked():
    text = (RECIPE / "build.sh").read_text()
    for name in DOWNLOADED:
        assert f'--output "$context/{name}"' in text
        assert re.search(rf"[0-9a-f]{{64}}  \$context/{re.escape(name)}\" \| sha256sum -c -", text)
