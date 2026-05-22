"""Workspace-scoped task state repository."""

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, MutableMapping, Optional, Tuple


class UnscopedTaskStateAccess(ValueError):
    """Raised when task state access is attempted without workspace scope."""


@dataclass(frozen=True)
class TaskState:
    workspace_id: str
    task_id: str
    status: str
    payload: Mapping[str, Any] = field(default_factory=dict)


class TaskStateRepository:
    """Stores task state behind a mandatory workspace predicate."""

    def __init__(self) -> None:
        self._states: MutableMapping[Tuple[str, str], TaskState] = {}

    def put(
        self,
        workspace_id: str,
        task_id: str,
        status: str,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> TaskState:
        workspace_id = self._require_scope(workspace_id)
        task_id = self._require_task_id(task_id)
        state = TaskState(
            workspace_id=workspace_id,
            task_id=task_id,
            status=status,
            payload=dict(payload or {}),
        )
        self._states[(workspace_id, task_id)] = state
        return state

    def get(self, workspace_id: str, task_id: str) -> Optional[TaskState]:
        workspace_id = self._require_scope(workspace_id)
        task_id = self._require_task_id(task_id)
        return self._states.get((workspace_id, task_id))

    def delete(self, workspace_id: str, task_id: str) -> bool:
        workspace_id = self._require_scope(workspace_id)
        task_id = self._require_task_id(task_id)
        return self._states.pop((workspace_id, task_id), None) is not None

    def list_for_workspace(self, workspace_id: str) -> Iterable[TaskState]:
        workspace_id = self._require_scope(workspace_id)
        return (
            state
            for (state_workspace_id, _), state in self._states.items()
            if state_workspace_id == workspace_id
        )

    def get_unscoped(self, task_id: str) -> TaskState:
        raise UnscopedTaskStateAccess(
            "task state access requires workspace_id and task_id predicates"
        )

    @staticmethod
    def _require_scope(workspace_id: str) -> str:
        if not workspace_id or not str(workspace_id).strip():
            raise UnscopedTaskStateAccess(
                "workspace_id is required for task state access"
            )
        return str(workspace_id)

    @staticmethod
    def _require_task_id(task_id: str) -> str:
        if not task_id or not str(task_id).strip():
            raise ValueError("task_id is required for task state access")
        return str(task_id)
