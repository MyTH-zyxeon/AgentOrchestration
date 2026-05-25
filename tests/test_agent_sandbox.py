import shutil

import pytest

from src.agent.sandbox import AgentSandbox


def test_get_path_returns_existing_sandbox(tmp_path):
    sandbox = AgentSandbox(base_path=str(tmp_path))

    created = sandbox.create("agent-1")

    assert sandbox.get_path("agent-1") == created


def test_get_path_drops_removed_tracked_directory(tmp_path):
    sandbox = AgentSandbox(base_path=str(tmp_path))
    created = sandbox.create("agent-1")
    shutil.rmtree(created)

    assert sandbox.get_path("agent-1") is None
    assert sandbox.get_path("agent-1") is None


def test_get_path_drops_file_replacing_tracked_directory(tmp_path):
    sandbox = AgentSandbox(base_path=str(tmp_path))
    created = sandbox.create("agent-1")
    shutil.rmtree(created)
    created.write_text("not a sandbox directory")

    assert sandbox.get_path("agent-1") is None


def test_get_path_rejects_symlink_escape(tmp_path):
    sandbox = AgentSandbox(base_path=str(tmp_path / "root"))
    created = sandbox.create("agent-1")
    outside = tmp_path / "outside"
    outside.mkdir()
    shutil.rmtree(created)
    try:
        created.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink setup is unavailable: {exc}")

    assert sandbox.get_path("agent-1") is None
    assert sandbox.get_path("agent-1") is None
