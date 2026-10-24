"""Generic artifact identity: existing Git trees or v1 content-addressed snapshots.

Snapshot identities bind the canonical source folder and every eligible file's
bytes. They do not confer execution authority or attest an external service.
"""
import os
from pathlib import Path

from ...ledger import LedgerError, content_hash
from ...snapshots import Snapshots, bytes_hash, safe_file, scope_list
from . import command


def is_git(directory):
    root = Path(directory).resolve()
    # A broken repository must fail in the Git path, never silently become a
    # different artifact kind. Nested worktrees use a .git file, not a folder.
    return any((p / '.git').exists() for p in (root, *root.parents))


def _paths(directory):
    root = Path(directory).resolve()
    if not root.is_dir():
        raise LedgerError('Artifact directory does not exist.')
    paths = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != '.onecrew']
        for name in dirs + files:
            target = Path(base) / name
            if target.is_symlink() or (hasattr(target, 'is_junction') and target.is_junction()):
                raise LedgerError('Artifact snapshots cannot traverse links or junctions.')
        paths.extend((Path(base) / name).relative_to(root).as_posix() for name in files)
        if len(paths) > 200:
            raise LedgerError('Artifact snapshot exceeds the existing 200-file scope limit.')
    return scope_list(paths)


def _manifest(directory):
    root = Path(directory).resolve()
    paths = _paths(root)
    before = Snapshots._working(root, paths)
    if paths != _paths(root) or before != Snapshots._working(root, paths):
        raise LedgerError('Artifact changed while computing its identity.')
    return {'version': 1, 'parent': None, 'source': str(root), 'head': None,
            'files': {p: {'working': bytes_hash(data), 'index': []} for p, data in before.items()}}


def identity(directory):
    """Read a current artifact id; keeps command.artifact_sha semantics for Git."""
    return command.artifact_sha(directory) if is_git(directory) else content_hash(_manifest(directory))


def capture(ledger, directory, scratch):
    """Return (isolated checkout, identity, receipt proof), reusing v1 snapshots."""
    directory = Path(directory).resolve()
    before = identity(directory)
    if is_git(directory):
        return command._checkout(directory, before, scratch), before, {'artifact_kind': 'git-tree'}
    state = Path(ledger.state_root).resolve()
    if state == directory or directory in state.parents:
        raise LedgerError('Non-Git artifact state root must be outside the source folder.')
    store = Snapshots(ledger.state_root)
    key = store.capture(directory, _paths(directory))
    if key != before or identity(directory) != before:
        raise LedgerError('Artifact changed while capturing its snapshot.')
    workspace = Path(scratch) / 'src'
    store.materialize(key, workspace)
    return workspace, before, {'artifact_kind': 'snapshot', 'artifact_snapshot': key}


def _load(ledger, value, directory):
    if not isinstance(value, str) or not command.TREE_ID.fullmatch(value) or set(value) == {'0'}:
        raise LedgerError('Artifact must have a nonzero content hash.')
    try:
        manifest = Snapshots(ledger.state_root).load(value)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise LedgerError('Artifact snapshot is missing or invalid: ' + str(error)[:160]) from error
    expected = Path(directory).resolve()
    if (manifest.get('parent') is not None or manifest.get('head') is not None or
            manifest.get('source') != str(expected) or any(item.get('index') or not item.get('working')
                                                         for item in manifest['files'].values())):
        raise LedgerError('Artifact snapshot does not bind this canonical source folder.')
    return manifest


def validate_evidence(ledger, value, body=None):
    """Verify snapshot and every retained blob. False means use existing Git pins."""
    body = body or {}
    if body.get('artifact_kind') != 'snapshot':
        if is_git(ledger.project):
            return False
        # Acceptance can validate the already-retained identity without a
        # verifier receipt. It still requires the exact v1 snapshot and blobs.
        if body.get('artifact_kind') not in (None, 'snapshot'):
            raise LedgerError('Non-Git artifact requires snapshot evidence.')
    if body.get('artifact_snapshot', value) != value:
        raise LedgerError('Artifact snapshot reference differs from the observed artifact.')
    directory = Path(body.get('cwd') or ledger.project).resolve()
    if directory != Path(ledger.project).resolve():
        raise LedgerError('Snapshot artifact belongs to a different project folder.')
    _load(ledger, value, directory)
    after = body.get('artifact_sha_after')
    if after is not None and (not isinstance(after, str) or not command.TREE_ID.fullmatch(after) or set(after) == {'0'}):
        raise LedgerError('After-artifact identity is invalid.')
    return True


def canonical(ledger, value):
    """Acceptance identity, with unchanged Git commit-to-tree normalization."""
    if not isinstance(value, str) or not command.TREE_ID.fullmatch(value) or set(value) == {'0'}:
        raise LedgerError('Artifact must be a nonzero 40/64-hex content hash.')
    if not is_git(ledger.project):
        _load(ledger, value, ledger.project)
        return value
    try:
        tree = command._git(ledger.project, 'rev-parse', '--verify', '-q', '--end-of-options', value + '^{tree}')
    except LedgerError:
        return value
    return tree if command.TREE_ID.fullmatch(tree or '') else value
