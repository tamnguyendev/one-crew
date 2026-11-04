"""Round 7 / T49d (R04, W40-R04/W46b/W12b/W41) — E6, E7, E12 on the S2 fixture of tests.test_wf_namespace_compat with the REAL archived old code.

What "rollback" means here: after the gate (tests.wf_rollback.rollback_drill, the same gate wfkit.upgrade_drill.guard_swap reuses) reports 0
blocks on the exact ledger hash, every later command is run by the UNMODIFIED archive of d3120c6 (the scanner's pre-namespace baseline, built
before R04), from the root's own project, on a disposable copy of S2; "roll-forward" is the current code reading the same copy again. No
installation is swapped (no venv, no wheel): the per-case rollback-script exit code and the venv package list of [E5] are NOT proven here.
No owner verb runs: approved/accepted/stopped are the exact events those verbs write (tests/wf_oldversion.py), and active-plan files are written
as the hooks' export would.

N5: R2 accepted + active plan of P2 re-exported as accepted, R4 and DUPk accepted. N6: the owner removed P2's active plan (U2, simulated),
R2 still approved; R4 and DUPk accepted. DUPa is approved (05 T49 fixture table). R3 has spent budget (one verdict run by the new code).
"""
import hashlib
import json
import shutil
import sqlite3
import unittest
import uuid
from unittest.mock import patch

from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import active_plan, compat_scan, plan, verdict
import tests.test_wf_namespace_compat as base
from tests import wf_oldversion as ov
from tests.wf_rollback import rollback_drill

LABELS = {'R1': (0, 'plan:r1'), 'R4': (0, 'plan:r4'), 'R2': (1, 'plan-ns:r2'), 'R3': (0, 'plan-ns:r3'), 'DUPa': (0, 'plan:dup'),
          'DUPb': (1, 'plan-ns:dup'), 'DUPk': (2, 'plan:dup')}


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dir_hash(path):
    digest = hashlib.sha256()
    for p in sorted(path.rglob('*')):
        if p.is_file(): digest.update(p.relative_to(path).as_posix().encode() + b'\0' + p.read_bytes() + b'\0')
    return digest.hexdigest()


def snapshot(state):
    """Every retained SQL row (tasks, events, requests, ...) and every file hash except the sqlite file itself and active-plan exports."""
    conn = sqlite3.connect((state / 'ledger.sqlite3').as_uri() + '?mode=ro', uri=True)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        rows = {t: {json.dumps(list(r), default=str) for r in conn.execute(f'SELECT * FROM "{t}"')} for t in tables}
        events = {r[0]: r[1] for r in conn.execute('SELECT seq, task_id FROM events')}
    finally:
        conn.close()
    files = {p.relative_to(state).as_posix(): file_sha(p) for p in state.rglob('*') if p.is_file()
             and not p.name.startswith('ledger.sqlite3') and p.name != 'active-plan.json'}
    return {'rows': rows, 'files': files, 'events': events}


def spent(state, task):
    """Budget spent by a root, read from the ledger (not through the code under test): its milestone runs (verdict.recorded) and attention marks."""
    conn = sqlite3.connect(str(state / 'ledger.sqlite3'))
    try:
        return tuple(conn.execute('SELECT COUNT(*) FROM events WHERE task_id=? AND kind=?', (task, kind)).fetchone()[0]
                     for kind in ('verdict.recorded', 'attention.exceeded'))
    finally:
        conn.close()


class T49dRollbackRollForward(base.NamespaceCompatTests):
    for _name in [n for n in dir(base.NamespaceCompatTests) if n.startswith('test_')]:
        locals()[_name] = None
    del _name

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._rolled = None

    def tearDown(self):
        for project in self.projects:                       # the old binary may export the hooks' file into a shared fixture project
            (project / '.onecrew' / 'active-plan.json').unlink(missing_ok=True)

    # ---- fixtures -----------------------------------------------------------------------------------------------------------
    def ledger_of(self, state, label):
        return Ledger(self.projects[LABELS[label][0]], state)

    def prepared(self, case):
        state = self.copy()
        ov.make_approved(state, self.ids['DUPa'], 'dup')
        with patch.object(active_plan, 'export', lambda *a, **k: None):      # R3 has spent budget; no active plan points at it
            verdict.run(self.ledger_of(state, 'R3'), 'plan-ns:r3', 'M1', self.projects[0])
        for label in ('R4', 'DUPk') + (('R2',) if case == 'N5' else ()):
            self.accept(state, label)
        if case == 'N5': self.write_active(state, 'accepted')
        else: (state / self.active_relative).unlink()
        return state

    def run_old(self, label_or_index, state, *args):
        index = LABELS[label_or_index][0] if isinstance(label_or_index, str) else label_or_index
        return self.old.run(self.projects[index], state, *args)

    def changed_file(self, title):
        path = self.runs / (title.replace(' ', '-') + '.json')
        path.write_text(json.dumps(ov.contract(title)), encoding='utf-8')
        return str(path)

    def rolled_back(self):
        """N5 on one copy: gate, receipt, then the step-3 old-version commands. Built once; every later test reads it."""
        cls = type(self)
        if cls._rolled: return cls._rolled
        state = self.prepared('N5')
        gate = rollback_drill(state)
        at_start = file_sha(state / 'ledger.sqlite3')                       # the ledger as the rollback starts
        before = snapshot(state)
        spent_before = {label: spent(state, self.ids[label]) for label in LABELS}
        readings = {label: self.new_reading(state, label) for label in LABELS}
        dup_p1 = state / 'plans' / 'dup'
        out = {'gate': gate, 'at_start': at_start, 'before': before, 'spent_before': spent_before, 'state': state, 'cmd': {}, 'dup': {}, 'readings': readings}
        run = lambda key, label, *args: out['cmd'].__setitem__(key, self.run_old(label, state, *args))
        out['dup']['start'] = dir_hash(dup_p1)
        run('R1 verdict', 'R1', 'verdict', 'run', '--plan', 'r1', '--milestone', 'M1')
        run('R1 amend', 'R1', 'plan', 'amend', 'r1', '--file', self.changed_file('R1 continued after rollback'), '--reason', 'continue after rollback', '--author', 'codex-fixture')
        run('R1 show', 'R1', 'plan', 'show', 'r1')
        for label, name in (('R2', 'r2'), ('R3', 'r3'), ('DUPb', 'dup')):
            run(f'{label} show', label, 'plan', 'show', name)
            run(f'{label} amend', label, 'plan', 'amend', name, '--file', self.changed_file(f'{label} amended'), '--reason', 'fixture', '--author', 'codex-fixture')
            run(f'{label} verdict', label, 'verdict', 'run', '--plan', name, '--milestone', 'M1')
        run('R4 amend', 'R4', 'plan', 'amend', 'r4', '--file', self.changed_file('R4 amended'), '--reason', 'fixture', '--author', 'codex-fixture')
        run('DUPk amend', 'DUPk', 'plan', 'amend', 'dup', '--file', self.changed_file('DUPk amended'), '--reason', 'fixture', '--author', 'codex-fixture')
        out['dup']['after_refusals'] = dir_hash(dup_p1)
        run('DUPa amend', 'DUPa', 'plan', 'amend', 'dup', '--file', self.changed_file('DUPa amended'), '--reason', 'fixture', '--author', 'codex-fixture')
        out['dup']['after_dupa'] = dir_hash(dup_p1)
        run('propose dup P2', 1, 'plan', 'propose', 'dup', '--file', self.changed_file('P2 dup'), '--author', 'codex-fixture')
        run('propose r2 P2', 1, 'plan', 'propose', 'r2', '--file', self.changed_file('P2 r2 again'), '--author', 'codex-fixture')
        out['dup']['end'] = dir_hash(dup_p1)
        cls._rolled = out
        return out

    # ---- [E6] ---------------------------------------------------------------------------------------------------------------
    def test_e6_n5_n6_last_scan_zero_with_the_ledger_hash_of_the_rollback_start(self):
        for case in ('N5', 'N6'):
            with self.subTest(case=case):
                state = self.prepared(case)
                gate = rollback_drill(state)
                self.assertTrue(gate['ran'], gate.get('conditions'))
                self.assertEqual(gate['scan']['blocking']['total'], 0)
                self.assertEqual([b for r in gate['scan']['roots'] for b in r['blocks']], [])
                self.assertEqual(gate['ledger_sha'], file_sha(state / 'ledger.sqlite3'))      # hash in the receipt == ledger as the rollback starts
        rolled = self.rolled_back()
        self.assertTrue(rolled['gate']['ran'])
        self.assertEqual(rolled['gate']['ledger_sha'], rolled['at_start'])

    def test_e6_counter_a_receipt_from_before_the_last_change_does_not_match(self):
        state = self.prepared('N5')
        early = compat_scan.scan(state)
        ov.make_stopped(state, self.ids['DUPa'], 'dup')                    # a change after that scan
        self.assertNotEqual(early['ledger_sha'], file_sha(state / 'ledger.sqlite3'))

    def test_e6_r1_reads_and_continues_with_the_old_version(self):
        cmd = self.rolled_back()['cmd']
        self.assertEqual(cmd['R1 verdict'][0], 0, cmd['R1 verdict'])
        self.assertEqual(cmd['R1 amend'][0], 0, cmd['R1 amend'])
        self.assertEqual(cmd['R1 show'][0], 0, cmd['R1 show'])
        shown = json.loads(cmd['R1 show'][1])
        self.assertEqual(shown['latest_revision'], 2)

    def test_e6_frozen_roots_answer_no_plan_named(self):
        cmd = self.rolled_back()['cmd']
        for label in ('R2', 'R3', 'DUPb'):
            for verb in ('show', 'amend', 'verdict'):
                code, out = cmd[f'{label} {verb}']
                with self.subTest(root=label, verb=verb):
                    self.assertNotEqual(code, 0, out)
                    self.assertIn('No plan named', out)

    def test_e6_accepted_r4_and_dupk_refuse_amend_and_p1_dup_changes_only_by_dupa(self):
        rolled = self.rolled_back()
        cmd, dup = rolled['cmd'], rolled['dup']
        for label in ('R4', 'DUPk'):
            code, out = cmd[f'{label} amend']
            self.assertNotEqual(code, 0, out)
            self.assertIn('accepted', out)
        self.assertEqual(dup['after_refusals'], dup['start'], 'plans/dup/ of P1 changed before the DUPa amend')
        self.assertEqual(cmd['DUPa amend'][0], 0, cmd['DUPa amend'])
        self.assertNotEqual(dup['after_dupa'], dup['start'])
        self.assertEqual(dup['end'], dup['after_dupa'], 'plans/dup/ of P1 changed after the DUPa amend')
        self.assertTrue((rolled['state'] / 'plans' / 'dup' / 'v2.json').is_file())
        amended = [k for k in ov.kinds_on(rolled['state'], self.ids['DUPa']) if k == 'plan.amended']
        self.assertEqual(len(amended), 1)
        self.assertNotIn('plan.amended', ov.kinds_on(rolled['state'], self.ids['DUPk']))

    def test_e6_propose_dup_from_p2_refused_and_propose_r2_creates_a_new_legacy_root(self):
        rolled = self.rolled_back()
        code, out = rolled['cmd']['propose dup P2']
        self.assertNotEqual(code, 0, out)
        code, out = rolled['cmd']['propose r2 P2']
        self.assertEqual(code, 0, out)
        new = ov.anchor_id(rolled['state'], self.pids[1], 'plan:r2')
        self.assertNotEqual(new, self.ids['R2'])
        self.assertTrue((rolled['state'] / 'plans' / 'r2' / 'v1.json').is_file())

    # ---- [E7] / [E12] -------------------------------------------------------------------------------------------------------
    def forward_problems(self, rolled):
        """The roll-forward check: nothing of the ledger before rollback is lost or rewritten; only R1, DUPa and the new plan:r2 grew;
        budget spent = before + what the old version recorded for R1 during the rollback; every root reads with the new code."""
        state, before = rolled['state'], rolled['before']
        after = snapshot(state)
        problems = []
        for table, rows in before['rows'].items():
            lost = rows - after['rows'].get(table, set())
            if lost: problems.append(f'{table}: {len(lost)} rows from before the rollback are gone or changed')
        changed = {f for f, h in before['files'].items() if after['files'].get(f) != h}
        if changed: problems.append(f'files rewritten: {sorted(changed)}')
        new_r2 = ov.anchor_id(state, self.pids[1], 'plan:r2')
        grown = {task for seq, task in after['events'].items() if seq not in before['events']}
        if not grown <= {self.ids['R1'], self.ids['DUPa'], new_r2}: problems.append(f'events added to {sorted(grown - {self.ids["R1"], self.ids["DUPa"], new_r2})}')
        old_r1_runs = sum(1 for seq, task in after['events'].items() if seq not in before['events'] and task == self.ids['R1'] and
                          self.kind(state, seq) == 'verdict.recorded')
        for label, was in rolled['spent_before'].items():
            want = (was[0] + (old_r1_runs if label == 'R1' else 0), was[1])
            if spent(state, self.ids[label]) != want: problems.append(f'{label}: spent {spent(state, self.ids[label])} != {want}')
        for label, (index, anchor) in LABELS.items():
            reading = self.new_reading(state, label)
            if 'error' in reading: problems.append(f'{label}: the new code cannot read it: {reading["error"]}'); continue
            if reading['id'] != self.ids[label]: problems.append(f'{label}: id changed')
            was = rolled['readings'][label]
            if label not in ('R1', 'DUPa') and reading != was: problems.append(f'{label}: new-code reading changed {was} -> {reading}')
            if label == 'R1':
                at_1 = sum(m['runs'] for m in plan.show(Ledger(self.projects[0], state), anchor, revision=1)['milestones'])
                if at_1 != was['runs'] + old_r1_runs: problems.append(f'R1: the new code reads {at_1} runs on revision 1')
                if reading['latest'] != was['latest'] + 1: problems.append('R1: the revision made during the rollback is not read')
        return problems

    def new_reading(self, state, label):
        index, anchor = LABELS[label]
        try:
            shown = plan.show(Ledger(self.projects[index], state), anchor)
        except LedgerError as error:
            return {'error': str(error)}
        return {'id': shown['anchor_task'], 'status': shown['status'], 'latest': shown['latest_revision'], 'sha': shown['sha'],
                'runs': sum(m['runs'] for m in shown['milestones'])}

    @staticmethod
    def kind(state, seq):
        conn = sqlite3.connect(str(state / 'ledger.sqlite3'))
        try: return conn.execute('SELECT kind FROM events WHERE seq=?', (seq,)).fetchone()[0]
        finally: conn.close()

    def test_e7_roll_forward_keeps_ids_revisions_evidence_and_budget(self):
        rolled = self.rolled_back()
        self.assertEqual(rolled['spent_before']['R3'][0], 1, 'the fixture gives R3 spent budget')
        self.assertEqual(self.forward_problems(rolled), [])
        r1 = plan.show(Ledger(self.projects[0], rolled['state']), 'plan:r1')
        self.assertEqual(r1['latest_revision'], 2)                                        # the revision R1 got during the rollback is kept
        self.assertEqual(spent(rolled['state'], self.ids['R1'])[0], rolled['spent_before']['R1'][0] + 1)
        # R7-E: DUPk (plan:dup whose files sit at plans/<P3>/dup/) is read by the new code from its OWN project's files, before and after
        # the rollback (tests.test_wf_r7_dupk); it was 'revision 1 does not match the recorded hash' at c9b1e97.
        for when, reading in (('before', rolled['readings']['DUPk']), ('after', self.new_reading(rolled['state'], 'DUPk'))):
            self.assertNotIn('error', reading, when)
            self.assertEqual((reading['id'], reading['status']), (self.ids['DUPk'], 'accepted'), when)
        for label in ('R2', 'R3', 'R4', 'DUPa', 'DUPb', 'DUPk'):
            index, anchor = LABELS[label]
            want = 2 if label == 'DUPa' else 1
            self.assertEqual(plan.show(Ledger(self.projects[index], rolled['state']), anchor)['latest_revision'], want, label)

    def test_e7_roll_forward_continues_r3(self):
        """R3 carries on with the new code: its spent run is still there (a second pass on the same artifact is refused for that reason) and
        the work continues with a new revision."""
        rolled = self.rolled_back()
        state = self.copy_of(rolled['state'])
        ledger = self.ledger_of(state, 'R3')
        with patch.object(active_plan, 'export', lambda *a, **k: None):
            with self.assertRaisesRegex(LedgerError, 'already passed'):
                verdict.run(ledger, 'plan-ns:r3', 'M1', self.projects[0])
            plan.amend(ledger, 'plan-ns:r3', dict(ov.contract('P1-r3'), title='R3 continued after roll-forward'), 'continue after roll-forward', 'codex-fixture')
        shown = plan.show(ledger, 'plan-ns:r3')
        self.assertEqual((shown['latest_revision'], shown['anchor_task']), (2, self.ids['R3']))
        self.assertEqual(spent(state, self.ids['R3'])[0], rolled['spent_before']['R3'][0])

    def copy_of(self, state):
        target = self.runs / ('fwd-' + uuid.uuid4().hex[:8])
        shutil.copytree(state, target)
        return target

    def test_e7_plan_show_r2_in_p2_names_both_anchors_and_explicit_anchors_work(self):
        state = self.rolled_back()['state']
        ledger = Ledger(self.projects[1], state)
        with self.assertRaises(LedgerError) as caught:
            plan.show(ledger, 'r2')
        self.assertIn('plan:r2', str(caught.exception)); self.assertIn('plan-ns:r2', str(caught.exception))
        self.assertEqual(plan.show(ledger, 'plan-ns:r2')['anchor_task'], self.ids['R2'])
        self.assertEqual(plan.show(ledger, 'plan-ns:r2')['status'], 'accepted')
        self.assertEqual(plan.show(ledger, 'plan:r2')['anchor_task'], ov.anchor_id(state, self.pids[1], 'plan:r2'))

    def test_e12_counter_a_roll_forward_that_resets_spent_budget_is_red(self):
        rolled = self.rolled_back()
        copy = self.copy_of(rolled['state'])
        with sqlite3.connect(str(copy / 'ledger.sqlite3')) as conn:                      # the mutant roll-forward: spent budget reset on R3
            conn.execute("DELETE FROM events WHERE task_id=? AND kind='verdict.recorded'", (self.ids['R3'],))
        problems = self.forward_problems(dict(rolled, state=copy))
        self.assertTrue(any(p.startswith('R3: spent') for p in problems), problems)
        self.assertTrue(any(p.startswith('events:') for p in problems), problems)

    def test_e12_counter_a_roll_forward_that_rewrites_a_revision_file_is_red(self):
        rolled = self.rolled_back()
        copy = self.copy_of(rolled['state'])
        revision = copy / 'plans' / 'r4' / 'v1.json'
        revision.write_text(revision.read_text(encoding='utf-8').replace('R4', 'R4 rewritten'), encoding='utf-8')
        problems = self.forward_problems(dict(rolled, state=copy))
        self.assertTrue(any(p.startswith('files rewritten') for p in problems), problems)


if __name__ == '__main__':
    unittest.main()
