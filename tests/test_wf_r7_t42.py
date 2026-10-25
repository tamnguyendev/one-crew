"""Round 7 / T42 (W23a, R01) — E6 "plan present does not replace plan report" against the code BEFORE W23a.

05 T42 [E6] evidence: "output `plan report` trước/sau thay đổi, trên cùng sổ: bằng nhau". tests.test_wf_r01_report.test_e6 proves that running
`plan present` leaves `plan report` unchanged and that report is the full page; this module adds the before/after-the-change reading: the
UNMODIFIED archive of 54b802c (the parent of 1b4f4c6, the commit that brought `plan present` / handover into report.py) and the current code
print the same `plan report` for the same ledger — three plans made by that old code (approved with a passing verdict, approved with an
amendment waiting, accepted). No owner verb runs: approved/accepted are inserted as the exact events (tests/wf_oldversion.py).
Counter-example: a report that grew the present page (or the handover block) differs from the old one and the check is red.
"""
import contextlib
import io
import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.v2 import plan_cli, report
import tests.wf_oldversion as ov

REPO = str(Path(__file__).resolve().parents[1])
PRE_W23A = '54b802c'


class ReportUnchangedByW23aTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = ov._short_runs()
        cls.old = ov.OldVersion(ov.archive(PRE_W23A, REPO, cls.runs))
        cls.proj = ov.git_project(cls.runs, 'P')
        cls.state = cls.runs / 'S'
        pid = None
        for name in ('ok', 'amd', 'acc'):
            file = cls.runs / (name + '.json')
            file.write_text(json.dumps(ov.contract('Plan ' + name)), encoding='utf-8')
            code, out = cls.old.run(cls.proj, cls.state, 'plan', 'propose', name, '--file', str(file), '--author', 'claude-probe')
            assert code == 0, out
            pid = pid or ov.project_id(cls.state, cls.proj)
            task = ov.anchor_id(cls.state, pid, 'plan:' + name)
            ov.make_approved(cls.state, task, name)
            code, out = cls.old.run(cls.proj, cls.state, 'verdict', 'run', '--plan', name, '--milestone', 'M1')
            assert code == 0, out
            if name == 'acc': ov.make_accepted(cls.state, task, name)
        bigger = dict(ov.contract('Plan amd, bigger'), non_goals=['Nothing else', 'No new dependency'])
        file = cls.runs / 'amd2.json'; file.write_text(json.dumps(bigger), encoding='utf-8')
        code, out = cls.old.run(cls.proj, cls.state, 'plan', 'amend', 'amd', '--file', str(file), '--reason', 'a second non-goal', '--author', 'claude-probe')
        assert code == 0, out

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    def new_report(self, name):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = plan_cli.main(['--project', str(self.proj), '--state-root', str(self.state), 'plan', 'report', name])
        return code, out.getvalue().strip()

    def differences(self):
        bad = []
        for name in ('ok', 'amd', 'acc'):
            before, after = self.old.run(self.proj, self.state, 'plan', 'report', name), self.new_report(name)
            if before[0] != 0 or after[0] != 0: bad.append(f'{name}: exit {before[0]} / {after[0]}')
            elif before[1] != after[1]: bad.append(f'{name}: plan report differs from the pre-W23a code')
        return bad

    def test_e6_plan_report_is_the_same_before_and_after_w23a(self):
        self.assertEqual(self.differences(), [])
        self.assertIn('1. Output đạt tới đâu', self.new_report('ok')[1])         # and it is still the full page
        self.assertNotIn('5. Bằng chứng còn thiếu', self.new_report('amd')[1])     # not the present page

    def test_e6_counter_a_report_that_grew_the_present_page_is_caught(self):
        real = report.render_report
        with patch.object(report, 'render_report', lambda state_root, name, *a, **k: real(state_root, name, *a, **k) + '\n' + report.render_present(state_root, name)):
            bad = self.differences()
        self.assertEqual(len(bad), 3, bad)


if __name__ == '__main__':
    unittest.main()
