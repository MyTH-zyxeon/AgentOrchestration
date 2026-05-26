from src.orchestrator.workflow import StepStatus, WorkflowManager, WorkflowStep


class TestWorkflowFinalization:
    def setup_method(self):
        self.manager = WorkflowManager()
        self.workflow = self.manager.create_workflow("deploy")

    def test_first_terminal_event_wins(self):
        revision = self.workflow.revision

        assert self.manager.finalize_workflow(
            self.workflow.id,
            StepStatus.COMPLETED,
            "attempt-1",
            revision,
            reason="worker-complete",
        )
        assert not self.manager.finalize_workflow(
            self.workflow.id,
            StepStatus.FAILED,
            "attempt-2",
            revision,
            reason="late-failure",
        )

        assert self.workflow.status == StepStatus.COMPLETED
        assert self.workflow.finalization_attempt == "attempt-1"
        assert self.workflow.revision == revision + 1
        assert self.workflow.terminal_reason == "worker-complete"
        assert self.workflow.audit_records[-1]["decision"] == (
            "ignored_duplicate_terminal"
        )
        assert "late-failure" not in str(self.workflow.audit_records)

    def test_stale_revision_is_rejected_before_state_commit(self):
        assert not self.manager.finalize_workflow(
            self.workflow.id,
            StepStatus.COMPLETED,
            "attempt-1",
            self.workflow.revision + 1,
            reason="stale-worker",
        )

        assert self.workflow.status == StepStatus.PENDING
        assert self.workflow.finalization_attempt is None
        assert self.workflow.revision == 0
        assert self.workflow.audit_records[-1]["decision"] == (
            "rejected_stale_revision"
        )

    def test_non_terminal_status_is_rejected(self):
        assert not self.manager.finalize_workflow(
            self.workflow.id,
            StepStatus.RUNNING,
            "attempt-1",
            self.workflow.revision,
            reason="not-terminal",
        )

        assert self.workflow.status == StepStatus.PENDING
        assert self.workflow.audit_records[-1]["decision"] == (
            "rejected_non_terminal"
        )

    def test_execute_workflow_finalizes_success_once(self):
        self.workflow.add_step(
            WorkflowStep("first", lambda: {"secret": "value"})
        )

        assert self.manager.execute_workflow(self.workflow.id)

        assert self.workflow.status == StepStatus.COMPLETED
        assert self.workflow.revision == 1
        assert self.workflow.audit_records[-1]["decision"] == (
            "accepted_terminal"
        )
        assert "secret" not in str(self.workflow.audit_records)
