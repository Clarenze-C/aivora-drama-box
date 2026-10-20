"""Structural rules for the review module: route table, decision boundaries and offline-only code.

These tests read the source and the router factory; they need no database.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from fastapi import APIRouter

from microdrama.contracts.routes import MODULE_ROUTE_PREFIXES, ROUTES
from microdrama.contracts.season import ApprovalCommand
from microdrama.review import build_router

REVIEW = Path(__file__).resolve().parents[3] / "src" / "microdrama" / "review"
TEMPLATES = REVIEW / "templates"


def _sources() -> dict[str, str]:
    return {
        str(path.relative_to(REVIEW)): path.read_text(encoding="utf-8")
        for path in sorted(REVIEW.rglob("*.py"))
        if "__pycache__" not in path.parts
    }


def _no_auth(request):  # pragma: no cover - never called: the factory is only inspected
    return None


def _factory_router() -> APIRouter:
    # The factory does not touch its collaborators until a request arrives, so None is enough here.
    return build_router(None, human_session=_no_auth, auth=None)  # type: ignore[arg-type]


def test_every_review_route_in_the_contract_table_is_implemented() -> None:
    surface = {
        (method, route.path)
        for route in _factory_router().routes
        for method in getattr(route, "methods", set())
    }
    for spec in ROUTES:
        if spec.owner_module != "review":
            continue
        assert (spec.method, spec.path) in surface, spec.path


def test_the_review_router_adds_only_the_ui_and_auth_pages_beyond_the_table() -> None:
    contract = {(s.method, s.path) for s in ROUTES if s.owner_module == "review"}
    allowed_prefixes = MODULE_ROUTE_PREFIXES["review"]
    for route in _factory_router().routes:
        for method in getattr(route, "methods", set()):
            key = (method, route.path)
            if key in contract:
                continue
            assert route.path.startswith(allowed_prefixes), key


def test_review_reads_return_the_contract_models_and_decisions_return_json_commands() -> None:
    """GETs declare the contract view; decisions build their JSON body with CommandAccepted."""
    by_key = {(s.method, s.path): s for s in ROUTES if s.owner_module == "review"}
    checked = 0
    for route in _factory_router().routes:
        for method in getattr(route, "methods", set()):
            spec = by_key.get((method, route.path))
            if spec is None:
                continue
            checked += 1
            if method == "GET":
                if spec.response_model is not None and spec.path == "/seasons/proposals":
                    assert route.response_model == list[spec.response_model], spec.path
                else:
                    assert route.response_model is spec.response_model, spec.path
            else:
                assert route.response_model is None, spec.path  # returns a JSONResponse
                assert spec.request_model is ApprovalCommand, spec.path
    assert checked == 5


def test_review_never_registers_routers_or_imports_composition_roots() -> None:
    banned = re.compile(
        r"include_router|create_app\(|from microdrama\.(api|workers)\b|import microdrama\.(api|workers)\b"
    )
    offenders = [name for name, text in _sources().items() if banned.search(text)]
    assert offenders == []


def test_approval_events_are_written_only_through_the_core_writer() -> None:
    writer = re.compile(
        r"INSERT\s+INTO\s+approval_events|insert_row\(\s*tx,\s*\"approval_events\"", re.I
    )
    assert [name for name, text in _sources().items() if writer.search(text)] == []
    tree = ast.parse((REVIEW / "service.py").read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "record_approval_event"
    ]
    assert len(calls) == 2, "exactly one Gate 1 and one Gate 2 decision path record an approval"


def test_review_never_sets_season_or_episode_state_directly() -> None:
    setter = re.compile(r"SET\s+state\s*=", re.I)
    assert [name for name, text in _sources().items() if setter.search(text)] == []


def test_review_issues_no_schema_changes_and_no_deletes() -> None:
    ddl = re.compile(
        r"\b(CREATE\s+(TABLE|INDEX|TRIGGER|FUNCTION)|ALTER\s+TABLE|DROP\s+TABLE|DELETE\s+FROM|TRUNCATE)\b",
        re.I,
    )
    assert [name for name, text in _sources().items() if ddl.search(text)] == []


def test_every_decision_entry_point_checks_the_human_owner_first() -> None:
    tree = ast.parse((REVIEW / "service.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in ("decide_season", "decide_episode"):
            first = node.body[0]
            assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Call), node.name
            assert getattr(first.value.func, "id", None) == "require_human_owner", node.name


def test_no_timers_schedulers_or_background_approvals() -> None:
    banned_modules = {"threading", "asyncio", "sched", "schedule", "apscheduler", "time", "signal"}
    for name, text in _sources().items():
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = {node.module.split(".")[0]}
            else:
                continue
            assert not (names & banned_modules), (name, names & banned_modules)


def test_review_makes_no_network_or_provider_calls() -> None:
    banned = {
        "httpx",
        "requests",
        "urllib",
        "socket",
        "aiohttp",
        "http",
        "boto3",
        "subprocess",
        "smtplib",
        "ftplib",
    }
    for name, text in _sources().items():
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = {node.module.split(".")[0]}
            else:
                continue
            assert not (names & banned), (name, names & banned)


def test_review_python_contains_no_float_literals() -> None:
    """Money is integer micro-USD and time is integer milliseconds (COMPATIBILITY.md)."""
    for name, text in _sources().items():
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                raise AssertionError(f"float literal {node.value!r} in {name}")


def test_review_does_not_define_its_own_transition_tables() -> None:
    literal = re.compile(r"^(SEASON|EPISODE|RELEASE)_TRANSITIONS\s*[:=]", re.M)
    assert [name for name, text in _sources().items() if literal.search(text)] == []


def test_the_page_templates_are_present() -> None:
    names = {path.name for path in TEMPLATES.glob("*.html")}
    assert {"base.html", "login.html", "proposals.html", "season.html", "episode.html"} <= names
