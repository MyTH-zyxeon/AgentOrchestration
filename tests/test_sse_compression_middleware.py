import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import PlainTextResponse, Response

from src.api.middleware import (
    SSECompressionMiddleware,
    current_sse_compression_policy,
)


def create_test_app():
    app = FastAPI()
    app.add_middleware(SSECompressionMiddleware)

    @app.get("/events")
    async def events():
        assert current_sse_compression_policy()["compression_disabled"]
        return Response(
            "data: ready\n\n",
            media_type="text/event-stream",
        )

    @app.get("/compressed-events")
    async def compressed_events():
        return Response(
            "compressed-by-handler",
            media_type="text/event-stream",
            headers={"Content-Encoding": "gzip"},
        )

    @app.get("/plain")
    async def plain():
        assert current_sse_compression_policy() is None
        return PlainTextResponse("ok")

    @app.get("/boom")
    async def boom():
        assert current_sse_compression_policy()["compression_disabled"]
        raise RuntimeError("handler failed")

    return app


def test_normal_request_does_not_set_sse_policy():
    client = TestClient(create_test_app())

    response = client.get("/plain", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert "X-Compression-Policy" not in response.headers
    assert current_sse_compression_policy() is None


def test_event_stream_disables_compression_and_buffering():
    client = TestClient(create_test_app())

    response = client.get(
        "/events",
        headers={
            "Accept": "text/event-stream",
            "Accept-Encoding": "gzip, br",
        },
    )

    assert response.status_code == 200
    assert response.headers["X-Compression-Policy"] == (
        "disabled-for-event-stream"
    )
    assert response.headers["Cache-Control"] == "no-transform"
    assert response.headers["X-Accel-Buffering"] == "no"
    assert "Content-Encoding" not in response.headers
    assert current_sse_compression_policy() is None


def test_compressed_event_stream_is_rejected_without_body_leak():
    client = TestClient(create_test_app())

    response = client.get(
        "/compressed-events",
        headers={"Accept": "text/event-stream"},
    )

    assert response.status_code == 406
    assert response.headers["X-Compression-Policy"] == (
        "rejected-compressed-sse"
    )
    assert "compressed-by-handler" not in response.text
    assert current_sse_compression_policy() is None


def test_event_stream_exception_clears_request_state():
    client = TestClient(create_test_app())

    with pytest.raises(RuntimeError):
        client.get("/boom", headers={"Accept": "text/event-stream"})

    assert current_sse_compression_policy() is None
