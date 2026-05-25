"""Workflow import file type validation."""

import json
from dataclasses import dataclass
from pathlib import PurePath
from typing import Dict, FrozenSet, Mapping, Optional, Sequence, Union

import yaml


UNSUPPORTED_WORKFLOW_IMPORT_FILE_ERROR = (
    "Unsupported workflow definition file type"
)


@dataclass(frozen=True)
class WorkflowImportFileTypes:
    """Shared accepted type config for workflow definition imports."""

    extensions_by_format: Mapping[str, FrozenSet[str]]
    mime_types_by_format: Mapping[str, FrozenSet[str]]

    def accepted_extensions(self) -> Sequence[str]:
        return tuple(
            sorted(
                extension
                for extensions in self.extensions_by_format.values()
                for extension in extensions
            )
        )

    def accepted_mime_types(self) -> Sequence[str]:
        return tuple(
            sorted(
                mime_type
                for mime_types in self.mime_types_by_format.values()
                for mime_type in mime_types
            )
        )

    def format_for_extension(self, extension: str) -> Optional[str]:
        normalized = extension.lower()
        for file_format, extensions in self.extensions_by_format.items():
            if normalized in extensions:
                return file_format
        return None

    def format_for_mime_type(self, mime_type: str) -> Optional[str]:
        normalized = mime_type.split(";", 1)[0].strip().lower()
        for file_format, mime_types in self.mime_types_by_format.items():
            if normalized in mime_types:
                return file_format
        return None

    def as_dict(self) -> Dict[str, Sequence[str]]:
        return {
            "extensions": self.accepted_extensions(),
            "mime_types": self.accepted_mime_types(),
        }


WORKFLOW_IMPORT_FILE_TYPES = WorkflowImportFileTypes(
    extensions_by_format={
        "json": frozenset({".json"}),
        "yaml": frozenset({".yaml", ".yml"}),
    },
    mime_types_by_format={
        "json": frozenset({"application/json"}),
        "yaml": frozenset(
            {"application/x-yaml", "application/yaml", "text/yaml"}
        ),
    },
)


class WorkflowImportValidationError(ValueError):
    """Raised when a workflow import file cannot be trusted server-side."""


def validate_workflow_import_file(
    filename: str,
    content_type: Optional[str],
    content: Union[bytes, str],
    accepted_types: WorkflowImportFileTypes = WORKFLOW_IMPORT_FILE_TYPES,
) -> str:
    """Validate file metadata and content before import parsing."""

    extension = PurePath(filename or "").suffix.lower()
    file_format = accepted_types.format_for_extension(extension)
    if file_format is None:
        raise WorkflowImportValidationError(
            UNSUPPORTED_WORKFLOW_IMPORT_FILE_ERROR
        )

    normalized_mime_type = (
        (content_type or "").split(";", 1)[0].strip().lower()
    )
    if normalized_mime_type:
        mime_format = accepted_types.format_for_mime_type(
            normalized_mime_type
        )
        if mime_format != file_format:
            raise WorkflowImportValidationError(
                UNSUPPORTED_WORKFLOW_IMPORT_FILE_ERROR
            )

    content_bytes = (
        content.encode("utf-8") if isinstance(content, str) else content
    )
    if not _content_matches_format(file_format, content_bytes):
        raise WorkflowImportValidationError(
            UNSUPPORTED_WORKFLOW_IMPORT_FILE_ERROR
        )

    return file_format


def _content_matches_format(file_format: str, content: bytes) -> bool:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False

    if not text.strip():
        return False

    try:
        if file_format == "json":
            parsed = json.loads(text)
        elif file_format == "yaml":
            parsed = yaml.safe_load(text)
        else:
            return False
    except (json.JSONDecodeError, yaml.YAMLError):
        return False

    return isinstance(parsed, (dict, list))
