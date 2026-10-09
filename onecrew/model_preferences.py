"""Local operator defaults for NEW jobs. Reset hints never become quota evidence."""
import json
from .ledger import LedgerError, canonical, text_field
from .snapshots import durable_write
from .routing import instant

DEFAULT = {'provider': 'codex', 'model': 'gpt-6-luna', 'reset_hint': None, 'source': 'built-in default'}


def validate(value):
    if not isinstance(value, dict) or set(value) - {'fallbacks'} != set(DEFAULT): raise LedgerError('Invalid model preference.')
    if value['provider'] not in ('claude', 'codex', 'kiro'): raise LedgerError('Invalid preferred provider.')
    text_field(value['model'], 'preferred model', 120);text_field(value['source'], 'preference source', 500)
    if value['reset_hint'] is not None: instant(value['reset_hint'])
    validate_fallbacks(value.get('fallbacks', []), value['provider'])
    return value


def validate_fallbacks(rows, primary):
    if not isinstance(rows, list) or len(rows) > 2: raise LedgerError('At most two fallback providers are allowed.')
    seen = {primary}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'provider', 'model'}:
            raise LedgerError('Fallback needs provider and explicit model.')
        if row['provider'] not in ('claude', 'codex', 'kiro') or row['provider'] in seen:
            raise LedgerError('Fallback providers must be unique and different from primary.')
        text_field(row['model'], 'fallback model', 120)
        seen.add(row['provider'])
    return rows


def read(ledger):
    path = ledger.state_root / 'model-preference.json'
    return validate(json.loads(path.read_text(encoding='utf-8'))) if path.exists() else dict(DEFAULT)


def save(ledger, provider, model, reset_hint=None, fallbacks=None):
    value = validate(dict(provider=provider, model=model, reset_hint=reset_hint, source='local operator; reset hint is user-reported'))
    if fallbacks is not None: value['fallbacks'] = validate_fallbacks(fallbacks, provider)
    durable_write(ledger.state_root / 'model-preference.json', canonical(value).encode())
    return dict(value, quota_verified=False, affects='new jobs only', automatic_fallback=bool(value.get('fallbacks')))


def resolve(ledger, provider, model, previous=None):
    pref = previous or read(ledger)
    chosen = provider or pref['provider']
    if model is None:
        model = pref['model'] if chosen == pref['provider'] else {'codex':'gpt-6-luna','claude':'sonnet'}.get(chosen)
    if not model: raise LedgerError('Specify a model for this provider.')
    return chosen, model
