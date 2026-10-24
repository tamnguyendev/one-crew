"""T33a [E1] (W40): the R00 scenarios run with the INSTALLED build's own code and commands, not the checkout.

From an offline temporary wheel installation (tests/wf_wheel): a forbidden plan name is refused before any write (T48a E1/E5); a class-B
kind and an unknown kind on a legacy `plan:` anchor are refused by the installed compat guard (T13a E12); a reply attributed to the user
is refused inside an AI session by the installed ledger (T20 E5); `compat scan` runs read-only on a temporary state root (T49a E4); a
command milestone runs end to end through the installed `onecrew` CLI. Every module loaded comes from the venv (boundary check), never
from the checkout.
"""
import json
import shutil
import unittest

from onecrew.v2 import boundary
from tests import wf_wheel as wh
from tests.test_v2_l1 import plan_json


class InstalledR00ScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = wh._runs()
        cls.wheel, _, (modules, packages) = wh.build_wheel(cls.runs)
        cls.python = wh.make_venv(cls.runs)
        wh.install(cls.python, cls.wheel)
        cls.ctx = wh.build_ctx(cls.python, modules, packages)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    def setUp(self):
        from tests.wf_env import owner_terminal
        owner_terminal(self)

    def check_body(self, body, env_extra=None):
        dump, tail = wh.run_case(self.python, body, cwd=self.runs, env_extra=env_extra)
        self.assertIsNotNone(dump, tail)
        self.assertEqual(boundary.violations(dump['end'], self.ctx), [], tail)

    def test_r00_scenarios_run_from_the_installed_build(self):
        contract = json.dumps(plan_json())
        self.check_body('''
import json, os, sys, subprocess, tempfile, hashlib
from pathlib import Path
from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import plan, verdict, compat, compat_scan, report
with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)/'project'; root.mkdir()
    def git(*args):
        subprocess.run(['git','-C',str(root),*args], check=True, capture_output=True)
    git('init','-q'); git('config','user.name','Fixture'); git('config','user.email','fixture@localhost')
    (root/'a.txt').write_text('base\\n'); git('add','.'); git('commit','-qm','base')
    state = Path(temp)/'state'; ledger = Ledger(root, state)
    contract = json.loads(''' + repr(contract) + ''')
    contract['milestones'][0]['verifier']['config']['argv'] = [sys.executable,'-c','print("ok")']
    # T48a E1/E5: forbidden names refused before any write (installed code)
    before = sorted(p.as_posix() for p in state.rglob('*')) if state.exists() else []
    for bad in ('a:b', 'x/y', '..', 'C:x', '/abs'):
        try:
            plan.propose(ledger, bad, contract, 'codex'); raise AssertionError('accepted ' + bad)
        except LedgerError as error:
            assert 'refused' in str(error)
    after = sorted(p.as_posix() for p in state.rglob('*')) if state.exists() else []
    assert before == after, (before, after)
    # a legacy-style root proposed by the installed code, then the compat guard
    plan.propose(ledger, 'P1', contract, 'codex')
    with ledger.transaction() as conn:
        anchor = plan.anchor_events(ledger, conn, 'P1')
    for kind in ('plan.revoked', 'no.such_kind'):
        try:
            compat.check_write(kind, {'plan': 'P1', 'revision': 1}, 'plan:P1'); raise AssertionError(kind)
        except LedgerError:
            pass
    assert compat.check_write('verdict.run_started', {'plan': 'P1', 'revision': 1}, 'plan:P1') is None
    # T20 E5: a reply attributed to the user is refused inside an AI session by the installed ledger (the v1 ledger CLI is not in the wheel)
    req = ledger.create_request(anchor['task_id'], 'q1', {'schema_version': 1, 'question': 'Allow?', 'reason': 'r', 'impact': 'i',
          'options': [{'id': 'yes', 'label': 'Yes'}, {'id': 'no', 'label': 'No'}], 'recommendation': 'no', 'action': {'type': 'authorize', 'parameters': {}}})
    os.environ['CLAUDE_CODE_CHILD_SESSION'] = '1'
    try:
        ledger.reply(req['id'], req['revision'], 'no', decided_by='user'); raise AssertionError('user reply accepted inside an AI session')
    except LedgerError as error:
        assert 'AI tool session' in str(error), error
    finally:
        os.environ.pop('CLAUDE_CODE_CHILD_SESSION', None)
    assert ledger.request(req['id'])['state'] == 'pending'
    # the milestone runs end to end with the installed `onecrew` console script (this venv), then report/present render
    plan.approve(ledger, 'P1', 'owner', 'fixture')
    exe = Path(sys.executable).with_name('onecrew' + ('.exe' if os.name == 'nt' else ''))               # the wheel's console script, in this venv
    assert exe.exists(), exe
    done = subprocess.run([str(exe), '--project', str(root), '--state-root', str(state), 'verdict', 'run', '--plan', 'P1', '--milestone', 'M1'],
                          capture_output=True, text=True, encoding='utf-8', env={**os.environ, 'PYTHONUTF8': '1'})
    assert done.returncode == 0, done.stdout[-400:] + done.stderr[-400:]
    assert plan.show(ledger, 'P1')['milestones'][0]['state'] == 'passed', plan.show(ledger, 'P1')['milestones']
    assert 'P1' in report.render_report(state, 'P1')
    # T49a E4: the compat scan is read-only on this state root
    digest = lambda: hashlib.sha256((state/'ledger.sqlite3').read_bytes()).hexdigest()
    h = digest(); scan = compat_scan.scan(state); assert digest() == h and scan['roots'], scan
''')
