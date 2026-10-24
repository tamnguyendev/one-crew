"""Managed artifact operations: safe-point acknowledgements and durable recovery.

NativeExecutor owns the artifact protocol and scoped candidate isolation.
Supervisor owns every process, termination proof and launch/settlement fence.
Control attempts plus existing event/blob storage are the only durable journal.
Pause waits for the current bounded operation; it never suspends a live process.
"""
import json
import time

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


def hold_views(ledger, selector, conn=None):
    """W33a (T15b [E1], [E3], [E4]): the record of HOW each running node that an open finding holds is held, read-only, from the executor's
    declaration — `executors.hold_plan`: a managed attempt (one with an `executor.managed` history) can be asked to pause at a safe point, so
    its state is at most "pause requested" until the Supervisor confirms; any other attempt (a hook session) only loses write permission,
    and the words say so ("đã ngừng cấp quyền ghi"), never "đã dừng"/"paused". One row per held active node:
    {node, attempt, findings, plan, text, requested (a pause was already asked), confirmed (the safe point acknowledged it)}."""
    from . import engine
    if conn is None:
        with ledger.transaction() as connection:
            return hold_views(ledger, selector, connection)
    view = engine.state(ledger, selector, conn)
    held = view.get('finding_blockers') or {}
    rows, adapter = [], None
    for active in view.get('active_nodes', []):
        findings_ = held.get(active['node'])
        if not findings_: continue
        adapter = adapter or ManagedExecutor(ledger, initialize=False)
        history = adapter._history(active['attempt'], conn)
        managed = any(p['phase'] == 'prepared' for p in history)
        plan = executors.hold_plan(ManagedExecutor.declaration if managed else executors.HookAdapter.declaration)
        rows.append({'node': active['node'], 'attempt': active['attempt'], 'findings': sorted(findings_), 'plan': plan, 'text': executors.hold_text(plan),
                     'requested': any(p['phase'] in ('pause_requested', 'paused', 'stop_requested') for p in history),
                     'confirmed': any(p['phase'] == 'paused' for p in history)})
    return rows


def hold_for_findings(ledger, selector, conn=None, *, reason=None):
    """W18/W36 (T07b [E16], T15c [E7]): when an open finding holds a node whose managed attempt is still running, ask THAT
    attempt to pause at its next safe point. Nothing is sent to an attempt without a managed history (a hook executor only
    loses write permission through the exported active plan, T15c [E9]; `hold_views` records that as the hold); a request
    already made is not repeated; the acknowledgement itself still comes only from the real Supervisor safe point (_ack_pause).
    Returns the requests made."""
    requests = []
    adapter = None
    for row in hold_views(ledger, selector, conn):
        if row['plan']['command'] != 'pause_at_safe_point' or row['requested']: continue   # declaration first: no pause command exists for a hook
        adapter = adapter or ManagedExecutor(ledger, initialize=False)
        text = reason or f'Open finding {", ".join(row["findings"])} holds node {row["node"]}'
        adapter.pause_at_safe_point(row['attempt'], text)
        requests.append({'node': row['node'], 'attempt': row['attempt'], 'findings': row['findings'], 'reason': text})
    return requests


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
        prepared = self.native.prepare(ledger, control, task, node, attempt)
        # Durable launch intent (W37b crash point b): the base snapshot and the exact node are what a rebuild needs after a
        # crash between the settled process and the candidate checkpoint. Written before the provider launch.
        self._write(attempt['id'], 'dispatching', base=prepared['base'], node_definition=node,
                    prompt_sha=content_hash(prepared['prompt']), profile=prepared['profile'])
        started = time.monotonic()
        prepared['worker'].run(attempt, prepared['prompt'], prepared['schema'], prepared['profile'])
        settled = control.attempt(attempt['id'])
        if not self._safe(settled):
            raise LedgerError('A managed candidate needs a successful, settled Supervisor process-tree receipt.')
        candidate = self.native.finish(ledger, task, node, attempt, prepared, settled, elapsed=time.monotonic() - started)
        self._write(attempt['id'], 'candidate', candidate=candidate)
        self._ack_pause(attempt['id'])
        return candidate

    def _rebuild(self, attempt_id):
        """W37b crash point (c): the process settled successfully and its launch intent is on record, but the controller died before
        the candidate checkpoint. Rebuild the candidate from the durable evidence only: the recorded base snapshot, the recorded node,
        and the worker's result read from the settled process outputs. No worker.run, no new charge. None when any piece is missing,
        so the attempt stays `unknown` rather than being guessed."""
        attempt = self.control.attempt(attempt_id)
        if not self._safe(attempt): return None
        history = self._history(attempt_id)
        prepared = next((p for p in history if p['phase'] == 'prepared'), None)
        intent = next((p for p in reversed(history) if p['phase'] == 'dispatching'), None)
        if prepared is None or intent is None or not intent.get('base') or not isinstance(intent.get('node_definition'), dict): return None
        node = intent['node_definition']
        if content_hash(node) != prepared['node_sha'] or node.get('id') != prepared['node']: return None
        if self.native is None: return None             # a state/recovery-only connection has no worker factory to read the result with
        task = self.ledger.task(attempt['task_id'], full=True)
        try:
            context = self.native.rebuild_context(self.ledger, self.control, node, intent['base'])
            seconds = self._process_result(attempt).get('seconds')
            candidate = self.native.finish(self.ledger, task, node, attempt, context, attempt,
                                           elapsed=seconds if isinstance(seconds, (int, float)) else 0, rebuilt_from='settled-process')
        except (LedgerError, OSError, ValueError, KeyError, TypeError):
            return None                                  # the durable outputs do not yield a candidate: the result stays unknown
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
        elif (attempt['status'] == 'settled' and proof.get('reason') is None and proof.get('tree_stopped') is True
              and json.loads(attempt.get('identity') or '{}').get('job_contained') is True
              and isinstance(proof.get('exit_code'), int) and not isinstance(proof.get('exit_code'), bool) and proof['exit_code'] != 0):
            state = 'failed'          # the contained process itself ended with a non-zero exit: a KNOWN failure. An interrupted or
                                      # timed-out supervisor (reason set) stays unknown: its effect may have happened.
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
        if result['candidate'] is None and result['state'] == 'unknown':
            rebuilt = self._rebuild(attempt_id)          # durable evidence only; never a worker.run
            if rebuilt is not None:
                self._write(attempt_id, 'candidate', candidate=rebuilt, rebuilt_from='settled-process')
                self._ack_pause(attempt_id)
                result = self.state(attempt_id)
                result['rebuilt_from'] = 'settled-process'
        # A settled process without a saved candidate and without enough durable
        # evidence is still an ambiguous operation result. There is deliberately no worker.run call here.
        if result['candidate'] is None and result['state'] not in ('paused', 'stopped', 'stop_requested', 'pause_requested', 'failed'):
            result.update(state='unknown', text='operation result unknown; reconcile before any retry')
        elif result['candidate'] is None and result['state'] == 'failed':
            result['text'] = 'the managed process failed (known result); repair or replan, nothing to replay'
        return result
