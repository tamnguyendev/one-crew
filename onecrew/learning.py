"""Scoped outcome evidence and proposed lessons. Never silently promotes routing."""
import argparse
import json
from pathlib import Path
from .ledger import Ledger, LedgerError, canonical, content_hash, text_field
from .usage import summarize


def record(conn, ledger, task_id, state):
    phase=state.get('phase')
    if phase not in ('completed','failed','blocked','cancelled'): return
    task=ledger._task(conn,task_id)
    config=conn.execute('SELECT * FROM executions WHERE task_id=?',(task_id,)).fetchone()
    payload=json.loads(task['payload']);profile=json.loads(config['configuration']).get('profile',{})
    selected=state.get('worker',profile)
    attempts=[dict(r) for r in conn.execute('SELECT * FROM attempts WHERE task_id=?',(task_id,))]
    data={'version':1,'task':task_id,'task_revision':task['revision'],'spec_revision':payload['spec_revision'],
        'phase':phase,'mode':profile.get('mode'),'provider':selected.get('provider'),'model':selected.get('model'),
        'provider_handoffs':state.get('handoffs',[]),
        'snapshot':state.get('snapshot'),'verification':state.get('verification'),'acceptance':state.get('acceptance'),
        'progress':{k:v for k,v in state.get('progress',{}).items() if k!='results'},
        'recovery':state.get('recovery'),'managed_calls':config['used_calls'],
        'usage':summarize(state.get('usage',[]),attempts),
        'assistance':'unknown','quality_score':None,'routing_policy':'explicit-profile',
        'device_tested':False,'candidate_files':len(state.get('files',{}))}
    from .skills import signature, STEPS
    data['signature']=signature(payload.get('goal',payload['spec_text']),profile.get('mode'),state.get('files',{}))
    data['procedure']=list(dict.fromkeys(r['action'] for r in state.get('receipts',[])
                                       if r['action'] in STEPS and r.get('successful') is True))
    data['skills']=[{k:s[k] for k in ('id','revision','reason')} for s in state.get('skills',[])]
    from .budget_policy import timing
    from .budget import current
    data['timing']=timing(conn,task,state,attempts)
    data['budget']=current(conn,task)
    data['budget_policy']=profile.get('budget_policy')
    data['repair_rounds']=state.get('native_change',{}).get('repairs',state.get('native_audit',{}).get('repairs'))
    data['test_results']={'passed':sum(t.get('passed') is True for t in state.get('tests',[])),
                          'failed':sum(t.get('passed') is False for t in state.get('tests',[]))}
    data['id']=content_hash({k:v for k,v in data.items() if k!='id'})
    if not conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind='learning.outcome' AND json_extract(payload,'$.id')=?",(task_id,data['id'])).fetchone():
        ledger._event(conn,task_id,'learning.outcome',data)
        event=conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        # Facts become a proposed retrospective, never a verified procedure or
        # an automatically injected instruction/model-selection rule.
        lesson={'task':task_id,'evidence_event':event,'snapshot':data['snapshot'],
                'text':f"Outcome {phase}; verification {data['verification']}; acceptance {data['acceptance']}. "
                       f"Used {data['managed_calls']} managed calls; repair rounds {data['repair_rounds']}; "
                       f"tests passed/failed {data['test_results']['passed']}/{data['test_results']['failed']}. "
                       'Review the linked outcome before reusing its budget or procedure; cause and best model are not established.',
                'status':'proposed','automatic_injection':False,'automatic_promotion':False,
                'origin':'deterministic-outcome-retrospective'}
        lesson['id']=content_hash(lesson)
        ledger._event(conn,task_id,'learning.lesson',lesson)
        return True
    return False


def outcomes(ledger,limit=50):
    if type(limit) is not int or not 1<=limit<=200: raise LedgerError('limit must be 1-200.')
    with ledger.transaction() as conn:
        if conn is None: return []
        rows=conn.execute("SELECT e.seq,e.payload FROM events e JOIN tasks t ON t.id=e.task_id WHERE t.project_id=? AND e.kind='learning.outcome' ORDER BY e.seq DESC LIMIT ?",(ledger.project_id,limit)).fetchall()
    return [{'event':r['seq'],**json.loads(r['payload'])} for r in rows]


def propose(ledger,task_id,evidence,text):
    text=text_field(text,'lesson',800)
    from .discovery import scan_text
    scan_text(text.encode())
    if type(evidence) is not int or evidence<1: raise LedgerError('Evidence must be an outcome event ID.')
    with ledger.transaction(write=True) as conn:
        ledger._task(conn,task_id)
        row=conn.execute("SELECT payload FROM events WHERE seq=? AND task_id=? AND kind='learning.outcome'",(evidence,task_id)).fetchone()
        if not row: raise LedgerError('Outcome evidence does not belong to this task.')
        outcome=json.loads(row['payload'])
        value={'task':task_id,'evidence_event':evidence,'snapshot':outcome['snapshot'],
            'text':text,'status':'proposed','automatic_injection':False,'automatic_promotion':False}
        value['id']=content_hash(value)
        if not conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind='learning.lesson' AND json_extract(payload,'$.id')=?",(task_id,value['id'])).fetchone():
            ledger._event(conn,task_id,'learning.lesson',value)
    return value


def lessons(ledger):
    with ledger.transaction() as conn:
        if conn is None: return []
        rows=conn.execute("SELECT e.task_id,e.payload FROM events e JOIN tasks t ON t.id=e.task_id WHERE t.project_id=? AND e.kind='learning.lesson' ORDER BY e.seq DESC LIMIT 100",(ledger.project_id,)).fetchall()
        results=[]
        for row in rows:
            value=json.loads(row['payload'])
            current=conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='workflow.checkpoint' ORDER BY seq DESC LIMIT 1",(row['task_id'],)).fetchone()
            if current and json.loads(current['payload']).get('snapshot')!=value['snapshot']: value['status']='stale'
            results.append(value)
        return results


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--project',type=Path,default=Path.cwd());p.add_argument('--state-root',type=Path)
    sub=p.add_subparsers(dest='group',required=True).add_parser('learning').add_subparsers(dest='command',required=True)
    sub.add_parser('outcomes');sub.add_parser('lessons')
    add=sub.add_parser('propose');add.add_argument('task');add.add_argument('--evidence',type=int,required=True);add.add_argument('--text',required=True)
    budget=sub.add_parser('budget');budget.add_argument('--goal',required=True)
    budget.add_argument('--mode',choices=('audit','change','delivery','branch'),default='audit')
    budget.add_argument('--provider',required=True);budget.add_argument('--model',required=True)
    a=p.parse_args(argv);ledger=Ledger(a.project,a.state_root)
    try:
        if a.command=='budget':
            from .budget_policy import recommend
            result=recommend(ledger,a.goal,a.mode,a.provider,a.model)
        else: result=outcomes(ledger) if a.command=='outcomes' else lessons(ledger) if a.command=='lessons' else propose(ledger,a.task,a.evidence,a.text)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError) as error:
        print(json.dumps({'error':str(error)}));return 2
