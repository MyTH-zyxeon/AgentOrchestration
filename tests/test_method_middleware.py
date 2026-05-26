import asyncio
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response

from src.api.middleware import MethodGuardMiddleware
from src.api.server import create_app


def make_request(method="GET"):
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/probe",
            "headers": [],
        }
    )


def test_trace_is_rejected_before_application_handler(caplog):
    called = []
    app = FastAPI()
    app.add_middleware(MethodGuardMiddleware)

    @app.api_route("/probe", methods=["TRACE"])
    async def probe():
        called.append(True)
        return {"status": "should-not-run"}

    client = TestClient(app)

    with caplog.at_level(logging.WARNING, logger="src.api.middleware"):
        response = client.request(
            "TRACE",
            "/probe",
            headers={"X-Private-Token": "secret-value"},
        )

    assert response.status_code == 405
    assert response.text == "Method Not Allowed"
    assert response.headers["X-Method-Guard"] == "blocked"
    assert "TRACE" not in response.headers["Allow"]
    assert called == []
    assert "TRACE" in caplog.text
    assert "secret-value" not in caplog.text


def test_normal_request_passes_with_safe_guard_header():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-Method-Guard"] == "passed"


def test_rejected_request_cleans_method_guard_state():
    middleware = MethodGuardMiddleware(lambda scope, receive, send: None)
    request = make_request("TRACE")
    called = False

    async def call_next(unused_request):
        nonlocal called
        called = True
        return Response("unexpected")

    response = asyncio.run(middleware.dispatch(request, call_next))

    assert response.status_code == 405
    assert called is False
    assert "method_guard" not in request.state._state


def test_success_path_cleans_method_guard_state():
    middleware = MethodGuardMiddleware(lambda scope, receive, send: None)
    request = make_request("GET")

    async def call_next(next_request):
        assert next_request.state.method_guard["method"] == "GET"
        return Response("ok")

    response = asyncio.run(middleware.dispatch(request, call_next))

    assert response.status_code == 200
    assert response.headers["X-Method-Guard"] == "passed"
    assert "method_guard" not in request.state._state


def test_exception_path_cleans_method_guard_state():
    middleware = MethodGuardMiddleware(lambda scope, receive, send: None)
    request = make_request("POST")

    async def call_next(next_request):
        assert next_request.state.method_guard["method"] == "POST"
        raise RuntimeError("downstream failure")

    try:
        asyncio.run(middleware.dispatch(request, call_next))
    except RuntimeError as exc:
        assert str(exc) == "downstream failure"

    assert "method_guard" not in request.state._state
