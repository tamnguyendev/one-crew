"""Count the owner's actions of a program run FROM THE LEDGER (and the chat log for the one message that lives outside it), per 03 §2.4 (T39).

Routine: (1) the assignment message in chat; (2) program approval together with enforce, one script = one action; (5) the
owner-manual M5 record together with the final acceptance = one action. Non-routine: one request on the plan's anchor task per
U1–U4 card, answered by the owner with the verbatim chat message and its time. Anything else counted on the owner is a problem:
more than two routine decisions, a request that asks to approve or accept a milestone, an approve/accept by a non-owner, an
amendment caused by a task-plan edit. Decision journals and reports written by the AI are never an input here ([E16]).
"""
import json
from pathlib import Path

ROUTINE_WINDOW_SECONDS = 600
MILESTONE_GATE_WORDS = ('duyệt mốc', 'nghiệm thu mốc', 'approve milestone', 'accept milestone', 'approve-milestone', 'accept-milestone')


def _parse(stamp):
    import datetime as dt
    return dt.datetime.fromisoformat(stamp.replace('Z', '+00:00'))


def count(ledger, name, chat_log=None):
    from onecrew.v2 import plan as plans
    with ledger.transaction() as conn:
        state = plans.anchor_events(ledger, conn, name)
        task_id = state['task_id']
        rows = conn.execute('SELECT seq,kind,payload,created_at FROM events WHERE task_id=? ORDER BY seq', (task_id,)).fetchall()
    events = [dict(json.loads(r['payload']), kind=r['kind'], seq=r['seq'], at=r['created_at']) for r in rows]
    problems, owner_verbs = [], []
    approvals = [e for e in events if e['kind'] == 'plan.approved']
    accepts = [e for e in events if e['kind'] == 'plan.accepted']
    amended = [e for e in events if e['kind'] == 'plan.amended']
    manual_records = [e for e in events if e['kind'] == 'verdict.recorded' and e.get('by') == 'owner']
    for e in approvals + accepts:
        if e.get('by') != 'owner': problems.append('%s by %s is not an owner action' % (e['kind'], e.get('by')))
    audit = Path(ledger.state_root) / 'plans' / 'audit.jsonl'
    enforces = []
    if audit.is_file():
        for line in audit.read_text(encoding='utf-8').splitlines():
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if value.get('require_plan') and value.get('by') == 'owner': enforces.append(value)
    # approve + enforce inside one script window count once; a stray enforce or approve is its own action
    approve_actions = len(approvals)
    for value in enforces:
        if not any(abs((_parse(value['at']) - _parse(a['at'])).total_seconds()) <= ROUTINE_WINDOW_SECONDS for a in approvals):
            approve_actions += 1
    final_actions = len(accepts)
    for e in manual_records:
        if not any(abs((_parse(e['at']) - _parse(a['at'])).total_seconds()) <= ROUTINE_WINDOW_SECONDS for a in accepts):
            final_actions += 1
    routine = approve_actions + final_actions
    requests = ledger.requests(task_id)
    cards = []
    for req in requests:
        question = req.get('question') or req.get('payload') or {}
        if isinstance(question, str):
            try: question = json.loads(question)
            except ValueError: question = {}
        text = ' '.join(str(question.get(k, '')) for k in ('question', 'reason')).lower() + ' ' + str((question.get('action') or {}).get('type', '')).lower()
        kind = 'milestone-gate' if any(w in text for w in MILESTONE_GATE_WORDS) else 'card'
        if kind == 'milestone-gate': problems.append('request %s asks the owner to approve or accept a milestone' % req['id'])
        cards.append({'id': req['id'], 'state': req.get('state'), 'kind': kind})
    if approve_actions > 1 or final_actions > 1 or routine > 2:
        problems.append('%d routine owner decisions (%d approval, %d final); the program allows exactly one approval (approve+enforce) and one final (M5 record+accept)'
                        % (routine, approve_actions, final_actions))
    chat = {'assignments': None, 'cards': None, 'answers_matched': None}
    if chat_log is not None:
        messages = json.loads(Path(chat_log).read_text(encoding='utf-8'))
        chat['assignments'] = sum(1 for m in messages if m.get('kind') == 'assign')
        chat_cards = [m for m in messages if m.get('kind') == 'card']
        answers = [m for m in messages if m.get('kind') == 'owner-answer']
        chat['cards'] = len(chat_cards)
        matched = 0
        for req in requests:
            answer = next((e for e in events if e['kind'] == 'request.answered' and e.get('request_id') == req['id']), None)
            if answer is None: continue
            reference = str((answer.get('provenance') or {}).get('reference', ''))
            if any(m['text'] in reference and m['at'] in reference for m in answers): matched += 1
            else: problems.append('answer of %s is not the verbatim chat message with its time' % req['id'])
        chat['answers_matched'] = matched
        if chat['cards'] != len(cards): problems.append('%d cards in chat but %d requests on the anchor task' % (chat['cards'], len(cards)))
    return {'plan': name, 'anchor_task': task_id, 'routine_decisions': routine,
            'approve_actions': approve_actions, 'approvals': len(approvals), 'enforces': len(enforces),
            'final_actions': final_actions, 'manual_records': len(manual_records), 'accepts': len(accepts),
            'cards': cards, 'amended': len(amended), 'chat': chat, 'problems': problems, 'ok': not problems}


def main(argv=None):
    import argparse
    from onecrew.ledger import Ledger
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True); parser.add_argument('--state-root', required=True)
    parser.add_argument('--plan', required=True); parser.add_argument('--chat-log')
    args = parser.parse_args(argv)
    result = count(Ledger(Path(args.project), Path(args.state_root)), args.plan, args.chat_log)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
