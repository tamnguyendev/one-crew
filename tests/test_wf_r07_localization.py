"""R07 provenance/capability laws on temporary repositories, no paid provider."""
import contextlib
import io
import json
from pathlib import Path
from unittest.mock import patch

from onecrew.discovery import Discovery
from onecrew.ledger import LedgerError
from onecrew.v2 import context, learning_cli, localization, plan as plans
from onecrew.v2.verifiers import command
from tests.test_v2_l1 import Fixture


ISSUE = 'Bấm "Xuất báo cáo" thì lỗi 500 khi chọn tháng 2.'


class LocalizationTests(Fixture):
    def setUp(self):
        super().setUp()
        (self.root / '.gitignore').write_text('.onecrew/\n')
        (self.root / 'ui.html').write_text('<button data-handler="ReportController.export" data-route="/reports/export">Xuất báo cáo</button>\n', encoding='utf-8')
        (self.root / 'reports.py').write_text('class ReportController:\n    def export(self, month):\n        return ExportService().build(month)\n\nclass ExportService:\n    def build(self, month):\n        return 31\n')
        (self.root / 'test_reports.py').write_text('def test_export_build():\n    assert ExportService().build(2) == 28\n')
        self.git('add', '.'); self.git('commit', '-q', '-m', 'before report issue repair')
        self.before = self.git('rev-parse', 'HEAD')
        self.propose('R')

    def test_text_suspects_have_pinned_sources_checks_and_separate_hypotheses(self):
        before_events = self.ledger.events(plans.show(self.ledger, 'R')['anchor_task'])
        with patch.object(Discovery, 'search', autospec=True, side_effect=Discovery.search) as search:
            result = localization.localize(self.ledger, ISSUE, revision=self.before, name='R')
        self.assertGreater(search.call_count, 0, 'the v1 search/coverage implementation is reused')
        suspects = {s['method']: s for s in result['suspects']}
        for name in ('ReportController.export', 'ExportService.build'):
            item = suspects[name]
            self.assertTrue(item['reason']); self.assertEqual(item['label'], 'hypothesis')
            self.assertEqual(item['source']['revision'], self.before)
            self.assertTrue(context.symbol_present(self.ledger.project, self.before, name, item['file'])[0])
            self.assertIn('test_export_build', item['next_check']['tests'])
            self.assertIn('tháng 2', item['next_check']['condition'])
        self.assertTrue(all(o['label'] == 'observed' for o in result['observations']))
        self.assertFalse(result['proposed_changes'])
        self.assertTrue(result['search_receipts'][0]['exhausted'])
        self.assertEqual(self.ledger.events(plans.show(self.ledger, 'R')['anchor_task']), before_events)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = learning_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'issue', 'localize', ISSUE,
                                      '--name', 'R', '--revision', self.before])
        self.assertEqual(code, 0, output.getvalue()); self.assertTrue(json.loads(output.getvalue())['suspects'])
        self.assertEqual(self.ledger.events(plans.show(self.ledger, 'R')['anchor_task']), before_events)

    def test_pinned_symbols_survive_head_rename_and_vague_issue_has_no_suspects(self):
        (self.root / 'reports.py').write_text('class RenamedService:\n    def renamed(self):\n        return 28\n')
        self.git('add', '.'); self.git('commit', '-q', '-m', 'future repair renamed old symbols')
        result = localization.localize(self.ledger, ISSUE, revision=self.before)
        self.assertIn('ExportService.build', [s['method'] for s in result['suspects']])
        self.assertFalse(context.symbol_present(self.root, 'HEAD', 'ExportService.build', 'reports.py')[0])
        vague = localization.localize(self.ledger, 'app chậm', revision=self.before)
        self.assertEqual(vague['status'], 'chưa đủ dữ liệu'); self.assertFalse(vague['suspects'])
        self.assertEqual(len(vague['needed']), 3)

    def test_image_capability_is_checked_before_any_image_access(self):
        calls = []
        missing = self.root / 'not-present.png'
        text_only = localization.localize(self.ledger, ISSUE, revision=self.before, image=missing,
                                          provider={'name': 'T', 'capabilities': [], 'observe_image': lambda p: calls.append(p)})
        self.assertFalse(calls); self.assertFalse(text_only['image']['read'])
        self.assertIn('không đọc ảnh', text_only['image']['reason'])
        self.assertFalse(any(o['source']['type'] == 'image' for o in text_only['observations']))
        image = self.root / 'error.png'; image.write_bytes(b'controlled fixture image bytes')
        def vision(path):
            calls.append(path.read_bytes())
            return ['Screen reports lỗi 500 on "Xuất báo cáo".']
        viewed = localization.localize(self.ledger, 'Error screenshot', revision=self.before, image=image,
                                       provider={'name': 'V', 'capabilities': ['vision'], 'observe_image': vision})
        self.assertEqual(calls, [image.read_bytes()]); self.assertTrue(viewed['image']['read'])
        self.assertTrue(any(o['source']['type'] == 'image' for o in viewed['observations']))
        self.assertTrue(viewed['suspects'])

    def test_incremental_map_uses_existing_context_and_rejects_forged_cached_declarations(self):
        first = localization.index_project(self.ledger, 'R', self.before)
        second = localization.index_project(self.ledger, 'R', self.before)
        self.assertFalse(second['recorded']); self.assertEqual(first['receipt'], second['receipt'])
        self.assertGreater(second['reused_files'], 0)
        (self.root / 'a.txt').write_text('changed unrelated text\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'next map')
        third = localization.index_project(self.ledger, 'R')
        self.assertGreater(third['reused_files'], 0); self.assertLess(third['reused_files'], third['files'])
        prior = localization._previous_map(self.ledger, 'R')
        file = next(f for f in prior['files'] if f['path'] == 'reports.py')
        file['symbols'][0]['symbol'] = 'Nonexistent.invented'
        actual = localization._build_map(self.ledger, 'HEAD', prior)
        self.assertFalse(any(s['symbol'] == 'Nonexistent.invented' for f in actual['files'] for s in f['symbols']))

    def test_related_lesson_is_data_and_never_a_fix_instruction(self):
        entry = {'key': 'lesson-x', 'lesson': 'x', 'text': 'Xuất báo cáo failed in an older case.', 'label': 'verified',
                 'scope': 'project', 'source': {'type': 'event', 'id': 1}}
        original = context.retrieve
        def retrieve(*args, **kwargs):
            value = original(*args, **kwargs)
            return dict(value, entries=[*value['entries'], entry])
        with patch.object(context, 'retrieve', side_effect=retrieve):
            result = localization.localize(self.ledger, ISSUE, revision=self.before)
        self.assertEqual(result['related_lessons'][0]['relevance'], 'similar, needs verification')
        self.assertFalse(result['related_lessons'][0]['authority']); self.assertFalse(result['proposed_changes'])


class HeldOutTests(Fixture):
    def test_six_pre_fix_issues_never_read_fix_or_own_issue_lessons(self):
        cases, labels, fixes = [], {}, {}
        for i in range(6):
            (self.root / 'component.py').write_text(f'class Feature{i}:\n    def execute_{i}(self):\n        return 0\n')
            (self.root / 'screen.html').write_text(f'<button data-handler="Feature{i}.execute_{i}">Screen action {i}</button>\n')
            self.git('add', '.'); self.git('commit', '-q', '-m', f'issue fixture {i} before repair')
            key = f'I{i}'
            cases.append({'id': key, 'description': f'Click "Screen action {i}" returns wrong result.', 'revision': self.git('rev-parse', 'HEAD')})
            labels[key] = {'file': 'component.py', 'method': f'Feature{i}.execute_{i}'}
            (self.root / 'component.py').write_text(f'class Feature{i}:\n    def execute_{i}(self):\n        return 1\n')
            self.git('add', '.'); self.git('commit', '-q', '-m', f'fix secret {i}')
            fixes[key] = self.git('rev-parse', 'HEAD')
        active, reads, oracle_times = [None], [], []
        real = localization.localize
        git = command._git
        def pinned(*args, **kwargs):
            active[0] = kwargs['issue_key']
            try: return real(*args, **kwargs)
            finally: active[0] = None
        def guarded(directory, *args, **kwargs):
            if active[0] and any(fixes[active[0]] in str(arg) for arg in args):
                reads.append(args)
                raise AssertionError('the fix oracle was read during lookup')
            return git(directory, *args, **kwargs)
        def oracle(key):
            self.assertIsNone(active[0], 'labels are inaccessible while localizing')
            oracle_times.append(key)
            return labels[key]
        with patch.object(localization, 'localize', side_effect=pinned), patch.object(command, '_git', side_effect=guarded), \
             patch.object(context, 'retrieve', side_effect=AssertionError('held-out lookup must not read issue lessons')):
            result = localization.evaluate(self.ledger, cases, oracle)
        self.assertEqual(reads, []); self.assertEqual(len(oracle_times), 6)
        self.assertEqual(result['denominator'], 6)
        for k in ('1', '3', '5'):
            self.assertEqual(result['top_k'][k], {'hits': 6, 'denominator': 6})
        self.assertTrue(all(r['seconds_to_candidate'] >= 0 and r['verified_root_cause_seconds'] is None for r in result['cases']))
        with self.assertRaises(LedgerError): localization.evaluate(self.ledger, [dict(cases[0], fix=fixes['I0'])], oracle)
