"""Shared Node/TypeScript toolchain pieces: dependency attach/lock, fixed bounded steps, report summaries, failure classes.

Used by the native_change Node recipe (node_change) and by delivery root stages. Commands are fixed by the runtime and
bounded in time, output and environment (sandbox_gate.command); this is NOT an OS sandbox.
"""
import json
import os
from pathlib import Path
import re
import time

from .ledger import LedgerError
from .sandbox_gate import command, GateUnavailable
from .snapshots import bytes_hash

STEP_SECONDS = {'typecheck': 300, 'vitest': 600, 'build': 300}
DEFAULT_SECONDS = 300
MAX_STEPS = 20
MAX_ARGS = 300
CHECKS = re.compile(r'(\d+)/(\d+) checks passed')
MAX_REPORT = 5_000_000
FAILURE_CLASSES = ('product', 'environment', 'runtime_bug')
# Ordered: an unusable environment explains the product-looking failures it causes (every check FAILs when Chrome
# never started), so environment signals win over product ones.
ENVIRONMENT = re.compile('|'.join((
    r'\bEADDRINUSE\b', r'address already in use',
    r'chrome did not launch', r'failed to launch the browser process', r'browser was not found at',
    r'could not find (?:chrome|expected browser)',
    r'backend did not become ready',
    r'cannot find module [\'"][^\'"\n]*node_modules', r'node_modules[^\n]{0,120}(?:missing|not found|does not exist|not installed)',
    r'ENOENT[^\n]{0,300}node_modules', r'no \.package-lock\.json', r'(?:typescript|vitest)[^\n]{0,40}not installed',
    r'python[^\n]{0,120}(?:not found|missing|is not recognized|no such file)', r'spawn [^\n]{0,300}python[^\n]{0,40}ENOENT',
    r'ENOENT[^\n]{0,300}python(?:\.exe)?\b',
    r'EPERM[^\n]{0,300}(?:junction|symlink|node_modules)', r'(?:junction|symlink)[^\n]{0,300}(?:EPERM|operation not permitted)',
)), re.I)
PRODUCT = re.compile('|'.join((
    r'\berror TS\d+', r'\bERROR: ', r'\[ERROR\]', r'Build failed with \d+ errors?',
    r'AssertionError', r'Assertion ?failed', r'Failing assertions \(', r'Owned tests without a passing result',
    r'Cannot find module [\'"]\.{1,2}/', r'Failed to (?:load url|resolve import)',
    r'^\s*(?:Tests|Test Files)\s+\d+ failed', r'^\s*(?:×|✗)\s+\S+\.(?:test|spec)\.', r'^\s*FAIL\b',
)), re.M)


def dependency_lock(modules):
    """Fingerprint of the installed dependency tree npm itself maintains; must not change while we verify."""
    lock = modules / '.package-lock.json'
    if not lock.is_file():
        raise GateUnavailable('Project node_modules has no .package-lock.json; install dependencies there (npm ci).')
    return bytes_hash(lock.read_bytes())


def attach_modules(target, link):
    if os.name != 'nt':
        os.symlink(target, link, target_is_directory=True); return
    import _winapi
    _winapi.CreateJunction(str(target), str(link))


def detach_modules(link, target):
    if os.path.lexists(link):
        if not (os.path.islink(link) or (hasattr(os.path, 'isjunction') and os.path.isjunction(link))):
            raise GateUnavailable('Verification node_modules is not the runtime junction; refusing to remove it.')
        os.rmdir(link) if os.name == 'nt' else os.unlink(link)
    if os.path.lexists(link) or not Path(target).is_dir():
        raise GateUnavailable('Could not detach verification node_modules cleanly.')


def summarize_e2e(out, minimum):
    """Pass only on an explicit 'N/N checks passed' summary with N >= minimum; collect FAIL lines for feedback."""
    found = CHECKS.findall(out)
    failed = [line.strip()[:400] for line in out.splitlines() if line.lstrip().startswith(('FAIL', 'XPASS'))][:40]
    if not found:
        return {'passed': False, 'reason': 'e2e printed no "N/N checks passed" summary.', 'failed_lines': failed}
    passed, total = (int(n) for n in found[-1])
    ok = passed == total and total >= minimum
    reason = None if ok else ('e2e checks: ' + str(passed) + '/' + str(total) + ' passed (minimum ' + str(minimum) + ').'
                              + ('\n' + '\n'.join(failed) if failed else ''))
    return {'passed': ok, 'reason': reason, 'checks_passed': passed, 'checks_total': total, 'failed_lines': failed}


def summarize_vitest(path, package_dir, owned_tests):
    """Pass only with real executed tests: >0 total, 0 failed, every owned test file passed with >=1 passing assertion."""
    if not path.is_file() or path.stat().st_size > MAX_REPORT:
        return {'passed': False, 'reason': 'Vitest JSON report missing or too large.'}
    try:
        report = json.loads(path.read_text(encoding='utf-8'))
    except ValueError:
        return {'passed': False, 'reason': 'Vitest JSON report unreadable.'}
    totals = {k: report.get(k) for k in ('numTotalTests', 'numPassedTests', 'numFailedTests', 'numPendingTests', 'numTodoTests')}
    files = {}; failures = []
    for result in report.get('testResults') or []:
        try:
            rel = Path(result.get('name', '')).resolve().relative_to(Path(package_dir).resolve()).as_posix()
        except ValueError:
            continue
        passed = sum(1 for a in result.get('assertionResults') or [] if a.get('status') == 'passed')
        files[rel] = {'status': result.get('status'), 'passed_assertions': passed}
        if result.get('status') != 'passed' and result.get('message'):
            failures.append(rel + ': ' + _first_lines(result['message']))  # e.g. the suite failed to load
        for assertion in result.get('assertionResults') or []:
            if assertion.get('status') == 'failed':
                message = _first_lines((assertion.get('failureMessages') or [''])[0])
                failures.append(rel + ' > ' + str(assertion.get('fullName') or assertion.get('title')) + (': ' + message if message else ''))
    missing = [t for t in owned_tests if files.get(t, {}).get('status') != 'passed' or files[t]['passed_assertions'] < 1]
    ok = (report.get('success') is True and isinstance(totals['numTotalTests'], int) and totals['numTotalTests'] > 0
          and totals['numFailedTests'] == 0 and (totals['numPassedTests'] or 0) > 0 and not missing)
    reason = None
    if not ok:
        reason = ('Owned tests without a passing result: ' + ', '.join(missing) if missing
                  else 'Vitest reported no passing tests or failures.')
        if failures:
            # The worker cannot read the verification workspace: give it the failing assertions themselves.
            reason += '\nFailing assertions (' + str(len(failures)) + '):\n- ' + '\n- '.join(failures)[:6000]
    return {'passed': ok, 'reason': reason, 'totals': totals, 'files': files, 'failures': failures[:50]}


def _first_lines(text, lines=4, limit=700):
    return ' | '.join(line.strip() for line in str(text).splitlines()[:lines] if line.strip())[:limit]


def classify_output(text, step=None):
    """'environment' | 'product' | 'runtime_bug' | None for the output of a failed fixed step.

    environment: the machine, not the code (port in use, browser/backend not started, dependencies, junction rights);
    product: compiler, bundler, test assertion or a FAILed product check; runtime_bug: an e2e run (step 'e2e*') that never
    printed its 'N/M checks passed' summary, so the harness itself did not finish. None: no known signal."""
    text = str(text or '')[-400_000:]
    if ENVIRONMENT.search(text):
        return 'environment'
    if str(step or '').startswith('e2e') and not CHECKS.search(text):
        return 'runtime_bug'
    if PRODUCT.search(text):
        return 'product'
    return None


def _steps(steps):
    if not isinstance(steps, (list, tuple)) or not 1 <= len(steps) <= MAX_STEPS:
        raise LedgerError('Fixed Node steps must be 1-' + str(MAX_STEPS) + ' (name, argv[, env]) entries.')
    result = []
    for step in steps:
        if not isinstance(step, (list, tuple)) or len(step) not in (2, 3):
            raise LedgerError('A fixed Node step is (name, argv) or (name, argv, env).')
        name, argv, extra = step[0], step[1], step[2] if len(step) == 3 else {}
        if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_:-]{0,39}', name):
            raise LedgerError('Fixed Node step name must be a short lowercase identifier.')
        if (not isinstance(argv, (list, tuple)) or not 1 <= len(argv) <= MAX_ARGS
                or not all(isinstance(a, str) and 0 < len(a) <= 4000 for a in argv)):
            raise LedgerError('Fixed Node step argv must be 1-' + str(MAX_ARGS) + ' non-empty strings: ' + name)
        if not isinstance(extra, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in extra.items()):
            raise LedgerError('Fixed Node step environment must map strings to strings: ' + name)
        result.append((name, [str(a) for a in argv], extra))
    return result


def run_fixed(steps, package_dir, env=None, timeouts=None, guard=None, check=None):
    """Run fixed argv steps in order with cwd ``package_dir``; stop at the first failed step.

    ``steps``: [(name, argv)] or [(name, argv, step_env)]; ``env``: extra environment for every step (sandbox_gate keeps
    its own allowlist); ``timeouts``: {name: seconds}, default STEP_SECONDS / DEFAULT_SECONDS. ``check(name, code, out,
    err) -> (ok, fields)`` refines a step's verdict and adds fields (e.g. a report summary). Returns (results, failure):
    every result holds step, argv, exit_code, stdout, stderr, seconds, the check fields, passed and failure_class;
    failure is the failed result or None. Deadlines and output limits raise GateUnavailable as sandbox_gate.command does.
    """
    package_dir = Path(package_dir)
    results = []
    for name, argv, extra in _steps(steps):
        seconds = (timeouts or {}).get(name, STEP_SECONDS.get(name, DEFAULT_SECONDS))
        if type(seconds) is not int or not 1 <= seconds <= 7200:
            raise LedgerError('Fixed Node step timeout must be 1-7200 seconds: ' + name)
        started = time.monotonic()
        code, out, err = command(argv, package_dir, seconds, guard, dict(env or {}, **extra) or None)
        result = {'step': name, 'argv': argv, 'exit_code': code, 'stdout': out, 'stderr': err,
                  'seconds': round(time.monotonic() - started, 3)}
        ok = code == 0
        if check:
            verdict, fields = check(name, code, out, err)
            result.update(fields or {})
            ok = ok and bool(verdict)
        result['passed'] = ok
        summary = result.get('summary')
        reason = summary.get('reason') if isinstance(summary, dict) else None
        result['failure_class'] = None if ok else classify_output(out + '\n' + err + '\n' + str(reason or ''), name)
        results.append(result)
        if not ok:
            return results, result
    return results, None
