"""Machine-level leases for heavy shared resources (DEV31 slice C, issue #32).

`resources` labels in a plan only keep nodes apart inside ONE plan. A gate run, an emulator, a build dir or `db:dev` is shared by
every session, plan and state root on the machine, so its lease lives in ONE small file per machine (not per state root):
`<home>/leases.json` plus an append-only `<home>/lease-events.jsonl` that keeps what happened. `<home>` is `ONECREW_LEASE_HOME`, else
`~/.onecrew/leases` (outside AppData on purpose, same reason as the host home).

Rules (each is a test in tests/test_dev31_resources.py):
- Only resources the user declared (`declare`, stored in `managed.json`) are leased; any other name is refused, never silently claimed.
- The key is the normalized name (casefold, trimmed, inner whitespace collapsed), so every state root sees the same lease.
- `write` is exclusive; `read` (light) is shared with other readers and waits while a writer holds it. FIFO: nobody jumps the queue.
- A holder that cannot get the resource is recorded as a waiter (visible in `status`), and gets it when `claim` is called again with
  the same claim id after the holders are gone. Nothing fails silently and nothing is retried in the background.
- `until` is advice for people, not a release: a lease past `until` whose holder process is alive stays held ("expired, holder alive").
- The claim id is not a credential (`status` shows it) and neither is a pid the caller names. A granted or queued claim returns a secret
  token ONCE; only its sha256 is stored. Renewing, retrying as a waiter, withdrawing and `release` require that token (a missing or wrong
  one changes nothing). The pid stays only the liveness signal of the work process. `status` and the events never show a token.
- A renewal asks for the mode already held; a different mode is refused (release and claim again). Every answer states the mode.
- A lease is released only by the holder's explicit `release`, or by `reconcile` after the holder's process death is confirmed (same
  identity probe as the supervisor: pid + creation time). An unknown probe (other machine, no access) never releases.
It builds on the control layer's pieces (process identity/probe, durable atomic write) and adds no ledger, engine or scheduler."""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
import uuid

from .ledger import LedgerError, canonical
from .snapshots import durable_write

MODES = ('write', 'read')
ALIASES = {'exclusive': 'write', 'heavy': 'write', 'light': 'read', 'shared': 'read'}
DEFAULT_TTL = 3600
LOCK_WAIT = 10.0
LOCK_UNREADABLE_STALE = 300.0   # a lock with no readable owner token is stolen only after this long (a live owner is never judged by age)


class Unmanaged(LedgerError):
    """The resource is outside the declared domain: OneCrew does not lease it."""


def home():
    configured = os.environ.get('ONECREW_LEASE_HOME')
    base = Path(configured) if configured else Path.home() / '.onecrew' / 'leases'
    base.mkdir(parents=True, exist_ok=True)
    return base


def normalize(name):
    text = re.sub(r'\s+', ' ', str(name or '')).strip().casefold()
    if not text or len(text) > 120 or any(ord(c) < 32 for c in text):
        raise LedgerError('A resource name must be 1-120 printable characters.')
    return text


def _mode(mode):
    mode = ALIASES.get(str(mode).casefold(), str(mode).casefold())
    if mode not in MODES:
        raise LedgerError(f'Unknown claim mode {mode!r}; use write (exclusive) or read (shared).')
    return mode


def _stamp(value):
    value = dt.datetime.fromisoformat(value)
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def _compatible(mode, holders):
    return all(h['mode'] == 'read' for h in holders) if mode == 'read' else not holders


class Leases:
    def __init__(self, base=None, *, domain=None, clock=None, probe_fn=None, identity_fn=None):
        self.base = Path(base) if base is not None else home()
        self.base.mkdir(parents=True, exist_ok=True)
        self.domain = None if domain is None else {normalize(d) for d in domain}
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
        from .process_core import identity, probe
        self._probe = probe_fn or probe
        self._identity = identity_fn or identity

    # --- storage ---------------------------------------------------------------------------------------------------------
    def _owner_token(self):
        try: ident = self._identity(os.getpid())
        except Exception: ident = None
        return {'pid': os.getpid(), 'identity': ident, 'nonce': uuid.uuid4().hex}

    @staticmethod
    def _read_token(lock):
        try:
            token = json.loads(lock.read_text(encoding='utf-8'))
            return token if isinstance(token, dict) and 'nonce' in token else None
        except (OSError, ValueError): return None

    def _lock_is_stale(self, lock):
        """Stale only when its owner process is confirmed dead, or the file carries no readable owner and is very old."""
        token = self._read_token(lock)
        if token is None:
            try: return time.time() - lock.stat().st_mtime > LOCK_UNREADABLE_STALE, None
            except OSError: return False, None
        try: dead = token.get('identity') is not None and self._probe(token['identity']) == 'dead'
        except Exception: dead = False
        return dead, token

    @contextlib.contextmanager
    def _locked(self):
        lock = self.base / 'leases.lock'
        mine = self._owner_token(); payload = json.dumps(mine).encode('utf-8')
        deadline = time.monotonic() + LOCK_WAIT
        while True:
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try: os.write(fd, payload)
                except BaseException:
                    os.close(fd); lock.unlink(missing_ok=True); raise
                os.close(fd); break
            except FileExistsError:
                with contextlib.suppress(OSError):
                    stale, seen = self._lock_is_stale(lock)
                    # unlink only the very lock that was judged stale (a lock another caller just created is left alone)
                    if stale and self._read_token(lock) == seen: lock.unlink()
                if time.monotonic() >= deadline: raise LedgerError('The lease store is busy; nothing was changed, try again.')
                time.sleep(.02)
        try: yield
        finally:
            with contextlib.suppress(OSError):
                if self._read_token(lock) == mine: lock.unlink()    # never delete a lock that is someone else's now

    def _load(self):
        path = self.base / 'leases.json'
        if not path.is_file(): return {'resources': {}}
        try: data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as error:
            raise LedgerError(f'{path} cannot be read ({type(error).__name__}); it was left as it is.')
        if not isinstance(data, dict) or not isinstance(data.get('resources'), dict):
            raise LedgerError(f'{path} is malformed; it was left as it is.')
        return data

    def _save(self, data):
        durable_write(self.base / 'leases.json', canonical(data).encode('utf-8'))

    def _log(self, kind, key, **fields):
        row = {'at': self.clock().isoformat(), 'event': kind, 'resource': key, **fields}
        with (self.base / 'lease-events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')

    def events(self, resource=None):
        path = self.base / 'lease-events.jsonl'
        if not path.is_file(): return []
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        return [r for r in rows if resource is None or r['resource'] == normalize(resource)]

    # --- domain ----------------------------------------------------------------------------------------------------------
    def managed(self):
        if self.domain is not None: return sorted(self.domain)
        path = self.base / 'managed.json'
        try: return sorted(normalize(x) for x in json.loads(path.read_text(encoding='utf-8')).get('resources', [])) if path.is_file() else []
        except (OSError, ValueError, AttributeError): raise LedgerError(f'{path} cannot be read; no resource is leased until it is fixed.')

    def declare(self, names):
        """The user's choice of resources OneCrew may lease (adds to the list)."""
        with self._locked():
            current = set(self.managed()) | {normalize(n) for n in names}
            durable_write(self.base / 'managed.json', canonical({'resources': sorted(current)}).encode('utf-8'))
        self.domain = None
        return sorted(current)

    def _key(self, name):
        key = normalize(name)
        if key not in self.managed():
            raise Unmanaged(f'{key!r} is not a resource OneCrew manages (declare it first); nothing was claimed.')
        return key

    # --- state of one holder ---------------------------------------------------------------------------------------------
    def _alive(self, who):
        ident = who.get('identity')
        if isinstance(ident, dict) and ident.get('unidentified'):
            return self._unidentified(ident)
        try: return self._probe(ident)
        except Exception: return 'unknown'

    @staticmethod
    def _unidentified(ident):
        """A worker whose creation time could not be read: only the pid is known, so only 'no such process' is a confirmed death
        ('dead' frees); a process that answers cannot be proven to be the same one, so it is never called alive either ('unknown' keeps)."""
        import socket
        from .process_core import exists
        if ident.get('host') != socket.gethostname(): return 'unknown'
        try: return 'dead' if exists(ident['pid']) == 'dead' else 'unknown'
        except Exception: return 'unknown'

    def _state(self, holder):
        proc = self._alive(holder)
        expired = self.clock() >= _stamp(holder['until'])
        if proc == 'dead':
            state = 'dead_unreleased'
            if isinstance(holder.get('attempt_ref'), dict):
                worker = self._attempt_worker(holder)       # read-only: what the next reconcile would do with this row
                if worker == 'unknown' or (isinstance(worker, dict) and worker.get('unidentified')): state = 'holder_dead_worker_unknown'
                elif worker is not None: state = 'holder_dead_worker_alive'
        elif proc == 'alive': state = 'expired_holder_alive' if expired else 'held'
        else: state = 'expired_holder_unknown' if expired else 'held_holder_unknown'
        return proc, state

    @staticmethod
    def _token_sha(token): return hashlib.sha256(str(token).encode('utf-8')).hexdigest()

    def _require_token(self, row, token, what):
        """The capability check: the caller proves it owns the claim with the secret returned when it was granted or queued."""
        if not token or not hmac.compare_digest(self._token_sha(token), str(row.get('token_sha') or '')):
            raise LedgerError(f'{what} refused: {row["claim"]} needs its claim token (returned once when it was claimed); '
                              'a claim id or a pid is not enough. Nothing was changed.')

    # --- reconcile (the only release without the holder's word) -----------------------------------------------------------
    def _reconcile(self, key, entry):
        changed = False
        for who, label in (('holders', 'released_after_death'), ('waiters', 'waiter_gone')):
            keep = []
            for row in entry[who]:
                if self._alive(row) == 'dead':
                    worker = self._attempt_worker(row) if who == 'holders' else None
                    if worker is not None:
                        # the engine that held this claim died, but the worker its attempt launched still runs: the lease moves to the
                        # worker (never freed on doubt: a failed lookup answers 'unknown' and the row is kept as it is)
                        if worker != 'unknown':
                            row['pid'] = int(worker['pid']); row['identity'] = worker
                            self._log('rebound', key, claim=row['claim'], session=row.get('session'), plan=row.get('plan'), pid=row['pid'],
                                      note='the holder died; the live worker of its launched attempt keeps the lease')
                            changed = True
                        keep.append(row); continue
                    self._log(label, key, claim=row['claim'], session=row.get('session'), plan=row.get('plan'),
                              state_root=row.get('state_root'), pid=row['identity'].get('pid'),
                              note='process death confirmed; the lease was not released by the holder')
                    changed = True
                else: keep.append(row)
            entry[who] = keep
        while entry['waiters'] and _compatible(entry['waiters'][0]['mode'], entry['holders']):
            row = entry['waiters'].pop(0)
            row['since'] = self.clock().isoformat(); row['until'] = (self.clock() + dt.timedelta(seconds=row['ttl'])).isoformat()
            entry['holders'].append(row); changed = True
            self._log('granted', key, claim=row['claim'], session=row.get('session'), plan=row.get('plan'), mode=row['mode'])
        return changed

    def _attempt_worker(self, row):
        """A dead holder row that names its attempt (state root + task + node unit): the worker Control recorded for that attempt, when it
        is alive (identity dict) or the lookup cannot say ('unknown': the row is kept). None = no launched worker is left, free the row.
        Read-only: the ledger is opened with mode=ro."""
        ref = row.get('attempt_ref')
        if not isinstance(ref, dict): return None
        try:
            import sqlite3
            db = Path(ref['state_root']) / 'ledger.sqlite3'
            if not db.is_file(): return 'unknown'
            conn = sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
            try:
                found = conn.execute("SELECT identity FROM attempts WHERE task_id=? AND status IN ('running','unknown') AND identity IS NOT NULL "
                                     "AND json_extract(operation,'$.unit')=? ORDER BY created_at DESC LIMIT 1", (ref['task_id'], ref['unit'])).fetchone()
            finally: conn.close()
            if not found: return None
            worker = worker_identity(json.loads(found[0]))
            if worker is None: return None
            if worker.get('unidentified'): return None if self._unidentified(worker) == 'dead' else worker   # cannot tell: kept
            return worker if self._alive({'identity': worker}) != 'dead' else None
        except Exception:
            return 'unknown'

    def reconcile(self):
        with self._locked():
            data = self._load(); changed = False
            for key, entry in data['resources'].items(): changed |= self._reconcile(key, entry)
            if changed: self._save(data)
            return changed

    # --- claim / release -------------------------------------------------------------------------------------------------
    def claim(self, resource, *, mode='write', session=None, plan=None, state_root=None, pid=None, ttl=DEFAULT_TTL, claim_id=None, token=None,
              only_own=False, project_id=None, project=None, attempt_ref=None):
        """Ask for a resource. Returns {'status': 'granted'|'waiting', 'claim': id, 'token': secret, ...}; the token is shown once, on the
        answer that creates the claim. Call again with the same claim id AND token to renew or retry (no token is returned again).
        `only_own` (the engine seam): a holder row whose work process is ANOTHER live process is not renewed with a token the caller
        merely read from a shared file; the answer is `waiting` with `foreign_holder` and nothing is changed."""
        key = self._key(resource); mode = _mode(mode)
        if ttl <= 0: raise LedgerError('ttl must be positive.')
        with self._locked():
            data = self._load()
            entry = data['resources'].setdefault(key, {'holders': [], 'waiters': []})
            self._reconcile(key, entry)
            claim_id = claim_id or 'LS-' + uuid.uuid4().hex[:12]
            mine = next((r for r in entry['holders'] if r['claim'] == claim_id), None)
            if mine and only_own:
                me = os.getpid() if pid is None else int(pid)
                try: my_identity = self._identity(me)
                except Exception: my_identity = None
                theirs = mine.get('identity')
                other = mine.get('pid') != me or (theirs is not None and my_identity is not None and theirs != my_identity)
                if other and self._alive(mine) == 'alive':
                    return {'status': 'waiting', 'claim': claim_id, 'resource': key, 'mode': mine['mode'], 'foreign_holder': mine.get('pid'),
                            'reason': f'{key!r} is held by another engine step of this node (pid {mine.get("pid")}); nothing was changed'}
            if mine:
                self._require_token(mine, token, 'Renewal')
                if mine['mode'] != mode:
                    raise LedgerError(f'Renewal refused: {claim_id} holds {key!r} as {mine["mode"]} and {mode} was asked; '
                                      'release it and claim again. Nothing was changed.')
                mine['until'] = (self.clock() + dt.timedelta(seconds=ttl)).isoformat(); mine['ttl'] = ttl   # renewal by the holder
                self._save(data); return {'status': 'granted', 'claim': claim_id, 'resource': key, 'mode': mine['mode'], 'until': mine['until']}
            queued = next((r for r in entry['waiters'] if r['claim'] == claim_id), None)
            if queued:
                self._require_token(queued, token, 'Retry')
                if queued['mode'] != mode:
                    raise LedgerError(f'Retry refused: {claim_id} waits for {key!r} as {queued["mode"]} and {mode} was asked; '
                                      'withdraw it and claim again. Nothing was changed.')
                self._save(data)
                return {'status': 'waiting', 'claim': claim_id, 'resource': key, 'mode': queued['mode'], 'position': entry['waiters'].index(queued) + 1,
                        'held_by': [self._who(h) for h in entry['holders']]}
            pid = os.getpid() if pid is None else int(pid)
            secret = secrets.token_urlsafe(32)
            row = {'claim': claim_id, 'token_sha': self._token_sha(secret), 'mode': mode, 'session': session, 'plan': plan,
                   'state_root': str(state_root) if state_root is not None else None,
                   'pid': pid, 'identity': self._identity(pid), 'ttl': ttl, 'asked_at': self.clock().isoformat()}
            if project_id: row['project_id'] = str(project_id)
            if project: row['project'] = str(project)
            if attempt_ref: row['attempt_ref'] = attempt_ref
            if not entry['waiters'] and _compatible(mode, entry['holders']):
                row['since'] = self.clock().isoformat(); row['until'] = (self.clock() + dt.timedelta(seconds=ttl)).isoformat()
                entry['holders'].append(row); self._log('claimed', key, claim=claim_id, session=session, plan=plan, mode=mode, pid=pid)
                result = {'status': 'granted', 'claim': claim_id, 'token': secret, 'resource': key, 'mode': mode, 'until': row['until']}
            else:
                entry['waiters'].append(row); self._log('waiting', key, claim=claim_id, session=session, plan=plan, mode=mode, pid=pid)
                result = {'status': 'waiting', 'claim': claim_id, 'token': secret, 'resource': key, 'mode': mode, 'position': len(entry['waiters']),
                          'held_by': [self._who(h) for h in entry['holders']]}
            self._save(data)
            return result

    def release(self, resource, claim_id, token):
        """The holder's explicit release (or a waiter withdrawing), with the claim's token. Anyone else is refused; expiry never releases."""
        key = self._key(resource)
        with self._locked():
            data = self._load(); entry = data['resources'].get(key) or {'holders': [], 'waiters': []}
            for who, label in (('holders', 'released'), ('waiters', 'withdrawn')):
                row = next((r for r in entry[who] if r['claim'] == claim_id), None)
                if row:
                    self._require_token(row, token, 'Release')
                    entry[who].remove(row); self._log(label, key, claim=claim_id, session=row.get('session'), plan=row.get('plan'))
                    self._reconcile(key, entry); data['resources'][key] = entry; self._save(data)
                    return {'status': label, 'claim': claim_id}
            raise LedgerError(f'{claim_id} holds nothing on {key!r}; only the holder releases (a lease is never freed by expiry).')

    def rebind(self, resource, claim_id, token, pid=None, identity=None):
        """The holder (with its token) moves the liveness of its claim to another process, e.g. the worker an unsettled attempt
        launched. The token stays private and unchanged; only the pid and its creation-time identity change. The claim is then
        freed by `reconcile` only when THAT process's death is confirmed (or by the holder's explicit release)."""
        key = self._key(resource)
        with self._locked():
            data = self._load(); entry = data['resources'].get(key) or {'holders': [], 'waiters': []}
            row = next((r for r in entry['holders'] if r['claim'] == claim_id), None)
            if row is None: raise LedgerError(f'{claim_id} holds nothing on {key!r}; nothing was rebound.')
            self._require_token(row, token, 'Rebind')
            if identity is None: identity = self._identity(int(pid))
            if not isinstance(identity, dict) or identity.get('pid') is None: raise LedgerError('Rebind refused: no process identity; nothing was changed.')
            row['pid'] = int(identity['pid']); row['identity'] = identity
            self._log('rebound', key, claim=claim_id, session=row.get('session'), plan=row.get('plan'), pid=row['pid'],
                      note='liveness moved to the worker of an unsettled attempt; freed only when its death is confirmed')
            data['resources'][key] = entry; self._save(data)
            return {'status': 'rebound', 'claim': claim_id, 'pid': row['pid']}

    # --- view ------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _who(row):
        return {'claim': row['claim'], 'mode': row['mode'], 'session': row.get('session'), 'plan': row.get('plan'),
                'state_root': row.get('state_root'), 'project_id': row.get('project_id'), 'project': row.get('project'),
                'pid': row['identity'].get('pid'), 'since': row.get('since') or row.get('asked_at'),
                'until': row.get('until')}

    def status(self, resource=None):
        """Read-only: who holds, since when, until when, in which state, and who waits. Frees nothing."""
        data = self._load(); out = []
        keys = [self._key(resource)] if resource else sorted(data['resources'])
        for key in keys:
            entry = data['resources'].get(key, {'holders': [], 'waiters': []})
            holders = []
            for h in entry['holders']:
                proc, state = self._state(h)
                holders.append(dict(self._who(h), process=proc, state=state))
            waiters = [dict(self._who(w), position=i + 1, process=self._alive(w)) for i, w in enumerate(entry['waiters'])]
            out.append({'resource': key, 'free': not holders, 'holders': holders, 'waiters': waiters})
        return {'managed': self.managed(), 'resources': out}


# --- the engine seam: a node that carries a DECLARED resource label claims it for its attempt ---------------------------------
def declared_among(labels):
    """The labels (normalized, sorted) that are declared in the machine store. Reads `managed.json` only: nothing is created and
    nothing is claimed for an undeclared label, and with no declared resource the engine is exactly as before."""
    configured = os.environ.get('ONECREW_LEASE_HOME')
    path = (Path(configured) if configured else Path.home() / '.onecrew' / 'leases') / 'managed.json'
    if not labels or not path.is_file(): return []
    try: declared = {normalize(x) for x in json.loads(path.read_text(encoding='utf-8')).get('resources', [])}
    except (OSError, ValueError, AttributeError, LedgerError): return []
    out = set()
    for label in labels:
        with contextlib.suppress(LedgerError):
            if normalize(label) in declared: out.add(normalize(label))
    return sorted(out)


def _store_error(labels):
    """Fail closed: when `managed.json` EXISTS but cannot be read, a node that carries any resources label must not run unleased.
    No file, or a node with no labels, is not an error (today's behaviour)."""
    configured = os.environ.get('ONECREW_LEASE_HOME')
    path = (Path(configured) if configured else Path.home() / '.onecrew' / 'leases') / 'managed.json'
    if not labels or not path.is_file(): return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or not isinstance(data.get('resources', []), list): raise ValueError('not a {"resources": [...]} object')
        for x in data.get('resources', []): normalize(x)
    except (OSError, ValueError, LedgerError) as error:
        return f'lease store unreadable: {path} ({type(error).__name__}: {error}); fix it or remove it'
    return None


def _claim_file(state_root, claim_id):
    return Path(state_root) / 'lease-claims' / (claim_id + '.json')


def node_claim(state_root, key, labels, *, session, plan, ttl, pid=None, project_id=None, project=None, attempt_ref=None):
    """Claim (write = exclusive) every declared label of a node for ONE attempt, in sorted order. The claim id is derived from
    (state root, attempt key, resource) so a later engine step retries the same claim; its token lives in `<state_root>/lease-claims/`
    (private to the engine, never in a view or an event). Returns None when no label is declared, else
    {'status': 'granted'|'waiting', 'held': [(resource, claim, token)], 'reason': ...}. A waiting answer holds nothing else."""
    broken = _store_error(labels)
    if broken: return {'status': 'waiting', 'held': [], 'reason': 'resource_lease: ' + broken}
    names = declared_among(labels)
    if not names: return None
    leases = Leases(); granted = []
    for name in names:
        claim_id = 'LS-' + hashlib.sha256(f'{state_root}|{key}|{name}'.encode('utf-8')).hexdigest()[:16]
        path = _claim_file(state_root, claim_id)
        try: saved = json.loads(path.read_text(encoding='utf-8')).get('token') if path.is_file() else None
        except (OSError, ValueError, AttributeError): saved = None
        try:
            answer = leases.claim(name, mode='write', session=session, plan=plan, state_root=str(state_root),
                                  pid=os.getpid() if pid is None else pid, ttl=ttl, claim_id=claim_id, token=saved, only_own=True,
                                  project_id=project_id, project=project, attempt_ref=attempt_ref)
            if answer.get('token'):
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    durable_write(path, canonical({'resource': name, 'claim': claim_id, 'token': answer['token']}).encode('utf-8'))
                except OSError as error:
                    # never leave a held claim with no stored token: give back what this call just granted (token still in memory)
                    with contextlib.suppress(LedgerError): leases.release(name, claim_id, answer['token'])   # also withdraws a queued claim
                    node_release(state_root, granted)
                    return {'status': 'waiting', 'held': [],
                            'reason': f'resource_lease: the claim token for {name!r} could not be stored in {path} ({error}); the claim was given back, fix the folder and retry'}
                saved = answer['token']
        except LedgerError as error:
            answer = {'status': 'waiting', 'reason': str(error)}
        if answer['status'] == 'granted':
            granted.append((name, claim_id, saved)); continue
        node_release(state_root, granted)
        if answer.get('reason'): why = answer['reason']
        elif answer.get('held_by'):
            h = answer['held_by'][0]
            why = (f"{name!r} is held by plan {h.get('plan')} (session {h.get('session')}, state root {h.get('state_root')}) "
                   f"since {h.get('since')} until {h.get('until')}")
        else: why = f"{name!r} has {answer.get('position', 1)} claim(s) queued ahead"
        return {'status': 'waiting', 'held': [], 'reason': 'resource_lease: ' + why}
    return {'status': 'granted', 'held': granted, 'reason': None}


def node_release(state_root, held):
    """Release the claims of an attempt that finished, was cancelled or never launched. Only the token releases; a refused or failed
    release changes nothing and the holder's confirmed death still frees it (reconcile)."""
    if not held: return
    leases = Leases()
    for name, claim_id, token in held:
        with contextlib.suppress(LedgerError):
            leases.release(name, claim_id, token)
        with contextlib.suppress(OSError):
            _claim_file(state_root, claim_id).unlink()


def worker_identity(recorded):
    """The live worker an attempt recorded with Control.launched (`recorded` = the decoded identity): its `worker` identity, else the
    record itself when it names a pid. A record without a creation time gets one from the running process now. Returns None when no
    worker was recorded or it is not alive (then nothing is left to protect)."""
    if not isinstance(recorded, dict): return None
    rec = recorded.get('worker') if isinstance(recorded.get('worker'), dict) else recorded
    if not isinstance(rec.get('pid'), int): return None
    from .process_core import exists, identity, probe
    import socket
    try:
        if rec.get('created') is None or not rec.get('host'): rec = identity(rec['pid'])
        return rec if probe(rec) != 'dead' else None
    except Exception:
        # the identity could not be read: only a confirmed absence frees; anything else keeps (an unidentified marker the caller holds)
        try:
            if exists(rec['pid']) == 'dead': return None
        except Exception: pass
        return {'pid': rec['pid'], 'host': rec.get('host') or socket.gethostname(), 'unidentified': True}


def node_rebind(state_root, held, worker):
    """An attempt ended UNSETTLED after launching `worker` (identity record): keep its claims and move their liveness to the worker.
    The token stays in `<state_root>/lease-claims/`. Returns True when the claims are kept (also when a rebind itself failed: a held
    claim is never given back while the worker may live; the engine's own death or the worker's still frees it by reconcile)."""
    if not held or not worker: return False
    leases = Leases()
    for name, claim_id, token in held:
        with contextlib.suppress(LedgerError):
            leases.rebind(name, claim_id, token, identity=worker)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(prog='onecrew.resource_lease', description='Machine-level leases for heavy shared resources.')
    parser.add_argument('--home', help='lease folder (default: ONECREW_LEASE_HOME or ~/.onecrew/leases)')
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('status').add_argument('resource', nargs='?')
    sub.add_parser('declare').add_argument('names', nargs='+')
    c = sub.add_parser('claim'); c.add_argument('resource'); c.add_argument('--mode', default='write'); c.add_argument('--session')
    c.add_argument('--plan'); c.add_argument('--state-root'); c.add_argument('--pid', type=int, required=True, help='the process that does the work')
    c.add_argument('--ttl', type=int, default=DEFAULT_TTL); c.add_argument('--claim')
    c.add_argument('--token', help='the claim token, to renew or retry an existing claim')
    r = sub.add_parser('release'); r.add_argument('resource'); r.add_argument('claim')
    r.add_argument('--token', required=True, help='the claim token returned when the claim was made')
    sub.add_parser('reconcile')
    args = parser.parse_args(argv)
    leases = Leases(args.home)
    try:
        if args.cmd == 'status': result = leases.status(args.resource)
        elif args.cmd == 'declare': result = {'managed': leases.declare(args.names)}
        elif args.cmd == 'claim':
            result = leases.claim(args.resource, mode=args.mode, session=args.session, plan=args.plan, state_root=args.state_root,
                                  pid=args.pid, ttl=args.ttl, claim_id=args.claim, token=args.token)
        elif args.cmd == 'release': result = leases.release(args.resource, args.claim, args.token)
        else: result = {'changed': leases.reconcile()}
    except LedgerError as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False)); return 2
    print(json.dumps(result, ensure_ascii=False, indent=1)); return 0 if result.get('status') != 'waiting' else 3


if __name__ == '__main__':
    sys.exit(main())
