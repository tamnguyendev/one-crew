"""T26 real temporary SOL/root/gate lifecycle; no provider or owner live state."""
import json
from pathlib import Path

from onecrew import conversations, solution_gate
from onecrew.ledger import Ledger, LedgerError, canonical
from onecrew.owned_intake import submit
from onecrew.v2 import plan, solution_link
from tests.test_conversations import solution
from tests.test_v2_l1 import Fixture, plan_json


class SolutionLinkTests(Fixture):
    def setUp(self):
        super().setUp()
        self.cid = conversations.create(self.ledger, 'Existing SOL work', 'fixture', 'user')['id']
        self.sol = conversations.propose(self.ledger, self.cid, 'source', solution(), 'codex')
        conversations.decide(self.ledger, self.sol['id'], self.sol['revision'], 'approve', 'user', 'temporary fixture approval')
        self.ref = {key: self.sol[key] for key in ('id', 'revision')}
        self.contract = plan_json(solution_ref=self.ref, authority={'edit': True, 'commands': True})

    def linked_root(self, approve=True):
        root = plan.propose(self.ledger, 'P1', self.contract, 'codex', workflow=True)
        if approve: plan.approve(self.ledger, 'P1', 'owner', 'temporary root approval')
        return root

    def job(self, key='write', ref=None, paths=None, **extra):
        ref = ref or self.ref
        work = {'schema_version': 1, 'goal': 'Edit the approved output', 'acceptance': ['Output corrected'],
                'preserve': ['Other files'], 'authority': {'edit': True},
                'scope': {'repository': '', 'paths': paths or ['a.txt']},
                'authorized_by': {'source': 'user', 'reference': 'temporary fixture'}}
        return submit(self.ledger, None, key, mode='work', contract=work, provider='codex', model='gpt-6.1-sol',
                      max_calls=10, max_seconds=60, solution_id=ref['id'], solution_revision=ref['revision'], **extra)

    def test_sol_only_approval_cannot_dispatch_before_root_approval(self):
        old = self.job('pre-link')
        root = self.linked_root(approve=False)
        with self.assertRaises(LedgerError): self.job('post-link')
        with self.assertRaisesRegex(LedgerError, 'SOL approval grants no execution'):
            solution_gate.check(self.ledger, old['id'])
        plan.approve(self.ledger, 'P1', 'owner', 'temporary root approval')
        with self.assertRaises(LedgerError): solution_gate.check(self.ledger, old['id'])
        fresh = self.job('root-handoff')
        allowed = solution_gate.check(self.ledger, fresh['id'])
        self.assertEqual(allowed['authority'], 'root')
        self.assertEqual(allowed['root']['task_id'], root['anchor_task'])
        with self.ledger.transaction() as conn:
            state = plan.anchor_events(self.ledger, conn, 'P1')
            raw = json.loads(self.ledger._task(conn, fresh['id'])['payload'])
        self.assertEqual(allowed['root']['sha'], state['approved']['sha'])
        self.assertEqual(raw['plan_binding']['sha'], allowed['root']['sha'])
        self.assertEqual(allowed['solution_authority'], 'none')
        self.assertEqual(solution_gate.context(self.ledger, fresh['id'])['authority'], 'root')

    def test_root_is_single_grant_even_if_sol_decision_changes(self):
        self.linked_root()
        conversations.decide(self.ledger, self.sol['id'], self.sol['revision'], 'request_changes', 'user', 'fixture SOL commentary')
        task = self.job()
        self.assertEqual(solution_gate.check(self.ledger, task['id'])['authority'], 'root')
        outside = self.job('outside-scope', paths=['other.txt'])
        with self.assertRaisesRegex(LedgerError, 'outside the owned scope'):
            solution_gate.check(self.ledger, outside['id'])

    def test_second_root_for_same_work_is_refused_with_existing_root_identity(self):
        root = self.linked_root()
        with self.assertRaises(LedgerError) as raised:
            plan.propose(self.ledger, 'P2', self.contract, 'codex', workflow=True)
        self.assertIn(root['anchor_task'], str(raised.exception))
        self.assertIn('plan-ns:P1', str(raised.exception))
        successor = conversations.propose(self.ledger, self.cid, 'next', dict(solution(), detail='Revised source'), 'codex', self.sol['id'])
        changed = dict(self.contract, solution_ref={key: successor[key] for key in ('id', 'revision')})
        with self.assertRaises(LedgerError): plan.propose(self.ledger, 'P2', changed, 'codex', workflow=True)
        self.assertFalse((Path(self.ledger.state_root)/'plans'/self.ledger.project_id/'P2').exists())

    def test_source_ref_change_needs_current_root_revision_approval_and_new_handoff(self):
        self.linked_root(); old = self.job()
        newer = conversations.propose(self.ledger, self.cid, 'next', dict(solution(), detail='Reviewed alternative'), 'codex', self.sol['id'])
        ref = {key: newer[key] for key in ('id', 'revision')}
        changed = dict(self.contract, solution_ref=ref)
        plan.amend(self.ledger, 'P1', changed, 'New source revision', 'codex')
        with self.assertRaises(LedgerError): solution_gate.check(self.ledger, old['id'])
        with self.assertRaises(LedgerError): self.job('before-approval', ref=ref)
        plan.approve(self.ledger, 'P1', 'owner', 'temporary second root approval')
        with self.assertRaises(LedgerError): solution_gate.check(self.ledger, old['id'])
        with self.assertRaises(LedgerError): self.job('old-reference')
        current = self.job('new-reference', ref=ref)
        result = solution_gate.check(self.ledger, current['id'])
        self.assertEqual(result['root']['revision'], 2)
        self.assertEqual(result['solution_ref'], ref)

    def test_wrong_project_missing_source_and_source_tampering_fail_closed(self):
        other = Path(self.temp.name)/'other'; other.mkdir()
        other_ledger = Ledger(other, self.ledger.state_root)
        with self.assertRaisesRegex(LedgerError, 'another project'):
            plan.propose(other_ledger, 'P1', self.contract, 'codex')
        bad = dict(self.contract, solution_ref={'id': 'SOL-'+'f'*32, 'revision': 'a'*64})
        with self.assertRaises(LedgerError): plan.propose(self.ledger, 'P2', bad, 'codex')
        self.linked_root(approve=False)
        with self.ledger.transaction(write=True) as conn:
            conn.execute('UPDATE solutions SET payload=? WHERE id=?', (canonical(dict(solution(), detail='tampered fixture')), self.sol['id']))
        with self.assertRaisesRegex(LedgerError, 'immutable revision'):
            plan.approve(self.ledger, 'P1', 'owner', 'fixture must refuse')

    def test_link_cannot_be_removed_or_moved_to_other_work(self):
        self.linked_root()
        absent = dict(self.contract); absent.pop('solution_ref')
        with self.assertRaisesRegex(LedgerError, 'remove'):
            plan.amend(self.ledger, 'P1', absent, 'Illegal unlink', 'codex')
        cid = conversations.create(self.ledger, 'Other work', 'other', 'user')['id']
        sol = conversations.propose(self.ledger, cid, 's', solution(), 'codex')
        other = dict(self.contract, solution_ref={key: sol[key] for key in ('id','revision')})
        with self.assertRaisesRegex(LedgerError, 'another SOL conversation'):
            plan.amend(self.ledger, 'P1', other, 'Illegal work switch', 'codex')

    def test_wrong_explicit_root_and_missing_link_receipt_are_refused(self):
        self.linked_root()
        plan.propose(self.ledger, 'Other', plan_json(authority={'edit': True}), 'codex')
        plan.approve(self.ledger, 'Other', 'owner', 'temporary other root approval')
        with self.assertRaisesRegex(LedgerError, 'different approved root'):
            self.job(plan_selector='plan-ns:Other')
        task = self.job()
        with self.ledger.transaction(write=True) as conn:
            conn.execute("DELETE FROM events WHERE kind='solution.linked'")
        with self.assertRaisesRegex(LedgerError, 'immutable SOL linkage'):
            solution_gate.check(self.ledger, task['id'])

    def test_legacy_root_and_missing_explicit_authority_cannot_acquire_link(self):
        with self.ledger.transaction() as conn:
            with self.assertRaisesRegex(LedgerError, 'legacy'):
                solution_link.validate_revision(self.ledger, conn, 'plan:P1', self.contract)
        absent = dict(self.contract); absent.pop('authority')
        with self.assertRaisesRegex(LedgerError, 'explicit authority'):
            plan.propose(self.ledger, 'P1', absent, 'codex')

    def test_core_policy_helper_keeps_pending_questions_and_explicit_task_stop(self):
        self.linked_root(); task = self.job()
        request = solution_gate.question(self.ledger, self.cid, 'pending', 'Change source?',
            'Fixture needs a decision', [task['id']], 'codex')
        with self.ledger.transaction() as conn:
            with self.assertRaisesRegex(LedgerError, 'pending'):
                solution_link.check_task(self.ledger, conn, self.ledger._task(conn, task['id']))
        solution_gate.reply(self.ledger, request['id'], request['revision'], 'continue_unchanged', 'user', 'fixture answer')
        with self.ledger.transaction() as conn:
            self.assertEqual(solution_link.check_task(self.ledger, conn, self.ledger._task(conn, task['id']))['authority'], 'root')
        stop = solution_gate.question(self.ledger, self.cid, 'stop', 'Stop work?', 'Fixture stop', [task['id']], 'codex')
        solution_gate.reply(self.ledger, stop['id'], stop['revision'], 'stop', 'user', 'fixture stop answer')
        with self.ledger.transaction() as conn:
            with self.assertRaisesRegex(LedgerError, 'stopped'):
                solution_link.check_task(self.ledger, conn, self.ledger._task(conn, task['id']))

    def test_root_adoption_waits_for_existing_v1_writer_to_settle(self):
        from onecrew.control import Control, migrate
        old = self.job('old-live-writer')
        migrate(self.ledger); control = Control(self.ledger)
        execution = control.configure(old['id'], old['revision'], {'mode': 'fixture'})
        attempt = control.reserve(old['id'], execution['revision'], 'live', {'stage': 'fixture'})
        self.linked_root(approve=False)
        with self.assertRaisesRegex(LedgerError, 'v1 writer'):
            plan.approve(self.ledger, 'P1', 'owner', 'must await old writer')
        control.finish(attempt['id'], attempt['generation'], {'fixture': 'not started'}, not_started=True)
        plan.approve(self.ledger, 'P1', 'owner', 'old writer is settled')
        self.assertEqual(solution_gate.check(self.ledger, self.job('new-linked')['id'])['authority'], 'root')

    def test_root_hash_and_source_content_are_checked_again_at_dispatch(self):
        self.linked_root(); task = self.job()
        with self.ledger.transaction(write=True) as conn:
            row = conn.execute("SELECT seq,payload FROM events WHERE kind='solution.linked'").fetchone()
            event = json.loads(row['payload']); event['sha'] = 'f' * 64
            conn.execute('UPDATE events SET payload=? WHERE seq=?', (canonical(event), row['seq']))
        with self.assertRaisesRegex(LedgerError, 'immutable SOL linkage'):
            solution_gate.check(self.ledger, task['id'])
