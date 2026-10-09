"""A failed DAG unit blocks its dependents while independent units can continue."""
import datetime as dt
import json

from .amendment import affected_tasks, plan_revision, profile_for
from .ledger import LedgerError, content_hash
from .budget import remaining


def blocks(conn, task_id, unit='root'):
    rows = conn.execute("SELECT payload FROM requests WHERE task_id=? AND state='pending'", (task_id,)).fetchall()
    for row in rows:
        action = json.loads(row['payload'])['action']
        affected = action['parameters'].get('affected_tasks')
        scoped = action['type'] == 'workflow.branch' and isinstance(affected, list) and affected and all(isinstance(x, str) for x in affected)
        if not scoped or unit == 'root':
            return True
        if unit != 'scheduler' and (not unit.startswith('task:') or unit[5:] in affected):
            return True
    return False


def record_failure(state, record, error):
    reason = ''.join(c for c in str(error) if ord(c) >= 32 or c in '\n\t')[:1000]
    state.setdefault('branch_errors', {})[record['task']] = {
        'task': record['task'], 'attempt': record['attempt'], 'base': record['base'],
        'owned': record['owned'], 'reason': reason, 'no_progress': 'No source progress' in reason}
    state['parallel_pending'] = [r for r in state.get('parallel_pending', []) if r['attempt'] != record['attempt']]
    if state.get('pending') == record['attempt']:
        state['pending'] = None


def question(workflow, task_id, state, error):
    control = workflow.control.status(task_id)
    bound = content_hash({'error': error, 'plan_revision': plan_revision(state), 'budget_revision': control['budget']['revision']})
    affected = sorted(affected_tasks(state['plan'], [error['task']]))
    action = {'type': 'workflow.branch', 'parameters': {'task': error['task'], 'fingerprint': bound,
              'affected_tasks': affected, 'budget_revision': control['budget']['revision']}}
    for old in workflow.ledger.requests(task_id):
        if old['question']['action'] == action:
            return old
    profile = profile_for(state, control)
    left = remaining(control['budget'],control['used_calls'],control['reserved_calls'])
    can_retry = left > 0 and state['failed_calls'] < profile['max_repairs'] and not error['no_progress']
    choice = 'retry' if can_retry else 'inspect'
    value = {'schema_version': 1, 'question': f"Nhánh {error['task']} đang chờ xử lý. Anh chọn cách nào?",
             'reason': error['reason'] or 'Worker did not publish valid output.',
             'impact': f"Chặn {', '.join(affected)}; nhánh độc lập vẫn tiếp tục. Khi hỏi còn {max(0,left)} calls. Retry chỉ sau stop/reconcile, giữ scope và deadline.",
             'options': [{'id': choice, 'label': 'Thử lại nhánh trong grant cũ' if can_retry else 'Kiểm tra nguyên nhân, giữ nhánh chờ'},
                         {'id': 'stop', 'label': 'Dừng toàn bộ task gốc, giữ output'}],
             'recommendation': choice, 'action': action}
    return workflow.ledger.create_request(task_id, 'branch:'+bound, value)


def process(workflow, task_id, sequence, state):
    """Called only while the controller holds the task lock, between dispatches."""
    for unit, error in list(state.get('branch_errors', {}).items()):
        request = question(workflow, task_id, state, error)
        if request['state'] == 'pending' or workflow.ledger.request(request['id']).get('controller_effect'):
            continue
        answer = request['answer']
        action = request['question']['action']['parameters']
        control = workflow.control.status(task_id)
        receipt = {'request_id': request['id'], 'reply_id': answer['id'], 'choice': answer['choice'],
                   'unit': unit, 'fingerprint': action['fingerprint'], 'budget_revision': action['budget_revision'],
                   'authority': 'existing_local_operator_grant', 'scope_expanded': False, 'budget_extended': False}
        if answer['choice'] == 'retry':
            attempt = workflow.control.attempt(error['attempt'])
            profile = profile_for(state, control)
            if (attempt['status'] != 'settled' or control['cancel_requested']
                    or control['budget']['revision'] != action['budget_revision']
                    or state['failed_calls'] >= profile['max_repairs'] or error['no_progress']
                    or remaining(control['budget'],control['used_calls'],control['reserved_calls']) <= 0
                    or workflow.control.clock() >= dt.datetime.fromisoformat(control['deadline'])):
                continue  # Reply is recorded, but no unsafe launch or extra budget is authorized.
            del state['branch_errors'][unit]
            state['failed_calls'] += 1
            state['phase'] = 'working'
            state['message'] = None
            receipt['effect'] = 'branch_resumed_existing_scope'
        elif answer['choice'] == 'stop':
            workflow.control.cancel(task_id)
            receipt['effect'] = 'cancel_requested'
        elif answer['choice'] == 'inspect':
            receipt['effect'] = 'inspection_requested'
        else:
            raise LedgerError('Unknown branch reply; no action applied.')
        state['triage_receipt'] = receipt
        sequence = workflow.persist(task_id, sequence, state)
    return sequence
