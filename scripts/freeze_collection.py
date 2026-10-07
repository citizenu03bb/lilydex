"""Create and verify a portable collection snapshot without touching source data."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {'.git', '.venv', '.cache', '.pytest_cache', '.ruff_cache',
                 '__pycache__', 'node_modules', 'evaluation', 'snapshots', 'development', 'data'}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def eligible_files(directory):
    for current, dirs, files in os.walk(directory, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS
                         and not d.startswith('.') and not Path(current, d).is_symlink())
        for name in sorted(files):
            path = Path(current, name)
            if (path.is_symlink() or name.startswith('.env') or name.endswith('.pyc')
                    or name.endswith(('.pem', '.key'))):
                continue
            yield path


def verify(snapshot):
    snapshot = Path(snapshot)
    sums = (snapshot / 'SHA256SUMS').read_text().splitlines()
    for line in sums:
        checksum, name = line.split('  ', 1)
        assert Path(name).name == name
        assert digest(snapshot / name) == checksum, f'Checksum: {name}'
    manifest = json.loads((snapshot / 'manifest.json').read_text())
    expected = {item['archive_path']: item for item in manifest['files']}
    found = set()
    with tarfile.open(snapshot / 'collection.tar.gz', 'r:gz') as archive:
        for member in archive:
            assert member.isfile() and member.name not in found
            found.add(member.name)
            stream = archive.extractfile(member)
            if member.name == 'snapshot-manifest.json':
                assert json.load(stream) == manifest
                continue
            assert member.name in expected, member.name
            item = expected[member.name]
            assert member.size == item['bytes']
            assert hashlib.file_digest(stream, 'sha256').hexdigest() == item['sha256'], member.name
    assert found == set(expected) | {'snapshot-manifest.json'}
    return manifest


def create():
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    destination = ROOT / 'outputs' / 'snapshots' / timestamp
    destination.mkdir(parents=True, exist_ok=False)
    manifest_path = ROOT / 'pokeprice_library_manifest.json'
    albums = json.loads(manifest_path.read_text())['albums']
    sources = [(p, 'project/' + p.relative_to(ROOT).as_posix()) for p in eligible_files(ROOT)]
    for album in albums:
        directory = Path(album['photos']).expanduser().resolve()
        sources.extend((p, 'photos/' + album['id'] + '/' + p.relative_to(directory).as_posix())
                       for p in eligible_files(directory)
                       if p.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp', '.heic'})
    manifest = {'created_utc': timestamp, 'original_project': str(ROOT), 'albums': albums,
                'excluded': sorted(EXCLUDED_DIRS) + ['.env*', '*.pem', '*.key', 'symlinks'],
                'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'git_status': subprocess.check_output(['git', 'status', '--short'], cwd=ROOT, text=True),
                'files': []}
    with tarfile.open(destination / 'collection.tar.gz', 'w:gz', compresslevel=3) as archive:
        for source, target in sources:
            before = source.stat()
            checksum = digest(source)
            archive.add(source, arcname=target, recursive=False)
            after = source.stat()
            assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns), source
            assert checksum == digest(source), f'Source changed: {source}'
            manifest['files'].append({'source_path': str(source), 'archive_path': target,
                                      'bytes': before.st_size, 'sha256': checksum})
        payload = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode()
        entry = tarfile.TarInfo('snapshot-manifest.json')
        entry.size = len(payload)
        archive.addfile(entry, io.BytesIO(payload))
    (destination / 'manifest.json').write_bytes(payload)
    (destination / 'SHA256SUMS').write_text(''.join(
        f'{digest(destination / name)}  {name}\n' for name in ['collection.tar.gz', 'manifest.json']))
    verify(destination)
    print(json.dumps({'snapshot': str(destination), 'files_verified': len(sources),
                      'archive_bytes': (destination / 'collection.tar.gz').stat().st_size}, indent=2))


def restore(snapshot, destination):
    manifest = verify(snapshot)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(Path(snapshot) / 'collection.tar.gz', 'r:gz') as archive:
        archive.extractall(destination, filter='data')
    for item in manifest['files']:
        assert digest(destination / item['archive_path']) == item['sha256']
    print(json.dumps({'restored': str(destination), 'files_verified': len(manifest['files'])}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['create', 'verify', 'restore'])
    parser.add_argument('snapshot', nargs='?')
    parser.add_argument('destination', nargs='?')
    args = parser.parse_args()
    if args.action == 'create':
        create()
    elif args.action == 'verify':
        print(json.dumps({'files_verified': len(verify(args.snapshot)['files'])}))
    else:
        restore(args.snapshot, args.destination)
