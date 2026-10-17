"""Call budgets per plan item (DESIGN-MVP section 4), enforced at the reserve point of the control (Control.reserve calls
`check_operation` for every attempt, with the operation the caller built).

An attempt names the item it works on in `operation['item']`; no `item` means the call counts only against the plan's total.
Rules while the v2 gate is on:
  - a `wont` item, and a `should` item the owner did not tick at approval, never run (Q3);
  - `repair_reserve` (20% of max_calls) is kept for repairs: `should` items cannot spend it;
  - an item may use at most its share: (max_calls - repair_reserve) / number of runnable items;
  - a `must` item at its cap stops and asks the owner ONE question (spooled, then created by sync_questions, Q2);
    a `should` item at its cap just stops: the caller moves to the next item and the report says so.
The caps are derived from the plan budget; the contract has no per-item budget field yet (parking lot).
"""
import json
import math
import uuid
from pathlib import Path

from ..ledger import LedgerError, utcnow

REPAIR_RESERVE = 0.2
QUESTION_TYPES = ('v2.plan_stopped', 'v2.item_budget')   # both count against attention.questions


def runnable(contract, ticked):
    return [i for i in contract['items'] if i['tier'] == 'must' or (i['tier'] == 'should' and i['id'] in ticked)]


def shares(contract, ticked):
    """(per-item cap, repair_reserve) from the approved budget."""
    total = contract['budget']['max_calls']
    reserve = math.ceil(total * REPAIR_RESERVE)
    return max(1, (total - reserve) // max(1, len(runnable(contract, ticked)))), reserve


def judge(contract, ticked, item, used_item, used_all):
    """(reason, ask_owner) when the call must not be made, else None."""
    entry = next((i for i in contract['items'] if i['id'] == item), None)
    if entry is None: return f'item {item} is not in the approved plan', False
    if entry['tier'] == 'wont': return f'item {item} is a "wont" item of the plan; it is never worked on', False
    if entry['tier'] == 'should' and item not in ticked:
        return f'item {item} is a "should" item the owner did not tick at approval; it does not run', False
    cap, reserve = shares(contract, ticked)
    if entry['tier'] == 'should' and used_all >= contract['budget']['max_calls'] - reserve:
        return f'the remaining calls are the repair reserve ({reserve}); "should" item {item} stops and the next item starts', False
    if used_item >= cap:
        if entry['tier'] == 'must': return f'must item {item} used its {cap} calls; it stops and the owner is asked one question', True
        return f'should item {item} used its {cap} calls; it stops and the next item starts', False
    return None


def check_operation(ledger, conn, task, operation):
    """Raise LedgerError when `operation` belongs to an item that may not spend another call. Called inside Control.reserve."""
    item = operation.get('item') if isinstance(operation, dict) else None
    from . import gate, plan
    if item is None or not gate.enforced(ledger): return
    state = plan.derive(ledger, conn, task['request_key'])
    if state is None or state['status'] != 'approved': return          # require_plan has already refused (or will)
    contract, _ = plan.load(ledger, state)
    ticked = set((state['approved'] or {}).get('ticked', []))
    used_item = conn.execute("SELECT COUNT(*) FROM attempts WHERE task_id=? AND json_extract(operation,'$.item')=?", (task['id'], item)).fetchone()[0]
    row = conn.execute('SELECT used_calls+reserved_calls AS n FROM executions WHERE task_id=?', (task['id'],)).fetchone()
    verdict = judge(contract, ticked, str(item), used_item, row['n'] if row else 0)
    if verdict is None: return
    reason, ask = verdict
    extra = {'plan': task['request_key'], 'revision': state['latest'], 'item': item, 'used': used_item, 'cap': shares(contract, ticked)[0]} if ask else None
    gate.refuse(ledger, task, reason, extra)


def sync_questions(ledger):
    """Turn spooled item-budget stops into ONE question per item on the plan's anchor task (idempotent by key). Beyond
    attention.questions (shared with plan_stopped) no question is made: attention.exceeded is recorded instead."""
    from . import plan
    spool = Path(ledger.state_root) / 'plans' / 'questions.jsonl'
    if not spool.exists(): return 0
    records = []
    for line in spool.read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            record = json.loads(line)
            if record['project_id'] == ledger.project_id and all(k in record for k in ('id', 'plan', 'revision', 'item', 'used', 'cap')): records.append(record)
        except (ValueError, KeyError, TypeError):
            continue
    made = 0
    for record in records:
        with ledger.transaction() as conn:
            state = plan.derive(ledger, conn, record['plan'])
            if state is None or state['status'] != 'approved' or state['latest'] != record['revision']: continue
            anchor = state['task_id']
            contract, _ = plan.load(ledger, state)
            asked = [r for r in ledger.requests(anchor) if r['question'].get('action', {}).get('type') in QUESTION_TYPES]
        key = f'v2i-{record["plan"]}-r{record["revision"]}-{record["item"]}'[:128]
        if any(r['question']['action']['parameters'].get('key') == key for r in asked): continue
        if len(asked) >= contract['attention']['questions']:
            with ledger.transaction(write=True) as conn:
                if not conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind='attention.exceeded' AND json_extract(payload,'$.spool_id')=?", (anchor, record['id'])).fetchone():
                    plan.emit(ledger, conn, anchor, 'attention.exceeded', {'plan': record['plan'], 'limit': contract['attention']['questions'], 'item': record['item'], 'spool_id': record['id']})
            continue
        ledger.create_request(anchor, key, {
            'schema_version': 1,
            'question': f'Item {record["item"]} of plan {record["plan"]} used its {record["cap"]} calls without finishing. What now?',
            'reason': 'The per-item call budget of the approved plan was reached; the AI cannot extend it.',
            'impact': 'The item stops; its finished work is kept. Nothing more is dispatched for it until the owner amends and re-approves the plan, or ends it.',
            'options': [{'id': 'amend_plan', 'label': 'Amend the plan (more budget for this item, new approval) and continue'},
                        {'id': 'stop', 'label': 'End the task; keep the evidence'}],
            'recommendation': 'amend_plan',
            'action': {'type': 'v2.item_budget', 'parameters': {'plan': record['plan'], 'revision': record['revision'], 'item': record['item'], 'key': key}}})
        made += 1
    return made
