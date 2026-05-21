from src.orchestrator.workflow import (
    ArtifactRetentionPolicy,
    StepStatus,
    Workflow,
    WorkflowStep,
)


def _workflow():
    workflow = Workflow("retention-workflow")
    step = WorkflowStep("archive-artifacts", lambda: None)
    workflow.add_step(step)
    return workflow, step


def test_cleanup_scheduling_defers_when_lifecycle_state_changed():
    workflow, step = _workflow()
    workflow.status = StepStatus.RUNNING
    policy = ArtifactRetentionPolicy(
        artifact_name="run-output.csv",
        retention_days=7,
        cleanup_after_step=step.id,
    )

    decision = workflow.schedule_artifact_cleanup(
        policy, expected_status=StepStatus.PENDING
    )

    assert decision.accepted is False
    assert decision.action == "defer"
    assert workflow.status == StepStatus.RUNNING
    assert workflow.artifact_retention_policies == {}
    assert workflow.audit_records[-1]["reason"] == (
        "workflow lifecycle changed before cleanup scheduling"
    )


def test_cleanup_scheduling_rejects_policy_violations():
    workflow, step = _workflow()
    policy = ArtifactRetentionPolicy(
        artifact_name="run-output.csv",
        retention_days=0,
        cleanup_after_step=step.id,
    )

    decision = workflow.schedule_artifact_cleanup(policy)

    assert decision.accepted is False
    assert decision.action == "reject"
    assert decision.reason == "retention days must be positive"
    assert workflow.status == StepStatus.PENDING
    assert workflow.artifact_retention_policies == {}


def test_cleanup_scheduling_rejects_duplicate_or_stale_policy():
    workflow, step = _workflow()
    policy = ArtifactRetentionPolicy(
        artifact_name="run-output.csv",
        retention_days=7,
        cleanup_after_step=step.id,
        policy_version=2,
    )
    stale_policy = ArtifactRetentionPolicy(
        artifact_name="run-output.csv",
        retention_days=10,
        cleanup_after_step=step.id,
        policy_version=1,
    )

    assert workflow.schedule_artifact_cleanup(policy).accepted is True
    decision = workflow.schedule_artifact_cleanup(stale_policy)

    assert decision.accepted is False
    assert decision.reason == "stale or duplicate artifact retention policy"
    assert workflow.artifact_retention_policies["run-output.csv"] == policy


def test_cleanup_scheduling_accepts_valid_policy_and_audits_decision():
    workflow, step = _workflow()
    policy = ArtifactRetentionPolicy(
        artifact_name="run-output.csv",
        retention_days=7,
        cleanup_after_step=step.id,
    )

    decision = workflow.schedule_artifact_cleanup(policy)

    assert decision.accepted is True
    assert decision.action == "schedule"
    assert workflow.artifact_retention_policies["run-output.csv"] == policy
    assert workflow.audit_records[-1] == {
        "event": "artifact_cleanup_policy",
        "artifact_name": "run-output.csv",
        "action": "schedule",
        "reason": "artifact cleanup policy accepted",
        "workflow_status": "pending",
        "policy_version": "1",
    }
