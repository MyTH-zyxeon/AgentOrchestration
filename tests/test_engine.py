import asyncio

from src.orchestrator.engine import OrchestrationEngine


def test_engine_records_completion_before_success_hooks():
    async def run_test():
        engine = OrchestrationEngine()
        agent_id = engine.registry.register("agent", "worker.processor")
        task_id = engine.scheduler.enqueue({"target_agent": agent_id})
        task = await engine.scheduler.dequeue()
        observed = []

        async def post_execute(task, result):
            observed.append(engine.scheduler.get_terminal_outcome(task["id"]))

        async def on_complete(task, result):
            observed.append(engine.scheduler.get_terminal_outcome(task["id"]))

        engine.register_hook("post_execute", post_execute)
        engine.register_hook("on_complete", on_complete)

        await engine._execute_task(task)

        outcome = engine.scheduler.get_terminal_outcome(task_id)
        assert outcome["status"] == "completed"
        assert outcome["result"]["status"] == "completed"
        observed_statuses = [item["status"] for item in observed]
        assert observed_statuses == ["completed", "completed"]

    asyncio.run(run_test())
