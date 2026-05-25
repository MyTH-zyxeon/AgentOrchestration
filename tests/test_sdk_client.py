import json
import socket
from unittest.mock import patch

import pytest

from src.sdk.client import DEFAULT_REQUEST_TIMEOUT, OrchestratorClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_request_uses_default_timeout():
    client = OrchestratorClient(
        base_url="https://example.test",
        api_key="test-key",
    )

    with patch(
        "src.sdk.client.urlopen",
        return_value=FakeResponse({"ok": True}),
    ) as urlopen:
        assert client.list_agents() == {"ok": True}

    request = urlopen.call_args.args[0]
    assert request.full_url == "https://example.test/api/v2/agents"
    assert urlopen.call_args.kwargs["timeout"] == DEFAULT_REQUEST_TIMEOUT


def test_request_uses_custom_timeout():
    client = OrchestratorClient(
        base_url="https://example.test",
        api_key="test-key",
        timeout=2.5,
    )

    with patch(
        "src.sdk.client.urlopen",
        return_value=FakeResponse({"id": "agent-1"}),
    ) as urlopen:
        assert client.get_agent("agent-1") == {"id": "agent-1"}

    assert urlopen.call_args.kwargs["timeout"] == 2.5


def test_request_timeout_can_be_configured_from_environment(monkeypatch):
    monkeypatch.setenv("AO_REQUEST_TIMEOUT", "7.25")

    client = OrchestratorClient(
        base_url="https://example.test",
        api_key="test-key",
    )

    with patch(
        "src.sdk.client.urlopen",
        return_value=FakeResponse({"ok": True}),
    ) as urlopen:
        assert client.list_agents() == {"ok": True}

    assert client.timeout == 7.25
    assert urlopen.call_args.kwargs["timeout"] == 7.25


@pytest.mark.parametrize("timeout", [0, -1, float("inf")])
def test_request_timeout_must_be_positive_and_finite(timeout):
    with pytest.raises(ValueError, match="positive finite"):
        OrchestratorClient(timeout=timeout)


def test_socket_timeout_propagates_to_caller():
    client = OrchestratorClient(
        base_url="https://example.test",
        api_key="test-key",
        timeout=1.0,
    )

    with patch("src.sdk.client.urlopen", side_effect=socket.timeout):
        with pytest.raises(socket.timeout):
            client.list_agents()
