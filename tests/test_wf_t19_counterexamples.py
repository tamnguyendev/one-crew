"""T19 counterexamples after the Codex review of 9aca8be (P1 W05): weakening that leaves the test body untouched must not pass.

Same fixture as tests/test_wf_test_integrity (temporary Git project, one approved command milestone running tests/test_x.py; the "worker" is the
test editing the file). The real path is `verdict.run`: the milestone may not end `passed` when
  (a) `@unittest.skip` is added to an approved test,            (b) the whole class is skipped,
  (c) the test is no longer discovered (renamed to a non-test name, or the file moved out of the test pattern),
  (d) a helper the test calls is weakened while the test body is unchanged (not provably intact -> not a pass).
A valid added test, a pure reformat (same AST) and a file move inside the test pattern stay `passed` and ask nobody.
Supported scope: Python test files found by name (tests/*.py, test_*.py, *_test(s).py); other languages are reported as unanalysed.
"""
import sys

from onecrew.v2 import plan as plans, verdict
from tests.test_v2_l1 import Fixture, plan_json, milestone

HELPER_FILE = '\n'.join([
    'import unittest, pathlib',
    'def rows_ok(text):',
    '    return text == "one" + chr(10)',
    'class ATests(unittest.TestCase):',
    '    def test_a_row_count(self):',
    '        self.assertTrue(rows_ok(pathlib.Path("a.txt").read_text()))',
    '    def test_b_other(self):',
    '        self.assertTrue(True)',
    'if __name__ == "__main__": unittest.main()', ''])


class CounterexampleTests(Fixture):
    def setUp(self):
        super().setUp()
        (self.root / 'tests').mkdir()
        (self.root / 'tests' / 'test_x.py').write_text(HELPER_FILE)
        (self.root / '.gitignore').write_text('__pycache__/' + chr(10))
        self.git('add', '.'); self.git('commit', '-qm', 'tests')
        argv = [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py']
        value = plan_json(milestones=[milestone(argv=argv)], scope={'owned': ['a.txt', 'tests/test_x.py', 'tests/test_y.py', 'helpers/']})
        value['understanding']['target']['paths'] = ['a.txt', 'tests/test_x.py']
        plans.propose(self.ledger, 'P1', value, 'codex', workflow=True)      # W11b/T25 [E4] (round 6): T19 is a workflow-root rule
        plans.approve(self.ledger, 'P1', 'owner', 'fixture')
        import os
        os.environ['ONECREW_ACTOR'] = 'codex'

    def rewrite(self, text, path='tests/test_x.py'):
        (self.root / path).write_text(text)
        self.git('add', '-A'); self.git('commit', '-qm', 'edit tests')

    def verify_once(self):
        shown = verdict.run(self.ledger, 'P1', 'M1', self.root)
        event = [p for k, p in self.events() if k == 'verdict.recorded'][-1]
        return shown['milestones'][0]['state'], event

    def test_a_skip_decorator_on_the_test_is_a_weakening(self):
        self.rewrite(HELPER_FILE.replace('    def test_a_row_count(self):', '    @unittest.skip("later")\n    def test_a_row_count(self):'))
        state, event = self.verify_once()
        self.assertEqual(state, 'failed'); self.assertEqual(event['test_integrity']['classification'], 'U1')
        self.assertEqual([(w['test'], w['kind']) for w in event['test_integrity']['weakened']], [('ATests.test_a_row_count', 'changed')])

    def test_b_skipping_the_whole_class_is_a_weakening(self):
        self.rewrite(HELPER_FILE.replace('class ATests(unittest.TestCase):', '@unittest.skip("all later")\nclass ATests(unittest.TestCase):'))
        state, event = self.verify_once()
        self.assertEqual(state, 'failed'); self.assertEqual(event['test_integrity']['classification'], 'U1')
        self.assertEqual({w['kind'] for w in event['test_integrity']['weakened']}, {'class_skipped'})

    def test_c_a_test_that_is_no_longer_discovered_is_removed(self):
        self.rewrite(HELPER_FILE.replace('def test_a_row_count', 'def check_a_row_count'))
        state, event = self.verify_once()
        self.assertNotEqual(state, 'passed'); self.assertEqual(event['result'], 'fail')
        self.assertEqual([(w['test'], w['kind']) for w in event['test_integrity']['weakened']], [('ATests.test_a_row_count', 'removed')])
        # the file itself moved out of the discovery pattern: every approved test of it is gone
        self.git('mv', 'tests/test_x.py', 'tests/x_helpers_only.py'); self.git('commit', '-qm', 'hide the file')
        state, event = self.verify_once()
        self.assertNotEqual(state, 'passed'); self.assertEqual(event['result'], 'fail')
        self.assertEqual({w['kind'] for w in event['test_integrity']['weakened']}, {'undiscoverable'})

    def test_d_a_weakened_helper_with_an_unchanged_test_body_is_not_a_pass(self):
        self.rewrite(HELPER_FILE.replace('    return text == "one" + chr(10)', '    return True'))
        state, event = self.verify_once()
        self.assertNotEqual(state, 'passed')
        self.assertEqual(event['result'], 'inconclusive')
        self.assertEqual(event['test_integrity']['classification'], 'insufficient')
        self.assertTrue(any(s['kind'] == 'support_changed' for s in event['test_integrity']['insufficient']))

    def test_valid_additions_reformat_and_moves_still_pass(self):
        before = len(self.ledger.requests())
        reformatted = HELPER_FILE.replace('    return text == "one" + chr(10)', '    return (text == ("one" + chr(10)))')   # same AST
        added = reformatted.replace('if __name__', '    def test_c_new(self):\n        self.assertEqual(1, 1)\nif __name__')
        self.rewrite(added)
        state, event = self.verify_once()
        self.assertEqual(state, 'passed'); self.assertEqual([a['test'] for a in event['test_integrity']['added']], ['ATests.test_c_new'])
        self.assertIsNone(event['test_integrity']['classification'])
        self.git('mv', 'tests/test_x.py', 'tests/test_y.py'); self.git('commit', '-qm', 'move inside the pattern')
        state, event = self.verify_once()
        self.assertEqual(state, 'passed')                                                               # the move keeps every approved test
        self.assertEqual([a['test'] for a in event['test_integrity']['added']], ['ATests.test_c_new']); self.assertIsNone(event['test_integrity']['classification'])
        self.assertEqual(event['test_integrity'].get('insufficient', []), [])
        self.assertEqual(len(self.ledger.requests()), before)
