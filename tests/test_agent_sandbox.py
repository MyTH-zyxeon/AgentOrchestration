import pytest

from src.agent.sandbox import ResourceLimits


def test_resource_limits_accepts_positive_integers():
    limits = ResourceLimits(cpu_time=1, memory_mb=128, disk_mb=1)

    assert limits.cpu_time == 1
    assert limits.memory_mb == 128
    assert limits.disk_mb == 1


@pytest.mark.parametrize("field", ["cpu_time", "memory_mb", "disk_mb"])
@pytest.mark.parametrize("value", [0, -1, 1.5, "1", True])
def test_resource_limits_rejects_invalid_values(field, value):
    kwargs = {"cpu_time": 60, "memory_mb": 512, "disk_mb": 100}
    kwargs[field] = value

    expected_message = f"{field} must be a positive integer"
    with pytest.raises(ValueError, match=expected_message):
        ResourceLimits(**kwargs)
