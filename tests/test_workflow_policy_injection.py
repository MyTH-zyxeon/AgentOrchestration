from src.orchestrator.workflow import StepStatus, WorkflowManager, WorkflowStep


def test_invalid_policy_guard_graph_rejected_before_lifecycle_transition():
    manager = WorkflowManager()
    workflow = manager.create_workflow("guarded")
    calls = []

    work_step = WorkflowStep("work", lambda: calls.append("work"))
    workflow.add_step(work_step)
    manager.register_policy_guard(
        "tenant-boundary",
        lambda: calls.append("guard"),
        step_id=work_step.id,
    )

    assert manager.execute_workflow(workflow.id) is False
    assert calls == []
    assert workflow.status == StepStatus.PENDING
    assert work_step.status == StepStatus.PENDING
    assert workflow.audit_records == [
        {
            "event": "policy_injection_rejected",
            "workflow_id": workflow.id,
            "reason": "duplicate_step_id",
        }
    ]


def test_policy_guard_executes_before_workflow_steps():
    manager = WorkflowManager()
    workflow = manager.create_workflow("guarded")
    calls = []

    manager.register_policy_guard(
        "tenant-boundary", lambda: calls.append("guard")
    )
    workflow.add_step(WorkflowStep("work", lambda: calls.append("work")))

    assert manager.execute_workflow(workflow.id) is True
    assert calls == ["guard", "work"]
    assert workflow.status == StepStatus.COMPLETED
    assert workflow.steps[0].is_policy_guard
    assert all(step.status == StepStatus.COMPLETED for step in workflow.steps)


def test_policy_guard_with_unknown_dependency_is_rejected():
    manager = WorkflowManager()
    workflow = manager.create_workflow("guarded")
    calls = []

    manager.register_policy_guard(
        "tenant-boundary",
        lambda: calls.append("guard"),
        dependencies=["missing-step"],
    )
    workflow.add_step(WorkflowStep("work", lambda: calls.append("work")))

    assert manager.execute_workflow(workflow.id) is False
    assert calls == []
    assert workflow.status == StepStatus.PENDING
    assert workflow.audit_records[-1]["reason"] == "unknown_dependency"
