"""T40c (RP, round 7): the RP delivery check of the published provider subset (wfkit.release_check, T54.5 / W40-RP).

Fixture bundles of tests.test_wf_release_check (simulated receipts, validator rules only; no provider is called):
  case K [E30]/[E35]/[E29]: four claude/codex cells pass on the delivered hash, the two kiro cells are blocked for a missing account;
     the RP gate passes with the four-cell subset, each usable cell carries its evidence hash and validity (direct), the kiro cells are
     `unverified`, and the pinned provider/model rows are unchanged by the check.
  x6 [E33]: the notes claim kiro:reviewer usable while the matrix says unverified (in the subset, or as a forged state) - refused.
  x7 [E34]: the codex:reviewer pass receipt is on another build than the delivered one, with no valid inheritance - refused, naming the
     cell.
x7 names the cell, both hashes and the missing comparison (wfkit/provider_evidence.py message, round 7).
Round 7 D (GAP 3): every cell that is not `usable` carries its status and the reason (finalgate.evidence_status, the one evaluator); the
RP notes receipt renders one line per cell (provider_evidence.render: usable with origin hash and validity, any other with its status and
reason, e.g. "chưa dùng được: thiếu tài khoản"); a cell without its reason, or a rendering that drops a reason, is refused naming the
cell; x6 is refused as "subset chứa ô chưa đạt" naming the cell (provider x role) and its status.
"""
import copy
import unittest

from wfkit import provider_evidence, release_check as check
from wfkit.finalgate import evidence_status, identity
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

    def notes(self, states, subset, rendered=None):
        lines = provider_evidence.render(states) if rendered is None and hasattr(provider_evidence, 'render') else (rendered or [])
        self.fx.change('notes', lambda r: r.update(provider_states=states, subset=sorted(subset), p1_count=len(subset), p1_label='subset',
                                                   matrix_markdown=chr(10).join(lines)))

    def states(self, rows, items):
        return check.providers(rows, items, check.Receipts(self.fx.root, True), self.fx.current, self.fx.current)

    def detail(self):
        return next(r['detail'] for r in self.fx.result()['reasons'] if r['code'] == 'T54.5')

    def test_e29_e30_every_cell_that_is_not_usable_carries_its_status_and_reason(self):
        rows, items = self.matrix()
        states = self.states(rows, items)
        for key in ('kiro:reviewer', 'kiro:advisor'):                                              # [E30] the reason of the blocked receipt
            self.assertEqual(states[key]['status'], 'unverified')
            self.assertEqual(states[key].get('reason'), 'thiếu tài khoản', states[key])
        for key in CELLS_K:
            self.assertNotIn('reason', states[key])
        a, b = identity(self.fx.previous), identity(self.fx.current)
        passed = {'kind': 'behavior', 'result': 'pass', 'at': '2026-10-24T12:00:00Z', **a}
        recheck = evidence_status(passed, [], b, None, 'codex:reviewer')                          # other hash, no comparison
        self.assertEqual(recheck['status'], 'recheck')
        self.assertIn(a['wheel_sha256'], recheck['reason']); self.assertIn(b['wheel_sha256'], recheck['reason'])
        self.assertIn('no inheritance comparison', recheck['reason'])
        affected = evidence_status(passed, [], b, {'id': 'cmp-1', 'source': a, 'target': b, 'affected': ['codex:reviewer']}, 'codex:reviewer')
        self.assertEqual(affected['status'], 'recheck'); self.assertIn('cmp-1', affected['reason'])
        failed = evidence_status(dict(passed, result='fail', **b), [], b, None, 'codex:reviewer')
        self.assertEqual(failed['status'], 'failed'); self.assertTrue(failed['reason'])

    def test_e29_e30_the_notes_render_each_cell_with_its_status_and_reason_and_a_dropped_reason_is_refused(self):
        rows, items = self.matrix()
        states = self.states(rows, items)
        lines = provider_evidence.render(states)
        text = chr(10).join(lines)
        self.assertIn('kiro:reviewer: chưa dùng được: thiếu tài khoản', text)                    # [E30] wording of case K
        self.assertIn('kiro:advisor: chưa dùng được: thiếu tài khoản', text)
        for key in CELLS_K:                                                                       # [E29] usable: origin hash + validity
            line = next(l for l in lines if l.startswith('- ' + key + ':'))
            self.assertIn('dùng được', line); self.assertIn('direct', line); self.assertIn(self.fx.current['wheel_sha256'], line)
        self.notes(states, CELLS_K)
        self.assertEqual(self.fx.result()['decision'], 'pass', self.fx.result())
        self.notes(states, CELLS_K, rendered=[l for l in lines if not l.startswith('- kiro:advisor:')])   # the reason line dropped
        self.fx.refused('T54.5')
        self.assertIn('kiro:advisor', self.detail())

    def test_e29_an_unusable_cell_without_its_reason_is_refused_naming_the_cell(self):
        rows, items = self.matrix()
        states = self.states(rows, items)
        stripped = copy.deepcopy(states); stripped['kiro:reviewer'] = {'status': 'unverified'}
        self.notes(stripped, CELLS_K, rendered=provider_evidence.render(states))
        self.fx.refused('T54.5')
        detail = self.detail()
        self.assertIn('kiro:reviewer', detail)
        self.assertIn('reason', detail)

    def test_e33_x6_refusal_says_the_subset_contains_a_cell_not_passed_and_names_it(self):
        rows, items = self.matrix()
        states = self.states(rows, items)
        self.notes(states, CELLS_K | {'kiro:reviewer'})
        self.fx.refused('T54.5')
        detail = self.detail()
        self.assertIn('subset chứa ô chưa đạt', detail)                                          # [E33] wording
        self.assertIn('kiro:reviewer', detail)
        self.assertIn('unverified', detail)
        self.assertNotIn('kiro:advisor', detail)

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
