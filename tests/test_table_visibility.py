import json

from src.api.table_visibility import (
    authorized_column_options,
    build_table_payload,
    fields_to_fetch,
    render_table_markup,
)


def test_hidden_sensitive_task_fields_are_absent_from_payload_and_markup():
    rows = [
        {
            "task_id": "task-1",
            "title": "Rotate launch key",
            "status": "open",
            "assignee_email": "ops@example.com",
            "internal_notes": "Vault token moves before launch",
        }
    ]

    payload = build_table_payload(
        "tasks",
        rows,
        visible_keys=("task_id", "title", "status"),
        granted_permissions=("tasks:view_sensitive",),
    )
    markup = render_table_markup(
        "tasks",
        rows,
        visible_keys=("task_id", "title", "status"),
        granted_permissions=("tasks:view_sensitive",),
    )

    serialized = json.dumps(payload)
    assert payload["fields_to_fetch"] == ["task_id", "title", "status"]
    assert "Rotate launch key" in serialized
    assert "ops@example.com" not in serialized
    assert "Vault token" not in serialized
    assert "ops@example.com" not in markup
    assert "Vault token" not in markup
    assert 'data-column="assignee_email"' not in markup
    assert 'data-column="internal_notes"' not in markup


def test_unauthorized_member_toggle_is_ignored_before_fetch_and_render():
    rows = [
        {
            "member_id": "member-1",
            "display_name": "Alex",
            "role": "admin",
            "email": "alex@example.com",
            "last_login_ip": "192.0.2.42",
        }
    ]

    payload = build_table_payload(
        "members",
        rows,
        visible_keys=("member_id", "display_name", "email", "last_login_ip"),
        granted_permissions=(),
    )
    markup = render_table_markup(
        "members",
        rows,
        visible_keys=("member_id", "display_name", "email", "last_login_ip"),
        granted_permissions=(),
    )

    assert payload["fields_to_fetch"] == ["member_id", "display_name"]
    assert payload["rows"] == [
        {"member_id": "member-1", "display_name": "Alex"}
    ]
    assert "alex@example.com" not in json.dumps(payload)
    assert "192.0.2.42" not in json.dumps(payload)
    assert "alex@example.com" not in markup
    assert "192.0.2.42" not in markup


def test_authorized_member_toggle_fetches_only_requested_sensitive_field():
    rows = [
        {
            "member_id": "member-1",
            "display_name": "Alex",
            "role": "admin",
            "email": "alex@example.com",
            "last_login_ip": "192.0.2.42",
        }
    ]

    payload = build_table_payload(
        "members",
        rows,
        visible_keys=("member_id", "email"),
        granted_permissions=("members:view_sensitive",),
    )

    assert fields_to_fetch(
        "members",
        visible_keys=("member_id", "email"),
        granted_permissions=("members:view_sensitive",),
    ) == ("member_id", "email")
    assert payload["rows"] == [
        {"member_id": "member-1", "email": "alex@example.com"}
    ]
    assert "192.0.2.42" not in json.dumps(payload)


def test_column_options_do_not_offer_sensitive_toggles_without_permission():
    unauthorized = authorized_column_options("members", granted_permissions=())
    authorized = authorized_column_options(
        "members",
        granted_permissions=("members:view_sensitive",),
    )

    assert [column["key"] for column in unauthorized] == [
        "member_id",
        "display_name",
        "role",
    ]
    assert [column["key"] for column in authorized] == [
        "member_id",
        "display_name",
        "role",
        "email",
        "last_login_ip",
    ]


def test_rendered_values_are_escaped():
    rows = [
        {
            "task_id": "task-1",
            "title": '<script data-secret="x">alert(1)</script>',
            "status": "open",
        }
    ]

    markup = render_table_markup(
        "tasks",
        rows,
        visible_keys=("task_id", "title", "status"),
        granted_permissions=(),
    )

    assert "<script" not in markup
    expected = (
        "&lt;script data-secret=&quot;x&quot;&gt;"
        "alert(1)&lt;/script&gt;"
    )
    assert expected in markup
