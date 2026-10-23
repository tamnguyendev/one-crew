"""T49a (W46a) — the read-only `compat scan` for `plan:` roots (R00).

Fixture (00 §6.1 / T49 fixture, S0 and S1):
  R1  plan:r1  approved (open), class 0/A only                 -> readable, continuable, no block
  R4  plan:r4  approved, one class-B event (plan.revoked)      -> B2 continue block (reads wrong)
  X1  plan:x1  accepted, plan.advised MISSING revision (B4)    -> B4 read block, EVEN THOUGH accepted
  X2  plan:x2  accepted, history readable (control for X1)     -> no block
S0 = R1,R4,X2 ; S1 = S0 + X1 (X1 crashes digest of the whole state root, so it sits in its own root).

Asserts: the three properties, the status by old rules, the event classes, B2 vs B4 split, `accepted` releases B2 but not B4, a
paused root releases nothing, the per-command prediction matches the REAL old binary, and the scan writes nothing. Counter-examples:
treating `accepted` as releasing a read block goes red on X1; one expectation for all old commands is rejected by the prediction check.
"""
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from onecrew.v2 import compat_scan
import tests.wf_oldversion as ov

REPO = str(Path(__file__).resolve().parents[1])
BASELINE = 'ee46539'


def _have_git():
    try:
        return subprocess.run(['git', '--version'], capture_output=True).returncode == 0
    except OSError:
        return False


@unittest.skipUnless(_have_git(), 'git required to archive the old version')
class CompatScanTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.runs = ov._short_runs()
        cls.old = ov.OldVersion(ov.archive(BASELINE, REPO, cls.runs))
        cls.proj = ov.git_project(cls.runs, 'P1')
        cls.s0 = cls.runs / 'S0'
        cls.s1 = cls.runs / 'S1'
        cls._build(cls.s0, with_x1=False)
        cls._build(cls.s1, with_x1=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    @classmethod
    def _propose(cls, state, name):
        f = cls.runs / f'c_{name}.json'
        f.write_text(json.dumps(ov.contract(name.upper())), encoding='utf-8')
        code, out = cls.old.run(cls.proj, state, 'plan', 'propose', name, '--file', str(f), '--author', 'claude-probe')
        assert code == 0, out

    @classmethod
    def _build(cls, state, with_x1):
        cls._propose(state, 'r1'); cls._propose(state, 'r4'); cls._propose(state, 'x2')
        if with_x1:
            cls._propose(state, 'x1')
        pid = ov.project_id(state, cls.proj)
        # R1: approved, class 0/A only (add a learning.outcome)
        t = ov.anchor_id(state, pid, 'plan:r1'); ov.make_approved(state, t, 'r1')
        ov.insert_event(state, t, 'learning.outcome', {'version': 1, 'task': 'ANCHOR', 'id': 'o1', 'phase': 'completed'})
        # R4: approved + a class-B plan.revoked
        t = ov.anchor_id(state, pid, 'plan:r4'); ov.make_approved(state, t, 'r4')
        ov.insert_event(state, t, 'plan.revoked', {'plan': 'r4', 'revision': 1, 'reason': 'fixture'})
        # X2: accepted, readable (control)
        t = ov.anchor_id(state, pid, 'plan:x2'); ov.make_accepted(state, t, 'x2')
        # X1: accepted but plan.advised missing revision BEFORE a valid plan.accepted (B4)
        if with_x1:
            t = ov.anchor_id(state, pid, 'plan:x1')
            ov.insert_event(state, t, 'plan.advised', {'plan': 'x1', 'sha': 'x'})     # missing 'revision' -> B4
            ov.make_accepted(state, t, 'x1')
        cls._pid = pid

    def _root(self, report, name):
        return next(r for r in report['roots'] if r['name'] == name)

    # E1: one row per root with the three properties, status, classes, blocks+type.
    def test_e1_rows_and_properties_on_S1(self):
        rep = compat_scan.scan(self.s1)
        r1, r4, x1, x2 = self._root(rep, 'r1'), self._root(rep, 'r4'), self._root(rep, 'x1'), self._root(rep, 'x2')
        # R1: open, readable + continuable, no block
        self.assertEqual(r1['status'], 'open')
        self.assertTrue(r1['properties']['old_readable'] and r1['properties']['old_continuable'])
        self.assertEqual(r1['blocks'], [])
        # R4: B2 continue block, reads wrong
        self.assertEqual([b['id'] for b in r4['blocks']], ['B2'])
        self.assertEqual(r4['blocks'][0]['type'], 'continue')
        self.assertTrue(r4['properties']['old_readable'] and not r4['properties']['old_continuable'])
        # X1: B4 read block, EVEN THOUGH accepted
        self.assertEqual(x1['status'], 'closed')
        self.assertEqual([b['id'] for b in x1['blocks']], ['B4'])
        self.assertEqual(x1['blocks'][0]['type'], 'read')
        self.assertFalse(x1['properties']['old_readable'])
        self.assertTrue(x1['preserved_only'])
        # X2: accepted, readable, no block
        self.assertEqual(x2['status'], 'closed')
        self.assertEqual(x2['blocks'], [])

    # E3: each block names type + the release condition; counts split read vs continue.
    def test_e3_blocks_named_with_type_and_release(self):
        rep = compat_scan.scan(self.s1)
        self.assertEqual(rep['blocking'], {'read': 1, 'continue': 1, 'total': 2})
        x1 = self._root(rep, 'x1')['blocks'][0]
        self.assertIn('none in this rollback', x1['released_by'])          # B4 has no release here
        self.assertIn('accepted', x1['not_released_by'])                   # and accepted does NOT release it
        r4 = self._root(rep, 'r4')['blocks'][0]
        self.assertIn('accepted', r4['released_by'])                       # B2 is released by accepted

    # E23 / counter: accepted does NOT release a read block; a scan that drops accepted-root events would miss X1.
    def test_e23_accepted_does_not_release_read_block(self):
        rep = compat_scan.scan(self.s1)
        x1 = self._root(rep, 'x1')
        self.assertEqual([b['id'] for b in x1['blocks']], ['B4'])
        # counter-example: a scanner that ignores events on an accepted root would report X1 as no-block -> this asserts it does NOT.
        self.assertFalse(x1['properties']['old_readable'])

    # E2: the scan's per-command prediction matches the REAL old binary on each plan: root.
    def test_e2_predictions_match_real_old_binary(self):
        rep = compat_scan.scan(self.s0)   # S0 has no X1, so the whole-state-root digest works for the other rows
        for name in ('r1', 'r4', 'x2'):
            root = self._root(rep, name)
            # plan show
            code, out = self.old.run(self.proj, self.s0, 'plan', 'show', name)
            pred = root['commands']['plan show']
            if 'exit 0' in pred:
                self.assertEqual(code, 0, f'{name}: predicted exit 0, got {code}: {out[:120]}')
            # plan amend prediction direction
            s = self.runs / f'amend_{name}'; shutil.copytree(self.s0, s)
            fb = self.runs / f'c_{name}_b.json'; fb.write_text(json.dumps(ov.contract(name.upper() + ' b', name + ' goal b')), encoding='utf-8')
            acode, aout = self.old.run(self.proj, s, 'plan', 'amend', name, '--file', str(fb), '--reason', 'r', '--author', 'claude-probe')
            shutil.rmtree(s, ignore_errors=True)
            if 'refused' in root['commands']['plan amend']:
                self.assertNotEqual(acode, 0, f'{name}: predicted amend refused, got exit {acode}')
            else:
                self.assertEqual(acode, 0, f'{name}: predicted amend exit 0, got {acode}: {aout[:120]}')

    def test_e2_x1_read_block_crashes_real_old_binary(self):
        # X1 on S1: the real old binary crashes show AND the whole-state-root digest -> matches the B4 prediction.
        show_code, _ = self.old.run(self.proj, self.s1, 'plan', 'show', 'x1')
        digest_code, _ = self.old.run(self.proj, self.s1, 'plan', 'digest')
        self.assertNotEqual(show_code, 0)
        self.assertNotEqual(digest_code, 0)
        x1 = self._root(compat_scan.scan(self.s1), 'x1')
        self.assertIn('KeyError', x1['commands']['plan show'])
        self.assertIn('whole state root', x1['commands']['plan digest'])

    # E24 / counter: the prediction is per-command, not one expectation for all.
    def test_e24_prediction_is_per_command(self):
        x1 = self._root(compat_scan.scan(self.s1), 'x1')['commands']
        x2 = self._root(compat_scan.scan(self.s1), 'x2')['commands']
        self.assertNotEqual(len(set(x1.values())), 1, 'a read-blocked root still differs per command text where it can')
        # an accepted readable root predicts amend REFUSED but show exit 0 — two different outcomes, not one blanket.
        self.assertIn('exit 0', x2['plan show'])
        self.assertIn('refused', x2['plan amend'])

    # E4 / E15: the scan writes nothing — ledger sha and file set unchanged across a scan.
    def test_e4_scan_is_read_only(self):
        before_sha = compat_scan._ledger_sha(self.s1)
        before_files = {p.name: p.stat().st_mtime_ns for p in (self.s1).rglob('*') if p.is_file()}
        compat_scan.scan(self.s1)
        after_sha = compat_scan._ledger_sha(self.s1)
        after_files = {p.name: p.stat().st_mtime_ns for p in (self.s1).rglob('*') if p.is_file()}
        self.assertEqual(before_sha, after_sha)
        self.assertEqual(set(before_files), set(after_files))

    # E18 / counter: a paused (stopped_with_report) root does not release a block.
    def test_e18_paused_does_not_release(self):
        s = self.runs / 'paused'; shutil.copytree(self.s1, s)
        # rebuild x1 as stopped instead of accepted: B4 must still hold
        import sqlite3
        c = sqlite3.connect(str(s / 'ledger.sqlite3'))
        t = ov.anchor_id(s, self._pid, 'plan:x1')
        c.execute("DELETE FROM events WHERE task_id=? AND kind='plan.accepted'", (t,)); c.commit(); c.close()
        ov.insert_event(s, t, 'milestone.stopped', {'plan': 'x1', 'revision': 1, 'milestone': 'M1', 'reason': 'fixture'})
        x1 = self._root(compat_scan.scan(s), 'x1')
        self.assertEqual(x1['status'], 'paused')
        self.assertEqual([b['id'] for b in x1['blocks']], ['B4'])        # still read-blocked
        shutil.rmtree(s, ignore_errors=True)


    # the scan runs through the installed-command router (onecrew compat scan), and --out inside the state root is refused.
    def test_cli_routes_and_out_is_refused_inside_state_root(self):
        import io as _io
        from contextlib import redirect_stdout
        from onecrew.v2 import cli
        out = _io.StringIO()
        with redirect_stdout(out):
            rc = cli.main(['--state-root', str(self.s1), 'compat', 'scan'])
        self.assertEqual(rc, 0, out.getvalue())
        self.assertIn('compat scan', out.getvalue())
        self.assertIn('plan:x1', out.getvalue())
        # --out into the state root is refused (read-only guarantee)
        inside = str(self.s1 / 'scan.json')
        rc = cli.main(['--state-root', str(self.s1), 'compat', 'scan', '--out', inside])
        self.assertEqual(rc, 2)
        self.assertFalse((self.s1 / 'scan.json').exists())
        # --out outside is allowed
        outside = str(self.runs / 'scan.json')
        rc = cli.main(['--state-root', str(self.s1), 'compat', 'scan', '--out', outside, '--json'])
        self.assertEqual(rc, 0)
        self.assertTrue(Path(outside).exists())
        import json as _json
        doc = _json.loads(Path(outside).read_text(encoding='utf-8'))
        self.assertEqual(doc['blocking']['total'], 2)


if __name__ == '__main__':
    unittest.main()
