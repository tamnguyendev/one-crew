"""Real scoped files and public survey consumer; provider calls are explicit fakes."""
import contextlib
import io
import json
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import cli, plan, survey, survey_worker
from tests.test_v2_l3 import Step0
from tests.test_wf_r01_step0_survey import scoped_plan, tree_hash


class SurveyWorkerTests(Step0):
    def setUp(self):
        super().setUp()
        self.propose('P1', scoped_plan())
        (self.root / 'source.txt').write_text('The report is read by the nightly job.\n', encoding='utf-8')
        self.opened = survey.open_survey(self.ledger, 'P1', 'U1', {
            'cap': {'minutes': 1, 'calls': 2}, 'end_condition': 'Cite the actual consumer in source.txt',
            'scope': {'mode': 'read_only', 'paths': ['source.txt']}})
        self.config = {'provider': 'codex', 'model': 'fixture-model', 'paths': ['source.txt']}
        self.calls = []
        self.answer = {'answer': 'The nightly job reads the report.', 'evidence': 'source.txt:1',
            'quote': 'read by the nightly job', 'hypothesis': 'refuted', 'confidence': 'high', 'resolved': True}

    def provider(self, prompt, config, env, scratch, limit):
        self.calls.append((prompt, config, limit))
        self.assertGreater(limit, 0); self.assertLessEqual(limit, 1)
        self.assertEqual(list(Path(scratch).iterdir()), [])
        return json.dumps(self.answer), {}, None, False, b'fixture provider envelope'

    def run_worker(self, **kwargs):
        return survey_worker.run(self.ledger, 'P1', self.opened['id'], self.config, call=kwargs.get('call', self.provider))

    def test_actual_cli_consumer_pins_model_retains_evidence_and_never_repeats_finished_call(self):
        source = self.root.parent / 'worker.json'; source.write_text(json.dumps(self.config))
        before = tree_hash(self.root)
        out = io.StringIO()
        with patch('onecrew.v2.verifiers.reviewer.call', side_effect=self.provider), contextlib.redirect_stdout(out):
            status = cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root),
                               'plan', 'survey', 'run', 'P1', self.opened['id'], '--file', str(source)])
        self.assertEqual(status, 0, out.getvalue())
        result = json.loads(out.getvalue()); self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['spent']['calls'], 2)
        self.assertEqual(self.run_worker()['status'], 'answered'); self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][1]['model'], 'fixture-model')
        self.assertEqual(tree_hash(self.root), before)
        finished = next(p for k, p in self.events('P1') if k == 'survey.finished')
        store = Snapshots(self.ledger.state_root)
        log = json.loads(store.read_blob(finished['log']))
        ref = next(op['receipt'] for op in log['ops'] if op['op'] == 'worker_receipt')
        receipt = json.loads(store.read_blob(ref))
        self.assertEqual((receipt['provider'], receipt['calls']), ('codex', 1))
        self.assertIn('source.txt', receipt['inputs'])

    def test_invented_citation_is_blocked_without_closing_unknown(self):
        self.answer['evidence'] = 'source.txt:999'
        result = self.run_worker()
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('quote', result['blocker']['detail'])
        unknown = plan.show(self.ledger, 'P1')['contract']['understanding']['unknowns'][0]
        self.assertEqual(unknown['status'], 'open')

    def test_outside_scope_cannot_call_provider(self):
        self.config['paths'] = ['outside.txt']
        result = self.run_worker()
        self.assertEqual(result['status'], 'blocked'); self.assertEqual(self.calls, [])

    def test_insufficient_cap_is_refused_before_a_launch_intent(self):
        self.config['paths'] = ['source.txt', 'a.txt']
        with self.assertRaisesRegex(LedgerError, 'cap must cover'): self.run_worker()
        self.assertNotIn(survey_worker.STARTED, self.kinds('P1'))
        self.assertEqual(self.calls, [])

    def test_timeout_retains_blocker_and_does_not_switch_provider(self):
        def timeout(*args):
            self.calls.append(args)
            return '', {}, None, True, b'fixture timeout'
        result = self.run_worker(call=timeout)
        self.assertEqual(result['status'], 'blocked'); self.assertEqual(len(self.calls), 1)
        self.assertIn('timeout', result['blocker']['detail'])

    def test_crash_after_durable_intent_cannot_blindly_launch_again(self):
        with patch.object(survey, 'run', side_effect=OSError('fixture crash after claim')):
            with self.assertRaises(OSError): self.run_worker()
        with self.assertRaisesRegex(LedgerError, 'reconcile'): self.run_worker()
        self.assertEqual(self.calls, [])
