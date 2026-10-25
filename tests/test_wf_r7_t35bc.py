"""T35b / T35c (PL, round 7): report-checker rules (wfkit.pilot_report) not yet shown red by a named counter-example.

Fixture reports of tests.test_wf_pilot_report (simulated, test-side renderer); passing proves the checker's rules only, never a pilot
result. Each case mutates exactly one rule of 05 T35 on an otherwise passing aggregate and asserts the refusal names that rule:
  [E23] owner minutes derived from the gap between two ledger events (not only from wait time) is refused;
  [E21] the amend lines carry their targets: authoring error 0, emergent situation ≈ 0; tier 1 compares the amend total to 23 on 11 jobs;
  [E22] the false-pass line compares to the baseline 2 on 11 jobs;
  [E20] the Stop-hook noise line compares to the baseline 81 on 11 jobs.
The aggregate-metric computation and the SKIP-leak link logic are not exercised here (owned by another branch).
"""
import unittest

from wfkit import pilot_report as pr
from tests import test_wf_pilot_report as fx


def refused_with(case, needle, report):
    result = pr.check_report(report, fx.render(report))
    case.assertEqual(result['result'], 'refused', result)
    case.assertTrue(any(needle in p for p in result['problems']), result['problems'])


class T35cCheckerRuleTests(unittest.TestCase):
    def setUp(self):
        good = fx.build('aggregate')
        self.assertEqual(pr.check_report(good, fx.render(good))['result'], 'pass')

    def test_e23_owner_minutes_from_an_event_gap_is_refused(self):
        r = fx.build('aggregate')
        m = fx.metric(r, 'owner_minutes')
        m['cells'] = {j: {'value': 12, 'derived_from': 'event_gap'} for j in r['jobs']}
        fx.finish(m, 'aggregate', 10)
        r['owner_notes_missing'] = {'missed_wait_1h_owner': ['J7']}
        refused_with(self, 'E23 owner_minutes J1: phút chủ động suy ra từ event_gap', r)

    def test_e21_amend_targets_and_tier1_total_baseline(self):
        for mid, wrong, expected in (('amend_authoring_error', 1, 0), ('amend_emergent', 0, '≈0')):
            with self.subTest(metric=mid):
                r = fx.build('aggregate')
                fx.metric(r, mid)['target'] = wrong
                refused_with(self, f'{mid}: target must be {expected}', r)
        r = fx.build('aggregate')
        next(c for c in r['tiers']['tier1']['comparisons'] if c['metric'] == 'amend_total')['baseline_jobs'] = 10
        refused_with(self, 'E6 tier 1 amend_total: baseline must be 23 trên 11 việc', r)

    def test_e22_false_pass_baseline_is_two_on_eleven_jobs(self):
        r = fx.build('aggregate')
        next(c for c in r['tiers']['tier1']['comparisons'] if c['metric'] == 'false_pass')['baseline_count'] = 3
        refused_with(self, 'E6 tier 1 false_pass: baseline must be 2 trên 11 việc', r)

    def test_e20_stop_hook_noise_baseline_is_81_on_eleven_jobs(self):
        r = fx.build('aggregate')
        next(c for c in r['tiers']['tier1']['comparisons'] if c['metric'] == 'noise_stop_hook')['baseline_count'] = 80
        refused_with(self, 'E6 tier 1 noise_stop_hook: baseline must be 81 trên 11 việc', r)


if __name__ == '__main__':
    unittest.main()
