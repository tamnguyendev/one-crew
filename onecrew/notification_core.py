"""The v1 durable notification envelope and ACK protocol, shared by both CLIs."""
import json
from .ledger import LedgerError, canonical, content_hash, key_field
from .snapshots import durable_write
from .locking_core import task_lock

def location(ledger, consumer, all_projects):
    key_field(consumer)
    scope={'consumer':consumer,'project':None if all_projects else ledger.project_id}
    return ledger.state_root/'notifications'/(content_hash(scope)[:32]+'.json')


def read_state(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'cursor':0,'batch':None,'last_ack':None}


def _projection(state, path, projection, allow_unbound):
    previous = state.get('projection')
    if path.exists() and previous != projection and not (previous is None and allow_unbound):
        raise LedgerError('Notification consumer belongs to another or unbound projection; use a new dedicated consumer.')
    state['projection'] = projection


def pull(ledger, consumer, all_projects=False, from_now=False, *, message, reconcile=None, extra=None, refresh=None,
         projection='v1', allow_unbound=True):
    if reconcile: reconcile(ledger, all_projects)
    path=location(ledger,consumer,all_projects)
    with task_lock(ledger,'notifications.'+path.stem):
        state=read_state(path)
        if from_now and path.exists(): raise LedgerError('Consumer already exists; cannot discard pending delivery.')
        _projection(state, path, projection, allow_unbound)
        if state['batch']: return refresh(ledger, state['batch']) if refresh else state['batch']
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
            added,conv_end,conv_more=(extra(ledger,conn,state.get('conversation_cursor',0),all_projects,from_now) if extra else ([],state.get('conversation_cursor',0),False))
            notices.extend(added)
        batch={'consumer':consumer,'after':state['cursor'],'through':end,'notifications':notices,
               'conversation_through':conv_end,'has_more':len(rows)==500 or conv_more,'all_projects':all_projects,'read_does_not_ack':True}
        batch['id']=content_hash(batch)
        state['batch']=batch
        durable_write(path,canonical(state).encode())
        return batch


def refresh_plan_notices(ledger, batch, *, message):
    """Reproject delayed plan deliveries without changing their ACK identity/cursor.

    The durable batch is the delivery envelope. Its ID remains bound to that
    envelope; current plan content is a view, never a new answer or approval.
    Existing v1 notices retain their original delivery semantics.
    """
    notices = []
    with ledger.transaction() as conn:
        for original in batch['notifications']:
            if not original.get('plan') or not isinstance(original.get('event'), int):
                notices.append(original)
                continue
            row = conn.execute('SELECT e.*,t.project_path FROM events e JOIN tasks t ON t.id=e.task_id WHERE e.seq=?',
                               (original['event'],)).fetchone() if conn else None
            current = message(conn, row) if row else None
            if current:
                notices.append(current)
    if notices == batch['notifications']:
        return batch
    return dict(batch, notifications=notices, projection='current_plan_state',
                acknowledgement_identity='original_delivery_envelope')


def ack(ledger,consumer,batch_id,all_projects=False, *, projection='v1', allow_unbound=True):
    path=location(ledger,consumer,all_projects)
    with task_lock(ledger,'notifications.'+path.stem):
        state=read_state(path)
        _projection(state, path, projection, allow_unbound)
        if not state['batch'] and state['last_ack']==batch_id: return {'acked':batch_id,'cursor':state['cursor']}
        if not state['batch'] or state['batch']['id']!=batch_id: raise LedgerError('Unknown/stale delivery batch; pull first.')
        if (state.get('watch_delivery_required') or state['batch'].get('watch_tasks')) and state['batch']['notifications']:
            delivery=state.get('delivery',{})
            if (delivery.get('batch')!=batch_id or delivery.get('status')!='host_message_observed'
                    or not delivery.get('receipt')):
                raise LedgerError('Watch was only read/prepared; a completed scheduled host-message receipt is required before ACK.')
            state['last_delivery']=state.pop('delivery')
        state['last_acked_batch']=state['batch']
        if 'watch_alerts' in state['batch']:state['watch_alerts']=state['batch']['watch_alerts']
        state.update(cursor=state['batch']['through'],conversation_cursor=state['batch'].get('conversation_through',state.get('conversation_cursor',0)),batch=None,last_ack=batch_id)
        durable_write(path,canonical(state).encode())
        return {'acked':batch_id,'cursor':state['cursor'],'answers_recorded':False}
