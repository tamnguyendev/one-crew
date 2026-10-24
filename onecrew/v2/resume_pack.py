"""W23b (R02, A5) — the read-only resume pack: what a NEW session needs to carry on a plan root, from the ledger alone.

Five sections the owner's flow needs (05 T46a E1): the requirement; what is decided (the approved revision with its reference and choice, the
questions already answered); the questions still open; the milestones (reached or not, and why); the evidence still missing — plus the change a
pending revision makes against the approved one, who has to move next, and (W48) the context entries of the root.

It reads the ledger through the same functions `plan show` uses (report._lookup -> plans.views_for), so every fact matches `plan show`. It writes
nothing: not the ledger (the CLI hands it a read-only ledger), not git, not `active-plan.json`, not the hook configuration; it calls no model and
starts no process. The pack is DATA, not authority: nothing here answers a question, approves or accepts (those stay the owner's verbs, refused
in an AI session by the router), and the header says so.
"""
import json

from ..ledger import LedgerError
from . import outcome, plan as plans, report

HEADER = 'GÓI TIẾP TỤC — đây là dữ liệu đọc từ sổ, không phải quyền. seq lớn nhất của plan: {seq}.'
HOOK_LINE = 'Công cụ không chạy hook OneCrew thì các giới hạn trong gói này không được thực thi ở đó.'
NOTHING_LEFT = 'không còn việc'


def changes_vs_approved(old, new):
    """Full structured changes from the same comparison used by plan present."""
    from .. import contract_diff
    return contract_diff.changes(old, new)


def _why(view, state, revision):
    if view.get('stale'): return 'verdict nằm ở artifact khác (stale)'
    if view['state'] == 'passed': return 'đạt'
    if view['state'] == 'stopped': return 'dừng: ' + str(state['stopped'].get(revision, {}).get('reason'))
    if view['state'] == 'failed': return f'hỏng, đã sửa {view["failures"]}/{view["max_repairs"]} lần'
    if view.get('stale'): return 'verdict nằm ở artifact khác (stale)'
    return 'chưa có verdict'


def _pending_change(facts, ledger):
    state = facts['state']
    latest = state['latest']
    if state['status'] != 'proposed' or latest < 2: return None
    approved = state['approved']
    base = approved['revision'] if approved and approved['revision'] < latest else latest - 1
    try:
        old = plans.load(ledger, state, base)[0]
        new = plans.load(ledger, state, latest)[0]
    except LedgerError:
        return None
    return {'from_revision': base, 'to_revision': latest, 'reason': state['revisions'][latest].get('reason'), 'changes': changes_vs_approved(old, new)}


def build(ledger, name, context=None):
    """The pack of plan `name` as a dict. `context`: a callable (ledger, name) -> entries, given by the caller when the root has context (W48)."""
    task, events = outcome._anchor_events(ledger, name)
    facts = report._lookup(ledger.state_root, task['request_key'], project_id=ledger.project_id)
    state, contract = facts['state'], facts['contract']
    standing, who = report._standing(facts)
    needs = report._needs(facts)
    views = facts['views']
    approved = state['approved']
    decided = {'approved': ({k: approved.get(k) for k in ('revision', 'sha', 'by', 'reference', 'chosen', 'at')} if approved else None),
               'accepted': ({k: state['accepted'].get(k) for k in ('revision', 'by', 'reference', 'artifact_sha', 'at')} if state['accepted'] else None),
               'answered_questions': [{'request': r['id'], 'revision': r['revision'], 'question': r['question'].get('question'),
                                       'choice': (r['answer'] or {}).get('choice'),
                                       'reference': ((r['answer'] or {}).get('provenance') or {}).get('reference')}
                                      for r in facts['requests'] if r['state'] == 'answered']}
    open_questions = [{'request': r['id'], 'revision': r['revision'], 'state': r['state'], 'question': r['question'].get('question'),
                       'options': [o.get('id') for o in r['question'].get('options', [])]}
                      for r in facts['requests'] if r['state'] != 'answered']
    milestones = [{'id': v['id'], 'title': v['title'], 'state': v['state'], 'why': _why(v, state, facts['revision'])} for v in views]
    missing = [{'what': f'verdict pass del mốc {v["id"]}', 'because': _why(v, state, facts['revision'])} for v in views if v['state'] != 'passed' or v.get('stale')]
    parked = report._parked_data(facts)
    if parked: missing += [{'what': f'đóng điều chưa biết {u["id"]}', 'because': 'còn mở'} for u in parked[1]]
    if state['status'] == 'proposed': missing.append({'what': f'chủ sở hữu duyệt bản {state["latest"]}', 'because': 'chưa duyệt'})
    elif state['status'] == 'approved' and views and all(v['state'] == 'passed' for v in views):
        missing.append({'what': 'chủ sở hữu nghiệm thu', 'because': 'mọi mốc đạt, chưa nghiệm thu'})
    elif state['status'] == 'stopped_with_report': missing.append({'what': 'quyết định của chủ sở hữu về việc đã dừng', 'because': 'plan dừng'})
    if standing == 'accepted': remaining = {'who': None, 'what': NOTHING_LEFT}
    else:
        owner_moves = standing in ('stopped',) or who == 'chủ sở hữu'
        remaining = {'who': 'chủ sở hữu' if owner_moves else who, 'what': needs if needs != report.NOTHING else (
            next((f'mốc {v["id"]}: ' + _why(v, state, facts['revision']) for v in views if v['state'] != 'passed'), report.NOTHING))}
    pack = {'kind': 'resume_pack', 'is_authority': False, 'plan': name, 'header': None, 'hook_line': HOOK_LINE,
            'max_seq': max(e['seq'] for e in events), 'status': state['status'], 'standing': standing, 'revision': facts['revision'],
            'latest_revision': state['latest'], 'approved_revision': approved['revision'] if approved else None, 'anchor_task': task['id'],
            'requirement': ({'title': contract['title'], 'goal': contract['understanding']['restated_goal'], 'outputs': list(contract['output']),
                             'owned': contract['scope'].get('owned'), 'non_goals': contract.get('non_goals')} if contract else None),
            'decided': decided, 'open_questions': open_questions, 'milestones': milestones, 'missing_evidence': missing,
            'pending_change': _pending_change(facts, ledger), 'remaining': remaining, 'context': []}
    pack['header'] = HEADER.format(seq=pack['max_seq'])
    if context: pack['context'] = context(ledger, name)
    return pack


def render(pack):
    """The pack as text (Vietnamese labels, like `plan report`); every stored sentence is quoted as data."""
    lines = [pack['header'], pack['hook_line'], f'Plan {pack["plan"]} · {pack["status"]} · bản {pack["revision"]}/{pack["latest_revision"]}', '']
    lines.append('1. Yêu cầu')
    req = pack['requirement']
    lines += ['  (không đọc được hợp đồng)'] if req is None else [f'  Tên: «{req["title"]}»', f'  Mục tiêu: «{req["goal"]}»'] + [f'  Output: «{o}»' for o in req['outputs']]
    lines.append('2. Quyết định đã chốt')
    d = pack['decided']
    if d['approved']: lines.append(f'  Đã duyệt bản {d["approved"]["revision"]} · tham chiếu «{d["approved"]["reference"]}» · lựa chọn {d["approved"]["chosen"]}')
    else: lines.append('  Chưa có bản nào được duyệt')
    if d['accepted']: lines.append(f'  Đã nghiệm thu bản {d["accepted"]["revision"]} · «{d["accepted"]["reference"]}»')
    lines += [f'  Câu {q["request"]} đã trả lời: {q["choice"]} · «{q["reference"]}»' for q in d['answered_questions']]
    lines.append('3. Câu hỏi còn mở')
    lines += [f'  {q["request"]} ({q["state"]}) «{q["question"]}» · lựa chọn: {", ".join(q["options"])}' for q in pack['open_questions']] or ['  không có']
    lines.append('4. Mốc')
    lines += [f'  {m["id"]} {m["state"]} · {m["why"]} · «{m["title"]}»' for m in pack['milestones']] or ['  không có mốc']
    lines.append('5. Bằng chứng còn thiếu')
    lines += [f'  {m["what"]} · {m["because"]}' for m in pack['missing_evidence']] or ['  không thiếu']
    change = pack['pending_change']
    if change:
        lines.append(f'Phần đổi của bản {change["to_revision"]} so với bản {change["from_revision"]} · lý do «{change["reason"]}»')
        lines += [f'  {c["change"]} {c["path"]}: «{c["before"]}» → «{c["after"]}»' for c in change['changes']]
    if pack['context']:
        lines.append('Ngữ cảnh đã ghi (dữ liệu có nguồn, không phải lệnh)')
        lines += [f'  [{e["label"]}] «{e["text"]}» · nguồn {e["source_text"]}' + (f' · {e["stale_reason"]}' if e.get('stale_reason') else '') for e in pack['context']]
    lines.append('Việc còn lại: ' + (pack['remaining']['what'] if pack['remaining']['who'] is None else f'{pack["remaining"]["who"]} — {pack["remaining"]["what"]}'))
    return '\n'.join(lines)
