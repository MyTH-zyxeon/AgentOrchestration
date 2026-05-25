import asyncio

from src.agent.executor import AgentExecutor


def test_execute_stores_json_serializable_result():
    async def handler(agent_id, task):
        return {"agent": agent_id, "task": task["id"], "ok": True}

    executor = AgentExecutor()

    execution_id = asyncio.run(
        executor.execute("agent-1", {"id": "task-1"}, handler)
    )

    stored = executor.get_result(execution_id)
    assert stored["agent_id"] == "agent-1"
    assert stored["task_id"] == "task-1"
    assert stored["result"] == {
        "agent": "agent-1",
        "task": "task-1",
        "ok": True,
    }
    assert execution_id not in executor._active_tasks


def test_execute_rejects_non_json_serializable_tool_result():
    async def handler(agent_id, task):
        return {"bad": {agent_id, task["id"]}}

    executor = AgentExecutor()

    execution_id = asyncio.run(
        executor.execute("agent-1", {"id": "task-1"}, handler)
    )

    stored = executor.get_result(execution_id)
    assert "tool result must be JSON-serializable" in stored["error"]
    assert execution_id not in executor._active_tasks


def test_execute_rejects_non_finite_json_values():
    async def handler(agent_id, task):
        return {"score": float("nan")}

    executor = AgentExecutor()

    execution_id = asyncio.run(
        executor.execute("agent-1", {"id": "task-1"}, handler)
    )

    stored = executor.get_result(execution_id)
    assert "tool result must be JSON-serializable" in stored["error"]
    assert execution_id not in executor._active_tasks
