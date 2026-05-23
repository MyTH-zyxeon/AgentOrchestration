import importlib.util
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "api" / "middleware.py"
)
SPEC = importlib.util.spec_from_file_location("api_middleware", MODULE_PATH)
api_middleware = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(api_middleware)

RequestContextMiddleware = api_middleware.RequestContextMiddleware
get_active_role = api_middleware.get_active_role
get_correlation_id = api_middleware.get_correlation_id
get_request_id = api_middleware.get_request_id
get_workspace_id = api_middleware.get_workspace_id


class ScopeAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            workspace = headers.get(b"x-auth-workspace-id")
            role = headers.get(b"x-auth-role")
            if workspace:
                scope["auth_workspace_id"] = workspace.decode()
            if role:
                scope["auth_role"] = role.decode()
        await self.app(scope, receive, send)


def build_client(raise_server_exceptions=True):
    app = FastAPI()

    @app.get("/context")
    async def context():
        return {
            "correlation_id": get_correlation_id(),
            "request_id": get_request_id(),
            "workspace_id": get_workspace_id(),
            "active_role": get_active_role(),
        }

    @app.get("/boom")
    async def boom():
        raise RuntimeError("boom")

    return TestClient(
        ScopeAuthMiddleware(RequestContextMiddleware(app)),
        raise_server_exceptions=raise_server_exceptions,
    )


def test_authenticated_context_wins_and_is_echoed():
    client = build_client()

    response = client.get(
        "/context",
        headers={
            "x-auth-workspace-id": "tenant-a",
            "x-auth-role": "admin",
            "x-workspace-id": "tenant-a",
            "x-role": "admin",
            "x-correlation-id": "corr-a",
            "x-request-id": "req-a",
        },
    )

    assert response.status_code == 200
    assert response.headers["x-correlation-id"] == "corr-a"
    assert response.headers["x-request-id"] == "req-a"
    assert response.json() == {
        "correlation_id": "corr-a",
        "request_id": "req-a",
        "workspace_id": "tenant-a",
        "active_role": "admin",
    }


def test_rejects_workspace_mismatch_before_handler():
    client = build_client()

    response = client.get(
        "/context",
        headers={
            "x-auth-workspace-id": "tenant-a",
            "x-auth-role": "admin",
            "x-workspace-id": "tenant-b",
            "x-correlation-id": "corr-mismatch",
            "x-request-id": "req-mismatch",
        },
    )

    assert response.status_code == 403
    assert response.text == "Workspace context mismatch"
    assert response.headers["x-correlation-id"] == "corr-mismatch"
    assert response.headers["x-request-id"] == "req-mismatch"


def test_context_is_reset_after_exception_path():
    client = build_client(raise_server_exceptions=False)

    assert client.get(
        "/boom",
        headers={
            "x-auth-workspace-id": "tenant-a",
            "x-auth-role": "admin",
            "x-correlation-id": "corr-a",
        },
    ).status_code == 500

    response = client.get(
        "/context",
        headers={
            "x-auth-workspace-id": "tenant-b",
            "x-auth-role": "operator",
            "x-correlation-id": "corr-b",
            "x-request-id": "req-b",
        },
    )

    assert response.status_code == 200
    assert response.json()["correlation_id"] == "corr-b"
    assert response.json()["workspace_id"] == "tenant-b"
    assert response.json()["active_role"] == "operator"
