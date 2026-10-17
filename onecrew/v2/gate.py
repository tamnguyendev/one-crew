"""Invariant 1 at the dispatch point: with v2 enforcement on, a task runs only while the plan named by its request key is the
latest revision, approved by the owner, not stopped and not yet accepted. Called from solution_gate.check, which every
dispatch path (enable, resume, configure, reserve, mutation) already goes through, in every mode including `work`.

Enforcement is opt-in per state root so that v1 keeps working unchanged: `plan enforce on --by owner`, or the environment
variable ONECREW_V2_REQUIRE_PLAN=1.
"""
import json
import os
import uuid
from pathlib import Path

from ..ledger import LedgerError, utcnow


def _plans(ledger):
    return Path(ledger.state_root) / 'plans'


def enforced(ledger):
    if os.environ.get('ONECREW_V2_REQUIRE_PLAN') == '1': return True
    try:
        return bool(json.loads((_plans(ledger) / 'policy.json').read_text(encoding='utf-8')).get('require_plan'))
    except (OSError, ValueError, AttributeError):
        return False


def set_enforced(ledger, on, who, reference):
    path = _plans(ledger)
    path.mkdir(parents=True, exist_ok=True)
    (path / 'policy.json').write_text(json.dumps({'require_plan': bool(on)}), encoding='utf-8')
    with (path / 'audit.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'at': utcnow(), 'require_plan': bool(on), 'by': who, 'reference': reference}, ensure_ascii=False) + '\n')
    return {'require_plan': bool(on), 'state_root': str(ledger.state_root)}


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
            plan.load(ledger, state)  # the file must still hash to what the owner approved
            return
    except LedgerError as error:
        reason = str(error)
    plans = _plans(ledger)
    plans.mkdir(parents=True, exist_ok=True)
    with (plans / 'refusals.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'id': uuid.uuid4().hex, 'at': utcnow(), 'task_id': task['id'], 'project_id': ledger.project_id,
                                 'request_key': name, 'reason': reason}, ensure_ascii=False) + '\n')
    raise LedgerError('Dispatch refused (v2): ' + reason + '.')


def sync_refusals(ledger):
    """Move spooled refusals into the ledger as dispatch.refused_no_plan events on the refused task. Idempotent."""
    spool = _plans(ledger) / 'refusals.jsonl'
    if not spool.exists(): return 0
    records = [json.loads(line) for line in spool.read_text(encoding='utf-8').splitlines() if line.strip()]
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
