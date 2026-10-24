"""W33a - what an executor can do (declared), and what was observed of it (with a source). R03, HD-28, 00 §5.

Nothing here promises a capability the adapter did not declare. The core asks the DECLARATION, never the executor's name:
  * `Dispatcher.send` refuses a command (pause, stop, ...) to an executor that did not declare it, and records only the commands it really sent;
  * `hold_plan` picks "withdraw write permission" for an executor that cannot pause, and the report words say so ("đã ngừng cấp quyền ghi"),
    never "đã dừng"; a pause is only ever "requested" until the executor confirms it (W33b, R08);
  * `observe` writes `executor.observed` (class A) with the time source and the moment OneCrew received it. A session OneCrew did not start
    (a Claude Code session seen through hooks) is reported only from a real receipt, tool call or hook event - never from a guessed call count,
    from internal reasoning or from "it looks hung" - and a number its adapter does not measure is refused;
  * a missing datum is `unknown` (or `not measured`), never 0.

This is the interface and the hook adapter. The full interface for managed workers (stop, pause at a safe point, isolation, recovery) is W33b.
"""
import argparse
import datetime as dt
import json
import math
import re
import sys
from pathlib import Path

from ..ledger import LedgerError, text_field, utcnow
from . import plan as plans

CAPABILITIES = ('start', 'stop', 'pause_at_safe_point', 'isolate', 'measure', 'recover')
MEASURES = ('time', 'calls')
KINDS = ('external_hook', 'managed', 'verifier')
WHATS = ('start', 'end', 'wait')
WAIT_REASONS = ('owner', 'resource', 'external_service')
# Where a time or a fact may come from. A session OneCrew does not run has no clock of its own that OneCrew can read.
EXTERNAL_SOURCES = ('receipt', 'tool_call', 'hook_event')
MANAGED_SOURCES = EXTERNAL_SOURCES + ('executor_clock',)
NOT_SOURCES = ('inferred', 'call_count', 'internal_reasoning', 'hang', 'idle', 'estimate', 'guess')       # named so the refusal says why
UNKNOWN, NOT_MEASURED = 'unknown', 'not_measured'
KIND = 'executor.observed'
BLOB = re.compile(r'[0-9a-f]{64}')


class CapabilityMissing(LedgerError):
    """A command was addressed to an executor that did not declare the capability."""


class Declaration:
    """What an adapter says it can do. Whatever it does not say is not promised."""

    def __init__(self, name, kind, capabilities=(), measures=()):
        if not (isinstance(name, str) and re.fullmatch(r'[a-z][a-z0-9_.-]{0,59}', name)): raise LedgerError('executor name: lower-case letters, digits, _ . -')
        if kind not in KINDS: raise LedgerError(f'executor kind must be one of {", ".join(KINDS)}.')
        capabilities, measures = frozenset(capabilities), frozenset(measures)
        if capabilities - set(CAPABILITIES): raise LedgerError('unknown capability: ' + ', '.join(sorted(capabilities - set(CAPABILITIES))))
        if measures - set(MEASURES): raise LedgerError('unknown measure: ' + ', '.join(sorted(measures - set(MEASURES))))
        if bool(measures) != ('measure' in capabilities): raise LedgerError('"measure" is declared together with what it measures (time, calls), and only then.')
        self.name, self.kind, self.capabilities, self.measures = name, kind, capabilities, measures

    def supports(self, capability):
        return capability in self.capabilities

    def measures_what(self, what):
        return what in self.measures

    def sources(self):
        return EXTERNAL_SOURCES if self.kind == 'external_hook' else MANAGED_SOURCES

    def view(self):
        return {'executor': self.name, 'kind': self.kind, 'capabilities': sorted(self.capabilities), 'measures': sorted(self.measures)}


class Executor:
    """The interface: a declaration, and one method per capability that the adapter implements. A method the adapter does not implement is
    never called by the core (Dispatcher checks the declaration first)."""
    declaration = None

    def supports(self, capability):
        return self.declaration.supports(capability)


class HookAdapter(Executor):
    """A Claude Code (or other AI) session that OneCrew only sees through its hooks. The user opened it; OneCrew can refuse a tool call and
    can read the tool calls and hook events that really happen. It cannot start, stop, pause, isolate, measure or recover it."""
    declaration = Declaration('claude-code-hook', 'external_hook')


class CommandVerifier(Executor):
    """Observes verifier runs. Managed control methods are supplied by W33b."""
    declaration = Declaration('command-verifier', 'verifier', ('measure',), ('time',))


REGISTRY = {a.declaration.name: a.declaration for a in (HookAdapter, CommandVerifier)}


def declaration_of(executor):
    return executor.declaration if hasattr(executor, 'declaration') else executor


class Dispatcher:
    """The one door through which the core sends a command to an executor. `sent` is the log of commands that were really sent."""

    def __init__(self):
        self.sent = []

    def send(self, executor, command, *args):
        declaration = declaration_of(executor)
        if command not in CAPABILITIES or command == 'measure': raise LedgerError(f'{command!r} is not a command an executor can be sent.')
        if not declaration.supports(command):
            raise CapabilityMissing(f'executor {declaration.name} did not declare {command}: the command is not sent.')
        if not callable(getattr(executor, command, None)):
            raise CapabilityMissing(f'executor {declaration.name} has no implementation of {command}: the command is not sent.')
        result = getattr(executor, command)(*args)
        self.sent.append({'executor': declaration.name, 'command': command, 'args': [str(a) for a in args]})
        return result


# ---- holding a branch (the policy; the hold event itself belongs to W18, R05) -----------------------------------------------------

HOLD_TEXT = {
    'revoke_write': {'vi': 'đã ngừng cấp quyền ghi vào phạm vi bị giữ (phiên không bị dừng)',
                     'en': 'write permission to the held scope is withdrawn (the session is not stopped)'},
    'pause_requested': {'vi': 'đã yêu cầu dừng tại điểm an toàn (chưa xác nhận)', 'en': 'a pause at the next safe point is requested (not confirmed yet)'},
}


def hold_plan(executor):
    """What OneCrew may do to hold work that `executor` does: ask for a pause only if the executor declared it, else withdraw write permission.
    The state is never "paused" here: that word needs the executor's confirmation (W33b)."""
    declaration = declaration_of(executor)
    if declaration.supports('pause_at_safe_point'):
        return {'executor': declaration.name, 'action': 'pause_at_safe_point', 'command': 'pause_at_safe_point', 'state': 'pause_requested'}
    return {'executor': declaration.name, 'action': 'revoke_write', 'command': None, 'state': 'write_revoked'}


def hold_text(plan, lang='vi'):
    return HOLD_TEXT['pause_requested' if plan['action'] == 'pause_at_safe_point' else 'revoke_write'][lang]


# ---- observing -------------------------------------------------------------------------------------------------------------------

def _stamp(text, name):
    if text is None: return None
    try:
        value = dt.datetime.fromisoformat(str(text))
    except ValueError as error:
        raise LedgerError(f'{name}: not an ISO time ({text!r}).') from error
    return (value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)).isoformat()


def _basis(ledger, declaration, source, ref):
    if source in NOT_SOURCES:
        raise LedgerError(f'source {source!r} is not an observation: {declaration.name} is reported only from a receipt, a real tool call or a real hook event '
                          f'(no inferred call count, no internal reasoning, no "hung" state).')
    if source not in declaration.sources():
        raise LedgerError(f'source {source!r} is not one of {", ".join(declaration.sources())} for {declaration.name} ({declaration.kind}).')
    text_field(ref, 'ref', 200)
    if not ref.strip(): raise LedgerError('ref: the receipt, tool call or hook event that shows it (non-empty).')
    if source == 'receipt':
        from ..snapshots import Snapshots
        if not BLOB.fullmatch(ref): raise LedgerError('a receipt ref is the 64-hex key of a blob in this state root.')
        try:
            Snapshots(ledger.state_root).read_blob(ref)
        except (OSError, LedgerError) as error:
            raise LedgerError('the receipt is not a blob in this state root: ' + str(error)[:120]) from error
    return {'type': source, 'ref': ref}


def observe(ledger, name, executor, attempt, what, *, source, ref, at=None, until=None, wait_reason=None, measured=None):
    """Write one observation (`executor.observed`, class A) on the anchor of plan `name`. `at` is when it happened by `source` (None = unknown: the
    observation is kept, the time is not invented; stored as `observed_at`, because plan.emit stamps `at` itself); the moment OneCrew received it is `received_at`. Repeating the same observation writes nothing."""
    declaration = declaration_of(executor)
    text_field(attempt, 'attempt', 100)
    if what not in WHATS: raise LedgerError(f'what must be one of {", ".join(WHATS)}.')
    basis = _basis(ledger, declaration, source, ref)
    at, until = _stamp(at, 'at'), _stamp(until, 'until')
    if what == 'wait':
        if wait_reason not in WAIT_REASONS: raise LedgerError(f'a wait names its reason: {", ".join(WAIT_REASONS)}.')
        if until and (not at or dt.datetime.fromisoformat(until) < dt.datetime.fromisoformat(at)):
            raise LedgerError('A closed wait requires ordered start/end times.')
    elif wait_reason or until: raise LedgerError('a reason and an end belong to a wait.')
    measured = dict(measured or {})
    if set(measured) - {'calls', 'seconds'}: raise LedgerError('measured: calls and seconds only.')
    for key, measure in (('calls', 'calls'), ('seconds', 'time')):
        if key in measured and not declaration.measures_what(measure):
            raise LedgerError(f'executor {declaration.name} does not declare measuring {measure}: a {key} figure for it is refused (not inferred, not 0).')
        if key in measured and (type(measured[key]) not in (int, float) or not math.isfinite(measured[key]) or measured[key] < 0): raise LedgerError(f'measured {key}: a finite non-negative number.')
    payload = dict(declaration.view(), plan=name, attempt=attempt, what=what, observed_at=at, time_source=source, basis=basis,
                   source_trust='operator_reported; reference not independently verified',
                   **({'wait': {'reason': wait_reason, 'until': until}} if what == 'wait' else {}), **({'measured': measured} if measured else {}))
    with ledger.transaction(write=True) as conn:
        state = plans.anchor_events(ledger, conn, name)
        for row in conn.execute("SELECT payload FROM events WHERE task_id=? AND kind=?", (state['task_id'], KIND)):
            old = json.loads(row['payload'])
            if all(old.get(k) == v for k, v in payload.items()): return dict(old, written=False)
        plans.emit(ledger, conn, state['task_id'], KIND, dict(payload, received_at=utcnow()))
    return dict(payload, written=True)


def _verifier_attempts(conn, task_id):
    """Attempts of the command/reviewer verifier, read from verdict.run's own events (no new write): start from run_started, end from the receipt or
    the abandonment. The time source is the ledger event."""
    from . import verdict
    attempts = []
    for run in verdict.run_records(conn, task_id):
        end = run['receipt'] or run['abandoned']
        attempts.append({'executor': CommandVerifier.declaration.name if run.get('kind') == 'command' else 'receipt-verifier',
                         'verifier_type': run.get('kind'), 'attempt': run.get('run_id'), 'derived': True,
                         'start': {'at': run.get('started'), 'time_source': 'ledger_event', 'received_at': run.get('at')},
                         'end': {'at': (end or {}).get('at') or (end or {}).get('detected_at'), 'time_source': 'ledger_event', 'received_at': (end or {}).get('at')} if end else UNKNOWN,
                         'ended_by': 'receipt' if run['receipt'] else 'abandoned' if run['abandoned'] else None})
    return attempts


def _seconds(start, end):
    try:
        return (dt.datetime.fromisoformat(end) - dt.datetime.fromisoformat(start)).total_seconds()
    except (TypeError, ValueError):
        return None


def summary(ledger, name):
    """Per executor and attempt: when it started and ended (with the source and the moment OneCrew received it), its waits, and what is measured.
    A datum that was not observed is `unknown`; a quantity the adapter does not measure is `not_measured`; neither is ever 0."""
    with ledger.transaction() as conn:
        state = plans.anchor_events(ledger, conn, name)
        rows = [json.loads(r['payload']) for r in conn.execute("SELECT payload FROM events WHERE task_id=? AND kind=? ORDER BY seq", (state['task_id'], KIND))]
        derived = _verifier_attempts(conn, state['task_id'])
    attempts = {}
    for p in rows:
        item = attempts.setdefault((p['executor'], p['attempt']), {
            'executor': p['executor'], 'kind': p['kind'], 'attempt': p['attempt'], 'capabilities': p['capabilities'], 'measures': p['measures'],
            'start': UNKNOWN, 'end': UNKNOWN, 'waits': {}, 'calls': [], 'seconds': []})
        seen = {'at': p['observed_at'] if p['observed_at'] else UNKNOWN, 'time_source': p['time_source'], 'ref': p['basis']['ref'], 'received_at': p['received_at']}
        if p['what'] == 'wait': item['waits'][p['basis']['ref']] = dict(seen, reason=p['wait']['reason'], until=p['wait']['until'] or UNKNOWN)
        else: item[p['what']] = seen
        item['calls'] += [p['measured']['calls']] if 'calls' in (p.get('measured') or {}) else []
        item['seconds'] += [p['measured']['seconds']] if 'seconds' in (p.get('measured') or {}) else []
    out = []
    for item in attempts.values():
        measures = item['measures']
        times_known = isinstance(item['start'], dict) and isinstance(item['end'], dict) and UNKNOWN not in (item['start']['at'], item['end']['at'])
        item['elapsed_seconds'] = NOT_MEASURED if 'time' not in measures else (item['seconds'][-1] if item['seconds'] else (_seconds(item['start']['at'], item['end']['at']) if times_known else UNKNOWN))
        item['calls'] = NOT_MEASURED if 'calls' not in measures else (sum(item['calls']) if item['calls'] else UNKNOWN)
        item.pop('seconds')
        item['waits'] = list(item['waits'].values())
        item['wait_seconds'] = (UNKNOWN if not item['waits'] or any(w['until'] == UNKNOWN or w['at'] == UNKNOWN for w in item['waits'])
                                else sum(_seconds(w['at'], w['until']) for w in item['waits']))
        out.append(item)
    for item in derived:
        known = isinstance(item['end'], dict) and item['end']['at']
        out.append(dict(item, kind='verifier', capabilities=sorted(CommandVerifier.declaration.capabilities), measures=['time'], waits=[], wait_seconds=UNKNOWN, calls=NOT_MEASURED,
                        elapsed_seconds=_seconds(item['start']['at'], item['end']['at']) if known else UNKNOWN))
    return {'plan': name, 'attempts': out}


def _word(value, lang):
    return {UNKNOWN: {'vi': 'không rõ', 'en': 'unknown'}, NOT_MEASURED: {'vi': 'không đo', 'en': 'not measured'}}[value][lang]


def _point(value, lang):
    if not isinstance(value, dict): return _word(UNKNOWN, lang)
    when = value['at'] if value['at'] != UNKNOWN else _word(UNKNOWN, lang)
    return f"{when} ({value['time_source']}, {'nhận' if lang == 'vi' else 'received'} {value.get('received_at')})"


def render(report, lang='vi'):
    """The attempts as plain text lines. A figure that was not observed prints as 'không rõ'; one the adapter does not measure prints 'không đo'."""
    labels = {'vi': ('bắt đầu', 'kết thúc', 'chờ', 'thời gian chạy', 'call'), 'en': ('start', 'end', 'wait', 'elapsed', 'calls')}[lang]
    lines = []
    for a in report['attempts']:
        elapsed = _word(a['elapsed_seconds'], lang) if isinstance(a['elapsed_seconds'], str) else f"{a['elapsed_seconds']:.0f}s"
        calls = _word(a['calls'], lang) if isinstance(a['calls'], str) else str(a['calls'])
        waits = '; '.join(f"{w['reason']} {w['at']} -> {w['until']}" for w in a['waits']) or '-'
        lines.append(f"- {a['executor']} · {a['attempt']} · {labels[0]}: {_point(a['start'], lang)} · {labels[1]}: {_point(a['end'], lang)} · "
                     f"{labels[2]}: {waits} · {labels[3]}: {elapsed} · {labels[4]}: {calls}")
    return '\n'.join(lines) if lines else ('không có quan sát' if lang == 'vi' else 'no observations')


# ---- command line: `onecrew executor list|observe|summary` --------------------------------------------------------------------------

def _parser():
    p = argparse.ArgumentParser(prog='onecrew executor')
    p.add_argument('--project', type=Path, default=Path.cwd()); p.add_argument('--state-root', type=Path)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('list', help='The declared capabilities of each known executor.')
    o = sub.add_parser('observe', help='Record one observation of an executor attempt, with its source.')
    o.add_argument('--plan', required=True); o.add_argument('--executor', required=True, choices=sorted(REGISTRY)); o.add_argument('--attempt', required=True)
    o.add_argument('--what', required=True, choices=WHATS); o.add_argument('--source', required=True); o.add_argument('--ref', required=True)
    o.add_argument('--at'); o.add_argument('--until'); o.add_argument('--wait-reason', choices=WAIT_REASONS)
    s = sub.add_parser('summary', help='Start, end and waits of each attempt, with sources; unknown stays unknown.')
    s.add_argument('--plan', required=True); s.add_argument('--lang', choices=('vi', 'en'), default='vi'); s.add_argument('--json', action='store_true')
    return p


def _without_group(argv):
    """The router passes the whole command line (global options, the group word, the command): drop the group word."""
    argv, out, i = list(argv), [], 0
    while i < len(argv):
        if argv[i] in ('--project', '--state-root'): out += argv[i:i + 2]; i += 2
        elif argv[i] == 'executor' and 'executor' not in out: i += 1
        else: out.append(argv[i]); i += 1
    return out


def main(argv=None):
    parsed = _parser().parse_args(_without_group(sys.argv[1:] if argv is None else argv))
    try:
        if parsed.command == 'list':
            print(json.dumps([d.view() for d in REGISTRY.values()], ensure_ascii=False, indent=2)); return 0
        from ..ledger import Ledger
        from . import where
        state_root = where.state_root_for(parsed.project, parsed.state_root)
        from .lint import ReadOnlyLedger
        ledger = Ledger(parsed.project, state_root) if parsed.command == 'observe' else ReadOnlyLedger(parsed.project, state_root)
        if parsed.command == 'observe':
            print(json.dumps(observe(ledger, parsed.plan, REGISTRY[parsed.executor], parsed.attempt, parsed.what, source=parsed.source, ref=parsed.ref,
                                     at=parsed.at, until=parsed.until, wait_reason=parsed.wait_reason), ensure_ascii=False, indent=2)); return 0
        report = summary(ledger, parsed.plan)
        print(json.dumps(report, ensure_ascii=False, indent=2) if parsed.json else render(report, parsed.lang)); return 0
    except LedgerError as error:
        print(json.dumps({'error': str(error), 'type': type(error).__name__}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
