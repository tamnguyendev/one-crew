"""Operator entry to solution deliveries; inspecting never launches work."""
import argparse
import json
from pathlib import Path
from .ledger import Ledger, LedgerError, read_json


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('--project',type=Path,default=Path.cwd());p.add_argument('--state-root',type=Path)
    sub=p.add_subparsers(dest='group',required=True).add_parser('delivery').add_subparsers(dest='command',required=True)
    q=sub.add_parser('submit');q.add_argument('--file',type=Path,required=True);q.add_argument('--start',action='store_true')
    for name in ('status','start','resume','cancel'):
        q=sub.add_parser(name);q.add_argument('task')
    a=p.parse_args(argv);ledger=Ledger(a.project,a.state_root)
    from .solution_delivery import Delivery,submit
    runtime=Delivery(ledger)
    try:
        if a.command=='submit':
            result=submit(ledger,**read_json(a.file))
            if a.start:
                from .runner import start
                state=runtime.enable(result['id'])
                if state['phase'] not in ('completed','cancelled','failed'): result['runner']=start(ledger,result['id'])
        elif a.command=='status':result=runtime.card(a.task)
        elif a.command=='cancel':result=runtime.control.cancel(a.task)
        else:
            from .runner import start
            runtime.enable(a.task)
            if a.command=='resume':runtime.resume(a.task)
            result=start(ledger,a.task)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError,TypeError,KeyError) as e:
        print(json.dumps({'error':str(e)},ensure_ascii=False));return 2
