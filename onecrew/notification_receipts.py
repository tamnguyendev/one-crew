"""Two-phase host notification receipts, separate from inspection and local ACK.

Evidence is a trusted local adapter's read_thread response, not a cryptographic
attestation or proof of an OS toast/user read. Never accept a proposed message as
evidence that a completed scheduled turn actually posted it.
"""
import datetime as dt
import json
from .ledger import LedgerError, canonical, content_hash, text_field, utcnow
from .notifications import location, read_state
from .snapshots import durable_write
from .workflow import task_lock


def pending(state, batch_id):
    batch=state.get('batch')
    if not batch or batch['id']!=batch_id or not batch.get('watch_tasks') or not batch['notifications']:
        raise LedgerError('Expected the current nonempty watch batch.')
    return batch


def begin(ledger, consumer, batch_id, thread, automation, body):
    text_field(thread,'Host thread',150);text_field(automation,'Automation',150)
    text_field(body,'Notification body',8000)
    path=location(ledger,consumer,True)
    with task_lock(ledger,'notifications.'+path.stem):
        state=read_state(path);pending(state,batch_id)
        draft={'batch':batch_id,'thread':thread,'automation':automation,'body':body.strip()}
        revision=content_hash(draft)
        old=state.get('delivery')
        if old:
            if old['revision']!=revision:raise LedgerError('Delivery already started with different content or destination.')
            return old
        delivery=dict(draft,revision=revision,status='awaiting_host_receipt',started_at=utcnow(),
            message='OneCrew · '+revision[:16]+'\n\n'+body.strip(),missing_checks=0,receipt=None)
        state['delivery']=delivery;durable_write(path,canonical(state).encode())
        return delivery


def confirm(ledger, consumer, batch_id, evidence):
    path=location(ledger,consumer,True)
    with task_lock(ledger,'notifications.'+path.stem):
        state=read_state(path);pending(state,batch_id);delivery=state.get('delivery')
        if not delivery or delivery['batch']!=batch_id:raise LedgerError('Begin delivery before checking a host receipt.')
        if evidence.get('schemaVersion')!=1 or evidence.get('thread',{}).get('id')!=delivery['thread']:
            raise LedgerError('Receipt comes from the wrong host thread or schema.')
        found=[]
        for turn in evidence.get('turns',[]):
            if turn.get('status')!='completed' or not turn.get('id') or not turn.get('completedAt'):continue
            completed=turn.get('completedAt')
            if not isinstance(completed,(int,float)) or completed < dt.datetime.fromisoformat(delivery['started_at']).timestamp():continue
            # Actual scheduler user-message envelope; quoted task output is never
            # sufficient. A manual status reply is not proactive delivery.
            origins=[item for item in turn.get('items',[]) if item.get('type')=='userMessage']
            automatic=any(any(block.get('type')=='text' and block.get('text','').lstrip().startswith('<heartbeat>')
                and '<automation_id>'+delivery['automation']+'</automation_id>' in block.get('text','')
                for block in item.get('content',[])) for item in origins)
            if not automatic:continue
            for item in turn.get('items',[]):
                if (item.get('type')=='agentMessage' and item.get('phase')=='final_answer' and item.get('id')
                        and item.get('text','').strip()==delivery['message']):
                    found.append({'thread':delivery['thread'],'turn':turn['id'],'message':item['id'],
                        'completed_at':turn['completedAt'],'evidence_hash':content_hash(evidence),
                        'source':'codex.read_thread.completed_scheduled_final'})
        if len(found)!=1:raise LedgerError('No unique completed scheduled final matches the exact notification; batch stays pending.')
        if delivery.get('receipt'):
            if any(delivery['receipt'][k]!=found[0][k] for k in ('thread','turn','message')):
                raise LedgerError('Conflicting host delivery receipt.')
            return delivery
        delivery.update(status='host_message_observed',receipt=found[0],confirmed_at=utcnow())
        durable_write(path,canonical(state).encode());return delivery


def missing(ledger,consumer,batch_id):
    path=location(ledger,consumer,True)
    with task_lock(ledger,'notifications.'+path.stem):
        state=read_state(path);pending(state,batch_id);delivery=state.get('delivery')
        if not delivery or delivery.get('receipt'):raise LedgerError('No unresolved host delivery attempt.')
        delivery['missing_checks']+=1
        durable_write(path,canonical(state).encode())
        return {'delivery_state':'unconfirmed','missing_checks':delivery['missing_checks'],
            'pause_due_error':delivery['missing_checks']>=3,'acked':False}


def redeliver(ledger,consumer,task,reason):
    """Explicitly requeue current state without rewinding history or forging ACK."""
    from .notification_watch import activity
    activity(ledger,[task]);text_field(reason,'Redelivery reason',1000)
    path=location(ledger,consumer,True)
    with task_lock(ledger,'notifications.'+path.stem):
        state=read_state(path)
        if state.get('batch'):raise LedgerError('Resolve the pending batch before requesting a redelivery.')
        previous=state.setdefault('watch_alerts',{}).pop(task,None)
        state.setdefault('redeliveries',[]).append({'task':task,'reason':reason,'at':utcnow(),'previous_alert':previous})
        durable_write(path,canonical(state).encode())
        return {'task':task,'requeued':True,'cursor_unchanged':state['cursor'],'delivery_confirmed':False}
