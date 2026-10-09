"""Transactional admission and bounded execution bookkeeping, schema v2."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import sqlite3
import uuid

from .ledger import Ledger, LedgerError, canonical, content_hash, key_field, utcnow

ACTIVE = ('reserved', 'running', 'unknown')


class CapacityWait(LedgerError):
    """Transient global pressure is queued, not a failed task or permission request."""


SCHEMA = (
    """CREATE TABLE executions (
        task_id TEXT PRIMARY KEY REFERENCES tasks(id), configuration TEXT NOT NULL,
        revision TEXT NOT NULL, status TEXT NOT NULL, used_calls INTEGER NOT NULL DEFAULT 0,
        reserved_calls INTEGER NOT NULL DEFAULT 0, cancel_requested INTEGER NOT NULL DEFAULT 0,
        CHECK(used_calls>=0), CHECK(reserved_calls>=0))""",
    """CREATE TABLE attempts (
        id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES executions(task_id),
        request_key TEXT NOT NULL, operation TEXT NOT NULL, operation_hash TEXT NOT NULL,
        generation INTEGER NOT NULL, status TEXT NOT NULL,
        charged INTEGER NOT NULL DEFAULT 0, identity TEXT, result TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(task_id, request_key))""",
    """CREATE UNIQUE INDEX one_active_attempt_per_task ON attempts(task_id)
        WHERE status IN ('reserved','running','unknown')""",
    """CREATE TABLE actions (
        id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), request_key TEXT NOT NULL,
        payload TEXT NOT NULL, revision TEXT NOT NULL, status TEXT NOT NULL, receipt TEXT,
        UNIQUE(task_id, request_key))""",
)


def migrate(ledger):
    # Initialize v1 separately so even an empty database has a committed backup.
    with ledger.transaction(write=True):
        pass
    with ledger.transaction(write=True) as conn:
        if conn.execute('PRAGMA user_version').fetchone()[0] == 2:
            return {'schema_version': 2, 'changed': False}
        directory = ledger.state_root / 'backups'
        directory.mkdir(exist_ok=True)
        target = directory / ('ledger-v1-' + uuid.uuid4().hex + '.sqlite3')
        # Separate read connection sees the committed v1 snapshot while the writer
        # reservation prevents another mutation between backup and migration.
        source = sqlite3.connect(ledger.path.as_uri() + '?mode=ro', uri=True)
        backup = sqlite3.connect(target)
        try:
            source.backup(backup)
        finally:
            source.close()
            backup.close()
        for statement in SCHEMA:
            conn.execute(statement)
        conn.execute('PRAGMA user_version=2')
        return {'schema_version': 2, 'changed': True, 'backup': str(target)}


class Control:
    def __init__(self, ledger, clock=None):
        self.ledger = ledger
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))

    def _execution(self, conn, task_id):
        task = self.ledger._task(conn, task_id)
        if conn.execute('PRAGMA user_version').fetchone()[0] != 2:
            raise LedgerError('Run core migrate before enabling execution.')
        execution = conn.execute('SELECT * FROM executions WHERE task_id=?', (task_id,)).fetchone()
        if execution is None:
            raise LedgerError('Task execution has not been configured.')
        return task, execution

    def configure(self, task_id, revision, configuration):
        """Trusted controller API. Does not convert inbox answers into authority."""
        with self.ledger.transaction(write=True) as conn:
            task = self.ledger._task(conn, task_id)
            if conn.execute('PRAGMA user_version').fetchone()[0] != 2:
                raise LedgerError('Run core migrate first.')
            if revision != task['revision']:
                raise LedgerError('Stale task revision.')
            encoded = canonical(configuration)
            bound = content_hash({'task_revision': revision, 'configuration': configuration})
            old = conn.execute('SELECT * FROM executions WHERE task_id=?', (task_id,)).fetchone()
            if old:
                if old['revision'] != bound:
                    raise LedgerError('Execution configuration already sealed; cannot reset budget.')
                return dict(old)
            conn.execute('INSERT INTO executions(task_id,configuration,revision,status) VALUES(?,?,?,?)',
                         (task_id, encoded, bound, 'queued'))
            self.ledger._event(conn, task_id, 'execution.configured', {'revision': bound})
            return dict(conn.execute('SELECT * FROM executions WHERE task_id=?', (task_id,)).fetchone())

    def reserve(self, task_id, execution_revision, request_key, operation):
        key_field(request_key)
        encoded = canonical(operation)
        operation_hash = content_hash(operation)
        with self.ledger.transaction(write=True) as conn:
            task, execution = self._execution(conn, task_id)
            if execution['revision'] != execution_revision:
                raise LedgerError('Stale execution revision.')
            old = conn.execute('SELECT * FROM attempts WHERE task_id=? AND request_key=?',
                               (task_id, request_key)).fetchone()
            if old:
                if old['operation_hash'] != operation_hash:
                    raise LedgerError('Attempt key already bound to different operation.')
                return dict(old)
            if execution['cancel_requested'] or execution['status'] in ('cancelled', 'completed', 'failed', 'paused'):
                raise LedgerError('Execution is stopped or terminal.')
            if self.clock() >= dt.datetime.fromisoformat(task['deadline']):
                raise LedgerError('Root deadline exhausted.')
            if conn.execute("SELECT 1 FROM requests WHERE task_id=? AND state='pending'", (task_id,)).fetchone():
                raise LedgerError('Task is waiting for user input.')
            limits = json.loads(task['payload'])['grant']['limits']
            if execution['used_calls'] + execution['reserved_calls'] >= limits['max_calls']:
                raise LedgerError('Root call budget exhausted.')
            if conn.execute("SELECT 1 FROM attempts WHERE task_id=? AND status IN ('reserved','running','unknown')",
                            (task_id,)).fetchone():
                raise LedgerError('Previous attempt must stop and reconcile first.')
            if conn.execute("SELECT COUNT(*) FROM attempts WHERE status IN ('reserved','running','unknown')").fetchone()[0] >= 2:
                raise CapacityWait('Global worker capacity exhausted.')
            generation = conn.execute('SELECT COALESCE(MAX(generation),0)+1 FROM attempts WHERE task_id=?',
                                      (task_id,)).fetchone()[0]
            attempt_id = 'ATT-' + uuid.uuid4().hex
            stamp = utcnow()
            conn.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                         (attempt_id, task_id, request_key, encoded, operation_hash, generation,
                          'reserved', 0, None, None, stamp, stamp))
            conn.execute("UPDATE executions SET reserved_calls=reserved_calls+1,status='running' WHERE task_id=?", (task_id,))
            self.ledger._event(conn, task_id, 'attempt.reserved', {'id': attempt_id, 'generation': generation})
            return dict(conn.execute('SELECT * FROM attempts WHERE id=?', (attempt_id,)).fetchone())

    def _attempt(self, conn, attempt_id):
        row = conn.execute('SELECT a.* FROM attempts a JOIN tasks t ON t.id=a.task_id '
                           'WHERE a.id=? AND t.project_id=?', (attempt_id, self.ledger.project_id)).fetchone()
        if row is None:
            raise LedgerError('Unknown attempt in this project.')
        return row

    def attempt(self, attempt_id):
        with self.ledger.transaction() as conn:
            if conn is None:
                raise LedgerError('Unknown attempt.')
            return dict(self._attempt(conn, attempt_id))

    def launched(self, attempt_id, generation, identity):
        with self.ledger.transaction(write=True) as conn:
            row = self._attempt(conn, attempt_id)
            if row['generation'] != generation:
                raise LedgerError('Stale attempt generation.')
            encoded = canonical(identity)
            if row['status'] == 'running' and row['identity'] == encoded:
                return
            if row['status'] != 'reserved':
                raise LedgerError('Attempt cannot launch from current state.')
            task, execution = self._execution(conn, row['task_id'])
            if execution['cancel_requested'] or execution['status'] == 'paused' or self.clock() >= dt.datetime.fromisoformat(task['deadline']):
                raise LedgerError('Cancel or deadline prevents launch.')
            if conn.execute("SELECT 1 FROM requests WHERE task_id=? AND state='pending'", (row['task_id'],)).fetchone():
                raise LedgerError('Pending question prevents launch.')
            conn.execute("UPDATE attempts SET status='running',charged=1,identity=?,updated_at=? WHERE id=?",
                         (encoded, utcnow(), attempt_id))
            conn.execute('UPDATE executions SET used_calls=used_calls+1,reserved_calls=reserved_calls-1 WHERE task_id=?',
                         (row['task_id'],))
            self.ledger._event(conn, row['task_id'], 'attempt.launched', {'id': attempt_id, 'generation': generation})

    def unknown(self, attempt_id, reason):
        with self.ledger.transaction(write=True) as conn:
            row = self._attempt(conn, attempt_id)
            if row['status'] not in ACTIVE:
                return
            conn.execute("UPDATE attempts SET status='unknown',result=?,updated_at=? WHERE id=?",
                         (canonical({'reason': reason}), utcnow(), attempt_id))
            conn.execute("UPDATE executions SET status='recovering' WHERE task_id=?", (row['task_id'],))
            self.ledger._event(conn, row['task_id'], 'attempt.unknown', {'id': attempt_id, 'reason': reason})

    def finish(self, attempt_id, generation, result, *, not_started=False):
        """Supervisor only: call after process-tree death is confirmed, never on lease expiry."""
        encoded = canonical(result)
        with self.ledger.transaction(write=True) as conn:
            row = self._attempt(conn, attempt_id)
            if generation != row['generation']:
                raise LedgerError('Stale attempt generation.')
            if row['status'] == 'settled':
                if row['result'] != encoded:
                    raise LedgerError('Attempt already settled with a different result.')
                return
            if row['status'] not in ACTIVE:
                raise LedgerError('Attempt cannot settle from current state.')
            if not_started and (row['charged'] or row['status'] != 'reserved'):
                raise LedgerError('Cannot refund a launched or ambiguous attempt.')
            if not row['charged']:
                conn.execute('UPDATE executions SET reserved_calls=reserved_calls-1,used_calls=used_calls+? WHERE task_id=?',
                             (0 if not_started else 1, row['task_id']))
            conn.execute("UPDATE attempts SET status='settled',charged=?,result=?,updated_at=? WHERE id=?",
                         (0 if not_started else 1, encoded, utcnow(), attempt_id))
            conn.execute("UPDATE executions SET status=CASE WHEN cancel_requested=1 THEN 'cancelled' WHEN status='paused' THEN 'paused' ELSE 'queued' END WHERE task_id=?",
                         (row['task_id'],))
            self.ledger._event(conn, row['task_id'], 'attempt.settled', {'id': attempt_id, 'result': result})

    def cancel(self, task_id):
        with self.ledger.transaction(write=True) as conn:
            self._execution(conn, task_id)
            active = conn.execute("SELECT 1 FROM attempts WHERE task_id=? AND status IN ('reserved','running','unknown')",
                                  (task_id,)).fetchone()
            conn.execute('UPDATE executions SET cancel_requested=1,status=? WHERE task_id=?',
                         ('cancelling' if active else 'cancelled', task_id))
            self.ledger._event(conn, task_id, 'execution.cancel_requested', {})

    def pause(self, task_id):
        with self.ledger.transaction(write=True) as conn:
            _, execution = self._execution(conn, task_id)
            if execution['status'] in ('completed', 'cancelled', 'failed'):
                raise LedgerError('Terminal execution cannot be paused.')
            conn.execute("UPDATE executions SET status='paused' WHERE task_id=?", (task_id,))
            self.ledger._event(conn, task_id, 'execution.pause_requested', {})

    def status(self, task_id):
        with self.ledger.transaction() as conn:
            task, execution = self._execution(conn, task_id)
            result = dict(execution)
            result['configuration'] = json.loads(execution['configuration'])
            result['deadline'] = task['deadline']
            result['attempts'] = [dict(r) for r in conn.execute('SELECT * FROM attempts WHERE task_id=? ORDER BY generation', (task_id,))]
            return result

    def propose_action(self, task_id, request_key, payload):
        key_field(request_key)
        with self.ledger.transaction(write=True) as conn:
            task, _ = self._execution(conn, task_id)
            revision = content_hash({'task_revision': task['revision'], 'payload': payload})
            old = conn.execute('SELECT * FROM actions WHERE task_id=? AND request_key=?', (task_id, request_key)).fetchone()
            if old:
                if old['revision'] != revision:
                    raise LedgerError('Action key already bound to different content.')
                return dict(old)
            action_id = 'ACT-' + uuid.uuid4().hex
            conn.execute('INSERT INTO actions VALUES(?,?,?,?,?,?,?)',
                         (action_id, task_id, request_key, canonical(payload), revision, 'proposed', None))
            self.ledger._event(conn, task_id, 'action.proposed', {'id': action_id, 'revision': revision})
            return dict(conn.execute('SELECT * FROM actions WHERE id=?', (action_id,)).fetchone())

    def _action(self, conn, action_id):
        row = conn.execute('SELECT a.* FROM actions a JOIN tasks t ON t.id=a.task_id '
                           'WHERE a.id=? AND t.project_id=?', (action_id, self.ledger.project_id)).fetchone()
        if row is None:
            raise LedgerError('Unknown action.')
        return row

    def authorize_action(self, action_id, revision):
        # Internal trusted controller API; intentionally not exposed as an inbox reply.
        with self.ledger.transaction(write=True) as conn:
            row = self._action(conn, action_id)
            if row['revision'] != revision:
                raise LedgerError('Stale action revision.')
            if row['status'] == 'authorized':
                return
            if row['status'] != 'proposed':
                raise LedgerError('Action cannot be authorized from current state.')
            conn.execute("UPDATE actions SET status='authorized' WHERE id=?", (action_id,))
            self.ledger._event(conn, row['task_id'], 'action.authorized', {'id': action_id, 'revision': revision})

    def execute_action(self, action_id, handler):
        with self.ledger.transaction(write=True) as conn:
            row = self._action(conn, action_id)
            if row['receipt']:
                return json.loads(row['receipt'])
            if row['status'] != 'authorized':
                raise LedgerError('Action is not authorized; unknown/executing actions must be reconciled.')
            conn.execute("UPDATE actions SET status='executing' WHERE id=?", (action_id,))
            self.ledger._event(conn, row['task_id'], 'action.executing', {'id': action_id})
        try:
            result = handler(json.loads(row['payload']))
            if not isinstance(result, dict) or type(result.get('verified')) is not bool:
                raise LedgerError('Action verifier must return a JSON boolean.')
            receipt = {'status': 'verified' if result['verified'] else 'failed', 'result': result}
            canonical(receipt)
        except Exception as error:
            receipt = {'status': 'unknown', 'error': type(error).__name__}
        with self.ledger.transaction(write=True) as conn:
            latest = self._action(conn, action_id)
            if latest['status'] != 'executing':
                if latest['receipt']:
                    return json.loads(latest['receipt'])
                raise LedgerError('Action state changed before receipt commit.')
            conn.execute("UPDATE actions SET status=?,receipt=? WHERE id=? AND status='executing'",
                         (receipt['status'], canonical(receipt), action_id))
            self.ledger._event(conn, row['task_id'], 'action.receipt', {'id': action_id, 'receipt': receipt})
        return receipt

    def reconcile_action(self, action_id, revision, observer):
        """Observe an ambiguous action; observer must not execute the effect again."""
        with self.ledger.transaction() as conn:
            row = self._action(conn, action_id)
            if row['revision'] != revision:
                raise LedgerError('Stale action revision.')
            if row['status'] not in ('unknown', 'executing'):
                raise LedgerError('Only ambiguous actions require reconciliation.')
        result = observer(json.loads(row['payload']))
        if not isinstance(result, dict) or type(result.get('verified')) is not bool:
            raise LedgerError('Reconciliation requires a JSON boolean and evidence.')
        if not result['verified']:
            return {'status': 'unknown', 'result': result}
        receipt = {'status': 'verified', 'result': result, 'reconciled': True}
        with self.ledger.transaction(write=True) as conn:
            latest = self._action(conn, action_id)
            if latest['status'] not in ('unknown', 'executing'):
                raise LedgerError('Action changed during reconciliation.')
            conn.execute("UPDATE actions SET status='verified',receipt=? WHERE id=?", (canonical(receipt), action_id))
            self.ledger._event(conn, row['task_id'], 'action.reconciled', {'id': action_id, 'receipt': receipt})
        return receipt
