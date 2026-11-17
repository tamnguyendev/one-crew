"""DEV31 slice C (issue #32): machine-level leases of heavy shared resources."""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from onecrew.ledger import LedgerError
from onecrew import resource_lease
from onecrew.resource_lease import Leases, Unmanaged

SLEEP = [sys.executable, '-c', 'import time; time.sleep(120)']


class Clock:
    def __init__(self): self.now = dt.datetime(2026, 11, 18, 1, 0, tzinfo=dt.timezone.utc)
    def __call__(self): return self.now
    def advance(self, seconds): self.now += dt.timedelta(seconds=seconds)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'machine'
        self.clock = Clock()
        self.procs = []
        self.addCleanup(self.reap)
        self.leases = self.store()

    def store(self, domain=('gate', 'emulator', 'db:dev')):
        return Leases(self.home, domain=domain, clock=self.clock)

    def child(self):
        proc = subprocess.Popen(SLEEP); self.procs.append(proc); return proc

    def kill(self, proc):
        proc.kill(); proc.wait(10)

    def reap(self):
        for proc in self.procs:
            if proc.poll() is None: proc.kill(); proc.wait(10)


class ResourceLeaseTests(Base):
    def test_exclusive_no_two_heavy(self):
        a, b = self.child(), self.child()
        first = self.leases.claim('gate', session='s1', pid=a.pid)
        second = self.leases.claim('gate', session='s2', pid=b.pid)
        self.assertEqual(first['status'], 'granted')
        self.assertEqual(second['status'], 'waiting')
        self.assertEqual(second['position'], 1)
        self.assertEqual(second['held_by'][0]['session'], 's1')
        view = self.leases.status('gate')['resources'][0]
        self.assertEqual(len(view['holders']), 1)
        self.assertEqual(self.leases.claim('gate', pid=b.pid, claim_id=second['claim'])['status'], 'waiting')  # still waiting, not granted
        self.leases.release('gate', first['claim'], a.pid)
        self.assertEqual(self.leases.claim('gate', pid=b.pid, claim_id=second['claim'])['status'], 'granted')

    def test_light_still_runs(self):
        a, b, c = self.child(), self.child(), self.child()
        self.leases.claim('gate', session='heavy', pid=a.pid)
        # work that claims nothing is not touched at all; another resource is independent; a different resource's reader is free
        self.assertEqual(self.leases.claim('emulator', mode='light', session='light', pid=b.pid)['status'], 'granted')
        self.assertEqual(self.leases.claim('emulator', mode='shared', session='light2', pid=c.pid)['status'], 'granted')
        self.assertTrue(self.leases.status('emulator')['resources'][0]['holders'][0]['mode'] == 'read')

    def test_two_state_roots(self):
        a, b = self.child(), self.child()
        one = Leases(self.home, domain=['gate'], clock=self.clock)
        two = Leases(self.home, domain=['gate'], clock=self.clock)   # another process / state root: same machine folder
        self.assertEqual(one.claim('Gate ', state_root=r'C:\roots\one', pid=a.pid)['status'], 'granted')
        got = two.claim('  GATE', state_root=r'C:\roots\two', pid=b.pid)   # name is normalized: same key
        self.assertEqual(got['status'], 'waiting')
        self.assertEqual(got['held_by'][0]['state_root'], r'C:\roots\one')
        self.assertEqual(two.status('gate')['resources'][0]['holders'][0]['state_root'], r'C:\roots\one')

    def test_lease_expired_process_alive(self):
        a, b = self.child(), self.child()
        held = self.leases.claim('gate', session='slow', pid=a.pid, ttl=60)
        self.clock.advance(3600)
        view = self.leases.status('gate')['resources'][0]
        self.assertFalse(view['free'])
        self.assertEqual(view['holders'][0]['state'], 'expired_holder_alive')
        self.assertEqual(self.leases.claim('gate', session='eager', pid=b.pid)['status'], 'waiting')   # never handed over on expiry
        self.assertFalse(any(e['event'].startswith('released') for e in self.leases.events('gate')))
        self.leases.claim('gate', pid=a.pid, claim_id=held['claim'], ttl=60)   # the holder may renew
        self.assertEqual(self.leases.status('gate')['resources'][0]['holders'][0]['state'], 'held')

    def test_holder_and_waiter_shown(self):
        a, b = self.child(), self.child()
        self.leases.claim('db:dev', session='S-hold', plan='PLAN-1', state_root=r'D:\state\a', pid=a.pid, ttl=600)
        self.leases.claim('db:dev', session='S-wait', plan='PLAN-2', state_root=r'D:\state\b', pid=b.pid)
        view = self.leases.status('db:dev')['resources'][0]
        holder, waiter = view['holders'][0], view['waiters'][0]
        for field, value in (('session', 'S-hold'), ('plan', 'PLAN-1'), ('state_root', r'D:\state\a'), ('pid', a.pid)):
            self.assertEqual(holder[field], value)
        self.assertTrue(holder['since']); self.assertTrue(holder['until']); self.assertEqual(holder['state'], 'held')
        self.assertEqual((waiter['session'], waiter['plan'], waiter['state_root'], waiter['pid'], waiter['position']),
                         ('S-wait', 'PLAN-2', r'D:\state\b', b.pid, 1))

    def test_release_after_death_only(self):
        a, b, c = self.child(), self.child(), self.child()
        held = self.leases.claim('gate', session='h', pid=a.pid, ttl=10)
        self.leases.claim('gate', session='w', pid=b.pid)
        self.clock.advance(1000)                        # long past `until`
        self.assertFalse(self.leases.reconcile())       # expiry alone frees nothing
        self.assertFalse(self.leases.status('gate')['resources'][0]['free'])
        with self.assertRaises(LedgerError): self.leases.release('gate', 'LS-not-the-holder', a.pid)     # only the holder releases
        self.kill(a)
        self.assertEqual(self.leases.status('gate')['resources'][0]['holders'][0]['state'], 'dead_unreleased')
        self.assertTrue(self.leases.reconcile())
        view = self.leases.status('gate')['resources'][0]
        self.assertEqual(view['holders'][0]['session'], 'w')   # the waiter got it after the death was confirmed
        self.assertTrue(any(e['event'] == 'released_after_death' and e['claim'] == held['claim'] for e in self.leases.events('gate')))
        self.assertEqual(self.leases.release('gate', view['holders'][0]['claim'], b.pid)['status'], 'released')   # explicit release works

    def test_crash_recovery(self):
        a, b = self.child(), self.child()
        crashed = self.leases.claim('emulator', session='crash', plan='P', state_root='R', pid=a.pid)
        self.kill(a)                                    # died without releasing
        taken = self.store().claim('emulator', session='next', pid=b.pid)   # next claimant reconciles by itself
        self.assertEqual(taken['status'], 'granted')
        record = [e for e in self.leases.events('emulator') if e['event'] == 'released_after_death']
        self.assertEqual(len(record), 1)
        self.assertEqual((record[0]['claim'], record[0]['session'], record[0]['plan'], record[0]['state_root'], record[0]['pid']),
                         (crashed['claim'], 'crash', 'P', 'R', a.pid))
        self.assertIn('not released by the holder', record[0]['note'])

    def test_outside_domain_not_claimed(self):
        a = self.child()
        with self.assertRaises(Unmanaged): self.leases.claim('printer', pid=a.pid)
        self.assertEqual([r['resource'] for r in self.leases.status()['resources']], [])
        self.assertFalse((self.home / 'leases.json').exists())    # nothing was written for it
        empty = Leases(self.home, clock=self.clock)               # no declared domain at all: nothing is managed
        with self.assertRaises(Unmanaged): empty.claim('gate', pid=a.pid)
        empty.declare(['Gate'])
        self.assertEqual(empty.claim('gate', pid=a.pid)['status'], 'granted')
        with self.assertRaises(Unmanaged): empty.claim('printer', pid=a.pid)

    def test_read_write_dependency(self):
        a, b, c, d = (self.child() for _ in range(4))
        r1 = self.leases.claim('db:dev', mode='read', session='r1', pid=a.pid)
        r2 = self.leases.claim('db:dev', mode='read', session='r2', pid=b.pid)
        self.assertEqual((r1['status'], r2['status']), ('granted', 'granted'))          # two readers share
        w = self.leases.claim('db:dev', mode='write', session='w', pid=c.pid)
        self.assertEqual(w['status'], 'waiting')                                          # a writer waits for the readers
        r3 = self.leases.claim('db:dev', mode='read', session='r3', pid=d.pid)
        self.assertEqual(r3['status'], 'waiting')                                         # no jumping the waiting writer
        self.leases.release('db:dev', r1['claim'], a.pid); self.leases.release('db:dev', r2['claim'], b.pid)
        view = self.leases.status('db:dev')['resources'][0]
        self.assertEqual([h['session'] for h in view['holders']], ['w'])                  # writer holds; the reader waits
        self.assertEqual([x['session'] for x in view['waiters']], ['r3'])
        self.leases.release('db:dev', w['claim'], c.pid)
        self.assertEqual(self.leases.status('db:dev')['resources'][0]['holders'][0]['session'], 'r3')

    def test_cli_status_and_claim(self):
        a = self.child()
        self.assertEqual(resource_lease.main(['--home', str(self.home), 'declare', 'gate']), 0)
        self.assertEqual(resource_lease.main(['--home', str(self.home), 'claim', 'gate', '--pid', str(a.pid), '--session', 'cli']), 0)
        self.assertEqual(resource_lease.main(['--home', str(self.home), 'claim', 'gate', '--pid', str(a.pid)]), 3)   # waits: exit 3
        self.assertEqual(resource_lease.main(['--home', str(self.home), 'claim', 'nope', '--pid', str(a.pid)]), 2)    # unmanaged: refused
        self.assertEqual(resource_lease.main(['--home', str(self.home), 'status']), 0)


class ResourceLeaseReviewTests(Base):
    """Opus review of 9cbafd4: F2 (claim id is not a credential), F3 (renewal keeps the mode), F4 (lock owner token)."""

    def holders(self, resource='gate'):
        return [(h['session'], h['mode']) for h in self.leases.status(resource)['resources'][0]['holders']]

    def test_claim_id_is_not_a_credential(self):
        a, b, other = self.child(), self.child(), self.child()
        held = self.leases.claim('gate', session='A', pid=a.pid)
        wait = self.leases.claim('gate', session='B', pid=b.pid)
        seen = self.leases.status('gate')['resources'][0]['holders'][0]['claim']    # status shows the id to everybody
        self.assertEqual(seen, held['claim'])
        before = (self.home / 'leases.json').read_bytes(); events = len(self.leases.events('gate'))
        with self.assertRaises(LedgerError): self.leases.claim('gate', session='X', pid=other.pid, claim_id=seen)       # impostor renews
        with self.assertRaises(LedgerError): self.leases.release('gate', seen, other.pid)                               # impostor releases
        with self.assertRaises(LedgerError): self.leases.release('gate', seen, b.pid)                                   # another claimant releases
        with self.assertRaises(LedgerError): self.leases.claim('gate', pid=a.pid, claim_id=wait['claim'])               # waiter retried by another process
        with self.assertRaises(LedgerError): self.leases.release('gate', wait['claim'], other.pid)                      # waiter withdrawn by another process
        self.assertEqual((self.home / 'leases.json').read_bytes(), before)    # nothing changed
        self.assertEqual(len(self.leases.events('gate')), events)
        self.assertEqual(self.holders(), [('A', 'write')])
        self.assertEqual(self.leases.claim('gate', pid=a.pid, claim_id=seen)['status'], 'granted')              # the holder still renews
        self.assertEqual(self.leases.release('gate', wait['claim'], b.pid)['status'], 'withdrawn')           # the waiter's own withdrawal
        self.assertEqual(self.leases.release('gate', seen, a.pid)['status'], 'released')                      # the holder's own release
        self.assertEqual(self.holders(), [])

    def test_release_needs_the_holder_pid_in_cli(self):
        a, other = self.child(), self.child()
        base = ['--home', str(self.home)]
        resource_lease.main(base + ['declare', 'gate'])
        held = self.leases.claim('gate', pid=a.pid)
        with self.assertRaises(SystemExit): resource_lease.main(base + ['release', 'gate', held['claim']])     # --pid is required
        self.assertEqual(resource_lease.main(base + ['release', 'gate', held['claim'], '--pid', str(other.pid)]), 2)
        self.assertEqual(self.holders(), [(None, 'write')])
        self.assertEqual(resource_lease.main(base + ['release', 'gate', held['claim'], '--pid', str(a.pid)]), 0)

    def test_renewal_keeps_the_mode(self):
        a, b = self.child(), self.child()
        r1 = self.leases.claim('gate', mode='read', session='R1', pid=a.pid)
        r2 = self.leases.claim('gate', mode='read', session='R2', pid=b.pid)
        self.assertEqual((r1['mode'], r2['mode']), ('read', 'read'))                                    # every grant states its mode
        with self.assertRaises(LedgerError) as raised:
            self.leases.claim('gate', mode='write', session='R1', pid=a.pid, claim_id=r1['claim'])      # a reader cannot renew as writer
        self.assertIn('release it and claim again', str(raised.exception))
        self.assertEqual(sorted(self.holders()), [('R1', 'read'), ('R2', 'read')])
        renewed = self.leases.claim('gate', mode='read', pid=a.pid, claim_id=r1['claim'])
        self.assertEqual((renewed['status'], renewed['mode']), ('granted', 'read'))
        w = self.leases.claim('gate', mode='write', session='W', pid=a.pid)
        self.assertEqual((w['status'], w['mode']), ('waiting', 'write'))
        with self.assertRaises(LedgerError): self.leases.claim('gate', mode='read', pid=a.pid, claim_id=w['claim'])   # waiter retry, other mode
        self.assertEqual(self.leases.claim('gate', mode='write', pid=a.pid, claim_id=w['claim'])['mode'], 'write')

    def lock_path(self): return self.home / 'leases.lock'

    def test_lock_of_a_live_owner_is_never_stolen_by_age(self):
        a = self.child()
        with mock.patch.object(resource_lease, 'LOCK_WAIT', 0.3):
            with self.leases._locked():
                old = time.time() - 3600; os.utime(self.lock_path(), (old, old))     # a long stall inside the lock
                with self.assertRaises(LedgerError): self.store().claim('gate', pid=a.pid)        # busy, not a theft
                self.assertTrue(self.lock_path().exists())
            self.assertFalse(self.lock_path().exists())
            self.assertEqual(self.store().claim('gate', pid=a.pid)['status'], 'granted')

    def test_lock_of_a_dead_owner_is_stolen(self):
        a, dead = self.child(), self.child()
        token = {'pid': dead.pid, 'identity': self.leases._identity(dead.pid), 'nonce': 'x'}
        self.kill(dead)
        self.lock_path().parent.mkdir(parents=True, exist_ok=True); self.lock_path().write_text(json.dumps(token), encoding='utf-8')
        self.assertEqual(self.leases.claim('gate', pid=a.pid)['status'], 'granted')      # fresh file, but its owner is confirmed dead
        self.assertFalse(self.lock_path().exists())

    def test_unreadable_lock_is_stolen_only_when_very_old(self):
        a = self.child()
        self.home.mkdir(parents=True, exist_ok=True); self.lock_path().write_text('not json', encoding='utf-8')
        with mock.patch.object(resource_lease, 'LOCK_WAIT', 0.3):
            with self.assertRaises(LedgerError): self.leases.claim('gate', pid=a.pid)
            old = time.time() - resource_lease.LOCK_UNREADABLE_STALE - 60; os.utime(self.lock_path(), (old, old))
            self.assertEqual(self.leases.claim('gate', pid=a.pid)['status'], 'granted')

    def test_lock_release_keeps_a_foreign_lock(self):
        with self.leases._locked():
            self.lock_path().write_text(json.dumps({'pid': 1, 'identity': None, 'nonce': 'someone-else'}), encoding='utf-8')
        self.assertTrue(self.lock_path().exists())                                         # not ours any more: left alone
        self.assertEqual(json.loads(self.lock_path().read_text(encoding='utf-8'))['nonce'], 'someone-else')


if __name__ == '__main__':
    unittest.main()
