import pytest

from src.agent.identity import IdentityGroupRoleMapper


class TestIdentityGroupRoleMapper:
    def setup_method(self):
        self.mapper = IdentityGroupRoleMapper()

    def test_role_mapping_ignores_display_name_only_matches(self):
        self.mapper.register_group_role(
            "idp-group-admins",
            "workspace-admin",
            display_name="Admins",
        )

        roles = self.mapper.resolve_roles(
            [{"display_name": "Admins"}]
        )

        assert roles == set()

    def test_role_mapping_uses_external_group_id_after_rename(self):
        self.mapper.register_group_role(
            "idp-group-admins",
            "workspace-admin",
            display_name="Admins",
        )

        roles = self.mapper.resolve_roles(
            [
                {
                    "external_id": "idp-group-admins",
                    "display_name": "Renamed Admins",
                }
            ]
        )

        assert roles == {"workspace-admin"}

    def test_duplicate_display_names_do_not_merge_roles(self):
        self.mapper.register_group_role(
            "idp-group-admins",
            "workspace-admin",
            display_name="Team",
        )
        self.mapper.register_group_role(
            "idp-group-viewers",
            "workspace-viewer",
            display_name="Team",
        )

        admin_roles = self.mapper.resolve_roles(
            [{"external_id": "idp-group-admins", "display_name": "Team"}]
        )
        missing_id_roles = self.mapper.resolve_roles(
            [{"display_name": "Team"}]
        )

        assert admin_roles == {"workspace-admin"}
        assert missing_id_roles == set()

    def test_repair_requires_administrator_approval_and_audit_metadata(self):
        self.mapper.register_group_role(
            "idp-group-admins",
            "workspace-admin",
            display_name="Admins",
        )

        with pytest.raises(ValueError):
            self.mapper.repair_group_mapping(
                "idp-group-admins",
                "idp-group-admins-v2",
                approved_by="",
                reason="IdP migration",
            )

        self.mapper.repair_group_mapping(
            "idp-group-admins",
            "idp-group-admins-v2",
            approved_by="security-admin",
            reason="IdP migration changed immutable group ID",
            display_name="Admins",
        )

        roles = self.mapper.resolve_roles(
            [{"external_id": "idp-group-admins-v2", "display_name": "Admins"}]
        )
        repair_events = [
            entry
            for entry in self.mapper.audit_log()
            if entry["event"] == "identity_group_mapping_repaired"
        ]

        assert roles == {"workspace-admin"}
        assert repair_events == [
            {
                "event": "identity_group_mapping_repaired",
                "old_external_group_id": "idp-group-admins",
                "new_external_group_id": "idp-group-admins-v2",
                "display_name": "Admins",
                "approved_by": "security-admin",
                "reason": "IdP migration changed immutable group ID",
                "roles": ["workspace-admin"],
                "timestamp": repair_events[0]["timestamp"],
            }
        ]

    def test_repair_rejects_unknown_old_external_id(self):
        with pytest.raises(KeyError):
            self.mapper.repair_group_mapping(
                "missing-group",
                "idp-group-admins-v2",
                approved_by="security-admin",
                reason="IdP migration",
            )
