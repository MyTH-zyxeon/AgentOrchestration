"""Authentication helpers shared by API routes and middleware."""

from typing import Iterable, Set

from fastapi import HTTPException, Request, status

DOCUMENTATION_SCOPE = "docs:read"
REVOKED_TOKENS = {"revoked", "stale"}


def bearer_token(request: Request) -> str:
    value = request.headers.get("Authorization", "")
    if not value.startswith("Bearer "):
        return ""
    return value[len("Bearer "):].strip()


def request_scopes(request: Request) -> Set[str]:
    raw = request.headers.get("X-AO-Scopes", "")
    return {part for part in raw.replace(",", " ").split() if part}


def require_bearer(request: Request) -> str:
    token = bearer_token(request)
    if not token or token in REVOKED_TOKENS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )
    return token


def require_scopes(request: Request, required_scopes: Iterable[str]) -> None:
    require_bearer(request)
    missing = set(required_scopes) - request_scopes(request)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden",
        )


def require_documentation_access(request: Request) -> None:
    require_scopes(request, {DOCUMENTATION_SCOPE})
