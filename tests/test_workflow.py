from src.orchestrator.workflow import WorkflowManager, WorkflowStep


def _failing_handler():
    raise RuntimeError("private runtime failure payload")


def test_cleanup_defers_artifact_while_retry_dependency_is_pending():
    manager = WorkflowManager()
    workflow = manager.create_workflow("retry-artifact-cleanup")
    step = WorkflowStep(
        "produce-artifact",
        _failing_handler,
        retries=1,
        retry_artifacts=["artifact-a"],
    )
    workflow.add_step(step)

    assert manager.execute_workflow(workflow.id) is False

    decision = manager.plan_artifact_cleanup(workflow.id, "artifact-a")

    assert decision["allowed"] is False
    assert decision["reason"] == "retry_dependency_pending"
    assert decision["blocked_steps"] == [{
        "step_id": step.id,
        "step_name": "produce-artifact",
        "status": "failed",
        "attempts": 1,
        "retries": 1,
    }]
    audit_text = str(manager.cleanup_audit())
    assert "private runtime failure payload" not in audit_text


def test_cleanup_allows_artifact_after_retry_budget_is_exhausted():
    manager = WorkflowManager()
    workflow = manager.create_workflow("retry-exhausted")
    step = WorkflowStep(
        "produce-artifact",
        _failing_handler,
        retries=1,
        retry_artifacts=["artifact-a"],
    )
    workflow.add_step(step)
    step.attempts = 2

    decision = manager.plan_artifact_cleanup(workflow.id, "artifact-a")

    assert decision["allowed"] is True
    assert decision["reason"] == "safe_to_cleanup"
    assert decision["blocked_steps"] == []


def test_cleanup_allows_unrelated_artifact():
    manager = WorkflowManager()
    workflow = manager.create_workflow("unrelated-artifact")
    step = WorkflowStep(
        "produce-artifact",
        _failing_handler,
        retries=1,
        retry_artifacts=["artifact-a"],
    )
    workflow.add_step(step)

    decision = manager.plan_artifact_cleanup(workflow.id, "artifact-b")

    assert decision["allowed"] is True
    assert decision["reason"] == "safe_to_cleanup"
    assert decision["blocked_steps"] == []
