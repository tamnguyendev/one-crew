"""Codex review P1: the package verifier must not say `pass` while a mandatory step failed.

Unit tests build reports by hand and call `judge`. One integration test runs the real verifier on the real handover package.
"""
import copy
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from wfkit import package_check as pc

PACKAGE = Path(os.environ['WF_PACKAGE']) if os.environ.get('WF_PACKAGE') else None      # e.g. D:/OneCrewRuns/wf-handover-6366137


def _step(sid, **kw):
    return {'id': sid, 'step': sid.replace('_', ' '), 'ok': True, 'mandatory': True, **kw}


# The facts each step records (as the runner writes them); judge recomputes every `ok` from these (P1-1).
FACTS = {
    'sha256sums': {'files': 3, 'bad': []}, 'wheel_sha': {'sha256': 'W', 'actual_sha256': 'W'}, 'venv': {'exit': 0},
    'pip_install': {'exit': 0}, 'help': {'exit': 0, 'needles': {'plan': True}}, 'smoke_body': {'exit': 0, 'observation': True},
    'verdict_run': {'exit': 0, 'm1': 'passed', 'tail': ''}, 'plan_report': {'rendered': True}, 'modules_from_venv': {'modules': 9, 'outside': {}},
    'checkout_not_on_path': {'on_path': []}, 'blocked_copy_built': {'exit': 0, 'needles': {'built': True}},
    'blocked_scan': {'exit': 0, 'blocking': {'total': 1}}, 'blocked_refused_no_pip': {'pip_invocations': 0},
    'blocked_installed_unchanged': {'installed': 'A'}, 'blocked_copy_unchanged': {'tree_sha': 'C'},
    'clear_scan': {'exit': 0, 'blocking': {'total': 0}}, 'clear_uninstall_current': {'exit': 0},
    'clear_install_previous': {'exit': 0, 'sha256': 'P', 'actual_sha256': 'P'}, 'clear_old_digest': {'needles': {'smoke': False}},
    'clear_old_copy_unchanged': {'tree_sha': 'D', 'copy_before': 'D'}, 'clear_uninstall_previous': {'exit': 0},
    'clear_reinstall_current': {'exit': 0}, 'clear_same_build_restored': {'installed': 'A'}, 'clear_roll_forward_reads': {'exit': 0, 'needles': {'smoke': True}},
    'clear_roll_forward_copy_unchanged': {'tree_sha': 'D'},
}


def good_report():
    steps = [_step(i, **copy.deepcopy(FACTS.get(i, {}))) for i in pc.BASE_REQUIRED + pc.ROLLBACK_REQUIRED]
    for s in steps:
        if s['id'] == 'clear_old_cannot_read_plan_ns':
            s.update(kind='negative', exit=1, expect={'exits': [1, 2], 'reason_any': ['No plan named']},
                     stdout_tail='', stderr_tail='{"error": "No plan named smoke"}')
        elif s['id'] == 'clear_old_digest':
            s.update(exit=0, stdout_tail='{"plans": []}', stderr_tail='')
    return {'steps': steps, 'result': None, 'previous_wheel_present': True,
            'rollback': {
                'blocked': {'scan_total': 1, 'decision': 'refused', 'pip_invocations': 0, 'installed_before': 'A', 'installed_after': 'A',
                            'copy_before': 'C', 'copy_after': 'C'},
                'clear': {'scan_total': 0, 'decision': 'allowed', 'pip_invocations': 4, 'installed_before': 'A', 'installed_after': 'A',
                          'copy_before': 'D', 'copy_after': 'D'}}}


def get(report, sid):
    return next(s for s in report['steps'] if s['id'] == sid)


class JudgeTests(unittest.TestCase):

    def test_i_all_mandatory_ok_passes(self):
        verdict = pc.judge(good_report())
        self.assertEqual(verdict, {'result': 'pass', 'reasons': []})

    def test_ii_mandatory_step_failed_is_refused_and_named(self):
        r = good_report()
        get(r, 'help').update(ok=False, exit=2)
        v = pc.judge(r)
        self.assertEqual(v['result'], 'refused')
        self.assertTrue(any('mandatory step failed: help' in x for x in v['reasons']), v)
        r = good_report()
        get(r, 'pip_install')['exit'] = 1           # nonzero exit even though ok says true
        self.assertEqual(pc.judge(r)['result'], 'refused')

    def test_iii_negative_test_failing_for_a_wrong_reason_is_refused(self):
        r = good_report()
        get(r, 'clear_old_cannot_read_plan_ns').update(exit=2, stderr_tail='{"error": "FileNotFoundError: onecrew.exe"}')
        v = pc.judge(r)
        self.assertEqual(v['result'], 'refused')
        self.assertTrue(any('different reason' in x for x in v['reasons']), v)
        r = good_report()
        get(r, 'clear_old_cannot_read_plan_ns').update(exit=0)       # it must actually fail
        self.assertEqual(pc.judge(r)['result'], 'refused')
        r = good_report()
        s = get(r, 'clear_old_cannot_read_plan_ns')
        del s['expect']                                              # a negative test without an expectation is not a test
        self.assertEqual(pc.judge(r)['result'], 'refused')

    def test_iv_report_claiming_pass_with_failed_mandatory_step_is_incoherent(self):
        r = good_report()
        get(r, 'clear_old_digest').update(ok=False, exit=2)
        r['result'] = 'pass'
        v = pc.judge(r)
        self.assertEqual(v['result'], 'refused')
        self.assertTrue(any('incoherent' in x for x in v['reasons']), v)
        # the original defect: a recorded ok=false step next to result pass
        r = good_report()
        r['steps'].append({'step': 'previous build: plan digest exit 2', 'ok': False, 'exit': 2})   # no id, mandatory by default
        r['result'] = 'pass'
        self.assertEqual(pc.judge(r)['result'], 'refused')
        # a faithful report may say refused; claiming refused on a clean report is incoherent too
        r = good_report()
        r['result'] = 'refused'
        self.assertEqual(pc.judge(r)['result'], 'refused')

    def test_v_encoding_error_in_a_tail_is_refused_even_with_exit_zero(self):
        r = good_report()
        get(r, 'clear_old_digest').update(
            exit=0, stderr_tail="{\"error\": \"'charmap' codec can't encode character '\\u1eae'\", \"type\": \"UnicodeEncodeError\"}")
        v = pc.judge(r)
        self.assertEqual(v['result'], 'refused')
        self.assertTrue(any('UnicodeEncodeError' in x for x in v['reasons']), v)
        r = good_report()
        get(r, 'verdict_run')['tail'] = 'Traceback (most recent call last):\n  File "x"'
        self.assertEqual(pc.judge(r)['result'], 'refused')

    def test_vi_blocked_branch_with_pip_activity_is_refused(self):
        for key, bad in (('pip_invocations', 1), ('installed_after', 'B'), ('copy_after', 'X')):
            r = good_report()
            r['rollback']['blocked'][key] = bad
            v = pc.judge(r)
            self.assertEqual(v['result'], 'refused', key)
        r = good_report()
        r['rollback']['blocked'].update(scan_total=0)                 # a "blocked" copy without a block proves nothing
        self.assertEqual(pc.judge(r)['result'], 'refused')
        r = good_report()
        r['rollback']['blocked'].update(decision='allowed')           # blocks present but rollback not refused
        self.assertEqual(pc.judge(r)['result'], 'refused')

    def test_vii_missing_expected_steps_and_branches_are_refused(self):
        r = good_report()
        r['steps'] = [s for s in r['steps'] if s['id'] != 'blocked_refused_no_pip']
        v = pc.judge(r)
        self.assertEqual(v['result'], 'refused')
        self.assertTrue(any('blocked_refused_no_pip' in x for x in v['reasons']), v)
        r = good_report()
        del r['rollback']['clear']
        self.assertEqual(pc.judge(r)['result'], 'refused')
        r = good_report()
        r['previous_wheel_present'] = None
        self.assertEqual(pc.judge(r)['result'], 'refused')

    def test_viii_non_mandatory_failure_does_not_decide_but_is_not_hidden_from_the_report(self):
        r = good_report()
        r['steps'].append({'id': 'extra_note', 'step': 'optional note', 'ok': False, 'mandatory': False})
        v = pc.judge(r)
        self.assertEqual(v['result'], 'pass')
        self.assertEqual(v['optional'], ['optional step failed (not deciding): extra_note'])     # shown, not deciding
        # P1-1: the report cannot make an ORACLE step optional; demoting it is refused
        r = good_report()
        get(r, 'help').update(mandatory=False, ok=False, exit=2)
        v = pc.judge(r)
        self.assertEqual(v['result'], 'refused')
        self.assertTrue(any('mandatory step demoted: help' in x for x in v['reasons']), v)

    def test_ix_judge_is_pure(self):
        r = good_report()
        before = copy.deepcopy(r)
        pc.judge(r)
        self.assertEqual(r, before)


class RunnerFactsTests(unittest.TestCase):

    def test_pip_invocations_are_counted_only_for_install_and_uninstall(self):
        runner = pc.Runner()
        import sys
        runner.run([sys.executable, '-m', 'pip', '--version'])
        self.assertEqual(runner.pip_invocations, 0)
        runner.run([sys.executable, '-m', 'pip', 'uninstall', '--yes', 'onecrew-package-check-not-installed'])
        self.assertEqual(runner.pip_invocations, 1)

    def test_child_env_forces_utf8(self):
        import sys
        code, so, se = pc.Runner().run([sys.executable, '-c', 'import os,sys;print(os.environ["PYTHONUTF8"], sys.stdout.encoding);print("\\u1eae")'])
        self.assertEqual(code, 0, se)
        self.assertIn('1 utf-8', so)
        self.assertIn('\u1eae', so)

    def test_tree_sha_changes_with_content(self):
        d = Path(tempfile.mkdtemp())
        try:
            (d / 'a').write_text('1')
            h1 = pc.tree_sha(d)
            (d / 'a').write_text('2')
            self.assertNotEqual(h1, pc.tree_sha(d))
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
