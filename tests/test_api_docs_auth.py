from fastapi.testclient import TestClient

from src.api.server import create_app


def docs_client():
    return TestClient(create_app())


class TestDocumentationAuth:
    def test_openapi_schema_denies_anonymous_clients(self):
        response = docs_client().get("/api/openapi.json")

        assert response.status_code == 401

    def test_swagger_docs_denies_anonymous_clients(self):
        response = docs_client().get("/api/docs")

        assert response.status_code == 401

    def test_openapi_schema_denies_revoked_tokens(self):
        response = docs_client().get(
            "/api/openapi.json",
            headers={
                "Authorization": "Bearer revoked",
                "X-AO-Scopes": "docs:read",
            },
        )

        assert response.status_code == 401

    def test_openapi_schema_denies_insufficient_scope(self):
        response = docs_client().get(
            "/api/openapi.json",
            headers={
                "Authorization": "Bearer valid-token",
                "X-AO-Scopes": "agents:read",
            },
        )

        assert response.status_code == 403

    def test_openapi_schema_allows_docs_scope(self):
        response = docs_client().get(
            "/api/openapi.json",
            headers={
                "Authorization": "Bearer valid-token",
                "X-AO-Scopes": "agents:read docs:read",
            },
        )

        assert response.status_code == 200
        assert response.json()["info"]["title"] == "Agent Orchestrator API"

    def test_health_remains_public(self):
        response = docs_client().get("/health")

        assert response.status_code == 200
