"""W30c: a typed owner stop has effects, preserving old-root semantics."""
from onecrew.ledger import LedgerError
from onecrew.v2 import answer_effects, namespaces, outcome, plan, questions, report, verdict
from tests.test_v2_l1 import Fixture, plan_json, milestone, BAD
from tests.test_wf_engine import EngineFixture, node
from unittest.mock import patch
import os


class AnswerEffectTests(Fixture):
    def test_actual_old_root_remains_stopped_and_readable_by_old_cli(self):
        import json
        from pathlib import Path
        from tests import wf_oldversion as ov
        old = ov.OldVersion(ov.archive('d3120c6', Path(__file__).resolve().parents[1], self.temp.name))
        raw = plan_json(milestones=[milestone(argv=BAD, max_repairs=0)])
        file = Path(self.temp.name) / 'legacy.json'; file.write_text(json.dumps(raw))
        code, output = old.run(self.root, self.ledger.state_root, 'plan', 'propose', 'Legacy', '--file', str(file), '--author', 'codex')
        self.assertEqual(code, 0, output)
        plan.approve(self.ledger, 'plan:Legacy', 'owner', 'fixture')
        verdict.run(self.ledger, 'plan:Legacy', 'M1')
        req = questions.list_for_plan(self.ledger, 'plan:Legacy', pending=True)[0]
        questions.answer(self.ledger, req['id'], req['revision'], 'stop', 'legacy answer')
        self.assertEqual(old.status_of(self.root, self.ledger.state_root, 'Legacy')['status'], 'stopped_with_report')
        with self.ledger.transaction() as conn:
            task = plan.derive(self.ledger, conn, 'plan:Legacy')['task_id']
            self.assertEqual(conn.execute("SELECT count(*) FROM events WHERE task_id=? AND kind IN ('request.applied','plan.closed')", (task,)).fetchone()[0], 0)

    def stopped(self, workflow=True):
        raw = plan_json(milestones=[milestone(argv=BAD, max_repairs=0)])
        plan.propose(self.ledger, 'P1', raw, 'codex', workflow=workflow,
                     capabilities=list(namespaces.CAPABILITIES) if workflow else None)
        plan.approve(self.ledger, 'P1', 'owner', 'fixture')
        verdict.run(self.ledger, 'P1', 'M1')
        return self.ledger.requests(plan.show(self.ledger, 'P1')['anchor_task'], pending=True)[0]

    def test_stop_closes_once_and_prevents_further_work_without_accepting(self):
        req = self.stopped()
        questions.answer(self.ledger, req['id'], req['revision'], 'stop', 'Do not spend more on this job.')
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'closed')
        self.assertEqual(self.kinds().count('plan.closed'), 1)
        self.assertEqual(self.kinds().count('request.applied'), 1)
        self.assertNotIn('plan.accepted', self.kinds())
        self.assertEqual(questions.list_for_plan(self.ledger, 'P1', pending=True), [])
        self.assertIn('ĐÃ ĐÓNG', report.render_present(self.ledger.state_root, 'P1'))
        self.assertIn('Do not spend more', report.render_present(self.ledger.state_root, 'P1'))
        self.assertEqual(outcome.ending(self.ledger, 'P1')['phase'], 'cancelled')
        with self.assertRaises(LedgerError): verdict.run(self.ledger, 'P1', 'M1')
        with self.assertRaises(LedgerError): plan.approve(self.ledger, 'P1', 'owner', 'cannot resurrect')
        questions.answer(self.ledger, req['id'], req['revision'], 'stop', 'same reply')
        self.assertEqual(self.kinds().count('plan.closed'), 1)

    def test_default_schema_two_records_answer_but_keeps_old_stop_semantics(self):
        req = self.stopped(workflow=False)
        questions.answer(self.ledger, req['id'], req['revision'], 'stop', 'stop')
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'stopped_with_report')
        self.assertNotIn('request.applied', self.kinds())

    def test_amend_answer_does_not_bypass_revision_approval_or_limits(self):
        req = self.stopped()
        questions.answer(self.ledger, req['id'], req['revision'], 'amend_plan', 'Revise the requirement.')
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'stopped_with_report')
        self.assertEqual(self.kinds().count('request.applied'), 1)
        with self.assertRaises(LedgerError): verdict.run(self.ledger, 'P1', 'M1')

    def test_recorded_but_unapplied_reply_reconciles_without_answering_again(self):
        req = self.stopped()
        self.ledger.reply(req['id'], req['revision'], 'stop', source='owner-terminal',
                          reference='stop after crash', decided_by='user', by='user')
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'stopped_with_report')
        applied = answer_effects.apply(self.ledger, req['id'])
        self.assertTrue(applied['applied'])
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'closed')
        self.assertEqual(self.kinds().count('request.answered'), 1)

    def test_unattributed_answer_never_changes_root_state(self):
        req = self.stopped()
        self.ledger.reply(req['id'], req['revision'], 'stop', source='worker')
        with self.assertRaises(LedgerError): answer_effects.apply(self.ledger, req['id'])
        self.assertNotIn('plan.closed', self.kinds())


class WorkflowAnswerTests(EngineFixture):
    def test_root_command_pass_cannot_bypass_internal_delivery_handoff(self):
        verdict.run(self.ledger,'P1','M1')
        artifact=verdict.artifact(self.ledger,'P1')['artifact_sha']
        with patch.dict(os.environ, {'ONECREW_ACTOR': ''}), self.assertRaisesRegex(LedgerError, 'handoff'):
            plan.accept(self.ledger,'P1','owner','fixture cannot bypass workflow',artifact)
        self.assertNotIn('plan.accepted',self.kinds())

    def hold(self):
        self.revise([node('A'), node('B', write=('b.txt',)), node('I', ['A', 'B'], integration=True, write=())])
        self.engine.request_action(self.ledger, 'P1', 'A', {'kind': 'write', 'paths': ['outside.txt']})
        return questions.list_for_plan(self.ledger, 'P1', pending=True)[0]

    def reply(self, request, choice):
        with patch.dict(os.environ, {'ONECREW_ACTOR': ''}):
            return questions.answer(self.ledger, request['id'], request['revision'], choice, 'owner decision fixture')

    def test_continue_resumes_exact_held_generations_inside_original_grant_once(self):
        request = self.hold()
        before = self.engine.state(self.ledger, 'P1')
        result = self.reply(request, 'continue')['controller_effect']
        after = self.engine.state(self.ledger, 'P1')
        self.assertEqual(result['effect'], 'continued_within_grant')
        self.assertFalse(result['grants_authority'])
        for nid in ('A', 'I'):
            self.assertEqual(after['nodes'][nid]['generation'], before['nodes'][nid]['generation'] + 1)
            self.assertEqual(after['nodes'][nid]['phase'], 'pending')
        self.assertEqual(after['nodes']['B'], before['nodes']['B'])
        self.reply(request, 'continue')
        self.assertEqual(self.engine.state(self.ledger, 'P1'), after)
        self.assertEqual(self.step()['node'], 'A')
        self.assertFalse((self.root / 'outside.txt').exists())

    def test_stop_closes_root_and_keeps_held_work_unaccepted(self):
        request = self.hold()
        self.reply(request, 'stop')
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'closed')
        self.assertEqual(self.engine.ready(self.ledger, 'P1'), [])
        self.assertNotIn('plan.accepted', self.kinds())

    def test_stale_internal_revision_does_not_resume_new_plan(self):
        request = self.hold()
        self.revise([node('A'), node('B', write=('b.txt',)), node('C'), node('I', ['A', 'B', 'C'], integration=True, write=())])
        before = self.engine.state(self.ledger, 'P1')
        self.reply(request, 'continue')
        self.assertEqual(self.engine.state(self.ledger, 'P1'), before)
        self.assertNotIn('request.applied', self.kinds())

    def test_unknown_attempt_cannot_be_reset_by_continue_answer(self):
        self.hold()
        self.reply(questions.list_for_plan(self.ledger, 'P1', pending=True)[0], 'continue')
        self.step(lambda ledger, control, task, item, attempt: {'artifact': self.store.blob(b'unknown'), 'receipt': self.store.blob(b'unknown receipt')})
        self.engine.request_action(self.ledger, 'P1', 'A', {'kind': 'write', 'paths': ['outside.txt']})
        request = questions.list_for_plan(self.ledger, 'P1', pending=True)[0]
        before = self.engine.state(self.ledger, 'P1')
        with self.assertRaisesRegex(LedgerError, 'unknown attempt'):
            self.reply(request, 'continue')
        self.assertEqual(self.engine.state(self.ledger, 'P1'), before)
        self.assertTrue(before['inflight'])
