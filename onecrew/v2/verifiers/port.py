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
import datetime as dt
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
from ...snapshots import ControlAlias, Snapshots, control_part, is_link, safe_file, scoped_path
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

def _leaves(text):
    """Does this path text leave the checkout (not a string, empty, absolute, a drive, a backslash, a `..` component), rather than name
    something inside it?"""
    return (not isinstance(text, str) or not text or '\\' in text or text.startswith('/') or re.match(r'[A-Za-z]:', text) is not None
            or '..' in text.split('/'))


def kept_reason(text):
    """Why the snapshot rules (scoped_path) keep this path INSIDE the checkout from every reader, or None: a path that leaves the checkout is
    not kept, it is outside. Only the name is judged; nothing is read."""
    if _leaves(text): return None
    try:
        scoped_path(text)
        return None
    except LedgerError:
        pass
    if any(control_part(part) for part in text.split('/')):
        return 'a control or credential path (.git, .onecrew, .ssh, .aws, .env*): its content is never read'
    if len(text) > 240:
        return 'longer than 240 characters, a path an adapter may not read'
    return 'a name an adapter may not read (a Windows device name, a reserved character, an empty part or a trailing dot or space)'


# A Windows short (8.3) name is the alias a volume gives to a file whose long name is longer than 8.3 characters or starts with a dot (.env.example is
# ENV~1.EXA): up to 6 characters, `~`, digits (8 characters in all), and an optional extension of up to 3. A name that holds a character no short name can
# hold (space . " * + , / : ; < = > ? [ \ ] |) is not one. The first part may hold a tilde of the long name (the Office lock file ~$K_TKBTLV.docx is
# ~$K_TK~1.DOC, .env~ is ENV~~1). This is the shape internal_plan.SHORT_NAME refuses in node scopes (2.3-B Q6), narrowed to what a volume can give.
SHORT_NAME = re.compile(r'([^.\s"*+,/:;<=>?\[\\\]|]{1,6})~([0-9]{1,6})(?:\.[^.\s"*+,/:;<=>?\[\\\]|]{1,3})?')
HARD_LINK = ('has more than one name on the disk (a hard link), and the other name may be one an adapter may not read (.git, .onecrew, .ssh, .aws, .env*): '
             'its content is never read')


def short_name_part(text):
    """The first component of the path `text` that has the form of a Windows short (8.3) name (ENV~1.EXA, GIT~1, PROGRA~1), else None. Only the form is
    judged, so no file system is needed: an alias stands for another file on one volume, and nothing in the text says which."""
    for part in str(text).split('/'):
        found = SHORT_NAME.fullmatch(part)
        if found and len(found.group(1)) + 1 + len(found.group(2)) <= 8: return part
    return None


def long_name(value, label):
    """`value`, a path that a contract names (already through scoped_path), unless one of its components has the form of a Windows short name (review
    dev6 section 3, 29/10). An alias can be the name of a kept file (ENV~1.EXA is .env.example), differs from one volume to another and is known only to
    the disk, so a milestone that names one cannot be judged where it is proposed. A run refuses it when it does reach a kept file (R10); the contract
    names the file by its long name instead, and a name that only looks like an alias (`notes~1-final.csv`, `backup~2024.csv`) is not refused."""
    part = short_name_part(value)
    if part is not None:
        raise LedgerError(f'{label}: {part!r} has the form of a Windows short (8.3) name, an alias that a volume gives to a file with a longer name '
                          '(.env.example is ENV~1.EXA). It can stand for a file that is never read and it differs from one volume to another: '
                          'name the file by its long name.')
    return value


def has_other_names(box, rel):
    """Does the file `rel` of the checkout that `box` (a Port) gives an adapter have another name on the disk (a hard link)? Nothing is read and nothing is
    recorded. The link count is what the OS tells about a file and no name check can: a hard link to a kept file is no link or junction, resolves to itself
    and carries an ordinary name (review E4, 29/10). A verifier checkout (checkout-index) and a materialized snapshot hold no hard link, so such a file was
    not given as part of the artifact: Port.read_text refuses it, and an adapter that reads files it found asks first, to say 'not verified' instead of
    being stopped by the refusal. A function of this module and not a method of the Port: the surface the core offers an adapter is pinned (T23)."""
    try:
        target = safe_file(box.workspace, rel)
    except LedgerError:
        return False                    # a name the port refuses when it is read
    return target.is_file() and target.stat().st_nlink > 1


def left_out_below(box, rel):
    """Does `rel` lie below a folder that was left out of the checkout (the Port's `left_out`, a name with a slash at the end)? Whether it exists cannot be
    told then: the folder is not listed, and the Port says 'exists' only because it must answer something for a kept name. A function of this module for the
    same reason as has_other_names: the surface of the Port is pinned."""
    return isinstance(rel, str) and any(rel.startswith(name) for name in box._left_out if name.endswith('/'))


class Port:
    """The only door from an adapter to anything. Every refusal raises AdapterViolation and is also kept (so a refusal the adapter swallows
    is still recorded)."""

    def __init__(self, workspace, grant, adapter, clock=time.monotonic, left_out=()):
        """`left_out`: names of the artifact that the checkout does not hold because the snapshot rules keep them from every reader (the identity of a
        folder without Git names them, a folder with a slash at the end, artifact.py): they answer as a kept name does in a Git checkout, 'it exists, what
        it says is not checked'. What lies below a folder that was left out cannot be told (it is not listed): it answers the same."""
        self._root = Path(workspace).resolve()
        self._grant = copy.deepcopy(grant)
        self._adapter = adapter
        self._clock = clock
        self._deadline = clock() + self._grant['max_minutes'] * 60
        self._left_out = tuple(left_out)
        self._violations, self._retries, self._calls, self._read, self._listing, self._kept = [], 0, 0, set(), None, set()

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
        except ControlAlias:            # the name looks ordinary, but on disk it is a kept file or folder (a Windows short name such as ENV~1.EXA)
            self._refuse('read', 'read_scope', f'{str(rel)[:200]!r} reaches a control or credential path (.git, .onecrew, .ssh, .aws, .env*) under another '
                                               'name, a Windows short name: its content is never read')
        except LedgerError:
            kept = kept_reason(rel)
            why = (f'is {kept}' if kept else 'goes through a link or a junction, or resolves outside the checkout; an adapter reads inside the checkout only'
                   if not _leaves(rel) else 'is outside the checkout of the artifact; an adapter reads inside it only')
            self._refuse('read', 'read_scope', f'{str(rel)[:200]!r} {why}')
        return target, PurePosixPath(text).as_posix()

    def files(self):
        """Every file of the checkout an adapter may read (posix paths relative to the workspace), sorted. A path that differs only in case is
        another path. A name the snapshot rules keep from every reader (kept_reason: .env*, .git, .onecrew, .ssh, .aws, a device name, a path over
        240 characters) is left out, a folder with what it holds, and does not stop the run (beta report B5, 29/10): reading it is still refused.
        A link or a junction still stops the run, whatever its name: a kept name does not hide one (review R14, 29/10). A file that has another name
        (a hard link) is listed like any other; read_text refuses it, and has_other_names(box, rel) tells it beforehand (review E4, 29/10)."""
        def withheld(rel):              # a name found by the walk is inside the checkout: any refusal of the snapshot rules keeps it
            try:
                scoped_path(rel)
                return False
            except LedgerError:
                return True
        if self._listing is None:
            found, kept = [], {name.rstrip('/') for name in self._left_out}
            for base, dirs, names_ in os.walk(self._root):
                self._tick()
                here = Path(base).relative_to(self._root)
                for name in list(dirs):
                    rel = (here / name).as_posix()
                    if withheld(rel): self._keep(rel, Path(base) / name, kept); dirs.remove(name)     # not walked: nothing below it is listed or read
                    else: self._safe(rel)
                for name in names_:
                    rel = (here / name).as_posix()
                    if withheld(rel): self._keep(rel, Path(base) / name, kept); continue
                    self._safe(rel)
                    found.append(rel)
                    if len(found) > MAX_FILES: raise Inconclusive(f'more than {MAX_FILES} files in the checkout')
            self._listing, self._kept = sorted(found), kept
        return list(self._listing)

    def _keep(self, rel, path, kept):
        """A kept name is left out of the listing, not refused. A link or a junction under it is not a kept file: it is a scope violation, judged as
        one (it is the link that is refused, not the name), so the name cannot hide it."""
        if is_link(path):
            self._refuse('read', 'read_scope', f'{rel!r} is a link or a junction (its name is also one an adapter may not read); an adapter follows no link')
        kept.add(rel)

    def _kept_exists(self, key):
        """Does the kept path `key` exist? Answered from the walk, or below a kept folder that was not walked from the disk without following a
        link; nothing is opened."""
        self.files()
        if key in self._kept or any(k.startswith(key.rstrip('/') + '/') for k in self._kept): return True
        if not any(key.startswith(k + '/') for k in self._kept): return False
        if any(key.startswith(name) for name in self._left_out if name.endswith('/')): return True      # below a folder left out of the checkout: it cannot be told, it is not read
        target = self._root
        for part in key.split('/'):
            target = target / part
            if target.is_symlink() or (hasattr(target, 'is_junction') and target.is_junction()): return False
        return target.exists()

    def exists(self, rel):
        """Is `rel` a file or a folder of the checkout? A kept name (see files) is answered by name only: its content is not read."""
        if kept_reason(rel): return self._kept_exists(PurePosixPath(rel).as_posix())
        _, key = self._safe(rel)
        listing = self.files()
        if key in set(listing): return True
        prefix = key.rstrip('/') + '/'
        return any(f.startswith(prefix) for f in listing)

    def read_text(self, rel, limit=MAX_READ):
        self._tick()
        target, key = self._safe(rel)
        if not target.is_file(): raise FileNotFoundError(key)
        if target.stat().st_nlink > 1: self._refuse('read', 'read_scope', f'{key!r} {HARD_LINK}')
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


def run(ledger, name, revision, plan_sha, milestone, directory, evidence_context=None, *, deadline=None):
    """Run the milestone's adapter on a clean checkout of the artifact; returns (receipt_blob, receipt)."""
    adapter = get(milestone['verifier']['type'])
    directory = Path(directory).resolve()
    if not directory.is_dir(): raise LedgerError('Verifier working directory does not exist: ' + str(directory))
    scratch = tempfile.mkdtemp(prefix='ocv-')
    try:
        workspace, before, proof = artifact.capture(ledger, directory, scratch)
        return _run(ledger, adapter, name, revision, plan_sha, milestone, directory, before, scratch, workspace, proof, evidence_context, deadline=deadline)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _run(ledger, adapter, name, revision, plan_sha, milestone, directory, before, scratch, workspace, proof, evidence_context=None, *, deadline=None):
    config = milestone['verifier']['config']
    own = {k: v for k, v in config.items() if k != 'authority'}
    from .. import verification_evidence
    binding = verification_evidence.for_receipt(ledger, evidence_context, milestone, before) if evidence_context else None
    top = Path(scratch) / 'src'
    granted = copy.deepcopy(config['authority'])
    if deadline is not None:
        left = (dt.datetime.fromisoformat(deadline) - dt.datetime.now(dt.timezone.utc)).total_seconds()
        if left <= 0: raise LedgerError('The original root deadline elapsed before verifier adapter dispatch.')
        granted['max_minutes'] = min(granted['max_minutes'], left / 60)
    box = Port(workspace, granted, adapter.NAME, left_out=proof.get('artifact_kept', ()))
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
    if binding is not None: receipt['evidence_binding'] = binding
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
