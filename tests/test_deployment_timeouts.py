import pytest

from src.api.server import create_app
from src.common.deployment_timeouts import DeploymentTimeouts
from src.common.errors import ConfigurationError


def test_default_ingress_timeout_exceeds_worker_and_retry_windows():
    timeouts = DeploymentTimeouts.from_config()

    assert timeouts.ingress_timeout_seconds > (
        timeouts.expected_heartbeat_window_seconds
    )
    assert timeouts.ingress_timeout_seconds > timeouts.retry_window_seconds


def test_validation_rejects_ingress_not_greater_than_heartbeat_window():
    with pytest.raises(ConfigurationError):
        DeploymentTimeouts.from_config(
            {
                "deployment": {
                    "timeouts": {
                        "worker_heartbeat_interval_seconds": 60,
                        "worker_heartbeat_grace_seconds": 30,
                        "retry_window_seconds": 10,
                        "ingress_timeout_seconds": 90,
                    }
                }
            }
        )


def test_validation_rejects_ingress_not_greater_than_retry_window():
    with pytest.raises(ConfigurationError):
        DeploymentTimeouts.from_config(
            {
                "deployment": {
                    "timeouts": {
                        "worker_heartbeat_interval_seconds": 10,
                        "worker_heartbeat_grace_seconds": 5,
                        "retry_window_seconds": 120,
                        "ingress_timeout_seconds": 120,
                    }
                }
            }
        )


def test_ingress_annotations_share_validated_timeout_source():
    timeouts = DeploymentTimeouts.from_config(
        {"deployment": {"timeouts": {"ingress_timeout_seconds": 180}}}
    )

    assert timeouts.to_ingress_annotations() == {
        "nginx.ingress.kubernetes.io/proxy-read-timeout": "180",
        "nginx.ingress.kubernetes.io/proxy-send-timeout": "180",
        "nginx.ingress.kubernetes.io/proxy-connect-timeout": "180",
    }


def test_create_app_stores_validated_deployment_timeouts():
    app = create_app(
        {"deployment": {"timeouts": {"ingress_timeout_seconds": 180}}}
    )

    assert app.state.deployment_timeouts.ingress_timeout_seconds == 180


def test_create_app_rejects_inconsistent_deployment_timeouts():
    with pytest.raises(ConfigurationError):
        create_app(
            {"deployment": {"timeouts": {"ingress_timeout_seconds": 30}}}
        )
