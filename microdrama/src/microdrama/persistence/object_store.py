"""Private filesystem object store (offline/mock implementation of ``ObjectStore``).

- Keys are validated relative paths (contracts ``ObjectKey``); no traversal.
- Writes are atomic (temp file + rename) and **write-once**: re-putting identical
  content is idempotent; different content under an existing key is refused, so
  durable assets referenced by hash can never silently change.
- Directories/files are created owner-only (0700/0600). No public URLs exist.
- Metadata (sha256, size, media type) is kept in a parallel ``.meta`` tree.

An S3-compatible adapter for live deployment is a T031+ readiness item.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from microdrama.contracts.errors import Conflict, NotFound, SchemaInvalid
from microdrama.contracts.infra import StoredObject
from microdrama.contracts.primitives import ObjectKey

_KEY = TypeAdapter(ObjectKey)
_META_DIR = ".meta"


class FilesystemObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)

    # --- paths --------------------------------------------------------------------

    def _validated(self, key: str) -> str:
        try:
            key = _KEY.validate_python(key)
        except ValidationError as exc:
            raise SchemaInvalid(f"invalid object key {key!r}") from exc
        if key.split("/", 1)[0] == _META_DIR:
            raise SchemaInvalid("object keys may not use the reserved .meta prefix")
        return key

    def _path(self, key: str) -> Path:
        path = (self.root / self._validated(key)).resolve()
        if self.root not in path.parents:
            raise SchemaInvalid(f"object key escapes the store: {key!r}")
        return path

    def _meta_path(self, key: str) -> Path:
        return self.root / _META_DIR / (self._validated(key) + ".json")

    # --- ObjectStore protocol -----------------------------------------------------

    def put_bytes(self, key: str, data: bytes, *, media_type: str) -> StoredObject:
        with tempfile.NamedTemporaryFile(dir=self.root, delete=False, prefix=".upload-") as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        return self._commit(key, tmp_path, media_type)

    def put_file(self, key: str, source: Path, *, media_type: str) -> StoredObject:
        fd, name = tempfile.mkstemp(dir=self.root, prefix=".upload-")
        os.close(fd)
        tmp_path = Path(name)
        shutil.copyfile(source, tmp_path)
        return self._commit(key, tmp_path, media_type)

    def get_bytes(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise NotFound(f"object {key} not found")
        return path.read_bytes()

    def local_path(self, key: str) -> Path:
        path = self._path(key)
        if not path.is_file():
            raise NotFound(f"object {key} not found")
        return path

    def head(self, key: str) -> StoredObject | None:
        meta = self._meta_path(key)
        if not meta.is_file() or not self._path(key).is_file():
            return None
        return StoredObject.model_validate_json(meta.read_text(encoding="utf-8"))

    def verify(self, key: str, sha256: str) -> bool:
        path = self._path(key)
        if not path.is_file():
            return False
        return _file_sha256(path) == sha256

    # --- internals ----------------------------------------------------------------

    def _commit(self, key: str, tmp_path: Path, media_type: str) -> StoredObject:
        try:
            os.chmod(tmp_path, 0o600)
            digest = _file_sha256(tmp_path)
            size = tmp_path.stat().st_size
            target = self._path(key)
            stored = StoredObject(key=key, sha256=digest, size_bytes=size, media_type=media_type)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                # Atomic create-if-absent: concurrent writers cannot overwrite each other.
                os.link(tmp_path, target)
            except FileExistsError:
                if _file_sha256(target) != digest:
                    raise Conflict(
                        f"object {key} already exists with different content", key=key
                    ) from None
            meta = self._meta_path(key)
            meta.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Metadata is (re)written after the object exists, so a crash between the two
            # steps is repaired by the next identical put.
            existing = self.head(key)
            if existing is not None and existing.sha256 == digest:
                return existing
            meta_tmp = meta.with_name(meta.name + ".tmp")
            meta_tmp.write_text(
                json.dumps(stored.model_dump(mode="json"), sort_keys=True), encoding="utf-8"
            )
            os.replace(meta_tmp, meta)
            return stored
        finally:
            tmp_path.unlink(missing_ok=True)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()
