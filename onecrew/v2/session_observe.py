"""User-level Claude observations. A session binds to one registered project and plan.

The binding lives outside all checkouts. Only a bound event gets a filtered payload.
Tool calls append to a private outbox. At the end of a turn (or via hook sync) the
outbox is imported into the ledger. Replaying a batch after a crash is idempotent.
"""
import datetime as dt
import hashlib
import itertools
import json
import os
import re
import uuid
from pathlib import Path

from . import hook_cli, where

OBSERVE_EVENTS = ('SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'PostToolUseFailure',
                  'SubagentStart', 'SubagentStop', 'Stop', 'SessionEnd')

# Chat can contain quoted config values spanning lines, or a credential on the
# line below its label. Mask these before running the shared per-line filter.
_CHAT_CREDENTIAL = re.compile(
    r"""(?ix)(\b[\w.-]*(?:password|passwd|pwd|token|secret|api[_-]?key|access[_-]?key|private[_-]?key|authorization)"""
    r"""["']?[ \t]*[:=][ \t]*)(?:"(?:\\.|[^"\\])*(?:"|\Z)|'(?:\\.|[^'\\])*(?:'|\Z)|\r?\n[ \t]*[^\r\n]+)""")

def _digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _clean(value, limit):
    from .diagnostics import redact
    if not isinstance(value, str): return None
    return redact(_CHAT_CREDENTIAL.sub(r'\1[withheld]', value), line_limit=None)[0][:limit]


def _sessions():
    return where.default_state_root() / 'claude-session-bindings'


def bindings():
    result = []
    for path in _sessions().glob('*.json'):
        try:
            result.append(json.loads(path.read_text(encoding='utf-8')))
        except (ValueError, OSError):
            continue
    return result


def _active(project, state_root):
    copy = hook_cli.state_copy(state_root, project)
    if copy is None: return None
    plan, error = hook_cli.load_plan(copy)
    if error or plan.get('status') != 'approved' or not plan.get('anchor_task'): return None
    return {'project': os.path.normcase(str(Path(project).resolve())), 'state_root': os.path.normcase(str(Path(state_root).resolve())),
            'plan': plan['plan'], 'anchor': plan['anchor'], 'task': plan['anchor_task'], 'revision': plan['revision']}


def _targets(event):
    # Use the owner profile's project registry and the external export. A plan
    # or config planted in a tool's working directory cannot select a ledger.
    projects = where._read_registry(where.registry_file())
    places = hook_cli.candidate_dirs(None, event)
    if event.get('tool_name') == 'Read':
        path = (event.get('tool_input') or {}).get('file_path')
        if isinstance(path, str):
            places.append((Path(event['cwd']).joinpath(path).parent, hook_cli.LIMITED))
    targets = {}
    for place, _role in places:
        for directory in where.repository_dirs(place):
            key = os.path.normcase(str(directory))
            if key in projects and key not in targets:
                targets[key] = _active(key, projects[key])
                break
    return [target for target in targets.values() if target]


def _binding(event, session):
    folder = _sessions()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (_digest(event['session_id']) + '.json')
    with hook_cli.appending(path.with_suffix('.lock'), wait=0.25, required=True):
        try:
            prior = json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            prior = {}
        if prior.get('ambiguous'): return None
        previous = prior.get('target')
        candidates = _targets(event)
        if previous and not any(t['task'] == previous['task'] and t['state_root'] == previous['state_root'] for t in candidates):
            registered = where.registered_state_root(previous['project'])
            current = (_active(previous['project'], registered)
                       if registered and os.path.normcase(str(registered.resolve())) == previous['state_root'] else None)
            if current: candidates.append(current)
        identities = {(t['state_root'], t['project'], t['task']) for t in candidates}
        if previous: identities.add((previous['state_root'], previous['project'], previous['task']))
        ambiguous = len(identities) > 1
        target = candidates[0] if candidates and not ambiguous else None
        record = {'session': session, 'target': target, 'ambiguous': ambiguous,
                  'status': 'bound' if target else 'unbound',
                  'reason': 'registered active plan' if target else ('multiple plans' if ambiguous else 'no active target')}
        if record != prior:
            from .install import write_text
            write_text(path, json.dumps(record, ensure_ascii=False))
        return target


def _rows(event, session, target):
    name = event['hook_event_name']
    tool = _clean(event.get('tool_name'), 120)
    tool_id = _clean(event.get('tool_use_id'), 200)
    inputs = event.get('tool_input') or {}
    base = {'session': session, 'cwd': _clean(event.get('cwd'), 1024), 'project': target['project'], 'plan': target['plan'],
            'revision': target['revision'], 'anchor': target['anchor'], 'task': target['task'], 'hook': name,
            'recorded_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'tool': tool, 'tool_use_id': tool_id,
            'agent_id': _clean(event.get('agent_id'), 200), 'agent_type': _clean(event.get('agent_type'), 120)}
    def row(kind, source='host', **values):
        # A tool call has a stable identity even if the host retries it.
        identity = [session, base['agent_id'], tool_id, name, kind, values.get('question_index')]
        return dict(base, observation=kind, source=source,
                    spool_id=_digest(json.dumps(identity)) if tool_id else uuid.uuid4().hex, **values)

    if name == 'UserPromptSubmit':
        if isinstance(event.get('prompt'), str):
            yield row('owner_prompt', 'owner', text=_clean(event['prompt'], None))
    elif tool == 'AskUserQuestion' and name in ('PreToolUse', 'PostToolUse'):
        response = event.get('tool_response')
        answers = response.get('answers') if isinstance(response, dict) else None
        for i, q in enumerate(inputs.get('questions') or []):
            if not isinstance(q, dict) or not isinstance(q.get('question'), str): continue
            question = q['question']
            link = _digest(json.dumps([session, base['agent_id'], tool_id, i])) if tool_id else None
            if name == 'PreToolUse':
                options = [_clean(o.get('label'), 500) for o in q.get('options', []) if isinstance(o, dict)]
                yield row('ai_question', 'ai_claim', question_index=i, question_id=link, text=_clean(question, 2000), options=options)
            elif isinstance(answers, dict) and isinstance(answers.get(question), str):
                yield row('owner_choice', 'owner', question_index=i, question_id=link, text=_clean(answers[question], 2000))
    elif name == 'PostToolUse' and tool in hook_cli.SHELL_TOOLS and inputs.get('run_in_background') is True:
        yield row('background_shell', label=_clean(inputs.get('description'), 160))
    elif name == 'PostToolUse' and tool in ('Write', 'Edit', 'NotebookEdit'):
        # Only the destination of a completed file edit, never its content or tool output.
        path = inputs.get('file_path') if tool != 'NotebookEdit' else inputs.get('notebook_path')
        if isinstance(path, str) and path and isinstance(event.get('cwd'), str):
            location = Path(os.path.normpath(os.path.join(event['cwd'], path)))
            if location.is_absolute() and not location.is_relative_to(target['project']):
                yield row('external_artifact', label=_clean(str(location), 1024))
                return
        yield row('tool_call')
    else:
        yield row({'SubagentStart': 'subagent_start', 'SubagentStop': 'subagent_stop',
                   'SessionStart': 'session_start', 'SessionEnd': 'session_end', 'Stop': 'turn_end'}.get(name, 'tool_call'))


def _outbox(project, state_root):
    return Path(state_root) / 'claude-observations' / _digest(os.path.normcase(str(Path(project).resolve())))


def observe(event):
    session = _clean(event.get('session_id'), 200)
    if not session or event.get('hook_event_name') not in OBSERVE_EVENTS: return
    target = _binding(event, session)
    if not target: return
    rows = list(_rows(event, session, target))
    if not rows: return
    folder = _outbox(target['project'], target['state_root'])
    folder.mkdir(parents=True, exist_ok=True)
    with hook_cli.appending(folder / 'append.lock', wait=0.25, required=True):
        with (folder / 'pending.jsonl').open('a+b') as stream:
            if stream.tell():
                stream.seek(-1, os.SEEK_END)
                if stream.read(1) != b'\n': stream.write(b'\n')  # isolate a partial append left by an interrupted hook
            for item in rows: stream.write((json.dumps(item, ensure_ascii=False) + '\n').encode('utf-8'))
    if event['hook_event_name'] in ('Stop', 'SessionEnd'):
        from ..ledger import Ledger
        flush(Ledger(target['project'], target['state_root']))


def flush(ledger):
    from . import namespaces, plan
    folder = _outbox(ledger.project, ledger.state_root)
    if not folder.is_dir(): return 0
    imported = 0
    # A second drainer leaves the batch to the first. Appenders only wait for
    # the rename, never for SQLite. A crash leaves a replayable batch on disk.
    with hook_cli.appending(folder / 'import.lock', wait=0.05, required=True):
        with hook_cli.appending(folder / 'append.lock', wait=0.25, required=True):
            pending = folder / 'pending.jsonl'
            if pending.exists(): pending.rename(folder / (uuid.uuid4().hex + '.batch'))
        for batch in sorted(folder.glob('*.batch'), key=lambda p: p.stat().st_mtime_ns):
            damaged = False
            with batch.open('rb') as stream:
                while lines := list(itertools.islice(stream, 64)):
                    with ledger.transaction(write=True) as conn:
                        for line in lines:
                            try:
                                r = json.loads(line)
                                anchor = namespaces.resolve(ledger, conn, r['anchor'])
                                if not anchor or anchor['id'] != r['task'] or r['project'] != ledger.project_path:
                                    raise ValueError('Observation target mismatch')
                                spool_id = r['spool_id']
                            except (ValueError, KeyError, TypeError):
                                damaged = True
                                continue
                            if conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind='hook.observed' AND json_extract(payload,'$.spool_id')=?",
                                            (anchor['id'], spool_id)).fetchone(): continue
                            plan.emit(ledger, conn, anchor['id'], 'hook.observed', r)
                            imported += 1
            if damaged: batch.rename(batch.with_suffix('.rejected'))
            else: batch.unlink()
    return imported
