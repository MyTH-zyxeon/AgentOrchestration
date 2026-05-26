import asyncio

import pytest
from starlette.requests import Request
from starlette.responses import Response

from src.api.middleware import ProxyForwardedHeaderMiddleware


def make_request(headers=None):
    raw_headers = []
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode(), value.encode()))

    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/health",
            "headers": raw_headers,
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )


def middleware():
    async def app(scope, receive, send):
        return None

    return ProxyForwardedHeaderMiddleware(app)


def has_proxy_state(request):
    return hasattr(request.state, "proxy_forwarded_header_decision")


class TestProxyForwardedHeaderMiddleware:
    def test_allows_matching_forwarded_headers(self):
        request = make_request(
            {
                "Forwarded": "for=203.0.113.10;proto=https;host=api.test",
                "X-Forwarded-For": "203.0.113.10, 10.0.0.1",
                "X-Forwarded-Proto": "HTTPS",
                "X-Forwarded-Host": "api.test",
            }
        )
        called = []

        async def call_next(inner_request):
            called.append(has_proxy_state(inner_request))
            return Response(status_code=204)

        response = asyncio.run(middleware().dispatch(request, call_next))

        assert response.status_code == 204
        assert called == [True]
        assert not has_proxy_state(request)

    def test_rejects_conflicting_forwarded_headers(self):
        request = make_request(
            {
                "Forwarded": "for=203.0.113.10;proto=https;host=api.test",
                "X-Forwarded-For": "198.51.100.8",
            }
        )
        called = []

        async def call_next(inner_request):
            called.append(inner_request)
            return Response(status_code=204)

        response = asyncio.run(middleware().dispatch(request, call_next))

        assert response.status_code == 400
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.body == b"Conflicting forwarded headers"
        assert b"203.0.113.10" not in response.body
        assert b"198.51.100.8" not in response.body
        assert called == []
        assert not has_proxy_state(request)

    def test_clears_state_when_handler_raises(self):
        request = make_request({"X-Forwarded-For": "203.0.113.10"})

        async def call_next(inner_request):
            assert has_proxy_state(inner_request)
            raise RuntimeError("handler failed")

        with pytest.raises(RuntimeError, match="handler failed"):
            asyncio.run(middleware().dispatch(request, call_next))

        assert not has_proxy_state(request)
