"""Exact shared account quota admission; the legacy mutation adapter stays outside."""
import copy
import json
from .ledger import LedgerError, content_hash, exact_fields, key_field, text_field
from .routing import choose, instant

def validate(binding, now):
    exact_fields(binding, ('account', 'bucket', 'provider', 'model', 'quota'), 'Quota binding')
    key_field(binding['account'])
    key_field(binding['bucket'])
    text_field(binding['model'], 'model', 100)
    if binding['provider'] not in ('codex', 'claude', 'kiro'):
        raise LedgerError('Unknown quota provider.')
    if binding['quota'] is None:
        raise LedgerError('Quota evidence is required.')
    choice = check(binding, binding['quota'], now)
    if choice['status'] != 'recommended':
        raise LedgerError('Quota evidence is stale, reset or insufficient: '+json.dumps(choice['rejected']))
    return copy.deepcopy(binding)

def check(binding, quota, now):
    return choose({'complexity': 1, 'risk': 'low', 'allowed_providers': [binding['provider']]}, [{
        'id': 'current', 'provider': binding['provider'], 'model': binding['model'], 'tier': 1,
        'cost_rank': 1, 'capability_verified': True, 'auth_mode': 'subscription', 'quota': quota}], now)

def current(conn, task_id):
    row = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='workflow.checkpoint' ORDER BY seq DESC LIMIT 1", (task_id,)).fetchone()
    return json.loads(row['payload']).get('quota_binding') if row else None

def reserve(control, conn, attempt):
    binding = current(conn, attempt['task_id'])
    if binding is None:
        return  # Existing explicit-worker workflows retain their original grant behavior.
    now = control.clock()
    validate(binding, now)
    operation = json.loads(attempt['operation'])
    if operation.get('provider') != binding['provider'] or operation.get('model') != binding['model']:
        raise LedgerError('Refresh quota for the selected worker before dispatch.')
    quota = copy.deepcopy(binding['quota'])
    # All projects sharing this ledger coordinate the same account/bucket. Released
    # means positively not launched. A timeout or unobserved usage never refunds it.
    rows = conn.execute("SELECT e.payload,a.status,a.charged,a.updated_at FROM events e JOIN attempts a ON a.id=json_extract(e.payload,'$.attempt') WHERE e.kind='quota.reserved'")
    for row in rows:
        held = json.loads(row['payload'])
        if (held['provider'], held['account'], held['bucket']) != (binding['provider'], binding['account'], binding['bucket']):
            continue
        if row['status'] == 'settled' and not row['charged']:
            continue
        if {w['name'] for w in held['windows']} != {w['name'] for w in quota['windows']}:
            raise LedgerError('Shared account quota window mapping differs across reservations.')
        for window in quota['windows']:
            previous = next((w for w in held['windows'] if w['name'] == window['name']), None)
            if previous is None:
                raise LedgerError('Quota window mapping changed while reservations remain; reconcile mapping first.')
            reset = instant(previous['resets_at'])
            if row['status'] != 'settled' or reset > now or instant(row['updated_at']) >= reset:
                # Include even a launched/settled estimate until its window expires.
                # New provider observations may already reflect it: over-reserving
                # is intentional until an authoritative settlement feed exists.
                window['reserved'] += previous['estimated_call']
    choice = check(binding, quota, now)
    if choice['status'] != 'recommended':
        raise LedgerError('Shared account quota insufficient after reservations: '+json.dumps(choice['rejected']))
    control.ledger._event(conn, attempt['task_id'], 'quota.reserved', {
        'attempt': attempt['id'], 'quota_revision': content_hash(binding), 'provider': binding['provider'],
        'account': binding['account'], 'bucket': binding['bucket'], 'windows': binding['quota']['windows'],
        'source': binding['quota']['source'], 'estimate_only': True})

def before_launch(control, conn, attempt):
    binding = current(conn, attempt['task_id'])
    if binding is None:
        return
    row = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='quota.reserved' AND json_extract(payload,'$.attempt')=?",
                       (attempt['task_id'], attempt['id'])).fetchone()
    if not row or json.loads(row['payload'])['quota_revision'] != content_hash(binding):
        raise LedgerError('Quota binding changed or reservation missing before launch.')
    validate(binding, control.clock())
