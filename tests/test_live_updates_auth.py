import time

import pytest
from fastapi.testclient import TestClient

from src.api.routes import live_update_auth
from src.api.server import create_app
from src.common.live_updates_auth import (
    LiveUpdateAuthError,
    LiveUpdateAuthService,
    LiveUpdateCredential,
)


def credential(**overrides):
    data = {
        "principal_id": "user-1",
        "workspace_id": "workspace-1",
        "roles": {"operator"},
        "scopes": {"live_updates:mint"},
        "expires_at": time.time() + 60,
        "not_before": 0.0,
        "revoked": False,
    }
    data.update(overrides)
    return LiveUpdateCredential(**data)


def test_bearer_client_can_mint_live_update_token():
    service = LiveUpdateAuthService(token_ttl_seconds=120)
    service.register_bearer_token("good-token", credential())

    token = service.mint_websocket_token(
        workspace_id="workspace-1",
        authorization_header="Bearer good-token",
        now=1000.0,
    )

    assert token.token.startswith("wst_")
    assert token.principal_id == "user-1"
    assert token.workspace_id == "workspace-1"
    assert token.expires_at == 1120.0


@pytest.mark.parametrize(
    "bad_credential",
    [
        credential(expires_at=time.time() - 1),
        credential(revoked=True),
        credential(principal_id=""),
        credential(roles={"viewer"}),
        credential(scopes={"agents:read"}),
        credential(not_before=time.time() + 60),
    ],
)
def test_invalid_principals_fail_closed_before_token_mint(bad_credential):
    service = LiveUpdateAuthService()
    service.register_bearer_token("bad-token", bad_credential)

    with pytest.raises(LiveUpdateAuthError):
        service.mint_websocket_token(
            workspace_id="workspace-1",
            authorization_header="Bearer bad-token",
        )


def test_workspace_mismatch_is_denied():
    service = LiveUpdateAuthService()
    service.register_bearer_token("good-token", credential())

    with pytest.raises(LiveUpdateAuthError):
        service.mint_websocket_token(
            workspace_id="other-workspace",
            authorization_header="Bearer good-token",
        )


def test_malformed_or_missing_credentials_are_denied():
    service = LiveUpdateAuthService()

    with pytest.raises(LiveUpdateAuthError):
        service.mint_websocket_token(
            workspace_id="workspace-1",
            authorization_header="Basic wrong",
        )

    with pytest.raises(LiveUpdateAuthError):
        service.mint_websocket_token(workspace_id="workspace-1")


def test_browser_session_can_mint_live_update_token():
    service = LiveUpdateAuthService()
    service.register_browser_session("session-1", credential())

    token = service.mint_websocket_token(
        workspace_id="workspace-1",
        browser_session="session-1",
    )

    assert token.principal_id == "user-1"


def test_live_update_token_endpoint_denies_anonymous_request():
    live_update_auth.reset()
    client = TestClient(create_app())

    response = client.post(
        "/api/v2/live-updates/token",
        json={"workspace_id": "workspace-1"},
    )

    assert response.status_code == 401


def test_live_update_token_endpoint_accepts_authorized_bearer():
    live_update_auth.reset()
    live_update_auth.register_bearer_token("api-token", credential())
    client = TestClient(create_app())

    response = client.post(
        "/api/v2/live-updates/token",
        json={"workspace_id": "workspace-1"},
        headers={"Authorization": "Bearer api-token"},
    )

    assert response.status_code == 200
    assert response.json()["workspace_id"] == "workspace-1"


def test_live_update_token_endpoint_accepts_browser_session():
    live_update_auth.reset()
    live_update_auth.register_browser_session("session-1", credential())
    client = TestClient(create_app())
    client.cookies.set("ao_session", "session-1")

    response = client.post(
        "/api/v2/live-updates/token",
        json={"workspace_id": "workspace-1"},
    )

    assert response.status_code == 200
    assert response.json()["principal_id"] == "user-1"
