from src.orchestrator.workflow import StepStatus, WorkflowManager, WorkflowStep


def test_deleted_workflow_rejects_existing_poll_without_payload_leakage():
    manager = WorkflowManager()
    workflow = manager.create_workflow("cleanup-race")

    poll = manager.start_poll(workflow.id)
    assert poll is not None
    assert manager.delete_workflow(workflow.id)

    assert not manager.complete_poll(poll["poll_id"])
    rejected = manager.audit_records()[-1]
    assert rejected["event"] == "poll_rejected"
    assert rejected["reason"] == "workflow_deleted"
    assert rejected["expected_revision"] == 1
    assert rejected["current_revision"] == 2
    assert "payload" not in rejected
    assert "result" not in rejected
    assert "handler" not in rejected


def test_deleted_workflow_rejects_new_poll():
    manager = WorkflowManager()
    workflow = manager.create_workflow("deleted")

    assert manager.delete_workflow(workflow.id)

    assert manager.start_poll(workflow.id) is None
    rejected = manager.audit_records()[-1]
    assert rejected == {
        "event": "poll_rejected",
        "workflow_id": workflow.id,
        "reason": "workflow_deleted",
    }


def test_execute_workflow_stops_when_handler_deletes_workflow():
    manager = WorkflowManager()
    workflow = manager.create_workflow("delete-during-poll")
    ran = []

    def delete_workflow():
        ran.append("delete")
        manager.delete_workflow(workflow.id)
        return {"private": "runtime-data"}

    def should_not_run():
        ran.append("second")
        return "stale"

    first = WorkflowStep("delete", delete_workflow)
    second = WorkflowStep("second", should_not_run)
    workflow.add_step(first).add_step(second)

    assert not manager.execute_workflow(workflow.id)
    assert ran == ["delete"]
    assert first.status == StepStatus.SKIPPED
    assert first.result is None
    assert second.status == StepStatus.PENDING
    assert workflow.status == StepStatus.SKIPPED
    assert manager.get_workflow(workflow.id) is None


def test_current_revision_poll_can_complete():
    manager = WorkflowManager()
    workflow = manager.create_workflow("current")

    poll = manager.start_poll(workflow.id)
    assert poll is not None
    assert manager.complete_poll(poll["poll_id"])

    completed = manager.audit_records()[-1]
    assert completed["event"] == "poll_completed"
    assert completed["workflow_id"] == workflow.id
    assert completed["revision"] == 1
