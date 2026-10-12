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
from .node_toolchain import (CHECKS, MAX_REPORT, STEP_SECONDS, attach_modules, classify_output, dependency_lock,  # noqa: F401
                             detach_modules, run_fixed, summarize_e2e, summarize_vitest)
from .sandbox_gate import task_guard, GateUnavailable
from .snapshots import safe_file, scope_list, scoped_path, bytes_hash, durable_write

FIELDS = ('toolchain', 'source_roots', 'owned', 'extra_sources', 'package', 'tests', 'regression_tests',
          'node_exe', 'build_script', 'reference', 'trusted_native')
OWNED_SUFFIXES = ('.ts', '.tsx', '.mts', '.cts', '.js', '.mjs', '.cjs', '.css', '.html', '.json')
TEST_SUFFIXES = ('.test.ts', '.test.tsx', '.test.js', '.test.mjs')
# Dependency/tool configuration stays operator-controlled: a worker cannot change what "the tests" mean.
LOCKED = re.compile(r'(?i)^(package\.json|package-lock\.json|npm-shrinkwrap\.json|pnpm-lock\.yaml|yarn\.lock|\.npmrc|'
                    r'tsconfig(\..*)?\.json|(vitest|vite|vitest\.workspace)\.config\..*)$')
GENERATED_DIR = re.compile(r'(?i)^(node_modules|dist|build|out|coverage)$|(^|[-_.])dist($|[-_.])')
# Optional fixed e2e step (SOL e2e-panel, 11/10/2026): `node <script>` after the build, with operator-pinned environment
# values from this allowlist only. It must print "N/N checks passed" (N >= min_checks) and exit 0.
E2E_FIELDS = ('script', 'env', 'timeout_seconds', 'min_checks')
E2E_ENV = frozenset({'CHROME_PATH', 'CHROME_ARGS', 'NA_PYTHON', 'NA_BACKEND_DIR', 'NA_E2E_BACKEND_PORT',
                     'NA_MOCK_PORT', 'NA_PROXY_PORT'})


def is_node(recipe):
    return isinstance(recipe, dict) and recipe.get('toolchain') == 'node'


def _under(path, package):
    return path.startswith(package + '/')


def validate(value):
    if not isinstance(value, dict):
        raise LedgerError('Node change recipe must be an object.')
    exact_fields({k: v for k, v in value.items() if k != 'e2e'}, FIELDS, 'Node change')
    if value['toolchain'] != 'node':
        raise LedgerError('Unknown native toolchain.')
    if value['trusted_native'] is not True:
        raise LedgerError('Node verification requires explicit trusted project execution.')
    value = dict(value)
    for key in ('source_roots', 'owned'):
        value[key] = scope_list(value[key])
    # The e2e step can be the whole verification (e.g. the deliverable IS the e2e harness): only then may tests be empty.
    value['tests'] = [] if value['tests'] == [] and 'e2e' in value else scope_list(value['tests'])
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
    if 'e2e' in value:
        value['e2e'] = validate_e2e(value['e2e'])
    return value


def validate_e2e(e2e):
    if not isinstance(e2e, dict):
        raise LedgerError('e2e must be an object.')
    exact_fields(e2e, E2E_FIELDS, 'Node e2e step')
    script = scoped_path(e2e['script'])
    if not script.lower().endswith(('.mjs', '.js', '.cjs')):
        raise LedgerError('e2e script must be a JavaScript file relative to the package.')
    env = e2e['env']
    if not isinstance(env, dict) or not set(env) <= E2E_ENV:
        raise LedgerError('e2e environment keys must come from the allowlist: ' + ', '.join(sorted(E2E_ENV)))
    for key, text in env.items():
        if not isinstance(text, str) or not 1 <= len(text) <= 500:
            raise LedgerError('e2e environment values must be short strings: ' + key)
        scan_text(text.encode())  # operator values are recorded; never accept credential-like content here
    if type(e2e['timeout_seconds']) is not int or not 60 <= e2e['timeout_seconds'] <= 1200:
        raise LedgerError('e2e timeout must be 60-1200 seconds.')
    if type(e2e['min_checks']) is not int or not 1 <= e2e['min_checks'] <= 10000:
        raise LedgerError('e2e min_checks must be 1-10000.')
    return dict(e2e, script=script)


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
    # Files under a generated output directory (dist, harness-dist, e2e-*-dist ...) are build OUTPUTS that the fixed build
    # step rewrites; they are staged but are not compiler inputs that must stay unchanged during verification.
    native['verification_inputs'] = {name: digest for name, digest in expected.items()
                                     if not any(GENERATED_DIR.search(part) for part in name.split('/')[:-1])}
    return destination, {'compiler_input_manifest_sha256': bytes_hash(canonical(expected).encode()),
                         'compiler_input_count': len(expected), 'local_only_source_count': len(omitted),
                         'skipped_large_local_files': skipped[:50]}


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
    vitest_files = [rel(p) for p in recipe['tests'] + recipe['regression_tests']]
    steps = [('typecheck', [str(node), str(tools['tsc']), '--noEmit', '-p', '.'])]
    if vitest_files:  # never run Vitest without files: that would run the whole suite instead of the pinned set
        steps.append(('vitest', [str(node), str(tools['vitest']), 'run', '--reporter=json', '--outputFile=' + str(report_path),
                                 '--no-cache', *vitest_files]))
    steps.append(('build', [str(node), recipe['build_script']]))
    e2e = recipe.get('e2e')
    if e2e:
        if not (package_dir / e2e['script']).is_file():
            raise GateUnavailable('Pinned e2e script missing from staged inputs: ' + e2e['script'])
        steps.append(('e2e', [str(node), e2e['script']], e2e['env']))

    def check(name, code, out, err):
        if name == 'vitest':
            summary = summarize_vitest(report_path, package_dir, [rel(t) for t in recipe['tests']])
            fields = {}
            if report_path.is_file() and report_path.stat().st_size <= MAX_REPORT:
                fields['report'] = runtime.store.blob(report_path.read_bytes())
            fields['summary'] = {k: v for k, v in summary.items() if k != 'passed'}
            return summary['passed'], fields
        if name == 'build':
            built = package_dir / 'dist/manifest.json'
            return built.is_file(), {'dist_manifest_sha256': bytes_hash(built.read_bytes()) if built.is_file() else None}
        if name == 'e2e':
            summary = summarize_e2e(out, e2e['min_checks'])
            return summary['passed'], {'summary': {k: v for k, v in summary.items() if k != 'passed'}}
        return True, {}

    timeouts = dict(STEP_SECONDS, **({'e2e': e2e['timeout_seconds']} if e2e else {}))
    attach_modules(modules, link)
    try:
        ran, failure = run_fixed(steps, package_dir, {'CI': 'true'}, timeouts, guard, check)
    finally:
        detach_modules(link, modules)
    results = [{k: runtime.store.blob(v.encode()) if k in ('stdout', 'stderr') else v for k, v in step.items()
                if k not in ('seconds', 'failure_class')} for step in ran]
    native_change.check_snapshot(runtime, state)
    native_test_workspace.check_inputs(runtime, state)
    native_test_workspace.check_workspace(state)
    if dependency_lock(modules) != lock:
        raise GateUnavailable('Project node_modules changed during verification; candidate and evidence preserved.')
    evidence = {'snapshot': state['snapshot'], 'steps': results, 'trusted_native': True, 'device_tested': False,
                'browser_tested': False, 'mock_e2e_ran': any(s['step'] == 'e2e' for s in results),
                'environment': dict(environment, dependency_lock_sha256=lock, node=str(node), npm_install_ran=False)}
    if failure is None:
        vitest = next((s for s in results if s['step'] == 'vitest'), None)
        totals = vitest['summary'].get('totals', {}) if vitest else {'numPassedTests': 'no'}
        e2e_note = ''
        if e2e:
            e2e_summary = results[-1]['summary']
            e2e_note = ', mock e2e ' + str(e2e_summary['checks_passed']) + '/' + str(e2e_summary['checks_total']) + ' checks'
        return {'passed': True, 'detail': 'typecheck, vitest (' + str(totals.get('numPassedTests')) + ' passed), build'
                + e2e_note + ' passed.', 'evidence': evidence, 'failure_kind': None}
    name, out, err, reason = failure['step'], failure['stdout'], failure['stderr'], failure.get('summary', {}).get('reason')
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
    # An unusable machine (port in use, browser/backend not started, dependencies) is not a product defect and must not
    # spend a repair round. A harness that printed no summary stays repairable here: the worker may own the e2e script.
    failure_class = failure['failure_class'] or 'product'
    return {'passed': False, 'detail': detail, 'evidence': evidence, 'failure_class': failure_class,
            'failure_kind': 'environment' if failure_class == 'environment' else 'test'}
