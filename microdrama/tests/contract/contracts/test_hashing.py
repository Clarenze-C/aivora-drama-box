from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from enum import StrEnum
from uuid import UUID

import pytest

from microdrama.contracts.examples import release_package, season_scope
from microdrama.contracts.hashing import (
    CanonicalizationError,
    canonical_hash,
    canonical_json,
    model_hash,
)


class Color(StrEnum):
    RED = "red"


def test_key_order_and_whitespace_do_not_matter() -> None:
    assert canonical_hash({"b": 1, "a": [1, 2]}) == canonical_hash({"a": [1, 2], "b": 1})
    assert canonical_json({"b": 1, "a": True}) == '{"a":true,"b":1}'


def test_list_order_matters_but_set_order_does_not() -> None:
    assert canonical_hash([1, 2]) != canonical_hash([2, 1])
    assert canonical_hash(frozenset({"x", "y", "z"})) == canonical_hash(frozenset({"z", "y", "x"}))


def test_floats_are_rejected() -> None:
    with pytest.raises(CanonicalizationError):
        canonical_hash({"amount": 1.5})
    with pytest.raises(CanonicalizationError):
        canonical_hash({"amount": 10.0})


def test_naive_datetimes_are_rejected_and_aware_are_normalized_to_utc() -> None:
    with pytest.raises(CanonicalizationError):
        canonical_hash(datetime(2026, 1, 1))
    bangkok = timezone(timedelta(hours=7))
    a = datetime(2026, 1, 1, 7, 0, tzinfo=bangkok)
    b = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    assert canonical_json(a) == canonical_json(b) == '"2026-01-01T00:00:00.000000Z"'


def test_thai_text_is_hashed_literally() -> None:
    assert canonical_json({"t": "ห้าหมื่นบาท"}) == '{"t":"ห้าหมื่นบาท"}'
    assert canonical_hash("ห้าหมื่นบาท") != canonical_hash("ห้าพันบาท")


def test_uuid_and_enum_normalization() -> None:
    u = UUID("12345678-1234-5678-1234-567812345678")
    assert (
        canonical_json({"id": u, "c": Color.RED})
        == '{"c":"red","id":"12345678-1234-5678-1234-567812345678"}'
    )


def test_unsupported_types_are_rejected() -> None:
    with pytest.raises(CanonicalizationError):
        canonical_hash(b"bytes")
    with pytest.raises(CanonicalizationError):
        canonical_hash({1: "non-string key"})


def test_model_hash_is_stable_and_sensitive() -> None:
    scope = season_scope()
    assert canonical_hash(scope) == canonical_hash(season_scope())
    changed = scope.model_copy(update={"logline": scope.logline + "!"})
    assert canonical_hash(changed) != canonical_hash(scope)


def test_release_package_hash_excludes_only_its_own_hash_cost_and_blockers() -> None:
    pkg = release_package()
    assert pkg.package_hash == pkg.compute_hash()
    assert model_hash(pkg, exclude={"package_hash", "gate_blockers", "cost"}) == pkg.package_hash
