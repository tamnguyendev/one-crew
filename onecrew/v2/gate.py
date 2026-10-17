"""Invariant 1 at the dispatch point: with v2 enforcement on, a task runs only while the plan named by its request key is the
latest revision, approved by the owner, not stopped and not yet accepted. Called from solution_gate.check, which every
dispatch path (enable, resume, configure, reserve, mutation) already goes through, in every mode including `work`.

Enforcement is opt-in per state root so that v1 keeps working unchanged: `plan enforce on --by owner`, or the environment
variable ONECREW_V2_REQUIRE_PLAN=1.
"""
import json
import os
import sys
import uuid
from pathlib import Path

from ..ledger import LedgerError, utcnow


def _plans(ledger):
    return Path(ledger.state_root) / 'plans'


def enforced(ledger):
    if os.environ.get('ONECREW_V2_REQUIRE_PLAN') == '1': return True
    path = _plans(ledger) / 'policy.json'
    if not path.exists(): return False
    try:
        return bool(json.loads(path.read_text(encoding='utf-8')).get('require_plan'))
    except (OSError, ValueError, AttributeError):
        return True  # a policy file that exists but cannot be read closes the gate, never opens it


def set_enforced(ledger, on, who, reference):
    from .ownership import refuse_in_ai_session
    refuse_in_ai_session('Changing enforcement')
    path = _plans(ledger)
    path.mkdir(parents=True, exist_ok=True)
    temporary = path / ('policy.json.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps({'require_plan': bool(on)}), encoding='utf-8')
    os.replace(temporary, path / 'policy.json')  # atomic: a reader sees the old or the new policy, never half of one
    with (path / 'audit.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'at': utcnow(), 'require_plan': bool(on), 'by': who, 'reference': reference}, ensure_ascii=False) + '\n')
    return {'require_plan': bool(on), 'state_root': str(ledger.state_root)}


def _over_budget(conn, task, budget):
    """A job may not carry larger limits than the approved plan's budget (invariant 3: the AI does not widen it). The limits
    compared are the CURRENT ones (original grant, or the latest extension), so widening after dispatch (C7) is caught too."""
    from ..budget import local_current
    limits = local_current(conn, task)['limits']
    if limits['max_calls'] > budget['max_calls']:
        return f'the job allows {limits["max_calls"]} calls but the approved plan budget is {budget["max_calls"]}'
    if limits['max_seconds'] is None or limits['max_seconds'] > budget['time'] * 60:
        return f'the job allows {limits["max_seconds"]} seconds but the approved plan budget is {budget["time"] * 60} ({budget["time"]} minutes)'
    return None


def check_extension(ledger, conn, task, max_calls, seconds):
    """C7: with the gate on, budget.extend / remove_deadline may not take the job past the budget of its approved plan.
    `seconds` None means "no time limit"."""
    if not enforced(ledger): return
    from . import plan
    state = plan.derive(ledger, conn, task['request_key'])
    if state is None or state['status'] != 'approved':
        raise LedgerError('Budget not extended (v2): no approved plan named ' + task['request_key'] + '.')
    budget = plan.load(ledger, state)[0]['budget']
    if max_calls > budget['max_calls']:
        raise LedgerError(f'Budget not extended (v2): {max_calls} calls exceeds the approved plan budget of {budget["max_calls"]}; amend the plan and have the owner approve it.')
    if seconds is None or seconds > budget['time'] * 60:
        raise LedgerError(f'Budget not extended (v2): {"no time limit" if seconds is None else str(int(seconds)) + " seconds"} exceeds the approved plan budget of {budget["time"]} minutes; amend the plan and have the owner approve it.')


def require_plan(ledger, conn, task):
    """Raise LedgerError unless the task's plan is approved. The refusal is spooled to a file (the caller's transaction is
    about to roll back, and may be read-only) and becomes a `dispatch.refused_no_plan` event in sync_refusals()."""
    if not enforced(ledger): return
    from . import plan
    name = task['request_key']
    try:
        state = plan.derive(ledger, conn, name)
        if state is None: reason = 'no plan named ' + name + ' (plan propose, then the owner runs plan approve)'
        elif state['status'] != 'approved': reason = f'plan {name} is {state["status"]}, not approved'
        else:
            contract, _ = plan.load(ledger, state)  # the file must still hash to what the owner approved
            reason = _over_budget(conn, task, contract['budget'])
            if reason is None: return
    except LedgerError as error:
        reason = str(error)
    refuse(ledger, task, reason)


def refuse(ledger, task, reason, question=None):
    """Spool the refusal (and, for a stopped must item, the owner question) to files and raise. The caller's transaction rolls back."""
    plans = _plans(ledger)
    plans.mkdir(parents=True, exist_ok=True)
    with (plans / 'refusals.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'id': uuid.uuid4().hex, 'at': utcnow(), 'task_id': task['id'], 'project_id': ledger.project_id,
                                 'request_key': task['request_key'], 'reason': reason}, ensure_ascii=False) + '\n')
    if question:
        with (plans / 'questions.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(question, id=uuid.uuid4().hex, at=utcnow(), project_id=ledger.project_id), ensure_ascii=False) + '\n')
    raise LedgerError('Dispatch refused (v2): ' + reason + '.')


def sync_refusals(ledger):
    """Move spooled refusals into the ledger as dispatch.refused_no_plan events on the refused task. Idempotent."""
    from .items import sync_questions
    sync_questions(ledger)
    spool = _plans(ledger) / 'refusals.jsonl'
    if not spool.exists(): return 0
    records, skipped = [], 0
    for line in spool.read_text(encoding='utf-8', errors='replace').splitlines():
        if not line.strip(): continue
        try:
            record = json.loads(line)
            if not all(isinstance(record.get(k), str) for k in ('id', 'task_id', 'project_id', 'request_key', 'reason', 'at')): raise ValueError
            records.append(record)
        except (ValueError, AttributeError):
            skipped += 1
    if skipped: print(f'warning: {spool.name}: skipped {skipped} unreadable line(s)', file=sys.stderr)
    added = 0
    with ledger.transaction(write=True) as conn:
        for record in records:
            if record['project_id'] != ledger.project_id: continue
            known = conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind='dispatch.refused_no_plan' AND json_extract(payload,'$.spool_id')=?",
                                 (record['task_id'], record['id'])).fetchone()
            if known or not conn.execute('SELECT 1 FROM tasks WHERE id=?', (record['task_id'],)).fetchone(): continue
            ledger._event(conn, record['task_id'], 'dispatch.refused_no_plan',
                          {'spool_id': record['id'], 'request_key': record['request_key'], 'reason': record['reason'], 'at': record['at']})
            added += 1
    return added
