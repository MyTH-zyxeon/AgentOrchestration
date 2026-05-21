import json

from src.sdk import client as sdk_client
from src.sdk.client import OrchestratorClient


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps({"ok": True}).encode()


def capture_request(monkeypatch):
    captured = {}

    def fake_urlopen(request):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["headers"] = dict(request.header_items())
        captured["data"] = request.data
        return FakeResponse()

    monkeypatch.setattr(sdk_client, "urlopen", fake_urlopen)
    return captured


class TestOrchestratorClientUrls:
    def test_base_url_trailing_slash_is_normalized(self, monkeypatch):
        captured = capture_request(monkeypatch)
        client = OrchestratorClient(
            base_url="https://example.test/",
            api_key="test-key",
        )

        assert client.list_agents() == {"ok": True}

        assert captured["url"] == "https://example.test/api/v2/agents"
        assert "//api/v2" not in captured["url"]

    def test_environment_base_url_trailing_slash_is_normalized(
        self,
        monkeypatch,
    ):
        captured = capture_request(monkeypatch)
        monkeypatch.setenv("AO_API_URL", "https://env.example.test/")
        client = OrchestratorClient(api_key="test-key")

        client.get_agent("agent-1")

        assert captured["url"] == (
            "https://env.example.test/api/v2/agents/agent-1"
        )

    def test_request_accepts_path_without_leading_slash(
        self,
        monkeypatch,
    ):
        captured = capture_request(monkeypatch)
        client = OrchestratorClient(
            base_url="https://example.test/",
            api_key="test-key",
        )

        client._request("GET", "agents")

        assert captured["url"] == "https://example.test/api/v2/agents"

    def test_query_string_is_preserved_after_canonical_api_prefix(
        self,
        monkeypatch,
    ):
        captured = capture_request(monkeypatch)
        client = OrchestratorClient(
            base_url="https://example.test/",
            api_key="test-key",
        )

        client.list_agents(status="running")

        assert captured["url"] == (
            "https://example.test/api/v2/agents?status=running"
        )
