"""Read-only task/worker console. Closing this viewer never cancels execution."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from .display_core import safe
from .ledger import Ledger, LedgerError, canonical, content_hash
from .snapshots import durable_write
from .supervisor import identity, native_python, probe
from .workflow import task_lock


def snapshot(ledger, task=None, all_projects=False, limit=12, verbose=False):
    if not 1<=limit<=100: raise LedgerError('Monitor limit must be 1-100 tasks.')
    result={'projects':[], 'total_tasks':0, 'shown_tasks':0, 'read_only':True}
    with ledger.transaction() as conn:
        if conn is None: return result
        if task: ledger._task(conn,task)
        where,args=('t.id=?',[task]) if task else (('1=1',[]) if all_projects else ('t.project_id=?',[ledger.project_id]))
        result['total_tasks']=conn.execute('SELECT COUNT(*) FROM tasks t WHERE '+where,args).fetchone()[0]
        rows=conn.execute("""SELECT t.*, (SELECT payload FROM events e WHERE e.task_id=t.id
            AND e.kind='workflow.checkpoint' ORDER BY seq DESC LIMIT 1) AS checkpoint
            FROM tasks t WHERE """+where+""" ORDER BY CASE WHEN EXISTS (
                SELECT 1 FROM events b WHERE b.task_id=t.id AND b.kind='android.job'
                AND json_extract(b.payload,'$.status') IN ('queued','waiting_input','running')
                AND b.seq=(SELECT MAX(b2.seq) FROM events b2 WHERE b2.task_id=t.id AND b2.kind='android.job'
                    AND json_extract(b2.payload,'$.request.key')=json_extract(b.payload,'$.request.key'))
            ) THEN 0 ELSE 1 END, CASE WHEN json_extract(checkpoint,'$.phase')
            IN ('completed','cancelled','failed') THEN 1 ELSE 0 END, t.created_at DESC LIMIT ?""",args+[limit]).fetchall()
        version=conn.execute('PRAGMA user_version').fetchone()[0];projects={}
        for row in rows:
            state=json.loads(row['checkpoint']) if row['checkpoint'] else {};payload=json.loads(row['payload'])
            execution=conn.execute('SELECT * FROM executions WHERE task_id=?',(row['id'],)).fetchone() if version>=2 else None
            profile=json.loads(execution['configuration']).get('profile',{}) if execution else {}
            profile=(state.get('amendment') or {}).get('profile',profile);worker=state.get('worker') or profile
            phase=state.get('phase','queued')
            if execution and (execution['cancel_requested'] or execution['status']=='paused'): phase=execution['status']
            item={'id':row['id'],'goal':safe(payload.get('goal',payload.get('spec_id',''))),
                  'phase':phase,'provider':safe(worker.get('provider','unknown')),'model':safe(worker.get('model','unknown')),
                  'used_calls':execution['used_calls'] if execution else 0,'workers':[], 'questions':[], 'builds':[]}
            runner=conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='runner.started' ORDER BY seq DESC LIMIT 1",(row['id'],)).fetchone()
            item['runner']=probe(json.loads(runner['payload']).get('identity')) if runner else 'not recorded'
            if version>=2:
                attempts=conn.execute("""SELECT * FROM attempts WHERE task_id=? ORDER BY
                    CASE WHEN status IN ('reserved','running','unknown') THEN 0 ELSE 1 END,
                    updated_at DESC, generation DESC LIMIT 100""",(row['id'],)).fetchall()
                units=set()
                for attempt in attempts:
                    op=json.loads(attempt['operation']);unit=op.get('unit','root')
                    if unit in units: continue
                    units.add(unit)
                    item['workers'].append({'unit':safe(unit),'stage':safe(op.get('stage','unknown')),
                        'status':attempt['status'],'attempt':attempt['id'],
                        'provider':safe(op.get('provider',worker.get('provider','unknown'))),
                        'model':safe(op.get('model',worker.get('model','unknown'))),
                        'model_source':'attempt' if op.get('model') else 'current configuration'})
            for req in conn.execute("SELECT id,revision,payload FROM requests WHERE task_id=? AND state='pending' ORDER BY created_at LIMIT 5",(row['id'],)):
                question=json.loads(req['payload'])
                item['questions'].append({'id':req['id'],'question':safe(question['question']),
                    'revision':req['revision'],'options':[{k:safe(v,200) for k,v in o.items()} for o in question['options']],
                    'reply_command':f"request reply {req['id']} --revision {req['revision']} --choice <option-id>"})
            build_keys=set()
            for event in conn.execute("SELECT payload FROM events WHERE task_id=? AND kind IN ('android.build','android.job') ORDER BY seq DESC LIMIT 80",(row['id'],)):
                build=json.loads(event['payload']);key=build['request']['key']
                if key in build_keys: continue
                build_keys.add(key)
                value={'key':safe(key),'status':safe(build['status']),'error':safe(build.get('error'))}
                latest_job=conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='android.job' AND json_extract(payload,'$.request.key')=? ORDER BY seq DESC LIMIT 1",(row['id'],key)).fetchone()
                if latest_job:
                    job=json.loads(latest_job['payload']);value['status']=job['status']
                    if job['status'] in ('running','queued','waiting_input') and job.get('identity') and probe(job['identity'])=='dead':
                        value.update(status='interrupted',error='Build controller stopped; no automatic replay.')
                    value['runner']=probe(job.get('identity')) if job.get('identity') else 'unknown'
                    receipt=conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='android.build' AND json_extract(payload,'$.request.key')=? ORDER BY seq DESC LIMIT 1",(row['id'],key)).fetchone()
                    if receipt: build=json.loads(receipt['payload'])
                if build.get('apk'): value['apk']=safe(build['apk'].get('path'),500)
                if verbose:
                    value['log_tail']=build_tail(row['id'],key,build)
                item['builds'].append(value)
                if len(item['builds'])>=3: break
            if verbose:
                item['plan']=safe(state.get('plan'),500);item['message']=safe(state.get('message'),500)
                item['tools']=[{'index':x.get('index'),'action':safe(x.get('action'))} for x in state.get('receipts',[])[-8:]]
                item['events']=[{'seq':e['seq'],'kind':safe(e['kind']),'at':e['created_at']} for e in conn.execute(
                    'SELECT seq,kind,created_at FROM events WHERE task_id=? ORDER BY seq DESC LIMIT 6',(row['id'],))][::-1]
            projects.setdefault(row['project_path'],[]).append(item)
        result['projects']=[{'path':safe(path,500),'tasks':items} for path,items in projects.items()]
        result['shown_tasks']=len(rows)
    return result


def build_tail(task,key,build):
    text=(build.get('stdout_tail','')+'\n'+build.get('stderr_tail',''))[-3000:]
    if build['status']=='building' and build.get('build_directory'):
        # Read only this adapter's known disposable export, never arbitrary event paths.
        allowed=Path.home()/'OneCrewBuilds'/content_hash({'task':task,'key':key})[:24]/'source'
        directory=Path(build['build_directory'])
        if directory.resolve().is_relative_to(allowed.resolve()) and directory.is_dir():
            for path in sorted(directory.glob('*.*')):
                if path.suffix not in ('.out','.err') or path.is_symlink(): continue
                try:
                    with path.open('rb') as stream:
                        stream.seek(max(0,path.stat().st_size-2000));text+='\n'+stream.read(2000).decode('utf-8',errors='replace')
                except OSError: pass
    return [safe(line,240) for line in text.splitlines()[-8:] if line.strip()]


def render(value, verbose=False):
    lines=['ONECREW | PROJECT > TASK > WORKER',
           f"Read-only monitor | {value['shown_tasks']}/{value['total_tasks']} tasks | Ctrl+C closes viewer, NOT workers."]
    if not value['projects']: lines.append('No tasks recorded in this scope.')
    for project in value['projects']:
        lines+=['',project['path']]
        for task in project['tasks']:
            lines += [f"  [{task['phase']}] {task['id']} | runner={task['runner']} | calls={task['used_calls']}",
                      f"    {task['goal']}",f"    Configured: {task['provider']} / {task['model']}"]
            if not task['workers']: lines.append('    No worker invocation recorded.')
            for worker in task['workers']:
                lines.append(f"    - {worker['unit']} [{worker['status']}] {worker['stage']} | {worker['provider']} / {worker['model']} ({worker['model_source']})")
            for question in task['questions']:
                lines.append(f"    INPUT {question['id']}: {question['question']} [waiting; skip does not approve]")
                lines += [f"      {o['id']}: {o['label']}" for o in question['options']]
                lines.append('      '+question['reply_command'])
            for build in task['builds']:
                lines.append(f"    BUILD {build['key']} [{build['status']}] {build.get('error','')}")
                if build.get('apk'): lines.append('      APK: '+build['apk'])
                for line in build.get('log_tail',[]): lines.append('      '+line)
            if verbose:
                lines += ['    Plan: '+task['plan'],'    Detail: '+task['message']]
                lines += [f"    tool #{tool['index']}: {tool['action']}" for tool in task['tools']]
                lines += [f"    {e['at']} #{e['seq']} {e['kind']}" for e in task['events']]
    return '\n'.join(lines)


def marker(ledger, task, all_projects, verbose, limit):
    key=content_hash({'project':None if all_projects else ledger.project_id,'task':task,
                      'all_projects':all_projects,'verbose':verbose,'limit':limit})[:24]
    return ledger.state_root/'monitors'/(key+'.json')


def open_terminal(ledger, task=None, *, all_projects=True, verbose=True, limit=12):
    if os.name!='nt': raise LedgerError('Separate monitor terminal is verified only on Windows.')
    if task: ledger.task(task)
    path=marker(ledger,task,all_projects,verbose,limit)
    with task_lock(ledger,'monitor.'+path.stem):
        for candidate in (path,path.with_suffix('.launch.json')):
            if candidate.exists():
                old=json.loads(candidate.read_text(encoding='utf-8'));current=probe(old.get('identity'))
                if current!='dead': return dict(old,status=current if old['status']=='alive' else 'starting',reused=True)
        args=[native_python(),'-X','utf8','-m','onecrew.monitor','--project',str(ledger.project),
              '--state-root',str(ledger.state_root),'monitor','--announce','--limit',str(limit)]
        if task: args+=['--task',task]
        if all_projects: args+=['--all-projects']
        if verbose: args+=['--verbose']
        child=subprocess.Popen(args,cwd=Path(__file__).resolve().parents[1],close_fds=True,
                               creationflags=0x10 | 0x01000000)  # visible new console, break away from caller's Job
        record={'identity':identity(child.pid),'status':'starting','read_only':True}
        # Child acknowledges separately, so a successful spawn is not presented as ready.
        launch=path.with_suffix('.launch.json');durable_write(launch,canonical(record).encode())
        end=time.monotonic()+3
        while time.monotonic()<end:
            if path.exists():
                ready=json.loads(path.read_text(encoding='utf-8'))
                if ready.get('identity')==record['identity']: return ready
            if child.poll() is not None: return dict(record,status='exited',exit_code=child.returncode)
            time.sleep(.05)
        return record


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',type=Path,default=Path.cwd());parser.add_argument('--state-root',type=Path)
    p=parser.add_subparsers(dest='command',required=True).add_parser('monitor')
    p.add_argument('--task');p.add_argument('--all-projects',action='store_true');p.add_argument('--verbose',action='store_true')
    p.add_argument('--once',action='store_true');p.add_argument('--json',action='store_true');p.add_argument('--terminal',action='store_true')
    p.add_argument('--limit',type=int,default=12);p.add_argument('--interval',type=float,default=2)
    p.add_argument('--announce',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args(argv)
    if not 1<=args.limit<=100 or not 1<=args.interval<=60: parser.error('limit 1-100, interval 1-60 seconds')
    if args.json and not args.once: parser.error('--json requires --once')
    ledger=Ledger(args.project,args.state_root)
    try:
        if args.terminal:
            print(json.dumps(open_terminal(ledger,args.task,all_projects=args.all_projects,verbose=args.verbose,limit=args.limit)));return 0
        if os.name=='nt' and sys.stdout.isatty():
            api=ctypes.WinDLL('kernel32');api.SetConsoleTitleW('OneCrew | Agents')
            from ctypes import wintypes as w
            api.GetStdHandle.restype=w.HANDLE
            api.GetConsoleMode.argtypes=[w.HANDLE,ctypes.POINTER(w.DWORD)]
            api.SetConsoleMode.argtypes=[w.HANDLE,w.DWORD]
            handle=api.GetStdHandle(-11);mode=w.DWORD()
            if api.GetConsoleMode(handle,ctypes.byref(mode)): api.SetConsoleMode(handle,mode.value|4)
        previous=None
        while True:
            value=snapshot(ledger,args.task,args.all_projects,args.limit,args.verbose)
            output=json.dumps(value,ensure_ascii=False,indent=2) if args.json else render(value,args.verbose)
            if output!=previous:
                if sys.stdout.isatty() and not args.once: print('\x1b[2J\x1b[H',end='')
                print(output,flush=True);previous=output
            if args.announce:
                record={'identity':identity(os.getpid()),'status':'alive','read_only':True,'console_attached':bool(ctypes.WinDLL('kernel32').GetConsoleWindow())}
                durable_write(marker(ledger,args.task,args.all_projects,args.verbose,args.limit),canonical(record).encode())
                args.announce=False
            if args.once: return 0
            time.sleep(args.interval)
    except KeyboardInterrupt: return 0
    except (ValueError,OSError) as error:
        print('Monitor: '+safe(error,500),file=sys.stderr);return 2


if __name__=='__main__': raise SystemExit(main())
