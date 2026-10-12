import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from onecrew import node_change, node_toolchain
from onecrew.delivery_recovery import classify_child
from onecrew.ledger import LedgerError
from onecrew.node_toolchain import (attach_modules, classify_output, dependency_lock, detach_modules, run_fixed,
                                    summarize_e2e, summarize_vitest)
from onecrew.sandbox_gate import GateUnavailable
from tests import test_node_change as nc

NODE = shutil.which('node')
WINDOWS_NODE = unittest.skipUnless(NODE and os.name == 'nt', 'needs node.exe on Windows')

# The e2e fake of the node_change fixture, plus failures that are the machine's, not the code's.
FAKE_E2E = r"""
import fs from 'node:fs';
const src=fs.readFileSync('src/app.ts','utf8');
if (src.includes('PORTBUSY')) { console.log('FAIL run: listen EADDRINUSE: address already in use 127.0.0.1:18766'); console.log('0/1 checks passed'); process.exit(1); }
if (src.includes('NOBACKEND')) { console.error('Error: backend did not become ready (it exited)'); process.exit(1); }
if (src.includes('CRASH')) { console.error('TypeError: page.evaluate is not a function'); process.exit(1); }
console.log('PASS a'); console.log('PASS b'); console.log('PASS c'); console.log('3/3 checks passed');
"""


class ClassifyOutputTests(unittest.TestCase):
    def test_product_signals(self):
        for text in ('src/app.ts(1,1): error TS2322: Type string is not assignable', 'src/a.ts:3:7: ERROR: Expected ";"',
                     '✘ [ERROR] Could not resolve "./x"', 'AssertionError: expected 1 to be 2',
                     ' FAIL  test/app.test.ts > adds', '      Tests  1 failed | 3 passed (4)',
                     'Failing assertions (1):\n- test/a.test.ts > t', 'FAIL fill: mach expected 102 got empty\n2/3 checks passed',
                     "Error: Cannot find module '../src/gone'"):
            self.assertEqual(classify_output(text), 'product', text)

    def test_environment_signals_win_over_product_ones(self):
        for text in ('Error: listen EADDRINUSE: address already in use 127.0.0.1:18766',
                     'STOP  Chrome did not launch (is another run using the profile?): x',
                     'Error: Failed to launch the browser process!', 'FAIL run: backend did not become ready (it exited)\n0/1 checks passed',
                     "Error: Cannot find module 'C:\\p\\node_modules\\vitest\\vitest.mjs'",
                     'Project node_modules has no .package-lock.json; install dependencies there (npm ci).',
                     'Error: spawn C:\\x\\.venv\\Scripts\\python.exe ENOENT',
                     "EPERM: operation not permitted, symlink 'C:\\p\\node_modules' -> 'C:\\w\\node_modules'",
                     'junction could not be created: EPERM'):
            self.assertEqual(classify_output(text, 'e2e'), 'environment', text)
        self.assertEqual(classify_output('error TS2322\nError: listen EADDRINUSE :::5173'), 'environment')

    def test_e2e_without_summary_is_a_runtime_bug_never_a_pass(self):
        self.assertEqual(classify_output('PASS a\nTypeError: x is not a function', 'e2e'), 'runtime_bug')
        self.assertEqual(classify_output('', 'e2e_mock'), 'runtime_bug')
        self.assertEqual(classify_output('PASS a\nFAIL b\n1/2 checks passed', 'e2e'), 'product')
        self.assertIsNone(classify_output('1/1 checks passed', 'e2e'))  # too few checks: the caller decides
        self.assertIsNone(classify_output('TypeError: x is not a function', 'build'))
        self.assertIsNone(classify_output(None))


class SummaryTests(unittest.TestCase):
    def test_node_change_reexports_the_shared_pieces(self):
        for name in ('summarize_e2e', 'summarize_vitest', 'dependency_lock', 'attach_modules', 'detach_modules', 'CHECKS',
                     'MAX_REPORT', 'STEP_SECONDS'):
            self.assertIs(getattr(node_change, name), getattr(node_toolchain, name), name)

    def test_summarize_e2e(self):
        self.assertTrue(summarize_e2e('PASS a\nPASS b\n2/2 checks passed\n', 2)['passed'])
        few = summarize_e2e('1/1 checks passed', 3)
        self.assertFalse(few['passed']); self.assertIn('minimum 3', few['reason'])
        failed = summarize_e2e('FAIL x: y\n1/2 checks passed', 1)
        self.assertEqual(failed['failed_lines'], ['FAIL x: y']); self.assertIn('1/2 passed', failed['reason'])
        self.assertIn('no "N/N checks passed"', summarize_e2e('PASS a', 1)['reason'])

    def test_summarize_vitest(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp); report = package / 'r.json'
            self.assertIn('missing', summarize_vitest(report, package, [])['reason'])
            result = lambda name, ok: {'name': str(package / name), 'status': 'passed' if ok else 'failed', 'assertionResults': [
                {'status': 'passed' if ok else 'failed', 'fullName': 'adds', 'failureMessages': [] if ok else ['AssertionError: 1 vs 2\n at x']}]}
            report.write_text(json.dumps({'success': False, 'numTotalTests': 2, 'numPassedTests': 1, 'numFailedTests': 1,
                                          'testResults': [result('test/a.test.ts', True), result('test/b.test.ts', False)]}))
            summary = summarize_vitest(report, package, ['test/a.test.ts'])
            self.assertFalse(summary['passed']); self.assertIn('test/b.test.ts > adds: AssertionError: 1 vs 2', summary['reason'])
            report.write_text(json.dumps({'success': True, 'numTotalTests': 1, 'numPassedTests': 1, 'numFailedTests': 0,
                                          'testResults': [result('test/a.test.ts', True)]}))
            self.assertTrue(summarize_vitest(report, package, ['test/a.test.ts'])['passed'])
            self.assertFalse(summarize_vitest(report, package, ['test/other.test.ts'])['passed'])

    def test_dependency_lock_and_junction_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            modules = Path(tmp) / 'project/node_modules'; modules.mkdir(parents=True)
            with self.assertRaises(GateUnavailable):
                dependency_lock(modules)
            (modules / '.package-lock.json').write_text('{"lockfileVersion":3}')
            self.assertEqual(len(dependency_lock(modules)), 64)
            link = Path(tmp) / 'capture/node_modules'; link.parent.mkdir()
            attach_modules(modules, link)
            self.assertTrue((link / '.package-lock.json').is_file())
            detach_modules(link, modules)
            self.assertFalse(os.path.lexists(link)); self.assertTrue((modules / '.package-lock.json').is_file())
            link.mkdir()  # a real directory is never removed as if it were the runtime junction
            with self.assertRaises(GateUnavailable):
                detach_modules(link, modules)


@WINDOWS_NODE
class RunFixedTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.dir, True)
        scripts = {'env.mjs': "console.log('cwd=' + process.cwd() + ' ci=' + process.env.CI + ' port=' + (process.env.NA_MOCK_PORT || 'none'));",
                   'tsc.mjs': "console.log('src/app.ts(1,1): error TS2322: bad'); process.exit(2);",
                   'never.mjs': "require('fs').writeFileSync('ran.txt', 'x');",
                   'silent.mjs': "console.log('PASS a');",
                   'hang.mjs': 'const end=Date.now()+60000; while (Date.now()<end) {}'}
        for name, text in scripts.items():
            (self.dir / name).write_text(text)

    def test_steps_run_in_order_with_env_and_stop_at_the_first_failure(self):
        results, failure = run_fixed([('first', [NODE, 'env.mjs']), ('second', [NODE, 'env.mjs'], {'NA_MOCK_PORT': '18766'}),
                                      ('typecheck', [NODE, 'tsc.mjs']), ('later', [NODE, 'never.mjs'])],
                                     self.dir, {'CI': 'true'})
        self.assertEqual([r['step'] for r in results], ['first', 'second', 'typecheck'])
        self.assertIn('ci=true port=none', results[0]['stdout']); self.assertIn('port=18766', results[1]['stdout'])
        self.assertIn('cwd=' + str(self.dir), results[0]['stdout'])
        self.assertTrue(results[0]['passed']); self.assertIsNone(results[0]['failure_class'])
        self.assertIs(failure, results[-1]); self.assertEqual(failure['exit_code'], 2)
        self.assertEqual(failure['failure_class'], 'product'); self.assertFalse((self.dir / 'ran.txt').exists())
        self.assertIsInstance(failure['seconds'], float)

    def test_check_refines_the_verdict_and_adds_fields(self):
        def check(name, code, out, err):
            summary = summarize_e2e(out, 1)
            return summary['passed'], {'summary': {k: v for k, v in summary.items() if k != 'passed'}}
        results, failure = run_fixed([('e2e', [NODE, 'silent.mjs'])], self.dir, check=check)
        self.assertEqual(failure['exit_code'], 0); self.assertFalse(failure['passed'])
        self.assertIn('no "N/N checks passed"', failure['summary']['reason'])
        self.assertEqual(failure['failure_class'], 'runtime_bug')

    def test_deadline_raises_like_the_gate(self):
        with self.assertRaises(GateUnavailable) as raised:
            run_fixed([('hang', [NODE, 'hang.mjs'])], self.dir, timeouts={'hang': 1})
        self.assertIn('deadline', str(raised.exception).lower())

    def test_a_step_that_cannot_start_is_unavailable_not_a_product_failure(self):
        with patch.object(node_toolchain, 'command', side_effect=PermissionError(13, 'Access is denied')):
            with self.assertRaises(GateUnavailable) as raised:
                run_fixed([('typecheck', [NODE, 'env.mjs'])], self.dir)
        self.assertIn('Could not run fixed Node step typecheck', str(raised.exception))
        self.assertIsInstance(raised.exception.__cause__, PermissionError)

    def test_bounded_inputs(self):
        for steps in ([], [('Bad Name', [NODE])], [('a', NODE)], [('a', [])], [('a', [NODE], {'X': 1})], [('a',)],
                      [('a', [NODE])] * 21):
            with self.assertRaises(LedgerError, msg=str(steps)[:80]):
                run_fixed(steps, self.dir)
        with self.assertRaises(LedgerError):
            run_fixed([('a', [NODE, 'env.mjs'])], self.dir, timeouts={'a': 0})


@WINDOWS_NODE
class NodeChangeFailureClassTests(unittest.TestCase):
    """A child's environment failure blocks as environment (bounded root retry) instead of spending a product repair."""
    candidate = nc.NodeChangeTests.candidate
    work_and_verify = nc.NodeChangeTests.work_and_verify

    def setUp(self):
        with patch.object(nc, 'FAKE_E2E', FAKE_E2E):
            nc.NodeChangeTests.setUp(self)  # method names contain 'e2e': the recipe carries the fixed e2e step

    def test_e2e_port_in_use_blocks_as_environment_without_repair(self):
        state = self.work_and_verify(self.candidate(source='export const add=(a:number,b:number)=>a+b; // PORTBUSY\n'))
        check = state['native_change']['checks'][-1]
        self.assertEqual((check['failure_class'], check['failure_kind']), ('environment', 'environment'))
        self.assertEqual(state['phase'], 'blocked'); self.assertEqual(state['recovery']['kind'], 'environment')
        self.assertIn('Node dependency/environment unavailable', state['message'])
        self.assertEqual(state['native_change']['repairs'], 0); self.assertEqual(len(self.worker.calls), 1)
        self.assertEqual(classify_child(state, False), 'environment')  # the delivery root retries, it does not repair
        self.assertIn('a-b', (self.ext / 'src/app.ts').read_text())

    def test_junction_eperm_blocks_as_environment_without_repair(self):
        # The junction is made by Python before run_fixed, so its OSError never reaches classify_output.
        denied = PermissionError(1, 'EPERM: operation not permitted, junction')
        with patch.object(node_change, 'attach_modules', side_effect=denied):
            state = self.work_and_verify(self.candidate())
        self.assertEqual(state['phase'], 'blocked'); self.assertEqual(state['recovery']['kind'], 'environment')
        self.assertIn('Could not attach node_modules', state['message'])
        self.assertEqual(classify_child(state, False), 'environment')
        self.assertEqual(state['native_change']['repairs'], 0); self.assertEqual(len(self.worker.calls), 1)
        self.assertIn('a-b', (self.ext / 'src/app.ts').read_text())

    def test_e2e_backend_not_ready_is_environment(self):
        state = self.work_and_verify(self.candidate(source='export const add=(a:number,b:number)=>a+b; // NOBACKEND\n'))
        self.assertEqual(state['native_change']['checks'][-1]['failure_class'], 'environment')
        self.assertEqual(state['phase'], 'blocked'); self.assertEqual(state['native_change']['repairs'], 0)

    def test_e2e_crash_without_summary_is_runtime_bug_and_stays_repairable_in_a_child(self):
        state = self.work_and_verify(self.candidate(source='export const add=(a:number,b:number)=>a+b; // CRASH\n'))
        native = state['native_change']
        self.assertEqual((native['checks'][-1]['failure_class'], native['checks'][-1]['failure_kind']), ('runtime_bug', 'test'))
        self.assertEqual(native['stage'], 'work'); self.assertEqual(native['repairs'], 1)
        self.assertIn('no "N/N checks passed"', native['feedback'])

    def test_e2e_type_error_is_a_product_repair(self):
        state = self.work_and_verify(self.candidate(source='TYPE_ERROR\n'))
        native = state['native_change']
        self.assertEqual((native['checks'][-1]['failure_class'], native['checks'][-1]['failure_kind']), ('product', 'test'))
        self.assertEqual(native['stage'], 'work'); self.assertEqual(native['repairs'], 1)

    def test_e2e_pass_keeps_the_evidence_shape(self):
        state = self.work_and_verify(self.candidate())
        check = state['native_change']['checks'][-1]
        self.assertTrue(check['passed'], check['detail']); self.assertIsNone(check['failure_kind'])
        self.assertNotIn('failure_class', check)
        self.assertEqual(list(check['evidence']['steps'][0]), ['step', 'argv', 'exit_code', 'stdout', 'stderr', 'passed'])
        self.assertEqual(list(check['evidence']['steps'][1]), ['step', 'argv', 'exit_code', 'stdout', 'stderr', 'report', 'summary', 'passed'])


if __name__ == '__main__':
    unittest.main()
