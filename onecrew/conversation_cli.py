"""Local conversation and solution commands; reads do not invoke providers."""
import argparse
import json
from pathlib import Path
from .ledger import Ledger, read_json
from . import conversations as c


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--project',type=Path,default=Path.cwd());p.add_argument('--state-root',type=Path)
    groups=p.add_subparsers(dest='group',required=True)
    consultation=groups.add_parser('consultation').add_subparsers(dest='command',required=True)
    for name in ('submit','route','feedback'):
        q=consultation.add_parser(name);q.add_argument('--file',type=Path,required=True)
        if name=='submit':q.add_argument('--start',action='store_true')
    for name in ('show','start','cancel','reconcile'):
        q=consultation.add_parser(name);q.add_argument('consultation')
    conv=groups.add_parser('conversation').add_subparsers(dest='command',required=True)
    q=conv.add_parser('create');q.add_argument('--title',required=True);q.add_argument('--key',required=True);q.add_argument('--source',default='cli')
    conv.add_parser('list')
    for name in ('read','attach'):
        q=conv.add_parser(name);q.add_argument('conversation');q.add_argument('--after',type=int,default=0);q.add_argument('--limit',type=int,default=20)
    q=conv.add_parser('append');q.add_argument('conversation');q.add_argument('--key',required=True);q.add_argument('--text',required=True);q.add_argument('--source',required=True)
    q.add_argument('--kind',default='proposal');q.add_argument('--reply-to');q.add_argument('--base-revision')
    q=conv.add_parser('summary');q.add_argument('conversation');q.add_argument('--file',type=Path,required=True)
    q=conv.add_parser('question');q.add_argument('conversation');q.add_argument('--file',type=Path,required=True)
    q=conv.add_parser('reply');q.add_argument('--file',type=Path,required=True)
    sol=groups.add_parser('solution').add_subparsers(dest='command',required=True)
    q=sol.add_parser('bind');q.add_argument('--file',type=Path,required=True)
    q=sol.add_parser('propose');q.add_argument('conversation');q.add_argument('--file',required=True,type=Path);q.add_argument('--key',required=True);q.add_argument('--source',required=True);q.add_argument('--expected-current')
    for name in ('review','diff'):
        q=sol.add_parser(name);q.add_argument('solution')
    q=sol.add_parser('select');q.add_argument('conversation');q.add_argument('solution');q.add_argument('--expected-current');q.add_argument('--source',required=True)
    for name in ('approve','request-changes'):
        q=sol.add_parser(name);q.add_argument('solution');q.add_argument('--revision',required=True);q.add_argument('--source',required=True);q.add_argument('--reference',required=True)
    a=p.parse_args(argv);ledger=Ledger(a.project,a.state_root)
    try:
        if a.group=='consultation':
            from . import consultations
            from .runner import start
            if a.command=='route':
                from .discussion import route
                value=route(**read_json(a.file))
            elif a.command=='submit':
                value=consultations.submit(ledger,**read_json(a.file))
                if a.start and value.get('id') and value['status'] in ('queued','running'):value['dispatch']=start(ledger,value['id'])
            elif a.command=='feedback':value=consultations.feedback(ledger,**read_json(a.file))
            elif a.command=='show':value=consultations.view(ledger,a.consultation)
            elif a.command=='cancel':value=consultations.cancel(ledger,a.consultation)
            elif a.command=='reconcile':
                value=consultations.reconcile(ledger,a.consultation)
            else:value=start(ledger,a.consultation)
        elif a.group=='conversation':
            if a.command=='create':value=c.create(ledger,a.title,a.key,a.source)
            elif a.command=='list':value=c.list_conversations(ledger)
            elif a.command in ('read','attach'):value=c.read(ledger,a.conversation,a.after,a.limit)
            elif a.command=='summary':value=c.summarize(ledger,a.conversation,**read_json(a.file))
            elif a.command in ('question','reply'):
                from . import solution_gate
                value=solution_gate.question(ledger,a.conversation,**read_json(a.file)) if a.command=='question' else solution_gate.reply(ledger,**read_json(a.file))
            else:value=c.append(ledger,a.conversation,a.key,a.text,a.source,a.kind,a.reply_to,a.base_revision)
        elif a.command=='bind':
            from .solution_slices import bind
            value=bind(ledger,**read_json(a.file))
        elif a.command=='propose':value=c.propose(ledger,a.conversation,a.key,read_json(a.file),a.source,a.expected_current)
        elif a.command=='select':value=c.select(ledger,a.conversation,a.solution,a.expected_current,a.source)
        elif a.command in ('review','diff'):value=c.show_solution(ledger,a.solution)
        else:value=c.decide(ledger,a.solution,a.revision,'approve' if a.command=='approve' else 'request_changes',a.source,a.reference)
        print(json.dumps(value,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError,TypeError) as error:
        print(json.dumps({'error':str(error)},ensure_ascii=False));return 2
