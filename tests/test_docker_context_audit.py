import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "audit_docker_context.py"
)
SPEC = importlib.util.spec_from_file_location(
    "audit_docker_context",
    SCRIPT_PATH,
)
audit_docker_context = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit_docker_context
SPEC.loader.exec_module(audit_docker_context)


def test_audit_context_uses_dockerignore_and_reports_size(tmp_path):
    (tmp_path / ".dockerignore").write_text("ignored\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('ok')\n", encoding="utf-8")
    ignored = tmp_path / "ignored"
    ignored.mkdir()
    (ignored / "cache.bin").write_bytes(b"x" * 100)

    audit = audit_docker_context.audit_context(tmp_path)

    assert audit.file_count == 2
    assert audit.total_bytes == len("ignored\n") + len("print('ok')\n")
    assert audit.prohibited_entries == []


def test_audit_context_reports_prohibited_generated_paths(tmp_path):
    cache_dir = tmp_path / "node_modules"
    cache_dir.mkdir()
    (cache_dir / "package.bin").write_bytes(b"x")

    audit = audit_docker_context.audit_context(tmp_path)

    assert audit.prohibited_entries == ["node_modules/package.bin"]


def test_audit_context_can_fail_on_size_budget(tmp_path, capsys):
    (tmp_path / "large.bin").write_bytes(b"x" * 4)

    result = audit_docker_context.main_with_args_for_test(tmp_path, 3)

    captured = capsys.readouterr()
    assert result == 1
    assert "context size exceeds budget" in captured.out
