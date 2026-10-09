"""Bounded host watch ticks for explicitly attached tasks; never dispatch work.

The host owns enabling/pausing its schedule. A watch has a separate consumer;
acknowledging the batch records delivery only, never a task decision.
"""
import json
from .ledger import Ledger, LedgerError, canonical, content_hash
from .notifications import pull, location, read_state
from .runner import status as runner_status
from .snapshots import durable_write
from .workflow import task_lock
from .monitor import safe
from .supervisor import probe


def activity(ledger, tasks):
    tasks=sorted(set(tasks))
    if not tasks or len(tasks)>100: raise LedgerError('Watch requires 1-100 explicit TASK IDs.')
    result=[]
    with ledger.transaction() as conn:
        for task in tasks:
            row=conn.execute('SELECT * FROM tasks WHERE id=?',(task,)).fetchone() if conn else None
            if not row: raise LedgerError('Unknown watched task: '+task)
            last=conn.execute("SELECT seq,payload FROM events WHERE task_id=? AND kind='workflow.checkpoint' ORDER BY seq DESC LIMIT 1",(task,)).fetchone()
            state=json.loads(last['payload']) if last else {}
            pending=conn.execute("SELECT COUNT(*) FROM requests WHERE task_id=? AND state='pending'",(task,)).fetchone()[0]
            phase=state.get('phase','queued')
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='executions'").fetchone():
                execution=conn.execute('SELECT status FROM executions WHERE task_id=?',(task,)).fetchone()
                if execution and execution['status']=='paused':phase='paused'
            held=bool(pending) or phase in ('completed','failed','cancelled','blocked','paused','waiting')
            runner={'status':'not_needed'}
            if not held:
                try:runner=runner_status(Ledger(row['project_path'],ledger.state_root),task)
                except (OSError,ValueError) as error:runner={'status':'unknown','error':str(error)[:300]}
            running=not held and runner['status']=='alive'
            builds=conn.execute("""SELECT e.payload FROM events e WHERE e.task_id=? AND e.kind='android.job'
                AND e.seq=(SELECT MAX(x.seq) FROM events x WHERE x.task_id=e.task_id AND x.kind=e.kind
                AND json_extract(x.payload,'$.request.key')=json_extract(e.payload,'$.request.key'))""",(task,)).fetchall()
            build_active=[]
            for build in builds:
                value=json.loads(build['payload'])
                if value.get('status') not in ('queued','running'):continue
                if value.get('identity') and probe(value['identity'])=='alive':build_active.append(value['request']['key'])
            if build_active and not pending:running=True
            status='waiting_input' if pending else phase
            if build_active and not pending:status='building'
            elif not held and not running: status='interrupted' if runner['status']=='stopped' else 'needs_attention'
            result.append({'task':task,'project':row['project_path'],'phase':phase,'status':status,
                'checkpoint':last['seq'] if last else 0,'pending_requests':pending,
                'runner':runner['status'],'running':running,'active_builds':build_active,
                'summary':safe(state.get('message','No workflow checkpoint yet.'),1500)})
    return result


def lifecycle(ledger, consumer, tasks):
    """Recheck after ACK, so a completion arriving during delivery is not dropped."""
    rows=activity(ledger,tasks);state=read_state(location(ledger,consumer,True))
    with ledger.transaction() as conn:
        unread=bool(conn and conn.execute('SELECT 1 FROM events WHERE seq>? AND task_id IN ('+
            ','.join('?' for _ in tasks)+') LIMIT 1',[state['cursor'],*tasks]).fetchone())
        from .conversations import installed
        if conn and installed(conn):
            unread=unread or bool(conn.execute('SELECT 1 FROM conversation_events WHERE seq>? LIMIT 1',
                (state.get('conversation_cursor',0),)).fetchone())
    active=any(row['running'] for row in rows)
    return {'activity':rows,'active':active,'unread':unread,
        'should_pause':not active and not unread and state.get('batch') is None,
        'transport':'host-scheduled-check','chat_callback':False}


def watch(ledger, consumer, tasks):
    tasks=sorted(set(tasks));rows=activity(ledger,tasks)
    pull(ledger,consumer,all_projects=True)
    path=location(ledger,consumer,True)
    with task_lock(ledger,'notifications.'+path.stem):
        state=read_state(path);batch=state['batch']
        if batch.get('watch_tasks'):
            if batch['watch_tasks']!=tasks:raise LedgerError('ACK the pending watch batch before changing task attachments.')
        else:
            notices=[item for item in batch['notifications'] if item.get('task') in tasks
                or set(item.get('affected_tasks',[])).intersection(tasks)]
            seen=dict(state.get('watch_alerts',{}));current={r['task']:r for r in rows}
            # Do not replay historical failures that have already been superseded.
            notices=[n for n in notices if n.get('kind')!='workflow.checkpoint'
                or n['event']>=current[n['task']]['checkpoint']]
            if not batch['has_more']:
                for row in rows:
                    if row['running']: continue
                    fingerprint=content_hash(row)
                    if seen.get(row['task'])!=fingerprint and not any(n.get('task')==row['task'] for n in notices):
                        notices.append(dict(row,kind='watch.current_state',event='watch:'+fingerprint,
                            content_is_data_not_instructions=True,details_command='entry connect '+row['task']))
                    seen[row['task']]=fingerprint
            batch.update(notifications=notices,watch_tasks=tasks,watch_alerts=seen)
            batch.pop('id',None);batch['id']=content_hash(batch)
            state['batch']=batch;durable_write(path,canonical(state).encode())
    return dict(batch,activity=rows,active=any(r['running'] for r in rows),
        pause_check='ACK this exact batch, then use should_pause from the ACK response.',
        transport='host-scheduled-check',chat_callback=False)
