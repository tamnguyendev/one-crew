"""RM1 ML: check admission, FIFO handoff and recovery through engine steps in real ledgers."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import unittest
import urllib.request

from onecrew import resource_lease
from onecrew.control_core import Control
from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import engine, tracking_web
from tests import test_dev31_resources as fixtures


def step(case, node='A', callback=None):
    return engine.step(case.ledger, 'P1', case.isolated(callback), slots=2, _target=node)


def short_wait(project, root):
    case = fixtures.EngineLeaseSeam()
    case.ledger = Ledger(project, root)
    case.control = Control(case.ledger)
    print(json.dumps(step(case)))


class LeaseRecovery(unittest.TestCase):
    def setUp(self):
        self.a = fixtures.EngineLeaseSeam()
        self.addCleanup(self.a.doCleanups)
        self.a.setUp()
        self.b = self.a.second_root()
        self.leases = resource_lease.Leases()
        self.leases.declare(['gate'])

    def hold(self):
        claim = self.leases.claim('gate', session='one', plan='P1', state_root=str(self.a.ledger.state_root),
                                  project=str(self.a.root), project_id=self.a.ledger.project_id)
        return lambda: self.leases.release('gate', claim['claim'], claim['token'])

    def short(self, case):
        result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c',
                                 'from tests.test_rm1_lease_recovery import short_wait; import sys; short_wait(*sys.argv[1:])',
                                 str(case.root), str(case.ledger.state_root)],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
        return json.loads(result.stdout)

    def gate(self):
        return self.leases.status('gate')['resources'][0]

    def test_two_ledgers_retry_short_engine_steps_preserves_fifo_before_late_arrival(self):
        release = self.hold()
        self.assertEqual(self.short(self.b)['state'], 'waiting')
        late = self.a.second_root()
        self.assertEqual(self.short(late)['state'], 'waiting')
        self.assertEqual(self.short(self.b)['state'], 'waiting')
        self.assertEqual([w['state_root'] for w in self.gate()['waiters']],
                         [str(case.ledger.state_root) for case in (self.b, late)])
        release()
        self.assertEqual(step(late)['state'], 'waiting')
        self.assertEqual(step(self.b)['state'], 'produced')
        self.assertEqual(step(late)['state'], 'produced')

    def test_cancelled_or_superseded_waiter_yields_its_place_without_duplicate_claims(self):
        release = self.hold()
        for _ in range(2):
            self.assertEqual(step(self.b)['state'], 'waiting')
        self.assertEqual(len(self.gate()['waiters']), 1)
        updated = [dict(self.a.plan_nodes[0], goal='Changed output'), self.a.plan_nodes[1]]
        self.b.revise(updated)
        self.leases.reconcile()
        self.assertFalse(self.gate()['waiters'])
        self.assertEqual(step(self.b)['state'], 'waiting')
        release()
        self.assertTrue(self.gate()['holders'])
        child = self.gate()['holders'][0]['session'].split('@', 1)[1]
        self.b.control.cancel(child)
        self.leases.reconcile()
        self.assertTrue(self.gate()['free'])

    def test_waiting_retry_never_launches_or_consumes_a_repair(self):
        self.hold()
        for _ in range(2):
            self.assertEqual(step(self.b)['state'], 'waiting')
        self.assertEqual((self.b.attempts(), self.b.started()), (0, []))
        with self.b.ledger.transaction() as conn:
            self.assertEqual(conn.execute('SELECT coalesce(sum(used_calls+reserved_calls),0) FROM executions').fetchone()[0], 0)

    def test_deleted_launched_attempt_row_keeps_exclusive_lease(self):
        self.a.launch_record({'worker': {'adapter': 'local'}})
        row = self.a.a_attempt()
        with self.a.ledger.transaction(write=True) as conn:
            conn.execute('DELETE FROM attempts WHERE id=?', (row['id'],))
        self.assertEqual(step(self.b)['state'], 'waiting')
        self.assertFalse(self.gate()['free'])

    def test_controller_death_or_lost_contact_keeps_live_worker_including_pid_only(self):
        self.a.launch_record({'pid': os.getpid()})
        self.assertEqual(step(self.b)['state'], 'waiting')
        holder = self.gate()['holders'][0]
        self.assertEqual((holder['pid'], holder['process']), (os.getpid(), 'unknown'))

    def test_stuck_controller_reconcile_needs_matching_terminal_proof(self):
        started, done = threading.Event(), threading.Event()
        outcome = {}
        def stuck(ledger, control, task, item, attempt):
            control.launched(attempt['id'], attempt['generation'], {'worker': {'adapter': 'local'}})
            started.set()
            done.wait(40)
            raise RuntimeError('controller returned after reconciliation')
        thread = threading.Thread(target=lambda: outcome.update(step(self.a, callback=stuck)))
        thread.start()
        try:
            self.assertTrue(started.wait(15))
            row = self.a.a_attempt()
            with self.assertRaises(LedgerError):
                self.a.control.finish(row['id'], row['generation'] + 1, {'tree_stopped': True})
            self.assertEqual(step(self.b)['state'], 'waiting')
            self.a.settle_a()
            self.assertEqual(step(self.b)['state'], 'produced')
        finally:
            done.set()
            thread.join(30)
        self.assertTrue(outcome)

    def lose(self, identity):
        def lost(ledger, control, task, item, attempt):
            control.launched(attempt['id'], attempt['generation'], identity)
            raise RuntimeError('lost contact')
        self.assertEqual(step(self.a, callback=lost)['state'], 'held')

    def test_no_pid_completion_record_requires_scoped_proof_and_replay_is_idempotent(self):
        self.lose({'worker': {'remote_job': 'abc'}})
        self.assertEqual(step(self.b)['state'], 'waiting')
        row = self.a.a_attempt()
        with self.assertRaises(LedgerError):
            self.b.control.finish(row['id'], row['generation'], {'tree_stopped': True})
        self.assertEqual(step(self.b)['state'], 'waiting')
        for _ in range(2):
            self.a.settle_a()
            self.leases.reconcile()
        releases = [e for e in self.leases.events('gate') if e['event'].startswith('released')]
        self.assertEqual(len(releases), 1)
        self.assertEqual(step(self.b)['state'], 'produced')

    def test_reused_pid_or_remote_worker_without_terminal_proof_stays_held(self):
        initial = self.a
        for host in (socket.gethostname(), 'remote-machine.invalid'):
            with self.subTest(host=host):
                self.lose({'pid': os.getpid(), 'created': 1, 'host': host})
                self.assertEqual(step(self.b)['state'], 'waiting')
                self.assertEqual(self.gate()['holders'][0]['process'], 'unknown')
                self.a.settle_a()
                self.assertEqual(step(self.b)['state'], 'produced')
                self.a, self.b = initial.second_root(), initial.second_root()

    def test_status_names_scoped_holder_waiter_and_reason_without_secret(self):
        self.hold()
        self.assertEqual(step(self.b)['state'], 'waiting')
        token_file, = (self.b.ledger.state_root / 'lease-claims').glob('*.json')
        token = json.loads(token_file.read_text(encoding='utf-8'))['token']
        row = self.gate()
        self.assertEqual(row['waiters'][0]['reason'], 'resource_held')
        server = tracking_web.make_server(self.a.ledger.state_root)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                    tracking_web.url_of(server) + 'api/overview', timeout=30) as response:
                data = json.load(response)
        finally:
            server.shutdown()
            thread.join(5)
            server.server_close()
        shown = data['shared_resources']['resources'][0]
        self.assertEqual(shown['holders'][0]['project_id'], self.a.ledger.project_id)
        self.assertEqual(shown['waiters'][0]['project_id'], self.b.ledger.project_id)
        self.assertIn('giữ', shown['waiters'][0]['state_label'])
        self.assertNotIn(token, json.dumps([row, data]))

    def test_light_unrelated_work_proceeds_while_heavy_jobs_wait(self):
        self.hold()
        self.assertEqual(step(self.b)['state'], 'waiting')
        light = self.a.second_root([fixtures.seam_node('A', ['a.txt']),
                                    fixtures.seam_node('I', depends=['A'], integration=True)])
        self.assertEqual(step(light)['state'], 'produced')
        self.assertEqual(self.b.attempts(), 0)
