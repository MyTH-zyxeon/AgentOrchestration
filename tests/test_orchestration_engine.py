import asyncio

from src.orchestrator.engine import OrchestrationEngine


class TestOrchestrationEngine:
    def test_execute_task_uses_pinned_registry_resolution(self):
        engine = OrchestrationEngine()
        first_agent = engine.registry.register("agent-1", "worker.processor")
        second_agent = engine.registry.register("agent-2", "worker.processor")
        results = []

        async def post_execute(task, result):
            results.append((task, result))

        engine.register_hook("post_execute", post_execute)

        asyncio.run(engine._execute_task({
            "id": "task-1",
            "attempt_id": "attempt-1",
            "target_agent": second_agent,
        }))

        assert results[0][1]["output"] == "Task task-1 processed by agent-2"
        assert engine.registry.audit_records()[0]["attempt_id"] == "attempt-1"
        assert engine.registry.audit_records()[0]["agent_id"] == second_agent
        assert engine.registry.resolve_handler("attempt-2", "worker.processor")["id"] == first_agent
