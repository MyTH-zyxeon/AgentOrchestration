import tempfile

import pytest

from src.common.artifacts import ArtifactStore, DigestMismatchError


class TestArtifactStore:
    def setup_method(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = ArtifactStore(self.temp_dir.name)

    def teardown_method(self):
        self.temp_dir.cleanup()

    def test_same_content_deduplicates_by_digest(self):
        first = self.store.store("report.csv", b"same-content")
        second = self.store.store("copy.csv", b"same-content")

        assert first.blob.digest == second.blob.digest
        assert first.blob.path == second.blob.path
        assert self.store.blob_count() == 1

    def test_same_name_different_content_gets_new_blob(self):
        first = self.store.store("artifact.log", b"first")
        second = self.store.store("artifact.log", b"second")

        assert first.blob.digest != second.blob.digest
        assert first.blob.path != second.blob.path
        assert second.version == 2
        assert self.store.read("artifact.log") == b"second"
        assert self.store.blob_count() == 2

    def test_digest_mismatch_fails_suspicious_metadata_reuse(self):
        claimed = ArtifactStore.compute_digest(b"old-content")

        with pytest.raises(DigestMismatchError):
            self.store.store(
                "artifact.bin",
                b"new-content",
                metadata={"content_digest": claimed, "source": "upload"},
            )

        assert self.store.get("artifact.bin") is None
        assert self.store.blob_count() == 1

    def test_verify_detects_blob_tampering(self):
        record = self.store.store("metrics.json", b'{"ok": true}')
        blob_path = self.store.root / record.blob.path
        blob_path.write_bytes(b'{"ok": false}')

        assert not self.store.verify("metrics.json")

    def test_metadata_includes_immutable_blob_reference(self):
        record = self.store.store(
            "trace.txt",
            b"trace-content",
            metadata={"task_id": "task-1"},
        )

        stored = self.store.get("trace.txt")
        assert stored is not None
        assert stored.metadata["content_digest"] == record.blob.digest
        assert stored.metadata["blob_ref"] == record.blob.path
        assert stored.metadata["task_id"] == "task-1"
