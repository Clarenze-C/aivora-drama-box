from __future__ import annotations

import importlib

import pytest

MODULES = [
    "contracts",
    "core",
    "persistence",
    "budget",
    "research",
    "story",
    "references",
    "rendering",
    "editing",
    "qa",
    "review",
    "publishing",
    "community",
    "memberships",
    "analytics",
    "api",
    "workers",
]


@pytest.mark.parametrize("name", MODULES)
def test_spec_layout_package_imports(name: str) -> None:
    importlib.import_module(f"microdrama.{name}")


def test_error_taxonomy_maps_to_spec_status_codes() -> None:
    from microdrama.contracts import errors as e

    assert e.SchemaInvalid.http_status == 422
    assert e.StaleRevision.http_status == 409
    assert e.IdempotencyConflict.http_status == 409
    assert e.Unauthorized.http_status == 403
    assert e.PolicyDenied.http_status == 403
    assert e.EffectDenied.http_status == 403
    assert issubclass(e.EffectDenied, e.PolicyDenied)
    assert not e.NeedsReconciliation.transient
    assert e.TransientProviderError.transient
