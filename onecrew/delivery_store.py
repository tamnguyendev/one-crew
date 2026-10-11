"""Opt-in root/child lineage in the existing ledger and budget admission path."""
import datetime as dt
import json
import sqlite3
import uuid

from .ledger import LedgerError, canonical, content_hash


def installed(conn):
    return bool(conn and conn.execute("SELECT 1 FROM sqlite_master WHERE name='delivery_roots'").fetchone())


def ensure(conn,ledger=None):
    if not installed(conn) and ledger is not None:
        directory=ledger.state_root/'backups';directory.mkdir(exist_ok=True)
        # Caller holds the write reservation; back up the committed state before additive DDL.
        target=directory/('ledger-before-delivery-'+uuid.uuid4().hex+'.sqlite3')
        source=sqlite3.connect(ledger.path.as_uri()+'?mode=ro',uri=True)
        backup=sqlite3.connect(target)
        try:source.backup(backup)
        finally:source.close();backup.close()
    conn.execute('CREATE TABLE IF NOT EXISTS delivery_roots(task_id TEXT PRIMARY KEY REFERENCES tasks(id), plan TEXT NOT NULL, revision TEXT NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS delivery_children(task_id TEXT PRIMARY KEY REFERENCES tasks(id), root TEXT NOT NULL REFERENCES delivery_roots(task_id), node TEXT NOT NULL, generation INTEGER NOT NULL, UNIQUE(root,node,generation))')


def root_id(conn, task):
    if not installed(conn): return None
    if conn.execute('SELECT 1 FROM delivery_roots WHERE task_id=?', (task,)).fetchone(): return task
    row = conn.execute('SELECT root FROM delivery_children WHERE task_id=?', (task,)).fetchone()
    return row[0] if row else None


def shared(conn, task):
    root = root_id(conn, task)
    if root is None: return None
    owner = conn.execute('SELECT * FROM tasks WHERE id=?', (root,)).fetchone()
    from .budget import local_current
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


def guard(ledger, conn, task):
    root = root_id(conn, task)
    if root is None or root == task: return
    execution = conn.execute('SELECT * FROM executions WHERE task_id=?', (root,)).fetchone()
    if not execution or execution['cancel_requested'] or execution['status'] in ('paused','completed','cancelled','failed','blocked'):
        raise LedgerError('Delivery root is stopped; child cannot proceed independently.')
    from .solution_gate import check
    check(ledger, root, conn)
    if conn.execute("SELECT 1 FROM requests WHERE task_id=? AND state='pending'", (root,)).fetchone():
        raise LedgerError('Delivery root has a pending question.')


def child_authority(ledger, conn, parent, node, generation, goal, recipe, solution_id, solution_revision):
    if not installed(conn): raise LedgerError('Delivery root missing.')
    row = conn.execute('SELECT * FROM delivery_roots WHERE task_id=?', (parent,)).fetchone()
    if not row: raise LedgerError('Delivery root missing.')
    task = ledger._task(conn, parent)
    binding = conn.execute('SELECT * FROM solution_bindings WHERE task_id=?', (parent,)).fetchone()
    if not binding or (binding['solution'],binding['revision']) != (solution_id,solution_revision):
        raise LedgerError('Child must retain root solution revision.')
    plan = json.loads(row['plan'])
    config = next((n['config'] for n in plan['nodes'] if n['id']==node and n['kind']=='change'), None)
    if config is None or config['recipe'] != recipe: raise LedgerError('Child recipe exceeds the sealed plan.')
    checkpoint = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='workflow.checkpoint' ORDER BY seq DESC LIMIT 1",(parent,)).fetchone()
    state = json.loads(checkpoint[0]) if checkpoint else {}
    intent = state.get('delivery',{}).get('child_intent')
    if intent != {'node':node,'generation':generation,'goal':goal}:
        raise LedgerError('Child requires a durable coordinator intent.')
    if state.get('phase') not in ('running','waiting_operation'):
        raise LedgerError('Delivery root not running.')
    from .budget import current
    return current(conn, task)
