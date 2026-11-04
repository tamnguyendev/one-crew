"""T37 (W06 with W02/W03, R04) [E1], [E2], [E4], [E5]: internal acceptance of children by node state and authority; the root waits for the owner.

Engine fixture (self_decide includes Q12): two children C and D are verified, OneCrew accepts them internally (Q12, one HD-05 record each);
the root stays `approved` (waiting for the owner), an acceptance attempted from the AI session is refused and no `plan.accepted` exists.
[E3]/[E6] (step 3) run only when the open decision O4 is answered "có"; it is not answered, so that step is NOT run and not counted here.
"""
import os

from onecrew.ledger import LedgerError
from onecrew.v2 import plan
from tests.test_wf_engine import EngineFixture, node


class ChildAcceptanceTests(EngineFixture):
    def test_e1_e2_e4_e5_children_accepted_internally_with_q12_records_and_the_root_still_waits(self):
        other = node('D', write=('b.txt',)); other['read'] = ['b.txt']
        integration = node('I', ['C', 'D'], integration=True, write=()); integration['read'] = []
        self.revise([node('C'), other, integration])
        for nid in ('C', 'D'):
            self.assertEqual(self.step()['node'], nid); self.verify(nid)
        before = len([1 for k, _ in self.events() if k == 'decision.recorded'])
        for nid in ('C', 'D'):
            accepted = self.engine.accept_node(self.ledger, 'P1', nid)
            self.assertEqual(accepted['state'], 'accepted')                                                   # [E1] internal acceptance
        records = [p for k, p in self.events() if k == 'decision.recorded'][before:]
        q12 = [p for p in records if p['basis'].startswith('Q12')]
        self.assertEqual(sorted(p['scope'] for p in q12), ['C', 'D'])                                         # [E1] one HD-05 record per child, authority Q12
        for p in q12:
            self.assertEqual(p['subject']['component'], 'onecrew.engine'); self.assertEqual(p['validity']['outcome'], 'in_authority')
            self.assertTrue(p['authority'] and p['evidence'])
        self.assertEqual([k for k, _ in self.events() if k == 'node.accepted'].count('node.accepted'), 2)
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'approved')                                  # [E2]/[E5] the root did not change
        self.assertEqual(os.environ.get('ONECREW_ACTOR'), 'codex')                                             # this is the AI session
        with self.assertRaises(LedgerError) as refused:
            plan.accept(self.ledger, 'P1', 'owner', 'the AI tries to accept the root', self.tree())             # [E2]/[E4] refused
        self.assertIn('cannot approve or accept', str(refused.exception))
        self.assertEqual([k for k, _ in self.events() if k == 'plan.accepted'], [])                             # [E4] count = 0
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'approved')
