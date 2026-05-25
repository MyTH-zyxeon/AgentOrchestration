"""Safe table projection and rendering helpers."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional, Tuple


@dataclass(frozen=True)
class TableColumn:
    key: str
    label: str
    sensitive: bool = False
    permission: Optional[str] = None


@dataclass(frozen=True)
class TableDefinition:
    name: str
    columns: Tuple[TableColumn, ...]
    default_visible_keys: FrozenSet[str]


class UnknownTableError(ValueError):
    """Raised when a caller requests an unregistered table."""


TASK_TABLE = TableDefinition(
    name="tasks",
    columns=(
        TableColumn("task_id", "Task ID"),
        TableColumn("title", "Title"),
        TableColumn("status", "Status"),
        TableColumn(
            "assignee_email",
            "Assignee email",
            sensitive=True,
            permission="tasks:view_sensitive",
        ),
        TableColumn(
            "internal_notes",
            "Internal notes",
            sensitive=True,
            permission="tasks:view_sensitive",
        ),
    ),
    default_visible_keys=frozenset({"task_id", "title", "status"}),
)

MEMBER_TABLE = TableDefinition(
    name="members",
    columns=(
        TableColumn("member_id", "Member ID"),
        TableColumn("display_name", "Display name"),
        TableColumn("role", "Role"),
        TableColumn(
            "email",
            "Email",
            sensitive=True,
            permission="members:view_sensitive",
        ),
        TableColumn(
            "last_login_ip",
            "Last login IP",
            sensitive=True,
            permission="members:view_sensitive",
        ),
    ),
    default_visible_keys=frozenset({"member_id", "display_name", "role"}),
)

TABLES: Dict[str, TableDefinition] = {
    TASK_TABLE.name: TASK_TABLE,
    MEMBER_TABLE.name: MEMBER_TABLE,
}


def get_table(table_name: str) -> TableDefinition:
    try:
        return TABLES[table_name]
    except KeyError as exc:
        raise UnknownTableError(f"Unknown table: {table_name}") from exc


def _normalise(values: Optional[Iterable[str]]) -> FrozenSet[str]:
    return frozenset(value for value in values or () if value)


def _requested_keys(
    table: TableDefinition,
    visible_keys: Optional[Iterable[str]],
) -> FrozenSet[str]:
    if visible_keys is None:
        return table.default_visible_keys
    return _normalise(visible_keys)


def authorized_visible_columns(
    table_name: str,
    visible_keys: Optional[Iterable[str]] = None,
    granted_permissions: Optional[Iterable[str]] = None,
) -> Tuple[TableColumn, ...]:
    """Return only columns that may be fetched and rendered."""
    table = get_table(table_name)
    requested = _requested_keys(table, visible_keys)
    permissions = _normalise(granted_permissions)

    return tuple(
        column
        for column in table.columns
        if column.key in requested
        and (not column.sensitive or column.permission in permissions)
    )


def authorized_column_options(
    table_name: str,
    granted_permissions: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """Return toggle metadata without advertising unauthorized columns."""
    table = get_table(table_name)
    permissions = _normalise(granted_permissions)
    allowed = (
        column
        for column in table.columns
        if not column.sensitive or column.permission in permissions
    )
    return [
        {
            "key": column.key,
            "label": column.label,
            "sensitive": column.sensitive,
        }
        for column in allowed
    ]


def fields_to_fetch(
    table_name: str,
    visible_keys: Optional[Iterable[str]] = None,
    granted_permissions: Optional[Iterable[str]] = None,
) -> Tuple[str, ...]:
    return tuple(
        column.key
        for column in authorized_visible_columns(
            table_name,
            visible_keys,
            granted_permissions,
        )
    )


def project_rows(
    table_name: str,
    rows: Iterable[Mapping[str, Any]],
    visible_keys: Optional[Iterable[str]] = None,
    granted_permissions: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """Project rows before serialization.

    Hidden fields never leave the API payload.
    """
    fields = fields_to_fetch(table_name, visible_keys, granted_permissions)
    return [
        {
            field: row[field]
            for field in fields
            if field in row
        }
        for row in rows
    ]


def build_table_payload(
    table_name: str,
    rows: Iterable[Mapping[str, Any]],
    visible_keys: Optional[Iterable[str]] = None,
    granted_permissions: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    columns = authorized_visible_columns(
        table_name,
        visible_keys,
        granted_permissions,
    )
    return {
        "table": table_name,
        "columns": [
            {
                "key": column.key,
                "label": column.label,
                "sensitive": column.sensitive,
            }
            for column in columns
        ],
        "fields_to_fetch": [column.key for column in columns],
        "rows": project_rows(
            table_name,
            rows,
            (column.key for column in columns),
            granted_permissions,
        ),
    }


def render_table_markup(
    table_name: str,
    rows: Iterable[Mapping[str, Any]],
    visible_keys: Optional[Iterable[str]] = None,
    granted_permissions: Optional[Iterable[str]] = None,
) -> str:
    payload = build_table_payload(
        table_name,
        rows,
        visible_keys,
        granted_permissions,
    )

    header_cells = "".join(
        "<th data-column=\"{key}\">{label}</th>".format(
            key=escape(column["key"], quote=True),
            label=escape(column["label"]),
        )
        for column in payload["columns"]
    )
    body_rows = []
    for row in payload["rows"]:
        cells = "".join(
            "<td data-column=\"{key}\">{value}</td>".format(
                key=escape(column["key"], quote=True),
                value=escape(str(row.get(column["key"], ""))),
            )
            for column in payload["columns"]
        )
        body_rows.append(f"<tr>{cells}</tr>")

    return (
        "<table>"
        f"<thead><tr>{header_cells}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
    )
