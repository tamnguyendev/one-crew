"""W40-RX1 / RX2 (T54j, T54k) [E8]: a DOCUMENT root, a DATA root and an OPS root run end to end on the INSTALLED build (clean venv,
temporary ledger, fake data), each `verdict run` through the installed `onecrew` console script, with the module-boundary check."""
import shutil
import unittest
from pathlib import Path

from tests import wf_wheel as wh
from tests.wf_env import owner_terminal
from tests.wf_installed_adapters import run_installed_adapters


class InstalledAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = wh._runs()
        cls.wheel, _, (modules, packages) = wh.build_wheel(cls.runs)
        cls.python = wh.make_venv(cls.runs)
        wh.install(cls.python, cls.wheel)
        cls.ctx = wh.build_ctx(cls.python, modules, packages)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    def setUp(self):
        owner_terminal(self)

    def test_e8_doc_data_and_ops_roots_run_end_to_end_from_the_installed_build(self):
        rows = run_installed_adapters(self.python, self.runs, self.ctx, commit='c' * 40, wheel_sha256='d' * 64)
        self.assertEqual([r['adapter'] for r in rows], ['doc', 'data', 'ops'])
        venv = Path(self.python).parent.resolve()
        for row in rows:
            with self.subTest(adapter=row['adapter']):
                self.assertEqual(row['result'], 'pass', row)
                self.assertEqual(row['boundary_violations'], [])
                self.assertTrue(row['root'].startswith('plan-ns:'))
                self.assertEqual(Path(row['command'][0]).resolve().parent, venv)
                self.assertNotIn('-m', row['command'])
                self.assertTrue(Path(row['state_root']).resolve().is_relative_to(Path(self.runs).resolve()))
                self.assertRegex(row['artifact'], r'^(?:[0-9a-f]{40}|[0-9a-f]{64})$')
                self.assertEqual((row['commit'], row['wheel_sha256']), ('c' * 40, 'd' * 64))

    def test_a_broken_document_link_really_fails_the_installed_milestone(self):
        rows = run_installed_adapters(self.python, self.runs, self.ctx, adapters=('doc',), variant='broken-doc')
        self.assertEqual(rows[0]['milestone_state'], 'failed', rows[0])
        self.assertEqual(rows[0]['result'], 'fail')
        self.assertEqual(rows[0]['boundary_violations'], [])


if __name__ == '__main__':
    unittest.main()
