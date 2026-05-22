from fastapi.testclient import TestClient

from src.api.server import create_app


def api_key_headers(**overrides):
    headers = {
        "Authorization": "Bearer active-token",
        "X-Principal-State": "active",
        "X-Auth-Scopes": "api_keys:write",
        "X-Workspace-Role": "admin",
        "X-Workspace-Id": "workspace-1",
        "X-MFA-Challenge": "verified",
        "X-Client-Type": "token",
    }
    headers.update(overrides)
    return headers


def create_api_key(client, headers):
    return client.post(
        "/api/v2/api-keys",
        params={"name": "deploy-key", "workspace_id": "workspace-1"},
        headers=headers,
    )


def test_privileged_api_key_creation_denies_anonymous_principal():
    client = TestClient(create_app())

    response = create_api_key(client, {})

    assert response.status_code == 401
    assert response.text == "missing_bearer_token"


def test_privileged_api_key_creation_denies_stale_and_revoked_principals():
    client = TestClient(create_app())

    stale = create_api_key(
        client,
        api_key_headers(**{"X-Principal-State": "stale"}),
    )
    revoked = create_api_key(
        client,
        api_key_headers(**{"X-Principal-State": "revoked"}),
    )

    assert stale.status_code == 401
    assert stale.text == "stale_principal"
    assert revoked.status_code == 401
    assert revoked.text == "revoked_principal"


def test_privileged_api_key_creation_requires_scope_role_and_mfa():
    client = TestClient(create_app())

    scoped = create_api_key(
        client,
        api_key_headers(**{"X-Auth-Scopes": "agents:read"}),
    )
    role = create_api_key(
        client,
        api_key_headers(**{"X-Workspace-Role": "viewer"}),
    )
    mfa = create_api_key(
        client,
        api_key_headers(**{"X-MFA-Challenge": "required"}),
    )

    assert scoped.status_code == 403
    assert scoped.text == "insufficient_scope"
    assert role.status_code == 403
    assert role.text == "insufficient_workspace_role"
    assert mfa.status_code == 403
    assert mfa.text == "mfa_challenge_required"


def test_privileged_api_key_creation_requires_matching_workspace():
    client = TestClient(create_app())

    response = create_api_key(
        client,
        api_key_headers(**{"X-Workspace-Id": "workspace-2"}),
    )

    assert response.status_code == 403
    assert response.text == "workspace_mismatch"


def test_privileged_api_key_creation_allows_browser_or_token_client():
    client = TestClient(create_app())

    token_response = create_api_key(client, api_key_headers())
    browser_response = create_api_key(
        client,
        api_key_headers(**{"X-Client-Type": "browser"}),
    )

    assert token_response.status_code == 200
    assert token_response.json()["status"] == "created"
    assert token_response.json()["client_type"] == "token"
    assert browser_response.status_code == 200
    assert browser_response.json()["client_type"] == "browser"
