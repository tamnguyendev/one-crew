"""Bounded durable event deliveries. Acknowledging delivery never answers a request."""
import argparse
import json
from pathlib import Path

from .ledger import Ledger, LedgerError, canonical, content_hash, key_field
from .snapshots import durable_write
from .locking_core import task_lock
from . import notification_core
from .notification_core import location, read_state, ack
from .display_core import safe


def message(conn, row):
    from .v2 import exceptions
    if exceptions.handles(conn, row):
        return exceptions.message(conn, row)
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
    from .conversation_delivery import batch as conversation_batch
    from .v2 import exceptions
    def reconcile(current, all_projects):
        reconcile_builds(current, all_projects)
        exceptions.observe_project(current, all_projects=all_projects)
    return notification_core.pull(ledger, consumer, all_projects, from_now, message=message,
        reconcile=reconcile, extra=conversation_batch, refresh=refresh_plan_notices)


def refresh_plan_notices(ledger, batch):
    return notification_core.refresh_plan_notices(ledger, batch, message=message)


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('--project',type=Path,default=Path.cwd());p.add_argument('--state-root',type=Path)
    sub=p.add_subparsers(dest='group',required=True).add_parser('notifications').add_subparsers(dest='command',required=True)
    for name in ('pull','ack','deliver','feed','watch','begin-delivery','confirm-delivery','delivery-missing','redeliver'):
        c=sub.add_parser(name);c.add_argument('--consumer',required=True);c.add_argument('--all-projects',action='store_true')
        if name in ('ack','watch'):c.add_argument('--task',action='append',default=[])
        if name=='pull': c.add_argument('--from-now',action='store_true')
        elif name=='ack': c.add_argument('--batch',required=True)
        if name in ('begin-delivery','confirm-delivery','delivery-missing'):c.add_argument('--batch',required=True)
        if name=='begin-delivery':
            c.add_argument('--thread',required=True);c.add_argument('--automation',required=True);c.add_argument('--file',type=Path,required=True)
        if name=='confirm-delivery':c.add_argument('--evidence-file',type=Path,required=True)
        if name=='redeliver':c.add_argument('--task',required=True);c.add_argument('--reason',required=True)
    a=p.parse_args(argv);ledger=Ledger(a.project,a.state_root)
    try:
        if a.command=='ack' and a.task and not a.all_projects:
            raise LedgerError('Watch ACK requires --all-projects.')
        if a.command in ('begin-delivery','confirm-delivery','delivery-missing','redeliver'):
            if not a.all_projects:raise LedgerError('Host delivery requires --all-projects and a dedicated watch consumer.')
            from . import notification_receipts as receipts
            if a.command=='begin-delivery':result=receipts.begin(ledger,a.consumer,a.batch,a.thread,a.automation,a.file.read_text(encoding='utf-8-sig'))
            elif a.command=='confirm-delivery':result=receipts.confirm(ledger,a.consumer,a.batch,json.loads(a.evidence_file.read_text(encoding='utf-8-sig')))
            elif a.command=='delivery-missing':result=receipts.missing(ledger,a.consumer,a.batch)
            else:result=receipts.redeliver(ledger,a.consumer,a.task,a.reason)
        elif a.command in ('deliver','feed'):
            if a.all_projects: raise LedgerError('Local delivery/feed is scoped to one project.')
            from .delivery import deliver, feed
            result=(deliver if a.command=='deliver' else feed)(ledger,a.consumer)
        elif a.command=='watch':
            if not a.all_projects:raise LedgerError('Watch uses its own --all-projects consumer with explicit --task IDs.')
            from .notification_watch import watch
            result=watch(ledger,a.consumer,a.task)
        else:
            result=pull(ledger,a.consumer,a.all_projects,a.from_now) if a.command=='pull' else ack(ledger,a.consumer,a.batch,a.all_projects)
            if a.command=='ack' and a.task:
                from .notification_watch import lifecycle
                result.update(lifecycle(ledger,a.consumer,a.task))
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError) as error:
        print(json.dumps({'error':str(error)},ensure_ascii=False));return 2
