"""T40b provider-matrix rules (program kit task WKP), judged by the shared evaluator.

No real provider, CLI or account was used. Every receipt below is a constructed
fixture written to a temp dir (SHA-pinned JSON, simulated=True). This proves the
kit rule (wfkit.provider_evidence.evaluate + the helpers in this module), not
provider capability: running the real CLIs is W45 and stays external.

Kit-level helpers defined here (product code unchanged; the evaluator has no
notion of them): fake_cli_manifest / cell_is_real (x3, E24, E20), p1_label and
provider_complete (x1, x2), notes_usable_ok (x6, T40c note vs matrix). The fake
CLI script is read (by ast, nothing imported or executed) from the FAKE literal
in tests/test_wf_rp_providers.py, the one the provider tests install.

Reading of x6/x7 (05-TESTCASES T40 fixtures): x6 = release notes call
kiro:reviewer "usable" while the matrix says unverified; x7 = codex:reviewer
receipt is a pass on a build other than the delivered one, so it is not direct
evidence and, with no valid HL2 comparison, cannot be usable for the delivered build.
"""
import ast
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from wfkit.finalgate import CELLS, Evidence
from wfkit.provider_evidence import evaluate

VENDOR = {'claude': 'Anthropic', 'codex': 'OpenAI', 'kiro': 'Amazon'}
A = {'commit': 'a' * 40, 'wheel_sha256': 'a' * 64}   # delivered build
B = {'commit': 'b' * 40, 'wheel_sha256': 'b' * 64}   # some other build


def fake_cli_source():
    tree = ast.parse((Path(__file__).parent / 'test_wf_rp_providers.py').read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == 'FAKE' for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError('FAKE script literal not found')


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def p1_label(states):
    """finalgate rule: 'full' only when all six cells are usable, else 'subset'."""
    return 'full' if {k for k, s in states.items() if s['status'] == 'usable'} == CELLS else 'subset'


def provider_complete(states, provider):
    return all(states[f'{provider}:{r}']['status'] == 'usable' for r in ('reviewer', 'advisor'))


def fake_cli_manifest(paths):
    return {hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}


def cell_is_real(receipt, manifest):
    cli = receipt.get('cli_identity') or {}
    if not (cli.get('path') and cli.get('version') and cli.get('sha256')):
        return False
    hashes = {cli['sha256'], *(cli.get('files') or {}).values()}
    return not (hashes & manifest)


def notes_usable_ok(notes_usable, states):
    return set(notes_usable) <= {k for k, s in states.items() if s['status'] == 'usable'}


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.n = 0
        script = self.root / 'fake_cli.py'
        script.write_text(fake_cli_source(), encoding='utf-8')
        self.manifest = fake_cli_manifest([script])
        self.fake_sha = next(iter(self.manifest))

    def ref(self, value):
        self.n += 1
        path = self.root / f'r{self.n}.json'
        raw = json.dumps(value, sort_keys=True).encode()
        path.write_bytes(raw)
        return {'path': path.name, 'sha256': hashlib.sha256(raw).hexdigest()}

    def build(self, spec=None, source=A, target=A, drop=()):
        """spec: cell -> dict(result, artifact, receipt (field overrides), cli_sha, status, reason)."""
        spec = spec or {}
        rows, items = [], []
        for key in sorted(CELLS):
            provider, role = key.split(':')
            s = spec.get(key, {})
            result = s.get('result', 'pass')
            cli_sha = s.get('cli_sha', sha('real-cli-' + provider))
            files = {f'{provider}.exe': cli_sha}
            rec = dict(s.get('artifact', source), result=result, at='2026-10-24T12:00:00Z', simulated=True,
                       provenance={'kind': 'fixture', 'source': 'T40b selftest'}, kind='behavior', item=key,
                       provider=provider, role=role, model='model-' + provider, vendor=VENDOR[provider],
                       cli_identity={'provider': provider, 'path': f'{provider}.exe', 'argv': [f'{provider}.exe'],
                                     'sha256': cli_sha, 'files': files, 'version': f'{provider} 1.0'})
            if result == 'blocked':
                rec['reason'] = s.get('reason', 'thiếu tài khoản')
            rec.update(s.get('receipt', {}))
            default = {'pass': 'usable', 'blocked': 'unverified', 'fail': 'failed'}[result]
            if result == 'pass' and source != target:
                default = 'recheck'
            rows.append({'id': key, 'provider': provider, 'role': role, 'model': 'model-' + provider,
                         'vendor': VENDOR[provider], 'cli_sha256': cli_sha, 'cli_files': copy.deepcopy(files),
                         'status': s.get('status', default)})
            items.append({'id': key, 'original': self.ref(rec), 'supplements': []})
        return [r for r in rows if r['id'] not in drop], items

    def run_eval(self, rows, items, source=A, target=A):
        return evaluate(rows, items, Evidence(self.root, fixture=True), source, target)

    def receipt(self, items, key):
        return Evidence(self.root, fixture=True).read(next(i for i in items if i['id'] == key)['original'])

    # E8
    def test_e8_six_rows_one_state_per_cell_and_nothing_else(self):
        rows, items = self.build()
        states = self.run_eval(rows, items)
        self.assertEqual(CELLS, set(states))
        self.assertEqual(6, len(states))
        self.assertTrue(all(s['status'] in {'usable', 'failed', 'unverified', 'recheck'} for s in states.values()))
        for row in rows:
            self.assertTrue(row['model'] and row['cli_sha256'])

    def test_e8_counter_example_five_or_extra_or_duplicate_rows_refused(self):
        rows, items = self.build()
        with self.assertRaises(ValueError):
            self.run_eval(rows[:5], items)
        with self.assertRaises(ValueError):
            self.run_eval(rows + [dict(rows[0], id='claude:planner', role='planner')], items)
        with self.assertRaises(ValueError):
            self.run_eval(rows[:5] + [dict(rows[0])], items)   # duplicate instead of the sixth cell

    # E9 / x5
    def test_e9_x5_missing_cli_account_or_quota_is_unverified_with_reason_never_usable(self):
        for reason in ('thiếu CLI', 'thiếu tài khoản', 'hết hạn mức'):
            with self.subTest(reason=reason):
                rows, items = self.build({'kiro:reviewer': {'result': 'blocked', 'reason': reason}})
                states = self.run_eval(rows, items)
                self.assertEqual('unverified', states['kiro:reviewer']['status'])
                self.assertEqual(reason, self.receipt(items, 'kiro:reviewer')['reason'])

    def test_e9_x5_blocked_cell_marked_usable_is_refused(self):
        rows, items = self.build({'kiro:reviewer': {'result': 'blocked', 'status': 'usable'}})
        with self.assertRaisesRegex(ValueError, 'reported status differs'):
            self.run_eval(rows, items)

    def test_e9_x5_blocked_without_reason_and_five_row_matrix_are_refused(self):
        rows, items = self.build({'kiro:advisor': {'result': 'blocked', 'receipt': {'reason': ''}}})
        with self.assertRaises(ValueError):
            self.run_eval(rows, items)
        rows, items = self.build(drop=('kiro:advisor',))
        self.assertEqual(5, len(rows))
        with self.assertRaisesRegex(ValueError, 'six-cell'):
            self.run_eval(rows, items)

    # x1 / E22
    def test_x1_e22_only_claude_receipts_cannot_be_full(self):
        spec = {k: {'result': 'blocked', 'reason': 'thiếu CLI'} for k in CELLS if not k.startswith('claude:')}
        rows, items = self.build(spec)
        states = self.run_eval(rows, items)
        usable = {k for k, s in states.items() if s['status'] == 'usable'}
        self.assertEqual({'claude:reviewer', 'claude:advisor'}, usable)
        self.assertLess(len(usable), 6)
        self.assertEqual('subset', p1_label(states))

    def test_x1_e22_counterexample_six_usable_is_the_only_full(self):
        rows, items = self.build()
        self.assertEqual('full', p1_label(self.run_eval(rows, items)))

    # x2 / E23
    def test_x2_e23_reviewer_without_advisor_is_not_complete_for_provider(self):
        rows, items = self.build({'codex:advisor': {'result': 'blocked', 'reason': 'hết hạn mức'}})
        states = self.run_eval(rows, items)
        self.assertEqual('usable', states['codex:reviewer']['status'])
        self.assertFalse(provider_complete(states, 'codex'))
        self.assertTrue(provider_complete(states, 'claude'))

    def test_x2_e23_advisor_without_reviewer_and_forged_complete_status(self):
        rows, items = self.build({'claude:reviewer': {'result': 'blocked', 'reason': 'thiếu CLI'}})
        states = self.run_eval(rows, items)
        self.assertTrue(states['claude:advisor']['status'] == 'usable' and not provider_complete(states, 'claude'))
        rows, items = self.build({'claude:reviewer': {'result': 'blocked', 'status': 'usable'}})
        with self.assertRaises(ValueError):
            self.run_eval(rows, items)

    # x3 / E24 / E20
    def test_x3_e24_e20_fake_cli_hash_is_not_a_real_cell(self):
        rows, items = self.build({'claude:reviewer': {'cli_sha': self.fake_sha}})
        states = self.run_eval(rows, items)     # shape is valid: the evaluator alone cannot tell
        self.assertEqual('usable', states['claude:reviewer']['status'])
        self.assertFalse(cell_is_real(self.receipt(items, 'claude:reviewer'), self.manifest))

    def test_x3_e24_e20_real_receipt_records_path_sha_version_provider_model_artifact(self):
        rows, items = self.build()
        for key in CELLS:
            rec = self.receipt(items, key)
            cli = rec['cli_identity']
            provider = key.split(':')[0]
            self.assertTrue(cell_is_real(rec, self.manifest), key)
            self.assertTrue(cli['path'] and len(cli['sha256']) == 64 and cli['version'])
            self.assertEqual((provider, 'model-' + provider), (rec['provider'], rec['model']))
            self.assertEqual(A['wheel_sha256'], rec['wheel_sha256'])
        stripped = self.receipt(items, 'codex:advisor')
        self.assertFalse(cell_is_real(dict(stripped, cli_identity=dict(stripped['cli_identity'], version='')), self.manifest))
        self.assertFalse(cell_is_real({k: v for k, v in stripped.items() if k != 'cli_identity'}, self.manifest))

    def test_x3_e24_fake_hash_inside_cli_files_also_detected(self):
        rows, items = self.build()
        rec = self.receipt(items, 'kiro:advisor')
        rec['cli_identity']['files']['fake_cli.py'] = self.fake_sha
        self.assertFalse(cell_is_real(rec, self.manifest))

    # x4 / E25
    def test_x4_e25_wrong_provider_model_role_or_vendor_not_accepted(self):
        for over in ({'provider': 'codex'}, {'model': 'other-model'}, {'role': 'advisor'}, {'vendor': 'Elsewhere'}):
            with self.subTest(over=over):
                rows, items = self.build({'claude:reviewer': {'receipt': over}})
                with self.assertRaisesRegex(ValueError, 'receipt provider/model mismatch'):
                    self.run_eval(rows, items)

    def test_x4_e25_wrong_cli_provider_or_cli_hash_not_accepted(self):
        bad = {'provider': 'claude', 'path': 'x.exe', 'argv': ['x.exe'], 'sha256': sha('real-cli-codex'),
               'files': {'x.exe': sha('real-cli-codex')}, 'version': '1'}
        rows, items = self.build({'codex:reviewer': {'receipt': {'cli_identity': bad}}})
        with self.assertRaises(ValueError):
            self.run_eval(rows, items)

    def test_x4_e25_wrong_artifact_receipt_not_accepted(self):
        rows, items = self.build({'claude:advisor': {'artifact': B}})
        with self.assertRaisesRegex(ValueError, 'original hash changed'):
            self.run_eval(rows, items)

    # case K, x6, x7, E28
    def case_k(self):
        return self.build({k: {'result': 'blocked', 'reason': 'thiếu tài khoản'} for k in CELLS if k.startswith('kiro:')})

    def test_k_e28_four_usable_two_kiro_unverified_matrix_is_consistent_not_full(self):
        rows, items = self.case_k()
        states = self.run_eval(rows, items)        # no exception: T40b passes
        self.assertEqual(6, len(states))
        self.assertEqual({k for k in CELLS if not k.startswith('kiro:')}, {k for k, s in states.items() if s['status'] == 'usable'})
        for k in ('kiro:reviewer', 'kiro:advisor'):
            self.assertEqual('unverified', states[k]['status'])
            self.assertEqual('thiếu tài khoản', self.receipt(items, k)['reason'])
        self.assertEqual(4, sum(s['status'] == 'usable' for s in states.values()))
        self.assertEqual('subset', p1_label(states))

    def test_x6_notes_calling_unverified_kiro_reviewer_usable_are_flagged(self):
        rows, items = self.case_k()
        states = self.run_eval(rows, items)
        honest = {'claude:reviewer', 'claude:advisor', 'codex:reviewer', 'codex:advisor'}
        self.assertTrue(notes_usable_ok(honest, states))
        self.assertFalse(notes_usable_ok(honest | {'kiro:reviewer'}, states))
        forged_rows, forged_items = self.build({'kiro:reviewer': {'result': 'blocked', 'status': 'usable'},
                                                'kiro:advisor': {'result': 'blocked'}})
        with self.assertRaises(ValueError):
            self.run_eval(forged_rows, forged_items)

    def test_x7_receipt_on_other_build_is_not_usable_for_delivered_build(self):
        # evidence passed on build B, delivered build is A, no comparison supplied.
        rows, items = self.build(source=B, target=A)
        states = self.run_eval(rows, items, source=B, target=A)
        self.assertEqual('recheck', states['codex:reviewer']['status'])
        self.assertFalse(notes_usable_ok({'codex:reviewer'}, states))
        next(r for r in rows if r['id'] == 'codex:reviewer')['status'] = 'usable'
        with self.assertRaisesRegex(ValueError, 'reported status differs'):
            self.run_eval(rows, items, source=B, target=A)

    # E36
    def test_e36_fewer_than_six_usable_does_not_fail_the_matrix_check(self):
        for usable in (0, 1, 2, 4):
            with self.subTest(usable=usable):
                keep = sorted(CELLS)[:usable]
                rows, items = self.build({k: {'result': 'blocked', 'reason': 'thiếu CLI'} for k in CELLS if k not in keep})
                states = self.run_eval(rows, items)      # must not raise
                self.assertEqual(usable, sum(s['status'] == 'usable' for s in states.values()))
                self.assertEqual(6, len(states))


if __name__ == '__main__':
    unittest.main()
