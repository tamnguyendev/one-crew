"""T47a (W30b) [E1], [E3], [E7], [E11]: the owner's answer has exactly its effect, and the pages say what was chosen.

Stopped plan (max_repairs 0, tests/test_wf_answer_effects.stopped): (a) the read command prints the question's card fields and works in an
AI session; (c) `amend_plan` closes the request, the plan waits for a new approved revision, the contract hash is unchanged and `verdict run`
is refused until the amendment is approved; (b) `stop` is shown as "đã chọn dừng" with the reference on `plan present` and in the report.
"""
import contextlib
import io
import json
import os

from onecrew.ledger import LedgerError
from onecrew.v2 import plan, questions, report, verdict
from tests.test_v2_l1 import plan_json, milestone, BAD
from tests.test_wf_answer_effects import AnswerEffectTests


class AnswerPagesTests(AnswerEffectTests):
    def show_cli(self, request_id):
        out = io.StringIO()
        env = dict(os.environ)
        os.environ['CLAUDE_CODE_CHILD_SESSION'] = '1'                                        # an AI session may read the card
        try:
            with contextlib.redirect_stdout(out):
                code = questions.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'question', 'show', request_id])
        finally:
            os.environ.clear(); os.environ.update(env)
        return code, json.loads(out.getvalue())

    def test_e1_the_read_command_prints_the_card_fields_in_both_places_without_answering(self):
        req = self.stopped()
        shown = questions.show(self.ledger, req['id'])                                       # owner terminal (this process)
        code, via_ai = self.show_cli(req['id'])                                              # AI session
        self.assertEqual(code, 0, via_ai); self.assertEqual(via_ai['id'], shown['id'])
        question = shown['question']
        for field in ('question', 'options', 'recommendation', 'reason', 'impact', 'action'):   # problem, choices, recommendation, evidence/reason, scope, decide-by action
            self.assertTrue(question.get(field), field)
        self.assertEqual(question['action']['type'], 'v2.plan_stopped')
        self.assertEqual(self.ledger.request(req['id'])['state'], 'pending')                 # [E8] reading answers nothing
        self.assertNotIn('request.answered', self.kinds())

    def test_e3_e7_amend_answer_waits_for_a_new_approved_revision_and_refuses_verdict_until_then(self):
        req = self.stopped()
        sha_before = plan.show(self.ledger, 'P1')['sha']
        effect = questions.answer(self.ledger, req['id'], req['revision'], 'amend_plan', 'Change the check, not the budget.')
        self.assertEqual(effect['controller_effect']['effect'], 'await_new_approved_revision')
        self.assertEqual(self.ledger.request(req['id'])['state'], 'answered')
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'stopped_with_report')     # waits; nothing continues by itself
        self.assertEqual(plan.show(self.ledger, 'P1')['sha'], sha_before)                     # [E7] the contract did not change
        with self.assertRaises(LedgerError):
            verdict.run(self.ledger, 'P1', 'M1')                                             # [E3] refused before a new approved revision
        self.assertNotIn('verdict.receipt_issued', self.kinds()[self.kinds().index('request.answered'):])
        page = report.render_present(self.ledger.state_root, 'P1')
        self.assertIn('đã chọn amend', page); self.assertIn('Change the check, not the budget.', page)          # [E11]-style line for amend
        plan.amend(self.ledger, 'P1', plan_json(milestones=[milestone(argv=BAD, max_repairs=1)]), 'raise the repair ceiling by one', 'codex')
        plan.approve(self.ledger, 'P1', 'owner', 'approved the amendment')
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'approved')
        shown = verdict.run(self.ledger, 'P1', 'M1')                                         # runs again only after the owner approved the new revision
        self.assertIn(shown['milestones'][0]['state'], ('failed', 'stopped'))

    def test_e11_stop_answer_is_shown_as_chosen_on_present_and_report(self):
        req = self.stopped()
        questions.answer(self.ledger, req['id'], req['revision'], 'stop', 'Do not spend more on this job.')
        present = report.render_present(self.ledger.state_root, 'P1')
        page = report.render_report(self.ledger.state_root, 'P1')
        for text in (present, page):
            self.assertIn('Chủ sở hữu đã chọn dừng', text); self.assertIn('Do not spend more on this job.', text); self.assertIn(req['id'], text)
        self.assertNotIn('đã chọn amend', present)
