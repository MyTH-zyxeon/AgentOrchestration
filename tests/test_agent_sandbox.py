import subprocess
import sys

from src.agent.runtime import AgentRuntime, RuntimeState
from src.agent import sandbox as sandbox_module
from src.agent.sandbox import AgentSandbox, ResourceLimits


def test_apply_limits_records_agent_limits_without_parent_rlimit(monkeypatch):
    calls = []

    def fail_parent_rlimit(*args):
        calls.append(args)

    if sandbox_module.resource is not None:
        monkeypatch.setattr("src.agent.sandbox.resource.setrlimit", fail_parent_rlimit)

    sandbox = AgentSandbox()
    limits = ResourceLimits(cpu_time=5, memory_mb=64)
    sandbox.apply_limits("agent-1", limits)

    assert sandbox.get_limits("agent-1") is limits
    assert calls == []


def test_runtime_applies_limits_at_child_process_boundary(monkeypatch):
    popen_calls = []

    class FakeProcess:
        pid = 12345

        def poll(self):
            return None

    def fake_popen(command, **kwargs):
        popen_calls.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr("src.agent.runtime.subprocess.Popen", fake_popen)

    runtime = AgentRuntime()
    limits = ResourceLimits(cpu_time=5, memory_mb=64)

    assert runtime.start("agent-1", ["python", "-m", "worker"], limits=limits)
    assert runtime.get_state("agent-1") is RuntimeState.RUNNING
    if sandbox_module.resource is None:
        assert "preexec_fn" not in popen_calls[0][1]
    else:
        assert popen_calls[0][1]["preexec_fn"] is not None


def test_resource_limits_apply_in_child_without_mutating_parent():
    if sandbox_module.resource is None:
        return

    parent_cpu = sandbox_module.resource.getrlimit(sandbox_module.resource.RLIMIT_CPU)
    parent_memory = sandbox_module.resource.getrlimit(sandbox_module.resource.RLIMIT_AS)

    limits = ResourceLimits(cpu_time=7, memory_mb=2048)
    script = "\n".join(
        [
            "import resource",
            "print(resource.getrlimit(resource.RLIMIT_CPU)[0])",
        ]
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=limits.as_preexec_fn(),
    )

    child_cpu = int(result.stdout.strip())
    assert child_cpu == 7
    assert sandbox_module.resource.getrlimit(sandbox_module.resource.RLIMIT_CPU) == parent_cpu
    assert sandbox_module.resource.getrlimit(sandbox_module.resource.RLIMIT_AS) == parent_memory
