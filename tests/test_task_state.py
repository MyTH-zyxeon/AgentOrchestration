import pytest

from src.orchestrator.task_state import (
    TaskStateRepository,
    UnscopedTaskStateAccess,
)


class TestTaskStateRepository:
    def setup_method(self):
        self.repository = TaskStateRepository()

    def test_requires_workspace_scope_for_reads_and_writes(self):
        with pytest.raises(UnscopedTaskStateAccess):
            self.repository.put("", "task-1", "queued")

        with pytest.raises(UnscopedTaskStateAccess):
            self.repository.get("", "task-1")

        with pytest.raises(UnscopedTaskStateAccess):
            self.repository.delete("", "task-1")

    def test_task_id_collisions_are_isolated_by_workspace(self):
        self.repository.put(
            "workspace-a",
            "shared-task",
            "queued",
            {"owner": "a"},
        )
        self.repository.put(
            "workspace-b",
            "shared-task",
            "running",
            {"owner": "b"},
        )

        workspace_a_state = self.repository.get(
            "workspace-a",
            "shared-task",
        )
        workspace_b_state = self.repository.get(
            "workspace-b",
            "shared-task",
        )

        assert workspace_a_state is not None
        assert workspace_b_state is not None
        assert workspace_a_state.status == "queued"
        assert workspace_a_state.payload == {"owner": "a"}
        assert workspace_b_state.status == "running"
        assert workspace_b_state.payload == {"owner": "b"}

    def test_listing_is_limited_to_one_workspace(self):
        self.repository.put("workspace-a", "task-1", "queued")
        self.repository.put("workspace-a", "task-2", "done")
        self.repository.put("workspace-b", "task-1", "running")

        states = list(self.repository.list_for_workspace("workspace-a"))

        assert {state.task_id for state in states} == {"task-1", "task-2"}
        assert {state.workspace_id for state in states} == {"workspace-a"}

    def test_unscoped_access_is_blocked(self):
        self.repository.put("workspace-a", "task-1", "queued")

        with pytest.raises(UnscopedTaskStateAccess):
            self.repository.get_unscoped("task-1")
