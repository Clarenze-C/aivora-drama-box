"""Private object store and asset metadata/lineage (T003)."""

from __future__ import annotations

import stat
import threading
import uuid

import pytest

from microdrama.contracts.enums import AssetState
from microdrama.contracts.errors import Conflict, NotFound, SchemaInvalid, StaleRevision
from microdrama.contracts.examples import asset_descriptor
from microdrama.contracts.infra import ObjectStore
from microdrama.persistence import (
    Database,
    FilesystemObjectStore,
    asset_revision,
    get_asset,
    lineage_sources,
    register_asset,
    set_asset_state,
    verify_persisted,
)
from microdrama.testing.seed import seed_episode, seed_season


class TestFilesystemObjectStore:
    def test_satisfies_protocol(self, object_store: FilesystemObjectStore) -> None:
        assert isinstance(object_store, ObjectStore)

    def test_put_get_head_verify(self, object_store: FilesystemObjectStore) -> None:
        stored = object_store.put_bytes(
            "episodes/e1/a.bin", b"abc", media_type="application/octet-stream"
        )
        assert stored.size_bytes == 3
        assert object_store.get_bytes("episodes/e1/a.bin") == b"abc"
        assert object_store.head("episodes/e1/a.bin") == stored
        assert object_store.verify("episodes/e1/a.bin", stored.sha256)
        assert not object_store.verify("episodes/e1/a.bin", "0" * 64)
        assert object_store.head("missing/key") is None
        with pytest.raises(NotFound):
            object_store.get_bytes("missing/key")

    def test_write_once(self, object_store: FilesystemObjectStore) -> None:
        first = object_store.put_bytes("k/obj", b"same", media_type="text/plain")
        assert object_store.put_bytes("k/obj", b"same", media_type="text/plain") == first
        with pytest.raises(Conflict):
            object_store.put_bytes("k/obj", b"different", media_type="text/plain")
        assert object_store.get_bytes("k/obj") == b"same"

    def test_concurrent_conflicting_writers_cannot_overwrite(
        self, object_store: FilesystemObjectStore
    ) -> None:
        outcomes: list[str] = []

        def put(data: bytes) -> None:
            try:
                object_store.put_bytes("race/obj", data, media_type="text/plain")
                outcomes.append("ok")
            except Conflict:
                outcomes.append("conflict")

        threads = [threading.Thread(target=put, args=(f"v{i}".encode(),)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert outcomes.count("ok") == 1
        winner = object_store.get_bytes("race/obj")
        assert object_store.verify("race/obj", object_store.head("race/obj").sha256)
        assert winner.startswith(b"v")

    @pytest.mark.parametrize(
        "key", ["../escape", "/abs", "a/../../b", ".meta/x", "a//b", "spaces are bad"]
    )
    def test_rejects_unsafe_keys(self, object_store: FilesystemObjectStore, key: str) -> None:
        with pytest.raises(SchemaInvalid):
            object_store.put_bytes(key, b"x", media_type="text/plain")

    def test_files_are_private(self, object_store: FilesystemObjectStore) -> None:
        object_store.put_bytes("p/q", b"x", media_type="text/plain")
        mode = stat.S_IMODE(object_store.local_path("p/q").stat().st_mode)
        assert mode == 0o600
        assert stat.S_IMODE(object_store.root.stat().st_mode) == 0o700


@pytest.mark.db
class TestAssetRegistry:
    def _descriptor(self, db: Database, store: FilesystemObjectStore, name: str, lineage=()):
        stored = store.put_bytes(
            f"episodes/x/{name}.mp4", name.encode() * 10, media_type="video/mp4"
        )
        with db.transaction() as tx:
            episode = seed_episode(tx, seed_season(tx))
        return asset_descriptor().model_copy(
            update={
                "asset_id": uuid.uuid4(),
                "object_key": stored.key,
                "sha256": stored.sha256,
                "size_bytes": stored.size_bytes,
                "episode_id": episode,
                "lineage": list(lineage),
            }
        )

    def test_round_trip_with_lineage(
        self, db: Database, object_store: FilesystemObjectStore
    ) -> None:
        source = self._descriptor(db, object_store, "source", lineage=[])
        derived = self._descriptor(db, object_store, "derived", lineage=[source.asset_id])
        with db.transaction() as tx:
            register_asset(tx, source)
            register_asset(tx, derived, generation_key="a" * 64)
        with db.transaction() as tx:
            assert get_asset(tx, derived.asset_id) == derived
            assert lineage_sources(tx, derived.asset_id) == [source.asset_id]

    def test_register_is_idempotent_but_not_overwritable(
        self, db: Database, object_store: FilesystemObjectStore
    ) -> None:
        d = self._descriptor(db, object_store, "idem")
        with db.transaction() as tx:
            register_asset(tx, d)
            register_asset(tx, d)
        with pytest.raises(Conflict), db.transaction() as tx:
            register_asset(tx, d.model_copy(update={"size_bytes": d.size_bytes + 1}))
        with pytest.raises(Conflict), db.transaction() as tx:
            tx.execute("UPDATE assets SET sha256 = %s WHERE id = %s", ("f" * 64, d.asset_id))

    def test_state_changes_use_optimistic_revision(
        self, db: Database, object_store: FilesystemObjectStore
    ) -> None:
        d = self._descriptor(db, object_store, "state")
        with db.transaction() as tx:
            register_asset(tx, d)
            rev = asset_revision(tx, d.asset_id)
            set_asset_state(tx, d.asset_id, AssetState.LOCKED, expected_revision=rev)
        with pytest.raises(StaleRevision), db.transaction() as tx:
            set_asset_state(tx, d.asset_id, AssetState.SUPERSEDED, expected_revision=rev)
        with db.transaction() as tx:
            assert get_asset(tx, d.asset_id).state is AssetState.LOCKED

    def test_verify_persisted_detects_tampering(
        self, db: Database, object_store: FilesystemObjectStore
    ) -> None:
        d = self._descriptor(db, object_store, "tamper")
        with db.transaction() as tx:
            register_asset(tx, d)
            assert verify_persisted(tx, object_store, d.asset_id)
        path = object_store.local_path(d.object_key)
        path.chmod(0o600)
        path.write_bytes(b"tampered")
        with db.transaction() as tx:
            assert not verify_persisted(tx, object_store, d.asset_id)
