"""T47a [E11]/[E12] gaps (R03 W30b): on a legacy `plan:` root an owner answer is RECORDED with choice, reference and the owner as
subject, has no class-B effect on the anchor, the root stays stopped_with_report, and the page says what was chosen.

Fixture: real temporary ledger; a root proposed by the archived old version d3120c6 (anchor key `plan:`, asserted), stopped because M1 hit its repair
ceiling (max_repairs 0, as tests/test_wf_answer_effects.stopped). The owner terminal is simulated (AI-session markers cleared,
ONECREW_ACTOR unset), as in the existing v2 tests. Counter-example: writing plan.closed on that anchor is refused as class B.
"""
import json
import os
from pathlib import Path

from onecrew.ledger import LedgerError
from onecrew.v2 import compat, plan, questions, report, verdict
from tests.test_v2_l1 import Fixture, plan_json, milestone, BAD
from tests.wf_env import owner_terminal
from tests import wf_oldversion as ov


SELECTOR = 'plan:Legacy'


def stopped_legacy(case, name=SELECTOR):
    """A root proposed by the OLD version (so its anchor key is `plan:`), stopped with one pending owner question; returns
    (request, anchor task id)."""
    owner_terminal(case); os.environ.pop('ONECREW_ACTOR', None)
    old = ov.OldVersion(ov.archive('d3120c6', Path(__file__).resolve().parents[1], case.temp.name))
    file = Path(case.temp.name) / 'legacy.json'; file.write_text(json.dumps(plan_json(milestones=[milestone(argv=BAD, max_repairs=0)])))
    code, output = old.run(case.root, case.ledger.state_root, 'plan', 'propose', 'Legacy', '--file', str(file), '--author', 'codex')
    case.assertEqual(code, 0, output)
    plan.approve(case.ledger, name, 'owner', 'fixture')
    verdict.run(case.ledger, name, 'M1')
    with case.ledger.transaction() as conn:
        state = plan.anchor_events(case.ledger, conn, name)
        key = conn.execute('SELECT request_key FROM tasks WHERE id=?', (state['task_id'],)).fetchone()[0]
    case.assertTrue(key.startswith('plan:'), key)                                         # really a legacy `plan:` anchor
    case.assertEqual(state['status'], 'stopped_with_report')
    request = case.ledger.requests(state['task_id'], pending=True)[0]
    return request, state['task_id']


def anchor_kinds(ledger, task):
    return [e['kind'] for e in ledger.events(task)]


def answered_payloads(ledger, task):
    return [e['payload'] for e in ledger.events(task) if e['kind'] == 'request.answered']


class LegacyRootAnswerTests(Fixture):
    def check_recorded_without_effect(self, req, task, choice, reference):
        answers = answered_payloads(self.ledger, task)
        self.assertEqual(len(answers), 1)
        answer = answers[0]
        self.assertEqual((answer['request_id'], answer['choice']), (req['id'], choice))     # choice in request.answered
        self.assertEqual(answer['provenance']['reference'], reference)                      # the reference
        self.assertEqual(answer['provenance']['decided_by'], 'user')                        # subject: the owner
        self.assertEqual(answer['provenance']['by'], 'user')
        self.assertEqual(answer['provenance']['source'], 'owner-terminal')
        self.assertFalse(answer['action_applied'])
        kinds = anchor_kinds(self.ledger, task)
        self.assertEqual(kinds.count('request.applied'), 0)                                  # [E12] no apply event on `plan:`
        self.assertEqual([k for k in kinds if compat.event_class(k) == 'B'], [])             # [E11] no class-B event on the anchor
        self.assertEqual(self.ledger.request(req['id'])['state'], 'answered')                # the request is closed
        self.assertEqual(plan.show(self.ledger, SELECTOR)['status'], 'stopped_with_report')     # the root keeps its old semantics

    def test_e11_stop_on_plan_root_is_recorded_shown_chosen_and_has_no_class_b_effect(self):
        req, task = stopped_legacy(self)
        questions.answer(self.ledger, req['id'], req['revision'], 'stop', 'Do not spend more on this job.')
        self.check_recorded_without_effect(req, task, 'stop', 'Do not spend more on this job.')
        page = report.render_present(self.ledger.state_root, SELECTOR)
        self.assertIn('đã chọn dừng', page)                                                  # [E11] "da chon dung" on plan present
        self.assertIn('Do not spend more on this job.', page)
        self.assertEqual(questions.list_for_plan(self.ledger, SELECTOR, pending=True), [])
        # counter-example: the class-B write the R03 root must never get is refused on a `plan:` anchor
        with self.assertRaisesRegex(LedgerError, 'class B'):
            compat.check_write('plan.closed', {'plan': SELECTOR, 'revision': 1}, SELECTOR)

    def test_e12_amend_answer_on_plan_root_is_recorded_with_choice_reference_owner_and_no_apply(self):
        req, task = stopped_legacy(self)
        questions.answer(self.ledger, req['id'], req['revision'], 'amend_plan', 'Change the check, not the budget.')
        self.check_recorded_without_effect(req, task, 'amend_plan', 'Change the check, not the budget.')
