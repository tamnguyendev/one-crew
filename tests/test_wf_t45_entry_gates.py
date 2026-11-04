"""T45b / T45c entry gates of PL-A and PL-B (kit task WKPL): wfkit.pilot_entry.pl_a_entry / pl_b_entry on FIXTURE receipts.

Receipts are built as in tests/test_wf_finalgate.py (sha-pinned JSON refs, simulated=True, provenance fixture); the interim report is
the T35b fixture of tests/test_wf_pilot_report.py plus a per-AC status block. Provider cells go through the shared evaluators
(wfkit.provider_evidence.evaluate, wfkit.finalgate.provider_capability). Passing proves the entry RULES only ("Biên nhận giả lập ở
selftest: chỉ chứng minh luật cổng"); no pilot ran and nothing here is pilot evidence or owner acceptance.
Each negative removes exactly one condition from an otherwise passing bundle and asserts the refusal names that condition.
"""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from wfkit.finalgate import CELLS
from wfkit.pilot_entry import PL_A_GATES, PL_B_GATES, pl_a_entry, pl_b_entry
import tests.test_wf_pilot_report as pilot_fixture

AC_STATUS = {'AC1': 'đạt', 'AC2': 'đạt', 'AC3': 'chỉ phần code và tài liệu', 'AC4': 'chưa đạt',
             'AC5': {'status': 'chỉ phần giữa kỳ 3/3', 'tier3': 'chưa kết luận giảm'}}


class EntryFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.count = 0
        self.b1 = {'commit': 'a' * 40, 'wheel_sha256': hashlib.sha256(b'build B1').hexdigest()}
        self.b2 = {'commit': 'b' * 40, 'wheel_sha256': hashlib.sha256(b'build B2').hexdigest()}
        self.state = self.root / 'pilot-state'; self.state.mkdir()
        self.monitored = self.root / 'monitored'; self.copy = self.root / 'monitored-copy'; self.free = self.root / 'free'
        for project in (self.monitored, self.copy, self.free):
            (project / '.claude').mkdir(parents=True)
            (project / '.claude' / 'settings.json').write_text('{"hooks": {}}', encoding='utf-8')

    def ref(self, value):
        self.count += 1
        path = self.root / f'r{self.count}.json'
        raw = json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
        path.write_bytes(raw)
        return {'path': path.name, 'sha256': hashlib.sha256(raw).hexdigest()}

    def receipt(self, artifact, **kw):
        value = dict(artifact)
        value.update({'result': 'pass', 'at': '2026-10-24T12:00:00Z', 'simulated': True,
                      'provenance': {'kind': 'fixture', 'source': 'T45 selftest'}})
        value.update(kw)
        return self.ref(value)

    def jobs(self, kind='doc'):
        return [{'id': 'J1', 'project': str(self.copy), 'state_root': str(self.state), 'kind': kind},
                {'id': 'J2', 'project': str(self.free), 'state_root': str(self.state), 'kind': 'code'}]

    def base(self, gates, artifact):
        return {'schema': 1, 'mode': 'fixture', 'artifact': dict(artifact), 'pilot_state_root': str(self.state),
                'monitored_projects': [str(self.monitored)],
                'receipts': {g: self.receipt(artifact, testcase=g) for g in gates}, 'jobs': self.jobs()}

    def assert_refused(self, result, code, needle):
        self.assertEqual(result['decision'], 'refused', result)
        details = [r['detail'] for r in result['reasons'] if r['code'] == code]
        self.assertTrue(details and any(needle in d for d in details), result['reasons'])
        self.assertEqual({r['code'] for r in result['reasons']}, {code}, 'only the removed condition may fail')
        return result


class PlAEntryTests(EntryFixture):
    def bundle(self, artifact=None):
        return self.base(PL_A_GATES, artifact or self.b1)

    def gate(self, bundle):
        return pl_a_entry(bundle, self.root, allow_simulated=True)

    def test_e2_all_conditions_met_passes_without_t35b(self):
        bundle = self.bundle()
        self.assertNotIn('T35b', bundle['receipts'])                      # PL-A never asks its own result
        result = self.gate(bundle)
        self.assertEqual(result['decision'], 'pass', result)
        self.assertEqual(result['wheel_sha256'], self.b1['wheel_sha256'])
        self.assertFalse(result['pilot_evidence'] or result['owner_acceptance'])
        self.assertIn('no pilot claim', result['proves'])

    def test_e2_missing_delivery_gate_receipt_is_refused(self):
        for name in PL_A_GATES:
            with self.subTest(gate=name):
                bundle = self.bundle()
                del bundle['receipts'][name]
                self.assert_refused(self.gate(bundle), 'delivery-gates', f'{name}: receipt missing')

    def test_e2_failed_delivery_gate_is_refused(self):
        bundle = self.bundle()
        bundle['receipts']['T54c'] = self.receipt(self.b1, testcase='T54c', result='fail')
        self.assert_refused(self.gate(bundle), 'delivery-gates', 'T54c: not pass')

    def test_e9_wrong_build_hash_is_refused_until_the_gates_rerun_on_it(self):
        bundle = self.bundle()
        bundle['artifact'] = dict(self.b2)                                 # gates passed on B1 only
        self.assert_refused(self.gate(bundle), 'delivery-gates', 'build hash differs')
        bundle['receipts'] = {g: self.receipt(self.b2, testcase=g) for g in PL_A_GATES}
        self.assertEqual(self.gate(bundle)['decision'], 'pass')

    def test_e10_monitored_project_is_refused_copy_and_unmonitored_accepted(self):
        bundle = self.bundle()
        bundle['jobs'][0]['project'] = str(self.monitored)
        self.assert_refused(self.gate(bundle), 'project', 'under the 2.1 monitor')

    def test_e10_job_must_use_the_pilot_state_root(self):
        bundle = self.bundle()
        bundle['jobs'][1]['state_root'] = str(self.root / 'other-state')
        self.assert_refused(self.gate(bundle), 'project', 'pilot state root')

    def test_e10_changing_monitored_config_needs_an_answered_u2(self):
        bundle = self.bundle()
        bundle['jobs'][0].update({'changes_monitored_config': True, 'anchor_task': 'task-anchor'})
        self.assert_refused(self.gate(bundle), 'project', 'without an answered U2')
        bundle['jobs'][0]['u2'] = self.receipt(self.b1, kind='U2', actor='codex', state='answered', task='task-anchor')
        self.assert_refused(self.gate(bundle), 'project', 'U2 not answered by the owner')
        bundle['jobs'][0]['u2'] = self.receipt(self.b1, kind='U2', actor='owner', state='answered', task='task-anchor')
        self.assertEqual(self.gate(bundle)['decision'], 'pass')

    def test_fixture_receipts_need_allow_simulated(self):
        result = pl_a_entry(self.bundle(), self.root)
        self.assertEqual(result['decision'], 'refused')
        self.assertEqual(result['reasons'][0]['code'], 'INPUT')


class PlBEntryTests(EntryFixture):
    """Fixture = case K (T55 C1): claude and codex cells pass on the pilot build, the two kiro cells are blocked (no account)."""

    def cell(self, artifact, key, result, vendor=None):
        provider, role = key.split(':')
        info = {'item': key, 'provider': provider, 'role': role, 'model': 'model-' + provider, 'kind': 'behavior',
                'vendor': vendor or ('OpenAI' if provider == 'codex' else 'Anthropic'),
                'cli_identity': {'provider': provider, 'path': f'{provider}.exe', 'argv': [f'{provider}.exe'], 'sha256': '1' * 64,
                                 'files': {f'{provider}.exe': '1' * 64}, 'version': 'fixture-1'}}
        ref = self.receipt(artifact, **info, result=result, reason='thiếu tài khoản' if result == 'blocked' else '')
        row = {k: info[k] for k in ('provider', 'role', 'model', 'vendor')} | {
            'id': key, 'cli_sha256': '1' * 64, 'cli_files': dict(info['cli_identity']['files']),
            'status': 'usable' if result == 'pass' else 'unverified'}
        return row, {'id': key, 'original': ref, 'supplements': []}

    def providers(self, bundle, artifact, results=None, vendors=None):
        results = results or {k: ('blocked' if k.startswith('kiro:') else 'pass') for k in CELLS}
        rows, items = [], []
        for key in sorted(CELLS):
            row, item = self.cell(artifact, key, results[key], (vendors or {}).get(key))
            rows.append(row); items.append(item)
        bundle.update({'providers': rows, 'provider_items': items})

    def interim(self, bundle, ac_status=AC_STATUS):
        report = pilot_fixture.build('interim')
        text = pilot_fixture.render(report)
        report['ac_status'] = copy.deepcopy(ac_status)
        md = self.root / f'interim{self.count}.md'
        md.write_text(text, encoding='utf-8')
        bundle['interim_report'] = {'json': self.ref(report), 'md': {'path': md.name, 'sha256': hashlib.sha256(md.read_bytes()).hexdigest()}}

    def bundle(self, artifact=None):
        artifact = artifact or self.b1
        bundle = self.base(PL_B_GATES + ('T35b', 'T14b'), artifact)
        bundle['jobs'] = self.jobs(kind='data')
        bundle['jobs'][0]['pins'] = ['codex:reviewer']
        bundle['author_vendor'] = 'Anthropic'
        self.providers(bundle, artifact)
        self.interim(bundle)
        return bundle

    def gate(self, bundle):
        return pl_b_entry(bundle, self.root, allow_simulated=True)

    def test_e16_case_k_codex_reviewer_usable_unpinned_kiro_unverified_passes(self):
        bundle = self.bundle()
        self.assertEqual({r['id']: r['status'] for r in bundle['providers'] if r['provider'] == 'kiro'},
                         {'kiro:reviewer': 'unverified', 'kiro:advisor': 'unverified'})
        result = self.gate(bundle)
        self.assertEqual(result['decision'], 'pass', result)
        self.assertTrue(all(result['conditions'].values()), result)
        self.assertFalse(any('kiro' in r['detail'] for r in result['reasons']))
        self.assertNotIn('T35c', bundle['receipts']); self.assertNotIn('T14c', bundle['receipts'])   # PL-B's own results not asked
        self.assertFalse(result['pilot_evidence'] or result['owner_acceptance'])

    def test_e14_missing_delivery_gate_receipt_is_refused(self):
        bundle = self.bundle()
        del bundle['receipts']['T54k']
        self.assert_refused(self.gate(bundle), 'delivery-gates', 'T54k: receipt missing')

    def test_e14_wrong_build_hash_is_refused(self):
        bundle = self.bundle()
        bundle['artifact'] = dict(self.b2)
        result = self.gate(bundle)
        self.assertEqual(result['decision'], 'refused')
        self.assertTrue(any('build hash differs' in r['detail'] for r in result['reasons'] if r['code'] == 'delivery-gates'), result)
        rerun = self.bundle(self.b2)
        self.assertEqual(self.gate(rerun)['decision'], 'pass')

    def test_e14_monitored_project_is_refused(self):
        bundle = self.bundle()
        bundle['jobs'][1]['project'] = str(self.monitored)
        self.assert_refused(self.gate(bundle), 'project', 'under the 2.1 monitor')

    def test_e3_data_job_without_t14b_is_refused_naming_w39(self):
        bundle = self.bundle()
        del bundle['receipts']['T14b']
        self.assert_refused(self.gate(bundle), 'T14b', 'needs T14b (W39)')
        bundle['receipts']['T14b'] = self.receipt(self.b1, testcase='T14b', result='fail')
        self.assert_refused(self.gate(bundle), 'T14b', 'T14b: not pass')

    def test_e3_code_and_doc_jobs_are_not_held_by_t14b(self):
        bundle = self.bundle()
        del bundle['receipts']['T14b']
        bundle['jobs'][0]['kind'] = 'doc'
        self.assertEqual(self.gate(bundle)['decision'], 'pass')

    def test_e4_interim_report_missing_or_failed_is_refused(self):
        bundle = self.bundle()
        del bundle['receipts']['T35b']
        self.assert_refused(self.gate(bundle), 'interim-report', 'T35b: receipt missing')
        bundle = self.bundle()
        del bundle['interim_report']
        self.assert_refused(self.gate(bundle), 'interim-report', 'interim report (T35b) missing')

    def test_e4_e6_interim_report_status_per_ac_is_read(self):
        cases = {'AC3 đạt (narrow phase)': (dict(AC_STATUS, AC3='đạt'), 'AC3'),
                 'AC5 concludes a reduction': (dict(AC_STATUS, AC5={'status': 'chỉ phần giữa kỳ 3/3', 'tier3': 'giảm 20%'}), 'AC5'),
                 'AC4 missing': ({k: v for k, v in AC_STATUS.items() if k != 'AC4'}, 'AC1-AC5'),
                 'status outside the catalog': (dict(AC_STATUS, AC2='ok'), 'AC2')}
        for label, (status, needle) in cases.items():
            with self.subTest(label):
                bundle = self.bundle()
                self.interim(bundle, status)
                self.assert_refused(self.gate(bundle), 'interim-report', needle)

    def test_e4_interim_report_refused_by_the_t35b_checker_is_refused(self):
        bundle = self.bundle()
        report = pilot_fixture.build('interim')
        report['ac_status'] = copy.deepcopy(AC_STATUS)
        text = pilot_fixture.render(report).replace('giữa kỳ', 'baseline', 1)
        md = self.root / 'bad.md'; md.write_text(text, encoding='utf-8')
        bundle['interim_report'] = {'json': self.ref(report), 'md': {'path': md.name, 'sha256': hashlib.sha256(md.read_bytes()).hexdigest()}}
        self.assert_refused(self.gate(bundle), 'interim-report', 'interim report refused')

    def test_e22_no_other_vendor_usable_reviewer_is_refused(self):
        variants = {
            'only claude cells pass': ({k: 'pass' if k.startswith('claude:') else 'blocked' for k in CELLS}, {}),
            'kiro reviewer passes with the author vendor': ({k: 'blocked' if k.startswith('codex:') else 'pass' for k in CELLS}, {}),
            'codex passes only as advisor': ({k: 'blocked' if k in ('codex:reviewer', 'kiro:reviewer', 'kiro:advisor') else 'pass' for k in CELLS}, {}),
        }
        for label, (results, vendors) in variants.items():
            with self.subTest(label):
                bundle = self.bundle()
                bundle['jobs'][0]['pins'] = []
                self.providers(bundle, self.b1, results, vendors)
                self.assert_refused(self.gate(bundle), 'provider-NL', 'no usable reviewer of another vendor')

    def test_e22_pinned_cell_not_usable_is_refused(self):
        bundle = self.bundle()
        bundle['jobs'][1]['pins'] = ['kiro:reviewer']                     # T55 C8: a pilot job pins an unverified cell
        self.assert_refused(self.gate(bundle), 'provider-NL', 'pinned cells not usable: kiro:reviewer')

    def test_reported_cell_status_must_match_evidence(self):
        bundle = self.bundle()
        next(r for r in bundle['providers'] if r['id'] == 'kiro:reviewer')['status'] = 'usable'   # x6-like forged usable cell
        self.assert_refused(self.gate(bundle), 'provider-NL', 'reported status differs from evidence')


if __name__ == '__main__':
    unittest.main()
