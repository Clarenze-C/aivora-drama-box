"""Image/voice generation fake: submit, reconcile, billing, and partial outputs."""

from __future__ import annotations

import hashlib
import io
import uuid
import wave

import pytest

from microdrama.contracts.cost import ProviderOperation
from microdrama.contracts.enums import ProviderOperationState, ReceiptKind
from microdrama.contracts.errors import NeedsReconciliation, NotFound
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.providers import GenerationProvider, ImageRequest, VoiceRequest
from microdrama.testing.fakes import (
    FakeClock,
    FakeGenerationProvider,
    GenerationScenario,
    SequentialIds,
)
from microdrama.testing.fakes.generation import voice_duration_ms

REQUEST_ID = uuid.UUID(int=21)
RESERVATION = uuid.UUID(int=22)


def _image(token: str = "img-token-1") -> ImageRequest:
    return ImageRequest(
        request_id=REQUEST_ID,
        model_config_ref="fake-image-profile",
        rights_route_id="rights-fixture-route",
        prompt_text="Medium close-up of a fixture character at dusk.",
        width=720,
        height=1280,
        seed=1234,
        client_token=token,
        reservation_id=RESERVATION,
    )


def _voice(token: str = "voice-token-1", text: str = "ลุงเล็ก หนี้ห้าหมื่นบาทนี่คืออะไรคะ") -> VoiceRequest:
    return VoiceRequest(
        request_id=REQUEST_ID,
        model_config_ref="fake-voice-profile",
        rights_route_id="rights-fixture-route",
        voice_id="voice-fon-v1",
        line_id="s1-l1",
        text_th=text,
        client_token=token,
        reservation_id=RESERVATION,
    )


def _op(request: ImageRequest | VoiceRequest) -> ProviderOperation:
    return ProviderOperation(
        operation_id=uuid.UUID(int=31),
        provider="fake-generation",
        operation_kind="generation.submit",
        client_token=request.client_token,
        request_sha256=canonical_hash(request),
        state=ProviderOperationState.PENDING_SUBMIT,
        deadline_at="2026-10-20T01:00:00Z",
    )


def _fake(
    clock: FakeClock, ids: SequentialIds, *steps: GenerationScenario
) -> FakeGenerationProvider:
    return FakeGenerationProvider(clock=clock, ids=ids, scenarios=steps)


def _drive_to_success(fake: FakeGenerationProvider, request: ImageRequest | VoiceRequest):
    op = _op(request)
    fake.submit(op, request)
    fake.status(op)  # RUNNING
    return fake.status(op)  # SUCCEEDED


def test_fake_satisfies_generation_protocol(clock: FakeClock, ids: SequentialIds) -> None:
    assert isinstance(_fake(clock, ids), GenerationProvider)


def test_happy_path_produces_decodable_png_and_wav(clock: FakeClock, ids: SequentialIds) -> None:
    fake = _fake(clock, ids)
    image = _drive_to_success(fake, _image())
    png = fake.fetch_output(image.outputs[0])
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert hashlib.sha256(png).hexdigest() == image.outputs[0].sha256
    assert image.outputs[0].complete is True

    voice = _drive_to_success(fake, _voice())
    wav_bytes = fake.fetch_output(voice.outputs[0])
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
        frames = wav.getnframes()
        rate = wav.getframerate()
    assert round(frames / rate * 1000) == voice_duration_ms(_voice().text_th)


def test_voice_duration_depends_only_on_thai_text_length() -> None:
    assert voice_duration_ms("ค่ะ") == 200  # floor
    assert voice_duration_ms("ก" * 50) == 2_000
    assert voice_duration_ms("ก" * 50) == voice_duration_ms("ข" * 50)


def test_ambiguous_submit_is_reconciled_to_the_same_external_id(
    clock: FakeClock, ids: SequentialIds
) -> None:
    fake = _fake(clock, ids, GenerationScenario.AMBIGUOUS_SUBMIT)
    request = _image("img-ambiguous")
    with pytest.raises(NeedsReconciliation):
        fake.submit(_op(request), request)
    recon = fake.reconcile(_op(request))
    assert recon.state is ProviderOperationState.SUBMITTED
    assert recon.external_id == FakeGenerationProvider.external_id_for("img-ambiguous")
    # Later status calls then succeed for the same job.
    assert fake.status(_op(request)).state is ProviderOperationState.RUNNING


def test_not_accepted_reconciles_to_not_found_which_makes_resubmission_safe(
    clock: FakeClock, ids: SequentialIds
) -> None:
    fake = _fake(clock, ids, GenerationScenario.NOT_ACCEPTED)
    request = _image("img-not-accepted")
    with pytest.raises(NeedsReconciliation):
        fake.submit(_op(request), request)
    recon = fake.reconcile(_op(request))
    assert recon.state is ProviderOperationState.NOT_FOUND
    assert recon.external_id is None
    assert fake.submit(_op(request), request).state is ProviderOperationState.SUBMITTED


def test_duplicate_submit_returns_same_external_id_without_second_charge(
    clock: FakeClock, ids: SequentialIds
) -> None:
    fake = _fake(clock, ids)
    request = _image("img-dup")
    first = fake.submit(_op(request), request)
    second = fake.submit(_op(request), request)
    assert first.external_id == second.external_id
    _drive_to_success(fake, request)
    settled = len(fake.ledger)
    fake.submit(_op(request), request)
    assert len(fake.ledger) == settled == 1


def test_denied_rights_fails_with_error_code_and_is_not_transient(
    clock: FakeClock, ids: SequentialIds
) -> None:
    fake = _fake(clock, ids, GenerationScenario.DENIED_RIGHTS)
    request = _image("img-denied")
    result = fake.submit(_op(request), request)
    assert result.state is ProviderOperationState.FAILED
    assert result.error_code == "RIGHTS_UNCLEARED"
    assert result.transient is False
    assert fake.ledger == []


def test_late_billing_reports_accrual_then_adjustment(clock: FakeClock, ids: SequentialIds) -> None:
    fake = _fake(clock, ids, GenerationScenario.LATE_BILLING)
    request = _image("img-late")
    op = _op(request)
    fake.submit(op, request)
    fake.status(op)
    first = fake.status(op)
    assert [r.kind for r in first.usage] == [ReceiptKind.ACCRUAL]
    second = fake.status(op)
    assert [r.kind for r in second.usage] == [ReceiptKind.ADJUSTMENT]
    assert second.usage[0].amount_micro_usd > 0
    assert len(fake.ledger) == 2
    assert fake.status(op).usage == []  # nothing further is billed


def test_partial_output_is_marked_incomplete_and_does_not_match_its_hash(
    clock: FakeClock, ids: SequentialIds
) -> None:
    fake = _fake(clock, ids, GenerationScenario.PARTIAL_OUTPUT)
    result = _drive_to_success(fake, _image("img-partial"))
    ref = result.outputs[0]
    assert ref.complete is False
    served = fake.fetch_output(ref)
    assert len(served) < ref.size_bytes
    assert hashlib.sha256(served).hexdigest() != ref.sha256


def test_unknown_output_reference_is_not_found(clock: FakeClock, ids: SequentialIds) -> None:
    from microdrama.contracts.cost import OutputRef

    fake = _fake(clock, ids)
    ghost = OutputRef(name="ghost.png", media_type="image/png", provider_ref="fake-output/none",
                      complete=True)  # fmt: skip
    with pytest.raises(NotFound):
        fake.fetch_output(ghost)
