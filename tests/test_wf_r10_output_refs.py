"""R10: a node's declared outputs must exist in the candidate and every source reference in a written text report must resolve
against the candidate tree, through the REAL CandidateChecker (the contract's own milestone command reads none of the reports)."""
import json
import os
import sys
import unittest

from onecrew.common_verification import CandidateChecker
from onecrew.control import Control, migrate
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, internal_plan, plan as plans
from onecrew.v2.verifiers import output_refs
from tests.test_v2_l1 import Fixture, plan_json, milestone
from tests.test_wf_engine import node

REPORTS = ['docs/rep/K03.md', 'docs/rep/skeleton-1.md', 'docs/rep/skeleton-2.md']
FILES = {'a.cs': 'class A {}\n', 'README.md': 'one\ntwo\nthree\n', 'src/Foo.cs': 'a\nb\nc\n',
         'other/Foo.cs': 'a\nb\nc\nd\ne\n', '.github/workflows/publish.yml': ''.join('line %d\n' % n for n in range(1, 41))}


class OutputRefsFixture(Fixture):
    def setUp(self):
        Fixture.setUp(self)
        self.engine, self.ip = engine, internal_plan
        for name, text in FILES.items():
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
        self.git('add', '-f', '.'); self.git('commit', '-qm', 'sources')
        check = [sys.executable, '-c', 'print("milestone reads none of the reports")']
        selected = [milestone(argv=check)]; self.check_ids = [row['id'] for row in selected]
        value = plan_json(milestones=selected, scope={'owned': ['a.txt'] + REPORTS}, authority={
            'edit': True, 'commands': True, 'apply_to_project': True, 'unconfined_commands': True,
            'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']})
        plans.propose(self.ledger, 'P1', value, 'codex', workflow=True,
                      capabilities=['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine'])
        plans.approve(self.ledger, 'P1', 'owner', 'fixture approved command and apply')
        os.environ['ONECREW_ACTOR'] = 'codex'
        self.store = Snapshots(self.ledger.state_root)
        migrate(self.ledger); self.control = Control(self.ledger)
        self.checker = CandidateChecker(self.ledger, 'P1')

    def verify_reports(self, written, declared=None, output=None):
        """The node C may write `declared` (default: the files it writes), names `output` as its deliverables (default: the fixture's
        prose output, which names no path) and produces `written` {path: text}."""
        declared = list(written) if declared is None else declared
        nodes = [node('C', write=declared), node('I', ['C'], integration=True, write=())]
        if output is not None: nodes[0]['output'] = list(output)
        for item in nodes: item['checks'] = [{'id': c, 'spec': 'The exact approved root command ' + c} for c in self.check_ids]
        self.ip.revise(self.ledger, 'P1', nodes, reason='Split work inside the approved scope', evidence=['a.txt:1'])
        def execute(ledger, control, task, item, attempt):
            control.launched(attempt['id'], attempt['generation'], {'fixture': True})
            base = self.store.capture(self.root, declared)
            artifact = self.store.overlay(base, {p: t.encode() for p, t in written.items()}, declared)
            control.finish(attempt['id'], attempt['generation'], {'artifact': artifact})
            return {'artifact': artifact, 'receipt': self.store.blob(b'fixture producer')}
        self.engine.step(self.ledger, 'P1', execute, control=self.control)
        return self.engine.verify(self.ledger, 'P1', 'C', self.checker)

    def assertOutFails(self, result, *reasons):
        self.assertEqual(result['result'], 'fail', 'verification must fail the declared-output / reference check')
        out = result['observed']['output_check']
        self.assertEqual(out['id'], 'OUT'); self.assertEqual(out['result'], 'fail')
        for reason in reasons: self.assertIn(reason, json.dumps(out))
        return out


class OutputRefsThroughCandidateCheckerTests(OutputRefsFixture):
    def test_a_reference_to_a_file_that_does_not_exist(self):
        out = self.assertOutFails(self.verify_reports({'docs/rep/K03.md': 'See `missing/Gone.cs:999999` for the leak.\n'}), 'missing/Gone.cs:999999')
        self.assertEqual(out['counts']['unresolvable'], 1)

    def test_b_reference_to_a_line_that_does_not_exist(self):
        for number, text in enumerate(['a.cs:999999', 'src/Foo.cs:0', 'src/Foo.cs:-3', 'src/Foo.cs:4', 'src/Foo.cs:3-2', 'src/Foo.cs:2-9']):
            with self.subTest(text):
                if number: self.setUp()
                out = self.assertOutFails(self.verify_reports({'docs/rep/K03.md': 'Finding at ' + text + ' here.\n'}), text)
                self.assertEqual(out['counts']['resolved'], 0)

    def test_c_bare_basename_is_unresolvable_even_when_unique_or_duplicated(self):
        for number, text in enumerate(['publish.yml:32', 'Foo.cs:2']):   # exists once elsewhere / exists in two directories
            with self.subTest(text):
                if number: self.setUp()
                self.assertOutFails(self.verify_reports({'docs/rep/K03.md': 'Look at ' + text + '.\n'}), text, 'bare basename')

    def test_d_required_output_missing_from_the_candidate(self):
        # R11: `write` is permission; the node's `output` naming the skeleton makes it a required deliverable
        both = ['docs/rep/K03.md', 'docs/rep/skeleton-1.md']
        result = self.verify_reports({'docs/rep/K03.md': 'ok a.cs:1\n'}, declared=both, output=['Report docs/rep/K03.md and docs/rep/skeleton-1.md'])
        out = self.assertOutFails(result, 'docs/rep/skeleton-1.md', 'required output missing')
        self.assertEqual(out['missing'], ['docs/rep/skeleton-1.md'])

    def test_d2_required_output_that_is_empty_without_the_artifact_declaring_it(self):
        # R11: an empty file is valid only when the artifact declares it; here the required report is empty in the source and untouched
        (self.root / 'docs' / 'rep').mkdir(parents=True); (self.root / 'docs' / 'rep' / 'K03.md').write_bytes(b'')
        result = self.verify_reports({'docs/rep/skeleton-1.md': 'ok a.cs:1\n'}, declared=['docs/rep/K03.md', 'docs/rep/skeleton-1.md'],
                                     output=['The report docs/rep/K03.md'])
        out = self.assertOutFails(result, 'docs/rep/K03.md', 'required output empty')
        self.assertEqual(out['empty_required'], ['docs/rep/K03.md'])

    def test_e_wrong_part_while_the_two_skeleton_files_are_correct(self):
        good = 'Cites a.cs:1 and src/Foo.cs:2-3 and README.md:3.\n'
        result = self.verify_reports({'docs/rep/skeleton-1.md': good, 'docs/rep/skeleton-2.md': good,
                                      'docs/rep/K03.md': 'Part says missing.cs:999999\n'})
        out = self.assertOutFails(result, 'missing.cs:999999')
        self.assertEqual(out['counts']['resolved'], 6)

    def test_f_malformed_reference_is_unverifiable_and_fails(self):
        for number, text in enumerate(['README.md:22-25:extra', 'a.cs:line 5', 'a.cs:12:5', 'a.cs:L3']):
            with self.subTest(text):
                if number: self.setUp()
                out = self.assertOutFails(self.verify_reports({'docs/rep/K03.md': 'See ' + text + ' today.\n'}), 'unverifiable')
                self.assertEqual(out['counts']['unverifiable'], 1)

    def test_g_valid_references_urls_and_output_mentions_pass(self):
        text = ('# Report\nSee a.cs:1, `src/Foo.cs:1-3`, other/Foo.cs:5 and README.md:2.\n'
                'Workflow .github/workflows/publish.yml:32 is covered.\n'
                'Docs at https://example.com/a/b.cs:99 and http://host:8080/x.md:7 are links.\n'
                'This report is docs/rep/K03.md:50 and the dump is below.\n```text\nGone.cs:77 zzz/none.cs:1\n```\n')
        result = self.verify_reports({'docs/rep/K03.md': text})
        self.assertEqual(result['result'], 'pass')
        out = result['observed']['output_check']
        self.assertEqual(out['result'], 'pass')
        self.assertEqual(out['counts'], {'total': 5, 'resolved': 5, 'unresolvable': 0, 'unverifiable': 0, 'skipped_outputs': 1})
        self.assertEqual([row['id'] for row in result['observed']['checks']], self.check_ids)


class ParserGrammarTests(unittest.TestCase):
    def refs(self, text): return [(r.path, r.start, r.end, r.kind) for r in output_refs.scan(text)]

    def test_forms_and_ranges(self):
        self.assertEqual(self.refs('x a/b.cs:3, c.md:4-9. (d/e.py:1)'),
                         [('a/b.cs', 3, 3, 'ref'), ('c.md', 4, 9, 'ref'), ('d/e.py', 1, 1, 'ref')])

    def test_fenced_text_log_console_output_blocks_are_skipped_but_code_blocks_are_scanned(self):
        text = '```text\na/b.cs:1\n```\n```cs\nc/d.cs:2\n```\n~~~log\ne/f.cs:3\n~~~\n```console\ng/h.cs:4\n```\nafter i/j.cs:5\n'
        self.assertEqual([r[0] for r in self.refs(text)], ['c/d.cs', 'i/j.cs'])

    def test_urls_and_host_ports_are_not_references(self):
        self.assertEqual(self.refs('https://github.com/o/r/blob/x/a.cs:12 ftp://h/p.cs:3 example.com:443'), [])

    def test_malformed_forms_are_reported_unverifiable_never_dropped(self):
        got = self.refs('a/b.cs:3-5:extra a/b.cs:line a/b.cs:7.5 a/b.cs:3-x src\\a.cs:3')
        self.assertEqual({row[3] for row in got}, {'unverifiable'}); self.assertEqual(len(got), 5)

    def test_comma_lists_and_mixed_items_are_checked_item_by_item(self):
        self.assertEqual(self.refs('a/b.cs:8,10,12 c/d.cs:8,10-12 e/f.cs:3, 5, 7-8.'),
                         [('a/b.cs', 8, 8, 'ref'), ('a/b.cs', 10, 10, 'ref'), ('a/b.cs', 12, 12, 'ref'),
                          ('c/d.cs', 8, 8, 'ref'), ('c/d.cs', 10, 12, 'ref'),
                          ('e/f.cs', 3, 3, 'ref'), ('e/f.cs', 5, 5, 'ref'), ('e/f.cs', 7, 8, 'ref')])

    def test_en_dash_is_a_range_separator(self):
        self.assertEqual(self.refs('a/b.cs:1–15 and (c/d.cs:192–199)'), [('a/b.cs', 1, 15, 'ref'), ('c/d.cs', 192, 199, 'ref')])

    def test_a_comma_without_a_digit_after_it_is_prose_and_ish_or_line_text_stays_unverifiable(self):
        self.assertEqual(self.refs('see a/b.cs:3, then more'), [('a/b.cs', 3, 3, 'ref')])
        got = self.refs('a/b.cs:316-ish a/b.cs:line a/b.cs:3-5:extra a/b.cs:8,10:x')
        self.assertEqual([row[3] for row in got], ['unverifiable'] * 4)

    def test_out_of_range_item_inside_a_list_fails_the_check(self):
        tree = {'a/b.cs': 12}
        good = output_refs.check(tree, output_refs.scan('a/b.cs:8,10,12 a/b.cs:8,10–12'), [])
        self.assertEqual((good['result'], good['counts']['resolved']), ('pass', 5))
        bad = output_refs.check(tree, output_refs.scan('a/b.cs:8,10,13 a/b.cs:8,10-13 a/b.cs:0,3'), [])
        self.assertEqual((bad['result'], bad['counts']['resolved'], bad['counts']['unresolvable']), ('fail', 4, 3))

    def test_prose_is_not_a_reference(self):
        self.assertEqual(self.refs('Note: see a/b.cs for more. Result: 3. Namespace.Class:Method file.txt: done'), [])

    def test_check_is_pure_and_lazy(self):
        refs = output_refs.scan('a/b.cs:2 a/b.cs:9 top.md:1 deep.md:1 own/out.md:4')
        tree = {'a/b.cs': lambda: 3, 'top.md': 1, 'x/deep.md': 1, 'own/out.md': 1}
        got = output_refs.check(tree, refs, ['own/out.md'])
        self.assertEqual(got['result'], 'fail')
        self.assertEqual(got['counts'], {'total': 4, 'resolved': 2, 'unresolvable': 2, 'unverifiable': 0, 'skipped_outputs': 1})


if __name__ == '__main__':
    unittest.main()
