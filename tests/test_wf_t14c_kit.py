"""T14c kit (WKPL): the T14b same-core comparison made PARAMETRIC over a state root (wfkit.pilot_entry.same_core).

The selftest drives CODE / DATA / OPS roots into one temporary ledger with the same fixtures as tests/test_wf_t14b_same_core.py
(reusing tests/test_wf_rx2_adapters), then calls same_core on that state root by root names only. The same function will later run
on the real pilot ledger after PL-B (T14c, PL-B); this module proves the comparison and its refusal, it does NOT claim a pilot.
Counter-example: a root whose lifecycle differs (approved and verified but never accepted) is refused, naming the root and the field.
"""
import copy
import sys

from onecrew.v2 import plan as plans, verdict
from tests.test_v2_l1 import Fixture, plan_json, milestone
import tests.test_wf_rx2_adapters as rx2
from wfkit.pilot_entry import same_core

SCOPE = {'owned': ['a.txt', 'output.csv', 'operation.json', 'post.json']}


class SameCoreKitTests(Fixture):
    def setUp(self):
        super().setUp()
        for name in ('input.csv', 'output.csv'):
            (self.root / name).write_text(rx2.TABLE, encoding='utf-8')
        rx2.write_ops(self.root)
        self.git('add', '.'); self.git('commit', '-qm', 'data and ops fixtures')
        self.milestones = {'CODE': milestone('M1', argv=[sys.executable, '-c', 'print("ok")']),
                           'DATA': rx2.milestone('data', copy.deepcopy(rx2.DATA)),
                           'OPS': rx2.milestone('ops', copy.deepcopy(rx2.OPS))}

    def drive(self, name, m, accept=True):
        plans.propose(self.ledger, name, plan_json(milestones=[m], scope=SCOPE), 'codex', workflow=True,
                      capabilities=['namespaced-storage', 'finding-register'])
        plans.approve(self.ledger, name, 'owner', 'fixture', estimate={'execution_seconds': [60, 120], 'evidence': ['fixture decomposition']})
        self.assertEqual(verdict.run(self.ledger, name, 'M1', self.root)['milestones'][0]['state'], 'passed', name)
        if accept:
            plans.accept(self.ledger, name, 'owner', 'fixture acceptance', verdict.artifact(self.ledger, name)['artifact_sha'])

    def roots(self, *names):
        return {n: (self.root, n) for n in names}

    def test_three_roots_on_one_state_root_share_the_core(self):
        for name, m in self.milestones.items():
            self.drive(name, m)
        result = same_core(self.ledger.state_root, self.roots('CODE', 'DATA', 'OPS'))
        self.assertTrue(result['ok'], result['differences'])
        code = result['roots']['CODE']
        self.assertEqual(code['lifecycle'], ['task.submitted', 'plan.proposed', 'plan.approved', 'verdict.run_started',
                                             'verdict.receipt_issued', 'verdict.recorded', 'milestone.passed', 'plan.accepted'])
        self.assertEqual(code["handover_shape"], ["BÀN GIAO", "Theo acceptance:", "Hạn chế còn lại:", 1])
        self.assertIn("execution_seconds", code["budget_fields"])
        for name in ('DATA', 'OPS'):
            self.assertEqual(result['roots'][name], code, name)
        self.assertFalse(result['pilot_evidence'])
        self.assertFalse(result['owner_acceptance'])

    def test_refuses_when_a_root_lifecycle_differs(self):
        self.drive('CODE', self.milestones['CODE'])
        self.drive('DATA', self.milestones['DATA'])
        self.drive('OPS', self.milestones['OPS'], accept=False)                  # counter-example: never accepted
        result = same_core(self.ledger.state_root, self.roots('CODE', 'DATA', 'OPS'))
        self.assertFalse(result['ok'])
        lifecycle = [d for d in result['differences'] if d['field'] == 'lifecycle']
        self.assertEqual([d['root'] for d in lifecycle], ['OPS'], result['differences'])
        self.assertNotIn('plan.accepted', lifecycle[0]['actual'])
        self.assertIn('plan.accepted', lifecycle[0]['expected'])
        self.assertNotIn('DATA', {d['root'] for d in result['differences']})

    def test_unknown_root_is_refused_never_passed(self):
        self.drive('CODE', self.milestones['CODE'])
        result = same_core(self.ledger.state_root, {'CODE': (self.root, 'CODE'), 'DATA': (self.root, 'NO-SUCH-ROOT')})
        self.assertFalse(result['ok'])
        self.assertEqual([(d['root'], d['field']) for d in result['differences']], [('DATA', 'readable')])

    def test_reads_only(self):
        for name, m in self.milestones.items():
            self.drive(name, m)
        before = self.ledger.path.read_bytes()
        same_core(self.ledger.state_root, self.roots('CODE', 'DATA', 'OPS'))
        self.assertEqual(before, self.ledger.path.read_bytes())


if __name__ == '__main__':
    import unittest
    unittest.main()
