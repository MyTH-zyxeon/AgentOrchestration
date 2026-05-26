"""Workflow Manager — Defines and executes multi-step agent workflows."""

from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowStep:
    def __init__(
        self,
        name: str,
        handler: Callable,
        retries: int = 0,
        timeout: int = 300,
    ):
        self.id = str(uuid4())
        self.name = name
        self.handler = handler
        self.retries = retries
        self.timeout = timeout
        self.status = StepStatus.PENDING
        self.result: Any = None
        self.error: Optional[str] = None


class Workflow:
    def __init__(self, name: str, description: str = ""):
        self.id = str(uuid4())
        self.name = name
        self.description = description
        self.steps: List[WorkflowStep] = []
        self._step_map: Dict[str, WorkflowStep] = {}
        self.status = StepStatus.PENDING

    def add_step(self, step: WorkflowStep) -> "Workflow":
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)


class WorkflowManager:
    def __init__(self):
        self._workflows: Dict[str, Workflow] = {}
        self._workflow_revisions: Dict[str, int] = {}
        self._deleted_revisions: Dict[str, int] = {}
        self._active_polls: Dict[str, Dict[str, Any]] = {}
        self._audit_records: List[Dict[str, Any]] = []

    def create_workflow(self, name: str, description: str = "") -> Workflow:
        workflow = Workflow(name, description)
        self._workflows[workflow.id] = workflow
        self._workflow_revisions[workflow.id] = 1
        return workflow

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        return self._workflows.get(workflow_id)

    def list_workflows(self) -> List[Workflow]:
        return list(self._workflows.values())

    def delete_workflow(self, workflow_id: str) -> bool:
        if self._workflows.pop(workflow_id, None) is None:
            return False

        revision = self._workflow_revisions.pop(workflow_id, 0) + 1
        self._deleted_revisions[workflow_id] = revision
        cancelled_polls = 0
        for poll in self._active_polls.values():
            if poll["workflow_id"] == workflow_id:
                poll["cancelled"] = True
                cancelled_polls += 1

        self._record_audit(
            "workflow_deleted",
            workflow_id=workflow_id,
            revision=revision,
            cancelled_polls=cancelled_polls,
        )
        return True

    def start_poll(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        if workflow_id not in self._workflows:
            reason = (
                "workflow_deleted"
                if workflow_id in self._deleted_revisions
                else "workflow_missing"
            )
            self._record_audit(
                "poll_rejected",
                workflow_id=workflow_id,
                reason=reason,
            )
            return None

        poll_id = str(uuid4())
        revision = self._workflow_revisions[workflow_id]
        poll = {
            "poll_id": poll_id,
            "workflow_id": workflow_id,
            "revision": revision,
            "cancelled": False,
        }
        self._active_polls[poll_id] = poll
        self._record_audit(
            "poll_started",
            workflow_id=workflow_id,
            poll_id=poll_id,
            revision=revision,
        )
        return dict(poll)

    def complete_poll(self, poll_id: str) -> bool:
        poll = self._active_polls.pop(poll_id, None)
        if poll is None:
            self._record_audit(
                "poll_rejected",
                poll_id=poll_id,
                reason="poll_missing",
            )
            return False

        workflow_id = poll["workflow_id"]
        current_revision = self._workflow_revisions.get(workflow_id)
        if (
            poll["cancelled"]
            or workflow_id not in self._workflows
            or current_revision != poll["revision"]
        ):
            reason = (
                "workflow_deleted"
                if workflow_id in self._deleted_revisions
                else "revision_changed"
            )
            self._record_audit(
                "poll_rejected",
                workflow_id=workflow_id,
                poll_id=poll_id,
                expected_revision=poll["revision"],
                current_revision=current_revision
                or self._deleted_revisions.get(workflow_id),
                reason=reason,
            )
            return False

        self._record_audit(
            "poll_completed",
            workflow_id=workflow_id,
            poll_id=poll_id,
            revision=current_revision,
        )
        return True

    def audit_records(self) -> List[Dict[str, Any]]:
        return [dict(record) for record in self._audit_records]

    def execute_workflow(self, workflow_id: str) -> bool:
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return False

        workflow.status = StepStatus.RUNNING
        for step in workflow.steps:
            poll = self.start_poll(workflow_id)
            if poll is None:
                workflow.status = StepStatus.SKIPPED
                return False

            step.status = StepStatus.RUNNING
            try:
                result = step.handler()
            except Exception as exc:
                step.error = str(exc)
                step.status = StepStatus.FAILED
                workflow.status = StepStatus.FAILED
                return False

            if not self.complete_poll(poll["poll_id"]):
                step.status = StepStatus.SKIPPED
                workflow.status = StepStatus.SKIPPED
                return False

            step.result = result
            step.status = StepStatus.COMPLETED

        workflow.status = StepStatus.COMPLETED
        return True

    def _record_audit(self, event: str, **fields: Any) -> None:
        record = {"event": event}
        record.update(fields)
        self._audit_records.append(record)

# 2019-03-27T19:58:07 update

# 2019-05-09T09:42:56 update

# 2019-12-03T10:07:42 update

# 2020-01-16T18:43:28 update

# 2020-03-20T10:40:15 update

# 2020-04-17T15:36:50 update

# 2020-05-04T14:44:01 update

# 2020-06-16T13:17:31 update

# 2020-08-05T17:00:24 update

# 2020-09-04T08:29:23 update

# 2020-09-09T17:52:02 update

# 2020-10-23T10:57:44 update

# 2020-12-05T20:55:47 update

# 2021-01-15T19:23:40 update

# 2021-02-03T20:43:12 update

# 2021-03-16T12:26:47 update

# 2021-04-20T14:33:28 update

# 2021-10-14T15:03:32 update

# 2021-10-21T17:24:55 update

# 2021-11-16T17:01:08 update

# 2021-11-22T09:51:21 update

# 2021-12-21T16:15:47 update

# 2022-03-23T16:52:27 update

# 2022-12-21T09:25:50 update

# 2023-01-09T09:55:25 update

# 2023-01-13T11:06:15 update

# 2023-01-26T11:00:59 update

# 2023-02-23T08:56:54 update

# 2023-05-17T08:07:16 update

# 2023-06-06T17:09:34 update

# 2023-06-13T10:35:28 update

# 2023-08-24T20:36:06 update

# 2023-10-30T19:10:13 update

# 2024-01-02T08:27:25 update

# 2024-01-24T12:13:15 update

# 2024-02-08T13:35:49 update

# 2024-05-07T16:09:24 update

# 2024-05-11T09:48:46 update

# 2024-05-21T19:25:41 update

# 2024-06-05T12:00:30 update

# 2024-06-25T09:40:26 update

# 2024-09-17T13:49:39 update

# 2024-10-14T17:39:35 update

# 2024-11-27T20:14:35 update

# 2024-12-25T19:31:41 update

# 2025-01-16T13:15:09 update

# 2025-02-05T14:06:59 update

# 2025-02-17T20:55:11 update

# 2025-04-30T19:36:53 update

# 2025-07-17T10:14:40 update

# 2025-08-29T12:13:15 update

# 2025-09-03T13:51:11 update

# 2025-09-19T16:08:24 update

# 2025-11-27T08:38:12 update

# 2026-01-27T13:23:38 update

# 2026-01-28T11:22:50 update
