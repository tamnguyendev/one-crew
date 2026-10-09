"""Explicit local-operator extensions; immutable original grant and cumulative usage."""
import datetime as dt
import getpass
import json

from .ledger import LedgerError, content_hash, key_field, text_field


def local_current(conn, task):
    row = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='grant.extended' ORDER BY seq DESC LIMIT 1", (task['id'],)).fetchone()
    if row:
        return json.loads(row['payload'])['budget']
    grant = json.loads(task['payload'])['grant']
    return {'limits': grant['limits'], 'deadline': task['deadline'],
            'revision': content_hash({'task_revision': task['revision'], 'grant': grant, 'deadline': task['deadline']})}


def current(conn, task):
    result = local_current(conn,task)
    from .goal_budget import group
    shared = group(conn,task['id'])
    if shared:
        result['local_revision'] = result['revision']
        result['revision'] = content_hash({'local_revision':result['revision'],'goal_revision':shared['revision']})
        result['deadline'] = min(result['deadline'],shared['deadline'],key=dt.datetime.fromisoformat)
        result['goal'] = shared
    return result


def remaining(budget, used, reserved):
    left = budget['limits']['max_calls']-used-reserved
    return min(left,budget['goal']['remaining_calls']) if budget.get('goal') else left


def extend(control, task_id, revision, request_key, max_calls, deadline, reason):
    key_field(request_key)
    text_field(reason, 'Extension reason', 1000)
    if type(max_calls) is not int or not 1 <= max_calls <= 10000:
        raise LedgerError('Extended total call limit must be 1-10000.')
    try:
        end = dt.datetime.fromisoformat(deadline)
        if end.tzinfo is None:
            raise ValueError()
        end = end.astimezone(dt.timezone.utc)
    except (TypeError, ValueError):
        raise LedgerError('Deadline must be an ISO timestamp with timezone.') from None
    proposal = {'previous_revision': revision, 'max_calls': max_calls, 'deadline': end.isoformat(), 'reason': reason}
    proposal_revision = content_hash(proposal)
    from .workflow import task_lock
    with task_lock(control.ledger, task_id), control.ledger.transaction(write=True) as conn:
        task, execution = control._execution(conn, task_id)
        duplicate = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='grant.extended' AND json_extract(payload,'$.request_key')=?", (task_id, request_key)).fetchone()
        if duplicate:
            receipt = json.loads(duplicate['payload'])
            if receipt['proposal_revision'] != proposal_revision:
                raise LedgerError('Extension key already bound to another proposal.')
            return receipt
        old = current(conn, task)
        if old['revision'] != revision:
            raise LedgerError('Stale budget revision; review current limits before extending.')
        if execution['cancel_requested'] or execution['status'] in ('completed', 'cancelled', 'failed'):
            raise LedgerError('Terminal/cancelled work cannot receive an extension.')
        if conn.execute("SELECT 1 FROM attempts WHERE task_id=? AND status!='settled'", (task_id,)).fetchone():
            raise LedgerError('Stop and reconcile every attempt before extending; unknown usage is retained.')
        if conn.execute("SELECT 1 FROM requests WHERE task_id=? AND state='pending'", (task_id,)).fetchone():
            raise LedgerError('Resolve the pending question before changing its budget revision.')
        created = dt.datetime.fromisoformat(task['created_at'])
        seconds = (end-created).total_seconds()
        old_end = dt.datetime.fromisoformat(local_current(conn,task)['deadline'])
        if (not 0 < seconds <= 28800 or end <= control.clock() or end < old_end
                or max_calls < old['limits']['max_calls'] or max_calls < execution['used_calls'] + execution['reserved_calls']):
            raise LedgerError('Extension must preserve used/old limits and have a future deadline within eight hours of original submission.')
        if end == old_end and max_calls == old['limits']['max_calls']:
            raise LedgerError('Extension must increase calls or deadline.')
        budget = {'limits': {'max_calls': max_calls, 'max_seconds': seconds}, 'deadline': end.isoformat(),
                  'revision': content_hash({'task_revision': task['revision'], 'proposal': proposal})}
        receipt = {'request_key': request_key, 'proposal_revision': proposal_revision, 'previous_revision': revision,
                   'budget': budget, 'reason': reason, 'used_calls': execution['used_calls'],
                   'reserved_calls': execution['reserved_calls'], 'scope_expanded': False,
                   'authority': {'actor': getpass.getuser(), 'trust': 'local_operator'}, 'automatic_resume': False}
        control.ledger._event(conn, task_id, 'grant.extended', receipt)
        return receipt
