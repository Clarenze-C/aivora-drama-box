"""`make contracts` outputs are complete, valid, deterministic and committed."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from microdrama.contracts import CONTRACT_VERSION, build
from microdrama.contracts.examples import VALID_BUILDERS, invalid_cases
from microdrama.contracts.registry import ALL_MODELS, CORE_PAYLOADS

MODULE_ROOT = Path(__file__).resolve().parents[3]


def test_every_spec_payload_has_valid_and_invalid_examples() -> None:
    assert set(VALID_BUILDERS) == set(CORE_PAYLOADS)
    assert {case[0] for case in invalid_cases()} >= set(CORE_PAYLOADS)
    assert len(CORE_PAYLOADS) == 29


def test_generated_files_validate() -> None:
    assert build.validate(build.render()) == []


def test_committed_contracts_match_source() -> None:
    assert build.main(["--check"]) == 0


def test_version_file() -> None:
    assert (
        (MODULE_ROOT / "contracts" / "VERSION").read_text().strip() == CONTRACT_VERSION == "1.4.0"
    )


def test_generation_is_deterministic_across_hash_seeds() -> None:
    code = (
        "from microdrama.contracts import build; import hashlib, json;"
        "f = build.render();"
        "print(hashlib.sha256(json.dumps(f, sort_keys=True).encode()).hexdigest())"
    )
    digests = set()
    for seed in ("0", "1", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(MODULE_ROOT / "src")}
        out = subprocess.run(
            [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
        )
        digests.add(out.stdout.strip())
    assert len(digests) == 1


def test_schemas_are_closed_objects() -> None:
    for name in ALL_MODELS:
        schema = json.loads(
            (MODULE_ROOT / "contracts" / "schemas" / "v1" / f"{name}.schema.json").read_text()
        )
        assert schema.get("additionalProperties") is False, (
            f"{name} schema must reject unknown fields"
        )


def test_structural_defects_are_rejected_by_the_published_schemas() -> None:
    manifest = json.loads(
        (MODULE_ROOT / "contracts" / "examples" / "v1" / "manifest.json").read_text()
    )
    for name in build.SCHEMA_MUST_REJECT:
        entry = manifest[f"examples/v1/invalid/{name}.json"]
        assert entry["json_schema_rejects"] is True, name
