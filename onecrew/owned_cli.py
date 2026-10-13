"""Operator CLI for runtime-owned jobs."""
import argparse
import json
from pathlib import Path
from .ledger import Ledger, LedgerError
from .owned_intake import submit


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',type=Path,default=Path.cwd())
    parser.add_argument('--state-root',type=Path)
    group=parser.add_subparsers(dest='group',required=True).add_parser('job')
    commands=group.add_subparsers(dest='command',required=True)
    p=commands.add_parser('submit')
    p.add_argument('--goal');p.add_argument('--key',required=True)
    p.add_argument('--mode',choices=['audit','change','delivery','branch','work'],default='audit')
    p.add_argument('--contract',type=Path,help='Work contract JSON (mode work): goal, scope, preserve, acceptance, authority.')
    p.add_argument('--provider',choices=['codex','claude','kiro'])
    p.add_argument('--model')
    p.add_argument('--max-calls',type=int,help='New-job default: 100; explicit value overrides; replay retains original.')
    p.add_argument('--max-seconds',type=int,help='New-job default: 7200 (2 hours); explicit value overrides; replay retains original.')
    p.add_argument('--image');p.add_argument('--branch');p.add_argument('--remote')
    p.add_argument('--solution-id');p.add_argument('--solution-revision')
    p.add_argument('--android-build-config',type=Path,help='Operator-authorized fixed Android recipe JSON, not worker shell commands.')
    p.add_argument('--native-change-config',type=Path,help='Scoped Claude Flutter recipe; execution=workspace enables native edit/test sessions.')
    p.add_argument('--start',action='store_true')
    p.add_argument('--terminal',action='store_true',help='Start in background and open the grouped verbose monitor.')
    p=commands.add_parser('native-audit')
    p.add_argument('task');p.add_argument('--reference',required=True)
    p.add_argument('--terminal',action='store_true')
    p=commands.add_parser('recover-permissions')
    p.add_argument('task');p.add_argument('--reference',required=True)
    p=commands.add_parser('remove-deadline',help='Explicit operator request: retain call limits, disable total wall-clock deadline; does not resume.')
    p.add_argument('task');p.add_argument('--revision',required=True)
    p.add_argument('--key',required=True);p.add_argument('--reference',required=True)
    for name in ('start','run','status','outputs','cancel','resume'):
        p=commands.add_parser(name);p.add_argument('task')
        if name=='outputs': p.add_argument('--details',action='store_true')
        if name in ('start','resume'): p.add_argument('--terminal',action='store_true')
    args=parser.parse_args(argv)
    ledger=Ledger(args.project,args.state_root)
    try:
        if args.command=='submit':
            build=json.loads(args.android_build_config.read_text(encoding='utf-8-sig')) if args.android_build_config else None
            change=json.loads(args.native_change_config.read_text(encoding='utf-8-sig')) if args.native_change_config else None
            if args.contract:
                from .work_contract import load
                contract=load(args.contract)
            else:contract=None
            if args.goal is None and contract is None:raise LedgerError('--goal is required (or --contract in mode work).')
            result=submit(ledger,args.goal,args.key,**{k:getattr(args,k) for k in
                ('mode','provider','model','max_calls','max_seconds','image','branch','remote','solution_id','solution_revision')},
                android_build=build,native_change=change,contract=contract)
            if args.start or args.terminal:
                from .owned import Owned
                from .runner import start
                Owned(ledger).enable(result['id'])
                result['runner']=start(ledger,result['id'])
        elif args.command=='status':
            result=ledger.task(args.task,full=True)
        else:
            from .owned import Owned
            runtime=Owned(ledger)
            if args.command=='outputs':
                state=runtime.state(args.task)[1]
                if state is None: raise LedgerError('Job is queued with no outputs; use job start to enable execution.')
                result=state if args.details else output_card(runtime,args.task,state)
            elif args.command=='cancel': result=runtime.control.cancel(args.task)
            elif args.command=='recover-permissions':
                from .workspace_worker import recover_permissions
                result=recover_permissions(runtime,args.task,args.reference)
            elif args.command=='remove-deadline':
                from .budget import remove_deadline
                result=remove_deadline(runtime.control,args.task,args.revision,args.key,args.reference)
            elif args.command=='native-audit':
                from .native_audit import enable
                from .runner import start
                enable(runtime,args.task,args.reference)
                result=start(ledger,args.task)
            elif args.command=='run':
                runtime.enable(args.task);result=runtime.run(args.task,steps=100)
            else:
                from .runner import start
                runtime.enable(args.task)
                if args.command=='resume': runtime.resume(args.task)
                result=start(ledger,args.task)
        if getattr(args,'terminal',False):
            from .monitor import open_terminal
            try: result['terminal']=open_terminal(ledger)
            except (ValueError,OSError) as error:
                result['terminal']={'status':'unavailable','error':str(error),'runner_unaffected':True}
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError) as error:
        print(json.dumps({'error':str(error)},ensure_ascii=False));return 2


def output_card(runtime,task_id,state):
    import difflib
    from .usage import summarize
    from .skills import review as skill_review
    changes=[]
    for path,blob in state['files'].items():
        original=state['original'].get(path)
        if original==blob: continue
        before=runtime.store.read_blob(original).decode('utf-8-sig') if original else ''
        after=runtime.store.read_blob(blob).decode('utf-8-sig')
        diff=''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile=path,tofile=path))
        changes.append({'path':path,'original':original,'candidate':blob,'diff':diff[:16000],'truncated':len(diff)>16000})
    control=runtime.control.status(task_id)
    return {'mode':'owned_execution','task':task_id,'phase':state['phase'],'message':state['message'],'plan':state['plan'],
            'verification':state['verification'],'execution':control['status'],
            'native_audit':{k:v for k,v in state.get('native_audit',{}).items()
                            if k in ('stage','repairs','attempts','baseline_calls','workspace')},
            'native_change':{k:v for k,v in state.get('native_change',{}).items()
                             if k in ('stage','repairs','attempts','checks','applied','review_accepted','candidate_report','timeout_checkpoints','caller_summary','apk_build')},
            'assistance':state.get('assistance','unknown'),
            'report':state.get('report'),'candidate_snapshot':state['snapshot'],'original_workspace_modified':bool(state.get('workspace_applied')),
            'skills':[{k:s[k] for k in ('id','revision','reason')} for s in state.get('skills',[])],
            'skill_candidates':[v for v in skill_review(runtime.ledger)
                                if v['status']=='proposed' and task_id in v['tasks']],
            'build':state.get('build_evidence'),'operation':state.get('operation'),
            'progress':state.get('progress'),'recovery':state.get('recovery'),
            'effort_watch':state.get('effort_watch'),
            'changes':changes,'tests':[{'passed':t['passed'],'snapshot':t['evidence'].get('snapshot'),
                'exit_code':t['evidence'].get('exit_code')} for t in state['tests']],
            'deliveries':state['deliveries'],'branches':state.get('branches',[]),'pending_questions':runtime.ledger.requests(task_id,pending=True),
            'usage':summarize(state['usage'],control['attempts']),'review':state.get('reviews',[]),
            'tool_receipts':state['receipts'],'acceptance':state['acceptance']}
