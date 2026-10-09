"""Provider-neutral shared-discussion tools for trusted local entry hosts."""
import json
from . import conversations as c,solution_gate as gate,consultations as consult
from .ledger import LedgerError

S={'type':'string'}


def spec(description,fields,required=None):
    return description,{'type':'object','properties':{key:S for key in fields.split()},
        'required':(required or fields).split(),'additionalProperties':False}


TOOLS={
 'conversation_create':spec('Create discussion without task or model calls.','title key'),
 'conversation_list':spec('List project discussions.',''),
 'conversation_read':spec('Attach from any entry; current solution, decisions, pending questions and delta.','conversation after','conversation'),
 'conversation_append':spec('Record data with provenance; no dispatch or approval.','conversation key text kind base_revision reply_to','conversation key text'),
 'solution_propose':spec('Propose immutable brief/detail; JSON payload with brief/detail/acceptance/non_goals/assumptions/questions.','conversation key payload expected_current','conversation key payload'),
 'solution_review':spec('Read solution, diff and approval.','solution'),
 'solution_bind':spec('Bind a legacy sealed DAG before its first model call; approved solution must pin spec hash. JSON binding arguments.','payload'),
 'solution_select':spec('Select draft using compare-and-swap; does not approve.','conversation solution expected_current','conversation solution'),
 'solution_decide':spec('Record only actual user approval/request_changes for exact revision; silence is not approval.','solution revision choice reference'),
 'conversation_question':spec('Persist required clarification/change request. JSON affected_tasks; holds bound work.','conversation key text reason affected_tasks kind','conversation key text reason affected_tasks'),
 'conversation_reply':spec('Record actual user response. Does not launch or reset budget.','qid revision choice reference solution solution_revision','qid revision choice reference'),
 'discussion_route':spec('JSON routing arguments. Default local; mentions/quotes are not consult intent. No worker launch.','payload'),
 'consultation_submit':spec('One explicit bounded provider review of pinned solution. JSON request; returns ID and background state. Never implement or approve.','payload'),
 'consultation_show':spec('Read consultation/result; includes stale revision flag.','consultation'),
 'consultation_cancel':spec('Request cancellation; retained ownership until settled.','consultation'),
 'consultation_feedback':spec('JSON observed review quality metrics with actual evidence; never promotes policy automatically.','payload'),
}
READ={'conversation_list','conversation_read','solution_review','consultation_show','discussion_route'}
DECISIONS={'solution_decide','conversation_reply','solution_bind'}


def call(server,name,args):
    ledger=server.ledger;source=server.source
    if name=='conversation_create':return c.create(ledger,args['title'],args['key'],source)
    if name=='conversation_list':return c.list_conversations(ledger)
    if name=='conversation_read':return c.read(ledger,args['conversation'],int(args.get('after','0')))
    if name=='conversation_append':return c.append(ledger,args['conversation'],args['key'],args['text'],source,args.get('kind','proposal'),args.get('reply_to'),args.get('base_revision'))
    if name=='solution_propose':return c.propose(ledger,args['conversation'],args['key'],json.loads(args['payload']),source,args.get('expected_current'))
    if name=='solution_review':return c.show_solution(ledger,args['solution'])
    if name=='solution_bind':
        from .solution_slices import bind
        return bind(ledger,**json.loads(args['payload']))
    if name=='solution_select':return c.select(ledger,args['conversation'],args['solution'],args.get('expected_current'),source)
    if name=='solution_decide':return c.decide(ledger,args['solution'],args['revision'],args['choice'],source,args['reference'])
    if name=='conversation_question':return gate.question(ledger,args['conversation'],args['key'],args['text'],args['reason'],json.loads(args['affected_tasks']),source,args.get('kind','solution_change'))
    if name=='conversation_reply':return gate.reply(ledger,source=source,**args)
    if name=='discussion_route':
        from .discussion import route
        payload=json.loads(args['payload']);payload['entry']=source
        return route(**payload)
    if name=='consultation_submit':
        payload=json.loads(args['payload']);payload['entry']=source
        result=consult.submit(ledger,**payload)
        if not result.get('id'):return result
        if result['status'] not in ('queued','running'):return result
        from .runner import start
        try:runner=start(ledger,result['id'])
        except (ValueError,OSError) as error:runner={'status':'unconfirmed','error':str(error)[:1000]}
        return dict(result,dispatch=runner)
    if name=='consultation_show':return consult.view(ledger,args['consultation'])
    if name=='consultation_cancel':return consult.cancel(ledger,args['consultation'])
    if name=='consultation_feedback':return consult.feedback(ledger,**json.loads(args['payload']))
    raise LedgerError('Unknown conversation tool.')
