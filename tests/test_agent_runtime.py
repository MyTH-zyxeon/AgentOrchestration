from src.agent.runtime import AgentRuntime, RuntimeState


class DummyProcess:
    pid = 12345

    def __init__(self):
        self.signals = []
        self.killed = False
        self.waited = False

    def poll(self):
        return None

    def send_signal(self, sig):
        self.signals.append(sig)

    def wait(self, timeout=None):
        self.waited = True

    def kill(self):
        self.killed = True


def test_start_isolates_agent_environment_from_ambient_agent_vars(monkeypatch):
    spawned = []

    def fake_popen(command, env, stdout, stderr):
        spawned.append(dict(env))
        return DummyProcess()

    monkeypatch.setenv("SHARED_SETTING", "base")
    monkeypatch.setenv("AO_AGENT_ID", "ambient-agent")
    monkeypatch.setenv("AO_AGENT_TOKEN", "ambient-token")
    monkeypatch.setattr("subprocess.Popen", fake_popen)

    runtime = AgentRuntime()

    assert runtime.start(
        "agent-a",
        ["worker"],
        env={"AO_AGENT_TOKEN": "token-a"},
    )
    assert runtime.start(
        "agent-b",
        ["worker"],
        env={"AGENT_SECRET": "secret-b"},
    )

    env_a = spawned[0]
    env_b = spawned[1]
    assert env_a["AO_AGENT_ID"] == "agent-a"
    assert env_a["AO_AGENT_TOKEN"] == "token-a"
    assert env_a["SHARED_SETTING"] == "base"
    assert env_b["AO_AGENT_ID"] == "agent-b"
    assert "AO_AGENT_TOKEN" not in env_b
    assert env_b["AGENT_SECRET"] == "secret-b"
    assert runtime.get_environment("agent-a")["AO_AGENT_TOKEN"] == "token-a"


def test_start_rejects_non_string_environment_before_spawn(monkeypatch):
    spawned = []

    def fake_popen(command, env, stdout, stderr):
        spawned.append(env)
        return DummyProcess()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    runtime = AgentRuntime()

    assert not runtime.start("agent-a", ["worker"], env={"LIMIT": 5})
    assert spawned == []
    assert runtime.get_state("agent-a") is RuntimeState.CRASHED


def test_environment_snapshot_is_not_mutated_after_start(monkeypatch):
    spawned = []

    def fake_popen(command, env, stdout, stderr):
        spawned.append(dict(env))
        return DummyProcess()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    runtime = AgentRuntime()
    agent_env = {"AGENT_SECRET": "initial"}

    assert runtime.start("agent-a", ["worker"], env=agent_env)
    agent_env["AGENT_SECRET"] = "changed"

    assert spawned[0]["AGENT_SECRET"] == "initial"
    assert runtime.get_environment("agent-a")["AGENT_SECRET"] == "initial"
