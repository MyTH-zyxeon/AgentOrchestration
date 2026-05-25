"""Validation-first webhook delivery state handling."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple


class EndpointState(Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    REVOKED = "revoked"
    EXPIRED = "expired"


class WebhookDeliveryRejected(ValueError):
    """Raised when endpoint state makes a webhook delivery unsafe."""


@dataclass
class WebhookEndpoint:
    endpoint_id: str
    workspace_id: str
    target_url: str
    state: EndpointState = EndpointState.ACTIVE
    version: int = 1
    expires_at: Optional[float] = None


@dataclass(frozen=True)
class QueuedWebhookEvent:
    event_id: str
    workspace_id: str
    endpoint_id: str
    endpoint_version: int
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class DeliveryRecord:
    event_id: str
    workspace_id: str
    endpoint_id: str
    endpoint_version: int
    attempt: int
    status: str
    callback_payload: Mapping[str, Any] = field(default_factory=dict)
    reason: Optional[str] = None


class WebhookDeliveryState:
    """Coordinates endpoint validation, retry decisions, and safe payloads."""

    INTERNAL_FIELDS: Set[str] = {
        "authorization",
        "endpoint_version",
        "internal_metadata",
        "internal_retry_state",
        "internal_trace",
        "secret",
        "token",
    }

    def __init__(self):
        self._endpoints: Dict[Tuple[str, str], WebhookEndpoint] = {}
        self._accepted: Dict[
            Tuple[str, str, str, int, int], DeliveryRecord
        ] = {}
        self._terminal: Dict[
            Tuple[str, str, str, int, int], DeliveryRecord
        ] = {}
        self.audit_log: List[Dict[str, Any]] = []

    def register_endpoint(
        self,
        endpoint_id: str,
        workspace_id: str,
        target_url: str,
        state: EndpointState = EndpointState.ACTIVE,
        version: int = 1,
        expires_at: Optional[float] = None,
    ) -> WebhookEndpoint:
        endpoint = WebhookEndpoint(
            endpoint_id=endpoint_id,
            workspace_id=workspace_id,
            target_url=target_url,
            state=state,
            version=version,
            expires_at=expires_at,
        )
        self._endpoints[(workspace_id, endpoint_id)] = endpoint
        return endpoint

    def set_endpoint_state(
        self,
        workspace_id: str,
        endpoint_id: str,
        state: EndpointState,
    ) -> None:
        self._lookup_endpoint(workspace_id, endpoint_id).state = state

    def rotate_endpoint(
        self,
        workspace_id: str,
        endpoint_id: str,
        target_url: Optional[str] = None,
    ) -> WebhookEndpoint:
        endpoint = self._lookup_endpoint(workspace_id, endpoint_id)
        endpoint.version += 1
        if target_url is not None:
            endpoint.target_url = target_url
        return endpoint

    def prepare_delivery(
        self,
        event: QueuedWebhookEvent,
        attempt: int = 1,
        now: Optional[float] = None,
    ) -> DeliveryRecord:
        endpoint = self._validate_before_delivery(event, now=now)
        key = self._record_key(event, attempt)
        existing = self._accepted.get(key)
        if existing is not None:
            return existing

        record = DeliveryRecord(
            event_id=event.event_id,
            workspace_id=endpoint.workspace_id,
            endpoint_id=endpoint.endpoint_id,
            endpoint_version=endpoint.version,
            attempt=attempt,
            status="ready",
            callback_payload=self._sanitize_payload(event.payload),
        )
        self._accepted[key] = record
        return record

    def retry_delivery(
        self,
        event: QueuedWebhookEvent,
        attempt: int,
        now: Optional[float] = None,
    ) -> DeliveryRecord:
        try:
            return self.prepare_delivery(event, attempt=attempt, now=now)
        except WebhookDeliveryRejected as exc:
            key = self._record_key(event, attempt)
            existing = self._terminal.get(key)
            if existing is not None:
                return existing
            record = DeliveryRecord(
                event_id=event.event_id,
                workspace_id=event.workspace_id,
                endpoint_id=event.endpoint_id,
                endpoint_version=event.endpoint_version,
                attempt=attempt,
                status="permanently_failed",
                reason=str(exc),
            )
            self._terminal[key] = record
            self.audit_log.append(
                {
                    "event_id": event.event_id,
                    "workspace_id": event.workspace_id,
                    "endpoint_id": event.endpoint_id,
                    "attempt": attempt,
                    "decision": "retry_rejected",
                    "reason": str(exc),
                }
            )
            return record

    def accepted_count(self) -> int:
        return len(self._accepted)

    def terminal_count(self) -> int:
        return len(self._terminal)

    def _validate_before_delivery(
        self,
        event: QueuedWebhookEvent,
        now: Optional[float] = None,
    ) -> WebhookEndpoint:
        endpoint = self._lookup_endpoint(event.workspace_id, event.endpoint_id)
        if endpoint.workspace_id != event.workspace_id:
            raise WebhookDeliveryRejected("endpoint workspace mismatch")
        if endpoint.state is not EndpointState.ACTIVE:
            raise WebhookDeliveryRejected(
                f"endpoint is {endpoint.state.value}"
            )
        if endpoint.expires_at is not None and now is not None:
            if endpoint.expires_at <= now:
                raise WebhookDeliveryRejected("endpoint is expired")
        if endpoint.version != event.endpoint_version:
            raise WebhookDeliveryRejected("endpoint version is stale")
        return endpoint

    def _lookup_endpoint(
        self,
        workspace_id: str,
        endpoint_id: str,
    ) -> WebhookEndpoint:
        endpoint = self._endpoints.get((workspace_id, endpoint_id))
        if endpoint is None:
            raise WebhookDeliveryRejected("endpoint not found in workspace")
        return endpoint

    def _record_key(
        self,
        event: QueuedWebhookEvent,
        attempt: int,
    ) -> Tuple[str, str, str, int, int]:
        return (
            event.workspace_id,
            event.endpoint_id,
            event.event_id,
            event.endpoint_version,
            attempt,
        )

    def _sanitize_payload(self, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                key: self._sanitize_payload(item)
                for key, item in value.items()
                if not self._is_internal_key(str(key))
            }
        if isinstance(value, list):
            return [self._sanitize_payload(item) for item in value]
        return value

    def _is_internal_key(self, key: str) -> bool:
        return key in self.INTERNAL_FIELDS or key.startswith("_")
