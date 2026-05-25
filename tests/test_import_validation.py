import asyncio

import pytest
from fastapi import HTTPException

from src.api.routes import (
    WorkflowImportValidationRequest,
    validate_workflow_import,
)
from src.common.import_validation import (
    UNSUPPORTED_WORKFLOW_IMPORT_FILE_ERROR,
    WORKFLOW_IMPORT_FILE_TYPES,
    WorkflowImportValidationError,
    validate_workflow_import_file,
)


def test_accepts_json_workflow_import_content():
    detected_format = validate_workflow_import_file(
        "workflow.json",
        "application/json; charset=utf-8",
        b'{"name": "daily-sync", "steps": []}',
    )

    assert detected_format == "json"


def test_rejects_renamed_unsupported_content():
    with pytest.raises(
        WorkflowImportValidationError,
        match=UNSUPPORTED_WORKFLOW_IMPORT_FILE_ERROR,
    ):
        validate_workflow_import_file(
            "workflow.json",
            "application/json",
            b"#!/bin/sh\nrm -rf /",
        )


def test_rejects_mismatched_mime_type():
    with pytest.raises(
        WorkflowImportValidationError,
        match=UNSUPPORTED_WORKFLOW_IMPORT_FILE_ERROR,
    ):
        validate_workflow_import_file(
            "workflow.yaml",
            "application/json",
            "name: daily-sync\nsteps: []\n",
        )


def test_accepted_type_lists_are_shared_config():
    accepted_types = WORKFLOW_IMPORT_FILE_TYPES.as_dict()

    assert ".json" in accepted_types["extensions"]
    assert ".yaml" in accepted_types["extensions"]
    assert "application/json" in accepted_types["mime_types"]
    assert "application/x-yaml" in accepted_types["mime_types"]


def test_validate_workflow_import_route_reuses_shared_validator():
    request = WorkflowImportValidationRequest(
        filename="workflow.yml",
        content_type="text/yaml",
        content="name: daily-sync\nsteps: []\n",
    )

    assert asyncio.run(validate_workflow_import(request)) == {
        "status": "valid",
        "format": "yaml",
    }


def test_validate_workflow_import_route_uses_consistent_error_message():
    request = WorkflowImportValidationRequest(
        filename="workflow.yml",
        content_type="application/json",
        content="name: daily-sync\nsteps: []\n",
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(validate_workflow_import(request))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == UNSUPPORTED_WORKFLOW_IMPORT_FILE_ERROR
