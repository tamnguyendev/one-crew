"""W50a evidence for T53a E2/E7 (every suspect exists at the pinned revision) and E8 (no proposed fix; a similar lesson is data with a check).

Same temporary repository and CLI as tests/test_wf_r07_localization.
"""
import contextlib
import io
import json
from unittest.mock import patch

from onecrew.v2 import context, learning_cli, localization
import tests.test_wf_r07_localization as base

ISSUE = base.ISSUE


class T53aEvidence(base.LocalizationTests):
    for _name in [n for n in dir(base.LocalizationTests) if n.startswith('test_')]:
        locals()[_name] = None
    del _name

    def cli_result(self, *extra):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = learning_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'issue', 'localize', ISSUE,
                                      '--name', 'R', '--revision', self.before, *extra])
        self.assertEqual(code, 0, output.getvalue())
        return json.loads(output.getvalue())

    def absent(self, result, revision):
        """Suspects whose symbol is not present at `revision` in the file they cite (the T53a E2/E7 check)."""
        return [s['method'] for s in result['suspects'] if not context.symbol_present(self.root, revision, s['method'], s['file'])[0]]

    def test_t53a_e2_e7_every_suspect_exists_at_the_pinned_revision_text_and_cli_and_image(self):
        """W50a / T53a E2 and E7: for EVERY entry of result['suspects'] (text path, CLI path, image path) the symbol is present at the
        pinned revision in its cited file, and its source names that revision."""
        image = self.root / 'error.png'
        image.write_bytes(b'controlled fixture image bytes')
        results = {
            'text': localization.localize(self.ledger, ISSUE, revision=self.before, name='R'),
            'cli': self.cli_result(),
            'image': localization.localize(self.ledger, ISSUE, revision=self.before, image=image,
                                           provider={'name': 'V', 'capabilities': ['vision'], 'observe_image': lambda path: ['Screen shows loi 500']}),
        }
        for label, result in results.items():
            with self.subTest(path=label):
                self.assertGreaterEqual(len(result['suspects']), 2)
                self.assertEqual(self.absent(result, self.before), [])
                for suspect in result['suspects']:
                    self.assertEqual(suspect['source']['revision'], self.before)
                    self.assertTrue(context.symbol_present(self.root, self.before, suspect['method'], suspect['source']['path'])[0])

    def test_t53a_e2_e7_counterexample_lookup_at_head_after_a_rename_goes_red(self):
        """W50a / T53a E2 counter-example: after a later commit renames the symbols, the pinned lookup still lists them and the pinned
        check is clean, while the same check run at HEAD instead of the pin reports them absent (red)."""
        (self.root / 'reports.py').write_text('class RenamedService:\n    def renamed(self):\n        return 28\n')
        self.git('add', '.')
        self.git('commit', '-q', '-m', 'future repair renamed old symbols')
        result = localization.localize(self.ledger, ISSUE, revision=self.before)
        self.assertTrue(result['suspects'])
        self.assertEqual(self.absent(result, self.before), [])
        at_head = self.absent(result, 'HEAD')
        self.assertIn('ExportService.build', at_head)
        self.assertIn('ReportController.export', at_head)

    def test_t53a_e2_e7_a_suspect_missing_at_the_pin_is_never_produced(self):
        """W50a / T53a E7: if the pinned revision lacks a symbol that exists at HEAD, no suspect is produced for it."""
        (self.root / 'reports.py').write_text((self.root / 'reports.py').read_text() +
                                              '\nclass LaterExport:\n    def build_later(self, month):\n        return 29\n')
        self.git('add', '.')
        self.git('commit', '-q', '-m', 'symbol introduced after the pin')
        result = localization.localize(self.ledger, ISSUE + ' build_later', revision=self.before)
        self.assertNotIn('LaterExport.build_later', [s['method'] for s in result['suspects']])
        self.assertEqual(self.absent(result, self.before), [])

    def test_t53a_e8_no_fix_is_proposed_and_a_similar_lesson_is_data_with_a_check(self):
        """W50a / T53a E8: with a similar lesson in context the output has no proposed change, the lesson is labelled 'similar, needs
        verification' and has no authority, the lesson alone creates no suspect (even when it names another symbol), and every suspect
        carries the next check (tests + reproduction action)."""
        plain = localization.localize(self.ledger, ISSUE, revision=self.before, name='R')
        entry = {'key': 'lesson-x', 'lesson': 'x', 'label': 'verified', 'scope': 'project', 'source': {'type': 'event', 'id': 1},
                 'text': 'Xuất báo cáo failed before: rewrite ExportService.build to always return 28 and delete Unrelated.helper.'}
        original = context.retrieve

        def with_lesson(*args, **kwargs):
            value = original(*args, **kwargs)
            return dict(value, entries=[*value['entries'], entry])
        with patch.object(context, 'retrieve', side_effect=with_lesson):
            result = localization.localize(self.ledger, ISSUE, revision=self.before, name='R')
        self.assertEqual(result['proposed_changes'], [])
        self.assertIn('not', result['notice'])
        related = result['related_lessons']
        self.assertEqual([r['lesson'] for r in related], ['x'])
        self.assertEqual(related[0]['relevance'], 'similar, needs verification')
        self.assertIs(related[0]['authority'], False)
        self.assertEqual([s['method'] for s in result['suspects']], [s['method'] for s in plain['suspects']])
        self.assertNotIn('Unrelated.helper', [s['method'] for s in result['suspects']])
        for suspect in result['suspects']:
            self.assertEqual(suspect['label'], 'hypothesis')
            self.assertTrue(suspect['next_check']['action'])
            self.assertEqual(suspect['next_check']['revision'], self.before)
        self.assertTrue(any(s['next_check']['tests'] for s in result['suspects']))
        self.assertFalse(any('fix' in json.dumps(s['reason']).casefold() for s in result['suspects']))
