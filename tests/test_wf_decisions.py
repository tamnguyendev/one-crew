"""T20 (W03) — decision record with a real subject, authority basis and evidence; `by=owner` refused from an AI session;
`interventions.record` refuses an owner actor from an AI session but accepts an AI actor.

Pure-core/v2 fixture: a temp state root, an anchor task via task_intake.submit (audit). No v1 runtime imports, so this runs
under the installed wheel too (W40/T33a). The AI session is simulated with CLAUDE_CODE_CHILD_SESSION, the same marker v2 uses.
"""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew import interventions as iv
from onecrew import task_intake
from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import decisions


AI = {'CLAUDE_CODE_CHILD_SESSION': '1'}


class Fixture:
    def __init__(self, case):
        tmp = tempfile.TemporaryDirectory(); case.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.project = self.base / 'project'; self.project.mkdir()
        self.state_root = self.base / 'state'
        self.ledger = Ledger(self.project, self.state_root)
        for name in ('ONECREW_ACTOR', 'ONECREW_RUNNER_INITIATOR', 'CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE'):
            os.environ.pop(name, None)
        self.task = task_intake.submit(self.ledger, 'A decision host', 'r00-decisions', mode='audit')['id']

    def events(self, kind):
        db = sqlite3.connect(self.ledger.path)
        try:
            return [json.loads(p) for (p,) in db.execute('SELECT payload FROM events WHERE kind=? ORDER BY seq', (kind,))]
        finally:
            db.close()

    def count(self, kind):
        return len(self.events(kind))


SUBJECT = {'component': 'kirocrew-worker', 'model': 'claude-sonnet-5-5'}
AUTHORITY = {'grant_id': 'G-01', 'revision': 'rev-abc'}
EVIDENCE = [{'id': 'E1', 'kind': 'read', 'ref': 'step0.py:265'}]


class DecisionRecordTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)

    # E1: every record has a real subject (component, model), authority basis and non-empty evidence.
    def test_e1_record_has_subject_authority_and_evidence(self):
        with patch.dict(os.environ, AI):
            payload = decisions.record(self.f.ledger, self.f.task, subject=SUBJECT, authority=AUTHORITY,
                                       evidence=EVIDENCE, basis='chose least-change fix', scope='W27a', by=None)
        self.assertEqual(payload['subject'], SUBJECT)
        self.assertEqual(payload['authority'], AUTHORITY)
        self.assertEqual(payload['evidence'], EVIDENCE)
        self.assertTrue(payload['subject']['component'] and payload['subject']['model'])
        self.assertTrue(payload['authority']['grant_id'] and payload['authority']['revision'])
        self.assertTrue(payload['evidence'])
        # actor recorded is the AI session's own, never 'owner'
        self.assertNotIn(payload['actor'], decisions.OWNER_ACTORS)
        self.assertEqual(self.f.count('decision.recorded'), 1)

    # E2 / E3: `by=owner` from an AI session is refused; the message names the AI session; nothing is written.
    def test_e2_by_owner_from_ai_session_is_refused_and_writes_nothing(self):
        before = self.f.count('decision.recorded')
        with patch.dict(os.environ, AI):
            with self.assertRaises(LedgerError) as caught:
                decisions.record(self.f.ledger, self.f.task, subject=SUBJECT, authority=AUTHORITY,
                                 evidence=EVIDENCE, basis='x', scope='W27a', by='owner')
        msg = str(caught.exception).lower()
        self.assertTrue('ai' in msg or 'session' in msg or 'owner' in msg, msg)
        self.assertEqual(self.f.count('decision.recorded'), before)        # E3: nothing written

    # E3 (counter): the owner may record a decision from their own terminal (no AI marker).
    def test_e3_owner_decision_from_owner_terminal_is_allowed(self):
        with patch.dict(os.environ, {'ONECREW_ACTOR': 'owner'}):
            payload = decisions.record(self.f.ledger, self.f.task, subject={'component': 'owner', 'model': 'human'},
                                       authority=AUTHORITY, evidence=EVIDENCE, basis='owner call', scope='W27a', by='owner')
        self.assertEqual(payload['actor'], 'owner')
        self.assertEqual(self.f.count('decision.recorded'), 1)

    # E4: a decision missing its authority basis is refused (0 recorded without a basis).
    def test_e4_decision_without_authority_basis_is_refused(self):
        for bad in (None, {}, {'grant_id': '', 'revision': 'r'}, {'grant_id': 'G', 'revision': ''}, {'grant_id': 'G'}):
            with patch.dict(os.environ, {'ONECREW_ACTOR': 'claude'}):
                with self.assertRaises(LedgerError, msg=f'authority={bad!r}'):
                    decisions.record(self.f.ledger, self.f.task, subject=SUBJECT, authority=bad,
                                     evidence=EVIDENCE, basis='x', scope='W27a', by=None)
        self.assertEqual(self.f.count('decision.recorded'), 0)

    # E1 (counter): empty subject or empty evidence is refused.
    def test_subject_and_evidence_must_be_non_empty(self):
        with patch.dict(os.environ, {'ONECREW_ACTOR': 'claude'}):
            with self.assertRaises(LedgerError):
                decisions.record(self.f.ledger, self.f.task, subject={}, authority=AUTHORITY, evidence=EVIDENCE, basis='x', scope='W', by=None)
            with self.assertRaises(LedgerError):
                decisions.record(self.f.ledger, self.f.task, subject=SUBJECT, authority=AUTHORITY, evidence=[], basis='x', scope='W', by=None)
            with self.assertRaises(LedgerError):
                decisions.record(self.f.ledger, self.f.task, subject={'component': 'c'}, authority=AUTHORITY, evidence=EVIDENCE, basis='x', scope='W', by=None)


class InterventionActorGuardTests(unittest.TestCase):
    """E5: recording a control.intervention with an owner actor from an AI session is refused and the count does not move;
    recording with the AI session's own actor adds exactly one line. The guard lives in the wheel (W03 wires interventions in)."""

    def setUp(self):
        self.f = Fixture(self)

    def test_e5_owner_actor_from_ai_session_refused_then_ai_actor_recorded(self):
        before = self.f.count('control.intervention')
        with patch.dict(os.environ, AI):
            with self.assertRaises(LedgerError) as caught:
                iv.record(self.f.ledger, self.f.task, 'work.extend', actor='owner', reason='r')
            self.assertTrue('session' in str(caught.exception).lower() or 'owner' in str(caught.exception).lower())
            self.assertEqual(self.f.count('control.intervention'), before)       # not incremented
            iv.record(self.f.ledger, self.f.task, 'work.extend', actor='claude', reason='r')
        self.assertEqual(self.f.count('control.intervention'), before + 1)        # AI actor: exactly one

    def test_user_actor_from_ai_session_is_also_refused(self):
        before = self.f.count('control.intervention')
        with patch.dict(os.environ, AI):
            with self.assertRaises(LedgerError):
                iv.record(self.f.ledger, self.f.task, 'work.extend', actor='user', reason='r')
        self.assertEqual(self.f.count('control.intervention'), before)

    def test_owner_actor_without_ai_session_is_allowed(self):
        before = self.f.count('control.intervention')
        with patch.dict(os.environ, {'ONECREW_ACTOR': 'owner'}):
            iv.record(self.f.ledger, self.f.task, 'work.extend', actor='user', reason='r')
        self.assertEqual(self.f.count('control.intervention'), before + 1)


if __name__ == '__main__':
    unittest.main()
