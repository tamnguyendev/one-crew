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
    attempts=[dict(r) for r in conn.execute('SELECT * FROM attempts WHERE task_id=?',(task_id,))]
    data={'version':1,'task':task_id,'task_revision':task['revision'],'spec_revision':payload['spec_revision'],
        'phase':phase,'mode':profile.get('mode'),'provider':profile.get('provider'),'model':profile.get('model'),
        'snapshot':state.get('snapshot'),'verification':state.get('verification'),'acceptance':state.get('acceptance'),
        'progress':{k:v for k,v in state.get('progress',{}).items() if k!='results'},
        'recovery':state.get('recovery'),'managed_calls':config['used_calls'],
        'usage':summarize(state.get('usage',[]),attempts),
        'assistance':'unknown','quality_score':None,'routing_policy':'explicit-profile',
        'device_tested':False,'candidate_files':len(state.get('files',{}))}
    data['id']=content_hash(data)
    if not conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind='learning.outcome' AND json_extract(payload,'$.id')=?",(task_id,data['id'])).fetchone():
        ledger._event(conn,task_id,'learning.outcome',data)


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
    a=p.parse_args(argv);ledger=Ledger(a.project,a.state_root)
    try:
        result=outcomes(ledger) if a.command=='outcomes' else lessons(ledger) if a.command=='lessons' else propose(ledger,a.task,a.evidence,a.text)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError) as error:
        print(json.dumps({'error':str(error)}));return 2
