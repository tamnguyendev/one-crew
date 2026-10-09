from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from onecrew.control import Control, migrate
from onecrew.ledger import Ledger, LedgerError
from onecrew.specs import Project
from onecrew.supervisor import Supervisor, identity, probe, native_python

ROOT = Path(__file__).resolve().parents[1]
SANDBOXES = ROOT / '.onecrew/control-tests'
SAMPLE = (ROOT/'specs/SPEC-001-duyet-spec.md').read_text(encoding='utf-8')


class ControlTests(unittest.TestCase):
    def setUp(self):
        SANDBOXES.mkdir(parents=True, exist_ok=True)
        self.base = Path(tempfile.mkdtemp(dir=SANDBOXES)).resolve()
        self.project = self.base/'project'
        (self.project/'specs').mkdir(parents=True)
        (self.project/'specs/SPEC-001-duyet-spec.md').write_text(SAMPLE, encoding='utf-8')
        self.ledger = Ledger(self.project, self.base/'state')
        self.grant = {'schema_version': 1, 'permissions': [], 'limits': {'max_calls': 3, 'max_seconds': 60}, 'source': 'fixture'}
        self.rev = Project(self.project).find('SPEC-001').revision
        self.task = self.ledger.submit('SPEC-001', self.rev, 'fixture', self.grant)
        self.migration = migrate(self.ledger)
        self.control = Control(self.ledger)
        self.execution = self.control.configure(self.task['id'], self.task['revision'], {'mode': 'test'})

    def tearDown(self):
        target = self.base.resolve()
        self.assertTrue(target.is_relative_to(SANDBOXES.resolve()))
        self.assertNotEqual(target, SANDBOXES.resolve())
        # Windows can briefly retain a terminated descendant's redirected handles.
        for retry in range(20):
            try:
                shutil.rmtree(target)
                break
            except PermissionError:
                if retry == 19:
                    raise
                time.sleep(.05)

    def reserve(self, key='one'):
        return self.control.reserve(self.task['id'], self.execution['revision'], key, {'stage': 'fixture'})

    def test_migration_has_readable_v1_backup_and_preserves_task(self):
        with closing(sqlite3.connect(self.migration['backup'])) as conn:
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT id FROM tasks').fetchone()[0], self.task['id'])
        self.assertFalse(migrate(self.ledger)['changed'])
        self.assertEqual(self.ledger.task(self.task['id'])['deadline'], self.task['deadline'])

    def test_budget_reserved_charged_and_settled_once_across_restart(self):
        attempt = self.reserve()
        self.assertEqual(self.reserve()['id'], attempt['id'])
        self.assertEqual(self.control.status(self.task['id'])['reserved_calls'], 1)
        self.control.launched(attempt['id'], attempt['generation'], {'fixture': 1})
        self.control.launched(attempt['id'], attempt['generation'], {'fixture': 1})
        self.control = Control(Ledger(self.project, self.base/'state'))
        self.control.finish(attempt['id'], attempt['generation'], {'verified': True})
        self.control.finish(attempt['id'], attempt['generation'], {'verified': True})
        state = self.control.status(self.task['id'])
        self.assertEqual((state['used_calls'], state['reserved_calls']), (1, 0))
        with self.assertRaises(LedgerError):
            self.control.finish(attempt['id'], attempt['generation'], {'verified': False})

    def test_budget_exhaustion_cannot_be_reset_by_configure(self):
        for i in range(3):
            row = self.reserve(str(i))
            self.control.finish(row['id'], row['generation'], {'fixture': True})
        self.control.configure(self.task['id'], self.task['revision'], {'mode': 'test'})
        with self.assertRaisesRegex(LedgerError, 'budget'):
            self.reserve('four')
        with self.assertRaisesRegex(LedgerError, 'sealed'):
            self.control.configure(self.task['id'], self.task['revision'], {'mode': 'reset'})

    def test_unknown_launch_holds_reservation_and_blocks_new_writer(self):
        row = self.reserve()
        self.control.unknown(row['id'], 'lost launch acknowledgement')
        with self.assertRaisesRegex(LedgerError, 'reconcile'):
            self.reserve('two')
        with self.assertRaisesRegex(LedgerError, 'refund'):
            self.control.finish(row['id'], row['generation'], {}, not_started=True)
        self.assertEqual(self.control.status(self.task['id'])['reserved_calls'], 1)

    def test_known_not_started_can_release_reservation_without_charge(self):
        row = self.reserve()
        self.control.finish(row['id'], row['generation'], {'not_started': True}, not_started=True)
        state = self.control.status(self.task['id'])
        self.assertEqual((state['used_calls'], state['reserved_calls']), (0, 0))

    def test_cancel_and_deadline_prevent_new_dispatch(self):
        future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
        self.control.clock = lambda: future
        with self.assertRaisesRegex(LedgerError, 'deadline'):
            self.reserve()
        self.control.clock = lambda: dt.datetime.now(dt.timezone.utc)
        self.control.cancel(self.task['id'])
        with self.assertRaisesRegex(LedgerError, 'stopped'):
            self.reserve()
        self.assertEqual(self.control.status(self.task['id'])['used_calls'], 0)

    def test_question_arriving_after_reservation_still_blocks_launch(self):
        row = self.reserve()
        question = {'schema_version': 1, 'question': 'Which?', 'reason': 'ambiguous', 'impact': 'wait',
                    'options': [{'id': 'a', 'label': 'A'}, {'id': 'b', 'label': 'B'}],
                    'recommendation': 'a', 'action': {'type': 'clarify', 'parameters': {}}}
        self.ledger.create_request(self.task['id'], 'question', question)
        with self.assertRaisesRegex(LedgerError, 'Pending'):
            self.control.launched(row['id'], row['generation'], {})
        self.assertEqual(self.control.status(self.task['id'])['used_calls'], 0)

    def test_global_capacity_across_roots_and_single_task_owner(self):
        first = self.reserve()
        with self.assertRaisesRegex(LedgerError, 'reconcile'):
            self.reserve('different')
        for i in range(2):
            task = self.ledger.submit('SPEC-001', self.rev, 'other-'+str(i), self.grant)
            execution = self.control.configure(task['id'], task['revision'], {})
            if i == 0:
                self.control.reserve(task['id'], execution['revision'], 'one', {})
            else:
                with self.assertRaisesRegex(LedgerError, 'capacity'):
                    self.control.reserve(task['id'], execution['revision'], 'one', {})
        self.assertEqual(self.control.attempt(first['id'])['status'], 'reserved')

    def test_concurrent_reserve_and_key_conflicts(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(lambda _: self.reserve(), range(4)))
        self.assertEqual(len({r['id'] for r in rows}), 1)
        with self.assertRaisesRegex(LedgerError, 'different'):
            self.control.reserve(self.task['id'], self.execution['revision'], 'one', {'stage': 'other'})

    def test_parallel_cancel_is_confirmed_only_after_both_units_settle(self):
        first = self.control.reserve(self.task['id'], self.execution['revision'], 'A', {'unit': 'task:A'})
        second = self.control.reserve(self.task['id'], self.execution['revision'], 'B', {'unit': 'task:B'})
        self.control.cancel(self.task['id'])
        self.control.finish(first['id'], first['generation'], {'stopped': True}, not_started=True)
        self.assertEqual(self.control.status(self.task['id'])['status'], 'cancelling')
        self.control.finish(second['id'], second['generation'], {'stopped': True}, not_started=True)
        self.assertEqual(self.control.status(self.task['id'])['status'], 'cancelled')

    def test_admission_checkpoint_failure_rolls_back_reservation(self):
        def fail(conn, attempt):
            raise sqlite3.OperationalError('checkpoint disk full')
        with self.assertRaises(sqlite3.OperationalError):
            self.control.reserve(self.task['id'], self.execution['revision'], 'atomic', {'unit': 'task:A'}, on_reserved=fail)
        state = self.control.status(self.task['id'])
        self.assertEqual(state['reserved_calls'], 0)
        self.assertEqual(state['attempts'], [])

    def test_stale_generation_and_transaction_failure_do_not_charge(self):
        row = self.reserve()
        with self.assertRaisesRegex(LedgerError, 'generation'):
            self.control.launched(row['id'], row['generation']+1, {})
        with patch.object(self.ledger, '_event', side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaises(sqlite3.OperationalError):
                self.control.launched(row['id'], row['generation'], {})
        self.assertEqual(self.control.attempt(row['id'])['status'], 'reserved')
        self.assertEqual(self.control.status(self.task['id'])['used_calls'], 0)

    def test_action_revision_and_ambiguous_effect_not_replayed(self):
        action = self.control.propose_action(self.task['id'], 'write', {'path': 'artifact.txt'})
        with self.assertRaisesRegex(LedgerError, 'Stale'):
            self.control.authorize_action(action['id'], 'old')
        self.control.authorize_action(action['id'], action['revision'])
        effects = []
        def effect(payload):
            effects.append(payload)
            raise TimeoutError('effect happened but response lost')
        self.assertEqual(self.control.execute_action(action['id'], effect)['status'], 'unknown')
        self.control.execute_action(action['id'], effect)
        self.assertEqual(len(effects), 1)
        receipt = self.control.reconcile_action(action['id'], action['revision'], lambda _: {'verified': True, 'evidence': 'found'})
        self.assertTrue(receipt['reconciled'])

    def test_action_string_false_is_not_verified(self):
        action = self.control.propose_action(self.task['id'], 'x', {})
        self.control.authorize_action(action['id'], action['revision'])
        result = self.control.execute_action(action['id'], lambda _: {'verified': 'false'})
        self.assertEqual(result['status'], 'unknown')

    @unittest.skipUnless(os.name == 'nt', 'Windows containment')
    def test_supervisor_success_and_pid_reuse_probe(self):
        attempt = self.reserve()
        result = Supervisor(self.control).run(attempt, [native_python(), '-c', "print('done')"], cwd=self.project)
        self.assertEqual(result['exit_code'], 0)
        self.assertTrue(result['tree_stopped'])
        self.assertIn('done', Path(result['stdout']).read_text())
        current = identity(os.getpid())
        self.assertEqual(probe(current), 'alive')
        self.assertEqual(probe(dict(current, created=current['created']-1)), 'dead')

    @unittest.skipUnless(os.name == 'nt', 'Windows containment')
    def test_supervisor_timeout_kills_descendants_and_preserves_budget(self):
        attempt = self.reserve()
        code = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); print(p.pid,flush=True); time.sleep(60)"
        result = Supervisor(self.control).run(attempt, [native_python(), '-c', code], cwd=self.project, timeout=.4)
        self.assertEqual(result['reason'], 'timeout')
        self.assertTrue(result['tree_stopped'])
        self.assertEqual(self.control.status(self.task['id'])['used_calls'], 1)
        from onecrew.runtime import process_alive
        descendant = int(Path(result['stdout']).read_text().strip())
        deadline = time.monotonic() + 2
        while process_alive(descendant) and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertFalse(process_alive(descendant))

    @unittest.skipUnless(os.name == 'nt', 'Windows containment')
    def test_supervisor_death_kills_job_and_reconcile_retains_charge(self):
        row = self.reserve()
        script = '''import sys
from onecrew.ledger import Ledger
from onecrew.control import Control
from onecrew.supervisor import Supervisor,native_python
c=Control(Ledger(sys.argv[1],sys.argv[2]))
Supervisor(c).run(c.attempt(sys.argv[3]),[native_python(),'-c','import time; time.sleep(60)'],cwd=sys.argv[1])
'''
        owner = subprocess.Popen([sys.executable, '-c', script, str(self.project), str(self.base/'state'), row['id']], cwd=ROOT,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic()+10
            token = None
            while time.monotonic()<deadline:
                current = self.control.attempt(row['id'])
                if current['identity']:
                    token = json.loads(current['identity'])
                    break
                time.sleep(.05)
            self.assertIsNotNone(token)
            owner.kill(); owner.wait(timeout=10)
            deadline = time.monotonic()+10
            while probe(token['worker']) != 'dead' and time.monotonic()<deadline:
                time.sleep(.05)
            self.assertEqual(probe(token['worker']), 'dead')
            self.assertEqual(Supervisor(self.control).reconcile(row['id'])['status'], 'settled')
            self.assertEqual(self.control.status(self.task['id'])['used_calls'], 1)
        finally:
            if owner.poll() is None:
                owner.kill(); owner.wait(timeout=10)

    @unittest.skipUnless(os.name == 'nt', 'Windows containment')
    def test_venv_redirector_is_rejected_before_it_can_escape_job(self):
        if not (Path(sys.executable).parent.parent/'pyvenv.cfg').exists():
            self.skipTest('No redirector in this test environment')
        row = self.reserve()
        with self.assertRaisesRegex(LedgerError, 'redirectors'):
            Supervisor(self.control).run(row, [sys.executable, '-c', 'print(1)'], cwd=self.project)
        state = self.control.status(self.task['id'])
        self.assertEqual((state['used_calls'], state['reserved_calls']), (0, 0))


if __name__ == '__main__':
    unittest.main()
