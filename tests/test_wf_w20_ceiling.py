"""T18a (W20) [E1], [E3], [E6], [E8]: the bounded recovery loop stops at the root ceiling with a blocker event, and its rule is recovery_core.decide.

Fixture: tests.test_wf_engine.EngineFixture (real temporary ledger, real Control); the worker always "repairs" wrongly (node A's check stays red).
[E3] run to the cap: with a root budget of 2 calls, A passes and I stays red with both calls spent; the decision on I is a
     `workflow.recovery_decided` blocker whose spent == ceiling (2/2), a further repair is refused and nothing is spent past the cap; on a fake clock past the root deadline the same blocker kind carries the deadline.
[E6] the sealed ceilings (max_calls, deadline) in the ledger are equal before and after.
[E1] the diagnose decision and the replan events carry their authority basis (the approval, the contract, the sealed root budget).
[E8] every repair round calls recovery_core.decide at least once (call counter); a parallel rewritten rule that does not call it turns the
     integration check red.
"""
import copy
import datetime as dt
import os
from types import SimpleNamespace
from unittest.mock import patch

from onecrew import budget_core, recovery_core
from onecrew.control_core import Control, migrate
from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import plan as plans, recovery_policy, repair_tasks, report
from tests.test_v2_l1 import Fixture, plan_json
from tests.test_wf_engine import EngineFixture, node


class _Loop:
    def red_round(self):
        self.step()
        def checker(item, artifact):
            result = self.checker(item, artifact)
            for row in result['checks']: row['result'] = 'fail'
            return result
        self.verify('A', checker)

    def group(self):
        with self.ledger.transaction() as conn:
            return budget_core.group(conn, self.root_view['anchor_task'])

    def decisions(self):
        return [p for k, p in self.events() if k == 'workflow.recovery_decided']


class CeilingTests(_Loop, EngineFixture):
    def setUp(self):
        Fixture.setUp(self)                                   # EngineFixture's setup with a 2-call root budget
        from onecrew.v2 import internal_plan, engine
        self.ip, self.engine = internal_plan, engine
        self.engine_caps = ['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine']
        value = plan_json(scope={'owned': ['a.txt', 'b.txt']}, budget={'max_calls': 2, 'time': 120}, authority={
            'edit': True, 'commands': True, 'edit_tests': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q9', 'Q12']})
        self.root_view = plans.propose(self.ledger, 'P1', value, 'codex', workflow=True, capabilities=self.engine_caps)
        plans.approve(self.ledger, 'P1', 'owner', 'fixture engine approval')
        actor = patch.dict(os.environ, ONECREW_ACTOR='codex'); actor.start(); self.addCleanup(actor.stop)
        self.store = Snapshots(self.ledger.state_root)
        migrate(self.ledger)
        self.control = Control(self.ledger)
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])

    def test_e3_e6_run_to_the_call_cap_records_a_blocker_with_spent_equal_to_the_ceiling(self):
        before = self.group()
        ceilings = (before['max_calls'], before['deadline'])
        def red(item, artifact):
            result = self.checker(item, artifact)
            for row in result['checks']: row['result'] = 'fail'
            return result
        for _ in range(10):                                                     # run to the cap: A passes, then I stays red
            ran = self.step()
            if ran.get('state') == 'waiting': break
            self.verify(ran['node'], red if ran['node'] == 'I' else None)
            if ran['node'] == 'I': break
        self.assertEqual(self.group()['used_calls'], 2)
        decision = recovery_policy.assess(self.ledger, 'P1', 'I')
        self.assertEqual(decision['disposition'], 'blocked')                    # was 'repair', then prepare raised a bare LedgerError (U2 ceiling)
        stop = decision['stop']                                                 # [E3] the budget stop is the blocker event
        self.assertEqual((stop['ceiling'], stop['limit'], stop['spent']), ('calls', 2, 2))
        self.assertEqual(decision['diagnosis']['spent']['used_calls'], decision['diagnosis']['spent']['max_calls'])
        self.assertEqual(decision['diagnosis']['failed_checks'], ['check-I'])
        self.assertEqual(decision['action'], 'ask')                             # decided by recovery_core.decide (class budget)
        self.assertEqual(decision['record']['class'], 'budget')
        self.assertEqual(decision['authority_basis']['budget']['authority'], 'approved-plan-root')
        self.assertFalse(decision['resets_budget']); self.assertFalse(decision['creates_owner_request'])
        with self.assertRaisesRegex(LedgerError, 'blocked'): recovery_policy.authorize_repair(self.ledger, 'P1', 'I')
        with self.assertRaisesRegex(LedgerError, 'blocked'):
            repair_tasks.prepare(self.ledger, 'P1', 'A', 'I', reason='One more repair.', evidence=[decision['source_receipt']])
        after = self.group()
        self.assertEqual(after['used_calls'], 2)                                # spent == ceiling, never over
        self.assertEqual((after['max_calls'], after['deadline']), ceilings)     # [E6]
        text = report.render_report(self.ledger.state_root, 'P1', project_id=self.ledger.project_id)
        self.assertIn('Blocker node I', text); self.assertIn('2/2 lời gọi', text)
        self.assertEqual(self.ledger.requests(self.root_view['anchor_task']), [])

    def test_e3_e6_deadline_reached_on_a_fake_clock_is_the_same_blocker_kind(self):
        self.red_round()
        first = recovery_policy.assess(self.ledger, 'P1', 'A')
        self.assertEqual(first['disposition'], 'repair')
        before = self.group()
        deadline = dt.datetime.fromisoformat(before['deadline'])
        early = (deadline - dt.timedelta(minutes=1)).isoformat()
        late = (deadline + dt.timedelta(seconds=1)).isoformat()
        self.assertIsNone(recovery_policy.stop_at_ceiling(self.ledger, 'P1', 'A', now=early))
        stopped = recovery_policy.stop_at_ceiling(self.ledger, 'P1', 'A', now=late)
        self.assertEqual(stopped['disposition'], 'blocked')
        self.assertEqual((stopped['stop']['ceiling'], stopped['stop']['limit'], stopped['stop']['spent']),
                         ('deadline', before['deadline'], before['deadline']))
        self.assertEqual(stopped['diagnosis']['failed_checks'], ['check-A'])
        self.assertEqual(recovery_policy.stop_at_ceiling(self.ledger, 'P1', 'A', now=late)['event'], stopped['event'])   # once
        with self.assertRaisesRegex(LedgerError, 'blocked'):
            recovery_policy.authorize_repair(self.ledger, 'P1', 'A', now=late)
        self.assertEqual(len(self.decisions()), 2)
        after = self.group()
        self.assertEqual((after['max_calls'], after['deadline']), (before['max_calls'], before['deadline']))   # [E6]
        text = report.render_report(self.ledger.state_root, 'P1', project_id=self.ledger.project_id)
        self.assertIn('Blocker node A', text)
        self.assertEqual(self.ledger.requests(self.root_view['anchor_task']), [])


class BasisAndRuleTests(_Loop, EngineFixture):
    def setUp(self):
        super().setUp()
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])

    def test_e1_diagnose_and_replan_events_carry_the_authority_basis(self):
        self.red_round(); first = recovery_policy.assess(self.ledger, 'P1', 'A')
        repair_tasks.prepare(self.ledger, 'P1', 'A', 'A', reason='First bounded repair.', evidence=[first['source_receipt']])
        self.red_round(); second = recovery_policy.assess(self.ledger, 'P1', 'A')
        self.assertEqual(second['disposition'], 'diagnose')
        basis = second['authority_basis']
        approved = plans.show(self.ledger, 'P1')
        self.assertEqual(basis['approval']['sha'], approved['sha'])
        self.assertEqual(basis['contract_sha'], second['contract_sha'])
        self.assertEqual(basis['budget']['authority'], 'approved-plan-root')
        self.assertFalse(basis['grants_authority'])
        definition = copy.deepcopy(self.ip.current(self.ledger, 'P1')['definition']['nodes'])
        definition[0]['goal'] = 'Investigate a different supported cause using the retained failing test.'
        recovery_policy.replan(self.ledger, 'P1', 'A', definition, reason='Different diagnosis.', evidence=[second['source_receipt']])
        replans = [p for k, p in self.events() if k == 'workflow.recovery_replanned']
        self.assertEqual([p['state'] for p in replans], ['reserved', 'published'])
        self.assertTrue(all(p['authority_basis'] == basis for p in replans))

    def rounds(self, decide_counter):
        """Two repair rounds; the number of recovery_core.decide calls in each."""
        counts = []
        self.red_round(); recovery_policy.assess(self.ledger, 'P1', 'A'); counts.append(decide_counter.call_count)
        receipt = self.decisions()[-1]['source_receipt']
        repair_tasks.prepare(self.ledger, 'P1', 'A', 'A', reason='Bounded repair.', evidence=[receipt])
        self.red_round(); recovery_policy.assess(self.ledger, 'P1', 'A'); counts.append(decide_counter.call_count - counts[0])
        return counts

    def test_e8_every_round_goes_through_recovery_core_decide(self):
        with patch.object(recovery_core, 'decide', wraps=recovery_core.decide) as counter:
            counts = self.rounds(counter)
        self.assertTrue(all(c >= 1 for c in counts), counts)

    def test_e8_counterexample_a_parallel_rule_turns_the_check_red(self):
        def parallel(d, node_id, cls, key, detail, now=None, policy=None):          # rewritten stop rule, never calls decide
            return 'repair', {'signature': 'parallel', 'count': 1, 'progress': None}
        with patch.object(recovery_core, 'decide', wraps=recovery_core.decide) as counter, \
             patch.object(recovery_policy, 'recovery_core', SimpleNamespace(decide=parallel, POLICY_VERSION=1)):
            counts = self.rounds(counter)
        self.assertFalse(all(c >= 1 for c in counts), counts)                         # the integration check is red
