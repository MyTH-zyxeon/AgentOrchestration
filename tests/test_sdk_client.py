from src.sdk import client as client_module
from src.sdk.client import OrchestratorClient


class _FakeResponse:
    def __init__(self, body=b"", status=200):
        self._body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def getcode(self):
        return self.status

    def read(self):
        return self._body


def test_delete_agent_returns_empty_result_for_204(monkeypatch):
    seen = {}

    def fake_urlopen(req):
        seen["method"] = req.get_method()
        seen["url"] = req.full_url
        return _FakeResponse(status=204)

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    client = OrchestratorClient(
        base_url="https://orchestrator.example",
        api_key="token",
    )

    assert client.delete_agent("agent-123") == {}
    assert seen == {
        "method": "DELETE",
        "url": "https://orchestrator.example/api/v2/agents/agent-123",
    }


def test_empty_success_body_returns_empty_result(monkeypatch):
    def fake_urlopen(req):
        return _FakeResponse(body=b" \n\t", status=200)

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    client = OrchestratorClient(
        base_url="https://orchestrator.example",
        api_key="token",
    )

    assert client.stop_agent("agent-123") == {}


def test_json_success_body_still_decodes(monkeypatch):
    def fake_urlopen(req):
        return _FakeResponse(body=b'{"ok": true}', status=200)

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    client = OrchestratorClient(
        base_url="https://orchestrator.example",
        api_key="token",
    )

    assert client.get_agent("agent-123") == {"ok": True}
