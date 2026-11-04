"""Dev7 review (R7-1, R7-2): what the page shows must follow the real projection, including what the ledger does not record.

R7-2: milestone-only plans read through the REAL overview item (what the board uses) and the detail, never a hand-built task.
R7-1: the page's own helpers decide when changed commands/binding must be repainted and when copy feedback is stale.
Real temporary ledgers and the shipped JS; no live provider."""
import json
import os
import sys
import unittest

from onecrew.ledger import LedgerError
from onecrew.v2 import plan, tracking, tracking_web, verdict
from tests import test_obs2_cards as cards
from tests import test_v2_l1 as fixtures

FAIL = [sys.executable, '-c', 'raise SystemExit(3)']


class MilestoneProgressFromProjection(fixtures.Fixture):
    run_js = cards.Cards.run_js

    def board(self):
        ov = tracking.overview(self.ledger.state_root)
        item = next(t for p in ov['projects'] for t in p['tasks'] if t['plan'] == 'P1')
        detail = tracking.detail(self.ledger.state_root, 'P1')
        lanes = [self.run_js('[workStage(' + json.dumps(t) + '),workStatus(' + json.dumps(t) + ')]') for t in (item, detail)]
        self.assertEqual(lanes[0], lanes[1], 'board card and detail disagree')
        return item, detail, lanes[0]

    def two_milestones(self, first=None):
        self.approved(value=fixtures.plan_json([fixtures.milestone('M1', **({'argv': first} if first else {})), fixtures.milestone('M2')]))

    def accepts(self, artifact):
        os.environ.pop('ONECREW_ACTOR', None)
        try:
            return plan.accept(self.ledger, 'P1', 'owner', 'fixture', artifact)['status']
        except LedgerError as e:
            return 'refused: ' + str(e)

    def test_approved_plan_without_any_check_is_not_started(self):
        self.two_milestones()
        item, detail, (stage, card) = self.board()
        self.assertEqual((stage, card), ('todo', 'Chưa khởi chạy'))
        self.assertFalse(item['has_started'])
        self.assertIn('chờ verdict của mốc M1, M2', item['status']['reason'])

    def test_a_failed_check_is_work_in_progress_not_never_started(self):
        self.two_milestones(first=FAIL)
        verdict.run(self.ledger, 'P1', 'M1')
        item, detail, (stage, card) = self.board()
        self.assertEqual([m['state'] for m in item['milestones']], ['failed', 'pending'])          # precondition: a real failed verdict, M2 untouched
        self.assertTrue(item['has_started'])
        self.assertEqual(stage, 'doing')
        self.assertNotEqual(card, 'Chưa khởi chạy')
        self.assertIn('M1', card); self.assertIn('chưa đạt', card)
        self.assertIn('M1', item['status']['reason']); self.assertIn('chưa đạt', item['status']['reason'])
        self.assertNotIn('chờ verdict của mốc M1', item['status']['reason'])
        self.assertIn('chờ verdict của mốc M2', item['status']['reason'])
        self.assertFalse(item['acceptance']['ready']); self.assertEqual(item['needs_user'], [])

    def test_partial_pass_names_what_is_left(self):
        self.two_milestones()
        verdict.run(self.ledger, 'P1', 'M1')
        item, detail, (stage, card) = self.board()
        self.assertEqual([m['state'] for m in item['milestones']], ['passed', 'pending'])
        self.assertEqual(stage, 'doing'); self.assertIn('M2', card); self.assertNotIn('M1', card)
        self.assertFalse(item['acceptance']['ready'])

    def test_passes_on_different_artifacts_are_work_not_acceptance(self):
        self.two_milestones()
        verdict.run(self.ledger, 'P1', 'M1'); first = self.tree()
        (self.root / 'a.txt').write_text('second artifact\n'); verdict.run(self.ledger, 'P1', 'M2'); second = self.tree()
        item, detail, (stage, card) = self.board()
        self.assertEqual([m['state'] for m in item['milestones']], ['passed', 'passed'])
        self.assertEqual(stage, 'doing'); self.assertFalse(item['acceptance']['ready']); self.assertEqual(item['needs_user'], [])
        self.assertTrue(self.accepts(first).startswith('refused')); self.assertTrue(self.accepts(second).startswith('refused'))

    def test_eligible_plan_is_offered_for_acceptance_then_done(self):
        self.two_milestones()
        verdict.run(self.ledger, 'P1', 'M1'); verdict.run(self.ledger, 'P1', 'M2')
        item, detail, (stage, card) = self.board()
        self.assertEqual((stage, card), ('accept', 'Đã kiểm đạt · chờ nghiệm thu'))
        self.assertEqual([n['kind'] for n in item['needs_user']], ['accept'])
        self.assertEqual(self.accepts(self.tree()), 'accepted')
        item, detail, (stage, card) = self.board()
        self.assertEqual((stage, card), ('done', 'Đã nghiệm thu'))


class LiveBindingHelpers(unittest.TestCase):
    """R7-1: the page decides from its own data, not from the ledger sequence alone."""
    run_js = cards.Cards.run_js
    HELPERS = tracking_web.PAGE[tracking_web.PAGE.index('function needCopyable('):tracking_web.PAGE.index('function needs_open_sync')] if 'function needCopyable(' in tracking_web.PAGE else ''

    def js(self, expr):
        if not self.HELPERS: self.fail('needCopyable/needsSig/copiedStillValid missing from the page')
        return self.run_js(expr, 'function needKey(n){return "need:"+n.kind+":"+(n.id||"")+":"+(n.revision||"")}\n' + self.HELPERS)

    def test_signature_changes_with_binding_and_commands_only(self):
        bound = {'needs_user': [{'kind': 'request', 'id': 'Q', 'revision': 'r1', 'human_command': 'cmd a', 'runtime_binding': {'verified': True},
                                 'options': [{'id': 'a', 'human_command': 'cmd a'}]}]}
        lost = json.loads(json.dumps(bound)); lost['needs_user'][0].update(human_command=None, runtime_binding={'verified': False}, binding_reason='why')
        lost['needs_user'][0]['options'][0]['human_command'] = None
        other = json.loads(json.dumps(bound)); other['needs_user'][0]['options'][0]['human_command'] = 'cmd b'
        same = json.loads(json.dumps(bound)); same['generated_at'] = 'later'
        sig = lambda d: self.js('needsSig(' + json.dumps(d) + ')')
        self.assertNotEqual(sig(bound), sig(lost))
        self.assertNotEqual(sig(bound), sig(other))
        self.assertEqual(sig(bound), sig(same))

    def test_copy_feedback_only_while_its_command_is_still_offered(self):
        need = {'kind': 'request', 'id': 'Q', 'revision': 'r1', 'human_command': 'cmd x', 'options': [{'id': 'a', 'human_command': 'cmd a'}]}
        k = 'need:request:Q:r1'
        valid = lambda copied, d: self.js('copiedStillValid(' + json.dumps(copied) + ',' + json.dumps(d) + ')')
        self.assertTrue(valid({'k': k, 'text': 'cmd a'}, {'needs_user': [need]}))
        lost = dict(need, human_command=None, options=[{'id': 'a', 'human_command': None}])
        self.assertFalse(valid({'k': k, 'text': 'cmd a'}, {'needs_user': [lost]}))
        self.assertFalse(valid({'k': k, 'text': 'cmd a'}, {'needs_user': []}))
        self.assertFalse(valid({'k': k, 'text': 'cmd old'}, {'needs_user': [need]}))
