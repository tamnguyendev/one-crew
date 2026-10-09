import json
import datetime as dt
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger, LedgerError
from onecrew.model_preferences import save, read
from onecrew.owned_intake import submit
from onecrew.owned import Owned
from onecrew.provider_limits import QuotaExhausted, check_event, check_attempt
from onecrew.provider_fallback import advance
from tests.test_workflow import FixtureWorker
from tests.test_owned import action

CHAIN = [{'provider': 'codex', 'model': 'gpt-6.1-sol'}, {'provider': 'kiro', 'model': 'claude-sonnet-5'}]


class Worker(FixtureWorker):
    def __init__(self, ledger, provider, responses):
        super().__init__(ledger, responses)
        self.provider = provider
        self.models = []

    def capability(self):
        return {'provider': self.provider, 'mode': 'fixture-only'}

    def run(self, attempt, prompt, schema, profile):
        self.models.append(profile['model'])
        super().run(attempt, prompt, schema, profile)

    def result(self, attempt):
        value, usage = super().result(attempt)
        if value == 'quota': raise QuotaExhausted(self.provider)
        if isinstance(value, str): raise LedgerError(value)
        return value, usage


class FallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)/'project'; self.root.mkdir()
        (self.root/'calc.py').write_text('x = 42\n')
        self.ledger = Ledger(self.root, Path(self.tmp.name)/'state')
        save(self.ledger, 'claude', 'sonnet', fallbacks=CHAIN)
        self.workers = {p: Worker(self.ledger, p, []) for p in ('claude', 'codex', 'kiro')}
        patcher = patch('onecrew.providers.make_worker', side_effect=lambda control, provider: self.workers[provider])
        patcher.start(); self.addCleanup(patcher.stop)

    def runtime(self, **options):
        task = submit(self.ledger, 'Inspect calc.py', 'inspect', **options)
        run = Owned(self.ledger); run.enable(task['id'])
        return run, task['id']

    def test_policy_replay_explicit_pin_and_old_schema(self):
        run, task = self.runtime()
        old = self.ledger.task(task, full=True)['handoff']['owned_execution']
        save(self.ledger, 'kiro', 'different')
        self.assertEqual(submit(self.ledger, 'Inspect calc.py', 'inspect')['id'], task)
        self.assertEqual(old['fallbacks'], CHAIN)
        for index, kwargs in enumerate(({'provider': 'claude'}, {'model': 'opus'})):
            save(self.ledger, 'claude', 'sonnet', fallbacks=CHAIN)
            pinned = submit(self.ledger, 'Inspect', 'pinned-'+str(index), **kwargs)
            self.assertNotIn('fallbacks', self.ledger.task(pinned['id'], full=True)['handoff']['owned_execution'])
        save(self.ledger, 'claude', 'sonnet')
        self.assertNotIn('fallbacks', read(self.ledger))
        for invalid in (CHAIN*2, [{'provider':'claude','model':'opus'}], [{'provider':'codex','model':''}]):
            with self.assertRaises(LedgerError): save(self.ledger, 'claude', 'sonnet', fallbacks=invalid)

    def test_forward_chain_restart_keeps_checkpoint_budget_and_outcome(self):
        self.workers['claude'].responses = [action('read', path='calc.py'), 'quota']
        self.workers['codex'].responses = ['quota']
        self.workers['kiro'].responses = [action('finish', report='calc.py sets x to 42; no tests run.'),
                                        {'accepted': True, 'feedback': 'Consistent.'}]
        run, task = self.runtime(max_calls=8)
        deadline = run.control.status(task)['deadline']
        state = run.run(task, steps=2)
        self.assertEqual(state['worker']['provider'], 'codex')
        self.assertEqual(len(state['receipts']), 1)
        self.assertEqual(state['step'], 1)
        snapshot = state['snapshot']
        # Mutable operator preferences cannot replace the sealed fallback policy.
        save(self.ledger, 'claude', 'opus', fallbacks=[])
        restored = Owned(self.ledger)
        state = restored.run(task)
        self.assertEqual(state['phase'], 'completed')
        self.assertEqual(state['snapshot'], snapshot)
        self.assertEqual(state['worker']['provider'], 'kiro')
        self.assertEqual([h['to']['provider'] for h in state['handoffs']], ['codex', 'kiro'])
        status = restored.control.status(task)
        self.assertEqual(status['used_calls'], 5)
        self.assertEqual(status['deadline'], deadline)
        self.assertEqual(self.workers['codex'].models, ['gpt-6.1-sol'])
        self.assertEqual(self.workers['kiro'].models, ['claude-sonnet-5']*2)
        self.assertEqual((self.root/'calc.py').read_text(), 'x = 42\n')
        from onecrew.learning import outcomes
        outcome = outcomes(self.ledger)[0]
        self.assertEqual(outcome['provider'], 'kiro')
        self.assertEqual(len(outcome['provider_handoffs']), 2)
        self.assertEqual([json.loads(a['operation'])['provider'] for a in status['attempts']],
                         ['claude','claude','codex','kiro','kiro'])

    def test_review_handoff_does_not_redo_action(self):
        self.workers['claude'].responses = [action('read', path='calc.py'), action('finish', report='calc.py sets x = 42. No tests run.'), 'quota']
        self.workers['codex'].responses = [{'accepted': True, 'feedback': 'Verified source report.'}]
        run, task = self.runtime()
        state = run.run(task, steps=2)
        self.assertEqual(state['response']['action'], 'finish')
        state = Owned(self.ledger).run(task)
        self.assertEqual(state['phase'], 'completed')
        self.assertEqual(self.workers['codex'].calls, ['owned_review'])
        self.assertEqual([r['action'] for r in state['receipts']], ['read', 'finish'])

    def test_budget_never_resets_on_switch(self):
        self.workers['claude'].responses = ['quota']
        self.workers['codex'].responses = ['quota']
        run, task = self.runtime(max_calls=2)
        state = run.run(task)
        self.assertEqual(state['phase'], 'blocked')
        self.assertEqual(run.control.status(task)['used_calls'], 2)
        self.assertFalse(self.workers['kiro'].calls)

    def test_all_exhausted_stops_without_looping(self):
        for worker in self.workers.values(): worker.responses = ['quota']
        run, task = self.runtime()
        state = run.run(task)
        self.assertEqual(state['phase'], 'blocked')
        self.assertEqual(run.control.status(task)['used_calls'], 3)
        self.assertEqual(len(state['handoffs']), 2)

    def test_unavailable_backup_is_skipped_without_inference(self):
        self.workers['claude'].responses = ['quota']
        self.workers['kiro'].responses = [action('read', path='calc.py')]
        run, task = self.runtime()
        with patch.object(self.workers['codex'], 'capability', side_effect=LedgerError('Authentication unavailable')):
            state = run.run(task, steps=2)
        self.assertEqual(state['worker']['provider'], 'kiro')
        self.assertEqual(len(state['handoffs'][0]['skipped']), 1)
        self.assertFalse(self.workers['codex'].calls)

    def test_nonquota_and_pinned_jobs_do_not_switch(self):
        for error in ('Authentication failed', 'HTTP 429', 'Docker SDK unavailable', 'timeout'):
            with self.subTest(error=error):
                self.assertIsNone(advance(None, '', 0, {}, LedgerError(error)))
        self.workers['claude'].responses = ['quota']
        run, task = self.runtime(provider='claude')
        state = run.run(task)
        self.assertEqual(state['phase'], 'blocked')
        self.assertNotIn('handoffs', state)
        self.assertFalse(self.workers['codex'].calls)

    def test_unknown_process_blocks_switch(self):
        self.workers['claude'].responses = ['quota']
        run, task = self.runtime()
        def unknown(attempt, prompt, schema, profile):
            run.control.launched(attempt['id'], attempt['generation'], {'fixture': True})
            run.control.unknown(attempt['id'], 'death unconfirmed')
            raise QuotaExhausted('claude')
        with patch.object(self.workers['claude'], 'run', side_effect=unknown): state = run.run(task)
        self.assertEqual(state['phase'], 'blocked')
        self.assertIsNotNone(state['pending'])
        self.assertFalse(self.workers['codex'].calls)

    def test_cancel_pending_approval_and_quota_binding_prevent_switch(self):
        self.workers['claude'].responses = ['quota']
        run, task = self.runtime()
        # Save a settled quota checkpoint, then exercise guards without dispatch.
        with patch('onecrew.provider_fallback.advance', return_value=None): state = run.run(task)
        seq, state = run.state(task)
        state['phase'] = 'running'
        state['quota_binding'] = {'provider': 'claude'}
        self.assertIsNone(advance(run, task, seq, state, QuotaExhausted('claude')))
        state.pop('quota_binding')
        with patch.object(run.ledger, 'requests', return_value=[{'state':'pending'}]):
            self.assertIsNone(advance(run, task, seq, state, QuotaExhausted('claude')))
        future=dt.datetime.fromisoformat(run.control.status(task)['deadline'])+dt.timedelta(seconds=1)
        with patch.object(run.control, 'clock', return_value=future):
            self.assertIsNone(advance(run, task, seq, state, QuotaExhausted('claude')))
        run.control.cancel(task)
        self.assertIsNone(advance(run, task, seq, state, QuotaExhausted('claude')))
        self.assertFalse(self.workers['codex'].calls)

    def test_cli_saves_exact_order_and_clears_for_new_jobs_only(self):
        from onecrew.provider_cli import main
        args=['--project',str(self.root),'--state-root',str(self.ledger.state_root),'prefer','claude','--model','sonnet']
        with patch('sys.stdout',new_callable=io.StringIO) as output:
            self.assertEqual(main(args+['--fallback','codex:gpt-6.1-sol','--fallback','kiro:claude-sonnet-5']),0)
            self.assertTrue(json.loads(output.getvalue())['automatic_fallback'])
        self.assertEqual(read(self.ledger)['fallbacks'],CHAIN)
        with patch('sys.stdout',new_callable=io.StringIO): self.assertEqual(main(args),0)
        self.assertEqual(read(self.ledger)['fallbacks'],[])


class LimitParserTests(unittest.TestCase):
    def test_known_native_errors_only(self):
        for provider, event in (
            ('claude', {'type':'result','is_error':True,'result':"You've hit your limit · resets 11pm"}),
            ('codex', {'type':'turn.failed','error':{'message':"You've hit your usage limit. Try later."}}),
            ('kiro', {'type':'runFinished','data':{'status':'failed','error':{'code':'quota_exhausted'}}})):
            with self.subTest(provider=provider), self.assertRaises(QuotaExhausted): check_event(provider, event)

    def test_source_model_text_auth_and_generic_rate_limits_are_not_quota(self):
        check_event('claude', {'type':'result','is_error':False,'result':"You've hit your limit"})
        check_event('codex', {'type':'item.completed','item':{'type':'agent_message','text':"You've hit your usage limit"}})
        check_event('codex', {'type':'error','message':"You've hit your usage limit"})  # no terminal failure
        for error in ({'code':'rate_limit_exceeded','message':'HTTP 429'}, {'code':'unauthorized'},
                      'API Error: 429 Too many requests', 'Authentication failed'):
            check_event('codex', {'type':'turn.failed','error':error})

    def test_nonzero_receipt_detected_but_timeout_and_unsettled_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'stdout.json'
            path.write_text(json.dumps({'type':'result','is_error':True,'result':"You've hit your limit"}))
            receipt = {'exit_code':1,'stdout':str(path)}
            with self.assertRaises(QuotaExhausted):
                check_attempt('claude', {'status':'settled','result':json.dumps(receipt)})
            check_attempt('claude', {'status':'unknown','result':json.dumps(receipt)})
            check_attempt('claude', {'status':'settled','result':json.dumps(dict(receipt, reason='timeout'))})

    def test_adapters_surface_quota_before_generic_nonzero_exit(self):
        from onecrew.providers import ClaudeArtifact, KiroArtifact
        from onecrew.workflow import CodexArtifact
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'stdout.json'
            for worker, event in (
                (ClaudeArtifact(None), {'type':'result','is_error':True,'result':"You've hit your limit"}),
                (CodexArtifact(None), {'type':'turn.failed','error':{'code':'usage_limit_exceeded'}}),
                (KiroArtifact(None), {'type':'runFinished','data':{'status':'failed','error':{'code':'quota_exhausted'}}})):
                path.write_text(json.dumps(event))
                attempt={'status':'settled','result':json.dumps({'stdout':str(path),'exit_code':1})}
                with self.subTest(worker=type(worker).__name__), self.assertRaises(QuotaExhausted): worker.result(attempt)


if __name__ == '__main__': unittest.main()
