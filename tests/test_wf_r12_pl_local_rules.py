"""Round 12, WKPL / T45e: three LOCAL rules (E19, E20, E27) of the A->B comparison, on synthetic fixtures only.

E19  acceptance-report lines on B: AC1-AC3 "chỉ bộ kiểm, chưa có việc thật trên B", R06-R08 "chỉ bộ kiểm, chưa dùng thật",
     the SKIP leak "không có dữ liệu"; a claim of real use without owner-chosen (U3) pilot data on B is refused; the count of
     items marked "đạt" on B without a check on B is 0.
E20  the pilot-checker rerun on the final artifact is labelled "kiểm báo cáo" and has no behaviour column (HL4).
E27  the comparison yields, per item, the affected flag, the basis and the (A, B) hash pair; the three record kinds sit in
     three separate files and no write edits a kind-1 record.

The real A->B comparison on two real builds and the real PL-B ledger stay external (U3); nothing here is pilot evidence.
"""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import test_wf_finalgate as base
from wfkit import finalgate as fg
from tests import test_wf_pilot_report as report_fixture
from wfkit import pilot_report as pr
from wfkit import pilot_tools as pt

SYN = {'commit': 'b' * 40, 'wheel_sha256': 'b' * 64}
OTHER = {'commit': 'a' * 40, 'wheel_sha256': 'a' * 64}


def real_work(target, **kw):
    row = dict(target, kind='pilot', simulated=False, authorized_by='U3', result='pass')
    row.update(kw)
    return row


class E19AcceptanceLinesTests(unittest.TestCase):
    def line(self, report, item):
        return next(x for x in report['lines'] if x['item'] == item)

    def test_default_report_carries_the_required_status_words(self):
        report = fg.acceptance_report(SYN)
        self.assertEqual([], fg.check_acceptance_report(report, SYN))
        for item in ('AC1', 'AC2', 'AC3'):
            self.assertIn('chỉ bộ kiểm, chưa có việc thật trên B', self.line(report, item)['text'])
        for item in ('R06', 'R07', 'R08'):
            self.assertIn('chỉ bộ kiểm, chưa dùng thật', self.line(report, item)['text'])
        self.assertIn('không có dữ liệu', self.line(report, 'skip_leak')['text'])
        self.assertEqual(0, fg.passed_without_check_on_target(report, SYN))

    def test_real_use_without_pilot_data_is_refused(self):
        for item in ('AC1', 'R07', 'skip_leak'):
            with self.subTest(item=item):
                report = fg.acceptance_report(SYN)
                row = self.line(report, item)
                row.update(status='đạt', text=f'{item}: đã dùng thật trên B')
                problems = fg.check_acceptance_report(report, SYN)
                self.assertTrue(any(item in p and 'dữ liệu pilot' in p for p in problems), problems)
                self.assertEqual(1, fg.passed_without_check_on_target(report, SYN))

    def test_real_work_receipts_that_do_not_count_are_refused(self):
        for label, bad in (('simulated', real_work(SYN, simulated=True)),
                           ('not owner chosen', real_work(SYN, authorized_by='coordinator')),
                           ('other build', real_work(OTHER)),
                           ('not pilot', real_work(SYN, kind='supplement')),
                           ('failed', real_work(SYN, result='fail'))):
            with self.subTest(label):
                report = fg.acceptance_report(SYN)
                row = self.line(report, 'AC2')
                row.update(status='đạt', text='AC2: việc thật trên B', real_work_on_target=[bad])
                problems = fg.check_acceptance_report(report, SYN)
                self.assertTrue(any('AC2' in p and 'dữ liệu pilot' in p for p in problems), problems)

    def test_owner_chosen_real_work_on_b_may_replace_the_partial_words(self):
        report = fg.acceptance_report(SYN, real_work=[real_work(SYN, item='AC1')])
        self.assertEqual('đạt', self.line(report, 'AC1')['status'])
        self.assertEqual([], fg.check_acceptance_report(report, SYN))
        self.assertEqual(0, fg.passed_without_check_on_target(report, SYN))
        # the other items keep their words
        self.assertIn('chỉ bộ kiểm, chưa có việc thật trên B', self.line(report, 'AC2')['text'])

    def test_passed_on_b_needs_a_passing_check_on_b(self):
        report = fg.acceptance_report(SYN)
        row = self.line(report, 'AC3')
        row.update(status='đạt', text='AC3: bốn loại', checks_on_target=[dict(OTHER, result='pass')])
        self.assertEqual(1, fg.passed_without_check_on_target(report, SYN))
        self.assertTrue(any('AC3' in p and 'kiểm trên B' in p for p in fg.check_acceptance_report(report, SYN)))
        row['checks_on_target'] = [dict(SYN, result='pass')]
        self.assertEqual(0, fg.passed_without_check_on_target(report, SYN))

    def test_missing_line_and_changed_words_are_refused(self):
        report = fg.acceptance_report(SYN)
        report['lines'] = [x for x in report['lines'] if x['item'] != 'R08']
        self.assertTrue(any('R08' in p and 'thiếu' in p for p in fg.check_acceptance_report(report, SYN)))
        for item, wrong in (('AC1', 'chỉ bộ kiểm'), ('R06', 'chưa dùng thật'), ('skip_leak', '0')):
            with self.subTest(item=item):
                report = fg.acceptance_report(SYN)
                self.line(report, item)['text'] = wrong
                self.assertTrue(any(item in p and 'chỉ bộ kiểm' in p or item in p and 'không có dữ liệu' in p
                                    for p in fg.check_acceptance_report(report, SYN)), item)
        report = fg.acceptance_report(SYN)
        report['lines'].append(dict(report['lines'][0]))
        self.assertTrue(any('trùng' in p for p in fg.check_acceptance_report(report, SYN)))

    def test_malformed_report_fails_closed(self):
        for value in (None, [], {}, {'lines': 'x'}, {'lines': [1]}):
            with self.subTest(value=value):
                self.assertTrue(fg.check_acceptance_report(value, SYN))


class E20RerunLabelTests(unittest.TestCase):
    def test_rerun_is_labelled_report_check_without_behaviour_column(self):
        row = pr.rerun_row(SYN)
        self.assertEqual('kiểm báo cáo', row['label'])
        self.assertEqual([], pr.check_rerun_row(row, SYN))
        self.assertTrue(all('hành vi' not in c.casefold() and 'behavio' not in c.casefold() for c in row['columns']))
        self.assertIn('kiểm báo cáo', row['line'])

    def test_a_behaviour_column_is_refused(self):
        for column in ('hành vi của B', 'Hành vi', 'behavior', 'behaviour_on_b'):
            with self.subTest(column=column):
                row = pr.rerun_row(SYN)
                row['columns'] = row['columns'] + [column]
                problems = pr.check_rerun_row(row, SYN)
                self.assertTrue(any('cột hành vi' in p for p in problems), problems)

    def test_missing_or_other_label_is_refused(self):
        for mutate in (lambda r: r.pop('label'), lambda r: r.update(label='bằng chứng hành vi'),
                       lambda r: r.update(label='kiểm báo cáo '), lambda r: r.update(line='đạt: bộ kiểm pilot chạy trên B')):
            row = pr.rerun_row(SYN)
            mutate(row)
            problems = pr.check_rerun_row(row, SYN)
            self.assertTrue(any('kiểm báo cáo' in p for p in problems), problems)

    def test_rerun_is_never_behaviour_evidence(self):
        row = pr.rerun_row(SYN)
        row.update(kind='behavior')
        self.assertTrue(any('không là bằng chứng hành vi' in p for p in pr.check_rerun_row(row, SYN)))
        row = pr.rerun_row(SYN)
        row['behavior_evidence'] = True
        self.assertTrue(any('không là bằng chứng hành vi' in p for p in pr.check_rerun_row(row, SYN)))
        # and the gate evaluator itself does not take the rerun as behavioural evidence (HL4)
        receipt = dict(pr.rerun_row(SYN), result='pass', at='2026-10-24T12:00:00Z')
        with self.assertRaisesRegex(ValueError, 'not behavioral evidence'):
            fg.evidence_status(receipt, [], SYN)

    def test_wrong_artifact_is_refused(self):
        row = pr.rerun_row(OTHER)
        self.assertTrue(any('artifact cuối' in p for p in pr.check_rerun_row(row, SYN)))

    def test_malformed_row_fails_closed(self):
        for value in (None, [], {}, {'label': 'kiểm báo cáo'}):
            with self.subTest(value=value):
                self.assertTrue(pr.check_rerun_row(value, SYN))


class E27ComparisonRecordTests(unittest.TestCase):
    def setUp(self):
        self.fx = base.FinalGateTests()
        self.addCleanup(self.fx.doCleanups)
        self.fx.setUp()
        self.computed = fg.compare(self.fx.bundle, fg.Evidence(self.fx.root, True))
        self.records = self.computed['records']
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)

    def record(self, item):
        return next(r for r in self.records if r['item'] == item)

    def test_every_item_has_flag_basis_and_hash_pair(self):
        self.assertEqual(sorted(self.computed['items']), [r['item'] for r in self.records])
        pair = {'A': self.computed['source'], 'B': self.computed['target']}
        for r in self.records:
            self.assertIsInstance(r['affected'], bool)
            self.assertTrue(r['basis'])
            self.assertEqual(pair, r['hashes'])
            self.assertEqual(2, r['kind'])
        self.assertEqual(self.computed['affected'], sorted(r['item'] for r in self.records if r['affected']))
        self.assertEqual([], fg.check_comparison_records(self.records, self.computed))

    def test_basis_names_changed_file_dependency_and_owned_paths(self):
        self.assertEqual([{'via': 'changed_file', 'files': ['onecrew/reviewer.py']}], self.record('codex:reviewer')['basis'])
        # AC1 depends_on codex:reviewer (changed): propagates through depends_on
        self.assertEqual([{'via': 'depends_on', 'items': ['codex:reviewer']}], self.record('AC1')['basis'])
        self.assertFalse(self.record('AC2')['affected'])
        self.assertEqual([{'via': 'unchanged'}], self.record('AC2')['basis'])

    def test_file_outside_the_map_is_the_basis_of_every_item(self):
        computed = copy.deepcopy(self.computed)
        computed['changed_files'] = ['onecrew/new_module.py']
        computed['affected'] = sorted(computed['items'])
        records = fg.comparison_records(computed)
        self.assertTrue(all(r['affected'] and r['basis'] == [{'via': 'unmapped_file', 'files': ['onecrew/new_module.py']}] for r in records))

    def test_incomplete_or_wrong_records_are_refused(self):
        def problems(mutate):
            records = copy.deepcopy(self.records)
            mutate(records)
            return fg.check_comparison_records(records, self.computed)
        cases = {
            'missing item': lambda rs: rs.pop(0),
            'flag missing': lambda rs: rs[0].pop('affected'),
            'flag wrong': lambda rs: rs[0].update(affected=not rs[0]['affected']),
            'basis missing': lambda rs: rs[0].pop('basis'),
            'basis empty': lambda rs: rs[0].update(basis=[]),
            'basis wrong': lambda rs: rs[0].update(basis=[{'via': 'changed_file', 'files': ['x.py']}]),
            'hash pair missing': lambda rs: rs[0].pop('hashes'),
            'hash pair swapped': lambda rs: rs[0].update(hashes={'A': rs[0]['hashes']['B'], 'B': rs[0]['hashes']['A']}),
            'hash B equals A': lambda rs: rs[0].update(hashes={'A': rs[0]['hashes']['A'], 'B': rs[0]['hashes']['A']}),
            'wrong kind': lambda rs: rs[0].update(kind=1),
        }
        for label, mutate in cases.items():
            with self.subTest(label):
                self.assertTrue(problems(mutate), label)

    def test_three_kinds_live_in_three_separate_files(self):
        kind1 = self.out / 'original-evidence.json'
        kind1.write_text('{"kind": 1}', encoding='utf-8')
        sha = hashlib.sha256(kind1.read_bytes()).hexdigest()
        layout = {1: [kind1], 2: [self.out / 'comparison-result.json'], 3: [self.out / 'gate-receipt.json']}
        self.assertEqual([], fg.check_record_layout(layout, {str(kind1): sha}))
        same = {1: [kind1], 2: [kind1], 3: [layout[3][0]]}
        self.assertTrue(any('tách' in p for p in fg.check_record_layout(same, {str(kind1): sha})))
        shared = {1: [kind1], 2: [layout[2][0]], 3: [layout[2][0]]}
        self.assertTrue(any('tách' in p for p in fg.check_record_layout(shared, {str(kind1): sha})))
        self.assertTrue(fg.check_record_layout({1: [kind1], 2: [layout[2][0]]}, {str(kind1): sha}))

    def test_writer_refuses_to_edit_a_kind_1_record(self):
        kind1 = self.out / 'original-evidence.json'
        fg.write_record(1, kind1, {'kind': 1, 'item': 'AC1'}, {})
        pins = {str(kind1): hashlib.sha256(kind1.read_bytes()).hexdigest()}
        # a kind-2 write aimed at the kind-1 file
        with self.assertRaisesRegex(ValueError, 'kind-1'):
            fg.write_record(2, kind1, {'kind': 2, 'records': self.records}, pins)
        # a kind-3 write too
        with self.assertRaisesRegex(ValueError, 'kind-1'):
            fg.write_record(3, kind1, {'kind': 3}, pins)
        # kind 1 is never rewritten
        with self.assertRaisesRegex(ValueError, 'kind-1'):
            fg.write_record(1, kind1, {'kind': 1, 'item': 'AC1', 'hash': 'new'}, pins)
        self.assertEqual({'kind': 1, 'item': 'AC1'}, json.loads(kind1.read_text(encoding='utf-8')))
        # a pinned file edited behind the writer's back is reported
        kind1.write_text('{"kind": 1, "item": "edited"}', encoding='utf-8')
        self.assertTrue(any('kind-1' in p for p in fg.verify_kind1_unchanged(pins)))

    def test_writer_writes_kind_2_and_3_to_their_own_files(self):
        kind1 = self.out / 'original-evidence.json'
        fg.write_record(1, kind1, {'kind': 1}, {})
        pins = {str(kind1): hashlib.sha256(kind1.read_bytes()).hexdigest()}
        two, three = self.out / 'comparison-result.json', self.out / 'gate-receipt.json'
        fg.write_record(2, two, {'kind': 2, 'records': self.records}, pins)
        fg.write_record(3, three, {'kind': 3, 'gate': 'CG-KET'}, pins)
        self.assertEqual([], fg.verify_kind1_unchanged(pins))
        self.assertEqual([], fg.check_record_layout({1: [kind1], 2: [two], 3: [three]}, pins))
        self.assertEqual(2, json.loads(two.read_text(encoding='utf-8'))['kind'])
        with self.assertRaisesRegex(ValueError, 'kind'):
            fg.write_record(2, self.out / 'x.json', {'kind': 1}, pins)

    def test_decide_exposes_the_per_item_records(self):
        result = fg.decide(self.fx.bundle, self.fx.root, allow_simulated=True)
        self.assertEqual('pass', result['decision'], result)
        self.assertEqual(self.records, result['comparison']['records'])

class PipelineWiringTests(unittest.TestCase):
    """The rules are enforced where a final gate / a pilot report is judged, not only when a caller remembers the helper."""

    def setUp(self):
        self.fx = base.FinalGateTests()
        self.addCleanup(self.fx.doCleanups)
        self.fx.setUp()
        self.ident = {k: self.fx.b[k] for k in ('commit', 'wheel_sha256')}

    def decide(self):
        return fg.decide(self.fx.bundle, self.fx.root, allow_simulated=True)

    def computed(self):
        return fg.compare(self.fx.bundle, fg.Evidence(self.fx.root, True))

    def refused_for(self, needle):
        result = self.decide()
        self.assertEqual('refused', result['decision'], result)
        detail = next((r['detail'] for r in result['reasons'] if r['code'] == 'KQ2'), '')
        self.assertIn(needle, detail, result['reasons'])
        self.assertFalse(result['conditions']['KQ2'])

    def test_conforming_inputs_still_pass_through_decide(self):
        b = self.fx.bundle
        b['acceptance_report'] = fg.acceptance_report(self.ident)
        b['rerun'] = pr.rerun_row(self.ident)
        b['comparison']['records'] = self.computed()['records']
        self.assertEqual('pass', self.decide()['decision'])

    def test_acceptance_report_violation_is_refused_by_decide(self):
        b = self.fx.bundle
        report = fg.acceptance_report(self.ident)
        report['lines'][0].update(status='đạt', text='AC1: đã dùng thật trên B')
        b['acceptance_report'] = report
        self.refused_for('AC1')
        report = fg.acceptance_report(self.ident)
        report['lines'] = [x for x in report['lines'] if x['item'] != 'R06']
        b['acceptance_report'] = report
        self.refused_for('R06')

    def test_rerun_violation_is_refused_by_decide(self):
        b = self.fx.bundle
        row = pr.rerun_row(self.ident)
        row['columns'] = row['columns'] + ['hành vi của B']
        b['rerun'] = row
        self.refused_for('cột hành vi')
        b['rerun'] = dict(pr.rerun_row(self.ident), label='bằng chứng hành vi')
        self.refused_for('kiểm báo cáo')

    def test_comparison_record_violation_is_refused_by_decide(self):
        b = self.fx.bundle
        records = self.computed()['records']
        records[0]['affected'] = not records[0]['affected']
        b['comparison']['records'] = records
        self.refused_for('affected flag')

    def test_record_layout_violation_is_refused_by_decide(self):
        b = self.fx.bundle
        kind1 = self.fx.root / 'original.json'
        kind1.write_text('{"kind": 1}', encoding='utf-8')
        sha = hashlib.sha256(kind1.read_bytes()).hexdigest()
        b['record_files'] = {'layout': {'1': ['original.json'], '2': ['result.json'], '3': ['gate.json']}, 'kind1_pins': {'original.json': sha}}
        self.assertEqual('pass', self.decide()['decision'])
        b['record_files']['layout']['2'] = ['original.json']
        self.refused_for('tách')
        b['record_files']['layout']['2'] = ['result.json']
        kind1.write_text('{"kind": 1, "edited": true}', encoding='utf-8')
        self.refused_for('kind-1 record edited')

    def test_real_mode_requires_the_four_inputs(self):
        problems = fg.t45e_local_problems(self.fx.bundle, self.computed(), self.fx.root, required=True)
        for needle in ('acceptance_report', 'rerun', 'records', 'record_files'):
            self.assertTrue(any(needle in p for p in problems), (needle, problems))
        self.assertEqual([], fg.t45e_local_problems(self.fx.bundle, self.computed(), self.fx.root))


class ReportWiringTests(unittest.TestCase):
    """pilot_report.check_report and pilot_tools.verify judge the rerun row of an aggregate report."""

    def aggregate(self, row=True):
        r = report_fixture.build('aggregate')
        if row:
            pt.attach_final_rerun(r, SYN)
        return r, report_fixture.render(r) + ('\n' + r['rerun_on_final']['line'] if row else '')

    def test_plain_aggregate_and_conforming_rerun_pass(self):
        r, text = self.aggregate(False)
        self.assertEqual('pass', pr.check_report(r, text)['result'])
        r, text = self.aggregate()
        self.assertEqual(SYN, r['final_artifact'])
        self.assertEqual('pass', pr.check_report(r, text)['result'], pr.check_report(r, text)['problems'])

    def refused(self, mutate, needle, text_edit=None):
        r, text = self.aggregate()
        mutate(r)
        r['figures_sha256'] = pr.figures_digest(r)
        res = pr.check_report(r, text_edit(text) if text_edit else text)
        self.assertEqual('refused', res['result'], res)
        self.assertTrue(any(needle in p for p in res['problems']), res['problems'])

    def test_rerun_violations_are_refused_by_check_report(self):
        self.refused(lambda r: r['rerun_on_final'].update(label='bằng chứng hành vi'), 'kiểm báo cáo')
        self.refused(lambda r: r['rerun_on_final']['columns'].append('hành vi của B'), 'cột hành vi')
        self.refused(lambda r: r['rerun_on_final'].update(kind='behavior'), 'không là bằng chứng hành vi')
        self.refused(lambda r: r['rerun_on_final'].update(commit='a' * 40, wheel_sha256='a' * 64), 'artifact cuối')
        self.refused(lambda r: r.pop('rerun_on_final'), 'rerun_on_final')
        self.refused(lambda r: r.pop('final_artifact'), 'final_artifact')
        self.refused(lambda r: None, 'kiểm báo cáo', text_edit=lambda t: t.rsplit('\n', 1)[0])

    def test_verify_emits_the_labelled_row_and_requires_it(self):
        r, text = self.aggregate()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(pt, 'generate_aggregate', return_value=(r, text + '\n')):
            pt.write_named(r, text + '\n', tmp, pt.AGG_FILES)
            res = pt.verify_aggregate({}, tmp, final=SYN)
            self.assertEqual('pass', res['result'], res)
            self.assertEqual(pr.RERUN_LABEL, res['rerun']['label'])
            self.assertEqual([], pr.check_rerun_row(res['rerun'], SYN))
        plain, ptext = self.aggregate(False)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(pt, 'generate_aggregate', return_value=(plain, ptext)):
            pt.write_named(plain, ptext, tmp, pt.AGG_FILES)
            res = pt.verify_aggregate({}, tmp, final=SYN)
            self.assertEqual('refused', res['result'])
            self.assertTrue(any('kiểm báo cáo' in p for p in res['problems']), res['problems'])
            self.assertEqual('pass', pt.verify_aggregate({}, tmp)['result'])
            self.assertNotIn('rerun', pt.verify_aggregate({}, tmp))



if __name__ == '__main__':
    unittest.main()
