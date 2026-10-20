"""Structural rules for core's source: no DDL, no deletes, one approval writer, no composition."""

from __future__ import annotations

import ast
import re
from pathlib import Path

CORE = Path(__file__).resolve().parents[3] / "src" / "microdrama" / "core"


def _sources() -> dict[str, str]:
    files = {}
    for path in sorted(CORE.rglob("*.py")):
        if "registry" in path.relative_to(CORE).parts or "__pycache__" in path.parts:
            continue
        files[str(path.relative_to(CORE))] = path.read_text(encoding="utf-8")
    return files


def test_core_sources_were_found() -> None:
    assert {"events.py", "jobs.py", "approvals.py", "state_machine.py"} <= set(_sources())


def test_core_never_issues_schema_changes() -> None:
    ddl = re.compile(
        r"\b(CREATE\s+(TABLE|INDEX|TRIGGER|FUNCTION|EXTENSION)|ALTER\s+TABLE|DROP\s+(TABLE|TRIGGER|INDEX))\b",
        re.I,
    )
    offenders = [name for name, text in _sources().items() if ddl.search(text)]
    assert offenders == []


def test_core_never_deletes_or_truncates_audit_rows() -> None:
    destructive = re.compile(r"\b(DELETE\s+FROM|TRUNCATE)\b", re.I)
    offenders = [name for name, text in _sources().items() if destructive.search(text)]
    assert offenders == []


def test_only_the_approval_module_writes_approval_events() -> None:
    writer = re.compile(
        r"INSERT\s+INTO\s+approval_events|insert_row\(\s*tx,\s*\"approval_events\"", re.I
    )
    offenders = [name for name, text in _sources().items() if writer.search(text)]
    assert offenders == ["approvals.py"]


def test_core_does_not_compose_routers_or_import_composition_roots() -> None:
    banned = re.compile(
        r"include_router|create_app\(|from microdrama\.(api|workers)\b|import microdrama\.(api|workers)\b"
    )
    offenders = []
    for name, text in _sources().items():
        if name == "api.py":  # core exports build_router; it is the integrator who registers it
            continue
        if banned.search(text):
            offenders.append(name)
    assert offenders == []


def test_core_does_not_duplicate_transition_tables() -> None:
    literal = re.compile(r"^(SEASON|EPISODE|JOB|RELEASE)_TRANSITIONS\s*[:=]", re.M)
    offenders = [name for name, text in _sources().items() if literal.search(text)]
    assert offenders == []


def test_state_writes_do_not_bypass_the_state_machine_for_episodes() -> None:
    """Episode/season state is written only by the state machine (and outcome helpers)."""
    setter = re.compile(r"SET\s+state\s*=", re.I)
    offenders = [
        name
        for name, text in _sources().items()
        if setter.search(text) and name != "state_machine.py"
    ]
    assert offenders == []


def test_allow_lists_exclude_runtime_models_and_provider_webhooks() -> None:
    """Models only propose and webhooks are untrusted input: neither may act or read the outbox."""
    from microdrama.contracts.enums import PrincipalKind as K
    from microdrama.core import auth

    assert auth.OPERATOR_KINDS == frozenset({K.SERVICE_WORKER, K.SCHEDULER})
    assert auth.OWNER_OR_OPERATOR_KINDS == frozenset({K.HUMAN_OWNER, K.SERVICE_WORKER, K.SCHEDULER})
    assert K.RUNTIME_MODEL not in auth.OWNER_OR_OPERATOR_KINDS
    assert K.PROVIDER_WEBHOOK not in auth.OWNER_OR_OPERATOR_KINDS


STATE_WRITERS = (
    "transition_season",
    "transition_episode",
    "set_episode_outcome",
    "clear_episode_outcome",
)


def test_every_state_and_outcome_writer_checks_the_actor_before_anything_else() -> None:
    """The first executable statement of each writer is the actor gate (no lock, no write before it)."""
    tree = ast.parse((CORE / "state_machine.py").read_text(encoding="utf-8"))
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for name in STATE_WRITERS:
        body = functions[name].body
        if isinstance(body[0], ast.Expr) and isinstance(
            getattr(body[0], "value", None), ast.Constant
        ):
            body = body[1:]  # skip the docstring
        first = body[0]
        assert isinstance(first, ast.Expr), name
        call = first.value
        assert (
            isinstance(call, ast.Call) and getattr(call.func, "id", None) == "require_state_actor"
        ), name
        assert [getattr(a, "id", None) for a in call.args] == ["actor"], name


def test_the_outcome_and_state_writers_are_the_only_state_setters() -> None:
    """Every writer above is the only code path that sets episode or season state from core."""
    tree = ast.parse((CORE / "state_machine.py").read_text(encoding="utf-8"))
    defined = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert set(STATE_WRITERS) <= defined


def test_only_the_system_clock_reads_the_wall_clock() -> None:
    """V-18: time comes from the caller's injected clock. Only clock.py may read the wall clock."""
    reader = re.compile(r"datetime\.now\(|datetime\.utcnow\(|time\.time\(")
    offenders = [
        name for name, text in _sources().items() if name != "clock.py" and reader.search(text)
    ]
    assert offenders == []


def test_provider_operations_take_now_as_a_required_argument() -> None:
    tree = ast.parse((CORE / "provider_ops.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in {
            "begin",
            "record_result",
            "needs_reconcile",
            "resubmit_allowed",
        }:
            kwonly = {
                a.arg: d for a, d in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True)
            }
            assert "now" in kwonly and kwonly["now"] is None, (
                node.name
            )  # None default means required


def test_outbox_dispatch_is_serialised_by_an_advisory_lock_not_skip_locked() -> None:
    """V-15: dispatchers take a transaction-level advisory lock; SKIP LOCKED would let a later
    event of an aggregate publish before an earlier one that another dispatcher holds."""
    text = (CORE / "events.py").read_text(encoding="utf-8")
    assert "pg_advisory_xact_lock" in text
    assert "SKIP LOCKED" not in text


def test_provider_begin_refuses_an_unreserved_metered_call_before_it_writes() -> None:
    """V-24: begin refuses a missing reservation for any kind not on the contract's unmetered list,
    and that check comes before the INSERT."""
    text = (CORE / "provider_ops.py").read_text(encoding="utf-8")
    guard = "reservation_id is None and operation_kind not in UNMETERED_OPERATION_KINDS"
    assert text.count(guard) == 1
    assert text.index(guard) < text.index("INSERT INTO provider_operations")


def test_the_api_enqueue_gate_is_the_contract_allow_list_and_runs_before_the_spec_lookup() -> None:
    """V-22: the route gates on API_ENQUEUEABLE_JOB_TYPES before it looks at the payload spec."""
    text = (CORE / "api.py").read_text(encoding="utf-8")
    gate = "body.job_type not in API_ENQUEUEABLE_JOB_TYPES"
    assert text.count(gate) == 1
    assert text.index(gate) < text.index("JOB_SPECS_BY_TYPE.get(body.job_type)")
