"""T13b [E3]/[E4], T19 (review a2476ab P1-D): a root approved by the OLD build keeps being workable after the upgrade — its baseline is found from
valid provenance, never from the current tree, and never by turning "unknown" into PASS.

Fixtures are legacy roots created by the archived old binary (ee46539, tests/wf_oldversion), approved with the fixture approval event the old
harness writes (no `at`, no `base_artifact` — the shape of a pre-W05 approval):
  (a) the approval row's ledger time lies AFTER a commit of the project -> the new build takes the last commit before that time as the
      baseline (provenance: the ledger row + git history); the command milestone passes; the integrity base is named in the verdict.
  (b) no commit precedes the approval time -> the verdict is `inconclusive` with the no-baseline reason; the report tells the owner the route;
      an AI session cannot record a baseline; the OWNER records it from a real commit (`verdict baseline`) with a reference; the milestone then
      passes with the recorded baseline; the baseline is not rewritten to another tree; a commit outside the repo is refused.
  (c) a root approved by the NEW build (base_artifact recorded) is unchanged: that artifact is the base, `verdict baseline` is refused.
  (d) a root with an attempt of unknown outcome keeps it (nothing is reconciled or replayed by recording a baseline).
  (e) the old binary still reads the root after the baseline record (class A, S/G/C unchanged); a new root keeps the full integrity check
      (a weakened test is still a U1 fail).
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path

from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import compat, plan as plans, report, verdict
import tests.wf_oldversion as ov

REPO = str(Path(__file__).resolve().parents[1])
BASELINE = 'ee46539'


def _have_git():
    try:
        return subprocess.run(['git', '--version'], capture_output=True).returncode == 0
    except OSError:
        return False


@unittest.skipUnless(_have_git(), 'git required to archive the old version')
class LegacyBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = ov._short_runs()
        cls.old = ov.OldVersion(ov.archive(BASELINE, REPO, cls.runs))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    def setUp(self):
        os.environ.pop('ONECREW_ACTOR', None)
        self.n = getattr(self, '_n', 0) + 1
        self.proj = ov.git_project(self.runs, f'P{id(self) % 10000}-{self.n}')
        self.state = self.runs / f'S{id(self) % 10000}-{self.n}'

    def legacy_root(self, name, approved_at):
        """A root the old binary created, approved by the fixture event with the given ledger row time (no `at`, no base_artifact)."""
        contract = ov.contract(name); contract['milestones'][0]['verifier']['config']['argv'] = [sys.executable, '-c', 'print("ok")']
        f = self.runs / f'c_{name}.json'; f.write_text(json.dumps(contract), encoding='utf-8')
        code, out = self.old.run(self.proj, self.state, 'plan', 'propose', name, '--file', str(f), '--author', 'claude-probe')
        self.assertEqual(code, 0, out)
        pid = ov.project_id(self.state, self.proj); anchor = ov.anchor_id(self.state, pid, 'plan:' + name)
        with ov._db(self.state) as c:
            c.execute('INSERT INTO events(task_id, kind, payload, created_at) VALUES (?,?,?,?)',
                      (anchor, 'plan.approved', json.dumps({'plan': name, 'revision': 1, 'sha': ov._sha(self.state, anchor), 'by': 'owner', 'reference': 'fixture',
                                                             'ticked': [], 'chosen': None, 'base_artifact': None}), approved_at))
            c.commit()
        return Ledger(self.proj, self.state), anchor

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.proj), *args], capture_output=True, text=True, check=True).stdout.strip()

    def test_a_the_ledger_time_of_the_approval_places_the_baseline_at_the_last_commit_before_it(self):
        ledger, _ = self.legacy_root('l1', '2099-01-01T00:00:00+00:00')        # after the project's only commit
        shown = verdict.run(ledger, 'plan:l1', 'M1', self.proj)
        self.assertEqual(shown['milestones'][0]['state'], 'passed')
        with ledger.transaction() as conn:
            state = plans.anchor_events(ledger, conn, 'plan:l1')
        self.assertIn('recorded_at', state['approved']); self.assertNotIn('at', state['approved'])
        self.assertEqual(state['verdicts'][-1]['result'], 'pass')
        self.assertNotIn('test_integrity', state['verdicts'][-1], 'nothing weakened, nothing insufficient: no integrity record is needed')

    def test_b_a_schema2_legacy_root_keeps_the_old_verdict_rule_and_a_recorded_baseline_changes_nothing(self):
        """W11b / T25 [E4] (round 6, decided 25/10 under delegated authority): a schema-2 legacy root runs under the OLD verdict rule — the
        command's result only, no T19 integrity check — so with no commit before its approval it PASSES without any baseline. `verdict
        baseline` still refuses an AI session, a commit outside the repo and an empty reference, records once for the owner (class A, not
        rewritten to another tree, idempotent for the same tree), moves nothing else, and does not change the schema-2 verdict."""
        ledger, anchor = self.legacy_root('l2', '2020-01-01T00:00:00+00:00')    # before every commit of the project
        shown = verdict.run(ledger, 'plan:l2', 'M1', self.proj)
        self.assertEqual(shown['milestones'][0]['state'], 'passed')                                     # old rule: the command passed
        with ledger.transaction() as conn:
            state = plans.anchor_events(ledger, conn, 'plan:l2')
        self.assertNotIn('workflow_version', state)
        last = state['verdicts'][-1]
        self.assertEqual(last['result'], 'pass'); self.assertNotIn('test_integrity', last)               # no T19 record on schema 2
        commit = self.git('rev-parse', 'HEAD')
        os.environ['CLAUDE_CODE_CHILD_SESSION'] = '1'
        try:
            with self.assertRaises(LedgerError):
                verdict.record_baseline(ledger, 'plan:l2', commit, 'owner', 'AI tries', self.proj)      # not an owner decision
        finally:
            os.environ.pop('CLAUDE_CODE_CHILD_SESSION', None)
        with self.assertRaises(LedgerError):
            verdict.record_baseline(ledger, 'plan:l2', 'deadbeefcafe', 'owner', 'not a commit', self.proj)
        with self.assertRaises(LedgerError):
            verdict.record_baseline(ledger, 'plan:l2', commit, 'owner', '   ', self.proj)              # a reference is required
        before = self.rows(anchor)
        view_before = plans.show(ledger, 'plan:l2')['milestones']
        recorded = verdict.record_baseline(ledger, 'plan:l2', commit, 'owner', 'decided in the owner terminal, fixture', self.proj)
        self.assertEqual(recorded['tree'], self.git('rev-parse', commit + '^{tree}'))
        self.assertEqual(compat.event_class(plans.BASELINE_KIND), 'A')
        after = self.rows(anchor)
        self.assertEqual(before['attempts'], after['attempts']); self.assertEqual(before['executions'], after['executions'])   # (d) nothing else moved
        with ledger.transaction() as conn:
            again = plans.anchor_events(ledger, conn, 'plan:l2')
        self.assertEqual(again['verdicts'], state['verdicts'])                                          # the schema-2 verdict is unchanged
        self.assertEqual(plans.show(ledger, 'plan:l2')['milestones'], view_before)
        # the recorded baseline is not rewritten to another tree; recording the same tree again is idempotent
        (self.proj / 'b.txt').write_text('x\n'); self.git('add', 'b.txt'); self.git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'more')
        with self.assertRaisesRegex(LedgerError, 'not rewritten'):
            verdict.record_baseline(ledger, 'plan:l2', self.git('rev-parse', 'HEAD'), 'owner', 'try again', self.proj)
        self.assertEqual(verdict.record_baseline(ledger, 'plan:l2', commit, 'owner', 'same', self.proj)['tree'], recorded['tree'])
        # (e) the old binary still reads the root
        self.assertEqual(self.old.status_of(self.proj, self.state, 'l2')['status'], 'approved')

    def test_c_a_root_approved_by_the_new_build_keeps_its_base_artifact_and_refuses_a_baseline_record(self):
        from tests.test_v2_l1 import plan_json
        ledger = Ledger(self.proj, self.state)
        value = plan_json(); value['milestones'][0]['verifier']['config']['argv'] = [sys.executable, '-c', 'print("ok")']
        plans.propose(ledger, 'N1', value, 'codex'); plans.approve(ledger, 'N1', 'owner', 'fixture')
        with ledger.transaction() as conn:
            approved = plans.anchor_events(ledger, conn, 'N1')['approved']
        self.assertTrue(approved.get('base_artifact'))
        with self.assertRaisesRegex(LedgerError, 'already records'):
            verdict.record_baseline(ledger, 'N1', self.git('rev-parse', 'HEAD'), 'owner', 'no need', self.proj)
        self.assertEqual(verdict.run(ledger, 'N1', 'M1', self.proj)['milestones'][0]['state'], 'passed')

    def rows(self, anchor):
        conn = sqlite3.connect(str(self.state / 'ledger.sqlite3'))
        try:
            out = {}
            for table in ('attempts', 'executions'):
                try: out[table] = [tuple(r) for r in conn.execute(f'SELECT * FROM {table} WHERE task_id=?', (anchor,))]
                except sqlite3.OperationalError: out[table] = []
            return out
        finally:
            conn.close()
