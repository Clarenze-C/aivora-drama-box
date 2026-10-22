"""Fixtures for the TikTok adapter tests (T022). Builders live in ``support``.

The lane directory is put on ``sys.path`` (the ``tests/contract/publishing/conftest``
pattern) so test modules can import ``tiktok_support`` at module level.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import pytest  # noqa: E402


@pytest.fixture
def bench(tmp_path: Path):
    from tiktok_support import AdapterBench

    return AdapterBench(tmp_path)


@pytest.fixture
def tiktok_world(db, tmp_path: Path, offline_settings):
    from tiktok_support import TikTokWorld

    def make(**kwargs):
        return TikTokWorld(db, tmp_path, offline_settings, **kwargs)

    return make


@pytest.fixture
def world(tiktok_world):
    return tiktok_world()
