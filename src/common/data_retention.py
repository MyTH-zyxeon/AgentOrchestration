"""Data-retention deletion manifests and reconciliation helpers."""

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Protocol, Sequence, Set, Tuple


class RetentionStore(Protocol):
    """Minimal store contract for retention delete workflows."""

    name: str

    def delete(self, key: str) -> bool:
        """Remove a record and return whether it existed."""

    def contains(self, key: str) -> bool:
        """Return whether a record is still present."""


@dataclass(frozen=True)
class DeletionTarget:
    store: str
    key: str
    derived: bool = False
    source_key: Optional[str] = None


@dataclass(frozen=True)
class DeletionManifest:
    workspace_id: str
    source_key: str
    targets: Sequence[DeletionTarget]

    @property
    def primary_target(self) -> DeletionTarget:
        for target in self.targets:
            if not target.derived:
                return target
        raise ValueError("deletion manifest requires a primary target")

    @property
    def derived_targets(self) -> Tuple[DeletionTarget, ...]:
        return tuple(target for target in self.targets if target.derived)

    @property
    def affected_stores(self) -> Tuple[str, ...]:
        return tuple(sorted({target.store for target in self.targets}))


@dataclass(frozen=True)
class DeletionCompletion:
    target: DeletionTarget
    removed: bool


@dataclass(frozen=True)
class DeletionRecord:
    manifest: DeletionManifest
    completions: Sequence[DeletionCompletion]
    stale_derived_removed: Sequence[DeletionCompletion] = ()

    @property
    def complete(self) -> bool:
        return bool(self.completions) and all(
            completion.removed for completion in self.completions
        )

    @property
    def affected_stores(self) -> Tuple[str, ...]:
        completions = tuple(self.completions) + tuple(
            self.stale_derived_removed
        )
        return tuple(
            sorted({completion.target.store for completion in completions})
        )


class InMemoryRetentionStore:
    """Small store implementation used by retention tests and dry-runs."""

    def __init__(self, name: str, records: Iterable[str] = ()):
        self.name = name
        self._records: Set[str] = set(records)

    def add(self, key: str) -> None:
        self._records.add(key)

    def delete(self, key: str) -> bool:
        if key not in self._records:
            return False
        self._records.remove(key)
        return True

    def contains(self, key: str) -> bool:
        return key in self._records

    def snapshot(self) -> Set[str]:
        return set(self._records)


class RetentionDeletionWorkflow:
    """Builds manifests, deletes primary records, and clears derived data."""

    def __init__(self, stores: Mapping[str, RetentionStore]):
        self._stores = dict(stores)

    def build_manifest(
        self,
        workspace_id: str,
        primary_store: str,
        primary_key: str,
        derived_targets: Mapping[str, Iterable[str]],
    ) -> DeletionManifest:
        targets = [DeletionTarget(primary_store, primary_key)]
        for store_name, keys in derived_targets.items():
            for key in keys:
                targets.append(
                    DeletionTarget(
                        store=store_name,
                        key=key,
                        derived=True,
                        source_key=primary_key,
                    )
                )
        return DeletionManifest(
            workspace_id=workspace_id,
            source_key=primary_key,
            targets=tuple(targets),
        )

    def delete_manifest(self, manifest: DeletionManifest) -> DeletionRecord:
        completions = tuple(
            DeletionCompletion(
                target=target,
                removed=self._store_for(target).delete(target.key),
            )
            for target in manifest.targets
        )
        return DeletionRecord(manifest=manifest, completions=completions)

    def reconcile(self, manifest: DeletionManifest) -> DeletionRecord:
        primary = manifest.primary_target
        if self._store_for(primary).contains(primary.key):
            return DeletionRecord(manifest=manifest, completions=())

        removed = []
        for target in manifest.derived_targets:
            store = self._store_for(target)
            if store.contains(target.key):
                removed.append(
                    DeletionCompletion(
                        target=target,
                        removed=store.delete(target.key),
                    )
                )
        return DeletionRecord(
            manifest=manifest,
            completions=(),
            stale_derived_removed=tuple(removed),
        )

    def _store_for(self, target: DeletionTarget) -> RetentionStore:
        try:
            return self._stores[target.store]
        except KeyError as exc:
            raise KeyError(f"unknown retention store: {target.store}") from exc
