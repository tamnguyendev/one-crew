"""W05 / T21: the revision comparator classifies each change; what it cannot classify is a change (safe)."""
import copy
import unittest

from onecrew.v2 import acceptance_diff as ad
from tests.test_v2_l1 import plan_json, milestone
from tests.test_v2_reviewer import reviewer_milestone

OUTPUT = 'Row count equals 100 after the import'


def contract(**extra):
    value = plan_json(output=[OUTPUT, 'The report lists every failed row'], milestones=[milestone(), dict(reviewer_milestone(), id='M2', covers=['O2'])])
    value['items'] = [{'id': 'I1', 'title': 'Do it', 'tier': 'must', 'milestone': 'M1'}, {'id': 'I2', 'title': 'Report', 'tier': 'must', 'milestone': 'M2'}]
    return dict(value, **extra)


class ContractPairsTests(unittest.TestCase):
    def pair(self, mutate):
        before = contract(); after = copy.deepcopy(before); mutate(after)
        return ad.classify_contract(before, after)

    def test_a_wording_only_is_not_a_change_of_acceptance(self):
        result = self.pair(lambda c: c['output'].__setitem__(0, 'row count  EQUALS 100, after the import.'))
        self.assertFalse(result['acceptance_changed']); self.assertEqual([c['kind'] for c in result['changes']], ['wording'])            # [E1] (a)

    def test_b_an_added_check_is_not_a_change_of_acceptance(self):
        def add(c): c['milestones'][1]['verifier']['config']['criteria'].append({'id': 'R9', 'question': 'Does the diff keep the header row of report.csv?'})
        result = self.pair(add)
        self.assertFalse(result['acceptance_changed']); self.assertEqual([c['kind'] for c in result['changes']], ['added_check'])          # [E1] (b)

    def test_c_a_changed_threshold_is_u1(self):
        result = self.pair(lambda c: c['output'].__setitem__(0, OUTPUT.replace('100', '90')))
        self.assertTrue(result['acceptance_changed']); self.assertEqual(result['classification'], 'U1')
        self.assertEqual([c['kind'] for c in result['changes']], ['threshold']); self.assertIn('threshold', result['summary'])              # [E2] (c)

    def test_d_a_dropped_required_result_is_u1(self):
        def drop(c): del c['output'][1]; del c['milestones'][1]; del c['items'][1]
        result = self.pair(drop)
        self.assertTrue(result['acceptance_changed']); self.assertIn('removed_result', [c['kind'] for c in result['changes']])             # [E2] (d)

    def test_e_a_narrowed_acceptance_is_u1(self):
        result = self.pair(lambda c: c['output'].__setitem__(1, 'The report lists failed rows of the first batch only'))
        self.assertTrue(result['acceptance_changed']); self.assertEqual(result['changes'][0]['kind'], 'narrowed_or_changed')              # [E2] (e)
        scope = self.pair(lambda c: c['scope'].__setitem__('owned', []))
        self.assertTrue(scope['acceptance_changed']); self.assertIn('narrowed', [c['kind'] for c in scope['changes']])

    def test_f_a_changed_obligation_is_u1(self):
        result = self.pair(lambda c: c['milestones'][0].__setitem__('covers', ['O2']))
        self.assertTrue(result['acceptance_changed']); self.assertEqual([c['kind'] for c in result['changes']], ['obligation'])            # [E2] (f)
        argv = self.pair(lambda c: c['milestones'][0]['verifier']['config'].__setitem__('argv', ['python', '-c', 'pass']))
        self.assertTrue(argv['acceptance_changed'])

    def test_g_an_unknown_field_change_is_treated_as_a_change(self):
        result = self.pair(lambda c: c.__setitem__('tolerance_policy', {'rows': 5}))
        self.assertTrue(result['acceptance_changed']); self.assertEqual(result['changes'][0]['kind'], 'unknown')                             # [E3] (g)

    def test_e4_table_of_seven_no_c_to_f_is_routine(self):
        """[E4]: a comparator that calls every change wording would turn (c)-(f) routine; this table keeps it red."""
        table = {'a': self.pair(lambda c: c['output'].__setitem__(0, OUTPUT + '.')),
                 'b': self.pair(lambda c: c['milestones'][1]['verifier']['config']['criteria'].append({'id': 'R9', 'question': 'Is report.csv sorted by id?'})),
                 'c': self.pair(lambda c: c['output'].__setitem__(0, OUTPUT.replace('100', '99'))),
                 'd': self.pair(lambda c: (c['output'].pop(), c['milestones'].pop(), c['items'].pop())),
                 'e': self.pair(lambda c: c['output'].__setitem__(1, 'The report lists every failed row except warnings')),
                 'f': self.pair(lambda c: c['milestones'][1].__setitem__('mode', 'until_pass')),
                 'g': self.pair(lambda c: c.__setitem__('extra_rule', True))}
        self.assertEqual({k: v['acceptance_changed'] for k, v in table.items()}, {'a': False, 'b': False, 'c': True, 'd': True, 'e': True, 'f': True, 'g': True})
        self.assertEqual([k for k in 'cdef' if table[k]['classification'] != 'U1'], [])


class NodePairsTests(unittest.TestCase):
    def nodes(self):
        from tests.test_wf_engine import node
        a = node('C'); a['checks'] = [{'id': 'M1', 'spec': 'Row count equals 100 after the import'}]
        return [a, node('I', ['C'], integration=True, write=())]

    def test_reworded_spec_and_added_check_are_routine_but_removed_or_tightened_are_u1(self):
        before = self.nodes(); outputs = ['O1']
        reworded = copy.deepcopy(before); reworded[0]['checks'][0]['spec'] = 'row count equals 100, after the import'
        self.assertFalse(ad.classify_nodes(before, reworded, outputs)['acceptance_changed'])
        added = copy.deepcopy(before); added[0]['checks'].append({'id': 'M2', 'spec': 'The log has no error line'})
        self.assertFalse(ad.classify_nodes(before, added, outputs)['acceptance_changed'])
        removed = copy.deepcopy(before); removed[0]['checks'] = []
        self.assertEqual(ad.classify_nodes(before, removed, outputs)['changes'][0]['kind'], 'removed_check')
        threshold = copy.deepcopy(before); threshold[0]['checks'][0]['spec'] = 'Row count equals 50 after the import'
        self.assertEqual(ad.classify_nodes(before, threshold, outputs)['changes'][0]['kind'], 'threshold')
        uncovered = copy.deepcopy(before); uncovered[0]['acceptance'] = []; uncovered[1]['acceptance'] = []
        self.assertEqual(ad.classify_nodes(before, uncovered, outputs)['changes'][0]['kind'], 'removed_result')
