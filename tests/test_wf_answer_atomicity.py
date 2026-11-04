"""P1-2 (T47c E6, T43d E7/E13): an owner answer and its mandatory workflow effect commit in ONE ledger transaction.

Invariant: there is never a committed state with an answered request of a plan-ns workflow root (capability
sequential-engine, action v2.plan_stopped / v2.workflow_hold, owner provenance) whose effect is still due.
Side I/O (active plan export, outcome note) runs only after that commit and cannot undo or half-apply it.
"""
import json
import os
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.v2 import active_plan, answer_effects, namespaces, plan, questions, verdict
from tests.test_v2_l1 import Fixture, plan_json, milestone, BAD
from tests.test_wf_engine import EngineFixture, node

MANDATORY = ('v2.plan_stopped', 'v2.workflow_hold')


class _Rollback(Exception):
    pass


def assert_no_answered_without_effect(ledger, task_id):
    """Fail when a committed answered request of a workflow root still owes its mandatory effect.

    Returns the request ids the invariant applies to (empty for a legacy/default root: there a reply is only recorded).
    An answer whose effect is no longer due (the root/internal revision moved on after the question) is not a gap: it is
    detected by evaluating the effect inside a transaction that is always rolled back."""
    with ledger.transaction() as conn:
        task = ledger._task(conn, task_id)
        if not task['request_key'].startswith(namespaces.NAMESPACED): return []
        state = plan.anchor_events(ledger, conn, task['request_key'])
        if not namespaces.has_capability(state, 'sequential-engine'): return []
        rows = [dict(row) for row in conn.execute("SELECT * FROM requests WHERE task_id=? AND state='answered'", (task_id,))]
        applied = {(e['request_id'], e['request_revision']) for e in
                   (json.loads(r['payload']) for r in conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='request.applied'", (task_id,)))}
    checked = []
    for row in rows:
        if json.loads(row['payload'])['action']['type'] not in MANDATORY: continue
        provenance = json.loads(row['answer']).get('provenance', {})
        if provenance.get('decided_by') != 'user' or provenance.get('by') != 'user': continue   # no owner answer, no owed effect
        checked.append(row['id'])
        if (row['id'], row['revision']) in applied: continue
        try:
            with ledger.transaction(write=True) as wconn:
                due = answer_effects.apply(ledger, row['id'], conn=wconn)
                raise _Rollback(due)
        except _Rollback as rolled:
            due = rolled.args[0]
        if due.get('applied'):
            raise AssertionError(f'Answered request {row["id"]} rev {row["revision"]} lacks its mandatory effect (request.applied).')
    return checked


def _crash_on(kind):
    real = plan.emit
    def emit(ledger, conn, task_id, event_kind, payload):
        if event_kind == kind: raise RuntimeError('simulated crash before ' + kind)
        return real(ledger, conn, task_id, event_kind, payload)
    return patch.object(plan, 'emit', emit)


class StoppedPlanAtomicityTests(Fixture):
    def setUp(self):
        super().setUp()
        raw = plan_json(milestones=[milestone(argv=BAD, max_repairs=0)])
        plan.propose(self.ledger, 'P1', raw, 'codex', workflow=True, capabilities=list(namespaces.CAPABILITIES))
        plan.approve(self.ledger, 'P1', 'owner', 'fixture')
        verdict.run(self.ledger, 'P1', 'M1')
        self.task = plan.show(self.ledger, 'P1')['anchor_task']
        self.req = self.ledger.requests(self.task, pending=True)[0]
        self.assertEqual(self.req['question']['action']['type'], 'v2.plan_stopped')

    def tearDown(self):
        assert_no_answered_without_effect(self.ledger, self.task)

    def answer(self, choice='stop', revision=None):
        return questions.answer(self.ledger, self.req['id'], self.req['revision'] if revision is None else revision, choice, 'owner stop fixture')

    def counts(self):
        kinds = self.kinds()
        return {k: kinds.count(k) for k in ('request.answered', 'request.applied', 'plan.closed')}

    def request_state(self):
        return self.ledger.request(self.req['id'])['state']

    def test_crash_inside_effect_rolls_back_reply_and_effect(self):
        for kind in ('plan.closed', 'request.applied'):
            with self.subTest(crash_before=kind), _crash_on(kind), self.assertRaises(RuntimeError):
                self.answer()
            self.assertEqual(self.request_state(), 'pending')
            self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'stopped_with_report')
            self.assertEqual(self.counts(), {'request.answered': 0, 'request.applied': 0, 'plan.closed': 0})
            assert_no_answered_without_effect(self.ledger, self.task)

    def test_retry_after_crash_applies_exactly_once(self):
        with _crash_on('request.applied'), self.assertRaises(RuntimeError):
            self.answer()
        result = self.answer()
        self.assertTrue(result['controller_effect']['applied'])
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'closed')
        self.assertEqual(self.counts(), {'request.answered': 1, 'request.applied': 1, 'plan.closed': 1})
        assert_no_answered_without_effect(self.ledger, self.task)

    def test_crash_in_post_commit_export_keeps_committed_reply_and_effect(self):
        with patch.object(active_plan, 'export', side_effect=OSError('disk gone')):
            result = self.answer()
        self.assertEqual(self.request_state(), 'answered')
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'closed')
        self.assertEqual(self.counts(), {'request.answered': 1, 'request.applied': 1, 'plan.closed': 1})
        self.assertTrue(result['controller_effect']['applied'])
        self.assertTrue(any('disk gone' in error for error in result['post_commit_errors']))
        assert_no_answered_without_effect(self.ledger, self.task)
        active_plan.export(self.ledger, 'P1')                     # re-running the side I/O alone is enough
        again = self.answer()
        self.assertNotIn('post_commit_errors', again)
        self.assertEqual(self.counts(), {'request.answered': 1, 'request.applied': 1, 'plan.closed': 1})

    def test_duplicate_stale_and_conflicting_replies(self):
        first = self.answer()
        second = self.answer()
        self.assertEqual(second['id'], first['id'])
        self.assertTrue(second['controller_effect']['repeated'])
        self.assertEqual(self.counts(), {'request.answered': 1, 'request.applied': 1, 'plan.closed': 1})
        with self.assertRaisesRegex(LedgerError, 'Conflicting'):
            self.answer('amend_plan')
        self.assertEqual(self.counts(), {'request.answered': 1, 'request.applied': 1, 'plan.closed': 1})

    def test_stale_revision_is_refused_without_state_change(self):
        with self.assertRaisesRegex(LedgerError, 'Stale'):
            self.answer(revision='stale-revision')
        self.assertEqual(self.request_state(), 'pending')
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'stopped_with_report')
        self.assertEqual(self.counts(), {'request.answered': 0, 'request.applied': 0, 'plan.closed': 0})

    def test_ai_session_cannot_answer_and_nothing_is_written(self):
        with patch.dict(os.environ, {'CLAUDE_CODE_CHILD_SESSION': '1'}), self.assertRaises(LedgerError):
            self.answer()
        self.assertEqual(self.request_state(), 'pending')
        self.assertEqual(self.counts(), {'request.answered': 0, 'request.applied': 0, 'plan.closed': 0})

    def test_applied_event_carries_owner_answer_provenance(self):
        receipt = self.answer()
        applied = [p for k, p in self.events() if k == 'request.applied']
        self.assertEqual(len(applied), 1)
        payload = applied[0]
        self.assertEqual((payload['request_id'], payload['request_revision'], payload['answer_id'], payload['choice'],
                          payload['reference'], payload['by'], payload['grants_authority']),
                         (self.req['id'], self.req['revision'], receipt['id'], 'stop', 'owner stop fixture', 'owner', False))
        answered = [p for k, p in self.events() if k == 'request.answered'][0]
        self.assertEqual((answered['provenance']['decided_by'], answered['provenance']['by']), ('user', 'user'))

    def test_answer_and_effect_share_one_transaction(self):
        # one write transaction for reply + effect: the request.answered and request.applied rows are adjacent
        self.answer()
        seq = [k for k in self.kinds() if k in ('request.answered', 'plan.closed', 'request.applied')]
        self.assertEqual(seq, ['request.answered', 'plan.closed', 'request.applied'])

    def test_helper_flags_a_reply_left_without_effect(self):
        # what a previous build could leave behind: reply committed alone, effect never run
        self.ledger.reply(self.req['id'], self.req['revision'], 'stop', source='owner-terminal',
                          reference='older build', decided_by='user', by='user')
        with self.assertRaisesRegex(AssertionError, 'lacks its mandatory effect'):
            assert_no_answered_without_effect(self.ledger, self.task)
        answer_effects.reconcile(self.ledger, 'P1')
        self.assertEqual(assert_no_answered_without_effect(self.ledger, self.task), [self.req['id']])


class LegacyRootTests(Fixture):
    def test_default_schema_root_records_reply_without_effect_and_is_outside_the_invariant(self):
        raw = plan_json(milestones=[milestone(argv=BAD, max_repairs=0)])
        plan.propose(self.ledger, 'P1', raw, 'codex')
        plan.approve(self.ledger, 'P1', 'owner', 'fixture')
        verdict.run(self.ledger, 'P1', 'M1')
        task = plan.show(self.ledger, 'P1')['anchor_task']
        req = self.ledger.requests(task, pending=True)[0]
        result = questions.answer(self.ledger, req['id'], req['revision'], 'stop', 'legacy stop')
        self.assertNotIn('controller_effect', result)
        self.assertEqual(self.ledger.request(req['id'])['state'], 'answered')
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'stopped_with_report')
        self.assertNotIn('request.applied', self.kinds())
        self.assertNotIn('plan.closed', self.kinds())
        self.assertEqual(assert_no_answered_without_effect(self.ledger, task), [])


class WorkflowHoldAtomicityTests(EngineFixture):
    def setUp(self):
        super().setUp()
        self.revise([node('A'), node('B', write=('b.txt',)), node('I', ['A', 'B'], integration=True, write=())])
        self.engine.request_action(self.ledger, 'P1', 'A', {'kind': 'write', 'paths': ['outside.txt']})
        self.request = questions.list_for_plan(self.ledger, 'P1', pending=True)[0]
        self.assertEqual(self.request['question']['action']['type'], 'v2.workflow_hold')
        self.task = plan.show(self.ledger, 'P1')['anchor_task']

    def tearDown(self):
        assert_no_answered_without_effect(self.ledger, self.task)

    def reply(self, choice):
        with patch.dict(os.environ, {'ONECREW_ACTOR': ''}):
            return questions.answer(self.ledger, self.request['id'], self.request['revision'], choice, 'owner hold fixture')

    def test_crash_inside_resume_rolls_back_continue_answer(self):
        before = self.engine.state(self.ledger, 'P1')
        with patch.object(self.engine, 'resume_held', side_effect=RuntimeError('simulated crash in resume')), self.assertRaises(RuntimeError):
            self.reply('continue')
        self.assertEqual(self.ledger.request(self.request['id'])['state'], 'pending')
        self.assertEqual(self.engine.state(self.ledger, 'P1'), before)
        self.assertNotIn('request.answered', self.kinds())
        assert_no_answered_without_effect(self.ledger, self.task)
        result = self.reply('continue')['controller_effect']
        self.assertEqual(result['effect'], 'continued_within_grant')
        self.assertEqual(self.kinds().count('request.applied'), 1)
        self.assertEqual(self.kinds().count('node.resumed'), 2)

    def test_crash_after_resume_rolls_back_resumed_nodes_too(self):
        before = self.engine.state(self.ledger, 'P1')
        with _crash_on('request.applied'), self.assertRaises(RuntimeError):
            self.reply('continue')
        self.assertEqual(self.engine.state(self.ledger, 'P1'), before)
        self.assertNotIn('node.resumed', self.kinds())
        self.assertEqual(self.ledger.request(self.request['id'])['state'], 'pending')

    def test_crash_inside_stop_rolls_back_then_retry_closes_once(self):
        with _crash_on('plan.closed'), self.assertRaises(RuntimeError):
            self.reply('stop')
        self.assertEqual(self.ledger.request(self.request['id'])['state'], 'pending')
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'approved')
        self.reply('stop')
        self.reply('stop')
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'closed')
        self.assertEqual(self.kinds().count('plan.closed'), 1)
        self.assertEqual(self.kinds().count('request.applied'), 1)
        with self.assertRaisesRegex(LedgerError, 'Conflicting'):
            self.reply('continue')


class EntryRouteTests(Fixture):
    """Every entry route (`onecrew ledger request reply`, the MCP reply) goes through answer_effects.reply_and_apply."""

    def stopped(self, workflow=True):
        raw = plan_json(milestones=[milestone(argv=BAD, max_repairs=0)])
        plan.propose(self.ledger, 'P1', raw, 'codex', workflow=workflow,
                     capabilities=list(namespaces.CAPABILITIES) if workflow else None)
        plan.approve(self.ledger, 'P1', 'owner', 'fixture')
        verdict.run(self.ledger, 'P1', 'M1')
        task = plan.show(self.ledger, 'P1')['anchor_task']
        return task, self.ledger.requests(task, pending=True)[0]

    def cli_reply(self, req, choice='stop'):
        import contextlib, io
        from onecrew import ledger_cli
        out = io.StringIO()
        with patch.dict(os.environ, {'ONECREW_ACTOR': 'user'}), contextlib.redirect_stdout(out):
            code = ledger_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'request', 'reply',
                                    req['id'], '--revision', req['revision'], '--choice', choice, '--decided-by', 'user',
                                    '--reference', 'owner typed stop', '--json'])
        return code, json.loads(out.getvalue())

    def counts(self):
        kinds = self.kinds()
        return {k: kinds.count(k) for k in ('request.answered', 'request.applied', 'plan.closed')}

    def test_ledger_cli_reply_applies_stop_in_the_same_transaction(self):
        task, req = self.stopped()
        code, result = self.cli_reply(req)
        self.assertEqual(code, 0, result)
        self.assertEqual(result['choice'], 'stop')
        self.assertTrue(result['controller_effect']['applied'])
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'closed')
        self.assertEqual(self.counts(), {'request.answered': 1, 'request.applied': 1, 'plan.closed': 1})
        self.assertEqual(assert_no_answered_without_effect(self.ledger, task), [req['id']])
        self.assertEqual(self.cli_reply(req)[0], 0)                                  # same answer again: same receipt, no second close
        self.assertEqual(self.counts(), {'request.answered': 1, 'request.applied': 1, 'plan.closed': 1})

    def test_mcp_reply_applies_stop_in_the_same_transaction(self):
        from onecrew.mcp_entry import Server
        task, req = self.stopped()
        server = Server(self.ledger, True, 'user-terminal')
        result = server.call('reply', dict(request=req['id'], revision=req['revision'], choice='stop',
                                           reference='owner typed stop', decided_by='user'))
        self.assertEqual(result['provenance']['source'], 'user-terminal')
        self.assertTrue(result['controller_effect']['applied'])
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'closed')
        self.assertEqual(self.counts(), {'request.answered': 1, 'request.applied': 1, 'plan.closed': 1})
        self.assertEqual(assert_no_answered_without_effect(self.ledger, task), [req['id']])

    def test_legacy_root_via_ledger_cli_records_reply_only(self):
        task, req = self.stopped(workflow=False)
        code, result = self.cli_reply(req)
        self.assertEqual(code, 0, result)
        self.assertNotIn('controller_effect', result)
        self.assertFalse(result['action_applied'])
        self.assertEqual(self.ledger.request(req['id'])['state'], 'answered')
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'stopped_with_report')
        self.assertEqual(self.counts(), {'request.answered': 1, 'request.applied': 0, 'plan.closed': 0})
        self.assertEqual(assert_no_answered_without_effect(self.ledger, task), [])

    def test_crash_inside_effect_on_ledger_cli_route_rolls_back_reply(self):
        task, req = self.stopped()
        with _crash_on('request.applied'), self.assertRaises(RuntimeError):
            self.cli_reply(req)
        self.assertEqual(self.ledger.request(req['id'])['state'], 'pending')
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'stopped_with_report')
        self.assertEqual(self.counts(), {'request.answered': 0, 'request.applied': 0, 'plan.closed': 0})
        assert_no_answered_without_effect(self.ledger, task)

    def test_non_owner_reply_to_a_workflow_stop_is_refused_by_the_entry_route(self):
        from onecrew.mcp_entry import Server
        task, req = self.stopped()
        server = Server(self.ledger, True, 'claude-entry')
        with self.assertRaisesRegex(LedgerError, 'owner answer'):
            server.call('reply', dict(request=req['id'], revision=req['revision'], choice='stop', reference='entry decided', decided_by='entry'))
        self.assertEqual(self.ledger.request(req['id'])['state'], 'pending')
        self.assertEqual(self.counts(), {'request.answered': 0, 'request.applied': 0, 'plan.closed': 0})
