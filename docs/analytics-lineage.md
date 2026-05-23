# Analytics Lineage

Transformed analytics datasets must include lineage metadata before they are
published. The metadata records the source table, transform version, generation
time, optional source columns, and optional source record count used by the
transform.

```python
from src.analytics import LineageMetadata, publish_transformed_dataset, with_lineage

dataset = with_lineage(
    [{"metric": "average_task_duration_ms", "value": 100}],
    LineageMetadata(
        source_table="task_events",
        transform_version="analytics.pipeline.v1",
        source_columns=["duration_ms"],
        input_record_count=10,
    ),
)
publish_transformed_dataset("out/task_metrics.json", dataset)
```

`publish_transformed_dataset` validates the lineage block before writing. It
raises `LineageError` and leaves the target path untouched when `source_table`,
`transform_version`, or `generated_at` is missing.

To trace a metric back to source data, load the transformed dataset and call
`trace_metric_lineage(dataset, metric_name)`. The result includes the metric
name, source table, transform version, generation timestamp, source columns, and
input record count.
