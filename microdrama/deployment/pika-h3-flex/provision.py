"""Explicit, hash-verified provisioning; never called by runtime startup."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import urllib.request


def verified(path, record):
    if not path.is_file() or path.is_symlink() or path.stat().st_size != record['size']:
        return False
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest() == record['sha256']


def provision(manifest, destination, *, download=False, opener=urllib.request.urlopen,
              free_bytes=None):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    revision = manifest['revision']
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Immutable repository revision required')
    pending = []
    for record in manifest['files']:
        rel = Path(record['path'])
        if rel.is_absolute() or '..' in rel.parts or not re.fullmatch(r'[0-9a-f]{64}', record['sha256']):
            raise ValueError('Unsafe manifest record')
        path = destination / rel
        if not path.resolve().is_relative_to(destination):
            raise ValueError('Model path escapes destination')
        if not verified(path, record):
            pending.append((path, record))
    if not pending:
        return {'status': 'VERIFIED', 'downloaded': 0}
    if not download:
        raise RuntimeError('Models unavailable; explicit --download required (preflight has no network)')
    # Reserve every missing final file plus one largest temporary and headroom.
    needed = sum(r['size'] for _, r in pending) + max(r['size'] for _, r in pending) + manifest['headroom_bytes']
    available = shutil.disk_usage(destination).free if free_bytes is None else free_bytes
    if available < needed:
        raise RuntimeError(f'Insufficient disk: need {needed}, available {available}')
    for path, record in pending:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.unverified-', dir=path.parent)
        temporary = Path(name)
        try:
            url = f"https://huggingface.co/{manifest['repository']}/resolve/{revision}/{record['path']}"
            count = 0
            with os.fdopen(fd, 'wb') as output, opener(url, timeout=60) as response:
                for chunk in iter(lambda: response.read(1024 * 1024), b''):
                    count += len(chunk)
                    if count > record['size']:
                        raise RuntimeError('Download exceeds pinned size')
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if not verified(temporary, record):
                raise RuntimeError('Model size/SHA256 mismatch; refused promotion')
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return {'status': 'VERIFIED', 'downloaded': len(pending)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=Path(__file__).with_name('models.json'))
    parser.add_argument('--destination', type=Path, default=Path('/opt/ComfyUI/models'))
    parser.add_argument('--download', action='store_true', help='Explicitly allow pinned weight downloads')
    args = parser.parse_args()
    print(json.dumps(provision(json.loads(args.manifest.read_text()), args.destination, download=args.download)))
