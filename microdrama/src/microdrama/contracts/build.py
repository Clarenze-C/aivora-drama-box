"""``make contracts`` / ``make contracts-check`` entry point.

Generates, under ``microdrama/contracts/``:
  VERSION
  schemas/v1/<Model>.schema.json      JSON Schema (validation mode) for every model
  examples/v1/valid/<Model>.json       canonical valid example per SPEC §4.2 payload
  examples/v1/invalid/<Model>__<case>.json
  examples/v1/manifest.json            example → model, expected validity, canonical hash

Then validates: valid examples parse with the Pydantic model, satisfy the
generated JSON Schema and reproduce their canonical hash; invalid examples are
rejected by the Pydantic model. ``--check`` regenerates in memory and fails if
the committed files differ (drift) or any validation fails.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import jsonschema
from pydantic import BaseModel, ValidationError

from microdrama.contracts import CONTRACT_VERSION
from microdrama.contracts.examples import EXTRA_VALID, VALID_BUILDERS, invalid_cases
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.registry import ALL_MODELS, CORE_PAYLOADS

ROOT = Path(__file__).resolve().parents[3] / "contracts"

# Invalid examples whose defect is structural (unknown field, enum, pattern, length,
# required field, range on a non-float value). The published JSON Schema itself must
# reject these, not only the Pydantic model. Cross-field rules (and integer-vs-float:
# JSON Schema treats 3.0 as an integer) are enforced by the Pydantic models only; the
# manifest records `json_schema_rejects` for every invalid example so consumers know.
SCHEMA_MUST_REJECT = frozenset(
    {
        "SeasonScope__unknown_field",
        "SeasonScope__stale_schema_version",
        "SeasonScope__constraint_above_enforced_limit",
        "ShotManifest__unknown_control",
        "RenderRequest__unknown_control",
        "BudgetReservationRequest__no_timeout",
        "UsageReceipt__negative_amount",
        "ProviderOperation__missing_client_token",
        "IdentityLock__empty_lock",
        "HookExperiment__two_candidates",
        "HookExperiment__new_render_jobs",
        "ObservationRequest__includes_intended_script",
        "ObservationRequest__includes_expected_dialogue",
        "ObservationReport__no_coverage",
        "ComparisonRequest__bad_hash",
        "QualificationResult__required_not_ten",
        "DomainEvent__bad_event_type",
    }
)


def _schema_rejects(schema: dict, payload: object) -> bool:
    validator = jsonschema.Draft202012Validator(schema)
    return any(True for _ in validator.iter_errors(payload))


def _dump(obj: object) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def render() -> dict[str, str]:
    """All generated files as {relative path: text}."""
    files: dict[str, str] = {"VERSION": CONTRACT_VERSION + "\n"}
    for name, model in sorted(ALL_MODELS.items()):
        schema = model.model_json_schema(mode="validation")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"urn:microdrama:contracts:{CONTRACT_VERSION}:{name}"
        files[f"schemas/v1/{name}.schema.json"] = _dump(schema)

    manifest: dict[str, dict[str, object]] = {}
    valid = {name: builder for name, builder in VALID_BUILDERS.items()}
    valid.update(EXTRA_VALID)
    for example_name, builder in sorted(valid.items()):
        model_name = example_name.split("__", 1)[0]
        instance = builder()
        path = f"examples/v1/valid/{example_name}.json"
        files[path] = _dump(instance.model_dump(mode="json"))
        manifest[path] = {
            "model": model_name,
            "expect": "valid",
            "canonical_sha256": canonical_hash(instance),
        }
    for model_name, case, reason, payload in invalid_cases():
        path = f"examples/v1/invalid/{model_name}__{case}.json"
        files[path] = _dump(payload)
        schema = json.loads(files[f"schemas/v1/{model_name}.schema.json"])
        manifest[path] = {
            "model": model_name,
            "expect": "invalid",
            "reason": reason,
            "json_schema_rejects": _schema_rejects(schema, payload),
        }
    files["examples/v1/manifest.json"] = _dump(manifest)
    return files


def validate(files: dict[str, str]) -> list[str]:
    problems: list[str] = []
    manifest = json.loads(files["examples/v1/manifest.json"])
    for path, entry in manifest.items():
        model: type[BaseModel] = ALL_MODELS[entry["model"]]
        text = files[path]
        if entry["expect"] == "valid":
            try:
                instance = model.model_validate_json(text)
            except ValidationError as exc:
                problems.append(f"{path}: valid example rejected: {exc.errors()[:1]}")
                continue
            if canonical_hash(instance) != entry["canonical_sha256"]:
                problems.append(f"{path}: canonical hash not reproducible")
            schema = json.loads(files[f"schemas/v1/{entry['model']}.schema.json"])
            try:
                jsonschema.validate(json.loads(text), schema, cls=jsonschema.Draft202012Validator)
            except jsonschema.ValidationError as exc:
                problems.append(f"{path}: fails generated JSON Schema: {exc.message[:200]}")
        else:
            try:
                model.model_validate_json(text)
            except ValidationError:
                continue
            problems.append(f"{path}: invalid example was ACCEPTED ({entry['reason']})")
    for path, entry in manifest.items():
        name = path.rsplit("/", 1)[-1].removesuffix(".json")
        if name not in SCHEMA_MUST_REJECT:
            continue
        schema = json.loads(files[f"schemas/v1/{entry['model']}.schema.json"])
        if not _schema_rejects(schema, json.loads(files[path])):
            problems.append(f"{path}: structural defect not rejected by the published JSON Schema")
    missing = SCHEMA_MUST_REJECT - {
        p.rsplit("/", 1)[-1].removesuffix(".json") for p in manifest if "/invalid/" in p
    }
    problems.extend(f"SCHEMA_MUST_REJECT names unknown example {m}" for m in sorted(missing))
    covered = {e["model"] for e in manifest.values() if e["expect"] == "invalid"}
    for name in CORE_PAYLOADS:
        if name not in covered:
            problems.append(f"{name}: no invalid example")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    files = render()
    problems = validate(files)
    if args.write:
        for rel, text in files.items():
            target = ROOT / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        generated = set(files)
        for stale in ROOT.glob("**/*.json"):
            rel = stale.relative_to(ROOT).as_posix()
            if rel not in generated and (rel.startswith("schemas/") or rel.startswith("examples/")):
                stale.unlink()
    else:
        for rel, text in files.items():
            target = ROOT / rel
            if not target.exists():
                problems.append(f"missing generated file {rel} (run make contracts)")
            elif target.read_text(encoding="utf-8") != text:
                problems.append(f"drift in {rel} (run make contracts)")
        for existing in ROOT.glob("**/*.json"):
            rel = existing.relative_to(ROOT).as_posix()
            if rel not in files and (rel.startswith("schemas/") or rel.startswith("examples/")):
                problems.append(f"stale generated file {rel}")

    for problem in problems:
        print("CONTRACT PROBLEM:", problem, file=sys.stderr)
    n_valid = sum(1 for p in files if "/valid/" in p)
    n_invalid = sum(1 for p in files if "/invalid/" in p)
    n_schema = sum(1 for p in files if p.startswith("schemas/"))
    print(
        f"contracts {CONTRACT_VERSION}: {n_schema} schemas, {n_valid} valid and "
        f"{n_invalid} invalid examples; {'OK' if not problems else f'{len(problems)} problem(s)'}"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
