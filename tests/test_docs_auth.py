import time

from fastapi.testclient import TestClient

from src.api.server import create_app


def create_docs_client(tokens):
    return TestClient(create_app({"docs_auth": {"tokens": tokens}}))


def valid_claims(**overrides):
    claims = {
        "subject": "docs-user",
        "workspace_id": "workspace-1",
        "scopes": ["docs:read"],
        "roles": ["admin"],
        "expires_at": time.time() + 300,
    }
    claims.update(overrides)
    return claims


def test_anonymous_cannot_read_openapi_schema():
    client = create_docs_client({"valid-token": valid_claims()})

    response = client.get("/api/openapi.json")

    assert response.status_code == 401
    assert response.json()["detail"] == "missing_token"


def test_malformed_authorization_header_is_denied():
    client = create_docs_client({"valid-token": valid_claims()})

    response = client.get(
        "/api/openapi.json",
        headers={"Authorization": "Token valid-token"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "malformed_authorization"


def test_stale_token_is_denied():
    client = create_docs_client({"stale-token": valid_claims(stale=True)})

    response = client.get(
        "/api/openapi.json",
        headers={"Authorization": "Bearer stale-token"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "stale_token"


def test_revoked_token_is_denied():
    client = create_docs_client({"revoked-token": valid_claims(revoked=True)})

    response = client.get(
        "/api/openapi.json",
        headers={"Authorization": "Bearer revoked-token"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "revoked_token"


def test_expired_token_is_denied():
    client = create_docs_client(
        {"expired-token": valid_claims(expires_at=time.time() - 1)}
    )

    response = client.get(
        "/api/openapi.json",
        headers={"Authorization": "Bearer expired-token"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "expired_token"


def test_token_without_docs_scope_is_denied():
    client = create_docs_client(
        {"scoped-token": valid_claims(scopes=["agents:read"])}
    )

    response = client.get(
        "/api/openapi.json",
        headers={"Authorization": "Bearer scoped-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "insufficient_scope"


def test_token_without_workspace_role_is_denied():
    client = create_docs_client(
        {"viewer-token": valid_claims(roles=["viewer"])}
    )

    response = client.get(
        "/api/openapi.json",
        headers={"Authorization": "Bearer viewer-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "insufficient_role"


def test_authorized_bearer_can_read_openapi_schema():
    client = create_docs_client({"valid-token": valid_claims()})

    response = client.get(
        "/api/openapi.json",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 200
    assert response.json()["openapi"].startswith("3.")


def test_authorized_browser_session_cookie_can_read_docs():
    client = create_docs_client(
        {"browser-token": valid_claims(roles=["operator"])}
    )

    response = client.get(
        "/api/docs",
        headers={"Cookie": "ao_session=browser-token"},
    )

    assert response.status_code == 200
    assert "Swagger UI" in response.text


def test_legacy_openapi_schema_path_requires_same_auth():
    client = create_docs_client({"valid-token": valid_claims()})

    denied = client.get("/openapi.json")
    allowed = client.get(
        "/openapi.json",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert denied.status_code == 401
    assert allowed.status_code == 200


def test_denial_happens_before_schema_generation():
    config = {"docs_auth": {"tokens": {"valid-token": valid_claims()}}}
    app = create_app(config)

    def fail_openapi():
        raise AssertionError(
            "schema should not be generated for denied principals"
        )

    app.openapi = fail_openapi
    client = TestClient(app)

    response = client.get("/api/openapi.json")

    assert response.status_code == 401
