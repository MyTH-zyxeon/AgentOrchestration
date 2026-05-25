"""Workflow Manager — Defines and executes multi-step agent workflows."""

from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional
from uuid import uuid4


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowParameterError(ValueError):
    """Raised when workflow parameter binding violates the schema."""


class WorkflowParameter:
    def __init__(
        self,
        name: str,
        aliases: Optional[Iterable[str]] = None,
        default: Any = None,
        required: bool = False,
    ):
        self.name = name
        self.aliases = list(aliases or [])
        self.default = default
        self.required = required


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
        self.parameters: Dict[str, WorkflowParameter] = {}
        self._parameter_aliases: Dict[str, str] = {}
        self.parameter_audit_log: List[Dict[str, str]] = []
        self.status = StepStatus.PENDING

    def add_parameter(
        self,
        name: str,
        aliases: Optional[Iterable[str]] = None,
        default: Any = None,
        required: bool = False,
    ) -> "Workflow":
        parameter = WorkflowParameter(name, aliases, default, required)
        pending_aliases = self._collect_parameter_aliases(parameter)

        for alias_key, display_name in pending_aliases.items():
            owner = self._parameter_aliases.get(alias_key)
            if owner is not None:
                self._record_parameter_decision(
                    "rejected",
                    "duplicate_parameter_alias",
                    parameter.name,
                    display_name,
                )
                raise WorkflowParameterError(
                    f"parameter alias '{display_name}' already maps to "
                    f"'{owner}'"
                )

        self.parameters[parameter.name] = parameter
        for alias_key in pending_aliases:
            self._parameter_aliases[alias_key] = parameter.name
        self._record_parameter_decision(
            "registered",
            "unique_parameter_aliases",
            parameter.name,
            str(len(pending_aliases) - 1),
        )
        return self

    def add_step(self, step: WorkflowStep) -> "Workflow":
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)

    def resolve_parameters(self, inputs: Mapping[str, Any]) -> Dict[str, Any]:
        if not self.parameters:
            return dict(inputs)

        resolved: Dict[str, Any] = {}
        input_sources: Dict[str, str] = {}
        for raw_name, value in inputs.items():
            alias_key = self._normalize_parameter_key(raw_name)
            parameter_name = self._parameter_aliases.get(alias_key)
            if parameter_name is None:
                self._record_parameter_decision(
                    "rejected",
                    "unknown_parameter",
                    str(raw_name),
                    str(raw_name),
                )
                raise WorkflowParameterError(
                    f"unknown workflow parameter '{raw_name}'"
                )
            if parameter_name in resolved:
                self._record_parameter_decision(
                    "rejected",
                    "duplicate_parameter_input",
                    parameter_name,
                    str(raw_name),
                )
                previous = input_sources[parameter_name]
                raise WorkflowParameterError(
                    f"parameter '{parameter_name}' was provided by both "
                    f"'{previous}' and '{raw_name}'"
                )
            resolved[parameter_name] = value
            input_sources[parameter_name] = str(raw_name)

        for name, parameter in self.parameters.items():
            if name in resolved:
                continue
            if parameter.required:
                self._record_parameter_decision(
                    "rejected",
                    "missing_required_parameter",
                    name,
                    name,
                )
                raise WorkflowParameterError(
                    f"missing required workflow parameter '{name}'"
                )
            if parameter.default is not None:
                resolved[name] = parameter.default

        self._record_parameter_decision(
            "resolved",
            "workflow_parameters_bound",
            str(len(resolved)),
            "",
        )
        return resolved

    def _collect_parameter_aliases(
        self,
        parameter: WorkflowParameter,
    ) -> Dict[str, str]:
        aliases: Dict[str, str] = {}
        for display_name in [parameter.name] + parameter.aliases:
            alias_key = self._normalize_parameter_key(display_name)
            if alias_key in aliases:
                self._record_parameter_decision(
                    "rejected",
                    "duplicate_parameter_alias",
                    parameter.name,
                    display_name,
                )
                raise WorkflowParameterError(
                    f"parameter alias '{display_name}' duplicates another "
                    "alias"
                )
            aliases[alias_key] = display_name
        return aliases

    def _record_parameter_decision(
        self,
        decision: str,
        reason: str,
        parameter: str,
        alias: str,
    ) -> None:
        self.parameter_audit_log.append(
            {
                "decision": decision,
                "reason": reason,
                "parameter": parameter,
                "alias": alias,
            }
        )

    @staticmethod
    def _normalize_parameter_key(value: str) -> str:
        normalized = str(value).strip().lower()
        if not normalized:
            raise WorkflowParameterError(
                "workflow parameter names cannot be empty"
            )
        return normalized


class WorkflowManager:
    def __init__(self):
        self._workflows: Dict[str, Workflow] = {}

    def create_workflow(
        self,
        name: str,
        description: str = "",
        parameters: Optional[Iterable[WorkflowParameter]] = None,
    ) -> Workflow:
        workflow = Workflow(name, description)
        for parameter in parameters or []:
            workflow.add_parameter(
                parameter.name,
                aliases=parameter.aliases,
                default=parameter.default,
                required=parameter.required,
            )
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

        workflow.status = StepStatus.RUNNING
        for step in workflow.steps:
            step.status = StepStatus.RUNNING
            try:
                result = step.handler()
                step.result = result
                step.status = StepStatus.COMPLETED
            except Exception as e:
                step.error = str(e)
                step.status = StepStatus.FAILED
                workflow.status = StepStatus.FAILED
                return False

        workflow.status = StepStatus.COMPLETED
        return True

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
