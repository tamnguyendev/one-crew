"""Node/TypeScript toolchain for the native_change recipe (SOL-22fcd61f).

Same trust model as the Flutter recipe: the operator authorizes the project's own TypeScript compiler, Vitest suite and
build script as trusted project code. Commands are fixed by the runtime (never by the model) and bounded in time, output
and environment, but this is NOT an OS sandbox: no network block, child processes allowed (esbuild needs them).

The worker still only reads the filtered snapshot and returns complete files. Verification runs in a separate workspace
staged from the snapshot plus local-only project files; the project's installed node_modules is attached by a
runtime-created junction that is removed right after the commands, and its lock manifest must be unchanged.
"""
import json
import os
from pathlib import Path
import re
import uuid

from .discovery import EXCLUDED, permitted, scan_text
from .ledger import LedgerError, canonical, exact_fields
from .native_audit import capture, workspace_path
from .sandbox_gate import command, task_guard, GateUnavailable
from .snapshots import safe_file, scope_list, scoped_path, bytes_hash, durable_write

FIELDS = ('toolchain', 'source_roots', 'owned', 'extra_sources', 'package', 'tests', 'regression_tests',
          'node_exe', 'build_script', 'reference', 'trusted_native')
OWNED_SUFFIXES = ('.ts', '.tsx', '.mts', '.cts', '.js', '.mjs', '.cjs', '.css', '.html', '.json')
TEST_SUFFIXES = ('.test.ts', '.test.tsx', '.test.js', '.test.mjs')
# Dependency/tool configuration stays operator-controlled: a worker cannot change what "the tests" mean.
LOCKED = re.compile(r'(?i)^(package\.json|package-lock\.json|npm-shrinkwrap\.json|pnpm-lock\.yaml|yarn\.lock|\.npmrc|'
                    r'tsconfig(\..*)?\.json|(vitest|vite|vitest\.workspace)\.config\..*)$')
GENERATED_DIR = re.compile(r'(?i)^(node_modules|dist|build|out|coverage)$|(^|[-_.])dist($|[-_.])')
STEP_SECONDS = {'typecheck': 300, 'vitest': 600, 'build': 300}
MAX_REPORT = 5_000_000


def is_node(recipe):
    return isinstance(recipe, dict) and recipe.get('toolchain') == 'node'


def _under(path, package):
    return path.startswith(package + '/')


def validate(value):
    if not isinstance(value, dict):
        raise LedgerError('Node change recipe must be an object.')
    exact_fields(value, FIELDS, 'Node change')
    if value['toolchain'] != 'node':
        raise LedgerError('Unknown native toolchain.')
    if value['trusted_native'] is not True:
        raise LedgerError('Node verification requires explicit trusted project execution.')
    value = dict(value)
    for key in ('source_roots', 'owned', 'tests'):
        value[key] = scope_list(value[key])
    value['regression_tests'] = scope_list(value['regression_tests']) if value['regression_tests'] != [] else []
    if len(value['regression_tests']) > 30:
        raise LedgerError('At most 30 read-only regression test files.')
    package = scoped_path(value['package'])
    if package not in value['source_roots']:
        raise LedgerError('Package must be a captured source root.')
    for name in value['owned']:
        leaf = name.rsplit('/', 1)[-1]
        if not _under(name, package) or not name.lower().endswith(OWNED_SUFFIXES):
            raise LedgerError('Node changes are restricted to explicit source files in the package.')
        if LOCKED.match(leaf) or any(GENERATED_DIR.search(part) for part in name.split('/')[1:-1]):
            raise LedgerError('Dependency, tool configuration and generated output stay operator-controlled: ' + name)
        if not permitted(name):
            raise LedgerError('Private paths cannot be worker-owned in a Node recipe.')
    if not all(p in value['owned'] and _under(p, package + '/test') and p.endswith(TEST_SUFFIXES) for p in value['tests']):
        raise LedgerError('Tests must be explicitly owned test files under <package>/test/.')
    for name in value['regression_tests']:
        if name in value['owned'] or not _under(name, package + '/test') or not name.endswith(TEST_SUFFIXES):
            raise LedgerError('Regression tests must be read-only test files under <package>/test/.')
    if value['extra_sources'] != {}:
        raise LedgerError('Node recipes do not accept hash-pinned extra sources.')
    node = value['node_exe']
    if not isinstance(node, str) or not Path(node).is_absolute() or not node.lower().endswith('\\node.exe') and not node.lower().endswith('/node.exe'):
        raise LedgerError('node_exe must be the absolute path of node.exe.')
    script = scoped_path(value['build_script'])
    if not script.lower().endswith(('.mjs', '.js', '.cjs')) or package + '/' + script in value['owned']:
        raise LedgerError('build_script must be a read-only script path relative to the package.')
    if not isinstance(value['reference'], str) or not 1 <= len(value['reference']) <= 500:
        raise LedgerError('Operator reference required.')
    return value


def prepare(runtime, state, recipe, progress=None):
    workspace = workspace_path(runtime.ledger.state_root, 'native-change')
    captured = capture(runtime, workspace, recipe['source_roots'], progress=progress)
    originals = {}
    for name in recipe['owned']:
        original = safe_file(runtime.ledger.project, name)
        if original.exists():
            data = original.read_bytes(); scan_text(data)
            if captured['files'].get(name) != bytes_hash(data):
                raise LedgerError('Writable file not captured: ' + name)
            originals[name] = runtime.store.blob(data)
        else:
            originals[name] = None
    state['native_change'] = {'stage': 'work', 'toolchain': 'node', 'workspace': str(workspace), 'originals': originals,
        'manifest': runtime.store.evidence(canonical(captured).encode()), 'worker_session': str(uuid.uuid4()),
        'review_session': str(uuid.uuid4()), 'worker_started': False, 'review_started': False,
        'attempts': [], 'repairs': 0, 'feedback': '', 'checks': [], 'applied': []}
    state['original'].update({p: h for p, h in originals.items() if h})
    state['files'].update(state['original'])


def _skip_dir(base, name):
    lowered = name.lower()
    return (lowered in EXCLUDED or lowered.startswith('.env') or GENERATED_DIR.search(name) is not None
            or (base / name).is_symlink() or (hasattr(base / name, 'is_junction') and (base / name).is_junction()))


def prepare_verification(runtime, state, recipe):
    """Stage snapshot + candidate + local-only project inputs (never shown to the model) into a fresh workspace."""
    native = state['native_change']; worker = Path(native['workspace'])
    manifest = json.loads(runtime.store.read_evidence(native['manifest']))['files']
    expected = dict(manifest, **state['files'])
    omitted = {}; skipped = []; total = 0; visited = 0
    for root in recipe['source_roots']:
        top = safe_file(runtime.ledger.project, root)
        for directory, dirs, files in os.walk(top, followlinks=False):
            base = Path(directory)
            dirs[:] = sorted(d for d in dirs if not _skip_dir(base, d))
            visited += len(dirs) + len(files)
            if visited > 100000:
                raise GateUnavailable('Local Node input enumeration exceeds limit.')
            for leaf in sorted(files):
                name = (base / leaf).relative_to(runtime.ledger.project).as_posix()
                if name in expected or leaf.lower().endswith('.log') or leaf.lower().startswith('.env'):
                    continue
                source = safe_file(runtime.ledger.project, name)
                if source.is_symlink():
                    continue
                if source.stat().st_size > 2_000_000:
                    skipped.append(name); continue
                data = source.read_bytes(); total += len(data)
                if len(omitted) >= 20000 or total > 128_000_000:
                    raise GateUnavailable('Local Node inputs exceed size limit.')
                omitted[name] = bytes_hash(data)
    if 'local_test_sources' in native and native['local_test_sources'] != omitted:
        raise GateUnavailable('Local Node input set changed; preserve prior verification evidence.')
    native['local_test_sources'] = omitted
    destination = workspace_path(runtime.ledger.state_root, 'native-test')
    destination.mkdir(parents=True, exist_ok=False)
    for name, digest in expected.items():
        data = safe_file(worker, name).read_bytes()
        if bytes_hash(data) != digest:
            raise GateUnavailable('Worker input changed while staging Node inputs: ' + name)
        durable_write(safe_file(destination, name), data)
    for name, digest in omitted.items():
        data = safe_file(runtime.ledger.project, name).read_bytes()
        if bytes_hash(data) != digest:
            raise GateUnavailable('Local input changed while staging Node inputs: ' + name)
        durable_write(safe_file(destination, name), data)
    expected = dict(expected, **omitted)
    native['verification_workspace'] = str(destination)
    native['verification_inputs'] = expected
    return destination, {'compiler_input_manifest_sha256': bytes_hash(canonical(expected).encode()),
                         'compiler_input_count': len(expected), 'local_only_source_count': len(omitted),
                         'skipped_large_local_files': skipped[:50]}


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


def verify(runtime, task_id, state, recipe):
    from . import native_change, native_test_workspace
    native = state['native_change']
    node = Path(recipe['node_exe'])
    if not node.is_file():
        raise GateUnavailable('Node executable unavailable; no AI code repair attempted.')
    modules = safe_file(runtime.ledger.project, recipe['package'] + '/node_modules')
    tools = {'tsc': modules / 'typescript/bin/tsc', 'vitest': modules / 'vitest/vitest.mjs'}
    if not all(p.is_file() for p in tools.values()):
        raise GateUnavailable('TypeScript/Vitest are not installed in the project node_modules; no AI code repair attempted.')
    native_change.check_snapshot(runtime, state)
    guard = task_guard(runtime.control, task_id); guard()
    lock = dependency_lock(modules)
    workspace, environment = prepare_verification(runtime, state, recipe)
    package_dir = workspace / recipe['package']
    if not (package_dir / recipe['build_script']).is_file():
        raise GateUnavailable('Pinned build script missing from staged inputs: ' + recipe['build_script'])
    link = package_dir / 'node_modules'
    rel = lambda p: p[len(recipe['package']) + 1:]
    report_path = package_dir / ('.onecrew-vitest-' + uuid.uuid4().hex + '.json')
    steps = [('typecheck', [str(node), str(tools['tsc']), '--noEmit', '-p', '.']),
             ('vitest', [str(node), str(tools['vitest']), 'run', '--reporter=json', '--outputFile=' + str(report_path),
                         '--no-cache', *[rel(p) for p in recipe['tests'] + recipe['regression_tests']]]),
             ('build', [str(node), recipe['build_script']])]
    results = []; failure = None
    attach_modules(modules, link)
    try:
        for name, argv in steps:
            code, out, err = command(argv, package_dir, STEP_SECONDS[name], guard, {'CI': 'true'})
            step = {'step': name, 'argv': argv, 'exit_code': code, 'stdout': runtime.store.blob(out.encode()),
                    'stderr': runtime.store.blob(err.encode())}
            ok = code == 0
            if name == 'vitest':
                summary = summarize_vitest(report_path, package_dir, [rel(t) for t in recipe['tests']])
                if report_path.is_file() and report_path.stat().st_size <= MAX_REPORT:
                    step['report'] = runtime.store.blob(report_path.read_bytes())
                step['summary'] = {k: v for k, v in summary.items() if k != 'passed'}
                ok = ok and summary['passed']
            if name == 'build':
                built = package_dir / 'dist/manifest.json'
                step['dist_manifest_sha256'] = bytes_hash(built.read_bytes()) if built.is_file() else None
                ok = ok and built.is_file()
            step['passed'] = ok; results.append(step)
            if not ok:
                failure = (name, out, err, step.get('summary', {}).get('reason')); break
    finally:
        detach_modules(link, modules)
    native_change.check_snapshot(runtime, state)
    native_test_workspace.check_inputs(runtime, state)
    native_test_workspace.check_workspace(state)
    if dependency_lock(modules) != lock:
        raise GateUnavailable('Project node_modules changed during verification; candidate and evidence preserved.')
    evidence = {'snapshot': state['snapshot'], 'steps': results, 'trusted_native': True, 'device_tested': False,
                'browser_tested': False, 'environment': dict(environment, dependency_lock_sha256=lock,
                                                             node=str(node), npm_install_ran=False)}
    if failure is None:
        totals = results[1]['summary'].get('totals', {})
        return {'passed': True, 'detail': 'typecheck, vitest (' + str(totals.get('numPassedTests')) + ' passed) and build passed.',
                'evidence': evidence, 'failure_kind': None}
    name, out, err, reason = failure
    try:
        detail = scan_text((out + err).encode())[-12000:]
    except LedgerError:
        detail = 'Command output withheld by credential policy; inspect local receipt.'
    if reason:
        try:
            reason = scan_text(reason.encode())
        except LedgerError:
            reason = 'Failure summary withheld by credential policy; inspect local receipt.'
    detail = 'Fixed Node step failed: ' + name + ('. ' + reason if reason else '') + '\n' + detail
    return {'passed': False, 'detail': detail, 'evidence': evidence, 'failure_kind': 'test'}
