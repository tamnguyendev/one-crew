"""docs/wf/audit/tools/legacy_continuation.py — the package-level legacy-root continuation check (review a2476ab P1-D, directive 25/10).

The judge decides from the mandatory steps only; the report's own `result` is compared, never trusted. Negative steps must have failed the
command for the expected reason and written nothing. An encoding error in any tail refuses the report. The run against a real package lives in
tests/test_wf_legacy_continuation_real.py (needs WF_PACKAGE; not in the gate registry because it must skip without a package).
"""
import copy
import importlib.util
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('legacy_continuation', REPO / 'docs' / 'wf' / 'audit' / 'tools' / 'legacy_continuation.py')
lc = importlib.util.module_from_spec(spec); spec.loader.exec_module(lc)


def good_report():
    steps = []
    for sid in lc.REQUIRED:
        s = {'id': sid, 'step': sid, 'ok': True, 'mandatory': True, 'stdout_tail': '', 'stderr_tail': ''}
        if sid in lc.NEGATIVE:
            s.update(exit=1, events_added=0, stderr_tail='refused: ' + lc.NEGATIVE[sid] + ' decision / commit not in the repository')
        steps.append(s)
    return {'steps': steps, 'result': None}


def get(report, sid):
    return next(s for s in report['steps'] if s['id'] == sid)


class JudgeTests(unittest.TestCase):
    def test_all_mandatory_ok_passes(self):
        self.assertEqual(lc.judge(good_report()), {'result': 'pass', 'reasons': []})

    def test_failed_or_missing_mandatory_step_is_refused_and_named(self):
        r = good_report(); get(r, 'legacy_passed_after_baseline')['ok'] = False
        self.assertIn('mandatory step failed: legacy_passed_after_baseline', lc.judge(r)['reasons'])
        r = good_report(); r['steps'] = [s for s in r['steps'] if s['id'] != 'legacy_route_in_handover']
        self.assertIn('mandatory step missing: legacy_route_in_handover', lc.judge(r)['reasons'])

    def test_report_claiming_pass_with_a_failed_step_is_incoherent(self):
        r = good_report(); get(r, 'baseline_owner_recorded')['ok'] = False; r['result'] = 'pass'
        reasons = lc.judge(r)['reasons']
        self.assertIn('mandatory step failed: baseline_owner_recorded', reasons)
        self.assertTrue(any('incoherent' in x for x in reasons))

    def test_negative_step_that_did_not_fail_or_failed_for_another_reason_or_wrote_events_is_refused(self):
        r = good_report(); get(r, 'baseline_ai_refused')['exit'] = 0
        self.assertTrue(any('did not fail' in x for x in lc.judge(r)['reasons']))
        r = good_report(); get(r, 'baseline_bad_commit_refused')['stderr_tail'] = 'Traceback: KeyError'
        self.assertTrue(any('another reason' in x for x in lc.judge(r)['reasons']))
        r = good_report(); get(r, 'baseline_ai_refused')['events_added'] = 1
        self.assertTrue(any('wrote events' in x for x in lc.judge(r)['reasons']))

    def test_encoding_error_in_a_tail_is_refused_even_when_the_step_says_ok(self):
        r = good_report(); get(r, 'legacy_root_built')['stderr_tail'] = "UnicodeEncodeError: 'charmap' codec can't encode"
        self.assertIn('encoding error in step output: legacy_root_built', lc.judge(r)['reasons'])

    def test_judge_is_pure(self):
        r = good_report(); before = copy.deepcopy(r); lc.judge(r); self.assertEqual(r, before)


if __name__ == '__main__':
    unittest.main()
