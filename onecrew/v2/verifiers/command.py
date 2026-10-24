"""Verifier `command`: run the milestone's argv in a workspace, within a minute cap, and keep the evidence.

The receipt is a blob (sha256-addressed, same store as v1 receipts) that binds plan hash, revision, milestone, argv and the
artifact (a Git tree hash of the working tree) to the exit code and output. verdict.run announces each receipt it makes
(verdict.receipt_issued) and record() takes no other receipt for a command milestone, so a hand-written receipt, however
well formed, is refused.
"""
import codecs
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from ...ledger import LedgerError, canonical, utcnow
from ...snapshots import Snapshots

OUTPUT_CAP = 1_000_000
TREE_ID = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')          # the only shape of a tree id that is ever given to git


def _git(directory, *args, env=None, input=None):
    # F8: the caller's GIT_DIR / GIT_WORK_TREE / ... never reach git; only what this module sets (GIT_INDEX_FILE) does
    clean = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
    done = subprocess.run(['git', '-C', str(directory), *args], capture_output=True, env=dict(clean, **{k: v for k, v in (env or {}).items() if k.upper().startswith('GIT_')}), timeout=120,
                          creationflags=0x08000000 if os.name == 'nt' else 0, input=input)
    if done.returncode:
        reason = done.stderr.decode('utf-8', 'replace') if isinstance(done.stderr, bytes) else str(done.stderr or '')
        raise LedgerError('git ' + ' '.join(args[:2]) + ' failed: ' + reason[:300])
    return done.stdout.decode('utf-8', 'replace').strip()


def toplevel(directory):
    """Resolved Git toplevel of a directory (C6: a verdict speaks about the project's repository, not a clone nested in it)."""
    return Path(_git(directory, 'rev-parse', '--show-toplevel')).resolve()


def artifact_sha(directory):
    """Git tree hash of the working tree (tracked and untracked, honouring .gitignore), via a throw-away index: the
    repository's own index and refs are not touched."""
    top = _git(directory, 'rev-parse', '--show-toplevel')
    with tempfile.TemporaryDirectory() as temp:
        env = {'GIT_INDEX_FILE': str(Path(temp) / 'index')}
        _git(top, 'read-tree', 'HEAD', env=env)
        _git(top, 'add', '-A', env=env)
        _git(top, 'rm', '-r', '--cached', '-q', '--ignore-unmatch', '--', '.onecrew', env=env)  # hook files (.onecrew/) are not part of the artifact
        return _git(top, 'write-tree', env=env)


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
        _git(top, 'rm', '-r', '--cached', '-q', '--ignore-unmatch', '--', '.onecrew', env=env)
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


def run(ledger, name, revision, plan_sha, milestone, directory, evidence_context=None, *, effective_environment=None):
    """Execute the milestone's command; returns (receipt_blob, receipt)."""
    argv, limit = milestone['verifier']['config']['argv'], milestone['verifier']['config']['max_minutes']
    directory = Path(directory).resolve()
    if not directory.is_dir(): raise LedgerError('Verifier working directory does not exist: ' + str(directory))
    before = artifact_sha(directory)
    scratch = tempfile.mkdtemp(prefix='ocv-')
    try:
        return _run(ledger, name, revision, plan_sha, milestone, directory, argv, limit, before, scratch, evidence_context,
                    effective_environment=effective_environment)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _run(ledger, name, revision, plan_sha, milestone, directory, argv, limit, before, scratch, evidence_context=None, *, effective_environment=None):
    workspace = _checkout(directory, before, scratch)
    # S1: children are always UTF-8, so a Vietnamese path or message cannot turn a pass into an encoding failure.
    env = verifier_env(directory) if effective_environment is None else dict(effective_environment)
    from .. import verification_evidence
    binding = verification_evidence.for_receipt(ledger, evidence_context, milestone, before, env) if evidence_context else None
    started, error, timed_out, code, out, err = utcnow(), None, False, None, b'', b''
    begin = time.monotonic()
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
    after = artifact_sha(directory)
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
