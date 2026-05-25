"""Workflow Manager — Defines and executes multi-step agent workflows."""

import json
import logging
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from src.common.metrics import metrics


logger = logging.getLogger(__name__)
DEFAULT_STATUS_MAX_BYTES = 8192


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
        self.attempt = 0
        self.revision = 0


class Workflow:
    def __init__(self, name: str, description: str = ""):
        self.id = str(uuid4())
        self.name = name
        self.description = description
        self.steps: List[WorkflowStep] = []
        self._step_map: Dict[str, WorkflowStep] = {}
        self.status = StepStatus.PENDING
        self.revision = 0
        self.audit_events: List[Dict[str, Any]] = []

    def add_step(self, step: WorkflowStep) -> "Workflow":
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)

    def record_audit(self, event: str, **details: Any) -> None:
        record = {
            "event": event,
            "workflow_revision": self.revision,
            **details,
        }
        self.audit_events.append(record)
        if len(self.audit_events) > 50:
            del self.audit_events[:-50]


class WorkflowManager:
    def __init__(self):
        self._workflows: Dict[str, Workflow] = {}

    def create_workflow(self, name: str, description: str = "") -> Workflow:
        workflow = Workflow(name, description)
        self._workflows[workflow.id] = workflow
        return workflow

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        return self._workflows.get(workflow_id)

    def list_workflows(self) -> List[Workflow]:
        return list(self._workflows.values())

    def delete_workflow(self, workflow_id: str) -> bool:
        return self._workflows.pop(workflow_id, None) is not None

    def execute_workflow(self, workflow_id: str) -> bool:
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return False

        self._set_workflow_status(
            workflow,
            StepStatus.RUNNING,
            "execute_start",
        )
        for step in workflow.steps:
            if not self._transition_step(
                workflow,
                step,
                StepStatus.RUNNING,
                expected_workflow_revision=workflow.revision,
                expected_step_revision=step.revision,
                expected_attempt=step.attempt,
            ):
                return False
            try:
                result = step.handler()
                step.result = result
                if not self._transition_step(
                    workflow,
                    step,
                    StepStatus.COMPLETED,
                    expected_workflow_revision=workflow.revision,
                    expected_step_revision=step.revision,
                    expected_attempt=step.attempt,
                ):
                    return False
            except Exception as e:
                step.error = str(e)
                self._transition_step(
                    workflow,
                    step,
                    StepStatus.FAILED,
                    expected_workflow_revision=workflow.revision,
                    expected_step_revision=step.revision,
                    expected_attempt=step.attempt,
                )
                self._set_workflow_status(
                    workflow,
                    StepStatus.FAILED,
                    "step_failed",
                )
                return False

        self._set_workflow_status(
            workflow,
            StepStatus.COMPLETED,
            "execute_complete",
        )
        return True

    def get_workflow_status(
        self,
        workflow_id: str,
        expand_results: bool = False,
        max_bytes: int = DEFAULT_STATUS_MAX_BYTES,
    ) -> Optional[Dict[str, Any]]:
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return None

        budget = max(512, int(max_bytes))
        payload: Dict[str, Any] = {
            "id": workflow.id,
            "name": workflow.name,
            "description": workflow.description,
            "status": workflow.status.value,
            "revision": workflow.revision,
            "step_count": len(workflow.steps),
            "steps": [],
            "audit_events": workflow.audit_events[-5:],
            "response": {
                "max_bytes": budget,
                "truncated": False,
                "expanded_results": expand_results,
            },
        }

        for index, step in enumerate(workflow.steps):
            entry = self._step_status(step)
            if expand_results and step.result is not None:
                entry["result"] = step.result
                expanded_payload = {
                    **payload,
                    "steps": [*payload["steps"], entry],
                }
                if self._json_size(expanded_payload) > budget:
                    entry.pop("result", None)
                    entry["result_summary"] = self._result_summary(step.result)
                    self._mark_status_truncated(
                        workflow,
                        payload,
                        "expanded_result_budget_exhausted",
                        omitted_steps=0,
                    )

            proposed = {**payload, "steps": [*payload["steps"], entry]}
            if self._json_size(proposed) > budget:
                omitted = len(workflow.steps) - index
                self._mark_status_truncated(
                    workflow,
                    payload,
                    "status_response_budget_exhausted",
                    omitted_steps=omitted,
                )
                break

            payload["steps"].append(entry)

        if self._json_size(payload) > budget:
            payload["audit_events"] = []
            self._mark_status_truncated(
                workflow,
                payload,
                "status_response_budget_exhausted",
                omitted_steps=max(
                    0,
                    len(workflow.steps) - len(payload["steps"]),
                ),
            )

        return payload

    def transition_step(
        self,
        workflow_id: str,
        step_id: str,
        status: StepStatus,
        *,
        expected_workflow_revision: Optional[int] = None,
        expected_step_revision: Optional[int] = None,
        expected_attempt: Optional[int] = None,
    ) -> bool:
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return False
        step = workflow.get_step(step_id)
        if not step:
            return False
        return self._transition_step(
            workflow,
            step,
            status,
            expected_workflow_revision=expected_workflow_revision,
            expected_step_revision=expected_step_revision,
            expected_attempt=expected_attempt,
        )

    def _set_workflow_status(
        self,
        workflow: Workflow,
        status: StepStatus,
        reason: str,
    ) -> None:
        if workflow.status == status:
            return
        workflow.status = status
        workflow.revision += 1
        workflow.record_audit(
            "workflow_status_committed",
            status=status.value,
            reason=reason,
        )

    def _transition_step(
        self,
        workflow: Workflow,
        step: WorkflowStep,
        status: StepStatus,
        *,
        expected_workflow_revision: Optional[int],
        expected_step_revision: Optional[int],
        expected_attempt: Optional[int],
    ) -> bool:
        checks = {
            "workflow_revision_mismatch": (
                expected_workflow_revision is not None
                and expected_workflow_revision != workflow.revision
            ),
            "step_revision_mismatch": (
                expected_step_revision is not None
                and expected_step_revision != step.revision
            ),
            "attempt_mismatch": (
                expected_attempt is not None
                and expected_attempt != step.attempt
            ),
        }
        for reason, failed in checks.items():
            if failed:
                self._defer_step_transition(workflow, step, status, reason)
                return False

        if status == step.status:
            return True

        allowed = {
            StepStatus.PENDING: {
                StepStatus.RUNNING,
                StepStatus.SKIPPED,
                StepStatus.FAILED,
            },
            StepStatus.RUNNING: {
                StepStatus.COMPLETED,
                StepStatus.FAILED,
                StepStatus.SKIPPED,
            },
            StepStatus.COMPLETED: set(),
            StepStatus.FAILED: {StepStatus.RUNNING},
            StepStatus.SKIPPED: {StepStatus.RUNNING},
        }
        if status not in allowed[step.status]:
            self._defer_step_transition(
                workflow,
                step,
                status,
                "invalid_lifecycle_transition",
            )
            return False

        if status == StepStatus.RUNNING:
            step.attempt += 1
        step.status = status
        step.revision += 1
        workflow.revision += 1
        workflow.record_audit(
            "workflow_step_transition_committed",
            step_id=step.id,
            status=status.value,
            step_revision=step.revision,
            attempt=step.attempt,
        )
        metrics.increment("workflow.step_transition.accepted")
        return True

    def _defer_step_transition(
        self,
        workflow: Workflow,
        step: WorkflowStep,
        status: StepStatus,
        reason: str,
    ) -> None:
        workflow.record_audit(
            "workflow_step_transition_deferred",
            step_id=step.id,
            requested_status=status.value,
            current_status=step.status.value,
            reason=reason,
            step_revision=step.revision,
            attempt=step.attempt,
        )
        metrics.increment("workflow.step_transition.deferred")
        logger.info("deferred workflow step transition: %s", reason)

    def _mark_status_truncated(
        self,
        workflow: Workflow,
        payload: Dict[str, Any],
        reason: str,
        *,
        omitted_steps: int,
    ) -> None:
        payload["response"]["truncated"] = True
        payload["response"]["reason"] = reason
        payload["response"]["omitted_steps"] = omitted_steps
        workflow.record_audit(
            "workflow_status_response_truncated",
            reason=reason,
            omitted_steps=omitted_steps,
            max_bytes=payload["response"]["max_bytes"],
        )
        metrics.increment("workflow.status_response.truncated")
        logger.info("truncated workflow status response: %s", reason)

    def _step_status(self, step: WorkflowStep) -> Dict[str, Any]:
        return {
            "id": step.id,
            "name": step.name,
            "status": step.status.value,
            "retries": step.retries,
            "timeout": step.timeout,
            "attempt": step.attempt,
            "revision": step.revision,
            "has_result": step.result is not None,
            "error": step.error,
        }

    def _result_summary(self, result: Any) -> Dict[str, Any]:
        return {
            "type": type(result).__name__,
            "encoded_bytes": self._json_size(result),
            "truncated": True,
        }

    def _json_size(self, value: Any) -> int:
        return len(
            json.dumps(
                value,
                default=str,
                separators=(",", ":"),
            ).encode("utf-8")
        )

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
