"""Conservative quota detection from native CLI error envelopes, never agent text."""
import json
from pathlib import Path
from .ledger import LedgerError


class QuotaExhausted(LedgerError):
    def __init__(self, provider):
        self.provider = provider
        super().__init__(provider + ': subscription usage limit exhausted.')


def exhausted_error(error):
    if isinstance(error, dict):
        # Explicit exhaustion, not rate_limit_exceeded/HTTP 429 (which may be transient).
        if error.get('code') in ('usage_limit_exceeded', 'quota_exhausted', 'insufficient_quota'):
            return True
        error = error.get('message')
    if not isinstance(error, str): return False
    return error.strip().lower().startswith(("you've hit your usage limit", "you've hit your limit",
                                             'your usage limit has been reached'))


def check_event(provider, event):
    if not isinstance(event, dict): return
    errors = []
    if provider == 'claude' and event.get('type') == 'result' and event.get('is_error') is True:
        errors = [event.get('result'), event.get('error')]
        if isinstance(event.get('errors'), list): errors += event['errors']
    elif provider == 'codex' and event.get('type') == 'turn.failed':
        errors = [event.get('error'), event.get('message')]
    elif provider == 'kiro' and event.get('type') == 'runFinished':
        data = event.get('data')
        if isinstance(data, dict) and data.get('status') in ('error', 'failed'):
            errors = [data.get('error')]
    if any(exhausted_error(error) for error in errors): raise QuotaExhausted(provider)


def check_attempt(provider, attempt, state_root=None):
    # Supervisor settlement attests process-tree death. Never interpret timeout or
    # reconciliation failure as permission to run another provider concurrently.
    if attempt.get('status') != 'settled': return
    receipt = json.loads(attempt['result'])
    if receipt.get('reason') or receipt.get('exit_code') is None or not receipt.get('stdout'): return
    path = Path(receipt['stdout'])
    if state_root is not None and attempt.get('id'):   # 2.3-B M6: read the output inside the state root that holds the attempt
        from .process_core import output_file
        path = output_file(state_root, attempt['id'], path)
    if path.stat().st_size > 4_000_000: raise LedgerError('Provider response exceeds 4 MB.')
    raw = path.read_text(encoding='utf-8')
    try:
        event = json.loads(raw)
    except ValueError:
        for line in raw.splitlines():
            try: event = json.loads(line)
            except ValueError: continue
            check_event(provider, event)
    else:
        check_event(provider, event)
