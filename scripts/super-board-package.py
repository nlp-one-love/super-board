#!/usr/bin/env python3
"""Manifest-based local installation. Never follows destination symlinks or deletes trees."""
import argparse
import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

MANIFEST = '.agents/super-board/manifest.json'
BEGIN, END = '<!-- super-board:begin', '<!-- super-board:end -->'


class Conflict(Exception):
    pass


@contextlib.contextmanager
def install_lock(root):
    try:
        import fcntl
    except ImportError:
        raise Conflict('Safe package mutations currently require POSIX file locking')
    path = safe(root, '.agents/super-board/install.lock')
    if path.is_symlink():
        raise Conflict('Installer lock cannot be a symlink')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Conflict('Another package operation is active')
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe(root, relative):
    if not isinstance(relative, str) or not relative or '\\' in relative:
        raise Conflict('Invalid managed path')
    parts = relative.split('/')
    if any(x in ('', '.', '..', '.git') for x in parts) or relative.startswith('/'):
        raise Conflict('Unsafe managed path')
    path = root
    for component in parts[:-1]:
        path = path / component
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise Conflict('Destination ancestor is a symlink or non-directory: ' + relative)
    return root / relative


def inspect(path):
    if path.is_symlink():
        return {'kind': 'link', 'target': os.readlink(path)}
    if not path.exists():
        return None
    mode = path.stat()
    if not stat.S_ISREG(mode.st_mode) or mode.st_nlink != 1:
        raise Conflict('Destination is a directory, special file or hardlink: ' + str(path))
    data = path.read_bytes()
    return {'kind': 'file', 'sha256': digest(data), 'mode': stat.S_IMODE(mode.st_mode)}


def record(data, mode=0o644):
    return {'kind': 'file', 'sha256': digest(data), 'mode': mode}


def read_manifest(root):
    path = safe(root, MANIFEST)
    if path.is_symlink():
        raise Conflict('Manifest cannot be a symlink')
    if not path.exists():
        return {'files': {}, 'version': None}
    inspect(path)
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or not isinstance(value.get('files'), dict):
        raise Conflict('Invalid manifest')
    for relative in value['files']:
        safe(root, relative)
    return value


def block(text):
    """Only accept one complete owned block; preserve everything outside it."""
    pattern = r'(?m)^<!-- super-board:begin[^\n]*-->\n.*?^<!-- super-board:end -->\n?'
    matches = list(re.finditer(pattern, text, re.S))
    if text.count(BEGIN) != len(matches) or text.count(END) != len(matches) or len(matches) > 1:
        raise Conflict('Malformed or duplicate AGENTS.md managed block')
    return matches[0] if matches else None


def payload(source, host):
    content, files = {}, {}
    for folder in ('skills', 'scripts', 'workflows', 'hooks'):
        for src in sorted((source / folder).rglob('*')):
            if '.git' in src.parts or '__pycache__' in src.parts or src.suffix == '.pyc':
                continue
            if src.is_symlink():
                raise Conflict('Source package contains a symlink: ' + str(src))
            if not src.is_file() or (folder == 'hooks' and 'dev' in src.relative_to(source / folder).parts):
                continue
            relative = src.relative_to(source / folder).as_posix()
            group = 'bin' if folder == 'scripts' else folder
            dest = '.agents/' + group + '/' + relative
            data = src.read_bytes()
            mode = 0o755 if src.suffix == '.sh' else 0o644
            files[dest], content[dest] = record(data, mode), data
    # Legacy paths are internal links. Codex discovers the real .agents/skills directly.
    for group in ('skills', 'bin', 'workflows', 'hooks'):
        names = {name.split('/')[2] for name in files if name.startswith('.agents/' + group + '/')}
        for name in names:
            relative = '.claude/' + group + '/' + name
            target = '../../.agents/' + group + '/' + name
            files[relative] = {'kind': 'link', 'target': target}
    if host == 'codex':
        # Do not make .codex settings or claim Claude hooks are enforced by Codex.
        pass
    version = (source / 'VERSION').read_text().strip()
    data = (version + '\n').encode()
    content['.agents/skills/super-board/VERSION'] = data
    files['.agents/skills/super-board/VERSION'] = record(data)
    return files, content, version


def make_plan(root, source, host, uninstall=False):
    old = read_manifest(root)
    files, content, version = ({}, {}, old['version']) if uninstall else payload(source, host)
    conflicts, changes = [], []
    for relative in sorted(set(old['files']) | set(files)):
        path = safe(root, relative)
        current = inspect(path)
        expected = old['files'].get(relative)
        wanted = files.get(relative)
        if current is not None and expected is None:
            conflicts.append(relative + ': existing unmanaged path')
        elif current != expected and (current is not None or wanted is not None):
            conflicts.append(relative + ': locally changed or missing managed path')
        elif current != wanted:
            changes.append({'path': relative, 'action': 'remove' if wanted is None else 'add' if current is None else 'change'})
    # AGENTS.md ownership is block-level, not the whole file.
    agents = safe(root, 'AGENTS.md')
    if agents.is_symlink():
        raise Conflict('AGENTS.md symlink is unsupported')
    current = agents.read_text() if agents.exists() else ''
    match = block(current)
    old_block = old.get('agents_block_sha256')
    if match and digest(match.group().encode()) != old_block:
        conflicts.append('AGENTS.md: unmanaged or locally changed block')
    elif old_block and not match:
        conflicts.append('AGENTS.md: managed block was removed')
    template = ''
    if not uninstall:
        template = ('<!-- super-board:begin v' + version + ' (managed) -->\n' +
                    (source / 'skills/super-board/references/agents-md-block.md').read_text().strip() +
                    '\n<!-- super-board:end -->\n')
    if match:
        updated = current[:match.start()] + template + current[match.end():]
    elif template:
        updated = current + ('\n' if current and not current.endswith('\n') else '') + template
    else:
        updated = current
    if updated != current:
        content['AGENTS.md'] = updated.encode()
        changes.append({'path': 'AGENTS.md', 'action': 'change' if agents.exists() else 'add'})
    new = {'schema': 1, 'version': version, 'source': source_metadata(source) if not uninstall else old.get('source'),
           'files': files, 'agents_block_sha256': digest(template.encode()) if template else None}
    return {'version': version, 'changes': changes, 'conflicts': conflicts}, new, content


def source_metadata(source):
    metadata = source / 'PACKAGE-SOURCE.json'
    if metadata.exists():
        return json.loads(metadata.read_text())
    p = subprocess.run(['git', '-C', str(source), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    return {'repository': 'nlp-one-love/super-board', 'commit': p.stdout.strip() if p.returncode == 0 else None,
            'version': (source / 'VERSION').read_text().strip(), 'kind': 'local-reviewed-checkout'}


def write(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno()); tmp = stream.name
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def backup(path):
    current = inspect(path)
    if current and current['kind'] == 'file':
        current = dict(current, data=base64.b64encode(path.read_bytes()).decode())
    return current


def put(path, entry, content=None):
    if entry is None:
        if path.exists() or path.is_symlink():
            path.unlink()  # A single manifest-owned file/link, never a directory tree.
    elif entry['kind'] == 'link':
        if path.exists() or path.is_symlink():
            path.unlink()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(entry['target'])
    else:
        write(path, content if content is not None else base64.b64decode(entry['data']), entry['mode'])


def apply(root, plan, manifest, content, uninstall=False):
    if plan['conflicts']:
        raise Conflict('Conflicts found; inspect --dry-run. No files were changed.')
    old = read_manifest(root)
    relatives = [x['path'] for x in plan['changes']] + [MANIFEST]
    # Capture all files before first mutation. Journal persists through interruption.
    before = {rel: backup(safe(root, rel)) for rel in relatives}
    ignore = safe(root, '.agents/super-board/.gitignore')
    if not ignore.exists():
        write(ignore, b'*\n')
    dest = safe(root, '.agents/super-board/backups/' + str(time.time_ns()) + '/transaction.json')
    data = {'status': 'pending', 'before': before, 'after': {}}
    for rel in relatives:
        if rel == MANIFEST:
            target = None if uninstall else record((json.dumps(manifest, indent=2) + '\n').encode())
        elif rel == 'AGENTS.md':
            target = record(content[rel])
        else:
            target = manifest['files'].get(rel)
        data['after'][rel] = target
    write(dest, (json.dumps(data, indent=2) + '\n').encode(), 0o600)
    try:
        for rel in relatives:
            target = data['after'][rel]
            blob = (json.dumps(manifest, indent=2) + '\n').encode() if rel == MANIFEST else content.get(rel)
            put(safe(root, rel), target, blob)
    except BaseException:
        # Restore only files this transaction touched. Never recursively remove.
        for rel in reversed(relatives):
            put(safe(root, rel), before[rel])
        data['status'] = 'rolled-back'
        write(dest, (json.dumps(data, indent=2) + '\n').encode(), 0o600)
        raise
    data['status'] = 'applied'
    write(dest, (json.dumps(data, indent=2) + '\n').encode(), 0o600)
    return {'version': manifest['version'], 'changed': len(plan['changes']), 'backup': str(dest.relative_to(root))}


def rollback(root, transaction, dry):
    path = safe(root, transaction)
    if not transaction.startswith('.agents/super-board/backups/') or path.is_symlink():
        raise Conflict('Rollback requires a local backup transaction')
    data = json.loads(path.read_text())
    conflicts = []
    for rel, expected in data['after'].items():
        current = inspect(safe(root, rel))
        before = data['before'][rel]
        old = {k: v for k, v in before.items() if k != 'data'} if before else None
        # Pending transactions can be partly applied; either known state is safe.
        if current != expected and not (data['status'] == 'pending' and current == old):
            conflicts.append(rel)
    if conflicts or dry:
        return {'conflicts': conflicts, 'wouldRestore': list(data['before'])}
    if data['status'] not in ('applied', 'pending'):
        raise Conflict('Transaction has already been rolled back')
    for rel, entry in reversed(list(data['before'].items())):
        put(safe(root, rel), entry)
    data['status'] = 'rolled-back'
    write(path, (json.dumps(data, indent=2) + '\n').encode(), 0o600)
    return {'restored': len(data['before'])}


def build(source, output, tag):
    version = (source / 'VERSION').read_text().strip()
    if not re.fullmatch(r'v\d+\.\d+\.\d+-gitea\.\d+', tag or '') or tag != 'v' + version:
        raise Conflict('Build requires an exact vMAJOR.MINOR.PATCH-gitea.N tag matching VERSION')
    if output.exists() or output.with_name(output.name + '.sha256').exists():
        raise Conflict('Release output already exists')
    top = subprocess.run(['git', '-C', str(source), 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    clean = subprocess.run(['git', '-C', str(source), 'status', '--porcelain'], capture_output=True, text=True)
    if top.returncode or Path(top.stdout.strip()).resolve() != source or clean.returncode or clean.stdout.strip():
        raise Conflict('Build requires a clean, committed fork checkout')
    entries = [source / p for p in ('VERSION', 'LICENSE', 'install.sh', 'get.sh')]
    for folder in ('skills', 'scripts', 'hooks', 'workflows', 'docs'):
        entries += sorted((source / folder).rglob('*'))
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata = source_metadata(source); metadata.update(tag=tag, kind='release')
    with tarfile.open(output, 'w:gz') as archive:
        for path in entries:
            if path.is_symlink():
                raise Conflict('Release source contains symlinks')
            if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc' or '.git' in path.parts:
                continue
            archive.add(path, arcname='super-board/' + path.relative_to(source).as_posix(), recursive=False)
        import io
        encoded = (json.dumps(metadata, indent=2) + '\n').encode()
        info = tarfile.TarInfo('super-board/PACKAGE-SOURCE.json'); info.size = len(encoded); info.mode = 0o644
        archive.addfile(info, io.BytesIO(encoded))
    checksum = digest(output.read_bytes())
    output.with_name(output.name + '.sha256').write_text(checksum + '  ' + output.name + '\n')
    return {'asset': str(output), 'sha256': checksum, 'tag': tag}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['install', 'update', 'uninstall', 'rollback', 'doctor', 'version', 'build'])
    parser.add_argument('--target', default='.')
    parser.add_argument('--source', default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--host', choices=['codex', 'claude'], default='codex')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--transaction')
    parser.add_argument('--output')
    parser.add_argument('--tag')
    args = parser.parse_args(argv)
    source, root = Path(args.source).resolve(), Path(args.target).absolute()
    if args.command == 'build':
        if not args.output:
            parser.error('build requires --output')
        return build(source, Path(args.output).absolute(), args.tag)
    if root.is_symlink() or root.resolve() != root:
        raise Conflict('Target must be a physical directory without symlink ancestors')
    result = subprocess.run(['git', '-C', str(root), 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    if result.returncode or Path(result.stdout.strip()).resolve() != root:
        raise Conflict('Target must be the root of an existing Git project, not a repositories folder')
    manifest = read_manifest(root)
    if args.command == 'version':
        return {'installed': manifest['version'], 'source': manifest.get('source')}
    if args.command == 'doctor':
        changed = [p for p, expected in manifest['files'].items() if inspect(safe(root, p)) != expected]
        agents = safe(root, 'AGENTS.md')
        if agents.is_symlink():
            raise Conflict('AGENTS.md symlink is unsupported')
        match = block(agents.read_text()) if agents.exists() else None
        actual = digest(match.group().encode()) if match else None
        if actual != manifest.get('agents_block_sha256'):
            changed.append('AGENTS.md:managed-block')
        return {'version': manifest['version'], 'changed': changed, 'ready': bool(manifest['version']) and not changed}
    if args.command == 'rollback':
        if not args.transaction:
            parser.error('rollback requires --transaction')
        if args.dry_run:
            return rollback(root, args.transaction, True)
        with install_lock(root):
            return rollback(root, args.transaction, False)
    plan, desired, content = make_plan(root, source, args.host, args.command == 'uninstall')
    if args.dry_run:
        return plan
    if plan['conflicts']:
        raise Conflict('Conflicts found; inspect --dry-run. No files were changed.')
    with install_lock(root):
        # Recompute under the lock; another install may have completed since preview.
        plan, desired, content = make_plan(root, source, args.host, args.command == 'uninstall')
        return apply(root, plan, desired, content, args.command == 'uninstall')


if __name__ == '__main__':
    try:
        result = main(); print(json.dumps(result))
        if result.get('conflicts') or result.get('ready') is False:
            sys.exit(1)
    except (Conflict, OSError, ValueError, KeyError, TypeError) as error:
        print('Package operation refused: ' + str(error), file=sys.stderr)
        sys.exit(1)
