"""Webhook endpoint registration and safe test delivery helpers."""

import hashlib
import hmac
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import uuid4


class WebhookDeliveryRejected(ValueError):
    """Raised when webhook delivery is rejected before dispatch."""


class WebhookEndpointStore:
    def __init__(self, test_secret: str = "ao-test-delivery-secret"):
        self._test_secret = test_secret
        self._endpoints: Dict[str, Dict[str, Any]] = {}
        self._delivery_records: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        self._audit_records: List[Dict[str, Any]] = []

    def register_endpoint(
        self,
        workspace_id: str,
        url: str,
        secret: str,
        events: Iterable[str],
        created_by: str,
    ) -> Dict[str, Any]:
        endpoint_id = str(uuid4())
        endpoint = {
            "id": endpoint_id,
            "workspace_id": workspace_id,
            "url": url,
            "secret": secret,
            "secret_version": 1,
            "events": set(events),
            "created_by": created_by,
            "active": True,
            "created_at": time.time(),
        }
        self._endpoints[endpoint_id] = endpoint
        self._record_audit(
            "endpoint_registered",
            endpoint_id=endpoint_id,
            workspace_id=workspace_id,
        )
        return self._public_endpoint(endpoint)

    def rotate_secret(
        self,
        endpoint_id: str,
        workspace_id: str,
        new_secret: str,
    ) -> Dict[str, Any]:
        endpoint = self._require_endpoint(endpoint_id, workspace_id)
        endpoint["secret"] = new_secret
        endpoint["secret_version"] += 1
        self._record_audit(
            "endpoint_secret_rotated",
            endpoint_id=endpoint_id,
            workspace_id=workspace_id,
            secret_version=endpoint["secret_version"],
        )
        return self._public_endpoint(endpoint)

    def disable_endpoint(self, endpoint_id: str, workspace_id: str) -> None:
        endpoint = self._require_endpoint(endpoint_id, workspace_id)
        endpoint["active"] = False
        self._record_audit(
            "endpoint_disabled",
            endpoint_id=endpoint_id,
            workspace_id=workspace_id,
        )

    def test_delivery(
        self,
        endpoint_id: str,
        workspace_id: str,
        event_type: str,
        payload: Dict[str, Any],
        idempotency_key: str,
    ) -> Dict[str, Any]:
        endpoint = self._require_endpoint(endpoint_id, workspace_id)
        if not endpoint["active"]:
            self._reject(
                "endpoint_disabled",
                endpoint_id=endpoint_id,
                workspace_id=workspace_id,
            )
        if event_type not in endpoint["events"]:
            self._reject(
                "event_not_allowed",
                endpoint_id=endpoint_id,
                workspace_id=workspace_id,
                event_type=event_type,
            )

        record_key = (endpoint_id, idempotency_key, "test")
        if record_key in self._delivery_records:
            return dict(self._delivery_records[record_key])

        delivery_id = str(uuid4())
        signature = self._signature(endpoint_id, event_type, idempotency_key)
        record = {
            "id": delivery_id,
            "endpoint_id": endpoint_id,
            "workspace_id": workspace_id,
            "event_type": event_type,
            "mode": "test",
            "idempotency_key": idempotency_key,
            "signature": signature,
            "secret_scope": "test",
            "payload": self._public_payload(payload),
            "status": "queued",
        }
        self._delivery_records[record_key] = record
        self._record_audit(
            "test_delivery_queued",
            endpoint_id=endpoint_id,
            workspace_id=workspace_id,
            event_type=event_type,
            delivery_id=delivery_id,
        )
        return dict(record)

    def delivery_records(self) -> List[Dict[str, Any]]:
        return [dict(record) for record in self._delivery_records.values()]

    def audit_records(self) -> List[Dict[str, Any]]:
        return [dict(record) for record in self._audit_records]

    def _require_endpoint(
        self,
        endpoint_id: str,
        workspace_id: str,
    ) -> Dict[str, Any]:
        endpoint = self._endpoints.get(endpoint_id)
        if endpoint is None or endpoint["workspace_id"] != workspace_id:
            self._reject(
                "endpoint_not_found",
                endpoint_id=endpoint_id,
                workspace_id=workspace_id,
            )
        return endpoint

    def _signature(
        self,
        endpoint_id: str,
        event_type: str,
        idempotency_key: str,
    ) -> str:
        message = f"{endpoint_id}:{event_type}:{idempotency_key}".encode()
        digest = hmac.new(
            self._test_secret.encode(),
            message,
            hashlib.sha256,
        ).hexdigest()
        return f"test-sha256={digest}"

    def _public_endpoint(self, endpoint: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": endpoint["id"],
            "workspace_id": endpoint["workspace_id"],
            "url": endpoint["url"],
            "events": sorted(endpoint["events"]),
            "active": endpoint["active"],
            "secret_version": endpoint["secret_version"],
        }

    def _public_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: value
            for key, value in payload.items()
            if not self._is_internal_key(key)
        }

    def _is_internal_key(self, key: str) -> bool:
        lowered = key.lower()
        return (
            lowered.startswith("_")
            or "secret" in lowered
            or "token" in lowered
            or "signature" in lowered
        )

    def _reject(
        self,
        reason: str,
        endpoint_id: str,
        workspace_id: str,
        event_type: Optional[str] = None,
    ) -> None:
        self._record_audit(
            "test_delivery_rejected",
            endpoint_id=endpoint_id,
            workspace_id=workspace_id,
            event_type=event_type,
            reason=reason,
        )
        raise WebhookDeliveryRejected(reason)

    def _record_audit(self, event: str, **fields: Any) -> None:
        record = {"event": event}
        record.update(
            {key: value for key, value in fields.items() if value is not None}
        )
        self._audit_records.append(record)
