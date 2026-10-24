"""T07a [E14] (W18): the branch hold from pending requests reuses v1's admission rule (`admission_core.blocking`) with the v2 policy.

Engine fixture with the finding register. A pending U2 question that names node A (as the W32a outside-authority request does) holds A and
its dependents through the real `engine.ready`/`step` path and nothing else: B runs. A pending decision card (no scope) holds nothing.
Answering the U2 releases A. Counter-example (wrong wiring): the same rows under v1's default policy (`unscoped_blocks=True`) would hold B
too — that is why the shared function takes the policy explicitly; v1's own behaviour is unchanged (tests/test_branch_inbox stays green).
"""
import os

from onecrew import admission_core
from onecrew.control_core import Control, migrate
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, finding_scope, internal_plan, plan
from tests.test_v2_l1 import Fixture, plan_json
from tests.test_wf_engine import EngineFixture, node

U2 = {'schema_version': 1, 'question': 'Allow the write outside the scope for A?', 'reason': 'U2', 'impact': 'A waits; B goes on.',
      'options': [{'id': 'grant', 'label': 'Grant'}, {'id': 'skip', 'label': 'Skip'}], 'recommendation': 'skip',
      'action': {'type': 'authorize', 'parameters': {'class': 'U2', 'nodes': ['A'], 'still_running': ['B']}}}
CARD = {'schema_version': 1, 'question': 'Keep or delete the old export?', 'reason': 'Decision needed before approve.', 'impact': 'plan P1',
        'options': [{'id': 'keep', 'label': 'Keep'}, {'id': 'delete', 'label': 'Delete'}], 'recommendation': 'keep',
        'action': {'type': 'v2.decision_card', 'parameters': {'card': {'problem': 'x'}}}}


class RequestHoldTests(EngineFixture):
    def setUp(self):
        Fixture.setUp(self)
        self.engine, self.ip = engine, internal_plan
        caps = ['namespaced-storage', 'finding-register', 'root-budget', 'internal-plan', 'sequential-engine']
        raw = plan_json(scope={'owned': ['a.txt', 'b.txt']}, authority={'edit': True, 'commands': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q8', 'Q9', 'Q12']})
        self.root_view = plan.propose(self.ledger, 'P1', raw, 'codex', workflow=True, capabilities=caps)
        plan.approve(self.ledger, 'P1', 'owner', 'temporary fixture grant')
        self.store = Snapshots(self.ledger.state_root); migrate(self.ledger); self.control = Control(self.ledger)
        os.environ['ONECREW_ACTOR'] = 'codex'
        b = node('B', write=('b.txt',)); b['read'] = ['b.txt']
        d = node('D', ['A'], write=()); d['read'] = ['a.txt']
        self.revise([node('A'), b, d, node('I', ['A', 'B', 'D'], integration=True, write=())])
        self.task = self.root_view['anchor_task']

    def test_e14_a_scoped_request_holds_its_nodes_and_dependents_through_the_real_path_and_a_card_holds_nothing(self):
        request = self.ledger.create_request(self.task, 'u2-a', U2)
        view = self.engine.state(self.ledger, 'P1')
        self.assertEqual(view['request_blockers'], {'A': [request['id']], 'D': [request['id']], 'I': [request['id']]})   # scope + dependents
        self.assertEqual([n['id'] for n in self.engine.ready(self.ledger, 'P1')], ['B'])                                 # independent work goes on
        self.assertEqual(self.step()['node'], 'B'); self.verify('B')
        self.assertEqual(self.engine.ready(self.ledger, 'P1'), [])
        card = self.ledger.create_request(self.task, 'card-1', CARD)                                                     # a question for the owner, no scope
        self.assertEqual(set(self.engine.state(self.ledger, 'P1')['request_blockers']), {'A', 'D', 'I'})                 # the card holds nothing more
        self.ledger.reply(request['id'], request['revision'], 'skip', decided_by='entry')
        view = self.engine.state(self.ledger, 'P1')
        self.assertEqual(view['request_blockers'], {})
        self.assertEqual([n['id'] for n in self.engine.ready(self.ledger, 'P1')], ['A'])
        self.assertEqual(self.ledger.request(card['id'])['state'], 'pending')
        self.assertEqual(self.step()['node'], 'A')

    def test_wrong_wiring_v1_default_policy_would_hold_independent_work(self):
        self.ledger.create_request(self.task, 'card-1', CARD)
        self.ledger.create_request(self.task, 'u2-a', U2)
        with self.ledger.transaction() as conn:
            rows = admission_core.pending(conn, self.task)
            # the v1 rule as the v1 controller uses it: a global question stops every unit (test_branch_inbox proves this is still so)
            self.assertTrue(admission_core.blocks(conn, self.task, 'task:B'))
        self.assertTrue(admission_core.blocking(rows, 'task:B'), 'v1 default: the unscoped card holds B too')
        self.assertEqual(len(admission_core.blocking(rows, 'task:B', scoped_types=finding_scope.V2_SCOPED_TYPES, unscoped_blocks=False)), 0)
        self.assertEqual(len(admission_core.blocking(rows, 'task:A', scoped_types=finding_scope.V2_SCOPED_TYPES, unscoped_blocks=False)), 1)
        self.assertEqual([n['id'] for n in self.engine.ready(self.ledger, 'P1')], ['B'])
