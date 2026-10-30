"""Verifier `command`: run the milestone's argv in a workspace, within a minute cap, and keep the evidence.

The receipt is a blob (sha256-addressed, same store as v1 receipts) that binds plan hash, revision, milestone, argv and the
artifact (a Git tree hash of the working tree) to the exit code and output. verdict.run announces each receipt it makes
(verdict.receipt_issued) and record() takes no other receipt for a command milestone, so a hand-written receipt, however
well formed, is refused.
"""
import codecs
import datetime as dt
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from ...ledger import LedgerError, canonical, utcnow
from ...snapshots import Snapshots

OUTPUT_CAP = 1_000_000
TREE_ID = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')          # the only shape of a tree id that is ever given to git


def _git(directory, *args, env=None, input=None, raw=False):
    # F8: the caller's GIT_DIR / GIT_WORK_TREE / ... never reach git; only what this module sets (GIT_INDEX_FILE) does
    clean = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
    done = subprocess.run(['git', '-C', str(directory), *args], capture_output=True, env=dict(clean, **{k: v for k, v in (env or {}).items() if k.upper().startswith('GIT_')}), timeout=120,
                          creationflags=0x08000000 if os.name == 'nt' else 0, input=input)
    if done.returncode:
        reason = done.stderr.decode('utf-8', 'replace') if isinstance(done.stderr, bytes) else str(done.stderr or '')
        raise LedgerError('git ' + ' '.join(args[:2]) + ' failed: ' + reason[:300])
    return done.stdout if raw else done.stdout.decode('utf-8', 'replace').strip()


def toplevel(directory):
    """Resolved Git toplevel of a directory (C6: a verdict speaks about the project's repository, not a clone nested in it)."""
    return Path(_git(directory, 'rev-parse', '--show-toplevel')).resolve()


def artifact_sha(directory):
    """Git tree hash of the working tree (tracked and untracked, honouring .gitignore), via a throw-away index: the
    repository's own index and refs are not touched. A name that hard_links finds (another name on the disk, a file through a junction, a name that
    cannot be examined) is never hashed: its place in the tree holds a marker blob made of its stat data only (size, modification time, file id), so
    the identity still changes when that file changes and nothing of its content reaches the object store (2.3 beta B2). verified_sha refuses such
    a tree; this one is what views, reports and evidence checks compare."""
    top = _git(directory, 'rev-parse', '--show-toplevel')
    linked = hard_links(top)
    with tempfile.TemporaryDirectory() as temp:
        env = {'GIT_INDEX_FILE': str(Path(temp) / 'index')}
        _git(top, 'read-tree', 'HEAD', env=env)
        if linked:
            _add_without(top, linked, Path(temp), env)
        else:
            _git(top, 'add', '-A', env=env)
        # hook files (.onecrew/) are not part of the artifact. -f: a hook may rewrite one between the add and this rm, and without it git refuses to drop
        # a staged entry that differs from both the file and HEAD (the gate on c6d8477); only the throw-away index is touched.
        _git(top, 'rm', '-r', '--cached', '-f', '-q', '--ignore-unmatch', '--', '.onecrew', env=env)
        return _git(top, 'write-tree', env=env)


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


NOSPARSE = ('-c', 'core.sparseCheckout=false', '-c', 'index.sparse=false')   # a sparse checkout clears skip-worktree on files on disk (review B2 P1)


def _add_without(top, linked, temp, env):
    """`git add -A` into the throw-away index of artifact_sha without reading any name of `linked`, then a marker blob at each of them: what os.lstat
    says of it, never its bytes. A name HEAD holds is kept from the add with skip-worktree: an excluding pathspec would make git refuse the whole add
    when the name is ignored (review B2 P2-1). A name only the untracked listing holds is left out by an excluding pathspec, with the whole junction
    it is reached through, so a file made below it meanwhile is not hashed either. A name git would not take (ignored and not in HEAD) gets no
    marker: the tree never held it. A name that is gone (a tracked file behind a junction that does not hold it) gets none either: `git add -A`
    drops it, as before (P3-5). Every marker must be in the index afterwards, or the identity is refused (P3-2). Sparse checkout is off for these
    commands: with it on, git clears skip-worktree on a file that is on disk and `add` would hash the linked file (review B2 P1)."""
    top = Path(top)
    enc = lambda n: n.encode('utf-8', 'surrogateescape')

    def listed(*args):
        return {n for n in _git(top, 'ls-files', '-z', *args, env=env, raw=True).decode('utf-8', 'surrogateescape').split('\0') if n}
    held, others = listed('--cached'), listed('--others', '--exclude-standard')
    keep, leave, marks = [], set(), []
    for name in linked:
        plain = name.rstrip('/')                       # a nested repository is listed as a folder with its slash
        if plain not in held and name not in others and plain not in others: continue
        try:
            status, failed = _lstat(top / plain), False
        except (OSError, ValueError):
            status, failed = None, True
        if status is None and not failed: continue     # gone: `git add -A` drops a tracked one from its stat alone, an untracked one is not there
        marks.append((plain, status))
        if plain in held:
            keep.append(plain)
        else:
            try:
                through = _through(top, plain)
            except (OSError, ValueError):              # P3-3: the name itself is left out, never read
                through = None
            leave.add(through or plain)
    if keep:
        _git(top, *NOSPARSE, 'update-index', '--skip-worktree', '-z', '--stdin', env=env, input=b''.join(enc(n) + b'\0' for n in keep))
    if leave:
        _git(top, *NOSPARSE, 'add', '-A', '--pathspec-from-file=-', '--pathspec-file-nul', env=env,
             input=b'\0'.join([b'.'] + [b':(exclude,literal)' + enc(n) for n in sorted(leave)]))
    else:
        _git(top, *NOSPARSE, 'add', '-A', env=env)
    if not marks: return
    files = []
    for number, (name, status) in enumerate(marks):
        text = (f'onecrew: not read (another name on the disk, or reached through a junction); size={status.st_size} '
                f'mtime_ns={status.st_mtime_ns} file={status.st_ino}\n' if status is not None else 'onecrew: not read (cannot be examined)\n')
        files.append(temp / f'marker-{number}')
        files[-1].write_bytes(text.encode('ascii'))
    oids = _git(top, 'hash-object', '-w', '--no-filters', '--stdin-paths', env=env, input='\n'.join(str(f) for f in files).encode('utf-8')).split()
    if len(oids) != len(marks): raise LedgerError('git hash-object did not hash every marker.')
    _git(top, *NOSPARSE, 'update-index', '--add', '-z', '--index-info', env=env,                 # -z: a name may hold any character but NUL
         input=b''.join(b'100644 ' + oid.encode('ascii') + b'\t' + enc(name) + b'\0' for oid, (name, _) in zip(oids, marks)))
    missing = {name for name, _ in marks} - listed('--cached')
    if missing: raise LedgerError(f'git did not take the marker of {sorted(missing)[0]!r}: the identity of this working tree cannot be made.')


def hard_links(directory):
    """The working-tree names that a verifier's trees would take from the disk and that are not safe to hash: a file with another name on the disk (a
    hard link), a file reached through a junction (git walks into it as into a folder), and a name that cannot be examined. That other name or place
    may be one every reader is kept from, an ignored .env or a home .ssh: `git add` would hash its content into the tree under an ordinary name and
    every verifier would read it in the checkout, where nothing tells (reviews FX-R01, D-R03). The names are those of HEAD, of the real index (a name
    added with -f or -N) and the untracked files that are not ignored, .onecrew included (git hashes it before the tree leaves it out, D-R04, D-R05);
    every one is looked at, whatever the stat data of an index says. Names, link counts and reparse tags only: nothing is read."""
    top = Path(_git(directory, 'rev-parse', '--show-toplevel'))
    listed = _git(top, 'ls-files', '-z', '--cached', raw=True)                     # the real index
    with tempfile.TemporaryDirectory() as temp:
        env = {'GIT_INDEX_FILE': str(Path(temp) / 'index')}
        _git(top, 'read-tree', 'HEAD', env=env)
        listed += b'\0' + _git(top, 'ls-files', '-z', '--cached', '--others', '--exclude-standard', env=env, raw=True)
    found, folders = set(), {}
    for name in set(listed.decode('utf-8', 'surrogateescape').split('\0')) - {''}:
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


def verified_sha(directory):
    """artifact_sha for a verifier and for an approval: refused before git hashes anything when hard_links finds a name. The run stops with the reason;
    it cannot go on without that file, as a tree that leaves it out is another artifact."""
    refuse_hard_links(directory)
    return artifact_sha(directory)


def tracked_tree(directory):
    """Git tree hash of what Git tracks now: a copy of the repository's real index (so a new file that was `git add`ed is in it) plus the
    modifications and deletions of the files in it (`add -u`), through a throw-away index. Unlike artifact_sha, an untracked file is never in it, and
    an ignored one is not either: what a reviewer is shown must not depend on build output lying around. The real index and the refs are not touched.
    Whatever the artifact holds and this tree does not is `changed_paths(tracked, artifact)`: the untracked files that are not ignored."""
    top = _git(directory, 'rev-parse', '--show-toplevel')
    real = Path(_git(top, 'rev-parse', '--git-path', 'index'))
    real = real if real.is_absolute() else Path(top) / real
    with tempfile.TemporaryDirectory() as temp:
        env = {'GIT_INDEX_FILE': str(Path(temp) / 'index')}
        if real.is_file(): shutil.copyfile(real, env['GIT_INDEX_FILE'])
        else: _git(top, 'read-tree', 'HEAD', env=env)                  # a repository whose index was never written: what HEAD holds is what Git tracks
        _git(top, 'add', '-u', env=env)
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
        process = subprocess.Popen(['git', '-C', str(directory), 'cat-file', 'blob', f'{tree}:{path}'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=clean,
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


def _checkout(directory, tree, destination):
    """C8: a clean checkout of exactly the artifact (`git archive <tree>`), so ignored files (__pycache__, build output) of the
    live workspace cannot change the result while the sha stays the same. Returns the directory to run in."""
    top = toplevel(directory)
    root = Path(destination) / 'src'
    root.mkdir()
    # F1: read-tree + checkout-index, not `git archive`: export-ignore / export-subst in .gitattributes would change the tree.
    env = {'GIT_INDEX_FILE': str(Path(destination) / 'checkout.index')}
    _git(top, 'read-tree', tree, env=env)
    _git(top, 'checkout-index', '-a', '-f', '--prefix=' + root.as_posix() + '/', env=env)
    relative = Path(directory).resolve().relative_to(top)
    return root / relative


KEEP_ENV = {'PATH', 'PATHEXT', 'SYSTEMROOT', 'SYSTEMDRIVE', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'TMPDIR', 'HOME', 'USERPROFILE', 'HOMEDRIVE',
             'HOMEPATH', 'USERNAME', 'USER', 'LOGNAME', 'LOCALAPPDATA', 'APPDATA', 'PROGRAMDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)', 'COMMONPROGRAMFILES',
             'PROCESSOR_ARCHITECTURE', 'NUMBER_OF_PROCESSORS', 'OS', 'LANG', 'LC_ALL', 'TZ', 'SHELL', 'TERM', 'CI'}


def verifier_env(directory):
    """F1: what the verifier sees is not the caller's environment. PYTHON*, GIT_*, *_PATH and every other variable are dropped (they can change
    a result without changing the artifact); PATH loses entries that are relative or inside the project or its scratch."""
    env = {k: v for k, v in os.environ.items() if k.upper() in KEEP_ENV}
    top = str(Path(directory).resolve())
    scratch = str(Path(tempfile.gettempdir()).resolve())
    keep = []
    for entry in env.get('PATH', '').split(os.pathsep):
        if not entry or not os.path.isabs(entry): continue
        resolved = str(Path(entry).resolve())
        if resolved.startswith(top) or (resolved.startswith(scratch) and not resolved.startswith(str(Path(sys.executable).resolve().parent))): continue
        keep.append(entry)
    env['PATH'] = os.pathsep.join(keep)
    return dict(env, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')


def _kill_tree(process):
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


def run(ledger, name, revision, plan_sha, milestone, directory, evidence_context=None, *, effective_environment=None, deadline=None):
    """Execute the milestone's command; returns (receipt_blob, receipt)."""
    argv, limit = milestone['verifier']['config']['argv'], milestone['verifier']['config']['max_minutes']
    directory = Path(directory).resolve()
    if not directory.is_dir(): raise LedgerError('Verifier working directory does not exist: ' + str(directory))
    before = verified_sha(directory)
    scratch = tempfile.mkdtemp(prefix='ocv-')
    try:
        return _run(ledger, name, revision, plan_sha, milestone, directory, argv, limit, before, scratch, evidence_context,
                    effective_environment=effective_environment, deadline=deadline)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _run(ledger, name, revision, plan_sha, milestone, directory, argv, limit, before, scratch, evidence_context=None, *, effective_environment=None, deadline=None):
    workspace = _checkout(directory, before, scratch)
    # S1: children are always UTF-8, so a Vietnamese path or message cannot turn a pass into an encoding failure.
    env = verifier_env(directory) if effective_environment is None else dict(effective_environment)
    from .. import verification_evidence
    binding = verification_evidence.for_receipt(ledger, evidence_context, milestone, before, env) if evidence_context else None
    started, error, timed_out, code, out, err = utcnow(), None, False, None, b'', b''
    begin = time.monotonic()
    if deadline is not None:
        left = (dt.datetime.fromisoformat(deadline) - dt.datetime.now(dt.timezone.utc)).total_seconds()
        if left <= 0: raise LedgerError('The original root deadline elapsed before verifier command dispatch.')
        limit = min(limit, left / 60)
    try:
        process = subprocess.Popen(argv, cwd=str(workspace), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, creationflags=0x08000000 if os.name == 'nt' else 0)
        try:
            out, err = process.communicate(timeout=limit * 60)
            code = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(process)
            out, err = process.communicate()
    except OSError as problem:
        error = f'{type(problem).__name__}: {problem}'[:300]
    try:
        after = verified_sha(directory)                # made the way the before one is: a link the command made is not hashed into a tree (D-R05)
    except LedgerError as problem:                     # the command ran: its receipt is kept, inconclusive, with the reason (review E-R01)
        after, error = None, error or f'the artifact after the command cannot be identified: {problem}'[:300]
    store = Snapshots(ledger.state_root)
    receipt = {'kind': 'command-receipt', 'plan': name, 'revision': revision, 'plan_sha': plan_sha, 'milestone': milestone['id'],
               'argv': argv, 'cwd': str(directory), 'exit_code': code, 'timed_out': timed_out, 'error': error,
               'seconds': round(time.monotonic() - begin, 2), 'started': started, 'artifact_sha': before, 'artifact_sha_after': after,
               'stdout': store.blob(out[-OUTPUT_CAP:]), 'stderr': store.blob(err[-OUTPUT_CAP:]),
               'stdout_bytes': len(out), 'stderr_bytes': len(err), 'output_truncated': len(out) > OUTPUT_CAP or len(err) > OUTPUT_CAP}
    rule = suspicious_rule(receipt)
    if binding is not None: receipt['evidence_binding'] = binding
    if rule: receipt['suspicious'] = rule            # the receipt names the rule that made the verdict inconclusive
    return store.blob(canonical(receipt).encode('utf-8')), receipt
