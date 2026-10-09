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
    p.add_argument('--goal',required=True);p.add_argument('--key',required=True)
    p.add_argument('--mode',choices=['audit','change','delivery'],default='audit')
    p.add_argument('--provider',choices=['codex','claude','kiro'],default='codex')
    p.add_argument('--model',default='gpt-6-luna')
    p.add_argument('--max-calls',type=int,default=20);p.add_argument('--max-seconds',type=int,default=1200)
    p.add_argument('--image');p.add_argument('--branch');p.add_argument('--remote')
    p.add_argument('--start',action='store_true')
    for name in ('start','run','status','outputs','cancel','resume'):
        p=commands.add_parser(name);p.add_argument('task')
    args=parser.parse_args(argv)
    ledger=Ledger(args.project,args.state_root)
    try:
        if args.command=='submit':
            result=submit(ledger,args.goal,args.key,**{k:getattr(args,k) for k in
                ('mode','provider','model','max_calls','max_seconds','image','branch','remote')})
            if args.start:
                from .owned import Owned
                from .runner import start
                Owned(ledger).enable(result['id'])
                result['runner']=start(ledger,result['id'])
        elif args.command=='status':
            result=ledger.task(args.task,full=True)
        else:
            from .owned import Owned
            runtime=Owned(ledger)
            if args.command=='outputs': result=runtime.state(args.task)[1]
            elif args.command=='cancel': result=runtime.control.cancel(args.task)
            elif args.command=='run':
                runtime.enable(args.task);result=runtime.run(args.task,steps=100)
            else:
                from .runner import start
                runtime.enable(args.task)
                if args.command=='resume': runtime.resume(args.task)
                result=start(ledger,args.task)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError) as error:
        print(json.dumps({'error':str(error)},ensure_ascii=False));return 2
