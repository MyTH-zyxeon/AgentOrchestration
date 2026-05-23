"""Safe webhook delivery with endpoint scoping and idempotent retries."""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Set, Tuple


INTERNAL_PAYLOAD_FIELDS = {
    "internal_run_id",
    "internal_trace_id",
    "operator_token",
    "worker_id",
}


class DeliveryRejected(ValueError):
    """Raised when a webhook delivery fails closed before dispatch."""


@dataclass
class WebhookEndpoint:
    """Registered webhook endpoint scoped to a single workspace."""

    endpoint_id: str
    workspace_id: str
    url: str
    enabled: bool = True
    disabled_reason: Optional[str] = None
    rotated_from: Optional[str] = None


@dataclass(frozen=True)
class WebhookEvent:
    """Public event payload for webhook delivery."""

    event_id: str
    workspace_id: str
    event_type: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class DeliveryResponse:
    """Response returned by a webhook transport implementation."""

    status_code: int
    body: str = ""


@dataclass(frozen=True)
class DeliveryResult:
    """Stored delivery outcome safe to expose to public integrations."""

    endpoint_id: str
    workspace_id: str
    event_id: str
    status: str
    status_code: Optional[int]
    retryable: bool
    attempt_count: int
    public_payload: Dict[str, Any]
    disabled_endpoint: bool = False


Transport = Callable[[WebhookEndpoint, Dict[str, Any]], DeliveryResponse]


@dataclass
class WebhookDeliveryService:
    """Dispatch webhook events without leaking internal metadata."""

    endpoints: Dict[Tuple[str, str], WebhookEndpoint] = field(
        default_factory=dict
    )
    deliveries: Dict[Tuple[str, str, str], DeliveryResult] = field(
        default_factory=dict
    )
    terminal_delivery_states: Set[str] = field(
        default_factory=lambda: {"delivered", "gone", "rejected"}
    )

    def register_endpoint(self, endpoint: WebhookEndpoint) -> None:
        if not endpoint.endpoint_id.strip():
            raise DeliveryRejected("endpoint_id is required")
        if not endpoint.workspace_id.strip():
            raise DeliveryRejected("workspace_id is required")
        if not endpoint.url.strip():
            raise DeliveryRejected("endpoint url is required")
        key = (endpoint.workspace_id, endpoint.endpoint_id)
        self.endpoints[key] = endpoint

    def deliver(
        self,
        workspace_id: str,
        endpoint_id: str,
        event: WebhookEvent,
        transport: Transport,
    ) -> DeliveryResult:
        endpoint = self._get_scoped_endpoint(workspace_id, endpoint_id, event)
        delivery_key = (workspace_id, endpoint_id, event.event_id)
        previous = self.deliveries.get(delivery_key)
        if previous and previous.status in self.terminal_delivery_states:
            return previous

        public_payload = sanitize_public_payload(event)
        attempt_count = previous.attempt_count + 1 if previous else 1
        response = transport(endpoint, public_payload)
        result = self._result_from_response(
            endpoint=endpoint,
            event=event,
            response=response,
            public_payload=public_payload,
            attempt_count=attempt_count,
        )
        self.deliveries[delivery_key] = result
        return result

    def _get_scoped_endpoint(
        self,
        workspace_id: str,
        endpoint_id: str,
        event: WebhookEvent,
    ) -> WebhookEndpoint:
        if event.workspace_id != workspace_id:
            raise DeliveryRejected("event workspace does not match delivery")

        endpoint = self.endpoints.get((workspace_id, endpoint_id))
        if endpoint is None:
            raise DeliveryRejected("endpoint is not registered for workspace")
        if not endpoint.enabled:
            raise DeliveryRejected("endpoint is disabled")
        return endpoint

    def _result_from_response(
        self,
        endpoint: WebhookEndpoint,
        event: WebhookEvent,
        response: DeliveryResponse,
        public_payload: Dict[str, Any],
        attempt_count: int,
    ) -> DeliveryResult:
        if response.status_code == 410:
            endpoint.enabled = False
            endpoint.disabled_reason = "410 gone"
            return DeliveryResult(
                endpoint_id=endpoint.endpoint_id,
                workspace_id=endpoint.workspace_id,
                event_id=event.event_id,
                status="gone",
                status_code=response.status_code,
                retryable=False,
                attempt_count=attempt_count,
                public_payload=public_payload,
                disabled_endpoint=True,
            )

        if 200 <= response.status_code < 300:
            return DeliveryResult(
                endpoint_id=endpoint.endpoint_id,
                workspace_id=endpoint.workspace_id,
                event_id=event.event_id,
                status="delivered",
                status_code=response.status_code,
                retryable=False,
                attempt_count=attempt_count,
                public_payload=public_payload,
            )

        return DeliveryResult(
            endpoint_id=endpoint.endpoint_id,
            workspace_id=endpoint.workspace_id,
            event_id=event.event_id,
            status="failed",
            status_code=response.status_code,
            retryable=500 <= response.status_code < 600,
            attempt_count=attempt_count,
            public_payload=public_payload,
        )


def sanitize_public_payload(event: WebhookEvent) -> Dict[str, Any]:
    """Remove internal-only fields before dispatch or persistence."""

    payload = {
        key: value
        for key, value in event.payload.items()
        if key not in INTERNAL_PAYLOAD_FIELDS and not key.startswith("_")
    }
    payload["event_id"] = event.event_id
    payload["event_type"] = event.event_type
    return payload
