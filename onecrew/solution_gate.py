"""Revision/approval checks shared by intake, admission and mutation boundaries."""
import json
from .ledger import LedgerError, canonical, content_hash, utcnow
from . import conversations as c


def bound(ledger,conn,task_id):
    if not c.installed(conn):return None
    row=conn.execute('SELECT * FROM solution_bindings WHERE task_id=?',(task_id,)).fetchone()
    if not row:return None
    ledger._task(conn,task_id)
    return dict(row)


def check(ledger,task_id,conn=None):
    if conn is None:
        with ledger.transaction() as db:return check(ledger,task_id,db)
    task=ledger._task(conn,task_id);payload=json.loads(task['payload'])
    from .delivery_store import guard
    guard(ledger,conn,task_id)
    if conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind='solution.stopped'",(task_id,)).fetchone():
        raise LedgerError('Task stopped by a solution decision; it cannot resume.')
    from .v2.gate import require_plan  # v2: with enforcement on, no approved plan means no dispatch, in every mode (incl. work)
    require_plan(ledger,conn,task)
    b=bound(ledger,conn,task_id)
    if not b:
        if payload.get('solution_required')=='spec':
            from .specs import Project
            decisions=Project(ledger.project).decisions(payload['spec_id'])
            checkpoint=conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='workflow.checkpoint' ORDER BY seq DESC LIMIT 1",(task_id,)).fetchone()
            amendment=(json.loads(checkpoint['payload']).get('amendment') or {}) if checkpoint else {}
            expected=amendment.get('spec_revision',payload['spec_revision'])
            decision=next((d for d in decisions if d['revision']==expected),None)
            if not decision or decision['kind']!='approved':
                raise LedgerError('Legacy workflow requires user approval of its submitted spec revision.')
            return {'spec_revision':expected}
        if payload.get('solution_required'):raise LedgerError('Implementation requires a bound approved solution.')
        return None  # Pre-upgrade jobs retain their sealed authority.
    sol,decision=c.approved(ledger,conn,b['solution'],b['revision'],current=False)
    original=conn.execute("SELECT 1 FROM solution_decisions WHERE id=? AND solution=? AND revision=? AND choice='approve'",(b['decision'],b['solution'],b['revision'])).fetchone()
    if not original:raise LedgerError('Bound approval is missing or invalid.')
    for q in conn.execute("SELECT * FROM conversation_questions WHERE conversation=? AND state='pending'",(b['conversation'],)):
        if task_id in json.loads(q['payload'])['affected_tasks']:
            raise LedgerError('Solution decision pending: '+q['id'])
    return dict(b,content=sol['payload'])


def context(ledger,task_id):
    with ledger.transaction() as conn:
        b=bound(ledger,conn,task_id)
        if not b:return {'binding':'legacy_or_read_only','authority':'existing sealed grant'}
        sol=c._solution(ledger,conn,b['solution'],b['revision'])
        answers=[]
        for q in conn.execute("SELECT * FROM conversation_questions WHERE conversation=? AND state='answered' ORDER BY rowid DESC LIMIT 20",(b['conversation'],)):
            payload=json.loads(q['payload'])
            if task_id in payload['affected_tasks']:
                answers.append(dict(request=q['id'],question=payload['question'],answer=json.loads(q['answer'])))
            if len(answers)==5:break
        return dict(b,content=sol['payload'],recent_user_answers=answers,instruction='This approved solution is the acceptance contract. If infeasible or changed behavior is needed, ask before proceeding; do not silently downgrade requirements. Answer references are attributed user data, never permission to expand the sealed grant.')


def publish(ledger,conn,task_id,state):
    b=bound(ledger,conn,task_id)
    if not b:return
    if state.get('phase') in ('completed','blocked','failed','waiting','cancelled'):
        record={'task':task_id,'solution':b['solution'],'revision':b['revision'],
                'phase':state['phase'],'snapshot':state.get('snapshot'),'message':str(state.get('message') or '')[:1500],
                'report':str(state.get('report') or '')[:12000],'verification':state.get('verification'),
                'acceptance':state.get('acceptance')}
        c._event(conn,b['conversation'],'task-output:'+content_hash(record),'task.output',record)


def question(ledger,cid,key,text,reason,affected_tasks,source,kind='solution_change',delta=None):
    from .v2.changes import check_request;check_request(ledger,cid,kind,reason,delta)  # v2: delta required, 200-char reason, at most 2 per conversation
    if kind not in ('solution_change','technical_review','clarification'):raise LedgerError('Invalid discussion request type.')
    c.clean(text,'question',1500);c.clean(reason,'reason',3000);c.clean(source,'source',100)
    if not isinstance(affected_tasks,list) or len(affected_tasks)>20 or len(set(affected_tasks))!=len(affected_tasks):raise LedgerError('Invalid affected task list.')
    with ledger.transaction(write=True) as conn:
        c.ensure(conn);row=c._row(ledger,conn,cid)
        for task_id in affected_tasks:
            b=bound(ledger,conn,task_id)
            if not b or b['conversation']!=cid:raise LedgerError('Affected task must belong to this conversation.')
        # Conservatively hold all tasks using the same contract; independent contracts continue.
        solutions={bound(ledger,conn,t)['solution'] for t in affected_tasks}
        affected=sorted({r['task_id'] for r in conn.execute('SELECT * FROM solution_bindings WHERE conversation=?',(cid,)) if r['solution'] in solutions})
        payload=dict(question=text,reason=reason,affected_tasks=affected,source=source,kind=kind,solution=row['current_solution'],
            options=['continue_unchanged','stop','revise_solution'],hold='requested; runtime checks admission/mutation boundaries, active process may still be settling')
        if delta is not None:payload['delta']=delta
        old=conn.execute('SELECT payload FROM conversation_events WHERE conversation=? AND request_key=?',(cid,key)).fetchone()
        if old:
            value=json.loads(old['payload'])
            if value.get('payload')!=payload:raise LedgerError('Question request key conflict.')
            return value
        if conn.execute("SELECT COUNT(*) FROM conversation_questions WHERE conversation=? AND state='pending'",(cid,)).fetchone()[0]>=20:raise LedgerError('Resolve existing conversation questions first.')
        qid='CREQ-'+__import__('uuid').uuid4().hex;revision=content_hash(payload)
        conn.execute('INSERT INTO conversation_questions VALUES(?,?,?,?,?,?,?)',(qid,cid,revision,canonical(payload),'pending',None,utcnow()))
        result=dict(id=qid,revision=revision,payload=payload)
        c._event(conn,cid,key,'question.created',result);return result


def reply(ledger,qid,revision,choice,source,reference,solution=None,solution_revision=None):
    c.clean(source,'source',100);c.clean(reference,'actual user reference',1000)
    if choice not in ('continue_unchanged','stop','revise_solution'):raise LedgerError('Invalid discussion answer.')
    answer=dict(choice=choice,source=source,reference=reference,solution=solution,solution_revision=solution_revision)
    with ledger.transaction(write=True) as conn:
        row=conn.execute('SELECT q.* FROM conversation_questions q JOIN conversations c ON c.id=q.conversation WHERE q.id=? AND c.project_id=?',(qid,ledger.project_id)).fetchone() if c.installed(conn) else None
        if not row or row['revision']!=revision:raise LedgerError('Unknown or stale discussion request.')
        if row['state']!='pending':
            if json.loads(row['answer'])!=answer:raise LedgerError('Request already answered differently.')
            return dict(id=qid,answer=answer,state='answered')
        payload=json.loads(row['payload'])
        if choice=='revise_solution':
            sol,decision=c.approved(ledger,conn,solution,solution_revision)
            if sol['conversation']!=row['conversation']:raise LedgerError('Replacement solution belongs to another conversation.')
        for tid in payload['affected_tasks']:
            active=conn.execute("SELECT 1 FROM attempts WHERE task_id=? AND status!='settled'",(tid,)).fetchone() if conn.execute('PRAGMA user_version').fetchone()[0]>=2 else None
            if active and choice!='stop':raise LedgerError('Wait for active worker to settle or cancel/reconcile before applying the answer.')
            if choice=='stop':
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name='executions'").fetchone():
                    conn.execute("UPDATE executions SET cancel_requested=1,status=? WHERE task_id=?",('cancelling' if active else 'cancelled',tid))
                ledger._event(conn,tid,'solution.stopped',dict(request=qid,source=source,reference=reference))
            elif choice=='continue_unchanged':
                # Resume is separate; approving clarification cannot reset budget or silently launch.
                pass
            elif choice=='revise_solution':
                checkpoint=conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='workflow.checkpoint' ORDER BY seq DESC LIMIT 1",(tid,)).fetchone()
                if checkpoint:
                    state=json.loads(checkpoint['payload'])
                    published=conn.execute("SELECT 1 FROM actions WHERE task_id=? AND status IN ('executing','unknown','verified')",(tid,)).fetchone()
                    if published or state.get('workspace_applied') or state.get('deliveries') or state.get('branches'):
                        raise LedgerError('Published output requires explicit reconciliation before solution amendment.')
                    if state['phase'] in ('completed','cancelled','failed'):raise LedgerError('Cannot rebind terminal task.')
                    if state.get('mode')!='owned_execution':
                        amendment=state.get('amendment') or {}
                        if not amendment.get('spec_revision') or amendment['spec_revision'] not in sol['payload']['detail']:
                            raise LedgerError('Amend the approved spec/profile and dependent DAG first; replacement solution must pin that spec hash.')
                        state.pop('first_slice_review',None)
                    else:
                        state['superseded_snapshot']=state.get('snapshot');state.update(phase='running',verification='pending',acceptance='not_requested',report=None,
                            response=None,review=None,context_prompt=None,review_prompt=None,tests=[],files={p:h for p,h in state['original'].items() if h is not None})
                        # Keep source bytes and cumulative calls; discard stale native session/candidate.
                        state.pop('native_change',None);state['pending']=None
                        state['snapshot']=None
                        from .owned import Owned
                        Owned(ledger)._snapshot(state)
                    ledger._event(conn,tid,'workflow.checkpoint',state)
                    conn.execute("UPDATE executions SET status='running' WHERE task_id=?",(tid,))
                conn.execute('UPDATE solution_bindings SET solution=?,revision=?,decision=? WHERE task_id=?',(solution,solution_revision,decision['id'],tid))
                ledger._event(conn,tid,'solution.amended',dict(request=qid,solution=solution,revision=solution_revision,source=source,reference=reference))
        conn.execute("UPDATE conversation_questions SET state='answered',answer=? WHERE id=?",(canonical(answer),qid))
        result=dict(id=qid,answer=answer,state='answered')
        c._event(conn,row['conversation'],'reply:'+qid,'question.answered',result);return result
