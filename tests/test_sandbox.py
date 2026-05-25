import os

import pytest

from src.agent.sandbox import AgentSandbox, SANDBOX_DIR_MODE


pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX directory mode bits are not enforced on Windows",
)


def _mode(path):
    return path.stat().st_mode & 0o777


def test_sandbox_directories_ignore_permissive_umask(tmp_path):
    base_path = tmp_path / "base"
    old_umask = os.umask(0)
    try:
        sandbox = AgentSandbox(str(base_path))
        agent_path = sandbox.create("agent-1")
    finally:
        os.umask(old_umask)

    assert _mode(base_path) == SANDBOX_DIR_MODE
    assert _mode(agent_path) == SANDBOX_DIR_MODE


def test_existing_base_directory_mode_is_tightened(tmp_path):
    base_path = tmp_path / "base"
    base_path.mkdir(mode=0o777)
    os.chmod(base_path, 0o777)

    AgentSandbox(str(base_path))

    assert _mode(base_path) == SANDBOX_DIR_MODE
