"""Public workflow consumers: core inspection and checkout-native dispatch."""
import contextlib
import io
import json
from pathlib import Path
from unittest.mock import patch

from onecrew.v2 import engine_cli
from tests.test_wf_engine import EngineFixture, node


class EngineCliTests(EngineFixture):
    def call(self, *args, **ports):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = engine_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'engine', *args], **ports)
        return code, json.loads(out.getvalue())

    def test_public_revise_state_ready_and_connected_step_reuse_runtime(self):
        source = Path(self.temp.name) / 'internal.json'
        source.write_text(json.dumps({'nodes': [node('C'), node('I', ['C'], integration=True, write=())],
                                      'reason': 'Explicit bounded split', 'evidence': ['a.txt:1']}))
        code, result = self.call('revise', 'plan-ns:P1', '--file', str(source))
        self.assertEqual(code, 0, result)
        self.assertEqual(result['internal_revision'], 1)
        before = self.kinds()
        self.assertEqual(self.call('ready', 'plan-ns:P1')[1][0]['id'], 'C')
        self.assertEqual(self.call('state', 'plan-ns:P1')[1]['root_status'], 'approved')
        self.assertEqual(self.kinds(), before)
        case = self
        class Executor:
            control = case.control
            def __call__(self, *args): return case.execute(*args)
        code, result = self.call('step', 'P1', native_executor=lambda ledger: Executor())
        self.assertEqual((code, result['node'], result['state']), (0, 'C', 'produced'))
        code, result = self.call('verify', 'P1', 'C', checker=lambda ledger, selector: self.checker)
        self.assertEqual((code, result['result']), (0, 'pass'))

    def test_installed_missing_native_port_refuses_before_opening_state(self):
        for args in [('step', 'P1'), ('verify', 'P1', 'C'), ('handoff', 'P1')]:
            with patch.object(engine_cli, 'Ledger', side_effect=AssertionError('must not open mutation state')):
                code, result = self.call(*args, native_executor=None, checker=None, handoff=None)
            self.assertEqual(code, 2)
            self.assertIn('connected native host adapter', result['error'])
