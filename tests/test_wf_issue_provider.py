"""W50b (T53b E5/E6/E9): the image path of `issue localize` is reachable from the CLI through the provider's capability declaration (TD19).

No product provider declares a vision adapter, so with `--provider codex` the image is never opened and the result says "không đọc ảnh" with the
provider's reason; an adapter injected into `providers.VISION_ADAPTERS` makes the same CLI call read the image, and its observations are sourced
by the image. `issue evaluate` runs the held-out evaluation from two separate files (cases / oracle) and reports top-1/3/5 with a denominator.
Counter-example (E9): a declaration that skips the capability check is caught.
"""
import contextlib
import io
import json
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.v2 import learning_cli, localization, plan as plans, providers
from tests.test_v2_l1 import Fixture, plan_json

ISSUE = 'Click "Export report" gives 500 for month 2.'


class IssueProviderTests(Fixture):
    def setUp(self):
        super().setUp()
        (self.root / '.gitignore').write_text('.onecrew/\n')
        (self.root / 'ui.html').write_text('<button data-handler="ReportController.export">Export report</button>\n')
        (self.root / 'reports.py').write_text('class ReportController:\n    def export(self, month):\n        return ExportService().build(month)\n\n'
                                              'class ExportService:\n    def build(self, month):\n        return 31\n')
        (self.root / 'test_reports.py').write_text('def test_export_build():\n    assert ExportService().build(2) == 28\n')
        self.git('add', '.'); self.git('commit', '-qm', 'before repair')
        self.pinned = self.git('rev-parse', 'HEAD')
        plans.propose(self.ledger, 'P1', plan_json(), 'codex')

    def cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = learning_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), *args])
        self.assertEqual(code, 0, out.getvalue())
        return json.loads(out.getvalue())

    def test_product_providers_declare_no_vision_so_the_cli_keeps_the_text_path_and_says_so(self):
        for name in providers.PROVIDERS:
            declaration = providers.vision(name)
            self.assertEqual(declaration['capabilities'], []); self.assertIsNone(declaration['observe_image']); self.assertIn('no vision adapter', declaration['reason'])
        with self.assertRaises(LedgerError):
            providers.vision('gpt')
        missing = self.root / 'not-present.png'                                                     # would raise if opened
        result = self.cli('issue', 'localize', ISSUE, '--name', 'P1', '--revision', self.pinned, '--image', str(missing), '--provider', 'codex')
        self.assertFalse(result['image']['read'])
        self.assertIn('không đọc ảnh', result['image']['reason']); self.assertIn('provider codex declares no vision adapter', result['image']['reason'])   # E5 (T)
        self.assertFalse(any(o['source']['type'] == 'image' for o in result['observations']))
        self.assertTrue(result['suspects'], 'the text path still runs')

    def test_an_injected_adapter_makes_the_same_cli_call_read_the_image(self):
        image = self.root / 'error.png'; image.write_bytes(b'controlled fixture image bytes')
        seen = []
        def observe(path):
            seen.append(path.read_bytes()); return ['Screen shows 500 on "Export report".']
        with patch.dict(providers.VISION_ADAPTERS, {'kiro': observe}):
            self.assertEqual(providers.vision('kiro')['capabilities'], ['vision'])
            result = self.cli('issue', 'localize', 'Error screenshot', '--name', 'P1', '--revision', self.pinned, '--image', str(image), '--provider', 'kiro')
        self.assertEqual(seen, [image.read_bytes()]); self.assertTrue(result['image']['read'])     # E5 (V)
        images = [o for o in result['observations'] if o['source']['type'] == 'image']
        self.assertEqual(len(images), 1); self.assertEqual(images[0]['source']['provider'], 'kiro')
        self.assertEqual(providers.vision('kiro')['capabilities'], [], 'the injection does not outlive the test')

    def test_e9_counterexample_a_declaration_without_the_capability_check_is_caught(self):
        """A provider dict claiming vision without an observer is refused before any image access; the reverse (observer, no capability) never reads."""
        calls = []
        text_only = localization.localize(self.ledger, ISSUE, revision=self.pinned, image=self.root / 'none.png',
                                          provider={'name': 'T', 'capabilities': [], 'observe_image': lambda p: calls.append(p)})
        self.assertEqual(calls, []); self.assertFalse(text_only['image']['read'])
        with self.assertRaises(LedgerError):
            localization.localize(self.ledger, ISSUE, revision=self.pinned, image=self.root / 'none.png', provider={'name': 'X', 'capabilities': ['vision']})

    def test_e6_evaluate_command_reports_top_k_with_a_denominator_from_separate_files(self):
        cases = [{'id': f'I{i}', 'description': ISSUE, 'revision': self.pinned} for i in range(1, 7)]
        oracle = {f'I{i}': {'file': 'reports.py', 'method': 'ExportService.build'} for i in range(1, 7)}
        (self.root / 'cases.json').write_text(json.dumps(cases)); (self.root / 'oracle.json').write_text(json.dumps(oracle))
        result = self.cli('issue', 'evaluate', '--cases', str(self.root / 'cases.json'), '--oracle', str(self.root / 'oracle.json'))
        self.assertEqual(result['denominator'], 6); self.assertEqual(len(result['cases']), 6)
        self.assertEqual({k: v['denominator'] for k, v in result['top_k'].items()}, {'1': 6, '3': 6, '5': 6})
        self.assertEqual(result['top_k']['5']['hits'], 6)
        self.assertTrue(all(r['seconds_to_candidate'] >= 0 and r['context_used'] is False for r in result['cases']))
        (self.root / 'cases.json').write_text(json.dumps([dict(cases[0], fix='reports.py:7')]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = learning_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'issue', 'evaluate',
                                      '--cases', str(self.root / 'cases.json'), '--oracle', str(self.root / 'oracle.json')])
        self.assertEqual(code, 2); self.assertIn('must not contain fixes', json.loads(out.getvalue())['error'])          # E10: a leaked fix is refused
