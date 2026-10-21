"""Pass A blindness tests (T018, AT-06): the observer provably cannot see the answers.

The spy inspects the ACTUAL outgoing payload handed to the observer seam (and the
serialized ``ObservationRequest`` a live provider would receive) and asserts the
absence of every intended answer: script lines, translations, critical terms and
canon facts. The request identity is derived without the script, so two different
scripts yield the identical request — and caller-supplied questions that quote
intended content are refused typed before anything is dispatched.
"""

from __future__ import annotations

import json
import uuid

import pytest
from qa_support import QAWorld
from test_observation_support import (
    CANON_STATEMENT,
    SpyObserver,
    observation_service,
    seed_canon,
)

from microdrama.contracts.errors import PolicyDenied
from microdrama.contracts.examples import script as example_script
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.qa import MediaUnderReview, NeutralQuestion
from microdrama.contracts.season import Script
from microdrama.persistence import insert_row, jsonb
from microdrama.qa.observation import (
    build_observation_request,
    default_neutral_questions,
    intended_content_tokens,
    observation_request_id,
    request_fingerprint,
    request_identity,
    screen_for_intended_content,
)


def _current_script(qa_world: QAWorld, episode_id: uuid.UUID) -> Script:
    row = qa_world.row(
        "SELECT body FROM scripts WHERE episode_id = %s AND status = 'CURRENT'", (episode_id,)
    )
    assert row is not None
    return Script.model_validate(row["body"])


def _banned(qa_world: QAWorld, episode_id: uuid.UUID) -> list[str]:
    return intended_content_tokens(_current_script(qa_world, episode_id), [CANON_STATEMENT])


def _norm(text: str) -> str:
    return "".join(text.split())


def _leaking(text: str) -> list[NeutralQuestion]:
    return [NeutralQuestion(question_id="q-evil", text=text)]


def test_spy_observer_payload_carries_no_intended_answers(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    seed_canon(qa_world, episode_id, reveals=(CANON_STATEMENT,))
    spy = SpyObserver(qa_world.observer())
    observation_service(qa_world, observer=spy).observe_media(episode_id, asset_id=asset_id)

    assert spy.calls == 1
    payload_dump = _norm(json.dumps(spy.payloads, default=str))
    for token in _banned(qa_world, episode_id):
        assert _norm(token) not in payload_dump, f"leak in observer payload: {token[:40]}"


def test_built_request_and_frozen_report_serialize_without_script_content(
    defect_suite, qa_world: QAWorld
) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    seed_canon(qa_world, episode_id, reveals=(CANON_STATEMENT,))
    frozen = observation_service(qa_world).observe_media(episode_id, asset_id=asset_id)
    request_dump = _norm(json.dumps(frozen.request.model_dump(mode="json"), default=str))
    report_dump = _norm(json.dumps(frozen.report.model_dump(mode="json"), default=str))
    for token in _banned(qa_world, episode_id):
        assert _norm(token) not in request_dump, f"leak in request payload: {token[:40]}"
        assert _norm(token) not in report_dump, f"leak in frozen report: {token[:40]}"


def test_request_identity_is_independent_of_the_script(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    service = observation_service(qa_world)
    first = service.observe_media(episode_id, asset_id=asset_id)
    assert not first.replayed

    # Swap in a materially different CURRENT script (same episode, same media).
    current = _current_script(qa_world, episode_id).model_dump(mode="json")
    current["version"] = 2
    current["scenes"] = [
        {**scene, "lines": [{**line, "text_th": "บทพูดที่เปลี่ยนไปโดยสิ้นเชิง"} for line in scene["lines"]]}
        for scene in current["scenes"]
    ]  # fmt: skip
    with qa_world.db.transaction() as tx:
        tx.execute(
            "UPDATE scripts SET status = 'SUPERSEDED' WHERE episode_id = %s AND status = 'CURRENT'",
            (episode_id,),
        )
        insert_row(
            tx,
            "scripts",
            {
                "id": uuid.uuid4(),
                "episode_id": episode_id,
                "version": 2,
                "canon_version": 1,
                "body": jsonb(current),
                "body_hash": canonical_hash(current),
                "status": "CURRENT",
            },
        )

    second = service.observe_media(episode_id, asset_id=asset_id)
    # Same media + same questions: the identical Pass A request — now a replay.
    assert second.replayed
    assert second.request.request_id == first.request.request_id
    assert request_identity(second.request) == request_identity(first.request)


def test_request_id_derivation_takes_no_script_argument() -> None:
    episode = uuid.UUID(int = 7)  # fmt: skip
    fingerprint = request_fingerprint(default_neutral_questions(), "th-TH")
    key = observation_request_id(episode, "a" * 16, fingerprint)
    assert key == observation_request_id(episode, "a" * 16, fingerprint)
    # different media or questions mint a different request; the script cannot, by type
    assert key != observation_request_id(episode, "b" * 16, fingerprint)
    assert len(fingerprint) == 64
    other_script_tokens = intended_content_tokens(example_script())
    assert not any(token in str(key) for token in other_script_tokens)


def test_question_quoting_a_script_line_is_refused(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    line = _current_script(qa_world, episode_id).scenes[0].lines[0].text_th
    with pytest.raises(PolicyDenied, match="quotes intended content"):
        observation_service(qa_world).observe_media(
            episode_id, asset_id=asset_id, questions=_leaking(f"Please confirm they say: {line}")
        )


def test_question_quoting_a_critical_term_is_refused(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    term = _current_script(qa_world, episode_id).scenes[0].lines[0].critical_terms[0].value_th
    with pytest.raises(PolicyDenied):
        observation_service(qa_world).observe_media(
            episode_id, asset_id=asset_id, questions=_leaking(f"Listen for {term}")
        )


def test_question_quoting_a_canon_fact_is_refused(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    seed_canon(qa_world, episode_id, reveals=(CANON_STATEMENT,))
    with pytest.raises(PolicyDenied):
        observation_service(qa_world).observe_media(
            episode_id, asset_id=asset_id, questions=_leaking(f"Is it true that {CANON_STATEMENT}")
        )


def test_default_questions_pass_the_screen(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    script = _current_script(qa_world, episode_id)
    # the neutral defaults must clear the same screen that refuses leaking questions
    screen_for_intended_content(
        default_neutral_questions(), script=script, canon_statements=[CANON_STATEMENT]
    )
    request = build_observation_request(
        episode_id=episode_id,
        media=[
            MediaUnderReview(asset_id=asset_id, asset_sha256="0" * 64, duration_ms=5_000)
        ],
        questions=default_neutral_questions(),
        request_id=uuid.uuid4(),
    )  # fmt: skip
    assert len(request.questions) == 4
    assert request.reservation_id is None
