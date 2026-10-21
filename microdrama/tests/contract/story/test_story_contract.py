"""Contract-level behaviour of the story module's payloads, playbook and compiler (T010).

Pure tests (no database): they pin the payload surface and frozen-contract compliance the
integrator registers against — closed models, closed enums, strict money/duration types,
the six-pattern directing playbook read from the shared accepted example as INPUT, the
compiler producing contract-valid EpisodePlan/Script/ShotManifest with every required
playbook/routing field, and typed refusals for canon writes outside PLANNED.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from story_contract_support import bible_from_scope, canonical_writer_output

from microdrama.contracts.enums import ControlKind, ShotPattern
from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.examples import season_scope
from microdrama.contracts.examples import shot as example_shot
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.season import EpisodePlan, Script, ShotManifest
from microdrama.story import (
    DEFAULT_SUPPORTED_CONTROLS,
    DIRECTING_PLAYBOOK,
    WRITABLE_CANON_KINDS,
    CanonKind,
    compile_episode,
    default_playbook_path,
    estimated_runtime_ms,
    load_playbook_example,
    parse_critic_verdict,
    parse_writer_draft,
)
from microdrama.story.models import DraftFinding, WriteOutcome, WriterDraft

_T0 = datetime(2026, 10, 21, tzinfo=UTC)


# --- module payloads are closed and strict -------------------------------------------


def test_module_payloads_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        DraftFinding(code="x", severity="BLOCKED", detail="d", surprise=True)
    with pytest.raises(ValidationError):
        WriterDraft(scenes=[], extra=1)


def test_write_status_enum_is_closed() -> None:
    outcome = WriteOutcome(episode_id=uuid4(), status="CURRENT", settled_micro_usd=1)
    assert outcome.status.value == "CURRENT"
    with pytest.raises(ValidationError):
        WriteOutcome(episode_id=uuid4(), status="SUCCESS", settled_micro_usd=1)


def test_money_is_integer_micro_usd_only() -> None:
    with pytest.raises(ValidationError):
        WriteOutcome(episode_id=uuid4(), status="REPLAYED", settled_micro_usd=1.5)


def test_bible_round_trips_deterministically() -> None:
    bible = bible_from_scope(season_scope())
    dumped = bible.model_dump(mode="json")
    round_tripped = type(bible).model_validate(dumped).model_dump(mode="json")
    assert canonical_hash(dumped) == canonical_hash(round_tripped)


# --- the directing playbook: six patterns, read from the shared example ---------------


def test_embedded_playbook_matches_the_shared_example_file() -> None:
    loaded = load_playbook_example(default_playbook_path())
    assert len(loaded) == len(DIRECTING_PLAYBOOK) == 6
    for embedded, from_file in zip(DIRECTING_PLAYBOOK, loaded, strict=True):
        assert embedded.pattern_id is from_file.pattern_id
        assert embedded.purpose == from_file.purpose
        assert embedded.coverage == from_file.coverage
        assert embedded.continuity == from_file.continuity
        assert embedded.payoff == from_file.payoff


def test_playbook_covers_exactly_the_contract_enum() -> None:
    assert {p.pattern_id for p in DIRECTING_PLAYBOOK} == set(ShotPattern)
    for pattern in DIRECTING_PLAYBOOK:
        assert pattern.coverage and pattern.continuity
        assert pattern.default_fallback and pattern.default_tier


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda d: d.update(runtime_enabled=True), "runtime_enabled"),
        (lambda d: d.update(version="directing-playbook-v2"), "version drift"),
        (lambda d: d.update(document_kind="ACTIVE_LIBRARY"), "document_kind"),
        (lambda d: d["patterns"].pop(), "exactly the six"),
        (lambda d: d["patterns"][0].pop("payoff"), "malformed"),
    ],
)
def test_mutated_example_copies_are_refused(tmp_path, mutate, match) -> None:
    """The example is validated input, never a trusted writable library."""
    document = json.loads(default_playbook_path().read_text(encoding="utf-8"))
    mutate(document)
    path = tmp_path / "directing-playbook.example.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(SchemaInvalid, match=match):
        load_playbook_example(path)


def test_missing_example_file_is_a_typed_error(tmp_path) -> None:
    with pytest.raises(SchemaInvalid, match="unreadable"):
        load_playbook_example(tmp_path / "absent.json")


# --- writer/critic parsing contracts --------------------------------------------------


def test_synthesized_writer_output_parses_but_cannot_pass_critics() -> None:
    """The fake's schema-synthesized draft (no curated content) parses structurally and
    is then blocked by the deterministic critic — never a silent pass."""
    from microdrama.story import WRITER_OUTPUT_SCHEMA
    from microdrama.testing.fakes.llm import synthesize

    synthesized = synthesize(WRITER_OUTPUT_SCHEMA, "story")
    draft = parse_writer_draft(synthesized)
    assert draft.scenes and draft.scenes[0].lines
    from microdrama.contracts.primitives import DEFAULT_LIMITS
    from microdrama.story import check_draft

    findings = check_draft(
        draft,
        scope=season_scope(),
        bible=bible_from_scope(season_scope()),
        episode_number=1,
        estimated_runtime_ms=estimated_runtime_ms(draft),
        limits=DEFAULT_LIMITS,
    )
    assert any(f.code == "unknown-speaker" for f in findings)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda o: o.update(scenes=[]),
        lambda o: o["scenes"][0].update(lines=[]),
        lambda o: o["scenes"][0]["lines"][0].pop("text_en"),
        lambda o: o["scenes"][0]["lines"][0].update(
            critical_terms=[{"kind": "MAGIC", "value_th": "x"}]
        ),
    ],
)
def test_parse_writer_draft_typed_failures(mutate) -> None:
    output = copy.deepcopy(canonical_writer_output())
    mutate(output)
    with pytest.raises(SchemaInvalid):
        parse_writer_draft(output)


def test_parse_critic_verdict_contract() -> None:
    verdict = parse_critic_verdict(
        {
            "passed": False,
            "findings": [{"code": "canon", "severity": "BLOCKED", "detail": "wrong amount"}],
        }
    )
    assert verdict.passed is False and verdict.findings[0].code == "canon"
    with pytest.raises(SchemaInvalid):
        parse_critic_verdict({"findings": []})
    # An unknown severity is conservatively REPAIRABLE, never dropped.
    soft = parse_critic_verdict(
        {"passed": True, "findings": [{"code": "pacing", "severity": "WHATEVER", "detail": "slow"}]}
    )
    assert soft.findings[0].severity.value == "REPAIRABLE"


# --- compiler output satisfies the frozen contracts ------------------------------------


def test_compiled_episode_satisfies_the_frozen_contracts() -> None:
    scope = season_scope()
    bible = bible_from_scope(scope)
    draft = parse_writer_draft(canonical_writer_output())
    episode_id, script_id, manifest_id = uuid4(), uuid4(), uuid4()

    plan, script, manifest, simplifications, notes = compile_episode(
        draft=draft,
        scope=scope,
        bible=bible,
        episode_id=episode_id,
        episode_number=1,
        script_id=script_id,
        manifest_id=manifest_id,
        script_version=1,
        manifest_version=1,
        identity_lock_id=None,
        supported_controls=DEFAULT_SUPPORTED_CONTROLS,
    )

    assert isinstance(plan, EpisodePlan) and isinstance(script, Script)
    assert isinstance(manifest, ShotManifest)
    assert 180_000 <= script.estimated_runtime_ms <= 300_000
    assert all(ln.actual_duration_ms is None for sc in script.scenes for ln in sc.lines)
    assert manifest.shots, "the manifest is never empty"
    assert simplifications and notes == []


def test_every_shot_carries_the_required_playbook_and_routing_fields() -> None:
    scope = season_scope()
    draft = parse_writer_draft(canonical_writer_output())
    _plan, _script, manifest, _s, _n = compile_episode(
        draft=draft,
        scope=scope,
        bible=bible_from_scope(scope),
        episode_id=uuid4(),
        episode_number=1,
        script_id=uuid4(),
        manifest_id=uuid4(),
        script_version=1,
        manifest_version=1,
        identity_lock_id=None,
        supported_controls=DEFAULT_SUPPORTED_CONTROLS,
    )
    playbook_ids = {p.pattern_id for p in DIRECTING_PLAYBOOK}
    for shot in manifest.shots:
        assert shot.shot_pattern_id in playbook_ids, "pattern must come from the playbook"
        assert shot.purpose and shot.coverage_role
        assert shot.framing and shot.eyelines and shot.sound
        assert shot.fallback_edit
        assert shot.preferred_render_tier
        assert shot.dramatic_importance and shot.temporal_risk
        assert ControlKind.TEXT_PROMPT in shot.required_identity_controls
        assert shot.acceptance_criteria
        assert shot.target_duration_ms <= 15_000


def test_camera_motion_is_simplified_not_silently_dropped() -> None:
    scope = season_scope()
    output = copy.deepcopy(canonical_writer_output())
    output["scenes"][0]["lines"][0]["controls"] = ["CAMERA_MOTION", "SEED"]
    draft = parse_writer_draft(output)
    _plan, _script, manifest, simplifications, _n = compile_episode(
        draft=draft,
        scope=scope,
        bible=bible_from_scope(scope),
        episode_id=uuid4(),
        episode_number=1,
        script_id=uuid4(),
        manifest_id=uuid4(),
        script_version=1,
        manifest_version=1,
        identity_lock_id=None,
        supported_controls=DEFAULT_SUPPORTED_CONTROLS,
    )
    shot = manifest.shots[1]  # first dialogue shot (line sc1-l1)
    assert ControlKind.CAMERA_MOTION not in shot.required_identity_controls
    assert ControlKind.SEED in shot.required_identity_controls
    assert simplifications and simplifications[0].removed_controls == ["CAMERA_MOTION"]


def test_later_episode_manifest_requires_the_identity_lock() -> None:
    """The frozen ShotManifest contract itself enforces IMP-01 for episode > 1."""
    scope = season_scope()
    draft = parse_writer_draft(canonical_writer_output())
    with pytest.raises(ValidationError, match="identity lock"):
        compile_episode(
            draft=draft,
            scope=scope,
            bible=bible_from_scope(scope),
            episode_id=uuid4(),
            episode_number=2,
            script_id=uuid4(),
            manifest_id=uuid4(),
            script_version=1,
            manifest_version=1,
            identity_lock_id=None,
            supported_controls=DEFAULT_SUPPORTED_CONTROLS,
        )


def test_canon_write_surface_is_planned_only() -> None:
    assert WRITABLE_CANON_KINDS == {"PLANNED"}
    assert {kind.value for kind in CanonKind} == {
        "PLANNED",
        "FINAL_APPROVED",
        "PUBLISHED",
    }
    from microdrama.story import StoryService

    assert hasattr(StoryService, "write_canon"), "the refusal hook is part of the surface"


def test_frozen_shot_example_still_validates_against_the_playbook_fields() -> None:
    """The contracts' own Shot example round-trips with every playbook field present."""
    shot = example_shot()
    assert shot.shot_pattern_id in {p.pattern_id for p in DIRECTING_PLAYBOOK}
    assert shot.acceptance_criteria and shot.fallback_edit
