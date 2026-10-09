"""Operator-bound legacy DAGs: review one verified slice before parallel expansion."""
import json
from .ledger import LedgerError,content_hash
from . import conversations as c


def bind(ledger,task,task_revision,solution,revision):
    with ledger.transaction(write=True) as conn:
        c.ensure(conn);row=ledger._task(conn,task)
        if row['revision']!=task_revision:raise LedgerError('Stale task revision.')
        payload=json.loads(row['payload'])
        if payload.get('owned_execution'):raise LedgerError('Owned jobs bind at submit; use a solution change request to amend.')
        sol,decision=c.approved(ledger,conn,solution,revision)
        if payload['spec_revision'] not in sol['payload']['detail']:raise LedgerError('Detailed solution must explicitly pin the submitted spec hash.')
        old=conn.execute('SELECT * FROM solution_bindings WHERE task_id=?',(task,)).fetchone()
        if old:
            if old['solution']!=solution or old['revision']!=revision:raise LedgerError('Task already bound; reconcile through a change request.')
            return dict(old)
        if conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind='attempt.reserved'",(task,)).fetchone():raise LedgerError('Bind before the first worker call.')
        conn.execute('INSERT INTO solution_bindings VALUES(?,?,?,?,?)',(task,sol['conversation'],solution,revision,decision['id']))
        result=dict(task=task,solution=solution,revision=revision)
        c._event(conn,sol['conversation'],'bound:'+task,'task.bound',result);return result


def permit_parallel(workflow,task_id,state,profile):
    from .solution_gate import context,check
    binding=context(workflow.ledger,task_id)
    if not binding.get('conversation'):return True  # Legacy authority is preserved.
    check(workflow.ledger,task_id)
    if not state['done']:return False  # First slice is serial, even for independent roots.
    contract=content_hash({'solution':binding['revision'],'plan':state['plan'],'amendment':state.get('amendment')})
    if (state.get('first_slice_review') or {}).get('contract')==contract:return True
    from .workflow import verify
    from .sandbox_gate import task_guard
    done=set(state['done']);ac={a for t in state['plan']['tasks'] if t['id'] in done for a in t['acceptance']}
    checks=[test for test in profile['checks'] if set(test['acceptance'])<=ac]
    if not checks:raise LedgerError('First slice requires a scoped acceptance check before parallel expansion.')
    key='slice:'+content_hash({'contract':contract,'snapshot':state['snapshot']})
    with workflow.ledger.transaction() as conn:
        request=conn.execute('SELECT * FROM requests WHERE task_id=? AND request_key=?',(task_id,key)).fetchone()
        existing=workflow.ledger._request_view(request) if request else None
    if existing:
        if existing['state']=='pending':return None
        choice=existing['answer']['choice']
        if choice!='approve':raise LedgerError('First slice not approved; revise/review it before parallel expansion.')
        state['first_slice_review']={'contract':contract,'snapshot':state['snapshot'],'request':existing['id'],'answer':existing['answer']}
        return True
    result=verify(workflow.store,state['snapshot'],dict(profile,checks=checks),guard=task_guard(workflow.control,task_id))
    if not result['passed']:raise LedgerError('First slice acceptance checks failed; review and repair before parallel expansion.')
    workflow.ledger.create_request(task_id,key,{'schema_version':1,
        'question':'Duyệt lát đầu trước khi chạy các phần song song?',
        'reason':'Scoped checks passed. Review the current diff and approved solution; tests alone do not establish user acceptance.',
        'impact':'Dependent expansion waits; calls/deadline and original source remain unchanged.',
        'options':[{'id':'approve','label':'Duyệt pattern và tiếp tục'},{'id':'rework','label':'Cần sửa solution hoặc output'}],
        'recommendation':'approve','action':{'type':'solution.slice_review','parameters':{'snapshot':state['snapshot'],'contract':contract}}})
    return None
