import asyncio
import time

from src.agent.executor import AgentExecutor


def test_execute_returns_execution_id_before_handler_finishes():
    asyncio.run(_assert_execute_returns_execution_id_before_handler_finishes())


async def _assert_execute_returns_execution_id_before_handler_finishes():
    executor = AgentExecutor()
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(agent_id, task):
        started.set()
        await release.wait()
        return {"ok": True}

    start = time.monotonic()
    execution_id = await executor.execute(
        "agent-1",
        {"id": "task-1"},
        handler,
    )
    elapsed = time.monotonic() - start

    assert execution_id in executor._active_tasks
    assert elapsed < 0.05
    assert executor.get_result(execution_id) is None

    await asyncio.wait_for(started.wait(), timeout=1)
    release.set()

    for _ in range(20):
        result = executor.get_result(execution_id)
        if result is not None:
            break
        await asyncio.sleep(0.01)

    assert result["execution_id"] == execution_id
    assert result["agent_id"] == "agent-1"
    assert result["task_id"] == "task-1"
    assert result["result"] == {"ok": True}
    assert execution_id not in executor._active_tasks


def test_cancel_stops_scheduled_execution_by_id():
    asyncio.run(_assert_cancel_stops_scheduled_execution_by_id())


async def _assert_cancel_stops_scheduled_execution_by_id():
    executor = AgentExecutor(max_concurrent=1)
    release = asyncio.Event()

    async def handler(agent_id, task):
        await release.wait()
        return "done"

    first_id = await executor.execute("agent-1", {"id": "first"}, handler)
    second_id = await executor.execute("agent-1", {"id": "second"}, handler)

    assert executor.cancel(second_id)
    for _ in range(20):
        result = executor.get_result(second_id)
        if result is not None:
            break
        await asyncio.sleep(0.01)

    assert result["execution_id"] == second_id
    assert result["cancelled"]
    assert second_id not in executor._active_tasks

    release.set()
    await asyncio.wait_for(executor._active_tasks[first_id], timeout=1)
