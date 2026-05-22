import pytest
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, Response
from fastapi.testclient import TestClient

from src.api.middleware import SSECompressionGuardMiddleware


def make_client():
    app = FastAPI()
    app.add_middleware(SSECompressionGuardMiddleware)

    @app.get("/events")
    async def events(request: Request):
        assert request.state.sse_compression_guard is True
        return Response("data: ok\n\n", media_type="text/event-stream")

    @app.get("/normal")
    async def normal(request: Request):
        assert request.state.sse_compression_guard is False
        return PlainTextResponse("ok")

    @app.get("/boom")
    async def boom(request: Request):
        assert request.state.sse_compression_guard is True
        raise RuntimeError("boom")

    return TestClient(app)


def test_sse_response_disables_transforming_compression():
    client = make_client()

    response = client.get(
        "/events",
        headers={"Accept": "text/event-stream", "Accept-Encoding": "gzip"},
    )

    assert response.status_code == 200
    assert response.headers["Content-Encoding"] == "identity"
    assert response.headers["X-Accel-Buffering"] == "no"
    assert "no-transform" in response.headers["Cache-Control"]


def test_normal_request_is_not_marked_as_sse():
    client = make_client()

    response = client.get("/normal")

    assert response.status_code == 200
    assert "Content-Encoding" not in response.headers


def test_sse_request_rejects_identity_forbidden_encoding():
    client = make_client()

    response = client.get(
        "/events",
        headers={
            "Accept": "text/event-stream",
            "Accept-Encoding": "gzip, identity;q=0",
        },
    )

    assert response.status_code == 406
    assert response.headers["Content-Encoding"] == "identity"
    assert "no-transform" in response.headers["Cache-Control"]


def test_sse_request_allows_explicit_identity_over_wildcard_reject():
    client = make_client()

    response = client.get(
        "/events",
        headers={
            "Accept": "text/event-stream",
            "Accept-Encoding": "identity;q=1, *;q=0",
        },
    )

    assert response.status_code == 200
    assert response.headers["Content-Encoding"] == "identity"


def test_sse_guard_clears_request_state_on_exception():
    client = make_client()

    with pytest.raises(RuntimeError):
        client.get("/boom", headers={"Accept": "text/event-stream"})
