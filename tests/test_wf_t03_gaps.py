"""T03 [E1]/[E7] gaps (R04 W04/W10): splitting a task keeps every approved acceptance item, and the mapping is recorded.

Fixture: the EngineFixture of tests/test_wf_engine (real temporary ledger, Git, internal-plan root) with a contract of TWO outputs
(A_T = {O1, O2}). Revision 1 has one work node T covering O1+O2 (+ the mandatory integration node I); revision 2 splits T into T1 (O1)
and T2 (O2). [E1]: the plan.revised of the split names a definition whose acceptance map sends every item of A_T to at least one node
and every node's acceptance back to an item of A_T, and its acceptance_diff records no removed result. [E7]: the counter-example
split (T1 and T2 both O1, O2 dropped) is refused as U1, publishes nothing and asks nobody.
"""
import copy
import json
import os

from onecrew.control import Control, migrate
from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import acceptance_diff, plan as plans
from tests.test_v2_l1 import plan_json, milestone
from tests.test_wf_engine import EngineFixture, node


def work(nid, acceptance, write=('a.txt',)):
    item = node(nid, write=write); item['acceptance'] = list(acceptance)
    item['goal'] = 'Produce evidence for ' + '+'.join(acceptance); item['output'] = ['Evidence for ' + o for o in acceptance]
    return item


def integration(upstream):
    item = node('I', upstream, integration=True, write=()); item['acceptance'] = ['O1', 'O2']
    return item


class SplitKeepsAcceptance(EngineFixture):
    def setUp(self):
        # EngineFixture.setUp with a two-output contract (same steps, different contract).
        super(EngineFixture, self).setUp()
        from onecrew.v2 import internal_plan, engine
        self.ip, self.engine = internal_plan, engine
        value = plan_json(milestones=[milestone(covers=['O1', 'O2'])], scope={'owned': ['a.txt', 'b.txt']}, authority={
            'edit': True, 'commands': True, 'edit_tests': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q9', 'Q12']})
        value['output'] = ['The sample exists', 'The second result exists']
        self.root_view = plans.propose(self.ledger, 'P1', value, 'codex', workflow=True,
                                       capabilities=['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine'])
        plans.approve(self.ledger, 'P1', 'owner', 'fixture engine approval')
        os.environ['ONECREW_ACTOR'] = 'codex'
        self.store = Snapshots(self.ledger.state_root)
        migrate(self.ledger); self.control = Control(self.ledger)
        self.revise([work('T', ['O1', 'O2']), integration(['T'])])

    def revised(self):
        return [p for k, p in self.events() if k == 'plan.revised']

    def test_e1_split_records_old_to_new_acceptance_mapping_in_plan_revised(self):
        split = [work('T1', ['O1']), work('T2', ['O2'], write=('b.txt',)), integration(['T1', 'T2'])]
        self.revise(split, reason='Split T into T1 and T2 inside the approved scope')
        events = self.revised()
        self.assertEqual(len(events), 2)                                                 # one plan.revised per split
        old = json.loads(self.store.read_blob(events[0]['definition']))
        new = json.loads(self.store.read_blob(events[1]['definition']))
        a_t = {'O1', 'O2'}
        self.assertEqual(set(old['acceptance']), a_t); self.assertEqual(set(new['acceptance']), a_t)
        self.assertEqual(new['acceptance'], {'O1': ['T1', 'I'], 'O2': ['T2', 'I']})       # every item of A_T -> >=1 node of the split
        work_nodes = [n for n in new['nodes'] if not n['integration']]
        self.assertEqual({o for n in work_nodes for o in n['acceptance']}, a_t)          # union of T1, T2 == A_T, nothing lost
        for n in new['nodes']:
            self.assertTrue(n['acceptance']); self.assertLessEqual(set(n['acceptance']), a_t)   # every node item -> an item of A_T
        self.assertEqual([oid for oid, ids in new['acceptance'].items() if not [i for i in ids if i != 'I']], [])   # [E7] unmapped list empty
        diff = events[1]['acceptance_diff']
        self.assertEqual(diff['classification'], 'routine')
        self.assertFalse([c for c in diff['changes'] if c['kind'] == 'removed_result'])
        self.assertEqual(self.ledger.requests(self.root_view['anchor_task']), [])        # T03 [E8]

    def test_e7_split_that_drops_an_item_is_refused_as_u1_and_publishes_nothing(self):
        before = self.ip.current(self.ledger, 'P1')['internal_revision']
        lossy = [work('T1', ['O1']), work('T2', ['O1'], write=('b.txt',)), integration(['T1', 'T2'])]
        lossy[-1]['acceptance'] = ['O1']                                                 # O2 is in no task any more
        with self.assertRaisesRegex(LedgerError, 'U1'):
            self.revise(lossy, reason='Split that loses O2')
        self.assertEqual(self.ip.current(self.ledger, 'P1')['internal_revision'], before)
        self.assertEqual(len(self.revised()), 1)
        self.assertEqual(self.ledger.requests(self.root_view['anchor_task']), [])
        # the classifier names the lost item (the reason the gate refuses)
        old = self.ip.current(self.ledger, 'P1')['definition']['nodes']
        diff = acceptance_diff.classify_nodes(old, lossy, ['O1', 'O2'])
        self.assertEqual(diff['classification'], 'U1')
        self.assertIn(('acceptance:O2', 'removed_result'), [(c['path'], c['kind']) for c in diff['changes']])

    def test_e7_counter_example_the_lossless_variant_of_the_same_split_is_accepted(self):
        """Same split shape with O2 kept: accepted. Shows the refusal above is caused by the lost item, not by the shape."""
        kept = [work('T1', ['O1']), work('T2', ['O1', 'O2'], write=('b.txt',)), integration(['T1', 'T2'])]
        shown = self.revise(kept, reason='Split that keeps O2')
        self.assertEqual(shown['internal_revision'], 2)
