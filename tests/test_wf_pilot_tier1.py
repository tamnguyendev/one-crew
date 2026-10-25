"""W38c (T35c) round 7 finding 3: a tier-1 composite comparison is computed over ONE job set.

SYNTHETIC data only (never a pilot): ten stub measured roots are fed to the real aggregate generator
(wfkit.pilot_tools.build_aggregate -> render_aggregate -> write_named), and the written JSON/Markdown are read back by
wfkit.pilot_report.check_files. Only the group C amend cells (manifest observations) change between cases; every expected
figure below is a literal computed by hand from those observations, never from pilot_report.values or the generator.

Rule under test: amend_total = amend_authoring_error + amend_requirement_change + amend_emergent is counted only over the jobs
that have a value for all three parts; a job missing any part is out of numerator and denominator alike and is listed per part.
"""
import json
import tempfile
import unittest
from pathlib import Path

from wfkit import pilot_report as pr, pilot_tools as pt

IDS = [f'J{i}' for i in range(1, 11)]
PARTS = ('amend_authoring_error', 'amend_requirement_change', 'amend_emergent')
AT = '2026-10-24T0{h}:00:00+00:00'


def stub_root(i):
    # every job had an amend in its ledger (amends=1): an amend cause without an observation is "không có dữ liệu", never 0
    return {'plan': f'R{i}', 'selector': f'R{i}', 'revision': 1, 'status': 'accepted',
            'time_to_output': {'wall_minutes': 10, 'excluding_owner_wait_minutes': 8, 'verified_at': AT.format(h=1)},
            'waits': {'owner': {'minutes': 2}}, 'owner_decisions': {'total': 2},
            'rework': {'repair_rounds': 0, 'amends': 1}, 'check_cost': {'runs': 1, 'unknown_runs': 0, 'seconds': 60}}


def stub_facts():
    zero = {'value': 0, 'derived_from': 'synthetic stub'}
    return {'task': 'synthetic', 'actions': [{'verb': 'approve', 'kind': 'root_approval', 'at': AT.format(h=1)},
                                             {'verb': 'accept', 'kind': 'acceptance', 'at': AT.format(h=2)}],
            'interventions': 0, 'verdicts': {'pass': 1, 'fail': 0, 'inconclusive': 0}, 'open_findings': 0,
            'false_pass': dict(zero), 'skip_records': [], 'skip_links': [], 'skip_leak': dict(zero),
            'noise_stop_hook': dict(zero), 'wrong_scope_block': dict(zero), 'noise_notifications': dict(zero),
            'missed_wait_1h': dict(zero), 'providers': {'codex': {'calls': 1, 'failures': 0, 'reasons': {}, 'inconclusive_receipts': 0}}}


def generate(amends, tmp):
    """amends: {part: {job: number}} (the observed amend causes). Returns (report json, markdown, check result) read back from files."""
    jobs = [{'id': j, 'ledger': 'L1', 'root': f'R{i}', 'type': 'code', 'final_outcome': 'accepted'} for i, j in enumerate(IDS, 1)]
    ledgers = [{'id': 'L1', 'project': 'SYNTHETIC-PROJECT', 'state_root': 'SYNTHETIC-STATE-ROOT', 'commit': 'c' * 40,
                'wheel_sha256': 'b' * 64, 'synthetic': True}]
    measured = {j: stub_root(i) for i, j in enumerate(IDS, 1)}
    facts = {j: stub_facts() for j in IDS}
    outcomes = {j: {'rows': 1} for j in IDS}
    chat = {j: {'decision': 2} for j in IDS}
    obs = {'owner_minutes': {j: 1 for j in IDS}, 'owner_retries': {j: 0 for j in IDS}, 'owner_keystrokes': {j: 2 for j in IDS},
           'actual_actions': {j: 2 for j in IDS}, 'missed_wait_1h_owner': {j: 0 for j in IDS}}
    obs.update({p: dict(cells) for p, cells in amends.items()})
    manifest = {'schema': 1, 'kind': 'aggregate', 'synthetic': True, 'ledgers': ledgers, 'jobs': jobs, 'chat_log': chat,
                'observations': obs, 'decision_log': [],
                'continuation_trial': {'job': 'J1', 'tool': 'kiro', 'package_sha256': 'a' * 64,
                                       'answers': [{'question': q, 'correct': True} for q in pr.QUESTIONS],
                                       'grader': {'identity': 'agent-codex', 'model': 'gpt-5.5'}, 'coordinator_model': 'claude-opus-5-5'}}
    report = pt.build_aggregate(ledgers, jobs, measured, facts, outcomes, manifest, chat, obs, {'L1': sorted(f'R{i}' for i in range(1, 11))})
    text = pt.render_aggregate(report)
    json_path, md_path = pt.write_named(report, text, tmp, pt.AGG_FILES)
    return json.loads(json_path.read_text(encoding='utf-8')), md_path.read_text(encoding='utf-8'), pr.check_files(json_path, md_path)


def amend_total(report):
    return next(c for c in report['tiers']['tier1']['comparisons'] if c['metric'] == 'amend_total')


def amend_line(text):
    found = [line for line in text.splitlines() if line.startswith('- amend_total:')]
    assert len(found) == 1, found
    return found[0]


def zeros(*jobs):
    return {j: 0 for j in jobs}


class Tier1CompositeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='t1c')
        self.addCleanup(self.tmp.cleanup)

    def run_case(self, amends):
        report, text, res = generate(amends, Path(self.tmp.name))
        self.assertEqual(res['result'], 'pass', res['problems'])
        return report, text

    def test_full_data(self):
        # J2 authoring 1, J5 requirement 2, J7 emergent 1, every other cell 0: 1 + 2 + 1 = 4 amends over all ten jobs, 0.4 per job
        amends = {'amend_authoring_error': dict(zeros(*IDS), J2=1), 'amend_requirement_change': dict(zeros(*IDS), J5=2),
                  'amend_emergent': dict(zeros(*IDS), J7=1)}
        report, text = self.run_case(amends)
        c = amend_total(report)
        self.assertEqual((c['pilot_count'], c['pilot_jobs'], c['pilot_per_job']), (4, 10, 0.4))
        self.assertEqual(c['computed_from'], ['J1', 'J10', 'J2', 'J3', 'J4', 'J5', 'J6', 'J7', 'J8', 'J9'])
        self.assertEqual(c['missing'], {})
        self.assertEqual((c['complete'], c['pilot_denominator']), (True, 10))
        self.assertEqual(c['per_job'], {'J1': 0, 'J10': 0, 'J2': 1, 'J3': 0, 'J4': 0, 'J5': 2, 'J6': 0, 'J7': 1, 'J8': 0, 'J9': 0})
        line = amend_line(text)
        self.assertIn('pilot 4 trên 10 việc (0.4 mỗi việc)', line)
        self.assertNotIn('một phần', line)

    def test_component_missing_for_the_same_job_across_parts(self):
        # J3 has no amend cause at all: out of the composite. Remaining: J2 authoring 1 + J5 requirement 2 = 3 over nine jobs = 0.333
        others = [j for j in IDS if j != 'J3']
        amends = {'amend_authoring_error': dict(zeros(*others), J2=1), 'amend_requirement_change': dict(zeros(*others), J5=2),
                  'amend_emergent': zeros(*others)}
        report, text = self.run_case(amends)
        c = amend_total(report)
        self.assertEqual((c['pilot_count'], c['pilot_jobs'], c['pilot_per_job']), (3, 9, 0.333))
        self.assertNotIn('J3', c['computed_from'])
        self.assertEqual(c['missing'], {'amend_authoring_error': ['J3'], 'amend_requirement_change': ['J3'], 'amend_emergent': ['J3']})
        self.assertFalse(c['complete'])
        line = amend_line(text)
        self.assertIn('pilot 3 trên 9 việc', line)
        self.assertIn('so sánh một phần', line)
        self.assertIn('J3', line)

    def test_codex_case_one_part_missing_and_another_part_present_for_that_job(self):
        # Codex P2: J3 lacks amend_authoring_error but HAS amend_requirement_change 1. The old generator counted that 1 and divided by
        # nine (1/9); J3 is outside the job set, so only the other nine jobs count: all zero -> 0 over 9 jobs.
        others = [j for j in IDS if j != 'J3']
        amends = {'amend_authoring_error': zeros(*others), 'amend_requirement_change': dict(zeros(*IDS), J3=1),
                  'amend_emergent': zeros(*IDS)}
        report, text = self.run_case(amends)
        c = amend_total(report)
        self.assertEqual((c['pilot_count'], c['pilot_jobs'], c['pilot_per_job']), (0, 9, 0.0))
        self.assertEqual(c['computed_from'], ['J1', 'J10', 'J2', 'J4', 'J5', 'J6', 'J7', 'J8', 'J9'])
        self.assertEqual(c['missing'], {'amend_authoring_error': ['J3']})
        self.assertIn('pilot 0 trên 9 việc', amend_line(text))

    def test_missing_in_different_jobs_for_different_parts(self):
        # J3 lacks authoring (has requirement 1), J4 lacks requirement (has authoring 1), J6 lacks emergent (has requirement 3):
        # all three are out. In: J1 J2 J5 J7 J8 J9 J10 with J2 authoring 1 + J5 requirement 2 + J7 emergent 1 = 4 over 7 = 0.571
        amends = {'amend_authoring_error': dict(zeros(*[j for j in IDS if j != 'J3']), J2=1, J4=1),
                  'amend_requirement_change': dict(zeros(*[j for j in IDS if j != 'J4']), J3=1, J5=2, J6=3),
                  'amend_emergent': dict(zeros(*[j for j in IDS if j != 'J6']), J7=1)}
        report, text = self.run_case(amends)
        c = amend_total(report)
        self.assertEqual((c['pilot_count'], c['pilot_jobs'], c['pilot_per_job']), (4, 7, 0.571))
        self.assertEqual(c['computed_from'], ['J1', 'J10', 'J2', 'J5', 'J7', 'J8', 'J9'])
        self.assertEqual(c['missing'], {'amend_authoring_error': ['J3'], 'amend_requirement_change': ['J4'], 'amend_emergent': ['J6']})
        self.assertEqual(c['per_job'], {'J1': 0, 'J10': 0, 'J2': 1, 'J5': 2, 'J7': 1, 'J8': 0, 'J9': 0})
        line = amend_line(text)
        self.assertIn('pilot 4 trên 7 việc', line)
        for job in ('J3', 'J4', 'J6'):
            self.assertIn(job, line)

    def test_all_missing(self):
        report, text = self.run_case({})
        c = amend_total(report)
        self.assertEqual((c['pilot_count'], c['pilot_jobs'], c['pilot_per_job'], c['computed_from']), (None, 0, None, []))
        self.assertTrue(c['no_data'])
        self.assertIn('pilot: không có dữ liệu', amend_line(text))

    def test_parts_present_but_no_job_has_all_of_them(self):
        # authoring only J1-J5, requirement only J6-J10, emergent everywhere: no job has all three -> no data (the old code said 5 jobs)
        amends = {'amend_authoring_error': {'J1': 1, 'J2': 0, 'J3': 0, 'J4': 0, 'J5': 0},
                  'amend_requirement_change': {'J6': 2, 'J7': 0, 'J8': 0, 'J9': 0, 'J10': 0}, 'amend_emergent': zeros(*IDS)}
        report, text = self.run_case(amends)
        c = amend_total(report)
        self.assertEqual((c['pilot_count'], c['pilot_jobs'], c['computed_from']), (None, 0, []))
        self.assertIn('pilot: không có dữ liệu', amend_line(text))

    def test_valid_zero_counts(self):
        # every cause observed as 0 in every job: a real 0 over ten jobs, not "không có dữ liệu"
        report, text = self.run_case({p: zeros(*IDS) for p in PARTS})
        c = amend_total(report)
        self.assertEqual((c['pilot_count'], c['pilot_jobs'], c['pilot_per_job'], c['complete']), (0, 10, 0.0, True))
        self.assertNotIn('no_data', c)
        self.assertIn('pilot 0 trên 10 việc', amend_line(text))

    def test_checker_refuses_a_count_from_outside_the_published_job_set(self):
        # the Codex shape written by hand: computed_from without J3, pilot_count still adding J3's requirement amend (1 trên 9)
        others = [j for j in IDS if j != 'J3']
        amends = {'amend_authoring_error': zeros(*others), 'amend_requirement_change': dict(zeros(*IDS), J3=1), 'amend_emergent': zeros(*IDS)}
        tmp = Path(self.tmp.name)
        report, text, _ = generate(amends, tmp)
        c = amend_total(report)
        c['pilot_count'], c['pilot_per_job'] = 1, 0.111
        text = text.replace('pilot 0 trên 9 việc (0.0 mỗi việc)', 'pilot 1 trên 9 việc (0.111 mỗi việc)')
        report['figures_sha256'] = pr.figures_digest(report)
        res = pr.check_report(report, text)
        self.assertEqual(res['result'], 'refused')
        self.assertTrue(any('E6 tier 1 amend_total' in p and '0 trên 9' in p for p in res['problems']), res['problems'])
        # a job outside the job set added to computed_from (with its per-job sum) is refused too
        report, text, _ = generate(amends, tmp)
        c = amend_total(report)
        c['computed_from'] = sorted(c['computed_from'] + ['J3'])
        c['pilot_jobs'], c['pilot_count'] = 10, 1
        report['figures_sha256'] = pr.figures_digest(report)
        res = pr.check_report(report, text)
        self.assertEqual(res['result'], 'refused')
        self.assertTrue(any('E6 tier 1 amend_total' in p and 'computed_from' in p for p in res['problems']), res['problems'])

    def test_checker_refuses_a_partial_comparison_rendered_as_full(self):
        others = [j for j in IDS if j != 'J3']
        amends = {p: zeros(*others) for p in PARTS}
        report, text, _ = generate(amends, Path(self.tmp.name))
        line = amend_line(text)
        cut = line.split('; so sánh một phần')[0]
        res = pr.check_report(report, text.replace(line, cut))
        self.assertEqual(res['result'], 'refused')
        self.assertTrue(any('E6 tier 1 amend_total' in p and 'một phần' in p for p in res['problems']), res['problems'])
        c = amend_total(report)
        c['complete'], c['missing'] = True, {}
        report['figures_sha256'] = pr.figures_digest(report)
        res = pr.check_report(report, text)
        self.assertEqual(res['result'], 'refused')
        self.assertTrue(any('E6 tier 1 amend_total' in p and 'missing' in p for p in res['problems']), res['problems'])


class SingleMetricJobSetTests(unittest.TestCase):
    """The same class of mistake on the single-metric path: summary, computed_from, missing and target_status from one job set."""

    def test_single_metric_figures_use_the_jobs_with_a_value(self):
        with tempfile.TemporaryDirectory(prefix='t1s') as tmp:
            others = [j for j in IDS if j != 'J3']
            amends = {'amend_authoring_error': dict(zeros(*others), J4=2), 'amend_requirement_change': zeros(*IDS), 'amend_emergent': zeros(*IDS)}
            report, text, res = generate(amends, Path(tmp))
        self.assertEqual(res['result'], 'pass', res['problems'])
        m = next(x for x in report['metrics'] if x['id'] == 'amend_authoring_error')
        self.assertEqual((m['k'], m['summary']['value'], m['missing'], m['target_status']), (9, 2, ['J3'], 'không đạt'))
        self.assertEqual([x['job'] for x in m['computed_from']], ['J1', 'J10', 'J2', 'J4', 'J5', 'J6', 'J7', 'J8', 'J9'])
        z = next(x for x in report['metrics'] if x['id'] == 'amend_emergent')
        self.assertEqual((z['k'], z['summary']['value'], z['target_status']), (10, 0, 'đạt'))


if __name__ == '__main__':
    unittest.main()
