"""T40c (RP, round 7): the RP delivery check of the published provider subset (wfkit.release_check, T54.5 / W40-RP).

Fixture bundles of tests.test_wf_release_check (simulated receipts, validator rules only; no provider is called):
  case K [E30]/[E35]/[E29]: four claude/codex cells pass on the delivered hash, the two kiro cells are blocked for a missing account;
     the RP gate passes with the four-cell subset, each usable cell carries its evidence hash and validity (direct), the kiro cells are
     `unverified`, and the pinned provider/model rows are unchanged by the check.
  x6 [E33]: the notes claim kiro:reviewer usable while the matrix says unverified (in the subset, or as a forged state) - refused.
  x7 [E34]: the codex:reviewer pass receipt is on another build than the delivered one, with no valid inheritance - refused, naming the
     cell.
x7 names the cell, both hashes and the missing comparison (wfkit/provider_evidence.py message, round 7). The wording of the per-cell
reason in the notes ("chưa dùng được: thiếu tài khoản") and an x6 refusal text that names the cell when only the subset lies are not
checked by the product (recorded as uncovered in docs/wf/r7-c2-matrix.json).
"""
import copy
import unittest

from wfkit import release_check as check
from wfkit.finalgate import identity
from tests import test_wf_release_check as base

CELLS_K = {'claude:reviewer', 'claude:advisor', 'codex:reviewer', 'codex:advisor'}


class T40cSubsetTests(unittest.TestCase):
    def setUp(self):
        self.fx = base.ReleaseCheckTests()
        self.addCleanup(self.fx.doCleanups)
        self.fx.setUp()
        self.fx.retarget('RP')

    def matrix(self, codex_reviewer_on=None):
        fx, rows, items = self.fx, [], []
        for provider in ('claude', 'codex', 'kiro'):
            for role in ('reviewer', 'advisor'):
                key = provider + ':' + role; usable = provider != 'kiro'
                row = {'id': key, 'provider': provider, 'role': role, 'model': 'fixture-model-' + provider, 'vendor': 'vendor-' + provider,
                       'cli_sha256': 'e' * 64, 'cli_files': {'fixture.exe': 'e' * 64}, 'status': 'usable' if usable else 'unverified'}
                rows.append(row)
                artifact = codex_reviewer_on if (key == 'codex:reviewer' and codex_reviewer_on) else None
                original = fx.receipt(artifact, kind='behavior', item=key, provider=provider, role=role, model=row['model'], vendor=row['vendor'],
                                      result='pass' if usable else 'blocked', reason='thiếu tài khoản',
                                      cli_identity={'provider': provider, 'path': 'fixture.exe', 'argv': ['fixture.exe'], 'sha256': 'e' * 64,
                                                    'files': row['cli_files'], 'version': 'fixture-1'})
                items.append({'id': key, 'original': original, 'supplements': []})
        fx.bundle['provider_bundle'] = {'artifacts': {'pilot': fx.current, 'final': fx.current}, 'providers': rows, 'comparison': {'items': items}}
        return rows, items

    def notes(self, states, subset):
        self.fx.change('notes', lambda r: r.update(provider_states=states, subset=sorted(subset), p1_count=len(subset), p1_label='subset'))

    def test_e29_e30_e35_case_k_four_cell_subset_is_delivered_with_kiro_unverified_and_pins_unchanged(self):
        rows, items = self.matrix()
        pins = copy.deepcopy(rows)
        states = check.providers(rows, items, check.Receipts(self.fx.root, True), self.fx.current, self.fx.current)
        usable = {k for k, s in states.items() if s['status'] == 'usable'}
        self.assertEqual(usable, CELLS_K)                                                         # [E30] the subset is the four cells
        for key in CELLS_K:                                                                       # [E29] origin hash and validity per cell
            self.assertEqual(states[key]['validity'], 'direct')
            self.assertEqual(states[key]['evidence'], identity(self.fx.current))
        self.assertEqual({states[k]['status'] for k in ('kiro:reviewer', 'kiro:advisor')}, {'unverified'})
        self.notes(states, usable)
        result = self.fx.result()
        self.assertEqual(result['decision'], 'pass', result)                                       # [E35] not held for the two kiro cells
        self.assertTrue(result['conditions']['T54.5'])
        self.assertEqual(self.fx.bundle['provider_bundle']['providers'], pins)                    # [E30] kiro provider/model pins unchanged
        self.notes(states, usable - {'codex:advisor'})                                            # [E29] a usable cell left out: refused
        self.fx.refused('T54.5')

    def test_e33_x6_a_kiro_reviewer_claimed_usable_against_the_matrix_is_refused(self):
        rows, items = self.matrix()
        states = check.providers(rows, items, check.Receipts(self.fx.root, True), self.fx.current, self.fx.current)
        self.notes(states, CELLS_K | {'kiro:reviewer'})                                           # x6 in the subset
        self.fx.refused('T54.5')
        forged = copy.deepcopy(states); forged['kiro:reviewer'] = {'status': 'usable', 'validity': 'direct', 'evidence': identity(self.fx.current)}
        self.notes(forged, CELLS_K | {'kiro:reviewer'})                                           # x6 as a forged cell state
        self.fx.refused('T54.5')
        next(r for r in rows if r['id'] == 'kiro:reviewer')['status'] = 'usable'                                                             # x6 in the matrix row itself
        self.notes(states, CELLS_K)
        self.fx.refused('T54.5')
        detail = next(r['detail'] for r in self.fx.result()['reasons'] if r['code'] == 'T54.5')
        self.assertIn('kiro:reviewer', detail)

    def test_e34_x7_codex_reviewer_pass_on_another_build_without_inheritance_is_refused_naming_the_cell(self):
        rows, items = self.matrix(codex_reviewer_on=self.fx.previous)
        self.notes({}, CELLS_K)
        self.fx.refused('T54.5')
        detail = next(r['detail'] for r in self.fx.result()['reasons'] if r['code'] == 'T54.5')
        self.assertIn('codex:reviewer', detail)
        self.assertIn('evidence not valid for the delivered build', detail)                       # [E34] both hashes, missing comparison
        self.assertIn(self.fx.previous['wheel_sha256'], detail)
        self.assertIn(self.fx.current['wheel_sha256'], detail)
        self.assertIn('no valid inheritance comparison', detail)


if __name__ == '__main__':
    unittest.main()
