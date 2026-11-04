"""Shared fixture of the R02 tests (W23b outcome / resume pack, W48a/b context): a temp project (git), temp state roots, and the helpers
that build plans with the REAL v2 functions (propose / approve / verdict run / accept). No model is ever called. The AI-session markers
are removed from the environment while the fixture plays the owner (the way tests/test_v2_report.py does), and set again by a test that
needs to prove an AI-session refusal.
"""
import contextlib
import io
import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger
from onecrew.v2 import plan as plans, verdict

from test_v2_l1 import BAD, OK, milestone, plan_json  # noqa: F401  (re-exported for the R02 tests)

AI_MARKERS = ('ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION')


class Sandbox:
    """A temp directory with git projects and state roots; the environment is cleaned for the owner's verbs."""

    def __init__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.env = patch.dict(os.environ)
        self.env.start()
        for name in AI_MARKERS: os.environ.pop(name, None)

    def close(self):
        self.env.stop()
        self.temp.cleanup()

    def project(self, name, files=None):
        root = self.base / name
        root.mkdir()
        self.git(root, 'init', '-q'); self.git(root, 'config', 'user.name', 'T'); self.git(root, 'config', 'user.email', 't@localhost')
        for relative, text in (files or {'a.txt': 'one\n'}).items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
        self.git(root, 'add', '.')
        self.git(root, 'commit', '-q', '-m', 'base')
        return root

    @staticmethod
    def git(root, *args):
        return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE).decode().strip()

    def commit(self, root, message, files):
        for relative, text in files.items():
            path = Path(root) / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
        self.git(root, 'add', '.')
        self.git(root, 'commit', '-q', '-m', message)
        return self.git(root, 'rev-parse', 'HEAD')

    def state(self, name):
        return self.base / name

    def ledger(self, project, state):
        return Ledger(project, state)


def tree(root):
    from onecrew.v2.verifiers import command
    return command.artifact_sha(root)


def approved(ledger, name, value, choose=None):
    if getattr(ledger, '_wf_legacy', False):
        # The current creation API deliberately forbids forging an old anchor.
        # Compatibility fixtures are created by the actual archived binary.
        old = ledger._wf_old
        path = ledger.state_root.parent / ('legacy-contract-' + name + '.json')
        path.write_text(json.dumps(value), encoding='utf-8')
        for args in [('plan', 'propose', name, '--file', str(path), '--author', 'claude'),
                     ('plan', 'approve', name, '--by', 'owner', '--reference', 'said yes in chat', *(['--choose', choose] if choose else []))]:
            code, out = old.run(ledger.project, ledger.state_root, *args)
            if code: raise AssertionError(out)
        return plans.show(ledger, name)
    plans.propose(ledger, name, value, 'claude')
    return plans.approve(ledger, name, 'owner', 'said yes in chat', choose=choose)


def pass_all(ledger, name, root, milestones=('M1',)):
    for mid in milestones: verdict.run(ledger, name, mid, root)


def events(ledger, name, kind=None):
    """[(seq, kind, payload)] of the plan's anchor, straight from the ledger (not through the code under test)."""
    with ledger.transaction() as conn:
        task = plans.anchor_events(ledger, conn, name)['task_id']
        rows = conn.execute('SELECT seq, kind, payload, created_at FROM events WHERE task_id=? ORDER BY seq', (task,)).fetchall()
    return [(r['seq'], r['kind'], json.loads(r['payload'])) for r in rows if kind is None or r['kind'] == kind]


def anchor(ledger, name):
    with ledger.transaction() as conn:
        return plans.anchor_events(ledger, conn, name)['task_id']


def count_kind(ledger, kind):
    """Events of `kind` over the WHOLE ledger (all projects)."""
    with ledger.transaction() as conn:
        return conn.execute('SELECT COUNT(*) FROM events WHERE kind=?', (kind,)).fetchone()[0] if conn else 0


def run_cli(argv):
    """The installed router in-process: (exit code, stdout, stderr)."""
    from onecrew.v2 import cli
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


@contextlib.contextmanager
def model_calls():
    """A counter on every door to a model (advisor.call, reviewer.call, the shared CLI finder). Yields the list of calls; the fakes raise, so a
    path that reached a model fails the test as well as being counted."""
    from onecrew.v2 import claude_cli
    from onecrew.v2.verifiers import advisor, reviewer
    calls = []

    def boom(*args, **kwargs):
        calls.append(args)
        raise AssertionError('a model was called')
    with patch.object(advisor, 'call', boom), patch.object(reviewer, 'call', boom), patch.object(claude_cli, 'cli_argv', boom):
        yield calls


@contextlib.contextmanager
def git_log():
    """Every git command the verifier module runs, as argv tuples (the throw-away index commands included)."""
    from onecrew.v2.verifiers import command
    seen = []
    real = command._git

    def spy(directory, *args, **kwargs):
        seen.append(tuple(args))
        return real(directory, *args, **kwargs)
    with patch.object(command, '_git', spy):
        yield seen


def make_world_ledger_rows(ledger):
    with ledger.transaction() as conn:
        return {r['kind']: r['n'] for r in conn.execute('SELECT kind, COUNT(*) n FROM events GROUP BY kind')}
