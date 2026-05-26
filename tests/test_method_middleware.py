import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.api.middleware import MethodMiddleware
from src.api.server import create_app


def test_trace_is_rejected_before_authentication():
    app = create_app()
    client = TestClient(app)

    response = client.request("TRACE", "/api/v2/agents")

    assert response.status_code == 405
    assert response.text == "Method Not Allowed"
    assert "GET" in response.headers["allow"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_normal_requests_continue_through_stack():
    app = FastAPI()
    app.add_middleware(MethodMiddleware)

    @app.get("/ok")
    async def ok(request: Request):
        assert request.state.method_middleware_checked is True
        return {"status": "ok"}

    client = TestClient(app)

    response = client.get("/ok")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_exception_path_clears_request_state():
    app = FastAPI()
    seen_scopes = []
    app.add_middleware(MethodMiddleware)

    @app.get("/boom")
    async def boom(request: Request):
        seen_scopes.append(request.scope)
        assert request.state.method_middleware_checked is True
        raise RuntimeError("boom")

    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/boom")

    assert response.status_code == 500
    assert seen_scopes[0].get("state", {}) == {}


@pytest.mark.parametrize("method", ["CONNECT", "BREW"])
def test_unsupported_methods_are_rejected(method):
    app = FastAPI()
    app.add_middleware(MethodMiddleware)

    @app.api_route(
        "/ok",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    )
    async def ok():
        return {"status": "ok"}

    client = TestClient(app)

    response = client.request(method, "/ok")

    assert response.status_code == 405
    assert response.text == "Method Not Allowed"
