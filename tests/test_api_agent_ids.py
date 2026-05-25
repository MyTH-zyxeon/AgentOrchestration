from fastapi.testclient import TestClient

from src.agent.registry import AgentRegistry, AgentStatus
from src.api import routes
from src.api.server import create_app


def make_client():
    routes.registry = AgentRegistry()
    return TestClient(create_app())


def auth_headers():
    return {"Authorization": "Bearer test-token"}


def test_mixed_case_agent_id_is_normalized_before_lookup():
    client = make_client()
    agent_id = routes.registry.register("casey", "worker.processor")

    response = client.get(
        f"/api/v2/agents/{agent_id.upper()}",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["id"] == agent_id


def test_mixed_case_agent_id_is_normalized_before_mutation():
    client = make_client()
    agent_id = routes.registry.register("casey", "worker.processor")

    response = client.post(
        f"/api/v2/agents/{agent_id.upper()}/start",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert routes.registry.get(agent_id)["status"] == AgentStatus.RUNNING.value


def test_unauthorized_request_does_not_lookup_or_mutate_agent():
    client = make_client()
    agent_id = routes.registry.register("casey", "worker.processor")

    response = client.post(f"/api/v2/agents/{agent_id.upper()}/start")

    assert response.status_code == 401
    assert routes.registry.get(agent_id)["status"] == AgentStatus.PENDING.value


def test_malformed_agent_id_fails_before_lookup_or_mutation():
    client = make_client()
    agent_id = routes.registry.register("casey", "worker.processor")

    response = client.post(
        "/api/v2/agents/not-a-uuid/start",
        headers=auth_headers(),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Malformed agent ID"
    assert routes.registry.get(agent_id)["status"] == AgentStatus.PENDING.value


def test_static_count_route_is_not_treated_as_agent_lookup():
    client = make_client()
    routes.registry.register("casey", "worker.processor")

    response = client.get("/api/v2/agents/count", headers=auth_headers())
    mixed_case_response = client.get(
        "/api/v2/agents/COUNT",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {"count": 1}
    assert mixed_case_response.status_code == 422
