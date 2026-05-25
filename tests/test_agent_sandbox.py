from pathlib import Path
import shutil

from src.agent.sandbox import AgentSandbox


def test_cleanup_all_returns_failures_and_continues(tmp_path, monkeypatch):
    sandbox = AgentSandbox(str(tmp_path))
    ok_path = sandbox.create("ok-agent")
    stuck_path = sandbox.create("stuck-agent")
    original_rmtree = shutil.rmtree

    def fail_for_stuck(path):
        if Path(path) == stuck_path:
            raise OSError("locked")
        return original_rmtree(path)

    monkeypatch.setattr(shutil, "rmtree", fail_for_stuck)

    failures = sandbox.cleanup_all()

    assert failures == ["stuck-agent"]
    assert not ok_path.exists()
    assert sandbox.get_path("ok-agent") is None
    assert stuck_path.exists()
    assert sandbox.get_path("stuck-agent") == stuck_path


def test_cleanup_all_returns_empty_list_when_all_destroyed(tmp_path):
    sandbox = AgentSandbox(str(tmp_path))
    first = sandbox.create("first")
    second = sandbox.create("second")

    assert sandbox.cleanup_all() == []
    assert not first.exists()
    assert not second.exists()
    assert sandbox.get_path("first") is None
    assert sandbox.get_path("second") is None
