"""Root-budget admission for verifier provider invocations through shared Control."""
import datetime as dt
import json
import os
import time
import uuid

from ..control_core import Control, migrate
from ..ledger import LedgerError, canonical, content_hash, utcnow
from ..snapshots import Snapshots
from ..task_intake import submit
from . import internal_plan as ip


class ProviderCall:
    def __init__(self, ledger, selector, context_key, *, call=None, label=None):
        # `label`: a metered call that is not one of the job providers (Jev advice), recorded under its own name.
        self.ledger, self.selector, self.context_key, self.call, self.label = ledger, selector, context_key, call, label
        self.attempts = []

    def __call__(self, prompt, config, env, scratch, limit):
        from .verifiers import reviewer
        from .verifiers import command
        from . import providers
        ledger = self.ledger
        with command.before_verifier():                # review of dev15 (#2): a refused admission never called the model; the run is not held
            with ledger.transaction() as conn:
                root, contract, sha = ip.context(ledger, conn, self.selector, 'root-budget')
                remaining = ip.ceilings(ledger, conn, root)
            seconds = min(float(limit) * 60, remaining['remaining_seconds'])
            if seconds < 1 or remaining['remaining_calls'] < 1:
                raise LedgerError('The shared root budget/deadline cannot admit another verifier provider call.')
        with command.before_verifier():                # review of dev16 (#2): up to the model call nothing here has called the model
            signature = content_hash({'root': root['task_id'], 'contract': sha, 'context': self.context_key,
                                      'prompt': prompt, 'provider': config['provider'], 'model': config['model']})
            migrate(ledger); control = Control(ledger)
            task = submit(ledger, 'Verify approved evidence: ' + self.context_key, 'verifier-' + uuid.uuid4().hex,
                provider=config['provider'], model=config['model'], max_calls=1, max_seconds=int(seconds),
                plan_selector=root['selector'], plan_revision=root['approved']['revision'],
                _metered_label=self.label)
            execution = control.configure(task['id'], task['revision'], {'mode': 'verifier-provider', 'signature': signature})
            def reserve(conn, attempt):
                # The existing reservation transaction makes concurrent retries
                # serialize, including a prior controller that died without a result.
                old = conn.execute("SELECT id FROM attempts WHERE id!=? AND status IN ('reserved','running','unknown') "
                                   "AND json_extract(operation,'$.verifier_signature')=?", (attempt['id'], signature)).fetchone()
                if old: raise LedgerError('Verifier outcome is unknown; reconcile the original attempt before retrying it.')
            attempt = control.reserve(task['id'], execution['revision'], 'provider',
                                      {'stage': 'verifier', 'verifier_signature': signature, 'verifier_root': root['task_id'], 'verifier_context': self.context_key,
                                       **({'advisory': True} if self.label else {})},
                                      on_reserved=reserve)
        calling = False                                # True from the statement that calls the model: from then on it may have run
        try:
            with command.before_verifier():
                self.attempts.append(attempt['id'])    # review of dev17 (P3): inside the cleanup, so no failure leaves the reservation behind
                started = time.monotonic()
                # Root admission and launch both recheck the original deadline; here before the launch is recorded, so an elapsed deadline
                # settles the attempt as not started (no call charged) instead of leaving its outcome unknown.
                budget = control.status(task['id'])['budget']
                left = (dt.datetime.fromisoformat(budget['deadline']) - dt.datetime.fromisoformat(utcnow())).total_seconds()
                if left <= 0: raise LedgerError('Verifier deadline elapsed before provider dispatch.')
                if config.get('provider', 'claude') == 'claude' and self.call is None:
                    # review of dev17 (P2): auth api without a key runs no process; settled as not started, so no call is charged
                    cli_env, refused = reviewer.provider_env(env, config.get('auth', 'subscription'))
                    if refused:
                        control.finish(attempt['id'], attempt['generation'], {'reason': providers.CREDENTIAL_MISSING, 'provider_invocations': 0},
                                       not_started=True)
                        return '', {}, refused, False, b''
                    reviewer.cli_argv(cli_env)         # review of dev18 (P2): no Claude CLI raises here, before the launch: settled as not started
                control.launched(attempt['id'], attempt['generation'],
                                 {'kind': 'verifier-controller', 'controller_pid': os.getpid(), 'provider': config['provider']})
            # From here on the model may have run. Between `calling = True` and the call itself there remain a few bytecodes; an interrupt landing
            # exactly there leaves the attempt unknown (the safe side: never "not started" for a call that may have happened). Review of dev18 P3.
            calling = True
            result = (self.call or reviewer.call)(prompt, config, env, scratch, min(seconds, left) / 60)
            answer, usage, error, timed_out, raw = result
            store = Snapshots(ledger.state_root)
            receipt = store.blob(canonical({'kind': 'metered-verifier-result', 'attempt': attempt['id'],
                'signature': signature, 'answer': store.blob(answer.encode('utf-8')), 'usage': usage,
                'error': error, 'timed_out': timed_out, 'raw': store.blob(raw[-1_000_000:]),
                'seconds': time.monotonic() - started, 'maximum_seconds': min(seconds, left)}).encode())
            control.finish(attempt['id'], attempt['generation'], {'receipt': receipt, 'provider_invocations': 1})
            return result
        except BaseException as error:
            status = control.attempt(attempt['id'])['status']
            if getattr(error, 'verifier_started', None) is False and status == 'reserved':
                control.finish(attempt['id'], attempt['generation'], {'reason': 'not started: ' + type(error).__name__}, not_started=True)
            elif not calling and status == 'running':
                # Launched but the model statement was never reached (Ctrl+C right after the launch was recorded): certainly not called, so
                # settled, never left unknown. Control charges a launched attempt and never refunds it; the one call stays counted.
                if getattr(error, 'verifier_started', None) is None:
                    try: error.verifier_started = False
                    except (AttributeError, TypeError): pass
                control.finish(attempt['id'], attempt['generation'], {'reason': 'launched, model not called: ' + type(error).__name__,
                                                                      'provider_invocations': 0})
            elif status != 'settled':
                control.unknown(attempt['id'], 'Verifier result unconfirmed: ' + type(error).__name__)
            raise
