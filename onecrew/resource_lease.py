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
- The claim id is not a credential by itself (`status` shows it): renewing a claim, retrying as a waiter and `release` must come from the
  holder's own process (pid -> identity incl. creation time must equal the stored one); a mismatch changes nothing.
- A renewal asks for the mode already held; a different mode is refused (release and claim again). Every answer states the mode.
- A lease is released only by the holder's explicit `release`, or by `reconcile` after the holder's process death is confirmed (same
  identity probe as the supervisor: pid + creation time). An unknown probe (other machine, no access) never releases.
It builds on the control layer's pieces (process identity/probe, durable atomic write) and adds no ledger, engine or scheduler."""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
from pathlib import Path
import re
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
        try: return self._probe(who.get('identity'))
        except Exception: return 'unknown'

    def _state(self, holder):
        proc = self._alive(holder)
        expired = self.clock() >= _stamp(holder['until'])
        if proc == 'dead': state = 'dead_unreleased'
        elif proc == 'alive': state = 'expired_holder_alive' if expired else 'held'
        else: state = 'expired_holder_unknown' if expired else 'held_holder_unknown'
        return proc, state

    def _require_holder(self, row, pid, what):
        """The claim id is not a credential: the caller's process identity must equal the stored one."""
        try: mine = self._identity(os.getpid() if pid is None else int(pid))
        except Exception as error:
            raise LedgerError(f'{what} refused: the caller process identity cannot be read ({type(error).__name__}); nothing was changed.')
        if mine != row.get('identity'):
            raise LedgerError(f'{what} refused: {row["claim"]} belongs to another process (pid {row["identity"].get("pid")}); '
                              'only its own process may renew or release it. Nothing was changed.')

    # --- reconcile (the only release without the holder's word) -----------------------------------------------------------
    def _reconcile(self, key, entry):
        changed = False
        for who, label in (('holders', 'released_after_death'), ('waiters', 'waiter_gone')):
            keep = []
            for row in entry[who]:
                if self._alive(row) == 'dead':
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

    def reconcile(self):
        with self._locked():
            data = self._load(); changed = False
            for key, entry in data['resources'].items(): changed |= self._reconcile(key, entry)
            if changed: self._save(data)
            return changed

    # --- claim / release -------------------------------------------------------------------------------------------------
    def claim(self, resource, *, mode='write', session=None, plan=None, state_root=None, pid=None, ttl=DEFAULT_TTL, claim_id=None):
        """Ask for a resource. Returns {'status': 'granted'|'waiting', 'claim': id, ...}; call again with the same claim id to retry."""
        key = self._key(resource); mode = _mode(mode)
        if ttl <= 0: raise LedgerError('ttl must be positive.')
        with self._locked():
            data = self._load()
            entry = data['resources'].setdefault(key, {'holders': [], 'waiters': []})
            self._reconcile(key, entry)
            claim_id = claim_id or 'LS-' + uuid.uuid4().hex[:12]
            mine = next((r for r in entry['holders'] if r['claim'] == claim_id), None)
            if mine:
                self._require_holder(mine, pid, 'Renewal')
                if mine['mode'] != mode:
                    raise LedgerError(f'Renewal refused: {claim_id} holds {key!r} as {mine["mode"]} and {mode} was asked; '
                                      'release it and claim again. Nothing was changed.')
                mine['until'] = (self.clock() + dt.timedelta(seconds=ttl)).isoformat(); mine['ttl'] = ttl   # renewal by the holder
                self._save(data); return {'status': 'granted', 'claim': claim_id, 'resource': key, 'mode': mine['mode'], 'until': mine['until']}
            queued = next((r for r in entry['waiters'] if r['claim'] == claim_id), None)
            if queued:
                self._require_holder(queued, pid, 'Retry')
                if queued['mode'] != mode:
                    raise LedgerError(f'Retry refused: {claim_id} waits for {key!r} as {queued["mode"]} and {mode} was asked; '
                                      'withdraw it and claim again. Nothing was changed.')
                self._save(data)
                return {'status': 'waiting', 'claim': claim_id, 'resource': key, 'mode': queued['mode'], 'position': entry['waiters'].index(queued) + 1,
                        'held_by': [self._who(h) for h in entry['holders']]}
            pid = os.getpid() if pid is None else int(pid)
            row = {'claim': claim_id, 'mode': mode, 'session': session, 'plan': plan,
                   'state_root': str(state_root) if state_root is not None else None,
                   'pid': pid, 'identity': self._identity(pid), 'ttl': ttl, 'asked_at': self.clock().isoformat()}
            if not entry['waiters'] and _compatible(mode, entry['holders']):
                row['since'] = self.clock().isoformat(); row['until'] = (self.clock() + dt.timedelta(seconds=ttl)).isoformat()
                entry['holders'].append(row); self._log('claimed', key, claim=claim_id, session=session, plan=plan, mode=mode, pid=pid)
                result = {'status': 'granted', 'claim': claim_id, 'resource': key, 'mode': mode, 'until': row['until']}
            else:
                entry['waiters'].append(row); self._log('waiting', key, claim=claim_id, session=session, plan=plan, mode=mode, pid=pid)
                result = {'status': 'waiting', 'claim': claim_id, 'resource': key, 'mode': mode, 'position': len(entry['waiters']),
                          'held_by': [self._who(h) for h in entry['holders']]}
            self._save(data)
            return result

    def release(self, resource, claim_id, pid):
        """The holder's explicit release (or a waiter withdrawing), from the holder's own process (`pid`). Anyone else is refused; expiry never releases."""
        key = self._key(resource)
        with self._locked():
            data = self._load(); entry = data['resources'].get(key) or {'holders': [], 'waiters': []}
            for who, label in (('holders', 'released'), ('waiters', 'withdrawn')):
                row = next((r for r in entry[who] if r['claim'] == claim_id), None)
                if row:
                    self._require_holder(row, pid, 'Release')
                    entry[who].remove(row); self._log(label, key, claim=claim_id, session=row.get('session'), plan=row.get('plan'))
                    self._reconcile(key, entry); data['resources'][key] = entry; self._save(data)
                    return {'status': label, 'claim': claim_id}
            raise LedgerError(f'{claim_id} holds nothing on {key!r}; only the holder releases (a lease is never freed by expiry).')

    # --- view ------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _who(row):
        return {'claim': row['claim'], 'mode': row['mode'], 'session': row.get('session'), 'plan': row.get('plan'),
                'state_root': row.get('state_root'), 'pid': row['identity'].get('pid'), 'since': row.get('since') or row.get('asked_at'),
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


def main(argv=None):
    parser = argparse.ArgumentParser(prog='onecrew.resource_lease', description='Machine-level leases for heavy shared resources.')
    parser.add_argument('--home', help='lease folder (default: ONECREW_LEASE_HOME or ~/.onecrew/leases)')
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('status').add_argument('resource', nargs='?')
    sub.add_parser('declare').add_argument('names', nargs='+')
    c = sub.add_parser('claim'); c.add_argument('resource'); c.add_argument('--mode', default='write'); c.add_argument('--session')
    c.add_argument('--plan'); c.add_argument('--state-root'); c.add_argument('--pid', type=int, required=True, help='the process that does the work')
    c.add_argument('--ttl', type=int, default=DEFAULT_TTL); c.add_argument('--claim')
    r = sub.add_parser('release'); r.add_argument('resource'); r.add_argument('claim')
    r.add_argument('--pid', type=int, required=True, help='the holder process (must be the one that claimed)')
    sub.add_parser('reconcile')
    args = parser.parse_args(argv)
    leases = Leases(args.home)
    try:
        if args.cmd == 'status': result = leases.status(args.resource)
        elif args.cmd == 'declare': result = {'managed': leases.declare(args.names)}
        elif args.cmd == 'claim':
            result = leases.claim(args.resource, mode=args.mode, session=args.session, plan=args.plan, state_root=args.state_root,
                                  pid=args.pid, ttl=args.ttl, claim_id=args.claim)
        elif args.cmd == 'release': result = leases.release(args.resource, args.claim, args.pid)
        else: result = {'changed': leases.reconcile()}
    except LedgerError as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False)); return 2
    print(json.dumps(result, ensure_ascii=False, indent=1)); return 0 if result.get('status') != 'waiting' else 3


if __name__ == '__main__':
    sys.exit(main())
