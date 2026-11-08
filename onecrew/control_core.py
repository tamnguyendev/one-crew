"""Transactional admission and bounded execution bookkeeping, schemas v2/v3."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import sqlite3
import uuid

from .ledger import Ledger, LedgerError, canonical, content_hash, key_field, utcnow
from .budget_core import current as current_budget

ACTIVE = ('reserved', 'running', 'unknown')
RECORD_ONLY_KEYS = ('support:records',)          # 2.4-S1: the support anchor of a project; configure (job enable/start, any executor) refuses it


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
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        if version == 3:
            return {'schema_version': 3, 'changed': False}
        directory = ledger.state_root / 'backups'
        directory.mkdir(exist_ok=True)
        target = directory / (f'ledger-v{version}-' + uuid.uuid4().hex + '.sqlite3')
        # Separate read connection sees the committed v1 snapshot while the writer
        # reservation prevents another mutation between backup and migration.
        source = sqlite3.connect(ledger.path.as_uri() + '?mode=ro', uri=True)
        backup = sqlite3.connect(target)
        try:
            source.backup(backup)
        finally:
            source.close()
            backup.close()
        if version == 1:
            for statement in SCHEMA:
                conn.execute(statement)
        conn.execute('DROP INDEX one_active_attempt_per_task')
        conn.execute("CREATE UNIQUE INDEX one_active_attempt_per_unit ON attempts(task_id,COALESCE(json_extract(operation,'$.unit'),'root')) WHERE status IN ('reserved','running','unknown')")
        conn.execute('PRAGMA user_version=3')
        return {'schema_version': 3, 'changed': True, 'backup': str(target)}


class RootPolicy:
    """The installed core executes only explicit, current namespaced root grants."""
    def check(self, ledger, task_id, conn):
        from .v2 import gate, plan_binding, solution_link
        task = ledger._task(conn, task_id)
        binding = plan_binding.read(task)
        if not isinstance(binding, dict) or not str(binding.get('selector', '')).startswith('plan-ns:'):
            raise LedgerError('Installed execution requires an explicit namespaced root binding; legacy jobs use the checkout policy.')
        gate.require_plan(ledger, conn, task)
        linked = solution_link.check_task(ledger, conn, task)
        payload = json.loads(task['payload'])
        if payload.get('solution_required') and linked is None:
            raise LedgerError('Legacy SOL/spec authority requires the checkout policy; root approval is the installed source.')
        if conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind='solution.stopped'", (task_id,)).fetchone():
            raise LedgerError('Task stopped by a solution decision; it cannot resume.')
        return linked


class Control:
    def __init__(self, ledger, clock=None, *, policy=None):
        self.ledger = ledger
        self.policy = policy or RootPolicy()
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))

    def _execution(self, conn, task_id):
        task = self.ledger._task(conn, task_id)
        if conn.execute('PRAGMA user_version').fetchone()[0] not in (2, 3):
            raise LedgerError('Run core migrate before enabling execution.')
        execution = conn.execute('SELECT * FROM executions WHERE task_id=?', (task_id,)).fetchone()
        if execution is None:
            raise LedgerError('Task execution has not been configured.')
        return task, execution

    def configure(self, task_id, revision, configuration):
        """Trusted controller API. Does not convert inbox answers into authority."""
        with self.ledger.transaction(write=True) as conn:
            task = self.ledger._task(conn, task_id)
            if task['request_key'] in RECORD_ONLY_KEYS:
                raise LedgerError('This task only holds records (2.4 support feedback); it is never executed.')
            self.policy.check(self.ledger,task_id,conn)
            if conn.execute('PRAGMA user_version').fetchone()[0] not in (2, 3):
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

    def reserve(self, task_id, execution_revision, request_key, operation, *, on_reserved=None):
        key_field(request_key)
        unit = key_field(operation.get('unit', 'root'))
        encoded = canonical(operation)
        operation_hash = content_hash(operation)
        with self.ledger.transaction(write=True) as conn:
            task, execution = self._execution(conn, task_id)
            self.policy.check(self.ledger,task_id,conn)
            if execution['revision'] != execution_revision:
                raise LedgerError('Stale execution revision.')
            old = conn.execute('SELECT * FROM attempts WHERE task_id=? AND request_key=?',
                               (task_id, request_key)).fetchone()
            if old:
                if old['operation_hash'] != operation_hash:
                    raise LedgerError('Attempt key already bound to different operation.')
                return dict(old)
            from .v2.root_writer import guard as guard_root_writer
            guard_root_writer(self.ledger, conn, task)
            from .v2.items import check_operation  # v2: per-item call budget of the approved plan (no-op unless the gate is on)
            check_operation(self.ledger, conn, task, operation)
            if execution['cancel_requested'] or execution['status'] in ('cancelled', 'completed', 'failed', 'paused'):
                raise LedgerError('Execution is stopped or terminal.')
            budget = current_budget(conn, task)
            if self.clock() >= dt.datetime.fromisoformat(budget['deadline']):
                raise LedgerError('Root deadline exhausted.')
            from .admission_core import blocks
            if blocks(conn, task_id, unit):
                raise LedgerError('Task is waiting for user input.')
            limits = budget['limits']
            if execution['used_calls'] + execution['reserved_calls'] >= limits['max_calls']:
                raise LedgerError('Root call budget exhausted.')
            if budget.get('goal') and budget['goal']['remaining_calls'] <= 0:
                raise LedgerError('Shared goal call budget exhausted; child task cannot reset it.')
            if unit != 'root' and conn.execute('PRAGMA user_version').fetchone()[0] < 3:
                raise LedgerError('Parallel work units require core migrate to schema v3.')
            active = conn.execute("SELECT operation FROM attempts WHERE task_id=? AND status IN ('reserved','running','unknown')", (task_id,)).fetchall()
            if any(unit == 'root' or json.loads(r['operation']).get('unit', 'root') in ('root', unit) for r in active):
                raise LedgerError('Previous attempt must stop and reconcile first.')
            from .admission_core import active_consultations as active_count
            # An advisory attempt (RD-A's Jev call, `advisory` in its operation) is no worker and has no effect on the work: lost or running, it holds no
            # capacity. A lost verifier call has an unknown effect, so it keeps its place until a recorded release; the message says how.
            if conn.execute("SELECT COUNT(*) FROM attempts WHERE status IN ('reserved','running','unknown') "
                            "AND COALESCE(json_extract(operation,'$.advisory'),0)=0").fetchone()[0]+active_count(conn) >= 2:
                lost = [row[0] for row in conn.execute("SELECT json_extract(operation,'$.verifier_context') FROM attempts WHERE status='unknown' "
                                                       "AND json_extract(operation,'$.verifier_context') IS NOT NULL "
                                                       "AND COALESCE(json_extract(operation,'$.advisory'),0)=0").fetchall()]
                raise CapacityWait('Global worker capacity exhausted.' + (
                    f" {len(lost)} check call(s) of unknown outcome hold it ({', '.join(lost[:4])}) and nothing releases them by itself: check what they did, "
                    'list the runs with `onecrew engine check-runs PLAN`, then `onecrew engine release-check PLAN RUN --reason "..."` '
                    '(`onecrew verdict release-run` for a verdict run). The calls stay charged.' if lost else ''))
            generation = conn.execute('SELECT COALESCE(MAX(generation),0)+1 FROM attempts WHERE task_id=?',
                                      (task_id,)).fetchone()[0]
            attempt_id = 'ATT-' + uuid.uuid4().hex
            stamp = utcnow()
            conn.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                         (attempt_id, task_id, request_key, encoded, operation_hash, generation,
                          'reserved', 0, None, None, stamp, stamp))
            conn.execute("UPDATE executions SET reserved_calls=reserved_calls+1,status='running' WHERE task_id=?", (task_id,))
            self.ledger._event(conn, task_id, 'attempt.reserved', {'id': attempt_id, 'generation': generation})
            row = dict(conn.execute('SELECT * FROM attempts WHERE id=?', (attempt_id,)).fetchone())
            from .quota_core import reserve as reserve_quota
            reserve_quota(self, conn, row)
            if on_reserved:
                on_reserved(conn, row)
            return row

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
            self.policy.check(self.ledger,row['task_id'],conn)
            if execution['cancel_requested'] or execution['status'] == 'paused' or self.clock() >= dt.datetime.fromisoformat(current_budget(conn, task)['deadline']):
                raise LedgerError('Cancel or deadline prevents launch.')
            from .admission_core import blocks
            if blocks(conn, row['task_id'], json.loads(row['operation']).get('unit', 'root')):
                raise LedgerError('Pending question prevents launch.')
            from .quota_core import before_launch
            before_launch(self, conn, row)
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
                         (0 if not_started else 1, encoded, self.clock().isoformat(), attempt_id))
            active = conn.execute("SELECT 1 FROM attempts WHERE task_id=? AND status IN ('reserved','running','unknown')", (row['task_id'],)).fetchone()
            conn.execute("UPDATE executions SET status=CASE WHEN cancel_requested=1 THEN ? WHEN status='paused' THEN 'paused' ELSE ? END WHERE task_id=?",
                         ('cancelling' if active else 'cancelled', 'running' if active else 'queued', row['task_id']))
            self.ledger._event(conn, row['task_id'], 'attempt.settled', {'id': attempt_id, 'result': result})

    def cancel(self, task_id):
        from .budget_core import group
        with self.ledger.transaction(write=True) as conn:
            self._execution(conn, task_id)
            goal = group(conn,task_id)
            members = [row['task_id'] for row in goal['members']] if goal and goal['owner_task_id'] == task_id else [task_id]
            # Group membership is already approved and immutable. One write transaction
            # fences concurrent admission in every member project of this ledger.
            for member in members:
                execution = conn.execute('SELECT * FROM executions WHERE task_id=?',(member,)).fetchone()
                if not execution:
                    from .budget_core import root_id
                    if root_id(conn,member)==task_id:
                        self.ledger._event(conn,member,'execution.cancel_requested',{'requested_by_task':task_id,'not_enabled':True})
                        continue  # Root cancellation fences a child submitted before its enable checkpoint.
                    raise LedgerError('Goal member execution missing; cancellation rolled back.')
                active = conn.execute("SELECT 1 FROM attempts WHERE task_id=? AND status IN ('reserved','running','unknown')",
                                      (member,)).fetchone()
                conn.execute('UPDATE executions SET cancel_requested=1,status=? WHERE task_id=?',
                             ('cancelling' if active else 'cancelled', member))
                if not execution['cancel_requested']:
                    self.ledger._event(conn, member, 'execution.cancel_requested', {'requested_by_task':task_id})

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
            result['budget'] = current_budget(conn, task)
            from .budget_core import cancellation_status
            result['status'] = cancellation_status(task_id,execution,result['budget'])
            result['deadline'] = result['budget']['deadline']
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
            self.policy.check(self.ledger,row['task_id'],conn)
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
            self.policy.check(self.ledger,row['task_id'],conn)
            if row['status'] != 'authorized':
                raise LedgerError('Action is not authorized; unknown/executing actions must be reconciled.')
            from .v2.root_writer import guard as guard_root_writer
            guard_root_writer(self.ledger, conn, self.ledger._task(conn, row['task_id']), effect=True, action_id=action_id)
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
