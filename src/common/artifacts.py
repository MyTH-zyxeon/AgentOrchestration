"""Content-addressed artifact storage."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


class DigestMismatchError(ValueError):
    """Raised when metadata claims a digest that does not match content."""


@dataclass(frozen=True)
class BlobRef:
    digest: str
    size: int
    path: str


@dataclass(frozen=True)
class ArtifactRecord:
    logical_name: str
    blob: BlobRef
    metadata: Dict[str, Any]
    version: int


class ArtifactStore:
    """Stores artifacts by verified content digest before deduplication."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.blob_dir = self.root / "blobs"
        self.metadata_dir = self.root / "metadata"
        self.blob_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)

    def store(
        self,
        logical_name: str,
        content: bytes,
        metadata: Optional[Dict[str, Any]] = None,
        claimed_digest: Optional[str] = None,
    ) -> ArtifactRecord:
        digest = self.compute_digest(content)
        metadata = dict(metadata or {})
        claimed_digest = claimed_digest or metadata.get("content_digest")
        blob = self._write_blob(digest, content)

        if claimed_digest is not None and claimed_digest != digest:
            raise DigestMismatchError(
                "metadata content_digest does not match uploaded content"
            )

        record_metadata = {
            **metadata,
            "content_digest": digest,
            "blob_ref": blob.path,
        }
        record = ArtifactRecord(
            logical_name=logical_name,
            blob=blob,
            metadata=record_metadata,
            version=self._next_version(logical_name),
        )
        self._metadata_path(logical_name).write_text(
            json.dumps(self._serialize(record), sort_keys=True),
            encoding="utf-8",
        )
        return record

    def get(self, logical_name: str) -> Optional[ArtifactRecord]:
        path = self._metadata_path(logical_name)
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        blob = BlobRef(**raw["blob"])
        return ArtifactRecord(
            logical_name=raw["logical_name"],
            blob=blob,
            metadata=raw["metadata"],
            version=raw["version"],
        )

    def read(self, logical_name: str) -> Optional[bytes]:
        record = self.get(logical_name)
        if record is None:
            return None
        path = self.root / record.blob.path
        if not path.exists():
            return None
        return path.read_bytes()

    def verify(self, logical_name: str) -> bool:
        record = self.get(logical_name)
        content = self.read(logical_name)
        if record is None or content is None:
            return False
        return self.compute_digest(content) == record.blob.digest

    def blob_count(self) -> int:
        return sum(1 for path in self.blob_dir.rglob("*") if path.is_file())

    @staticmethod
    def compute_digest(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def _write_blob(self, digest: str, content: bytes) -> BlobRef:
        path = self._blob_path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(content)
        return BlobRef(
            digest=digest,
            size=len(content),
            path=str(path.relative_to(self.root)),
        )

    def _next_version(self, logical_name: str) -> int:
        existing = self.get(logical_name)
        if existing is None:
            return 1
        return existing.version + 1

    def _blob_path(self, digest: str) -> Path:
        return self.blob_dir / digest[:2] / digest

    def _metadata_path(self, logical_name: str) -> Path:
        name_digest = self.compute_digest(logical_name.encode("utf-8"))
        return self.metadata_dir / f"{name_digest}.json"

    @staticmethod
    def _serialize(record: ArtifactRecord) -> Dict[str, Any]:
        return {
            "logical_name": record.logical_name,
            "blob": {
                "digest": record.blob.digest,
                "size": record.blob.size,
                "path": record.blob.path,
            },
            "metadata": record.metadata,
            "version": record.version,
        }
