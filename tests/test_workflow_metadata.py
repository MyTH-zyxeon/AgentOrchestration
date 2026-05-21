import pytest

from src.common.metrics import metrics
from src.orchestrator.workflow import (
    StepStatus,
    WorkflowManager,
    WorkflowMetadataError,
    WorkflowStep,
)


def test_create_workflow_rejects_reserved_metadata_before_registration():
    manager = WorkflowManager()

    with pytest.raises(WorkflowMetadataError) as exc_info:
        manager.create_workflow("invoice-sync", metadata={"status": "running"})

    assert "metadata.status" in str(exc_info.value)
    assert manager.list_workflows() == []
    assert len(manager.audit_records) == 1
    assert manager.audit_records[0]["event"] == "workflow_metadata_rejected"
    assert manager.audit_records[0]["scope"] == "workflow"
    assert manager.audit_records[0]["owner_id"]
    assert manager.audit_records[0]["key_path"] == "metadata.status"
    assert manager.audit_records[0]["reason"] == "reserved_metadata_key"


def test_add_step_rejects_nested_reserved_metadata_without_mutating_steps():
    workflow = WorkflowManager().create_workflow("invoice-sync")
    step = WorkflowStep(
        "dispatch",
        lambda: "ok",
        metadata={"public": {"task_id": "spoofed-task"}},
    )

    with pytest.raises(WorkflowMetadataError) as exc_info:
        workflow.add_step(step)

    assert exc_info.value.key_path == "metadata.public.task_id"
    assert workflow.steps == []
    assert workflow.get_step(step.id) is None
    assert workflow.audit_records[0] == {
        "event": "workflow_metadata_rejected",
        "scope": "step",
        "owner_id": step.id,
        "key_path": "metadata.public.task_id",
        "reason": "reserved_metadata_key",
    }


def test_execute_defers_reserved_metadata_added_after_registration():
    manager = WorkflowManager()
    workflow = manager.create_workflow("invoice-sync")
    workflow.add_step(WorkflowStep("dispatch", lambda: "ok"))
    workflow.metadata["routing"] = "manual-override"

    assert manager.execute_workflow(workflow.id) is False

    assert workflow.status is StepStatus.PENDING
    assert workflow.steps[0].status is StepStatus.PENDING
    assert workflow.audit_records[-1] == {
        "event": "workflow_metadata_rejected",
        "scope": "workflow",
        "owner_id": workflow.id,
        "key_path": "metadata.routing",
        "reason": "reserved_metadata_key",
    }
    assert manager.audit_records[-1] == workflow.audit_records[-1]
    assert metrics.snapshot()["counters"]["workflow.metadata.rejected"] >= 1


def test_valid_metadata_executes_without_private_metadata_in_audit():
    manager = WorkflowManager()
    workflow = manager.create_workflow(
        "invoice-sync",
        metadata={"team": "finance"},
    )
    workflow.add_step(
        WorkflowStep(
            "dispatch",
            lambda: {"sent": True},
            metadata={"public": {"channel": "email"}},
        )
    )

    assert manager.execute_workflow(workflow.id) is True

    assert workflow.status is StepStatus.COMPLETED
    assert workflow.steps[0].result == {"sent": True}
    assert workflow.audit_records == []
    assert manager.audit_records == []
