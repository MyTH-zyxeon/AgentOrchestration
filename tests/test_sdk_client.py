import pytest

from src.sdk.client import OrchestratorClient


class RecordingClient(OrchestratorClient):
    def __init__(self):
        super().__init__(base_url="https://example.test", api_key="token")
        self.calls = []

    def _request(self, method, path, data=None):
        self.calls.append((method, path, data))
        return {"ok": True}


def test_register_agent_maps_none_config_to_empty_object():
    client = RecordingClient()

    result = client.register_agent("worker", "worker.processor")

    assert result == {"ok": True}
    assert client.calls == [
        (
            "POST",
            "/agents",
            {
                "name": "worker",
                "agent_type": "worker.processor",
                "config": {},
            },
        )
    ]


def test_register_agent_accepts_mapping_config():
    client = RecordingClient()

    client.register_agent(
        "worker",
        "worker.processor",
        config={"retries": 3},
    )

    assert client.calls[0][2]["config"] == {"retries": 3}


@pytest.mark.parametrize("invalid_config", [["bad"], "bad"])
def test_register_agent_rejects_non_mapping_config(invalid_config):
    client = RecordingClient()

    with pytest.raises(TypeError, match="config must be a mapping"):
        client.register_agent(
            "worker",
            "worker.processor",
            config=invalid_config,
        )

    assert client.calls == []
