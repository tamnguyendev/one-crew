"""DEV31 slice C (issue #32): machine-level leases of heavy shared resources."""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from onecrew.ledger import LedgerError
from onecrew import resource_lease
from onecrew.resource_lease import Leases, Unmanaged
from onecrew.v2 import engine

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
        self.assertEqual(self.leases.claim('gate', pid=b.pid, claim_id=second['claim'], token=second['token'])['status'], 'waiting')  # still waiting
        self.leases.release('gate', first['claim'], first['token'])
        self.assertEqual(self.leases.claim('gate', pid=b.pid, claim_id=second['claim'], token=second['token'])['status'], 'granted')

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
        self.leases.claim('gate', pid=a.pid, claim_id=held['claim'], token=held['token'], ttl=60)   # the holder may renew
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
        waiter = self.leases.claim('gate', session='w', pid=b.pid)
        self.clock.advance(1000)                       # long past `until`
        self.assertFalse(self.leases.reconcile())       # expiry alone frees nothing
        self.assertFalse(self.leases.status('gate')['resources'][0]['free'])
        with self.assertRaises(LedgerError): self.leases.release('gate', 'LS-not-the-holder', held['token'])     # only the holder releases
        self.kill(a)
        self.assertEqual(self.leases.status('gate')['resources'][0]['holders'][0]['state'], 'dead_unreleased')
        self.assertTrue(self.leases.reconcile())
        view = self.leases.status('gate')['resources'][0]
        self.assertEqual(view['holders'][0]['session'], 'w')   # the waiter got it after the death was confirmed
        self.assertTrue(any(e['event'] == 'released_after_death' and e['claim'] == held['claim'] for e in self.leases.events('gate')))
        self.assertEqual(self.leases.release('gate', view['holders'][0]['claim'], waiter['token'])['status'], 'released')   # explicit release works

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
        self.leases.release('db:dev', r1['claim'], r1['token']); self.leases.release('db:dev', r2['claim'], r2['token'])
        view = self.leases.status('db:dev')['resources'][0]
        self.assertEqual([h['session'] for h in view['holders']], ['w'])                  # writer holds; the reader waits
        self.assertEqual([x['session'] for x in view['waiters']], ['r3'])
        self.leases.release('db:dev', w['claim'], w['token'])
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
        # the impostor knows the claim id AND the live holder's pid (both are visible in `status`) but not the token
        for wrong in (None, '', 'not-the-token', wait['token']):
            with self.assertRaises(LedgerError): self.leases.claim('gate', session='X', pid=a.pid, claim_id=seen, token=wrong)    # renews
            with self.assertRaises(LedgerError): self.leases.release('gate', seen, wrong)                                         # releases
        with self.assertRaises(LedgerError): self.leases.claim('gate', pid=b.pid, claim_id=wait['claim'], token=held['token'])   # retries the waiter
        with self.assertRaises(LedgerError): self.leases.release('gate', wait['claim'], held['token'])                         # withdraws the waiter
        with self.assertRaises(LedgerError): self.leases.claim('gate', pid=b.pid, claim_id=wait['claim'])                       # no token at all
        self.assertEqual((self.home / 'leases.json').read_bytes(), before)    # nothing changed
        self.assertEqual(len(self.leases.events('gate')), events)
        self.assertEqual(self.holders(), [('A', 'write')])
        self.assertEqual(self.leases.claim('gate', pid=a.pid, claim_id=seen, token=held['token'])['status'], 'granted')   # the holder still renews
        self.assertEqual(self.leases.release('gate', wait['claim'], wait['token'])['status'], 'withdrawn')           # the waiter's own withdrawal
        self.assertEqual(self.leases.release('gate', seen, held['token'])['status'], 'released')                      # the holder's own release
        self.assertEqual(self.holders(), [])

    def test_token_is_shown_once_and_never_stored_or_listed(self):
        a, b = self.child(), self.child()
        held = self.leases.claim('gate', session='A', pid=a.pid)
        wait = self.leases.claim('gate', session='B', pid=b.pid)
        self.assertEqual(self.leases.claim('gate', pid=a.pid, claim_id=held['claim'], token=held['token']).get('token'), None)   # not repeated
        tokens = (held['token'], wait['token']); self.assertNotEqual(*tokens); self.assertGreaterEqual(len(held['token']), 40)
        seen = json.dumps(self.leases.status()) + json.dumps(self.leases.events()) + (self.home / 'leases.json').read_text(encoding='utf-8') \
            + (self.home / 'lease-events.jsonl').read_text(encoding='utf-8')
        for token in tokens: self.assertNotIn(token, seen)
        self.assertIn(resource_lease.Leases._token_sha(held['token']), (self.home / 'leases.json').read_text(encoding='utf-8'))   # only the hash

    def test_release_needs_the_token_in_cli(self):
        a, other = self.child(), self.child()
        base = ['--home', str(self.home)]
        resource_lease.main(base + ['declare', 'gate'])
        held = self.leases.claim('gate', pid=a.pid)
        with self.assertRaises(SystemExit): resource_lease.main(base + ['release', 'gate', held['claim']])     # --token is required
        self.assertEqual(resource_lease.main(base + ['release', 'gate', held['claim'], '--token', 'guess']), 2)
        self.assertEqual(resource_lease.main(base + ['claim', 'gate', '--pid', str(a.pid), '--claim', held['claim']]), 2)    # renewal w/o token
        self.assertEqual(self.holders(), [(None, 'write')])
        self.assertEqual(resource_lease.main(base + ['claim', 'gate', '--pid', str(a.pid), '--claim', held['claim'], '--token', held['token']]), 0)
        self.assertEqual(resource_lease.main(base + ['release', 'gate', held['claim'], '--token', held['token']]), 0)

    def test_renewal_keeps_the_mode(self):
        a, b = self.child(), self.child()
        r1 = self.leases.claim('gate', mode='read', session='R1', pid=a.pid)
        r2 = self.leases.claim('gate', mode='read', session='R2', pid=b.pid)
        self.assertEqual((r1['mode'], r2['mode']), ('read', 'read'))                                    # every grant states its mode
        with self.assertRaises(LedgerError) as raised:
            self.leases.claim('gate', mode='write', session='R1', pid=a.pid, claim_id=r1['claim'], token=r1['token'])      # a reader cannot renew as writer
        self.assertIn('release it and claim again', str(raised.exception))
        self.assertEqual(sorted(self.holders()), [('R1', 'read'), ('R2', 'read')])
        renewed = self.leases.claim('gate', mode='read', pid=a.pid, claim_id=r1['claim'], token=r1['token'])
        self.assertEqual((renewed['status'], renewed['mode']), ('granted', 'read'))
        w = self.leases.claim('gate', mode='write', session='W', pid=a.pid)
        self.assertEqual((w['status'], w['mode']), ('waiting', 'write'))
        with self.assertRaises(LedgerError): self.leases.claim('gate', mode='read', pid=a.pid, claim_id=w['claim'], token=w['token'])   # retry, other mode
        self.assertEqual(self.leases.claim('gate', mode='write', pid=a.pid, claim_id=w['claim'], token=w['token'])['mode'], 'write')

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


OK = [sys.executable, '-c', 'print("ok")']
SEAM_CAPS = ['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine', 'parallel-engine', 'execution-mode']
SEAM_OWNED = ['a.txt', 'b.txt', 'c.txt', 'api.py']


def seam_contract(**extra):
    """The smallest contract that passes step 0, self-contained so the wheel can run this module (no v1 test fixture)."""
    value = {'schema_version': 2, 'title': 'Sample', 'size': 'S',
             'understanding': {'restated_goal': 'Do the sample and prove it.', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']},
                               'assumptions': [], 'confidence': 'high', 'unknowns': []},
             'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'the file to work on is there'}],
             'output': ['The sample exists'], 'scope': {'owned': ['a.txt']}, 'non_goals': ['Nothing else'],
             'items': [{'id': 'I1', 'title': 'Do it', 'tier': 'must', 'milestone': 'M1'},
                       {'id': 'S1', 'title': 'Nice to have', 'tier': 'should'}, {'id': 'W1', 'title': 'Never', 'tier': 'wont'}],
             'milestones': [{'id': 'M1', 'title': 'Milestone M1', 'verifier': {'type': 'command', 'config': {'argv': OK}}, 'covers': ['O1']}],
             'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1}, 'profile_version': None}
    return dict(value, **extra)


def seam_node(nid, write=(), depends=(), resources=(), integration=False):
    return {'id': nid, 'goal': 'Produce evidence for O1', 'input': [], 'output': ['Evidence for O1'],
            'acceptance': ['O1'], 'depends': [{'node': upstream, 'requires': 'verified'} for upstream in depends],
            'read': list(write), 'write': list(write), 'resources': list(resources), 'estimate_seconds': [1, 2],
            'execution_cap_seconds': 60, 'budget_calls': 1,
            'checks': [{'id': 'check-' + nid, 'spec': 'Check the declared O1 output of ' + nid}], 'integration': integration}


class EngineLeaseSeam(unittest.TestCase):
    """R2-C: a node whose `resources` carry a resource declared in the MACHINE lease store claims it for its attempt, across state roots.
    Self-contained: a real temp git project, ledger and Control from modules the wheel ships."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self._setup_project(Path(self.temp.name))
        self.machine = Path(self.temp.name) / 'machine'
        os.environ.update(ONECREW_LEASE_HOME=str(self.machine), LOCALAPPDATA=str(Path(self.temp.name) / 'local'),
                          APPDATA=str(Path(self.temp.name) / 'roaming'))
        self.plan_nodes = [seam_node('A', ['a.txt'], resources=['gate']), seam_node('I', depends=['A'], integration=True)]
        self.revise(self.plan_nodes)

    def _setup_project(self, base):
        from onecrew.ledger import Ledger
        from onecrew.snapshots import Snapshots
        from onecrew.control_core import Control, migrate
        from onecrew.v2 import plan as plans
        self.root = base / 'project'; self.root.mkdir()
        self.git('init', '-q'); self.git('config', 'user.name', 'T'); self.git('config', 'user.email', 't@localhost')
        (self.root / 'a.txt').write_text('one\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'base')
        self.ledger = Ledger(self.root, base / 'state')
        env = mock.patch.dict(os.environ); env.start(); self.addCleanup(env.stop)
        for name in ('ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(name, None)
        for name in SEAM_OWNED[1:]: (self.root / name).write_text(name + '\n')
        raw = seam_contract(scope={'owned': list(SEAM_OWNED)}, authority={'edit': True, 'commands': True, 'edit_tests': True,
                                                                          'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']})
        self.root_view = plans.propose(self.ledger, 'P1', raw, 'codex', workflow=True, capabilities=SEAM_CAPS)
        plans.approve(self.ledger, 'P1', 'owner', 'fixture 2.4-C approval')
        os.environ['ONECREW_ACTOR'] = 'codex'
        self.store = Snapshots(self.ledger.state_root); migrate(self.ledger); self.control = Control(self.ledger)

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True).stdout.decode().strip()

    def revise(self, nodes):
        from onecrew.v2 import internal_plan
        return internal_plan.revise(self.ledger, 'P1', nodes, reason='Split work inside the approved scope', evidence=['a.txt:1'])

    def events(self):
        from onecrew.v2 import plan as plans
        with self.ledger.transaction() as conn:
            task = plans.derive(self.ledger, conn, 'P1')['task_id']
        return [(e['kind'], e['payload']) for e in self.ledger.events(task)]

    def started(self):
        return [p for k, p in self.events() if k == 'node.started']

    def attempts(self):
        with self.ledger.transaction() as conn: return conn.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]

    def execute(self, ledger, control, task, item, attempt):
        control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        artifact = self.store.blob(('artifact-' + item['id']).encode())
        receipt = self.store.blob(('executor-' + item['id']).encode())
        control.finish(attempt['id'], attempt['generation'], {'fixture': True, 'artifact': artifact})
        return {'artifact': artifact, 'receipt': receipt}

    def isolated(self, callback=None, capabilities=('start', 'isolate'), name='fixture-isolated-artifact'):
        from onecrew.v2 import executors
        case = self
        class Isolated(executors.Executor):
            declaration = executors.Declaration(name, 'managed', capabilities)
            control = case.control
            def start(self, *args): return (callback or case.execute)(*args)
            def isolate(self, attempt_id): return {'attempt': attempt_id, 'writes': 'scoped candidate only'}
        return Isolated()

    def second_root(self, nodes=None):
        other = type(self)(self._testMethodName)
        self.addCleanup(other.doCleanups)
        other.temp = tempfile.TemporaryDirectory(); other.addCleanup(other.temp.cleanup)
        other._setup_project(Path(other.temp.name))                                # another project + state root, the same machine lease folder
        other.revise(nodes or self.plan_nodes)
        return other

    def holding(self, executor_started, release):
        def hold(ledger, control, task, item, attempt):
            control.launched(attempt['id'], attempt['generation'], {'fixture': True}); executor_started.set()
            if not release.wait(20): raise AssertionError('release missing')
            out = {'artifact': self.store.blob(b'A out'), 'receipt': self.store.blob(b'A receipt')}
            control.finish(attempt['id'], attempt['generation'], out); return out
        return self.isolated(hold)

    def test_declared_resource_holds_a_second_state_root_until_the_first_finishes(self):
        Leases().declare(['gate'])
        other = self.second_root()
        self.assertNotEqual(str(self.ledger.state_root), str(other.ledger.state_root))
        started, release, result = threading.Event(), threading.Event(), {}
        thread = threading.Thread(target=lambda: result.update(engine.step(self.ledger, 'P1', self.holding(started, release), slots=2, _target='A')))
        thread.start()
        try:
            self.assertTrue(started.wait(10))
            view = Leases().status('gate')['resources'][0]
            self.assertEqual(len(view['holders']), 1)
            self.assertEqual(view['holders'][0]['state_root'], str(self.ledger.state_root))
            held = engine.step(other.ledger, 'P1', other.isolated(), slots=2, _target='A')
            self.assertEqual(held['state'], 'waiting')                                    # surfaced like a capacity wait, nothing launched
            reason = ' '.join(held['reasons'])
            self.assertIn('capacity_full: resource_lease', reason)
            self.assertIn(str(self.ledger.state_root), reason); self.assertIn('plan P1', reason); self.assertIn('since', reason); self.assertIn('until', reason)
            self.assertEqual(other.started(), []); self.assertEqual(other.attempts(), 0)
            again = engine.step(other.ledger, 'P1', other.isolated(), slots=2, _target='A')   # the next step retries the same claim: still held
            self.assertEqual(again['state'], 'waiting')
            claims = list((Path(other.ledger.state_root) / 'lease-claims').glob('*.json'))
            self.assertEqual(len(claims), 1)                                              # one claim, retried, not one per step
            tokens = [json.loads(p.read_text(encoding='utf-8'))['token']
                      for p in claims + list((Path(self.ledger.state_root) / 'lease-claims').glob('*.json'))]
            self.assertEqual(len(tokens), 2)
        finally:
            release.set(); thread.join(20)
        self.assertEqual(result['state'], 'produced')
        handed = Leases().status('gate')['resources'][0]['holders']                          # released when the attempt finished: FIFO hands it on
        self.assertEqual([h['state_root'] for h in handed], [str(other.ledger.state_root)])
        self.assertFalse((Path(self.ledger.state_root) / 'lease-claims').exists() and list((Path(self.ledger.state_root) / 'lease-claims').glob('*.json')))
        launched = engine.step(other.ledger, 'P1', other.isolated(), slots=2, _target='A')   # the second root now launches
        self.assertEqual(launched['state'], 'produced')
        self.assertEqual([p['node'] for p in other.started()], ['A'])
        self.assertEqual(Leases().status('gate')['resources'][0]['holders'], [])
        # the secret never reaches a view, an event of either ledger or the lease log
        everything = json.dumps(Leases().status()) + json.dumps(Leases().events()) + json.dumps(self.events()) + json.dumps(other.events()) \
            + json.dumps(engine.state(other.ledger, 'P1'), default=str) + json.dumps(held)
        for token in tokens: self.assertNotIn(token, everything)

    def test_an_undeclared_label_stays_inside_one_plan(self):
        Leases().declare(['emulator'])                                            # 'gate' is not declared: today's behaviour, in-plan only
        other = self.second_root()
        started, release, result = threading.Event(), threading.Event(), {}
        thread = threading.Thread(target=lambda: result.update(engine.step(self.ledger, 'P1', self.holding(started, release), slots=2, _target='A')))
        thread.start()
        try:
            self.assertTrue(started.wait(10))
            self.assertEqual(Leases().status()['resources'], [])                  # nothing was claimed for it
            free = engine.step(other.ledger, 'P1', other.isolated(), slots=2, _target='A')
            self.assertEqual(free['state'], 'produced')                           # another state root is not held by a label nobody declared
        finally:
            release.set(); thread.join(20)
        self.assertEqual(result['state'], 'produced')
        self.assertFalse((Path(self.ledger.state_root) / 'lease-claims').exists())
        self.assertFalse((Path(other.ledger.state_root) / 'lease-claims').exists())

    def test_no_declared_resource_changes_nothing(self):
        self.assertEqual(engine.step(self.ledger, 'P1', self.isolated(), slots=2, _target='A')['state'], 'produced')
        self.assertFalse(self.machine.exists() and any(self.machine.iterdir()))

    def test_a_failing_executor_still_releases_the_lease(self):
        Leases().declare(['gate'])
        def boom(ledger, control, task, item, attempt): raise RuntimeError('worker failed')
        out = engine.step(self.ledger, 'P1', self.isolated(boom), slots=2, _target='A')
        self.assertEqual(out['state'], 'held')
        self.assertEqual(Leases().status('gate')['resources'][0]['holders'], [])


class PageSection(Base):
    """DEV31 on the tracking PAGE: the machine leases the CLI shows (`python -m onecrew.resource_lease status`) are in the page's JSON and drawn by the page script."""

    LONG = 3600 * 24 * 3650

    def setUp(self):
        super().setUp()
        from onecrew.v2 import tracking_host_web
        self.web = tracking_host_web
        patch = mock.patch.dict(os.environ, {'ONECREW_LEASE_HOME': str(self.home), 'LOCALAPPDATA': self.tmp.name, 'APPDATA': self.tmp.name,
                                             'USERPROFILE': self.tmp.name, 'HOME': self.tmp.name})
        patch.start()
        self.addCleanup(patch.stop)

    def real(self, domain=('gate', 'emulator')):
        """A store on the lease home the page reads, with the real clock (the page's own Leases() uses it)."""
        return Leases(self.home, domain=domain)

    def declared(self, *names):
        Leases(self.home).declare(list(names))

    def need_node(self):
        from tests import dev31_page_js
        if not dev31_page_js.node(): self.skipTest('Node unavailable; not verified')
        return dev31_page_js

    def js(self, call, data):
        return self.need_node().run(call, '\nlast={shared_resources:' + json.dumps(data) + '};')

    def test_holder_and_waiter_shown_on_the_page_json_and_script(self):
        self.declared('gate', 'emulator')
        a, b = self.child(), self.child()
        store = Leases(self.home)
        first = store.claim('gate', session='sess-A', plan='plan-A', state_root='D:/root-A', pid=a.pid, ttl=self.LONG)
        second = store.claim('gate', session='sess-B', plan='plan-B', state_root='D:/root-B', pid=b.pid, ttl=self.LONG)
        data = self.web.shared_resources()
        self.assertTrue(data['declared'])
        self.assertIsNone(data['error'])
        by = {r['resource']: r for r in data['resources']}
        self.assertEqual(sorted(by), ['emulator', 'gate'])
        self.assertTrue(by['emulator']['free'])                                              # a declared resource nobody holds is listed as free
        gate = by['gate']
        self.assertFalse(gate['free'])
        [holder] = gate['holders']
        [waiter] = gate['waiters']
        self.assertEqual((holder['plan'], holder['session'], holder['state_root'], holder['pid'], holder['state'], holder['mode']),
                         ('plan-A', 'sess-A', 'D:/root-A', a.pid, 'held', 'write'))
        self.assertTrue(holder['since'] and holder['until'])
        self.assertEqual((waiter['plan'], waiter['session'], waiter['position'], waiter['state_root']), ('plan-B', 'sess-B', 1, 'D:/root-B'))
        self.assertEqual((first['status'], second['status']), ('granted', 'waiting'))
        html = self.js('resSectionHtml()', data)
        for wanted in ('gate', 'đang được giữ', 'Giữ:', 'plan-A', 'sess-A', 'D:/root-A', 'đang giữ', 'Chờ, vị trí', '<b>1</b>', 'plan-B', 'sess-B', 'đến ', 'emulator', 'trống',
                       'Chỉ đọc'):
            self.assertIn(wanted, html)
        self.assertNotIn('<button', html)                                                     # no claim / release / renew control

    def test_lease_states_expired_with_a_live_holder_still_holds_and_is_said_so(self):
        self.declared('gate')
        a = self.child()
        past = Clock()
        past.now = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)
        Leases(self.home, clock=past).claim('gate', session='s', plan='p', pid=a.pid, ttl=60)
        [gate] = self.web.shared_resources()['resources']
        self.assertEqual((gate['free'], gate['holders'][0]['state']), (False, 'expired_holder_alive'))
        self.assertIn('vẫn giữ', gate['holders'][0]['state_label'])
        self.assertIn('vẫn giữ', self.js('resSectionHtml()', self.web.shared_resources()))
        self.kill(a)
        [gate] = self.web.shared_resources()['resources']
        self.assertEqual(gate['holders'][0]['state'], 'dead_unreleased')                     # shown as dead, but the page never frees it
        self.assertEqual(len(Leases(self.home).status('gate')['resources'][0]['holders']), 1)

    def test_page_shows_no_token_in_json_html_or_served_overview(self):
        self.declared('gate')
        a, b = self.child(), self.child()
        store = Leases(self.home)
        tokens = [store.claim('gate', session='s1', pid=a.pid, ttl=self.LONG)['token'], store.claim('gate', session='s2', pid=b.pid, ttl=self.LONG)['token']]
        data = self.web.shared_resources()
        blob = json.dumps(data)
        for token in tokens: self.assertNotIn(token, blob)
        self.assertNotIn('token', blob)                                                       # neither the secret nor its hash field
        html = self.js('resSectionHtml()', data)
        for token in tokens: self.assertNotIn(token, html)
        self.assertNotIn('token', html)
        from tests import dev31_page_js
        from onecrew.v2 import tracking
        state = Path(self.tmp.name) / 'state'
        fake = tracking._overview_shell(state, tracking._now(None), {'status': 'ok'})
        with mock.patch.object(tracking, 'overview', return_value=fake):
            with dev31_page_js.Served(state) as served:
                status, body = served.get('/api/overview')
        self.assertEqual(status, 200)
        for token in tokens: self.assertNotIn(token, body.decode('utf-8'))
        self.assertNotIn(b'token_sha', body)

    def test_no_lease_home_says_not_declared_and_creates_nothing(self):
        missing = Path(self.tmp.name) / 'no-such-home'
        with mock.patch.dict(os.environ, {'ONECREW_LEASE_HOME': str(missing)}):
            data = self.web.shared_resources()
            attached = self.web.attach({'projects': []})
        self.assertFalse(missing.exists())                                                    # Leases() makes its folder: it must not have been built
        self.assertEqual((data['declared'], data['resources'], data['error']), (False, [], None))
        self.assertIn('chưa khai báo', data['empty_note'])
        self.assertIn('chưa khai báo', attached['shared_resources']['empty_note'])
        self.assertIn('chưa khai báo tài nguyên', self.js('resSectionHtml()', data))
        empty = Path(self.tmp.name) / 'empty-home'
        empty.mkdir()                                                                         # a folder without managed.json: still nothing is created in it
        with mock.patch.dict(os.environ, {'ONECREW_LEASE_HOME': str(empty)}):
            self.assertEqual(self.web.shared_resources()['resources'], [])
        self.assertEqual(list(empty.iterdir()), [])

    def test_reading_the_page_data_changes_no_lease_file(self):
        self.declared('gate')
        a = self.child()
        Leases(self.home).claim('gate', session='s', plan='p', pid=a.pid, ttl=self.LONG)
        before = {p.name: p.read_bytes() for p in self.home.iterdir()}
        self.web.attach({'projects': []})
        self.web.attach({'projects': []})
        self.assertEqual({p.name: p.read_bytes() for p in self.home.iterdir()}, before)       # no lock file left, no event, no release, no reconcile write

    def test_hostile_names_are_escaped_by_the_page_script(self):
        self.declared('gate')
        a, b = self.child(), self.child()
        store = Leases(self.home)
        store.claim('gate', session='<img src=x onerror=alert(1)>', plan='<script>alert(7)</script>', state_root='D:/<b>r</b>', pid=a.pid, ttl=self.LONG)
        store.claim('gate', session='"><svg onload=alert(2)>', plan="</td><i>w</i>", pid=b.pid, ttl=self.LONG)
        html = self.js('resSectionHtml()', self.web.shared_resources())
        for raw in ('<img', '<script', '<b>r</b>', '<svg', '<i>w</i>', 'onload=alert(2)>'):
            self.assertNotIn(raw, html)
        for escaped in ('&lt;img src=x onerror=alert(1)&gt;', '&lt;script&gt;alert(7)&lt;/script&gt;', 'D:/&lt;b&gt;r&lt;/b&gt;', '&quot;&gt;&lt;svg onload=alert(2)&gt;'):
            self.assertIn(escaped, html)

    def test_an_unreadable_store_is_an_error_not_free(self):
        self.declared('gate')
        (self.home / 'leases.json').write_text('{not json', encoding='utf-8')
        data = self.web.shared_resources()
        self.assertTrue(data['error'])
        self.assertEqual(data['resources'], [])
        html = self.js('resSectionHtml()', data)
        self.assertIn('Không coi là trống', html)
        self.assertEqual((self.home / 'leases.json').read_text(encoding='utf-8'), '{not json')   # left as it was

    def test_plan_panel_lists_only_the_resources_that_plan_holds_or_waits_for(self):
        self.declared('gate', 'emulator')
        a, b = self.child(), self.child()
        store = Leases(self.home)
        store.claim('gate', session='s1', plan='plan-A', pid=a.pid, ttl=self.LONG)
        store.claim('emulator', session='s2', plan='plan-B', pid=b.pid, ttl=self.LONG)
        data = self.web.shared_resources()
        mine = self.need_node().run('hostPlanPanel({project:"D:/x",plan:"plan:plan-A"})', '\nlast={shared_resources:' + json.dumps(data) + '};')
        self.assertIn('gate', mine)
        self.assertNotIn('emulator', mine)
        self.assertEqual(self.need_node().run('hostPlanPanel({project:"D:/x",plan:"nobody"})', '\nlast={shared_resources:' + json.dumps(data) + '};'), '')

    def test_served_page_has_the_section_and_the_overview_json_carries_the_leases(self):
        self.declared('gate')
        a = self.child()
        Leases(self.home).claim('gate', session='s1', plan='plan-A', pid=a.pid, ttl=self.LONG)
        from tests import dev31_page_js
        from onecrew.v2 import tracking
        state = Path(self.tmp.name) / 'state'
        fake = tracking._overview_shell(state, tracking._now(None), {'status': 'ok'})
        with mock.patch.object(tracking, 'overview', return_value=fake):
            with dev31_page_js.Served(state) as served:
                status, page = served.get('/')
                status2, body = served.get('/api/overview')
        self.assertEqual((status, status2), (200, 200))
        text = page.decode('utf-8')
        for wanted in ('id="resources"', 'Tài nguyên dùng chung', 'function resSectionHtml'): self.assertIn(wanted, text)
        data = json.loads(body)['shared_resources']
        self.assertTrue(data['read_only'])
        self.assertEqual([(r['resource'], r['free'], r['holders'][0]['plan']) for r in data['resources']], [('gate', False, 'plan-A')])


if __name__ == '__main__':
    unittest.main()
