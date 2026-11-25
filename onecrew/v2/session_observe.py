"""User-level Claude observations. A session binds to one registered project and plan.

The binding lives outside all checkouts. Only a bound event gets a filtered payload.
Tool calls append to a private outbox. At the end of a turn (or via hook sync) the
outbox is imported into the ledger. Replaying a batch after a crash is idempotent.

The install key (S7 review P2-1, P2-1b, P2-2) is a guard against naive and accidental forging, NOT a security boundary.
`hook user install --observe` mints a random key per settings file, puts it in the handler's arguments (`hook observe --install-key <key>`) and keeps
its hash in OneCrew's machine state (where.observation_keys_file). observe() and flush() do nothing without a key whose hash is there, and every
outbox line carries an HMAC made with the key. That stops what a careless or naive caller does: `hook observe` / `hook sync` run by hand, `python -c`,
a script, `python -m onecrew.v2.hook_cli`, `onecrew_cli.py`, importlib, an in-process observe() call without the key, a line appended to the outbox.
It does NOT stop a determined AI that runs as the same OS account, which can still forge rows: it can replace the check in its own Python process,
point LOCALAPPDATA at a folder (even under .onecrew/scratch) holding its own key file and a copy of the project registry, strip CLAUDE* in a script
and call install.user_hook('install', <its own settings>, observe=True) to mint a key, build the settings path at run time to read the key (the
shell check only sees commands that name the file; the user hook does not judge Read), or read it from the command line of a running hook process.
What bounds the harm is elsewhere and holds for forged rows too: every session row is labelled "Ghi nhận trong phiên Claude (chưa xác thực)", and no
session row can clear the "Bản sửa chưa rõ nguồn lời chủ" warning (goal_history), approve, accept or record a verdict.
CLAUDE_CODE_ENTRYPOINT (input_source) is a label of how the host says it was started, not proof of who typed: the desktop app also reports
claude-desktop for prompts it sends itself (scheduled tasks, session_send).
"""
import datetime as dt
import hashlib
import hmac
import itertools
import json
import os
import re
import uuid
from pathlib import Path

from . import hook_cli, where

SESSION_SOURCE = 'claude_session'
# Keep the historical observation keys so that links and replay IDs remain stable.
SESSION_INPUT_LABELS = dict.fromkeys(('owner_prompt', 'owner_choice'), 'Ghi nhận trong phiên Claude (chưa xác thực)')
MACHINE_SOURCE = 'claude_machine'
MACHINE_LABEL = 'Máy gửi trong phiên Claude'


def input_label(record):
    if record.get('source') == MACHINE_SOURCE:
        return MACHINE_LABEL
    return SESSION_INPUT_LABELS[record['observation']]

OBSERVE_EVENTS = ('SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'PostToolUseFailure',
                  'SubagentStart', 'SubagentStop', 'Stop', 'SessionEnd')

# Chat can contain quoted config values spanning lines, or a credential on the
# line below its label. Mask these before running the shared per-line filter.
_CHAT_CREDENTIAL = re.compile(
    r"""(?ix)(\b[\w.-]*(?:password|passwd|pwd|token|secret|api[_-]?key|access[_-]?key|private[_-]?key|authorization)"""
    r"""["']?[ \t]*[:=][ \t]*)(?:"(?:\\.|[^"\\])*(?:"|\Z)|'(?:\\.|[^'\\])*(?:'|\Z)|\r?\n[ \t]*[^\r\n]+)""")

def _digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


# ---- the install key (P2-1): only the handler OneCrew installed carries it --------------------------------------------------------------------
KEY_FLAG = '--install-key'
KEY_MIN = 32
# P2-4: only a prompt typed in an interactive session can later be cited as the owner's words. Absent = older hosts and the test fixtures.
INTERACTIVE_ENTRYPOINTS = frozenset(('cli', 'claude-desktop'))


def key_id(key):
    """The hash of an install key, as the key file keeps it (never the key itself)."""
    return hashlib.sha256(b'onecrew-observation-key\0' + key.encode('utf-8')).hexdigest()


def registered_keys():
    """{settings file (normal form): key id} of every observation handler `hook user install --observe` wrote; {} when unreadable."""
    try:
        value = json.loads(where.observation_keys_file().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    installs = value.get('installs') if isinstance(value, dict) else None
    return {k: v for k, v in installs.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(installs, dict) else {}


def accepted(key):
    """The key id when `key` is the key of an installed observation handler, else None."""
    if not isinstance(key, str) or len(key) < KEY_MIN: return None
    wanted = key_id(key)
    return wanted if any(hmac.compare_digest(wanted, known) for known in registered_keys().values()) else None


def _seal(item, key):
    body = json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return hmac.new(key.encode('utf-8'), body, hashlib.sha256).hexdigest()


def sealed(item, key):
    """The outbox form of one row: the row, the id of the key that wrote it, and an HMAC over both made with that key."""
    item = dict(item, kid=key_id(key))
    return dict(item, mac=_seal(item, key))


def input_source(entrypoint=None):
    """SESSION_SOURCE for a prompt or answer of an interactive session (CLAUDE_CODE_ENTRYPOINT cli, claude-desktop, or absent), MACHINE_SOURCE for
    every other entrypoint (sdk-cli = `claude -p`, sdk-ts, sdk-py, scheduled runs, anything new)."""
    value = os.environ.get('CLAUDE_CODE_ENTRYPOINT') if entrypoint is None else entrypoint
    return SESSION_SOURCE if not value or value in INTERACTIVE_ENTRYPOINTS else MACHINE_SOURCE


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
    """([the active target of every registered project this call reaches], the active target of the session's own project or None).
    QSAT: the session's own project is the SESSION place of candidate_dirs (the hook process directory)."""
    # Use the owner profile's project registry and the external export. A plan
    # or config planted in a tool's working directory cannot select a ledger.
    projects = where._read_registry(where.registry_file())
    places = hook_cli.candidate_dirs(None, event, session_dir=event['cwd'])
    if event.get('tool_name') == 'Read':
        path = (event.get('tool_input') or {}).get('file_path')
        if isinstance(path, str):
            places.append((Path(event['cwd']).joinpath(path).parent, hook_cli.LIMITED))
    targets, own = {}, None
    for place, role in places:
        for directory in where.repository_dirs(place):
            key = os.path.normcase(str(directory))
            if key in projects and key not in targets:
                targets[key] = _active(key, projects[key])
                if role == hook_cli.SESSION: own = targets[key]
                break
    return [target for target in targets.values() if target], own


def _binding(event, session):
    folder = _sessions()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (_digest(event['session_id']) + '.json')
    with hook_cli.appending(path.with_suffix('.lock'), wait=0.25, required=True):
        try:
            prior = json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            prior = {}
        if prior.get('ambiguous'): return None      # any record marked ambiguous stays so, an older release's (no cause) included (giu-ban-ghi-cu)
        previous = prior.get('target')
        candidates, own = _targets(event)
        # QSAT D3: when the session's own project is registered and has an active plan, that plan alone is the candidate; the projects the call
        # only reaches (a Read, an Edit, a shell command in another repository) add no identity. A plan switch in the session's project still
        # makes the session ambiguous (previous below), and a session outside every registered project keeps the earlier rule.
        if own: candidates = [own]
        if previous and not any(t['task'] == previous['task'] and t['state_root'] == previous['state_root'] for t in candidates):
            registered = where.registered_state_root(previous['project'])
            current = (_active(previous['project'], registered)
                       if registered and os.path.normcase(str(registered.resolve())) == previous['state_root'] else None)
            if current: candidates.append(current)
        reached = {(t['state_root'], t['project'], t['task']) for t in candidates}
        identities = set(reached)
        if previous: identities.add((previous['state_root'], previous['project'], previous['task']))
        ambiguous = len(identities) > 1
        target = candidates[0] if candidates and not ambiguous else None
        record = {'session': session, 'target': target, 'ambiguous': ambiguous,
                  'status': 'bound' if target else 'unbound',
                  'reason': 'registered active plan' if target else ('multiple plans' if ambiguous else 'no active target')}
        if ambiguous:       # QSAT D4: a record written by this release says why, so it stays apart from an older release's record
            record['cause'] = 'places' if len(reached) > 1 else 'plan_changed'
        if record != prior:
            from .install import write_text
            write_text(path, json.dumps(record, ensure_ascii=False))
        return target


# QSAT: the short field each hand-over tool already has, kept as the row's one-line summary (PreToolUse only). The app's send_message has none.
SUMMARY_FIELDS = {'Agent': 'description', 'Task': 'description', 'SendMessage': 'summary', 'mcp__ccd_session__start_session': 'title'}


def _rows(event, session, target):
    name = event['hook_event_name']
    tool = _clean(event.get('tool_name'), 120)
    tool_id = _clean(event.get('tool_use_id'), 200)
    inputs = event.get('tool_input') or {}
    base = {'session': session, 'cwd': _clean(event.get('cwd'), 1024), 'project': target['project'], 'plan': target['plan'],
            'revision': target['revision'], 'anchor': target['anchor'], 'task': target['task'], 'hook': name,
            'recorded_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'tool': tool, 'tool_use_id': tool_id,
            'agent_id': _clean(event.get('agent_id'), 200), 'agent_type': _clean(event.get('agent_type'), 120)}
    # P2-4: an allowlist. Print mode (sdk-cli), the SDKs and scheduled runs are machine input, not words typed in a session.
    source_of_input = input_source()

    def row(kind, source='host', **values):
        # A tool call has a stable identity even if the host retries it.
        identity = [session, base['agent_id'], tool_id, name, kind, values.get('question_index')]
        return dict(base, observation=kind, source=source,
                    spool_id=_digest(json.dumps(identity)) if tool_id else uuid.uuid4().hex, **values)

    if name == 'UserPromptSubmit':
        if isinstance(event.get('prompt'), str):
            yield row('owner_prompt', source_of_input, text=_clean(event['prompt'], None))
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
                yield row('owner_choice', source_of_input, question_index=i, question_id=link, text=_clean(answers[question], 2000))
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
    elif name == 'PreToolUse' and tool in SUMMARY_FIELDS:
        # QSAT D1/D2: one short line of a hand-over, from the field the tool already has; masked and capped, never the prompt or message itself
        raw = inputs.get(SUMMARY_FIELDS[tool]) if isinstance(inputs, dict) else None
        summary = _clean(raw, 160) if isinstance(raw, str) and raw.strip() else None
        yield row('tool_call', **({'summary': summary} if summary else {}))
    else:
        yield row({'SubagentStart': 'subagent_start', 'SubagentStop': 'subagent_stop',
                   'SessionStart': 'session_start', 'SessionEnd': 'session_end', 'Stop': 'turn_end'}.get(name, 'tool_call'))


def _outbox(project, state_root):
    return Path(state_root) / 'claude-observations' / _digest(os.path.normcase(str(Path(project).resolve())))


def observe(event, key=None):
    """Record one hook event. `key`: the install key the handler carries (`hook observe --install-key <key>`); without an accepted key nothing is
    read, bound or written, and nothing is said."""
    if not accepted(key): return
    session = _clean(event.get('session_id'), 200)
    if not session or event.get('hook_event_name') not in OBSERVE_EVENTS: return
    event = dict(event, cwd=str(Path.cwd()))
    target = _binding(event, session)
    if not target: return
    if event['hook_event_name'] == 'PostToolUse':
        from . import owner_results
        owner_results.hook(dict(target, anchor_task=target['task']), target['project'], event)
    rows = list(_rows(event, session, target))
    if not rows: return
    folder = _outbox(target['project'], target['state_root'])
    folder.mkdir(parents=True, exist_ok=True)
    with hook_cli.appending(folder / 'append.lock', wait=0.25, required=True):
        with (folder / 'pending.jsonl').open('a+b') as stream:
            if stream.tell():
                stream.seek(-1, os.SEEK_END)
                if stream.read(1) != b'\n': stream.write(b'\n')  # isolate a partial append left by an interrupted hook
            for item in rows: stream.write((json.dumps(sealed(item, key), ensure_ascii=False) + '\n').encode('utf-8'))
    if event['hook_event_name'] in ('Stop', 'SessionEnd'):
        from ..ledger import Ledger
        flush(Ledger(target['project'], target['state_root']), key)


HELD_FLUSHES = 20      # a line that names another installed key is put back at most this many times, then dropped (its signature cannot be checked here)


def _opened(line, key, mine, known):
    """(row, held): the row of an outbox line sealed with `key`, else None. held is the line to put back (with its count raised) when it names
    another installed key that has not imported it yet, else None (the line is rejected)."""
    try:
        r = json.loads(line)
    except ValueError:
        return None, None
    if not isinstance(r, dict): return None, None
    held = r.pop('held', 0)               # outside the signature: only the flushes that put the line back add it
    if r.get('kid') != mine:
        if not (isinstance(r.get('kid'), str) and r['kid'] in known) or not isinstance(held, int) or isinstance(held, bool) or not 0 <= held < HELD_FLUSHES:
            return None, None
        return None, (json.dumps(dict(r, held=held + 1), ensure_ascii=False) + '\n').encode('utf-8')
    mac = r.pop('mac', None)
    if not isinstance(mac, str) or not hmac.compare_digest(mac, _seal(r, key)): return None, False
    r.pop('kid')
    return r, False


def flush(ledger, key=None):
    """Import the outbox of this ledger's project. `key`: as for observe(); without an accepted key nothing is moved or imported (0)."""
    from . import namespaces, plan
    mine = accepted(key)
    if not mine: return 0
    known = set(registered_keys().values())
    folder = _outbox(ledger.project, ledger.state_root)
    if not folder.is_dir(): return 0
    imported, others = 0, []
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
                            r, held = _opened(line, key, mine, known)
                            if r is None:
                                if held: others.append(held)
                                else: damaged = True
                                continue
                            try:
                                anchor = namespaces.resolve(ledger, conn, r['anchor'])
                                if not anchor or anchor['id'] != r['task'] or r['project'] != ledger.project_path:
                                    raise ValueError('Observation target mismatch')
                                spool_id = r['spool_id']
                                if r.get('observation') in SESSION_INPUT_LABELS and r.get('source') != MACHINE_SOURCE:
                                    r['source'] = SESSION_SOURCE  # also covers a sealed row in the older 'owner' spelling (unsealed lines never get here)
                            except (ValueError, KeyError, TypeError):
                                damaged = True
                                continue
                            if conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind='hook.observed' AND json_extract(payload,'$.spool_id')=?",
                                            (anchor['id'], spool_id)).fetchone(): continue
                            plan.emit(ledger, conn, anchor['id'], 'hook.observed', r)
                            imported += 1
            if damaged: batch.rename(batch.with_suffix('.rejected'))
            else: batch.unlink()
        if others:          # lines of another installed handler (another settings file) wait for that handler's flush
            with hook_cli.appending(folder / 'append.lock', wait=0.25, required=True):
                with (folder / 'pending.jsonl').open('a+b') as stream:
                    if stream.tell():
                        stream.seek(-1, os.SEEK_END)
                        if stream.read(1) != b'\n': stream.write(b'\n')
                    stream.writelines(others)
    return imported
