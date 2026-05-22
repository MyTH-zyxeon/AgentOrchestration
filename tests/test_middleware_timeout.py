import asyncio
import logging

import pytest

from src.api.middleware import RequestTimeoutMiddleware


def run_middleware(app, timeout_seconds=0.05, query_string=b""):
    messages = []
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/events",
        "query_string": query_string,
        "state": {},
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    middleware = RequestTimeoutMiddleware(app, timeout_seconds)
    asyncio.run(middleware(scope, receive, send))
    return messages, scope


def header_map(message):
    return dict(message.get("headers", []))


def test_timeout_middleware_allows_normal_response():
    async def app(scope, receive, send):
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [],
        })
        await send({
            "type": "http.response.body",
            "body": b"ok",
            "more_body": False,
        })

    messages, scope = run_middleware(app)

    assert messages[0]["status"] == 200
    assert header_map(messages[0])[b"x-request-timeout-ms"] == b"50"
    assert messages[1]["body"] == b"ok"
    assert "request_timeout_seconds" not in scope["state"]


def test_timeout_middleware_rejects_before_response(caplog):
    async def app(scope, receive, send):
        await asyncio.sleep(0.05)

    with caplog.at_level(logging.WARNING):
        messages, scope = run_middleware(
            app,
            timeout_seconds=0.001,
            query_string=b"token=secret",
        )

    headers = header_map(messages[0])
    assert messages[0]["status"] == 504
    assert headers[b"x-request-timeout"] == b"true"
    assert headers[b"cache-control"] == b"no-store"
    assert messages[1]["body"] == b"Request timed out"
    assert "request_timeout_seconds" not in scope["state"]
    assert "token=secret" not in caplog.text


def test_timeout_middleware_bounds_streaming_response():
    async def app(scope, receive, send):
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [],
        })
        await asyncio.sleep(0.05)
        await send({
            "type": "http.response.body",
            "body": b"late",
            "more_body": False,
        })

    messages, scope = run_middleware(app, timeout_seconds=0.001)

    assert messages[0]["status"] == 200
    assert header_map(messages[0])[b"x-request-timeout-ms"] == b"1"
    assert messages[1] == {
        "type": "http.response.body",
        "body": b"",
        "more_body": False,
    }
    assert "request_timeout_seconds" not in scope["state"]


def test_timeout_middleware_clears_state_on_exception():
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/events",
        "query_string": b"",
        "state": {},
    }

    async def app(scope, receive, send):
        raise RuntimeError("boom")

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        pass

    middleware = RequestTimeoutMiddleware(app, 0.05)

    with pytest.raises(RuntimeError):
        asyncio.run(middleware(scope, receive, send))

    assert "request_timeout_seconds" not in scope["state"]
