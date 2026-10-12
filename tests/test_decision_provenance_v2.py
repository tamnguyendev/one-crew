"""Decision provenance v2 (A2, 12/10/2026): who decided, through which channel, on whose words or delegation.

The user wants three sources kept apart: the user decided; Claude relayed the user's answer; Claude decided under a
delegation (or without one). A relay needs a reference to the user's words (only its hash is stored); a delegation
covers only its classes and time and never business/architecture/permission/budget decisions."""
import contextlib
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from onecrew import conversations as c
from onecrew import delegations as dg
from onecrew import eval_scorecard as sc
from onecrew import solution_gate as gate
from onecrew.cli import main
from onecrew.decision_provenance import SOURCES, source
from onecrew.eval_observe import DECISION_SOURCES, decision_source, observe
from onecrew.interventions import project_records
from onecrew.ledger import LedgerError
from onecrew.owned_intake import submit
from tests.test_autonomy_round2 import done
from tests.test_conversations import solution
from tests.test_interventions import LedgerFixture

QUOTE = 'Anh duyệt: lỗi mạng tạm thời thì cứ thử lại.'
QUOTE_SHA = hashlib.sha256(QUOTE.encode('utf-8')).hexdigest()
ZERO = dict.fromkeys(SOURCES, 0)


def recovery(cls):
    return {'schema_version': 1, 'question': 'Retry?', 'reason': 'Recovery needs a decision', 'impact': 'Root waits',
            'options': [{'id': 'retry', 'label': 'Retry'}, {'id': 'stop', 'label': 'Stop'}], 'recommendation': 'retry',
            'action': {'type': 'delivery.recovery', 'parameters': {'signature': 's', 'progress': 'p', 'node': 'n', 'class': cls, 'episode': 1}}}


def later(minutes):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutes)).isoformat()


class Base(unittest.TestCase):
    def setUp(self):
        self.f = LedgerFixture(self)
        self.ledger = self.f.ledger

    def cli(self, actor, *args):
        out = io.StringIO()
        env = {'ONECREW_ACTOR': actor} if actor else {}
        with patch.dict(os.environ, env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try: code = main(['--project', str(self.f.project), '--state-root', str(self.f.state_root), *args])
            except SystemExit as error: code = error.code  # argparse usage error
        text = out.getvalue()
        return code, (json.loads(text) if text.strip().startswith('{') else text)

    def reply(self, actor, request, *extra):
        return self.cli(actor, 'request', 'reply', request['id'], '--revision', request['revision'], '--choice', 'retry', '--json', *extra)

    def metrics(self, task):
        return observe(self.f.state_root, [task])['tasks'][0]['metrics']

    def grant(self, classes='transient,environment', actor='claude', until=None):
        return self.cli(actor, 'delegation', 'grant', '--reference', QUOTE, '--classes', classes, '--until', until or later(60))

    def stored(self):
        return b''.join(p.read_bytes() for p in self.f.state_root.glob('ledger.sqlite3*'))


class SourceTests(Base):
    def test_sources_enum(self):
        self.assertEqual(DECISION_SOURCES, ('user', 'relayed', 'delegated', 'undelegated', 'observed', 'unknown'))
        self.assertEqual(SOURCES, DECISION_SOURCES)
        ref = dg.reference(QUOTE)
        cases = [({'by': 'user'}, 'user'), ({'by': 'user', 'channel': 'user_direct', 'decided_by': 'user'}, 'user'),
                 ({'by': 'claude', 'decided_by': 'user'}, 'unknown'),  # a relay without the user's words
                 ({'by': 'claude', 'decided_by': 'user', 'channel': 'entry_relay', 'user_reference': ref}, 'relayed'),
                 ({'by': 'codex', 'decided_by': 'user', 'user_reference': dict(ref, quote_sha256='not-a-hash')}, 'unknown'),
                 ({'by': 'unknown', 'decided_by': 'user', 'user_reference': ref}, 'unknown'),
                 ({'by': 'claude', 'decided_by': 'entry'}, 'undelegated'),  # legacy 'entry' receipt
                 ({'decided_by': 'entry'}, 'undelegated'),
                 ({'basis': 'observed', 'by': 'onecrew'}, 'observed'), ({'basis': 'observed', 'by': 'claude'}, 'unknown'),
                 ({}, 'unknown'), (None, 'unknown')]
        for provenance, expected in cases:
            self.assertEqual(source(provenance), expected, provenance)
        self.assertEqual(decision_source({'provenance': {'decided_by': 'user'}}, 'user'), 'user')  # sender from the reply's record

    def test_reference_stores_a_hash_only(self):
        ref = dg.reference('  ' + QUOTE + '\n', 'window')
        self.assertEqual((ref['kind'], ref['quote_sha256']), ('window', QUOTE_SHA))
        self.assertTrue(dg.valid_reference(ref))
        for bad in ('', '   ', 'x' * 8001):
            with self.assertRaises(LedgerError): dg.reference(bad)
        with self.assertRaises(LedgerError): dg.reference(QUOTE, 'email')

    def test_decision_class_comes_from_the_request(self):
        self.assertEqual(dg.decision_class(recovery('transient')), 'transient')
        self.assertEqual(dg.decision_class({'action': {'type': 'job.effort_warning', 'parameters': {}}}), 'budget')
        self.assertEqual(dg.decision_class({'action': {'type': 'solution.slice_review', 'parameters': {}}}), 'business')
        self.assertIsNone(dg.decision_class({'action': {'type': 'noop', 'parameters': {}}}))
        self.assertIsNone(dg.decision_class(recovery('Not A Class!')))

    def test_observed_resolution_not_decision(self):
        task = self.f.task()
        with self.ledger.transaction(write=True) as conn:
            self.ledger._event(conn, task, 'request.resolved', {'request_id': 'REQ-x', 'basis': 'observed', 'by': 'onecrew'})
        m = self.metrics(task)
        self.assertEqual((m['decisions_answered'], m['decisions_by_source']), (1, dict(ZERO, observed=1)))
        fixture = done(decisions_answered=1, decisions_by_source=dict(ZERO, observed=1))
        self.assertEqual(sc.assistance_level(fixture), ('autonomous', []))


class ReplyTests(Base):
    def test_relay_requires_reference(self):
        task = self.f.task()
        bare, quoted = (self.ledger.create_request(task, 'q' + str(n), recovery('transient')) for n in range(2))
        code, receipt = self.reply('claude', bare, '--decided-by', 'user')
        self.assertEqual(code, 0)
        self.assertEqual((receipt['provenance']['channel'], receipt['provenance']['user_reference']), ('entry_relay', None))
        self.assertEqual(decision_source(receipt), 'unknown')
        code, receipt = self.reply('claude', quoted, '--decided-by', 'user', '--user-quote', QUOTE)
        self.assertEqual(code, 0)
        p = receipt['provenance']
        self.assertEqual((p['channel'], p['by'], p['decided_by'], p['decision_class']), ('entry_relay', 'claude', 'user', 'transient'))
        self.assertEqual((p['user_reference']['kind'], p['user_reference']['quote_sha256']), ('chat', QUOTE_SHA))
        self.assertEqual(decision_source(receipt), 'relayed')
        self.assertNotIn(QUOTE.encode('utf-8'), self.stored())  # the hash, never the words
        m = self.metrics(task)
        self.assertEqual(m['decisions_by_source'], dict(ZERO, relayed=1, unknown=1))
        self.assertIn('entry_relayed_decision', sc.assistance_level(observe(self.f.state_root, [task])['tasks'][0])[1])

    def test_user_typed_reply_is_user_direct(self):
        task = self.f.task(); request = self.ledger.create_request(task, 'q', recovery('product'))
        code, receipt = self.reply('user', request, '--user-quote', QUOTE)
        p = receipt['provenance']
        self.assertEqual((code, p['channel'], p['decided_by'], p['user_reference']['kind']), (0, 'user_direct', 'user', 'cli'))
        self.assertEqual(self.metrics(task)['decisions_by_source'], dict(ZERO, user=1))
        self.assertEqual(self.reply('user', request, '--decided-by', 'entry')[0], 2)  # a user reply is never an entry decision

    def test_mcp_reply_mirrors_cli(self):
        from onecrew.mcp_entry import Server
        task = self.f.root('root', 'waiting'); server = Server(self.ledger, True, 'claude-entry')
        request = self.ledger.create_request(task, 'q', recovery('environment'))
        with patch('onecrew.runner.status', return_value={'status': 'alive'}), patch('onecrew.keeper.ensure', return_value={}):
            with self.assertRaisesRegex(LedgerError, 'does not cover'):
                server.call('reply', dict(request=request['id'], revision=request['revision'], choice='retry', reference='r',
                                          delegation='DLG-' + '0' * 32))
            receipt = server.call('reply', dict(request=request['id'], revision=request['revision'], choice='retry',
                                                reference='user said retry', decided_by='user', user_quote=QUOTE))
        p = receipt['provenance']
        self.assertEqual((p['by'], p['channel'], p['user_reference']['quote_sha256']), ('claude', 'entry_relay', QUOTE_SHA))
        self.assertEqual(decision_source(receipt), 'relayed')


class DelegationTests(Base):
    def test_delegation_cli_grant_list_revoke(self):
        for classes in ('budget', 'transient,architecture', 'business', 'permission', 'Bad Class'):
            code, out = self.grant(classes)
            self.assertEqual(code, 2, classes)
        self.assertIn("stay the user's", self.grant('transient,budget')[1]['error'])
        self.assertEqual(self.grant(until=later(-1))[0], 2)
        self.assertEqual(self.grant(until=later(60 * 24 * 31))[0], 2)
        self.assertEqual(self.grant(until='2026-12-01T00:00:00')[0], 2)  # no timezone
        self.assertEqual(self.cli('claude', 'delegation', 'grant', '--classes', 'transient', '--until', later(60))[0], 2)  # needs the quote (argparse)
        until = later(60)
        code, granted = self.grant(until=until)
        self.assertEqual(code, 0)
        self.assertRegex(granted['id'], r'^DLG-[0-9a-f]{32}$')
        self.assertEqual((granted['classes'], granted['by'], granted['channel']), (['environment', 'transient'], 'claude', 'entry_relay'))
        self.assertEqual(granted['user_reference']['quote_sha256'], QUOTE_SHA)
        self.assertNotIn(QUOTE.encode('utf-8'), self.stored())
        self.assertEqual(self.grant(until=until)[1]['id'], granted['id'])  # replay
        self.assertEqual([d['id'] for d in self.cli(None, 'delegation', 'list')[1]['delegations']], [granted['id']])
        code, revoked = self.cli('user', 'delegation', 'revoke', granted['id'])
        self.assertEqual((code, revoked['revoked']['by']), (0, 'user'))
        self.assertEqual(self.cli(None, 'delegation', 'list')[1]['delegations'], [])
        everything = self.cli(None, 'delegation', 'list', '--all')[1]['delegations']
        self.assertEqual([(d['id'], d['active']) for d in everything], [(granted['id'], False)])
        rows = [(r['command'], r['actor'], r['scope'], r['scope_id']) for r in project_records(self.ledger, 'delegation')]
        self.assertEqual(rows, [('delegation.grant', 'claude', 'delegation', granted['id']), ('delegation.revoke', 'user', 'delegation', granted['id'])])
        self.assertNotEqual(self.grant(until=later(90))[1]['id'], granted['id'])  # another end is another grant

    def test_delegated_requires_scope(self):
        task = self.f.task()
        delegation = self.grant('transient')[1]['id']
        covered, product, budget = (self.ledger.create_request(task, cls, recovery(cls)) for cls in ('transient', 'product', 'budget'))
        code, receipt = self.reply('claude', covered, '--decided-by', 'entry', '--delegation', delegation)
        p = receipt['provenance']
        self.assertEqual((code, p['channel'], p['delegation'], p['decision_class'], p['decided_by']),
                         (0, 'entry_delegated', delegation, 'transient', 'entry'))
        for request in (product, budget):
            code, out = self.reply('claude', request, '--decided-by', 'entry', '--delegation', delegation)
            self.assertEqual(code, 2); self.assertIn('does not cover', out['error'])
            self.assertEqual(self.ledger.request(request['id'])['state'], 'pending')
        self.assertEqual(self.reply('claude', product, '--decided-by', 'user', '--delegation', delegation)[0], 2)
        self.assertEqual(self.reply('user', product, '--delegation', delegation)[0], 2)  # only an entry decides under a delegation
        self.assertEqual(self.reply('claude', product, '--decided-by', 'entry')[1]['provenance']['channel'], 'entry_undelegated')
        observed = observe(self.f.state_root, [task])['tasks'][0]
        self.assertEqual(observed['metrics']['decisions_by_source'], dict(ZERO, delegated=1, undelegated=1))
        reasons = sc.assistance_level(observed)[1]
        self.assertIn('entry_delegated_decision', reasons); self.assertIn('entry_undelegated_decision', reasons)

    def test_out_of_scope_is_undelegated(self):
        start = dt.datetime(2026, 10, 12, 8, 0, tzinfo=dt.timezone.utc)
        at = lambda minutes: (start + dt.timedelta(minutes=minutes)).isoformat()
        record = {'classes': ['transient', 'budget'], 'granted_at': at(0), 'until': at(60), 'user_reference': dg.reference(QUOTE), 'revoked': None}
        did = 'DLG-' + 'a' * 32
        claim = lambda cls, by='claude': {'by': by, 'decided_by': 'entry', 'channel': 'entry_delegated', 'delegation': did, 'decision_class': cls}
        self.assertEqual(source(claim('transient'), None, {did: record}, at(10)), 'delegated')
        for provenance, delegations, moment in ((claim('transient'), {did: record}, at(61)),  # expired
                                                (claim('transient'), {did: record}, at(-1)),  # before the grant
                                                (claim('product'), {did: record}, at(10)),  # class not delegated
                                                (claim('budget'), {did: record}, at(10)),  # never delegable, even if listed
                                                (claim(None), {did: record}, at(10)),  # class unknown
                                                (claim('transient'), {}, at(10)),  # delegation not recorded
                                                (claim('transient'), None, at(10)),
                                                (claim('transient', 'user'), {did: record}, at(10)),
                                                (claim('transient'), {did: dict(record, user_reference=None)}, at(10))):
            self.assertEqual(source(provenance, None, delegations, moment), 'undelegated', (provenance, moment))
        revoked = dict(record, revoked={'at': at(5), 'by': 'user', 'user_reference': None})
        self.assertEqual(source(claim('transient'), None, {did: revoked}, at(10)), 'undelegated')
        self.assertEqual(source(claim('transient'), None, {did: revoked}, at(1)), 'delegated')  # revocation is not retroactive


class ContractDecisionTests(Base):
    def contract(self, approve_actor='claude', *extra):
        cid = c.create(self.ledger, 'Contract', 'contract-' + str(len(extra)) + approve_actor, 'fixture')['id']
        sol = c.propose(self.ledger, cid, 'solution', solution(), 'fixture')
        code, decision = self.cli(approve_actor, 'solution', 'approve', sol['id'], '--revision', sol['revision'], '--source', 'chat',
                                  '--reference', 'chat 12/10 10:00', *extra)
        self.assertEqual(code, 0, decision)
        task = submit(self.ledger, 'Fix arithmetic', 'job-' + cid[-8:], mode='change', provider='claude', model='sonnet',
                      image='sha256:' + 'a' * 64, solution_id=sol['id'], solution_revision=sol['revision'])['id']
        return cid, sol, decision, task

    def test_sol_approval_provenance(self):
        cid, sol, decision, task = self.contract('claude', '--decided-by', 'user', '--user-quote', QUOTE)
        self.assertEqual((decision['decision']['channel'], decision['decision']['user_reference']['quote_sha256']), ('entry_relay', QUOTE_SHA))
        self.assertEqual(decision['decision']['decision_class'], 'business')
        m = self.metrics(task)
        # The first approval is the handoff: reported as such, never counted as an entry decision.
        self.assertEqual((m['handoff_approval'], m['decisions_by_source']['relayed'], m['decisions_answered']), ('relayed', 0, 0))
        self.assertNotIn('entry_relayed_decision', sc.assistance_level(observe(self.f.state_root, [task])['tasks'][0])[1])
        rows = project_records(self.ledger, 'solution', sol['id'])
        self.assertEqual([(r['command'], r['actor']) for r in rows], [('solution.approve', 'claude')])
        code, again = self.cli('claude', 'solution', 'approve', sol['id'], '--revision', sol['revision'], '--source', 'chat',
                               '--reference', 'chat 12/10 11:00', '--decided-by', 'user', '--user-quote', QUOTE)
        self.assertEqual(code, 0)
        observed = observe(self.f.state_root, [task])['tasks'][0]
        self.assertEqual(observed['metrics']['repeat_approvals'], dict(ZERO, relayed=1))
        level, reasons = sc.assistance_level(observed)
        self.assertEqual(level, 'assisted'); self.assertIn('repeat_handoff', reasons); self.assertIn('entry_relayed_decision', reasons)

    def test_sol_approval_without_or_against_provenance(self):
        _, _, _, legacy = self.contract('claude')  # no decided_by: who approved cannot be shown
        observed = observe(self.f.state_root, [legacy])['tasks'][0]
        self.assertEqual(observed['metrics']['handoff_approval'], 'unknown')
        self.assertIn('decision_provenance_unknown', sc.assistance_level(observed)[1])
        _, _, _, entry = self.contract('codex', '--decided-by', 'entry')  # the entry approving for the user
        observed = observe(self.f.state_root, [entry])['tasks'][0]
        self.assertEqual(observed['metrics']['handoff_approval'], 'undelegated')
        self.assertIn('entry_undelegated_decision', sc.assistance_level(observed)[1])
        _, _, _, user = self.contract('user')
        self.assertEqual(self.metrics(user)['handoff_approval'], 'user')

    def test_creq_reply_provenance(self):
        cid, sol, _, task = self.contract('user')
        first = gate.question(self.ledger, cid, 'q1', 'Keep the API?', 'Contract question', [task], 'claude')
        answer = Path(self.f.base / 'answer.json')
        answer.write_text(json.dumps({'qid': first['id'], 'revision': first['revision'], 'choice': 'continue_unchanged',
                                      'source': 'terminal', 'reference': 'typed by the user'}), encoding='utf-8')
        code, reply = self.cli('user', 'conversation', 'reply', '--file', str(answer))
        self.assertEqual((code, reply['answer']['decision']['channel'], reply['affected_tasks']), (0, 'user_direct', [task]))
        self.assertEqual(self.cli('user', 'conversation', 'reply', '--file', str(answer))[0], 0)  # replay is the same answer
        second = gate.question(self.ledger, cid, 'q2', 'Stop?', 'Scope question', [task], 'claude')
        gate.reply(self.ledger, second['id'], second['revision'], 'continue_unchanged', 'codex', 'no provenance recorded')
        m = self.metrics(task)
        self.assertEqual((m['decisions_answered'], m['decisions_by_source']), (2, dict(ZERO, user=1, unknown=1)))
        replies = [e['payload'] for e in self.f.events(task, 'control.intervention')]
        self.assertEqual([(r['command'], r['actor']) for r in replies], [('conversation.reply', 'user')])


if __name__ == '__main__':
    unittest.main()
