"""W22 (RX1) - the document verifier adapter (`doc`): sources, structure, links and IDs, as a v2 verifier (T14a, the adapter half).

Three layers:
  DocChecksTests      the adapter on a plain folder (no ledger): each check finds what it is declared to find, and does NOT
                      find a problem in the good sample (so a check that always fails is red here too);
  DocConfigTests      the contract form (propose-time refusals, the core-owned `authority`);
  DocVerdictTests     the adapter through the real path `verdict run` -> receipt blob -> verdict.recorded on a Git project,
                      and through the checkout CLI module (not an installed-wheel drill).
The sample documents are real files in tests/wf_rx1_fixture. No model is called anywhere.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import contract as contracts, plan as plans, verdict
from onecrew.v2.verifiers import doc, port

from tests import test_v2_l1 as l1
from tests.test_v2_l1 import Fixture, plan_json

SAMPLE = Path(__file__).resolve().parent / 'wf_rx1_fixture'
PY = sys.executable

GOOD = {
    'docs': [
        {'path': 'docs/guide.md', 'headings': ['Tổng quan', 'Cài đặt', 'Nguồn'],
         'tables': [{'under': 'Cài đặt', 'columns': ['Bước', 'Lệnh']}],
         'sources': {'section': 'Nguồn', 'min': 1, 'cite': 'S\\d+', 'external': 'unverified'}},
        {'path': 'docs/design.md', 'headings': ['Kiến trúc']},
    ],
    'links': True,
    'ids': [{'name': 'REQ', 'pattern': 'REQ-\\d+', 'defined_in': ['docs/design.md']}],
}


def doc_config(**changes):
    value = json.loads(json.dumps(GOOD))
    value.update(changes)
    return value


def doc_milestone(config=None, mid='M1', **extra):
    return dict({'id': mid, 'title': 'Document ' + mid, 'verifier': {'type': 'doc', 'config': config or doc_config()}, 'covers': ['O1']}, **extra)


class Folder(unittest.TestCase):
    """A scratch copy of the sample documents."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'tree'
        shutil.copytree(SAMPLE, self.root)

    def edit(self, rel, old, new, count=1):
        path = self.root / rel
        text = path.read_text(encoding='utf-8')
        self.assertIn(old, text, 'the sample no longer contains ' + old)
        path.write_text(text.replace(old, new, count), encoding='utf-8', newline='\n')

    def check(self, config=None):
        normal = doc.validate_config(config or doc_config(), 'test')
        return doc.run(normal, port.Port(self.root, port.authority(None, 'test'), 'doc'))

    def problems(self, report, check):
        found = [c for c in report['checks'] if c['id'] == check]
        self.assertEqual(len(found), 1, f'check {check} missing from {[c["id"] for c in report["checks"]]}')
        return found[0]['problems']

    def assertClean(self, report):
        bad = {c['id']: c['problems'] for c in report['checks'] if not c['ok']}
        self.assertEqual(bad, {})

    def assertOnly(self, report, check):
        """Exactly one check is red, and it is `check`: the others stay green (a checker that fails everything would not pass this)."""
        bad = sorted(c['id'] for c in report['checks'] if not c['ok'])
        self.assertEqual(bad, [check], {c['id']: c['problems'] for c in report['checks'] if not c['ok']})


class DocChecksTests(Folder):
    def test_the_good_sample_is_clean_and_every_check_ran(self):
        report = self.check()
        self.assertClean(report)
        ids = [c['id'] for c in report['checks']]
        self.assertEqual(ids, ['documents', 'structure', 'sources', 'links', 'ids'])
        self.assertTrue(all(c['checked'] > 0 for c in report['checks']), 'a check that examined nothing proves nothing')

    # ---- sources ----------------------------------------------------------------------------------------------------
    def test_a_cited_source_file_that_does_not_exist_is_a_problem(self):
        (self.root / 'sources' / 'notes.txt').unlink()
        report = self.check()
        self.assertOnly(report, 'sources')
        self.assertTrue(any('S2' in p and 'sources/notes.txt' in p for p in self.problems(report, 'sources')), self.problems(report, 'sources'))

    def test_a_source_anchor_that_does_not_exist_is_a_problem(self):
        self.edit('docs/guide.md', 'spec.md#phạm-vi', 'spec.md#không-có')
        report = self.check()
        self.assertTrue(any('S1' in p and 'không-có' in p for p in self.problems(report, 'sources')))

    def test_a_citation_without_an_entry_is_a_problem(self):
        self.edit('docs/guide.md', 'Tham khảo thêm [S3].', 'Tham khảo thêm [S3] và [S7].')
        report = self.check()
        self.assertOnly(report, 'sources')
        self.assertTrue(any('S7' in p for p in self.problems(report, 'sources')))

    def test_a_source_entry_without_a_locator_is_a_problem(self):
        self.edit('docs/guide.md', '- [S2] sources/notes.txt — ghi chú phỏng vấn', '- [S2] ghi chú phỏng vấn')
        self.assertTrue(any('S2' in p and 'locator' in p for p in self.problems(self.check(), 'sources')))

    def test_a_missing_sources_section_is_a_problem(self):
        self.edit('docs/guide.md', '## Nguồn', '## Tài liệu')
        report = self.check()
        self.assertTrue(any('Nguồn' in p for p in self.problems(report, 'sources')))

    def test_fewer_sources_than_the_declared_minimum_is_a_problem(self):
        config = doc_config()
        config['docs'][0]['sources']['min'] = 4
        self.assertTrue(any('at least 4' in p for p in self.problems(self.check(config), 'sources')))

    def test_external_sources_are_listed_as_not_verified_and_can_be_forbidden(self):
        report = self.check()
        self.assertClean(report)
        self.assertEqual(len(report['unverified']), 1)
        self.assertIn('https://example.invalid/tham-khao', report['unverified'][0])     # named, never reported as reachable
        config = doc_config()
        config['docs'][0]['sources']['external'] = 'forbid'
        self.assertTrue(any('S3' in p and 'external' in p for p in self.problems(self.check(config), 'sources')))

    def test_a_citation_inside_a_code_block_is_not_a_citation(self):
        # the sample cites [S9] only inside a fenced block: clean. Move it into the text: a problem.
        self.assertClean(self.check())
        self.edit('docs/guide.md', 'Tham khảo thêm [S3].', 'Tham khảo thêm [S3] [S9].')
        self.assertTrue(any('S9' in p for p in self.problems(self.check(), 'sources')))

    # ---- structure --------------------------------------------------------------------------------------------------
    def test_a_missing_required_heading_is_a_problem(self):
        self.edit('docs/guide.md', '## Cài đặt\n', '## Triển khai\n')
        report = self.check()
        self.assertTrue(any('Cài đặt' in p for p in self.problems(report, 'structure')))

    def test_a_heading_at_the_wrong_level_is_a_problem(self):
        config = doc_config()
        config['docs'][0]['headings'] = ['Tổng quan', {'text': 'Cài đặt', 'level': 3}]
        self.assertTrue(any('level 3' in p for p in self.problems(self.check(config), 'structure')))
        config['docs'][0]['headings'] = ['Tổng quan', {'text': 'Cài đặt', 'level': 2}]
        self.assertClean(self.check(config))

    def test_a_heading_inside_a_code_block_does_not_count(self):
        self.edit('docs/guide.md', '## Nguồn\n', '```text\n## Phần giả\n```\n\n## Nguồn\n')
        config = doc_config()
        config['docs'][0]['headings'].append('Phần giả')
        self.assertTrue(any('Phần giả' in p for p in self.problems(self.check(config), 'structure')))

    def test_ordered_headings_must_come_in_the_declared_order(self):
        config = doc_config()
        config['docs'][0].update(headings=['Nguồn', 'Tổng quan'], ordered=True)
        self.assertTrue(any('order' in p for p in self.problems(self.check(config), 'structure')))
        config['docs'][0]['ordered'] = False
        self.assertClean(self.check(config))

    def test_a_required_table_must_exist_under_its_heading_with_its_columns_in_order(self):
        self.edit('docs/guide.md', '| Bước | Lệnh | Ghi chú |', '| Lệnh | Bước | Ghi chú |')
        self.assertTrue(any('Cài đặt' in p and 'Bước' in p for p in self.problems(self.check(), 'structure')))

    def test_a_table_under_another_heading_does_not_satisfy_the_requirement(self):
        config = doc_config()
        config['docs'][0]['tables'] = [{'under': 'Tổng quan', 'columns': ['Bước', 'Lệnh']}]
        self.assertTrue(any('Tổng quan' in p for p in self.problems(self.check(config), 'structure')))

    # ---- links ------------------------------------------------------------------------------------------------------
    def test_a_link_to_a_file_that_does_not_exist_is_a_problem(self):
        self.edit('docs/guide.md', '(design.md#kiến-trúc)', '(thiet-ke.md#kiến-trúc)')
        report = self.check()
        self.assertOnly(report, 'links')
        self.assertTrue(any('thiet-ke.md' in p for p in self.problems(report, 'links')))

    def test_a_link_to_a_heading_that_does_not_exist_is_a_problem(self):
        self.edit('docs/guide.md', '#cài-đặt)', '#cai-dat)')
        self.assertTrue(any('#cai-dat' in p for p in self.problems(self.check(), 'links')))

    def test_a_duplicate_heading_gets_a_numbered_anchor(self):
        self.assertClean(self.check())                                  # design.md links to #kiến-trúc-1
        self.edit('docs/design.md', '(#kiến-trúc-1)', '(#kiến-trúc-2)')
        self.assertTrue(any('kiến-trúc-2' in p for p in self.problems(self.check(), 'links')))

    def test_a_link_that_leaves_the_project_is_a_problem_not_a_read(self):
        self.edit('docs/guide.md', '(design.md#kiến-trúc)', '(../../etc/passwd)')
        problems = self.problems(self.check(), 'links')
        self.assertTrue(any('outside' in p for p in problems), problems)

    def test_a_link_is_case_sensitive_like_the_repository(self):
        self.edit('docs/guide.md', '(design.md#kiến-trúc)', '(Design.md#kiến-trúc)')
        self.assertTrue(any('Design.md' in p for p in self.problems(self.check(), 'links')))

    def test_a_missing_image_is_a_problem(self):
        (self.root / 'img' / 'diagram.png').unlink()
        self.assertTrue(any('diagram.png' in p for p in self.problems(self.check(), 'links')))

    def test_a_reference_style_link_is_checked(self):
        self.edit('docs/guide.md', '## Nguồn', 'Xem [mục kia][k].\n\n[k]: khong-co-file.md\n\n## Nguồn')
        self.assertTrue(any('khong-co-file.md' in p for p in self.problems(self.check(), 'links')))

    def test_a_link_inside_a_code_block_or_a_code_span_is_not_checked(self):
        self.assertClean(self.check())                                  # the sample has a broken link inside a fenced block
        self.edit('docs/guide.md', 'Tham khảo thêm [S3].', 'Tham khảo thêm [S3]. Mã `[x](khong-co.md)` thì bỏ qua.')
        self.assertClean(self.check())

    def test_web_links_are_listed_as_not_verified(self):
        self.edit('docs/guide.md', 'Tham khảo thêm [S3].', 'Tham khảo thêm [S3] và [web](https://example.invalid/x).')
        report = self.check()
        self.assertClean(report)
        self.assertTrue(any('https://example.invalid/x' in u for u in report['unverified']))

    def test_links_can_be_switched_off_but_then_the_check_is_not_reported(self):
        self.edit('docs/guide.md', '(design.md#kiến-trúc)', '(thiet-ke.md)')
        report = self.check(doc_config(links=False))
        self.assertNotIn('links', [c['id'] for c in report['checks']])

    # ---- ids --------------------------------------------------------------------------------------------------------
    def test_an_id_used_but_never_defined_is_a_problem(self):
        self.edit('docs/guide.md', 'REQ-1 và REQ-2', 'REQ-1 và REQ-3')
        report = self.check()
        self.assertOnly(report, 'ids')
        self.assertTrue(any('REQ-3' in p for p in self.problems(report, 'ids')))

    def test_an_id_defined_twice_is_a_problem(self):
        self.edit('docs/design.md', '### REQ-2 Kiểm được sau khi cài', '### REQ-1 Kiểm được sau khi cài')
        problems = self.problems(self.check(), 'ids')
        self.assertTrue(any('REQ-1' in p and 'twice' in p for p in problems), problems)

    def test_an_id_inside_a_code_block_is_not_a_reference(self):
        self.assertClean(self.check())                                  # REQ-99 appears only inside a fenced block
        self.edit('docs/guide.md', 'Tham khảo thêm [S3].', 'Tham khảo thêm [S3] (REQ-99).')
        self.assertTrue(any('REQ-99' in p for p in self.problems(self.check(), 'ids')))

    def test_a_longer_id_is_not_mistaken_for_a_shorter_one(self):
        self.edit('docs/guide.md', 'REQ-1 và REQ-2', 'REQ-1 và REQ-2 và XREQ-9 và REQ-2x')
        self.assertClean(self.check())

    # ---- the documents themselves -----------------------------------------------------------------------------------
    def test_a_declared_document_that_is_missing_is_a_problem_not_a_silent_pass(self):
        (self.root / 'docs' / 'design.md').unlink()
        report = self.check()
        self.assertTrue(any('docs/design.md' in p for p in self.problems(report, 'documents')))

    def test_a_document_that_is_not_utf8_is_a_problem(self):
        (self.root / 'docs' / 'design.md').write_bytes(b'# Thi\xe1\xbaxt\xff\xfe k\xe1\n')
        self.assertTrue(any('UTF-8' in p for p in self.problems(self.check(), 'documents')))

    def test_a_document_over_the_size_limit_is_inconclusive_not_a_pass(self):
        (self.root / 'docs' / 'design.md').write_bytes(b'x' * (doc.MAX_FILE + 1))
        with self.assertRaises(port.Inconclusive):
            self.check()

    def test_an_empty_document_is_a_problem(self):
        (self.root / 'docs' / 'design.md').write_text('', encoding='utf-8')
        self.assertTrue(any('empty' in p for p in self.problems(self.check(), 'documents')))

    def test_the_adapter_module_imports_nothing_that_reaches_the_shell_the_network_or_the_ledger(self):
        import ast
        tree = ast.parse(Path(doc.__file__).read_text(encoding='utf-8'))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): imported |= {a.name for a in node.names}
            if isinstance(node, ast.ImportFrom): imported.add('.' * node.level + (node.module or ''))
        forbidden = {'os', 'subprocess', 'shutil', 'socket', 'urllib.request', 'http', 'http.client', 'ctypes', 'pathlib', 'tempfile', 'importlib'}
        self.assertEqual(imported & forbidden, set())
        self.assertEqual({m for m in imported if m.startswith('.')}, {'...ledger', '...snapshots', '.'})      # no plan, verdict, gate or Ledger object

    def test_the_adapter_does_not_write_anywhere(self):
        before = sorted((str(p.relative_to(self.root)), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file())
        self.check()
        after = sorted((str(p.relative_to(self.root)), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file())
        self.assertEqual(before, after)


class DocConfigTests(Fixture):
    def test_a_doc_milestone_is_a_valid_contract_and_the_authority_is_filled_by_the_core(self):
        value = contracts.validate(plan_json(milestones=[doc_milestone()]))
        config = value['milestones'][0]['verifier']['config']
        self.assertEqual(config['authority'], {'retries': 0, 'calls': 0, 'commands': [], 'max_minutes': 5})
        self.assertEqual(config['docs'][0], doc.validate_config(GOOD, 'x')['docs'][0])

    def test_bad_configs_are_refused_at_propose_not_at_run(self):
        good = doc_config()
        def broken(**changes): return dict(good, **changes)
        cases = {
            'no documents': broken(docs=[]),
            'unknown key': broken(extra=1),
            'a path that leaves the project': broken(docs=['../x.md']),
            'an absolute path': broken(docs=['/etc/x.md']),
            'not Markdown': broken(docs=['docs/a.py']),
            'a drive path': broken(docs=['C:/x.md']),
            'duplicate document': broken(docs=['docs/a.md', 'docs/a.md']),
            'too many documents': broken(docs=[f'docs/{n}.md' for n in range(40)]),
            'a bad regular expression': broken(ids=[{'name': 'X', 'pattern': '(', 'defined_in': ['docs/a.md']}]),
            'a pattern that is too long': broken(ids=[{'name': 'X', 'pattern': 'a' * 300}]),
            'unknown heading key': broken(docs=[{'path': 'docs/a.md', 'headings': [{'text': 'A', 'lvl': 2}]}]),
            'external is not a known mode': broken(docs=[{'path': 'docs/a.md', 'sources': {'section': 'S', 'external': 'trust'}}]),
            'a table without columns': broken(docs=[{'path': 'docs/a.md', 'tables': [{'under': 'A', 'columns': []}]}]),
            'a link switch that is not a boolean': broken(links='yes'),
        }
        for label, config in cases.items():
            with self.subTest(label), self.assertRaises(LedgerError):
                contracts.validate(plan_json(milestones=[doc_milestone(config)]))
        self.assertTrue(contracts.validate(plan_json(milestones=[doc_milestone(broken(docs=['docs/a.md'], ids=[]))])))

    def test_the_authority_is_bounded_by_the_core_not_by_the_adapter(self):
        for label, authority in {'retries over the cap': {'retries': 9}, 'calls over the cap': {'calls': 99}, 'a command as a string': {'commands': ['make']},
                                 'too many commands': {'commands': [[PY, '-c', '1']] * 9}, 'unknown field': {'unconfined': True},
                                 'minutes over the cap': {'max_minutes': 600}}.items():
            with self.subTest(label), self.assertRaises(LedgerError):
                contracts.validate(plan_json(milestones=[doc_milestone(dict(doc_config(), authority=authority))]))
        value = contracts.validate(plan_json(milestones=[doc_milestone(dict(doc_config(), authority={'retries': 1}))]))
        self.assertEqual(value['milestones'][0]['verifier']['config']['authority']['retries'], 1)

    def test_an_unknown_verifier_type_is_still_refused(self):
        with self.assertRaises(LedgerError):
            contracts.validate(plan_json(milestones=[dict(doc_milestone(), verifier={'type': 'magic', 'config': {}})]))

    def test_an_adapter_cannot_take_a_name_of_the_core(self):
        class Impostor:
            NAME = 'command'
            validate_config = staticmethod(lambda config, label: config)
            run = staticmethod(lambda config, p: {})
        with self.assertRaises(LedgerError): port.register(Impostor)


class DocVerdictTests(Fixture):
    """The adapter on the real path, on a Git project (the sample documents committed)."""

    def setUp(self):
        super().setUp()
        shutil.copytree(SAMPLE, self.root, dirs_exist_ok=True)
        self.git('add', '.'); self.git('commit', '-q', '-m', 'documents')

    def doc_plan(self, config=None, name='P1', **kw):
        return self.approved(name, plan_json(milestones=[doc_milestone(config, **kw)]))

    def write(self, rel, old, new, commit=True):
        path = self.root / rel
        path.write_text(path.read_text(encoding='utf-8').replace(old, new), encoding='utf-8', newline='\n')
        if commit: self.git('commit', '-qam', 'edit ' + rel)

    def receipt_of(self, view):
        key = view['milestones'][0]['last_verdict']['receipt']
        return json.loads(Snapshots(self.ledger.state_root).read_blob(key).decode('utf-8'))

    def test_a_clean_document_passes_with_a_receipt_the_core_issued(self):
        self.doc_plan()
        view = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(view['milestones'][0]['state'], 'passed')
        self.assertEqual(view['milestones'][0]['last_verdict']['by'], 'doc')
        receipt = self.receipt_of(view)
        self.assertEqual((receipt['kind'], receipt['adapter'], receipt['violations']), ('doc-receipt', 'doc', []))
        self.assertEqual(receipt['artifact_sha'], self.tree())
        self.assertEqual([c['id'] for c in receipt['checks']], ['documents', 'structure', 'sources', 'links', 'ids'])
        self.assertEqual(receipt['config']['docs'][0]['path'], 'docs/guide.md')
        kinds = self.kinds()
        self.assertLess(kinds.index('verdict.receipt_issued'), kinds.index('verdict.recorded'))
        self.assertEqual(self.kinds().count('adapter.violation'), 0)

    def test_a_broken_link_fails_the_milestone_and_the_repair_passes_it(self):
        self.doc_plan(max_repairs=2)
        self.write('docs/guide.md', '(design.md#kiến-trúc)', '(thiet-ke.md#kiến-trúc)')
        view = verdict.run(self.ledger, 'P1', 'M1', self.root)
        row = view['milestones'][0]
        self.assertEqual((row['state'], row['failures'], row['repairs_left']), ('failed', 1, 1))
        receipt = self.receipt_of(view)
        self.assertEqual([c['id'] for c in receipt['checks'] if not c['ok']], ['links'])
        finding = receipt['findings'][0]
        self.assertEqual(finding['status'], 'open')                         # a finding the adapter reports is open; only the core closes one
        self.assertIn('thiet-ke.md', finding['text'])
        self.write('docs/guide.md', '(thiet-ke.md#kiến-trúc)', '(design.md#kiến-trúc)')
        self.assertEqual(verdict.run(self.ledger, 'P1', 'M1', self.root)['milestones'][0]['state'], 'passed')

    def test_the_check_reads_the_artifact_not_the_live_folder(self):
        self.doc_plan()
        (self.root / '.gitignore').write_text('ignored.md\n'); self.git('add', '.gitignore'); self.git('commit', '-qm', 'ignore')
        (self.root / 'ignored.md').write_text('# only on this disk\n')
        self.write('docs/guide.md', '(design.md#kiến-trúc)', '(../ignored.md)')
        row = verdict.run(self.ledger, 'P1', 'M1', self.root)['milestones'][0]
        self.assertEqual(row['state'], 'failed')                              # an ignored file is not part of the artifact

    def test_an_untracked_document_is_part_of_the_artifact(self):
        self.doc_plan()
        (self.root / 'docs' / 'extra.md').write_text('# Thêm\n', encoding='utf-8')
        self.write('docs/guide.md', '(design.md#kiến-trúc)', '(extra.md)', commit=False)
        self.assertEqual(verdict.run(self.ledger, 'P1', 'M1', self.root)['milestones'][0]['state'], 'passed')

    def test_stopping_at_max_repairs_works_like_every_other_milestone(self):
        self.doc_plan(max_repairs=0)
        self.write('docs/guide.md', '(design.md#kiến-trúc)', '(thiet-ke.md#kiến-trúc)')
        view = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(view['status'], 'stopped_with_report')
        self.assertIn('milestone.stopped', self.kinds())

    def test_a_hand_written_doc_receipt_is_refused(self):
        self.doc_plan()
        sha = self.tree()
        with self.ledger.transaction() as conn:
            plan_sha = plans.derive(self.ledger, conn, 'P1')['revisions'][1]['sha']
        config = contracts.validate(plan_json(milestones=[doc_milestone()]))['milestones'][0]['verifier']['config']
        body = {'kind': 'doc-receipt', 'adapter': 'doc', 'plan': 'P1', 'revision': 1, 'plan_sha': plan_sha, 'milestone': 'M1', 'config': config,
                'artifact_sha': sha, 'artifact_sha_after': sha, 'checks': [{'id': 'documents', 'ok': True, 'checked': 1, 'problems': []}],
                'findings': [], 'unverified': [], 'violations': [], 'error': None, 'timed_out': False}
        blob = Snapshots(self.ledger.state_root).blob(json.dumps(body, sort_keys=True).encode())
        with self.assertRaises(LedgerError) as caught: verdict.record(self.ledger, 'P1', 'M1', 'pass', 'doc', blob, sha)
        self.assertIn('not issued by verdict run', str(caught.exception))
        self.assertEqual(plans.show(self.ledger, 'P1')['milestones'][0]['runs'], 0)

    def test_a_doc_milestone_is_not_verified_by_another_verifier_or_by_an_owner_word(self):
        self.doc_plan()
        for by in ('command', 'reviewer', 'owner', 'claude'):
            with self.subTest(by), self.assertRaises(LedgerError):
                verdict.record(self.ledger, 'P1', 'M1', 'pass', by, '0' * 64, self.tree())

    def test_the_verdict_must_match_what_the_receipt_supports(self):
        self.doc_plan(max_repairs=2)
        self.write('docs/guide.md', '(design.md#kiến-trúc)', '(thiet-ke.md#kiến-trúc)')
        view = verdict.run(self.ledger, 'P1', 'M1', self.root)
        key = view['milestones'][0]['last_verdict']['receipt']
        with self.assertRaises(LedgerError) as caught: verdict.record(self.ledger, 'P1', 'M1', 'pass', 'doc', key, self.tree())
        self.assertIn('supports a fail verdict', str(caught.exception))
        self.assertEqual(plans.show(self.ledger, 'P1')['milestones'][0]['runs'], 1)

    def test_the_checkout_cli_runs_a_doc_milestone(self):
        self.doc_plan()
        state = Path(self.ledger.state_root)
        command = [PY, '-X', 'utf8', '-m', 'onecrew.v2.plan_cli', '--project', str(self.root), '--state-root', str(state), 'verdict', 'run', '--plan', 'P1', '--milestone', 'M1']
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        done = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', env=env, cwd=str(self.root))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)['milestones'][0]['state'], 'passed')

    def test_plan_lint_accepts_a_doc_contract(self):
        from onecrew.v2 import lint
        self.assertEqual(lint.lint(lint.ReadOnlyLedger(self.root, self.ledger.state_root), plan_json(milestones=[doc_milestone()]), 'claude-sonnet-5-5'), [])

    def test_the_report_of_a_doc_root_renders(self):
        from onecrew.v2 import report
        self.doc_plan()
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        text = report.render_report(self.ledger.state_root, 'P1')
        self.assertIn('M1', text)


if __name__ == '__main__':
    unittest.main()
