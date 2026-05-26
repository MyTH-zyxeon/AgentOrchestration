"""Embedded admin console session exchange helpers."""

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple
from uuid import uuid4


class EmbeddedConsoleTokenError(ValueError):
    """Raised when an embedded console token cannot create a session."""


@dataclass(frozen=True)
class EmbeddedConsoleConfig:
    audience: str
    issuer_secrets: Mapping[str, str]
    session_ttl_seconds: int = 300


@dataclass(frozen=True)
class EmbeddedConsoleSession:
    session_id: str
    issuer: str
    tenant_id: str
    subject: str
    audience: str
    expires_at: int


class EmbeddedConsoleSessionExchange:
    """Validate signed exchange tokens before creating embedded sessions."""

    def __init__(
        self,
        config: EmbeddedConsoleConfig,
        now: Optional[Callable[[], float]] = None,
    ):
        self.config = config
        self._now = now or time.time
        self._audit_records: List[Dict[str, Any]] = []

    def exchange(
        self,
        token: str,
        workspace_id: str,
        requested_by: Optional[str] = None,
    ) -> EmbeddedConsoleSession:
        try:
            header, claims, signing_input, signature = self._decode(token)
            issuer = self._claim_text(claims, "iss")
            tenant_id = (
                self._claim_text(claims, "tenant_id")
                or self._claim_text(claims, "tenant")
            )

            self._validate_header(header)
            self._validate_issuer_and_signature(
                issuer,
                signing_input,
                signature,
            )
            self._validate_expiration(claims)
            self._validate_audience(claims)
            self._validate_tenant(tenant_id, workspace_id)

            expires_at = int(self._now()) + self.config.session_ttl_seconds
            session = EmbeddedConsoleSession(
                session_id=str(uuid4()),
                issuer=issuer,
                tenant_id=tenant_id,
                subject=self._claim_text(claims, "sub") or "",
                audience=self.config.audience,
                expires_at=expires_at,
            )
            self._record_audit(
                action="session_created",
                reason="accepted",
                issuer=issuer,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                requested_by=requested_by,
            )
            return session
        except EmbeddedConsoleTokenError as error:
            self._record_audit(
                action="session_rejected",
                reason=str(error),
                workspace_id=workspace_id,
                requested_by=requested_by,
            )
            raise

    def audit_records(self) -> List[Dict[str, Any]]:
        return [record.copy() for record in self._audit_records]

    def _decode(
        self,
        token: str,
    ) -> Tuple[Dict[str, Any], Dict[str, Any], bytes, bytes]:
        parts = token.split(".")
        if len(parts) != 3:
            raise EmbeddedConsoleTokenError("malformed_token")

        header_segment, payload_segment, signature_segment = parts
        try:
            header = json.loads(self._b64decode(header_segment))
            claims = json.loads(self._b64decode(payload_segment))
            signature = self._b64decode(signature_segment)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise EmbeddedConsoleTokenError("malformed_token") from error

        if not isinstance(header, dict) or not isinstance(claims, dict):
            raise EmbeddedConsoleTokenError("malformed_token")

        signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
        return header, claims, signing_input, signature

    def _validate_header(self, header: Mapping[str, Any]) -> None:
        if header.get("alg") != "HS256":
            raise EmbeddedConsoleTokenError("unsupported_algorithm")
        if header.get("typ") not in (None, "JWT"):
            raise EmbeddedConsoleTokenError("unsupported_token_type")

    def _validate_issuer_and_signature(
        self,
        issuer: str,
        signing_input: bytes,
        signature: bytes,
    ) -> None:
        if not issuer:
            raise EmbeddedConsoleTokenError("missing_issuer")

        secret = self.config.issuer_secrets.get(issuer)
        if not secret:
            raise EmbeddedConsoleTokenError("unknown_issuer")

        expected = hmac.new(
            secret.encode("utf-8"),
            signing_input,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(expected, signature):
            raise EmbeddedConsoleTokenError("invalid_signature")

    def _validate_expiration(self, claims: Mapping[str, Any]) -> None:
        now = self._now()
        exp = claims.get("exp")
        if not isinstance(exp, (int, float)) or exp <= now:
            raise EmbeddedConsoleTokenError("token_expired")

        nbf = claims.get("nbf")
        if isinstance(nbf, (int, float)) and nbf > now:
            raise EmbeddedConsoleTokenError("token_not_yet_valid")

    def _validate_audience(self, claims: Mapping[str, Any]) -> None:
        audience = claims.get("aud")
        if audience == self.config.audience:
            return
        if isinstance(audience, list) and audience == [self.config.audience]:
            return
        raise EmbeddedConsoleTokenError("invalid_audience")

    def _validate_tenant(self, tenant_id: str, workspace_id: str) -> None:
        if not tenant_id:
            raise EmbeddedConsoleTokenError("missing_tenant")
        if tenant_id != workspace_id:
            raise EmbeddedConsoleTokenError("tenant_mismatch")

    def _record_audit(
        self,
        action: str,
        reason: str,
        workspace_id: str,
        requested_by: Optional[str],
        issuer: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        record = {
            "action": action,
            "reason": reason,
            "workspace_id": workspace_id,
        }
        if issuer:
            record["issuer"] = issuer
        if tenant_id:
            record["tenant_id"] = tenant_id
        if requested_by:
            record["requested_by"] = requested_by
        self._audit_records.append(record)

    @staticmethod
    def _claim_text(claims: Mapping[str, Any], key: str) -> str:
        value = claims.get(key)
        return value if isinstance(value, str) else ""

    @staticmethod
    def _b64decode(segment: str) -> bytes:
        padded = segment + "=" * (-len(segment) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii"))
