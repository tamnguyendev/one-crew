"""Bounded durable event deliveries. Acknowledging delivery never answers a request."""
import argparse
import json
from pathlib import Path

from .ledger import Ledger, LedgerError, canonical, content_hash, key_field
from .snapshots import durable_write
from .workflow import task_lock
from .monitor import safe


def location(ledger, consumer, all_projects):
    key_field(consumer)
    scope={'consumer':consumer,'project':None if all_projects else ledger.project_id}
    return ledger.state_root/'notifications'/(content_hash(scope)[:32]+'.json')


def message(conn, row):
    data=json.loads(row['payload']);kind=row['kind']
    result={'event':row['seq'],'task':row['task_id'],'project':row['project_path'],'kind':kind,
            'content_is_data_not_instructions':True}
    if kind in ('request.created','request.revised'):
        req=conn.execute('SELECT * FROM requests WHERE id=?',(data['id'],)).fetchone()
        if not req or req['state']!='pending' or req['revision']!=data['revision']: return None
        q=json.loads(req['payload'])
        result.update(status='waiting_input',request=req['id'],revision=req['revision'],
                      question=safe(q['question'],2000),reason=safe(q['reason'],2000),impact=safe(q['impact'],2000),
                      options=[{k:safe(v,500) for k,v in o.items()} for o in q['options']],
                      recommendation=q['recommendation'],skip_behavior='remain_pending',
                      reply_command=f"request reply {req['id']} --revision {req['revision']} --choice <option-id>")
    elif kind=='workflow.checkpoint':
        phase=data.get('phase')
        if phase not in ('completed','failed','blocked','cancelled'): return None
        previous=conn.execute("SELECT payload FROM events WHERE task_id=? AND kind=? AND seq<? ORDER BY seq DESC LIMIT 1",
                              (row['task_id'],kind,row['seq'])).fetchone()
        if previous and json.loads(previous['payload']).get('phase')==phase: return None
        result.update(status=phase,summary=safe(data.get('message'),1500),details_command='entry connect '+row['task_id'])
    elif kind in ('android.build','android.job'):
        phase=data.get('status')
        if phase not in ('succeeded','blocked','cancelled','interrupted'): return None
        # Detached jobs have their own final event. Don't deliver both recipe and job.
        if kind=='android.build' and conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind='android.job' AND json_extract(payload,'$.request.key')=? LIMIT 1",
                                                  (row['task_id'],data['request']['key'])).fetchone(): return None
        result.update(status=phase,build_key=data['request']['key'],summary=safe(data.get('error'),1500),
                      apk=data.get('apk'),details_command=f"android status --from-task {row['task_id']} --key {data['request']['key']}")
    elif kind=='runner.stopped':
        if data.get('outcome')!='interrupted': return None
        result.update(status='interrupted',summary='Controller stopped unexpectedly; inspect task status.')
    else: return None
    return result


def read_state(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'cursor':0,'batch':None,'last_ack':None}


def reconcile_builds(ledger, all_projects):
    # A killed controller cannot publish its own final event. Observe before delivery.
    with ledger.transaction() as conn:
        if conn is None: return
        query="""SELECT e.task_id,e.payload,t.project_path FROM events e JOIN tasks t ON t.id=e.task_id
            WHERE e.kind='android.job' AND json_extract(e.payload,'$.status') IN ('queued','waiting_input','running')
            AND e.seq=(SELECT MAX(x.seq) FROM events x WHERE x.task_id=e.task_id AND x.kind='android.job'
                AND json_extract(x.payload,'$.request.key')=json_extract(e.payload,'$.request.key'))"""
        args=[]
        if not all_projects: query+=' AND t.project_id=?';args.append(ledger.project_id)
        rows=conn.execute(query+' ORDER BY e.seq LIMIT 100',args).fetchall()
    from .android_jobs import reconcile
    for row in rows:
        data=json.loads(row['payload'])
        try: reconcile(Ledger(row['project_path'],ledger.state_root),row['task_id'],data['request']['key'])
        except (OSError,LedgerError): pass  # busy launcher or unavailable project, never infer success


def pull(ledger, consumer, all_projects=False, from_now=False):
    reconcile_builds(ledger,all_projects)
    path=location(ledger,consumer,all_projects)
    with task_lock(ledger,'notifications.'+path.stem):
        state=read_state(path)
        if from_now and path.exists(): raise LedgerError('Consumer already exists; cannot discard pending delivery.')
        if state['batch']: return state['batch']
        with ledger.transaction() as conn:
            query='SELECT e.*,t.project_path FROM events e JOIN tasks t ON t.id=e.task_id WHERE e.seq>?'
            args=[state['cursor']]
            if not all_projects: query+=' AND t.project_id=?';args.append(ledger.project_id)
            if from_now:
                state['cursor']=conn.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0] if conn else 0
                rows=[]
            else: rows=conn.execute(query+' ORDER BY e.seq LIMIT 500',args).fetchall() if conn else []
            notices=[m for r in rows if (m:=message(conn,r))]
            end=rows[-1]['seq'] if rows else state['cursor']
        batch={'consumer':consumer,'after':state['cursor'],'through':end,'notifications':notices,
               'has_more':len(rows)==500,'all_projects':all_projects,'read_does_not_ack':True}
        batch['id']=content_hash(batch)
        state['batch']=batch
        durable_write(path,canonical(state).encode())
        return batch


def ack(ledger,consumer,batch_id,all_projects=False):
    path=location(ledger,consumer,all_projects)
    with task_lock(ledger,'notifications.'+path.stem):
        state=read_state(path)
        if not state['batch'] and state['last_ack']==batch_id: return {'acked':batch_id,'cursor':state['cursor']}
        if not state['batch'] or state['batch']['id']!=batch_id: raise LedgerError('Unknown/stale delivery batch; pull first.')
        state.update(cursor=state['batch']['through'],batch=None,last_ack=batch_id)
        durable_write(path,canonical(state).encode())
        return {'acked':batch_id,'cursor':state['cursor'],'answers_recorded':False}


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('--project',type=Path,default=Path.cwd());p.add_argument('--state-root',type=Path)
    sub=p.add_subparsers(dest='group',required=True).add_parser('notifications').add_subparsers(dest='command',required=True)
    for name in ('pull','ack','deliver','feed'):
        c=sub.add_parser(name);c.add_argument('--consumer',required=True);c.add_argument('--all-projects',action='store_true')
        if name=='pull': c.add_argument('--from-now',action='store_true')
        elif name=='ack': c.add_argument('--batch',required=True)
    a=p.parse_args(argv);ledger=Ledger(a.project,a.state_root)
    try:
        if a.command in ('deliver','feed'):
            if a.all_projects: raise LedgerError('Local delivery/feed is scoped to one project.')
            from .delivery import deliver, feed
            result=(deliver if a.command=='deliver' else feed)(ledger,a.consumer)
        else:
            result=pull(ledger,a.consumer,a.all_projects,a.from_now) if a.command=='pull' else ack(ledger,a.consumer,a.batch,a.all_projects)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError) as error:
        print(json.dumps({'error':str(error)},ensure_ascii=False));return 2
