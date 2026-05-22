"""Dependency review exception manifest validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

import yaml


DATE_FIELDS = ("expires_on", "expires", "expiration_date")


@dataclass(frozen=True)
class DependencyExceptionManifest:
    """Parsed dependency review exception manifest."""

    path: Path
    records: List[Dict[str, Any]]
    source_lines: Dict[str, int]


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def load_manifest(path: Path) -> DependencyExceptionManifest:
    text = path.read_text(encoding="utf-8")
    loaded = yaml.safe_load(text) or {}
    if not isinstance(loaded, Mapping):
        raise ValueError("manifest root must be a mapping")

    records = loaded.get("exceptions", [])
    if records is None:
        records = []
    if not isinstance(records, list):
        raise ValueError("manifest exceptions must be a list")

    normalized_records = []
    for index, record in enumerate(records, start=1):
        if not isinstance(record, Mapping):
            raise ValueError(f"exception #{index} must be a mapping")
        normalized_records.append(dict(record))

    return DependencyExceptionManifest(
        path=path,
        records=normalized_records,
        source_lines=_source_lines_by_id(text),
    )


def validate_manifest(
    manifest: DependencyExceptionManifest,
    *,
    today: Optional[date] = None,
) -> List[str]:
    current_date = today or utc_today()
    errors: List[str] = []
    seen_ids = set()

    for index, record in enumerate(manifest.records, start=1):
        record_id = _string_value(record, "id") or f"#{index}"
        if not _string_value(record, "id"):
            errors.append(f"{record_id}: id is required")
        elif record_id in seen_ids:
            errors.append(f"{record_id}: id must be unique")
        seen_ids.add(record_id)

        for field in ("owner", "reason"):
            if not _string_value(record, field):
                errors.append(f"{record_id}: {field} is required")

        coordinate_error = _validate_coordinate(record)
        if coordinate_error:
            errors.append(f"{record_id}: {coordinate_error}")

        expires_value = _date_field_value(record)
        if not expires_value:
            errors.append(f"{record_id}: expires_on is required")
            continue

        try:
            expires_on = parse_date(str(expires_value))
        except ValueError:
            errors.append(f"{record_id}: expires_on must be an ISO date")
            continue

        if expires_on < current_date:
            errors.append(
                f"{record_id}: expired on {expires_on.isoformat()}; "
                "remove or renew the exception"
            )

    return errors


def validate_overrides(
    manifest: DependencyExceptionManifest,
    overrides: Iterable[str],
    *,
    today: Optional[date] = None,
) -> List[str]:
    current_date = today or utc_today()
    active_keys = set()
    for record in manifest.records:
        expires_value = _date_field_value(record)
        try:
            expires_on = (
                parse_date(str(expires_value)) if expires_value else None
            )
        except ValueError:
            expires_on = None

        if expires_on and expires_on >= current_date:
            record_id = _string_value(record, "id")
            coordinate = dependency_coordinate(record)
            if record_id:
                active_keys.add(record_id)
            if coordinate:
                active_keys.add(coordinate)

    errors = []
    for override in _normalize_overrides(overrides):
        if override not in active_keys:
            errors.append(
                f"{override}: override has no active matching manifest entry"
            )
    return errors


def render_summary(
    manifest: DependencyExceptionManifest,
    *,
    today: Optional[date] = None,
    repository: Optional[str] = None,
    server_url: str = "https://github.com",
    ref: Optional[str] = None,
    validation_errors: Optional[Sequence[str]] = None,
) -> str:
    current_date = today or utc_today()
    errors = list(validation_errors or [])
    manifest_url = _manifest_url(
        manifest.path,
        repository=repository,
        server_url=server_url,
        ref=ref,
    )

    lines = [
        "## Dependency Review Exceptions",
        "",
        f"Manifest: [{manifest.path.as_posix()}]({manifest_url})",
        f"Validation date: `{current_date.isoformat()}`",
        "",
    ]

    if errors:
        lines.extend(["### Validation errors", ""])
        lines.extend(f"- `{_escape_markdown(error)}`" for error in errors)
        lines.append("")

    if not manifest.records:
        lines.append("No dependency review exceptions are registered.")
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "| ID | Dependency | Owner | Expires | Record |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for record in manifest.records:
        record_id = _string_value(record, "id") or "(missing id)"
        coordinate = dependency_coordinate(record) or "(missing coordinate)"
        owner = _string_value(record, "owner") or "(missing owner)"
        expires = str(_date_field_value(record) or "(missing expiry)")
        record_url = _record_url(
            manifest_url,
            manifest.source_lines.get(record_id),
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape_table_cell(record_id),
                    _escape_table_cell(coordinate),
                    _escape_table_cell(owner),
                    _escape_table_cell(expires),
                    f"[manifest record]({record_url})",
                ]
            )
            + " |"
        )

    return "\n".join(lines) + "\n"


def dependency_coordinate(record: Mapping[str, Any]) -> Optional[str]:
    explicit = _string_value(record, "coordinate")
    if explicit:
        return explicit

    ecosystem = _string_value(record, "ecosystem")
    name = _string_value(record, "name")
    version = _string_value(record, "version") or _string_value(
        record, "version_range"
    )
    if not ecosystem or not name:
        return None

    coordinate = f"{ecosystem}:{name}"
    if version:
        coordinate += f"@{version}"
    return coordinate


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _validate_coordinate(record: Mapping[str, Any]) -> Optional[str]:
    if _string_value(record, "coordinate"):
        return None

    missing = []
    for field in ("ecosystem", "name"):
        if not _string_value(record, field):
            missing.append(field)
    if not (
        _string_value(record, "version")
        or _string_value(record, "version_range")
    ):
        missing.append("version or version_range")

    if missing:
        return "dependency coordinate requires " + ", ".join(missing)
    return None


def _date_field_value(record: Mapping[str, Any]) -> Optional[Any]:
    for field in DATE_FIELDS:
        value = record.get(field)
        if value:
            return value
    return None


def _string_value(record: Mapping[str, Any], field: str) -> str:
    value = record.get(field)
    if value is None:
        return ""
    return str(value).strip()


def _normalize_overrides(overrides: Iterable[str]) -> List[str]:
    normalized = []
    for override in overrides:
        for item in str(override).replace(",", "\n").splitlines():
            item = item.strip()
            if item:
                normalized.append(item)
    return normalized


def _source_lines_by_id(text: str) -> Dict[str, int]:
    line_by_id: Dict[str, int] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("id:"):
            value = stripped.split(":", 1)[1].strip().strip("'\"")
            if value:
                line_by_id[value] = line_number
        elif stripped.startswith("- id:"):
            value = stripped.split(":", 1)[1].strip().strip("'\"")
            if value:
                line_by_id[value] = line_number
    return line_by_id


def _manifest_url(
    path: Path,
    *,
    repository: Optional[str],
    server_url: str,
    ref: Optional[str],
) -> str:
    if repository:
        revision = ref or "HEAD"
        return (
            f"{server_url.rstrip('/')}/{repository}/blob/{revision}/"
            f"{path.as_posix()}"
        )
    return path.as_posix()


def _record_url(manifest_url: str, line_number: Optional[int]) -> str:
    if line_number is None:
        return manifest_url
    return f"{manifest_url}#L{line_number}"


def _escape_markdown(value: str) -> str:
    return value.replace("`", "'")


def _escape_table_cell(value: str) -> str:
    return _escape_markdown(value).replace("|", "\\|")


def validation_errors_for(
    manifest: DependencyExceptionManifest,
    overrides: Iterable[str],
    *,
    today: Optional[date] = None,
) -> Tuple[List[str], List[str]]:
    manifest_errors = validate_manifest(manifest, today=today)
    override_errors = validate_overrides(manifest, overrides, today=today)
    return manifest_errors, override_errors
