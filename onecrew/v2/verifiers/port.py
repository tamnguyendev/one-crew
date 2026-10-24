"""The port between the core and a verifier ADAPTER (W22, RX1; T14a, T23).

One core runs every kind of output. What differs between a code root, a document root (and, later, data and operations roots) is the
adapter named in the milestone's `verifier.type` and the checks it declares; the milestone lifecycle, repair limits, stop rules, budget, finding
and receipt rules, and the owner's acceptance are the same functions for all of them. This module is that single seam:

  - `register` / `names` / `get`: the adapters (a name, `validate_config(config, label)`, `run(config, port)`). The core never tests which
    adapter it has; it asks the registry. `BUILTIN` is the one table of the adapters that ship in the wheel.
  - `normalize`: the contract form. The `authority` of a milestone (retries, reserved calls, granted commands, minutes) is read, bounded and
    stored by THIS module from the approved contract; an adapter validates only its own keys and cannot widen the authority.
  - `Port`: everything an adapter is given. It reads inside a clean checkout of the artifact and nothing else. A retry beyond the policy, a
    call beyond the reservation, a command outside the grant, a read outside the checkout, closing a finding and setting a status are refused;
    each refusal is kept as a violation. An adapter has no ledger, no verdict and no owner verb to call.
  - `run`: makes the receipt. The result is computed from the checks by `expected_result`, never taken from the adapter's words; a run with a
    violation, an error, a timeout, a write into the checkout or a changed artifact is `inconclusive` and never a pass.
  - `record_violations`: writes one `adapter.violation` event (class A in compat.py) per refusal, naming the adapter and the act.

What this does NOT do: it does not contain code that the adapter runs in this process (an adapter is first-party code that the wheel
ships, selected by name from the registry; the contract cannot load a module by path). The checks that need no trust are the ones made from
outside it: the checkout fingerprint before and after, the artifact before and after, and the receipt rules of verdict.record.
"""
import copy
import hashlib
import importlib
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath

from ...ledger import LedgerError, canonical, utcnow
from ...snapshots import Snapshots, safe_file, scoped_path
from . import command, artifact

BUILTIN = ('doc', 'data', 'ops')            # shipped adapters; no task-type branch in the lifecycle
RESERVED = ('command', 'reviewer', 'owner-manual')
NAME = re.compile(r'[a-z][a-z0-9_-]{1,31}')
RETRY_CAP, CALLS_CAP, COMMANDS_CAP, MINUTES_CAP = 2, 5, 3, 30
MAX_READ = 8_000_000
MAX_FILES = 20_000
MAX_PROBLEMS, MAX_FINDINGS, MAX_TEXT = 200, 100, 500
REPORT_KEYS = ('checks', 'findings', 'unverified')
_registry = {}
_loaded = []


class AdapterViolation(LedgerError):
    """An act the core refused. `op` is the port method, `rule` the core rule that forbids it."""

    def __init__(self, message, op='', rule=''):
        super().__init__(message)
        self.op, self.rule = op, rule


class Inconclusive(Exception):
    """The adapter cannot say pass or fail (a file too large to read, a source it cannot reach): the verdict is inconclusive, never a pass."""


class Timeout(Inconclusive):
    pass


# ---- the registry ---------------------------------------------------------------------------------------------------------

def register(adapter):
    name = getattr(adapter, 'NAME', None)
    if not isinstance(name, str) or not NAME.fullmatch(name) or name in RESERVED:
        raise LedgerError(f'A verifier adapter needs a short lowercase NAME that is not one of {", ".join(RESERVED)}.')
    if not callable(getattr(adapter, 'validate_config', None)) or not callable(getattr(adapter, 'run', None)):
        raise LedgerError(f'Adapter {name} needs validate_config(config, label) and run(config, port).')
    if name in _registry and _registry[name] is not adapter: raise LedgerError(f'A verifier adapter named {name} is already registered.')
    _registry[name] = adapter


def unregister(name):
    _registry.pop(name, None)


def _load_builtin():
    for module in BUILTIN:
        if module not in _loaded:
            importlib.import_module(f'{__package__}.{module}')
            _loaded.append(module)


def names():
    _load_builtin()
    return tuple(sorted(_registry))


def known(name):
    return name in names()


def get(name):
    if not known(name): raise LedgerError(f'No verifier adapter named {name}.')
    return _registry[name]


def receipt_kind(name):
    return f'{name}-receipt'


# ---- the contract form ----------------------------------------------------------------------------------------------------

def _int(value, label, low, high):
    if type(value) is not int or not low <= value <= high: raise LedgerError(f'{label}: expected an integer {low}-{high}.')
    return value


def authority(raw, label):
    """The authority of one milestone, bounded by the core: how many retries the adapter may ask for, how many calls are reserved for it, which
    exact commands it may run, and how many minutes. The default is none of the first three."""
    raw = {} if raw is None else raw
    if not isinstance(raw, dict) or set(raw) - {'retries', 'calls', 'commands', 'max_minutes'}:
        raise LedgerError(label + '.authority: takes retries, calls, commands and max_minutes.')
    from ...work_contract import argv_value
    commands = raw.get('commands', [])
    if not isinstance(commands, list) or len(commands) > COMMANDS_CAP: raise LedgerError(f'{label}.authority.commands: a list of at most {COMMANDS_CAP} argument lists.')
    return {'retries': _int(raw.get('retries', 0), label + '.authority.retries', 0, RETRY_CAP),
            'calls': _int(raw.get('calls', 0), label + '.authority.calls', 0, CALLS_CAP),
            'commands': [argv_value(c, label + '.authority.commands') for c in commands],
            'max_minutes': _int(raw.get('max_minutes', 5), label + '.authority.max_minutes', 1, MINUTES_CAP)}


def normalize(name, config, label):
    """The stored form of a milestone's config: what the adapter validates, then the authority the core validated."""
    if config is None: config = {}
    if not isinstance(config, dict): raise LedgerError(label + ': the verifier config must be an object.')
    own = dict(config)
    granted = authority(own.pop('authority', None), label)
    checked = get(name).validate_config(own, label)
    if not isinstance(checked, dict) or 'authority' in checked: raise LedgerError(f'Adapter {name} must return its own keys only; the authority belongs to the core.')
    return {**checked, 'authority': granted}


# ---- what the adapter is given ---------------------------------------------------------------------------------------------

class Port:
    """The only door from an adapter to anything. Every refusal raises AdapterViolation and is also kept (so a refusal the adapter swallows
    is still recorded)."""

    def __init__(self, workspace, grant, adapter, clock=time.monotonic):
        self._root = Path(workspace).resolve()
        self._grant = copy.deepcopy(grant)
        self._adapter = adapter
        self._clock = clock
        self._deadline = clock() + self._grant['max_minutes'] * 60
        self._violations, self._retries, self._calls, self._read, self._listing = [], 0, 0, set(), None

    # read-only views of what was granted
    @property
    def workspace(self):
        return self._root

    @property
    def authority(self):
        return copy.deepcopy(self._grant)

    @property
    def adapter(self):
        return self._adapter

    def _note(self, op, rule, detail):
        self._violations.append({'op': op, 'rule': rule, 'detail': str(detail)[:MAX_TEXT]})

    def _refuse(self, op, rule, message):
        self._note(op, rule, message)
        raise AdapterViolation(message, op, rule)

    def _tick(self):
        if self._clock() > self._deadline: raise Timeout(f'the time reserved for this run ({self._grant["max_minutes"]} minutes) is over')

    # ---- reading, inside the checkout only
    def _safe(self, rel):
        try:
            text = scoped_path(rel)
            target = safe_file(self._root, text)
        except LedgerError:
            self._refuse('read', 'read_scope', f'{str(rel)[:200]!r} is outside the checkout of the artifact; an adapter reads inside it only')
        return target, PurePosixPath(text).as_posix()

    def files(self):
        """Every file of the checkout (posix paths relative to the workspace), sorted. A path that differs only in case is another path."""
        if self._listing is None:
            found = []
            for base, dirs, names_ in os.walk(self._root):
                self._tick()
                for name in dirs + names_:
                    self._safe((Path(base) / name).relative_to(self._root).as_posix())
                for name in names_:
                    found.append((Path(base) / name).relative_to(self._root).as_posix())
                    if len(found) > MAX_FILES: raise Inconclusive(f'more than {MAX_FILES} files in the checkout')
            self._listing = sorted(found)
        return list(self._listing)

    def exists(self, rel):
        _, key = self._safe(rel)
        listing = self.files()
        if key in set(listing): return True
        prefix = key.rstrip('/') + '/'
        return any(f.startswith(prefix) for f in listing)

    def read_text(self, rel, limit=MAX_READ):
        self._tick()
        target, key = self._safe(rel)
        if not target.is_file(): raise FileNotFoundError(key)
        with target.open('rb') as stream:
            data = stream.read(min(limit, MAX_READ) + 1)
        if len(data) > min(limit, MAX_READ): raise Inconclusive(f'{key} is larger than {min(limit, MAX_READ)} bytes; it is not read in part')
        self._read.add(key)
        return data.decode('utf-8')

    # ---- commands, only the exact ones granted
    def run_command(self, argv):
        """(exit_code, stdout, stderr) of a command the approved contract granted, run in the checkout with the verifier environment."""
        self._tick()
        if not isinstance(argv, (list, tuple)) or list(argv) not in self._grant['commands']:
            self._refuse('run_command', 'command_authority', f'command {str(argv)[:200]} is not in the list granted to this milestone ({len(self._grant["commands"])} granted)')
        left = max(1.0, self._deadline - self._clock())
        process = subprocess.Popen(list(argv), cwd=str(self._root), env=command.verifier_env(self._root), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, creationflags=0x08000000 if os.name == 'nt' else 0)
        try:
            out, err = process.communicate(timeout=left)
        except subprocess.TimeoutExpired:
            command._kill_tree(process)
            process.communicate()
            raise Timeout('a granted command did not finish in the time reserved') from None
        return process.returncode, out[-100_000:].decode('utf-8', 'replace'), err[-100_000:].decode('utf-8', 'replace')

    # ---- the acts that belong to the core
    def retry(self, why=''):
        if self._retries >= self._grant['retries']:
            self._refuse('retry', 'retry_policy', f'retry refused: the retry policy of this milestone allows {self._grant["retries"]} and {self._retries} were used')
        self._retries += 1

    def spend(self, calls=1):
        if type(calls) is not int or calls < 1: raise LedgerError('spend: a whole number of calls, at least 1.')
        if self._calls + calls > self._grant['calls']:
            self._refuse('spend', 'budget_reservation', f'spend refused: {calls} call(s) on top of {self._calls} is outside the reservation of {self._grant["calls"]}')
        self._calls += calls

    def close_finding(self, finding_id, evidence=None):
        self._refuse('close_finding', 'finding_close_needs_receipt',
                     f'finding {str(finding_id)[:60]} stays open: a finding is closed by the core on a receipt, not by an adapter')

    def set_status(self, status):
        if status == 'accepted':
            self._refuse('set_status', 'accepted_needs_owner_verb', 'accepted is set only by the owner acceptance verb (plan accept); an adapter cannot set it')
        self._refuse('set_status', 'status_is_the_cores', f'{str(status)[:40]!r} is derived by the core from verdicts; an adapter cannot set a status')


# ---- the run, and the receipt -----------------------------------------------------------------------------------------------

def _fingerprint(root):
    """What is in the checkout: path -> (size, mtime, content hash of a small file). Taken before and after the adapter ran, from outside it."""
    seen = {}
    for base, dirs, files in os.walk(root):
        for name in list(dirs):
            path = Path(base) / name
            linked = path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())
            seen[path.relative_to(root).as_posix() + '/'] = ('link', str(path.resolve())) if linked else ()
            if linked: dirs.remove(name)
        for name in files:
            path = Path(base) / name
            stat = path.lstat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest() if not path.is_symlink() else str(path.readlink())
            seen[path.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns, digest)
    return seen


def _text(value, limit=MAX_TEXT):
    return value[:limit] if isinstance(value, str) else None


def _checks(report, box):
    """The report as the core keeps it. Anything that is not a check, a finding or an unverified note is a claim and is a violation; a finding is
    always stored open."""
    extra = sorted(set(report) - set(REPORT_KEYS), key=str)
    if extra: box._note('report', 'report_claims', f'the report carries {", ".join(map(str, extra))}: the core decides status and result, an adapter reports checks and findings only')
    checks = report.get('checks')
    if not isinstance(checks, list) or not 1 <= len(checks) <= MAX_PROBLEMS: raise Inconclusive('the report has no checks or too many checks')
    clean = []
    for entry in checks:
        if (not isinstance(entry, dict) or not isinstance(entry.get('id'), str) or not isinstance(entry.get('ok'), bool)
                or not entry['id'] or len(entry['id']) > 40 or not isinstance(entry.get('problems', []), list)
                or any(not isinstance(p, str) for p in entry.get('problems', []))
                or type(entry.get('checked', 0)) is not int or entry.get('checked', 0) < 0):
            raise Inconclusive('a check of the report is malformed')
        problems = [_text(p) for p in entry.get('problems', []) if isinstance(p, str)][:MAX_PROBLEMS]
        clean.append({'id': entry['id'][:40], 'ok': entry['ok'] and not problems, 'checked': entry.get('checked', 0), 'problems': problems})
    if len({c['id'] for c in clean}) != len(clean): raise Inconclusive('check ids are duplicated')
    if not isinstance(report.get('findings', []), list) or not isinstance(report.get('unverified', []), list):
        raise Inconclusive('findings and unverified must be lists')
    if any(not isinstance(u, str) for u in report.get('unverified', [])):
        raise Inconclusive('an unverified note is malformed')
    findings = []
    for entry in (report.get('findings') or [])[:MAX_FINDINGS]:
        if not isinstance(entry, dict) or not isinstance(entry.get('id'), str) or not isinstance(entry.get('text'), str): raise Inconclusive('a finding of the report is malformed')
        if entry.get('status', 'open') != 'open':
            box._note('report', 'finding_close_needs_receipt', f'finding {entry["id"][:60]} was reported as {str(entry["status"])[:20]}: a finding is closed by the core on a receipt')
        findings.append({'id': entry['id'][:60], 'text': _text(entry['text']), 'status': 'open', **({'path': _text(entry['path'], 300)} if isinstance(entry.get('path'), str) else {})})
    unverified = [_text(u) for u in (report.get('unverified') or [])[:MAX_FINDINGS] if isinstance(u, str)]
    return clean, findings, unverified


def run(ledger, name, revision, plan_sha, milestone, directory):
    """Run the milestone's adapter on a clean checkout of the artifact; returns (receipt_blob, receipt)."""
    adapter = get(milestone['verifier']['type'])
    directory = Path(directory).resolve()
    if not directory.is_dir(): raise LedgerError('Verifier working directory does not exist: ' + str(directory))
    scratch = tempfile.mkdtemp(prefix='ocv-')
    try:
        workspace, before, proof = artifact.capture(ledger, directory, scratch)
        return _run(ledger, adapter, name, revision, plan_sha, milestone, directory, before, scratch, workspace, proof)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _run(ledger, adapter, name, revision, plan_sha, milestone, directory, before, scratch, workspace, proof):
    config = milestone['verifier']['config']
    own = {k: v for k, v in config.items() if k != 'authority'}
    top = Path(scratch) / 'src'
    box = Port(workspace, config['authority'], adapter.NAME)
    first = _fingerprint(top)
    started, begin, error, timed_out, report = utcnow(), time.monotonic(), None, False, None
    try:
        report = adapter.run(copy.deepcopy(own), box)
        box._tick()
    except AdapterViolation as refused:
        error = 'stopped by a refused act: ' + str(refused)[:200]
    except Timeout as late:
        timed_out, error = True, str(late)[:300]
    except Inconclusive as unsure:
        error = 'inconclusive: ' + str(unsure)[:280]
    except Exception as problem:          # an adapter that crashes has no verdict
        error = f'adapter_error {type(problem).__name__}: {problem}'[:300]
    after_tree = _fingerprint(top)
    if after_tree != first:
        changed = sorted(p for p in set(first) | set(after_tree) if first.get(p) != after_tree.get(p))
        box._note('write', 'read_only_scope', 'the adapter changed the checkout: ' + ', '.join(changed[:10]) + (f' and {len(changed) - 10} more' if len(changed) > 10 else ''))
    checks, findings, unverified = [], [], []
    if error is None:
        try:
            if not isinstance(report, dict): raise Inconclusive('the adapter returned no report')
            checks, findings, unverified = _checks(report, box)
        except Inconclusive as unsure:
            error = 'inconclusive: ' + str(unsure)[:280]
    after = artifact.identity(directory)
    receipt = {'kind': receipt_kind(adapter.NAME), 'adapter': adapter.NAME, 'plan': name, 'revision': revision, 'plan_sha': plan_sha, 'milestone': milestone['id'],
               'config': config, 'cwd': str(directory), 'started': started, 'seconds': round(time.monotonic() - begin, 2),
               'artifact_sha': before, 'artifact_sha_after': after, 'checks': checks, 'findings': findings, 'unverified': unverified,
               'files_read': sorted(box._read)[:500], 'retries_used': box._retries, 'calls': box._calls,
               'violations': [dict(v, adapter=adapter.NAME) for v in box._violations[:50]], 'error': error, 'timed_out': timed_out, **proof}
    return Snapshots(ledger.state_root).blob(canonical(receipt).encode('utf-8')), receipt


def expected_result(receipt):
    """The verdict a receipt supports, from its fields alone (so verdict.record judges it the same way verdict.run did): pass only when every
    check is ok, nothing went wrong, the artifact did not move and the adapter oversteps nothing."""
    if not isinstance(receipt, dict): return 'inconclusive'
    artifact_id = receipt.get('artifact_sha')
    if (not isinstance(artifact_id, str) or not command.TREE_ID.fullmatch(artifact_id) or set(artifact_id) == {'0'} or
            receipt.get('error') or receipt.get('timed_out') or receipt.get('violations') or artifact_id != receipt.get('artifact_sha_after')):
        return 'inconclusive'
    checks = receipt.get('checks')
    if (not isinstance(checks, list) or not checks or any(not isinstance(c, dict) or type(c.get('ok')) is not bool or
            not isinstance(c.get('id'), str) or type(c.get('checked')) is not int or c['checked'] < 0 or
            not isinstance(c.get('problems'), list) or any(not isinstance(p, str) for p in c['problems']) for c in checks)):
        return 'inconclusive'
    return 'pass' if all(c['ok'] and not c['problems'] for c in checks) else 'fail'


def record_violations(ledger, name, revision, milestone_id, blob, receipt):
    """One `adapter.violation` event per refusal, on the plan's anchor, naming the adapter, the act, the core rule and the receipt. Class A."""
    found = receipt.get('violations') or []
    if not found: return 0
    from .. import plan as plans
    with ledger.transaction(write=True) as conn:
        state = plans.anchor_events(ledger, conn, name)
        for v in found:
            plans.emit(ledger, conn, state['task_id'], 'adapter.violation',
                       {'plan': name, 'revision': revision, 'milestone': milestone_id, 'adapter': v['adapter'], 'op': v['op'], 'rule': v['rule'],
                        'detail': v['detail'], 'receipt': blob})
    return len(found)
