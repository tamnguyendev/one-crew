"""T28 (R05, round 7) [E4]/[E6]: plan v2 closes a finding only through the register's closure function.

Real temporary ledger, injected reviewer receipts (tests.test_wf_findings fixture, no model). One run of the three cases on one finding F:
(a) a commit changes the related file, (b) a generic accept, (c) a passing re-check on the new artifact with evidence. The integration
check counts calls of the shared closure transition `finding_core.close_finding`: 0 at (a) and (b), at least 1 at (c), and F ends
resolved with its evidence and artifact. The "wrong wiring" counter-example - plan v2 sets F closed itself without calling the register
transition - is patched into onecrew.v2.findings and turns the integration check red.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from onecrew import finding_core
from onecrew.v2 import findings, plan as plans
from tests import test_wf_findings


def rewired_close(value, ident, receipt, *, shown, resolution, listed=None, receipts=(), status='resolved', head_closed=160):
    """The counter-example: v2 marks the finding closed itself, never calling the register's transition."""
    target = next(f for f in value['findings'] if f['id'] == ident)
    target.update(status=status, resolution=dict(resolution))
    return target


class T28ClosureWiringTests(unittest.TestCase):
    def setUp(self):
        self.fx = test_wf_findings.FindingTests()
        self.addCleanup(self.fx.doCleanups)
        self.fx.setUp()

    def run_cases(self):
        """Returns (calls at a, calls at b, calls at c, status after a, after b, final row)."""
        fx = self.fx
        fx.open()
        with patch.object(finding_core, 'close_finding', wraps=finding_core.close_finding) as close:
            (fx.root / 'a.txt').write_text('repaired\n')
            fx.git('add', 'a.txt'); fx.git('commit', '-q', '-m', 'repair')            # (a) a commit changes the related file
            fx.artifact = fx.tree()
            after_a = (close.call_count, fx.rows()[0]['status'])
            fx.open(fx.receipt('pass'))                                                   # (b) the reviewer's generic accept/pass ...
            with fx.ledger.transaction(write=True) as conn:                              # ... and a generic plan accept
                plans.emit(fx.ledger, conn, fx.task, 'plan.accepted', {'plan': 'P1', 'revision': 1, 'artifact_sha': fx.artifact})
            after_b = (close.call_count, fx.rows()[0]['status'])
            receipt = fx.receipt('pass')                                                  # (c) passing re-check on the new artifact
            closed = fx.close(receipt)
            calls_c = close.call_count - after_b[0]
        return after_a, after_b, calls_c, closed, receipt, findings.list_findings(fx.ledger, 'P1')[0]

    def integration_holds(self, after_a, after_b, calls_c, closed, receipt, row):
        return (after_a == (0, 'open') and after_b == (0, 'open') and calls_c >= 1 and closed['closed'] == ['RF1']
                and row['status'] == 'resolved' and row['resolution']['evidence'] == [receipt]
                and row['resolution']['artifact_sha'] == self.fx.artifact)

    def test_e4_closure_goes_through_the_register_transition_only_at_c(self):
        self.assertTrue(self.integration_holds(*self.run_cases()))

    def test_e6_wrong_wiring_closing_without_the_register_turns_the_check_red(self):
        mutant = SimpleNamespace(**{k: getattr(finding_core, k) for k in dir(finding_core) if not k.startswith('__')})
        mutant.close_finding = rewired_close
        with patch.object(findings, 'core', mutant):
            outcome = self.run_cases()
        after_a, after_b, calls_c, closed, receipt, row = outcome
        self.assertEqual(row['status'], 'resolved', 'the mutant does close F, by itself')
        self.assertEqual(calls_c, 0)
        self.assertFalse(self.integration_holds(*outcome))


if __name__ == '__main__':
    unittest.main()
