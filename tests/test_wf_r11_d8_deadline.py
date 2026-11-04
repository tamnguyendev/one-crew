"""Round 11 finding C (P2): the D8 execution-cap deadline check must look at the same nodes the D8 cost counts.

Reproduced defect (Codex round 11, 26/10/2026): `internal_plan.revise` refused a revision when ANY node's execution_cap_seconds exceeded
the remaining root deadline, verified nodes with valid reused evidence included: A and B verified with cap 600 s, the integration node
capped at 30 s, 100 s left on the root -> the integration revise was refused although only 30 s of work remains.

Required: the cap check (decision time and publication time) uses the to-come set of `_to_come`; a still-pending node, a verified node
whose generation this revision moves, and the integration node stay checked; the deadline is never extended and a shrinking deadline
between decision and publication is still refused.
"""
import copy
from unittest.mock import patch

from onecrew.ledger import LedgerError
from tests import test_wf_r10_d8_revise_ceiling as r10


class DeadlineToComeTests(r10.ReviseCeilingTests):
    def setUp(self):
        super().setUp()
        for item in self.nodes:
            item['execution_cap_seconds'] = 30 if item['integration'] else 600
        self.revise(self.nodes)                                    # 7200 s left at plan time: every cap fits

    def remaining(self, *seconds):
        """Patch the root ceilings so successive reads report the given remaining seconds (last value repeats)."""
        real, values = self.ip.ceilings, list(seconds)
        def shrunk(ledger, conn, state):
            result = dict(real(ledger, conn, state))
            result['remaining_seconds'] = values.pop(0) if len(values) > 1 else values[0]
            return result
        return patch.object(self.ip, 'ceilings', side_effect=shrunk)

    def test_reproduction_verified_nodes_with_reused_evidence_do_not_block_the_integration_revise(self):
        self.run_units()
        with self.remaining(100):
            self.revise(self.changed('I', goal='Integrate A and B into one checked result'))
        cost = self.last_cost()
        self.assertEqual((cost['counted'], cost['reused']), (['I'], ['A', 'B']))
        self.assertEqual(self.engine.state(self.ledger, 'P1')['nodes']['A']['state'], 'verified')

    def test_a_a_still_pending_node_with_a_cap_beyond_the_deadline_is_refused(self):
        self.assertEqual(self.step()['node'], 'A'); self.verify('A')        # B never ran
        with self.remaining(100), self.assertRaisesRegex(LedgerError, 'execution cap exceeds the remaining root deadline'):
            self.revise(self.changed('I', goal='Integrate A and B into one checked result'))

    def test_b_a_verified_node_whose_generation_moves_must_fit_the_deadline(self):
        self.run_units()
        with self.remaining(100), self.assertRaisesRegex(LedgerError, 'execution cap exceeds the remaining root deadline'):
            self.revise(self.changed('A', goal='Produce evidence for O1 with the full path key'))

    def test_b2_a_dependency_change_reruns_the_dependent_and_keeps_it_checked(self):
        self.run_units()
        nodes = self.changed('B', goal='Produce evidence for O1 again')
        next(n for n in nodes if n['id'] == 'B')['execution_cap_seconds'] = 50     # B fits, I fits, A reused
        with self.remaining(100):
            self.revise(nodes)
        self.assertEqual(self.last_cost()['counted'], ['B', 'I'])

    def test_c_an_integration_node_cap_beyond_the_deadline_is_refused(self):
        self.run_units()
        nodes = self.changed('I', goal='Integrate A and B into one checked result', execution_cap_seconds=200)
        with self.remaining(100), self.assertRaisesRegex(LedgerError, 'execution cap exceeds the remaining root deadline'):
            self.revise(nodes)

    def test_d_a_deadline_shrinking_before_publication_is_still_refused(self):
        self.run_units()
        before = self.ip.current(self.ledger, 'P1')['internal_revision']
        with self.remaining(100, 20), self.assertRaisesRegex(LedgerError, 'changed before revision publication'):
            self.revise(self.changed('I', goal='Integrate A and B into one checked result'))   # I cap 30 > 20 at publish
        self.assertEqual(self.ip.current(self.ledger, 'P1')['internal_revision'], before)

    def test_d2_a_node_invalidated_between_decision_and_publication_is_not_published_as_reused(self):
        self.run_units()
        real, calls = self.ip._to_come, []
        def drifted(*args, **kwargs):
            counted, reused = real(*args, **kwargs)
            calls.append(1)
            return (counted, reused) if len(calls) == 1 else (counted | {'A'}, reused - {'A'})
        before = self.ip.current(self.ledger, 'P1')['internal_revision']
        with patch.object(self.ip, '_to_come', side_effect=drifted),                 self.assertRaisesRegex(LedgerError, 'changed before revision publication'):
            self.revise(self.changed('I', goal='Integrate A and B into one checked result'))
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.ip.current(self.ledger, 'P1')['internal_revision'], before)

    def test_e_no_deadline_left_refuses_even_reused_plans_that_still_have_work(self):
        self.run_units()
        with self.remaining(0), self.assertRaisesRegex(LedgerError, 'execution cap exceeds the remaining root deadline'):
            self.revise(self.changed('I', goal='Integrate A and B into one checked result'))


def load_tests(loader, tests, pattern):
    # Only this round's cases; the inherited R10 cases run in their own module.
    import unittest
    own = [name for name in vars(DeadlineToComeTests) if name.startswith('test_')]
    return unittest.TestSuite(DeadlineToComeTests(name) for name in sorted(own))


if __name__ == '__main__':
    import unittest
    unittest.main()
