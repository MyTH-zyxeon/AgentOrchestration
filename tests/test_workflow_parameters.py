from src.orchestrator.workflow import StepStatus, WorkflowManager, WorkflowStep


def test_parameter_binding_preserves_explicit_false_defaults():
    manager = WorkflowManager()
    workflow = manager.create_workflow("deploy")
    seen = []

    def handler(parameters):
        seen.append(parameters)
        return "ok"

    step = WorkflowStep(
        "gate",
        handler,
        parameters={
            "enabled": False,
            "retries": 0,
            "label": "",
            "region": "us",
        },
    )
    workflow.add_step(step)

    assert manager.execute_workflow(workflow.id)

    assert seen == [{
        "enabled": False,
        "retries": 0,
        "label": "",
        "region": "us",
    }]
    assert step.result == "ok"


def test_parameter_binding_applies_explicit_false_overrides():
    manager = WorkflowManager()
    workflow = manager.create_workflow("deploy")
    seen = []

    def handler(parameters):
        seen.append(parameters)

    step = WorkflowStep(
        "gate",
        handler,
        parameters={"enabled": True, "count": 4, "label": "default"},
    )
    workflow.add_step(step)

    assert manager.execute_workflow(
        workflow.id,
        {step.id: {"enabled": False, "count": 0, "label": ""}},
    )

    assert seen == [{"enabled": False, "count": 0, "label": ""}]


def test_parameter_binding_skips_none_overrides_without_losing_defaults():
    manager = WorkflowManager()
    workflow = manager.create_workflow("deploy")
    step = WorkflowStep(
        "gate",
        lambda parameters: parameters,
        parameters={"enabled": False, "region": "us"},
    )
    workflow.add_step(step)

    assert manager.bind_workflow_parameters(
        workflow.id,
        {step.id: {"enabled": None}},
    )

    assert step.parameters == {"enabled": False, "region": "us"}


def test_parameter_binding_defers_after_workflow_starts():
    manager = WorkflowManager()
    workflow = manager.create_workflow("deploy")
    step = WorkflowStep(
        "gate",
        lambda parameters: parameters,
        parameters={"enabled": False},
    )
    workflow.add_step(step)
    workflow.status = StepStatus.RUNNING

    assert not manager.bind_workflow_parameters(
        workflow.id,
        {step.id: {"enabled": True}},
    )

    assert workflow.status is StepStatus.RUNNING
    assert step.parameters == {"enabled": False}
    assert workflow.audit_events[-1] == {
        "event": "parameter_binding_deferred",
        "workflow_id": workflow.id,
        "status": "running",
        "step_ids": [step.id],
    }


def test_parameter_audit_omits_runtime_values():
    manager = WorkflowManager()
    workflow = manager.create_workflow("deploy")
    step = WorkflowStep(
        "gate",
        lambda parameters: parameters,
        parameters={"secret": False},
    )
    workflow.add_step(step)

    assert manager.bind_workflow_parameters(
        workflow.id,
        {step.id: {"secret": "do-not-log"}},
    )

    event = workflow.audit_events[-1]
    assert event["event"] == "parameter_binding_applied"
    assert event["default_keys"] == ["secret"]
    assert event["override_keys"] == ["secret"]
    assert event["bound_keys"] == ["secret"]
    assert "do-not-log" not in repr(event)


def test_existing_no_arg_handlers_still_execute():
    manager = WorkflowManager()
    workflow = manager.create_workflow("legacy")
    step = WorkflowStep("legacy", lambda: "ok")
    workflow.add_step(step)

    assert manager.execute_workflow(workflow.id)
    assert step.result == "ok"
