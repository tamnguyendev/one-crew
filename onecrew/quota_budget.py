"""Conservative account-window reservations in the existing admission transaction."""
import copy
import json

from .ledger import LedgerError, content_hash, exact_fields, key_field, text_field
from .routing import choose, instant
from .quota_core import validate, check, current, reserve, before_launch








def bind(workflow, task_id, revision, binding):
    from .workflow import task_lock
    with task_lock(workflow.ledger, task_id):
        sequence, state = workflow.state(task_id)
        control = workflow.control.status(task_id)
        if not state or content_hash(state) != revision:
            raise LedgerError('Stale workflow revision.')
        if control['cancel_requested'] or state['pending'] or state.get('parallel_pending') or any(a['status'] != 'settled' for a in control['attempts']):
            raise LedgerError('Quota binding requires a settled non-cancelled checkpoint.')
        binding = validate(binding, workflow.control.clock())
        selected = state.get('worker', control['configuration']['profile'])
        if binding['provider'] != selected.get('provider', 'codex') or binding['model'] != selected['model']:
            raise LedgerError('Quota binding must match the selected worker; it cannot switch model or authorize API use.')
        old = state.get('quota_binding')
        prior_bindings = ([old] if old else []) + [r['binding'] for r in state.get('quota_history', [])]
        for prior in prior_bindings:
            if prior['provider'] == binding['provider']:
                if (prior['account'], prior['bucket']) != (binding['account'], binding['bucket']):
                    raise LedgerError('Account/bucket alias is pinned for this provider; changing it would evade reservations.')
                if {w['name'] for w in prior['quota']['windows']} != {w['name'] for w in binding['quota']['windows']}:
                    raise LedgerError('Required quota windows cannot be removed or renamed by refresh.')
        if old:
            state.setdefault('quota_history', []).append({'revision': content_hash(old), 'binding': old})
        state['quota_binding'] = binding
        workflow.persist(task_id, sequence, state)
        return {'workflow_revision': content_hash(state), 'quota_revision': content_hash(binding),
                'account': binding['account'], 'bucket': binding['bucket'], 'authority': 'local_operator',
                'automatic_refresh': False}
