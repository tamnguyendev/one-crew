"""Managed artifact operations: safe-point acknowledgements and durable recovery.

NativeExecutor owns the artifact protocol and scoped candidate isolation.
Supervisor owns every process, termination proof and launch/settlement fence.
Control attempts plus existing event/blob storage are the only durable journal.
Pause waits for the current bounded operation; it never suspends a live process.
"""
import json

from ..common_executor import NativeExecutor
from ..ledger import LedgerError, canonical, content_hash, text_field
from ..control_core import Control
from ..process_core import Supervisor
from .. import host_status_core
from ..snapshots import Snapshots
from . import executors

KIND = 'executor.managed'


def unresolved(ledger, selector, conn=None):
    """Prepared operation results that cannot safely be replayed by a replan.

    A Control-confirmed not-started preflight is excluded; a charged/ambiguous
    attempt with no durable candidate retains its ownership across generations.
    """
    from . import plan as plans, plan_binding
    if conn is None:
        with ledger.transaction() as connection:
            return unresolved(ledger, selector, connection)
    root = plans.anchor_events(ledger, conn, selector)
    rows = conn.execute("SELECT e.payload,e.task_id FROM events e JOIN tasks t ON t.id=e.task_id WHERE e.kind=? AND t.project_id=? ORDER BY e.seq",
                        (KIND, ledger.project_id)).fetchall()
    histories = {}
    for row in rows:
        task = ledger._task(conn, row['task_id'])
        binding = plan_binding.submitted(conn, task) or plan_binding.read(task)
        if not binding or binding['root_task_id'] != root['task_id']:
            continue
        value = json.loads(row['payload'])
        histories.setdefault(value['attempt'], []).append(value)
    pending = []
    for attempt_id, history in histories.items():
        prepared = next((p for p in history if p['phase'] == 'prepared'), None)
        if prepared is None or any(p['phase'] == 'candidate' for p in history):
            continue
        attempt = conn.execute('SELECT status,charged,task_id FROM attempts WHERE id=?', (attempt_id,)).fetchone()
        if attempt and attempt['status'] == 'settled' and not attempt['charged']:
            continue
        pending.append({'attempt': attempt_id, 'node': prepared['node'], 'task': attempt['task_id'] if attempt else None,
                        'status': attempt['status'] if attempt else 'unknown', 'reason': 'managed result lacks a durable candidate; reconcile before replay'})
    return pending


class ManagedExecutor(executors.Executor):
    requires_pin = True
    declaration = executors.Declaration('managed-native-artifact', 'managed',
        ('start', 'stop', 'pause_at_safe_point', 'isolate', 'measure', 'recover'), ('time',))

    def __init__(self, ledger, worker_factory=None, *, initialize=True):
        self.native = NativeExecutor(ledger, worker_factory=worker_factory) if initialize else None
        self.control = self.native.control if self.native else Control(ledger)
        self.ledger = ledger

    def __call__(self, ledger, control, task, node, attempt):
        return self.start(ledger, control, task, node, attempt)

    def _history(self, attempt_id, conn=None):
        if conn is None:
            with self.ledger.transaction() as connection:
                return self._history(attempt_id, connection)
        attempt = self.control._attempt(conn, attempt_id)
        rows = conn.execute("SELECT seq,payload FROM events WHERE task_id=? AND kind=? AND json_extract(payload,'$.attempt')=? ORDER BY seq",
                            (attempt['task_id'], KIND, attempt_id)).fetchall()
        return [dict(json.loads(row['payload']), event=row['seq']) for row in rows]

    def _write(self, attempt_id, phase, **facts):
        with self.ledger.transaction(write=True) as conn:
            attempt = self.control._attempt(conn, attempt_id)
            value = dict(attempt=attempt_id, attempt_generation=attempt['generation'], phase=phase, **facts)
            value['id'] = content_hash(value)
            old = conn.execute("SELECT seq FROM events WHERE task_id=? AND kind=? AND json_extract(payload,'$.id')=?",
                               (attempt['task_id'], KIND, value['id'])).fetchone()
            if old:
                return dict(value, event=old['seq'])
            self.ledger._event(conn, attempt['task_id'], KIND, value)
            return dict(value, event=conn.execute('SELECT last_insert_rowid()').fetchone()[0])

    @staticmethod
    def _process_result(attempt):
        try:
            body = json.loads(attempt.get('result') or '{}')
        except (ValueError, TypeError):
            return {}
        return body if isinstance(body, dict) else {}

    def _candidate(self, history):
        saved = next((p for p in reversed(history) if p['phase'] == 'candidate'), None)
        if saved is None:
            return None
        candidate = saved['candidate']
        body = json.loads(Snapshots(self.ledger.state_root).read_blob(candidate['receipt']))
        if (body.get('kind') != 'native-node-receipt' or body.get('attempt') != saved['attempt']
                or body.get('artifact') != candidate['artifact']):
            raise LedgerError('The retained candidate is not bound to this managed attempt.')
        return dict(candidate)

    def _safe(self, attempt):
        body = self._process_result(attempt)
        identity = json.loads(attempt.get('identity') or '{}')
        return (attempt['status'] == 'settled' and identity.get('job_contained') is True
                and body.get('tree_stopped') is True and body.get('reason') is None and body.get('exit_code') == 0
                and body.get('stdout') and body.get('stderr') and type(body.get('seconds')) in (int, float))

    def _ack_pause(self, attempt_id):
        history = self._history(attempt_id)
        request = next((p for p in reversed(history) if p['phase'] == 'pause_requested'), None)
        if request is None or any(p['phase'] == 'paused' for p in history):
            return
        attempt = self.control.attempt(attempt_id)
        if not self._safe(attempt):
            return
        # Only now can Control pause the execution. During Supervisor.run a
        # Control.pause would kill the current operation instead of waiting.
        self.control.pause(attempt['task_id'])
        proof = Snapshots(self.ledger.state_root).blob(canonical(self._process_result(attempt)).encode())
        self._write(attempt_id, 'paused', safe_point='bounded_operation_completed', process_receipt=proof,
                    request=request['event'], candidate=self._candidate(history), text='đã dừng tại điểm an toàn')

    def start(self, ledger, control, task, node, attempt):
        if self.native is None:
            raise LedgerError('This adapter is connected only for state/control/recovery, not a fresh launch.')
        if ledger is not self.ledger or control.ledger.project_id != self.ledger.project_id:
            raise LedgerError('Managed execution requires its connected ledger and Control.')
        # Publish launch intent atomically before any provider/process dispatch.
        with ledger.transaction(write=True) as conn:
            current = control._attempt(conn, attempt['id'])
            history = self._history(attempt['id'], conn)
            dispatched = any(p['phase'] == 'prepared' for p in history)
            original = next((p for p in history if p['phase'] == 'prepared'), None)
            if original and (original['task_revision'] != task['revision'] or original['node_sha'] != content_hash(node)):
                raise LedgerError('A managed attempt cannot be rebound to different node inputs or task revision.')
            if not dispatched:
                if current['status'] != 'reserved':
                    raise LedgerError('The managed attempt is not a fresh reservation; reconcile it first.')
                ledger._event(conn, task['id'], KIND, {'attempt': attempt['id'], 'attempt_generation': current['generation'],
                    'phase': 'prepared', 'task_revision': task['revision'], 'node': node['id'], 'node_sha': content_hash(node),
                    'read': list(node['read']), 'write': list(node['write']),
                    'inputs_sha': content_hash(node.get('input_artifacts', {}))})
        if dispatched:
            recovered = self.recover(attempt['id'])
            if recovered.get('candidate'):
                return recovered['candidate']
            raise LedgerError('Managed intent already exists; ' + recovered['state'] + ', no process is replayed.')
        candidate = self.native.start(ledger, control, task, node, attempt)
        settled = control.attempt(attempt['id'])
        if not self._safe(settled):
            raise LedgerError('A managed candidate needs a successful, settled Supervisor process-tree receipt.')
        self._write(attempt['id'], 'candidate', candidate=candidate)
        self._ack_pause(attempt['id'])
        return candidate

    def pause_at_safe_point(self, attempt_id, reason='The branch is held'):
        text_field(reason, 'pause reason', 1000)
        self._write(attempt_id, 'pause_requested', reason=reason)
        self._ack_pause(attempt_id)
        return self.state(attempt_id)

    def stop(self, attempt_id, reason='Stop this managed operation'):
        text_field(reason, 'stop reason', 1000)
        attempt = self.control.attempt(attempt_id)
        self._write(attempt_id, 'stop_requested', reason=reason)
        self.control.cancel(attempt['task_id'])
        return self.state(attempt_id)

    def state(self, attempt_id):
        attempt = self.control.attempt(attempt_id)
        history = self._history(attempt_id)
        candidate = self._candidate(history)
        phases = {p['phase'] for p in history}
        proof = self._process_result(attempt)
        stopped = attempt['status'] == 'settled' and proof.get('tree_stopped') is True
        if 'stop_requested' in phases:
            state = 'stopped' if stopped else 'stop_requested'
        elif 'paused' in phases and self._safe(attempt):
            state = 'paused'
        elif 'pause_requested' in phases:
            state = 'pause_requested'
        elif candidate and self._safe(attempt):
            state = 'completed'
        else:
            state = 'running' if attempt['status'] == 'running' else 'unknown'
        host = host_status_core.status(self.ledger.state_root)
        return {'state': state, 'attempt': attempt_id, 'generation': attempt['generation'], 'candidate': candidate,
                'safe_point_acknowledged': state == 'paused', 'tree_stopped': stopped,
                'text': 'đã dừng tại điểm an toàn' if state == 'paused' else 'pause requested, not confirmed' if state == 'pause_requested' else state,
                'measured': {'seconds': proof.get('seconds', 'unknown'), 'calls': 'not_measured'},
                'host': host, 'automatic_restart': False, 'restart_reason': host['text']}

    def measure(self, attempt_id):
        return self.state(attempt_id)['measured']

    def isolate(self, attempt_id):
        history = self._history(attempt_id)
        prepared = next((p for p in history if p['phase'] == 'prepared'), None)
        if prepared is None:
            raise LedgerError('No sealed managed operation exists for isolation.')
        return {'attempt': attempt_id, 'write_scope': prepared['write'], 'read_scope': prepared['read'],
                'candidate': self._candidate(history), 'writes': 'artifact-only scoped snapshot output; no project apply',
                'read_isolation': False, 'network_isolation': False}

    def recover(self, attempt_id):
        attempt = self.control.attempt(attempt_id)
        before = attempt['status']
        if before != 'settled':
            reconciled = Supervisor(self.control).reconcile(attempt_id)
            self._write(attempt_id, 'reconciled', previous=before, result=reconciled)
        self._ack_pause(attempt_id)
        result = self.state(attempt_id)
        # A settled process without a saved candidate is still an ambiguous
        # operation result. There is deliberately no worker.run call here.
        if result['candidate'] is None and result['state'] not in ('paused', 'stopped', 'stop_requested', 'pause_requested'):
            result.update(state='unknown', text='operation result unknown; reconcile before any retry')
        return result
