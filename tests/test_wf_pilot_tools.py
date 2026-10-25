"""W38b / W38c / W38d local tools (wfkit.pilot_tools), on FIXTURES only.

* report: the interim (T35b) generator runs over the fixture ledger of tests.test_wf_r03a_metrics (three finished plan roots built through the
  real plan code under a fake clock); its output must be accepted by wfkit.pilot_report.check_report (round trip), be deterministic, carry
  fixture provenance and no acceptance claim, and the checker must still refuse a forged copy.
* rerun-check: the A->B analysis of T45e (E23-E26) on a four-item fixture map.
* supp-run: supplementary checks run on a fixture "final wheel" (bytes written by the test), receipts read back through finalgate.Evidence.
No pilot, provider or owner decision is used or claimed.
"""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import test_wf_r03a_metrics as r03

from onecrew.v2 import outcome
from wfkit import pilot_report as pr, pilot_tools as pt
from wfkit.finalgate import Evidence

H = 'b' * 64
COMMIT = 'c' * 40


def manifest(**changes):
    m = {'schema': 1, 'kind': 'interim', 'fixture': True,
         'provenance': {'state_root': 'FIXTURE-STATE-ROOT', 'commit': COMMIT, 'wheel_sha256': H},
         'jobs': [{'id': 'J1', 'root': 'P1'}, {'id': 'J2', 'root': 'P2'}, {'id': 'J3', 'root': 'P3'}],
         'chat_log': {'J1': {'decision': 2, 'intervention': 0, 'outcome': 1}, 'J2': {'decision': 2, 'intervention': 0, 'outcome': 1},
                      'J3': {'decision': 4, 'intervention': 0, 'outcome': 1}},
         'observations': {'owner_minutes': {'J1': 3, 'J3': 9}, 'owner_retries': {'J1': 0, 'J2': 1, 'J3': 2}},
         'desktop_window': {'event_id': 'EV-1', 'emitted_at': '2026-10-24T12:00:00+00:00', 'shown_at': '2026-10-24T12:00:03+00:00',
                            'delivery_status': 'đã giao'}}
    m.update(changes)
    return m


class Generated(r03.ThreeRoots):
    def setUp(self):
        super().setUp()
        for name in ('P1', 'P2', 'P3'):
            outcome.record(self.ledger, name)


class ReportGeneratorTests(Generated):
    """One test method on purpose: building the three-root fixture ledger takes minutes on a loaded machine, so each case is a sub-test."""

    def case_round_trip_passes_the_existing_checker(self):
        report, text = pt.generate_interim(self.ledger, manifest())
        res = pr.check_report(report, text)
        self.assertEqual(res['result'], 'pass', res)
        self.assertEqual((res['owner_acceptance'], res['pilot_evidence'], res['simulated']), (False, False, True))

    def case_figures_come_from_the_ledger_and_unknown_is_not_zero(self):
        report, text = pt.generate_interim(self.ledger, manifest())
        by = {m['id']: m for m in report['metrics']}
        self.assertEqual([c['value'] for c in by['time_to_usable']['cells'].values()], [18, 4, 49])      # hand-worked in test_wf_r03a_metrics
        self.assertEqual([c['value'] for c in by['rework_rounds']['cells'].values()], [1, 0, 2])
        self.assertEqual([c['value'] for c in by['owner_decisions']['cells'].values()], [2, 2, 4])
        self.assertEqual(by['owner_minutes']['cells']['J2'], {'no_data': pr.NO_NOTES})                    # no owner note: not 0
        self.assertEqual(report['owner_notes_missing']['owner_minutes'], ['J2'])
        for mid in ('false_pass', 'noise_stop_hook', 'ledger_manual_fixes', 'owner_keystrokes'):
            self.assertEqual(by[mid]['k'], 0, mid)
            self.assertIn('no_data', by[mid]['summary'], mid)
        self.assertEqual(by['amend_authoring_error']['cells']['J3'], {'no_data': 'nguyên nhân amend không có trong sổ'})   # P3 had an amend
        self.assertEqual(by['amend_authoring_error']['cells']['J1'], {'value': 0})                         # P1 had none
        self.assertNotIn('skip_leak', by)
        self.assertNotIn('baseline', text.lower())
        detail = {d['job']: d for d in report['jobs_detail']}
        self.assertEqual((detail['J3']['verdicts'], detail['J3']['revision'], detail['J3']['status']), ({'pass': 1, 'fail': 2}, 2, 'accepted'))
        self.assertEqual(detail['J3']['open_findings'], pt.UNKNOWN)

    def case_deterministic_and_provenance_without_acceptance(self):
        a = pt.generate_interim(self.ledger, manifest())
        b = pt.generate_interim(self.ledger, manifest())
        self.assertEqual(a, b)
        report, text = a
        self.assertEqual(report['provenance'], {'kind': 'fixture', 'state_root': 'FIXTURE-STATE-ROOT', 'commit': COMMIT, 'wheel_sha256': H,
                                                'generator': 'wfkit.pilot_tools report'})
        self.assertIn('fixture, không phải pilot thật', text)
        self.assertIn('không phải nghiệm thu', text)
        self.assertIs(report['owner_acceptance'], False)
        self.assertIs(report['pilot_evidence'], False)

    def case_files_are_written_and_checkable_by_the_cli_checker(self):
        report, text = pt.generate_interim(self.ledger, manifest())
        with tempfile.TemporaryDirectory() as tmp:
            j, m = pt.write_report(report, text, tmp)
            self.assertEqual(pr.check_files(j, m)['result'], 'pass')

    def case_refuses_a_forged_report(self):
        report, text = pt.generate_interim(self.ledger, manifest())
        forged = json.loads(json.dumps(report))
        by = {m['id']: m for m in forged['metrics']}
        by['owner_minutes']['cells']['J2'] = {'value': 0}                    # a missing note turned into 0
        res = pr.check_report(forged, text)
        self.assertEqual(res['result'], 'refused')
        self.assertTrue(any('E35' in p or 'E23' in p or 'E7' in p for p in res['problems']), res['problems'])
        forged = json.loads(json.dumps(report))
        forged['ledger_columns']['hand_filled'] = 1
        self.assertEqual(pr.check_report(forged, text)['result'], 'refused')
        self.assertEqual(pr.check_report(report, text + 'Ghi chú: đã có baseline sơ bộ.\n')['result'], 'refused')
        forged = json.loads(json.dumps(report))
        forged['owner_acceptance'] = True
        self.assertEqual(pr.check_report(forged, text)['result'], 'refused')

    def case_chat_ledger_mismatch_is_reported_with_both_sources_not_hidden(self):
        m = manifest()
        m['chat_log']['J2']['decision'] = 5
        report, text = pt.generate_interim(self.ledger, m)
        row = next(r for r in report['ledger_columns']['rows'] if (r['job'], r['column']) == ('J2', 'decision'))
        self.assertEqual((row['ledger'], row['chat'], row['match']), (2, 5, False))
        self.assertTrue(row['reason'])
        self.assertEqual(pr.check_report(report, text)['result'], 'pass')

    def case_missing_outcome_row_is_listed_and_the_report_is_refused_by_the_checker(self):
        with self.ledger.transaction(write=True) as conn:
            for row in conn.execute("SELECT seq, payload FROM events WHERE kind='learning.outcome'").fetchall():
                if json.loads(row['payload']).get('plan_revision') == 1:
                    conn.execute('DELETE FROM events WHERE seq=?', (row['seq'],))
        report, text = pt.generate_interim(self.ledger, manifest())
        gaps = report['outcomes']['missing']
        self.assertTrue(gaps)
        res = pr.check_report(report, text)
        self.assertEqual(res['result'], 'refused')
        self.assertTrue(any('E25' in p for p in res['problems']), res['problems'])

    # ---- refusals of the generator itself ----------------------------------------------------------------------------
    def test_generator(self):
        order = ['round_trip_passes_the_existing_checker', 'figures_come_from_the_ledger_and_unknown_is_not_zero', 'deterministic_and_provenance_without_acceptance', 'files_are_written_and_checkable_by_the_cli_checker', 'refuses_a_forged_report', 'chat_ledger_mismatch_is_reported_with_both_sources_not_hidden', 'missing_outcome_row_is_listed_and_the_report_is_refused_by_the_checker', 'refuses_aggregate_kind', 'refuses_hand_filled_group_a_and_missing_chat_log', 'refuses_unknown_root_and_unended_root', 'refuses_undeclared_fixture_flag_and_missing_provenance']
        for name in order:
            with self.subTest(name):
                getattr(self, 'case_' + name)()

    def refuses(self, m, needle):
        with self.assertRaises(pt.ReportError) as ctx:
            pt.generate_interim(self.ledger, m)
        self.assertIn(needle, str(ctx.exception))

    def case_refuses_aggregate_kind(self):
        self.refuses(manifest(kind='aggregate'), 'only kind "interim"')

    def case_refuses_hand_filled_group_a_and_missing_chat_log(self):
        self.refuses(manifest(observations={'time_to_usable': {'J1': 1}}), 'only supply group B/C')
        m = manifest()
        del m['chat_log']['J3']
        self.refuses(m, 'chat_log needs')

    def case_refuses_unknown_root_and_unended_root(self):
        m = manifest()
        m['jobs'][0]['root'] = 'NOPE'
        self.refuses(m, 'not exactly one plan root')
        self.propose('P4', r03.plan_json(title='Fourth'))
        m = manifest()
        m['jobs'][0]['root'] = 'P4'
        self.refuses(m, 'has not ended')

    def case_refuses_undeclared_fixture_flag_and_missing_provenance(self):
        m = manifest()
        del m['fixture']
        self.refuses(m, 'fixture must be declared')
        m = manifest()
        m['provenance']['wheel_sha256'] = 'zz'
        self.refuses(m, 'provenance needs')


# ---- W38d: re-run plan ------------------------------------------------------------------------------------------------

SRC = {'commit': 'a' * 40, 'wheel_sha256': 'a' * 64}
DST = {'commit': 'd' * 40, 'wheel_sha256': 'd' * 64}


def analysis(**changes):
    a = {'schema': 1, 'source': SRC, 'target': DST, 'changed_files': ['onecrew/a.py'],
         'items': [{'id': 'T1', 'owned': ['onecrew/a.py'], 'depends_on': []}, {'id': 'T2', 'owned': ['onecrew/b.py'], 'depends_on': ['T1']},
                   {'id': 'T3', 'owned': ['onecrew/c.py'], 'depends_on': []}, {'id': 'T4', 'owned': ['onecrew/d.py'], 'depends_on': []}],
         'jobs': [{'id': 'J1', 'items': ['T1']}, {'id': 'J2', 'items': ['T2']}, {'id': 'J3', 'items': ['T3']}, {'id': 'J4', 'items': ['T4']}],
         'evidence': [{'job': 'J3', 'wheel_sha256': SRC['wheel_sha256']}, {'job': 'J4', 'wheel_sha256': SRC['wheel_sha256']}]}
    a.update(changes)
    return a


def good_plan(**changes):
    p = {'rerun_jobs': ['J1', 'J2'], 'supplements': {'T1': ['chk-1'], 'T2': ['chk-2']}}
    p.update(changes)
    return p


class RerunPlanTests(unittest.TestCase):
    def refused(self, a, p, needle):
        res = pt.check_rerun_plan(a, p)
        self.assertEqual(res['result'], 'refused', res)
        self.assertTrue(any(needle in x for x in res['problems']), res['problems'])
        return res

    def test_good_plan_reruns_exactly_the_affected_jobs(self):
        res = pt.check_rerun_plan(analysis(), good_plan())
        self.assertEqual(res['result'], 'pass', res)
        self.assertEqual((res['affected_items'], res['rerun_required']), (['T1', 'T2'], ['J1', 'J2']))     # T2 depends on T1: spread by dependency_core
        self.assertEqual((res['owner_acceptance'], res['pilot_evidence']), (False, False))

    def test_refuses_the_whole_pilot(self):
        self.refused(analysis(), good_plan(rerun_jobs=['J1', 'J2', 'J3', 'J4']), 'chạy lại toàn bộ pilot không theo phân tích')

    def test_refuses_skipping_an_affected_job(self):
        res = self.refused(analysis(), good_plan(rerun_jobs=['J1']), 'bỏ qua việc bị ảnh hưởng: J2')
        self.assertEqual(res['rerun_required'], ['J1', 'J2'])

    def test_refuses_an_unaffected_job_and_an_unknown_one(self):
        self.refused(analysis(), good_plan(rerun_jobs=['J1', 'J2', 'J3']), 'chạy lại việc không bị ảnh hưởng')
        self.refused(analysis(), good_plan(rerun_jobs=['J1', 'J2', 'J9']), 'not pilot jobs')

    def test_file_outside_the_map_affects_every_item_so_rerunning_all_is_allowed(self):
        a = analysis(changed_files=['onecrew/a.py', 'onecrew/new.py'])
        res = pt.check_rerun_plan(a, good_plan(rerun_jobs=['J1', 'J2', 'J3', 'J4'], supplements={t: ['x'] for t in ('T1', 'T2', 'T3', 'T4')}))
        self.assertEqual(res['result'], 'pass', res)
        self.assertEqual(res['outside_map'], ['onecrew/new.py'])
        self.refused(a, good_plan(), 'bỏ qua việc bị ảnh hưởng: J3, J4')

    def test_refuses_missing_analysis_and_missing_supplement_and_changed_hash(self):
        self.refused(analysis(), None, 'kế thừa không có phân tích')
        self.refused(analysis(), good_plan(supplements={'T1': ['chk-1']}), 'mục bị ảnh hưởng thiếu kiểm bổ sung: T2')
        res = self.refused(analysis(evidence=[{'job': 'J3', 'wheel_sha256': DST['wheel_sha256']}]), good_plan(), 'hash bằng chứng bị đổi')
        self.assertIn(DST['wheel_sha256'], ' '.join(res['problems']))
        self.assertIn(SRC['wheel_sha256'], ' '.join(res['problems']))

    def test_refuses_malformed_analysis(self):
        a = analysis()
        a['jobs'][0]['items'] = ['T9']
        self.refused(a, good_plan(), 'INPUT: pilot jobs must each name known items')
        self.refused(analysis(source=DST), good_plan(), 'đối chiếu sai cặp hash')

    def test_nothing_changed_requires_no_rerun(self):
        res = pt.check_rerun_plan(analysis(changed_files=[]), {'rerun_jobs': [], 'supplements': {}})
        self.assertEqual(res['result'], 'pass', res)


# ---- W38d: supplementary checks run on the final artifact ---------------------------------------------------------------

class SupplementRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        wheel = b'fixture wheel bytes'
        (self.root / 'final.whl').write_bytes(wheel)
        self.sha = hashlib.sha256(wheel).hexdigest()
        self.final = {'commit': 'f' * 40, 'wheel_sha256': self.sha}
        self.ref = self.write('final-receipt.json', dict(self.final, result='pass', at='2026-10-25T10:00:00+00:00', simulated=True,
                                                         provenance={'kind': 'fixture', 'source': 'test'}))

    def write(self, name, body):
        raw = json.dumps(body, sort_keys=True).encode('utf-8')
        (self.root / name).write_bytes(raw)
        return {'path': name, 'sha256': hashlib.sha256(raw).hexdigest()}

    def spec(self, **changes):
        ok = [sys.executable, '-c', 'import os,sys; sys.exit(0 if os.environ["ONECREW_FINAL_WHEEL_SHA256"] else 3)']
        s = {'schema': 1, 'mode': 'fixture', 'artifact': dict(self.final, wheel='final.whl'), 'final_receipt': self.ref,
             'affected': ['AC1'], 'checks': [{'id': 'c1', 'item': 'AC1', 'argv': ok}]}
        s.update(changes)
        return s

    def run_spec(self, spec):
        return pt.run_supplements(spec, self.root, self.root / 'out', now=lambda: '2026-10-25T11:00:00+00:00')

    def test_runs_the_check_and_writes_receipts_readable_by_finalgate(self):
        res = self.run_spec(self.spec())
        self.assertEqual((res['results'], res['all_pass']), ({'c1': 'pass'}, True))
        receipt = Evidence(self.root, True).read(res['receipts']['c1'])
        self.assertEqual((receipt['kind'], receipt['item'], receipt['result'], receipt['wheel_sha256'], receipt['simulated']),
                         ('supplement', 'AC1', 'pass', self.sha, True))
        self.assertEqual(receipt['check']['exit_code'], 0)
        self.assertEqual(receipt['provenance'], {'kind': 'fixture', 'source': 'wfkit.pilot_tools supp-run'})
        self.assertIs(res['owner_acceptance'], False)

    def test_failing_and_unstartable_checks_are_recorded_not_passed(self):
        bad = [sys.executable, '-c', 'import sys; sys.exit(7)']
        res = self.run_spec(self.spec(checks=[{'id': 'c1', 'item': 'AC1', 'argv': bad}, {'id': 'c2', 'item': 'AC1', 'argv': ['no-such-program-xyz']}]))
        self.assertEqual(res['results'], {'c1': 'fail', 'c2': 'blocked'})
        self.assertFalse(res['all_pass'])
        blocked = Evidence(self.root, True).read(res['receipts']['c2'])
        self.assertTrue(blocked['reason'])

    def test_refuses_a_wheel_that_differs_from_the_artifact(self):
        (self.root / 'final.whl').write_bytes(b'another wheel')
        with self.assertRaises(ValueError) as ctx:
            self.run_spec(self.spec())
        self.assertIn('differs from the artifact', str(ctx.exception))
        self.assertFalse((self.root / 'out').exists())                               # nothing ran, nothing written

    def test_refuses_a_receipt_with_another_wheel_sha(self):
        other = self.write('other.json', dict(self.final, wheel_sha256='e' * 64, result='pass', at='2026-10-25T10:00:00+00:00', simulated=True,
                                              provenance={'kind': 'fixture', 'source': 'test'}))
        with self.assertRaises(ValueError) as ctx:
            self.run_spec(self.spec(final_receipt=other))
        self.assertIn('wheel sha of the receipt given', str(ctx.exception))
        self.assertFalse((self.root / 'out').exists())

    def test_refuses_an_affected_item_without_a_check_and_a_real_mode_fixture_receipt(self):
        with self.assertRaises(ValueError) as ctx:
            self.run_spec(self.spec(affected=['AC1', 'AC2']))
        self.assertIn('mục bị ảnh hưởng thiếu kiểm bổ sung: AC2', str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            self.run_spec(self.spec(mode='real'))
        self.assertIn('simulated evidence cannot prove a real gate', str(ctx.exception))

    def test_refuses_a_tampered_receipt_reference(self):
        ref = dict(self.ref, sha256='0' * 64)
        with self.assertRaises(ValueError) as ctx:
            self.run_spec(self.spec(final_receipt=ref))
        self.assertIn('receipt hash changed', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
