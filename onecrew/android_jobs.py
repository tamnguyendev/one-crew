"""Detached fixed-recipe builds. Persistent submission, no AI and no implicit replay."""
import argparse
from contextlib import ExitStack
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import time

from .android_build import AndroidBuild
from .ledger import Ledger, LedgerError, canonical, utcnow
from .snapshots import durable_write
from .supervisor import identity, native_python, probe
from .workflow import task_lock

TERMINAL = {'succeeded', 'blocked', 'cancelled', 'interrupted'}


def read_record(path):
    for attempt in range(5):
        try:return json.loads(path.read_text(encoding='utf-8'))
        except PermissionError:
            if os.name!='nt' or attempt==4:raise
            time.sleep(.02*(attempt+1))


def paths(ledger, task, key):
    root = AndroidBuild(ledger).location(task, key)
    return root, root/'job.json'


def save(ledger, task, path, value):
    value['updated_at'] = utcnow()
    durable_write(path, canonical(value).encode())
    with ledger.transaction(write=True) as conn:
        ledger._event(conn, task, 'android.job', value)


def status(ledger, task, key):
    root, path = paths(ledger, task, key)
    if not path.exists(): return AndroidBuild(ledger).status(task, key)
    value = read_record(path)
    process = probe(value.get('identity')) if value.get('identity') else 'unknown'
    value['runner'] = process
    if value['status'] not in TERMINAL:
        if process == 'dead':
            value.update(status='interrupted', error='Build controller stopped; inspect logs. Same key never replays.')
        elif process == 'unknown': value['observed_status'] = 'unknown'
    if (root/'receipt.json').exists(): value['build'] = AndroidBuild(ledger).status(task, key)
    value['pending_questions'] = ledger.requests(task, pending=True)
    value['status_command'] = f'android status --from-task {task} --key {key}'
    return value


def dispatch(ledger, task, key, flutter_root, android_sdk, *, max_seconds=1200,
             dependency_policy='as-of', native_authorized=False, dependency_root=None, queue_seconds=1800):
    if os.name != 'nt': raise LedgerError('Detached builds require native Windows.')
    if not native_authorized: raise LedgerError('Explicit trusted native build authorization required.')
    if type(max_seconds) is not int or not 10 <= max_seconds <= 1800: raise LedgerError('Build limit must be 10-1800 seconds.')
    if type(queue_seconds) is not int or not 1 <= queue_seconds <= 28800: raise LedgerError('Queue limit must be 1-28800 seconds.')
    if dependency_policy not in ('as-of','head'): raise LedgerError('Unknown dependency policy.')
    root, path = paths(ledger, task, key)
    request = dict(task=task,key=key,flutter_root=str(Path(flutter_root).resolve()),
                   android_sdk=str(Path(android_sdk).resolve()),max_seconds=max_seconds,
                   dependency_policy=dependency_policy,native_authorized=True,
                   dependency_root=str(Path(dependency_root).resolve()) if dependency_root else None)
    with task_lock(ledger, 'android.launch.'+root.name):
        if path.exists():
            prior = read_record(path)
            if prior['request'] != request or prior['queue_seconds'] != queue_seconds:
                raise LedgerError('Build request key conflicts with prior configuration.')
            result=status(ledger,task,key)
            if result['status']=='succeeded':
                from .android_build import verify_apk
                artifact=result.get('apk') or result.get('build',{}).get('apk')
                if not artifact or verify_apk(Path(artifact['path']))!=artifact:
                    raise LedgerError('APK changed after successful build receipt.')
            return result
        if (root/'receipt.json').exists():
            prior = AndroidBuild(ledger).status(task,key)
            if prior['request'] != request: raise LedgerError('Build request key conflicts with prior configuration.')
            from .android_build import verify_apk
            if prior['status']=='succeeded' and verify_apk(Path(prior['apk']['path']))!=prior['apk']:
                raise LedgerError('APK changed after successful build receipt.')
            return prior
        now = dt.datetime.now(dt.timezone.utc)
        record = dict(request=request,status='queued',queue_seconds=queue_seconds,
                      queue_deadline=(now+dt.timedelta(seconds=queue_seconds)).isoformat(),
                      submitted_at=now.isoformat(),identity=None,logs=str(root))
        root.mkdir(parents=True,exist_ok=True)
        save(ledger,task,path,record)
        args = [native_python(),'-X','utf8','-m','onecrew.android_jobs','--project',str(ledger.project),
                '--state-root',str(ledger.state_root),'--task',task,'--key',key]
        try:
            with (root/'runner.out').open('wb') as out, (root/'runner.err').open('wb') as err:
                child = subprocess.Popen(args,cwd=Path(__file__).resolve().parents[1],stdin=subprocess.DEVNULL,
                    stdout=out,stderr=err,close_fds=True,creationflags=0x8 | 0x200 | 0x01000000)
            record['identity'] = identity(child.pid)
            save(ledger,task,path,record)
        except (OSError,ValueError) as error:
            record.update(status='blocked',error=str(error));save(ledger,task,path,record)
            return record
    until = time.monotonic()+3
    while time.monotonic()<until:
        result=status(ledger,task,key)
        if result.get('worker_started_at') or result['status'] in TERMINAL: return result
        time.sleep(.05)
    return status(ledger,task,key)


def cancel(ledger, task, key):
    root,path=paths(ledger,task,key)
    if not path.exists(): raise LedgerError('Legacy foreground build: cancel its source task.')
    value=status(ledger,task,key)
    if value['status'] in TERMINAL: return value
    durable_write(root/'cancel.json',canonical({'requested_at':utcnow()}).encode())
    return dict(value,status='cancelling')


def reconcile(ledger, task, key):
    """Persist observed process death once; never restart a build."""
    root,path=paths(ledger,task,key)
    with task_lock(ledger,'android.launch.'+root.name):
        value=read_record(path)
        if value['status'] not in TERMINAL and value.get('identity') and probe(value['identity'])=='dead':
            value.update(status='interrupted',error='Build controller stopped; no automatic replay.',finished_at=utcnow())
            save(ledger,task,path,value)
        return value


def run(ledger, task, key, interval=.5, builder=None):
    root,path=paths(ledger,task,key)
    until=time.monotonic()+10
    while True:
        try:
            with task_lock(ledger,'android.launch.'+root.name):
                record=read_record(path)
            break
        except LedgerError:
            if time.monotonic()>=until: raise
            time.sleep(.05)
    with task_lock(ledger,'android.worker.'+root.name):
        if record['status'] in TERMINAL: return record
        if record.get('identity') != identity(os.getpid()): raise LedgerError('Build worker identity mismatch.')
        record['worker_started_at']=utcnow();save(ledger,task,path,record)
        builder=builder or AndroidBuild(ledger)
        from .control import Control
        def cancelled():
            return (root/'cancel.json').exists() or Control(ledger).status(task)['cancel_requested']
        def guard():
            if cancelled(): raise LedgerError('Android build cancelled.')
            control=Control(ledger)
            if control.status(task)['configuration']['profile'].get('android_build'):
                from .sandbox_gate import task_guard
                task_guard(control,task)()
            if ledger.requests(task,pending=True): raise LedgerError('Required input arrived during build; stopped, no automatic replay.')
        try:
            while True:
                if cancelled():
                    record.update(status='cancelled');break
                control=Control(ledger)
                if control.status(task)['configuration']['profile'].get('android_build'):
                    from .sandbox_gate import task_guard
                    task_guard(control,task)()
                if dt.datetime.now(dt.timezone.utc)>=dt.datetime.fromisoformat(record['queue_deadline']):
                    record.update(status='blocked',error='Queue deadline exhausted; no build started.');break
                waiting='waiting_input' if ledger.requests(task,pending=True) else 'queued'
                if record['status']!=waiting:
                    record['status']=waiting;save(ledger,task,path,record)
                if waiting=='waiting_input': time.sleep(interval);continue
                with ExitStack() as stack:
                    try: stack.enter_context(task_lock(ledger,'android.capacity'))
                    except LedgerError as error:
                        if 'already owns' not in str(error): raise
                        time.sleep(interval);continue
                    guard()
                    record.update(status='running');save(ledger,task,path,record)
                    result=builder._build(**record['request'],external_guard=guard)
                    record.update(status='cancelled' if cancelled() else result['status'],
                                  apk=result.get('apk'),error=result.get('error'))
                    break
        except (ValueError,OSError) as error:
            record.update(status='blocked',error=str(error))
        record['finished_at']=utcnow();save(ledger,task,path,record)
        from .delivery import best_effort
        best_effort(ledger)
        return record


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--project',required=True);p.add_argument('--state-root',required=True)
    p.add_argument('--task',required=True);p.add_argument('--key',required=True)
    a=p.parse_args()
    run(Ledger(a.project,a.state_root),a.task,a.key)


if __name__=='__main__': main()
