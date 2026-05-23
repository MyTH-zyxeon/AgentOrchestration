import json
from datetime import datetime, timezone

import pytest

from src.analytics import (
    LineageError,
    LineageMetadata,
    publish_transformed_dataset,
    trace_metric_lineage,
    with_lineage,
)


def test_publish_transformed_dataset_writes_lineage_metadata(tmp_path):
    metadata = LineageMetadata(
        source_table="task_events",
        transform_version="analytics.pipeline.v1",
        generated_at=datetime(2026, 5, 23, 4, 0, tzinfo=timezone.utc),
        source_columns=["task_id", "duration_ms"],
        input_record_count=2,
    )
    dataset = with_lineage(
        [
            {"task_id": "task-1", "duration_ms": 120},
            {"task_id": "task-2", "duration_ms": 80},
        ],
        metadata,
    )

    output_path = tmp_path / "task_metrics.json"
    publish_transformed_dataset(output_path, dataset)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["lineage"]["source_table"] == "task_events"
    assert payload["lineage"]["transform_version"] == "analytics.pipeline.v1"
    assert payload["records"][0]["task_id"] == "task-1"


def test_publish_transformed_dataset_fails_without_lineage(tmp_path):
    output_path = tmp_path / "missing-lineage.json"

    with pytest.raises(LineageError, match="missing lineage metadata"):
        publish_transformed_dataset(output_path, {"records": []})

    assert not output_path.exists()


def test_trace_metric_lineage_explains_metric_source():
    dataset = with_lineage(
        [{"metric": "average_task_duration_ms", "value": 100}],
        LineageMetadata(
            source_table="task_events",
            transform_version="analytics.pipeline.v2",
            generated_at=datetime(2026, 5, 23, 4, 5, tzinfo=timezone.utc),
            source_columns=["duration_ms"],
            input_record_count=10,
        ),
    )

    trace = trace_metric_lineage(dataset, "average_task_duration_ms")

    assert trace == {
        "metric": "average_task_duration_ms",
        "source_table": "task_events",
        "transform_version": "analytics.pipeline.v2",
        "generated_at": "2026-05-23T04:05:00+00:00",
        "source_columns": ["duration_ms"],
        "input_record_count": 10,
    }
