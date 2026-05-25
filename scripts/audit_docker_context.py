"""Audit Docker build context size and generated-path hygiene."""

from __future__ import annotations

import argparse
import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple


DEFAULT_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_PROHIBITED_NAMES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    "node_modules",
    "dist",
    "build",
    "htmlcov",
    "coverage",
}


@dataclass(frozen=True)
class ContextAudit:
    root: Path
    total_bytes: int
    file_count: int
    top_entries: List[Tuple[str, int]]
    prohibited_entries: List[str]

    @property
    def ok(self) -> bool:
        return not self.prohibited_entries


def load_dockerignore(root: Path) -> List[str]:
    ignore_file = root / ".dockerignore"
    if not ignore_file.exists():
        return []

    patterns = []
    for line in ignore_file.read_text(encoding="utf-8").splitlines():
        pattern = line.strip()
        if not pattern or pattern.startswith("#") or pattern.startswith("!"):
            continue
        patterns.append(pattern.strip("/"))
    return patterns


def is_ignored(relative_path: str, patterns: Sequence[str]) -> bool:
    parts = Path(relative_path).parts
    for pattern in patterns:
        if not pattern:
            continue
        if pattern in parts:
            return True
        if fnmatch.fnmatch(relative_path, pattern):
            return True
        if fnmatch.fnmatch(Path(relative_path).name, pattern):
            return True
    return False


def is_prohibited(relative_path: str, names: Iterable[str]) -> bool:
    parts = set(Path(relative_path).parts)
    return any(name in parts for name in names)


def audit_context(
    root: Path,
    prohibited_names: Iterable[str] = DEFAULT_PROHIBITED_NAMES,
) -> ContextAudit:
    root = root.resolve()
    ignore_patterns = load_dockerignore(root)
    top_entries: List[Tuple[str, int]] = []
    prohibited_entries = set()
    total_bytes = 0
    file_count = 0

    for current_root, dirs, files in os.walk(root):
        current = Path(current_root)
        rel_dir = current.relative_to(root).as_posix()
        if rel_dir == ".":
            rel_dir = ""

        dirs[:] = [
            directory
            for directory in dirs
            if not is_ignored(
                f"{rel_dir}/{directory}".strip("/"),
                ignore_patterns,
            )
        ]

        for filename in files:
            rel_path = f"{rel_dir}/{filename}".strip("/")
            if is_ignored(rel_path, ignore_patterns):
                continue

            file_path = current / filename
            size = file_path.stat().st_size
            total_bytes += size
            file_count += 1
            top_entries.append((rel_path, size))

            if is_prohibited(rel_path, prohibited_names):
                prohibited_entries.add(rel_path)

    top_entries.sort(key=lambda item: item[1], reverse=True)
    return ContextAudit(
        root=root,
        total_bytes=total_bytes,
        file_count=file_count,
        top_entries=top_entries[:10],
        prohibited_entries=sorted(prohibited_entries),
    )


def format_bytes(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value} B"


def run_audit(root: Path, max_bytes: int) -> int:
    audit = audit_context(root)
    print(
        "Docker context size: "
        f"{format_bytes(audit.total_bytes)} across {audit.file_count} files "
        f"(budget {format_bytes(max_bytes)})"
    )
    print("Largest context entries:")
    for path, size in audit.top_entries:
        print(f"  {format_bytes(size):>10}  {path}")

    failures = []
    if audit.total_bytes > max_bytes:
        failures.append(
            "context size exceeds budget: "
            f"{format_bytes(audit.total_bytes)} > {format_bytes(max_bytes)}"
        )
    if audit.prohibited_entries:
        entries = ", ".join(audit.prohibited_entries[:20])
        failures.append(f"prohibited generated paths included: {entries}")

    if failures:
        print("Docker context audit failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("Docker context audit passed")
    return 0


def main_with_args_for_test(root: Path, max_bytes: int) -> int:
    return run_audit(root, max_bytes)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    args = parser.parse_args()
    return run_audit(args.root, args.max_bytes)


if __name__ == "__main__":
    raise SystemExit(main())
