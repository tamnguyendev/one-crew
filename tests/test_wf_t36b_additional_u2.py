"""T36b (W32a) [E11]: three kinds of additional work — mandatory into the forecast (A2), optional into the backlog, outside-authority into one
U2 request that holds exactly the dependent nodes while the rest keeps running; [E16]/[E17]: no ETA change without a reason, the optional work
never enters the ETA, and the U2 is the ONLY request (no request for the mandatory or optional work).

Engine fixture (root budget): nodes A (depends on the outside-authority work), B (independent), I (integration). The outside-authority work
`db-grant` holds A (and I) through the unknown mechanism and B runs; the owner's resolution of the unknown releases A.
"""
from onecrew.ledger import LedgerError
from onecrew.v2 import estimates, plan, runtime_unknowns
from tests.test_wf_engine import EngineFixture, node


class AdditionalWorkTests(EngineFixture):
    def setUp(self):
        super().setUp()
        import os
        actor = os.environ.pop('ONECREW_ACTOR', None)                                            # the owner approves from their own terminal
        plan.approve(self.ledger, 'P1', 'owner', 'fixture with estimate', estimate={'execution_seconds': [7200, 10800], 'evidence': ['fixture decomposition']})
        if actor is not None: os.environ['ONECREW_ACTOR'] = actor
        independent = node('B', write=('b.txt',)); independent['read'] = ['b.txt']
        integration = node('I', ['A', 'B'], integration=True, write=()); integration['read'] = []
        self.revise([node('A'), independent, integration])
        self.task = plan.show(self.ledger, 'P1')['anchor_task']

    def test_e11_three_kinds_mandatory_forecast_optional_backlog_outside_authority_u2_holds_dependents(self):
        before = estimates.read(self.ledger, 'P1')['remaining_seconds']
        mandatory = estimates.additional(self.ledger, 'P1', 'migration', 'mandatory', 'A2 needs a schema migration', ['O1'], [3600, 7200], ['a.txt:1'])
        optional = estimates.additional(self.ledger, 'P1', 'cleanup', 'optional', 'dead code could go', ['O1'], [1800, 3600], ['a.txt:1'])
        self.assertEqual(len(self.ledger.requests(self.task)), 0, 'mandatory and optional work ask nobody')          # [E17]
        self.assertEqual((mandatory['disposition'], optional['disposition']), ('forecast', 'backlog'))
        after = estimates.read(self.ledger, 'P1')
        self.assertEqual(after['remaining_seconds'], [before[0] + 3600, before[1] + 7200])                           # only the mandatory work moves the ETA
        self.assertTrue(all(row.get('reason') for row in after['history']))                                           # [E16] every ETA record has a reason
        with self.assertRaises(LedgerError):
            estimates.additional(self.ledger, 'P1', 'x', 'optional', 'holds nothing', ['O1'], [60, 120], ['a.txt:1'], nodes=['A'])
        outside = estimates.additional(self.ledger, 'P1', 'db-grant', 'outside_authority', 'needs a write on the shared DB repo outside the scope',
                                       ['O1'], [3600, 7200], ['a.txt:1'], nodes=['A'], still_running=['B'])
        self.assertEqual(outside['disposition'], 'U2')
        u2 = outside['u2']
        requests = self.ledger.requests(self.task)
        self.assertEqual([r['id'] for r in requests], [u2['request']])                                                # exactly one request: the U2
        action = requests[0]['question']['action']
        self.assertEqual((action['type'], action['parameters']['class'], action['parameters']['additional'], action['parameters']['nodes']), ('authorize', 'U2', 'db-grant', ['A']))
        self.assertEqual(action['parameters']['still_running'], ['B'])
        self.assertEqual(requests[0]['state'], 'pending')
        self.assertEqual(estimates.read(self.ledger, 'P1')['remaining_seconds'], after['remaining_seconds'], 'outside-authority work is not taken into the ETA')
        view = self.engine.state(self.ledger, 'P1')
        self.assertEqual(set(view['unknown_blockers']), {'A'})                                                         # exactly the dependent node (I waits on A through its inputs)
        self.assertEqual([n['id'] for n in self.engine.ready(self.ledger, 'P1')], ['B'])                              # the rest runs
        self.assertEqual(self.step()['node'], 'B'); self.verify('B')
        again = estimates.additional(self.ledger, 'P1', 'db-grant', 'outside_authority', 'needs a write on the shared DB repo outside the scope',
                                     ['O1'], [3600, 7200], ['a.txt:1'], nodes=['A'], still_running=['B'])
        self.assertEqual(len(self.ledger.requests(self.task)), 1, 'the same work twice is one U2')
        self.assertEqual(again['u2']['request'], u2['request'])
        import os
        actor = os.environ.pop('ONECREW_ACTOR', None)                                            # the owner resolves from their own terminal
        try:
            runtime_unknowns.resolve(self.ledger, 'P1', 'additional-db-grant', by='owner', evidence='a.txt:1', answer='Owner granted the DB write in a new revision')
        finally:
            if actor is not None: os.environ['ONECREW_ACTOR'] = actor
        self.assertEqual(self.engine.state(self.ledger, 'P1')['unknown_blockers'], {})
        self.assertEqual(self.step()['node'], 'A')
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'approved')
