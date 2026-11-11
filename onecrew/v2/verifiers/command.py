"""Verifier `command`: run the milestone's argv in a workspace, within a minute cap, and keep the evidence.

The receipt is a blob (sha256-addressed, same store as v1 receipts) that binds plan hash, revision, milestone, argv and the
artifact (a Git tree hash of the working tree) to the exit code and output. verdict.run announces each receipt it makes
(verdict.receipt_issued) and record() takes no other receipt for a command milestone, so a hand-written receipt, however
well formed, is refused.
"""
import codecs
import contextvars
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

from ...ledger import LedgerError, canonical, utcnow
from ...snapshots import Snapshots, check_alone

OUTPUT_CAP = 1_000_000
TREE_ID = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')          # the only shape of a tree id that is ever given to git


# ---- How long making the identity of a working tree may take (hotfix of the verdict timeout on a large repository) -------------------------------
#
# Outside an operation that needs the identity (a view, a hook) a git step keeps its limit of STEP_SECONDS. An operation that needs it (a verifier, an
# approval, a report) runs inside snapshot_limits(): each snapshot then has one budget for ALL its steps, git and the Python walks over the files alike,
# never more than the root deadline leaves. The budget is separate from the verifier's max_minutes and from the root's budget, and it grants nothing: no
# write, no call, no extra time for the verifier. It only decides how long OneCrew waits before saying that it could not finish.
STEP_SECONDS = 120
SNAPSHOT_ENV = 'ONECREW_SNAPSHOT_MINUTES'
SNAPSHOT_MINUTES = 60
SNAPSHOT_MINUTES_MAX = 720
PROGRESS_SECONDS = 30
GIT_PROGRAM = ('git',)

_limits = contextvars.ContextVar('onecrew_snapshot_limits', default=None)
_active = contextvars.ContextVar('onecrew_snapshot_budget', default=None)
_read_only = contextvars.ContextVar('onecrew_read_only_objects', default=None)


class ReadIsolationFailed(LedgerError):
    """A read (leaves_no_objects) could not keep git's writes out of the project, so it stopped. It has no result and it never falls back to the project's own store."""

    def __init__(self, directory, cause):
        self.directory, self.cause = str(directory), cause
        super().__init__(f'This read stopped and gave no result: the throw-away object store that keeps it from writing to the project could not be set up for {directory} ({cause}). '
                         'Nothing was judged and nothing was stored in the project. Fix the cause (git, the repository, the temp folder), then run the same command again.')

    def structured(self):
        return {'read_isolation': {'directory': self.directory, 'cause': self.cause}, 'stored_in_project': False, 'next': 'Fix the cause, then run the same command again.'}


class SnapshotFailed(LedgerError):
    """The identity of the working tree could not be made in time. `verifier_started` says what is known of the verifier: False (it was not called, so
    a new run may start), True (it ran: its receipt is kept, inconclusive) or None (the caller does not know, which is held like any unknown outcome)."""

    def __init__(self, stage, step, seconds, limit, reason='timeout', verifier_started=None, root_bound=False):
        self.stage, self.step, self.seconds, self.limit, self.reason, self.verifier_started = stage, step, round(seconds, 1), round(limit, 1), reason, verifier_started
        cause = (f'the root deadline leaves no time for it (it was given {self.limit} s)' if reason == 'deadline'
                 else f'stopped after {self.seconds} s, the limit is {self.limit} s')
        super().__init__(f'The snapshot of the working tree ({stage}, step: {step}) did not finish: {cause}. Nothing was recorded as passed. '
                         f'It takes longer with more files that are neither ignored nor committed. ' +
                         ('The root execution window is exhausted; increasing the snapshot limit cannot extend it. Retain the evidence for an owner decision under a valid grant.' if reason == 'deadline'
                          else f'Set {SNAPSHOT_ENV} to more minutes (now {self.limit / 60:g}' + ('; the root deadline still applies' if root_bound else '') + '), then run the same command again.'))

    def structured(self):
        started = self.verifier_started
        return {'snapshot': {'stage': self.stage, 'step': self.step, 'seconds': self.seconds, 'limit_seconds': self.limit, 'reason': self.reason},
                'verifier_started': 'unknown' if started is None else started,
                'next': ('Read `verdict status`: the verifier may have run, it is not run again by itself.' if started is None else
                         'The verifier ran: its receipt is kept and the verdict is inconclusive. Running it again is a new decision.' if started else
                         ('The verifier was not called. Ask the owner about the root deadline.' if self.reason == 'deadline' else
                          f'The verifier was not called. Raise {SNAPSHOT_ENV} and run `verdict run` again; no release is needed.'))}


class _Budget:
    def __init__(self, stage, limit, reason='timeout', root_bound=False):
        self.stage, self.limit, self.begin, self.said, self.names = stage, limit, time.monotonic(), None, 0
        self.reason, self.root_bound = reason, root_bound

    def spent(self):
        return time.monotonic() - self.begin

    def left(self):
        return self.limit - self.spent()

    def check(self, step):
        if self.left() <= 0: raise SnapshotFailed(self.stage, step, self.spent(), self.limit, 'deadline' if self.limit <= 0 else self.reason, root_bound=self.root_bound)

    def say(self, step):
        """A line each PROGRESS_SECONDS, the first one after that long: a quick snapshot says nothing."""
        now = time.monotonic()
        if now - (self.said if self.said is not None else self.begin) < PROGRESS_SECONDS: return
        self.said = now
        print(f'onecrew: snapshot ({self.stage}): {step}, {int(self.spent())} s of {int(self.limit)} s', file=sys.stderr, flush=True)

    def tick(self, step):
        """Called for each name of a walk over the files: the walk stays inside the budget too."""
        self.names += 1
        if self.names % 1024 == 0:
            self.check(step)
            self.say(f'{step} ({self.names} names)')


def snapshot_seconds():
    """The budget of one snapshot, in seconds. A value that cannot be read is refused: it never turns into another limit, and there is no unlimited one."""
    text = os.environ.get(SNAPSHOT_ENV, '').strip()
    if not text: return SNAPSHOT_MINUTES * 60
    try:
        minutes = float(text)
    except ValueError:
        minutes = 0
    if not 0 < minutes <= SNAPSHOT_MINUTES_MAX:
        refused = LedgerError(f'{SNAPSHOT_ENV} must be a number of minutes above 0 and at most {SNAPSHOT_MINUTES_MAX}, not {text!r}.')
        refused.verifier_started = False               # issue #2, review of dev14: reading a setting never calls a verifier, wherever it is read
        raise refused
    return minutes * 60


@contextmanager
def snapshot_limits(deadline=None):
    """Inside it, each snapshot has the budget of snapshot_seconds(), never more than the root `deadline` leaves."""
    token = _limits.set({'seconds': snapshot_seconds(), 'deadline': deadline})
    try:
        yield
    finally:
        _limits.reset(token)


@contextmanager
def _snapshot(stage, floor=0):
    """One snapshot's configured finite budget; a nested call shares it. snapshot_limits can also bound it by the root deadline. `floor`: what is left for
    a step that must end a run whose verifier already ran, when the root deadline has passed meanwhile (the time the run's grace always gave it)."""
    limits = _limits.get()
    if _active.get() is not None:
        yield
        return
    # Every snapshot entry point honors the configured finite budget, including
    # handoff, acceptance and status. Bare non-snapshot git steps retain 120s.
    if limits is None:
        limits = {'seconds': snapshot_seconds(), 'deadline': None}
    limit = limits['seconds']
    reason = 'timeout'
    if limits['deadline'] is not None:
        left = (dt.datetime.fromisoformat(limits['deadline']) - dt.datetime.now(dt.timezone.utc)).total_seconds()
        if max(left, floor) < limit: reason = 'deadline'
        limit = min(limit, max(left, floor))
    budget = _Budget(stage, limit, reason, root_bound=limits['deadline'] is not None)
    budget.check('start')
    token = _active.set(budget)
    try:
        yield
    finally:
        _active.reset(token)


def _bounded(function):
    """A snapshot entry point: its own budget when it is the outermost one."""
    @wraps(function)
    def wrapper(*args, **kwargs):
        with _snapshot('identity'):
            return function(*args, **kwargs)
    return wrapper


def _tick(step):
    budget = _active.get()
    if budget is not None: budget.tick(step)


def _feed(stream, data):
    try:
        if data: stream.write(data)
    except OSError:                       # git ended (or was killed): nobody reads the rest
        pass
    finally:
        try: stream.close()
        except OSError: pass             # a broken pipe still belongs to this pump


def _collect(stream, into):
    try:
        into.append(stream.read())
    finally:
        stream.close()


@contextmanager
def leaves_no_objects():
    """A read that judges the working tree (plan show, engine next, the reports) stores nothing in the project. Git computes the same ids: what it would
    write goes to a throw-away object store, and the project's objects stay readable as an alternate, so a diff against the tree just made still works. The
    tree made here exists only for the length of the read: a door that keeps or pins a tree (handoff, verdict, acceptance, `verdict artifact`) runs outside this.
    When the store cannot be set up the read has no result: no later git of this read runs, and the end of the read raises ReadIsolationFailed even when the code
    in between caught the error (several views treat a failed git as "not judged", which would read as a pass here)."""
    if _read_only.get() is not None:
        yield
        return
    state = {'temp': None, 'directories': {}, 'stores': {}, 'failure': None}
    token = _read_only.set(state)
    try:
        try:
            yield
        finally:
            _read_only.reset(token)
            if state['temp']: state['temp'].cleanup()   # git's loose objects are read-only on Windows: this removes those too, a plain rmtree does not
    except Exception as error:
        if state['failure'] is not None and not isinstance(error, ReadIsolationFailed): raise ReadIsolationFailed(*state['failure']) from error
        raise
    if state['failure'] is not None: raise ReadIsolationFailed(*state['failure'])


def reading_only():
    return _read_only.get() is not None


NOT_A_REPOSITORY = 'not a git repository (or any of the parent directories)'      # git walked to the top and found none; a broken .git says something else


def _objects_of(directory):
    """The objects folder of the repository at `directory`. None only when it certainly is no repository, so git there has nothing to write into. Anything else
    raises: a repository whose store cannot be named must not be taken for "no repository"."""
    if not Path(directory).is_dir(): return None
    clean = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
    done = subprocess.run(['git', '-C', str(directory), 'rev-parse', '--git-path', 'objects'], capture_output=True, env=dict(clean, LC_ALL='C', LANGUAGE='C'), timeout=30,
                          stdin=subprocess.DEVNULL, creationflags=0x08000000 if os.name == 'nt' else 0)
    detail = done.stderr.decode('utf-8', 'replace').strip()
    if done.returncode:
        if NOT_A_REPOSITORY in detail: return None
        raise OSError(f'git exited with {done.returncode}: {detail[:200]}')
    named = done.stdout.decode('utf-8', 'surrogateescape').strip()
    if not named: raise OSError('git named no objects folder')
    objects = (Path(directory) / named).resolve()
    if not objects.is_dir(): raise OSError(f'the objects folder {objects} is not there')
    return objects


def _temporary_store(state, objects):
    store = os.path.normcase(str(objects))
    if store not in state['stores']:
        path = objects.as_posix()
        if any(ord(c) < 32 for c in path): raise ValueError('the path of the objects folder holds a control character')
        state['temp'] = state['temp'] or tempfile.TemporaryDirectory(prefix='onecrew-read-', ignore_cleanup_errors=True)
        temporary = Path(state['temp'].name) / str(len(state['stores'])) / 'objects'
        temporary.mkdir(parents=True)
        alternate = '"' + path.replace('\\', '\\\\').replace('"', '\\"') + '"'     # quoted: a path may hold the separator
        state['stores'][store] = {'GIT_OBJECT_DIRECTORY': str(temporary), 'GIT_ALTERNATE_OBJECT_DIRECTORIES': alternate}
    return state['stores'][store]


def _object_env(directory):
    """The object-store override of the read in progress, one store per repository. Nothing when no read is in progress or `directory` is no repository. When the
    store cannot be set up this raises, now and for every later git of the same read: git never runs against the project's own store."""
    state = _read_only.get()
    if state is None: return {}
    if state['failure'] is not None: raise ReadIsolationFailed(*state['failure'])
    try:
        key = os.path.normcase(os.path.abspath(str(directory)))
        if key in state['directories']: return state['directories'][key]
        objects = _objects_of(directory)
        if objects is None: return {}
        state['directories'][key] = _temporary_store(state, objects)
        return state['directories'][key]
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        state['failure'] = (str(directory), f'{type(error).__name__}: {error}'[:300])
    raise ReadIsolationFailed(*state['failure'])


def _git(directory, *args, env=None, input=None, raw=False):
    # F8: the caller's GIT_DIR / GIT_WORK_TREE / ... never reach git; only what this module sets (GIT_INDEX_FILE) does
    clean = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
    budget, step = _active.get(), ' '.join(a for a in args if not a.startswith('-') and '=' not in a)[:60] or 'git'
    if budget is not None: budget.check(step)
    limit = budget.left() if budget is not None else STEP_SECONDS
    begin = time.monotonic()
    # Threads, not subprocess.run(timeout): on Windows run() writes `input` first, and with thousands of names that write lasts as long as git works, so
    # the limit was looked at only when git was nearly done. Here the limit holds while git reads its input, and a kill reaches only this git's own tree.
    process = subprocess.Popen([*GIT_PROGRAM, '-C', str(directory), *args], stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=dict(clean, **{k: v for k, v in (env or {}).items() if k.upper().startswith('GIT_')}, **_object_env(directory)),
                               creationflags=0x08000000 if os.name == 'nt' else 0)
    out, err = [], []
    pumps = [threading.Thread(target=_collect, args=(process.stdout, out), daemon=True), threading.Thread(target=_collect, args=(process.stderr, err), daemon=True)]
    if input is not None: pumps.append(threading.Thread(target=_feed, args=(process.stdin, input), daemon=True))
    for pump in pumps: pump.start()
    try:
        while True:
            left = limit - (time.monotonic() - begin)
            if left <= 0: raise subprocess.TimeoutExpired(process.args, limit)
            try:
                process.wait(timeout=min(left, PROGRESS_SECONDS))
                break
            except subprocess.TimeoutExpired:
                if budget is not None: budget.say(step)
    except subprocess.TimeoutExpired:
        _kill_tree(process)
        process.wait()
        for pump in pumps: pump.join(5)
        stage, spent = (budget.stage, budget.spent()) if budget is not None else ('outside a verifier', time.monotonic() - begin)
        raise SnapshotFailed(stage, step, spent, budget.limit if budget is not None else STEP_SECONDS,
                             budget.reason if budget is not None else 'timeout', root_bound=bool(budget is not None and budget.root_bound)) from None
    except BaseException:
        _kill_tree(process)
        raise
    for pump in pumps: pump.join()
    stdout, stderr = (out[0] if out else b''), (err[0] if err else b'')
    if process.returncode:
        raise LedgerError('git ' + ' '.join(args[:2]) + ' failed: ' + stderr.decode('utf-8', 'replace')[:300])
    return stdout if raw else stdout.decode('utf-8', 'replace').strip()


def toplevel(directory):
    """Resolved Git toplevel of a directory (C6: a verdict speaks about the project's repository, not a clone nested in it)."""
    return Path(_git(directory, 'rev-parse', '--show-toplevel')).resolve()


@_bounded
def artifact_sha(directory, verified=False):
    """Git tree hash of the working tree (tracked and untracked, honouring .gitignore), via a throw-away index: the
    repository's own index and refs are not touched. A name that hard_links finds (another name on the disk, a file through a junction, a name that
    cannot be examined) is never hashed: its place in the tree holds a marker blob made of its stat data only (size, modification time, file id), so
    the identity still changes when that file changes and nothing of its content reaches the object store (2.3 beta B2). verified_sha refuses such
    a tree; this one is what views, reports and evidence checks compare.
    A name can also change between that check and git's read of it (Codex review of beta 2.3.0.dev9, P1). So git never walks the working tree here:
    every file it takes is opened first and judged on that handle (_Pins: a regular file, one name on the disk, its final path the path as named),
    kept open while `git update-index` hashes exactly those files (the same clean conversion as `git add`), and only then closed. On Windows the open
    handle (shared for reading and writing, not for deleting) keeps the file and every folder above it from being renamed, deleted or replaced, so
    the file git reads is the one judged. Links and folders (a nested repository, a file that became a folder) are pinned the same way, although git
    reads no content there: otherwise such a name could become a hard link before git looks at it (review of 3c1687a, finding 1). A file that fails
    is a marker here and refuses verified_sha. A file that is gone is dropped, as `git add -A` drops it, unless the real index keeps it outside a
    sparse checkout. OneCrew's own files (.onecrew/) are never part of the tree, so they are neither held nor read (finding 4)."""
    top = str(Path(_git(directory, 'rev-parse', '--show-toplevel')).resolve())
    linked = set(hard_links(top))
    if verified and linked: refuse_hard_links(top)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
        env = {'GIT_INDEX_FILE': str(Path(temp) / 'index')}
        _git(top, 'read-tree', 'HEAD', env=env)
        held, others = _listed(top, env, '--cached'), _listed(top, env, '--others', '--exclude-standard')
        with _Pins(top) as pins:
            names = sorted(n for n in held | others if n not in linked and n.rstrip('/') not in linked and not _own(n))
            refused, gone = pins.pin(names)
            if refused and verified: raise HardLinked(_refusal(*refused[0]))
            why = dict(refused)
            linked |= set(why)
            _stage(top, env, sorted(pins.held), [n for n in gone if n in held and n not in _sparse_kept(top)])
            _repositories_for_files(top, env, pins)
            if linked: _add_markers(top, sorted(linked), held, others, Path(temp), env, why)
            pins.recheck()
        # hook files (.onecrew/) are not part of the artifact. -f: a hook may rewrite one between the add and this rm, and without it git refuses to drop
        # a staged entry that differs from both the file and HEAD (the gate on c6d8477); only the throw-away index is touched.
        _git(top, 'rm', '-r', '--cached', '-f', '-q', '--ignore-unmatch', '--', '.onecrew', env=env)
        return _git(top, 'write-tree', env=env)


class InputRefused(LedgerError):
    """A verifier with declared inputs cannot start: what it would read cannot be established. The verifier was not called, so a new run may start."""
    verifier_started = False


class NoRoom(LedgerError):
    """The checkout would not fit. Refused before anything is written; the verifier was not called."""
    verifier_started = False

    def __init__(self, needed, free, where):
        self.needed, self.free, self.where = needed, free, str(where)
        super().__init__(f'The checkout for the verifier needs about {needed} bytes and {where} has {free} free. Nothing was written and the verifier was not called. '
                         'Free some space, point TEMP at another disk, or declare the inputs the command reads (verifier.config.inputs).')

    def structured(self):
        return {'no_room': {'needed_bytes': self.needed, 'free_bytes': self.free, 'where': self.where}, 'verifier_started': False, 'next': 'Free space or declare inputs, then run the same command again.'}


def scope_paths(inputs):
    """The declared inputs plus every .gitattributes above them: those decide how a file is cleaned and checked out, so a change there is a change of the input."""
    paths = set(inputs) | {'.gitattributes'}
    for item in inputs:
        parts = item.split('/')
        for depth in range(1, len(parts)):
            paths.add('/'.join(parts[:depth]) + '/.gitattributes')
    return sorted(paths)


def _load_scope(top, env, tree, paths):
    """The entries of `tree` under `paths` into the throw-away index. Returns the names."""
    rows = _git(top, 'ls-tree', '-r', '-z', '--full-tree', tree, '--', *paths, raw=True).split(b'\0')
    lines, names = [], set()
    for row in rows:
        if not row: continue
        head, name = row.split(b'\t', 1)
        mode, _, oid = head.split(b' ')
        lines.append(mode + b' ' + oid + b'\t' + name + b'\0'); names.add(name.decode('utf-8', 'surrogateescape'))
    if lines: _git(top, *NOSPARSE, 'update-index', '-z', '--index-info', env=env, input=b''.join(lines))
    return names


@_bounded
def scoped_tree(directory, inputs, verified=False):
    """artifact_sha for declared inputs only: a tree holding HEAD's entries for them, then the working files that are neither ignored nor committed, each pinned and judged on its
    handle exactly as artifact_sha does, so the same content gives the same ids. Nothing outside the inputs is listed, opened or hashed. With `verified` (a verifier) a hard link or a
    junction among them refuses, and an input with nothing in it refuses: it would be a check of nothing. Without it (a view) these change the identity instead."""
    top = str(Path(_git(directory, 'rev-parse', '--show-toplevel')).resolve())
    paths = scope_paths(inputs)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
        env = {'GIT_INDEX_FILE': str(Path(temp) / 'index'), 'GIT_LITERAL_PATHSPECS': '1'}
        _git(top, 'read-tree', '--empty', env=env)
        held = _load_scope(top, env, 'HEAD', paths)
        others = _listed(top, env, '--others', '--exclude-standard', '--', *paths)
        with _Pins(top) as pins:
            refused, gone = pins.pin(sorted(n for n in held | others if not _own(n)))
            if refused and verified: raise HardLinked(_refusal(*refused[0]))
            why = dict(refused)
            kept_out = _sparse_kept(top)
            _stage(top, env, sorted(pins.held), [n for n in gone if n in held and n not in kept_out])
            _repositories_for_files(top, env, pins)
            if why: _add_markers(top, sorted(why), held, others, Path(temp), env, why)
            pins.recheck()
        have = _listed(top, env, '--cached')
        if verified:
            empty = [i for i in inputs if not any(n == i or n.rstrip('/') == i or n.startswith(i + '/') for n in have)]
            if empty: raise InputRefused('Declared input not found, or everything in it is ignored by Git: ' + ', '.join(empty) + '. The verifier was not called: it would check nothing there.')
        return _git(top, 'write-tree', env=env)


def scoped_of_tree(directory, tree, inputs):
    """The part of an existing tree that `inputs` name, as a tree: what scoped_tree gave if the working files were that tree. Only ever a tree id reaches git."""
    if not TREE_ID.fullmatch(tree or ''): raise LedgerError('A tree id is 40 or 64 lowercase hex characters.')
    top = toplevel(directory)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
        env = {'GIT_INDEX_FILE': str(Path(temp) / 'index'), 'GIT_LITERAL_PATHSPECS': '1'}
        _git(top, 'read-tree', '--empty', env=env)
        _load_scope(top, env, tree, scope_paths(inputs))
        return _git(top, 'write-tree', env=env)


def _inside(name, inputs):
    return any(name == i or name.startswith(i + '/') for i in inputs)


def check_argv_scope(directory, argv, inputs):
    """A word of the command that names something in the repository must be inside the inputs. The checkout holds only those, so anything else would read as missing, or, by an
    absolute path, reach the live tree around the checkout. Not an analysis of the program: only what the command line itself names. Refused before the verifier is called."""
    top = Path(toplevel(directory)); here = Path(directory).resolve()
    for word in argv:
        for piece in {word, word.split('=', 1)[-1]}:
            if not piece or piece.startswith('-') or len(piece) > 500 or any(c in piece for c in '\r\n\t*?"<>|'): continue
            try:
                # review of dev24d (P1): `.`/`..` and a path that does not exist yet are normalised first (the longest existing parent resolved)
                full = real_path(piece if os.path.isabs(piece) else here / piece)
                if os.path.isabs(piece) and not _within(os.path.normcase(str(full)), os.path.normcase(str(top))): continue    # outside the repository
                if not os.path.isabs(piece) and not full.exists(): continue      # a relative name made later lands in the checkout, not the live tree
            except (OSError, ValueError, RuntimeError):
                continue
            if not _within(os.path.normcase(str(full)), os.path.normcase(str(top))):
                raise InputRefused(f'The command names {piece!r}, which is outside the repository. The verifier was not called.')
            name = full.relative_to(top).as_posix()
            if os.path.isabs(piece): raise InputRefused(f'The command names the live tree by an absolute path ({piece!r}): it would read or write past the checkout. Use a path relative to the working folder. The verifier was not called.')
            if name == '.' or not _inside(name, inputs):
                raise InputRefused(f'The command names {piece!r}, which is not among the declared inputs ({", ".join(inputs)}). Declare it, or remove the inputs to check the whole tree. The verifier was not called.')


def _short_name(path):
    """The 8.3 spelling of a folder on Windows (another way to write the same live tree), or None."""
    if os.name != 'nt': return None
    try:
        import ctypes
        size = ctypes.windll.kernel32.GetShortPathNameW(str(path), None, 0)
        if not size: return None
        buffer = ctypes.create_unicode_buffer(size)
        ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, size)
        return buffer.value if buffer.value and buffer.value.lower() != str(path).lower() else None
    except (OSError, AttributeError, ValueError):
        return None


def live_tree_pattern(top):
    """Every way a text is likely to spell the live tree: either slash, doubled in a string literal, a drive letter as `C:` or `/c`, `/mnt/c`, `/cygdrive/c`, the 8.3 name,
    any case on Windows. A match must end at a path separator or at a character no file name continues with: `.../mep` does not match `.../mep-old`."""
    sep = r'[\\/]+'
    spellings = []
    for spelled in {str(Path(top)), _short_name(top)} - {None}:
        parts = [p for p in re.split(r'[\\/]+', spelled) if p]
        if not parts: continue
        body = sep.join(re.escape(p) for p in parts[1:])
        drive = re.fullmatch(r'([A-Za-z]):', parts[0])
        if drive:                                          # C:\a\b, C:/a/b, C:\\a\\b, /c/a/b, /mnt/c/a/b, /cygdrive/c/a/b
            letter = re.escape(drive.group(1))
            spellings.append(rf'(?:{letter}:|/{letter}|/mnt/{letter}|/cygdrive/{letter})' + (sep + body if body else ''))
        elif spelled.startswith(('\\\\', '//')):          # \\server\share\a
            spellings.append(sep + re.escape(parts[0]) + (sep + body if body else ''))
        else:                                              # /home/a/b
            spellings.append(sep + re.escape(parts[0]) + (sep + body if body else ''))
    return re.compile(('(?:' + '|'.join(spellings) + r')(?![A-Za-z0-9_.\-~$])').encode(), re.I if os.name == 'nt' else 0)


SCAN_CHUNK = 1 << 20


def fold(name):
    """A repository-relative name as the file system compares it: `.`/`..` removed, `/` separators, case folded on Windows."""
    import posixpath
    text = posixpath.normpath(str(name).replace('\\', '/'))
    return text.lower() if os.name == 'nt' else text


def real_path(path):
    """review of dev24d (P1): a path as the system finds it, also when it does not exist yet: absolute, `.`/`..` removed, the longest existing parent
    resolved (links, junctions, 8.3 names) and the rest appended."""
    path = Path(os.path.abspath(path))
    rest = []
    while not path.exists() and path.parent != path:
        rest.insert(0, path.name)
        path = path.parent
    return Path(path.resolve(), *rest)


DOTTED = re.compile(rb'[\\/]\.{1,2}(?=[\\/]|$)')
CANDIDATE = re.compile(rb'(?:[A-Za-z]:|/mnt/[A-Za-z](?=[\\/])|/cygdrive/[A-Za-z](?=[\\/])|/[A-Za-z](?=[\\/])|(?<![A-Za-z0-9_.\-~$:])(?=[\\/]))[^\r\n"\'<>|*?\0`]*')


def _drive_form(text):
    """/mnt/c/a, /cygdrive/c/a and /c/a (a POSIX shell's way to write C:\\a) as C:/a."""
    match = re.match(r'^(?:/mnt|/cygdrive)?/([A-Za-z])(?=[\\/])(.*)$', text)
    return (match.group(1) + ':' + match.group(2)) if (match and os.name == 'nt') else text


def _dotted_live(data, top):
    """review of dev24d (P1): does this text spell the live tree with `.` or `..` in the path (D:\\work\\.\\repo, /home/a/x/../repo)? The literal
    pattern does not see those spellings; every absolute path written with a dot segment is normalised and compared by path components."""
    if not DOTTED.search(data): return False
    outer = os.path.normcase(os.path.normpath(str(top)))
    for line in data.splitlines():
        if not DOTTED.search(line): continue
        for found in CANDIDATE.finditer(line):
            text = found.group(0).decode('utf-8', 'replace').rstrip(' .,;:)]}')
            if not DOTTED.search(found.group(0)): continue
            text = _drive_form(text)
            if not os.path.isabs(text): continue
            seen = os.path.normcase(os.path.normpath(text))
            if _within(seen, outer) or (seen.startswith(outer) and not re.match(r'[A-Za-z0-9_.\-~$]', seen[len(outer):len(outer) + 1] or ' ')):
                return True
    return False


def _named_by_argv(argv, directory, top):
    """review of dev24d (P1): the repository-relative names the command line names (any spelling: `./`, `.`, `..`, case on Windows), folded."""
    here, named = Path(directory).resolve(), set()
    for word in argv:
        for piece in {word, word.split('=', 1)[-1]}:
            if not piece or piece.startswith('-') or len(piece) > 500: continue
            try:
                full = real_path(piece if os.path.isabs(piece) else here / piece)
            except (OSError, ValueError, RuntimeError):
                continue
            outer = os.path.normcase(str(Path(top).resolve()))
            seen = os.path.normcase(str(full))
            if _within(seen, outer): named.add('.' if seen == outer else fold(os.path.relpath(seen, outer)))      # `.`: the whole repository (dev24e)
    return named


def _relative_program(workspace, word, env):
    """review of dev24d (P2): a relative program with a folder exists in the working folder of the check (on Windows with a PATHEXT ending too)."""
    base = Path(workspace) / word
    if base.is_file(): return True
    if os.name == 'nt':
        endings = [e for e in ((env or {}).get('PATHEXT') or os.environ.get('PATHEXT') or '.COM;.EXE;.BAT;.CMD').split(os.pathsep) if e]
        return any(Path(str(base) + e).is_file() for e in endings)
    return False


def _names_live_tree(path, pattern, top=None):
    """Does this file's text spell the live tree? (True, False, or None for content that is not text: NUL bytes without a UTF-16 mark.)
    Review of dev24d (P1): a spelling with `.`/`..` segments too (_dotted_live)."""
    def spells(data):
        return bool(pattern.search(data)) or (top is not None and _dotted_live(data, top))
    with open(path, 'rb') as handle:
        head = handle.read(8000)
        if head.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            handle.seek(0)
            text = handle.read().decode('utf-16', 'replace').encode('utf-8', 'replace')
            return spells(text)
        if b'\0' in head: return None
        handle.seek(0)
        tail, keep = b'', 4096
        while True:
            block = handle.read(SCAN_CHUNK)
            if not block: return False
            if spells(tail + block): return True
            tail = (tail + block)[-keep:]


def check_live_tree_named(directory, argv, workspace_root, unscanned=()):
    """A verifier with declared inputs runs on a checkout of only those; its evidence later speaks only for them. A command line word, or a text file among the inputs,
    that spells the live tree by an absolute path would let the command read or write the real files beside the checkout: a pass that stays valid while what it read
    changes, or a write no snapshot sees. Refused before the verifier is called. This reads what the checkout holds; a path the program builds at run time from
    elsewhere (an environment variable, a file outside the repository) is not seen. Returns what was scanned, for the receipt.
    unscanned: inputs the owner's contract exempts from the text scan (mep4); never the command line, which is always checked. They are counted and listed."""
    top = toplevel(directory)
    pattern = live_tree_pattern(top)
    for word in argv:
        if isinstance(word, str) and (pattern.search(word.encode('utf-8', 'surrogateescape')) or _dotted_live(word.encode('utf-8', 'surrogateescape'), top)):
            raise InputRefused(f'The command names the live tree by an absolute path ({word!r}): it would read or write past the checkout of the declared inputs. The verifier was not called.')
    named = _named_by_argv(argv, directory, top)
    # review of dev24e (P1): an exemption equal to, under or above a path the command line names is dropped (a named folder runs what is inside it)
    unscanned = tuple(u for u in unscanned if not any(n == fold(u) or n.startswith(fold(u) + '/') or n == '.' or fold(u).startswith(n + '/') for n in named))
    scanned = {'files': 0, 'not_text': 0}
    skipped = 0
    root = Path(workspace_root)
    for folder, folders, files in os.walk(root):
        for item in files:
            path = Path(folder) / item
            if path.is_symlink(): continue
            if unscanned and _inside(fold(path.relative_to(root).as_posix()), [fold(u) for u in unscanned]):
                skipped += 1
                continue
            found = _names_live_tree(path, pattern, top)
            if found is None:
                scanned['not_text'] += 1
                continue
            scanned['files'] += 1
            if found:
                name = path.relative_to(root).as_posix()
                raise InputRefused(f'The declared input {name!r} spells the live tree by an absolute path ({top}). The command could read or write the real files beside the '
                                   'checkout, which the snapshot of the inputs does not see. Use a path relative to the working folder, or, when the command only reads '
                                   f'that text and never follows it, name it in the verifier\'s `inputs_unscanned` (e.g. "inputs_unscanned": [{json.dumps(name, ensure_ascii=False)}]): it stays an input, '
                                   'is not scanned, the owner approves the exemption with the contract and the receipt lists it; the command line is never exempt. '
                                   'Removing it from `inputs` leaves it out of the checkout. The verifier was not called.')
    if unscanned: scanned.update(unscanned=skipped, unscanned_paths=list(unscanned))
    return scanned


APPEXECLINK = 0x8000001B                               # IO_REPARSE_TAG_APPEXECLINK: a Windows app execution alias (…\WindowsApps\python.exe)


def parse_app_alias(data):
    """The program an app execution alias starts, from its reparse data (REPARSE_DATA_BUFFER, tag APPEXECLINK, version 3): the third of the
    NUL-terminated UTF-16 strings (package id, app id, program, app type). None when the data is not that."""
    if len(data) < 12: return None
    tag, length = int.from_bytes(data[0:4], 'little'), int.from_bytes(data[4:6], 'little')
    body = data[8:8 + length]
    if tag != APPEXECLINK or len(body) < 4 or int.from_bytes(body[0:4], 'little') != 3: return None
    strings = body[4:].decode('utf-16-le', 'replace').split('\0')
    program = strings[2] if len(strings) > 2 else ''
    return program if program and os.path.isabs(program) else None


def app_alias_target(path):
    """Windows: the program an app execution alias at `path` starts, or None when `path` is not one or its target cannot be read. The alias itself
    has no readable bytes (reading it raises EINVAL), so the program is read from the alias's reparse data."""
    if os.name != 'nt': return None
    try:
        if getattr(os.lstat(path), 'st_reparse_tag', 0) != APPEXECLINK: return None
    except OSError:
        return None
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.DeviceIoControl.restype = wintypes.BOOL
    kernel.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                       ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    # FILE_READ_ATTRIBUTES, share read|write|delete, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS: the alias, not what it starts
    handle = kernel.CreateFileW(str(path), 0x80, 0x7, None, 3, 0x00200000 | 0x02000000, None)
    if handle is None or handle == ctypes.c_void_p(-1).value: return None
    try:
        buffer, size = ctypes.create_string_buffer(16 * 1024), wintypes.DWORD()
        if not kernel.DeviceIoControl(handle, 0x000900A8, None, 0, buffer, len(buffer), ctypes.byref(size), None): return None    # FSCTL_GET_REPARSE_POINT
        return parse_app_alias(buffer.raw[:size.value])
    finally:
        kernel.CloseHandle(handle)


def is_bare_word(word):
    """A program named without any folder (`python`, `git`): found on a PATH."""
    return isinstance(word, str) and bool(word) and not os.path.isabs(word) and '/' not in word and '\\' not in word


class ProgramMissing(LedgerError):
    """review of dev24c: the program the command names does not exist (a bare name not on the verifier's PATH, or an absolute path that is gone).
    Nothing was started: refused before the verifier, the run is not held."""
    verifier_started = False


def _which(word, env):
    """review of dev24c (P2): a bare name looked up on the PATH of `env` only. Not shutil.which: on Windows before Python 3.12 it also looks in the
    current folder of the OneCrew process. Windows tries the PATHEXT endings (the name as written first when it already has one of them)."""
    path = (env or {}).get('PATH') or ''
    if os.name == 'nt':
        endings = [e for e in ((env or {}).get('PATHEXT') or os.environ.get('PATHEXT') or '.COM;.EXE;.BAT;.CMD').split(os.pathsep) if e]
        names = ([word] if any(word.lower().endswith(e.lower()) for e in endings) else []) + [word + e for e in endings]
    else:
        names = [word]
    for folder in path.split(os.pathsep):
        if not folder or not os.path.isabs(folder): continue
        for name in names:
            candidate = os.path.join(folder, name)
            if app_alias_target(candidate): return candidate                  # an app execution alias has no readable bytes, but it starts a program
            if os.path.isfile(candidate) and (os.name == 'nt' or os.access(candidate, os.X_OK)): return candidate
    return None


def program_path(word, env):
    """review of dev24b (P1-a): the program a bare word names, looked up ONCE on the PATH of the verifier's own environment. Windows CreateProcess
    does not search the PATH of the environment a child is given (it searches the parent's folder and the parent's PATH), so the command is started
    by this path, and the receipt fingerprints the same file. An absolute word is itself; a word with a folder is left to the command."""
    if os.path.isabs(word): return word
    if not is_bare_word(word): return None
    return _which(word, env)


def _target(invoked):
    """The file a started path runs: the program of an app execution alias, else the path with every link resolved (file and folder links)."""
    alias = app_alias_target(invoked)
    return (Path(alias) if alias else Path(invoked).resolve()), alias


def tool_identity(word, env, found=None):
    """The program the command starts, by its bytes (review of dev24c: every command receipt, with or without inputs).
    - `invoked`: the path the process is started with, as found (links NOT resolved: a POSIX venv's bin/python is a link that belongs to the venv);
    - `path`: the file it runs (links resolved, or the program of a Windows app execution alias, `alias` keeping the alias); its sha256;
    - `environment`: for a Python interpreter, its installed packages, found from the invoked path the way Python finds them (python_environment).
    A program inside the inputs (a word with a folder) is in the tree already. A program whose bytes cannot be read is recorded with `sha256: None`
    and the reason; `tool_changed` then never lets a pass carry over."""
    if not os.path.isabs(word) and ('/' in word or '\\' in word): return {'word': word, 'in_inputs': True}
    found = found or program_path(word, env)
    if not found or not (Path(found).is_file() or app_alias_target(found)): return {'word': word, 'invoked': found, 'path': None, 'sha256': None}
    program, alias = _target(found)
    identity = {'word': word, 'invoked': os.path.abspath(found), 'path': str(program)}
    if alias: identity['alias'] = os.path.abspath(found)
    try:
        identity['sha256'] = _cached_digest(program)[1]
    except OSError as error:
        identity.update(sha256=None, unreadable=f'{type(error).__name__}: {error}'[:200])
    try:
        identity['environment'] = python_environment(found, program)
    except OSError as error:
        identity['environment'] = {'unreadable': f'{type(error).__name__}: {error}'[:200]}
    return identity


# review of dev24b/c (P2): hard caps on what a fingerprint reads, counted while walking (every entry, folders too), never after listing a whole tree
ENV_FILES_MAX, ENV_BYTES_MAX, META_FILE_MAX = 20000, 512 * 1024 * 1024, 16 * 1024 * 1024


class _ReadCap:
    """Entries and bytes a fingerprint reads, counted as they are met. Over a cap: refused, before the verifier (InputRefused)."""
    def __init__(self, what):
        self.what, self.files, self.bytes = what, 0, 0

    def add(self, size):
        self.files += 1
        self.bytes += size
        if self.files > ENV_FILES_MAX or self.bytes > ENV_BYTES_MAX:
            raise InputRefused(f'{self.what} is too large to fingerprint: more than {ENV_FILES_MAX} entries or {ENV_BYTES_MAX // (1024 * 1024)} MB. '
                               'Declare a smaller folder. The verifier was not called.')
        _tick('fingerprinting ' + self.what)


_DIGESTS, DIGESTS_MAX = {}, 50000


def _stat_key(path):
    st = os.stat(path)
    return (os.path.normcase(os.path.abspath(path)), st.st_size, st.st_mtime_ns, getattr(st, 'st_ino', 0)), st.st_size


def _cached_digest(path, cap=None):
    """review of dev24d (P2): (size, sha256) of a file, remembered by its path, size, time of change (ns) and file id, so a view polled again does
    not read unchanged bytes again. A file rewritten with the same size and the same time of change to the nanosecond is taken as unchanged.
    `cap`: refuse a larger file (InputRefused) before reading it."""
    key, size = _stat_key(path)
    if cap is not None and size > cap:
        raise InputRefused(f'{path} is larger than {cap // (1024 * 1024)} MB: it cannot be fingerprinted. The verifier was not called.')
    if key not in _DIGESTS:
        digest, read = hashlib.sha256(), 0
        with open(path, 'rb') as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b''):
                read += len(block)
                if cap is not None and read > cap:
                    raise InputRefused(f'{path} is larger than {cap // (1024 * 1024)} MB: it cannot be fingerprinted. The verifier was not called.')
                digest.update(block)
        if len(_DIGESTS) >= DIGESTS_MAX: _DIGESTS.clear()
        _DIGESTS[key] = (read, digest.hexdigest())
    return _DIGESTS[key]


def _meta(path, budget):
    """The sha256 of one metadata file (RECORD, .pth, pyvenv.cfg), at most META_FILE_MAX, counted in the budget."""
    size, sha = _cached_digest(path, META_FILE_MAX)
    budget.add(size)
    return sha


def _read_capped(path, budget):
    """The bytes of one metadata file (RECORD, .pth, pyvenv.cfg), at most META_FILE_MAX, read in blocks."""
    parts, size = [], 0
    with open(path, 'rb') as handle:
        while True:
            block = handle.read(64 * 1024)
            if not block: break
            size += len(block)
            if size > META_FILE_MAX:
                raise InputRefused(f'{path} is larger than {META_FILE_MAX // (1024 * 1024)} MB: the Python environment cannot be fingerprinted. The verifier was not called.')
            parts.append(block)
    budget.add(size)
    return b''.join(parts)


def _entries(folder, budget):
    """The entries of one folder, each counted before anything is sorted."""
    out = []
    with os.scandir(folder) as found:
        for entry in found:
            budget.add(0)
            out.append(Path(entry.path))
    return sorted(out, key=lambda p: p.name.lower())


def _venv_cfg(invoked):
    for root in (Path(invoked).parent, Path(invoked).parent.parent):
        if (root / 'pyvenv.cfg').is_file(): return root / 'pyvenv.cfg'
    return None


def _site_packages(invoked, target, budget):
    """The site-packages folders of a Python interpreter, found on disk only (no subprocess), the way Python finds its prefix (review of dev24c, P1):
    pyvenv.cfg next to the path it was STARTED with (a POSIX venv's bin/python is a link into the base installation, and still the venv's) makes it a
    venv: its own Lib/site-packages or lib/python3*/site-packages, plus the base installation's (`home`) when include-system-site-packages = true.
    Without pyvenv.cfg the prefix is found from the program the links resolve to. Every folder looked at is counted (budget)."""
    cfg = _venv_cfg(invoked)
    base = Path(invoked) if cfg is not None else Path(target)
    roots, found = [base.parent, base.parent.parent], []
    if cfg is not None:
        text = _read_capped(cfg, budget).decode('utf-8', 'replace')
        pairs = {l.split('=', 1)[0].strip().lower(): l.split('=', 1)[1].strip() for l in text.splitlines() if '=' in l}
        if pairs.get('include-system-site-packages', '').lower() == 'true' and pairs.get('home'):
            roots += [Path(pairs['home']), Path(pairs['home']).parent]
    for root in roots:
        candidates = [root / 'Lib' / 'site-packages']
        lib = root / 'lib'
        if lib.is_dir():
            candidates += [p / 'site-packages' for p in _entries(lib, budget) if p.name.lower().startswith('python3')]
        for candidate in candidates:
            if candidate.is_dir() and candidate.resolve() not in [f.resolve() for f in found]: found.append(candidate)
    return found, cfg


def python_environment(invoked, target=None):
    """2.5.0.dev24 (review of dev24, P1): what a Python interpreter loads beyond its own exe, read from disk only: every installed distribution
    (its dist-info folder name, which holds the version, and the sha256 of its RECORD), every .pth file and pyvenv.cfg. None when the program is not a
    Python interpreter (by the name it is started with or the file it runs). Review of dev24b/c: under the same caps as env_inputs, counted while
    reading (folders too); one RECORD, .pth or pyvenv.cfg at most META_FILE_MAX."""
    target = Path(target) if target is not None else Path(invoked).resolve()
    if not (Path(invoked).name.lower().startswith('python') or target.name.lower().startswith('python')): return None
    budget = _ReadCap('the Python environment of ' + str(invoked))
    folders, cfg = _site_packages(invoked, target, budget)
    digest, count = hashlib.sha256(), 0
    if cfg is not None: digest.update(b'cfg:' + _meta(cfg, budget).encode('ascii'))
    for folder in folders:
        digest.update(b'site:' + str(folder.resolve()).encode('utf-8', 'surrogateescape'))
        for entry in _entries(folder, budget):
            if entry.name.endswith('.dist-info') or entry.name.endswith('.egg-info'):
                record = entry / 'RECORD'
                sha = _meta(record, budget) if record.is_file() else hashlib.sha256(b'').hexdigest()
                digest.update(b'dist:' + entry.name.encode('utf-8', 'surrogateescape') + b':' + sha.encode('ascii'))
                count += 1
            elif entry.suffix == '.pth' and entry.is_file():
                digest.update(b'pth:' + entry.name.encode('utf-8', 'surrogateescape') + b':' + _meta(entry, budget).encode('ascii'))
    return {'site_packages': [str(f) for f in folders], 'distributions': count, 'sha256': digest.hexdigest()}


def _place(path):
    """A path as the system finds it: resolved (links, junctions, `..`), case folded on Windows."""
    return os.path.normcase(str(Path(path).resolve()))


def _within(inner, outer):
    """`inner` is `outer` or inside it, by whole path components (C:\\repo-tools is not inside C:\\repo)."""
    return inner == outer or inner.startswith(outer.rstrip(os.sep) + os.sep)


_TOPS = {}


def project_top(directory):
    """review of dev24c (P2): the folder a verifier must not take programs or env_inputs from: the Git repository the project is in (its toplevel),
    else the project folder. The same at propose, at the run and at the check of a receipt."""
    key = str(Path(directory).resolve())
    if key not in _TOPS:
        try:
            _TOPS[key] = str(toplevel(key))            # only a found repository is remembered: a folder may become one later
        except (LedgerError, OSError, subprocess.SubprocessError):
            return key
    return _TOPS[key]


def env_inputs_inside(paths, repo):
    """review of dev24b (P2): the first declared env_input that is the repository, inside it or holding it, after resolving (`..`, case, junction).
    Such a file belongs in `inputs`: at accept it must be judged in the accepted tree, not on the live disk."""
    top = _place(project_top(repo))
    for path in paths or ():
        place = _place(path)
        if _within(place, top) or _within(top, place): return path
    return None


def env_inputs_twice(paths):
    """review of dev24c (P2): two declared env_inputs that resolve to one place (links, junctions, `..`, case): the second one, else None."""
    seen = set()
    for path in paths or ():
        place = _place(path)
        if place in seen: return path
        seen.add(place)
    return None


def _walk(root, budget):
    """Every entry under `root`, counted as it is met (folders too). A link (symlink, junction) is not followed: it is recorded by where it points.
    (relative name, kind, path or target) rows, kind 'file', 'dir' or 'link'."""
    out, stack = [], [root]
    while stack:
        folder = stack.pop()
        with os.scandir(folder) as found:
            for entry in found:
                rel = os.path.relpath(entry.path, root).replace(os.sep, '/')
                linked = entry.is_symlink() or getattr(entry, 'is_junction', lambda: False)()
                if linked:
                    budget.add(0)
                    try:
                        out.append((rel, 'link', os.readlink(entry.path)))
                    except OSError:
                        out.append((rel, 'link', ''))
                elif entry.is_dir(follow_symlinks=False):
                    budget.add(0)
                    out.append((rel, 'dir', ''))
                    stack.append(entry.path)
                elif entry.is_file(follow_symlinks=False):
                    budget.add(entry.stat(follow_symlinks=False).st_size)
                    out.append((rel, 'file', entry.path))
    return out


def _file_sha(path):
    return _cached_digest(path)[1]


def env_inputs_identity(paths, repo=None):
    """2.5.0.dev24 (review of dev24, P1): the bytes of the owner-declared paths outside the repository (a file, or every entry under a folder), one
    sha256 each. Review of dev24b/c: a missing or unreadable path, a path inside the repository (or holding it), two names of one place, or more than
    the caps is refused (InputRefused: before the verifier, and at show/accept the pass is not carried). Inside a folder, a sub-folder's name and a
    link's target are part of the fingerprint; what a link points to is not read."""
    out, seen, budget = {}, {}, _ReadCap('env_inputs')
    top = _place(project_top(repo)) if repo is not None else None
    for path in paths or ():
        try:
            real = Path(path).resolve(strict=True)
        except OSError as error:
            raise InputRefused(f'The declared env_input {path} is missing or cannot be read ({type(error).__name__}). The verifier was not called.')
        place = os.path.normcase(str(real))
        if place in seen: raise InputRefused(f'The declared env_inputs {seen[place]} and {path} are the same place. The verifier was not called.')
        seen[place] = path
        if top is not None and (_within(place, top) or _within(top, place)):
            raise InputRefused(f'The declared env_input {path} is inside the repository (or holds it): declare it in inputs. The verifier was not called.')
        digest = hashlib.sha256()
        try:
            if real.is_file():
                budget.add(real.stat().st_size)
                rows = [(real.name, 'file', str(real))]
            elif real.is_dir():
                rows = sorted(_walk(str(real), budget), key=lambda row: row[0].lower())
            else:
                raise InputRefused(f'The declared env_input {path} is neither a file nor a folder. The verifier was not called.')
            for rel, kind, value in rows:
                _tick('fingerprinting env_inputs')
                body = _file_sha(value) if kind == 'file' else value
                digest.update(kind.encode('ascii') + b':' + rel.encode('utf-8', 'surrogateescape') + b':' + body.encode('utf-8', 'surrogateescape') + b'\n')
        except OSError as error:
            raise InputRefused(f'The declared env_input {path} cannot be read ({type(error).__name__}: {error})'[:300] + '. The verifier was not called.')
        out[path] = digest.hexdigest()
    return out


def tool_changed(tool, env=None):
    """Whether the program a receipt names would not be the one the command starts now, or has other bytes or another Python environment
    (mep7 hole (b); review of dev24c, P1): the invoked path is looked up again (a bare word on the PATH, an absolute one as written), the file it runs
    is resolved again (file and folder links, an app execution alias), and both are compared with the receipt, then the bytes and the environment.
    A receipt made before the invoked path was recorded, or whose environment could not be read, is a change."""
    if not isinstance(tool, dict) or tool.get('in_inputs'): return False
    if not tool.get('path') or 'invoked' not in tool or 'environment' not in tool: return True
    if isinstance(tool['environment'], dict) and 'unreadable' in tool['environment']: return True     # an environment never read proves nothing
    word = tool.get('word')
    invoked = _which(word, env if env is not None else os.environ) if is_bare_word(word) else word
    if not invoked or os.path.normcase(os.path.abspath(invoked)) != os.path.normcase(tool['invoked']): return True
    try:
        program, alias = _target(invoked)
        if os.path.normcase(str(program)) != os.path.normcase(tool['path']): return True
        if bool(alias) != bool(tool.get('alias')): return True
        if _cached_digest(program)[1] != tool.get('sha256'): return True
        now = python_environment(invoked, program)
    except (OSError, LedgerError):                     # unreadable, or over a cap (dev24b): never a carried pass
        return True
    return (now or {}).get('sha256') != (tool['environment'] or {}).get('sha256')


def program_reasons(body, project, declared=None, env_from=None):
    """review of dev24c (P1, owner 11/11 "Sửa cả lỗi cũ"): why a command receipt no longer speaks for the program it ran, its Python environment
    or its declared env_inputs; [] when it still does. The one program rule every place that judges command evidence applies (plan show, owner
    accept, the reuse of a retained proof). A receipt this runtime wrote always names its program; one under this checkout policy that does not is
    not current. The verifier environment is made the way the run made it: from its cwd, or `env_from` (a candidate check ran in a scratch checkout
    with the project's environment); the PATH without the project's repository."""
    if not isinstance(body, dict) or body.get('kind') != 'command-receipt': return []
    program = body.get('program')
    if program is None:
        if body.get('checkout_policy') == CHECKOUT_POLICY: return ['the receipt does not name the program it ran: run the milestone again']
        return []                                      # a receipt of another policy: judged by the policy rule and the policy epoch
    reasons = []
    # review of dev24d: the lookup environment is made once per receipt, and only for a bare word (an absolute program needs none)
    env = verifier_env(Path(env_from or body.get('cwd') or project)) if is_bare_word(program.get('word')) else {}
    if declared is None: declared = list(body.get('env_inputs') or {})          # what the run declared, as it recorded it
    if tool_changed(program, env):
        reasons.append('the program the command starts, or its Python packages, changed: ' + str(program.get('invoked') or program.get('word')))
    if declared:
        try:
            now = env_inputs_identity(declared, project)
        except (LedgerError, OSError) as error:
            reasons.append('env_inputs: ' + str(error)[:300])
        else:
            if now != body.get('env_inputs'): reasons.append('a declared input outside the repository changed (env_inputs)')
    return reasons


def _tree_size(directory, tree):
    """(files, bytes) of a tree, from the object headers; nothing is read into memory or written."""
    files = total = 0
    for row in _git(toplevel(directory), 'ls-tree', '-r', '-l', '-z', tree, raw=True).split(b'\0'):
        if not row: continue
        size = row.split(b'\t', 1)[0].split()[-1]
        files += 1
        if size.isdigit(): total += int(size)
    return files, total


ROOM_MARGIN = 64 * 1024 * 1024


def _check_room(directory, tree, destination):
    """Before the checkout starts: a tree that cannot fit is refused with the numbers instead of failing part way."""
    files, total = _tree_size(directory, tree)
    free = shutil.disk_usage(destination).free
    if free < total + total // 10 + ROOM_MARGIN: raise NoRoom(total + total // 10 + ROOM_MARGIN, free, destination)
    return files, total


SCRATCH_PREFIX = 'ocv-'
SCRATCH_OWNER = 'owner.json'


def _host():
    """This machine's name; os.uname does not exist on Windows, so a missing COMPUTERNAME must not break the run."""
    import platform
    return os.environ.get('COMPUTERNAME') or platform.node()


def _own_scratch(scratch):
    Path(scratch, SCRATCH_OWNER).write_text(json.dumps({'pid': os.getpid(), 'host': _host()}), encoding='utf-8')


def _remove_scratch(scratch):
    """Remove a scratch folder, also names beyond MAX_PATH and read-only files. A plain rmtree(ignore_errors=True) leaves those silently, and the owner
    mark, a short name, goes first, so no later sweep ever finds the folder (seen on Windows: a checkout of 646 long names, 65 MB, left by each run).
    Whatever still cannot be removed is marked again, so the next run's sweep tries it once this process is gone."""
    def again(func, path, _):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except OSError:
            pass
    target = _long(scratch)
    if sys.version_info >= (3, 12): shutil.rmtree(target, onexc=again)
    else: shutil.rmtree(target, onerror=again)
    if os.path.lexists(target):
        try:
            _own_scratch(target)
        except OSError:
            pass
    return not os.path.lexists(target)


def _sweep_scratch():
    """Scratch folders a killed run left behind. Only a folder that carries the owner mark of a process that is gone on this machine; nothing else in the temp folder is touched."""
    from .. import verdict
    try:
        names = list(Path(tempfile.gettempdir()).glob(SCRATCH_PREFIX + '*'))
    except OSError:
        return
    for folder in names:
        try:
            owner = json.loads((folder / SCRATCH_OWNER).read_text(encoding='utf-8'))
            if owner.get('host') == (_host()) and owner.get('pid') != os.getpid() and not verdict.process_alive(owner.get('pid')):
                _remove_scratch(folder)
        except (OSError, ValueError, AttributeError):
            continue


def _refusal(name, why):
    if why == HELD_OPEN:
        return f'{name!r} {why}. Close that program, or wait until it is done with the file, and try again.'
    return (f'{name!r} {why}: the other name or place may be a control or credential file (.env, .ssh), whose content would be read under this one. '
            'Replace it with a copy, or move it out of the working tree, and try again.')


def _own(name):
    """OneCrew's own files (hooks, the active plan): never part of a tree (they are dropped from it at the end), so they are not held while git reads:
    OneCrew's writer replaces them meanwhile (review of 3c1687a, finding 4)."""
    return name.rstrip('/') == '.onecrew' or name.startswith('.onecrew/')


def _listed(top, env, *args):
    return {n for n in _git(top, 'ls-files', '-z', *args, env=env, raw=True).decode('utf-8', 'surrogateescape').split('\0') if n}


def _sparse_kept(top):
    """The names the real index keeps outside a sparse checkout (skip-worktree): absent on purpose, kept as HEAD holds them (review B2 round 3)."""
    rows = _git(top, 'ls-files', '-t', '-z', raw=True).decode('utf-8', 'surrogateescape').split('\0')
    return {row[2:] for row in rows if row.startswith('S ')}


def _stage(top, env, present, gone):
    """Drop `gone` from the throw-away index, then hash `present` into it: `git update-index` with exactly these names, so nothing else of the working
    tree is read (a name made after the listing is not taken). In that order, sorted, and with --remove and --replace, a file that became a folder or a
    folder that became a file takes its new place as with `git add -A` / `add -u` (review of 3c1687a, finding 2): the gone file under a folder that is
    now a file is dropped first; a folder that was a file (not a nested repository) is dropped before the files in it are added."""
    enc = lambda n: n.rstrip('/').encode('utf-8', 'surrogateescape') + b'\0'
    if gone: _git(top, *NOSPARSE, 'update-index', '--force-remove', '-z', '--stdin', env=env, input=b''.join(enc(n) for n in gone))
    if present: _git(top, *NOSPARSE, 'update-index', '--add', '--remove', '--replace', '-z', '--stdin', env=env,
                     input=b''.join(enc(n) for n in sorted(present, key=lambda n: n.rstrip('/'))))


def _repositories_for_files(top, env, pins):
    """A tracked file that is now a nested repository: `update-index --remove` dropped the file (the listing ran against an index that still held
    it, so the folder was never listed as untracked); the repository's commit takes its place, as `git add -A` and `add -u` record it (review of
    570c64e, finding 1). Only where git sees a repository, as it decides: a HEAD that resolves through that folder's own .git, and no file under
    the folder taken already; a broken gitfile, an empty .git or a repository without a commit is a plain folder, as for git (review of 1cf3112).
    The folder stays pinned; git reads only its HEAD, no content."""
    folders = [name for name, kind in pins.kinds.items() if kind == 'folder']
    if not folders: return
    staged = _listed(top, env, '--cached')
    repositories = [n for n in folders if n.rstrip('/') not in staged and not any(s.startswith(n.rstrip('/') + '/') for s in staged)
                    and _repository(Path(top).joinpath(*n.rstrip('/').split('/')))]
    if repositories:
        _git(top, *NOSPARSE, 'update-index', '--add', '-z', '--stdin', env=env,
             input=b''.join(n.rstrip('/').encode('utf-8', 'surrogateescape') + b'\0' for n in sorted(repositories)))


def _repository(folder):
    """Whether git takes `folder` for a nested repository: its own .git (a folder or a gitfile) with a HEAD that resolves to a commit. --git-dir, so
    that git never looks upwards into the project's repository."""
    if _lstat(folder / '.git') is None: return False
    try:
        _git(folder, '--git-dir', str(folder / '.git'), 'rev-parse', '--verify', '-q', 'HEAD^{commit}')
    except LedgerError:
        return False
    return True


class _Pins:
    """The names git is about to read, each opened and judged on its handle and held until git has read them (P1 of the review of beta dev9): regular
    files, and links and folders (a nested repository, a file that became a folder), whose content git does not read but whose name could otherwise
    become a hard link before git looks at it (review of 3c1687a, finding 1). pin(names) -> (refused [(name, reason)], gone [names]); the names held
    are self.held. On Windows a raw handle (no C-runtime descriptor limit) keeps each name, and every folder above it, from being renamed, deleted or
    replaced until it is closed. POSIX cannot keep a name: each file is judged on a descriptor that is closed at once (one open descriptor per file
    ran into the open-file limit, finding 3), and recheck() makes sure each name still leads to what was judged (a recorded limit: git may have read
    the new one first)."""

    def __init__(self, top):
        self.top, self.held, self.folders, self.kinds = Path(top), {}, {}, {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        for handle, _ in self.held.values():
            if handle is not None: _close(handle)
        self.held.clear(); self.kinds.clear()

    def pin(self, names):
        refused, gone = [], []
        for name in names:
            _tick('opening the files')
            path = self.top.joinpath(*name.rstrip('/').split('/'))
            if self._beyond_link(name):
                gone.append(name); continue
            try:
                status = _lstat(path)
            except (OSError, ValueError):
                refused.append((name, 'cannot be examined')); continue
            if status is None:
                gone.append(name); continue
            kind = 'link' if stat.S_ISLNK(status.st_mode) else 'folder' if stat.S_ISDIR(status.st_mode) else 'file'
            try:
                self.held[name] = _open_judged(path, kind, status)
                self.kinds[name] = kind
            except FileNotFoundError:
                gone.append(name)
            except LedgerError as error:
                refused.append((name, str(error)))
            except OSError as error:
                refused.append((name, HELD_OPEN if getattr(error, 'winerror', None) == 32 else f'cannot be opened ({error.__class__.__name__})'))
        return refused, gone

    def _beyond_link(self, name):
        """A folder on the way to `name` is a link: git stores that link and drops every name behind it, so the name is gone here too and nothing
        behind the link is opened (E-R02; the pins had broken it, the affected regression of 3c1687a). A junction is not a link here: git walks into
        it, and the final path of the handle refuses the name."""
        parts = name.rstrip('/').split('/')
        for depth in range(1, len(parts)):
            folder = '/'.join(parts[:depth])
            if folder not in self.folders:
                try:
                    status = _lstat(self.top.joinpath(*parts[:depth]))
                except (OSError, ValueError):
                    status = None
                self.folders[folder] = status is not None and stat.S_ISLNK(status.st_mode)
            if self.folders[folder]: return True
        return False

    def recheck(self):
        if os.name == 'nt': return                              # the open handles kept every name in place
        for name, (_, facts) in self.held.items():
            now = _lstat(self.top.joinpath(*name.rstrip('/').split('/')))
            if now is None or (now.st_dev, now.st_ino, stat.S_IFMT(now.st_mode)) != facts:
                raise HardLinked(_refusal(name, 'was replaced while git read it'))


# A Windows sharing violation: another program holds the file open with delete access (it may rename or delete it), so it cannot be pinned (review
# of 3c1687a, finding 5). It is tried three times over 0.2 s, then not read.
HELD_OPEN = 'is held open by another program that may rename or delete it, so it cannot be kept in place while git reads it'


def _long(path):
    text = os.path.abspath(str(path))
    if os.name != 'nt' or text.startswith('\\\\?\\'): return text
    return '\\\\?\\UNC\\' + text[2:] if text.startswith('\\\\') else '\\\\?\\' + text


def _open_judged(path, kind='file', status=None):
    """(handle, facts) of `path`, judged on a handle: a regular file has one name on the disk, a link is still a link, a folder still a plain folder,
    and the final path of each is `path` (no junction on the way). On Windows the handle is returned open: it is the pin. Elsewhere no descriptor stays
    open and facts are (dev, ino, type) for recheck(). LedgerError when the judgment fails."""
    if os.name == 'nt':
        import _winapi
        flags = {'file': 0, 'link': 0x02000000 | 0x00200000, 'folder': 0x02000000}[kind]    # BACKUP_SEMANTICS (a folder); OPEN_REPARSE_POINT (the link)
        for attempt in range(3):
            try:
                handle = _winapi.CreateFile(_long(path), 0x80000000, 0x1 | 0x2, 0, 3, flags, 0)    # GENERIC_READ; share read and write, never delete
                break
            except OSError as error:
                if getattr(error, 'winerror', None) != 32 or attempt == 2: raise
                time.sleep(0.1)
        try:
            _judge_windows(handle, path, kind)
        except BaseException:
            _winapi.CloseHandle(handle)
            raise
        return handle, None
    if kind != 'file':
        return None, (status.st_dev, status.st_ino, stat.S_IFMT(status.st_mode))
    fd = os.open(str(path), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        check_alone(fd, path, repr(str(path)))
        now = os.fstat(fd)
    finally:
        os.close(fd)
    return None, (now.st_dev, now.st_ino, stat.S_IFREG)


def _judge_windows(handle, path, kind='file'):
    import ctypes
    from ctypes import wintypes

    class Info(ctypes.Structure):
        _fields_ = [('attributes', wintypes.DWORD), ('created', wintypes.FILETIME), ('accessed', wintypes.FILETIME), ('written', wintypes.FILETIME),
                    ('volume', wintypes.DWORD), ('size_high', wintypes.DWORD), ('size_low', wintypes.DWORD), ('links', wintypes.DWORD),
                    ('index_high', wintypes.DWORD), ('index_low', wintypes.DWORD)]
    info = Info()
    if not ctypes.windll.kernel32.GetFileInformationByHandle(ctypes.c_void_p(handle), ctypes.byref(info)):
        raise LedgerError('cannot be examined')
    folder, reparse = info.attributes & 0x10, info.attributes & 0x400       # FILE_ATTRIBUTE_DIRECTORY, FILE_ATTRIBUTE_REPARSE_POINT
    if kind == 'link':
        if not reparse: raise LedgerError('is no longer a link')
    elif kind == 'folder':
        if not folder or reparse: raise LedgerError('is no longer a plain folder')
    elif folder:
        raise LedgerError('is not a regular file')
    elif info.links > 1:
        raise LedgerError('has more than one name on the disk (a hard link)')
    buffer = ctypes.create_unicode_buffer(32768)
    size = ctypes.windll.kernel32.GetFinalPathNameByHandleW(ctypes.c_void_p(handle), buffer, 32768, 0)
    final = buffer.value if 0 < size < 32768 else None
    if final and final.startswith('\\\\?\\UNC\\'): final = '\\\\' + final[8:]
    elif final and final.startswith('\\\\?\\'): final = final[4:]
    if final is None or os.path.normcase(final) != os.path.normcase(os.path.abspath(str(path))):
        raise LedgerError(f'is reached through a link or junction ({final or "its final path cannot be told"})')


def _close(handle):
    if os.name == 'nt':
        import _winapi
        _winapi.CloseHandle(handle)
    else:
        os.close(handle)


class HardLinked(LedgerError):
    """A working-tree name that a verifier's tree would take is a hard link, is reached through a junction, or cannot be examined (refuse_hard_links)."""


JUNCTION = 0xA0000003                                  # IO_REPARSE_TAG_MOUNT_POINT: a folder git walks into, wherever it leads


def _lstat(path):
    """os.lstat of a working-tree name; None when the name is gone. On Windows a name that fails is tried again through the \\\\?\\ prefix, so that a
    path beyond MAX_PATH (the default LongPathsEnabled=0 with a repository's core.longpaths) is examined, not skipped (review E-R04); any other
    failure is raised to the caller, which refuses the name."""
    text = str(path)
    try:
        return os.lstat(text)
    except NotADirectoryError:
        return None                                     # a folder on the way is a file now (POSIX): the name is gone
    except FileNotFoundError:
        if os.name != 'nt' or text.startswith('\\\\?\\'): return None
    except OSError:
        if os.name != 'nt' or text.startswith('\\\\?\\'): raise
    full = os.path.abspath(text)
    try:
        return os.lstat('\\\\?\\UNC\\' + full[2:] if full.startswith('\\\\') else '\\\\?\\' + full)
    except FileNotFoundError:
        return None


def _is_junction(path):
    """A folder git walks into although its content is elsewhere: a junction. A directory symlink is not one: git stores it as a link and hashes
    nothing behind it (review E-R02). By the reparse tag, so with any Python (Path.is_junction needs 3.12); a cloud placeholder is not one either."""
    status = _lstat(path)
    return status is not None and getattr(status, 'st_reparse_tag', 0) == JUNCTION


def _through(top, name):
    """The first folder on the way to `name` that is a junction, or None."""
    parts = name.split('/')
    return next((f for f in ('/'.join(parts[:n]) for n in range(1, len(parts))) if _is_junction(top / f)), None)


# A sparse checkout clears skip-worktree on a file that is on disk unless told it may be there (review B2 P1); turning sparse checkout off instead
# makes `add -A` drop every absent file outside the cone (review B2 round 3, P2). Git 2.42+.
NOSPARSE = ('-c', 'sparse.expectFilesOutsideOfPatterns=true', '-c', 'index.sparse=false')


def _add_markers(top, linked, held, others, temp, env, why=None):
    """A marker blob at each name of `linked` that the tree would hold (HEAD holds it, or it is an untracked file that is not ignored): what os.lstat
    says of it, never its bytes (2.3 beta B2). A name git would not take gets none: the tree never held it. A name that is gone gets none either: it is
    dropped from the index, as `git add -A` drops it, unless the real index keeps it outside a sparse checkout. Every marker must be in the index
    afterwards, or the identity is refused (review B2 P3-2). A name `why` says another program holds open says so in its marker (review of 3c1687a,
    finding 5)."""
    top = Path(top)
    enc = lambda n: n.encode('utf-8', 'surrogateescape')
    marks, gone = [], []
    for name in linked:
        plain = name.rstrip('/')                       # a nested repository is listed as a folder with its slash
        if plain not in held and name not in others and plain not in others: continue
        try:
            status, failed = _lstat(top / plain), False
        except (OSError, ValueError):
            status, failed = None, True
        if status is None and not failed:
            if plain in held: gone.append(plain)
            continue
        marks.append((plain, status))
    # a tracked file that became a junction: git walks into it, so the files behind it are marked and the name itself is dropped, as git drops a
    # file that became a folder; a marker at both names is a pair git refuses (review of 570c64e, finding 2)
    inner = {name for name, _ in marks if any(other.startswith(name + '/') for other, _ in marks)}
    gone += [name for name in inner if name in held]
    marks = [(name, status) for name, status in marks if name not in inner]
    gone = [n for n in gone if n not in _sparse_kept(top)]
    if gone: _stage(top, env, [], gone)
    if not marks: return
    files = []
    for number, (name, status) in enumerate(marks):
        reason = 'held open by another program' if HELD_OPEN in ((why or {}).get(name), (why or {}).get(name + '/')) else 'another name on the disk, or reached through a junction'
        text = (f'onecrew: not read ({reason}); size={status.st_size} mtime_ns={status.st_mtime_ns} file={status.st_ino}\n' if status is not None
                else 'onecrew: not read (cannot be examined)\n')
        files.append(temp / f'marker-{number}')
        files[-1].write_bytes(text.encode('ascii'))
    oids = _git(top, 'hash-object', '-w', '--no-filters', '--stdin-paths', env=env, input='\n'.join(str(f) for f in files).encode('utf-8')).split()
    if len(oids) != len(marks): raise LedgerError('git hash-object did not hash every marker.')
    _git(top, *NOSPARSE, 'update-index', '--add', '-z', '--index-info', env=env,                 # -z: a name may hold any character but NUL
         input=b''.join(b'100644 ' + oid.encode('ascii') + b'\t' + enc(name) + b'\0' for oid, (name, _) in zip(oids, marks)))
    missing = {name for name, _ in marks} - _listed(top, env, '--cached')
    if missing: raise LedgerError(f'git did not take the marker of {sorted(missing)[0]!r}: the identity of this working tree cannot be made.')


@_bounded
def hard_links(directory):
    """The working-tree names that a verifier's trees would take from the disk and that are not safe to hash: a file with another name on the disk (a
    hard link), a file reached through a junction (git walks into it as into a folder), and a name that cannot be examined. That other name or place
    may be one every reader is kept from, an ignored .env or a home .ssh: `git add` would hash its content into the tree under an ordinary name and
    every verifier would read it in the checkout, where nothing tells (reviews FX-R01, D-R03). The names are those of HEAD, of the real index (a name
    added with -f or -N) and the untracked files that are not ignored, .onecrew included (git hashes it before the tree leaves it out, D-R04, D-R05);
    every one is looked at, whatever the stat data of an index says. Names, link counts and reparse tags only: nothing is read."""
    top = Path(_git(directory, 'rev-parse', '--show-toplevel'))
    listed = _git(top, 'ls-files', '-z', '--cached', raw=True)                     # the real index
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
        env = {'GIT_INDEX_FILE': str(Path(temp) / 'index')}
        _git(top, 'read-tree', 'HEAD', env=env)
        listed += b'\0' + _git(top, 'ls-files', '-z', '--cached', '--others', '--exclude-standard', env=env, raw=True)
    found, folders = set(), {}
    for name in set(listed.decode('utf-8', 'surrogateescape').split('\0')) - {''}:
        _tick('looking for links')
        parts, crossed = name.split('/'), False
        try:
            for depth in range(1, len(parts)):
                folder = '/'.join(parts[:depth])
                if folder not in folders: folders[folder] = _is_junction(top / folder)
                if folders[folder]:
                    crossed = True
                    break
            status = None if crossed else _lstat(top / name)
        except (OSError, ValueError):
            found.add(name)                             # it cannot be examined: refused, never skipped (E-R04)
            continue
        if crossed or (status is not None and stat.S_ISREG(status.st_mode) and status.st_nlink > 1): found.add(name)
    return sorted(found)


@_bounded
def refuse_hard_links(directory):
    """Raise HardLinked, with the reason and the way out, when hard_links finds a name."""
    found = hard_links(directory)
    if found:
        top = Path(_git(directory, 'rev-parse', '--show-toplevel'))
        name, more = found[0], f' (and {len(found) - 1} more)' if len(found) > 1 else ''
        try:
            through = _through(top, name)
            status = None if through else _lstat(top / name)
            what = (f'is reached through {through!r}, a junction' if through else
                    'has more than one name on the disk (a hard link)' if status is not None and status.st_nlink > 1 else 'cannot be examined')
        except (OSError, ValueError):
            what = 'cannot be examined'
        raise HardLinked(f'{name!r}{more} {what}: the other name or place may be a control or credential file (.env, .ssh), whose content would be '
                         'read under this one. Replace it with a copy, or move it out of the working tree, and try again.')


@_bounded
def verified_sha(directory):
    """artifact_sha for a verifier and for an approval: refused before git hashes anything when hard_links finds a name. The run stops with the reason;
    it cannot go on without that file, as a tree that leaves it out is another artifact."""
    refuse_hard_links(directory)
    return artifact_sha(directory, verified=True)


@_bounded
def tracked_tree(directory):
    """Git tree hash of what Git tracks now: a copy of the repository's real index (so a new file that was `git add`ed is in it) plus the
    modifications and deletions of the files in it (`add -u`), through a throw-away index. Unlike artifact_sha, an untracked file is never in it, and
    an ignored one is not either: what a reviewer is shown must not depend on build output lying around. The real index and the refs are not touched.
    Whatever the artifact holds and this tree does not is `changed_paths(tracked, artifact)`: the untracked files that are not ignored.
    As artifact_sha, the files are pinned and judged on their handles before `git update-index` reads them (Codex review of beta dev9, P1): a file
    that has another name on the disk or is reached through a junction refuses the tree (HardLinked)."""
    top = str(Path(_git(directory, 'rev-parse', '--show-toplevel')).resolve())
    real = Path(_git(top, 'rev-parse', '--git-path', 'index'))
    real = real if real.is_absolute() else Path(top) / real
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
        env = {'GIT_INDEX_FILE': str(Path(temp) / 'index')}
        if real.is_file(): shutil.copyfile(real, env['GIT_INDEX_FILE'])
        else: _git(top, 'read-tree', 'HEAD', env=env)                  # a repository whose index was never written: what HEAD holds is what Git tracks
        held, kept_out = _listed(top, env, '--cached'), _sparse_kept(top)
        with _Pins(top) as pins:
            refused, gone = pins.pin(sorted(n for n in held if n not in kept_out and not _own(n)))
            if refused: raise HardLinked(_refusal(*refused[0]))
            _stage(top, env, sorted(pins.held), gone)
            _repositories_for_files(top, env, pins)
            pins.recheck()
        _git(top, 'rm', '-r', '--cached', '-f', '-q', '--ignore-unmatch', '--', '.onecrew', env=env)     # -f: as in artifact_sha
        return _git(top, 'write-tree', env=env)


def _two_trees(first, second):
    if not all(isinstance(t, str) and TREE_ID.fullmatch(t) for t in (first, second)): raise LedgerError('A tree id is 40 or 64 lowercase hex characters.')


def changed_paths(directory, first, second):
    """Paths (posix, relative to the repository top) that differ between two trees; renames are not paired, so both sides are listed. A submodule whose
    commit differs is listed too, whatever `diff.ignoreSubmodules` or the `ignore` of .gitmodules say (--ignore-submodules=none): this list decides what
    a reviewer is shown and which commits are neutral, so nothing may be left out of it by a configuration."""
    _two_trees(first, second)
    # from the repository's top, always: `diff.relative=true` (a config an AI can set) makes git list only the paths below the folder it runs in
    out = _git(toplevel(directory), 'diff', '--name-only', '--no-renames', '--ignore-submodules=none', '-z', '--end-of-options', first, second)
    return [p for p in out.split('\0') if p]


def submodule_paths(directory, first, second):
    """The changed paths that are a submodule (a gitlink, mode 160000) in either tree. A submodule that moved to another commit is code nobody here can
    read, so it is never a neutral change, whatever path it sits at."""
    _two_trees(first, second)
    out = _git(toplevel(directory), 'diff', '--raw', '-z', '--no-renames', '--ignore-submodules=none', '--end-of-options', first, second)
    parts = out.split('\0')
    found = []
    for meta, path in zip(parts[0::2], parts[1::2]):          # `:<old mode> <new mode> <old sha> <new sha> <status>` then the path
        modes = meta.lstrip(':').split(' ')[:2]
        if '160000' in modes: found.append(path)
    return found


def binary_paths(directory, first, second):
    """The changed paths that git itself shows only as `Binary files ... differ`: a binary file, or text that a diff attribute (`-diff`, also in
    .git/info/attributes), a diff driver marked binary or core.bigFileThreshold keeps out of the text diff. Read from --numstat, which prints `-` for both
    counts of such a path."""
    _two_trees(first, second)
    out = _git(toplevel(directory), 'diff', '--numstat', '--no-renames', '--ignore-submodules=none', '-z', '--end-of-options', first, second)      # from the top (see changed_paths)
    found = []
    for item in out.split('\0'):
        counts = item.split('\t', 2)
        if len(counts) == 3 and counts[0] == '-' and counts[1] == '-': found.append(counts[2])
    return found


def blob_head(directory, tree, path, size=8000):
    """The first `size` bytes of `path` as `tree` holds it (git's own window for deciding that a file is binary); b'' when the tree has no such file."""
    clean = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
    try:
        process = subprocess.Popen(['git', '-C', str(directory), 'cat-file', 'blob', f'{tree}:{path}'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=dict(clean, **_object_env(directory)),
                                   creationflags=0x08000000 if os.name == 'nt' else 0)
    except OSError:
        return b''
    try:
        return process.stdout.read(size)
    finally:
        try:
            process.kill()
        except OSError:
            pass
        process.wait()
        process.stdout.close()


TEXT_MARKS = (codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE, codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)       # a byte order mark: text in UTF-16/32, whatever NULs it holds


def looks_binary(head):
    """A NUL byte in the first bytes (git's own test), unless the file starts with a UTF-16/32 byte order mark: that is text, made of NULs."""
    return b'\0' in head and not head.startswith(TEXT_MARKS)


def text_hidden_paths(directory, first, second, paths):
    """Of `paths` (changed, and shown by git only as `Binary files differ`), those whose TEXT may be withheld: unless EVERY version that exists (the old and
    the new one) is a real binary file (looks_binary), one of them is text that a diff attribute, a diff driver marked binary, core.bigFileThreshold or a
    NUL byte hides. A real binary file (an image, a jar), before and after, is named by its `Binary files differ` header and is not in this list. The
    test is the NUL byte, so a text file with a NUL in it counts as binary (a known limit, in the docs)."""
    _two_trees(first, second)
    found = []
    for path in paths:
        versions = [head for head in (blob_head(directory, tree, path) for tree in (first, second)) if head]
        if not versions or not all(looks_binary(head) for head in versions): found.append(path)
    return found


EMPTY_TREE = {'sha1': '4b825dc642cb6eb9a060e54bf8d69288fbee4904',            # git knows the empty tree without storing it
              'sha256': '6ef19b41225c5369f1c104d45d8d85efa9b057b53b14b4b9b939dd74decc5321'}
ATTR_SOURCE_GIT = (2, 40)


def git_version(top):
    found = re.search(r'(\d+)\.(\d+)', _git(top, 'version'))
    return (int(found.group(1)), int(found.group(2))) if found else (0, 0)


def _require_attr_source(top):
    """The exact-bytes checkout needs --attr-source (git 2.40). An older git is refused with what to do; it never checks out with the attributes."""
    have = git_version(top)
    if have < ATTR_SOURCE_GIT:
        raise LedgerError(f'git {have[0]}.{have[1]} is too old for the verifier checkout: it needs git {ATTR_SOURCE_GIT[0]}.{ATTR_SOURCE_GIT[1]} or '
                          'later (--attr-source) to give each file the exact bytes locked in git. Update git, then run the verdict again.')


CHECKOUT_POLICY = 'exact-blob-bytes/3'   # in the evidence binding: a receipt made under another checkout policy is stale (review of dev17)
# /3 (review of dev24c, owner 11/11 "Sửa cả lỗi cũ"): every command receipt names the program it ran and its Python packages (`program`), so a
# receipt of /2 is not current: on a plan not yet accepted, each such pass runs once again after the upgrade (the policy epoch); accepted plans keep it.
                                         # /2 (review of dev20): every file and folder of the checkout has the same fixed time of change
CHECKOUT_MTIME = 946684800               # 2000-01-01T00:00:00Z: a git tree has no times, so none of its files is newer than another


def _fixed_times(root):
    """Every file and folder under `root` gets CHECKOUT_MTIME, so a check that compares times of change sees the same answer on every run."""
    budget = _active.get()
    for folder, names, files in os.walk(root, topdown=False):
        for name in files + names:
            if budget is not None: budget.tick('fixed times')
            os.utime(os.path.join(folder, name), (CHECKOUT_MTIME, CHECKOUT_MTIME))      # no link to follow: links are plain files
    os.utime(root, (CHECKOUT_MTIME, CHECKOUT_MTIME))


def policy_current(body):
    """Review of dev19: the ONE rule every place that reuses or publishes a verifier result applies (the candidate proofs, the node receipt, an
    issued result, a recorded receipt): it was made under the checkout policy of this OneCrew. Every receipt a verifier writes carries the field;
    one written before it (or under another policy) is never reused, whatever the verifier type."""
    return isinstance(body, dict) and body.get('checkout_policy') == CHECKOUT_POLICY


def object_format(top):
    form = _git(top, 'rev-parse', '--show-object-format').strip() or 'sha1'
    if form not in EMPTY_TREE: raise LedgerError(f'The repository uses the object format {form!r}, which this checkout does not know.')
    return form


def exact_bytes(folder, form):
    """(git arguments, GIT_* environment) under which git reads no attribute and no machine config: the files are the blobs' bytes, a symbolic
    link is a plain file. `folder` gets the two empty files these point at. Used by the verifier checkout and by every git that later reads
    those files back (the candidate materialization), so both see the same bytes."""
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    (folder / 'no-attributes').write_bytes(b''); (folder / 'no-config').write_bytes(b'')
    args = ('--attr-source=' + EMPTY_TREE[form], '-c', 'core.autocrlf=false', '-c', 'core.eol=lf', '-c', 'core.safecrlf=false',
            '-c', 'core.attributesFile=' + (folder / 'no-attributes').as_posix(), '-c', 'core.symlinks=false',
            *(('-c', 'core.longpaths=true') if os.name == 'nt' else ()))
    return args, {'GIT_ATTR_NOSYSTEM': '1', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': str(folder / 'no-config')}


def _bare_git_dir(top, destination):
    """An empty git folder in `destination` for the checkout: no info/attributes, no config but the object format of the repository at `top`."""
    own = destination / 'checkout.git'
    for folder in ('objects', 'refs', 'info'): (own / folder).mkdir(parents=True)
    (own / 'HEAD').write_text('ref: refs/heads/checkout\n', encoding='ascii')
    form = object_format(top)
    (own / 'object-format').write_text(form, encoding='ascii')
    (own / 'config').write_text('[core]\n\trepositoryformatversion = 1\n\tbare = false\n[extensions]\n\tobjectformat = ' + form + '\n', encoding='ascii')
    return own


def _checkout(directory, tree, destination):
    """C8: a clean checkout of exactly the artifact (`git archive <tree>`), so ignored files (__pycache__, build output) of the
    live workspace cannot change the result while the sha stays the same. Returns the directory to run in."""
    top = toplevel(directory)
    root = Path(destination) / 'src'
    root.mkdir()
    # F1: read-tree + checkout-index, not `git archive`: export-ignore / export-subst in .gitattributes would change the tree.
    env = {'GIT_INDEX_FILE': str(Path(destination) / 'checkout.index')}
    _git(top, 'read-tree', tree, env=env)
    # Issue #4 (dev14): the line endings of the checkout never follow this machine's git config (core.autocrlf, core.eol), which is not part of
    # the artifact's identity; the bytes depend only on the tree and its .gitattributes, both hashed. Times of change are those of the checkout.
    # Review of dev14: nor the attributes kept outside the tree. checkout-index runs against an empty git folder of our own (so the repository's
    # info/attributes and its own config are not read; the objects are the repository's), with core.attributesFile pointed at an empty file and the
    # system attributes off. What is left is the tree's own .gitattributes, read from the index.
    # Review of dev15: nor the global or system git config, where filter.<name>.smudge (Git LFS, say) lives: the bytes are the tree's blobs, as git
    # stores them. The two settings that config usually carried and a checkout needs are set here, the same on every machine.
    # Owner 09/11 ("Đồng ý": the check runs on exactly the content locked in git, the same on every machine): nor the tree's own .gitattributes.
    # Attributes are read from the empty tree (--attr-source, git 2.40 or later; an older git is refused, never a quiet fall back), so no eol,
    # filter, ident or working-tree-encoding applies: each file holds its blob's bytes. A symbolic link is a plain file holding its target, on
    # every system (core.symlinks=false), so no check follows a link out of the checkout and every machine sees the same files.
    _require_attr_source(top)
    own = _bare_git_dir(top, Path(destination))
    args, isolated = exact_bytes(own, (own / 'object-format').read_text(encoding='ascii').strip())
    env = dict(env, GIT_DIR=str(own), GIT_OBJECT_DIRECTORY=str(_objects_of(top)), **isolated)
    _git(top, *args, 'checkout-index', '-a', '-f', '--prefix=' + root.as_posix() + '/', env=env)
    _fixed_times(root)                                 # review of dev20: the times of change come from the policy, not from when it ran
    relative = Path(directory).resolve().relative_to(top)
    return root / relative


KEEP_ENV = {'PATH', 'PATHEXT', 'SYSTEMROOT', 'SYSTEMDRIVE', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'TMPDIR', 'HOME', 'USERPROFILE', 'HOMEDRIVE',
             'HOMEPATH', 'USERNAME', 'USER', 'LOGNAME', 'LOCALAPPDATA', 'APPDATA', 'PROGRAMDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)', 'COMMONPROGRAMFILES',
             'PROCESSOR_ARCHITECTURE', 'NUMBER_OF_PROCESSORS', 'OS', 'LANG', 'LC_ALL', 'TZ', 'SHELL', 'TERM', 'CI'}


def verifier_env(directory):
    """F1: what the verifier sees is not the caller's environment. PYTHON*, GIT_*, *_PATH and every other variable are dropped (they can change
    a result without changing the artifact); PATH loses entries that are relative or inside the project or its scratch."""
    env = {k: v for k, v in os.environ.items() if k.upper() in KEEP_ENV}
    # review of dev24c (P2): the project's repository (not the milestone's cwd), by whole path components, case folded on Windows
    top = _place(project_top(directory))
    scratch, own = _place(tempfile.gettempdir()), _place(Path(sys.executable).parent)
    keep = []
    for entry in env.get('PATH', '').split(os.pathsep):
        if not entry or not os.path.isabs(entry): continue
        resolved = _place(entry)
        if _within(resolved, top) or (_within(resolved, scratch) and not _within(resolved, own)): continue
        keep.append(entry)
    env['PATH'] = os.pathsep.join(keep)
    return dict(env, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')


class _Job:
    """Windows: the verifier and every process it starts live in a job object that is killed when its last handle closes. OneCrew holds that handle, so when this
    process dies, even by a hard kill, the system ends the command and its children: none outlives the run as an orphan. The command starts suspended and runs only
    once it is in the job, so it cannot start a child outside it first. Elsewhere, or when the system refuses the job, `active` is False and the old behaviour stays."""
    CREATE_SUSPENDED = 0x00000004

    def __init__(self):
        self.handle, self.active, self.left = None, False, None
        if os.name != 'nt': return
        import ctypes
        from ctypes import wintypes
        self._k = ctypes.WinDLL('kernel32', use_last_error=True)
        self._k.CreateJobObjectW.restype = wintypes.HANDLE
        self._k.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        handle = self._k.CreateJobObjectW(None, None)
        if not handle: return

        class Basic(ctypes.Structure):
            _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64), ('LimitFlags', wintypes.DWORD),
                        ('MinimumWorkingSetSize', ctypes.c_size_t), ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                        ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD), ('SchedulingClass', wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', ctypes.c_uint64 * 6), ('ProcessMemoryLimit', ctypes.c_size_t),
                        ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000                     # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self._k.SetInformationJobObject(wintypes.HANDLE(handle), 9, ctypes.byref(info), ctypes.sizeof(info)):   # JobObjectExtendedLimitInformation
            self._k.CloseHandle(wintypes.HANDLE(handle))
            return
        self.handle = handle

    def flags(self):
        return self.CREATE_SUSPENDED if self.handle else 0

    def adopt(self, process):
        """Put the suspended command in the job, then let it run. A command that cannot be put in the job still runs (old behaviour), recorded as not contained."""
        if not self.handle: return
        import ctypes
        from ctypes import wintypes
        process_handle = wintypes.HANDLE(int(process._handle))
        self.active = bool(self._k.AssignProcessToJobObject(wintypes.HANDLE(self.handle), process_handle))
        ntdll = ctypes.WinDLL('ntdll')
        if ntdll.NtResumeProcess(process_handle) != 0:
            _kill_tree(process)
            raise OSError('the verifier command could not be resumed after it was started suspended')

    def running(self):
        """How many processes of the command are still alive (None without a job)."""
        if not self.active: return None
        import ctypes
        from ctypes import wintypes

        class Accounting(ctypes.Structure):
            _fields_ = [('TotalUserTime', ctypes.c_int64), ('TotalKernelTime', ctypes.c_int64), ('ThisPeriodTotalUserTime', ctypes.c_int64),
                        ('ThisPeriodTotalKernelTime', ctypes.c_int64), ('TotalPageFaultCount', wintypes.DWORD), ('TotalProcesses', wintypes.DWORD),
                        ('ActiveProcesses', wintypes.DWORD), ('TotalTerminatedProcesses', wintypes.DWORD)]
        info = Accounting()
        if not self._k.QueryInformationJobObject(wintypes.HANDLE(self.handle), 1, ctypes.byref(info), ctypes.sizeof(info), None): return None
        return int(info.ActiveProcesses)

    SETTLE_SECONDS = 0.5

    def end(self, settle=False):
        """Ends whatever of the command is still running and releases the job. Returns how many processes it ended (None without a job).
        settle: after a normal exit, wait up to SETTLE_SECONDS for the count to reach zero first. A console command started without a window keeps one
        process of the system's console host in the job for a few milliseconds after it exits (measured: gone within 50 ms); without the wait every clean
        run reads as one process left running. A child the command really left (one that sleeps or serves) is still there after the wait, and counted."""
        if not self.handle: return None
        from ctypes import wintypes
        try:
            self.left = self.running()
            give_up = time.monotonic() + self.SETTLE_SECONDS
            while settle and self.left and time.monotonic() < give_up:
                time.sleep(0.02)
                self.left = self.running()
            if self.active: self._k.TerminateJobObject(wintypes.HANDLE(self.handle), 1)
        finally:
            self._k.CloseHandle(wintypes.HANDLE(self.handle))
            self.handle = None
        return self.left


def _kill_tree(process, job=None):
    if job is not None: job.end()
    if os.name == 'nt':
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)], capture_output=True, creationflags=0x08000000)
    process.kill()


MIN_SECONDS = 2.0                               # a success faster than this AND silent is named fast_and_silent (job 5: exit 0 in 0.8 s, no output, corrupted argv)
NOT_FOUND_CODES = (127, 9009)                   # the shell's "command not found" (POSIX, cmd.exe)
CONTROL = re.compile(r'[\x00-\x1f\x7f]')


def suspicious_rule(receipt):
    """Why a run that looks like a pass (or a missing program) cannot be believed, as `suspicious: <rule>`, or None. Judged from the
    receipt's own fields, so the rule applies the same when verdict.record re-reads a receipt. A receipt written before the output sizes
    were kept (no stdout_bytes) is not judged on emptiness."""
    error = receipt.get('error') or ''
    if error.startswith('FileNotFoundError') or receipt.get('exit_code') in NOT_FOUND_CODES: return 'suspicious: executable_not_found'
    if receipt.get('exit_code') != 0 or receipt.get('timed_out'): return None
    if any(CONTROL.search(a) for a in receipt.get('argv', ()) if isinstance(a, str)): return 'suspicious: control_char_argv'
    if receipt.get('stdout_bytes') == 0 and receipt.get('stderr_bytes') == 0:
        # Speed alone proves nothing (a device check prints its answer in 1-2 s): only a fast run that also printed nothing is named for both.
        return 'suspicious: fast_and_silent' if receipt.get('seconds', MIN_SECONDS) < MIN_SECONDS else 'suspicious: empty_output'
    return None


def expected_result(receipt):
    """The verdict a receipt supports: pass only on exit 0 with an unchanged artifact and no suspicious_rule; fail on a real non-zero exit;
    else inconclusive."""
    if receipt['error'] or receipt['timed_out'] or receipt['exit_code'] is None or receipt['artifact_sha'] != receipt['artifact_sha_after']:
        return 'inconclusive'
    if suspicious_rule(receipt): return 'inconclusive'
    return 'pass' if receipt['exit_code'] == 0 else 'fail'


@contextmanager
def before_verifier():
    """What fails in here failed before the verifier was called, and the error says so: a new run may start, no release is needed (W37a keeps a run
    of unknown outcome only when that is not known)."""
    try:
        yield
    except BaseException as failed:                    # issue #2 (dev14): any failure in here, not only SnapshotFailed: a git checkout that
        if getattr(failed, 'verifier_started', None) is None:      # fails, an OSError, a LedgerError from the environment, a bad value;
            try:                                       # review of dev15: Ctrl+C too (KeyboardInterrupt), which stays what it is
                failed.verifier_started = False
            except (AttributeError, TypeError):
                if not isinstance(failed, Exception): raise
                raise NotStarted(f'{type(failed).__name__}: {failed}'[:500]) from failed
        raise


class NotStarted(LedgerError):
    """A failure before the verifier was called whose own exception cannot carry the mark."""
    verifier_started = False


def run(ledger, name, revision, plan_sha, milestone, directory, evidence_context=None, *, effective_environment=None, deadline=None):
    """Execute the milestone's command; returns (receipt_blob, receipt)."""
    with before_verifier():                            # issue #2 (dev14): the directory check and the scratch directory too; MEP inputs as well
        argv, limit = milestone['verifier']['config']['argv'], milestone['verifier']['config']['max_minutes']
        inputs = milestone['verifier']['config'].get('inputs')
        directory = Path(directory).resolve()
        if not directory.is_dir(): raise LedgerError('Verifier working directory does not exist: ' + str(directory))
        if inputs and evidence_context: raise InputRefused('Declared inputs are not supported on a workflow root: its handoff judges the whole artifact. The verifier was not called.')
    with snapshot_limits(deadline):
        with before_verifier():                        # mep7 hole (a), 2.5.0.dev24
            _sweep_scratch()
        begin = time.monotonic()
        with before_verifier(), _snapshot('before the verifier'):
            if inputs:
                check_argv_scope(directory, argv, inputs)
                try:
                    before = scoped_tree(directory, inputs, verified=True)
                except HardLinked as refused:
                    refused.verifier_started = False
                    raise
            else:
                before = verified_sha(directory)
        timing = {'before_seconds': round(time.monotonic() - begin, 2), 'limit_seconds': round(snapshot_seconds(), 1)}
        with before_verifier():                        # mep7 hole (a), 2.5.0.dev24: the scratch directory is made before any dispatch
            scratch = tempfile.mkdtemp(prefix=SCRATCH_PREFIX)
            _own_scratch(scratch)
        try:
            return _run(ledger, name, revision, plan_sha, milestone, directory, argv, limit, before, scratch, evidence_context,
                        effective_environment=effective_environment, deadline=deadline, timing=timing)
        finally:
            _remove_scratch(scratch)


def _run(ledger, name, revision, plan_sha, milestone, directory, argv, limit, before, scratch, evidence_context=None, *, effective_environment=None, deadline=None, timing=None):
    timing = dict(timing or {})
    begin = time.monotonic()
    with before_verifier():                            # up to the Popen below the verifier has not been called, whatever fails here
        inputs = milestone['verifier']['config'].get('inputs')
        with _snapshot('checkout for the verifier'):
            timing['checkout_files'], timing['checkout_bytes'] = _check_room(directory, before, scratch)
            workspace = _checkout(directory, before, scratch)
        timing['checkout_seconds'] = round(time.monotonic() - begin, 2)
        if inputs and not workspace.is_dir(): raise InputRefused(f'The working folder {workspace.name!r} is not in the checkout of the declared inputs. The verifier was not called.')
        scanned = check_live_tree_named(directory, argv, Path(scratch) / 'src', milestone['verifier']['config'].get('inputs_unscanned') or ()) if inputs else None
        # S1: children are always UTF-8, so a Vietnamese path or message cannot turn a pass into an encoding failure.
        env = verifier_env(directory) if effective_environment is None else dict(effective_environment)
        # review of dev24b/c (P1-a, P2): a bare program is looked up once, on THIS environment's PATH; it, or an absolute one, must exist; the process is
        # started from exactly that path (executable=), the child still sees argv[0] as written; the receipt fingerprints the same file
        found = program_path(argv[0], env)
        if is_bare_word(argv[0]) and found is None:
            raise ProgramMissing(f"The program {argv[0]!r} is not on the verifier's PATH (the PATH without folders of the project's repository or the temp "
                                 'folder). Name it by its absolute path. The verifier was not called.')
        if os.path.isabs(argv[0]) and not (os.path.isfile(argv[0]) or app_alias_target(argv[0])):
            raise ProgramMissing(f'The program {argv[0]} does not exist. The verifier was not called.')
        if not os.path.isabs(argv[0]) and not is_bare_word(argv[0]) and not _relative_program(workspace, argv[0], env):     # review of dev24d (P2)
            raise ProgramMissing(f'The program {argv[0]} is not in the working folder of the check. The verifier was not called.')
        program = tool_identity(argv[0], env, found)
        declared = milestone['verifier']['config'].get('env_inputs')
        outside = env_inputs_identity(declared, directory) if declared else None
        batch = os.name == 'nt' and found and Path(found).suffix.lower() in ('.bat', '.cmd')
        start, executable = ([found, *argv[1:]], None) if batch else (list(argv), found)    # a batch file is started by its path, as cmd needs
        from .. import verification_evidence
        binding = verification_evidence.for_receipt(ledger, evidence_context, milestone, before, env) if evidence_context else None
        scope = None
        if inputs:
            try:
                head = _git(directory, 'rev-parse', '--verify', '-q', 'HEAD')
            except LedgerError:
                head = None
            scope = {'paths': list(inputs), 'effective': scope_paths(inputs), 'files': timing['checkout_files'], 'bytes': timing['checkout_bytes'], 'head': head, 'tool': program,
                     'live_tree_scan': scanned}
            if outside is not None: scope['env_inputs'] = outside      # 2.5.0.dev24 (P1): the owner-declared paths outside the repository
        started, error, timed_out, code, out, err = utcnow(), None, False, None, b'', b''
        begin = time.monotonic()
        if deadline is not None:                       # issue #2 (dev14): inside before_verifier too, up to the Popen
            left = (dt.datetime.fromisoformat(deadline) - dt.datetime.now(dt.timezone.utc)).total_seconds()
            if left <= 0:
                failed = LedgerError('The original root deadline elapsed before verifier command dispatch.')
                failed.verifier_started = False
                raise failed
            limit = min(limit, left / 60)
        job = _Job()                                   # Windows: the command and its children end with this process, even on a hard kill
    try:
        process = subprocess.Popen(start, executable=executable, cwd=str(workspace), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, creationflags=(0x08000000 | job.flags()) if os.name == 'nt' else 0)
        job.adopt(process)
        try:
            out, err = process.communicate(timeout=limit * 60)
            code = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(process, job)
            out, err = process.communicate()
        except BaseException:                          # an interrupt: the command does not outlive this run
            _kill_tree(process, job)
            raise
    except OSError as problem:
        error = f'{type(problem).__name__}: {problem}'[:300]
    finally:
        left = job.end(settle=code is not None) if job.handle else job.left    # a child the command left running is ended here, and counted
    if os.name == 'nt': timing['contained'], timing['left_running'] = job.active, left
    seconds = round(time.monotonic() - begin, 2)       # the verifier alone: the snapshots around it are in `snapshot` of the receipt
    finished = time.monotonic()
    try:
        with _snapshot('after the verifier', floor=STEP_SECONDS):
            after = scoped_tree(directory, inputs, verified=True) if inputs else verified_sha(directory)            # made the way the before one is: a link the command made is not hashed into a tree (D-R05)
    except LedgerError as problem:                     # the command ran: its receipt is kept, inconclusive, with the reason (review E-R01)
        after, error = None, error or f'the artifact after the command cannot be identified: {problem}'[:300]
        if isinstance(problem, SnapshotFailed):
            problem.verifier_started = True
            timing['failed'] = problem.structured()
    timing['after_seconds'] = round(time.monotonic() - finished, 2)
    store = Snapshots(ledger.state_root)
    receipt = {'kind': 'command-receipt', 'checkout_policy': CHECKOUT_POLICY, 'plan': name, 'revision': revision, 'plan_sha': plan_sha, 'milestone': milestone['id'],
               'argv': argv, 'cwd': str(directory), 'exit_code': code, 'timed_out': timed_out, 'error': error,
               'seconds': seconds, 'snapshot': timing, 'started': started, 'artifact_sha': before, 'artifact_sha_after': after,
               'stdout': store.blob(out[-OUTPUT_CAP:]), 'stderr': store.blob(err[-OUTPUT_CAP:]),
               'stdout_bytes': len(out), 'stderr_bytes': len(err), 'output_truncated': len(out) > OUTPUT_CAP or len(err) > OUTPUT_CAP,
               'program': program, **({'env_inputs': outside} if outside is not None else {}),       # review of dev24c (P1): every command receipt
               **({'input_scope': scope} if scope else {})}
    rule = suspicious_rule(receipt)
    if binding is not None: receipt['evidence_binding'] = binding
    if rule: receipt['suspicious'] = rule            # the receipt names the rule that made the verdict inconclusive
    return store.blob(canonical(receipt).encode('utf-8')), receipt
