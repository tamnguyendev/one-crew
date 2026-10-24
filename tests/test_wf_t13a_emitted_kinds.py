"""T13a [E1], [E2] (W11a): the kinds the CURRENT code really writes on a legacy `plan:` anchor are each class 0 or A, checked against
what was actually emitted (not a hand-written list), and the REAL old binary still reads the root afterwards.

A legacy root is created by the archived old binary (ee46539); then the current code approves it, runs its command verifier, records a
decision, writes context, a forecast, an exception observation and reads report/present. Every event the current code added to that anchor
must be class 0 or A (`compat.event_class`), and the old binary's `plan show` must still read the same status. Counter-examples: a class-B
kind and an unknown kind on the same anchor are refused before any write. A new root (workflow=True) declares its workflow version and
capabilities ([E2]).
"""
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import compat, context, estimates, exceptions, plan as plans, report, verdict
import tests.wf_oldversion as ov

REPO = str(Path(__file__).resolve().parents[1])
BASELINE = 'ee46539'


def _have_git():
    try:
        return subprocess.run(['git', '--version'], capture_output=True).returncode == 0
    except OSError:
        return False


@unittest.skipUnless(_have_git(), 'git required to archive the old version')
class EmittedKindsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = ov._short_runs()
        cls.old = ov.OldVersion(ov.archive(BASELINE, REPO, cls.runs))
        cls.proj = ov.git_project(cls.runs, 'P1')
        cls.state = cls.runs / 'S'

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    def kinds_on(self, ledger, selector):
        with ledger.transaction() as conn:
            task = plans.anchor_events(ledger, conn, selector)['task_id']
            return [row['kind'] for row in conn.execute('SELECT kind FROM events WHERE task_id=? ORDER BY seq', (task,))]

    def test_e1_every_kind_the_current_code_writes_on_a_legacy_anchor_is_class_0_or_a_and_the_old_binary_still_reads_it(self):
        contract = ov.contract('L1'); contract['milestones'][0]['verifier']['config']['argv'] = [sys.executable, '-c', 'print("ok")']
        f = self.runs / 'c_l1.json'; f.write_text(json.dumps(contract), encoding='utf-8')
        code, out = self.old.run(self.proj, self.state, 'plan', 'propose', 'l1', '--file', str(f), '--author', 'claude-probe')
        self.assertEqual(code, 0, out)
        ledger = Ledger(self.proj, self.state)
        before = self.kinds_on(ledger, 'plan:l1')
        plans.approve(ledger, 'plan:l1', 'owner', 'fixture', estimate={'execution_seconds': [60, 120], 'evidence': ['fixture decomposition']})
        shown = verdict.run(ledger, 'plan:l1', 'M1', self.proj)
        self.assertEqual(shown['milestones'][0]['state'], 'passed')
        with ledger.transaction() as conn:
            task = plans.anchor_events(ledger, conn, 'plan:l1')['task_id']
            event = conn.execute("SELECT seq FROM events WHERE task_id=? AND kind='milestone.passed'", (task,)).fetchone()[0]
        context.observe(ledger, 'plan:l1', {'type': 'task_done', 'text': 'M1 done', 'source': {'type': 'event', 'id': event}})
        estimates.reforecast(ledger, 'plan:l1', 'eta1', [30, 60], 'half done', ['fixture:eta'])
        exceptions.observe(ledger, 'plan:l1')
        verdict.status(ledger, 'plan:l1')
        report.render_report(self.state, 'l1'); report.render_present(self.state, 'l1')
        after = self.kinds_on(ledger, 'plan:l1')
        written = after[len(before):]
        self.assertTrue(written, 'the current code wrote something')
        classes = {kind: compat.event_class(kind) for kind in written}
        self.assertEqual({k: c for k, c in classes.items() if c not in ('0', 'A')}, {}, classes)      # [E1] on what was really written
        self.assertTrue({'verdict.run_started', 'verdict.receipt_issued', 'verdict.recorded', 'context.entry', 'estimate.eta'} <= set(written))
        self.assertEqual(self.old.status_of(self.proj, self.state, 'l1')['status'], 'approved')         # the old binary still reads S
        for bad in ('plan.revoked', 'node.started', 'verdict.run_reconciled-unknown-kind'):
            with self.assertRaises(LedgerError):
                with ledger.transaction(write=True) as conn:
                    plans.emit(ledger, conn, task, bad, {'plan': 'l1', 'revision': 1})               # class B / unknown: refused, nothing written
        self.assertEqual(self.kinds_on(ledger, 'plan:l1'), after)

    def test_e2_a_new_root_declares_its_workflow_version_and_capabilities(self):
        ledger = Ledger(self.proj, self.runs / 'S2')
        from tests.test_v2_l1 import plan_json
        plans.propose(ledger, 'N1', plan_json(), 'codex', workflow=True, capabilities=['namespaced-storage'])
        with ledger.transaction() as conn:
            state = plans.anchor_events(ledger, conn, 'N1')
        self.assertTrue(state.get('workflow_version')); self.assertIn('namespaced-storage', state['capabilities'])
        self.assertTrue(state['selector'].startswith('plan-ns:'))
