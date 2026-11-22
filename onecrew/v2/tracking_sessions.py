"""Task-scoped Claude sessions on the read-only tracking server (UIMOCK: the mockup's "Phiên Claude" page).

The page goes straight to the task's session: a strip of numbers (steps, commands, edits, agent branches, failed commands, tokens, cost), the
lane chart "Claude đã làm gì" (main session, each sub-agent, background commands; a list of timed steps on a phone), Claude's self-reported
task list and the charts "Token, loại bước, suy luận". Steps come from the hook observations in the ledger; the session transcript (models,
tokens, cost, the self-reported list, reasoning summaries) is read only for the ONE session the reader picked in the session bar (never
before a pick: a private file is opened on the reader's request only). Before a pick the page shows the ledger's steps of all the task's
sessions. Without any observed session every frame stays and says "chưa quan sát".
"""
import datetime as dt
import hashlib
import json
from collections import Counter, defaultdict
from html import escape
from urllib.parse import urlencode

from ..ledger import LedgerError
from . import owner_results, report, session_transcript, tracking, tracking_dashboard
from .session_observe import SESSION_INPUT_LABELS, input_label
from .tracking_dashboard import chip, icon

KINDS = ('hook.observed', 'hook.logged', 'hook.blocked', 'hook.stop_blocked')
LABELS = {**SESSION_INPUT_LABELS, 'ai_question': 'Câu hỏi của Claude',
          'subagent_start': 'Agent bắt đầu', 'subagent_stop': 'Agent kết thúc', 'background_shell': 'Mở lệnh nền',
          'session_start': 'Mở phiên', 'session_end': 'Kết thúc phiên', 'turn_end': 'Kết thúc lượt',
          'external_artifact': 'Ghi tệp ngoài dự án',
          'hook.logged': 'Hook ghi nhận', 'hook.blocked': 'Hook đã chặn', 'hook.stop_blocked': 'Hook đã chặn dừng',
          'PreToolUse': 'Gọi công cụ', 'PostToolUse': 'Công cụ trả về', 'PostToolUseFailure': 'Công cụ báo lỗi'}
STATES = {'pending': 'Chờ', 'in_progress': 'Đang làm', 'completed': 'Đã làm'}
STATE_ICONS = {'pending': ('todo', 'idle'), 'in_progress': ('play', 'run'), 'completed': ('ok', 'ok')}
READ_TOOLS = ('Read', 'Grep', 'Glob', 'LS', 'WebFetch', 'WebSearch', 'NotebookRead')
EDIT_TOOLS = ('Write', 'Edit', 'MultiEdit', 'NotebookEdit')
SHELL_TOOLS = ('Bash', 'PowerShell')
WINDOWS = (('1h', '1 giờ', 3600), ('6h', '6 giờ', 6 * 3600), ('all', 'Cả khung', None))


def _key(session):
    return hashlib.sha256(session.encode()).hexdigest()


def _url(path, **query):
    return escape(path + '?' + urlencode(query), quote=True)


def _show(value):
    return escape(session_transcript.clean(value))


def _clock(value):
    stamp = tracking._at(value)
    return stamp.astimezone().strftime('%H:%M:%S · %d/%m/%Y') if stamp else 'Chưa rõ giờ'


def _hm(value):
    stamp = tracking._at(value)
    return stamp.astimezone().strftime('%H:%M') if stamp else '--:--'


def plan_name(selector):
    """The name the owner knows (UI58), never the ledger's namespaced selector."""
    text = str(selector or '')
    for prefix in ('plan-ns:', 'plan:'):
        if text.startswith(prefix): return text[len(prefix):]
    return text


def category(row):
    """The shape of a step on the chart: read, edit, command, check, agent, talk or other."""
    kind = row.get('observation') or row['kind']
    tool = row.get('tool') or ''
    if kind in ('background_shell',) or tool in SHELL_TOOLS: return 'cmd'
    if kind == 'external_artifact' or tool in EDIT_TOOLS: return 'edit'
    if tool in READ_TOOLS: return 'read'
    if kind in ('subagent_start', 'subagent_stop') or tool in ('Agent', 'Task'): return 'agent'
    if kind in ('owner_prompt', 'owner_choice', 'ai_question', 'turn_end') or tool == 'AskUserQuestion': return 'talk'
    if kind in ('hook.blocked', 'hook.stop_blocked'): return 'check'
    return 'other'


def lane_of(row):
    agent = row.get('agent_id') or ''
    kind = row.get('observation') or row['kind']
    if kind == 'background_shell': return 'Lệnh nền'
    return 'Agent con · ' + session_transcript.clean(agent) if agent else 'Phiên chính'


def label_of(row):
    kind = row.get('observation') or row['kind']
    label = LABELS.get(kind) or LABELS.get(row.get('hook')) or 'Sự kiện'
    if kind in SESSION_INPUT_LABELS: label = input_label(row)
    if kind == 'tool_call' and row.get('hook') == 'PostToolUseFailure': label = LABELS['PostToolUseFailure']
    return label


def _normal(event):
    row = json.loads(event['payload'])
    row.update(kind=event['kind'], time=row.get('recorded_at') or row.get('at') or event['created_at'])
    row['clock'] = _hm(row['time'])
    row['what'] = label_of(row)
    return row


def stats(rows):
    """Counts of one set of observed rows: steps (one per tool call, its before/after rows counted once), commands, edits, agent branches,
    failed tool calls."""
    steps, commands, edits, errors = set(), set(), set(), 0
    for i, r in enumerate(rows):
        ident = (r.get('agent_id'), r.get('tool_use_id')) if r.get('tool_use_id') else ('row', i)
        steps.add(ident)
        cat = category(r)
        if cat == 'cmd': commands.add(ident)
        if cat == 'edit': edits.add(ident)
        if r.get('hook') == 'PostToolUseFailure' or r['kind'] in ('hook.blocked',): errors += 1
    agents = {r.get('agent_id') for r in rows if r.get('agent_id')}
    return {'steps': len(steps), 'commands': len(commands), 'edits': len(edits), 'agents': len(agents), 'errors': errors}


def _read(state_root, selector, project_id, selected=None):
    reader, source = tracking._source(state_root)
    if source['status'] != 'ok':
        raise LedgerError(source['detail'])
    with reader.transaction() as conn:
        if conn is None:
            raise LedgerError('Sổ không mở được.')
        task = tracking._find(conn, reader, selector, project_id)
        revision = owner_results.latest_revision(conn, task['id'])
        args = (task['id'], *KINDS)
        where = (" FROM events WHERE task_id=? AND kind IN (?,?,?,?) "
                 "AND json_type(payload,'$.session')='text' AND json_extract(payload,'$.session')<>''")
        sessions = conn.execute("SELECT json_extract(payload,'$.session') AS sid, count(*) AS total, "
                                "max(seq) AS last_seq, max(created_at) AS last_at" + where
                                + " GROUP BY sid ORDER BY last_seq DESC", args).fetchall()
        sessions = [dict(r) for r in sessions]
        session = None
        if selected is not None:
            session = next((r['sid'] for r in sessions if _key(r['sid']) == selected), None)
            if session is None:
                raise LedgerError('Phiên chưa được ghi nhận cho việc này.')
        records = conn.execute('SELECT kind, payload, created_at' + where + (" AND json_extract(payload,'$.session')=?" if session else '')
                               + ' ORDER BY seq', (*args, session) if session else args).fetchall()
    rows = sorted((_normal(e) for e in records), key=lambda r: r['time'])
    return task, revision, sessions, session, rows


def observed(state_root, selector, project_id):
    """The ledger's view of a task's latest observed session (no transcript): rows, counts and time range (the overview's card)."""
    task, _revision, sessions, _session, rows = _read(state_root, selector, project_id)
    if sessions:
        latest = sessions[0]['sid']
        rows = [r for r in rows if r.get('session') == latest]
    return {'rows': rows, 'stats': stats(rows), 'last_at': rows[-1]['time'] if rows else '',
            'range': ('từ ' + _hm(rows[0]['time']) + ' đến ' + _hm(rows[-1]['time'])) if rows else ''}


# ---- drawing -----------------------------------------------------------------------------------------------------------------------------

def _ms(value):
    stamp = tracking._at(value)
    return stamp.timestamp() if stamp else None


def _glyph(cat, x, y, err=False):
    stroke = ' stroke="var(--fail)" stroke-width="2"' if err else ''
    shapes = {'read': f'<circle cx="{x:.1f}" cy="{y}" r="5" fill="var(--c-doc)"{stroke}/>',
              'edit': f'<rect x="{x - 4.5:.1f}" y="{y - 4.5}" width="9" height="9" fill="var(--c-sua)"{stroke}/>',
              'cmd': f'<path d="M{x:.1f} {y - 6}l5.5 10.5h-11z" fill="var(--c-lenh)"{stroke}/>',
              'check': f'<path d="M{x:.1f} {y - 6}l6 6-6 6-6-6z" fill="var(--c-kiem)"{stroke}/>',
              'agent': f'<path d="M{x:.1f} {y - 6}l5.2 3v6l-5.2 3-5.2-3v-6z" fill="var(--c-agent)"{stroke}/>',
              'talk': f'<path d="M{x - 6:.1f} {y - 5}h12l-6 11z" fill="var(--c-giao)"{stroke}/>',
              'other': f'<path d="M{x - 1.5:.1f} {y - 6}h3v4.5h4.5v3h-4.5v4.5h-3v-4.5h-4.5v-3h4.5z" fill="var(--c-khac)"{stroke}/>'}
    return shapes[cat]


def lanes_svg(rows, window=None):
    """The lane chart: one band per lane (main session first), a mark per step at its time, an hour axis. `window`: the last N seconds."""
    times = [t for t in (_ms(r['time']) for r in rows) if t is not None]
    if not times: return ''
    t1 = max(times)
    t0 = max(min(times), t1 - window) if window else min(times)
    if t1 - t0 < 60: t0, t1 = t0 - 30, t1 + 30
    lanes = sorted({lane_of(r) for r in rows}, key=lambda name: (name != 'Phiên chính', name == 'Lệnh nền', name))
    W, L0, R, top, lane_h = 1000, 170, 16, 26, 34
    H = top + lane_h * len(lanes) + 8
    x = lambda t: L0 + (t - t0) / (t1 - t0) * (W - L0 - R)
    g = [f'<svg class="lanes" viewBox="0 0 {W} {H}" role="img" aria-label="Các bước theo thời gian: {len(rows)} bước, {len(lanes)} làn">']
    span = t1 - t0
    step = next((s for s in (60, 300, 600, 900, 1800, 3600, 7200, 14400, 21600, 43200, 86400) if span / s <= 8), 86400)
    tick = (int(t0 // step) + 1) * step
    while tick < t1:
        g.append(f'<line class="gridl" x1="{x(tick):.1f}" x2="{x(tick):.1f}" y1="{top - 6}" y2="{H - 6}"/>'
                 f'<text x="{x(tick):.1f}" y="{top - 10}" text-anchor="middle">{dt.datetime.fromtimestamp(tick).strftime("%H:%M")}</text>')
        tick += step
    for i, lane in enumerate(lanes):
        y = top + i * lane_h + lane_h / 2
        g.append(f'<g class="lane-g"><rect class="lane-band" x="{L0 - 4}" y="{y - 11}" width="{W - L0 - R + 8}" height="22" rx="4"/>'
                 f'<text class="lname" x="4" y="{y + 4}">{escape(lane[:24] + ("…" if len(lane) > 24 else ""))}</text>')
        for r in rows:
            if lane_of(r) != lane: continue
            t = _ms(r['time'])
            if t is None or t < t0: continue
            err = r.get('hook') == 'PostToolUseFailure'
            title = escape(r['clock'] + ' ' + r['what'] + (' · ' + session_transcript.clean(r.get('tool')) if r.get('tool') else ''))
            g.append(f'<g class="ev-g"><title>{title}</title>{_glyph(category(r), x(t), y, err)}</g>')
        g.append('</g>')
    g.append('</svg>')
    return ''.join(g)


def legend_row():
    return '<ul class="legend-row">' + ''.join(f'<li>{tracking_dashboard._shape(k)}{w}</li>' for k, w in tracking_dashboard.STEP_KINDS) + '</ul>'


def step_list(rows, reading):
    """Every step, grouped by lane (main session first), with its time and, when the transcript names it, what it worked on."""
    lanes = defaultdict(list)
    for r in rows:
        agent = r.get('agent_id') or ''
        tool = _show(r.get('tool'))
        detail = (_show(r.get('text') or r.get('label') or r.get('reason'))
                  or (escape(reading.details.get((agent, r.get('tool_use_id')), '')) if reading else ''))
        title = (f'<time title="{_clock(r["time"])}">{r["clock"]}</time> {tracking_dashboard._shape(category(r))}<b>{escape(r["what"])}</b>'
                 + (f' · {tool}' if tool else ''))
        content = f'<details><summary>{title}</summary><p>{detail}</p></details>' if detail else f'<span class="st1">{title}</span>'
        lanes[lane_of(r)].append('<li>' + content + '</li>')
    return ''.join(f'<section class="lane-list"><h3>{escape(lane)}</h3><ol class="plain slist">{"".join(items)}</ol></section>'
                   for lane, items in sorted(lanes.items(), key=lambda pair: (pair[0] != 'Phiên chính', pair[0] == 'Lệnh nền', pair[0])))


def per_quarter_svg(rows):
    """Steps per 15 minutes (bars), from the observed rows."""
    times = sorted(t for t in (_ms(r['time']) for r in rows) if t is not None)
    if not times: return ''
    start = times[0] - times[0] % 900
    buckets = Counter(int((t - start) // 900) for t in times)
    n = max(buckets) + 1
    W, H, L0, B, T = 600, 150, 34, 20, 12
    top = max(buckets.values())
    bw = max(2, min(26, (W - L0 - 8) / n * .7))
    slot = (W - L0 - 8) / n
    g = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="Số bước mỗi 15 phút; cao nhất {top}">',
         f'<line class="base" x1="{L0}" x2="{W - 8}" y1="{H - B}" y2="{H - B}"/><text x="{L0 - 6}" y="{T + 4}" text-anchor="end">{top}</text>'
         f'<text x="{L0 - 6}" y="{H - B + 4}" text-anchor="end">0</text>']
    for i in range(n):
        v = buckets.get(i, 0)
        if not v: continue
        h = v / top * (H - B - T)
        g.append(f'<rect x="{L0 + i * slot + (slot - bw) / 2:.1f}" y="{H - B - h:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="1.5" fill="var(--c-doc)">'
                 f'<title>{dt.datetime.fromtimestamp(start + i * 900).strftime("%H:%M")}: {v} bước</title></rect>')
    for i in sorted({0, n // 2, n - 1}):
        g.append(f'<text x="{L0 + i * slot + slot / 2:.1f}" y="{H - 5}" text-anchor="middle">{dt.datetime.fromtimestamp(start + i * 900).strftime("%H:%M")}</text>')
    return ''.join(g) + '</svg>'


def by_kind_svg(rows):
    counts = Counter(category(r) for r in rows)
    if not counts: return ''
    top = max(counts.values())
    W, row_h = 600, 24
    H = row_h * len(tracking_dashboard.STEP_KINDS) + 4
    g = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="Số bước theo loại">']
    colors = {'read': 'c-doc', 'edit': 'c-sua', 'cmd': 'c-lenh', 'check': 'c-kiem', 'agent': 'c-agent', 'talk': 'c-giao', 'other': 'c-khac'}
    for i, (k, word) in enumerate(tracking_dashboard.STEP_KINDS):
        y = i * row_h + 4
        w = counts[k] / top * (W - 220)
        g.append(f'<text x="0" y="{y + 13}">{word}</text><rect x="110" y="{y + 3}" width="{W - 220}" height="12" rx="3" fill="var(--idle-bg)"/>'
                 f'<rect x="110" y="{y + 3}" width="{max(0, w):.1f}" height="12" rx="3" fill="var({"--" + colors[k]})"/><text x="{W - 4}" y="{y + 13}" text-anchor="end">{counts[k]}</text>')
    return ''.join(g) + '</svg>'


STYLE = r'''
main{padding:12px 16px 24px}.pc{max-width:1400px;margin:0 auto}
.range{margin:0 0 10px;font-size:13px;color:var(--ink2)}
.strip{display:flex;flex-wrap:wrap;align-items:stretch;gap:8px;margin:0 0 12px}
.swho{display:flex;flex-direction:column;justify-content:center;gap:2px;padding:4px 12px 4px 0;min-width:0}.swho b{display:flex;align-items:center;gap:6px;font-size:16px}
.swho span{font-size:12.5px;color:var(--ink2)}
.picker{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:0 0 12px;font-size:13px}
.pgrid{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:12px;align-items:start}
.ctl{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:0 0 8px}.wlabel{font-size:12.5px;color:var(--ink2);margin-left:auto}
svg.lanes{display:block;width:100%;height:auto;user-select:none}svg.lanes text{fill:var(--ink2);font-size:11px;font-family:inherit}svg.lanes .lname{font-size:12.5px;fill:var(--ink)}
.lane-band{fill:var(--band)}.gridl{stroke:var(--rule);stroke-width:1}.ev-g path,.ev-g rect,.ev-g circle{stroke:var(--sheet);stroke-width:1}
.lane-list h3{margin:10px 0 4px;font-size:13px;font-weight:600;color:var(--ink2)}
.slist li{display:block;padding:4px 2px;border-bottom:1px solid var(--rule);font-size:13.5px;min-width:0;overflow-wrap:anywhere}
.slist li:last-child{border-bottom:0}.slist summary{cursor:pointer;list-style:none}.slist summary::-webkit-details-marker{display:none}
.slist time{color:var(--ink2);font-size:12.5px;margin-right:4px}.slist .shape{vertical-align:-2px;margin-right:4px}.slist p{margin:4px 0 2px 46px;white-space:pre-wrap;color:var(--ink2)}
.steps-box{max-height:420px;overflow:auto;margin-top:8px}
.prow{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,7fr);gap:12px;margin-top:12px;align-items:start}
.steps{list-style:none;margin:0 0 10px;padding:0;display:grid;gap:6px}.steps li{display:flex;align-items:center;gap:8px;font-size:13.5px;min-width:0}
.chart{display:block;width:100%;height:auto;margin:6px 0 8px}.chart text{fill:var(--ink2);font-size:11px;font-family:inherit}.chart .base{stroke:var(--rule)}
h4.sub{margin:12px 0 6px;font-size:12.5px;font-weight:600;color:var(--ink2);display:flex;align-items:center;gap:6px}
.think{margin:0;padding:8px 10px;border-left:3px solid var(--c-agent);background:var(--idle-bg);border-radius:0 6px 6px 0;font-size:13.5px}.think p{margin:0 0 6px}
.owner-results{list-style:none;margin:0;padding:0;display:grid;gap:6px;font-size:13.5px}.owner-results small{display:block;color:var(--ink2)}
article,section.panel{overflow-wrap:anywhere}
@media (max-width:1000px){.prow{grid-template-columns:minmax(0,1fr)}}
@media (max-width:899px){.pgrid{grid-template-columns:minmax(0,1fr)}svg.lanes,.ctl .wlabel{display:none}.steps-box{max-height:none}}
@media (max-width:760px){.ntile{flex:1 1 calc(33% - 8px)}.swho{width:100%}}
@media (max-width:420px){.ntile{flex:1 1 calc(50% - 8px)}}
'''

SCRIPT = r'''
document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('[data-window]');if(!b)return;var w=b.getAttribute('data-window');
  document.querySelectorAll('[data-window]').forEach(function(x){x.setAttribute('aria-pressed',String(x===b))});
  document.querySelectorAll('[data-lanes]').forEach(function(x){x.hidden=x.getAttribute('data-lanes')!==w})});
'''


def page(state_root, selector, project_id, selected, *, comparison=True):
    task, revision, sessions, session, rows = _read(state_root, selector, project_id, selected)
    name = plan_name(task['request_key'])
    scope = dict(plan=selector, project_id=task['project_id'])
    reading = None
    if session is not None:
        rows = [r for r in rows if r.get('session') == session]
        reading = (session_transcript.read(session, rows) if comparison else
                   session_transcript.Reading(note='Bản sao sổ chỉ hiển thị sự kiện đã ghi nhận.'))
    s = stats(rows)
    empty = not rows
    first, last = (rows[0]['time'], rows[-1]['time']) if rows else (None, None)
    head = (f'<div class="vhead"><h2>Phiên Claude</h2>{tracking_dashboard.source_chip(dt.datetime.now(dt.timezone.utc), "Phiên Claude")}'
            + chip(f'{len(sessions)} phiên đã quan sát' if sessions else 'chưa quan sát phiên nào', None, 'eye')
            + f'<a class="chip t-run" href="/sessions" title="Chọn việc khác">{icon("list", "sm")}Lọc theo việc {escape(name)} ×</a></div>')
    head += (f'<p class="range">Khung giờ của {"phiên đang xem" if session else "các phiên"}: từ {_clock(first)} đến {_clock(last)}. Bước lấy từ quan sát của hook trong sổ.</p>'
             if rows else f'<p class="range">Chưa quan sát phiên Claude nào gắn với việc {escape(name)}: hook quan sát chưa ghi gì vào sổ cho việc này.</p>')
    if reading is not None and reading.note:
        head += f'<p role="status" class="empty-st">{icon("warn", "sm", "wait")}<span>{escape(reading.note.strip())}</span></p>'
    models = ', '.join(escape(m) for m in sorted(reading.models)) if reading and reading.models else ''
    tokens = sum(reading.usage.values()) if reading and reading.usage else None
    cost = None
    if reading is not None and reading.cost is not None:
        cost = f'{reading.cost:,.4f} USD' + ((' · từ ' + escape(reading.cost_since)) if reading.cost_since else ' · chưa rõ thời điểm bắt đầu')
    tile = lambda name_, value, word, bad=False: (f'<div class="ntile{" bad" if bad else ""}">{icon(name_)}<span><b>{value}</b><small>{word}</small></span></div>')
    dash = '–'
    strip = (f'<div class="swho"><b>{icon("robot")}{models or ("Chưa có model" if session else "Model: chọn một phiên")}</b>'
             f'<span>{("Số dưới đây: " + _hm(first) + " đến " + _hm(last)) if rows else "Chưa quan sát"}</span></div>'
             + tile('steps', dash if empty else s['steps'], 'bước') + tile('code', dash if empty else s['commands'], 'lệnh')
             + tile('pencil', dash if empty else s['edits'], 'sửa') + tile('robot', dash if empty else s['agents'], 'nhánh agent')
             + tile('warn', dash if empty else s['errors'], 'lệnh lỗi', bool(s['errors']))
             + tile('out', f'{tokens:,}' if tokens is not None else dash, 'token (vào, ra, đệm)')
             + tile('coin', escape(cost.split(' · ')[0]) if cost else dash, 'chi phí ước tính'))
    picker = ''
    if sessions:
        links = ''.join(f'<a href="{_url("/sessions", **scope, session=_key(r["sid"]))}"' + (' aria-current="page"' if r['sid'] == session else '')
                        + f'>{_show(r["sid"])}</a>' for r in sessions)
        picker = (f'<nav class="picker" aria-label="Chọn phiên">{icon("eye", "sm")}<span class="mut">{len(sessions)} phiên:</span><span class="segs">'
                  f'<a href="{_url("/sessions", **scope)}"' + ('' if session else ' aria-current="page"') + f'>Tất cả</a>{links}</span></nav>')
    if empty:
        did = f'<p class="empty-st">{icon("eyeoff", "sm", "idle")}<span>Chưa quan sát: không có bước nào của Claude được ghi cho việc này, nên chưa có làn phiên chính, agent con hay lệnh chạy ngầm.</span></p>'
    else:
        svgs = ''.join(f'<div data-lanes="{key}"' + ('' if key == 'all' else ' hidden') + f'>{lanes_svg(rows, window)}</div>' for key, _w, window in WINDOWS)
        did = (f'<div class="ctl"><span class="segs" role="group" aria-label="Khung giờ">'
               + ''.join(f'<button type="button" data-window="{key}" aria-pressed="{str(key == "all").lower()}">{word}</button>' for key, word, _ in WINDOWS)
               + f'</span><span class="wlabel">{_hm(first)}–{_hm(last)}, {s["steps"]} bước</span></div>{svgs}{legend_row()}'
               f'<div class="steps-box">{step_list(rows, reading)}</div>')
    timeline = (f'<section class="panel" aria-label="Dòng thời gian"><h3 class="ptitle">{icon("clock", "sm")}<span class="grow">Claude đã làm gì</span></h3>{did}</section>')
    summaries = ''.join('<p>' + escape(x) + '</p>' for x in reading.summaries) if reading else ''
    side = (f'<section class="panel side" aria-label="Tóm tắt suy luận"><h3 class="ptitle">{icon("brain", "sm")}<span class="grow">Tóm tắt suy luận</span></h3>'
            + (f'<div class="think">{summaries or "<p>Bị che · chưa có tóm tắt.</p>"}</div>' if reading else
               f'<p class="empty-st">{icon("eyeoff", "sm", "idle")}<span>{"Chưa quan sát." if empty else "Chọn một phiên để đọc tóm tắt suy luận từ nhật ký của nó."}</span></p>'))
    if revision:
        scoped_reader = report._Reader(state_root, task['project_id'], task['project_path'])
        receipts = owner_results.status(scoped_reader, task['id'], revision)
        if session is not None:
            receipts = [r for r in receipts if r['session'] == session]
        if receipts:
            side += f'<h4 class="sub">{icon("person", "sm")}Kết quả lệnh chủ</h4><ul class="owner-results">' + ''.join(
                f'<li>{_show(owner_results.LABELS[r["kind"]])} {_show(r["detail"])} · {_show(owner_results.STAGES[r["stage"]])}'
                f'<small>{_show(r["host"] or "")} {_show(r["session"] or "")}</small></li>' for r in receipts) + '</ul>'
    side += '</section>'
    if reading is not None and reading.tasks:
        items = ''.join(f'<li class="{escape(status)}">{icon(STATE_ICONS.get(status, ("question", "unknown"))[0], "sm", STATE_ICONS.get(status, ("question", "unknown"))[1])}<span>{escape(text)} · {escape(STATES.get(status, status))}</span></li>'
                        for text, status in reading.tasks)
        plan_list = f'<p class="small mut">Lần cập nhật {_clock(reading.tasks_at)}</p><ul class="steps">{items}</ul>'
    elif reading is not None:
        plan_list = f'<p class="empty-st">{icon("list", "sm", "idle")}<span>Chưa có bước tự báo trong nhật ký phiên này.</span></p>'
    else:
        plan_list = f'<p class="empty-st">{icon("eyeoff", "sm", "idle")}<span>{"Chưa quan sát: chưa có danh sách việc Claude tự báo." if empty else "Chọn một phiên để đọc danh sách việc Claude tự báo."}</span></p>'
    tasks_panel = (f'<section class="panel" aria-label="Danh sách việc Claude tự báo"><h3 class="ptitle">{icon("list", "sm")}<span class="grow">Danh sách việc</span>'
                   f'{chip("Claude tự báo", "wait")}</h3>{plan_list}</section>')
    estimate = (f'<p class="small mut">Ước tính theo nhật ký của phiên · Model: {models or "Chưa có số liệu"} · Token: {f"{tokens:,}" if tokens is not None else "Chưa có số liệu"}'
                f' (tổng vào, ra và bộ nhớ đệm) · Chi phí ước tính theo giá niêm yết: {cost or "Chưa có số liệu"}</p>' if reading is not None else '')
    charts = (f'<p class="empty-st">{icon("eyeoff", "sm", "idle")}<span>Chưa quan sát: chưa có token, loại bước hay khối suy luận để vẽ.</span></p>' if empty else
              f'{estimate}<h4 class="sub">{icon("chart", "sm")}Bước mỗi 15 phút</h4>{per_quarter_svg(rows)}<h4 class="sub">{icon("steps", "sm")}Bước theo loại</h4>{by_kind_svg(rows)}'
              + (f'<h4 class="sub">{icon("brain", "sm")}Khối suy luận</h4><p class="small">{len(reading.summaries)} tóm tắt suy luận trong nhật ký; phần suy luận gốc bị che.</p>' if reading is not None else ''))
    charts_panel = (f'<section class="panel" aria-label="Biểu đồ"><h3 class="ptitle">{icon("chart", "sm")}<span class="grow">Token, loại bước, suy luận</span></h3>{charts}</section>')
    body = (f'<div class="pc">{head}<div class="strip" aria-label="Tóm tắt phiên">{strip}</div>{picker}<div class="pgrid">{timeline}{side}</div>'
            f'<div class="prow">{tasks_panel}{charts_panel}</div></div>')
    return tracking_dashboard.document('Phiên Claude', 'sessions', body, STYLE, scope=scope, script=SCRIPT)


def picker_page(state_root, project_id=None, target='/sessions'):
    """/sessions or /direction without a task: the tasks of the ledger, those with observed sessions first, each opening its own page."""
    value = tracking._overview(state_root, project_id=project_id, reuse_seconds=tracking.REUSE_SECONDS, rhythm=True)
    value = tracking.outward(value)
    seen = value.get('session_tasks', {})
    tasks = [t for group in value['projects'] for t in group['tasks'] if t.get('selector')]
    tasks.sort(key=lambda t: (-(seen.get(t.get('id')) or 0), str((t.get('last_update') or {}).get('at') or t.get('created_at') or '')), reverse=False)
    title = 'Phiên Claude' if target == '/sessions' else 'Hướng đi'
    rows = ''.join(f'<li><a href="{_url(target, plan=t["selector"], project_id=t["project_id"])}">{icon("robot" if seen.get(t.get("id")) else "eyeoff", "sm", "run" if seen.get(t.get("id")) else "idle")}'
                   f'<span>{escape(t.get("row_title") or plan_name(t["selector"]))}</span></a> '
                   + (chip(f'{seen[t["id"]]} phiên', 'run') if seen.get(t.get('id')) else chip('chưa quan sát')) + '</li>' for t in tasks)
    body = (f'<div class="pc"><div class="vhead"><h2>{title}</h2>{tracking_dashboard.source_chip(value["generated_at"])}</div>'
            f'<p class="range">Chọn một việc. Việc có phiên Claude đã quan sát đứng trước.</p><ul class="plain picklist">{rows or "<li>Sổ chưa có việc nào.</li>"}</ul></div>')
    style = STYLE + '.picklist{display:grid;gap:6px}.picklist a{display:inline-flex;align-items:center;gap:6px;text-decoration:none}.picklist a:hover{text-decoration:underline}'
    return tracking_dashboard.document(title, 'sessions' if target == '/sessions' else 'direction', body, style)
