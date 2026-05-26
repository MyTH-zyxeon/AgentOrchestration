"""Authentication guard for documentation endpoints."""

from __future__ import annotations

import hashlib
import time
from collections import deque
from typing import (
    Any,
    Callable,
    Deque,
    Dict,
    Iterable,
    Mapping,
    Optional,
    Set,
    Tuple,
)

from fastapi import HTTPException
from starlette.requests import Request


class DocumentationAuthGuard:
    """Authorize access to documentation and OpenAPI schema endpoints."""

    def __init__(
        self,
        config: Optional[Mapping[str, Any]] = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        settings = dict(config or {})
        self.required_scope = str(settings.get("required_scope", "docs:read"))
        self.allowed_roles = self._coerce_set(
            settings.get("allowed_roles", ["admin", "owner", "operator"])
        )
        self.cookie_name = str(
            settings.get("session_cookie_name", "ao_session")
        )
        self._clock = clock or time.time
        self._tokens = self._normalize_tokens(settings.get("tokens", {}))
        self._decisions: Deque[Dict[str, Any]] = deque(
            maxlen=int(settings.get("audit_limit", 64))
        )

    def authorize(self, request: Request) -> Dict[str, Any]:
        token, source = self._extract_token(request)
        claims = self._tokens.get(token)
        token_id = self._token_id(token)

        if claims is None:
            self._deny(401, "unknown_token", token_id=token_id, source=source)

        if claims.get("revoked"):
            self._deny(
                401,
                "revoked_token",
                claims=claims,
                token_id=token_id,
                source=source,
            )

        if claims.get("stale"):
            self._deny(
                401,
                "stale_token",
                claims=claims,
                token_id=token_id,
                source=source,
            )

        expires_at = self._coerce_timestamp(claims.get("expires_at"))
        if expires_at is not None and expires_at <= self._clock():
            self._deny(
                401,
                "expired_token",
                claims=claims,
                token_id=token_id,
                source=source,
            )

        scopes = self._coerce_set(
            claims.get("scopes", claims.get("scope", []))
        )
        if self.required_scope not in scopes:
            self._deny(
                403,
                "insufficient_scope",
                claims=claims,
                token_id=token_id,
                source=source,
            )

        roles = self._coerce_set(claims.get("roles", claims.get("role", [])))
        if not roles.intersection(self.allowed_roles):
            self._deny(
                403,
                "insufficient_role",
                claims=claims,
                token_id=token_id,
                source=source,
            )

        principal = {
            "subject": str(
                claims.get("subject", claims.get("sub", "documentation-user"))
            ),
            "workspace_id": claims.get("workspace_id"),
            "scopes": sorted(scopes),
            "roles": sorted(roles),
            "source": source,
        }
        request.state.docs_principal = principal
        self._record(
            "allowed",
            "authorized",
            claims=claims,
            token_id=token_id,
            source=source,
        )
        return principal

    def audit_log(self) -> Tuple[Dict[str, Any], ...]:
        return tuple(self._decisions)

    def _extract_token(self, request: Request) -> Tuple[str, str]:
        authorization = request.headers.get("Authorization", "")
        if authorization:
            scheme, _, credential = authorization.partition(" ")
            if scheme.lower() != "bearer" or not credential.strip():
                self._deny(401, "malformed_authorization")
            return credential.strip(), "authorization_header"

        cookie_token = request.cookies.get(self.cookie_name)
        if cookie_token:
            return cookie_token.strip(), "session_cookie"

        self._deny(401, "missing_token")

    def _deny(
        self,
        status_code: int,
        reason: str,
        claims: Optional[Mapping[str, Any]] = None,
        token_id: Optional[str] = None,
        source: Optional[str] = None,
    ) -> None:
        self._record(
            "denied",
            reason,
            claims=claims,
            token_id=token_id,
            source=source,
        )
        raise HTTPException(status_code=status_code, detail=reason)

    def _record(
        self,
        event: str,
        reason: str,
        claims: Optional[Mapping[str, Any]] = None,
        token_id: Optional[str] = None,
        source: Optional[str] = None,
    ) -> None:
        self._decisions.append(
            {
                "event": event,
                "reason": reason,
                "workspace_id": (claims or {}).get("workspace_id"),
                "subject": (claims or {}).get(
                    "subject",
                    (claims or {}).get("sub"),
                ),
                "token_id": token_id,
                "source": source,
                "timestamp": self._clock(),
            }
        )

    def _normalize_tokens(self, tokens: Any) -> Dict[str, Dict[str, Any]]:
        if isinstance(tokens, Mapping):
            return {
                str(token): dict(claims or {})
                for token, claims in tokens.items()
                if str(token)
            }

        if (
            isinstance(tokens, Iterable)
            and not isinstance(tokens, (str, bytes))
        ):
            return {str(token): {} for token in tokens if str(token)}

        return {}

    def _coerce_set(self, value: Any) -> Set[str]:
        if value is None:
            return set()
        if isinstance(value, str):
            return {item for item in value.replace(",", " ").split() if item}
        if isinstance(value, Iterable):
            return {str(item) for item in value if str(item)}
        return {str(value)}

    def _coerce_timestamp(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _token_id(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
