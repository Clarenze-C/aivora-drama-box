"""Tiny offline fixtures only; never download weights."""
import hashlib
import importlib.util
import io
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('pika_provision', Path(__file__).with_name('provision.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def manifest():
    return {'revision': 'a' * 40, 'repository': 'offline/fixture', 'headroom_bytes': 10,
            'files': [{'path': 'vae/test.bin', 'size': 3, 'sha256': hashlib.sha256(b'abc').hexdigest()}]}


def forbidden(*args, **kwargs):
    raise AssertionError('Network forbidden')


def test_preflight_no_network(tmp_path, manifest):
    with pytest.raises(RuntimeError, match='explicit --download'):
        module.provision(manifest, tmp_path, opener=forbidden)


def test_space_gate_before_network(tmp_path, manifest):
    with pytest.raises(RuntimeError, match='Insufficient disk'):
        module.provision(manifest, tmp_path, download=True, opener=forbidden, free_bytes=15)


def test_mismatch_never_promoted(tmp_path, manifest):
    with pytest.raises(RuntimeError, match='mismatch'):
        module.provision(manifest, tmp_path, download=True, opener=lambda *a, **k: io.BytesIO(b'bad'), free_bytes=100)
    assert not (tmp_path / 'vae/test.bin').exists()
    assert not list(tmp_path.rglob('.unverified-*'))


def test_verified_atomic_download_and_reuse(tmp_path, manifest):
    result = module.provision(manifest, tmp_path, download=True, opener=lambda *a, **k: io.BytesIO(b'abc'), free_bytes=100)
    assert result == {'status': 'VERIFIED', 'downloaded': 1}
    assert module.provision(manifest, tmp_path, opener=forbidden)['downloaded'] == 0


def test_corrupted_existing_never_reused(tmp_path, manifest):
    (tmp_path / 'vae').mkdir()
    (tmp_path / 'vae/test.bin').write_bytes(b'bad')
    with pytest.raises(RuntimeError, match='explicit --download'):
        module.provision(manifest, tmp_path, opener=forbidden)


def test_traversal_rejected(tmp_path, manifest):
    manifest['files'][0]['path'] = '../escape'
    with pytest.raises(ValueError, match='Unsafe'):
        module.provision(manifest, tmp_path, opener=forbidden)
