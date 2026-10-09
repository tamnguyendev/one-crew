"""A fixed set of approved tasks share one additional finite goal budget."""
from contextlib import ExitStack
import datetime as dt
import json

from .ledger import Ledger, LedgerError, content_hash, exact_fields, text_field
from .routing import instant


def group(conn, task_id):
    row = conn.execute("SELECT e.payload FROM events e, json_each(e.payload,'$.members') m WHERE e.kind='budget.group' AND json_extract(m.value,'$.task_id')=?", (task_id,)).fetchone()
    if not row:
        return None
    result = json.loads(row['payload'])
    ids = [r['task_id'] for r in result['members']]
    slots = ','.join('?' for _ in ids)
    totals = conn.execute(f'SELECT SUM(used_calls),SUM(reserved_calls) FROM executions WHERE task_id IN ({slots})', ids).fetchone()
    result.update(used_calls=totals[0] or 0, reserved_calls=totals[1] or 0)
    result['remaining_calls'] = max(0,result['max_calls']-result['used_calls']-result['reserved_calls'])
    attempts = conn.execute(f"SELECT COUNT(*),SUM(status='unknown') FROM attempts WHERE task_id IN ({slots}) AND status IN ('reserved','running','unknown')",ids).fetchone()
    result.update(active_attempts=attempts[0],unknown_attempts=attempts[1] or 0)
    return result


def cancellation_status(task_id, execution, budget):
    """An owner cannot report stopped while any member still has an active attempt."""
    goal = budget.get('goal')
    if execution['cancel_requested'] and goal and goal['owner_task_id'] == task_id:
        return 'cancelling' if goal['active_attempts'] else 'cancelled'
    return execution['status']


def create(workflow, owner_id, revision, proposal):
    from .budget import local_current
    from .workflow import task_lock
    exact_fields(proposal, ('members','max_calls','deadline','reason'), 'Goal budget')
    members = proposal['members']
    if not isinstance(members,list) or not 2 <= len(members) <= 20:
        raise LedgerError('Goal budget requires 2-20 explicit tasks.')
    if type(proposal['max_calls']) is not int or not 1 <= proposal['max_calls'] <= 10000:
        raise LedgerError('Goal call cap must be a finite integer 1-10000.')
    text_field(proposal['reason'],'Goal budget reason',1000)
    end = instant(proposal['deadline']).astimezone(dt.timezone.utc)
    by_id = {}
    for row in members:
        exact_fields(row, ('task_id','project','workflow_revision'), 'Goal member')
        for field in ('task_id','project','workflow_revision'):
            text_field(row[field],field,1000)
        if row['task_id'] in by_id:
            raise LedgerError('Goal members must be unique.')
        by_id[row['task_id']] = row
    if owner_id not in by_id or by_id[owner_id]['workflow_revision'] != revision:
        raise LedgerError('Owner must be included at the reviewed workflow revision.')
    normalized = dict(proposal,members=sorted(members,key=lambda r:r['task_id']),deadline=end.isoformat())
    digest = content_hash(normalized)
    ledgers = {key:Ledger(row['project'],workflow.ledger.state_root) for key,row in by_id.items()}
    if ledgers[owner_id].project_id != workflow.ledger.project_id:
        raise LedgerError('Owner project does not match this entry.')
    # Acquire task locks in a stable order; the transaction then fences direct core
    # admission as well. No graph, scheduler or model invocation is added here.
    with ExitStack() as stack:
        for key in sorted(by_id):
            stack.enter_context(task_lock(ledgers[key],key))
        conn = stack.enter_context(workflow.ledger.transaction(write=True))
        previous = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='budget.group'",(owner_id,)).fetchone()
        if previous:
            result = json.loads(previous['payload'])
            if result['revision'] != digest:
                raise LedgerError('Goal budget is immutable; cannot reset its members or limits.')
            return group(conn,owner_id)
        created, used, reserved, owner_budget = [], 0, 0, None
        for key,row in by_id.items():
            task = ledgers[key]._task(conn,key)
            if group(conn,key):
                raise LedgerError('Task already belongs to a goal budget; nested/repeated groups are forbidden.')
            execution = conn.execute('SELECT * FROM executions WHERE task_id=?',(key,)).fetchone()
            checkpoint = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='workflow.checkpoint' ORDER BY seq DESC LIMIT 1",(key,)).fetchone()
            if not execution or not checkpoint or content_hash(json.loads(checkpoint['payload'])) != row['workflow_revision']:
                raise LedgerError('Missing or stale member workflow revision.')
            state = json.loads(checkpoint['payload'])
            if execution['cancel_requested'] or execution['status'] in ('failed','cancelled'):
                raise LedgerError('Cancelled/failed tasks cannot join a goal budget.')
            if state['pending'] or state.get('parallel_pending') or state.get('tool_pending') or conn.execute("SELECT 1 FROM attempts WHERE task_id=? AND status!='settled'",(key,)).fetchone():
                raise LedgerError('Stop/reconcile all member attempts before grouping.')
            if conn.execute("SELECT 1 FROM requests WHERE task_id=? AND state='pending'",(key,)).fetchone():
                raise LedgerError('Resolve member inbox questions before changing their effective budget.')
            created.append(instant(task['created_at']))
            used += execution['used_calls']
            reserved += execution['reserved_calls']
            if key == owner_id:
                owner_budget = local_current(conn,task)
        if (end <= workflow.control.clock() or end > min(created)+dt.timedelta(hours=8)
                or end > instant(owner_budget['deadline']) or proposal['max_calls'] > owner_budget['limits']['max_calls']
                or proposal['max_calls'] < used+reserved):
            raise LedgerError('Goal budget must retain prior spend and fit the owner grant and original eight-hour boundary.')
        payload = dict(normalized,owner_task_id=owner_id,revision=digest,authority='local_operator',
                       calls_already_used=used,automatic_dispatch=False)
        workflow.ledger._event(conn,owner_id,'budget.group',payload)
        return group(conn,owner_id)
