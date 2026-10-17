"""Verifier `command`: run the milestone's argv in a workspace, within a minute cap, and keep the evidence.

The receipt is a blob (sha256-addressed, same store as v1 receipts) that binds plan hash, revision, milestone, argv and the
artifact (a Git tree hash of the working tree) to the exit code and output. A verdict for this verifier is accepted only
with such a receipt, so a pass cannot be typed in by hand.
"""
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from ...ledger import LedgerError, canonical, utcnow
from ...snapshots import Snapshots

OUTPUT_CAP = 1_000_000


def _git(directory, *args, env=None):
    done = subprocess.run(['git', '-C', str(directory), *args], capture_output=True, env=env, timeout=120,
                          creationflags=0x08000000 if os.name == 'nt' else 0)
    if done.returncode: raise LedgerError('git ' + ' '.join(args[:2]) + ' failed: ' + done.stderr.decode('utf-8', 'replace')[:300])
    return done.stdout.decode('utf-8', 'replace').strip()


def artifact_sha(directory):
    """Git tree hash of the working tree (tracked and untracked, honouring .gitignore), via a throw-away index: the
    repository's own index and refs are not touched."""
    top = _git(directory, 'rev-parse', '--show-toplevel')
    with tempfile.TemporaryDirectory() as temp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(temp) / 'index'))
        _git(top, 'read-tree', 'HEAD', env=env)
        _git(top, 'add', '-A', env=env)
        return _git(top, 'write-tree', env=env)


def _kill_tree(process):
    if os.name == 'nt':
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)], capture_output=True, creationflags=0x08000000)
    process.kill()


def expected_result(receipt):
    """The verdict a receipt supports: pass only on exit 0 with an unchanged artifact; fail on a real non-zero exit; else inconclusive."""
    if receipt['error'] or receipt['timed_out'] or receipt['exit_code'] is None or receipt['artifact_sha'] != receipt['artifact_sha_after']:
        return 'inconclusive'
    return 'pass' if receipt['exit_code'] == 0 else 'fail'


def run(ledger, name, revision, plan_sha, milestone, directory):
    """Execute the milestone's command; returns (receipt_blob, receipt)."""
    argv, limit = milestone['verifier']['config']['argv'], milestone['verifier']['config']['max_minutes']
    directory = Path(directory).resolve()
    if not directory.is_dir(): raise LedgerError('Verifier working directory does not exist: ' + str(directory))
    before = artifact_sha(directory)
    # S1: children are always UTF-8, so a Vietnamese path or message cannot turn a pass into an encoding failure.
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    started, error, timed_out, code, out, err = utcnow(), None, False, None, b'', b''
    begin = time.monotonic()
    try:
        process = subprocess.Popen(argv, cwd=str(directory), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
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
               'output_truncated': len(out) > OUTPUT_CAP or len(err) > OUTPUT_CAP}
    return store.blob(canonical(receipt).encode('utf-8')), receipt
