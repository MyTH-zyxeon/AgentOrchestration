import asyncio

import pytest

from src.agent.executor import AgentExecutor


async def value_handler(agent_id, task):
    return task["value"]


def test_executor_evicts_oldest_results_when_max_results_reached():
    async def run_tasks():
        executor = AgentExecutor(max_results=2)
        first_id = await executor.execute(
            "agent-1",
            {"id": "first", "value": 1},
            value_handler,
        )
        second_id = await executor.execute(
            "agent-1",
            {"id": "second", "value": 2},
            value_handler,
        )
        third_id = await executor.execute(
            "agent-1",
            {"id": "third", "value": 3},
            value_handler,
        )
        return executor, first_id, second_id, third_id

    executor, first_id, second_id, third_id = asyncio.run(run_tasks())

    assert executor.get_result(first_id) is None
    assert executor.get_result(second_id)["result"] == 2
    assert executor.get_result(third_id)["result"] == 3
    assert len(executor._results) == 2


def test_executor_rejects_invalid_max_results():
    with pytest.raises(ValueError, match="max_results"):
        AgentExecutor(max_results=0)
