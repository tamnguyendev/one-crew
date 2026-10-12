"""Explicit local-operator extensions; immutable original grant and cumulative usage."""
import datetime as dt
import getpass
import json

from .ledger import LedgerError, content_hash, key_field, text_field

# Comparable sentinel for existing deadline consumers, only selected by an
# explicit operator event. Original grants/deadlines remain immutable.
UNBOUNDED_DEADLINE = dt.datetime.max.replace(tzinfo=dt.timezone.utc).isoformat()


def remove_deadline(control, task_id, revision, request_key, reason):
    """Opt one settled task into calls-only budgeting; never launch or add calls."""
    key_field(request_key);text_field(reason, 'Actual operator request', 1000)
    proposal = {'previous_revision':revision, 'request_key':request_key, 'reason':reason,
                'operation':'remove_deadline'}
    digest = content_hash(proposal)
    from .workflow import task_lock
    with task_lock(control.ledger,task_id), control.ledger.transaction(write=True) as conn:
        task,execution = control._execution(conn,task_id)
        duplicate = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='grant.extended' AND json_extract(payload,'$.request_key')=?",(task_id,request_key)).fetchone()
        if duplicate:
            receipt=json.loads(duplicate['payload'])
            if receipt['proposal_revision']!=digest:raise LedgerError('Budget key already bound to another proposal.')
            return receipt
        old=current(conn,task)
        if old['revision']!=revision:raise LedgerError('Stale budget revision.')
        if old.get('goal'):raise LedgerError('Cannot remove a shared goal deadline through a member task.')
        if old.get('time_unlimited'):raise LedgerError('Task already has no wall-clock deadline.')
        if execution['cancel_requested'] or execution['status'] in ('completed','cancelled','failed'):
            raise LedgerError('Terminal/cancelled work cannot change budget.')
        if conn.execute("SELECT 1 FROM attempts WHERE task_id=? AND status!='settled'",(task_id,)).fetchone():
            raise LedgerError('Stop and reconcile every attempt before changing the budget.')
        if conn.execute("SELECT 1 FROM requests WHERE task_id=? AND state='pending'",(task_id,)).fetchone():
            raise LedgerError('Resolve the pending question before changing its budget revision.')
        budget={'limits':dict(old['limits'],max_seconds=None),'deadline':UNBOUNDED_DEADLINE,
                'time_unlimited':True,'revision':content_hash({'task_revision':task['revision'],'proposal':proposal})}
        receipt={**proposal,'proposal_revision':digest,'previous_deadline':old['deadline'],
                 'budget':budget,'used_calls':execution['used_calls'],'reserved_calls':execution['reserved_calls'],
                 'scope_expanded':False,'automatic_resume':False,
                 'authority':{'actor':getpass.getuser(),'trust':'local_operator'}}
        control.ledger._event(conn,task_id,'grant.extended',receipt)
        return receipt


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


def extend(control, task_id, revision, request_key, max_calls, deadline, reason, *, restart_expired=False):
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
    if type(restart_expired) is not bool:
        raise LedgerError('Restart-expired must be an explicit boolean.')
    if restart_expired:
        proposal['restart_expired'] = True
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
        pending = [json.loads(r['payload'])['action'] for r in conn.execute("SELECT payload FROM requests WHERE task_id=? AND state='pending'", (task_id,))]
        # A delivery's own budget question asks for exactly this extension; any other pending question must be answered first.
        if any(not (a['type'] == 'delivery.recovery' and a['parameters'].get('class') == 'budget') for a in pending):
            raise LedgerError('Resolve the pending question before changing its budget revision.')
        created = dt.datetime.fromisoformat(task['created_at'])
        seconds = (end-created).total_seconds()
        old_end = dt.datetime.fromisoformat(local_current(conn,task)['deadline'])
        now = control.clock()
        if restart_expired and (now < old_end or old.get('goal')):
            raise LedgerError('Restart window requires an expired local deadline without a shared goal budget.')
        window_seconds = (end-now).total_seconds() if restart_expired else seconds
        if (not 0 < window_seconds <= 28800 or end <= now or end < old_end
                or max_calls < old['limits']['max_calls'] or max_calls < execution['used_calls'] + execution['reserved_calls']):
            raise LedgerError('Extension must preserve used/old limits and stay within eight hours of original submission, or of explicit expired-task restart.')
        if end == old_end and max_calls == old['limits']['max_calls']:
            raise LedgerError('Extension must increase calls or deadline.')
        budget = {'limits': {'max_calls': max_calls, 'max_seconds': seconds}, 'deadline': end.isoformat(),
                  'revision': content_hash({'task_revision': task['revision'], 'proposal': proposal})}
        receipt = {'request_key': request_key, 'proposal_revision': proposal_revision, 'previous_revision': revision,
                   'budget': budget, 'reason': reason, 'used_calls': execution['used_calls'],
                   'reserved_calls': execution['reserved_calls'], 'scope_expanded': False,
                   'authority': {'actor': getpass.getuser(), 'trust': 'local_operator'}, 'automatic_resume': False}
        if restart_expired:
            receipt['restart_window'] = {'authorized_at': now.isoformat(), 'seconds': window_seconds,
                                         'previous_deadline': old_end.isoformat(), 'explicit_operator_request': True}
        control.ledger._event(conn, task_id, 'grant.extended', receipt)
        return receipt
