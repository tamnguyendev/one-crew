"""Operator entry to solution deliveries; inspecting never launches work."""
import argparse
import json
from pathlib import Path
from .ledger import Ledger, LedgerError, read_json

READ_ONLY = {('delivery', 'status')}
RECORDED = {('delivery', name): 'delivery.' + name for name in ('submit', 'start', 'resume', 'cancel')}


def _record(ledger, task, command, reason=None, key=None):
    """Mutating entry commands are interventions; recording never changes the task."""
    from .interventions import cli_note
    cli_note(ledger, RECORDED[('delivery', command)], [task], reason=reason, key=key)


def parser():
    p=argparse.ArgumentParser()
    p.add_argument('--project',type=Path,default=Path.cwd());p.add_argument('--state-root',type=Path)
    sub=p.add_subparsers(dest='group',required=True).add_parser('delivery').add_subparsers(dest='command',required=True)
    q=sub.add_parser('submit');q.add_argument('--file',type=Path);q.add_argument('--start',action='store_true')
    # Goal-level dispatch: the approved SOL envelope is the authority and OneCrew derives the plan.
    q.add_argument('--solution');q.add_argument('--revision');q.add_argument('--goal');q.add_argument('--key')
    for name in ('status','start','resume','cancel'):
        q=sub.add_parser(name);q.add_argument('task')
        if name!='status':q.add_argument('--reason')
    return p


def execute(a,ledger):
    from .solution_delivery import Delivery,submit
    runtime=Delivery(ledger)
    if a.command=='submit':
        if a.file:
            if a.solution or a.goal:raise LedgerError('Use either --file or --solution/--revision/--goal/--key.')
            spec=read_json(a.file)
        else:
            if not (a.solution and a.revision and a.goal and a.key):raise LedgerError('--solution, --revision, --goal and --key are required without --file.')
            spec={'goal':a.goal,'key':a.key,'solution_id':a.solution,'solution_revision':a.revision}
        result=submit(ledger,**spec)
        # A replayed submission (same key) is the same handoff, so it is recorded once.
        _record(ledger,result['id'],'submit','planned by OneCrew' if 'plan' not in spec else 'entry-authored plan',key='submit')
        if a.start:
            from .runner import start
            state=runtime.enable(result['id'])
            if state['phase'] not in ('completed','cancelled','failed'): result['runner']=start(ledger,result['id'])
        return result
    if a.command=='status':return runtime.card(a.task)
    if a.command=='cancel':
        result=runtime.control.cancel(a.task);_record(ledger,a.task,'cancel',a.reason);return result
    from .runner import start
    runtime.enable(a.task)
    if a.command=='resume':runtime.resume(a.task)
    result=start(ledger,a.task);_record(ledger,a.task,a.command,a.reason);return result


def main(argv=None):
    a=parser().parse_args(argv);ledger=Ledger(a.project,a.state_root)
    try:
        result=execute(a,ledger)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError,TypeError,KeyError) as e:
        print(json.dumps({'error':str(e)},ensure_ascii=False));return 2
