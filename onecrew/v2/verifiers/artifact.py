"""Generic artifact identity: existing Git trees or v1 content-addressed snapshots.

Snapshot identities bind the canonical source folder and every eligible file's
bytes, and the names (never the content) of the control and credential files that
were left out. They do not confer execution authority or attest an external service.
"""
import os
import contextvars
from functools import wraps
from pathlib import Path

from ...ledger import LedgerError, content_hash
from ...snapshots import Snapshots, bytes_hash, is_link, safe_file, scope_list, scoped_path
from . import command


_observation = contextvars.ContextVar('onecrew_artifact_observation', default=None)


def observed_view(function):
    """One fresh observation for related projections in a single publication.

    Never wraps execution, apply or acceptance. No process-wide/stat cache:
    the next operation reads bytes again, including untracked dependencies.
    """
    @wraps(function)
    def wrapped(*args, **kwargs):
        token = _observation.set({})
        try:
            return function(*args, **kwargs)
        finally:
            _observation.reset(token)
    return wrapped


def is_git(directory):
    root = Path(directory).resolve()
    # A broken repository must fail in the Git path, never silently become a
    # different artifact kind. Nested worktrees use a .git file, not a folder.
    return any((p / '.git').exists() for p in (root, *root.parents))


def _kept(rel):
    """Do the snapshot rules (scoped_path) keep this path of the folder from every reader: .env*, .ssh, .aws, a nested .git, a device name, a reserved
    character, a path over 240 characters? The name decides; nothing is opened."""
    try:
        scoped_path(rel)
        return False
    except LedgerError:
        return True


def _holds_files(path):
    """Does the kept folder `path` hold a file, at any depth (`.onecrew` folders do not count, as they never did)? Names only, and the walk stops at the
    first file. A link or a junction met on the way stops the run, as it does anywhere in the folder (review R14)."""
    for base, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d != '.onecrew']
        if any(is_link(Path(base) / name) for name in dirs + files):
            raise LedgerError('Artifact snapshots cannot traverse links or junctions.')
        if files: return True
    return False


def _paths(directory):
    """(paths, kept): the files that identify a folder which is not a Git tree, and the names left out of its identity (a folder with a slash at the end).
    A name the snapshot rules keep from every reader is left out, as Port.files() leaves it out of a checkout (beta report B5, D8): never read, never
    hashed, no part of the 200-file limit, and a folder is not walked (it is named only if it holds a file: an empty one changes nothing, as it never did). A link or a junction still
    stops the run, whatever its name (review R14); `.onecrew` folders are skipped as they always were. While the folder holds kept names, a file that has
    another name on the disk (a hard link) stops it too: that other name may be a kept one, and the file would be read and hashed under the ordinary
    name (review E4); a folder that holds none is identified as it always was."""
    root = Path(directory).resolve()
    if not root.is_dir():
        raise LedgerError('Artifact directory does not exist.')
    paths, kept = [], []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != '.onecrew']
        for name in dirs + files:
            if is_link(Path(base) / name):
                raise LedgerError('Artifact snapshots cannot traverse links or junctions.')
        here = Path(base).relative_to(root)
        for name in list(dirs):
            rel = (here / name).as_posix()
            if _kept(rel):
                if _holds_files(Path(base) / name): kept.append(rel + '/')           # a folder is named with its slash: what was left out is not a file
                dirs.remove(name)                              # not walked: nothing below it is listed or read
        for name in files:
            rel = (here / name).as_posix()
            (kept if _kept(rel) else paths).append(rel)
        if len(paths) > 200:
            raise LedgerError('Artifact snapshot exceeds the existing 200-file scope limit.')
        if len(kept) > 200:
            raise LedgerError('Artifact snapshot leaves out more than 200 control or credential names.')
    for rel in kept:
        try:
            rel.encode('utf-8')
        except UnicodeEncodeError:                             # it is named in the identity, so it must be text (review FX-R05); 4bb41b3 refused it too
            raise LedgerError('Artifact holds a control or credential name that is not valid Unicode; rename or remove it.') from None
    shared = next((rel for rel in paths if (root / rel).stat().st_nlink > 1), None) if kept else None
    if shared:
        raise LedgerError(f'{shared!r} has more than one name on the disk (a hard link) and the folder holds control or credential names '
                          f'({", ".join(sorted(kept)[:3])}): the other name may be one of those, and the file would be read and hashed under this one. '
                          'Break the link or move the credential file out of the folder.')
    return scope_list(paths), sorted(kept)


def _manifest(directory):
    """The identity of the folder, as a snapshot manifest: its files by content, and, when there are any, the names left out (`kept`: names only). A folder
    without kept names has the manifest, and so the identity, it always had."""
    root = Path(directory).resolve()
    paths, kept = _paths(root)
    before = Snapshots._working(root, paths)
    if (paths, kept) != _paths(root) or before != Snapshots._working(root, paths):
        raise LedgerError('Artifact changed while computing its identity.')
    return {'version': 1, 'parent': None, 'source': str(root), 'head': None,
            'files': {p: {'working': bytes_hash(data), 'index': []} for p, data in before.items()}, **({'kept': kept} if kept else {})}


def identity(directory):
    """Read a current artifact id; keeps command.artifact_sha semantics for Git. What a view, a report or an evidence check compares (no adapter reads
    the tree): for Git a hard link or a junction does not stop it, so a changed artifact is still seen as changed (review D-R01; such a name is a
    marker of its stat data, never its content, B2). A folder without Git is refused with the reason when it holds a hard link (AL-01): its
    identity is the snapshot of its files, which never reads such a file."""
    observation = _observation.get()
    key = str(Path(directory).resolve())
    if observation is not None and key in observation:
        return observation[key]
    value = command.artifact_sha(directory) if is_git(directory) else content_hash(_manifest(directory))
    if observation is not None and not command.reading_only(): observation[key] = value      # a read's tree is gone after the read; a door must not take it for one it can keep
    return value


def verified_identity(directory):
    """identity for a verifier, which reads the tree: for Git, refused before git hashes anything when a name of the working tree is a hard link or
    is reached through a junction (command.verified_sha, reviews FX-R01, D-R03)."""
    return command.verified_sha(directory) if is_git(directory) else content_hash(_manifest(directory))


def capture(ledger, directory, scratch):
    """Return (isolated checkout, identity, receipt proof), reusing v1 snapshots."""
    directory = Path(directory).resolve()
    before = verified_identity(directory)
    if is_git(directory):
        return command._checkout(directory, before, scratch), before, {'artifact_kind': 'git-tree'}
    state = Path(ledger.state_root).resolve()
    if state == directory or directory in state.parents:
        raise LedgerError('Non-Git artifact state root must be outside the source folder.')
    store = Snapshots(ledger.state_root)
    paths, kept = _paths(directory)
    key = store.capture(directory, paths, kept=kept)
    if key != before or verified_identity(directory) != before:
        raise LedgerError('Artifact changed while capturing its snapshot.')
    workspace = Path(scratch) / 'src'
    store.materialize(key, workspace)
    return workspace, before, {'artifact_kind': 'snapshot', 'artifact_snapshot': key, **({'artifact_kept': kept} if kept else {})}


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
