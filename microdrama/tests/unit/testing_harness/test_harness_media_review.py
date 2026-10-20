"""ASR and media-review fakes: truth-only reporting, observation before comparison, seeded defects."""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from microdrama.contracts.enums import (
    AssetKind,
    AssetState,
    CheckFamily,
    CoverageStatus,
    Provenance,
    QAOutcome,
    Severity,
)
from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.examples import script
from microdrama.contracts.hashing import canonical_hash, file_sha256
from microdrama.contracts.media import AssetDescriptor, MediaInfo
from microdrama.contracts.providers import (
    ASRProvider,
    ASRRequest,
    ComparisonMaterials,
    MediaReviewProvider,
)
from microdrama.contracts.qa import (
    ComparisonRequest,
    MediaUnderReview,
    NeutralQuestion,
    ObservationRequest,
)
from microdrama.testing.fakes import (
    FakeASRProvider,
    FakeClock,
    FakeMediaReviewProvider,
    SequentialIds,
)
from microdrama.testing.fakes.media_review import PREFIX_IDENTITY, PREFIX_TEMPORAL
from microdrama.testing.media import make_clip

T0 = datetime(2026, 10, 20, tzinfo=UTC)
EPISODE = uuid.UUID(int=41)
LINE_WRONG_AMOUNT = "ห้าหมื่นบาท"
SCRIPT_LINE_FON = "ลุงเล็ก หนี้ห้าหมื่นบาทนี่คืออะไรคะ"


def _asr(clock: FakeClock, ids: SequentialIds, registry) -> FakeASRProvider:
    return FakeASRProvider(clock=clock, ids=ids, truth=registry)


def _review(clock: FakeClock, ids: SequentialIds, registry, phrases=()) -> FakeMediaReviewProvider:
    return FakeMediaReviewProvider(
        clock=clock, ids=ids, truth=registry, unreleased_claim_phrases=phrases
    )


def _asr_request(sha: str, asset: uuid.UUID) -> ASRRequest:
    return ASRRequest(
        request_id=uuid.UUID(int=51),
        asset_id=asset,
        asset_sha256=sha,
        model_config_ref="fake-asr-profile",
        client_token=f"asr-{sha[:8]}",
    )


def _descriptor(
    name: str, path: Path, sha: str, kind: AssetKind, has_audio: bool, has_video: bool
) -> AssetDescriptor:
    asset_id = uuid.uuid5(uuid.NAMESPACE_URL, f"asset:{name}")
    media = (
        MediaInfo(duration_ms=5_000, has_video=has_video, has_audio=has_audio)
        if kind is AssetKind.VIDEO
        else None
    )
    return AssetDescriptor(
        asset_id=asset_id,
        asset_kind=kind,
        object_key=f"fixtures/{path.name}",
        sha256=sha,
        size_bytes=path.stat().st_size,
        media_type="video/mp4" if kind is AssetKind.VIDEO else "application/json",
        media=media,
        state=AssetState.PROVISIONAL,
        provenance=Provenance.ORIGINAL_FIXTURE,
        created_at=T0,
    )


def _observe(clock, ids, registry, suite, name, phrases=()):
    defect = suite[name]
    kind = AssetKind.CAPTION if defect.media_kind == "caption" else AssetKind.VIDEO
    descriptor = _descriptor(name, defect.path, defect.sha256, kind,
                             defect.truth.has_audio, defect.truth.has_video)  # fmt: skip
    request = ObservationRequest(
        request_id=uuid.uuid5(uuid.NAMESPACE_URL, f"obs:{name}"),
        episode_id=EPISODE,
        media=[
            MediaUnderReview(
                asset_id=descriptor.asset_id,
                asset_sha256=defect.sha256,
                duration_ms=defect.truth.duration_ms,
            )
        ],  # fmt: skip
        questions=[
            NeutralQuestion(question_id="q-speakers", text="Who is speaking and what do they say?"),
            NeutralQuestion(
                question_id="q-amounts", text="List any amounts shown on screen or spoken."
            ),
        ],
    )
    review = _review(clock, ids, registry, phrases)
    result = review.observe(request, [descriptor])
    return result, request, descriptor


def _compare(clock, ids, registry, suite, name, phrases=()):
    result, _, _ = _observe(clock, ids, registry, suite, name, phrases)
    report = result.report
    script_doc = script()
    materials = ComparisonMaterials(frozen_report=report, script=script_doc)
    request = ComparisonRequest(
        request_id=uuid.uuid5(uuid.NAMESPACE_URL, f"cmp:{name}"),
        episode_id=EPISODE,
        observation_report_id=report.report_id,
        observation_report_sha256=canonical_hash(report),
        script_id=script_doc.script_id,
        script_version=1,
        script_sha256=canonical_hash(script_doc),
        canon_version=1,
        canon_sha256=canonical_hash({"canon": "v1"}),
    )
    return _review(clock, ids, registry, phrases).compare(request, materials)


def _ids_of(findings, check: str):
    return [f for f in findings if f.check_id == check]


def test_fakes_satisfy_their_protocols(clock: FakeClock, ids: SequentialIds, defect_suite) -> None:
    _, registry = defect_suite
    assert isinstance(_asr(clock, ids, registry), ASRProvider)
    assert isinstance(_review(clock, ids, registry), MediaReviewProvider)


def test_asr_reports_exactly_the_declared_speech_for_clean_media(clock, ids, defect_suite) -> None:
    suite, registry = defect_suite
    clean = suite["clean"]
    result = _asr(clock, ids, registry).transcribe(
        _asr_request(clean.sha256, uuid.UUID(int=52)), clean.path
    )
    assert [s.text for s in result.segments] == [s.text_th for s in clean.truth.spoken]
    assert all(c.status is CoverageStatus.CHECKED for c in result.coverage)
    assert result.provenance is Provenance.FAKE_SYNTHETIC
    assert all(r.provenance is Provenance.FAKE_SYNTHETIC for r in result.usage)


def test_asr_never_invents_text_for_unknown_media(clock, ids, defect_suite, tmp_path) -> None:
    _, registry = defect_suite
    unknown = make_clip(tmp_path / "unknown.mp4", duration_ms=1_000, with_audio=True)
    sha = file_sha256(str(unknown))
    result = _asr(clock, ids, registry).transcribe(_asr_request(sha, uuid.UUID(int=53)), unknown)
    assert result.segments == []
    assert {c.status for c in result.coverage} == {CoverageStatus.UNAVAILABLE}
    assert "ลุงเล็ก" not in repr(result)


def test_asr_refuses_to_report_truth_for_a_file_with_a_different_hash(
    clock, ids, defect_suite
) -> None:
    suite, registry = defect_suite
    clean = suite["clean"]
    wrong = _asr_request("0" * 64, uuid.UUID(int=54))
    result = _asr(clock, ids, registry).transcribe(wrong, clean.path)
    assert result.segments == []
    assert CoverageStatus.UNAVAILABLE in {c.status for c in result.coverage}


def test_asr_on_missing_audio_is_unavailable_not_silence(clock, ids, defect_suite) -> None:
    suite, registry = defect_suite
    defect = suite["missing_audio"]
    result = _asr(clock, ids, registry).transcribe(
        _asr_request(defect.sha256, uuid.UUID(int=55)), defect.path
    )
    assert result.segments == []
    assert {c.status for c in result.coverage} == {CoverageStatus.UNAVAILABLE}


def test_observe_has_no_script_parameter_and_builds_from_truth_only(
    clock, ids, defect_suite
) -> None:
    suite, registry = defect_suite
    assert list(inspect.signature(FakeMediaReviewProvider.observe).parameters) == [
        "self",
        "request",
        "media",
    ]
    result, _, _ = _observe(clock, ids, registry, suite, "wrong_amount")
    heard = " ".join(s.text for s in result.report.transcript)
    assert "ห้าพันบาท" in heard  # what the media says
    assert LINE_WRONG_AMOUNT not in heard  # the intended script's amount is not reported
    assert result.report.provenance is Provenance.FAKE_SYNTHETIC
    assert result.report.model_config_ref == "fake-observer-v1"


def test_observe_reports_identity_and_temporal_defects_as_observations(
    clock, ids, defect_suite
) -> None:
    suite, registry = defect_suite
    result, _, _ = _observe(clock, ids, registry, suite, "identity_swap")
    labels = [
        o.description
        for o in result.report.observations
        if o.description.startswith(PREFIX_IDENTITY)
    ]
    assert f"{PREFIX_IDENTITY}lek" in labels
    black, _, _ = _observe(clock, ids, registry, suite, "black_frames")
    assert any(o.description == f"{PREFIX_TEMPORAL}black frames" for o in black.report.observations)


def test_observe_rejects_media_outside_the_request(clock, ids, defect_suite) -> None:
    suite, registry = defect_suite
    clean = suite["clean"]
    descriptor = _descriptor("clean", clean.path, clean.sha256, AssetKind.VIDEO, True, True)
    request = ObservationRequest(
        request_id=uuid.UUID(int=61),
        episode_id=EPISODE,
        media=[
            MediaUnderReview(
                asset_id=uuid.UUID(int=62), asset_sha256=clean.sha256, duration_ms=5_000
            )
        ],
        questions=[NeutralQuestion(question_id="q", text="Who speaks?")],
    )
    with pytest.raises(SchemaInvalid):
        _review(clock, ids, registry).observe(request, [descriptor])


def test_clean_media_compares_without_any_blocking_finding(clock, ids, defect_suite) -> None:
    suite, registry = defect_suite
    result = _compare(clock, ids, registry, suite, "clean")
    assert result.findings
    assert not [f for f in result.findings if f.blocks_release]
    assert any(f.outcome is QAOutcome.PASS for f in result.findings)
    assert all(f.provenance is Provenance.FAKE_SYNTHETIC for f in result.findings)


@pytest.mark.parametrize(
    ("defect", "check", "severity"),
    [
        ("wrong_amount", "asr.critical_term_match", Severity.CRITICAL),
        ("wrong_speaker", "asr.speaker_match", Severity.CRITICAL),
        ("identity_swap", "visual_identity.match", Severity.CRITICAL),
        ("silence_gap", "asr.line_present", Severity.CRITICAL),
        ("black_frames", "temporal.black_frames", Severity.MAJOR),
        ("frozen_frames", "temporal.frozen_frames", Severity.MAJOR),
        ("bad_caption", "caption.critical_term_match", Severity.CRITICAL),
        ("caption_out_of_bounds", "caption.cue_within_media", Severity.MAJOR),
    ],
)
def test_each_seeded_defect_produces_its_expected_finding(
    clock, ids, defect_suite, defect: str, check: str, severity: Severity
) -> None:
    suite, registry = defect_suite
    findings = _ids_of(_compare(clock, ids, registry, suite, defect).findings, check)
    assert findings, f"{defect} should raise {check}"
    assert any(f.severity is severity and f.outcome is QAOutcome.REPAIRABLE for f in findings)


def test_wrong_amount_is_critical_and_blocks_release(clock, ids, defect_suite) -> None:
    suite, registry = defect_suite
    finding = _ids_of(_compare(clock, ids, registry, suite, "wrong_amount").findings,
                      "asr.critical_term_match")[0]  # fmt: skip
    assert finding.severity is Severity.CRITICAL
    assert finding.blocks_release is True
    assert finding.expected is not None and finding.expected.startswith(LINE_WRONG_AMOUNT)
    assert "ห้าพันบาท" in (finding.observed or "")


def test_wrong_cta_is_flagged_only_when_the_unreleased_phrase_is_configured(
    clock, ids, defect_suite
) -> None:
    suite, registry = defect_suite
    assert not _ids_of(
        _compare(clock, ids, registry, suite, "wrong_cta").findings, "caption.release_claim"
    )
    flagged = _compare(clock, ids, registry, suite, "wrong_cta", phrases=("ดูได้แล้วตอนนี้",))
    release = _ids_of(flagged.findings, "caption.release_claim")
    assert release and release[0].severity is Severity.CRITICAL


def test_truncated_output_is_never_a_pass(clock, ids, defect_suite) -> None:
    suite, registry = defect_suite
    truncated = suite["truncated_output"]
    assert truncated.complete is False
    result = _compare(clock, ids, registry, suite, "truncated_output")
    assert not [f for f in result.findings if f.outcome is QAOutcome.PASS]
    assert any(f.outcome is QAOutcome.UNKNOWN for f in result.findings)
    for finding in result.findings:
        if finding.outcome is QAOutcome.UNKNOWN:
            assert finding.coverage is not CoverageStatus.CHECKED


def test_missing_audio_never_passes_speech_checks(clock, ids, defect_suite) -> None:
    suite, registry = defect_suite
    result = _compare(clock, ids, registry, suite, "missing_audio")
    asr = [f for f in result.findings if f.check_family is CheckFamily.ASR]
    assert asr and all(f.outcome is QAOutcome.UNKNOWN for f in asr)


def test_compare_rejects_materials_that_do_not_match_the_request_hashes(
    clock, ids, defect_suite
) -> None:
    suite, registry = defect_suite
    result, _, _ = _observe(clock, ids, registry, suite, "clean")
    script_doc = script()
    request = ComparisonRequest(
        request_id=uuid.UUID(int=71),
        episode_id=EPISODE,
        observation_report_id=result.report.report_id,
        observation_report_sha256="f" * 64,  # not the frozen report
        script_id=script_doc.script_id,
        script_version=1,
        script_sha256=canonical_hash(script_doc),
        canon_version=1,
        canon_sha256=canonical_hash({"canon": "v1"}),
    )
    materials = ComparisonMaterials(frozen_report=result.report, script=script_doc)
    with pytest.raises(SchemaInvalid):
        _review(clock, ids, registry).compare(request, materials)


def test_status_for_requires_checked_coverage_across_the_whole_range(defect_suite) -> None:
    suite, _ = defect_suite
    truncated = suite["truncated_output"].truth
    assert truncated.covered_ranges_ms == ()
    assert file_sha256(str(suite["truncated_output"].path)) == suite["truncated_output"].sha256
    # Nothing covered: no window is CHECKED for any family, so no PASS can be drawn from it.
    from microdrama.testing.fakes.media_review import coverage_windows

    windows = coverage_windows(uuid.UUID(int=81), CheckFamily.ASR, 5_000, ())
    assert {w.status for w in windows} == {CoverageStatus.UNSAMPLED}
