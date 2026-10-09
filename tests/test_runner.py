import datetime as dt
import json
import subprocess
import time
import unittest
from unittest.mock import patch

import test_workflow as fixtures
from onecrew.runner import loop, status
from onecrew.supervisor import native_python, probe


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WorkflowTests()
        self.fixture.setUp()
        self.fixture.enable()

    def tearDown(self):
        self.fixture.tearDown()

    def test_detached_runner_survives_launcher_exit_and_cancel_stops_it(self):
        f = self.fixture
        f.workflow.control.pause(f.task['id'])
        args = [native_python(), '-X', 'utf8', '-m', 'onecrew', '--project', str(f.project),
                '--state-root', str(f.base/'state'), 'work', 'start', f.task['id'], '--json']
        result = subprocess.run(args, cwd=fixtures.ROOT, capture_output=True, timeout=12)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        record = json.loads(result.stdout)
        try:
            self.assertEqual(record['status'], 'alive', record)
            self.assertEqual(probe(record['identity']), 'alive')
            duplicate = subprocess.run(args, cwd=fixtures.ROOT, capture_output=True, timeout=12)
            self.assertEqual(json.loads(duplicate.stdout)['identity'], record['identity'])
            self.assertEqual(f.workflow.control.status(f.task['id'])['used_calls'], 0)
        finally:
            f.workflow.control.cancel(f.task['id'])
            end = time.monotonic() + 8
            while time.monotonic() < end and status(f.ledger, f.task['id'])['status'] != 'stopped':
                time.sleep(.1)
        self.assertEqual(status(f.ledger, f.task['id'])['status'], 'stopped')

    def test_waits_cannot_extend_root_deadline_or_spend_model_calls(self):
        f = self.fixture
        f.workflow.control.pause(f.task['id'])
        deadline = f.workflow.control.status(f.task['id'])['deadline']
        f.workflow.control.clock = lambda: dt.datetime.fromisoformat(deadline) + dt.timedelta(hours=8)
        with patch('onecrew.runner.Workflow', return_value=f.workflow):
            self.assertEqual(loop(f.ledger, f.task['id']), 'deadline')
        state = f.workflow.state(f.task['id'])[1]
        self.assertEqual(state['phase'], 'blocked')
        self.assertEqual(f.worker.calls, [])
        self.assertEqual(f.workflow.control.status(f.task['id'])['deadline'], deadline)

    def test_explicit_extension_after_wait_deadline_retains_resume_phase(self):
        from onecrew.budget import extend
        f = self.fixture
        old = f.ledger.task(f.task['id'])['budget']
        f.workflow.control.clock = lambda: dt.datetime.fromisoformat(old['deadline']) + dt.timedelta(seconds=1)
        with patch('onecrew.runner.Workflow', return_value=f.workflow):
            self.assertEqual(loop(f.ledger, f.task['id']), 'deadline')
        future = (dt.datetime.fromisoformat(f.task['created_at']) + dt.timedelta(hours=1)).isoformat()
        extend(f.workflow.control, f.task['id'], old['revision'], 'more-time', 6, future, 'Resume approved scope')
        self.assertEqual(f.workflow.resume(f.task['id'])['phase'], 'planning')
        self.assertEqual(f.workflow.run(f.task['id'])['phase'], 'completed')
        self.assertEqual(f.workflow.control.status(f.task['id'])['used_calls'], 3)


if __name__ == '__main__':
    unittest.main()
