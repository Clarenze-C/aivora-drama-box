"""Shared builders for the story tests (T010). Plain helpers; fixtures live in conftest.

Everything runs against real PostgreSQL (root ``db`` fixture) with the T007 fakes. The
happy-path writer draft is original Thai dialogue for the contracts' chicken-rice family
drama scope (speakers fon/lek/nok, two locations, in-band runtime), scripted onto the fake
writer role; the fake critic role is scripted to pass. Tests override either with
``script_token``/``script_role`` or scenario queues for the failure paths.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.enums import RuntimeRole
from microdrama.contracts.examples import season_scope
from microdrama.contracts.hashing import canonical_hash
from microdrama.persistence import Database, insert_row, jsonb
from microdrama.story import (
    SeasonBible,
    StoryService,
    build_story_service,
    estimate_line_ms,
    estimated_runtime_ms,
    parse_writer_draft,
)
from microdrama.testing.fakes import FakeClock, FakeLLMProvider, SequentialIds
from microdrama.testing.seed import seed_episode

T0 = datetime(2026, 10, 21, tzinfo=UTC)

# Original Thai dialogue (episode 1). (thai, english, speaker, terms, staging-controls)
_LINES_SCENE_1: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [
    (
        "ลุงเล็ก ร้านข้าวมันไก่ของแม่เปิดได้อีกไหมคะ",
        "Uncle Lek, can Mother's chicken-rice stall open again?",
        "fon",
        [("NAME", "ลุงเล็ก")],
        [],
    ),
    (
        "เปิดได้ แต่ต้องรีบเก็บรายได้ก่อนสิ้นเดือนนะหนู",
        "We can, but we must gather income before the month ends.",
        "lek",
        [],
        [],
    ),
    (
        "ทำไมลุงถึงเคร่งเครียดแบบนี้คะ",
        "Why are you so tense, Uncle?",
        "fon",
        [],
        [],
    ),
    (
        "เรื่องมันยาว กินข้าวก่อนแล้วค่อยคุยกัน",
        "It is a long story; eat first, then we talk.",
        "lek",
        [],
        [],
    ),
    ("หนูอยากรู้ตอนนี้เลยค่ะ", "I want to know right now.", "fon", [], []),
    (
        "งั้นเจอหลังร้านตอนหกโมงเย็นนะ",
        "Then meet me behind the shop at six in the evening.",
        "lek",
        [("DATE_TIME", "หกโมงเย็น")],
        [],
    ),
    (
        "สวัสดีครับ คุณฝนเป็นลูกสาวเจ้าของร้านใช่ไหมครับ",
        "Hello. You are Fon, the owner's daughter, right?",
        "nok",
        [],
        [],
    ),
    ("ขอโทษค่ะ ใครบอกคะ", "Excuse me, who told you?", "fon", [], []),
    ("ผมมาจากบริษัทให้กู้ยืมครับ", "I come from the lending company.", "nok", [], []),
    (
        "แม่หนูไม่เคยพูดถึงเรื่องหนี้เลยสักคำ",
        "My mother never once mentioned any debt.",
        "fon",
        [("NEGATION", "ไม่เคย")],
        [],
    ),
    (
        "หนี้ห้าหมื่นบาทค้างชำระมาสามเดือนแล้วครับ",
        "A fifty-thousand-baht debt, unpaid for three months.",
        "nok",
        [("MONEY", "ห้าหมื่นบาท"), ("NUMBER", "สามเดือน")],
        ["CAMERA_MOTION", "SEED"],  # camera motion is unsupported -> staged simplification
    ),
    (
        "นกครับ ให้เวลาพวกเราหน่อยได้ไหม",
        "Nok, could you give us some time?",
        "lek",
        [],
        [],
    ),
]
_LINES_SCENE_2: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [
    (
        "ลุงเล็ก หนี้ห้าหมื่นบาทนี่คืออะไรคะ",
        "Uncle Lek, what is this fifty-thousand-baht debt?",
        "fon",
        [("MONEY", "ห้าหมื่นบาท")],
        [],
    ),
    (
        "แม่หนูไม่อยากให้หนูรู้",
        "Your mother didn't want you to know.",
        "lek",
        [("NEGATION", "ไม่อยาก")],
        [],
    ),
    (
        "ทำไมแม่ต้องปิดบังหนูด้วยคะ",
        "Why did Mother hide it from me?",
        "fon",
        [],
        [],
    ),
    (
        "เพราะแม่กลัวว่าหนูจะเลิกเรียนกลางคัน",
        "Because she feared you would quit your studies halfway.",
        "lek",
        [],
        [],
    ),
    ("ตอนนี้หนูเรียนจบแล้ว หนูช่วยได้ค่ะ", "I have graduated now; I can help.", "fon", [], []),
    (
        "เงินที่มีอยู่ไม่พอจ่ายดอกเบี้ยเดือนหน้า",
        "The money we have is not enough for next month's interest.",
        "lek",
        [("NEGATION", "ไม่พอ")],
        [],
    ),
    (
        "ถ้าหนูขายมอเตอร์ไซค์ของหนูล่ะคะ",
        "What if I sell my motorcycle?",
        "fon",
        [],
        [],
    ),
    ("ยังไม่พอหรอกหนู", "That still would not be enough, child.", "lek", [], []),
    ("ภายในวันศุกร์นะครับ", "By Friday, please.", "nok", [("DATE_TIME", "วันศุกร์")], []),
    (
        "หนูจะหาสามหมื่นบาทที่เหลือให้ได้เองค่ะ",
        "I will find the remaining thirty thousand baht myself.",
        "fon",
        [("MONEY", "สามหมื่นบาท")],
        [],
    ),
]

# The reveal the approved arc schedules for episode 2 (must NOT appear in episode 1).
EP2_REVEAL_TH = "ลุงเล็กเป็นคนค้ำประกันให้แม่"


def _line_payloads(rows: list[tuple[str, str, str, list[tuple[str, str]], list[str]]]):
    for text_th, text_en, speaker, terms, controls in rows:
        yield {
            "speaker_character_id": speaker,
            "text_th": text_th,
            "text_en": text_en,
            "critical_terms": [{"kind": kind, "value_th": value} for kind, value in terms],
            **({"controls": controls} if controls else {}),
        }


def canonical_writer_output() -> dict[str, Any]:
    """The happy-path episode-1 draft as raw model output (data, not instructions)."""
    return {
        "scenes": [
            {
                "location_id": "stall",
                "summary": "Fon reopens the stall; the collector Nok arrives.",
                "staging": {"controls": ["STYLE_REFERENCE"], "sound": "morning market"},
                "lines": list(_line_payloads(_LINES_SCENE_1)),
            },
            {
                "location_id": "shophouse-room",
                "summary": "Fon confronts Uncle Lek about the hidden debt.",
                "staging": {"sound": "quiet room tone"},
                "lines": list(_line_payloads(_LINES_SCENE_2)),
            },
        ]
    }


def canonical_draft():
    return parse_writer_draft(canonical_writer_output())


# The fixture must stay inside the approved 180-300 s runtime band (loud fixture guard).
assert 180_000 <= estimated_runtime_ms(canonical_draft()) <= 300_000, (
    "canonical draft runtime drifted out of the approved band"
)
for text_th, _en, _sp, terms, _c in [*_LINES_SCENE_1, *_LINES_SCENE_2]:
    for _kind, value in terms:
        assert value in text_th, f"fixture critical term {value!r} missing from its Thai line"


def thai_reveal_scope() -> Any:
    """The example scope with the episode-2 reveal stated in Thai (matchable in dialogue)."""
    scope = season_scope()
    beat2 = scope.arc[1]
    return scope.model_copy(
        update={
            "arc": [
                scope.arc[0],
                beat2.model_copy(update={"planned_reveals": [EP2_REVEAL_TH]}),
            ]
        }
    )


class World:
    """One story service wired to the real database and the T007 fakes."""

    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.clock = FakeClock(T0)
        self.ids = SequentialIds("story-tests")
        self.budget = BudgetService(db, self.clock, SequentialIds("story-budget"), settings)
        self.llm = FakeLLMProvider(clock=self.clock, ids=SequentialIds("story-llm"))
        self.service: StoryService = build_story_service(
            db,
            self.clock,
            self.ids,
            settings,
            budget=self.budget,
            llm=self.llm,
        )
        # Happy-path scripting: the writer produces the canonical draft; the critic passes.
        self.llm.script_role(RuntimeRole.STORY_ARCHITECT, canonical_writer_output())
        self.llm.script_role(RuntimeRole.CRITIC, {"passed": True, "findings": []})

    # --- seeds -----------------------------------------------------------------------

    def season(
        self,
        *,
        approved: bool = True,
        scope: Any = None,
        season_scope_hash: str | None = None,
    ) -> tuple[uuid.UUID, Any]:
        """A season with one proposal (APPROVED with a bound Gate 1 approval, or PROPOSED).

        ``season_scope_hash`` deliberately desynchronises the season row's bound hash from
        the proposal's own scope hash (insert-time only; the DB forbids rebinding later).
        """
        season_id = uuid.uuid4()
        use_scope = (scope or season_scope()).model_copy(
            update={"season_id": season_id, "scope_version": 1}
        )
        scope_hash = canonical_hash(use_scope)
        bound_hash = season_scope_hash if season_scope_hash is not None else scope_hash
        with self.db.transaction() as tx:
            from microdrama.testing.seed import seed_gate1_approval

            approval_id = seed_gate1_approval(tx, season_id, bound_hash) if approved else None
            insert_row(
                tx,
                "seasons",
                {
                    "id": season_id,
                    "state": "SEASON_APPROVED" if approved else "PROPOSED",
                    "title_th": use_scope.title_th,
                    "title_en": use_scope.title_en,
                    "approved_scope_version": 1 if approved else None,
                    "approved_scope_hash": bound_hash if approved else None,
                    "approval_event_id": approval_id,
                    "approved_at": self.clock.now() if approved else None,
                },
                returning="id",
            )
            insert_row(
                tx,
                "season_proposals",
                {
                    "id": uuid.uuid4(),
                    "season_id": season_id,
                    "scope_version": 1,
                    "scope": jsonb(use_scope),
                    "scope_hash": scope_hash,
                    "status": "APPROVED" if approved else "PROPOSED",
                },
                returning="id",
            )
        return season_id, use_scope

    def add_proposal(self, season_id: uuid.UUID, scope: Any, *, version: int, status: str) -> None:
        """An extra proposal version (e.g. later trend research producing scope v2)."""
        use_scope = scope.model_copy(update={"season_id": season_id, "scope_version": version})
        with self.db.transaction() as tx:
            insert_row(
                tx,
                "season_proposals",
                {
                    "id": uuid.uuid4(),
                    "season_id": season_id,
                    "scope_version": version,
                    "scope": jsonb(use_scope),
                    "scope_hash": canonical_hash(use_scope),
                    "status": status,
                },
                returning="id",
            )

    def episode(
        self,
        season_id: uuid.UUID,
        scope: Any,
        *,
        number: int = 1,
        state: str = "PLANNED",
        identity_lock_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        with self.db.transaction() as tx:
            episode_id = seed_episode(tx, season_id, number=number, state=state)
            if canonical_hash(scope) is not None:
                tx.execute(
                    "UPDATE episodes SET approved_scope_hash = %s, identity_lock_id = %s "
                    "WHERE id = %s",
                    (canonical_hash(scope), identity_lock_id, episode_id),
                )
        return episode_id

    def compiled(self, *, scope: Any = None) -> tuple[uuid.UUID, uuid.UUID, SeasonBible, Any]:
        season_id, use_scope = self.season(scope=scope)
        result = self.service.compile_season(season_id)
        return season_id, result.bible.season_id, result.bible, use_scope

    # --- reads -----------------------------------------------------------------------

    def row(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        with self.db.transaction(readonly=True) as tx:
            return tx.fetchone(sql, params)

    def rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self.db.transaction(readonly=True) as tx:
            return tx.fetchall(sql, params)

    def count(self, sql: str, params: tuple = ()) -> int:
        with self.db.transaction(readonly=True) as tx:
            return int(tx.fetchval(sql, params) or 0)

    def events(self, aggregate_id: uuid.UUID, event_type: str) -> list[dict[str, Any]]:
        rows = self.rows(
            "SELECT payload FROM domain_events WHERE aggregate_id = %s AND event_type = %s "
            "ORDER BY sequence",
            (aggregate_id, event_type),
        )
        return [dict(row["payload"]) for row in rows]

    def generate_calls(self) -> int:
        return len(self.llm.calls)

    def episode_charges(self, episode_id: uuid.UUID) -> list[dict[str, Any]]:
        return self.rows(
            "SELECT * FROM charges WHERE episode_id = %s ORDER BY created_at, id",
            (episode_id,),
        )

    def committed(self, episode_id: uuid.UUID) -> int:
        row = self.row(
            "SELECT reserved_outstanding_micro_usd, accrued_micro_usd, settled_micro_usd "
            "FROM budget_accounts WHERE scope_kind = 'EPISODE' AND episode_id = %s",
            (episode_id,),
        )
        assert row is not None
        return (
            row["reserved_outstanding_micro_usd"]
            + row["accrued_micro_usd"]
            + row["settled_micro_usd"]
        )


__all__ = [
    "EP2_REVEAL_TH",
    "T0",
    "World",
    "canonical_draft",
    "canonical_writer_output",
    "estimate_line_ms",
    "thai_reveal_scope",
]
