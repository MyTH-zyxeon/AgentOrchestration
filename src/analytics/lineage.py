"""Lineage metadata support for transformed analytics datasets."""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Union


REQUIRED_LINEAGE_FIELDS = ("source_table", "transform_version", "generated_at")


class LineageError(ValueError):
    """Raised when transformed analytics lineage metadata is invalid."""


@dataclass(frozen=True)
class LineageMetadata:
    """Source metadata required to publish transformed analytics datasets."""

    source_table: str
    transform_version: str
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    source_columns: Optional[List[str]] = None
    input_record_count: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        generated_at = self.generated_at
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)

        metadata: Dict[str, Any] = {
            "source_table": self.source_table,
            "transform_version": self.transform_version,
            "generated_at": generated_at.isoformat(),
        }
        if self.source_columns is not None:
            metadata["source_columns"] = list(self.source_columns)
        if self.input_record_count is not None:
            metadata["input_record_count"] = self.input_record_count
        validate_lineage({"lineage": metadata})
        return metadata


def with_lineage(
    records: Iterable[Mapping[str, Any]],
    metadata: LineageMetadata,
) -> Dict[str, Any]:
    """Return a transformed dataset payload with lineage metadata attached."""

    return {
        "lineage": metadata.to_dict(),
        "records": [dict(record) for record in records],
    }


def validate_lineage(dataset: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate and return lineage metadata for a transformed dataset."""

    lineage = dataset.get("lineage")
    if not isinstance(lineage, Mapping):
        raise LineageError("transformed dataset is missing lineage metadata")

    missing = [
        field
        for field in REQUIRED_LINEAGE_FIELDS
        if not str(lineage.get(field, "")).strip()
    ]
    if missing:
        fields = ", ".join(missing)
        raise LineageError(
            f"lineage metadata missing required field(s): {fields}"
        )

    try:
        datetime.fromisoformat(str(lineage["generated_at"]))
    except ValueError as exc:
        raise LineageError(
            "lineage generated_at must be an ISO timestamp"
        ) from exc

    record_count = lineage.get("input_record_count")
    if record_count is not None:
        if not isinstance(record_count, int) or record_count < 0:
            raise LineageError(
                "lineage input_record_count must be a non-negative int"
            )

    return dict(lineage)


def publish_transformed_dataset(
    output_path: Union[os.PathLike[str], str],
    dataset: Mapping[str, Any],
) -> None:
    """Write a transformed dataset only after required lineage validates."""

    validate_lineage(dataset)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output.with_name(f"{output.name}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(dict(dataset), handle, sort_keys=True)
        handle.write("\n")
    temp_path.replace(output)


def trace_metric_lineage(
    dataset: Mapping[str, Any],
    metric_name: str,
) -> Dict[str, Any]:
    """Return source lineage details for a metric derived from a dataset."""

    lineage = validate_lineage(dataset)
    return {
        "metric": metric_name,
        "source_table": lineage["source_table"],
        "transform_version": lineage["transform_version"],
        "generated_at": lineage["generated_at"],
        "source_columns": lineage.get("source_columns", []),
        "input_record_count": lineage.get("input_record_count"),
    }
