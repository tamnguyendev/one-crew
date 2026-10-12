"""Detached local controller. Polling waits never invoke a model or extend a grant."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
import uuid

from .ledger import Ledger, LedgerError
from .supervisor import identity, native_python, probe
from .workflow import Workflow, task_lock


def workflow_for(ledger, task_id):
    if ledger.task(task_id, full=True)['handoff'].get('solution_delivery'):
        from .solution_delivery import Delivery
        return Delivery(ledger)
    if ledger.task(task_id, full=True)['handoff'].get('owned_execution'):
        from .owned import Owned
        return Owned(ledger)
    return Workflow(ledger)


def status(ledger, task_id):
    if task_id.startswith('CONSULT-'):
        from .consultations import view
        record=view(ledger,task_id)['runner']
        return dict(record,status=probe(record['identity'])) if record else {'status':'stopped'}
    with ledger.transaction() as conn:
        ledger._task(conn, task_id)
        rows = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='runner.started' ORDER BY seq DESC LIMIT 10", (task_id,)).fetchall()
    for row in rows:
        record = json.loads(row['payload'])
        state = probe(record['identity'])
        if state in ('alive', 'unknown'):
            return dict(record, status=state)
    return {'status': 'stopped'}


def _supervised(ledger, task_id, result):
    """A delivery root's live runner is always paired with a keeper; best-effort, never fails the start."""
    if task_id.startswith('CONSULT-'): return result
    try:
        if ledger.task(task_id, full=True)['handoff'].get('solution_delivery'):
            from .keeper import ensure
            result['keeper'] = ensure(ledger.state_root)
    except (OSError, ValueError) as error:
        result['keeper'] = {'status': 'unavailable', 'error': str(error)[:300]}
    return result


def _watch(ledger, task_id, every=60):
    """A detached delivery-root runner re-ensures its keeper, so a dead keeper is replaced while work continues.

    Only runners launched by start() (which records the launcher) do this; a foreground or fixture loop never spawns one."""
    try:
        detached = bool(os.environ.get('ONECREW_RUNNER_INITIATOR')) and bool(ledger.task(task_id, full=True)['handoff'].get('solution_delivery'))
    except (OSError, ValueError, sqlite3.Error):
        detached = False
    due = [time.monotonic()+every]

    def watch():
        if not detached or time.monotonic() < due[0]: return
        due[0] = time.monotonic()+every
        try:
            from .keeper import ensure
            ensure(ledger.state_root)
        except (OSError, ValueError):
            pass  # supervision is advisory; it never stops the coordinator
    return watch


def loop(ledger, task_id, interval=.5):
    with task_lock(ledger, task_id + '.runner'):
        if task_id.startswith('CONSULT-'):
            from .consultations import run
            # Same detached controller; one bounded review. Capacity waits are code, not model calls.
            while True:
                result=run(ledger,task_id)
                if result.get('waiting_reason')!='capacity':return result['status']
                time.sleep(interval)
        workflow = workflow_for(ledger, task_id)
        from .interventions import initiator, runtime_revision
        # Runtime identity + launcher make a code change or keeper restart visible as evidence.
        record = {'identity': identity(os.getpid()), 'started_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                  'runtime': runtime_revision(), 'initiator': initiator()}
        with ledger.transaction(write=True) as conn:
            workflow.control._execution(conn, task_id)
            ledger._event(conn, task_id, 'runner.started', record)
        outcome = 'interrupted'
        watch = _watch(ledger, task_id)
        try:
            while True:
                watch()
                seq, state = workflow.state(task_id)
                control = workflow.control.status(task_id)
                if state is None:
                    raise LedgerError('Enable a workflow before starting its controller.')
                if control['cancel_requested']:
                    outcome = control['status']  # may still be cancelling/unknown
                    return outcome
                if state['phase'] in ('completed', 'cancelled', 'failed'):
                    outcome = state['phase']
                    return outcome
                if workflow.control.clock() >= dt.datetime.fromisoformat(control['deadline']):
                    if hasattr(workflow, 'deadline_exhausted'):
                        # Delivery roots ask one typed budget question instead of an untyped block.
                        workflow.deadline_exhausted(task_id)
                        outcome = 'deadline'
                        return outcome
                    with task_lock(ledger, task_id):
                        seq, state = workflow.state(task_id)
                        if state['phase'] != 'blocked':
                            state['resume_phase'] = state['phase']
                        state['phase'] = 'blocked'
                        state['message'] = 'Root deadline exhausted, including queue/user/pause waits.'
                        workflow.persist(task_id, seq, state)
                    outcome = 'deadline'
                    return outcome
                if state['phase'] == 'blocked':
                    if state.get('mode') == 'owned_execution':
                        outcome = 'blocked'
                        return outcome
                    from .triage import handle
                    result = handle(workflow, task_id)
                    if result['status'] in ('blocked', 'cancelled'):
                        outcome = result['status']
                        return outcome
                    if result['status'] == 'waiting':
                        time.sleep(interval)
                    continue
                from .branch_inbox import blocks
                from .amendment import profile_for
                with ledger.transaction() as conn:
                    question_blocks = blocks(conn, task_id, 'scheduler' if profile_for(state, control).get('parallel') and state['phase'] in ('working', 'waiting_branches') else 'root')
                if control['status'] == 'paused' or question_blocks:
                    time.sleep(interval)
                    continue
                try:
                    result = workflow.run(task_id, steps=1)
                    # Passive waits (capacity, recovery backoff, a child question or solution hold) poll, never spin.
                    if result.get('waiting_reason') in ('capacity','decision','recovery') or result['phase'] in ('waiting','waiting_branches','waiting_operation'):
                        time.sleep(interval)
                except LedgerError as error:
                    # A foreground command may briefly own a checkpoint. Never launch through it.
                    if 'already owns' not in str(error):
                        raise
                    time.sleep(interval)
        except Exception as error:
            # Preserve paid/pending attempts; a parser/controller defect must not
            # leave the durable task claiming to run after its runner has died.
            import traceback
            traceback.print_exc()
            with task_lock(ledger,task_id):
                seq,state=workflow.state(task_id)
                if state is not None and state['phase'] not in ('completed','cancelled','failed'):
                    state.setdefault('resume_phase',state['phase'])
                    state.update(phase='blocked',message='Controller error: '+type(error).__name__+
                                 '; inspect runner log. Checkpoint and pending attempt preserved.',
                                 recovery={'kind':'controller','automatic_retry':False,'error_type':type(error).__name__})
                    workflow.persist(task_id,seq,state)
            outcome='blocked'
            return outcome
        finally:
            with ledger.transaction(write=True) as conn:
                ledger._event(conn, task_id, 'runner.stopped', {'identity': record['identity'], 'outcome': outcome})
            from .delivery import best_effort
            best_effort(ledger)


def start(ledger, task_id, initiator=None):
    if os.name != 'nt':
        raise LedgerError('Detached controller is verified only on native Windows.')
    current = status(ledger, task_id)
    if current['status'] not in ('stopped','dead'):
        # Already running: the keeper may have idle-exited (e.g. during a long decision wait); re-pair it.
        return _supervised(ledger, task_id, dict(current)) if current['status'] == 'alive' else current
    if task_id.startswith('CONSULT-'):
        from .consultations import view
        state={'phase':view(ledger,task_id)['status']}
    else:
        workflow = workflow_for(ledger, task_id)
        _, state = workflow.state(task_id)
    if state is None or state['phase'] in ('completed', 'failed', 'cancelled'):
        raise LedgerError('Enable/resume a non-terminal workflow before start.')
    directory = ledger.state_root/'runners'/uuid.uuid4().hex
    directory.mkdir(parents=True)
    argv = [native_python(), '-X', 'utf8', '-m', 'onecrew.runner', '--project', str(ledger.project),
            '--state-root', str(ledger.state_root), task_id]
    from .interventions import actor
    # The runner's own later actions are OneCrew's, not the launching entry's.
    env = dict(os.environ, ONECREW_RUNNER_INITIATOR=initiator or actor(), ONECREW_ACTOR='onecrew')
    with (directory/'stdout.txt').open('wb') as out, (directory/'stderr.txt').open('wb') as err:
        # Break away from the launcher's Job. If forbidden, fail rather than claiming durability.
        process = subprocess.Popen(argv, cwd=Path(__file__).resolve().parents[1], stdin=subprocess.DEVNULL,
                                   stdout=out, stderr=err, close_fds=True, env=env,
                                   creationflags=0x8 | 0x200 | 0x01000000)
    deadline = time.monotonic() + 5
    result = None
    while time.monotonic() < deadline:
        current = status(ledger, task_id)
        if current['status'] != 'stopped':
            result = dict(current, logs=str(directory))
            break
        if process.poll() is not None:
            return {'status': 'exited', 'exit_code': process.returncode, 'logs': str(directory)}
        time.sleep(.05)
    return _supervised(ledger, task_id, result or {'status': 'starting', 'identity': identity(process.pid), 'logs': str(directory)})


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--state-root', required=True, type=Path)
    parser.add_argument('task')
    args = parser.parse_args(argv)
    try:
        print(loop(Ledger(args.project, args.state_root), args.task), flush=True)
        return 0
    except (ValueError, OSError) as error:
        print(str(error), flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
