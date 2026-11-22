"""Read-only direction history from one plan anchor (UIMOCK: the mockup's "Hướng đi" page). No transcript or model is needed.

Four number tiles (owner messages, AI questions / owner choices, direction changes, ledger traces / plan amends), the band "Phiên thấy gì,
sổ thấy gì" (stages, observed session marks, ledger marks on one time axis), then the stage cards (a letter per stage, the owner's words
verbatim labelled "lời chủ") or the turning points or every step, searchable and paged. Numbers are the ledger's; a session never observed
is said ("chưa quan sát"), never counted as zero activity."""
import datetime as dt
import itertools
import json
import re
from dataclasses import dataclass, field
from html import escape

from ..ledger import LedgerError
from . import session_observe, tracking, tracking_dashboard
from .tracking_dashboard import chip, icon, source_chip
from .tracking_sessions import _clock, _hm, _url, plan_name

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
    kind: str = ''
    obs: str = ''
    direction: bool = False
    session: str = ''
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
        entry = Entry(seq, stamp.isoformat(), phase, '', text, kind=kind, obs=obs or '', direction=bool(direction), session=str(p.get('session') or ''))
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


def totals(entries, events=()):
    """The page's four numbers, from the ledger rows the page reads (the overview reuses them)."""
    owner = sum(1 for e in entries if e.obs == 'owner_prompt' and e.label != session_observe.MACHINE_LABEL)
    asks = [e for e in entries if e.obs == 'ai_question']
    drift = sum(1 for e in entries if (e.direction and 'Chưa thấy bản sửa' in e.note) or e.obs == 'external_artifact')
    return {'owner': owner, 'asks': len(asks), 'open_asks': sum(1 for e in asks if e.status == 'Còn mở'),
            'choices': sum(1 for e in entries if e.obs == 'owner_choice'), 'turns': sum(1 for e in entries if e.direction), 'drift': drift,
            'ledger': sum(1 for e in entries if e.kind != 'hook.observed'), 'amends': sum(1 for e in entries if e.kind == 'plan.amended'),
            'sessions': len({e.session for e in entries if e.kind == 'hook.observed' and e.session})}


LETTERS = 'ABCDEFGH'


def _phases(entries):
    """Stage letters in order of first appearance; a stage met again keeps its letter."""
    order = []
    for e in entries:
        if e.phase not in order: order.append(e.phase)
    return {name: (LETTERS[i % len(LETTERS)] + ("'" * (i // len(LETTERS))), 'var(--d-' + LETTERS[i % len(LETTERS)] + ')') for i, name in enumerate(order)}


def _tag(entry, phases, small=True):
    letter, color = phases.get(entry.phase, ('?', 'var(--d-H)'))
    return f'<span class="dtag{" s" if small else ""}" style="--d:{color}" title="Giai đoạn {escape(entry.phase)}">{escape(letter)}</span>'


def _card(entry, scope, stored, phases=None):
    who = entry.obs in ('owner_prompt', 'owner_choice') and entry.label != session_observe.MACHINE_LABEL
    kind = 'k-owner' if who else 'k-ask' if entry.obs == 'ai_question' else 'k-ledger' if entry.kind != 'hook.observed' else 'k-ai'
    mark = icon('person', '', 'need') if who else icon('robot', '', 'run') if entry.obs == 'ai_question' else icon('book', '', 'ok') if entry.kind != 'hook.observed' else icon('code')
    tags = (_tag(entry, phases) if phases else '') + (chip('lời chủ', 'need', 'person') if who else chip('sổ ghi', 'ok', 'book') if entry.kind != 'hook.observed' else '')
    body = f'<div class="hwho"><time title="{_clock(entry.time)}">{_hm(entry.time)}</time>{tags}</div><h3>{escape(entry.label)}</h3>'
    if entry.text:
        body += f'<p class="words q">{escape(entry.text)}</p>'
    if entry.options:
        body += '<ul class="hopts">' + ''.join(f'<li>{escape(o)}</li>' for o in entry.options) + '</ul>'
    if entry.status:
        body += f'<strong class="hstatus">{escape(entry.status)}</strong>'
    if entry.note:
        body += f'<p class="note">{icon("flag", "sm", "fail") if "Nhắc phạm vi" in entry.note else icon("robot", "sm")}<span>{escape(entry.note)}</span></p>'
    for title, key in entry.refs:
        ref = f'{title} · <code title="{escape(key)}">{escape(key[:12])}…</code>'
        body += (f'<p class="ref"><a href="{_url("/api/evidence", **scope, key=key, format="text")}">{icon("file", "sm")}{ref}</a></p>'
                 if key in stored else f'<p class="ref">{icon("file", "sm", "idle")}{ref} · chỉ có mã trong sổ</p>')
    return f'<article id="event-{entry.seq}" class="hev {kind}"><div class="card">{mark}<div class="hbody">{body}</div></div></article>'


def _band(entries, phases):
    """Stages, observed session marks and ledger marks on one time axis (percent positions: no distortion at any width)."""
    times = [t.timestamp() for t in (tracking._at(e.time) for e in entries) if t]
    if not times:
        return '<p class="empty-st">' + icon('eyeoff', 'sm', 'idle') + '<span>Sổ chưa có bước nào của việc này.</span></p>'
    t0, t1 = min(times), max(times)
    if t1 - t0 < 60: t0, t1 = t0 - 30, t1 + 30
    pos = lambda e: ((tracking._at(e.time).timestamp() - t0) / (t1 - t0) * 100) if tracking._at(e.time) else 0
    firsts = []
    for e in entries:
        if not firsts or firsts[-1][0] != e.phase: firsts.append((e.phase, pos(e)))
    stage = ''
    for i, (name, start) in enumerate(firsts):
        end = firsts[i + 1][1] if i + 1 < len(firsts) else 100
        letter, color = phases[name]
        stage += (f'<span class="pseg" style="left:{start:.2f}%;width:{max(.8, end - start):.2f}%;--d:{color}" title="{escape(letter + " " + name)}">'
                  f'<b>{escape(letter)}</b></span>')
    observed = [e for e in entries if e.kind == 'hook.observed']
    marks = ''.join(f'<i class="mk {"m-own" if e.obs == "owner_prompt" else "m-ask" if e.obs == "ai_question" else "m-choice" if e.obs == "owner_choice" else "m-make"}"'
                    f' style="left:{pos(e):.2f}%" title="{escape(_hm(e.time) + " " + e.label)}"></i>' for e in observed)
    session = marks or '<span class="trk-empty">chưa quan sát phiên nào</span>'
    ledger = ''.join(f'<i class="mk m-ledger" style="left:{pos(e):.2f}%" title="{escape(_hm(e.time) + " " + e.label)}"></i>' for e in entries if e.kind != 'hook.observed')
    ticks = ''.join(f'<span style="left:{p:.0f}%">{dt.datetime.fromtimestamp(t0 + (t1 - t0) * p / 100).astimezone().strftime("%H:%M %d/%m")}</span>' for p in (0, 50, 100))
    legend = ''.join(f'<li><span class="swatch" style="width:14px;background:{color}"></span>{escape(letter)} {escape(name)}</li>' for name, (letter, color) in phases.items())
    return (f'<div class="band"><div class="bl">Hướng</div><div class="trk">{stage}</div><div class="bl">Phiên</div><div class="trk">{session}</div>'
            f'<div class="bl">Sổ</div><div class="trk">{ledger}</div><div></div><div class="axis">{ticks}</div></div><ul class="legend-row">{legend}</ul>')


STYLE = r"""
main{padding:12px 16px 24px}.hw{max-width:980px;margin:0 auto}
.hstrip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:0 0 12px}.hstrip .ntile small{white-space:normal}
.band{display:grid;grid-template-columns:56px minmax(0,1fr);gap:8px 8px;align-items:center;margin:8px 0}
.bl{font-size:12.5px;font-weight:600;color:var(--ink)}.trk{position:relative;height:22px;border-bottom:1px solid var(--rule)}
.pseg{position:absolute;top:3px;height:16px;border-radius:3px;background:var(--d);display:flex;align-items:center;justify-content:center;overflow:hidden}
.pseg b{font-size:11px;color:var(--ink)}.trk-empty{font-size:12.5px;color:var(--ink2)}
.mk{position:absolute;top:6px;width:10px;height:10px;margin-left:-5px;border-radius:50%;background:var(--ink)}
.mk.m-ask{border-radius:1px;transform:rotate(45deg);background:var(--run)}.mk.m-choice{border-radius:1px;transform:rotate(45deg);background:var(--ok)}
.mk.m-make{border-radius:1px;background:var(--ink2)}.mk.m-ledger{border-radius:2px;background:var(--ok)}
.axis{position:relative;height:16px;font-size:11px;color:var(--ink2)}.axis span{position:absolute;transform:translateX(-50%);white-space:nowrap}
.axis span:first-child{transform:none}.axis span:last-child{transform:translateX(-100%)}
.hctl{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;margin:0 0 10px}
.hctl form{display:flex;flex-wrap:wrap;gap:6px;align-items:center;flex:1 1 220px;margin:0}
.hctl input{min-width:0;flex:1 1 160px;max-width:300px;height:32px;padding:0 10px;border:1px solid var(--rule);border-radius:8px;background:var(--sheet)}
.hctl button{height:32px;padding:0 12px;border:1px solid var(--rule);border-radius:8px;background:var(--sheet);cursor:pointer}
.phase{margin:0 0 10px;padding:10px 14px 4px 16px;border:1px solid var(--rule);border-radius:10px;background:var(--sheet);box-shadow:inset 4px 0 0 var(--d)}
.phase>header{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:4px 10px;align-items:center}
.phase>header h2{margin:0;font-size:16px;font-weight:650;overflow-wrap:anywhere}.ptime{font-size:12.5px;color:var(--ink2);white-space:nowrap}
.trig{display:flex;align-items:flex-start;gap:6px;margin:6px 0 2px;font-size:13.5px;min-width:0}.trig .own{font-style:italic;white-space:pre-wrap;overflow-wrap:anywhere}
.pcounts{display:flex;flex-wrap:wrap;gap:2px 12px;margin:4px 0 6px;padding:0;list-style:none;color:var(--ink2);font-size:12.5px}
.pcounts li{display:inline-flex;align-items:center;gap:3px}.pcounts b{color:var(--ink)}
.hev .card{display:flex;gap:9px;align-items:flex-start;padding:7px 0 9px;border-top:1px solid var(--rule);min-width:0}.hev .card>.ic{margin-top:2px}
.hbody{min-width:0;flex:1}.hwho{font-size:12px;color:var(--ink2);display:flex;flex-wrap:wrap;gap:4px 6px;align-items:center}
.hbody h3{margin:2px 0;font-size:14px;font-weight:650}.q{margin:1px 0 0;overflow-wrap:anywhere}.words{white-space:pre-wrap}
.k-owner .q{font-style:italic}.k-owner .q::before{content:"“"}.k-owner .q::after{content:"”"}
.hopts{display:flex;flex-wrap:wrap;gap:4px;margin:5px 0 0;padding:0;list-style:none}
.hopts li{font-size:12.5px;padding:1px 8px;border:1px solid var(--rule);border-radius:999px;color:var(--ink2)}
.hstatus{display:block;font-size:13px;margin-top:4px}.note{display:flex;align-items:flex-start;gap:6px;margin:4px 0 0;font-size:13px;color:var(--ink2);white-space:pre-wrap}
.ref{display:flex;align-items:center;gap:5px;margin:4px 0 0;font-size:13px;overflow-wrap:anywhere}.ref a{display:inline-flex;align-items:center;gap:5px}
.pager{display:flex;gap:12px;align-items:center;margin:10px 0;font-size:13.5px}
@media (max-width:760px){.hstrip{grid-template-columns:repeat(2,minmax(0,1fr))}}
"""


def page(state_root, selector, project_id, query):
    task, events = _records(state_root, selector, project_id)
    entries = _entries(events)
    view = query.get('view', 'phases')
    if view not in VIEWS:
        raise LedgerError('Không có góc xem này.')
    search = _clean(query.get('q', '')).strip()
    phases = _phases(entries)
    rows = [r for r in entries if (view != 'turns' or r.turn) and r.matches(search.casefold())]
    count = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    number = query.get('page', '1')
    if not re.fullmatch(r'[1-9][0-9]{0,8}', number):
        raise LedgerError('Số trang không hợp lệ.')
    current = min(count, int(number))
    rows = rows[(current-1)*PAGE_SIZE:current*PAGE_SIZE]
    stored = tracking._stored(state_root, {k for r in rows for _, k in r.refs if len(k) == 64})
    scope = dict(plan=selector, project_id=task['project_id'])
    name = plan_name(task['request_key'])
    t = totals(entries, events)
    seen = t['sessions'] > 0
    head = (f'<div class="vhead"><h2>Hướng đi</h2>{source_chip(dt.datetime.now(dt.timezone.utc), "Sổ và phiên")}'
            + chip(f'{t["sessions"]} phiên đã quan sát' if seen else 'chưa quan sát phiên nào', None, 'eye')
            + f'<a class="chip t-run" href="/direction" title="Chọn việc khác">{icon("list", "sm")}{escape(name)}</a></div>')
    later = '' if seen else ' · chưa quan sát'
    tile = lambda name_, value, word, bad=False: (f'<div class="ntile{" bad" if bad else ""}">{icon(name_)}<span><b>{value}</b><small>{word}</small></span></div>')
    strip = (tile('person', t['owner'], 'tin chủ gõ' + later)
             + tile('robot', f'{t["asks"]} / {t["choices"]}', 'AI hỏi / chủ bấm' + (f', {t["open_asks"]} chưa trả lời' if t['open_asks'] else later), bool(t['open_asks']))
             + tile('turn', t['turns'], 'lần đổi hướng' + later)
             + tile('book', f'{t["ledger"]} / {t["amends"]}', 'dấu vết sổ / sửa plan' + (f', {t["drift"]} vượt hợp đồng' if t['drift'] else ''), bool(t['drift'])))
    band = (f'<section class="panel rail" aria-label="Phiên thấy gì, sổ thấy gì"><h3 class="ptitle">{icon("clock", "sm")}<span class="grow">Phiên thấy gì, sổ thấy gì</span>'
            f'<span class="small mut">{"giai đoạn, lời chủ và câu hỏi trong phiên, dấu vết trong sổ" if seen else "sổ ghi duyệt và kiểm; phiên chưa quan sát"}</span></h3>{_band(entries, phases)}</section>')
    links = ''.join(f'<a role="tab"' + (' aria-current="page"' if mode == view else '') + f' href="{_url("/direction", **scope, view=mode, q=search)}">{label}</a>'
                    for mode, label in VIEWS.items())
    fields = ''.join(f'<input type="hidden" name="{k}" value="{escape(v)}">' for k, v in dict(scope, view=view).items())
    ctl = (f'<div class="hctl"><nav class="segs" role="tablist" aria-label="Mức chi tiết">{links}</nav>'
           f'<form action="/direction">{fields}<input type="search" name="q" value="{escape(search)}" placeholder="Tìm trong lời chủ, câu hỏi, commit" aria-label="Tìm trong lịch sử">'
           f'<button>Tìm</button></form>'
           '<details class="info"><summary aria-label="Giải thích" title="Giải thích">i</summary><div><p>Giai đoạn: mỗi bản kế hoạch và mỗi lời đổi hướng mở một giai đoạn.'
           ' Điểm rẽ: chỉ các lời đổi hướng và câu hỏi. Tất cả bước: mọi dòng sổ và phiên đã quan sát.</p></div></details></div>')
    body = ''
    if not any(e.label in (session_observe.SESSION_INPUT_LABELS['owner_prompt'], session_observe.MACHINE_LABEL) for e in entries):
        body += f'<p class="empty-st">{icon("eyeoff", "sm", "idle")}<span>Chưa quan sát lời chủ trong phiên Claude cho việc này: thẻ dưới đây chỉ có dấu vết trong sổ.</span></p>'
    if view == 'phases':
        for phase, group in itertools.groupby(rows, key=lambda r: r.phase):
            group = list(group)
            letter, color = phases[phase]
            first_owner = next((g for g in group if g.obs == 'owner_prompt' and g.label != session_observe.MACHINE_LABEL and g.text), None)
            trig = (f'<p class="trig">{chip("lời chủ", "need", "person")}<span class="own">“{escape(first_owner.text)}”</span></p>' if first_owner else
                    f'<p class="trig">{chip("sổ ghi", "ok", "book")}<span class="clamp1">{escape(group[0].label + (" · " + group[0].text if group[0].text else ""))}</span></p>')
            c = totals(group)
            counts = (f'<ul class="pcounts"><li>{icon("person", "sm")}<b>{c["owner"]}</b> tin chủ</li><li>{icon("robot", "sm")}<b>{c["asks"]}</b> AI hỏi</li>'
                      f'<li>{icon("check", "sm")}<b>{c["choices"]}</b> chủ bấm</li><li>{icon("book", "sm")}<b>{c["ledger"]}</b> sổ</li></ul>')
            span = f'{_hm(group[0].time)}–{_hm(group[-1].time)}'
            body += (f'<section class="phase" style="--d:{color}"><header><span class="dtag" style="--d:{color}">{escape(letter)}</span><h2>{escape(phase)}</h2>'
                     f'<span class="ptime">{span}</span></header>{trig}{counts}' + ''.join(_card(r, scope, stored, phases) for r in group) + '</section>')
    else:
        body += ''.join(_card(r, scope, stored, phases) for r in rows)
    if not rows:
        body += '<p class="empty-st">Không có sự kiện phù hợp.</p>'
    body += f'<nav class="pager" aria-label="Phân trang"><span>Trang {current}/{count}</span>'
    for n, label in ((current-1, 'Trang trước'), (current+1, 'Trang sau')):
        if 1 <= n <= count:
            body += f'<a href="{_url("/direction", **scope, view=view, q=search, page=n)}">{label}</a>'
    body += '</nav>'
    content = (f'<div class="hw">{head}<section class="hstrip" aria-label="Tóm tắt">{strip}</section>{band}'
               f'<section class="panel" aria-label="Từng bước">{ctl}<div id="huong-body">{body}</div></section></div>')
    return tracking_dashboard.document('Hướng đi', 'direction', content, STYLE, scope=scope)
