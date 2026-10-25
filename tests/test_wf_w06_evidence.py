"""W06 evidence for T05 E1, E2, E4, E5, E6 (T37 E3/E6 wait on owner decision O4 and are NOT covered here).

Real temporary ledger, Git and Control attempts (tests.test_wf_engine.EngineFixture); eligibility is read from the real
engine state after the real step / verify / accept_node, never from a hand-built view.
"""
from unittest.mock import patch

from tests.test_wf_engine import EngineFixture, node


class T05EligibilityTests(EngineFixture):
    def setUp(self):
        super().setUp()
        self.revise([node('U'), node('D', ['U']), node('A', ['U'], requires='accepted', write=('b.txt',)),
                     node('I', ['U', 'D', 'A'], integration=True, write=())])

    def look(self, nid):
        return self.engine.eligible(self.engine.state(self.ledger, 'P1'), nid)

    def walk(self):
        """What the three consumers answer at each state of U: produced, verified, accepted."""
        self.assertEqual(self.step()['node'], 'U')
        produced = {n: self.look(n) for n in ('D', 'A')}
        self.assertEqual(self.engine.state(self.ledger, 'P1')['nodes']['U']['state'], 'produced')
        self.verify('U')
        verified = {n: self.look(n) for n in ('D', 'A')}
        self.assertEqual(self.engine.state(self.ledger, 'P1')['nodes']['U']['state'], 'verified')
        self.engine.accept_node(self.ledger, 'P1', 'U')
        accepted = {n: self.look(n) for n in ('D', 'A')}
        return produced, verified, accepted

    def test_t05_e1_e2_e4_reasons_and_transitions_on_the_real_engine_state(self):
        """W06 / T05 E1: produced U -> D not eligible, reason names U and `verified`. E2: verified U -> D eligible.
        E4: verified (not accepted) U -> a `requires: accepted` consumer is not eligible, reason names `accepted`;
        it becomes eligible only after accept_node."""
        produced, verified, accepted = self.walk()
        self.assertFalse(produced['D']['ready'])
        self.assertIn('U', produced['D']['reason']); self.assertIn('verified', produced['D']['reason'])
        self.assertTrue(verified['D']['ready'])
        self.assertFalse(verified['A']['ready'])
        self.assertIn('U', verified['A']['reason']); self.assertIn('accepted', verified['A']['reason'])
        self.assertTrue(accepted['A']['ready'])

    def violations(self):
        """The T05 forbidden results, as a list; empty means the function under test is honest."""
        out = []
        produced, verified, _ = self.walk()
        if produced['D']['ready']: out.append('E5: D eligible while U is only produced')
        if verified['A']['ready']: out.append('E6: verified treated as accepted')
        return out

    def test_t05_e5_e6_the_real_function_has_no_violation(self):
        """W06 / T05 E5 and E6: no run of the real eligible() reports D ready on a produced U or an accepted-consumer ready on a verified U."""
        self.assertEqual(self.violations(), [])

    def test_t05_e5_counterexample_produced_counted_as_verified_goes_red(self):
        """W06 / T05 E5 mutant: if _rank counted `produced` as `verified`, the same check reports the violation."""
        real = self.engine._rank
        states = self.engine.STATES
        def mutant(record):
            rank = real(record)
            return states['verified'] if rank == states['produced'] else rank
        with patch.object(self.engine, '_rank', mutant):
            self.assertTrue(any(v.startswith('E5') for v in self.violations()))

    def test_t05_e6_counterexample_verified_counted_as_accepted_goes_red(self):
        """W06 / T05 E6 mutant: if _rank counted `verified` as `accepted`, the same check reports the violation."""
        real = self.engine._rank
        states = self.engine.STATES
        def mutant(record):
            rank = real(record)
            return states['accepted'] if rank == states['verified'] else rank
        with patch.object(self.engine, '_rank', mutant):
            self.assertTrue(any(v.startswith('E6') for v in self.violations()))
