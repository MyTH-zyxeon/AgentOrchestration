import pytest

from src.orchestrator.workflow import (
    StepStatus,
    Workflow,
    WorkflowManager,
    WorkflowStep,
    WorkflowValidationError,
)


def test_runnable_selector_uses_dependencies_not_declaration_order():
    events = []
    workflow = Workflow("parallel")
    child = WorkflowStep(
        "publish",
        lambda: events.append("publish"),
        depends_on=["build"],
    )
    build = WorkflowStep("build", lambda: events.append("build"))
    workflow.add_step(child).add_step(build)

    manager = WorkflowManager()
    manager._workflows[workflow.id] = workflow

    assert manager.execute_workflow(workflow.id)
    assert events == ["build", "publish"]
    selected_steps = [
        entry["step"]
        for entry in workflow.audit_log
        if entry["decision"] == "selected"
    ]
    assert selected_steps == ["build", "publish"]
    assert workflow.status is StepStatus.COMPLETED


def test_runnable_selector_is_deterministic_for_parallel_nodes():
    workflow = Workflow("parallel")
    workflow.add_step(WorkflowStep("zeta", lambda: "zeta"))
    workflow.add_step(WorkflowStep("alpha", lambda: "alpha"))

    runnable = workflow.runnable_steps()

    assert [step.name for step in runnable] == ["alpha", "zeta"]
    assert workflow.audit_log == [
        {
            "decision": "selected",
            "step": "alpha",
            "reason": "dependencies_ready",
        },
        {
            "decision": "selected",
            "step": "zeta",
            "reason": "dependencies_ready",
        },
    ]


def test_invalid_dependency_is_rejected_before_state_changes():
    workflow = Workflow("invalid")
    step = WorkflowStep("deploy", lambda: "ok", depends_on=["build"])
    workflow.add_step(step)

    manager = WorkflowManager()
    manager._workflows[workflow.id] = workflow

    assert not manager.execute_workflow(workflow.id)
    assert workflow.status is StepStatus.PENDING
    assert step.status is StepStatus.PENDING
    assert workflow.audit_log[-1] == {
        "decision": "rejected",
        "step": "deploy",
        "reason": "missing_dependency",
    }


def test_duplicate_step_names_are_rejected_with_audit():
    workflow = Workflow("duplicate")
    workflow.add_step(WorkflowStep("build", lambda: "first"))

    with pytest.raises(WorkflowValidationError):
        workflow.add_step(WorkflowStep("build", lambda: "second"))

    assert workflow.audit_log[-1] == {
        "decision": "rejected",
        "step": "build",
        "reason": "duplicate_step_name",
    }


def test_dependency_cycles_are_rejected_before_dispatch():
    workflow = Workflow("cycle")
    workflow.add_step(WorkflowStep("a", lambda: "a", depends_on=["b"]))
    workflow.add_step(WorkflowStep("b", lambda: "b", depends_on=["a"]))

    manager = WorkflowManager()
    manager._workflows[workflow.id] = workflow

    assert not manager.execute_workflow(workflow.id)
    assert workflow.status is StepStatus.PENDING
    assert workflow.audit_log[-1]["reason"] == "dependency_cycle"
