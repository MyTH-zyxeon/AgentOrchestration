import base64
import hashlib
import hmac
import json

import pytest

from src.api.embedded_console import (
    EmbeddedConsoleConfig,
    EmbeddedConsoleSessionExchange,
    EmbeddedConsoleTokenError,
)


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _token(secret, claims, header=None):
    token_header = header or {"alg": "HS256", "typ": "JWT"}
    header_segment = _b64(
        json.dumps(token_header, separators=(",", ":")).encode("utf-8")
    )
    payload_segment = _b64(
        json.dumps(claims, separators=(",", ":")).encode("utf-8")
    )
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    signature = hmac.new(
        secret.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).digest()
    return f"{header_segment}.{payload_segment}.{_b64(signature)}"


class TestEmbeddedConsoleSessionExchange:
    def setup_method(self):
        self.config = EmbeddedConsoleConfig(
            audience="embedded-admin-console",
            issuer_secrets={
                "dashboard-a": "dashboard-a-secret",
                "dashboard-b": "dashboard-b-secret",
            },
            session_ttl_seconds=60,
        )
        self.exchange = EmbeddedConsoleSessionExchange(
            self.config,
            now=lambda: 1_000,
        )

    def _claims(self, **overrides):
        claims = {
            "iss": "dashboard-a",
            "sub": "admin-user",
            "aud": "embedded-admin-console",
            "tenant_id": "workspace-1",
            "exp": 1_060,
        }
        claims.update(overrides)
        return claims

    def test_creates_session_for_exact_audience_and_tenant(self):
        token = _token("dashboard-a-secret", self._claims())

        session = self.exchange.exchange(
            token,
            workspace_id="workspace-1",
            requested_by="operator-1",
        )

        assert session.issuer == "dashboard-a"
        assert session.tenant_id == "workspace-1"
        assert session.audience == "embedded-admin-console"
        assert session.expires_at == 1_060
        audit = self.exchange.audit_records()[-1]
        assert audit["action"] == "session_created"
        assert audit["reason"] == "accepted"
        assert "token" not in audit
        assert "payload" not in audit
        assert "secret" not in audit

    def test_rejects_wrong_audience_before_session_creation(self):
        token = _token(
            "dashboard-a-secret",
            self._claims(aud="other-integration"),
        )

        with pytest.raises(
            EmbeddedConsoleTokenError,
            match="invalid_audience",
        ):
            self.exchange.exchange(token, workspace_id="workspace-1")

        audit = self.exchange.audit_records()[-1]
        assert audit["action"] == "session_rejected"
        assert audit["reason"] == "invalid_audience"
        assert not any(
            record["action"] == "session_created"
            for record in self.exchange.audit_records()
        )

    def test_rejects_tenant_mismatch_before_session_creation(self):
        token = _token(
            "dashboard-a-secret",
            self._claims(tenant_id="workspace-2"),
        )

        with pytest.raises(EmbeddedConsoleTokenError, match="tenant_mismatch"):
            self.exchange.exchange(token, workspace_id="workspace-1")

        assert self.exchange.audit_records()[-1]["reason"] == "tenant_mismatch"
        assert not any(
            record["action"] == "session_created"
            for record in self.exchange.audit_records()
        )

    def test_rejects_expired_token(self):
        token = _token("dashboard-a-secret", self._claims(exp=999))

        with pytest.raises(EmbeddedConsoleTokenError, match="token_expired"):
            self.exchange.exchange(token, workspace_id="workspace-1")

        assert self.exchange.audit_records()[-1]["reason"] == "token_expired"

    def test_accepts_configured_multi_issuer_token(self):
        token = _token(
            "dashboard-b-secret",
            self._claims(iss="dashboard-b", sub="partner-admin"),
        )

        session = self.exchange.exchange(token, workspace_id="workspace-1")

        assert session.issuer == "dashboard-b"
        assert session.subject == "partner-admin"

    def test_rejects_unknown_multi_issuer_token(self):
        token = _token(
            "dashboard-c-secret",
            self._claims(iss="dashboard-c"),
        )

        with pytest.raises(EmbeddedConsoleTokenError, match="unknown_issuer"):
            self.exchange.exchange(token, workspace_id="workspace-1")

        assert self.exchange.audit_records()[-1]["reason"] == "unknown_issuer"
