"""Project a selected local Claude transcript onto a few display fields, in memory only."""
import datetime as dt
import json
import math
import re
from dataclasses import dataclass, field

from . import diagnostics, install, session_observe


def clean(value):
    return session_observe._clean(value, 500) or ''


def _safe_id(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,199}', value)


@dataclass
class Reading:
    note: str = ''
    models: set = field(default_factory=set)
    usage: dict = field(default_factory=dict)
    cost: float | None = None
    cost_since: str = ''
    tasks: list = field(default_factory=list)
    tasks_at: str = ''
    summaries: list = field(default_factory=list)
    details: dict = field(default_factory=dict)


def _update_tasks(reading, inputs, stamp):
    rows = inputs.get('items', inputs.get('todos'))
    if isinstance(rows, list):
        reading.tasks = [[clean(r.get('content')), clean(r.get('status'))] for r in rows
                         if isinstance(r, dict) and isinstance(r.get('content'), str)]
    else:
        tasks = reading.tasks
        if inputs.get('advance') is True:
            active = next((i for i, r in enumerate(tasks) if r[1] == 'in_progress'), -1)
            if active >= 0:
                tasks[active][1] = 'completed'
            pending = next((r for r in tasks[active + 1:] if r[1] == 'pending'), None)
            if pending:
                pending[1] = 'in_progress'
        done = inputs.get('done')
        for index in done if isinstance(done, list) else []:
            if type(index) is int and 1 <= index <= len(tasks):
                tasks[index - 1][1] = 'completed'
        start = inputs.get('start')
        if type(start) is int and 1 <= start <= len(tasks):
            for row in tasks:
                if row[1] == 'in_progress':
                    row[1] = 'pending'
            tasks[start - 1][1] = 'in_progress'
    reading.tasks_at = stamp


def _scan(path, reading, session, agent, calls):
    """Track message IDs because Claude may repeat usage across streamed content blocks."""
    recognized = bad = 0
    pending = {}
    with path.open('rb') as stream:
        # Tool output can be very large. Skip an oversized record without materialising its payload.
        limit = 8 * 1024 * 1024
        while line := stream.readline(limit + 1):
            if len(line) > limit:
                while line and not line.endswith(b'\n'):
                    line = stream.readline(limit + 1)
                bad += 1
                continue
            try:
                row = json.loads(line)
            except (UnicodeError, ValueError, RecursionError):
                bad += 1
                continue
            if not isinstance(row, dict):
                bad += 1
                continue
            if row.get('sessionId') not in (None, session) or (not agent and row.get('isSidechain')):
                continue
            kind = row.get('type')
            if kind == 'cost-state' and not agent:
                usd = row.get('totalCostUSD')
                if type(usd) in (float, int) and 0 <= usd <= 1e12 and math.isfinite(usd):
                    reading.cost = usd
                    since = row.get('startTime')
                    reading.cost_since = (dt.datetime.fromtimestamp(since / 1000, dt.timezone.utc).date().isoformat()
                                          if type(since) in (float, int) and 0 < since < 4102444800000 else '')
                    recognized += 1
                continue
            msg = row.get('message')
            if kind not in ('assistant', 'user') or not isinstance(msg, dict):
                continue
            recognized += 1
            stamp = clean(row.get('timestamp'))
            blocks = msg.get('content')
            if kind == 'assistant':
                model = clean(msg.get('model'))
                if model:
                    reading.models.add(model)
                usage = msg.get('usage')
                key = msg.get('id') or row.get('requestId') or row.get('uuid')
                if isinstance(usage, dict) and isinstance(key, str):
                    amounts = [usage.get(k) for k in ('input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')]
                    valid = [n for n in amounts if type(n) is int and 0 <= n <= 10**15]
                    if valid:
                        reading.usage[agent, key] = sum(valid)
            for b in blocks if isinstance(blocks, list) else []:
                if not isinstance(b, dict):
                    continue
                typ = b.get('type')
                if kind == 'user' and typ == 'tool_result':
                    tid = b.get('tool_use_id')
                    update = pending.pop(tid, None) if isinstance(tid, str) else None
                    if update and not b.get('is_error'):
                        _update_tasks(reading, *update)
                if kind != 'assistant':
                    continue
                if typ in ('thinking_summary', 'reasoning_summary', 'thinking'):
                    # Only an explicitly designated summary. Never fall back to the thinking field.
                    summary = clean(b.get('summary') or (b.get('text') if typ != 'thinking' else None))
                    if summary and len(reading.summaries) < 100:
                        reading.summaries.append(summary)
                inputs, tid = b.get('input'), b.get('id')
                if typ != 'tool_use' or not isinstance(inputs, dict) or not isinstance(tid, str):
                    continue
                if (agent, tid) in calls:
                    reading.details[agent, tid] = clean(inputs.get('description') or inputs.get('file_path'))
                if not agent and b.get('name') in ('TodoWrite', 'mcp__ccd_turn__update_plan'):
                    pending[tid] = ({k: inputs[k] for k in ('todos', 'items', 'advance', 'start', 'done') if k in inputs}, stamp)
    return recognized, bad


def read(session, observed):
    reading = Reading()
    # Neither query parameters nor paths supplied by a hook are filesystem authority.
    folder = install.user_settings_file().parent / 'projects'
    calls = {(r.get('agent_id') or '', r['tool_use_id']) for r in observed if isinstance(r.get('tool_use_id'), str)}
    try:
        paths = []
        if _safe_id(session) and not diagnostics._inside(folder, folder.parent):
            for directory in folder.iterdir():
                path = directory / (session + '.jsonl')
                if not diagnostics._inside(path, folder.parent) and path.is_file():
                    paths.append(path)
        if len(paths) != 1:
            reading.note = 'Không đọc được nhật ký phiên.' if not paths else 'Có nhiều nhật ký trùng mã phiên.'
            return reading
        main = paths[0]
        n, bad = _scan(main, reading, session, '', calls)
        missing = 0
        agents = {r['agent_id'] for r in observed if _safe_id(r.get('agent_id'))}
        for agent in sorted(agents):
            path = main.parent / session / 'subagents' / ('agent-' + agent + '.jsonl')
            if diagnostics._inside(path, folder.parent) or not path.is_file():
                missing += 1
                continue
            count, errors = _scan(path, reading, session, agent, calls)
            bad += errors
            missing += int(count == 0)
        if not n:
            reading.note = 'Không đọc được định dạng nhật ký phiên.'
        elif bad:
            reading.note = 'Một phần nhật ký không đọc được.'
        if missing:
            reading.note += f' Thiếu nhật ký của {missing} agent con.'
    except FileNotFoundError:
        reading.note = 'Không đọc được nhật ký phiên.'
    except (OSError, RuntimeError, ValueError):
        reading.note = 'Không đọc được đầy đủ nhật ký phiên.'
    return reading
