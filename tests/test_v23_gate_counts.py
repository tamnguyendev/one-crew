r"""Codex review of beta 2.3.0.dev9, P2: the gate took an expected failure for a passed test. wfkit/gate.py parse_unittest read
`OK (expected failures=1)` as run=1, passed=1, errors=0, skipped=0, and _counts_pass accepted the receipt; an unexpected success (`FAILED
(unexpected successes=1)`) was not counted at all. wfkit/namespace_lineage.py counted the same way for the lineage check.

Expected: pass, failure/error, skip, expected failure and unexpected success are told apart; an expected failure is never a passed test; a receipt
with one is not a pass unless its testcase allows it explicitly (`allow_expected_failures`, 0 when absent: the criterion of a gate is not weakened);
an unexpected success is a failure. Shown through the real path: the gate's runner runs unittest, writes the receipt, and the gate decides on it; a
clean run is the control. Receipts and logs of earlier gates are not touched (the dev9 gate's 217 runs had no skip and no expected failure).
No network, no provider, no model; temporary folders.
"""
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from wfkit import gate

COMMIT = 'c' * 40
WHEEL = 'a' * 64
MODULES = {
    'test_xf': '''
        import unittest
        class T(unittest.TestCase):
            @unittest.expectedFailure
            def test_known(self):
                self.assertEqual(1, 2)
    ''',
    'test_us': '''
        import unittest
        class T(unittest.TestCase):
            @unittest.expectedFailure
            def test_now_passes(self):
                self.assertEqual(1, 1)
    ''',
    'test_ok': '''
        import unittest
        class T(unittest.TestCase):
            def test_one(self):
                self.assertEqual(1, 1)
            def test_two(self):
                self.assertTrue(True)
    ''',
    'test_xf_print': '''
        import unittest
        class T(unittest.TestCase):
            def test_prints(self):
                print('Ran 1 test in 0.001s')
                print()
                print('OK')
            @unittest.expectedFailure
            def test_known(self):
                self.assertEqual(1, 2)
    ''',
    'test_mixed': '''
        import unittest
        class T(unittest.TestCase):
            def test_pass(self): pass
            @unittest.skip('no')
            def test_skip(self): pass
            @unittest.expectedFailure
            def test_known(self): self.assertEqual(1, 2)
    ''',
}


class Parser(unittest.TestCase):
    def test_c01_each_outcome_is_counted_apart(self):
        cases = {
            'Ran 1 test in 0.001s\n\nOK (expected failures=1)\n': dict(run=1, passed=0, errors=0, skipped=0, expected_failures=1, unexpected_successes=0),
            'Ran 1 test in 0.001s\n\nFAILED (unexpected successes=1)\n': dict(run=1, passed=0, errors=0, skipped=0, expected_failures=0, unexpected_successes=1),
            'Ran 3 tests in 0.001s\n\nOK (skipped=2)\n': dict(run=3, passed=1, errors=0, skipped=2, expected_failures=0, unexpected_successes=0),
            'Ran 2 tests in 0.001s\n\nOK\n': dict(run=2, passed=2, errors=0, skipped=0, expected_failures=0, unexpected_successes=0),
            'Ran 20 tests in 1.0s\n\nFAILED (failures=1, errors=2, skipped=3, expected failures=4, unexpected successes=5)\n':
                dict(run=20, passed=5, errors=3, skipped=3, expected_failures=4, unexpected_successes=5),
        }
        for text, want in cases.items():
            with self.subTest(text.strip().splitlines()[-1]):
                got = gate.parse_unittest(text)
                self.assertEqual({k: got.get(k) for k in want}, want)


class RunnerReceiptDecision(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project'
        (self.root / 'tests').mkdir(parents=True)
        (self.root / 'tests' / '__init__.py').write_text('', encoding='utf-8')
        for name, body in MODULES.items():
            (self.root / 'tests' / f'{name}.py').write_text(textwrap.dedent(body), encoding='utf-8')
        self.out = Path(self.temp.name) / 'gate'

    def receipt(self, module, tag):
        r = gate.run_unittests(self.root, [f'tests.{module}'], Path(self.temp.name) / 'none.whl', WHEEL, self.out, tag, sys.executable)
        r.update(release='R01', testcase=f'R01/{tag}', commit=COMMIT, wheel_sha256=WHEEL)
        return r

    def decision(self, receipt, entry=None):
        config = {'releases': {'R01': {'testcases': {receipt['testcase']: entry or {}}}}}
        build = {'release': 'R01', 'commit': COMMIT, 'wheel_sha256': WHEEL, 'dirty': []}
        install = {'ok': True, 'control_refused': True, 'wheel_sha256': WHEEL, 'loaded': {}}
        return gate.decide('R01', config, build, {receipt['testcase']: receipt}, install, {'ok': True})

    def not_pass(self, decision):
        return [r for r in decision['reasons'] if r['code'] == 'not-pass']

    def test_c02_an_expected_failure_is_not_a_passed_test_and_the_gate_refuses_it(self):
        r = self.receipt('test_xf', 'xf')
        self.assertEqual(r['exit_code'], 0)                                       # unittest itself calls this run successful
        self.assertEqual((r['tests_run'], r['tests_passed'], r.get('tests_expected_failures')), (1, 0, 1))
        d = self.decision(r)
        self.assertEqual(d['decision'], 'refused')
        self.assertTrue(self.not_pass(d), d['reasons'])

    def test_c03_an_unexpected_success_is_a_failure(self):
        r = self.receipt('test_us', 'us')
        self.assertEqual(r.get('tests_unexpected_successes'), 1)
        self.assertNotEqual(r['result'], 'pass')
        self.assertTrue(self.not_pass(self.decision(r)))

    def test_c04_an_explicit_allowance_is_the_only_way_an_expected_failure_passes(self):
        r = self.receipt('test_mixed', 'mixed')
        self.assertEqual((r['tests_run'], r['tests_passed'], r['tests_skipped'], r.get('tests_expected_failures')), (3, 1, 1, 1))
        self.assertTrue(self.not_pass(self.decision(r)))                                                    # no allowance at all
        self.assertTrue(self.not_pass(self.decision(r, {'allow_skips': 1})))                                # skips allowed, not this
        self.assertFalse(self.not_pass(self.decision(r, {'allow_skips': 1, 'allow_expected_failures': 1})))

    def test_c07_a_test_that_prints_ok_does_not_hide_the_real_summary(self):
        """Independent review of the first fix: stdout comes before stderr in the log, and the first `OK` line won."""
        r = self.receipt('test_xf_print', 'xfprint')
        self.assertEqual((r['tests_run'], r['tests_passed'], r.get('tests_expected_failures')), (2, 1, 1))
        self.assertTrue(self.not_pass(self.decision(r)))

    def test_c05_control_a_clean_run_passes_as_before(self):
        r = self.receipt('test_ok', 'ok')
        self.assertEqual((r['result'], r['tests_run'], r['tests_passed'], r['tests_errors'], r['tests_skipped']), ('pass', 2, 2, 0, 0))
        self.assertEqual((r.get('tests_expected_failures'), r.get('tests_unexpected_successes')), (0, 0))
        self.assertFalse(self.not_pass(self.decision(r)))


class LineageCounter(unittest.TestCase):
    """The lineage check counts with unittest's own result object: the same rule, on its code (it runs one module in a venv: not run here)."""

    def test_c06_the_lineage_counter_takes_expected_failures_and_unexpected_successes_out_of_passed(self):
        source = (Path(gate.__file__).parent / 'namespace_lineage.py').read_text(encoding='utf-8')
        self.assertIn('len(result.expectedFailures)', source)
        self.assertIn('len(result.unexpectedSuccesses)', source)
        self.assertIn("'tests_expected_failures'", source)


if __name__ == '__main__':
    unittest.main()
