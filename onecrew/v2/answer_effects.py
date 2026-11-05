"""W30c: apply a recorded owner answer once, without enlarging the grant.

Two paths reach `apply` (P1-2, T47c E6 / T43d E7,E13):
- the current answer path: `reply_and_apply` (used by questions.answer, `request reply` and the MCP reply) writes the
  reply and runs `_apply` inside ONE
  write transaction, so a committed answered request of a workflow root always carries its mandatory effect
  (plan.closed / node.resumed + request.applied); a failure anywhere in it rolls the reply back as well. The side I/O
  (`after_commit`: active plan export, outcome note) runs only after that commit.
- `reconcile` (and `apply` without conn): repairs an answered-but-unapplied request left by a PREVIOUS build, which
  committed the reply and the effect in two transactions, or by a reply recorded through the plain v1 request surface.
  It is not the atomicity mechanism of the current path.
"""
import json
import sys

from ..ledger import LedgerError
from . import namespaces, plan


def apply(ledger, request_id, conn=None):
    """Apply the effect of a recorded owner answer, exactly once.

    conn: an open write transaction (the caller's): the effect is written into it, nothing is committed here and no side
    I/O runs; the caller commits and then calls `after_commit`. Without conn the effect has its own transaction and the
    side I/O runs after it commits (repair path)."""
    if conn is not None:
        return _apply(ledger, conn, request_id)[0]
    with ledger.transaction(write=True) as connection:
        result, selector = _apply(ledger, connection, request_id)
    errors = after_commit(ledger, selector, result)
    return dict(result, post_commit_errors=errors) if errors else result


def reply_and_apply(ledger, request_id, revision, choice, *, source, reference, decided_by, by, export=False):
    """The one implementation of "record an answer" for every entry route (questions.answer, `request reply`, MCP reply).

    ONE write transaction: v1 `reply` (revision, choice, provenance, idempotency and conflict checks) and, when the request
    belongs to a plan-ns root with the sequential-engine capability and a supported action, its effect. Any other request
    (legacy/default root, ordinary task) gets the reply only. A mandatory effect that cannot be applied (e.g. the answer
    lacks owner provenance, or resume is refused) raises and rolls the reply back with it. Side I/O runs after commit.
    Returns the receipt, plus controller_effect when an effect applied and post_commit_errors when side I/O failed."""
    with ledger.transaction(write=True) as conn:
        receipt = ledger.reply(request_id, revision, choice, source=source, reference=reference,
                               decided_by=decided_by, by=by, conn=conn)
        effect, selector = _apply(ledger, conn, request_id)
        if export and selector is None:
            selector = ledger._task(conn, ledger._request(conn, request_id)['task_id'])['request_key']
    errors = after_commit(ledger, selector, effect, export=export)
    result = dict(receipt, controller_effect=effect) if effect.get('applied') else dict(receipt)
    if str(effect.get('reason', '')).startswith('superseded'):      # recorded, and it changed nothing: said in the result, not left to be assumed
        result['no_effect'] = {'reason': effect['reason'], 'note': 'Câu hỏi này thuộc trạng thái cũ của plan: câu trả lời đã ghi nhưng không có hiệu lực. Đọc bước tiếp theo hiện tại.'}
    if errors: result['post_commit_errors'] = errors
    return result


def after_commit(ledger, selector, result, export=False):
    """Side I/O after a committed effect; it never changes ledger state, so a failure is reported, not raised.

    export=True exports the active plan even when nothing was newly applied (questions.answer always refreshes it)."""
    from . import active_plan, outcome
    fresh = result.get('applied') and not result.get('repeated')
    errors = []
    if selector and (fresh or export):
        try: active_plan.export(ledger, selector)
        except Exception as error: errors.append(f'active plan export: {type(error).__name__}: {error}')
    if selector and fresh:
        try: outcome.note(ledger, selector)
        except Exception as error: errors.append(f'outcome note: {type(error).__name__}: {error}')
    for line in errors: print('Answer committed; ' + line, file=sys.stderr)
    return errors


def _apply(ledger, conn, request_id):
    """Returns (result, selector of the root or None). Writes only into conn."""
    request = ledger._request(conn, request_id)
    task = ledger._task(conn, request['task_id'])
    if not task['request_key'].startswith(namespaces.NAMESPACED):
        return {'applied': False, 'reason': 'legacy_root'}, None
    state = plan.anchor_events(ledger, conn, task['request_key'])
    if not namespaces.has_capability(state, 'sequential-engine'):
        return {'applied': False, 'reason': 'capability_not_declared'}, None
    if request['state'] != 'answered':
        return {'applied': False, 'reason': 'answer_required'}, state['selector']
    question = json.loads(request['payload'])
    action = question['action']
    parameters = action.get('parameters', {})
    if action['type'] not in ('v2.plan_stopped', 'v2.workflow_hold'):
        return {'applied': False, 'reason': 'unsupported_action'}, state['selector']
    answer = json.loads(request['answer'])
    provenance = answer.get('provenance', {})
    if answer.get('choice') == 'superseded_by_approval':       # closed by a later plan.approved (plan._supersede_holds): nobody answered it, nothing to apply
        return {'applied': False, 'reason': 'superseded_by_approval'}, state['selector']
    if provenance.get('decided_by') != 'user' or provenance.get('by') != 'user':
        raise LedgerError('A workflow effect requires a recorded owner answer; a worker claim is not one.')
    previous = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='request.applied' AND json_extract(payload,'$.request_id')=? AND json_extract(payload,'$.request_revision')=?",
                            (state['task_id'], request_id, request['revision'])).fetchone()
    if previous: return dict(json.loads(previous['payload']), applied=True, repeated=True), state['selector']
    workflow_hold = action['type'] == 'v2.workflow_hold'
    revision = parameters.get('contract_revision') if workflow_hold else parameters.get('revision')
    choice = answer['choice']
    # `stop` is the owner ending this root: it means the same whichever revision the question was asked on, while the root is still open.
    ending = workflow_hold and choice == 'stop' and state['status'] in ('approved', 'proposed') and parameters.get('root') == state['task_id']
    if not ending and (revision != state['latest'] or state['status'] not in (('approved',) if workflow_hold else ('stopped_with_report',))):
        return {'applied': False, 'reason': 'superseded_root_state'}, state['selector']
    if workflow_hold and not ending:
        from . import engine
        view = engine.state(ledger, state['selector'], conn)
        if (parameters.get('root') != state['task_id'] or parameters.get('plan') != state['selector']
                or parameters.get('contract_sha') != state['approved']['sha']
                or parameters.get('internal_revision') != view['internal_revision']):
            return {'applied': False, 'reason': 'superseded_workflow_question'}, state['selector']
    elif not workflow_hold:
        stopped = state['stopped'][revision]
        if parameters.get('milestone') != stopped.get('milestone'):
            raise LedgerError('The answer does not identify the currently stopped milestone.')
    if choice not in (('continue', 'stop', 'amend_plan') if workflow_hold else ('stop', 'amend_plan')):
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
    return dict(effect, applied=True), state['selector']


def reconcile(ledger, selector):
    """Repair an answered-but-unapplied request left by a previous build (reply and effect in two transactions) or by a
    reply recorded through the plain v1 request surface, without inventing another answer. The current answer path
    (questions.answer) never leaves such a state: it commits reply and effect together."""
    with ledger.transaction() as conn:
        state = plan.anchor_events(ledger, conn, selector)
        rows = conn.execute("SELECT id FROM requests WHERE task_id=? AND state='answered' ORDER BY updated_at,id", (state['task_id'],)).fetchall()
    return [apply(ledger, row['id']) for row in rows]
