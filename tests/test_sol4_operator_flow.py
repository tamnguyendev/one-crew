"""F2/F5/F8: C7/C14/C15 operator paths on temporary real ledgers."""
import contextlib
import copy
import io
import json
import os
import sys
from unittest.mock import patch

from onecrew.v2 import active_plan, cli, engine, findings, internal_plan, notification_cli, plan, report, tracking, verdict
from onecrew.common_handoff import handoff
from onecrew.common_verification import CandidateChecker
from tests.test_v2_l1 import Fixture, milestone, plan_json
from tests.test_review_b2_e2e import LoopFixture, GRANT
from tests.test_wf_engine import node
from tests.test_wf_managed_executor import ManagedFixture


class EnforcePreflightTests(Fixture):
    def call(self, name, mode='enforce', human=True):
        output = io.StringIO()
        args = ['--project', str(self.root), '--state-root', str(self.ledger.state_root),
                'owner', 'enforce', name, '--mode', mode]
        with contextlib.redirect_stdout(output): code = cli.main(args + (['--human'] if human else []))
        return code, output.getvalue()

    def test_c15_missing_or_unapproved_plan_never_changes_policy_in_either_output_mode(self):
        self.propose()
        for name, mode, human in [('P1', 'enforce', True), ('NOPE', 'log', True), ('P1', 'log', False)]:
            before = active_plan.policy(self.ledger)
            code, out = self.call(name, mode, human)
            self.assertNotEqual(code, 0, out)
            self.assertEqual(active_plan.policy(self.ledger), before)
            if human:
                self.assertIn('Chưa đổi chế độ', out)
                self.assertNotIn('Chưa xác nhận được kết quả', out)

    def test_partial_export_error_reports_committed_mode_and_keeps_owner_guard(self):
        self.approved()
        with patch('onecrew.v2.active_plan.export', side_effect=OSError('fixture export fault')):
            code, out = self.call('P1')
        self.assertEqual(code, 2, out)
        self.assertIn('đã ghi', out)
        self.assertIn('enforce', out)
        self.assertNotIn('plan changed before export', out)
        self.assertEqual(active_plan.policy(self.ledger)['mode'], 'enforce')
        with patch.dict(os.environ, {'CLAUDE_CODE_CHILD_SESSION': '1'}):
            code, out = self.call('P1', 'log')
        self.assertEqual(code, 2)
        self.assertEqual(active_plan.policy(self.ledger)['mode'], 'enforce')


class EngineOperatorFlowTests(LoopFixture):
    paths = ('a.txt',)
    bad = {'a.txt': b'candidate\n'}
    milestones = (milestone('M1', argv=[sys.executable, '-c', 'from pathlib import Path;print("checked");assert Path("a.txt").read_text()=="candidate\\n"']),)
    def prepare(self): pass

    def test_c7_next_action_reaches_handoff_verdict_and_owner_acceptance(self):
        checker = CandidateChecker(self.ledger, 'P1')
        self.step()
        need = self.step()
        self.assertEqual(need['next_action']['kind'], 'verify_node', need)
        self.verify('C', checker)
        self.step(); self.verify('I', checker)
        need = self.step()
        self.assertEqual(need['state'], 'handoff_ready', need)
        self.assertEqual(need['next_action']['kind'], 'handoff')
        detail = tracking.detail(self.ledger.state_root, 'P1')
        self.assertIn('handoff', detail['status']['reason'])
        self.assertNotIn('Chờ bộ thực thi kiểm mốc', detail['status']['reason'])
        digest = report.render_digest(self.ledger.state_root)
        self.assertIn('bước tiếp theo (bộ thực thi)', digest)
        self.assertIn('handoff', digest)
        handoff(self.ledger, 'P1')
        need = self.step()
        self.assertEqual(need['next_action']['kind'], 'verify_milestone', need)
        verdict.run(self.ledger, 'P1', 'M1')
        need = self.step()
        self.assertEqual(need['state'], 'awaiting_acceptance', need)
        self.assertTrue(need['next_action']['owner_only'])
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'approved')
        self.assertIn(str(self.root), need['next_action']['command'])
        self.assertIn(str(self.ledger.state_root), need['next_action']['command'])
        with patch.dict(os.environ):
            os.environ.pop('ONECREW_ACTOR', None)
            plan.accept(self.ledger, 'P1', 'owner', 'isolated operator fixture', verdict.artifact(self.ledger, 'P1')['artifact_sha'])
        self.assertEqual(self.step()['state'], 'accepted')

    def test_missing_apply_grant_is_explained_without_granting_it(self):
        value = plan_json(scope={'owned': ['a.txt']}, authority={**GRANT, 'apply_to_project': False})
        plan.propose(self.ledger, 'NoApply', value, 'codex', workflow=True,
                     capabilities=['namespaced-storage', 'finding-register', 'root-budget', 'internal-plan', 'sequential-engine'])
        with patch.dict(os.environ):
            os.environ.pop('ONECREW_ACTOR', None)
            plan.approve(self.ledger, 'NoApply', 'owner', 'isolated missing grant fixture')
        internal_plan.revise(self.ledger, 'NoApply', [node('C'), node('I', ['C'], integration=True, write=())], reason='fixture', evidence=['a.txt:1'])
        action = engine.next_action(self.ledger, 'NoApply')
        self.assertIn('apply_to_project', action['delivery_limit'])
        self.assertFalse(plan.show(self.ledger, 'NoApply')['contract']['authority']['apply_to_project'])

    def test_guidance_reads_without_effect_and_cannot_extend_exhausted_root(self):
        before = self.events()
        with patch.object(engine.ip, 'ceilings', return_value={'remaining_seconds': 0, 'remaining_calls': 0}):
            need = engine.next_action(self.ledger, 'P1')
        self.assertEqual(need['kind'], 'owner_decision')
        self.assertTrue(need['owner_only'])
        self.assertEqual(self.events(), before)


class TimeoutOperatorTests(ManagedFixture):
    def test_c14_timeout_has_reason_recovery_and_one_durable_notification(self):
        self.delay = 10
        nodes = self.ip.current(self.ledger, 'P1')['definition']['nodes']
        nodes[0]['execution_cap_seconds'] = 4; nodes[0]['estimate_seconds'] = [.1, .5]
        self.revise(nodes)
        initial = notification_cli.pull(self.ledger, 'timeout-fixture', from_now=True)
        notification_cli.ack(self.ledger, 'timeout-fixture', initial['id'])  # empty fixture batch; no attention/answer is claimed
        with patch('onecrew.v2.notification_cli.best_effort', return_value={'enabled': False}) as publish:
            result = engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual(result['state'], 'held', result)
        self.assertIn('execution', result['reason'].lower())
        self.assertEqual(result['next_action']['kind'], 'revise_node', result)
        with patch.object(engine.ip, 'ceilings', return_value={'remaining_seconds': 120, 'remaining_calls': 0}):
            need = engine.next_action(self.ledger, 'P1')
        self.assertEqual(need['kind'], 'owner_decision')
        self.assertTrue(need['owner_only'])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'engine', 'diagnose', 'P1', 'C'])
        self.assertEqual(code, 0, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['kind'], 'revise_node')
        batch = notification_cli.pull(self.ledger, 'timeout-fixture')
        notices = [n for n in batch['notifications'] if n['status'] == 'execution']
        self.assertEqual(len(notices), 1, batch)
        self.assertIn('revise', notices[0]['user_action'])
        self.assertFalse(notices[0]['user_attention_verified'])
        self.assertEqual(publish.call_count, 1)
        engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual(len(self.launches), 1)
        notices = [p for k, p in self.events() if k == 'notice.exception' and p['category'] == 'execution']
        self.assertEqual(len(notices), 1)
        nodes = self.ip.current(self.ledger, 'P1')['definition']['nodes']
        nodes[0]['execution_cap_seconds'] = 30
        self.revise(nodes)
        refreshed = notification_cli.pull(self.ledger, 'timeout-fixture')
        self.assertEqual([n for n in refreshed['notifications'] if n['status'] == 'execution'], [])
