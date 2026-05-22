import pytest

from src.agent.sandbox import AgentSandbox, ResourceLimits
from src.common.errors import ConfigurationError


class TestResourceLimits:
    def test_resource_limits_accept_positive_integer_config_values(self):
        limits = ResourceLimits(cpu_time="30", memory_mb="256", disk_mb="128")

        assert limits.cpu_time == 30
        assert limits.memory_mb == 256
        assert limits.disk_mb == 128

    @pytest.mark.parametrize("field", ["cpu_time", "memory_mb", "disk_mb"])
    @pytest.mark.parametrize(
        "value",
        [0, -1, "0", "-5", "invalid", None, True],
    )
    def test_resource_limits_reject_invalid_config_values(self, field, value):
        values = {"cpu_time": 30, "memory_mb": 256, "disk_mb": 128}
        values[field] = value

        message = f"{field} must be a positive integer"
        with pytest.raises(ConfigurationError, match=message):
            ResourceLimits(**values)

    def test_sandbox_create_validates_mutated_limits(self, tmp_path):
        limits = ResourceLimits(cpu_time=30, memory_mb=256, disk_mb=128)
        limits.memory_mb = -1
        sandbox = AgentSandbox(base_path=str(tmp_path))

        message = "memory_mb must be a positive integer"
        with pytest.raises(ConfigurationError, match=message):
            sandbox.create("agent-1", limits=limits)

        assert not (tmp_path / "agent-1").exists()
