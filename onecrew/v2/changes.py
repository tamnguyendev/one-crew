"""CREQ with a limit (DESIGN-MVP section 4, "CREQ co han"): with the v2 gate on, a solution change request must carry a `delta`
(what is added, dropped, or the budget change) and a `reason` of at most 200 characters, and at most MAX_CHANGES of them may be
made for one conversation. The next one is refused and stops the plans bound to that conversation (stopped_with_report), so the
owner decides instead of the AI negotiating forever. Called from solution_gate.question.
"""
import json

from ..ledger import LedgerError

MAX_CHANGES = 2
DELTA_KEYS = ('add', 'drop', 'budget_delta')


def check_request(ledger, cid, kind, reason, delta):
    from . import gate
    if not gate.enforced(ledger): return
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 200:       # F5: every kind, the asker's own label decides nothing
        raise LedgerError('A request to the owner needs a reason of 1-200 characters (v2 gate on).')
    if kind == 'solution_change' and (not isinstance(delta, dict) or not delta or set(delta) - set(DELTA_KEYS) or len(json.dumps(delta)) > 1000):
        raise LedgerError('A change request needs a delta with at least one of add, drop, budget_delta (v2 gate on).')
    from .. import conversations as c
    with ledger.transaction() as conn:
        if not c.installed(conn): return
        made = list(conn.execute('SELECT payload FROM conversation_questions WHERE conversation=?', (cid,)))   # F5: all kinds count
        keys = [r['task_id'] for r in conn.execute('SELECT task_id FROM solution_bindings WHERE conversation=?', (cid,))]
        names = [conn.execute('SELECT request_key FROM tasks WHERE id=?', (t,)).fetchone()['request_key'] for t in keys]
    if len(made) < MAX_CHANGES: return
    stopped = [name for name in dict.fromkeys(names) if _stop(ledger, name)]
    raise LedgerError(f'Request {len(made) + 1} to the owner refused: {MAX_CHANGES} were already made for this conversation (max_changes). '
                      + ('Plan ' + ', '.join(stopped) + ' is now stopped_with_report: the owner decides.' if stopped else 'The owner decides.'))


def _stop(ledger, name):
    """Stop the plan `name` at its current milestone (reason max_changes) and ask the owner the one question. True when stopped."""
    from . import plan, verdict
    with ledger.transaction(write=True) as conn:
        state = plan.derive(ledger, conn, name)
        if state is None or state['status'] != 'approved': return False
        contract, sha = plan.load(ledger, state)
        revision = state['latest']
        views = plan.milestone_views(contract, state, revision)
        current = next((v for v in views if v['state'] != 'passed'), views[-1])
        stopped = {'plan': name, 'revision': revision, 'milestone': current['id'], 'plan_sha': sha, 'failures': current['failures'],
                   'max_repairs': current['max_repairs'], 'reason': 'max_changes exceeded', 'mode': current['mode']}
        plan.emit(ledger, conn, state['task_id'], 'milestone.stopped', stopped)
        anchor, limit = state['task_id'], contract['attention']['questions']
    verdict._escalate(ledger, name, anchor, stopped, limit)
    return True
