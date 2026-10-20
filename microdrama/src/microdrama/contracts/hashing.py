"""Canonical JSON and hashing — defined once, used for every approval/media/policy link.

Canonical form (contract v1):
- UTF-8 JSON, object keys sorted, separators ``,`` and ``:``, no insignificant
  whitespace, non-ASCII emitted literally (Thai text is hashed as written; no
  Unicode normalization is applied).
- Allowed scalars: str, int, bool, None. **Floats are rejected** (money is
  integer micro-USD, time is integer ms, ratios are integer basis points).
- UUID → lowercase string. Enum → its value. Timezone-aware datetime → UTC
  ``YYYY-MM-DDTHH:MM:SS.ffffffZ``; naive datetimes are rejected. date → ISO date.
- Sets/frozensets → list sorted by each element's canonical encoding.
- Pydantic models → ``model_dump(mode="python")`` then the rules above.

A hash proves identity/integrity of content. It does not prove truth, quality
or rights clearance.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class CanonicalizationError(TypeError):
    pass


def _normalize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _normalize(value.model_dump(mode="python"))
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, Enum):
        return _normalize(value.value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise CanonicalizationError("floats are not allowed in canonical JSON")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise CanonicalizationError("naive datetime cannot be canonicalized")
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = k.value if isinstance(k, Enum) else k
            if isinstance(key, UUID):
                key = str(key)
            if not isinstance(key, str):
                raise CanonicalizationError(f"object keys must be strings, got {type(k).__name__}")
            out[key] = _normalize(v)
        return out
    if isinstance(value, set | frozenset):
        items = [_normalize(v) for v in value]
        return sorted(items, key=lambda item: _dumps(item))
    if isinstance(value, list | tuple):
        return [_normalize(v) for v in value]
    raise CanonicalizationError(f"unsupported type for canonical JSON: {type(value).__name__}")


def _dumps(normalized: Any) -> str:
    return json.dumps(
        normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def canonical_json(value: Any) -> str:
    return _dumps(_normalize(value))


def canonical_json_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_hash(value: Any) -> str:
    """SHA-256 hex of the canonical JSON encoding of ``value``."""
    return sha256_hex(canonical_json_bytes(value))


def model_hash(model: BaseModel, *, exclude: Iterable[str] = ()) -> str:
    """Hash of a model's canonical form, excluding e.g. its own stored hash field."""
    data = model.model_dump(mode="python", exclude=set(exclude))
    return canonical_hash(data)


def file_sha256(path: str, *, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
