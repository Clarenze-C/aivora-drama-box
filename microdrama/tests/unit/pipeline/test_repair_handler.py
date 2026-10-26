"""The ``qa.plan_repairs`` handler contract (build-review F02).

The handler must consume ``RepairPlanOutcome`` (the plan id is nested at
``outcome.plan.plan_id``), route a Gate 2 ``human_feedback`` job to the feedback
planner with the approval event as its causation id, and turn a typed
``NoRepairableInput`` into an explicit no-work success instead of an escaped
exception. These tests pin the wiring with module-boundary substitutes — the
composed UI → job → changed-media path is covered by the repair wave's
integration tests.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from microdrama.contracts.jobs import EpisodeStepInput
from microdrama.pipeline.handlers import build_handlers
from microdrama.qa.repairs import NoRepairableInput, RepairPlanOutcome


class _RepairsBoundary:
    """Records planner selection; returns the real nested outcome shape."""

    def __init__(self, *, outcome=None, raise_on_findings=None, raise_on_feedback=None):
        self.calls: list[str] = []
        self.executed: list = []
        self._outcome = outcome
        self._raise_on_findings = raise_on_findings
        self._raise_on_feedback = raise_on_feedback

    def plan_from_findings(self, episode_id):
        self.calls.append(f"findings:{episode_id}")
        if self._raise_on_findings is not None:
            raise self._raise_on_findings
        return self._outcome

    def plan_from_feedback(self, episode_id, approval_event_id):
        self.calls.append(f"feedback:{episode_id}:{approval_event_id}")
        if self._raise_on_feedback is not None:
            raise self._raise_on_feedback
        return self._outcome

    def execute_plan(self, plan_id):
        self.executed.append(plan_id)
        return SimpleNamespace(steps=[object()], returns_to_gate2=True, status="COMPLETED")


def _world(repairs):
    return SimpleNamespace(db=None, qa_repairs=repairs, analytics=None)


def _ctx(episode_id, *, trigger, causation_id=None):
    return SimpleNamespace(
        payload=EpisodeStepInput(episode_id=episode_id, trigger=trigger),
        job=SimpleNamespace(causation_id=causation_id),
    )


def test_findings_trigger_uses_findings_planner_and_executes_nested_plan():
    episode_id = uuid4()
    plan_id = uuid4()
    outcome = RepairPlanOutcome.model_construct(
        plan=SimpleNamespace(plan_id=plan_id, trigger=SimpleNamespace(value="QA_FINDING")),
        status="PLANNED",
        replayed=False,
    )
    repairs = _RepairsBoundary(outcome=outcome)
    handler = build_handlers(_world(repairs))["qa.plan_repairs"]
    result = handler(_ctx(episode_id, trigger="scheduled"))
    assert repairs.calls == [f"findings:{episode_id}"]
    assert repairs.executed == [plan_id]  # the NESTED id, never outcome.plan_id
    assert result.result["plan_id"] == str(plan_id)
    assert result.result["trigger"] == "QA_FINDING"


def test_human_feedback_trigger_routes_to_the_feedback_planner_with_the_approval():
    episode_id = uuid4()
    approval_id = uuid4()
    plan_id = uuid4()
    outcome = RepairPlanOutcome.model_construct(
        plan=SimpleNamespace(plan_id=plan_id, trigger=SimpleNamespace(value="HUMAN_FEEDBACK")),
        status="PLANNED",
        replayed=False,
    )
    repairs = _RepairsBoundary(outcome=outcome)
    handler = build_handlers(_world(repairs))["qa.plan_repairs"]
    result = handler(_ctx(episode_id, trigger="human_feedback", causation_id=approval_id))
    assert repairs.calls == [f"feedback:{episode_id}:{approval_id}"]
    assert repairs.executed == [plan_id]
    assert result.result["plan_id"] == str(plan_id)


def test_human_feedback_without_causation_fails_typed():
    handler = build_handlers(_world(_RepairsBoundary()))["qa.plan_repairs"]
    result = handler(_ctx(uuid4(), trigger="human_feedback", causation_id=None))
    assert result.error_code == "repair_missing_approval"


def test_no_repairable_input_is_an_explicit_no_work_success():
    for trigger, causation in (("scheduled", None), ("human_feedback", uuid4())):
        boundary = _RepairsBoundary(raise_on_findings=NoRepairableInput("none"))
        if trigger == "human_feedback":
            boundary = _RepairsBoundary(raise_on_feedback=NoRepairableInput("no items"))
        handler = build_handlers(_world(boundary))["qa.plan_repairs"]
        result = handler(_ctx(uuid4(), trigger=trigger, causation_id=causation))
        assert result.result["plan_id"] is None
        assert result.result["reason"] == "nothing_repairable"
        assert boundary.executed == []
