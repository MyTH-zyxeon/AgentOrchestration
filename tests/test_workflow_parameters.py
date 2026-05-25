import pytest

from src.orchestrator.workflow import (
    StepStatus,
    Workflow,
    WorkflowManager,
    WorkflowParameter,
    WorkflowParameterError,
)


def test_duplicate_aliases_are_rejected_before_registration():
    workflow = Workflow("daily-refresh")

    with pytest.raises(WorkflowParameterError):
        workflow.add_parameter("account_id", aliases=["account", "ACCOUNT"])

    assert workflow.parameters == {}
    assert workflow.status is StepStatus.PENDING
    assert workflow.parameter_audit_log[-1] == {
        "decision": "rejected",
        "reason": "duplicate_parameter_alias",
        "parameter": "account_id",
        "alias": "ACCOUNT",
    }


def test_alias_collision_with_existing_parameter_is_rejected():
    workflow = Workflow("daily-refresh")
    workflow.add_parameter("account_id", aliases=["account"])

    with pytest.raises(WorkflowParameterError):
        workflow.add_parameter("workspace_id", aliases=["account"])

    assert list(workflow.parameters) == ["account_id"]
    assert workflow.status is StepStatus.PENDING
    assert (
        workflow.parameter_audit_log[-1]["reason"]
        == "duplicate_parameter_alias"
    )
    assert workflow.parameter_audit_log[-1]["alias"] == "account"


def test_resolve_parameters_binds_aliases_to_canonical_names():
    workflow = Workflow("daily-refresh")
    workflow.add_parameter("account_id", aliases=["account"])
    workflow.add_parameter("limit", aliases=["page_size"], default=100)

    resolved = workflow.resolve_parameters({"account": "acct_123"})

    assert resolved == {"account_id": "acct_123", "limit": 100}
    assert workflow.parameter_audit_log[-1] == {
        "decision": "resolved",
        "reason": "workflow_parameters_bound",
        "parameter": "2",
        "alias": "",
    }


def test_resolve_parameters_rejects_duplicate_canonical_input():
    workflow = Workflow("daily-refresh")
    workflow.add_parameter("limit", aliases=["page_size"])

    with pytest.raises(WorkflowParameterError):
        workflow.resolve_parameters({"limit": 25, "page_size": 50})

    assert workflow.status is StepStatus.PENDING
    assert workflow.parameter_audit_log[-1] == {
        "decision": "rejected",
        "reason": "duplicate_parameter_input",
        "parameter": "limit",
        "alias": "page_size",
    }


def test_manager_registers_parameters_before_publishing_workflow():
    manager = WorkflowManager()
    workflow = manager.create_workflow(
        "daily-refresh",
        parameters=[WorkflowParameter("region", aliases=["cloud_region"])],
    )

    assert manager.get_workflow(workflow.id) is workflow
    assert workflow.resolve_parameters({"cloud_region": "us-east-1"}) == {
        "region": "us-east-1"
    }


def test_manager_does_not_publish_invalid_parameter_schema():
    manager = WorkflowManager()

    with pytest.raises(WorkflowParameterError):
        manager.create_workflow(
            "daily-refresh",
            parameters=[WorkflowParameter("region", aliases=["region"])],
        )

    assert manager.list_workflows() == []


def test_parameter_helpers_are_public_exports():
    from src.orchestrator import WorkflowParameter as ExportedParameter
    from src.orchestrator import WorkflowParameterError as ExportedError

    assert ExportedParameter is WorkflowParameter
    assert ExportedError is WorkflowParameterError
