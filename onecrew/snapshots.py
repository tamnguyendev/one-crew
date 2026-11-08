"""Content-addressed, scoped snapshots. Never mutate the source workspace."""
from __future__ import annotations

import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import uuid

from .ledger import LedgerError, canonical, content_hash

MAX_FILE = 2_000_000
MAX_TOTAL = 16_000_000
MAX_EVIDENCE = 64_000_000
EVIDENCE_CHUNK = 1_000_000
CONTROL_NAMES = ('.git', '.onecrew', '.ssh', '.aws')        # path components no snapshot carries ...
CREDENTIAL_PREFIX = '.env'                                   # ... nor any component that starts with this


def control_part(part):
    """Is this one path component a control or credential name (`.git`, `.onecrew`, `.ssh`, `.aws`, `.env*`, any case)?"""
    return part.lower() in CONTROL_NAMES or part.lower().startswith(CREDENTIAL_PREFIX)


def scoped_path(value):
    if not isinstance(value, str) or not value or len(value) > 240 or '\\' in value:
        raise LedgerError('Scope paths must be relative POSIX file paths.')
    parts = value.split('/')
    for part in parts:
        if (part in ('', '.', '..') or part.endswith((' ', '.')) or
                re.search(r'[<>:"|?*\x00-\x1f]', part) or
                re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part, re.I)):
            raise LedgerError('Unsafe scope path.')
        if control_part(part):
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


class ControlAlias(LedgerError):
    """The NAME passed scoped_path, but on disk it reaches a control or credential path: a Windows short (8.3) name such as ENV~1.EXA for
    `.env.example` or GIT~1 for `.git`."""


def is_link(path):
    """Is this path a symbolic link or, on Windows, a junction? Neither is followed by a snapshot, a checkout listing or an adapter."""
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def safe_file(root, name):
    name = scoped_path(name)
    target = root
    for part in name.split('/'):
        target = target / part
        if is_link(target):
            raise LedgerError('Snapshot paths cannot traverse links or junctions.')
    top, real = root.resolve(), target.resolve()
    if not real.is_relative_to(top):
        raise LedgerError('Snapshot path escaped root.')
    if any(control_part(part) for part in real.relative_to(top).parts):          # judged by what the name reaches, not by how it is spelled
        raise ControlAlias('Control or credential paths cannot enter worker snapshots (this name reaches one, a Windows short name).')
    return target


def final_path(fd):
    """The path the open file `fd` really is, as the system resolves it (links and junctions followed); None when it cannot be told."""
    if os.name == 'nt':
        import ctypes
        import msvcrt
        buffer = ctypes.create_unicode_buffer(32768)
        size = ctypes.windll.kernel32.GetFinalPathNameByHandleW(ctypes.c_void_p(msvcrt.get_osfhandle(fd)), buffer, 32768, 0)
        if not size or size >= 32768: return None
        text = buffer.value
        return '\\\\' + text[8:] if text.startswith('\\\\?\\UNC\\') else text[4:] if text.startswith('\\\\?\\') else text
    try:
        return os.readlink(f'/proc/self/fd/{fd}')
    except OSError:
        pass
    try:
        import fcntl                                   # macOS
        if hasattr(fcntl, 'F_GETPATH'):
            return fcntl.fcntl(fd, fcntl.F_GETPATH, b'\0' * 1024).split(b'\0', 1)[0].decode('utf-8', 'surrogateescape')
    except OSError:
        pass
    return None


def check_alone(fd, expected, label):
    """Judge the open file `fd` that is about to be read as `expected`: a regular file, no other name on the disk (link count 1), and the file the path
    as named leads to with no link or junction on the way (its final path is `expected`). A hard link may be the other name of a file every reader
    is kept from (an ignored .env, a home folder, the ledger), and a folder made a junction after its path was checked leads anywhere; judged on the
    handle, a change between the check and the read cannot slip through (2.3 alpha AL-01; Codex review of beta 2.3.0.dev9, P1). LedgerError otherwise."""
    status = os.fstat(fd)
    if not stat.S_ISREG(status.st_mode):
        raise LedgerError(f'{label} is not a regular file, so it is not read.')
    if status.st_nlink > 1:
        raise LedgerError(f'{label} has another name on the disk (a hard link), so it is not read; remove the other name or use a copy.')
    final = final_path(fd)
    if final is None and os.name != 'nt':
        final = os.path.realpath(str(expected))         # no handle API on this system: the path as it resolves now (a recorded limit)
    if final is None or os.path.normcase(final) != os.path.normcase(os.path.abspath(str(expected))):
        raise LedgerError(f'{label} is reached through a link or junction ({final or "its final path cannot be told"}), so it is not read.')


def _alone(path, name):
    """The bytes of a scope file, read on a handle check_alone accepted (`path` is the scope root, resolved, joined with the name)."""
    with open(path, 'rb') as handle:
        check_alone(handle.fileno(), path, f'Snapshot file {name}')
        return handle.read()


def bytes_hash(data):
    return hashlib.sha256(data).hexdigest()


def _holds(target, data):
    try:
        return target.read_bytes() == data
    except OSError:
        return False


def durable_write(target, data):
    target.parent.mkdir(parents=True, exist_ok=True)
    # Do not repeat a long content-addressed filename: Windows Store state roots
    # can fit the destination but exceed MAX_PATH for the temporary sibling.
    temporary = target.with_name('.oc-' + uuid.uuid4().hex + '.tmp')
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
                # dev11 (test_a_r13): a destination another thread holds open already
                # holding exactly these bytes is written; anything else still fails.
                if _holds(target, data): break
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

    def set_aside_damaged(self, key):
        """A blob whose bytes are not its name is never read as evidence. Set aside (kept, under another name) once a recorded decision closed the
        run that named it: otherwise the same result, computed again, could never be stored. Returns True when a file was set aside."""
        if not isinstance(key, str) or not re.fullmatch('[0-9a-f]{64}', key):
            return False
        path = self.root / 'blobs' / key
        if not path.exists() or bytes_hash(path.read_bytes()) == key:
            return False
        os.replace(path, path.with_name(key + '.damaged'))
        return True

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

    def evidence(self, data):
        """Bounded runtime metadata/logs; never raises the source-file limit.

        Small evidence retains its legacy blob reference. Large evidence uses
        immutable chunks and a whole-document hash, published only after writes.
        """
        if len(data) > MAX_EVIDENCE:
            raise LedgerError('Runtime evidence exceeds 64 MB.')
        if len(data) <= MAX_FILE:
            return self.blob(data)
        return {'format':'chunked-evidence-v1', 'bytes':len(data), 'sha256':bytes_hash(data),
                'chunks':[self.blob(data[i:i+EVIDENCE_CHUNK]) for i in range(0,len(data),EVIDENCE_CHUNK)]}

    def read_evidence(self, reference):
        if isinstance(reference,str): return self.read_blob(reference)
        if (not isinstance(reference,dict) or set(reference)!={'format','bytes','sha256','chunks'}
                or reference['format']!='chunked-evidence-v1'
                or type(reference['bytes']) is not int or not MAX_FILE < reference['bytes'] <= MAX_EVIDENCE
                or not isinstance(reference['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',reference['sha256'])
                or not isinstance(reference['chunks'],list)
                or len(reference['chunks'])!=(reference['bytes']+EVIDENCE_CHUNK-1)//EVIDENCE_CHUNK):
            raise LedgerError('Invalid runtime evidence reference.')
        parts=[]
        for index,key in enumerate(reference['chunks']):
            data=self.read_blob(key)
            expected=min(EVIDENCE_CHUNK,reference['bytes']-index*EVIDENCE_CHUNK)
            if len(data)!=expected: raise LedgerError('Runtime evidence chunk length mismatch.')
            parts.append(data)
        data=b''.join(parts)
        if bytes_hash(data)!=reference['sha256']:
            raise LedgerError('Runtime evidence document hash mismatch.')
        return data

    def save(self, manifest):
        key = content_hash(manifest)
        target, data = self.root / 'manifests' / (key + '.json'), canonical(manifest).encode('utf-8')
        # dev11 (test_a_r13): content-addressed, like blob(): an existing manifest with these exact bytes is not replaced again. Two doors
        # capturing the same source saved it twice, and on Windows replacing a file another thread is reading fails.
        if not _holds(target, data): durable_write(target, data)
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

    def capture(self, project, paths, kept=None):
        """`kept`: names of the folder that the snapshot rules keep from every reader and that are left out (artifact identity of a folder without Git,
        beta report D8). They are named in the manifest, not read, and a manifest without any is the one there always was."""
        project = Path(project).resolve()
        paths = scope_list(paths)
        before = self._working(project, paths)
        head = self.git(project, 'rev-parse', '--verify', 'HEAD', allow_failure=True)
        index = self.git(project, 'ls-files', '--stage', '-z', '--', *paths, allow_failure=True)
        # Non-Git folders have no index. A Git folder with unreadable index is unsafe.
        if index is None and self.git(project, 'rev-parse', '--git-dir', allow_failure=True) is not None:
            raise LedgerError('Git index unavailable.')
        # the working bytes are stored only once the second pass below agrees: a folder made a junction between the two passes leaves nothing
        # behind in the store (review of AL-01, P3)
        files = {p: {'working': data, 'index': []} for p, data in before.items()}
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
        for item in files.values():
            if item['working'] is not None: item['working'] = self.blob(item['working'])
        return self.save({'version': 1, 'parent': None, 'source': str(project),
                          'head': head.decode('ascii').strip() if head else None, 'files': files, **({'kept': list(kept)} if kept else {})})

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
            result[name] = _alone(path, name) if path.exists() else None
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
