import json

from src.orchestrator.workflow import StepStatus, WorkflowManager, WorkflowStep


def test_status_response_truncates_large_expanded_result():
    manager = WorkflowManager()
    workflow = manager.create_workflow("large graph")
    step = WorkflowStep("expand graph", lambda: None)
    workflow.add_step(step)
    step.status = StepStatus.COMPLETED
    step.result = {
        "nodes": [{"id": i, "payload": "x" * 200} for i in range(40)]
    }

    status = manager.get_workflow_status(
        workflow.id,
        expand_results=True,
        max_bytes=2000,
    )

    assert status["response"]["truncated"]
    assert status["steps"][0]["result_summary"]["truncated"]
    assert "result" not in status["steps"][0]
    assert len(json.dumps(status, default=str).encode("utf-8")) <= 2000
    assert (
        workflow.audit_events[-1]["event"]
        == "workflow_status_response_truncated"
    )


def test_status_response_omits_steps_after_budget_is_exhausted():
    manager = WorkflowManager()
    workflow = manager.create_workflow("wide graph")
    for index in range(60):
        workflow.add_step(WorkflowStep(f"step {index}", lambda: None))

    status = manager.get_workflow_status(workflow.id, max_bytes=1500)

    assert status["response"]["truncated"]
    assert status["response"]["omitted_steps"] > 0
    assert len(status["steps"]) < len(workflow.steps)


def test_stale_revision_transition_is_deferred_without_lifecycle_change():
    manager = WorkflowManager()
    workflow = manager.create_workflow("revision guard")
    step = WorkflowStep("run once", lambda: "ok")
    workflow.add_step(step)
    step.status = StepStatus.RUNNING
    step.revision = 1
    step.attempt = 1
    workflow.revision = 2

    accepted = manager.transition_step(
        workflow.id,
        step.id,
        StepStatus.COMPLETED,
        expected_workflow_revision=1,
        expected_step_revision=1,
        expected_attempt=1,
    )

    assert not accepted
    assert step.status == StepStatus.RUNNING
    assert workflow.audit_events[-1]["reason"] == "workflow_revision_mismatch"


def test_completed_step_cannot_reenter_running_without_retry_state():
    manager = WorkflowManager()
    workflow = manager.create_workflow("lifecycle guard")
    step = WorkflowStep("already done", lambda: "ok")
    workflow.add_step(step)
    step.status = StepStatus.COMPLETED

    accepted = manager.transition_step(
        workflow.id,
        step.id,
        StepStatus.RUNNING,
        expected_workflow_revision=0,
        expected_step_revision=0,
        expected_attempt=0,
    )

    assert not accepted
    assert step.status == StepStatus.COMPLETED
    assert (
        workflow.audit_events[-1]["reason"]
        == "invalid_lifecycle_transition"
    )
