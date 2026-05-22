import pytest

from src.sdk.client import OrchestratorClient


class RecordingClient(OrchestratorClient):
    def __init__(self):
        super().__init__(base_url="https://example.test", api_key="token")
        self.calls = []

    def _request(self, method, path, data=None):
        self.calls.append((method, path, data))
        return {"ok": True}


def test_register_agent_rejects_empty_name():
    client = RecordingClient()

    with pytest.raises(ValueError, match="Agent name"):
        client.register_agent("", "worker.processor")

    assert client.calls == []


def test_register_agent_rejects_whitespace_name():
    client = RecordingClient()

    with pytest.raises(ValueError, match="Agent name"):
        client.register_agent("   \t\n", "worker.processor")

    assert client.calls == []


def test_register_agent_trims_name_before_request():
    client = RecordingClient()

    result = client.register_agent(
        "  worker-a  ",
        "worker.processor",
        config={"queue": "critical"},
    )

    assert result == {"ok": True}
    assert client.calls == [
        (
            "POST",
            "/agents",
            {
                "name": "worker-a",
                "agent_type": "worker.processor",
                "config": {"queue": "critical"},
            },
        )
    ]
