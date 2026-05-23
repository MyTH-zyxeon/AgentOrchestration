from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.middleware import AuthMiddleware, AutomationAuthPolicy


NOW = 1_700_000_000


def _token(
    kind="user",
    workspace="workspace-a",
    permission="operator",
    token_id="ok",
):
    return f"{kind}:{workspace}:{permission}:{NOW}:{token_id}"


def _client(policy=None):
    app = FastAPI()
    app.add_middleware(
        AuthMiddleware,
        auth_policy=policy or AutomationAuthPolicy(now=lambda: NOW),
    )

    @app.get("/api/v2/agents")
    async def list_agents():
        return {"ok": True}

    @app.post("/api/v2/agents")
    async def create_agent():
        return {"created": True}

    return TestClient(app)


def _headers(token, workspace="workspace-a"):
    return {
        "Authorization": f"Bearer {token}",
        "X-Workspace-ID": workspace,
    }


def test_denies_anonymous_automation_requests():
    response = _client().get("/api/v2/agents")
    assert response.status_code == 401


def test_denies_stale_tokens_before_route_handling():
    stale = f"user:workspace-a:operator:{NOW - 4000}:old-token"
    response = _client().post("/api/v2/agents", headers=_headers(stale))
    assert response.status_code == 401


def test_denies_revoked_tokens_before_route_handling():
    policy = AutomationAuthPolicy(
        revoked_token_ids={"revoked-token"},
        now=lambda: NOW,
    )
    response = _client(policy).post(
        "/api/v2/agents",
        headers=_headers(_token(token_id="revoked-token")),
    )
    assert response.status_code == 401


def test_denies_insufficient_user_role_for_writes():
    response = _client().post(
        "/api/v2/agents",
        headers=_headers(_token(permission="viewer")),
    )
    assert response.status_code == 403


def test_separates_machine_scopes_from_user_roles():
    machine_with_user_role = _token(kind="machine", permission="admin")
    user_with_machine_scope = _token(kind="user", permission="write")

    assert _client().post(
        "/api/v2/agents",
        headers=_headers(machine_with_user_role),
    ).status_code == 401
    assert _client().post(
        "/api/v2/agents",
        headers=_headers(user_with_machine_scope),
    ).status_code == 401


def test_denies_machine_read_scope_for_mutations():
    response = _client().post(
        "/api/v2/agents",
        headers=_headers(_token(kind="machine", permission="read")),
    )
    assert response.status_code == 403


def test_allows_authorized_user_with_workspace_role():
    response = _client().post(
        "/api/v2/agents",
        headers=_headers(_token(permission="operator")),
    )
    assert response.status_code == 200
    assert response.json() == {"created": True}


def test_allows_machine_write_scope_for_automation_clients():
    response = _client().post(
        "/api/v2/agents",
        headers=_headers(_token(kind="machine", permission="write")),
    )
    assert response.status_code == 200
    assert response.json() == {"created": True}


def test_denies_workspace_mismatch():
    response = _client().get(
        "/api/v2/agents",
        headers=_headers(
            _token(workspace="workspace-a"),
            workspace="workspace-b",
        ),
    )
    assert response.status_code == 401
