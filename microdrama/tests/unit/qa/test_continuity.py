"""T042b unit tests: the actual-media continuity comparison, offline.

Pure-function coverage of the honesty rules and the repair-target routing —
no database, no service. The media is the labeled offline continuity defect
suite (session-scoped, generated once): the declared fixture truth IS the
offline observation stand-in, keyed by each file's real sha256, so the
comparison always runs against the actual exported media bytes.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from microdrama.config import Settings
from microdrama.contracts.enums import QAOutcome, RepairTarget
from microdrama.qa.continuity import (
    CALIBRATION_LABEL,
    CHECK_SPECS,
    CONTINUITY_CHECK_IDS,
    ContinuityDimension,
    ContinuityEvaluator,
    ContinuityObservation,
    EpisodeContinuityExpectations,
    FixtureContinuityObserver,
    LabeledContinuityCase,
    ObservedContinuityWindow,
    continuity_findings,
    run_continuity_calibration,
)
from microdrama.qa.report import green_summary

EPISODE_ID = uuid.uuid5(uuid.UUID(int=0), "t042b-unit")

ALL_DIMENSIONS = {dimension: 9_000 for dimension in ContinuityDimension}


def _evaluator(
    thresholds: dict[ContinuityDimension, int] | None = None,
) -> ContinuityEvaluator:
    return ContinuityEvaluator(
        "fixture-continuity",
        "1",
        "fixture-truth",
        thresholds if thresholds is not None else dict(ALL_DIMENSIONS),
    )


@pytest.fixture(scope="module")
def continuity_suite(tmp_path_factory):
    """The labeled offline continuity fixture set, generated once per module."""
    from microdrama.testing.media import FixtureTruthRegistry, continuity_defect_suite

    registry = FixtureTruthRegistry()
    root = tmp_path_factory.mktemp("continuity-suite")
    return continuity_defect_suite(root, registry), registry


@pytest.fixture(scope="module")
def expectations():
    from microdrama.testing.media import clean_continuity_expectations

    return clean_continuity_expectations(EPISODE_ID)


def _observe(registry, fixture, evaluator=None, *, sha=None):
    observer = FixtureContinuityObserver(registry, Settings(), evaluator or _evaluator())
    return observer.observe_continuity(
        asset_id=EPISODE_ID,
        asset_sha256=sha or fixture.sha256,
        media_path=fixture.path,
        duration_ms=fixture.truth.duration_ms,
    )


def _findings(observation, expectations, *, duration_ms=5_000, safe_area=None):
    kwargs = {} if safe_area is None else {"safe_area_bp": safe_area}
    return continuity_findings(
        run_key="t042b-unit-run-key",
        episode_id=EPISODE_ID,
        asset_id=EPISODE_ID,
        asset_sha256=observation.media_sha256,
        duration_ms=duration_ms,
        observation=observation,
        frozen_sha256=observation.observation_sha256(),
        expectations=expectations,
        **kwargs,
    )


# --- the clean control -------------------------------------------------------------------


def test_clean_media_passes_every_check_with_checked_coverage(
    continuity_suite, expectations
) -> None:
    suite, registry = continuity_suite
    observation = _observe(registry, suite["clean"])
    findings, coverage, evidence = _findings(observation, expectations)
    by_check = {f.check_id: f for f in findings}
    assert set(by_check) == set(CONTINUITY_CHECK_IDS)
    for finding in findings:
        assert finding.outcome is QAOutcome.PASS, finding.check_id
        assert finding.coverage.value == "CHECKED"
        assert not finding.repair_targets
    assert all(w.status.value == "CHECKED" for w in coverage)
    assert evidence["registered"] is True
    assert evidence["observation_sha256"] == observation.observation_sha256()
    assert evidence["media_sha256"] == suite["clean"].sha256
    # a green summary over the clean continuity findings is actually green
    all_green, blocking, _unknown = green_summary(findings, ())
    assert all_green and not blocking


# --- seeded defects: one check each, earliest correct repair target ------------------------


_DEFECT_KINDS = (
    "identity_defect",
    "outfit_defect",
    "prop_holder_defect",
    "location_defect",
    "eyeline_defect",
    "proof_text_defect",
    "thai_voice_defect",
    "subtitle_safe_area_defect",
)


@pytest.mark.parametrize("kind", _DEFECT_KINDS)
def test_seeded_defect_flags_exactly_its_check(continuity_suite, expectations, kind) -> None:
    suite, registry = continuity_suite
    observation = _observe(registry, suite[kind])
    findings, coverage, _evidence = _findings(observation, expectations)
    flagged = {f.check_id: f for f in findings if f.outcome is QAOutcome.REPAIRABLE}
    assert set(flagged) == set(suite[kind].defect_check_ids), (
        f"{kind}: flagged {sorted(flagged)} instead of {suite[kind].defect_check_ids}"
    )
    for check_id, finding in flagged.items():
        targets = {target for target in finding.repair_targets}
        if check_id in {
            CHECK_SPECS[ContinuityDimension.IDENTITY].check_id,
            CHECK_SPECS[ContinuityDimension.OUTFIT].check_id,
            CHECK_SPECS[ContinuityDimension.PROP_HOLDER].check_id,
            CHECK_SPECS[ContinuityDimension.LOCATION_SPACE].check_id,
            CHECK_SPECS[ContinuityDimension.EYELINE_HANDOFF].check_id,
            CHECK_SPECS[ContinuityDimension.PROOF_TEXT].check_id,
        }:
            assert targets == {RepairTarget.SHOT}, (check_id, targets)
            assert RepairTarget.CAPTION not in targets  # no caption-only fix, ever
        elif check_id == CHECK_SPECS[ContinuityDimension.THAI_VOICE].check_id:
            assert targets == {RepairTarget.LINE, RepairTarget.AUDIO_MIX}
        else:
            assert check_id == CHECK_SPECS[ContinuityDimension.SUBTITLE_SAFE_AREA].check_id
            assert targets == {RepairTarget.CAPTION, RepairTarget.EDIT}
    # a CRITICAL continuity mismatch blocks release even though the id is not in
    # the configured T017 critical set
    all_green, blocking, _unknown = green_summary(findings, ())
    if any(f.severity.value == "CRITICAL" for f in flagged.values()):
        assert not all_green
        assert set(flagged) <= set(blocking)


def test_identity_defect_blocks_release_outside_critical_check_ids(
    continuity_suite, expectations
) -> None:
    """The frozen blocking rule (CRITICAL severity) carries the new ids too."""
    suite, registry = continuity_suite
    observation = _observe(registry, suite["identity_defect"])
    findings, _coverage, _evidence = _findings(observation, expectations)
    identity = CHECK_SPECS[ContinuityDimension.IDENTITY].check_id
    all_green, blocking, _unknown = green_summary(
        findings,
        ("technical.decode", "asr.speaker_match"),  # T017 ids only
    )
    assert not all_green
    assert identity in blocking


# --- honesty rules -----------------------------------------------------------------------


def test_unregistered_media_never_passes(continuity_suite, expectations) -> None:
    """Media no observation source knows observes nothing: UNKNOWN, never PASS."""
    from microdrama.testing.media import FixtureTruthRegistry

    suite, _registry = continuity_suite
    empty = FixtureTruthRegistry()  # knows nothing
    observation = _observe(empty, suite["clean"])
    assert observation.source_label == "unregistered"
    assert not observation.windows
    findings, coverage, _evidence = _findings(observation, expectations)
    assert findings
    for finding in findings:
        assert finding.outcome is QAOutcome.UNKNOWN
        assert finding.coverage.value == "UNAVAILABLE"
    assert all(w.status.value == "UNAVAILABLE" for w in coverage)
    all_green, blocking, _unknown = green_summary(findings, ())
    assert all_green and not blocking  # honest unknown, not a silent blocker


def test_sha_mismatch_observes_nothing(continuity_suite, expectations) -> None:
    """A lied-about sha256 must not observe the registered bytes' truth."""
    suite, registry = continuity_suite
    observation = _observe(registry, suite["clean"], sha="0" * 64)
    assert observation.source_label == "unregistered"
    findings, _coverage, _evidence = _findings(observation, expectations)
    assert all(f.outcome is QAOutcome.UNKNOWN for f in findings)


def test_missing_observer_and_missing_expectations_stay_unknown(
    continuity_suite, expectations
) -> None:
    suite, _registry = continuity_suite
    duration = suite["clean"].truth.duration_ms
    for expectations_arg in (expectations, None):
        findings, coverage, _evidence = continuity_findings(
            run_key="t042b-unit-run-key",
            episode_id=EPISODE_ID,
            asset_id=EPISODE_ID,
            asset_sha256=suite["clean"].sha256,
            duration_ms=duration,
            observation=None,
            frozen_sha256=None,
            expectations=expectations_arg,
        )
        assert {f.check_id for f in findings} == set(CONTINUITY_CHECK_IDS)
        for finding in findings:
            assert finding.outcome is QAOutcome.UNKNOWN
            assert finding.coverage.value == "UNAVAILABLE"
        assert coverage and all(w.status.value == "UNAVAILABLE" for w in coverage)


def test_frozen_digest_is_required_and_verified(continuity_suite, expectations) -> None:
    suite, registry = continuity_suite
    observation = _observe(registry, suite["clean"])
    from microdrama.contracts.errors import SchemaInvalid

    for bad_digest in (None, "0" * 64):
        with pytest.raises(SchemaInvalid):
            continuity_findings(
                run_key="t042b-unit-run-key",
                episode_id=EPISODE_ID,
                asset_id=EPISODE_ID,
                asset_sha256=suite["clean"].sha256,
                duration_ms=5_000,
                observation=observation,
                frozen_sha256=bad_digest,
                expectations=expectations,
            )


def test_partially_sampled_window_is_unknown_never_pass(continuity_suite, expectations) -> None:
    """A still-frame/keyframe PASS of part of a window cannot certify the rest."""
    from microdrama.qa.continuity import observation_from_truth

    suite, _registry = continuity_suite
    clean = suite["clean"].truth
    # sample only the first half of scene 1's window
    partial_truth = clean.model_copy(
        update={
            "fixture_id": "continuity-partial-sample",
            "covered_ranges_ms": ((0, 1_900),),
            "continuity": (clean.continuity[0].model_copy(update={"end_ms": 1_900}),),
        }
    )
    observation = observation_from_truth(partial_truth, "a" * 64, _evaluator())
    findings, coverage, _evidence = _findings(observation, expectations)
    identity = CHECK_SPECS[ContinuityDimension.IDENTITY].check_id
    identity_findings = [f for f in findings if f.check_id == identity]
    assert identity_findings
    for finding in identity_findings:
        # scene 1 is only half sampled: no PASS may leave this comparison
        assert finding.outcome is QAOutcome.UNKNOWN
        assert finding.coverage.value in {"PARTIAL", "UNSAMPLED"}
    windows = [w for w in coverage if w.check_id == identity]
    assert any(w.status.value == "UNSAMPLED" for w in windows)


def test_uncalibrated_dimension_is_unavailable(continuity_suite, expectations) -> None:
    suite, registry = continuity_suite
    only_identity = ContinuityEvaluator(
        "fixture-continuity", "1", "fixture-truth", {ContinuityDimension.IDENTITY: 9_000}
    )
    observation = _observe(registry, suite["clean"], only_identity)
    findings, coverage, _evidence = _findings(observation, expectations)
    identity = CHECK_SPECS[ContinuityDimension.IDENTITY].check_id
    by_check = {f.check_id: f for f in findings}
    assert by_check[identity].outcome is QAOutcome.PASS
    for check_id in CONTINUITY_CHECK_IDS:
        if check_id == identity:
            continue
        finding = by_check[check_id]
        assert finding.outcome is QAOutcome.UNKNOWN, check_id
        assert finding.coverage.value == "UNAVAILABLE", check_id


def test_below_threshold_confidence_is_unknown(continuity_suite, expectations) -> None:
    """A declared observation under the calibrated threshold cannot clear."""
    from microdrama.qa.continuity import observation_from_truth

    suite, _registry = continuity_suite
    low = suite["clean"].truth.model_copy(
        update={
            "fixture_id": "continuity-low-confidence",
            "continuity": tuple(
                window.model_copy(update={"confidence_bp": 4_000})
                for window in suite["clean"].truth.continuity
            ),
        }
    )
    observation = observation_from_truth(low, "b" * 64, _evaluator())
    findings, coverage, _evidence = _findings(observation, expectations)
    assert findings
    for finding in findings:
        assert finding.outcome is QAOutcome.UNKNOWN, finding.check_id
    assert all(w.status.value == "UNSAMPLED" for w in coverage)


# --- safe area configuration --------------------------------------------------------------


def test_safe_area_configuration_changes_the_verdict(continuity_suite, expectations) -> None:
    suite, registry = continuity_suite
    observation = _observe(registry, suite["subtitle_safe_area_defect"])
    subtitle = CHECK_SPECS[ContinuityDimension.SUBTITLE_SAFE_AREA].check_id
    strict, _coverage, _evidence = _findings(observation, expectations)
    flagged = [f for f in strict if f.check_id == subtitle and f.outcome is QAOutcome.REPAIRABLE]
    assert flagged  # the seeded defect trips the default safe area
    # a "safe area" that contains the defective box would be a config lie; the
    # comparison must follow configuration, and a matching box must PASS
    lax, _coverage2, _evidence2 = _findings(
        observation, expectations, safe_area=(0, 0, 10_000, 10_000)
    )
    passing = [f for f in lax if f.check_id == subtitle]
    assert all(f.outcome is QAOutcome.PASS for f in passing)


# --- expectations/observation binding (scoped review fixes 31 Oct 2026) --------------------


def test_expectations_reject_foreign_episode_and_out_of_range_windows(
    continuity_suite, expectations
) -> None:
    """The expectations seam payload must be THIS episode's, inside the media."""
    from microdrama.contracts.errors import Conflict

    suite, _registry = continuity_suite
    # bound expectations (windows inside the measured 5 s media) raise nothing
    expectations.validate_binding(expectations.episode_id, suite["clean"].truth.duration_ms)
    # another episode's payload is rejected outright
    with pytest.raises(Conflict, match="different episode"):
        expectations.validate_binding(uuid.uuid4(), suite["clean"].truth.duration_ms)
    # a window beyond the measured exported-media duration is rejected too
    stretched = EpisodeContinuityExpectations(
        episode_id=expectations.episode_id,
        windows=(
            expectations.windows[0],
            dataclasses.replace(expectations.windows[1], end_ms=5_001),
        ),
    )
    with pytest.raises(Conflict, match="duration"):
        stretched.validate_binding(stretched.episode_id, suite["clean"].truth.duration_ms)


def test_findings_reject_a_frozen_observation_of_other_media(
    continuity_suite, expectations
) -> None:
    """Comparison refuses an observation keyed to bytes other than the asset's."""
    from microdrama.contracts.errors import SchemaInvalid
    from microdrama.qa.continuity import observation_from_truth

    suite, _registry = continuity_suite
    # clean windows frozen against UNRELATED bytes, offered for this asset
    forged = observation_from_truth(suite["clean"].truth, "e" * 64, _evaluator())
    with pytest.raises(SchemaInvalid, match="different media bytes"):
        continuity_findings(
            run_key="t042b-unit-run-key",
            episode_id=EPISODE_ID,
            asset_id=EPISODE_ID,
            asset_sha256="f" * 64,
            duration_ms=5_000,
            observation=forged,
            frozen_sha256=forged.observation_sha256(),
            expectations=expectations,
        )


# --- observation binding ------------------------------------------------------------------


def test_observation_digest_binds_media_evaluator_and_ranges(continuity_suite) -> None:
    from microdrama.qa.continuity import observation_from_truth

    suite, registry = continuity_suite
    observation = _observe(registry, suite["clean"])
    base = observation.observation_sha256()
    # a different evaluator calibration is a different frozen observation
    other_evaluator = _observe(
        registry,
        suite["clean"],
        _evaluator({**ALL_DIMENSIONS, ContinuityDimension.IDENTITY: 5_000}),
    )
    assert other_evaluator.observation_sha256() != base
    # different sampled ranges are a different observation
    resampled = suite["clean"].truth.model_copy(
        update={
            "fixture_id": "continuity-resampled",
            "covered_ranges_ms": ((0, 3_800), (3_800, 5_000)),
        }
    )
    resampled_observation = observation_from_truth(resampled, "c" * 64, _evaluator())
    assert resampled_observation.observation_sha256() != base


def test_observer_refuses_outside_offline_mock(continuity_suite) -> None:
    from microdrama.contracts.enums import ExecutionMode
    from microdrama.contracts.errors import EffectDenied

    suite, registry = continuity_suite
    live = Settings(execution_mode=ExecutionMode.PRODUCTION)
    observer = FixtureContinuityObserver(registry, live, _evaluator())
    with pytest.raises(EffectDenied):
        observer.observe_continuity(
            asset_id=EPISODE_ID,
            asset_sha256=suite["clean"].sha256,
            media_path=suite["clean"].path,
            duration_ms=5_000,
        )


def test_motion_findings_cite_observed_media_windows(continuity_suite, expectations) -> None:
    """Every continuity finding cites the exported media, not a keyframe result."""
    suite, registry = continuity_suite
    observation = _observe(registry, suite["clean"])
    findings, _coverage, _evidence = _findings(observation, expectations)
    assert findings
    for finding in findings:
        assert finding.evidence, finding.check_id
        assert finding.evidence[0].ref.startswith("continuity:")
        assert 0 <= finding.start_ms < finding.end_ms <= 5_000


# --- offline calibration ------------------------------------------------------------------


def test_calibration_report_is_offline_labeled_and_deterministic(
    continuity_suite, expectations
) -> None:
    suite, registry = continuity_suite
    observer = FixtureContinuityObserver(registry, Settings(), _evaluator())
    cases = [
        LabeledContinuityCase(
            case_id=fixture.kind,
            media_path=fixture.path,
            asset_sha256=fixture.sha256,
            duration_ms=fixture.truth.duration_ms,
            defect_check_ids=frozenset(fixture.defect_check_ids),
            expectations=expectations,
        )
        for fixture in suite.values()
    ]
    report = run_continuity_calibration(cases, observer)
    assert report.case_count == len(cases) == 9
    assert report.label == CALIBRATION_LABEL == "OFFLINE_FIXTURE_ONLY"
    assert report.live_activation_enabled is False
    assert set(report.per_check) == set(CONTINUITY_CHECK_IDS)
    for check_id, calibration in report.per_check.items():
        assert calibration.tp == 1, check_id  # exactly its own seeded defect
        assert calibration.fp == 0, (check_id, calibration)
        assert calibration.fn == 0, (check_id, calibration)
        assert calibration.tn == 8, check_id
        assert calibration.applicable_cases == 9
        assert calibration.coverage_counts.get("CHECKED", 0) >= 1
    # applicability by shot class: the prop/proof checks are defined only by
    # the two-handed scene class; identity applies in every class
    prop = CHECK_SPECS[ContinuityDimension.PROP_HOLDER].check_id
    proof = CHECK_SPECS[ContinuityDimension.PROOF_TEXT].check_id
    identity = CHECK_SPECS[ContinuityDimension.IDENTITY].check_id
    two_handed = report.applicability_by_shot_class["TWO_HANDED_DIALOGUE"]
    single = report.applicability_by_shot_class["SINGLE_DIALOGUE"]
    assert two_handed[prop] == 9 and prop not in single  # 9 cases × the s1 window
    assert two_handed[proof] == 9 and proof not in single
    assert two_handed[identity] == 9 and single[identity] == 9
    # deterministic: the same inputs produce the identical report
    again = run_continuity_calibration(cases, observer)
    assert again.as_payload() == report.as_payload()


def test_calibration_counts_false_positives(continuity_suite, expectations) -> None:
    """A mislabeled case surfaces as FP or FN — the runner cannot hide it."""
    suite, registry = continuity_suite
    observer = FixtureContinuityObserver(registry, Settings(), _evaluator())
    mislabeled = LabeledContinuityCase(
        case_id="mislabeled",
        media_path=suite["identity_defect"].path,
        asset_sha256=suite["identity_defect"].sha256,
        duration_ms=suite["identity_defect"].truth.duration_ms,
        defect_check_ids=frozenset({CHECK_SPECS[ContinuityDimension.OUTFIT].check_id}),
        expectations=expectations,
    )
    report = run_continuity_calibration([mislabeled], observer)
    identity = CHECK_SPECS[ContinuityDimension.IDENTITY].check_id
    outfit = CHECK_SPECS[ContinuityDimension.OUTFIT].check_id
    assert report.per_check[identity].fp == 1  # flagged, not labeled
    assert report.per_check[outfit].fn == 1  # labeled, not flagged


def test_calibration_counts_unobserved_as_unknown_not_tn(continuity_suite, expectations) -> None:
    """An applicable-but-unobserved check is unknown_cases, never a TN."""
    suite, _registry = continuity_suite
    from microdrama.testing.media import FixtureTruthRegistry

    empty = FixtureTruthRegistry()
    observer = FixtureContinuityObserver(empty, Settings(), _evaluator())
    case = LabeledContinuityCase(
        case_id="unregistered-media",
        media_path=suite["clean"].path,
        asset_sha256=suite["clean"].sha256,
        duration_ms=5_000,
        defect_check_ids=frozenset(),
        expectations=expectations,
    )
    report = run_continuity_calibration([case], observer)
    for check_id, calibration in report.per_check.items():
        assert calibration.unknown_cases >= 1, check_id  # observed nothing
        assert calibration.tn == 0, (check_id, calibration)  # unknown is not a pass
        assert calibration.tp == 0 and calibration.fp == 0 and calibration.fn == 0


# --- observation model guards --------------------------------------------------------------


def test_observation_rejects_windows_outside_sampled_ranges() -> None:
    from microdrama.contracts.errors import SchemaInvalid

    with pytest.raises(SchemaInvalid):
        ContinuityObservation(
            media_sha256="0" * 64,
            evaluator=_evaluator(),
            sampled_ranges_ms=((1_000, 2_000),),
            windows=(ObservedContinuityWindow(start_ms=0, end_ms=3_000),),
            source_label="fixture-truth",
        )


def test_observation_rejects_disordered_ranges() -> None:
    from microdrama.contracts.errors import SchemaInvalid

    with pytest.raises(SchemaInvalid):
        ContinuityObservation(
            media_sha256="0" * 64,
            evaluator=_evaluator(),
            sampled_ranges_ms=((2_000, 3_000), (0, 1_000)),
            windows=(),
            source_label="fixture-truth",
        )
