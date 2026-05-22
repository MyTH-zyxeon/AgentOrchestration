from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


WORKFLOW_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = WORKFLOW_ROOT / "src" / "orchestrator" / "workflow.py"
SPEC = spec_from_file_location("workflow_module", WORKFLOW_PATH)
workflow_module = module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(workflow_module)

StepStatus = workflow_module.StepStatus
WorkflowManager = workflow_module.WorkflowManager
WorkflowParameterError = workflow_module.WorkflowParameterError
WorkflowStep = workflow_module.WorkflowStep


class TestWorkflowParameters:
    def test_execute_preserves_explicit_false_default(self):
        manager = WorkflowManager()
        workflow = manager.create_workflow("false-default")
        step = WorkflowStep(
            "feature flag",
            lambda enabled: enabled,
            parameter_defaults={"enabled": False},
            required_parameters=["enabled"],
        )
        workflow.add_step(step)

        assert manager.execute_workflow(workflow.id) is True
        assert step.result is False
        assert step.parameter_audit[-1] == {
            "event": "parameters_bound",
            "keys": ["enabled"],
        }

    def test_execute_preserves_explicit_false_override(self):
        manager = WorkflowManager()
        workflow = manager.create_workflow("false-override")
        step = WorkflowStep(
            "feature flag",
            lambda enabled: enabled,
            parameter_defaults={"enabled": True},
            parameters={"enabled": False},
            required_parameters=["enabled"],
        )
        workflow.add_step(step)

        assert manager.execute_workflow(workflow.id) is True
        assert step.result is False

    def test_missing_required_parameter_does_not_advance_lifecycle(self):
        manager = WorkflowManager()
        workflow = manager.create_workflow("missing-param")
        step = WorkflowStep(
            "requires value",
            lambda required: required,
            required_parameters=["required"],
        )
        workflow.add_step(step)

        assert manager.execute_workflow(workflow.id) is False
        assert workflow.status == StepStatus.PENDING
        assert step.status == StepStatus.PENDING
        assert "required" in step.error
        assert step.parameter_audit[-1] == {
            "event": "parameters_rejected",
            "missing": ["required"],
        }

    def test_parameter_audit_records_names_without_values(self):
        step = WorkflowStep(
            "secret param",
            lambda enabled, token: enabled,
            parameter_defaults={"enabled": False, "token": "secret-token"},
            required_parameters=["token"],
        )

        params = step.bind_parameters()

        assert params["token"] == "secret-token"
        assert "secret-token" not in str(step.parameter_audit)
        assert step.parameter_audit[-1] == {
            "event": "parameters_bound",
            "keys": ["enabled", "token"],
        }

    def test_bind_parameters_rejects_missing_required_key(self):
        step = WorkflowStep(
            "requires value",
            lambda required: required,
            required_parameters=["required"],
        )

        try:
            step.bind_parameters()
        except WorkflowParameterError as exc:
            assert "required" in str(exc)
        else:
            raise AssertionError("required parameter was accepted")
