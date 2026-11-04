"""2.3-A1 (docs/v23/HOP-DONG-2.3.vi.md §4, KA-01…KA-20): read the project's sourced knowledge and deliver it to a worker.

One reader for both sources of knowledge — wiki pages of the project (Markdown, pinned by content hash at the revision read) and the
ledger's context entries — chooses what a consumer (a root, a node of it) may use: inside the project, inside the consumer's read
scope, still applicable at the current revision/conditions, relevant to the task, within a character cap that never drops a
mandatory constraint silently. The supported adapter (NativeExecutor) puts exactly that package in the worker prompt and seals
it in the attempt receipt; what the worker declares it used is checked against what was delivered. A1 writes no knowledge.

These are checkout tests on real git repositories and real ledgers; the provider is a fixture worker (no model call).
"""
import copy
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from onecrew.common_executor import NativeExecutor
from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import context, knowledge, plan as plans, wiki
from tests.test_v2_l1 import plan_json
from tests.test_wf_engine import EngineFixture, node

PIN = {'role': 'worker', 'provider': 'claude', 'model': 'claude-haiku-5-5'}


def fence(meta):
    return '```onecrew\n' + json.dumps(meta) + '\n```\n'


class KnowledgeFixture(EngineFixture):
    def setUp(self):
        super().setUp()
        (self.root / 'b.txt').write_text('two\n')
        (self.root / 'requirements.txt').write_text('lib==1.0\n')
        self.git('add', '.'); self.git('commit', '-q', '-m', 'more files')
        self.head = self.git('rev-parse', 'HEAD')
        self.wiki_dir = self.root / 'docs' / 'wiki'
        self.wiki_dir.mkdir(parents=True)

    def page(self, name, text, commit=True):
        (self.wiki_dir / name).write_text(text, encoding='utf-8')
        if commit:
            self.git('add', '.'); self.git('commit', '-q', '-m', 'wiki ' + name)
            self.head = self.git('rev-parse', 'HEAD')

    def item(self, nid='C', read=('a.txt',), write=('a.txt',), goal='Produce evidence for O1'):
        value = node(nid, write=write)
        value['read'] = list(read); value['goal'] = goal; value['executor'] = dict(PIN)
        return value

    def consumer(self, item=None, plan='P1'):
        return knowledge.consumer(self.ledger, plan, node=item or self.item())

    def ids(self, package, use=None):
        return [e['id'] for e in package['entries'] if use is None or e['use'] == use]


class ReaderTests(KnowledgeFixture):
    def test_ka01_every_entry_carries_its_source_revision_and_content_hash(self):
        self.page('auth.md', '# Notes\n\n## a.txt keeps one line\n' + fence({
            'id': 'one-line', 'kind': 'constraint', 'label': 'verified', 'must': True, 'applies_to': ['a.txt'],
            'sources': [{'type': 'file', 'path': 'a.txt', 'revision': self.head}]}) + 'Never split a.txt into two lines.\n\n'
            '## Free note\nThe team prefers short commits in a.txt work.\n')
        package = knowledge.package(self.ledger, self.consumer(), cap_chars=6000)
        by_id = {e['id']: e for e in package['entries']}
        self.assertIn('one-line', by_id)
        entry = by_id['one-line']
        self.assertEqual(entry['origin']['type'], 'wiki')
        self.assertEqual(entry['origin']['path'], 'docs/wiki/auth.md')
        self.assertRegex(entry['origin']['sha256'], r'^[0-9a-f]{64}$')
        self.assertEqual(entry['use'], 'fact'); self.assertTrue(entry['must'])
        free = [e for e in package['entries'] if e['id'] != 'one-line']
        self.assertEqual(len(free), 1)
        self.assertEqual(free[0]['label'], 'unverified')                 # a section without typed source is a lead, never a fact
        self.assertEqual(free[0]['use'], 'lead')
        self.assertTrue(package['data_not_authority'])

    def test_ka02_a_changed_page_changes_the_knowledge_revision(self):
        self.page('auth.md', '## Note\nkeep a.txt short\n')
        first = knowledge.package(self.ledger, self.consumer(), cap_chars=6000)['revision']
        self.page('auth.md', '## Note\nkeep a.txt very short\n', commit=False)       # uncommitted edits are a new state too
        second = knowledge.package(self.ledger, self.consumer(), cap_chars=6000)['revision']
        self.assertNotEqual(first, second)

    def test_ka03_another_project_on_the_same_state_root_is_invisible(self):
        other = Path(self.temp.name) / 'other'; other.mkdir()
        subprocess.run(['git', '-C', str(other), 'init', '-q'], check=True)
        subprocess.run(['git', '-C', str(other), 'config', 'user.email', 't@localhost'], check=True)
        subprocess.run(['git', '-C', str(other), 'config', 'user.name', 'T'], check=True)
        (other / 'a.txt').write_text('other\n')
        subprocess.run(['git', '-C', str(other), 'add', '.'], check=True); subprocess.run(['git', '-C', str(other), 'commit', '-qm', 'o'], check=True)
        second = Ledger(other, self.ledger.state_root)
        plans.propose(second, 'Q1', plan_json(), 'codex')
        context.add(second, 'Q1', kind='decision', label='verified', text='Other project secret decision about a.txt',
                    source={'type': 'file_line', 'path': 'a.txt', 'line': 1, 'revision': 'HEAD'})
        package = knowledge.package(self.ledger, self.consumer(), cap_chars=6000)
        self.assertNotIn('secret', json.dumps(package))

    def test_ka04_a_source_outside_the_read_scope_is_not_delivered_and_not_named(self):
        self.page('b.md', '## b.txt format\n' + fence({'id': 'b-format', 'kind': 'finding', 'label': 'verified', 'applies_to': ['a.txt'],
                  'sources': [{'type': 'file', 'path': 'b.txt', 'revision': self.head}]}) + 'b.txt holds the PRIVATE-B format.\n')
        package = knowledge.package(self.ledger, self.consumer(self.item(read=('a.txt',))), cap_chars=6000)
        self.assertNotIn('b-format', self.ids(package))
        self.assertNotIn('PRIVATE-B', json.dumps(package))
        self.assertEqual(package['omitted']['by_reason'].get('source_outside_read_scope'), 1)
        allowed = knowledge.package(self.ledger, self.consumer(self.item(read=('a.txt', 'b.txt'))), cap_chars=6000)
        self.assertIn('b-format', self.ids(allowed))

    def test_ka05_working_memory_of_a_root_stays_with_that_root(self):
        context.add(self.ledger, 'P1', kind='decision', label='verified', text='P1 decided to keep a.txt as one line',
                    source={'type': 'file_line', 'path': 'a.txt', 'line': 1, 'revision': 'HEAD'})
        mine = knowledge.package(self.ledger, self.consumer(), cap_chars=6000)
        self.assertTrue(any('keep a.txt as one line' in e['text'] for e in mine['entries']))
        plans.propose(self.ledger, 'P2', plan_json(), 'codex', workflow=True, capabilities=self.engine_caps)
        other = knowledge.package(self.ledger, knowledge.consumer(self.ledger, 'P2', node=self.item()), cap_chars=6000)
        self.assertFalse(any('keep a.txt as one line' in e['text'] for e in other['entries']))


class SelectionTests(KnowledgeFixture):
    def test_ka06_many_newer_unrelated_entries_do_not_push_out_an_old_mandatory_constraint(self):
        self.page('core.md', '## a.txt line rule\n' + fence({'id': 'old-rule', 'kind': 'constraint', 'label': 'verified', 'must': True,
                  'applies_to': ['a.txt'], 'sources': [{'type': 'file', 'path': 'a.txt', 'revision': self.head}]}) + 'Keep a.txt to one line.\n')
        noise = ''.join(f'## Unrelated topic {i}\nThe deployment calendar entry number {i} for the marketing site.\n' for i in range(260))
        self.page('noise.md', noise)
        package = knowledge.package(self.ledger, self.consumer(), cap_chars=6000)
        self.assertIn('old-rule', self.ids(package))
        self.assertGreaterEqual(package['omitted']['total'], 200)
        self.assertFalse(package['omitted']['eof'])

    def test_ka07_mandatory_knowledge_over_the_cap_stops_before_any_model_call(self):
        long = 'Keep a.txt exactly as specified. ' * 200
        self.page('must.md', '## Big rule\n' + fence({'id': 'big', 'kind': 'constraint', 'label': 'verified', 'must': True,
                  'applies_to': ['a.txt'], 'sources': [{'type': 'file', 'path': 'a.txt', 'revision': self.head}]}) + long + '\n')
        with self.assertRaises(knowledge.KnowledgeOverflow) as caught:
            knowledge.package(self.ledger, self.consumer(), cap_chars=8000)
        self.assertIn('big', str(caught.exception))

    def test_ka08_optional_entries_over_the_cap_are_listed_with_a_total_and_a_cursor(self):
        body = ''.join(f'## a.txt hint {i}\nHint {i} about a.txt formatting and the O1 evidence.\n' for i in range(40))
        self.page('hints.md', body)
        package = knowledge.package(self.ledger, self.consumer(), cap_chars=5500)
        self.assertTrue(package['entries'])
        omitted = package['omitted']
        self.assertGreater(omitted['by_reason'].get('cap', 0), 0)
        self.assertEqual(omitted['total'], sum(omitted['by_reason'].values()))
        self.assertTrue(omitted['cursor']); self.assertFalse(omitted['eof'])
        self.assertTrue(all(row['reason'] == 'cap' for row in omitted['index']))


class ApplicabilityTests(KnowledgeFixture):
    def test_ka09_a_refuted_conclusion_whose_source_changed_becomes_a_lead(self):
        self.page('r.md', '## Two-line a.txt fails\n' + fence({'id': 'two-fails', 'kind': 'rejected', 'label': 'refuted', 'applies_to': ['a.txt'],
                  'sources': [{'type': 'file', 'path': 'a.txt', 'revision': self.head}]}) + 'Writing two lines into a.txt was tried and failed.\n')
        unchanged = {e['id']: e for e in knowledge.package(self.ledger, self.consumer(), cap_chars=6000)['entries']}
        self.assertEqual(unchanged['two-fails']['use'], 'rejected')
        (self.root / 'a.txt').write_text('one\nnow two\n'); self.git('commit', '-qam', 'a.txt changed')
        changed = {e['id']: e for e in knowledge.package(self.ledger, self.consumer(), cap_chars=6000)['entries']}
        self.assertEqual(changed['two-fails']['use'], 'lead')
        self.assertEqual(changed['two-fails']['label'], 'refuted')                  # history kept, current use re-opened
        self.assertEqual(changed['two-fails']['applicability']['state'], 'recheck')

    def test_ka10_same_source_but_a_changed_dependency_is_not_used_as_a_fact(self):
        self.page('d.md', '## lib 1.0 quirk\n' + fence({'id': 'lib-quirk', 'kind': 'finding', 'label': 'verified', 'applies_to': ['a.txt'],
                  'sources': [{'type': 'file', 'path': 'a.txt', 'revision': self.head}],
                  'conditions': [{'type': 'file_contains', 'path': 'requirements.txt', 'text': 'lib==1.0'}]}) + 'With lib 1.0, a.txt needs a trailing newline.\n')
        self.assertEqual({e['id']: e['use'] for e in knowledge.package(self.ledger, self.consumer(), cap_chars=6000)['entries']}['lib-quirk'], 'fact')
        (self.root / 'requirements.txt').write_text('lib==2.0\n'); self.git('commit', '-qam', 'lib 2')
        package = knowledge.package(self.ledger, self.consumer(), cap_chars=6000)
        self.assertNotIn('lib-quirk', [e['id'] for e in package['entries'] if e['use'] == 'fact'])
        self.assertEqual(package['omitted']['by_reason'].get('not_applicable'), 1)

    def test_ka11_an_unverifiable_condition_makes_the_entry_a_lead_only(self):
        self.page('u.md', '## Works on the build server\n' + fence({'id': 'server', 'kind': 'finding', 'label': 'verified', 'applies_to': ['a.txt'],
                  'sources': [{'type': 'file', 'path': 'a.txt', 'revision': self.head}],
                  'conditions': [{'type': 'text', 'text': 'only on the nightly build server'}]}) + 'a.txt is generated there.\n')
        entry = {e['id']: e for e in knowledge.package(self.ledger, self.consumer(), cap_chars=6000)['entries']}['server']
        self.assertEqual((entry['use'], entry['applicability']['state']), ('lead', 'unknown'))

    def test_ka12_unchanged_sources_and_true_conditions_are_reused_without_recheck(self):
        self.page('ok.md', '## lib 1.0 rule\n' + fence({'id': 'rule', 'kind': 'decision', 'label': 'verified', 'applies_to': ['a.txt'],
                  'sources': [{'type': 'file', 'path': 'a.txt', 'revision': self.head}],
                  'conditions': [{'type': 'file_contains', 'path': 'requirements.txt', 'text': 'lib==1.0'}]}) + 'Use lib 1.0 for a.txt.\n')
        (self.root / 'b.txt').write_text('unrelated change\n'); self.git('commit', '-qam', 'b only')
        entry = {e['id']: e for e in knowledge.package(self.ledger, self.consumer(), cap_chars=6000)['entries']}['rule']
        self.assertEqual((entry['use'], entry['applicability']['state']), ('fact', 'applies'))


class CursorTests(KnowledgeFixture):
    def test_ka13_pages_continue_until_eof_and_never_claim_eof_early(self):
        self.page('hints.md', ''.join(f'## a.txt hint {i}\nHint {i} about a.txt and the O1 evidence.\n' for i in range(30)))
        consumer = self.consumer()
        page = knowledge.package(self.ledger, consumer, cap_chars=5000)
        seen = set(self.ids(page))
        relevant_total = len(seen) + page['omitted']['by_reason'].get('cap', 0) + page['omitted']['by_reason'].get('not_relevant', 0)
        hops = 0
        while not page['omitted']['eof']:
            page = knowledge.read(self.ledger, consumer, page['omitted']['cursor'], cap_chars=5000)
            new = set(self.ids(page)); self.assertTrue(new, 'a page that is not the last delivers something')
            self.assertFalse(new & seen); seen |= new; hops += 1
            self.assertLess(hops, 40)
        self.assertEqual(len(seen), relevant_total)

    def test_ka14_a_cursor_of_an_older_knowledge_state_is_refused(self):
        self.page('hints.md', ''.join(f'## a.txt hint {i}\nHint {i} about a.txt and the O1 evidence.\n' for i in range(30)))
        consumer = self.consumer()
        cursor = knowledge.package(self.ledger, consumer, cap_chars=5000)['omitted']['cursor']
        self.page('hints.md', '## a.txt hint changed\nA new hint for a.txt.\n')
        with self.assertRaises(LedgerError):
            knowledge.read(self.ledger, consumer, cursor, cap_chars=5000)


class DeliveryTests(KnowledgeFixture):
    """KA-15…KA-20 through the actual NativeExecutor with a fixture worker (the shape of tests/test_wf_native_executor)."""

    def setUp(self):
        super().setUp()
        self.calls, self.values = [], []
        self.adapter = NativeExecutor(self.ledger)
        factory = patch('onecrew.artifact_provider_core.make_worker', side_effect=self.factory)
        factory.start(); self.addCleanup(factory.stop)

    def factory(self, control, provider):
        case = self
        class Worker:
            def capability(self): return {'provider': provider, 'mode': 'fixture-no-tools'}
            def run(self, attempt, prompt, schema, profile):
                case.calls.append({'prompt': prompt, 'schema': schema, 'attempt': attempt['id']})
                control.launched(attempt['id'], attempt['generation'], {'fixture': True})
                control.finish(attempt['id'], attempt['generation'], {'exit_code': 0, 'fixture': True})
            def result(self, attempt):
                value = case.values.pop(0)
                value = value(case.calls[-1]['prompt']) if callable(value) else value
                return copy.deepcopy(value), [{'source': 'fixture'}]
        return Worker()

    def definition(self):
        return [self.item('C'), dict(node('I', ['C'], integration=True, write=()), executor=dict(PIN))]

    def receipt(self, result):
        return json.loads(self.store.read_blob(result['receipt']))

    def rule_page(self):
        self.page('rules.md', '## a.txt line rule\n' + fence({'id': 'one-line', 'kind': 'constraint', 'label': 'verified', 'must': True,
                  'applies_to': ['a.txt'], 'sources': [{'type': 'file', 'path': 'a.txt', 'revision': self.head}]}) + 'Keep a.txt to one line.\n'
                  '## a.txt hint\nThe O1 evidence lives in a.txt.\n')

    def test_ka16_the_receipt_seals_exactly_the_knowledge_put_in_the_prompt(self):
        self.rule_page()
        self.revise(self.definition())
        self.values.append({'summary': 'done', 'files': [{'path': 'a.txt', 'content': 'one\n'}], 'backlog': [],
                            'knowledge': {'used': ['one-line'], 'rejected': [], 'requests': []}})
        result = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual(result['state'], 'produced', result)
        receipt = self.receipt(result)
        package_text = self.store.read_blob(receipt['knowledge']['package']).decode('utf-8')
        self.assertIn(package_text, self.calls[0]['prompt'])
        self.assertIn('one-line', receipt['knowledge']['delivered'])
        self.assertEqual(receipt['knowledge_use']['violations'], [])
        self.assertIn('knowledge', self.calls[0]['schema']['properties'])

    def test_ka15_a_requested_omitted_entry_reaches_the_continuation_attempt(self):
        self.page('hints.md', ''.join(f'## a.txt hint {i}\nHint {i} about a.txt and the O1 evidence.\n' for i in range(40)))
        self.revise(self.definition())
        asked = []
        def first(prompt):
            package = json.loads(prompt.split('\n', 1)[1])['knowledge']
            asked.append(package['omitted']['index'][0]['id'])          # the worker picks one listed, undelivered entry
            return {'summary': 'part', 'files': [{'path': 'a.txt', 'content': 'one\n'}], 'backlog': [],
                    'continuation': {'remaining': 'need one more hint'}, 'knowledge': {'used': [], 'rejected': [], 'requests': list(asked)}}
        def second(prompt):
            package = json.loads(prompt.split('\n', 1)[1])['knowledge']
            self.assertIn(asked[0], [e['id'] for e in package['requested']])
            return {'summary': 'done', 'files': [{'path': 'a.txt', 'content': 'one\n'}], 'backlog': [], 'knowledge': {'used': list(asked)}}
        self.values += [first, second]
        with patch.object(knowledge, 'NATIVE_CAP_CHARS', 5000):
            partial = self.engine.step(self.ledger, 'P1', self.adapter)
            self.assertEqual(partial['state'], 'continuing', partial)
            done = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual(done['state'], 'produced', done)
        receipt = self.receipt(done)
        self.assertIn(asked[0], receipt['knowledge']['delivered'])
        self.assertEqual(receipt['knowledge_use']['violations'], [])

    def test_ka17_a_broken_wiki_page_does_not_stop_an_independent_node(self):
        self.page('bad.md', '## Broken\n```onecrew\n{not json\n```\ntext\n')
        self.rule_page()
        self.revise(self.definition())
        self.values.append({'summary': 'done', 'files': [{'path': 'a.txt', 'content': 'one\n'}], 'backlog': [], 'knowledge': {'used': ['one-line']}})
        result = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual(result['state'], 'produced', result)
        receipt = self.receipt(result)
        self.assertTrue(any(p['path'] == 'docs/wiki/bad.md' for p in receipt['knowledge']['problems']))
        self.assertIn('one-line', receipt['knowledge']['delivered'])

    def test_ka18_ka19_declared_use_is_checked_against_what_was_delivered(self):
        self.rule_page()
        self.revise(self.definition())
        self.values.append({'summary': 'done', 'files': [{'path': 'a.txt', 'content': 'one\n'}], 'backlog': [],
                            'knowledge': {'used': ['never-delivered', 'rules-a-txt-hint'], 'rejected': [], 'requests': []}})
        result = self.engine.step(self.ledger, 'P1', self.adapter)
        use = self.receipt(result)['knowledge_use']
        self.assertEqual(use['violations'], [{'id': 'never-delivered', 'problem': 'not_delivered'}])
        self.assertIn('rules-a-txt-hint', use['leads_used'])
        self.assertIn('one-line', use['must_unacknowledged'])
        self.assertFalse(use['proves_semantics'])

    def test_ka20_delivery_writes_no_knowledge(self):
        self.rule_page()
        self.revise(self.definition())
        before_entries = len([1 for kind, _ in self.events() if kind == 'context.entry'])
        page_before = (self.wiki_dir / 'rules.md').read_bytes()
        package = knowledge.package(self.ledger, self.consumer(), cap_chars=6000)
        self.assertTrue(package['entries'])
        self.assertEqual(len([1 for kind, _ in self.events() if kind == 'context.entry']), before_entries)
        self.assertEqual((self.wiki_dir / 'rules.md').read_bytes(), page_before)

    def test_no_knowledge_source_keeps_the_prompt_unchanged(self):
        self.revise(self.definition())
        self.values.append({'summary': 'done', 'files': [{'path': 'a.txt', 'content': 'one\n'}], 'backlog': []})
        result = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual(result['state'], 'produced', result)
        receipt = self.receipt(result)
        self.assertIsNone(receipt['knowledge']['package'])
        self.assertNotIn('"knowledge"', self.calls[0]['prompt'].split('\n', 1)[1])


class WikiParserTests(KnowledgeFixture):
    def test_sections_metadata_and_problems(self):
        text = '# Title\nintro\n\n## First\n' + fence({'id': 'first', 'kind': 'decision', 'label': 'observed'}) + 'body one\n\n### Sub\nbody two\n'
        parsed = wiki.parse(text, 'docs/wiki/x.md')
        self.assertEqual([e['id'] for e in parsed['entries']], ['first', 'x-sub'])
        self.assertEqual(parsed['entries'][0]['text'].strip(), 'body one')
        self.assertEqual(parsed['problems'], [])
        broken = wiki.parse('## B\n```onecrew\n{"id": 1}\n```\n', 'docs/wiki/y.md')
        self.assertTrue(broken['problems'])


class CliTests(KnowledgeFixture):
    """`onecrew wiki show|read|pages` through the v2 router, read-only."""

    def run_cli(self, *args):
        import contextlib, io
        from onecrew.v2 import cli
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), *args])
        return code, out.getvalue()

    def test_show_read_and_pages(self):
        self.page('hints.md', ''.join(f'## a.txt hint {i}\nHint {i} about a.txt and the O1 evidence.\n' for i in range(30))
                  + '## Bad\n```onecrew\n{"id": 3}\n```\n')
        self.revise([self.item('C'), dict(node('I', ['C'], integration=True, write=()), executor=dict(PIN))])
        code, out = self.run_cli('wiki', 'show', '--plan', 'P1', '--node', 'C', '--cap', '5000')
        self.assertEqual(code, 0, out)
        first = json.loads(out)
        self.assertTrue(first['entries'] and first['omitted']['cursor'])
        code, out = self.run_cli('wiki', 'read', '--plan', 'P1', '--node', 'C', '--cap', '5000', '--cursor', first['omitted']['cursor'])
        self.assertEqual(code, 0, out)
        self.assertFalse(set(e['id'] for e in json.loads(out)['entries']) & set(e['id'] for e in first['entries']))
        code, out = self.run_cli('wiki', 'show', '--plan', 'P1', '--node', 'C', '--text')
        self.assertEqual(code, 0, out)
        self.assertIn('GÓI TRI THỨC', out)
        code, out = self.run_cli('wiki', 'pages')
        self.assertEqual(code, 0, out)
        self.assertTrue(json.loads(out)['problems'])
