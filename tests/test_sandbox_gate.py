import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import test_workflow as fixtures
from onecrew.ledger import LedgerError, content_hash
from onecrew.sandbox_gate import ContainerGate, GateUnavailable, command
from onecrew.supervisor import native_python
from onecrew.workflow import validate_profile, verify

IMAGE = 'sha256:'+'a'*64


def profile():
    value = fixtures.profile()
    value['context'].append('checks.py')
    value['checks'] = [{'id': 'functional', 'acceptance': ['AC-CONFIG', 'AC-DOC'],
                        'kind': 'container_test', 'path': 'checks.py',
                        'expected': {'image': IMAGE, 'argv': ['/usr/local/bin/python', '-B', '/work/checks.py'], 'timeout_seconds': 10}}]
    return value


class FakeEngine:
    def __init__(self):
        self.calls = []
        self.exit_code = 0
        self.running = False
        self.fail_cleanup = False
        self.timeout = False
        self.volumes = None

    def __call__(self, argv, directory, timeout, guard):
        args = argv[5:]
        self.calls.append(args)
        if guard:
            guard()
        if args[0] == 'info':
            return 0, json.dumps({'OSType': 'linux', 'ServerVersion': 'fixture'}), ''
        if args[0] == 'image':
            return 0, json.dumps({'Id': IMAGE, 'Config': {'Volumes': self.volumes}}), ''
        if args[0] == 'start':
            if self.timeout:
                raise GateUnavailable('test timeout')
            return self.exit_code, 'assertion failure' if self.exit_code else '2 tests passed', ''
        if args[0] == 'inspect':
            return 0, json.dumps({'Running': self.running, 'ExitCode': self.exit_code, 'OOMKilled': False, 'Error': ''}), ''
        if args[0] in ('rm', 'container') and self.fail_cleanup:
            return 1, '', 'engine lost'
        return 0, '', ''


class SandboxGateTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.WorkflowTests()
        self.f.setUp()
        (self.f.project/'checks.py').write_text('assert True\n', encoding='utf-8')
        self.profile = profile()
        self.snapshot = self.f.workflow.store.capture(self.f.project, self.profile['context'])
        self.engine = FakeEngine()
        self.gate = ContainerGate(self.f.workflow.store, self.engine)
        self.gate.docker = 'fixture-docker.exe'

    def tearDown(self):
        # Windows can briefly retain redirected log handles after confirmed process exit,
        # as in the existing native supervisor fixture. Never ignore a persistent lock.
        for retry in range(20):
            try:
                self.f.tearDown()
                break
            except PermissionError:
                if retry == 19:
                    raise
                time.sleep(.05)

    def test_candidate_only_readonly_offline_and_cleanup_before_receipt(self):
        check = self.profile['checks'][0]
        result = self.gate.evaluate(self.snapshot, check)
        self.assertTrue(result['passed'])
        self.assertEqual(result['evidence']['snapshot'], self.snapshot)
        self.assertEqual(result['evidence']['check_revision'], content_hash(check))
        create = next(a for a in self.engine.calls if a[0] == 'create')
        for flag in ('--read-only', '--no-healthcheck', '--cap-drop', '--memory', '--pids-limit'):
            self.assertIn(flag, create)
        self.assertEqual(create[create.index('--network')+1], 'none')
        mount = create[create.index('--mount')+1]
        self.assertTrue(mount.endswith('target=/work,readonly'))
        self.assertNotIn(str(self.f.project), mount)
        self.assertNotIn('docker.sock', ' '.join(create))
        self.assertEqual(self.engine.calls[-1][0], 'rm')
        self.assertEqual(len(list(self.gate.root.glob('*/receipt.json'))), 1)
        self.engine.calls.clear()
        self.gate.evaluate(self.snapshot, check)
        self.assertEqual(self.engine.calls[0][0], 'rm')  # recovery before new work

    def test_test_failure_is_failure_but_timeout_and_unknown_cleanup_cannot_pass(self):
        check = self.profile['checks'][0]
        self.engine.exit_code = 1
        self.assertFalse(self.gate.evaluate(self.snapshot, check)['passed'])
        self.engine.timeout = True
        with self.assertRaises(GateUnavailable):
            self.gate.evaluate(self.snapshot, check)
        self.assertEqual(self.engine.calls[-1][0], 'rm')
        self.engine.timeout = False
        self.engine.exit_code = 0
        self.engine.fail_cleanup = True
        with self.assertRaisesRegex(GateUnavailable, 'cleanup unconfirmed'):
            self.gate.evaluate(self.snapshot, check)

    def test_validator_forbids_worker_tests_mutable_images_and_bad_timeouts(self):
        validate_profile(self.profile)
        for mutate in (lambda p: p['owned'].append('checks.py'),
                       lambda p: p['checks'][0]['expected'].update(image='python:latest'),
                       lambda p: p['checks'][0]['expected'].update(timeout_seconds=True),
                       lambda p: p['checks'][0]['expected'].update(argv=['python', '/work/checks.py'])):
            bad = copy.deepcopy(self.profile)
            mutate(bad)
            with self.assertRaises(LedgerError):
                validate_profile(bad)
        self.engine.volumes = {'/data': {}}
        with self.assertRaisesRegex(GateUnavailable, 'volumes'):
            self.gate.preflight(self.profile['checks'])

    def test_infrastructure_failure_before_enable_has_zero_model_calls(self):
        with patch('onecrew.sandbox_gate.ContainerGate.preflight', side_effect=GateUnavailable('engine unavailable')):
            with self.assertRaises(GateUnavailable):
                self.f.workflow.enable(self.f.task['id'], self.f.task['revision'], self.profile)
        self.assertEqual(self.f.worker.calls, [])
        self.assertIsNone(self.f.workflow.state(self.f.task['id'])[1])

    def test_lost_engine_at_verify_blocks_without_ai_repair_then_reuses_candidate(self):
        f = self.f
        with patch('onecrew.sandbox_gate.ContainerGate.preflight', return_value={'fixture': True}):
            f.workflow.enable(f.task['id'], f.task['revision'], self.profile)
        with patch('onecrew.sandbox_gate.ContainerGate.evaluate', side_effect=GateUnavailable('engine lost')):
            state = f.workflow.run(f.task['id'])
        self.assertEqual(state['phase'], 'blocked')
        self.assertEqual(state['resume_phase'], 'verifying')
        self.assertEqual(len(f.worker.calls), 3)
        f.workflow.resume(f.task['id'])
        with patch('onecrew.sandbox_gate.ContainerGate.evaluate', side_effect=self.gate.evaluate):
            state = f.workflow.run(f.task['id'])
        self.assertEqual(state['phase'], 'completed')
        self.assertEqual(state['acceptance'], 'pending')
        self.assertEqual(len(f.worker.calls), 3)

    def test_native_command_timeout_does_not_wait_for_inherited_pipes(self):
        began = time.monotonic()
        with self.assertRaisesRegex(GateUnavailable, 'deadline'):
            command([native_python(), '-c', 'import time; time.sleep(20)'], self.f.base/'native-command', .15)
        self.assertLess(time.monotonic()-began, 5)


if __name__ == '__main__':
    unittest.main()
