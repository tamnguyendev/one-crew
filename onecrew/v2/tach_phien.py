"""TACHPHIEN (roadmap T0): `hook prompt` reminds the owner to split a long session. It only reminds: it never blocks, never asks, and any error in it
is silence.

A note is given only for a turn the owner typed (giao_viec.owner_typed) in a session with a plan. The size of the context is the input of the last
assistant turn in the session transcript (`input_tokens + cache_creation_input_tokens + cache_read_input_tokens`); only the end of the file is read.
Kinds, one note per turn, in this order:
  idle      the context is large and that turn is older than the cache TTL: the next turn writes the whole context again
  big       the context is large
  boundary  the plan was just approved, a milestone passed, or every milestone passed, and the context is above the floor: once per state
Each note writes one `reminded` line (rule split_session:<kind>, never the owner's words); a session gets at most `max_reminders` of them. The limits
come from `<state-root>/plans/tach-phien.json` (the owner's file); a missing or broken file or value means the built-in one, `"off": true` turns the
reminder off.
"""
import datetime as dt
import json
from pathlib import Path

from . import giao_viec, messages

CONFIG_NAME = 'tach-phien.json'
DEFAULTS = {'tokens': 200_000, 'ttl_seconds': 3600, 'boundary_tokens': 60_000, 'max_reminders': 3}
TAIL_BYTES = 512 * 1024
USAGE_KEYS = ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')


def config(state_root):
    """The limits of the owner's file over the defaults. A value that is not a whole number of zero or more is ignored."""
    values = dict(DEFAULTS, off=False)
    if not state_root: return values
    try:
        given = json.loads((Path(state_root) / 'plans' / CONFIG_NAME).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError, RecursionError):
        return values
    if not isinstance(given, dict): return values
    for key in DEFAULTS:
        if type(given.get(key)) is int and given[key] >= 0: values[key] = given[key]
    values['off'] = given.get('off') is True
    return values


def _age_from(stamp):
    """Seconds since an ISO timestamp of the transcript; None when it cannot be read."""
    if not isinstance(stamp, str): return None
    try:
        at = dt.datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    except ValueError:
        return None
    if at.tzinfo is None: at = at.replace(tzinfo=dt.timezone.utc)
    return (dt.datetime.now(dt.timezone.utc) - at).total_seconds()


def last_turn(transcript):
    """(context tokens, age in seconds or None) of the last assistant turn of the main session; None when the transcript does not tell: no file, no such
    turn in the last TAIL_BYTES, or the session was compacted after it (that turn's size no longer holds)."""
    if not isinstance(transcript, str) or not transcript: return None
    path = Path(transcript)
    if not path.is_file(): return None
    with path.open('rb') as stream:
        size = stream.seek(0, 2)
        start = max(0, size - TAIL_BYTES)
        stream.seek(start)
        lines = stream.read(TAIL_BYTES).split(b'\n')
    if start: lines = lines[1:]                         # the first piece is the end of a line that began before the tail
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if not isinstance(row, dict) or row.get('isSidechain'): continue
        if row.get('isCompactSummary') or (row.get('type') == 'system' and row.get('subtype') == 'compact_boundary'): return None
        message = row.get('message')
        usage = message.get('usage') if isinstance(message, dict) else None
        if row.get('type') != 'assistant' or not isinstance(usage, dict): continue
        tokens = sum(usage[k] for k in USAGE_KEYS if type(usage.get(k)) is int and 0 <= usage[k] <= 10**12)
        if tokens: return tokens, _age_from(row.get('timestamp'))
    return None


def phase(plan):
    """([plan, revision, milestones passed], the stage's name) of an approved plan."""
    milestones = plan.get('milestones') or []
    passed = sum(1 for m in milestones if m.get('state') == 'passed')
    stage = 'acceptance' if milestones and passed == len(milestones) else 'milestone' if passed else 'approved'
    return [plan.get('plan'), plan.get('revision'), passed], stage


def new_phase(mark, seen):
    """True when `mark` is a stage the session has not been told about: nothing told yet, another plan or revision, or more milestones passed."""
    if not isinstance(seen, list) or len(seen) != 3 or seen[:2] != mark[:2]: return True
    return not isinstance(seen[2], int) or mark[2] > seen[2]


def note(event, root, plan, record, session_state):
    """The reminder of this turn (and its ledger line and session counter), or None. `record` and `session_state` are hook_cli's. Never raises."""
    try:
        if not giao_viec.owner_typed(event.get('prompt')): return None
        limits = config(plan.get('state_root'))
        if limits['off']: return None
        session = event.get('session_id')
        mine = session_state(root, session)
        count = mine.get('split_count', 0)
        if count >= limits['max_reminders']: return None
        turn = last_turn(event.get('transcript_path'))
        if turn is None: return None
        tokens, age = turn
        mark, stage = phase(plan)
        if tokens >= limits['tokens']:
            kind = 'idle' if age is not None and age > limits['ttl_seconds'] else 'big'
        elif plan.get('status') == 'approved' and tokens >= limits['boundary_tokens'] and new_phase(mark, mine.get('split_mark')):
            kind = 'boundary'
        else:
            return None
        text = messages.t('tachphien.' + kind, plan=plan.get('plan'), thousands=round(tokens / 1000), minutes=int((age or 0) // 60),
                          stage=messages.t('tachphien.stage.' + stage))
        session_state(root, session, {'split_count': count + 1, 'split_mark': mark})
        record(root, plan, 'reminded', 'UserPromptSubmit', f'reminded to split the session ({kind}): last turn input {tokens} tokens',
               'split_session:' + kind, session=session)
        return text
    except Exception:                                   # noqa: BLE001 - a reminder never locks the session
        return None
