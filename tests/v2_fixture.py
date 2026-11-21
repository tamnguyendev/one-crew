"""Git-backed plan fixtures shared by checkout and installed-wheel tests."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger
from onecrew.snapshots import Snapshots
from onecrew.v2 import plan as plans
from onecrew.v2.verifiers import command

PY = sys.executable
OK = [PY, '-c', 'print("ok")']
BAD = [PY, '-c', 'raise SystemExit(3)']


def milestone(mid='M1', argv=OK, **extra):
    return dict({'id': mid, 'title': 'Milestone ' + mid, 'verifier': {'type': 'command', 'config': {'argv': argv}}, 'covers': ['O1']}, **extra)


def plan_json(milestones=None, **extra):
    # L3: the smallest contract that passes step 0 (size S: no options; one precondition; nothing open). tests/test_v2_l3.py covers step 0 itself.
    value = {'schema_version': 2, 'title': 'Sample', 'size': 'S',
             'understanding': {'restated_goal': 'Do the sample and prove it.', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']},
                               'assumptions': [], 'confidence': 'high', 'unknowns': []},
             'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'the file to work on is there'}],
             'output': ['The sample exists'],
             'scope': {'owned': ['a.txt']}, 'non_goals': ['Nothing else'],
             'items': [{'id': 'I1', 'title': 'Do it', 'tier': 'must', 'milestone': 'M1'},
                       {'id': 'S1', 'title': 'Nice to have', 'tier': 'should'}, {'id': 'W1', 'title': 'Never', 'tier': 'wont'}],
             'milestones': milestones or [milestone()], 'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1},
             'profile_version': None}
    return dict(value, **extra)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / 'project'; self.root.mkdir()
        self.git('init', '-q'); self.git('config', 'user.name', 'T'); self.git('config', 'user.email', 't@localhost')
        (self.root / 'a.txt').write_text('one\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'base')
        self.ledger = Ledger(self.root, base / 'state')
        env = patch.dict(os.environ); env.start(); self.addCleanup(env.stop)
        for name in ('ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(name, None)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.PIPE).decode().strip()

    def propose(self, name='P1', value=None):
        return plans.propose(self.ledger, name, value or plan_json(), 'claude')

    def approved(self, name='P1', value=None, **kw):
        self.propose(name, value)
        return plans.approve(self.ledger, name, 'owner', 'said yes in chat', **kw)

    def events(self, name='P1'):
        with self.ledger.transaction() as conn:
            task = plans.derive(self.ledger, conn, name)['task_id']
        return [(e['kind'], e['payload']) for e in self.ledger.events(task)]

    def kinds(self, name='P1'):
        return [k for k, _ in self.events(name)]

    def tree(self):
        return command.artifact_sha(self.root)

    def issue(self, blob, milestone='M1', revision=1):
        """What verdict.run does just before it records: announce the receipt it made."""
        with self.ledger.transaction(write=True) as conn:
            task = plans.derive(self.ledger, conn, 'P1')['task_id']
            plans.emit(self.ledger, conn, task, 'verdict.receipt_issued', {'plan': 'P1', 'revision': revision, 'milestone': milestone, 'receipt': blob})

    def receipt(self, **fields):
        body = {'kind': 'command-receipt', 'plan': 'P1', 'revision': 1, 'milestone': 'M1', 'argv': OK, 'exit_code': 0, 'timed_out': False,
                'error': None, 'artifact_sha': self.tree(), 'artifact_sha_after': self.tree()}
        with self.ledger.transaction() as conn:
            body['plan_sha'] = plans.derive(self.ledger, conn, 'P1')['revisions'][1]['sha']
        body.update(fields)
        return Snapshots(self.ledger.state_root).blob(json.dumps(body, sort_keys=True).encode()), body
