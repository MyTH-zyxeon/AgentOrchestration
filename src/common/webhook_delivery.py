"""Webhook delivery runtime with endpoint and DNS guardrails."""

import asyncio
import inspect
import socket
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import urlparse


@dataclass(frozen=True)
class WebhookEndpoint:
    id: str
    workspace_id: str
    url: str
    enabled: bool = True


@dataclass(frozen=True)
class DeliveryResult:
    delivery_id: str
    endpoint_id: str
    workspace_id: str
    status: str
    attempts: int
    payload: Dict[str, Any]
    response_status: Optional[int] = None
    error: Optional[str] = None
    retry: bool = False


class WebhookDeliveryRuntime:
    def __init__(
        self,
        resolver: Callable = None,
        sender: Callable = None,
        dns_timeout: float = 2.0,
        max_attempts: int = 3,
    ):
        self._resolver = resolver or socket.getaddrinfo
        self._sender = sender or self._send_noop
        self._dns_timeout = dns_timeout
        self._max_attempts = max_attempts
        self._records: Dict[str, DeliveryResult] = {}

    async def deliver(
        self,
        endpoint: WebhookEndpoint,
        workspace_id: str,
        event: Dict[str, Any],
        delivery_id: str,
        attempt: int = 1,
    ) -> DeliveryResult:
        existing = self._records.get(delivery_id)
        if existing:
            return existing

        valid, error = self._validate_endpoint(endpoint, workspace_id)
        payload = self._public_payload(event)
        if not valid:
            return self._record(
                delivery_id,
                endpoint,
                "rejected",
                attempt,
                payload,
                error=error,
            )

        dns_error = await self._resolve(endpoint.url)
        if dns_error:
            return self._record(
                delivery_id,
                endpoint,
                "retry",
                attempt,
                payload,
                error=dns_error,
                retry=attempt < self._max_attempts,
            )

        try:
            response_status = await self._send(endpoint.url, payload)
        except Exception:
            return self._record(
                delivery_id,
                endpoint,
                "retry",
                attempt,
                payload,
                error="delivery_failed",
                retry=attempt < self._max_attempts,
            )

        if 200 <= response_status < 300:
            return self._record(
                delivery_id,
                endpoint,
                "delivered",
                attempt,
                payload,
                response_status=response_status,
            )

        retry = response_status >= 500 and attempt < self._max_attempts
        return self._record(
            delivery_id,
            endpoint,
            "retry" if retry else "rejected",
            attempt,
            payload,
            response_status=response_status,
            error="endpoint_rejected_delivery",
            retry=retry,
        )

    def _validate_endpoint(
        self,
        endpoint: WebhookEndpoint,
        workspace_id: str,
    ) -> Tuple[bool, Optional[str]]:
        parsed = urlparse(endpoint.url)
        if not endpoint.enabled:
            return False, "endpoint_disabled"
        if endpoint.workspace_id != workspace_id:
            return False, "workspace_mismatch"
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False, "invalid_endpoint_url"
        return True, None

    async def _resolve(self, url: str) -> Optional[str]:
        parsed = urlparse(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._resolver, parsed.hostname, port),
                timeout=self._dns_timeout,
            )
        except (asyncio.TimeoutError, OSError, socket.gaierror):
            return "dns_resolution_failed"
        return None

    async def _send(self, url: str, payload: Dict[str, Any]) -> int:
        result = self._sender(url, payload)
        if inspect.isawaitable(result):
            result = await result
        return int(result)

    def _record(
        self,
        delivery_id: str,
        endpoint: WebhookEndpoint,
        status: str,
        attempt: int,
        payload: Dict[str, Any],
        response_status: int = None,
        error: str = None,
        retry: bool = False,
    ) -> DeliveryResult:
        result = DeliveryResult(
            delivery_id=delivery_id,
            endpoint_id=endpoint.id,
            workspace_id=endpoint.workspace_id,
            status=status,
            attempts=attempt,
            payload=payload,
            response_status=response_status,
            error=error,
            retry=retry,
        )
        self._records[delivery_id] = result
        return result

    def _public_payload(self, event: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: value
            for key, value in event.items()
            if not key.startswith("_") and not key.startswith("internal_")
        }

    def _send_noop(self, url: str, payload: Dict[str, Any]) -> int:
        return 202
