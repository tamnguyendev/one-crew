"""Read-only direction history from one plan anchor. No transcript or model is needed."""
import itertools
import json
import re
from dataclasses import dataclass, field
from html import escape

from ..ledger import LedgerError
from . import session_observe, tracking, tracking_dashboard
from .tracking_sessions import _clock, _url

VIEWS = {'phases': 'Giai đoạn', 'turns': 'Điểm rẽ', 'all': 'Tất cả bước'}
PAGE_SIZE = 25
OBSERVATIONS = ('owner_prompt', 'ai_question', 'owner_choice', 'external_artifact')
KINDS = ('plan.proposed', 'plan.amended', 'plan.approved', 'verdict.recorded', 'node.produced',
         'request.created', 'request.revised', 'request.answered')
# An explicit directive is a cue to compare the contract, never a scope judgment.
CHANGE = re.compile(r'^(?:(?:hãy|tôi muốn|mình muốn|please) +)?(?:đổi hướng|chuyển (?:sang|hướng)|'
                    r'thay mục tiêu|mở rộng phạm vi|change direction|switch to)\b[^.!?\n]*(?:[.!]|$)', re.I | re.M)


def _clean(value):
    return session_observe._clean(value, None) or ''


@dataclass
class Entry:
    seq: int
    time: str
    phase: str
    label: str
    text: str = ''
    turn: bool = True
    status: str = ''
    note: str = ''
    options: list = field(default_factory=list)
    refs: list = field(default_factory=list)

    def matches(self, needle):
        return any(needle in value.casefold() for value in
                   [self.label, self.text, self.phase, self.status, self.note, *self.options, *(key for _, key in self.refs)])


def _records(state_root, selector, project_id):
    reader, source = tracking._source(state_root)
    if source['status'] != 'ok':
        raise LedgerError(source['detail'])
    marks = ','.join('?' for _ in KINDS)
    observed = ','.join('?' for _ in OBSERVATIONS)
    with reader.transaction() as conn:
        if conn is None:
            raise LedgerError('Sổ không mở được.')
        task = tracking._find(conn, reader, selector, project_id)
        rows = conn.execute(f"""SELECT seq,kind,payload,created_at FROM events WHERE task_id=? AND
            (kind IN ({marks}) OR (kind='hook.observed' AND json_extract(payload,'$.observation') IN ({observed})))
            ORDER BY seq""", (task['id'], *KINDS, *OBSERVATIONS)).fetchall()
    events = []
    for row in rows:
        payload = json.loads(row['payload'])
        when = payload.get('recorded_at') or row['created_at']
        # Batched hook events can reach the ledger after a later contract revision.
        stamp = tracking._at(when) or tracking._at(row['created_at'])
        events.append((stamp, row['seq'], row['kind'], payload))
    return task, sorted(events, key=lambda e: (e[0], e[1]))


def _entries(events):
    entries, questions, requests, passed = [], {}, {}, {}
    last_amend = max(((stamp, seq) for stamp, seq, kind, _ in events if kind == 'plan.amended'), default=None)
    phase = 'Trước đề xuất'
    revision = None
    for stamp, seq, kind, p in events:
        obs = p.get('observation')
        text = _clean(p.get('text'))
        direction = obs in ('owner_prompt', 'owner_choice') and CHANGE.search(text)
        if kind in ('plan.proposed', 'plan.amended'):
            revision = p.get('revision')
            phase = f'Bản {revision}'
        elif direction:
            phase = f'Điểm rẽ #{seq}' + (f' · bản {revision}' if revision else '')
        entry = Entry(seq, stamp.isoformat(), phase, '', text)
        if kind in ('plan.proposed', 'plan.amended'):
            ai = p.get('author') in ('claude', 'codex', 'ai', 'agent', 'kiro')
            entry.label = 'Đề xuất của AI' if ai else 'Đề xuất kế hoạch'
            entry.text = _clean(p.get('title'))
            reason = _clean(p.get('reason'))
            if reason:
                entry.note = ('AI tóm tắt · ' if ai else 'Lý do sửa · ') + reason
        elif kind == 'plan.approved':
            entry.label = 'Duyệt kế hoạch'
            entry.text = f'Bản {p.get("revision")}'
        elif kind in ('node.produced', 'verdict.recorded'):
            is_check = kind == 'verdict.recorded'
            name = _clean(p.get('milestone') or p.get('node'))
            entry.label = ('Lần kiểm · ' if is_check else 'Sản phẩm · ') + name
            artifact = p.get('artifact_sha') if is_check else p.get('artifact')
            for title, key in [('Sản phẩm', artifact), ('Biên nhận', p.get('receipt'))]:
                if isinstance(key, str) and re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', key):
                    entry.refs.append((title, key))
            if is_check:
                entry.text = {'pass': 'Đạt', 'fail': 'Không đạt', 'inconclusive': 'Chưa kết luận'}.get(p.get('result'), '')
                identity = (p.get('revision'), name)
                if identity in passed and artifact and artifact != passed[identity]:
                    entry.note = 'Nhắc phạm vi · kiểm bản mã khác sau khi mốc đã đạt.'
                if p.get('result') == 'pass' and artifact:
                    passed[identity] = artifact
        elif kind in ('request.created', 'request.revised'):
            question = p.get('question') or {}
            entry.label, entry.text = 'Câu hỏi trong sổ', _clean(question.get('question'))
            labels = {o['id']: _clean(o.get('label')) for o in question.get('options', [])}
            entry.options, entry.status = list(labels.values()), 'Còn mở'
            if p['id'] in requests:
                requests[p['id']][1].status = 'Đã có bản mới'
            requests[p['id']] = (p['revision'], entry, labels)
        elif kind == 'request.answered':
            target = requests.get(p.get('request_id'))
            entry.label = 'Trả lời trong sổ'
            entry.text = _clean(p.get('choice'))
            if target and target[0] == p.get('revision'):
                entry.text = target[2].get(p.get('choice'), entry.text)
                target[1].status = 'Đã trả lời · ' + entry.text
        elif obs == 'external_artifact':
            entry.label, entry.text = 'Sản phẩm ngoài repo', _clean(p.get('label'))
            entry.note = 'Nhắc phạm vi · hook ghi nhận đích ghi ngoài thư mục dự án.'
        elif obs in ('ai_question', 'owner_choice'):
            # Missing IDs never link two events, even when the texts or options match.
            key = (p.get('session'), p.get('agent_id'), p.get('question_id'))
            if obs == 'ai_question':
                entry.label, entry.status = 'AI hỏi', 'Còn mở'
                entry.options = [_clean(o) for o in p.get('options') or [] if isinstance(o, str)]
                if key[0] and key[2]:
                    questions[key] = entry
            else:
                entry.label = session_observe.input_label(p)
                if key in questions:
                    questions[key].status = 'Đã trả lời · ' + text
                else:
                    entry.status = 'Chưa gắn với câu hỏi'
        else:
            entry.label, entry.turn = session_observe.input_label(p), bool(direction)
        if direction:
            entry.note = 'Nhắc phạm vi · phiên Claude có yêu cầu đổi hướng. Đối chiếu với bản sửa kế hoạch.'
            if last_amend is None or last_amend < (stamp, seq):
                entry.note += ' Chưa thấy bản sửa sau lời này.'
        entries.append(entry)
    return entries


def _card(entry, scope, stored):
    body = f'<time>{_clock(entry.time)}</time><h3>{escape(entry.label)}</h3>'
    if entry.text:
        body += f'<p class="words">{escape(entry.text)}</p>'
    if entry.options:
        body += '<ul>' + ''.join(f'<li>{escape(o)}</li>' for o in entry.options) + '</ul>'
    if entry.status:
        body += f'<strong>{escape(entry.status)}</strong>'
    if entry.note:
        body += f'<p class="note">{escape(entry.note)}</p>'
    for title, key in entry.refs:
        ref = f'{title} · <code>{key}</code>'
        body += (f'<p><a href="{_url("/api/evidence", **scope, key=key, format="text")}">{ref}</a></p>'
                 if key in stored else f'<p>{ref} · chỉ có mã trong sổ</p>')
    return f'<article id="event-{entry.seq}">{body}</article>'


def page(state_root, selector, project_id, query):
    task, events = _records(state_root, selector, project_id)
    entries = _entries(events)
    view = query.get('view', 'phases')
    if view not in VIEWS:
        raise LedgerError('Không có góc xem này.')
    search = _clean(query.get('q', '')).strip()
    rows = [r for r in entries if (view != 'turns' or r.turn) and r.matches(search.casefold())]
    count = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    number = query.get('page', '1')
    if not re.fullmatch(r'[1-9][0-9]{0,8}', number):
        raise LedgerError('Số trang không hợp lệ.')
    current = min(count, int(number))
    rows = rows[(current-1)*PAGE_SIZE:current*PAGE_SIZE]
    stored = tracking._stored(state_root, {k for r in rows for _, k in r.refs if len(k) == 64})
    scope = dict(plan=selector, project_id=task['project_id'])
    links = []
    for mode, label in VIEWS.items():
        active = ' aria-current="page"' if mode == view else ''
        links.append(f'<a{active} href="{_url("/direction", **scope, view=mode, q=search)}">{label}</a>')
    fields = ''.join(f'<input type="hidden" name="{k}" value="{escape(v)}">' for k, v in dict(scope, view=view).items())
    body = '<nav aria-label="Góc xem">' + ''.join(links) + '</nav>'
    body += f'<form action="/direction">{fields}<label>Tìm trong lịch sử <input type="search" name="q" value="{escape(search)}"></label> <button>Tìm</button></form>'
    if not any(e.label in (session_observe.SESSION_INPUT_LABELS['owner_prompt'], session_observe.MACHINE_LABEL) for e in entries):
        body += '<p>Chưa ghi nhận nội dung từ phiên Claude cho việc này.</p>'
    for phase, group in itertools.groupby(rows, key=lambda r: r.phase):
        if view == 'phases':
            body += f'<h2>{escape(phase)}</h2>'
        body += ''.join(_card(r, scope, stored) for r in group)
    if not rows:
        body += '<p>Không có sự kiện phù hợp.</p>'
    body += f'<nav aria-label="Phân trang"><span>Trang {current}/{count}</span>'
    for n, label in ((current-1, 'Trang trước'), (current+1, 'Trang sau')):
        if 1 <= n <= count:
            body += f'<a href="{_url("/direction", **scope, view=view, q=search, page=n)}">{label}</a>'
    style = tracking_dashboard.STYLE + """
main{max-width:52rem;overflow-wrap:anywhere}article,form{margin:.65rem 0}time{font-size:.85rem}
.words,.note{white-space:pre-wrap}.note{border-inline-start:3px solid var(--line);padding-left:.65rem}
input{max-width:100%;font:inherit}nav [aria-current]{font-weight:bold;text-decoration-thickness:3px}
"""
    return (f'<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Hướng đi · OneCrew</title><style>{style}</style><header><b>OneCrew</b><nav aria-label="Trang">'
            f'<a href="{_url("/", **scope)}">Trở về việc {escape(_clean(selector))}</a><a href="{_url("/sessions", **scope)}">Phiên Claude</a>'
            f'</nav></header><main><h1>Hướng đi</h1>{body}</nav></main></html>').encode()
