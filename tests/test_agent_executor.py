import asyncio

import pytest

from src.agent import executor as executor_module
from src.agent.executor import AgentExecutor


async def _handler(agent_id, task):
    return {"agent_id": agent_id, "task_id": task["id"]}


def _execute(executor, task_id):
    return asyncio.run(executor.execute("agent-1", {"id": task_id}, _handler))


def test_results_are_bounded_by_max_results():
    executor = AgentExecutor(max_results=2)

    first = _execute(executor, "first")
    second = _execute(executor, "second")
    third = _execute(executor, "third")

    assert executor.get_result(first) is None
    assert executor.get_result(second)["task_id"] == "second"
    assert executor.get_result(third)["task_id"] == "third"
    assert len(executor._results) == 2


def test_results_expire_by_ttl(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(executor_module.time, "time", lambda: now[0])
    executor = AgentExecutor(max_results=10, result_ttl_seconds=5.0)

    execution_id = _execute(executor, "ttl")
    assert executor.get_result(execution_id)["task_id"] == "ttl"

    now[0] = 106.0

    assert executor.get_result(execution_id) is None
    assert len(executor._results) == 0


def test_shutdown_clears_completed_results():
    executor = AgentExecutor(max_results=10)
    execution_id = _execute(executor, "shutdown")
    assert executor.get_result(execution_id) is not None

    asyncio.run(executor.shutdown())

    assert executor.get_result(execution_id) is None
    assert executor._results == {}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_results": 0},
        {"max_results": -1},
        {"max_results": True},
        {"result_ttl_seconds": 0},
        {"result_ttl_seconds": -1},
        {"result_ttl_seconds": False},
    ],
)
def test_result_retention_options_validate_positive_values(kwargs):
    with pytest.raises(ValueError):
        AgentExecutor(**kwargs)
