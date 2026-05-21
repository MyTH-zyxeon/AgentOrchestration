import asyncio

from src.agent.executor import AgentExecutor


async def wait_for_result(executor, execution_id, attempts=10):
    for _ in range(attempts):
        result = executor.get_result(execution_id)
        if result is not None:
            return result
        await asyncio.sleep(0)
    return None


class TestAgentExecutor:
    def test_cancel_stores_terminal_result_for_polling(self):
        async def handler(agent_id, task):
            await asyncio.sleep(60)

        async def run():
            executor = AgentExecutor()
            execution_id = await executor.execute(
                "agent-1",
                {"id": "task-1", "payload": {"secret": "not-for-result"}},
                handler,
            )

            assert executor.get_result(execution_id) is None
            assert executor.cancel(execution_id)

            result = await wait_for_result(executor, execution_id)
            assert result["execution_id"] == execution_id
            assert result["agent_id"] == "agent-1"
            assert result["task_id"] == "task-1"
            assert result["status"] == "cancelled"
            assert "cancelled_at" in result
            assert "payload" not in result

        asyncio.run(run())

    def test_execute_returns_id_before_handler_finishes(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def handler(agent_id, task):
            started.set()
            await release.wait()
            return "done"

        async def run():
            executor = AgentExecutor()
            execution_id = await executor.execute(
                "agent-1",
                {"id": "task-1"},
                handler,
            )

            await started.wait()
            assert executor.get_result(execution_id) is None

            release.set()
            result = await wait_for_result(executor, execution_id)
            assert result["execution_id"] == execution_id
            assert result["result"] == "done"

        asyncio.run(run())
