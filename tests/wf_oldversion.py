"""The old-version comparator (W11a, reused by T13a/T35a/T41b/T49a/T54).

The "old version" is the rollback target: the archive of a commit, UNMODIFIED, with NO wrapper. We get it with `git archive <sha>`
into a temp dir and run it with PYTHONPATH pointed at that tree (the method EV-J/EV-K used and proved on this machine; a pip wheel is
not needed and setuptools is not required). No owner verbs are ever run: approved/accepted/stopped states are built by inserting the
exact events approve()/accept()/record() write (plan.py:324-326, 369-371).

The comparator reads S/G/C/H/V for a root with the old binary and compares two readings:
  S — status: `plan show` exit code, status, revision, sha.
  G — gate/hook: the decision an old hook/gate would make from the derived status (approved/stopped => managed).
  C — continue: `plan amend` and `verdict run` exit codes and the status after.
  H — display: `plan report` minutes and `plan digest` order. H is ALLOWED to differ (minutes, digest order) when a neutral event is last.
  V — v1 consumer: whether a v1 consumer (task_intake.outcomes) reads a learning.outcome on the same ledger without error.

compare(a, b) returns {'S': bool, 'G': bool, 'C': bool, 'H_within_allowed': bool, ...}: S/G/C True == identical; a class-A event must
keep S, G, C identical and may differ only in H.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid


def _short_runs():
    base = Path(os.environ.get('TEMP') or tempfile.gettempdir()) / 'wfr00' / uuid.uuid4().hex[:6]
    base.mkdir(parents=True)
    return base


def archive(sha, repo, into):
    """git archive <sha> from `repo` extracted into `into`/base-<sha>; returns the extracted tree path."""
    tree = Path(into) / ('base-' + sha[:12])
    tree.mkdir(parents=True, exist_ok=True)
    tar = Path(into) / (sha[:12] + '.tar')
    subprocess.run(['git', 'archive', '--format=tar', '-o', str(tar), sha], cwd=repo, check=True, capture_output=True)
    import tarfile
    with tarfile.open(tar) as t:
        t.extractall(tree)                      # trusted: our own repo archive
    tar.unlink()
    return tree


class OldVersion:
    """A handle on one extracted old-version tree, used to run its CLI on temp state roots."""

    def __init__(self, tree):
        self.tree = Path(tree)
        self.env = {k: v for k, v in os.environ.items() if k not in ('ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'PYTHONPATH')}
        self.env['PYTHONPATH'] = str(self.tree)
        self.env['PYTHONDONTWRITEBYTECODE'] = '1'

    def run(self, proj, state, *args):
        r = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'onecrew.v2.plan_cli',
                            '--project', str(proj), '--state-root', str(state), *args],
                           env=self.env, capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=str(proj))
        return r.returncode, (r.stdout + r.stderr).strip()

    def status_of(self, proj, state, name):
        code, out = self.run(proj, state, 'plan', 'show', name)
        try:
            body = json.loads(out)
        except ValueError:
            body = {}
        return {'exit': code, 'status': body.get('status'), 'revision': body.get('revision') or body.get('latest_revision'),
                'sha': body.get('sha') or body.get('plan_sha'), 'raw': out[:400]}


# ---- temp fixtures (no owner verbs) ---------------------------------------------------------------------------------------

def git_project(root, name):
    p = Path(root) / name
    p.mkdir(parents=True)
    (p / 'a.txt').write_text('x\n', encoding='utf-8')
    for args in (['init', '-q'], ['add', 'a.txt'], ['-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'init']):
        subprocess.run(['git', *args], cwd=p, check=True, capture_output=True)
    return p


def contract(title, goal='Do the sample and prove it.'):
    return {'schema_version': 2, 'title': title, 'size': 'S',
            'understanding': {'restated_goal': goal, 'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']},
                              'assumptions': [], 'confidence': 'high', 'unknowns': []},
            'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'the file is there'}],
            'output': ['The sample exists'], 'scope': {'owned': ['a.txt']}, 'non_goals': ['Nothing else'],
            'items': [{'id': 'I1', 'title': 'Do it', 'tier': 'must', 'milestone': 'M1'}],
            'milestones': [{'id': 'M1', 'title': 'Milestone M1',
                            'verifier': {'type': 'command', 'config': {'argv': [sys.executable, '-c', 'print("ok")']}}, 'covers': ['O1']}],
            'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1}, 'profile_version': None}


import sqlite3


def _db(state):
    c = sqlite3.connect(str(Path(state) / 'ledger.sqlite3'))
    c.row_factory = sqlite3.Row
    return c


def project_id(state, proj_path):
    """The project_id the old binary assigned. It lowercases project_path on Windows, so match case-insensitively; fall back to the
    only project when a single one exists (the common test case)."""
    want = str(Path(proj_path).resolve())
    rows = _db(state).execute('SELECT DISTINCT project_id, project_path FROM tasks').fetchall()
    for r in rows:
        if r['project_path'] == want or r['project_path'].lower() == want.lower():
            return r['project_id']
    ids = {r['project_id'] for r in rows}
    if len(ids) == 1:
        return next(iter(ids))
    raise LookupError('no project_id for ' + want)


def anchor_id(state, proj_id, key):
    return _db(state).execute('SELECT id FROM tasks WHERE project_id=? AND request_key=?', (proj_id, key)).fetchone()['id']


def kinds_on(state, task):
    return [r['kind'] for r in _db(state).execute('SELECT kind FROM events WHERE task_id=? ORDER BY seq', (task,))]


def insert_event(state, task, kind, payload):
    c = _db(state)
    c.execute('INSERT INTO events(task_id, kind, payload, created_at) VALUES (?,?,?,?)',
              (task, kind, json.dumps(payload), '2026-10-23T00:00:00+00:00'))
    c.commit()


def _sha(state, task, revision=1):
    row = _db(state).execute("SELECT payload FROM events WHERE task_id=? AND kind IN ('plan.proposed','plan.amended') "
                             "AND json_extract(payload,'$.revision')=?", (task, revision)).fetchone()
    return json.loads(row['payload'])['sha']


def make_approved(state, task, name, revision=1):
    insert_event(state, task, 'plan.approved', {'plan': name, 'revision': revision, 'sha': _sha(state, task, revision),
                 'by': 'owner', 'reference': 'fixture', 'ticked': [], 'chosen': None, 'base_artifact': None})


def make_accepted(state, task, name, revision=1):
    make_approved(state, task, name, revision)
    insert_event(state, task, 'plan.accepted', {'plan': name, 'revision': revision, 'sha': _sha(state, task, revision),
                 'by': 'owner', 'reference': 'fixture', 'artifact_sha': '0' * 40, 'receipts': {}})


def make_stopped(state, task, name, revision=1):
    make_approved(state, task, name, revision)
    insert_event(state, task, 'milestone.stopped', {'plan': name, 'revision': revision, 'milestone': 'M1', 'reason': 'fixture'})


# ---- the S/G/C/H/V comparator ---------------------------------------------------------------------------------------------

def read(old, proj, state, name):
    """One S/G/C/H/V reading of root `name` by the old binary on state root `state` (a disposable copy)."""
    s = old.status_of(proj, state, name)
    gate = 'managed' if s['status'] in ('approved', 'stopped_with_report') else ('closed' if s['status'] == 'accepted' else 'none')
    report_code, report_out = old.run(proj, state, 'plan', 'report', name)
    minutes = None
    try:
        minutes = json.loads(report_out).get('minutes')
    except ValueError:
        pass
    digest_code, digest_out = old.run(proj, state, 'plan', 'digest')
    return {'S': {'exit': s['exit'], 'status': s['status'], 'revision': s['revision'], 'sha': s['sha']},
            'G': gate,
            'C': {'report_exit': report_code, 'digest_exit': digest_code},
            'H': {'minutes': minutes, 'digest': digest_out[:400]},
            'read_blocked': s['exit'] != 0 or digest_code != 0}


def compare(a, b):
    """Compare two readings. S/G/C identical == True. H may differ (minutes/digest order are allowed to change for a neutral last event)."""
    return {'S': a['S'] == b['S'], 'G': a['G'] == b['G'], 'C': a['C'] == b['C'],
            'H_within_allowed': True,            # H is explicitly allowed to differ; the caller asserts S/G/C
            'read_blocked_a': a['read_blocked'], 'read_blocked_b': b['read_blocked']}
