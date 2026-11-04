"""2.4-S1 review P3b (S1-R14): the released 2.2.0.dev18 and 2.3.0.dev10 wheels still read a ledger that holds 2.4 support records.

The ledger is written by this checkout: an approved plan P1, a report (support anchor `support:records` with support.feedback), a classification,
a link to P1 and an owner confirmation. Each old wheel is installed offline in its own venv under the run's TEMP (D:/OneCrewRuns/v24/tmp-int when
run through run_regress.sh) and runs `plan show P1`, `compat scan` and `notifications pull` against that ledger from a cwd outside the checkout:
exit 0, the plan still readable with the same status, no traceback. Skipped when the release package folder is not on this machine.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from onecrew.ledger import Ledger
from onecrew.v2 import plan as plans, support
from tests import wf_wheel as wh
from tests.test_v2_l1 import plan_json

PACKAGE = Path('D:/OneCrewRuns/v23/pkg/onecrew-2.3.0.dev10-beta/wheel')
WHEELS = {'2.2.0.dev18': PACKAGE / 'previous' / 'onecrew-2.2.0.dev18-py3-none-any.whl', '2.3.0.dev10': PACKAGE / 'onecrew-2.3.0.dev10-py3-none-any.whl'}


@unittest.skipUnless(all(p.is_file() for p in WHEELS.values()), 'the 2.3.0.dev10 release package is not on this machine')
class OldReadersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = Path(tempfile.gettempdir()) / ('s1-old-' + uuid.uuid4().hex[:6]); cls.runs.mkdir()
        cls.pythons = {}
        for version, wheel in WHEELS.items():
            python = wh.make_venv(cls.runs / ('venv ' + version))
            wh.install(python, wheel)
            cls.pythons[version] = python
        cls.project = cls.runs / 'project'; cls.project.mkdir()
        git = lambda *a: subprocess.run(['git', '-C', str(cls.project), *a], check=True, capture_output=True)
        git('init', '-q'); git('config', 'user.name', 'T'); git('config', 'user.email', 't@localhost')
        (cls.project / 'a.txt').write_text('one\n'); git('add', '.'); git('commit', '-q', '-m', 'base')
        cls.state = cls.runs / 'state'
        saved = {k: os.environ.pop(k) for k in ('ONECREW_ACTOR', 'CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE') if k in os.environ}
        try:
            ledger = Ledger(cls.project, cls.state)
            plans.propose(ledger, 'P1', plan_json(), 'claude')
            plans.approve(ledger, 'P1', 'owner', 'fixture approval')
            cls.status = plans.show(ledger, 'P1')['status']
            made = support.report(ledger, text='an error report the old readers must survive', plan='P1')
            support.classify(ledger, made['id'], 'task_result', ['event:1'])
            support.link(ledger, made['id'], plan='P1')
            support.confirm(ledger, made['id'], 'fixture owner')
        finally:
            os.environ.update(saved)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    def run_old(self, version, *args):
        exe = self.pythons[version].parent / 'onecrew.exe'
        env = {k: v for k, v in os.environ.items() if k.upper() not in ('PYTHONPATH', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'ONECREW_ACTOR')}
        env['LOCALAPPDATA'] = str(self.runs / 'localappdata')
        done = subprocess.run([str(exe), '--project', str(self.project), '--state-root', str(self.state), *args], capture_output=True, text=True,
                              encoding='utf-8', errors='replace', cwd=self.runs, env=env)
        return done.returncode, done.stdout, done.stderr

    def test_old_wheels_read_a_ledger_with_support_records(self):
        with Ledger(self.project, self.state).transaction() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM tasks WHERE request_key=?', (support.ANCHOR_KEY,)).fetchone()[0], 1)
        for version in WHEELS:
            with self.subTest(version=version):
                code, out, err = self.run_old(version, 'plan', 'show', 'P1')
                self.assertEqual(code, 0, out + err); self.assertNotIn('Traceback', out + err)
                self.assertEqual(json.loads(out)['status'], self.status)
                code, out, err = self.run_old(version, 'compat', 'scan', '--json')
                self.assertEqual(code, 0, out + err); self.assertNotIn('Traceback', out + err)
                self.assertEqual(json.loads(out)['blocking']['read'], 0)
                code, out, err = self.run_old(version, 'notifications', 'pull', '--consumer', 'old-' + version.replace('.', '-'))
                self.assertEqual(code, 0, out + err); self.assertNotIn('Traceback', out + err)
                self.assertTrue(json.loads(out)['read_does_not_ack'])
