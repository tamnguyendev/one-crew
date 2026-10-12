"""Local conversation and solution commands; reads do not invoke providers."""
import argparse
import json
from pathlib import Path
from .ledger import Ledger, read_json
from . import conversations as c

READ_ONLY = {('consultation', 'show'), ('consultation', 'route'), ('conversation', 'list'), ('conversation', 'read'),
             ('conversation', 'attach'), ('solution', 'review'), ('solution', 'diff')}
RECORDED = {('consultation', 'submit'): 'consultation.submit', ('consultation', 'feedback'): 'consultation.feedback',
            ('consultation', 'start'): 'consultation.start', ('consultation', 'cancel'): 'consultation.cancel',
            ('consultation', 'reconcile'): 'consultation.reconcile', ('conversation', 'create'): 'conversation.create',
            ('conversation', 'append'): 'conversation.append', ('conversation', 'summary'): 'conversation.summary',
            ('conversation', 'question'): 'conversation.question', ('conversation', 'reply'): 'conversation.reply',
            ('solution', 'bind'): 'solution.bind', ('solution', 'propose'): 'solution.propose', ('solution', 'select'): 'solution.select',
            ('solution', 'approve'): 'solution.approve', ('solution', 'request-changes'): 'solution.request-changes'}


def provenance_flags(q):
    q.add_argument('--decided-by', choices=('user', 'entry'), default=None)
    q.add_argument('--user-quote', help="The user's own words for this decision (relay); only a hash is stored.")
    q.add_argument('--quote-kind', choices=('chat', 'window', 'cli'), default=None)


def parser():
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
    q=conv.add_parser('reply');q.add_argument('--file',type=Path,required=True);provenance_flags(q)
    sol=groups.add_parser('solution').add_subparsers(dest='command',required=True)
    q=sol.add_parser('bind');q.add_argument('--file',type=Path,required=True)
    q=sol.add_parser('propose');q.add_argument('conversation');q.add_argument('--file',required=True,type=Path);q.add_argument('--key',required=True);q.add_argument('--source',required=True);q.add_argument('--expected-current')
    for name in ('review','diff'):
        q=sol.add_parser(name);q.add_argument('solution')
    q=sol.add_parser('select');q.add_argument('conversation');q.add_argument('solution');q.add_argument('--expected-current');q.add_argument('--source',required=True)
    for name in ('approve','request-changes'):
        q=sol.add_parser(name);q.add_argument('solution');q.add_argument('--revision',required=True);q.add_argument('--source',required=True);q.add_argument('--reference',required=True)
        provenance_flags(q)
    return p


def decision(a,ledger):
    """Who decided a SOL decision or CREQ answer. These are business decisions: never covered by a delegation."""
    from .delegations import decision as build
    from .interventions import actor
    return build(ledger,actor(),a.decided_by,a.user_quote,a.quote_kind,None,'business')


def execute(a,ledger):
    if a.group=='consultation':
        from . import consultations
        from .runner import start
        if a.command=='route':
            from .discussion import route
            return route(**read_json(a.file))
        if a.command=='submit':
            value=consultations.submit(ledger,**read_json(a.file))
            if a.start and value.get('id') and value['status'] in ('queued','running'):value['dispatch']=start(ledger,value['id'])
            return value
        if a.command=='feedback':return consultations.feedback(ledger,**read_json(a.file))
        if a.command=='show':return consultations.view(ledger,a.consultation)
        if a.command=='cancel':return consultations.cancel(ledger,a.consultation)
        if a.command=='reconcile':return consultations.reconcile(ledger,a.consultation)
        return start(ledger,a.consultation)
    if a.group=='conversation':
        if a.command=='create':return c.create(ledger,a.title,a.key,a.source)
        if a.command=='list':return c.list_conversations(ledger)
        if a.command in ('read','attach'):return c.read(ledger,a.conversation,a.after,a.limit)
        if a.command=='summary':return c.summarize(ledger,a.conversation,**read_json(a.file))
        if a.command in ('question','reply'):
            from . import solution_gate
            if a.command=='question':return solution_gate.question(ledger,a.conversation,**read_json(a.file))
            return solution_gate.reply(ledger,**read_json(a.file),decision=decision(a,ledger))
        return c.append(ledger,a.conversation,a.key,a.text,a.source,a.kind,a.reply_to,a.base_revision)
    if a.command=='bind':
        from .solution_slices import bind
        return bind(ledger,**read_json(a.file))
    if a.command=='propose':return c.propose(ledger,a.conversation,a.key,read_json(a.file),a.source,a.expected_current)
    if a.command=='select':return c.select(ledger,a.conversation,a.solution,a.expected_current,a.source)
    if a.command in ('review','diff'):return c.show_solution(ledger,a.solution)
    return c.decide(ledger,a.solution,a.revision,'approve' if a.command=='approve' else 'request_changes',a.source,a.reference,decision(a,ledger))


def record(a,ledger,value,**attribution):
    """Task-bound commands record on their tasks; discussion-level ones at conversation/solution/consultation scope.
    attribution: actor/channel for the MCP transport (the CLI uses ONECREW_ACTOR)."""
    command=RECORDED.get((a.group,a.command))
    if not command or not isinstance(value,dict):return
    from .interventions import cli_note
    payload=value.get('payload') if isinstance(value.get('payload'),dict) else {}
    tasks=value.get('affected_tasks') or payload.get('affected_tasks') or ([value['task']] if isinstance(value.get('task'),str) else [])
    if a.group=='consultation':
        scope=('consultation',value.get('id') if str(value.get('id','')).startswith('CONSULT-') else getattr(a,'consultation',None))
    elif a.group=='solution':
        scope=('solution',getattr(a,'solution',None) or value.get('id'))
    else:
        scope=('conversation',getattr(a,'conversation',None) or value.get('id'))
    if scope[1] is not None and not isinstance(scope[1],str):scope=(scope[0],None)
    ident=value.get('id') if isinstance(value.get('id'),str) else None
    # A replayed idempotent command returns the same record ID: one intervention. Control actions repeat.
    key=command+':'+ident if ident and a.command not in ('cancel','reconcile','start') else None
    cli_note(ledger,command,tasks,scope=scope,key=key,**attribution)


def main(argv=None):
    a=parser().parse_args(argv);ledger=Ledger(a.project,a.state_root)
    try:
        value=execute(a,ledger)
        record(a,ledger,value)
        print(json.dumps(value,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError,TypeError) as error:
        print(json.dumps({'error':str(error)},ensure_ascii=False));return 2
