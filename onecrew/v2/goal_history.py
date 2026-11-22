"""Revision-one goal, cited Claude session inputs, and the scope the owner is reviewing."""
import json
import re

from ..ledger import LedgerError, text_field
from . import plan
from .session_observe import SESSION_INPUT_LABELS, SESSION_SOURCE


def pin(ledger, name, words):
    plan.require_owner('owner', 'Pinning the original goal')
    text_field(words, 'goal', 2000)
    with ledger.transaction(write=True) as conn:
        state = plan.anchor_events(ledger, conn, name)
        if state.get('goal_pin'):
            if state['goal_pin']['text'] != words:
                raise LedgerError('The original goal is already pinned.')
        elif state['latest'] != 1 or state['approved'] or state['status'] != 'proposed':
            raise LedgerError('Pin the original goal on the proposed first revision.')
        else:
            plan.emit(ledger, conn, state['task_id'], 'plan.goal_pinned',
                      {'revision': 1, 'sha': state['revisions'][1]['sha'], 'text': words, 'kind': 'typed'})
    return plan._show(ledger, name)


def source(conn, state, seq):
    row = conn.execute("SELECT kind,payload FROM events WHERE seq=? AND task_id=? "
                       "AND kind IN ('hook.observed','plan.goal_pinned','plan.approved')",
                       (seq, state['task_id'])).fetchone()
    p = json.loads(row['payload']) if row else {}
    if not row or not p.get('revision') or p['revision'] not in {state['latest'], (state['approved'] or {}).get('revision')}:
        raise LedgerError('Goal source must belong to this plan and revision.')
    if any(s['seq'] == seq for r in state['revisions'].values() for s in r.get('goal_sources', [])):
        raise LedgerError('This observation already belongs to a prior amendment.')
    # D10 (S7 review, P2 new): the pinned goal and the option chosen at an approval are the ORIGINAL goal, not words asking for this change. Citing
    # them as the source of a change is refused, so they can never clear "Bản sửa chưa rõ nguồn lời chủ".
    if row['kind'] in ('plan.goal_pinned', 'plan.approved'):
        raise LedgerError('Goal source must be words asking for this change: the pinned goal and the option chosen at approval are the original goal, '
                          'already shown beside every revision; cite the session input that asked for the change.')
    # Older hook events called session inputs 'owner'. Neither spelling authenticates a person.
    if row['kind'] != 'hook.observed' or p.get('source') not in (SESSION_SOURCE, 'owner') or not p.get('text'):
        raise LedgerError('Goal source needs an eligible session input or recorded owner words.')
    result = {'seq': seq, 'text': p['text'], 'observed_revision': p['revision'], 'source': SESSION_SOURCE}
    if p.get('observation') == 'owner_prompt':
        return dict(result, kind='typed')
    if p.get('observation') == 'owner_choice' and p.get('question_id') and p.get('session'):
        rows = conn.execute("""SELECT seq,payload FROM events WHERE task_id=? AND seq<? AND kind='hook.observed'
                            AND json_extract(payload,'$.observation')='ai_question'
                            AND json_extract(payload,'$.question_id')=? ORDER BY seq DESC""",
                            (state['task_id'], seq, p['question_id']))
        for row in rows:
            q = json.loads(row['payload'])
            if (all(q.get(k) == p.get(k) for k in ('revision', 'session', 'agent_id'))
                    and q.get('source') == 'ai_claim' and p['text'] in (q.get('options') or [])):
                recommended = re.search(r'\((?:recommended|khuyến nghị)\)\s*$', p['text'], re.I)
                return dict(result, kind='picked_recommendation' if recommended else 'picked_other',
                            question=q['text'], question_seq=row['seq'], question_id=p['question_id'])
    raise LedgerError('Goal source needs a typed prompt or a recorded choice matching its AI question.')


def _scope(contract):
    return {'items': {i['id']: i['title'] for i in contract['items']},
            'owned': sorted(contract['scope']['owned'])}


def view(ledger, state, revision, contract):
    try:
        first = contract if revision == 1 else plan.load(ledger, state, 1)[0]
    except (LedgerError, OSError, ValueError) as error:
        return {'original': state.get('goal_pin'), 'unavailable': str(error)}
    baseline, current = _scope(first), _scope(contract)
    # Historical typed/picked citations were all hook observations, including those labelled owner. A citation of the pinned goal or of an approved
    # choice stored by an older release stays visible but, like every hook citation, sources no change (D10): no revision after 1 has owner words
    # OneCrew can vouch for, so each one keeps the warning.
    changes = [dict(s, revision=n, source='owner-terminal' if s['kind'] in ('pinned_goal', 'approved_choice') else SESSION_SOURCE) for n, r in sorted(state['revisions'].items())
               if n <= revision for s in r.get('goal_sources', [])]
    owner_sourced = set()
    delta = {}
    for key in ('items', 'owned'):
        before, after = set(baseline[key]), set(current[key])
        delta[key] = {'added': sorted(after - before), 'removed': sorted(before - after)}
    delta['items']['renamed'] = sorted(k for k in baseline['items'].keys() & current['items'].keys()
                                       if baseline['items'][k] != current['items'][k])
    return {'original': state.get('goal_pin') or {'kind': 'unknown', 'text': (first.get('origin') or {}).get('quote')},
            'revision_one': dict(baseline, sha=state['revisions'][1]['sha'], output=first['output'],
                                 goal=first['understanding']['restated_goal']),
            'sources': changes, 'scope': current, 'delta': delta,
            'unsourced_revisions': [n for n in sorted(state['revisions']) if 1 < n <= revision and n not in owner_sourced],
            'presentation_stale': state['revisions'][revision].get(
                'presentation_stale', baseline != current and first.get('presentation') == contract.get('presentation'))}


def lines(view):
    if view.get('unavailable'):
        return ['Chưa đối chiếu được với bản 1: ' + view['unavailable']]
    original = view['original']
    label = 'Mục tiêu gốc do chủ gõ' if original['kind'] == 'typed' else 'Mục tiêu bản 1 (nguồn chưa rõ)'
    result = [label + ': ' + (original.get('text') or 'chưa ghi')]
    if view['unsourced_revisions']:
        result.append('Bản sửa chưa rõ nguồn lời chủ: ' + ', '.join(map(str, view['unsourced_revisions'])))
    labels = {'pinned_goal': 'Mục tiêu gốc chủ đã ghim (không phải lời xin đổi)', 'approved_choice': 'Phương án chủ chọn lúc duyệt (không phải lời xin đổi)', 'typed': SESSION_INPUT_LABELS['owner_prompt'],
              'picked_recommendation': SESSION_INPUT_LABELS['owner_choice'] + ' (khuyến nghị của AI)',
              'picked_other': SESSION_INPUT_LABELS['owner_choice'] + ' (phương án khác của AI)'}
    for s in view['sources']:
        result.append(f"Bản {s['revision']} · {labels[s['kind']]} (#{s['seq']}): "
                      + (f"{s['question']} → " if 'question' in s else '') + s['text'])
    for key, label in [('items', 'Mục'), ('owned', 'Tệp trong phạm vi')]:
        diff = view['delta'][key]
        for field, word in [('added', 'thêm'), ('removed', 'bớt'), ('renamed', 'đổi tên')]:
            if diff.get(field):
                names = diff[field]
                if key == 'items':
                    titles = view['revision_one' if field == 'removed' else 'scope']['items']
                    names = [f'{n} ({titles[n]})' for n in names]
                result.append(f"{label} {word} so với bản 1: " + ', '.join(names))
    if view['presentation_stale']:
        result.append('Cần đối chiếu trước khi duyệt: phạm vi đã đổi, phần mô tả cho chủ vẫn là bản cũ.')
    return result
