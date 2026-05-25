import pytest

from src.agent.runtime import AgentRuntime


class FakeProcess:
    pid = 12345

    def __init__(self):
        self._poll = None

    def poll(self):
        return self._poll


class TestAgentRuntime:
    def test_start_rejects_reserved_agent_id_before_launch(self, monkeypatch):
        launched = []

        def fake_popen(*args, **kwargs):
            launched.append((args, kwargs))
            return FakeProcess()

        monkeypatch.setattr("src.agent.runtime.subprocess.Popen", fake_popen)
        runtime = AgentRuntime()

        with pytest.raises(ValueError) as error:
            runtime.start(
                "agent-a",
                ["python", "-m", "worker"],
                env={"AO_AGENT_ID": "agent-b"},
            )

        assert "AO_AGENT_ID" in str(error.value)
        assert launched == []

    def test_start_rejects_reserved_mode_before_launch(self, monkeypatch):
        launched = []

        def fake_popen(*args, **kwargs):
            launched.append((args, kwargs))
            return FakeProcess()

        monkeypatch.setattr("src.agent.runtime.subprocess.Popen", fake_popen)
        runtime = AgentRuntime()

        with pytest.raises(ValueError) as error:
            runtime.start(
                "agent-a",
                ["python", "-m", "worker"],
                env={"AO_AGENT_MODE": "debug"},
            )

        assert "AO_AGENT_MODE" in str(error.value)
        assert launched == []

    def test_start_allows_non_reserved_env(self, monkeypatch):
        launched = []

        def fake_popen(*args, **kwargs):
            launched.append((args, kwargs))
            return FakeProcess()

        monkeypatch.setattr("src.agent.runtime.subprocess.Popen", fake_popen)
        runtime = AgentRuntime()

        assert runtime.start(
            "agent-a",
            ["python", "-m", "worker"],
            env={"WORKER_TIMEOUT": "30"},
        )

        env = launched[0][1]["env"]
        assert env["WORKER_TIMEOUT"] == "30"
        assert env["AO_AGENT_ID"] == "agent-a"
