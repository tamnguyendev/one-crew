"""An ordinary task may pin one explicit approved plan root in its sealed payload.

The job request key remains its own idempotency key. This is a reference to the
existing owner approval and budget, never another approval or budget store.
"""
import json

from ..ledger import LedgerError, content_hash
from . import namespaces, plan as plans

FIELDS = {'project_id', 'root_task_id', 'selector', 'revision', 'sha'}


def capture(ledger, conn, selector, revision=None):
    _, explicit = namespaces.parse(selector)
    if explicit is None:
        raise LedgerError('plan_selector must explicitly name plan:NAME or plan-ns:NAME.')
    state = plans.derive(ledger, conn, explicit)
    if state is None or state['status'] != 'approved':
        raise LedgerError('Plan binding requires the selected root to be approved in this project.')
    if revision is not None and (type(revision) is not int or revision != state['latest']):
        raise LedgerError('Plan binding revision is stale or invalid.')
    contract, sha = plans.load(ledger, state)
    from . import solution_link
    solution_link.validate_root(ledger, conn, state, contract, sha)
    return {'project_id': ledger.project_id, 'root_task_id': state['task_id'],
            'selector': state['selector'], 'revision': state['latest'], 'sha': sha}


def validate(ledger, conn, binding):
    if not isinstance(binding, dict) or set(binding) != FIELDS or binding.get('project_id') != ledger.project_id:
        raise LedgerError('Plan binding belongs to another project or has an invalid shape.')
    observed = capture(ledger, conn, binding['selector'], binding['revision'])
    if observed != binding:
        raise LedgerError('Bound plan root or approved revision changed; submit a new explicit handoff.')
    return plans.derive(ledger, conn, binding['selector'])


def read(task):
    return json.loads(task['payload']).get('plan_binding')


def submitted(conn, task):
    row = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='task.submitted' ORDER BY seq LIMIT 1", (task['id'],)).fetchone()
    return json.loads(row['payload']).get('plan_binding') if row else None


def required(conn, task):
    return read(task) is not None or submitted(conn, task) is not None


def state_for_task(ledger, conn, task):
    binding = read(task)
    original = submitted(conn, task)
    if original is not None and binding != original:
        raise LedgerError('Task plan binding differs from its sealed submission.')
    if binding is None:
        state = plans.derive(ledger, conn, task['request_key'])
        if state is not None and namespaces.has_capability(state, 'root-budget'):
            raise LedgerError('This workflow root requires a sealed plan binding; submit a new explicit handoff.')
        return state
    if task['project_id'] != ledger.project_id or content_hash(json.loads(task['payload'])) != task['revision']:
        raise LedgerError('Task plan binding is not covered by this task revision.')
    return validate(ledger, conn, binding)


def implicit_workflow(ledger, conn, request_key):
    """Preserve implicit schema-2 handoffs, but seal an opted-in workflow root."""
    try:
        namespaces.parse(request_key)
    except LedgerError:
        return None  # v1 job keys may contain ':' without naming any plan
    try:
        state = plans.derive(ledger, conn, request_key)
    except LedgerError as error:
        # Ambiguity is never resolved by choosing an anchor. The old schema-2
        # route still refuses it at its existing dispatch gate.
        if 'ambiguous' in str(error):
            return None
        raise
    if state is None or not namespaces.has_capability(state, 'root-budget'):
        return None
    return capture(ledger, conn, state['selector'])


def first_approval_at(ledger, conn, binding):
    row = conn.execute("SELECT payload,created_at FROM events WHERE task_id=? AND kind='plan.approved' ORDER BY seq LIMIT 1", (binding['root_task_id'],)).fetchone()
    if row is None:
        raise LedgerError('The workflow root has no owner approval.')
    return json.loads(row['payload']).get('at') or row['created_at']


def inherited_workflow(ledger, conn, parent_id):
    parent = ledger._task(conn, parent_id)
    binding = read(parent)
    if binding is None:
        return None
    state = plans.derive(ledger, conn, binding['selector'])
    if state is None or not namespaces.has_capability(state, 'root-budget'):
        return None
    state_for_task(ledger, conn, parent)
    return binding
