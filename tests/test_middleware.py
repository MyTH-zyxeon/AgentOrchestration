"""Tests for API middleware behavior."""

import asyncio
from typing import Dict, Optional

import pytest
from starlette.requests import Request
from starlette.responses import Response

from src.api.middleware import (
    AuthMiddleware,
    PathNormalizationMiddleware,
    collapse_duplicate_slashes,
)


def make_request(
    path: str, headers: Optional[Dict[str, str]] = None
) -> Request:
    raw_headers = [
        (name.lower().encode("latin-1"), value.encode("latin-1"))
        for name, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": b"",
            "headers": raw_headers,
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )


async def ok_response(request: Request) -> Response:
    return Response("ok", status_code=200)


def run(coro):
    return asyncio.run(coro)


def test_collapse_duplicate_slashes():
    assert collapse_duplicate_slashes("/api//v2///agents") == "/api/v2/agents"
    assert collapse_duplicate_slashes("/api/v2/agents") == "/api/v2/agents"
    assert collapse_duplicate_slashes("/") == "/"


def test_normal_path_passes_without_header_or_state():
    request = make_request("/health")
    middleware = PathNormalizationMiddleware(app=None)

    response = run(middleware.dispatch(request, ok_response))

    assert response.status_code == 200
    assert "X-AO-Path-Normalized" not in response.headers
    assert request.scope["path"] == "/health"
    assert not hasattr(request.state, "path_normalized")


def test_duplicate_slashes_are_normalized_before_auth_rejection():
    request = make_request("/api//v2//agents")
    normalizer = PathNormalizationMiddleware(app=None)
    auth = AuthMiddleware(app=None)

    async def auth_call_next(inner_request: Request) -> Response:
        return await auth.dispatch(inner_request, ok_response)

    response = run(normalizer.dispatch(request, auth_call_next))

    assert response.status_code == 401
    assert response.headers["X-AO-Path-Normalized"] == "true"
    assert request.scope["path"] == "/api/v2/agents"
    assert request.scope["raw_path"] == b"/api/v2/agents"
    assert not hasattr(request.state, "path_normalized")


def test_duplicate_slashes_preserve_public_token_route():
    request = make_request("/api//v2//auth//token")
    normalizer = PathNormalizationMiddleware(app=None)
    auth = AuthMiddleware(app=None)

    async def auth_call_next(inner_request: Request) -> Response:
        return await auth.dispatch(inner_request, ok_response)

    response = run(normalizer.dispatch(request, auth_call_next))

    assert response.status_code == 200
    assert response.headers["X-AO-Path-Normalized"] == "true"
    assert request.scope["path"] == "/api/v2/auth/token"
    assert not hasattr(request.state, "path_normalized")


def test_duplicate_slash_state_is_cleared_when_downstream_raises():
    request = make_request("/api//v2//agents")
    normalizer = PathNormalizationMiddleware(app=None)

    async def raising_call_next(inner_request: Request) -> Response:
        assert inner_request.scope["path"] == "/api/v2/agents"
        raise RuntimeError("downstream failed")

    with pytest.raises(RuntimeError, match="downstream failed"):
        run(normalizer.dispatch(request, raising_call_next))

    assert request.scope["path"] == "/api/v2/agents"
    assert not hasattr(request.state, "path_normalized")
