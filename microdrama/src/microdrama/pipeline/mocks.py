"""Clearly-labeled mock request fixtures for the offline pipeline (T029).

Only the request shapes that have no durable row of their own: the W01 research
request (its concept drafts and comparator corpus are pilot configuration, not
ledger state). Everything else the pipeline reads back from the database.
"""

from __future__ import annotations

from uuid import uuid4

from microdrama.contracts.examples import season_scope
from microdrama.research import (
    ComparatorCorpus,
    ConceptDraft,
    PersonaProfile,
    ResearchRequest,
    ResearchTrigger,
)

MOCK_SOURCES = ("src-thai-drama-1", "src-thai-drama-2")

# Comparator material deliberately unrelated to the candidate concept (the CLEAR
# originality path), mirroring the research lane's canonical fixture.
MOCK_COMPARATOR_SCENE = (
    "A retired detective hunts a kidnapping syndicate through the flooded alleys of old "
    "Bangkok while his former partner covers for him."
)


def mock_research_request(season_id, *, trigger: str = "scheduled") -> ResearchRequest:
    """The W01 pilot request: two original mock concepts over the fake source lane."""
    base = season_scope()
    first = base.model_copy(
        update={
            "title_en": "River of Small Debts",
            "logline": "A young cook must save her aunt's noodle boat before the river rises.",
            "premise": "Original mock fiction about inheritance, pride and slow forgiveness.",
        }
    )
    second = base.model_copy(
        update={
            "title_en": "The Quiet Photographer",
            "logline": "A shy photographer documents a night market's last season.",
            "premise": "Original mock fiction about memory, gentrification and courage.",
        }
    )
    return ResearchRequest(
        trigger=ResearchTrigger.SCHEDULED if trigger == "scheduled" else ResearchTrigger.MANUAL,
        trigger_key=f"research.daily:{season_id}:{uuid4().hex[:8]}",
        source_provider_id="fake-sources",
        allowed_source_ids=list(MOCK_SOURCES),
        query_texts=["thai micro drama family trends"],
        comments=[],
        comparator_corpus=ComparatorCorpus(
            scenes=[MOCK_COMPARATOR_SCENE],
            personas=[PersonaProfile(name="Detective Somchai", traits=["stubborn", "loner"])],
        ),
        candidate_concepts=[
            ConceptDraft(concept_id="concept-a", theme_keys=["thai", "drama"], scope=first),
            ConceptDraft(concept_id="concept-b", theme_keys=["drama"], scope=second),
        ],
    )


__all__ = ["MOCK_SOURCES", "mock_research_request", "script_story_fakes"]

# --- W03 writer/critic scripting (the happy-path episode-1 mock draft) ----------------------
#
# The same fixture dialogue the story lane's tests use (fon/lek/nok stall-debt
# scene): speakers match the compiled characters of the approved ``season_scope``
# and the runtime stays inside the approved band, so the critics' automatic
# checks pass on a draft that exercised every rule rather than bypassing them.

_LINES_SCENE_1: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [
    (
        "ลุงเล็ก ร้านข้าวมันไก่ของแม่เปิดได้อีกไหมคะ",
        "Uncle Lek, can Mother's chicken-rice stall open again?",
        "fon",
        [("NAME", "ลุงเล็ก")],
        [],
    ),
    (
        "เปิดได้ แต่ต้องรีบเก็บรายได้ก่อนสิ้นเดือน",
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
        "สวัสดีครับ คุณฝนลูกสาวเจ้าของร้านใช่ไหมครับ",
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


def _line_payloads(rows):
    for text_th, text_en, speaker, terms, controls in rows:
        yield {
            "speaker_character_id": speaker,
            "text_th": text_th,
            "text_en": text_en,
            "critical_terms": [{"kind": kind, "value_th": value} for kind, value in terms],
            **({"controls": controls} if controls else {}),
        }


def mock_writer_output() -> dict:
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


def script_story_fakes(llm) -> None:
    """Script the fake LLM's writer/critic roles for the mock pipeline path."""
    from microdrama.contracts.enums import RuntimeRole

    llm.script_role(RuntimeRole.STORY_ARCHITECT, mock_writer_output())
    llm.script_role(RuntimeRole.CRITIC, {"passed": True, "findings": []})
