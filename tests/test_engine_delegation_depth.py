import asyncio

from src.agent import AgentStatus
from src.orchestrator.engine import (
    DelegationDepthError,
    OrchestrationEngine,
)


def make_task(task_id, agent_id, depth=0):
    return {
        "id": task_id,
        "target_agent": agent_id,
        "delegation_depth": depth,
    }


def test_task_below_delegation_limit_executes_and_records_outcome():
    engine = OrchestrationEngine(max_delegation_depth=2)
    agent_id = engine.registry.register("worker", "worker.processor")

    asyncio.run(engine._execute_task(make_task("task-1", agent_id, depth=1)))

    assert engine.get_task_outcome("task-1")["status"] == "completed"
    assert engine.registry.get(agent_id)["status"] == AgentStatus.PAUSED.value
    assert engine.list_transitions()[0] == {
        "task_id": "task-1",
        "decision": "delegation_reserved",
        "reason": "within_limit",
        "delegation_depth": 1,
    }


def test_task_at_delegation_limit_is_rejected_before_side_effects():
    engine = OrchestrationEngine(max_delegation_depth=2)
    agent_id = engine.registry.register("worker", "worker.processor")
    pre_execute_calls = []
    errors = []

    async def pre_execute(task):
        pre_execute_calls.append(task["id"])

    async def on_error(task, error):
        errors.append((task["id"], error))

    engine.register_hook("pre_execute", pre_execute)
    engine.register_hook("on_error", on_error)

    asyncio.run(engine._execute_task(make_task("task-2", agent_id, depth=2)))

    assert pre_execute_calls == []
    assert isinstance(errors[0][1], DelegationDepthError)
    assert engine.get_task_outcome("task-2") == {
        "task_id": "task-2",
        "status": "rejected",
        "reason": "delegation_depth_exceeded",
    }
    assert engine.registry.get(agent_id)["status"] == AgentStatus.PENDING.value


def test_retry_after_terminal_outcome_does_not_execute_again():
    engine = OrchestrationEngine(max_delegation_depth=2)
    agent_id = engine.registry.register("worker", "worker.processor")
    calls = []

    async def run_agent_task(agent, task):
        calls.append(task["id"])
        return {"status": "completed"}

    engine._run_agent_task = run_agent_task
    task = make_task("task-3", agent_id, depth=1)

    asyncio.run(engine._execute_task(task))
    asyncio.run(engine._execute_task(task))

    assert calls == ["task-3"]
    assert engine.get_task_outcome("task-3")["status"] == "completed"
    assert engine.list_transitions()[-1] == {
        "task_id": "task-3",
        "decision": "duplicate_ignored",
        "reason": "completed",
    }


def test_malformed_delegation_depth_fails_closed_before_execution():
    engine = OrchestrationEngine(max_delegation_depth=2)
    agent_id = engine.registry.register("worker", "worker.processor")
    errors = []

    async def on_error(task, error):
        errors.append(error)

    engine.register_hook("on_error", on_error)

    asyncio.run(engine._execute_task(make_task("task-4", agent_id, depth="x")))

    assert isinstance(errors[0], DelegationDepthError)
    assert engine.get_task_outcome("task-4") == {
        "task_id": "task-4",
        "status": "rejected",
        "reason": "invalid_delegation_depth",
    }
    assert engine.registry.get(agent_id)["status"] == AgentStatus.PENDING.value
