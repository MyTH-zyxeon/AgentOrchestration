from src.common.data_retention import (
    InMemoryRetentionStore,
    RetentionDeletionWorkflow,
)


def _build_workflow():
    stores = {
        "artifacts": InMemoryRetentionStore("artifacts", {"doc-1"}),
        "embeddings": InMemoryRetentionStore(
            "embeddings",
            {"doc-1:chunk-1", "doc-1:chunk-2"},
        ),
        "embedding_index": InMemoryRetentionStore(
            "embedding_index",
            {"doc-1:index"},
        ),
    }
    return RetentionDeletionWorkflow(stores), stores


def _build_manifest(workflow):
    return workflow.build_manifest(
        workspace_id="tenant-a",
        primary_store="artifacts",
        primary_key="doc-1",
        derived_targets={
            "embeddings": ["doc-1:chunk-1", "doc-1:chunk-2"],
            "embedding_index": ["doc-1:index"],
        },
    )


def test_manifest_lists_primary_and_derived_stores():
    workflow, _ = _build_workflow()
    manifest = _build_manifest(workflow)

    assert manifest.affected_stores == (
        "artifacts",
        "embedding_index",
        "embeddings",
    )
    assert manifest.primary_target.store == "artifacts"
    assert {target.store for target in manifest.derived_targets} == {
        "embedding_index",
        "embeddings",
    }


def test_delete_manifest_removes_primary_and_derived_records():
    workflow, stores = _build_workflow()
    manifest = _build_manifest(workflow)

    record = workflow.delete_manifest(manifest)

    assert record.complete
    assert len(record.completions) == 4
    assert record.affected_stores == (
        "artifacts",
        "embedding_index",
        "embeddings",
    )
    assert not stores["artifacts"].contains("doc-1")
    assert not stores["embeddings"].contains("doc-1:chunk-1")
    assert not stores["embeddings"].contains("doc-1:chunk-2")
    assert not stores["embedding_index"].contains("doc-1:index")


def test_reconcile_removes_stale_derived_records_when_primary_is_missing():
    workflow, stores = _build_workflow()
    stores["artifacts"].delete("doc-1")
    manifest = _build_manifest(workflow)

    record = workflow.reconcile(manifest)

    assert len(record.stale_derived_removed) == 3
    assert record.affected_stores == ("embedding_index", "embeddings")
    assert stores["embeddings"].snapshot() == set()
    assert stores["embedding_index"].snapshot() == set()


def test_reconcile_keeps_derived_records_when_primary_exists():
    workflow, stores = _build_workflow()
    manifest = _build_manifest(workflow)

    record = workflow.reconcile(manifest)

    assert record.stale_derived_removed == ()
    assert stores["embeddings"].contains("doc-1:chunk-1")
    assert stores["embedding_index"].contains("doc-1:index")
