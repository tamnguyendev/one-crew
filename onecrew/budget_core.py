"""The budget reads shared by the ledger and v2 (core): the current grant of a task, the shared goal / delivery budget it belongs to.
Moved here from budget.py, goal_budget.py and delivery_store.py so that the core imports no v1 module; those modules import these
names back, so there is one source. Only reads live here: extensions (budget.extend / remove_deadline) and goal budgets
(goal_budget.create) stay v1."""
import datetime as dt
import json

from .ledger import content_hash

# Comparable sentinel for existing deadline consumers, only selected by an
# explicit operator event. Original grants/deadlines remain immutable.
UNBOUNDED_DEADLINE = dt.datetime.max.replace(tzinfo=dt.timezone.utc).isoformat()


def local_current(conn, task):
    row = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='grant.extended' ORDER BY seq DESC LIMIT 1", (task['id'],)).fetchone()
    if row:
        return json.loads(row['payload'])['budget']
    grant = json.loads(task['payload'])['grant']
    return {'limits': grant['limits'], 'deadline': task['deadline'],
            'revision': content_hash({'task_revision': task['revision'], 'grant': grant, 'deadline': task['deadline']})}


def current(conn, task):
    result = local_current(conn,task)
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


# ---- delivery roots (tables exist only in a ledger that ever ran a delivery) -----------------------------------------------

def installed(conn):
    return bool(conn and conn.execute("SELECT 1 FROM sqlite_master WHERE name='delivery_roots'").fetchone())


def root_id(conn, task):
    if not installed(conn): return None
    if conn.execute('SELECT 1 FROM delivery_roots WHERE task_id=?', (task,)).fetchone(): return task
    row = conn.execute('SELECT root FROM delivery_children WHERE task_id=?', (task,)).fetchone()
    return row[0] if row else None


def shared(conn, task):
    root = root_id(conn, task)
    if root is None: return None
    owner = conn.execute('SELECT * FROM tasks WHERE id=?', (root,)).fetchone()
    budget = local_current(conn, owner)
    members = [root] + [r[0] for r in conn.execute('SELECT task_id FROM delivery_children WHERE root=? ORDER BY task_id', (root,))]
    marks = ','.join('?' for _ in members)
    counters = conn.execute(f'SELECT COALESCE(SUM(used_calls),0),COALESCE(SUM(reserved_calls),0) FROM executions WHERE task_id IN ({marks})', members).fetchone()
    active = conn.execute(f"SELECT COUNT(*),COALESCE(SUM(status='unknown'),0) FROM attempts WHERE task_id IN ({marks}) AND status IN ('reserved','running','unknown')", members).fetchone()
    plan = conn.execute('SELECT revision FROM delivery_roots WHERE task_id=?', (root,)).fetchone()[0]
    return dict(owner_task_id=root, members=[{'task_id':t} for t in members], max_calls=budget['limits']['max_calls'],
                deadline=budget['deadline'], used_calls=counters[0], reserved_calls=counters[1],
                remaining_calls=max(0,budget['limits']['max_calls']-sum(counters)), active_attempts=active[0], unknown_attempts=active[1],
                revision=content_hash({'root':root,'plan':plan,'budget':budget['revision']}), authority='sealed-delivery-plan')


# ---- shared goal budget -------------------------------------------------------------------------------------------------------

def group(conn, task_id):
    delivery = shared(conn, task_id)
    if delivery: return delivery
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
