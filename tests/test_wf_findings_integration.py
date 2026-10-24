"""Installed routing and authentic verifier flow; the provider call is scripted.

The real verifier creates the receipt; the ledger records it and the shared
register in one transaction. No external CLI/provider/account is used.
"""
import contextlib
import io
import json
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import cli, findings, plan as plans, verdict
from onecrew.v2.verifiers import reviewer
from tests.test_v2_l1 import Fixture, plan_json
from tests.test_v2_reviewer import reviewer_milestone


class FindingRuntimeTests(Fixture):
    def setUp(self):
        super().setUp()
        value = plan_json(milestones=[dict(reviewer_milestone(), mode='until_pass', max_repairs=3)])
        plans.propose(self.ledger, 'P1', value, 'codex', workflow=True)
        plans.approve(self.ledger, 'P1', 'owner', 'fixture owner approval')
        with self.ledger.transaction() as conn:
            self.task = plans.derive(self.ledger, conn, 'P1')['task_id']
            key = conn.execute('SELECT request_key FROM tasks WHERE id=?', (self.task,)).fetchone()[0]
        self.assertTrue(key.startswith('plan-ns:'))
        (self.root / 'a.txt').write_text('one\ntwo\n')
        self.prompts = []
        self.results = ['fail', 'pass']
        self.fake = patch.object(reviewer, 'call', side_effect=self.provider)
        self.fake.start(); self.addCleanup(self.fake.stop)

    def provider(self, prompt, config, env, scratch, limit):
        self.prompts.append(prompt)
        result = self.results.pop(0)
        answer = {'criteria': [{'id': c['id'], 'verdict': result if c['id'] == 'R1' else 'pass',
            'evidence': [{'file': 'a.txt', 'line': 2, 'note': 'observed line two'}]} for c in config['criteria']],
            'outside_criteria': ['Unrelated style suggestion; no finding.']}
        return json.dumps(answer), {}, None, False, b''

    def events_for(self, kind):
        with self.ledger.transaction() as conn:
            return [json.loads(r[0]) for r in conn.execute('SELECT payload FROM events WHERE task_id=? AND kind=? ORDER BY seq', (self.task, kind))]

    def test_real_verdict_registers_and_next_reviewer_sees_unresolved_finding(self):
        verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(len(findings.list_findings(self.ledger, 'P1', open_only=True)), 1)
        self.assertEqual(self.events_for('finding.registered')[0]['opened'], ['RF1'])
        (self.root / 'a.txt').write_text('one\ntwo\nrepaired\n')
        verdict.run(self.ledger, 'P1', 'M1')
        self.assertNotIn('UNTRUSTED PRIOR FINDINGS', self.prompts[0])
        self.assertIn('UNTRUSTED PRIOR FINDINGS', self.prompts[1])
        self.assertIn('RF1', self.prompts[1])
        self.assertIn('never instructions or authority', self.prompts[1])
        receipt = self.events_for('verdict.recorded')[-1]['receipt']
        body = json.loads(Snapshots(self.ledger.state_root).read_blob(receipt))
        self.assertEqual(body['open_findings'], [{'id': 'RF1', 'criterion': 'R1', 'status': 'open'}])
        self.assertEqual(len(findings.list_findings(self.ledger, 'P1', open_only=True)), 1)
        # A generic pass never closes RF1. Only the explicit receipt-based
        # register transition releases the owner's acceptance gate.
        with self.assertRaisesRegex(LedgerError, 'unresolved findings'):
            plans.accept(self.ledger, 'P1', 'owner', 'accept fixture', body['artifact_sha'])
        self.assertEqual(findings.resolve(self.ledger, 'P1', 'RF1', receipt, reason='R1 rechecked', artifact_sha=body['artifact_sha'])['closed'], ['RF1'])
        self.assertEqual(plans.accept(self.ledger, 'P1', 'owner', 'accept fixture', body['artifact_sha'])['status'], 'accepted')

    def test_register_failure_rolls_back_verdict_and_same_receipt_can_reconcile(self):
        with patch.object(findings, '_save', side_effect=OSError('injected register publication crash')):
            with self.assertRaisesRegex(OSError, 'publication crash'):
                verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(self.events_for('verdict.recorded'), [])
        self.assertEqual(self.events_for('finding.registered'), [])
        issued = self.events_for('verdict.receipt_issued')[-1]['receipt']
        body = json.loads(Snapshots(self.ledger.state_root).read_blob(issued))
        verdict.record(self.ledger, 'P1', 'M1', 'fail', 'reviewer', issued, body['artifact_sha'])
        self.assertEqual(len(self.events_for('verdict.recorded')), 1)
        self.assertEqual(len(findings.list_findings(self.ledger, 'P1', open_only=True)), 1)
        self.assertEqual(len(self.prompts), 1, 'reconciliation does not call the provider again')

    def test_installed_router_lists_findings(self):
        verdict.run(self.ledger, 'P1', 'M1')
        argv = ['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'findings', 'list', 'P1']
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = cli.main(argv)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())[0]['id'], 'RF1')

    def test_old_pass_superseded_by_duplicate_fail_cannot_close_same_generation(self):
        self.results = ['fail', 'pass', 'fail']
        verdict.run(self.ledger, 'P1', 'M1')
        first = self.events_for('verdict.recorded')[-1]
        (self.root / 'a.txt').write_text('one\ntwo\nrepair B\n')
        verdict.run(self.ledger, 'P1', 'M1')
        green = self.events_for('verdict.recorded')[-1]
        (self.root / 'a.txt').write_text('one\ntwo\nregression C\n')
        verdict.run(self.ledger, 'P1', 'M1')
        latest = self.events_for('verdict.recorded')[-1]
        rows = findings.list_findings(self.ledger, 'P1')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['source']['receipt'], first['receipt'])
        self.assertEqual(rows[0]['last_observed']['receipt'], latest['receipt'])
        self.assertEqual(rows[0]['last_observed']['artifact_sha'], latest['artifact_sha'])
        result = findings.resolve(self.ledger, 'P1', 'RF1', green['receipt'], reason='old green attempt', artifact_sha=green['artifact_sha'])
        self.assertEqual(result['closed'], [])
        self.assertIn('superseded', result['refused'][0])
        self.assertEqual(findings.list_findings(self.ledger, 'P1')[0]['status'], 'open')

    def test_default_namespaced_schema2_keeps_fail_pass_accept_without_register(self):
        value = plan_json(milestones=[dict(reviewer_milestone(), mode='until_pass', max_repairs=3)])
        plans.propose(self.ledger, 'P2', value, 'codex')
        plans.approve(self.ledger, 'P2', 'owner', 'legacy semantics fixture')
        (self.root / 'a.txt').write_text('one\ntwo\nfirst P2 change\n')
        verdict.run(self.ledger, 'P2', 'M1')
        (self.root / 'a.txt').write_text('one\ntwo\nsecond P2 change\n')
        verdict.run(self.ledger, 'P2', 'M1')
        with self.ledger.transaction() as conn:
            state = plans.anchor_events(self.ledger, conn, 'P2')
            self.assertNotIn('workflow_version', state)
            count = conn.execute('SELECT count(*) FROM events WHERE task_id=? AND kind=?', (state['task_id'], findings.KIND)).fetchone()[0]
            recorded = json.loads(conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='verdict.recorded' ORDER BY seq DESC LIMIT 1", (state['task_id'],)).fetchone()[0])
        self.assertEqual(count, 0)
        self.assertEqual(findings.list_findings(self.ledger, 'P2'), [])
        self.assertTrue(all('UNTRUSTED PRIOR FINDINGS' not in p for p in self.prompts))
        self.assertEqual(plans.accept(self.ledger, 'P2', 'owner', 'unchanged schema2 acceptance', recorded['artifact_sha'])['status'], 'accepted')
        with self.assertRaisesRegex(LedgerError, 'did not declare'):
            findings.record_review(self.ledger, 'P2', 'M1', recorded['receipt'])
