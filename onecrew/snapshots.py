"""Content-addressed, scoped snapshots. Never mutate the source workspace."""
from __future__ import annotations

import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import uuid

from .ledger import LedgerError, canonical, content_hash

MAX_FILE = 2_000_000
MAX_TOTAL = 16_000_000


def scoped_path(value):
    if not isinstance(value, str) or not value or len(value) > 240 or '\\' in value:
        raise LedgerError('Scope paths must be relative POSIX file paths.')
    parts = value.split('/')
    for part in parts:
        if (part in ('', '.', '..') or part.endswith((' ', '.')) or
                re.search(r'[<>:"|?*\x00-\x1f]', part) or
                re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part, re.I)):
            raise LedgerError('Unsafe scope path.')
        if part.lower() in ('.git', '.onecrew', '.ssh', '.aws') or part.lower().startswith('.env'):
            raise LedgerError('Control or credential paths cannot enter worker snapshots.')
    if PurePosixPath(value).is_absolute():
        raise LedgerError('Absolute scope paths are forbidden.')
    return value


def scope_list(paths):
    if not isinstance(paths, list) or not 1 <= len(paths) <= 200:
        raise LedgerError('Scope requires 1-200 explicit file paths.')
    paths = sorted(scoped_path(p) for p in paths)
    lowered = [p.lower() for p in paths]
    if len(set(lowered)) != len(paths):
        raise LedgerError('Duplicate or case-colliding scope paths.')
    if any(b.startswith(a + '/') for a in lowered for b in lowered if a != b):
        raise LedgerError('A scope file cannot be another file directory.')
    return paths


def safe_file(root, name):
    name = scoped_path(name)
    target = root
    for part in name.split('/'):
        target = target / part
        if target.is_symlink() or (hasattr(target, 'is_junction') and target.is_junction()):
            raise LedgerError('Snapshot paths cannot traverse links or junctions.')
    if not target.resolve().is_relative_to(root.resolve()):
        raise LedgerError('Snapshot path escaped root.')
    return target


def bytes_hash(data):
    return hashlib.sha256(data).hexdigest()


def durable_write(target, data):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name('.' + target.name + '.' + uuid.uuid4().hex)
    try:
        with temporary.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # A Windows reader may briefly hold the destination without delete sharing.
        # Retry only this atomic replacement; never truncate the existing receipt.
        for attempt in range(5):
            try:
                os.replace(temporary, target)
                break
            except PermissionError:
                if os.name!='nt' or attempt==4:raise
                __import__('time').sleep(.02*(attempt+1))
    finally:
        temporary.unlink(missing_ok=True)


class Snapshots:
    def __init__(self, state_root):
        self.root = Path(state_root).resolve() / 'snapshots'

    def blob(self, data):
        if len(data) > MAX_FILE:
            raise LedgerError('Snapshot file exceeds 2 MB.')
        key = bytes_hash(data)
        target = self.root / 'blobs' / key
        if target.exists():
            if bytes_hash(target.read_bytes()) != key:
                raise LedgerError('Corrupt existing snapshot blob.')
        else:
            durable_write(target, data)
        return key

    def read_blob(self, key):
        if not isinstance(key, str) or not re.fullmatch('[0-9a-f]{64}', key):
            raise LedgerError('Invalid snapshot blob reference.')
        path = self.root / 'blobs' / key
        if path.stat().st_size > MAX_FILE:
            raise LedgerError('Snapshot blob exceeds size cap.')
        data = path.read_bytes()
        if bytes_hash(data) != key:
            raise LedgerError('Snapshot blob hash mismatch.')
        return data

    def save(self, manifest):
        key = content_hash(manifest)
        durable_write(self.root / 'manifests' / (key + '.json'), canonical(manifest).encode('utf-8'))
        self.load(key)  # A durable reference is publishable only after all blobs verify.
        return key

    def load(self, key):
        if not isinstance(key, str) or not re.fullmatch('[0-9a-f]{64}', key):
            raise LedgerError('Invalid snapshot reference.')
        path = self.root / 'manifests' / (key + '.json')
        if path.stat().st_size > 200_000:
            raise LedgerError('Snapshot manifest exceeds size cap.')
        value = json.loads(path.read_text(encoding='utf-8'))
        if content_hash(value) != key:
            raise LedgerError('Snapshot manifest hash mismatch.')
        if value.get('version') != 1 or not isinstance(value.get('files'), dict):
            raise LedgerError('Unsupported snapshot manifest.')
        scope_list(list(value['files']))
        total = 0
        for item in value['files'].values():
            for reference in (item['working'], *[s['blob'] for s in item['index']]):
                if reference is not None:
                    total += len(self.read_blob(reference))
        if total > MAX_TOTAL:
            raise LedgerError('Snapshot exceeds 16 MB.')
        return value

    @staticmethod
    def git(project, *args, allow_failure=False):
        result = subprocess.run(['git', '--literal-pathspecs', '-C', str(project), *args],
                                capture_output=True, timeout=20)
        if result.returncode and not allow_failure:
            raise LedgerError('Cannot capture scoped Git state.')
        return result.stdout if result.returncode == 0 else None

    def capture(self, project, paths):
        project = Path(project).resolve()
        paths = scope_list(paths)
        before = self._working(project, paths)
        head = self.git(project, 'rev-parse', '--verify', 'HEAD', allow_failure=True)
        index = self.git(project, 'ls-files', '--stage', '-z', '--', *paths, allow_failure=True)
        # Non-Git folders have no index. A Git folder with unreadable index is unsafe.
        if index is None and self.git(project, 'rev-parse', '--git-dir', allow_failure=True) is not None:
            raise LedgerError('Git index unavailable.')
        files = {p: {'working': self.blob(data) if data is not None else None, 'index': []}
                 for p, data in before.items()}
        for entry in (index or b'').split(b'\0'):
            if not entry:
                continue
            metadata, name = entry.split(b'\t', 1)
            mode, oid, stage = metadata.decode('ascii').split()
            name = name.decode('utf-8')
            if name not in files or mode not in ('100644', '100755'):
                raise LedgerError('Unsupported Git entry (links/submodules are not portable).')
            data = self.git(project, 'cat-file', 'blob', oid)
            files[name]['index'].append({'stage': int(stage), 'mode': mode, 'blob': self.blob(data)})
        if (before != self._working(project, paths) or
                index != self.git(project, 'ls-files', '--stage', '-z', '--', *paths, allow_failure=True) or
                head != self.git(project, 'rev-parse', '--verify', 'HEAD', allow_failure=True)):
            raise LedgerError('Source changed during snapshot; retry without publishing.')
        return self.save({'version': 1, 'parent': None, 'source': str(project),
                          'head': head.decode('ascii').strip() if head else None, 'files': files})

    @staticmethod
    def _working(project, paths):
        result = {}
        total = 0
        for name in paths:
            path = safe_file(project, name)
            if path.exists() and not path.is_file():
                raise LedgerError('Scope must name files, not directories.')
            if path.exists() and path.stat().st_size > MAX_FILE:
                raise LedgerError('Snapshot file exceeds size cap.')
            result[name] = path.read_bytes() if path.exists() else None
            total += len(result[name] or b'')
            if total > MAX_TOTAL:
                raise LedgerError('Snapshot exceeds total size cap.')
        return result

    def overlay(self, base, changes, owned):
        manifest = self.load(base)
        owned = scope_list(owned)
        if not isinstance(changes, dict) or not changes or not set(changes) <= set(owned):
            raise LedgerError('Worker changes must be non-empty and owned.')
        if not set(owned) <= set(manifest['files']):
            raise LedgerError('Owned files must be in captured scope.')
        for name, data in changes.items():
            if data is not None and not isinstance(data, bytes):
                raise LedgerError('Artifact must contain bytes or a deletion.')
            manifest['files'][name]['working'] = self.blob(data) if data is not None else None
        manifest['parent'] = base
        return self.save(manifest)

    def materialize(self, key, destination, *, staged=False):
        manifest = self.load(key)
        destination = Path(destination).resolve()
        destination.mkdir(parents=True, exist_ok=False)
        for name, item in manifest['files'].items():
            if staged:
                entries = item['index']
                if len(entries) > 1 or (entries and entries[0]['stage'] != 0):
                    raise LedgerError('Unmerged stages require explicit conflict resolution.')
                reference = entries[0]['blob'] if entries else None
            else:
                reference = item['working']
            if reference is not None:
                target = safe_file(destination, name)
                durable_write(target, self.read_blob(reference))
        return destination

    def context(self, key):
        manifest = self.load(key)
        result = {}
        for name, item in manifest['files'].items():
            if item['working'] is None:
                result[name] = None
            else:
                data = self.read_blob(item['working'])
                try:
                    result[name] = data.decode('utf-8')
                except UnicodeError:
                    result[name] = {'binary_sha256': item['working'], 'bytes': len(data)}
        return result

    def diff(self, before, after):
        a, b = self.context(before), self.context(after)
        result = []
        for name in sorted(set(a) | set(b)):
            old, new = a.get(name), b.get(name)
            if old == new:
                continue
            if isinstance(old, dict) or isinstance(new, dict):
                result.append(f'Binary change: {name}\n')
            else:
                result.extend(difflib.unified_diff((old or '').splitlines(True), (new or '').splitlines(True),
                                                  fromfile='before/' + name, tofile='after/' + name))
        return ''.join(result)
