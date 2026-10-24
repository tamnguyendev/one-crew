"""T45d/e and T55: real validator over explicitly simulated, pinned fixtures."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

from wfkit.finalgate import BASE_ITEMS, CELLS, GATES, compare, decide, Evidence, evidence_status
from onecrew.dependency_core import affected_tasks


class FinalGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.count = 0
        self.a = self.wheel('a', 'a' * 40, 'old')
        self.b = self.wheel('b', 'b' * 40, 'new')
        self.bundle = self.make_bundle()

    def wheel(self, name, commit, reviewer):
        path = self.root / f'{name}.whl'
        with ZipFile(path, 'w') as archive:
            archive.writestr('onecrew/reviewer.py', reviewer)
            archive.writestr('onecrew/advisor.py', 'same')
            for item in BASE_ITEMS:
                archive.writestr(f'onecrew/{item}.py', 'same')
        return {'commit': commit, 'wheel_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'wheel': path.name}

    def ref(self, value):
        self.count += 1
        path = self.root / f'r{self.count}.json'
        raw = json.dumps(value, sort_keys=True).encode()
        path.write_bytes(raw)
        return {'path': path.name, 'sha256': hashlib.sha256(raw).hexdigest()}

    def receipt(self, artifact, **kw):
        value = {k: artifact[k] for k in ('commit', 'wheel_sha256')}
        value.update({'result': 'pass', 'at': '2026-10-24T12:00:00Z', 'simulated': True,
                      'provenance': {'kind': 'fixture', 'source': 'T55 selftest'}})
        value.update(kw)
        return self.ref(value)

    def edit(self, ref, **changes):
        value = json.loads((self.root / ref['path']).read_text())
        value.update(changes)
        new = self.ref(value)
        ref.clear()
        ref.update(new)

    def make_bundle(self):
        items = []
        for key in sorted(BASE_ITEMS):
            items.append({'id': key, 'owned': [f'onecrew/{key}.py'],
                          'depends_on': ['codex:reviewer'] if key == 'AC1' else [],
                          'original': self.receipt(self.a, kind='behavior', item=key),
                          'supplements': [self.receipt(self.b, kind='supplement', item=key)] if key == 'AC1' else []})
        rows = []
        for key in sorted(CELLS):
            provider, role = key.split(':')
            blocked = provider == 'kiro'
            info = {'item': key, 'provider': provider, 'role': role, 'model': 'model-' + provider,
                    'vendor': 'OpenAI' if provider == 'codex' else 'Anthropic', 'kind': 'behavior'}
            info['cli_identity'] = {'provider': provider, 'path': f'{provider}.exe', 'argv': [f'{provider}.exe'],
                                    'sha256': '1' * 64, 'files': {f'{provider}.exe': '1' * 64}, 'version': 'fixture-1'}
            original = self.receipt(self.a, **info, result='blocked' if blocked else 'pass', reason='account unavailable' if blocked else '')
            extra = [self.receipt(self.b, **info, result='blocked' if blocked else 'pass', reason='account unavailable' if blocked else '')] if role == 'reviewer' else []
            items.append({'id': key, 'owned': [f'onecrew/{role}.py'], 'depends_on': [], 'original': original, 'supplements': extra})
            rows.append({k: info[k] for k in ('provider', 'role', 'model', 'vendor')} | {'id': key, 'cli_sha256': '1' * 64,
                        'cli_files': copy.deepcopy(info['cli_identity']['files']), 'status': 'unverified' if blocked else 'usable'})
        gates = {}
        for name in GATES:
            gates[name] = {'receipt': self.receipt(self.b, gate=name, manifest_sha256='c' * 64),
                           'doccheck': self.receipt(self.b, testcase='T38a', problems=0, kit_guard={'ok': True, 'manifest_sha256': 'c' * 64},
                                                  manifest_sha256='c' * 64, block_sha256='d' * 64,
                                                  command=['python', '-m', 'wfkit.kitguard', 'doccheck']),
                           'evidence': [{'item': 'AC1', 'receipt': items[0]['supplements'][0], 'validity': 'direct'}]}
        phases = {}
        for name, entry, completion, start, finish in (
                ('PL-A', 'T45b', ['T35b'], '10:00:00', '11:00:00'),
                ('PL-B', 'T45c', ['T35c', 'T14c'], '13:00:00', '14:00:00')):
            phases[name] = {'artifact': self.a, 'started_at': f'2026-10-23T{start}Z', 'completed_at': f'2026-10-23T{finish}Z',
                'entry': self.receipt(self.a, testcase=entry, at='2026-10-23T09:00:00Z'),
                'releases': {g: self.receipt(self.a, gate=g, at='2026-10-23T08:00:00Z') for g in GATES},
                'completion': {t: self.receipt(self.a, kind='pilot', testcase=t, at='2026-10-23T12:00:00Z' if name == 'PL-A' else '2026-10-23T15:00:00Z') for t in completion},
                'pinned_cells': ['codex:reviewer'], 'author_vendor': 'Anthropic'}
        eligible = sorted(k for k in CELLS if not k.startswith('kiro:'))
        return {'schema': 1, 'mode': 'fixture', 'artifacts': {'pilot': self.a, 'final': self.b},
                'comparison': {'id': 'comparison-A-B', 'source': self.a, 'target': self.b,
                               'mapping': self.receipt(self.a, kind='impact-map', tasks=[{k: copy.deepcopy(i[k]) for k in ('id', 'owned', 'depends_on')} for i in items]),
                               'changed_files': ['onecrew/reviewer.py'], 'affected': ['AC1'] + sorted(k for k in CELLS if k.endswith(':reviewer')), 'items': items},
                'gates': gates, 'phases': phases, 'author_vendor': 'Anthropic', 'providers': rows,
                'monitored_files': [{'path': '.claude/hooks.json', 'before_sha256': 'e' * 64, 'after_sha256': 'e' * 64}],
                'publications': {p: {'cells': eligible, 'missing': sorted(CELLS - set(eligible)), 'label': 'partial'} for p in ('T40c', 'T54i', 'T40d')}}

    def run_gate(self):
        return decide(self.bundle, self.root, allow_simulated=True)

    def assert_refused(self, *codes):
        result = self.run_gate()
        self.assertEqual('refused', result['decision'], result)
        self.assertTrue(set(codes) <= {r['code'] for r in result['reasons']}, result)
        return result

    def item(self, key):
        return next(i for i in self.bundle['comparison']['items'] if i['id'] == key)

    def test_n0_partial_optional_unverified_passes_retains_hash(self):
        before = copy.deepcopy(self.bundle)
        result = self.run_gate()
        self.assertEqual('pass', result['decision'], result)
        self.assertTrue(all(result['conditions'].values()))
        self.assertEqual(self.a['wheel_sha256'], result['provider_states']['codex:advisor']['evidence']['wheel_sha256'])
        self.assertEqual('inherited', result['provider_states']['codex:advisor']['validity'])
        self.assertEqual(self.b['wheel_sha256'], result['wheel_sha256'])
        self.assertTrue(result['simulated_receipts_used'])
        self.assertIn('no real pilot claim', result['proves'])
        self.assertEqual(before, self.bundle)

    def test_fixture_cannot_claim_real_gate(self):
        self.assertEqual('refused', decide(self.bundle, self.root)['decision'])
        self.bundle['mode'] = 'real'
        self.assert_refused('KQ1', 'KQ2', 'KQ3')

    def test_empty_or_malformed_input_fails_closed(self):
        for value in ({}, [], None, {'schema': 1, 'mode': 'real'}):
            with self.subTest(value=value):
                self.assertEqual('refused', decide(value, self.root)['decision'])

    def test_kq1_missing_gate(self):
        del self.bundle['gates']['CG-R07']
        self.assert_refused('KQ1')

    def test_kq1_wrong_artifact(self):
        self.edit(self.bundle['gates']['CG-R06']['receipt'], **{k: self.a[k] for k in ('commit', 'wheel_sha256')})
        self.assert_refused('KQ1')

    def test_kq1_not_pass(self):
        self.edit(self.bundle['gates']['KN-R03-R04']['receipt'], result='fail')
        self.assert_refused('KQ1')

    def test_kq1_missing_doccheck_command(self):
        self.edit(self.bundle['gates']['CG-R03']['doccheck'], command=[])
        self.assert_refused('KQ1')

    def test_existing_gate_and_doccheck_receipt_fields(self):
        ref = self.bundle['gates']['CG-R00']['receipt']
        record = json.loads((self.root / ref['path']).read_text())
        del record['gate']; del record['result']
        record.update(release='R00', decision='pass')
        self.bundle['gates']['CG-R00']['receipt'] = self.ref(record)
        self.edit(self.bundle['gates']['CG-R00']['doccheck'], command='python -I -X utf8 - < section-7 block deadbeef (cwd=docs)')
        self.assertEqual('pass', self.run_gate()['decision'])

    def test_kq1_inherited_evidence_requires_matching_comparison(self):
        use = {'item': 'context', 'receipt': self.item('context')['original'], 'validity': 'inherited', 'comparison_id': 'wrong'}
        self.bundle['gates']['CG-R00']['evidence'] = [use]
        self.assert_refused('KQ1')
        use['comparison_id'] = self.bundle['comparison']['id']
        self.assertEqual('pass', self.run_gate()['decision'])

    def test_kq2_missing_comparison(self):
        self.bundle['comparison'] = {}
        self.assert_refused('KQ2')

    def test_kq2_wrong_pair(self):
        self.bundle['comparison']['source'] = self.b
        self.assert_refused('KQ2')

    def test_kq2_omitted_dependency(self):
        self.bundle['comparison']['affected'].remove('AC1')
        self.assert_refused('KQ2')

    def test_kq2_omitted_edge_cannot_rewrite_pinned_map(self):
        self.item('AC1')['depends_on'] = []
        self.bundle['comparison']['affected'].remove('AC1')
        self.assert_refused('KQ2')

    def test_kq2_invalid_wheel_is_refusal_not_traceback(self):
        path = self.root / self.b['wheel']
        path.write_bytes(b'bad zip')
        self.b['wheel_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assert_refused('KQ2')

    def test_kq2_missing_cell_is_refusal_not_traceback(self):
        self.bundle['comparison']['items'].remove(self.item('codex:reviewer'))
        self.assert_refused('KQ2', 'KQ6')

    def test_full_matrix_direct_and_inherited_both_pass(self):
        for key in CELLS:
            row = self.item(key)
            self.edit(row['original'], result='pass', reason='')
            for ref in row['supplements']:
                self.edit(ref, result='pass', reason='')
        for row in self.bundle['providers']:
            row['status'] = 'usable'
        for publication in self.bundle['publications'].values():
            publication.update(cells=sorted(CELLS), missing=[], label='full')
        self.assertEqual('pass', self.run_gate()['decision'])
        for key in CELLS:
            row = self.item(key)
            if key.endswith(':advisor'):
                rec = json.loads((self.root / row['original']['path']).read_text())
                rec.update({k: self.b[k] for k in ('commit', 'wheel_sha256')})
                row['supplements'] = [self.ref(rec)]
        result = self.run_gate()
        self.assertEqual('pass', result['decision'], result)
        self.assertEqual({'direct'}, {x['validity'] for x in result['provider_states'].values()})

    def test_common_hl_c4_c5_c6_do_not_inherit_without_valid_proof(self):
        original = json.loads((self.root / self.item('codex:advisor')['original']['path']).read_text())
        proof = compare(self.bundle, Evidence(self.root, True))
        self.assertEqual('usable', evidence_status(original, [], self.b, proof, 'codex:advisor')['status'])
        for bad in (None, dict(proof, source=self.b), dict(proof, affected=['codex:advisor'])):
            self.assertEqual('recheck', evidence_status(original, [], self.b, bad, 'codex:advisor')['status'])

    def test_kq2_missing_supplement(self):
        self.item('AC1')['supplements'] = []
        self.assert_refused('KQ2')

    def test_kq2_supplement_wrong_hash(self):
        self.edit(self.item('AC1')['supplements'][0], **{k: self.a[k] for k in ('commit', 'wheel_sha256')})
        self.assert_refused('KQ2')

    def test_kq2_original_hash_rewritten(self):
        self.edit(self.item('AC2')['original'], **{k: self.b[k] for k in ('commit', 'wheel_sha256')})
        self.assert_refused('KQ2')

    def test_kq2_actual_wheel_diff_not_declared_text(self):
        self.bundle['comparison']['changed_files'] = []
        self.assert_refused('KQ2')

    def test_kq2_unknown_file_affects_every_item(self):
        path = self.root / self.b['wheel']
        with ZipFile(path, 'a') as wheel:
            wheel.writestr('onecrew/unmapped.py', 'new')
        self.b['wheel_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.bundle['comparison']['changed_files'].append('onecrew/unmapped.py')
        self.bundle['comparison']['affected'] = sorted(BASE_ITEMS | CELLS)
        proof = compare(self.bundle, Evidence(self.root, True))
        self.assertEqual(BASE_ITEMS | CELLS, set(proof['affected']))
        self.assert_refused('KQ2')

    def test_kq2_wheel_hash_and_receipt_hash_are_checked(self):
        (self.root / self.a['wheel']).write_bytes(b'not a wheel')
        self.assert_refused('KQ2')
        ref = self.bundle['gates']['CG-R00']['receipt']
        (self.root / ref['path']).write_text('{}')
        self.assert_refused('KQ1')

    def test_kq3_not_started(self):
        self.bundle['phases']['PL-B']['started_at'] = None
        self.assert_refused('KQ3')

    def test_kq3_missing_completion(self):
        del self.bundle['phases']['PL-B']['completion']['T35c']
        self.assert_refused('KQ3')

    def test_kq3_not_completed(self):
        self.bundle['phases']['PL-B']['completed_at'] = None
        self.assert_refused('KQ3')

    def test_kq3_evaluation_does_not_replace_real_pilot(self):
        self.edit(self.bundle['phases']['PL-B']['completion']['T35c'], kind='evaluation')
        self.assert_refused('KQ3')

    def test_kq4_entry_refused(self):
        self.edit(self.bundle['phases']['PL-B']['entry'], result='refused')
        self.assert_refused('KQ4')

    def test_kq4_late_entry_for_each_phase(self):
        for name in ('PL-A', 'PL-B'):
            with self.subTest(name=name):
                ref = self.bundle['phases'][name]['entry']
                old = copy.deepcopy(ref)
                self.edit(ref, at='2026-10-24T23:00:00Z')
                self.assert_refused('KQ4')
                ref.clear(); ref.update(old)

    def test_kq4_release_wrong_hash_and_late_release(self):
        ref = self.bundle['phases']['PL-B']['releases']['CG-R05']
        self.edit(ref, **{k: self.b[k] for k in ('commit', 'wheel_sha256')})
        self.assert_refused('KQ4')
        self.edit(ref, **{k: self.a[k] for k in ('commit', 'wheel_sha256')}, at='2026-10-24T23:00:00Z')
        self.assert_refused('KQ4')

    def test_kq4_unavailable_pin(self):
        self.bundle['phases']['PL-B']['pinned_cells'].append('kiro:reviewer')
        self.assert_refused('KQ4')

    def test_kq5_hook_changed_without_u2(self):
        self.bundle['monitored_files'][0]['after_sha256'] = 'f' * 64
        self.assert_refused('KQ5')

    def test_kq5_valid_prior_u2_and_late_u2(self):
        row = self.bundle['monitored_files'][0]
        row.update(after_sha256='f' * 64, changed_at='2026-10-24T13:00:00Z')
        row['authorization'] = self.receipt(self.a, kind='U2', actor='owner', path=row['path'], before_sha256=row['before_sha256'], after_sha256=row['after_sha256'])
        self.assertEqual('pass', self.run_gate()['decision'])
        self.edit(row['authorization'], at='2026-10-24T14:00:00Z')
        self.assert_refused('KQ5')

    def test_kq6_independence_uses_model_vendor_not_cli_brand(self):
        self.bundle['author_vendor'] = 'OpenAI'
        # Only codex can remain usable as reviewer; a different CLI is not enough.
        self.edit(self.item('claude:reviewer')['supplements'][0], result='blocked', reason='quota')
        next(r for r in self.bundle['providers'] if r['id'] == 'claude:reviewer')['status'] = 'recheck'
        self.assert_refused('KQ6')

    def test_kq6_missing_provider_matrix(self):
        self.bundle['providers'] = []
        self.assert_refused('KQ6')

    def test_kq6_missing_unreadable_or_mismatched_cli_hash_cannot_pass(self):
        ref = self.item('codex:reviewer')['supplements'][0]
        original = copy.deepcopy(ref)
        cli = json.loads((self.root / ref['path']).read_text())['cli_identity']
        for bad in ({}, dict(cli, sha256=None, identity_errors=['unreadable executable']), dict(cli, sha256='2' * 64),
                    dict(cli, files=dict(cli['files'], **{'fake_cli.py': '2' * 64}))):
            with self.subTest(cli=bad):
                self.edit(ref, cli_identity=bad)
                self.assert_refused('KQ6')
                ref.clear(); ref.update(original)

    def test_kq6_blocked_does_not_create_pass_or_erase_inheritance(self):
        row = self.item('codex:advisor')
        rec = json.loads((self.root / row['original']['path']).read_text())
        rec.update({k: self.b[k] for k in ('commit', 'wheel_sha256')})
        rec.update(result='blocked', reason='quota')
        row['supplements'] = [self.ref(rec)]
        self.assertEqual('pass', self.run_gate()['decision'])
        self.assertEqual('inherited', self.run_gate()['provider_states']['codex:advisor']['validity'])

    def test_kq7_all_publication_sets_must_match(self):
        for name in ('T40c', 'T54i', 'T40d'):
            with self.subTest(name=name):
                self.bundle['publications'][name]['cells'].append('kiro:reviewer')
                self.assert_refused('KQ7')
                self.bundle['publications'][name]['cells'].remove('kiro:reviewer')

    def test_kq7_partial_cannot_claim_full(self):
        self.bundle['publications']['T40d']['label'] = 'full'
        self.assert_refused('KQ7')

    def test_all_failed_conditions_are_reported_once(self):
        self.bundle['gates'] = {}
        self.bundle['monitored_files'] = []
        self.bundle['providers'] = []
        result = self.assert_refused('KQ1', 'KQ5', 'KQ6')
        self.assertEqual(len(result['reasons']), len({r['code'] for r in result['reasons']}))

    def test_closure_preserves_v1_owned_overlap_and_dependencies(self):
        plan = {'tasks': [{'id': 'B', 'owned': ['x'], 'depends_on': []},
                          {'id': 'C', 'owned': ['x'], 'depends_on': []},
                          {'id': 'D', 'owned': ['y'], 'depends_on': ['C']},
                          {'id': 'E', 'owned': ['z'], 'depends_on': []}]}
        self.assertEqual({'B', 'C', 'D'}, affected_tasks(plan, ['B']))

    def test_cli_outputs_structured_decision_and_never_accepts(self):
        path = self.root / 'bundle.json'
        path.write_text(json.dumps(self.bundle))
        run = subprocess.run([sys.executable, '-m', 'wfkit.finalgate', str(path), '--allow-simulated'], capture_output=True, text=True)
        self.assertEqual(0, run.returncode, run.stderr + run.stdout)
        result = json.loads(run.stdout)
        self.assertEqual('pass', result['decision'])
        self.assertIn('no real pilot claim', result['proves'])
        denied = subprocess.run([sys.executable, '-m', 'wfkit.finalgate', str(path)], capture_output=True, text=True)
        self.assertNotEqual(0, denied.returncode)
        self.assertEqual('refused', json.loads(denied.stdout)['decision'])


if __name__ == '__main__':
    unittest.main()
