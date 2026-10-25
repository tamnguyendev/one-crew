"""Audit W02 (T17a): a workflow root without an authority field is judged at the gate by effective(), as decide() is.

Kept apart from tests/test_wf_r04a_authority.py, whose bytes are pinned by wfkit/development-manifest.json.
"""
import unittest

from onecrew import solution_gate
from onecrew.ledger import LedgerError
from onecrew.owned_intake import submit
from onecrew.v2 import authority, gate, plan as plans

from tests.test_v2_l1 import Fixture, plan_json


class WorkflowRootWithoutAuthorityTests(Fixture):
    """Audit W02 (T17a): a workflow root approved without an `authority` field grants only what effective() says (edit inside
    scope.owned, no bool grants); the gate must judge a bound child by that same grant, as decide() does."""

    def setUp(self):
        super().setUp()
        plans.propose(self.ledger, 'W', plan_json(scope={'owned': ['a.txt']}), 'codex', workflow=True,
                      capabilities=['namespaced-storage', 'root-budget'])
        plans.approve(self.ledger, 'W', 'owner', 'fixture workflow root without authority')
        gate.set_enforced(self.ledger, True, 'owner', 'test')

    def child(self, key, child_authority, paths):
        contract = {'schema_version': 1, 'goal': 'A work job', 'acceptance': ['done'], 'preserve': ['everything'], 'authority': child_authority,
                    'scope': {'repository': '', 'paths': list(paths)}, 'authorized_by': {'source': 'user', 'reference': 'test'}}
        return submit(self.ledger, None, key, mode='work', provider='kiro', model='claude-sonnet-5', contract=contract,
                      plan_selector='plan-ns:W')['id']

    def test_w02_bound_child_outside_effective_grant_is_refused_like_decide(self):
        with self.ledger.transaction() as conn:
            contract = plans.load(self.ledger, plans.derive(self.ledger, conn, 'W'))[0]
        self.assertNotIn('authority', contract)
        self.assertEqual(authority.decide(contract, {'kind': 'write', 'paths': ['secret']})['class'], 'U2')
        self.assertEqual(authority.decide(contract, {'kind': 'unconfined_command'})['class'], 'U2')
        task = self.child('outside', {'edit': True, 'commands': True, 'unconfined_commands': True, 'apply_to_project': True}, ['secret'])
        with self.assertRaises(LedgerError) as caught:
            solution_gate.check(self.ledger, task)
        text = str(caught.exception)
        for expect in ('exceeds the authority', 'outside the owned scope', 'unconfined_commands', 'apply_to_project', 'commands'):
            self.assertIn(expect, text)

    def test_w02_bound_child_inside_scope_owned_is_still_admitted(self):
        self.assertTrue(authority.decide(plans.load(self.ledger, self.ledger_state())[0], {'kind': 'write', 'paths': ['a.txt']})['in_authority'])
        self.assertIsNone(solution_gate.check(self.ledger, self.child('inside', {'edit': True}, ['a.txt'])))

    def ledger_state(self):
        with self.ledger.transaction() as conn:
            return plans.derive(self.ledger, conn, 'W')


if __name__ == '__main__':
    unittest.main()
