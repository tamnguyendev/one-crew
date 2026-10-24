"""T36a (W32b, R04) [E1], [E2], [E3], [E5], [E6], [E8] as one scenario on the fixture engine with a fake clock.

Three pieces of work in one internal plan: A (6 h) must be split into tasks under the 2 h cap; B needs a bounded read-only survey node
before any implementation (an estimate-blocking unknown resolved by the survey); C cannot be split and declares its reason and its own
finite cap. A task above the cap without a reason is refused ([E5]); B's implementation does not start before the survey is verified
([E2]/[E6]); three hours of waiting (fake clock) change neither the approved deadline nor the baseline ([E8]).
"""
import copy
import os

from onecrew.budget_core import group
from onecrew.ledger import LedgerError
from onecrew.v2 import estimates, exceptions, plan, runtime_unknowns
from tests.test_wf_engine import EngineFixture, node


def sized(nid, hours, **extra):
    item = node(nid, **extra)
    item['estimate_seconds'] = [int(hours * 3600 * 0.8), int(hours * 3600)]
    item['execution_cap_seconds'] = int(hours * 3600)
    return item


class ScenarioTests(EngineFixture):
    def setUp(self):
        from onecrew.control_core import Control, migrate
        from onecrew.snapshots import Snapshots
        from onecrew.v2 import engine, internal_plan
        from tests.test_v2_l1 import Fixture, plan_json
        Fixture.setUp(self)
        self.ip, self.engine = internal_plan, engine
        self.engine_caps = ['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine']
        value = plan_json(scope={'owned': ['a.txt', 'b.txt']}, budget={'max_calls': 100, 'time': 2880},        # a two-day root: the 2 h cap is the rule under test, not the deadline
                          authority={'edit': True, 'commands': True, 'edit_tests': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q9', 'Q12']})
        self.root_view = plan.propose(self.ledger, 'P1', value, 'codex', workflow=True, capabilities=self.engine_caps)
        plan.approve(self.ledger, 'P1', 'owner', 'fixture with estimate', estimate={'execution_seconds': [21600, 28800], 'evidence': ['fixture decomposition'],
                                                                                   'deadline': '2026-10-26T08:00:00+07:00'})
        os.environ['ONECREW_ACTOR'] = 'codex'
        self.store = Snapshots(self.ledger.state_root); migrate(self.ledger); self.control = Control(self.ledger)
        self.task = plan.show(self.ledger, 'P1')['anchor_task']

    def test_e5_e1_a_task_above_the_cap_is_refused_and_the_split_is_accepted(self):
        big = sized('A', 6)                                                                     # 6 h in one task, no reason
        with self.assertRaises(LedgerError) as refused:
            self.revise([big, node('I', ['A'], integration=True, write=())])
        self.assertIn('Split a task above two hours', str(refused.exception))                    # [E5]
        a1, a2 = sized('A1', 2), sized('A2', 2, write=('b.txt',)); a2['read'] = ['b.txt']; a2['depends'] = [{'node': 'A1', 'requires': 'verified'}]
        a3 = sized('A3', 2, write=()); a3['read'] = ['a.txt']; a3['depends'] = [{'node': 'A2', 'requires': 'verified'}]
        self.revise([a1, a2, a3, node('I', ['A1', 'A2', 'A3'], integration=True, write=())])
        definition = self.engine.state(self.ledger, 'P1')['definition']['nodes']
        self.assertTrue(all(n['execution_cap_seconds'] <= 7200 for n in definition if n['id'].startswith('A')))   # [E1]

    def test_e3_an_indivisible_task_needs_its_reason_and_own_finite_cap(self):
        c = sized('C', 5)
        with self.assertRaises(LedgerError):
            self.revise([c, node('I', ['C'], integration=True, write=())])
        c['indivisible'] = {'reason': 'one 5-hour database migration that cannot be checkpointed mid-way', 'cap_seconds': c['execution_cap_seconds']}
        self.revise([c, node('I', ['C'], integration=True, write=())])
        shown = next(n for n in self.engine.state(self.ledger, 'P1')['definition']['nodes'] if n['id'] == 'C')
        self.assertEqual(shown['indivisible']['cap_seconds'], 18000); self.assertIn('cannot be checkpointed', shown['indivisible']['reason'])   # [E3]
        bad = copy.deepcopy(c); bad['indivisible'] = {'reason': 'too long to split', 'cap_seconds': 18000}
        with self.assertRaises(LedgerError):
            self.revise([bad, node('I', ['C'], integration=True, write=())])                     # a reason that explains nothing is refused

    def test_e2_e6_b_waits_for_its_survey_and_e8_waiting_moves_no_deadline(self):
        survey = sized('B0', 1, write=()); survey['read'] = ['a.txt']
        impl = sized('B1', 2, write=('b.txt',)); impl['read'] = ['b.txt']; impl['depends'] = [{'node': 'B0', 'requires': 'verified'}]
        self.revise([survey, impl, node('I', ['B0', 'B1'], integration=True, write=())])
        runtime_unknowns.open_unknown(self.ledger, 'P1', 'b-format', question='Which input format does B consume?', affected=['B1'], required_by=['B1'],
                                      resolver='poc', evidence=['a.txt:1'], blocks_estimate=True, survey_node='B0')
        self.assertEqual([n['id'] for n in self.engine.ready(self.ledger, 'P1')], ['B0'])         # [E2] the survey first
        self.assertEqual(self.step()['node'], 'B0')
        self.assertEqual(self.engine.ready(self.ledger, 'P1'), [])                                # [E6] no implementation before the survey is verified and the unknown closed
        self.verify('B0')
        with self.assertRaises(LedgerError):
            runtime_unknowns.resolve(self.ledger, 'P1', 'b-format', by='poc', evidence='a.txt:1', answer='csv')   # the answer must cite the verified survey
        receipt = self.engine.state(self.ledger, 'P1')['nodes']['B0']['verification_receipt']
        with self.ledger.transaction() as conn:
            before = group(conn, self.task)['deadline']
        baseline = estimates.read(self.ledger, 'P1')['baseline']
        for hour in range(4):                                                                     # [E8] three hours of waiting for the owner
            exceptions.observe(self.ledger, 'P1', f'2026-10-25T{9 + hour:02d}:00:00+07:00')
        with self.ledger.transaction() as conn:
            self.assertEqual(group(conn, self.task)['deadline'], before)
        self.assertEqual(estimates.read(self.ledger, 'P1')['baseline'], baseline)
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'approved')
        runtime_unknowns.resolve(self.ledger, 'P1', 'b-format', by='poc', evidence=receipt, answer='csv, confirmed by the survey')
        self.assertEqual([n['id'] for n in self.engine.ready(self.ledger, 'P1')], ['B1'])          # only now
        kinds = self.kinds()
        self.assertLess(kinds.index('node.verification'), len(kinds))
        started = [p['node'] for k, p in self.events() if k == 'node.started']
        self.assertEqual(started, ['B0'])                                                          # [E6] no B1 start before the survey
