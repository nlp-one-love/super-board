#!/usr/bin/env python3
"""Install a pinned, checksummed release from the user's fork using the LOCAL installer."""
import argparse
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request


def extract(archive, dest):
    total = 0
    with tarfile.open(archive, 'r:gz') as bundle:
        members = bundle.getmembers()
        if len(members) > 20000:
            raise ValueError('Package has too many entries')
        for member in members:
            parts = member.name.split('/')
            if (parts[0] != 'super-board' or any(x in ('.', '..', '.git') for x in parts)
                    or '\\' in member.name or member.name.startswith('/')
                    or not (member.isfile() or member.isdir())):
                raise ValueError('Unsafe package entry')
            total += member.size
            if total > 100 * 1024 * 1024:
                raise ValueError('Package exceeds size limit')
        # All entries are plain files/directories under a fresh private directory.
        for member in members:
            path = dest / member.name
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    raise ValueError('Duplicate package entry')
                with bundle.extractfile(member) as stream:
                    path.write_bytes(stream.read())
    return dest / 'super-board'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--update', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'v\d+\.\d+\.\d+-gitea\.\d+', args.tag):
        parser.error('An exact fork release tag is required; branches/latest are unsupported')
    name = 'super-board-' + args.tag + '.tar.gz'
    base = 'https://github.com/nlp-one-love/super-board/releases/download/' + args.tag + '/'
    # Retain the download for inspection/recovery; never recursively remove a tree.
    scratch = Path(tempfile.mkdtemp(prefix='super-board-release-'))
    def fetch(url, maximum):
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(maximum + 1)
        if len(data) > maximum:
            raise ValueError('Release asset exceeds size limit')
        return data
    checksum = fetch(base + name + '.sha256', 1024).decode().strip().split()
    if len(checksum) != 2 or not re.fullmatch(r'[0-9a-f]{64}', checksum[0]) or checksum[1] != name:
        raise ValueError('Invalid release checksum file')
    data = fetch(base + name, 30 * 1024 * 1024)
    if hashlib.sha256(data).hexdigest() != checksum[0]:
        raise ValueError('Release checksum mismatch')
    archive = scratch / name; archive.write_bytes(data)
    source = extract(archive, scratch / 'unpacked')
    import json
    metadata = json.loads((source / 'PACKAGE-SOURCE.json').read_text())
    if metadata.get('tag') != args.tag or metadata.get('repository') != 'nlp-one-love/super-board':
        raise ValueError('Release provenance does not match the selected fork/tag')
    if (source / 'VERSION').read_text().strip() != args.tag[1:]:
        raise ValueError('Release VERSION mismatch')
    # Never execute the downloaded install/get/package scripts. The reviewed
    # local installer only copies their payload after validating every destination.
    command = [sys.executable, str(Path(__file__).with_name('super-board-package.py')),
               'update' if args.update else 'install', '--source', str(source), '--target', args.target]
    if args.dry_run:
        command.append('--dry-run')
    return subprocess.run(command).returncode


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, tarfile.TarError):
        print('Release installation refused: download, checksum, provenance or archive validation failed', file=sys.stderr)
        sys.exit(1)
