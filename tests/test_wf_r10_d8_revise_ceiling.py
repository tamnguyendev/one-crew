"""Round 10 D8 (2.2/L0): the revise ceiling counts only the work that must still run.

Reproduced defect (SDK trial 26/10, sample root): `internal_plan.revise` compared the sum of `budget_calls` (and of the upper estimates) of
ALL nodes with what is left of the root, verified unchanged nodes included -> at the end of a root the integration node could not be
revised ("needs 23 calls but the root has 15 left").

Required: cost to come = nodes that are new or whose generation the revision moves (definition/dependency/input change) + nodes not
finished with valid evidence (pending, produced, held, running, failed) - the mandatory integration node is always one of these until it is
verified; unchanged nodes with valid evidence cost 0 more. Spend already used is never subtracted back (the root group keeps used/reserved);
the root ceilings stay. A stale `expected_revision` and an unreconciled attempt are refused as before.
"""
import copy

from onecrew.ledger import LedgerError
from onecrew.v2 import plan as plans
from tests.test_v2_l1 import Fixture, plan_json
from tests.test_wf_engine import EngineFixture, node


def costly(nid, dependencies=(), integration=False, write=('a.txt',)):
    item = node(nid, dependencies, integration=integration, write=write)
    item['budget_calls'] = 3
    return item


class ReviseCeilingTests(EngineFixture):
    def setUp(self):
        Fixture.setUp(self)
        from onecrew.control_core import Control, migrate
        from onecrew.snapshots import Snapshots
        from onecrew.v2 import engine, internal_plan
        import os
        self.ip, self.engine = internal_plan, engine
        value = plan_json(scope={'owned': ['a.txt', 'b.txt']}, budget={'max_calls': 10, 'time': 120}, authority={
            'edit': True, 'commands': True, 'edit_tests': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']})
        self.root_view = plans.propose(self.ledger, 'P1', value, 'codex', workflow=True,
                                       capabilities=['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine'])
        plans.approve(self.ledger, 'P1', 'owner', 'fixture engine approval')
        os.environ['ONECREW_ACTOR'] = 'codex'
        self.store = Snapshots(self.ledger.state_root); migrate(self.ledger); self.control = Control(self.ledger)
        a = costly('A'); b = costly('B', write=('b.txt',)); b['read'] = ['b.txt']
        integration = costly('I', ['A', 'B'], integration=True, write=())
        self.nodes = [a, b, integration]
        self.revise(self.nodes)                                    # 9 calls planned, 10 granted

    def group(self):
        from onecrew.budget_core import group
        with self.ledger.transaction() as conn:
            return group(conn, self.root_view['anchor_task'])

    def last_cost(self):
        payload = [p for kind, p in self.events() if kind == 'plan.revised'][-1]
        return payload['cost']

    def run_units(self):
        for nid in ('A', 'B'):
            self.assertEqual(self.step()['node'], nid); self.verify(nid)
        used = self.group()['used_calls'] + self.group()['reserved_calls']
        self.assertGreater(used, 0)
        return used

    def changed(self, nid, **fields):
        nodes = copy.deepcopy(self.nodes)
        next(n for n in nodes if n['id'] == nid).update(fields)
        return nodes

    def test_a_only_the_last_node_changes_while_earlier_nodes_are_valid(self):
        self.run_units()
        left = self.group()['remaining_calls']
        self.assertLess(left, 9)                                   # the old rule (all nodes, 9 calls) would refuse
        self.revise(self.changed('I', goal='Integrate A and B into one checked result'))
        cost = self.last_cost()
        self.assertEqual((cost['calls'], cost['counted'], cost['reused']), (3, ['I'], ['A', 'B']))
        self.assertEqual(self.group()['remaining_calls'], left)    # nothing refunded, nothing charged by the revise
        self.assertEqual(self.engine.state(self.ledger, 'P1')['nodes']['A']['state'], 'verified')

    def test_b_a_dependency_change_makes_a_verified_node_rerun_and_count(self):
        self.run_units()
        self.revise(self.changed('A', goal='Produce evidence for O1 with the full path key'))
        cost = self.last_cost()
        self.assertEqual((cost['calls'], cost['counted'], cost['reused']), (6, ['A', 'I'], ['B']))
        self.assertIsNone(self.engine.state(self.ledger, 'P1')['nodes']['A']['state'])

    def test_b_the_ceiling_still_refuses_what_must_run_beyond_the_remaining_calls(self):
        self.run_units()
        left = self.group()['remaining_calls']
        nodes = self.changed('A', goal='Produce evidence again', budget_calls=left)        # A + I = left + 3 > left
        with self.assertRaisesRegex(LedgerError, 'calls but the root has'):
            self.revise(nodes)

    def test_c_rename_does_not_erase_used_cost(self):
        used = self.run_units()
        nodes = copy.deepcopy(self.nodes)
        nodes[0]['id'] = 'A2'; nodes[2]['depends'][0]['node'] = 'A2'; nodes[2]['checks'][0]['spec'] = nodes[2]['checks'][0]['spec']
        nodes[0]['checks'][0]['id'] = 'check-A'                     # the check moves with the renamed node (no acceptance change)
        self.revise(nodes)
        cost = self.last_cost()
        self.assertEqual(sorted(cost['counted']), ['A2', 'I'])
        self.assertEqual(self.group()['used_calls'] + self.group()['reserved_calls'], used)

    def test_d_an_unknown_attempt_stays_in_the_accounting_and_blocks_the_revise(self):
        self.assertEqual(self.step()['node'], 'A'); self.verify('A')
        def lost(ledger, control, task, item, attempt):
            control.launched(attempt['id'], attempt['generation'], {'fixture': True})
            raise RuntimeError('provider connection lost after launch')
        self.assertEqual(self.step(lost)['state'], 'held')
        before = self.group()
        self.assertGreaterEqual(before['unknown_attempts'], 1)
        with self.assertRaisesRegex(LedgerError, 'Reconcile'):
            self.revise(self.changed('I', goal='Integrate A and B into one checked result'))
        self.assertEqual(self.group()['remaining_calls'], before['remaining_calls'])

    def test_e_stale_expected_revision_is_refused_as_before(self):
        self.run_units()
        current = self.ip.current(self.ledger, 'P1')['internal_revision']
        with self.assertRaisesRegex(LedgerError, 'Stale internal plan revision'):
            self.ip.revise(self.ledger, 'P1', self.changed('I', goal='Integrate A and B once more'), reason='late writer',
                           evidence=['a.txt:1'], expected_revision=current - 1)


if __name__ == '__main__':
    import unittest
    unittest.main()
