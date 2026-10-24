"""T32 actual Control admission/intents, temporary ledgers, no provider/effects."""
import os
import shutil
from pathlib import Path
from unittest.mock import Mock, patch

from onecrew.control import Control
from onecrew.ledger import Ledger, LedgerError
from onecrew.owned_intake import submit
from onecrew.v2 import plan
from tests.test_wf_engine import EngineFixture
from tests.test_v2_l1 import plan_json


class RootWriterTests(EngineFixture):
    def job(self, key, *, edit=True, ledger=None, bound=True):
        ledger = ledger or self.ledger
        options = {'plan_selector': 'plan-ns:P1'} if bound else {}
        if edit:
            options.update(mode='work', contract={'schema_version': 1, 'goal': 'Edit a.txt',
                'acceptance': ['a.txt corrected'], 'preserve': ['Other files'], 'authority': {'edit': True},
                'scope': {'repository': '', 'paths': ['a.txt']},
                'authorized_by': {'source': 'user', 'reference': 'temporary fixture'}})
        task = submit(ledger, None if edit else 'Read a.txt', key, provider='codex', model='gpt-6.1-sol',
                      max_calls=10, max_seconds=60, **options)
        control = Control(ledger)
        execution = control.configure(task['id'], task['revision'], {'mode': 'fixture'})
        return task, control, execution

    def reserve(self, job, key='open', **operation):
        task, control, execution = job
        return control.reserve(task['id'], execution['revision'], key, {'stage': 'fixture', **operation})

    def action(self, job, key='apply'):
        task, control, _ = job
        action = control.propose_action(task['id'], key, {'kind': 'apply', 'files': ['a.txt'], 'fixture': True})
        control.authorize_action(action['id'], action['revision'])
        return action

    def test_second_ordinary_writer_refused_before_reservation_and_budget_charge(self):
        first, second = self.job('writer-one'), self.job('writer-two')
        active = self.reserve(first)
        before = self.ledger.task(second[0]['id'])['budget']
        with self.assertRaises(LedgerError) as raised:
            self.reserve(second, unit='isolated-fake', readonly=True, managed_slot=True)
        self.assertIn(self.root_view['anchor_task'], str(raised.exception))
        self.assertIn(first[0]['id'], str(raised.exception))
        self.assertEqual(self.ledger.task(second[0]['id'])['budget'], before)
        self.assertEqual(second[1].status(second[0]['id'])['attempts'], [])
        self.assertEqual(self.reserve(first)['id'], active['id'])
        first[1].finish(active['id'], active['generation'], {'fixture': 'not started'}, not_started=True)
        self.assertEqual(self.reserve(second)['status'], 'reserved')

    def test_unknown_attempt_retains_writer_until_existing_reconciliation(self):
        first, second = self.job('writer-one'), self.job('writer-two')
        active = self.reserve(first)
        first[1].unknown(active['id'], 'fixture interrupted before outcome known')
        with self.assertRaises(LedgerError): self.reserve(second)
        self.assertEqual(first[1].attempt(active['id'])['status'], 'unknown')

    def test_readonly_candidate_computation_does_not_take_shared_writer_slot(self):
        first, read = self.job('writer'), self.job('isolated-candidate', edit=False)
        self.assertEqual(self.reserve(first)['status'], 'reserved')
        self.assertEqual(self.reserve(read)['status'], 'reserved')

    def test_managed_readonly_publish_action_conflicts_with_live_ordinary_writer(self):
        first, managed = self.job('writer'), self.job('managed-candidate', edit=False)
        active = self.reserve(first)
        action = self.action(managed)
        handler = Mock(return_value={'verified': True})
        with self.assertRaises(LedgerError): managed[1].execute_action(action['id'], handler)
        self.assertEqual(handler.call_count, 0)
        first[1].finish(active['id'], active['generation'], {'fixture': 'not started'}, not_started=True)
        self.assertEqual(managed[1].execute_action(action['id'], handler)['status'], 'verified')
        self.assertEqual(handler.call_count, 1)

    def test_executing_publish_blocks_other_writer_and_second_publish(self):
        managed, other = self.job('managed-candidate', edit=False), self.job('ordinary-writer')
        action = self.action(managed)
        another = self.action(managed, 'second-apply')
        def effect(_):
            with self.assertRaises(LedgerError): self.reserve(other)
            with self.assertRaises(LedgerError):
                managed[1].execute_action(another['id'], lambda _: {'verified': True})
            return {'verified': True}
        self.assertEqual(managed[1].execute_action(action['id'], effect)['status'], 'verified')
        self.assertEqual(self.reserve(other)['status'], 'reserved')

    def test_unknown_publish_retains_ownership_until_verified_reconciliation(self):
        managed, other = self.job('managed-candidate', edit=False), self.job('ordinary-writer')
        action = self.action(managed)
        def ambiguous(_): raise OSError('fixture lost result')
        self.assertEqual(managed[1].execute_action(action['id'], ambiguous)['status'], 'unknown')
        with self.assertRaises(LedgerError): self.reserve(other)
        managed[1].reconcile_action(action['id'], action['revision'], lambda _: {'verified': False})
        with self.assertRaises(LedgerError): self.reserve(other)
        managed[1].reconcile_action(action['id'], action['revision'], lambda _: {'verified': True, 'fixture': 'observed'})
        self.assertEqual(self.reserve(other)['status'], 'reserved')

    def test_same_name_in_other_project_is_a_different_writer_root(self):
        other_root = Path(self.temp.name) / 'other-project'
        shutil.copytree(self.root, other_root)
        other_ledger = Ledger(other_root, self.ledger.state_root)
        contract = plan_json(authority={'edit': True, 'commands': True, 'edit_tests': True})
        with patch.dict(os.environ, {'ONECREW_ACTOR': 'user'}):
            plan.propose(other_ledger, 'P1', contract, 'codex', workflow=True)
            other = plan.approve(other_ledger, 'P1', 'owner', 'temporary second-project fixture')
        self.assertNotEqual(self.root_view['anchor_task'], other['anchor_task'])
        first, second = self.job('writer'), self.job('writer', ledger=other_ledger)
        self.assertEqual(self.reserve(first)['status'], 'reserved')
        self.assertEqual(self.reserve(second)['status'], 'reserved')

    def test_unbound_v1_work_grants_keep_existing_admission(self):
        first, second = self.job('v1-one', bound=False), self.job('v1-two', bound=False)
        self.assertEqual(self.reserve(first)['status'], 'reserved')
        self.assertEqual(self.reserve(second)['status'], 'reserved')
