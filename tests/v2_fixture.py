"""Git-backed plan fixtures shared by checkout and installed-wheel tests."""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
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
        """Model the paired start and issuance from a completed verifier attempt."""
        now = dt.datetime.now(dt.timezone.utc)
        attempt = {'plan': 'P1', 'revision': revision, 'milestone': milestone, 'run_id': uuid.uuid4().hex[:12]}
        with self.ledger.transaction(write=True) as conn:
            state = plans.derive(self.ledger, conn, 'P1')
            contract = plans.load(self.ledger, state, revision)[0]
            kind = next(m['verifier']['type'] for m in contract['milestones'] if m['id'] == milestone)
            plans.emit(self.ledger, conn, state['task_id'], 'verdict.run_started',
                       dict(attempt, kind=kind, pid=os.getpid(), host='fixture', max_minutes=1, started=now.isoformat(),
                            deadline=(now + dt.timedelta(minutes=1)).isoformat()))
            plans.emit(self.ledger, conn, state['task_id'], 'verdict.receipt_issued', dict(attempt, receipt=blob))

    def receipt(self, **fields):
        body = {'kind': 'command-receipt', 'plan': 'P1', 'revision': 1, 'milestone': 'M1', 'argv': OK, 'exit_code': 0, 'timed_out': False,
                'error': None, 'artifact_sha': self.tree(), 'artifact_sha_after': self.tree()}
        with self.ledger.transaction() as conn:
            body['plan_sha'] = plans.derive(self.ledger, conn, 'P1')['revisions'][1]['sha']
        body.update(fields)
        return Snapshots(self.ledger.state_root).blob(json.dumps(body, sort_keys=True).encode()), body


def option(oid, evidence=('x/y.py:1',), **extra):
    return dict({'id': oid, 'summary': f'Option {oid}', 'evidence': list(evidence), 'strengths': ['simple'], 'weaknesses': ['slow'],
                 'unknowns': [], 'cost': '3 calls', 'risk': 'low'}, **extra)


def options(*ids, recommended=None):
    return {'recommended': recommended or ids[0], 'reason': 'cheapest that works', 'items': [option(i) for i in ids]}


def step0_json(size='M', unknowns=(), assumptions=(('the file is text', 'a.txt:1'),), confidence='high', opts='default', pre=None, **extra):
    value = plan_json(size=size)
    value['understanding'] = {'restated_goal': 'Prove the sample.', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']},
                              'assumptions': [{'text': t, 'evidence': e} for t, e in assumptions], 'confidence': confidence,
                              'unknowns': [{'id': u, 'question': f'What about {u}?', 'status': 'open', 'closed_by': None, 'evidence': None,
                                            'affected': ['O1'], 'required_by': 'approval'} for u in unknowns]}   # W31a: an open unknown is scoped at proposal
    if size != 'S' and not unknowns:      # 2.2.0.dev2: size M/L with no unknowns says what was checked (unknowns_missing)
        value['understanding']['no_unknowns_because'] = 'read a.txt:1 and the sample has one path; nothing is open'
    value['options'] = options('A', 'B') if opts == 'default' and size != 'S' else (None if opts == 'default' else opts)
    if value['options'] is None: del value['options']
    value['preconditions'] = pre or value['preconditions']
    return dict(value, **extra)


ORIGIN = {'by': 'owner', 'at': '2026-10-19', 'quote': 'Add the sample file and prove it works.'}
DECISION = {'id': 'D1', 'choice': 'Plain text file', 'alternative': 'JSON file', 'cost': 'None'}
AUTHOR = 'claude-fable-5-1'


OWNER_PART = {'request': 'Thêm tệp mẫu và chứng minh nó dùng được.', 'user_sees': ['Tệp mẫu có trong dự án.'],
              'acceptance_steps': ['Mở tệp mẫu và đọc nội dung.'], 'not_doing': 'Không sửa phần nào khác.'}   # dev12 (U1): approve needs it once the owner rules exist


def sourced(value, source='origin', **extra):
    """`value` with an origin, the owner part and every item pointing at `source` (plus any extra fields)."""
    value = dict(value, origin=dict(ORIGIN), **{'presentation': dict(OWNER_PART), **extra})
    value['items'] = [dict(i, source=source) for i in value['items']]
    return value


def size_m():
    """A size M contract that passes the rest of step 0 (options whose evidence is a real file)."""
    return step0_json(size='M', opts={'recommended': 'A', 'reason': 'cheapest', 'items': [option('A', evidence=('a.txt:1',)), option('B', evidence=('a.txt:1',))]})


def answers(*verdicts, note='fine'):
    return json.dumps({'answers': [{'id': f'Q{n}', 'verdict': v, 'note': note} for n, v in enumerate(verdicts or ('ok', 'ok', 'ok'), 1)]})


class AdvisorFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.prompts = []
        self.reply = answers()

    def stub(self):
        from onecrew.v2.verifiers import advisor
        def fake(prompt, model, env, scratch, limit):
            self.prompts.append((prompt, model, scratch))
            return self.reply, {'num_turns': 1}, None, False, b'RAW-OUTPUT'
        patcher = patch.object(advisor, 'call', fake); patcher.start(); self.addCleanup(patcher.stop)

    def start(self, author=AUTHOR, rules=True, **extra):
        from onecrew.v2.verifiers import advisor
        self.stub()
        if rules: advisor.init_rules(self.ledger)
        plans.propose(self.ledger, 'P1', sourced(plan_json(), decisions=[DECISION], **extra), author)

    def advice(self):
        with self.ledger.transaction() as conn:
            return plans.derive(self.ledger, conn, 'P1')['advice'].get(1)
