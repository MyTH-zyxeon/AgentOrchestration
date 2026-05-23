import hashlib

import pytest

from src.storage import ArtifactDownloadCache, CacheIntegrityError


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_cache_hit_verifies_checksum_without_redownload(tmp_path):
    cache = ArtifactDownloadCache(tmp_path)
    content = b"artifact-payload"
    expected_digest = _sha256(content)
    downloads = []

    def downloader(path):
        downloads.append(path)
        path.write_bytes(content)

    first = cache.get("artifact-a", downloader, expected_digest, len(content))
    second = cache.get(
        "artifact-a",
        lambda path: pytest.fail("valid cache hit should not redownload"),
        expected_digest,
        len(content),
    )

    assert first == second
    assert first.read_bytes() == content
    assert len(downloads) == 1


def test_corrupt_cache_entry_is_evicted_and_redownloaded(tmp_path):
    cache = ArtifactDownloadCache(tmp_path)
    original = b"artifact-payload"
    replacement = b"artifact-payload-fixed"
    original_digest = _sha256(original)
    replacement_digest = _sha256(replacement)

    cached = cache.get(
        "artifact-a",
        lambda path: path.write_bytes(original),
        original_digest,
        len(original),
    )
    cached.write_bytes(b"corrupt")

    refreshed = cache.get(
        "artifact-a",
        lambda path: path.write_bytes(replacement),
        replacement_digest,
        len(replacement),
    )

    assert refreshed == cached
    assert refreshed.read_bytes() == replacement


def test_partial_cache_entry_is_evicted_and_redownloaded(tmp_path):
    cache = ArtifactDownloadCache(tmp_path)
    content = b"complete-artifact"
    expected_digest = _sha256(content)

    cached = cache.get(
        "artifact-a",
        lambda path: path.write_bytes(content),
        expected_digest,
        len(content),
    )
    cached.write_bytes(content[:4])

    refreshed = cache.get(
        "artifact-a",
        lambda path: path.write_bytes(content),
        expected_digest,
        len(content),
    )

    assert refreshed.read_bytes() == content


def test_download_checksum_mismatch_fails_closed(tmp_path):
    cache = ArtifactDownloadCache(tmp_path)

    with pytest.raises(CacheIntegrityError):
        cache.get(
            "artifact-a",
            lambda path: path.write_bytes(b"wrong"),
            _sha256(b"expected"),
            len(b"expected"),
        )

    assert list(tmp_path.iterdir()) == []
