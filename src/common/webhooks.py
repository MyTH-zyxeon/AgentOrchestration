"""Webhook endpoint ownership and delivery guards."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional


ACTIVE_OWNER_ROLES = {"owner", "admin"}


class WebhookOwnershipError(ValueError):
    """Raised when a principal cannot mutate a webhook endpoint."""


@dataclass(frozen=True)
class WebhookPrincipal:
    workspace_id: str
    subject_id: str
    role: str


@dataclass
class WebhookEndpoint:
    endpoint_id: str
    workspace_id: str
    owner_subject_id: str
    url: str
    secret_version: str
    enabled: bool = True
    updated_at: float = 0.0

    def public_dict(self) -> Dict[str, Any]:
        return {
            "endpoint_id": self.endpoint_id,
            "workspace_id": self.workspace_id,
            "owner_subject_id": self.owner_subject_id,
            "url": self.url,
            "enabled": self.enabled,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class WebhookDeliveryRecord:
    delivery_id: str
    endpoint_id: str
    workspace_id: str
    event_type: str
    idempotency_key: str
    status: str
    reason: str
    attempt: int
    created_at: float

    def public_dict(self) -> Dict[str, Any]:
        return {
            "delivery_id": self.delivery_id,
            "endpoint_id": self.endpoint_id,
            "workspace_id": self.workspace_id,
            "event_type": self.event_type,
            "idempotency_key": self.idempotency_key,
            "status": self.status,
            "reason": self.reason,
            "attempt": self.attempt,
            "created_at": self.created_at,
        }


class WebhookEndpointStore:
    """In-memory endpoint store with workspace-safe webhook dispatch."""

    def __init__(self) -> None:
        self._endpoints: Dict[str, WebhookEndpoint] = {}
        self._deliveries: Dict[str, WebhookDeliveryRecord] = {}

    def register_endpoint(
        self,
        *,
        endpoint_id: str,
        workspace_id: str,
        owner_subject_id: str,
        url: str,
        secret_version: str,
        principal: WebhookPrincipal,
    ) -> WebhookEndpoint:
        self._require_mutation_scope(workspace_id, principal)
        endpoint = WebhookEndpoint(
            endpoint_id=endpoint_id,
            workspace_id=workspace_id,
            owner_subject_id=owner_subject_id,
            url=url,
            secret_version=secret_version,
            updated_at=time.time(),
        )
        self._endpoints[endpoint_id] = endpoint
        return endpoint

    def rotate_secret(
        self,
        endpoint_id: str,
        *,
        new_secret_version: str,
        principal: WebhookPrincipal,
    ) -> WebhookEndpoint:
        endpoint = self._get_endpoint(endpoint_id)
        self._require_endpoint_owner(endpoint, principal)
        endpoint.secret_version = new_secret_version
        endpoint.updated_at = time.time()
        return endpoint

    def disable_endpoint(
        self,
        endpoint_id: str,
        *,
        principal: WebhookPrincipal,
    ) -> WebhookEndpoint:
        endpoint = self._get_endpoint(endpoint_id)
        self._require_endpoint_owner(endpoint, principal)
        endpoint.enabled = False
        endpoint.updated_at = time.time()
        return endpoint

    def deliver(
        self,
        endpoint_id: str,
        *,
        event_type: str,
        payload: Dict[str, Any],
        secret_version: str,
        idempotency_key: str,
        principal: WebhookPrincipal,
    ) -> WebhookDeliveryRecord:
        if idempotency_key in self._deliveries:
            return self._deliveries[idempotency_key]

        endpoint = self._endpoints.get(endpoint_id)
        reason = self._delivery_rejection_reason(
            endpoint,
            secret_version,
            principal,
        )
        status = "rejected" if reason else "delivered"
        record = WebhookDeliveryRecord(
            delivery_id=str(uuid.uuid4()),
            endpoint_id=endpoint_id,
            workspace_id=principal.workspace_id,
            event_type=event_type,
            idempotency_key=idempotency_key,
            status=status,
            reason=reason or "ok",
            attempt=1,
            created_at=time.time(),
        )
        self._deliveries[idempotency_key] = record
        return record

    def delivery_count(self) -> int:
        return len(self._deliveries)

    def _get_endpoint(self, endpoint_id: str) -> WebhookEndpoint:
        if endpoint_id not in self._endpoints:
            raise WebhookOwnershipError("endpoint not found")
        return self._endpoints[endpoint_id]

    def _require_mutation_scope(
        self,
        workspace_id: str,
        principal: WebhookPrincipal,
    ) -> None:
        if principal.workspace_id != workspace_id:
            raise WebhookOwnershipError("workspace scope mismatch")
        if principal.role not in ACTIVE_OWNER_ROLES:
            raise WebhookOwnershipError("active owner role required")

    def _require_endpoint_owner(
        self,
        endpoint: WebhookEndpoint,
        principal: WebhookPrincipal,
    ) -> None:
        self._require_mutation_scope(endpoint.workspace_id, principal)
        if (
            principal.role != "admin"
            and principal.subject_id != endpoint.owner_subject_id
        ):
            raise WebhookOwnershipError("endpoint owner required")

    def _delivery_rejection_reason(
        self,
        endpoint: Optional[WebhookEndpoint],
        secret_version: str,
        principal: WebhookPrincipal,
    ) -> str:
        if endpoint is None:
            return "endpoint_not_found"
        if endpoint.workspace_id != principal.workspace_id:
            return "workspace_scope_mismatch"
        if principal.role not in ACTIVE_OWNER_ROLES:
            return "active_owner_role_required"
        if not endpoint.enabled:
            return "endpoint_disabled"
        if endpoint.secret_version != secret_version:
            return "stale_secret_version"
        return ""
