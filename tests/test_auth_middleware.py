import base64
import json
import time

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from src.api.middleware import AuthMiddleware


def make_token(claims):
    header = {"alg": "none", "typ": "JWT"}
    parts = []
    for part in (header, claims, "signature"):
        if isinstance(part, str):
            encoded = part.encode("utf-8")
        else:
            encoded = json.dumps(part).encode("utf-8")
        parts.append(
            base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")
        )
    return ".".join(parts)


async def protected_endpoint(request):
    return JSONResponse({"ok": True})


def make_client(revoked_token_ids=()):
    app = Starlette(
        routes=[Route("/api/v2/workers/run", protected_endpoint)]
    )
    app.add_middleware(
        AuthMiddleware,
        revoked_token_ids=revoked_token_ids,
    )
    return TestClient(app)


def valid_claims(**overrides):
    now = int(time.time())
    claims = {
        "sub": "worker-1",
        "workspace_id": "workspace-1",
        "role": "worker",
        "scope": "worker",
        "nbf": now - 10,
        "exp": now + 60,
        "jti": "token-1",
    }
    claims.update(overrides)
    return claims


def test_worker_token_with_future_nbf_is_denied():
    client = make_client()
    token = make_token(valid_claims(nbf=int(time.time()) + 60))

    response = client.get(
        "/api/v2/workers/run",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_revoked_worker_token_is_denied():
    client = make_client(revoked_token_ids={"token-1"})
    token = make_token(valid_claims())

    response = client.get(
        "/api/v2/workers/run",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    "claims",
    [
        valid_claims(sub=""),
        valid_claims(workspace_id=""),
        valid_claims(role="viewer", scope="read"),
        valid_claims(exp=int(time.time()) - 1),
    ],
)
def test_anonymous_stale_or_insufficient_worker_tokens_are_denied(claims):
    client = make_client()
    token = make_token(claims)

    response = client.get(
        "/api/v2/workers/run",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_authorized_worker_token_can_reach_protected_route():
    client = make_client()
    token = make_token(valid_claims())

    response = client.get(
        "/api/v2/workers/run",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
