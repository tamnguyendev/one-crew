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


# The facts each step records (as the runner writes them); judge recomputes every `ok` from these (oracle principle, Codex P1-1).
FACTS = {
    'wheel_sha': {'sha256': 'W', 'actual_sha256': 'W'},
    'venv': {'exit': 0},
    'pip_install': {'exit': 0},
    'old_venv_previous_wheel': {'exit': 0, 'venv_exit': 0, 'previous': {'file': 'p.whl', 'sha256': 'P'}, 'previous_actual_sha256': 'P'},
    'legacy_root_by_old_build': {'exit': 0},
    'legacy_root_built': {'exit': 0, 'observation': True},
    'legacy_inconclusive_not_passed': {'exit': 1, 'm1': 'pending', 'result': 'inconclusive',
                                       'integrity': {'classification': 'insufficient', 'error': 'no approved baseline for this root'}},
    'legacy_route_in_handover': {'route_in_page': True, 'o1_line': 'O1 — baseline needed'},
    'baseline_owner_recorded': {'exit': 0, 'baselines': 1, 'recorded': [{'tree': 'T', 'from_commit': 'H'}], 'tree': 'T', 'head': 'H'},
    'legacy_passed_after_baseline': {'exit': 0, 'm1': 'passed', 'result': 'pass'},
    'legacy_identity_unchanged': {'exit': 0, 'anchor': 'A', 'anchor_built': 'A', 'anchor_counted_before': 'A', 'revision': 1, 'revision_built': 1,
                                  'approved_rows': 1, 'approved_rows_built': 1, 'verdicts': ['inconclusive', 'pass'], 'baselines': 1},
    'modules_from_venv': {'modules': 9, 'outside': {}},
}


def good_report():
    steps = []
    for sid in lc.REQUIRED:
        s = {'id': sid, 'step': sid, 'ok': True, 'mandatory': True, 'stdout_tail': '', 'stderr_tail': '', **copy.deepcopy(FACTS.get(sid, {}))}
        if sid in lc.NEGATIVE:
            s.update(kind='negative', exit=1, events_added=0, baselines=0,
                     stderr_tail='refused: ' + lc.NEGATIVE[sid] + ' decision / commit not in the repository')
        steps.append(s)
    return {'steps': steps, 'result': None}


def get(report, sid):
    return next(s for s in report['steps'] if s['id'] == sid)


class JudgeTests(unittest.TestCase):
    def test_all_mandatory_ok_passes(self):
        self.assertEqual(lc.judge(good_report()), {'result': 'pass', 'reasons': []})

    def test_failed_or_missing_mandatory_step_is_refused_and_named(self):
        r = good_report(); get(r, 'legacy_passed_after_baseline').update(ok=False, m1='pending', result='fail')
        self.assertIn('mandatory step failed: legacy_passed_after_baseline', lc.judge(r)['reasons'])
        r = good_report(); r['steps'] = [s for s in r['steps'] if s['id'] != 'legacy_route_in_handover']
        self.assertIn('mandatory step missing: legacy_route_in_handover', lc.judge(r)['reasons'])

    def test_report_claiming_pass_with_a_failed_step_is_incoherent(self):
        r = good_report(); get(r, 'baseline_owner_recorded').update(ok=False, exit=1, baselines=0); r['result'] = 'pass'
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

    # ---- oracle counter-examples (the report supplies observations only; Codex P1-1 principle) ----
    def test_demoted_required_step_is_refused(self):
        r = good_report(); get(r, 'legacy_passed_after_baseline').update(mandatory=False, ok=False, m1='pending', result='fail')
        v = lc.judge(r)
        self.assertEqual(v['result'], 'refused')
        self.assertTrue(any('mandatory step demoted: legacy_passed_after_baseline' in x for x in v['reasons']), v)

    def test_ok_true_on_the_inconclusive_step_with_result_passed_is_refused(self):
        r = good_report(); get(r, 'legacy_inconclusive_not_passed').update(result='pass', m1='passed')
        v = lc.judge(r)
        self.assertEqual(v['result'], 'refused')
        self.assertTrue(any('legacy_inconclusive_not_passed' in x and 'disagrees' in x for x in v['reasons']), v)

    def test_duplicate_step_id_is_refused_in_either_order(self):
        for bad_first in (False, True):
            r = good_report()
            i = next(n for n, s in enumerate(r['steps']) if s['id'] == 'legacy_passed_after_baseline')
            good = r['steps'][i]; bad = dict(good, ok=False, m1='pending', result='fail')
            r['steps'][i:i + 1] = [bad, good] if bad_first else [good, bad]
            v = lc.judge(r)
            self.assertEqual(v['result'], 'refused')
            self.assertTrue(any('duplicate step id' in x for x in v['reasons']), v)

    def test_ok_true_while_recorded_facts_fail_is_refused(self):
        cases = [('legacy_passed_after_baseline', {'m1': 'pending'}), ('baseline_ai_refused', {'baselines': 1}),
                 ('baseline_owner_recorded', {'baselines': 2}), ('legacy_identity_unchanged', {'revision': 2}),
                 ('legacy_identity_unchanged', {'verdicts': ['pass']}), ('modules_from_venv', {'outside': {'onecrew': 'D:/checkout'}}),
                 ('wheel_sha', {'actual_sha256': 'X'}), ('old_venv_previous_wheel', {'previous_actual_sha256': 'X'}),
                 ('legacy_route_in_handover', {'route_in_page': False})]
        for sid, facts in cases:
            r = good_report(); get(r, sid).update(facts)
            v = lc.judge(r)
            self.assertEqual(v['result'], 'refused', (sid, facts))
            self.assertTrue(any(sid in x for x in v['reasons']), (sid, v))

    def test_ok_false_while_facts_pass_is_refused(self):
        r = good_report(); get(r, 'modules_from_venv')['ok'] = False
        self.assertTrue(any('disagrees' in x for x in lc.judge(r)['reasons']))

    def test_missing_fact_is_refused(self):
        r = good_report(); del get(r, 'legacy_inconclusive_not_passed')['result']
        self.assertTrue(any('fact missing' in x and 'legacy_inconclusive_not_passed' in x for x in lc.judge(r)['reasons']))
        r = good_report(); del get(r, 'baseline_ai_refused')['events_added']
        self.assertTrue(any('fact missing' in x and 'baseline_ai_refused' in x for x in lc.judge(r)['reasons']))

    def test_judge_is_pure(self):
        r = good_report(); before = copy.deepcopy(r); lc.judge(r); self.assertEqual(r, before)


if __name__ == '__main__':
    unittest.main()
