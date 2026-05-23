"""Checksum-validated local artifact download cache."""

import hashlib
import json
import time
from pathlib import Path
from typing import Callable, Optional


class CacheIntegrityError(RuntimeError):
    """Raised when a downloaded artifact fails checksum validation."""


class ArtifactDownloadCache:
    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get(
        self,
        cache_key: str,
        downloader: Callable[[Path], None],
        expected_sha256: str,
        expected_size: Optional[int] = None,
    ) -> Path:
        expected_sha256 = self._normalize_digest(expected_sha256)
        artifact_path = self._artifact_path(cache_key)
        metadata_path = self._metadata_path(cache_key)

        if self._is_valid_hit(
            artifact_path,
            metadata_path,
            expected_sha256,
            expected_size,
        ):
            return artifact_path

        self._evict(artifact_path, metadata_path)
        tmp_path = artifact_path.with_name(f"{artifact_path.name}.tmp")
        tmp_path.unlink(missing_ok=True)
        downloader(tmp_path)

        if not tmp_path.exists():
            raise FileNotFoundError(f"Downloader did not create {tmp_path}")

        actual_size = tmp_path.stat().st_size
        actual_sha256 = self._sha256(tmp_path)
        if actual_sha256 != expected_sha256:
            tmp_path.unlink(missing_ok=True)
            raise CacheIntegrityError("Downloaded artifact checksum mismatch")
        if expected_size is not None and actual_size != expected_size:
            tmp_path.unlink(missing_ok=True)
            raise CacheIntegrityError("Downloaded artifact size mismatch")

        tmp_path.replace(artifact_path)
        metadata_path.write_text(
            json.dumps(
                {
                    "cache_key_hash": self._key_hash(cache_key),
                    "sha256": expected_sha256,
                    "size": actual_size,
                    "cached_at": time.time(),
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return artifact_path

    def _is_valid_hit(
        self,
        artifact_path: Path,
        metadata_path: Path,
        expected_sha256: str,
        expected_size: Optional[int],
    ) -> bool:
        if not artifact_path.exists() or not metadata_path.exists():
            return False

        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False

        cached_size = metadata.get("size")
        if metadata.get("sha256") != expected_sha256:
            return False
        if expected_size is not None and cached_size != expected_size:
            return False
        if artifact_path.stat().st_size != cached_size:
            return False
        return self._sha256(artifact_path) == expected_sha256

    def _artifact_path(self, cache_key: str) -> Path:
        return self.cache_dir / f"{self._key_hash(cache_key)}.artifact"

    def _metadata_path(self, cache_key: str) -> Path:
        return self.cache_dir / f"{self._key_hash(cache_key)}.json"

    def _evict(self, artifact_path: Path, metadata_path: Path) -> None:
        artifact_path.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)

    @staticmethod
    def _key_hash(cache_key: str) -> str:
        return hashlib.sha256(cache_key.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_digest(value: str) -> str:
        digest = value.strip().lower()
        if len(digest) != 64:
            raise ValueError("expected_sha256 must be a SHA-256 hex digest")
        int(digest, 16)
        return digest

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as artifact:
            for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
