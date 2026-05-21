import pytest

from src.common.report_cache import AuthorizationContext, ReportingResultCache


def _context(
    *,
    roles=("admin",),
    workspace_id="workspace-a",
    scopes=("reports:read",),
    access_version="v1",
):
    return AuthorizationContext.from_values(
        user_id="user-1",
        workspace_id=workspace_id,
        roles=roles,
        scopes=scopes,
        access_version=access_version,
    )


def test_role_downgrade_does_not_reuse_admin_cached_report():
    cache = ReportingResultCache(
        lambda context: "reports:read" in context.scopes
    )
    params = {"range": "month"}

    cache.set(
        "revenue", params, _context(roles=("admin",)), {"rows": ["admin"]}
    )

    assert cache.get("revenue", params, _context(roles=("viewer",))) is None


def test_workspace_removal_revalidates_before_cached_hit():
    allowed_workspaces = {"workspace-a"}
    cache = ReportingResultCache(
        lambda context: context.workspace_id in allowed_workspaces
    )
    context = _context(workspace_id="workspace-a")

    cache.set("revenue", {"range": "month"}, context, {"rows": ["private"]})
    allowed_workspaces.clear()

    with pytest.raises(PermissionError, match="report cache access denied"):
        cache.get("revenue", {"range": "month"}, context)


def test_cache_key_includes_workspace_role_scope_and_access_version():
    cache = ReportingResultCache(lambda context: True)
    params = {"filters": {"region": "apac"}}
    admin_v1 = _context(roles=("admin",), access_version="v1")
    admin_v2 = _context(roles=("admin",), access_version="v2")
    owner_v1 = _context(roles=("owner",), access_version="v1")
    other_scope = _context(roles=("admin",), scopes=("reports:export",))
    other_workspace = _context(workspace_id="workspace-b")

    cache.set("revenue", params, admin_v1, {"rows": ["admin-v1"]})

    assert cache.get("revenue", params, admin_v1) == {"rows": ["admin-v1"]}
    assert cache.get("revenue", params, admin_v2) is None
    assert cache.get("revenue", params, owner_v1) is None
    assert cache.get("revenue", params, other_scope) is None
    assert cache.get("revenue", params, other_workspace) is None


def test_cached_report_payloads_are_isolated_from_callers():
    cache = ReportingResultCache(lambda context: True)
    context = _context()
    params = {"range": "month"}

    cache.set("revenue", params, context, {"rows": [{"value": 1}]})
    first = cache.get("revenue", params, context)
    first["rows"][0]["value"] = 99

    assert cache.get("revenue", params, context) == {"rows": [{"value": 1}]}
