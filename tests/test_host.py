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
        self.assertIn('already owns', self.events('host.admitted')[-1]['note'])
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
