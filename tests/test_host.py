"""OneCrew host (GX-GAP-04, 13/10/2026): jobs dispatched through a durable request run under a host that lives outside the
entry. The host admits once, never starts a second runner, restarts a dead runner within a bound, leaves waits for the
user alone, never revives a runner that died with a reboot and enforces cancel. Launch is a fixture here; the real
Task Scheduler host and the closed entry are shown by the live acceptance run."""
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from onecrew import host
from onecrew.ledger import LedgerError
from tests.test_work_contract import WorkFixture

T0 = dt.datetime(2026, 10, 13, 12, 0, tzinfo=dt.timezone.utc)


def at(seconds):
    return T0 + dt.timedelta(seconds=seconds)


class HostFixture(WorkFixture):
    def setUp(self):
        super().setUp()
        self.home = Path(self.temp.name) / 'host-home'; self.home.mkdir()
        os.environ['ONECREW_HOST_HOME'] = str(self.home); self.addCleanup(os.environ.pop, 'ONECREW_HOST_HOME', None)
        _, self.task, _ = self.job(self.contract(local_branches=['production']), [])
        self.launched = []

    def launch(self, request):
        self.launched.append(request['task'])
        return {'identity': {'pid': 4242 + len(self.launched), 'created': 10 ** 18, 'host': 'fixture'}, 'logs': 'fixture', 'runtime': 'fixture'}

    def request(self, **extra):
        value = dict({'id': 'HD-' + os.urandom(6).hex(), 'task': self.task, 'project': str(self.root.resolve()),
                      'state_root': str(Path(self.ledger.state_root).resolve()), 'runtime': str(Path(host.__file__).resolve().parents[1]),
                      'initiator': 'fixture', 'at': T0.isoformat()}, **extra)
        host._write(host.queue_dir(self.ledger.state_root) / (value['id'] + '.json'), value)
        return value

    def events(self, kind):
        with self.ledger.transaction() as conn:
            return [json.loads(r['payload']) for r in conn.execute('SELECT payload FROM events WHERE task_id=? AND kind=? ORDER BY seq', (self.task, kind))]

    def scan(self, seconds, status='stopped', boot=1):
        with patch('onecrew.runner.status', return_value={'status': status, 'identity': {'pid': 1, 'created': 10 ** 18, 'host': 'x'}}):
            return host.scan(self.ledger.state_root, now=at(seconds), launch=self.launch, boot=boot)

    def phase(self):
        from onecrew.owned import Owned
        return Owned(self.ledger).state(self.task)[1]


class DispatchTests(HostFixture):
    def seen(self, at='2000-01-01T00:00:00+00:00'):
        return {'identity': {}, 'roots_seen': {str(Path(self.ledger.state_root).resolve()): at}}

    def test_dispatch_needs_a_live_host_that_serves_this_state_root(self):
        with self.assertRaises(LedgerError): host.dispatch(self.ledger, self.task, wait=0)
        with patch('onecrew.host.lease', return_value={'identity': {}, 'roots_seen': {}}):
            with self.assertRaises(LedgerError): host.dispatch(self.ledger, self.task, wait=0)  # the host does not scan this root
        with patch('onecrew.host.lease', return_value=self.seen()):
            queued = host.dispatch(self.ledger, self.task, wait=0)
        self.assertEqual(queued['status'], 'queued')
        self.assertEqual(len(list(host.queue_dir(self.ledger.state_root).glob('HD-*.json'))), 1)
        self.assertEqual(self.events('host.dispatch')[0]['task'], self.task)

    def test_runner_start_uses_the_host_only_for_a_served_state_root(self):
        from onecrew import runner
        with patch('onecrew.host.lease', return_value={'identity': {}, 'roots_seen': {}}), \
                patch('onecrew.host.dispatch', return_value={'status': 'admitted'}) as sent, \
                patch('onecrew.runner.subprocess.Popen', side_effect=OSError('entry launch attempted')):
            with self.assertRaises(OSError): runner.start(self.ledger, self.task)  # not served: the entry path, never the host
        with patch('onecrew.host.lease', return_value=self.seen()), patch('onecrew.host.dispatch', return_value={'status': 'admitted'}) as sent:
            self.assertEqual(runner.start(self.ledger, self.task), {'status': 'admitted'})
        self.assertEqual(sent.call_count, 1)

    def test_a_request_the_host_cannot_see_is_withdrawn_with_a_clear_error(self):
        # N1-r1 (13/10/2026): a packaged entry's writes were invisible to the host and the entry was told 'queued'.
        future = '2999-01-01T00:00:00+00:00'  # the host scanned this root after the request was written
        with patch('onecrew.host.lease', return_value=self.seen(future)):
            with self.assertRaises(LedgerError) as caught: host.dispatch(self.ledger, self.task, wait=0.3)
        self.assertIn('cannot see the request', str(caught.exception))
        self.assertEqual(list(host.queue_dir(self.ledger.state_root).glob('HD-*.json')), [])
        self.assertTrue(self.events('host.unseen'))

    def test_the_host_home_is_outside_appdata(self):
        with patch.dict(os.environ, {'ONECREW_HOST_HOME': ''}):
            os.environ.pop('ONECREW_HOST_HOME')
            with patch('onecrew.host.Path.mkdir'):
                self.assertNotIn('appdata', str(host.home()).lower())


class AdmissionTests(HostFixture):
    def test_admits_once_and_never_starts_a_second_runner(self):
        first = self.request()
        actions = self.scan(0)
        self.assertEqual((actions[0]['action'], self.launched), ('admitted', [self.task]))
        self.assertEqual(self.events('host.admitted')[0]['request'], first['id'])
        self.request()
        self.scan(1, status='alive')
        self.assertEqual(self.launched, [self.task], 'a second runner was started for a task that has one')
        self.assertIn('not launched', self.events('host.admitted')[-1]['note'])
        self.assertEqual(list(host.queue_dir(self.ledger.state_root).glob('HD-*.json')), [])

    def test_a_cancelled_or_finished_task_is_refused(self):
        from onecrew.control import Control
        Control(self.ledger).cancel(self.task)
        self.request(); self.scan(0)
        self.assertEqual(self.launched, [])
        self.assertTrue(self.events('host.refused'))


class SupervisionTests(HostFixture):
    def admitted(self):
        self.request(); self.scan(0)
        self.assertEqual(self.launched, [self.task])

    def test_a_dead_runner_is_restarted_with_backoff_then_blocked_once(self):
        self.admitted()
        self.assertEqual(self.scan(5)[0]['action'], 'backoff')            # died; first restart waits 10 s
        self.assertEqual(self.scan(16)[0]['action'], 'restarted')
        self.assertEqual(self.scan(40)[0]['action'], 'backoff')           # second restart waits 60 s after the first
        self.assertEqual(self.scan(80)[0]['action'], 'restarted')
        self.assertEqual(self.scan(390)[0]['action'], 'restarted')
        self.assertEqual(self.scan(800)[0]['action'], 'exhausted')
        self.assertEqual(len(self.launched), 4)
        state = self.phase()
        self.assertEqual((state['phase'], state['recovery']['kind']), ('blocked', 'coordinator'))
        self.assertEqual(self.scan(900), [], 'the exhausted task is no longer supervised')
        self.assertEqual(len(self.events('host.restarted')), 3)

    def test_a_launched_runner_that_has_not_registered_yet_is_not_restarted(self):
        # N1-r2 (13/10/2026): the runner took 38 s to write runner.started; the host launched a second one after 12 s.
        self.admitted()
        with patch('onecrew.supervisor.probe', return_value='alive'):
            self.assertEqual(self.scan(5), [])
            self.assertEqual(self.scan(60), [], 'a starting runner was treated as dead')
        self.assertEqual(self.launched, [self.task])
        self.assertFalse(self.events('host.restarted'))

    def test_a_task_waiting_for_the_user_is_released_not_restarted(self):
        self.admitted()
        with patch('onecrew.host._task_view', return_value={'phase': 'running', 'status': 'paused', 'cancel': False, 'pending': 0}):
            actions = self.scan(100)
        self.assertEqual(actions[0]['action'], 'released')
        self.assertEqual(self.launched, [self.task])

    def test_a_runner_lost_with_a_reboot_needs_an_explicit_resume(self):
        self.admitted()
        actions = self.scan(100, boot=10 ** 19)  # the runner was created before the last boot
        self.assertEqual(actions[0]['action'], 'reboot')
        self.assertEqual(self.launched, [self.task])
        self.assertEqual(self.phase()['recovery']['kind'], 'coordinator_reboot')

    def test_cancel_is_enforced_when_the_runner_does_not_stop_by_itself(self):
        self.admitted()
        from onecrew.control import Control
        Control(self.ledger).cancel(self.task)
        with patch('onecrew.work_tools._terminate', return_value=True) as stopped:
            self.assertEqual(self.scan(10, status='alive'), [])
            actions = self.scan(10 + host.CANCEL_GRACE, status='alive')
        self.assertEqual((actions[0]['action'], stopped.call_count), ('cancel_enforced', 1))
        self.assertTrue(self.events('host.cancel_enforced'))


class DurableAdmissionTests(HostFixture):
    """Codex review 2 (13/10/2026): two requests and a retry before runner.started launched three runners."""

    def stopped(self):
        return patch('onecrew.runner.status', return_value={'status': 'stopped'})

    def test_requests_before_the_runner_registers_launch_once(self):
        self.request(); self.request()
        with self.stopped(), patch('onecrew.supervisor.probe', return_value='alive'):
            host.scan(self.ledger.state_root, now=at(0), launch=self.launch, boot=1)
            self.request()  # a retry while the first runner is still starting
            host.scan(self.ledger.state_root, now=at(5), launch=self.launch, boot=1)
        self.assertEqual(self.launched, [self.task], 'RED-GX2-F3: a second runner was launched before the first registered')
        notes = [e.get('note') for e in self.events('host.admitted') if not e.get('launched')]
        self.assertEqual(len(notes), 2); self.assertTrue(all('not launched' in n for n in notes))

    def test_a_host_stopped_between_launch_record_and_identity_does_not_launch_again_within_grace(self):
        class HostKilled(BaseException):
            """The host process dies inside launch: no handler of the host runs (models TerminateProcess)."""
        def crashing(request):
            raise HostKilled()
        self.request()
        with self.stopped():
            with self.assertRaises(HostKilled): host.scan(self.ledger.state_root, now=at(0), launch=crashing, boot=1)
            self.request()
            host.scan(self.ledger.state_root, now=at(30), launch=self.launch, boot=1)
            self.assertEqual(self.launched, [], 'a launch recorded as in progress was repeated within the grace period')
            self.request()
            host.scan(self.ledger.state_root, now=at(30 + host.LAUNCH_GRACE + 1), launch=self.launch, boot=1)
        self.assertEqual(self.launched, [self.task])  # nothing owns the task after the grace: launched exactly once

    def test_a_launch_that_fails_is_recorded_failed_and_does_not_hold_off_the_next_request(self):
        def failing(request):
            raise OSError('python not found')
        self.request()
        with self.stopped():
            actions = host.scan(self.ledger.state_root, now=at(0), launch=failing, boot=1)
            self.assertEqual(actions[0]['action'], 'failed')
            record = json.loads(host._launch_record(self.ledger.state_root, self.task).read_text())
            self.assertEqual(record['state'], 'failed')
            self.request()
            host.scan(self.ledger.state_root, now=at(10), launch=self.launch, boot=1)
        self.assertEqual(self.launched, [self.task], 'a failed launch held off the next request as if it were still starting')

    def test_an_admission_in_progress_elsewhere_is_not_doubled(self):
        import msvcrt
        self.request()
        path = host._launch_record(self.ledger.state_root, self.task).with_suffix('.lock'); path.parent.mkdir(parents=True, exist_ok=True)
        with self.stopped(), path.open('a+b') as other, patch.object(host.time, 'sleep'),                 patch.object(host.time, 'monotonic', side_effect=[0.0] + [100.0] * 50):
            msvcrt.locking(other.fileno(), msvcrt.LK_NBLCK, 1)  # another host is deciding for this task right now
            try: host.scan(self.ledger.state_root, now=at(0), launch=self.launch, boot=1)
            finally: other.seek(0); msvcrt.locking(other.fileno(), msvcrt.LK_UNLCK, 1)
        self.assertEqual(self.launched, [])
        self.assertIn('another admission', self.events('host.admitted')[-1]['note'])

    def test_supervision_follows_the_identity_of_the_runner_that_owns_the_task(self):
        from onecrew.supervisor import identity
        self.request()
        with self.stopped(), patch('onecrew.host._runner_lock_held', return_value=True):
            host.scan(self.ledger.state_root, now=at(0), launch=self.launch, boot=1)  # owner without identity: not launched
        entry = json.loads((self.ledger.state_root / 'host' / 'supervised.json').read_text())['tasks'][self.task]
        self.assertIsNone(entry['runner'])
        mine = identity(os.getpid())
        with patch('onecrew.runner.status', return_value={'status': 'alive', 'identity': mine}):
            host.scan(self.ledger.state_root, now=at(5), launch=self.launch, boot=1)
        entry = json.loads((self.ledger.state_root / 'host' / 'supervised.json').read_text())['tasks'][self.task]
        self.assertEqual(entry['runner'], mine, 'the reboot rule needs the identity of the runner that owns the task')

    def test_a_probe_of_the_runner_lock_does_not_make_a_starting_runner_give_up(self):
        import threading
        from onecrew.workflow import task_lock
        path = self.ledger.state_root / 'locks'; path.mkdir(parents=True, exist_ok=True)
        held = threading.Event(); release = threading.Event()
        def prober():
            import msvcrt
            from onecrew.ledger import key_field
            with (path / (key_field(self.task + '.runner') + '.lock')).open('a+b') as stream:
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1); held.set(); release.wait(0.3)
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        (path / (__import__('onecrew.ledger', fromlist=['key_field']).key_field(self.task + '.runner') + '.lock')).write_bytes(b'0')
        thread = threading.Thread(target=prober); thread.start(); held.wait(5)
        try:
            with task_lock(self.ledger, self.task + '.runner'):
                pass  # the probe held it for 0.3 s; the runner waits it out instead of reporting another owner
        finally:
            release.set(); thread.join()

    def test_a_held_runner_lock_is_an_owner(self):
        from onecrew.workflow import task_lock
        self.request()
        with self.stopped(), task_lock(self.ledger, self.task + '.runner'):
            host.scan(self.ledger.state_root, now=at(0), launch=self.launch, boot=1)
        self.assertEqual(self.launched, [])
        self.assertIn('lock', self.events('host.admitted')[-1]['note'])


class LeaseTests(unittest.TestCase):
    def test_lease_is_trusted_only_with_a_fresh_heartbeat_from_a_live_process(self):
        from onecrew.supervisor import identity
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            record = {'identity': identity(os.getpid()), 'heartbeat': dt.datetime.now(dt.timezone.utc).isoformat()}
            host._write(base / 'lease.json', record)
            self.assertIsNotNone(host.lease(base))
            host._write(base / 'lease.json', dict(record, heartbeat=(dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)).isoformat()))
            self.assertIsNone(host.lease(base))
            host._write(base / 'lease.json', dict(record, stopped_at='x'))
            self.assertIsNone(host.lease(base))

    def test_serve_once_writes_a_lease_and_scans_registered_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); host.register(base / 'state', base)
            with patch('onecrew.host.scan', return_value=[{'action': 'admitted'}]) as scanned:
                self.assertEqual(host.serve(base, once=True), 'stopped')
            self.assertEqual(scanned.call_count, 1)
            record = json.loads((base / 'lease.json').read_text())
            self.assertIn('stopped_at', record); self.assertEqual(record['last_actions'], [{'action': 'admitted'}])
            self.assertIn(str((base / 'state').resolve()), record['roots_seen'])  # what the host itself scanned
            self.assertIn('host started', (base / 'host.log').read_text())

    def test_task_xml_is_a_per_user_least_privilege_logon_task_without_time_limit(self):
        text = host.task_xml(Path(host.__file__).resolve().parents[1], user='DOMAIN\\someone')
        for needle in ('<LogonTrigger>', '<RunLevel>LeastPrivilege</RunLevel>', '<LogonType>InteractiveToken</LogonType>',
                       '<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>', '-m onecrew.host run', 'DOMAIN\\someone'):
            self.assertIn(needle, text)


if __name__ == '__main__':
    unittest.main()
