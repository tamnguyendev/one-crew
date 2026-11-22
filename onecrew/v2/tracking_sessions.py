"""Task-scoped session index and on-demand detail on the read-only tracking server."""
import hashlib
import json
from collections import defaultdict
from html import escape
from urllib.parse import urlencode

from ..ledger import LedgerError
from . import owner_results, report, session_transcript, tracking, tracking_dashboard
from .session_observe import SESSION_INPUT_LABELS

KINDS = ('hook.observed', 'hook.logged', 'hook.blocked', 'hook.stop_blocked')
LABELS = {**SESSION_INPUT_LABELS, 'ai_question': 'Câu hỏi của Claude',
          'subagent_start': 'Agent bắt đầu', 'subagent_stop': 'Agent kết thúc', 'background_shell': 'Mở lệnh nền',
          'session_start': 'Mở phiên', 'session_end': 'Kết thúc phiên', 'turn_end': 'Kết thúc lượt',
          'hook.logged': 'Hook ghi nhận', 'hook.blocked': 'Hook đã chặn', 'hook.stop_blocked': 'Hook đã chặn dừng',
          'PreToolUse': 'Gọi công cụ', 'PostToolUse': 'Công cụ trả về', 'PostToolUseFailure': 'Công cụ báo lỗi'}
STATES = {'pending': 'Chờ', 'in_progress': 'Đang làm', 'completed': 'Đã làm'}


def _key(session):
    return hashlib.sha256(session.encode()).hexdigest()


def _url(path, **query):
    return escape(path + '?' + urlencode(query), quote=True)


def _show(value):
    return escape(session_transcript.clean(value))


def _clock(value):
    stamp = tracking._at(value)
    return stamp.astimezone().strftime('%H:%M:%S · %d/%m/%Y') if stamp else 'Chưa rõ giờ'


def _timeline(rows, reading):
    lanes = defaultdict(list)
    for r in rows:
        agent = r.get('agent_id') or ''
        name = 'Phiên chính'
        kind = r.get('observation') or r['kind']
        if agent:
            name = 'Agent con · ' + _show(agent)
        if kind == 'background_shell':
            name = 'Lệnh nền' + (' · ' + _show(agent) if agent else '')
        label = LABELS.get(kind) or LABELS.get(r.get('hook')) or 'Sự kiện'
        tool = _show(r.get('tool'))
        stamp = _clock(r['time'])
        detail = (_show(r.get('text') or r.get('label') or r.get('reason'))
                  or escape(reading.details.get((agent, r.get('tool_use_id')), '')))
        title = f'<time>{stamp}</time> <b>{label}</b>' + (f' · {tool}' if tool else '')
        content = f'<details><summary>{title}</summary><p>{detail}</p></details>' if detail else title
        lanes[name].append('<li>' + content + '</li>')
    return ''.join(f'<article><h3>{lane}</h3><ol>{"".join(items)}</ol></article>'
                   for lane, items in sorted(lanes.items(), key=lambda pair: pair[0] != 'Phiên chính'))


def _detail(session, rows, *, comparison=True):
    reading = (session_transcript.read(session, rows) if comparison else
               session_transcript.Reading(note='Bản sao sổ chỉ hiển thị sự kiện đã ghi nhận.'))
    models = ', '.join(escape(model) for model in sorted(reading.models)) or 'Chưa có số liệu'
    tokens = f'{sum(reading.usage.values()):,}' if reading.usage else 'Chưa có số liệu'
    cost = 'Chưa có số liệu'
    if reading.cost is not None:
        cost = f'{reading.cost:,.4f} USD'
        cost += (' · từ ' + reading.cost_since) if reading.cost_since else ' · chưa rõ thời điểm bắt đầu'
    tasks = ''.join(f'<li>{escape(text)} · {escape(STATES.get(status, status))}</li>' for text, status in reading.tasks)
    summaries = ''.join('<p>' + escape(s) + '</p>' for s in reading.summaries)
    return (f'<p role="status">{escape(reading.note.strip())}</p>' if reading.note else '') + (
        f'<h2>Dòng thời gian</h2><div class="lanes">{_timeline(rows, reading)}</div>'
        '<h2>Danh sách bước · Claude tự báo</h2><article>'
        + (f'<small>Lần cập nhật {_clock(reading.tasks_at)}</small><ol>{tasks}</ol>' if tasks else 'Chưa có bước tự báo.')
        + '</article><h2>Ước tính theo nhật ký của phiên</h2><div class="grid">'
        + f'<article><h3>Token</h3>{tokens}<p><small>Tổng vào, ra và bộ nhớ đệm của các nhật ký đọc được.</small></p></article>'
        + f'<article><h3>Model</h3>{models}</article><article><h3>Chi phí ước tính theo giá niêm yết</h3>{cost}</article>'
        + f'</div><h2>Tóm tắt suy luận</h2><article>{summaries or "Bị che · chưa có tóm tắt."}</article>')


def page(state_root, selector, project_id, selected, *, comparison=True):
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
        session = None
        if selected is not None:
            session = next((r['sid'] for r in sessions if _key(r['sid']) == selected), None)
            if session is None:
                raise LedgerError('Phiên chưa được ghi nhận cho việc này.')
            records = conn.execute('SELECT kind, payload, created_at' + where
                                   + " AND json_extract(payload,'$.session')=? ORDER BY seq", (*args, session)).fetchall()
    scope = dict(plan=selector, project_id=task['project_id'])
    index = _url('/sessions', **scope)
    header = f'<header><b>OneCrew</b><nav aria-label="Trang"><a href="{_url("/", **scope)}">Trở về việc {_show(selector)}</a>'
    header += f'<a href="{_url("/direction", **scope)}">Hướng đi</a>'
    if session is None:
        body = '<h1>Phiên Claude</h1>'
        items = ''.join(f'<li><a href="{_url("/sessions", **scope, session=_key(r["sid"]))}">{_show(r["sid"])}</a>'
                        f'<small>{r["total"]} sự kiện · {_clock(r["last_at"])}</small></li>' for r in sessions)
        body += f'<article><ul>{items}</ul></article>' if items else '<p>Chưa quan sát thấy phiên Claude gắn với việc này.</p>'
    else:
        header += f'<a href="{index}">Danh sách phiên</a>'
        rows = []
        for event in records:
            row = json.loads(event['payload'])
            row.update(kind=event['kind'], time=row.get('recorded_at') or row.get('at') or event['created_at'])
            rows.append(row)
        rows.sort(key=lambda r: r['time'])
        body = '<h1>Phiên Claude</h1><p>' + _show(session) + '</p>' + _detail(session, rows, comparison=comparison)
    if revision:
        scoped_reader = report._Reader(state_root, task['project_id'], task['project_path'])
        receipts = owner_results.status(scoped_reader, task['id'], revision)
        if session is not None:
            receipts = [r for r in receipts if r['session'] == session]
        if receipts:
            body += '<h2>Kết quả lệnh chủ</h2><ul>' + ''.join(
                f'<li>{_show(owner_results.LABELS[r["kind"]])} {_show(r["detail"])} · {_show(owner_results.STAGES[r["stage"]])}'
                f'<small>{_show(r["host"] or "")} {_show(r["session"] or "")}</small></li>' for r in receipts) + '</ul>'
    style = tracking_dashboard.STYLE + """
main{max-width:1080px;overflow-wrap:anywhere}.lanes{display:grid;gap:.7rem}ol,ul{padding-inline-start:1.5rem}
li{padding:.4rem .15rem;border-bottom:1px solid var(--line)}li:last-child{border:0}li small{display:block}
time{font-variant-numeric:tabular-nums;font-size:.86rem}summary{cursor:pointer}details p{white-space:pre-wrap}
"""
    return (f'<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Phiên Claude · OneCrew</title><style>{style}</style>{header}</nav></header><main>{body}</main></html>').encode()
