"""W03 audit counter-examples (T20): an AI tool session cannot write the owner's decision through any route.

Routes: decisions.record with an owner/human subject or a made-up grant on a plan root; `plan card present --component owner --model human`;
conversations.decide (CLI `solution approve`, MCP solution_decide) with an owner-like source; skills.decide; interventions.record.
The same guard as Ledger.reply: the CLAUDE_CODE_CHILD_SESSION marker. A terminal (no marker) still records.
"""
import json
import os
import unittest
from unittest.mock import patch

from onecrew import conversations, interventions as iv, skills, task_intake
from onecrew.ledger import LedgerError
from onecrew.v2 import authority, cards, decisions, plan as plans
from tests.test_conversations import solution
from tests.test_v2_l3 import Step0, step0_json
from tests.test_wf_r01_card import csv_choice, technical

AI = {'CLAUDE_CODE_CHILD_SESSION': '1'}
OWNER = {'component': 'owner', 'model': 'human'}
EVIDENCE = [{'ref': 'x/y.py:1'}]


class DecisionRouteTests(Step0):
    def setUp(self):
        super().setUp()
        self.propose('P1', step0_json(size='S', authority={'edit': True}))
        plans.approve(self.ledger, 'P1', 'owner', 'said yes')
        with self.ledger.transaction() as conn:
            self.state = plans.derive(self.ledger, conn, 'P1')
        contract, _ = plans.load(self.ledger, self.state, self.state['approved']['revision'])
        self.grant = authority.grant_ref(self.state['selector'], contract, self.state['approved']['sha'])

    def recorded(self):
        return [p for k, p in self.events('P1') if k == 'decision.recorded']

    def record(self, **kw):
        args = dict(subject={'component': 'step0', 'model': 'claude-sonnet-5-5'}, authority=self.grant, evidence=EVIDENCE, basis='b', scope='s')
        args.update(kw)
        return decisions.record(self.ledger, self.state['task_id'], **args)

    def test_owner_human_subject_is_refused_in_an_ai_session(self):
        with patch.dict(os.environ, AI):
            with self.assertRaises(LedgerError) as caught: self.record(subject=OWNER)
        self.assertIn('AI tool session', str(caught.exception)); self.assertEqual(self.recorded(), [])
        for subject in ({'component': 'User', 'model': 'x'}, {'component': 'step0', 'model': 'Human'}):
            with patch.dict(os.environ, AI), self.assertRaises(LedgerError): self.record(subject=subject)
        self.assertEqual(self.recorded(), [])

    def test_a_made_up_grant_on_a_plan_root_is_refused_in_an_ai_session(self):
        with patch.dict(os.environ, AI):
            with self.assertRaises(LedgerError) as caught: self.record(authority={'grant_id': 'made-up', 'revision': '1'})
        self.assertIn('grant', str(caught.exception)); self.assertEqual(self.recorded(), [])
        with patch.dict(os.environ, AI):
            self.record()                                                            # the root's real grant records
        self.assertEqual(len(self.recorded()), 1)

    def test_a_terminal_still_records_the_owner_decision(self):
        with patch.dict(os.environ, {'ONECREW_ACTOR': 'owner'}):
            payload = self.record(subject=OWNER, by='owner')
        self.assertEqual(payload['actor'], 'owner'); self.assertEqual(len(self.recorded()), 1)

    def test_card_present_with_an_owner_subject_is_refused_and_writes_nothing(self):
        path = self.root.parent / 'choices.json'
        path.write_text(json.dumps({'choices': [csv_choice(), technical('T1', authority=self.grant)]}), encoding='utf-8')
        with patch.dict(os.environ, AI):
            code, out = self.cli('plan', 'card', 'present', 'P1', '--file', str(path), '--component', 'owner', '--model', 'human')
        self.assertNotEqual(code, 0); self.assertIn('AI tool session', out)
        self.assertEqual(self.recorded(), []); self.assertEqual(self.ledger.requests(self.state['task_id']), [])
        with patch.dict(os.environ, AI), self.assertRaises(LedgerError):
            cards.present(self.ledger, 'P1', [technical('T1', authority=self.grant)], OWNER)
        self.assertEqual(self.recorded(), [])


class SolutionDecisionTests(Step0):
    def setUp(self):
        super().setUp()
        self.cid = conversations.create(self.ledger, 'SOL', 'fixture', 'codex')['id']
        self.sol = conversations.propose(self.ledger, self.cid, 'source', solution(), 'codex')

    def approved(self):
        with self.ledger.transaction() as conn:
            return conversations.approved(self.ledger, conn, self.sol['id'], self.sol['revision'])

    def test_approve_with_user_source_is_refused_in_an_ai_session(self):
        for source in ('user', 'owner', 'user-chat', 'claude'):
            with patch.dict(os.environ, AI), self.assertRaises(LedgerError, msg=source) as caught:
                conversations.decide(self.ledger, self.sol['id'], self.sol['revision'], 'approve', source, 'said yes')
            self.assertIn('AI tool session', str(caught.exception))
        with self.assertRaises(LedgerError): self.approved()
        with patch.dict(os.environ, AI), self.assertRaises(LedgerError):
            conversations.decide(self.ledger, self.sol['id'], self.sol['revision'], 'request_changes', 'user', 'said no')

    def test_cli_solution_approve_is_refused_in_an_ai_session(self):
        from onecrew import conversation_cli
        import contextlib, io
        out = io.StringIO()
        with patch.dict(os.environ, AI), contextlib.redirect_stdout(out):
            code = conversation_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'solution', 'approve',
                                          self.sol['id'], '--revision', self.sol['revision'], '--source', 'user', '--reference', 'yes'])
        self.assertNotEqual(code, 0); self.assertIn('AI tool session', out.getvalue())
        with self.assertRaises(LedgerError): self.approved()

    def test_a_terminal_still_records_the_approval(self):
        conversations.decide(self.ledger, self.sol['id'], self.sol['revision'], 'approve', 'user', 'said yes')
        self.assertEqual(self.approved()[1]['choice'], 'approve')

    def test_an_ai_may_still_request_changes_under_its_own_name(self):
        with patch.dict(os.environ, AI):
            value = conversations.decide(self.ledger, self.sol['id'], self.sol['revision'], 'request_changes', 'claude', 'needs a test')
        self.assertEqual(value['choice'], 'request_changes')


class SkillAndInterventionTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from onecrew.ledger import Ledger
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        base = Path(tmp.name); (base / 'p').mkdir()
        self.ledger = Ledger(base / 'p', base / 'state')
        env = patch.dict(os.environ); env.start(); self.addCleanup(env.stop)
        for name in ('ONECREW_ACTOR', 'CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE'): os.environ.pop(name, None)

    def test_skill_decide_is_refused_in_an_ai_session_before_anything_is_read(self):
        for decision in ('approved', 'rejected'):
            with patch.dict(os.environ, AI), self.assertRaises(LedgerError) as caught:
                skills.decide(self.ledger, 'SKILL-x', 'r1', decision, 'operator said yes')
            self.assertIn('AI tool session', str(caught.exception))
        with self.assertRaises(LedgerError) as caught:                 # a terminal passes the guard and reaches the revision check
            skills.decide(self.ledger, 'SKILL-x', 'r1', 'approved', 'operator said yes')
        self.assertNotIn('AI tool session', str(caught.exception))

    def test_intervention_owner_actor_is_refused_in_an_ai_session_but_recorded_from_a_terminal(self):
        task = task_intake.submit(self.ledger, 'host', 'w03-audit', mode='audit')['id']
        for actor in ('owner', 'user', 'human', 'Owner '):
            with patch.dict(os.environ, AI), self.assertRaises(LedgerError, msg=actor):
                iv.record(self.ledger, task, 'work.extend', actor=actor, reason='r')
        with patch.dict(os.environ, dict(AI, ONECREW_ACTOR='user')), self.assertRaises(LedgerError):
            iv.record(self.ledger, task, 'work.extend', reason='r')
        self.assertEqual(iv.record(self.ledger, task, 'work.extend', actor='user', reason='r')['actor'], 'user')
