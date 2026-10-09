"""Durable short questions; replies may only resume the already sealed scope."""
import datetime as dt

from .ledger import LedgerError, content_hash
from .budget import remaining


def fingerprint(state):
    return content_hash({key: state.get(key) for key in
                         ('phase', 'task_revision', 'snapshot', 'plan', 'done', 'worker', 'amendment',
                          'message', 'resume_phase', 'pending', 'parallel_pending', 'failed_calls', 'repairs')})


def ensure_request(workflow, task_id):
    _, state = workflow.state(task_id)
    if not state or state['phase'] != 'blocked':
        return None
    bound = fingerprint(state)
    control = workflow.control.status(task_id)
    budget_revision = control['budget']['revision']
    for request in workflow.ledger.requests(task_id):
        action = request['question']['action']
        if action == {'type': 'workflow.triage', 'parameters': {'fingerprint': bound, 'budget_revision': budget_revision}}:
            return request
    task = workflow.ledger.task(task_id, full=True)
    from .amendment import profile_for
    profile = profile_for(state, control)
    left = remaining(task['budget'],control['used_calls'],control['reserved_calls'])
    safe = (bool(state.get('resume_phase')) and left > 0 and not control['cancel_requested']
            and state['failed_calls'] < profile['max_repairs']
            and all(a['status'] == 'settled' for a in control['attempts'])
            and workflow.control.clock() < dt.datetime.fromisoformat(control['deadline']))
    first = 'retry' if safe else 'inspect'
    question = {'schema_version': 1,
                'question': 'OneCrew đang dừng tại một vấn đề. Anh muốn xử lý thế nào?',
                'reason': (state['message'] or 'Cần kiểm tra checkpoint trước khi tiếp tục.')[:1000],
                'impact': f'Còn tối đa {max(0,left)} lượt gọi trong grant hiện tại. Giữ nguyên scope, deadline và model đã chọn; không cấp thêm quyền.',
                'options': [{'id': first, 'label': 'Thử lại trong phạm vi cũ' if safe else 'Xem output và xử lý nguyên nhân'},
                            {'id': 'stop', 'label': 'Dừng task, giữ lại output'}],
                'recommendation': first,
                'action': {'type': 'workflow.triage', 'parameters': {'fingerprint': bound, 'budget_revision': budget_revision}}}
    return workflow.ledger.create_request(task_id, 'triage:' + content_hash(question['action']), question)


def handle(workflow, task_id):
    _, current = workflow.state(task_id)
    if current and current.get('branch_errors') and current['phase'] in ('working', 'waiting_branches'):
        from .workflow import task_lock
        from .branch_inbox import process
        with task_lock(workflow.ledger, task_id):
            seq, current = workflow.state(task_id)
            process(workflow, task_id, seq, current)
        return {'status': current['phase'], 'requests': workflow.ledger.requests(task_id, pending=True)}
    request = ensure_request(workflow, task_id)
    if request is None:
        return {'status': 'not_blocked'}
    if request['state'] == 'pending':
        return {'status': 'waiting', 'request': request}
    applied = workflow.ledger.request(request['id']).get('controller_effect')
    if applied:
        return {'status': 'cancelled' if applied['choice'] == 'stop' else 'blocked', 'receipt': applied}
    _, state = workflow.state(task_id)
    bound = request['question']['action']['parameters']['fingerprint']
    if fingerprint(state) != bound:
        raise LedgerError('Blocker changed; the old reply cannot resume a new state.')
    answer = request['answer']
    receipt = {'request_id': request['id'], 'reply_id': answer['id'], 'choice': answer['choice'],
               'fingerprint': bound, 'authority': 'existing_local_operator_grant',
               'budget_revision': request['question']['action']['parameters']['budget_revision'],
               'scope_expanded': False, 'budget_extended': False}
    if answer['choice'] == 'retry':
        control = workflow.control.status(task_id)
        if (remaining(control['budget'],control['used_calls'],control['reserved_calls']) <= 0
                or workflow.control.clock() >= dt.datetime.fromisoformat(control['deadline'])):
            return {'status': 'blocked', 'reason': 'Budget/deadline exhausted after the question was created.'}
        receipt['effect'] = 'resumed_existing_scope'
        workflow.resume(task_id, triage_receipt=receipt)
        return {'status': 'resumed', 'receipt': receipt}
    if answer['choice'] not in ('inspect', 'stop'):
        raise LedgerError('Unsupported triage choice; no action applied.')
    from .workflow import task_lock
    with task_lock(workflow.ledger, task_id):
        seq, state = workflow.state(task_id)
        if fingerprint(state) != bound:
            raise LedgerError('Blocker changed before applying reply.')
        if workflow.control.status(task_id)['budget']['revision'] != receipt['budget_revision']:
            raise LedgerError('Budget changed before applying reply.')
        if answer['choice'] == 'stop':
            workflow.control.cancel(task_id)
            receipt['effect'] = 'cancel_requested'
        else:
            receipt['effect'] = 'inspection_requested'
        state['triage_receipt'] = receipt
        workflow.persist(task_id, seq, state)
    return {'status': 'cancelled' if answer['choice'] == 'stop' else 'blocked', 'receipt': receipt}
