"""Opt-in root/child lineage in the existing ledger and budget admission path."""
import datetime as dt
import json
import sqlite3
import uuid

from .ledger import LedgerError, canonical, content_hash
from .budget_core import installed, root_id, shared  # noqa: F401  (the budget reads live in budget_core; re-exported)


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
