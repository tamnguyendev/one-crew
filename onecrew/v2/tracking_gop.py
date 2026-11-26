"""TRANGGOP: one tracking page over several ledgers of the machine (trang gộp). Read-only.

On when `track serve/open` got `--so <state root>` (repeatable) or <state root>/tracking.json holds "so", "de_xuat_tu" or
"phien_claude_thu_muc"; without any of them the page and its data are exactly as before.

  "so": [<state root> | {"path": ..., "ten": ...}]   more ledgers, opened read-only (sqlite mode=ro) like the page's own
  "de_xuat_tu": <markdown file>                      its "- " bullets are "Đề xuất chờ bạn"; the file is only read
  "phien_claude_thu_muc": [<folder>]                 Claude transcript folders the hand-over stream, the session names and the "BƯỚC:" lines
                                                     are read from; none listed = no transcript is read for them

The "Việc" strip is the open plans of the shown ledgers: no plan.accepted and no plan.closed event. Owner option gop-an-cu: a plan under an
old "plan:" anchor (the owner close command refuses it) is not in the strip; it stays in the Công việc list, marked "kiểu cũ".

A "BƯỚC: ..." line is what an agent says it is about to do: shown as unverified, never used for pass, done or progress.
"""
import datetime as dt
import hashlib
import json
import os
import re
import threading
import time
import unicodedata
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from ..ledger import LedgerError
from . import namespaces, session_observe, tracking, tracking_sessions

PORT_FILE = 'tracking.json'
KEYS = ('so', 'de_xuat_tu', 'phien_claude_thu_muc')
STEP_LABEL = 'agent tự báo, chưa xác thực'
NONE = 'chưa có dữ liệu'
OLD_WORD = 'kiểu cũ'
DELEGATION = {'Agent': 'description', 'Task': 'description', 'SendMessage': 'summary', 'mcp__ccd_session__start_session': 'title',
              'mcp__ccd_session_mgmt__send_message': 'summary'}
LINE_LIMIT = 8 * 1024 * 1024
FILES_CAP, FILE_DAYS = 60, 14          # the newest transcript files of the listed folders, none older than this
MESSAGES_CAP, STEPS_CAP, CARDS_CAP, PROPOSALS_CAP = 200, 100, 24, 100
CACHE_SECONDS = 20

# ---- masking: every text that comes from a ledger, a transcript or the owner's file ---------------------------------------------------
_TAIL = r'(?:[^\s"\'<>|*?`]|[ ](?=[^\s"\'<>|*?`]*[\\/]))*'          # a path runs on through a space when the next word has a separator
_PATH = '[đã che đường dẫn]'
_MASKS = [
    (re.compile(r'-----BEGIN[^\n]*?-----.*?(?:-----END[^\n]*?-----|\Z)', re.S), '[đã che khóa riêng]'),
    (re.compile(r'(?:ghp_|github_pat_|sk-ant-)[A-Za-z0-9_\-]*'), '[đã che khóa]'),
    (re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'), '[đã che email]'),
    (re.compile(r'(["\'`])(?:[A-Za-z]:[\\/]|%[A-Za-z_]\w*%[\\/]|\$env:[A-Za-z_]\w*[\\/]|~[\\/]|/[A-Za-z]/|[/\\]Users[/\\])[^"\'`\n]*?\1', re.I),
     r'\1' + _PATH + r'\1'),
    (re.compile(r'\b[A-Za-z]:[\\/]' + _TAIL), _PATH),
    (re.compile(r'[/\\](?:Users|home)[/\\]' + _TAIL, re.I), _PATH),
    (re.compile(r'(?<![\w/.:\\-])/[A-Za-z]/' + _TAIL), _PATH),
    (re.compile(r'%[A-Za-z_]\w*%(?:[\\/]' + _TAIL + ')?'), _PATH),
    (re.compile(r'\$env:[A-Za-z_]\w*(?:[\\/]' + _TAIL + ')?', re.I), _PATH),
    (re.compile(r'(?<![\w~])~[\\/]' + _TAIL), _PATH),
    (re.compile(r'\b[A-Za-z]--[A-Za-z0-9][A-Za-z0-9._-]*'), _PATH),                # Claude project folder names (D--...)
]
_USER_HOME = re.compile(r'[A-Za-z]:(?:\\|/)+Users(?:\\|/)+[^\\/"<>\n]+')


def mask(value, limit=400):
    """The text with secrets (the shared redaction), keys, e-mails and paths masked, cut to `limit` characters AFTER masking."""
    text = session_observe._clean(str(value or ''), 20000) or ''
    for pattern, word in _MASKS:
        text = pattern.sub(word, text)
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _no_home(value):
    """Every string of a model with a user's home folder written as "~" (the merged list carries project paths)."""
    if isinstance(value, str): return _USER_HOME.sub('~', value)
    if isinstance(value, dict): return {k: _no_home(v) for k, v in value.items()}
    if isinstance(value, list): return [_no_home(v) for v in value]
    return value


# ---- what to show ----------------------------------------------------------------------------------------------------------------------
def ledger_id(root):
    return hashlib.sha256(os.path.normcase(str(Path(root).resolve())).encode('utf-8')).hexdigest()[:10]


def _label(root):
    root = Path(root)
    return (root.parent.name or root.name) if root.name.lower() == 'state' else root.name


def read_file(state_root):
    """The dict of <state root>/tracking.json, or {} (a bad file is reported by tracking_web.default_port, not here)."""
    try:
        value = json.loads((Path(state_root) / PORT_FILE).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def settings(state_root, so=()):
    """What one request of the page shows: {active, ledgers: [{id, label, root, own, missing}], proposals: Path|None, folders: [Path]}.
    The page's own ledger is first. The file is read again on every call. Nothing is written."""
    state_root = Path(state_root).resolve()
    value = read_file(state_root)
    listed = value.get('so') if isinstance(value.get('so'), list) else []
    ledgers, seen = [], set()
    for entry, own in [(str(state_root), True)] + [(e, False) for e in [*(so or ()), *listed]]:
        name = entry.get('ten') if isinstance(entry, dict) else None
        path = entry.get('path') if isinstance(entry, dict) else entry
        if not isinstance(path, (str, os.PathLike)) or not str(path).strip():
            continue
        root = Path(path)
        root = (root if root.is_absolute() else state_root / root).resolve()
        key = ledger_id(root)
        if key in seen:
            continue
        seen.add(key)
        label = mask(name if isinstance(name, str) and name.strip() else _label(root), 60)
        ledgers.append({'id': key, 'label': label, 'root': root, 'own': own, 'missing': not (root / 'ledger.sqlite3').is_file()})
    proposals = value.get('de_xuat_tu')
    proposals = (state_root / proposals).resolve() if isinstance(proposals, str) and proposals.strip() else None
    folders = value.get('phien_claude_thu_muc')
    folders = [(state_root / f).resolve() for f in folders if isinstance(f, str) and f.strip()] if isinstance(folders, list) else []
    active = bool(so) or any(value.get(k) for k in KEYS)
    return {'active': active, 'ledgers': ledgers, 'proposals': proposals, 'folders': folders}


def ledger_root(view, key):
    """The state root of one SHOWN ledger by its id: a request can never name another folder."""
    for ledger in view['ledgers']:
        if ledger['id'] == key:
            return ledger['root']
    raise LedgerError('Sổ này không nằm trong các sổ trang đang xem.')


def _old(selector):
    text = str(selector or '')
    return text.startswith(namespaces.LEGACY) and not text.startswith(namespaces.NAMESPACED)


# ---- the ledgers, read-only -------------------------------------------------------------------------------------------------------------
def _rows(root, sql, args=()):
    reader, source = tracking._source(root)
    if source['status'] != 'ok':
        return []
    with reader.transaction() as conn:
        return [] if conn is None else [dict(r) for r in conn.execute(sql, args)]


def plans_of(ledger):
    """Every plan proposed, accepted or closed in one ledger: {plan, selector, project_id, project, done, old, title, status, at, so, label}."""
    rows = _rows(ledger['root'], "SELECT e.kind, e.payload, e.created_at, t.id AS task, t.request_key, t.project_id, t.project_path FROM events e "
                                 "JOIN tasks t ON t.id = e.task_id WHERE e.kind IN ('plan.proposed','plan.amended','plan.approved',"
                                 "'plan.accepted','plan.closed') ORDER BY e.seq")
    plans = {}
    for row in rows:
        try:
            payload = json.loads(row['payload'])
        except ValueError:
            continue
        name = payload.get('plan') if isinstance(payload, dict) else None
        if not isinstance(name, str) or not name:
            continue
        plan = plans.setdefault(row['task'], {'plan': name, 'selector': row['request_key'], 'project_id': row['project_id'],
                                              'project': Path(str(row['project_path'] or '')).name, 'done': False, 'old': _old(row['request_key']),
                                              'title': '', 'status': 'proposed', 'at': '', 'so': ledger['id'], 'label': ledger['label'],
                                              'own': ledger['own']})
        kind = row['kind'].split('.')[1]
        if kind in ('accepted', 'closed'):
            plan['done'] = True
        if not plan['done'] or kind in ('accepted', 'closed'):
            plan['status'] = {'amended': 'proposed'}.get(kind, kind)
        if isinstance(payload.get('title'), str):
            plan['title'] = mask(payload['title'], 200)
        plan['at'] = row['created_at']
    return list(plans.values())


def all_plans(view):
    out = []
    for ledger in view['ledgers']:
        try:
            out += plans_of(ledger)
        except Exception:                     # one unreadable ledger never takes the page down; it is named as unreadable
            ledger['missing'] = True
    return out


def open_plans(view, plans=None):
    return [p for p in (all_plans(view) if plans is None else plans) if not p['done']]


def strip(view, plans=None):
    """The "Việc" strip: the open plans of the shown ledgers without the old "plan:" ones (option gop-an-cu)."""
    return sorted((p for p in open_plans(view, plans) if not p['old']), key=lambda p: p['at'], reverse=True)


def overview(view, *, project_id=None, reuse_seconds=0, comparison=True):
    """tracking.overview of every shown ledger as one model; each task carries so = {id, label, own, old}. `project_id` narrows the page's own
    ledger only (`--project-only`); the others show all their projects."""
    base, projects, untracked = None, {}, {'statement': tracking.STATEMENT, 'other_tasks': [], 'registry_projects_without_plan': [], 'hook_sessions': []}
    notes = []
    for ledger in view['ledgers']:
        try:
            value = tracking.overview(ledger['root'], project_id=project_id if ledger['own'] else None, reuse_seconds=reuse_seconds,
                                      comparison=comparison)
        except Exception as error:
            notes.append(f'sổ {ledger["label"]}: không đọc được ({type(error).__name__})')
            continue
        if value['source']['status'] != 'ok':
            notes.append(f'sổ {ledger["label"]}: {value["source"]["status"]}')
        for project in value['projects']:
            for task in project['tasks']:
                task['so'] = {'id': ledger['id'], 'label': ledger['label'], 'own': ledger['own'], 'old': _old(task.get('selector'))}
            projects.setdefault(project['path'], []).extend(project['tasks'])
        if ledger['own']:
            base = value
            untracked = value.get('untracked') or untracked
    if base is None:
        base = tracking._overview_shell(view['ledgers'][0]['root'], tracking._now(None), {'ledger': '', 'status': 'unreadable', 'detail': None})
    base['projects'] = [{'path': path, 'tasks': tasks} for path, tasks in projects.items()]
    base['tasks_total'] = sum(len(p['tasks']) for p in base['projects'])
    base['untracked'] = untracked
    base['ledgers'] = [{'id': l['id'], 'label': l['label'], 'own': l['own']} for l in view['ledgers']]
    base['ledger_notes'] = notes
    return _no_home(base)


_MERGED = {}
_MERGED_LOCK = threading.Lock()


def cached_overview(view, *, project_id=None, comparison=False):
    """The merged list for the page's polls: built again only when a ledger file changed or CACHE_SECONDS passed. The list does not compare
    with the projects (hundreds of tasks); a task opened on the page is compared as before."""
    def stamp(root):
        out = []
        for name in ('ledger.sqlite3', 'ledger.sqlite3-wal'):
            try:
                s = (root / name).stat(); out.append((s.st_mtime_ns, s.st_size))
            except OSError:
                out.append(None)
        return tuple(out)
    key = (tuple((l['id'], l['label']) for l in view['ledgers']), project_id, comparison)
    state = tuple(stamp(l['root']) for l in view['ledgers'])
    with _MERGED_LOCK:
        got = _MERGED.get(key)
        if got and got[0] == state and time.monotonic() - got[1] < CACHE_SECONDS:
            return dict(got[2])
        value = overview(view, project_id=project_id, reuse_seconds=tracking.REUSE_SECONDS, comparison=comparison)
        _MERGED[key] = (state, time.monotonic(), value)
        return dict(value)


# ---- the owner's proposals file ---------------------------------------------------------------------------------------------------------
def proposals(view):
    """(the "- " bullets of the named file, a note). The file is opened for reading only."""
    path = view.get('proposals')
    if path is None:
        return [], 'Chưa chỉ định tệp đề xuất (tracking.json "de_xuat_tu").'
    try:
        text = path.read_text(encoding='utf-8-sig', errors='replace')[:400000]
    except OSError:
        return [], 'Không đọc được tệp đề xuất.'
    found = [mask(m.group(1).strip(), 500) for m in re.finditer(r'(?m)^[ \t]*[-*][ \t]+(\S.*)$', text)]
    return found[:PROPOSALS_CAP], '' if found else 'Tệp đề xuất không có gạch đầu dòng nào.'


# ---- transcripts of the listed folders ---------------------------------------------------------------------------------------------------
_FILE_CACHE = {}


def _files(view):
    """(path, session id, agent id) of the newest .jsonl files of the listed folders (main sessions and sub-agents)."""
    found = []
    oldest = time.time() - FILE_DAYS * 86400
    for folder in view['folders']:
        for pattern, sub in (('*.jsonl', False), ('*/subagents/agent-*.jsonl', True)):
            try:
                paths = list(folder.glob(pattern))
            except OSError:
                continue
            for path in paths:
                session = path.parent.parent.name if sub else path.stem
                agent = path.stem[len('agent-'):] if sub else ''
                try:
                    if path.is_symlink() or not path.resolve().is_relative_to(folder):
                        continue
                    info = path.stat()
                except OSError:
                    continue
                if info.st_mtime >= oldest:
                    found.append((info.st_mtime, info.st_size, path, session, agent))
    found.sort(key=lambda f: f[0], reverse=True)
    return found[:FILES_CAP]


def _step_text(line):
    text = unicodedata.normalize('NFC', line).strip()
    for mark in ('BƯỚC:', 'BƯỚC :'):
        if text.startswith(mark):
            return text[len(mark):].strip()
    return None


def _scan(path, session, agent):
    """One transcript file: its session title, the delegation calls it made and the "BƯỚC:" lines of its assistant text (each with the tool call
    right after it). Only these leave the function, masked; ordinary text, tool results and the owner's words are never kept."""
    title, handovers, steps, waiting = '', [], [], []
    with path.open('rb') as stream:
        while line := stream.readline(LINE_LIMIT + 1):
            if len(line) > LINE_LIMIT:
                while line and not line.endswith(b'\n'):
                    line = stream.readline(LINE_LIMIT + 1)
                continue
            if b'"assistant"' not in line and b'"custom-title"' not in line:
                continue
            try:
                row = json.loads(line)
            except (UnicodeError, ValueError, RecursionError):
                continue
            if not isinstance(row, dict):
                continue
            if row.get('type') == 'custom-title' and isinstance(row.get('customTitle'), str):
                title = mask(' '.join(row['customTitle'].split()), 120)
                continue
            message = row.get('message')
            if row.get('type') != 'assistant' or not isinstance(message, dict):
                continue
            at = str(row.get('timestamp') or '')[:40]
            blocks = message.get('content')
            for block in blocks if isinstance(blocks, list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get('type') == 'text' and isinstance(block.get('text'), str):
                    for part in block['text'].splitlines():
                        text = _step_text(part)
                        if text:
                            step = {'at': at, 'session': session, 'agent': agent, 'text': mask(text, 300), 'next': ''}
                            steps.append(step); waiting.append(step)
                elif block.get('type') == 'tool_use':
                    name = str(block.get('name') or '')
                    data = block.get('input') if isinstance(block.get('input'), dict) else {}
                    said = data.get('description') or data.get('summary') or data.get('title') or ''
                    for step in waiting:
                        step['next'] = mask(name.rsplit('__', 1)[-1] + (': ' + str(said) if said else ''), 200)
                    waiting = []
                    if name in DELEGATION:
                        label = data.get(DELEGATION[name])
                        body = next((data[k] for k in ('message', 'prompt', 'content') if isinstance(data.get(k), str) and data[k].strip()), '')
                        lines = [x.strip() for x in body.splitlines() if x.strip()][:3]
                        if name in ('Agent', 'Task'):
                            to = 'agent con ' + str(data.get('subagent_type') or 'agent')
                        elif name == 'mcp__ccd_session__start_session':
                            to = 'phiên mới'
                        else:
                            to = str(data.get('to') or data.get('session_id') or NONE)
                            to = 'phiên khác' if to.startswith(('uds:', 'local_')) else to
                        handovers.append({'at': at, 'session': session, 'agent': agent, 'tool': name, 'id': str(block.get('id') or ''),
                                          'to': mask(to, 80), 'label': mask(label, 200) if isinstance(label, str) else '',
                                          'lines': [mask(x, 200) for x in lines]})
    return {'title': title, 'handovers': handovers[-MESSAGES_CAP:], 'steps': steps[-STEPS_CAP:]}


def transcripts(view):
    """{titles: {session: name}, handovers: [...], steps: [...]} of the listed folders only; nothing at all when none is listed."""
    out = {'titles': {}, 'handovers': [], 'steps': []}
    for mtime, size, path, session, agent in _files(view):
        key = str(path)
        got = _FILE_CACHE.get(key)
        if not got or got[0] != (mtime, size):
            try:
                got = ((mtime, size), _scan(path, session, agent))
            except OSError:
                continue
            _FILE_CACHE[key] = got
        value = got[1]
        if value['title'] and not agent:
            out['titles'][session] = value['title']
        out['handovers'] += value['handovers']
        out['steps'] += value['steps']
    out['handovers'] = sorted(out['handovers'], key=lambda x: x['at'], reverse=True)[:MESSAGES_CAP]
    out['steps'] = sorted(out['steps'], key=lambda x: x['at'], reverse=True)[:STEPS_CAP]
    return out


# ---- what the ledgers observed ------------------------------------------------------------------------------------------------------------
def observed(view):
    """(sessions, delegation rows) of the hook observations of every shown ledger, newest first."""
    sessions, handovers = [], []
    marks = ','.join('?' * len(tracking_sessions.KINDS))
    for ledger in view['ledgers']:
        try:
            rows = _rows(ledger['root'], "SELECT e.kind, e.payload, e.created_at, t.request_key, t.project_id, t.project_path FROM events e "
                                         f"JOIN tasks t ON t.id = e.task_id WHERE e.kind IN ({marks}) ORDER BY e.seq DESC LIMIT 6000",
                         tracking_sessions.KINDS)
        except Exception:
            continue
        by = {}
        for row in reversed(rows):
            try:
                item = json.loads(row['payload'])
            except ValueError:
                continue
            sid = item.get('session') if isinstance(item, dict) else None
            if not isinstance(sid, str) or not sid:
                continue
            item.update(kind=row['kind'], time=item.get('recorded_at') or item.get('at') or row['created_at'])
            item['clock'] = tracking_sessions._hm(item['time']); item['what'] = tracking_sessions.label_of(item)
            entry = by.setdefault(sid, {'session': sid, 'so': ledger['id'], 'label': ledger['label'], 'own': ledger['own'], 'rows': []})
            entry['rows'].append(item)
            entry.update(selector=row['request_key'], project_id=row['project_id'], project=Path(str(row['project_path'] or '')).name,
                         last=item['time'])
            if item.get('hook') == 'PreToolUse' and item.get('tool') in DELEGATION:
                handovers.append({'at': str(item['time']), 'session': sid, 'agent': item.get('agent_id') or '', 'tool': item['tool'],
                                  'id': str(item.get('tool_use_id') or ''), 'to': NONE,
                                  'label': mask(item.get('summary'), 200) if item.get('summary') else '', 'lines': [], 'so': ledger['id']})
        sessions += by.values()
    sessions.sort(key=lambda s: str(s['last']), reverse=True)
    return sessions, handovers


def guess(message, names):
    """The task a message is about, guessed from its summary line (QSAT) or its first lines: a plan name written there as a word."""
    text = ' '.join([message.get('label') or '', *message.get('lines', [])])
    for name in names:
        if re.search(r'(?<![\w-])' + re.escape(name) + r'(?![\w-])', text):
            return name
    return None


def stream(view, plans=None):
    """The hand-over stream: the ledgers' observation rows, completed by the listed transcripts (recipient, first lines) for the same call."""
    plans = all_plans(view) if plans is None else plans
    sessions, rows = observed(view)
    read = transcripts(view)
    so_of = {s['session']: s['so'] for s in sessions}
    by_id = {(r['session'], r['id']): r for r in rows if r['id']}
    for item in read['handovers']:
        known = by_id.get((item['session'], item['id']))
        if known:
            known.update(to=item['to'], lines=item['lines'], label=item['label'] or known['label'])
        else:
            rows.append(dict(item, so=so_of.get(item['session'], '')))
    rows.sort(key=lambda r: str(r['at']), reverse=True)
    names = sorted({p['plan'] for p in plans}, key=len, reverse=True)
    for row in rows[:MESSAGES_CAP]:
        row['task'] = guess(row, names)
    return rows[:MESSAGES_CAP], sessions, read


# ---- drawing -------------------------------------------------------------------------------------------------------------------------------
def task_href(plan):
    query = {'plan': plan['selector'], 'project_id': plan['project_id']}
    if not plan['own']:
        query['so'] = plan['so']
    return '?' + urlencode(query) + '#viec'


def _session_href(entry):
    query = {'plan': entry['selector'], 'project_id': entry['project_id'], 'session': tracking_sessions._key(entry['session'])}
    if not entry['own']:
        query['so'] = entry['so']
    return '/sessions?' + urlencode(query)


def _name(session, titles):
    return titles.get(session) or 'phiên ' + mask(session, 80)[:8]


def _when(value):
    stamp = tracking._at(str(value).replace('Z', '+00:00'))
    return stamp.astimezone().strftime('%H:%M %d/%m') if stamp else NONE


def _day(value):
    stamp = tracking._at(str(value).replace('Z', '+00:00'))
    return stamp.astimezone().strftime('%d/%m/%Y') if stamp else NONE


def _state(last):
    stamp = tracking._at(str(last).replace('Z', '+00:00'))
    if not stamp:
        return 'đã kết thúc', 'idle'
    age = (dt.datetime.now(dt.timezone.utc) - stamp).total_seconds()
    return ('đang làm', 'run') if age < 120 else ('rảnh', 'wait') if age < 3600 else ('đã kết thúc', 'idle')


def _block(name, title, body, note=''):
    return (f'<section class="panel gblock" data-khoi="{name}" aria-label="{escape(title)}"><h3 class="ptitle"><span class="grow">{escape(title)}</span>'
            f'{note}</h3>{body}</section>')


def _empty(text):
    return f'<p class="empty-st"><span>{escape(text)}</span></p>'


def _lanes(sessions, titles):
    """The dev33 view of one session: numbers, lane chart. The latest observed session; token and cost stay behind its own page (a transcript
    is opened only for the session the reader picks)."""
    if not sessions:
        return _empty('Chưa quan sát phiên Claude nào trong các sổ đang xem.')
    entry = sessions[0]
    s = tracking_sessions.stats(entry['rows'])
    tiles = ''.join(f'<div class="ntile"><span><b>{value}</b><small>{word}</small></span></div>' for value, word in
                    ((s['steps'], 'bước'), (s['commands'], 'lệnh'), (s['edits'], 'sửa'), (s['agents'], 'nhánh agent'), (s['errors'], 'lệnh lỗi'),
                     ('–', 'token: mở phiên')))
    return (f'<p class="range">Phiên quan sát gần nhất: <b>{escape(_name(entry["session"], titles))}</b> · sổ {escape(entry["label"])} · '
            f'<a href="{escape(_session_href(entry))}">mở làn, số, token của phiên này</a></p><div class="strip">{tiles}</div>'
            f'<div class="gsvg">{tracking_sessions.lanes_svg(entry["rows"])}</div>{tracking_sessions.legend_row()}')


def _cards(sessions, titles):
    cards = []
    for entry in sessions[:CARDS_CAP]:
        word, tone = _state(entry['last'])
        s = tracking_sessions.stats(entry['rows'])
        last = entry['rows'][-1]
        what = last['what'] + (' · ' + mask(last.get('tool'), 60) if last.get('tool') else '')
        cards.append(f'<a class="gcard" data-so="{entry["so"]}" href="{escape(_session_href(entry))}"><b>{escape(_name(entry["session"], titles))}</b>'
                     f'<span class="chip t-{tone}">{word}</span><span class="small">{escape(what)}</span>'
                     f'<span class="small mut">{s["steps"]} bước · {s["commands"]} lệnh · {s["edits"]} sửa · {_when(entry["last"])}</span>'
                     f'<span class="small mut">{escape(mask(entry["project"], 60))} · sổ {escape(entry["label"])}</span></a>')
    return '<div class="gcards">' + ''.join(cards) + '</div>' if cards else _empty('Chưa quan sát phiên nào.')


def _flow(rows, titles, by_name):
    if not rows:
        return _empty('Chưa quan sát lần giao việc nào.')
    out, day = [], None
    for row in rows:
        if _day(row['at']) != day:
            day = _day(row['at'])
            out.append(f'<li class="gday">{day}</li>')
        sender = ('agent con của ' if row['agent'] else '') + _name(row['session'], titles)
        label = row['label'] or ' / '.join(row['lines']) or 'không có dòng tóm tắt'
        task = by_name.get(row['task']) if row.get('task') else None
        link = f' <a class="chip t-run" href="{escape(task_href(task))}">việc (đoán): {escape(task["plan"])}</a>' if task else ''
        out.append(f'<li data-so="{row.get("so", "")}"><span class="small mut">{_when(row["at"])}</span> <b>{escape(sender)}</b> → {escape(row["to"])}'
                   f'<div>{escape(label)}{link}</div></li>')
    return '<ol class="plain glist">' + ''.join(out) + '</ol>'


def _steps(steps, titles):
    if not steps:
        return _empty('Chưa có dòng BƯỚC nào (chỉ đọc nhật ký phiên của thư mục trong tracking.json "phien_claude_thu_muc").')
    out = []
    for step in steps:
        who = ('agent con của ' if step['agent'] else '') + _name(step['session'], titles)
        after = f'<div class="small mut">Lệnh ngay sau: {escape(step["next"])}</div>' if step['next'] else '<div class="small mut">Chưa thấy lệnh sau đó</div>'
        out.append(f'<li><span class="small mut">{_when(step["at"])} · {escape(who)}</span><div>BƯỚC: {escape(step["text"])} '
                   f'<span class="chip t-wait">chưa xác thực</span></div>{after}</li>')
    return f'<p class="small mut">Dòng {STEP_LABEL}: chỉ để xem, không tính đạt, xong hay tiến độ.</p><ol class="plain glist">{"".join(out)}</ol>'


def _strip(items):
    if not items:
        return _empty('Không có việc nào đang mở trong các sổ đang xem.')
    return '<div class="gstrip">' + ''.join(
        f'<a class="gtask" data-viec="{escape(p["plan"])}" data-so="{p["so"]}" href="{escape(task_href(p))}" title="{escape(p["title"] or p["plan"])}">'
        f'<b>{escape(p["plan"])}</b><span class="small mut">{escape(p["label"])} · {escape(STATUS_WORD.get(p["status"], p["status"]))}</span></a>'
        for p in items) + '</div>'


STATUS_WORD = {'proposed': 'chờ duyệt', 'approved': 'đang làm', 'accepted': 'đã nghiệm thu', 'closed': 'đã đóng'}


def switch(view):
    buttons = ''.join(f'<button type="button" data-gso="{l["id"]}" data-so="{l["id"]}" aria-pressed="false">{escape(l["label"])}'
                      + (' (không đọc được)' if l['missing'] else '') + '</button>' for l in view['ledgers'])
    return ('<nav class="gswitch" data-khoi="loc-so" aria-label="Lọc theo sổ"><span class="mut small">Sổ:</span><span class="segs">'
            f'<button type="button" data-gso="" aria-pressed="true">Tất cả</button>{buttons}</span></nav>')


def render(view):
    """(the ledger switch, the Phiên Claude section) as HTML. Block order matters to a reader of the page: the BƯỚC block is followed by the
    proposals block, and nothing from ordinary transcript text is drawn in either."""
    plans = all_plans(view)
    rows, sessions, read = stream(view, plans)
    titles = read['titles']
    by_name = {}
    for plan in sorted(plans, key=lambda p: (not p['done'], p['at'])):
        by_name[plan['plan']] = plan
    items = strip(view, plans)
    old = sum(p['old'] for p in open_plans(view, plans))
    note = f'<span class="chip">{len(items)} việc mở</span>' + (f'<span class="chip">{old} việc {OLD_WORD} ở tab Công việc</span>' if old else '')
    found, why = proposals(view)
    listed = '<ul>' + ''.join(f'<li>{escape(x)}</li>' for x in found) + '</ul>' if found else _empty(why)
    section = ('<section id="gop-phien" aria-label="Phiên Claude">'
               + _block('dai-viec', 'Việc', _strip(items), note)
               + _block('the-luoi', 'Phiên', _cards(sessions, titles))
               + _block('lan', 'Claude đã làm gì', _lanes(sessions, titles))
               + _block('luong', 'Luồng giao việc', _flow(rows, titles, by_name))
               + _block('buoc', 'Bước agent tự báo', _steps(read['steps'], titles), '<span class="chip t-wait">chưa xác thực</span>')
               + _block('de-xuat', 'Đề xuất chờ bạn', listed)
               + '</section>')
    return switch(view), section


STYLE = r'''
.gswitch{display:flex;flex-wrap:wrap;align-items:center;gap:6px;padding:6px 16px;border-bottom:1px solid var(--rule)}
#gop-phien{display:none;max-width:1400px;margin:0 auto;padding:12px 16px 24px}
body[data-gop=phien] #gop-phien{display:grid;gap:12px;grid-template-columns:minmax(0,1fr)}body[data-gop=phien] main#main{display:none}
.gblock{overflow-wrap:anywhere}.gstrip{display:flex;flex-wrap:wrap;gap:6px;max-height:190px;overflow:auto}
.gtask{display:flex;flex-direction:column;padding:5px 10px;border:1px solid var(--rule);border-radius:8px;text-decoration:none}.gtask:hover{background:var(--sel)}
.gcards{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:8px}
.gcard{display:flex;flex-direction:column;align-items:flex-start;gap:3px;padding:8px 10px;border:1px solid var(--rule);border-radius:10px;text-decoration:none;min-width:0}
.glist{max-height:460px;overflow:auto}.glist li{padding:5px 0;border-bottom:1px solid var(--rule);font-size:13.5px}.glist li.gday{font-weight:650;color:var(--ink2)}
#gop-phien .strip{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 8px}#gop-phien .range{margin:0 0 8px;font-size:13px;color:var(--ink2)}
.gsvg{overflow-x:auto}svg.lanes{display:block;width:100%;min-width:560px;height:auto}svg.lanes text{fill:var(--ink2);font-size:11px;font-family:inherit}
.lane-band{fill:var(--band)}.gridl{stroke:var(--rule);stroke-width:1}
.sotag{margin-left:4px}
[data-so-off]{display:none!important}
'''

# The work page's own script calls gopPick(t) when it filters rows; the rest is the hash view and the ledger switch.
SCRIPT = r'''
(function(){
function view(){var phien=location.hash==='#phien';document.body.setAttribute('data-gop',phien?'phien':'viec');
  var cur=phien?'sessions':'work';document.querySelectorAll('#nav [data-nav]').forEach(function(a){if(a.getAttribute('data-nav')===cur)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')})}
window.addEventListener('hashchange',view);view();
document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('[data-gso]');if(!b)return;var so=b.getAttribute('data-gso');window.gopSo=so;
  document.querySelectorAll('[data-gso]').forEach(function(x){x.setAttribute('aria-pressed',String(x===b))});
  document.querySelectorAll('#gop-phien .gcard,#gop-phien .gtask,#gop-phien .glist li[data-so]').forEach(function(x){if(so&&x.getAttribute('data-so')!==so)x.setAttribute('data-so-off','');else x.removeAttribute('data-so-off')});
  if(window.gopRender)window.gopRender()});
})();
'''
