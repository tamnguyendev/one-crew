import contextlib
import io
import json
import unittest

import test_workflow as fixtures
from onecrew.workflow_cli import main


class WorkViewTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.WorkflowTests()
        self.f.setUp()
        self.f.enable()
        self.f.workflow.run(self.f.task['id'], steps=2)

    def tearDown(self):
        self.f.tearDown()

    def cli(self, command, *flags):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(['--project', str(self.f.project), '--state-root', str(self.f.base/'state'),
                         'work', command, self.f.task['id'], *flags])
        self.assertEqual(code, 0, out.getvalue())
        return out.getvalue()

    def test_brief_full_and_json_preserve_same_revision_without_model_calls(self):
        before = len(self.f.worker.calls)
        card = json.loads(self.cli('outputs', '--json'))['outputs'][0]
        brief, full = self.cli('outputs'), self.cli('outputs', '--full')
        self.assertIn(card['revision'], brief)
        self.assertIn('pending', brief)
        self.assertNotIn('+++', brief)
        self.assertIn('+++', full)
        self.assertIn('settings.json', full)
        self.assertEqual(len(self.f.worker.calls), before)

    def test_status_shows_limits_and_ready_dependency_without_raw_spec(self):
        plain = self.cli('status')
        self.assertIn('1/2 việc', plain)
        self.assertIn('2/6', plain)
        self.assertIn('Sẵn sàng theo dependency: doc', plain)
        self.assertNotIn('spec_text', plain)
        structured = json.loads(self.cli('status', '--json'))
        self.assertIn(structured['control']['budget']['revision'], plain)


if __name__ == '__main__':
    unittest.main()
