"""BG-A: let a user SEE Claude Code background work (subagents, background shell commands) under a OneCrew work item.

Read-only observation, no control. The host (Claude Code) stays the executor; OneCrew only records what the hook payloads say and shows it.
No new ledger, scheduler or engine: records are lines of `<project>/.onecrew/background.jsonl` (append-only, one writer at a time through the same lock
as violations.jsonl), and the view is derived from those lines every time, so a restart loses nothing and invents nothing.

Hook fields used (Claude Code docs, https://code.claude.com/docs/en/hooks, checked 2026-11-18 against the installed 2.1.x):
  common:           session_id, cwd, hook_event_name; agent_id / agent_type when the hook fires inside a subagent
  PostToolUse:      tool_name, tool_input {run_in_background (Bash/PowerShell/Agent)}, tool_use_id,
                    tool_response of an Agent call: status ("completed" | "async_launched"), agentId, outputFile
  SubagentStart/Stop: agent_id, agent_type (SubagentStop = "finished responding": NOT a verdict, no success/failure in it)
  Stop:             the turn of the PARENT session ended (children are not finished by it)
  SessionEnd:       reason
Everything else stays unknown: the documented hooks carry no exit code, no end signal and no task id for a background shell command, so for one
only the launch is observed. `last_assistant_message`, transcripts and tool output are never read or stored.

Identities are kept apart. HOST side: session_id, agent_id (the child itself), parent_agent_id (the agent in whose context the call ran), tool_use_id,
external_task_id (None: no documented field). ONECREW side: project, plan, revision, attempt (None: a hook payload cannot say which attempt). A child is
keyed by (session, kind, its own id), never by a name or a working directory: two sessions that reuse an id are two children.

Only stdlib: the hook runs it on the hot path.
"""
import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path

FILE = 'background.jsonl'
LOCK = 'violations.lock'
VERSION = 1
SOURCE = 'hook payload'
TRUST = 'host-reported; not independently verified'
STALE_SECONDS = 1800                  # no signal for this long: the state is unknown (silence is not a hang, and not success)
MAX_BYTES = 1_000_000                 # beyond this only state changes are kept; beyond twice this nothing
MAX_READ = 4_000_000
STATES = ('running', 'waiting', 'finished', 'unknown')
SESSION_EVENTS = ('parent_stop', 'session_start', 'session_end')      # repeat within one session; each occurrence is its own record
OUTCOMES = ('host_reported_completed', 'failed', 'unknown')
LABELS = {'running': 'đang chạy', 'waiting': 'đang chờ', 'finished': 'đã kết thúc', 'unknown': 'chưa rõ'}
OUTCOME_LABELS = {'host_reported_completed': 'host báo hoàn tất (chưa phải kết quả đã kiểm)', 'failed': 'host báo lỗi',
                  'unknown': 'chưa biết thành công hay thất bại'}
SECRET = re.compile(r'(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|authorization|bearer|credential)s?\b(\s*[=:]\s*|\s+)(?:(?:bearer|basic|token)\s+)?\S+')
LONG = re.compile(r'\b(?:sk|ghp|gho|xox[bap]|AKIA)[-_A-Za-z0-9]{12,}\b|\b[A-Za-z0-9+/_-]{40,}={0,2}')
CONTROL = re.compile(r'[\x00-\x1f\x7f]')


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def clean(text, limit=120):
    """Bounded, one-line, secret-masked text."""
    if text is None: return None
    text = CONTROL.sub(' ', str(text))
    text = LONG.sub('[đã che]', SECRET.sub(lambda m: m.group(1) + '=[đã che]', text))
    return text[:limit]


def _text(value, limit=200):
    return value[:limit] if isinstance(value, str) and value.strip() and not CONTROL.search(value) else None


def _norm(path):
    try:
        return os.path.normcase(str(Path(path).resolve()))
    except (OSError, ValueError, TypeError):
        return os.path.normcase(str(path))


def _when(text):
    try:
        value = dt.datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


# ---- payload -> records ------------------------------------------------------------------------------------------------------

def _base(event, project, plan, ev, at):
    bound = None
    if isinstance(plan, dict) and plan.get('plan'):
        bound = {'plan': plan.get('plan'), 'revision': plan.get('revision'), 'anchor': plan.get('anchor')}
    return {'v': VERSION, 'at': at or now(), 'source': SOURCE, 'trust': TRUST, 'hook': _text(event.get('hook_event_name'), 40), 'ev': ev,
            'session': _text(event.get('session_id'), 120), 'project': str(project), 'bound': bound}


def records_from(event, project, plan=None, at=None):
    """[record, ...] for one hook payload; [] when the payload says nothing about background work. A field that is missing stays None."""
    if not isinstance(event, dict): return []
    name = event.get('hook_event_name')
    own_agent, own_type = _text(event.get('agent_id'), 120), _text(event.get('agent_type'), 80)
    tool, tool_use = event.get('tool_name'), _text(event.get('tool_use_id'), 120)
    out = []

    def add(ev, **fields):
        record = _base(event, project, plan, ev, at)
        record.update(ckind=None, agent_id=None, agent_type=None, parent_agent_id=None, tool_use_id=None, external_task_id=None, status_raw=None,
                      output_ref=None, summary=None, mode=None, reason=None)
        record.update(fields)
        record['key'] = hashlib.sha256(json.dumps([record['project'], record['hook'], record['session'], record['ev'], record['ckind'], record['agent_id'], record['tool_use_id'],
                                                   record['status_raw'], record['reason'], record['parent_agent_id'],
                                                   # a parent Stop / SessionStart / SessionEnd repeats in one session (every turn, every resume) and the payload
                                                   # carries no turn id: its time is part of its identity, or only the first one of a session would ever be kept
                                                   record['at'] if ev in SESSION_EVENTS else None]).encode()).hexdigest()[:24]
        out.append(record)

    if name == 'SubagentStart' and own_agent:
        add('launched', ckind='subagent', agent_id=own_agent, agent_type=own_type, mode='unknown')
    elif name == 'SubagentStop' and own_agent:
        add('finished', ckind='subagent', agent_id=own_agent, agent_type=own_type, reason='finished responding (not a verdict)')
    elif name == 'Stop':
        add('parent_stop', parent_agent_id=own_agent)
    elif name == 'SessionEnd':
        add('session_end', reason=_text(event.get('reason'), 40))
    elif name == 'SessionStart':
        add('session_start', reason=_text(event.get('source'), 40))
    elif name in ('PostToolUse', 'PostToolUseFailure') and tool in ('Agent', 'Task'):
        response = event.get('tool_response') if isinstance(event.get('tool_response'), dict) else {}
        wanted = event.get('tool_input') if isinstance(event.get('tool_input'), dict) else {}
        child = _text(response.get('agentId'), 120)
        status = _text(response.get('status'), 40)
        summary = clean(wanted.get('description'), 100)
        if name == 'PostToolUseFailure':
            add('launch_failed', ckind='subagent', agent_id=child, tool_use_id=tool_use, parent_agent_id=own_agent, status_raw='failure', summary=summary)
        elif status == 'async_launched' or (status is None and wanted.get('run_in_background') is True):
            add('launched', ckind='subagent', agent_id=child, agent_type=_text(wanted.get('subagent_type'), 80), tool_use_id=tool_use,
                parent_agent_id=own_agent, status_raw=status, output_ref=_text(response.get('outputFile'), 300), mode='background', summary=summary)
        elif status == 'completed':
            add('finished', ckind='subagent', agent_id=child, agent_type=_text(wanted.get('subagent_type'), 80), tool_use_id=tool_use,
                parent_agent_id=own_agent, status_raw=status, mode='foreground', summary=summary, reason='the host reported the foreground call completed')
        elif status:
            add('finished', ckind='subagent', agent_id=child, tool_use_id=tool_use, parent_agent_id=own_agent, status_raw=status, summary=summary,
                reason='the host reported another status')
    elif name == 'PostToolUse' and tool in ('Bash', 'PowerShell') and isinstance(event.get('tool_input'), dict) and event['tool_input'].get('run_in_background') is True:
        if tool_use:
            add('launched', ckind='shell', tool_use_id=tool_use, parent_agent_id=own_agent, mode='background', summary=clean(event['tool_input'].get('command'), 100))
    elif name == 'PostToolUse' and own_agent:
        add('activity', ckind='subagent', agent_id=own_agent, agent_type=own_type, tool_use_id=tool_use)     # a call made INSIDE the subagent: it was alive then
    return out


# ---- the file ----------------------------------------------------------------------------------------------------------------

def path_of(project):
    return Path(project) / '.onecrew' / FILE


def _lines(path, limit=MAX_READ):
    try:
        with path.open('rb') as stream:
            size = stream.seek(0, os.SEEK_END)
            stream.seek(max(0, size - limit))
            data = stream.read().decode('utf-8', errors='replace')
    except OSError:
        return [], False
    rows = data.splitlines()
    cut = size > limit
    if cut and rows: rows = rows[1:]                    # the first line of a cut read is partial
    return rows, cut


def _parse(line):
    try:
        item = json.loads(line)
    except ValueError:
        return None
    return item if isinstance(item, dict) and isinstance(item.get('key'), str) and item.get('ev') else None


def write(project, records, locker=None):
    """Append the records that are not already in the file (by key). Returns {'written', 'duplicates', 'refused'}. A repo without .onecrew/ is left alone."""
    folder = Path(project) / '.onecrew'
    result = {'written': 0, 'duplicates': 0, 'refused': 0}
    if not folder.is_dir() or not records: return result
    path = folder / FILE
    seen = {item['key'] for item in (_parse(l) for l in _lines(path)[0]) if item}
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    from contextlib import nullcontext
    for record in records:
        if record['key'] in seen:
            result['duplicates'] += 1
            continue
        if size > 2 * MAX_BYTES or (size > MAX_BYTES and record['ev'] == 'activity'):
            result['refused'] += 1                        # bounded: a flood of activity cannot grow the file without end
            continue
        data = (json.dumps(record, ensure_ascii=False) + '\n').encode('utf-8')
        try:
            with (locker(folder / LOCK) if locker else nullcontext()):
                with path.open('ab') as stream: stream.write(data)
        except OSError:
            result['refused'] += 1
            continue
        seen.add(record['key'])
        size += len(data)
        result['written'] += 1
    return result


def note(event, project, plan=None, locker=None, at=None):
    """The hook side: derive records from one payload and append them. Never raises into the hook."""
    try:
        return write(project, records_from(event, project, plan, at), locker)
    except Exception as error:                                   # a recording problem must not stop a tool call
        return {'written': 0, 'duplicates': 0, 'refused': 0, 'error': type(error).__name__}


def load(project):
    """(records, info): the valid, de-duplicated records of this project's file, in arrival order; info counts what was not used."""
    rows, cut = _lines(path_of(project))
    seen, records, bad, dups = set(), [], 0, 0
    for line in rows:
        if not line.strip(): continue
        item = _parse(line)
        if item is None:
            bad += 1
            continue
        if item['key'] in seen:
            dups += 1
            continue
        seen.add(item['key'])
        records.append(item)
    return records, {'unreadable_lines': bad, 'duplicate_lines': dups, 'truncated_read': cut}


# ---- the view ----------------------------------------------------------------------------------------------------------------

def _child_id(record):
    if record['ckind'] == 'subagent': return record.get('agent_id') or ('tool_use:' + str(record.get('tool_use_id')))
    return record.get('tool_use_id') or '?'


def view(project, plan=None, session=None, now_time=None, stale=STALE_SECONDS):
    """What a user sees for `project` (optionally one plan, one host session): the children with their state, and what OneCrew has not observed.
    Order of arrival does not matter: every state is derived from the records' times, and an end is never undone by a late start."""
    clock = _when(now_time) or dt.datetime.now(dt.timezone.utc)
    records, info = load(project)
    here = _norm(project)
    mine, foreign = [], 0
    for record in records:
        if _norm(record.get('project')) != here:
            foreign += 1                              # a line that names another project is not shown here, whatever id it carries
            continue
        mine.append(record)
    children, sessions = {}, {}
    for record in mine:
        sid = record.get('session')
        info_s = sessions.setdefault(sid, {'parent_stops': [], 'ends': [], 'starts': []})
        if record['ev'] == 'parent_stop' and not record.get('parent_agent_id'): info_s['parent_stops'].append(record['at'])
        elif record['ev'] == 'session_end': info_s['ends'].append(record['at'])
        elif record['ev'] == 'session_start': info_s['starts'].append(record['at'])
        if not record.get('ckind'): continue
        key = (sid, record['ckind'], _child_id(record))
        children.setdefault(key, []).append(record)
    # a subagent launched by an Agent call (keyed by its tool_use_id when the response had no agentId) is not merged with one seen by its own id:
    # without a shared identifier nothing is guessed
    items = []
    for (sid, kind, cid), group in children.items():
        group.sort(key=lambda r: (r['at']))
        first = group[0]
        launches = [r for r in group if r['ev'] == 'launched']
        ends = [r for r in group if r['ev'] in ('finished', 'launch_failed')]
        gone = [r for r in group if r['ev'] == 'gone']
        activity = [r for r in group if r['ev'] in ('activity',)]
        bound = first.get('bound')                  # the binding of the FIRST observation sticks: a later plan or revision does not move a child,
        later = next((r['bound'] for r in group if r.get('bound') and r.get('bound') != bound), None)    # and a child seen outside any contract is not adopted by one
        last = max(r['at'] for r in group)
        s = sessions.get(sid, {'parent_stops': [], 'ends': [], 'starts': []})
        output = next((r['output_ref'] for r in launches if r.get('output_ref')), None)
        agent = next((r['agent_type'] for r in group if r.get('agent_type')), None)
        started = launches[0]['at'] if launches else None
        notes = []
        outcome, state, reason = 'unknown', 'running', 'host-reported: launched, no end signal'
        end = None
        if ends:
            end = ends[0] if not any(r['ev'] == 'launch_failed' for r in ends) else next(r for r in ends if r['ev'] == 'launch_failed')
            state = 'finished'
            if end['ev'] == 'launch_failed' or end.get('status_raw') in ('failed', 'error', 'failure'):
                outcome, reason = 'failed', 'the host reported the call failed'
            elif end.get('status_raw') == 'completed':
                outcome, reason = 'host_reported_completed', end.get('reason') or 'the host reported completion'
            else:
                outcome, reason = 'unknown', end.get('reason') or 'the host reported an end without an outcome'
            if any(r['at'] > end['at'] for r in activity): notes.append('activity after the end was seen (late or repeated event; kept as finished)')
            if started is None: notes.append('the start was not observed (late child)')
        else:
            session_ended = [t for t in s['ends'] if t >= last]
            stops = [t for t in s['parent_stops'] if t >= (started or first['at']) and t >= last]
            if gone:
                state, reason = 'unknown', 'the host or a probe said the task is gone: that is not success'
            elif session_ended:
                state, reason = 'unknown', 'the host session ended after the last observation: nobody can say whether it still runs'
            elif _when(last) and (clock - _when(last)).total_seconds() > stale:
                state, reason = 'unknown', f'no signal for more than {int(stale // 60)} minutes: unknown, not "hung" and not finished'
            elif stops:
                state, reason = 'waiting', 'the parent turn ended; this child was not reported finished (its end is still awaited)'
            else:
                state, reason = 'running', 'host-reported: ' + ('launched' if launches else 'activity seen') + ', no end signal'
            if kind == 'shell':
                notes.append('the hook documents no end or exit signal for a background shell command: its end cannot be observed here')
        if later: notes.append(f"later events were seen under plan {later.get('plan')} bản {later.get('revision')}; the binding stays that of the first observation")
        item = {'key': {'session': sid, 'kind': kind, 'id': cid}, 'kind': 'subagent' if kind == 'subagent' else 'background_shell',
                'host': {'session_id': sid, 'agent_id': cid if kind == 'subagent' and not str(cid).startswith('tool_use:') else None, 'agent_type': agent,
                         'external_task_id': None, 'tool_use_id': next((r['tool_use_id'] for r in group if r.get('tool_use_id')), None),
                         'launched_in_agent_id': next((r['parent_agent_id'] for r in launches if r.get('parent_agent_id')), None)},
                'onecrew': {'project': str(project), 'plan': (bound or {}).get('plan'), 'revision': (bound or {}).get('revision'),
                            'attempt': None, 'bound': bool(bound)},
                'state': state, 'state_label': LABELS[state], 'state_reason': reason, 'outcome': outcome, 'outcome_label': OUTCOME_LABELS[outcome],
                'source': SOURCE, 'trust': TRUST, 'mode': next((r['mode'] for r in launches if r.get('mode')), None), 'started_at': started,
                'last_observed': last, 'finished_at': end['at'] if end else None, 'output_ref': output,
                'output_note': 'reference reported by the host; OneCrew did not open it' if output else 'no output reference reported',
                'summary': next((r['summary'] for r in group if r.get('summary')), None), 'notes': notes, 'events': len(group)}
        item['next_step'] = _next(item)
        items.append(item)
    if plan is not None: items = [i for i in items if i['onecrew']['plan'] == plan]
    if session is not None: items = [i for i in items if i['host']['session_id'] == session]
    items.sort(key=lambda i: (i['started_at'] or i['last_observed'] or '', str(i['key']['id'])))
    counts = {s: sum(1 for i in items if i['state'] == s) for s in STATES}
    seen_hooks = sorted({r['hook'] for r in mine if r.get('hook')})
    unobserved = _unobserved(items, seen_hooks, info, foreign)
    parent_done = bool(items) and any(sessions.get(i['host']['session_id'], {}).get('parent_stops') for i in items)
    return {'kind': 'onecrew-background-view', 'version': VERSION, 'read_only': True, 'controls': 'none: observation only; OneCrew cannot start, stop, pause or resume host work',
            'project': str(project), 'plan': plan, 'session': session, 'generated_at': clock.isoformat(timespec='seconds'), 'items': items, 'counts': counts,
            'all_observed_finished': (all(i['state'] == 'finished' for i in items) if items else None),
            'parent_turn_ended': parent_done,
            'note': 'a parent turn or session ending never finishes a child; "all_observed_finished" covers only the children listed',
            'hooks_seen': seen_hooks, 'unobserved': unobserved,
            'refused': {'other_project_lines': foreign, **info}}


def _next(item):
    s = item['state']
    if s == 'finished':
        return ('đọc kết quả tại ' + item['output_ref'] + ' rồi chạy verdict; host báo hoàn tất không phải verdict' if item['output_ref']
                else 'lấy kết quả từ phiên host rồi chạy verdict; host báo hoàn tất không phải verdict hay nghiệm thu')
    if s == 'unknown': return 'hỏi phiên host hoặc chủ dự án: không coi là xong, không coi là thất bại; mở lại phiên host để thấy thêm quan sát'
    if s == 'waiting': return 'chờ tín hiệu kết thúc từ host; nếu cần, mở phiên host (OneCrew không dừng hay chạy lại giúp)'
    return 'chờ host báo kết thúc' + (' hoặc đọc output tại ' + item['output_ref'] if item['output_ref'] else '')


def _unobserved(items, seen_hooks, info, foreign):
    lines = ['kết thúc/mã thoát của lệnh shell nền: hook không có tín hiệu này',
             'việc con làm giữa lúc bắt đầu và kết thúc (chỉ thấy các lần gọi Agent/Task/Bash/PowerShell qua hook)',
             'nội dung transcript, lập luận và output của con: không đọc',
             'lệnh chạy nền do host tự chuyển (quá thời gian chờ) không có cờ run_in_background: không thấy',
             'phiên bản host trong payload: không có (chưa biết)',
             'con nào không đi qua hook (chưa cài hook nền, hoặc hook không bắt): không thấy, và "không có dòng nào" không có nghĩa là không có việc nền']
    for wanted in ('PostToolUse', 'SubagentStart', 'SubagentStop', 'Stop', 'SessionEnd'):
        if wanted not in seen_hooks: lines.append(f'chưa thấy sự kiện {wanted}: có thể hook chưa cài hoặc chưa xảy ra')
    outside = [i for i in items if not i['onecrew']['bound']]
    if outside: lines.append(f'{len(outside)} việc nền nằm ngoài mọi hợp đồng (không gắn kế hoạch nào)')
    unknown_out = [i for i in items if i['state'] == 'finished' and i['outcome'] == 'unknown']
    if unknown_out: lines.append(f'{len(unknown_out)} việc đã kết thúc nhưng chưa biết thành công hay thất bại')
    if info.get('unreadable_lines'): lines.append(f"{info['unreadable_lines']} dòng ghi nhận không đọc được (bỏ qua)")
    if info.get('truncated_read'): lines.append('tệp ghi nhận lớn hơn mức đọc: chỉ đọc phần cuối')
    if foreign: lines.append(f'{foreign} dòng thuộc project khác trong tệp này: không hiển thị')
    lines.append('gắn với node/attempt của OneCrew: hook không nói được (để trống)')
    return lines


def render(value):
    """Plain text of a view (Vietnamese)."""
    out = [f"# Việc nền của host (quan sát qua hook; chỉ đọc, không điều khiển)", f"project: {value['project']}" + (f"  kế hoạch: {value['plan']}" if value['plan'] else '')]
    counts = value['counts']
    out.append('Tổng: ' + ', '.join(f"{LABELS[s]} {counts[s]}" for s in STATES))
    if value['items']:
        out.append('Mọi việc đã quan sát đều kết thúc: ' + ('có' if value['all_observed_finished'] else 'chưa') + ' (lượt của phiên mẹ kết thúc không làm con kết thúc)')
    else:
        out.append('Chưa quan sát việc nền nào (không có nghĩa là không có).')
    for i in value['items']:
        one, host = i['onecrew'], i['host']
        out.append('')
        out.append(f"- [{i['state_label']}] {i['kind']} {host['agent_id'] or host['tool_use_id'] or '?'}" + (f" ({host['agent_type']})" if host['agent_type'] else '')
                   + (f" — {i['summary']}" if i['summary'] else ''))
        out.append(f"  thuộc: " + (f"kế hoạch {one['plan']} bản {one['revision']}" if one['bound'] else 'NGOÀI hợp đồng') + f"; phiên host {host['session_id']}; attempt: chưa rõ")
        out.append(f"  nguồn: {i['source']} ({i['trust']}); quan sát gần nhất {i['last_observed']}; bắt đầu {i['started_at'] or 'chưa quan sát'}")
        out.append(f"  vì sao: {i['state_reason']}")
        if i['state'] == 'finished': out.append(f"  kết quả: {i['outcome_label']}")
        out.append(f"  output: {i['output_ref'] or 'không có tham chiếu'}" + (f" ({i['output_note']})" if i['output_ref'] else ''))
        out.append(f"  bước tiếp: {i['next_step']}")
        out += [f"  lưu ý: {n}" for n in i['notes']]
    out += ['', 'OneCrew CHƯA quan sát / ngoài hợp đồng:'] + [f'  - {line}' for line in value['unobserved']]
    return '\n'.join(out) + '\n'


def gone_record(project, session, kind, child_id, reason, plan=None, at=None):
    """A probe (or the host) says the process of this child is no longer there. It is kept as unknown: a vanished process is not success."""
    base = _base({'hook_event_name': 'probe', 'session_id': session}, project, plan, 'gone', at)
    base.update(ckind=kind, agent_id=child_id if kind == 'subagent' else None, parent_agent_id=None, agent_type=None,
                tool_use_id=child_id if kind == 'shell' else None, external_task_id=None, status_raw=None, output_ref=None, summary=None, mode=None,
                reason=clean(reason, 100))
    base['key'] = hashlib.sha256(json.dumps([str(project), 'probe', session, 'gone', kind, child_id, base['reason']]).encode()).hexdigest()[:24]
    return base
