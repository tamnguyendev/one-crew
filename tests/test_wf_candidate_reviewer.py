"""Candidate reviewer: an approved reviewer milestone runs on the node's candidate tree.

Independence is judged against the proposal author AND the actual producing child
model; the call goes through the metered root budget; the retained proof is a
reviewer receipt the native learning loader understands. The provider is a fixture
function standing in for reviewer.call (interface only; no real CLI is proven here).
"""
import contextlib
import io
import json
import os
import sys
from unittest.mock import patch

from onecrew import budget_core, cli
from onecrew.common_verification import CandidateChecker
from onecrew.ledger import LedgerError
from onecrew.v2 import incidents, plan
from onecrew.v2.verifiers import reviewer
from tests.test_v2_l1 import milestone
from tests.test_v2_reviewer import reviewer_milestone, answer, row
from tests.test_wf_candidate_handoff import CandidateFixture

CRITERIA = [{'id': 'R1', 'question': 'Does a.txt hold the candidate line (cite file:line)?'}]


class CandidateReviewerFixture(CandidateFixture):
    producer = {'role': 'worker', 'provider': 'codex', 'model': 'gpt-6.1-sol'}

    def milestones(self):
        check = [sys.executable, '-c', 'from pathlib import Path; assert Path("a.txt").read_text()=="candidate\\n"; print("candidate tested")']
        return [milestone('M1', argv=check), dict(reviewer_milestone(criteria=CRITERIA), id='M2')]

    def produce(self):
        definition = self.definition()
        for item in definition: item['executor'] = dict(self.producer)
        self.revise(definition)
        def factory(control, provider):
            class Worker:
                def capability(self): return {'provider': provider, 'mode': 'fixture-tools-disabled'}
                def run(self, attempt, prompt, schema, profile):
                    control.launched(attempt['id'], attempt['generation'], {'fixture': True})
                    control.finish(attempt['id'], attempt['generation'], {'exit_code': 0})
                def result(self, attempt):
                    return {'summary': 'producer', 'files': [{'path': 'a.txt', 'content': 'candidate\n'}], 'backlog': []}, []
            return Worker()
        with patch('onecrew.artifact_provider_core.make_worker', side_effect=factory):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'engine', 'step', 'plan-ns:P1'])
            self.assertEqual(code, 0, out.getvalue())

    def counters(self):
        with self.ledger.transaction() as conn:
            root = plan.anchor_events(self.ledger, conn, 'P1')
            return budget_core.group(conn, root['task_id'])

    def fake_call(self, calls):
        def fake(prompt, config, env, scratch, limit):
            calls.append({'prompt': prompt, 'config': config, 'limit': limit})
            return answer(row('R1')), {}, None, False, b'fixture'
        return fake


class CandidateReviewerTests(CandidateReviewerFixture):
    def test_reviewer_milestone_runs_on_candidate_with_independence_from_actual_producer(self):
        self.produce()
        before = self.counters()['used_calls']        # the producing child already charged the root group
        calls = []
        with patch.object(reviewer, 'call', side_effect=self.fake_call(calls)):
            result = self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.assertEqual(result['result'], 'pass', result)
        rows = {r['id']: r for r in result['observed']['checks']}
        self.assertEqual({k: v['result'] for k, v in rows.items()}, {'M1': 'pass', 'M2': 'pass'})
        wrapper = json.loads(self.store.read_blob(rows['M2']['evidence']))
        self.assertEqual(wrapper['kind'], 'candidate-reviewer-check')
        proof = json.loads(self.store.read_blob(wrapper['reviewer_receipt']))
        self.assertEqual((proof['kind'], proof['provider'], proof['model'], proof['role']), ('reviewer-receipt', 'claude', 'claude-haiku-5-5', 'reviewer'))
        self.assertEqual(proof['artifact_sha'], result['observed']['candidate_tree'])
        self.assertEqual(proof['calls'], 1)
        # independence: weakest level over proposal author and the ACTUAL producer (codex child), both recorded
        self.assertEqual(proof['independence']['level'], 'cross_vendor')
        self.assertEqual([p['provider'] for p in proof['independence']['producers']], ['codex'])
        self.assertEqual(len(calls), 1)
        # the diff the reviewer saw starts from the real approval base and shows the candidate change
        self.assertIn('candidate', calls[0]['prompt'])
        # the call was admitted through the shared root budget: exactly one more call charged
        self.assertEqual(self.counters()['used_calls'], before + 1)
        self.assertEqual((self.root / 'a.txt').read_text(), 'one\n')

    def test_producer_on_the_reviewer_model_is_refused_before_any_call(self):
        self.producer = {'role': 'worker', 'provider': 'claude', 'model': 'claude-haiku-5-5'}
        self.produce()
        before = self.counters()['used_calls']
        with patch.object(reviewer, 'call', side_effect=AssertionError('independence must be refused before the call')):
            with self.assertRaisesRegex(LedgerError, 'reviewer would be the author'):
                self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.assertEqual(self.counters()['used_calls'], before)        # refused before any metered call

    def test_failed_reviewer_verdict_fails_the_node_and_learning_reads_the_typed_proof(self):
        self.produce()
        def failing(prompt, config, env, scratch, limit):
            return answer(row('R1', 'fail')), {}, None, False, b'fixture'
        with patch.object(reviewer, 'call', side_effect=failing):
            result = self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        rows = {r['id']: r['result'] for r in result['observed']['checks']}
        self.assertEqual(rows['M2'], 'fail')
        self.assertNotEqual(result['result'], 'pass')
        receipt = self.engine.state(self.ledger, 'P1')['nodes']['C']['verification_receipt']
        with self.ledger.transaction() as conn:
            state = plan.anchor_events(self.ledger, conn, 'P1')
            proof, outcome, _, _ = incidents._node_receipt(self.ledger, conn, state, receipt, json.loads(self.store.read_blob(receipt)), latest=True)
        kinds = {c['id']: c['kind'] for c in proof['supported_checks']}
        self.assertEqual(kinds.get('M2'), 'candidate-reviewer-check')
        self.assertEqual(outcome, result['result'])

    def test_provider_error_keeps_the_node_inconclusive_not_failed(self):
        self.produce()
        def quota(prompt, config, env, scratch, limit):
            return '', {}, 'quota_exhausted: fixture', False, b''
        with patch.object(reviewer, 'call', side_effect=quota):
            result = self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        rows = {r['id']: r['result'] for r in result['observed']['checks']}
        self.assertEqual(rows['M2'], 'inconclusive')
        self.assertEqual(result['result'], 'inconclusive')
