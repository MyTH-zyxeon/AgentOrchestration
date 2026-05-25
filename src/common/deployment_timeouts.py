"""Deployment timeout settings shared by workers and ingress."""

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from src.common.errors import ConfigurationError


def _positive_int(value: Any, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ConfigurationError(f"{name} must be a positive integer")

    if parsed <= 0:
        raise ConfigurationError(f"{name} must be a positive integer")
    return parsed


@dataclass(frozen=True)
class DeploymentTimeouts:
    """Timeouts for long-running tasks and deployed ingress."""

    worker_heartbeat_interval_seconds: int = 30
    worker_heartbeat_grace_seconds: int = 10
    retry_window_seconds: int = 60
    ingress_timeout_seconds: int = 90

    @classmethod
    def from_config(
        cls,
        config: Optional[Mapping[str, Any]] = None,
    ) -> "DeploymentTimeouts":
        timeouts = {}
        if config:
            timeouts = dict(config.get("deployment", {}).get("timeouts", {}))
            timeouts.update(config.get("timeouts", {}))

        return cls(
            worker_heartbeat_interval_seconds=_positive_int(
                timeouts.get("worker_heartbeat_interval_seconds", 30),
                "worker_heartbeat_interval_seconds",
            ),
            worker_heartbeat_grace_seconds=_positive_int(
                timeouts.get("worker_heartbeat_grace_seconds", 10),
                "worker_heartbeat_grace_seconds",
            ),
            retry_window_seconds=_positive_int(
                timeouts.get("retry_window_seconds", 60),
                "retry_window_seconds",
            ),
            ingress_timeout_seconds=_positive_int(
                timeouts.get("ingress_timeout_seconds", 90),
                "ingress_timeout_seconds",
            ),
        ).validate()

    @property
    def expected_heartbeat_window_seconds(self) -> int:
        return (
            self.worker_heartbeat_interval_seconds
            + self.worker_heartbeat_grace_seconds
        )

    @property
    def minimum_ingress_timeout_seconds(self) -> int:
        return max(
            self.expected_heartbeat_window_seconds,
            self.retry_window_seconds,
        )

    def validate(self) -> "DeploymentTimeouts":
        if (
            self.ingress_timeout_seconds
            <= self.minimum_ingress_timeout_seconds
        ):
            raise ConfigurationError(
                "ingress_timeout_seconds must be greater than the "
                "worker heartbeat window and retry window"
            )
        return self

    def to_ingress_annotations(self) -> Dict[str, str]:
        timeout = str(self.ingress_timeout_seconds)
        return {
            "nginx.ingress.kubernetes.io/proxy-read-timeout": timeout,
            "nginx.ingress.kubernetes.io/proxy-send-timeout": timeout,
            "nginx.ingress.kubernetes.io/proxy-connect-timeout": timeout,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "worker_heartbeat_interval_seconds": (
                self.worker_heartbeat_interval_seconds
            ),
            "worker_heartbeat_grace_seconds": (
                self.worker_heartbeat_grace_seconds
            ),
            "retry_window_seconds": self.retry_window_seconds,
            "ingress_timeout_seconds": self.ingress_timeout_seconds,
            "expected_heartbeat_window_seconds": (
                self.expected_heartbeat_window_seconds
            ),
            "minimum_ingress_timeout_seconds": (
                self.minimum_ingress_timeout_seconds
            ),
            "ingress_annotations": self.to_ingress_annotations(),
        }
