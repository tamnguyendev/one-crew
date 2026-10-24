"""W30c: apply a recorded owner answer once, without enlarging the grant."""
import json

from ..ledger import LedgerError
from . import namespaces, plan


def apply(ledger, request_id):
    selector = None
    with ledger.transaction(write=True) as conn:
        request = ledger._request(conn, request_id)
        task = ledger._task(conn, request['task_id'])
        if not task['request_key'].startswith(namespaces.NAMESPACED):
            return {'applied': False, 'reason': 'legacy_root'}
        state = plan.anchor_events(ledger, conn, task['request_key'])
        if not namespaces.has_capability(state, 'sequential-engine'):
            return {'applied': False, 'reason': 'capability_not_declared'}
        if request['state'] != 'answered':
            return {'applied': False, 'reason': 'answer_required'}
        question = json.loads(request['payload'])
        action = question['action']
        parameters = action.get('parameters', {})
        if action['type'] not in ('v2.plan_stopped', 'v2.workflow_hold'):
            return {'applied': False, 'reason': 'unsupported_action'}
        answer = json.loads(request['answer'])
        provenance = answer.get('provenance', {})
        if provenance.get('decided_by') != 'user' or provenance.get('by') != 'user':
            raise LedgerError('A workflow effect requires a recorded owner answer; a worker claim is not one.')
        previous = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='request.applied' AND json_extract(payload,'$.request_id')=? AND json_extract(payload,'$.request_revision')=?",
                                (state['task_id'], request_id, request['revision'])).fetchone()
        if previous: return dict(json.loads(previous['payload']), applied=True, repeated=True)
        workflow_hold = action['type'] == 'v2.workflow_hold'
        revision = parameters.get('contract_revision') if workflow_hold else parameters.get('revision')
        if revision != state['latest'] or state['status'] not in (('approved',) if workflow_hold else ('stopped_with_report',)):
            return {'applied': False, 'reason': 'superseded_root_state'}
        if workflow_hold:
            from . import engine
            view = engine.state(ledger, state['selector'], conn)
            if (parameters.get('root') != state['task_id'] or parameters.get('plan') != state['selector']
                    or parameters.get('contract_sha') != state['approved']['sha']
                    or parameters.get('internal_revision') != view['internal_revision']):
                return {'applied': False, 'reason': 'superseded_workflow_question'}
        else:
            stopped = state['stopped'][revision]
            if parameters.get('milestone') != stopped.get('milestone'):
                raise LedgerError('The answer does not identify the currently stopped milestone.')
        choice = answer['choice']
        if choice not in (('continue', 'stop') if workflow_hold else ('stop', 'amend_plan')):
            raise LedgerError('Unsupported stopped-plan answer; stop limits cannot be reset by a reply.')
        resumed = None
        if workflow_hold and choice == 'continue':
            resumed = engine.resume_held(ledger, state['selector'], request_id=request_id,
                request_revision=request['revision'], contract_sha=parameters['contract_sha'],
                generations=parameters['generations'], conn=conn)
        effect = {'plan': state['name'], 'revision': revision, 'request_id': request_id,
                  'request_revision': request['revision'], 'answer_id': answer['id'], 'choice': choice,
                  'reference': provenance['reference'], 'by': 'owner', 'grants_authority': False,
                  'effect': 'closed' if choice == 'stop' else 'continued_within_grant' if resumed else 'await_new_approved_revision'}
        if resumed is not None: effect['resumed'] = resumed
        if choice == 'stop':
            plan.emit(ledger, conn, state['task_id'], 'plan.closed', dict(effect, reason=provenance['reference']))
        plan.emit(ledger, conn, state['task_id'], 'request.applied', effect)
        selector = state['selector']
    from . import active_plan, outcome
    active_plan.export(ledger, selector)
    outcome.note(ledger, selector)
    return dict(effect, applied=True)


def reconcile(ledger, selector):
    """Repair a crash after reply persistence, without inventing another answer."""
    with ledger.transaction() as conn:
        state = plan.anchor_events(ledger, conn, selector)
        rows = conn.execute("SELECT id FROM requests WHERE task_id=? AND state='answered' ORDER BY updated_at,id", (state['task_id'],)).fetchall()
    return [apply(ledger, row['id']) for row in rows]
