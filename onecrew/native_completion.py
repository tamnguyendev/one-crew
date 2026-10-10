"""Caller census and an opt-in APK gate for the current working tree.

These are runtime operations, never arbitrary worker shell permissions.
"""
import json
import os
from pathlib import Path
import re
import shutil
import zipfile
from urllib.parse import urljoin, urlparse
from urllib.request import url2pathname

from .discovery import EXCLUDED, scan_text
from .ledger import LedgerError, canonical, exact_fields
from .snapshots import safe_file, scoped_path, bytes_hash, durable_write
from .sandbox_gate import command, task_guard
from .android_build import verify_apk


def validate(recipe):
    symbol = recipe.get('caller_symbol')
    if symbol is not None and (not isinstance(symbol, str) or not re.fullmatch(r'[A-Za-z_]\w{0,99}', symbol)):
        raise LedgerError('Caller census requires one Dart identifier.')
    build = recipe.get('apk_build')
    if build is None:
        return
    exact_fields(build, ('package', 'base_package_name', 'android_sdk', 'max_seconds', 'native_authorized'), 'Current APK build')
    scoped_path(build['package'])
    if build['package'] not in recipe['source_roots']:
        raise LedgerError('APK package must be captured for review.')
    if not re.fullmatch(r'[a-z][a-z0-9_]*', build['base_package_name']):
        raise LedgerError('Expected Dart base package name required.')
    if not Path(build['android_sdk']).is_absolute() or build['native_authorized'] is not True:
        raise LedgerError('APK build requires an absolute SDK and explicit native authority.')
    if type(build['max_seconds']) is not int or not 10 <= build['max_seconds'] <= 3600:
        raise LedgerError('APK command timeout must be 10-3600 seconds.')


def census(project, symbol):
    """Read Dart bytes locally; expose only paths, hashes and hit line numbers.

    Internal directory aliases are deduplicated, external links fail closed.
    Unreadable files / traversal errors must not become a claim of full coverage.
    """
    root = Path(project).resolve()
    files, hits, aliases, excluded = {}, {}, {}, []
    pattern = re.compile(rb'(?<![A-Za-z0-9_])' + symbol.encode() + rb'(?![A-Za-z0-9_])')
    def error(value):
        raise LedgerError('Caller census could not enumerate project source.') from value
    count = 0
    for directory, dirs, names in os.walk(root, followlinks=False, onerror=error):
        current = Path(directory)
        for name in list(dirs):
            path = current/name
            relative = path.relative_to(root).as_posix()
            if name.lower() in EXCLUDED or name.lower() in ('.gradle', '.symlinks', '.plugin_symlinks', 'ephemeral'):
                dirs.remove(name); excluded.append(relative); continue
            if path.is_symlink() or path.is_junction():
                target = path.resolve()
                if not target.is_relative_to(root):
                    raise LedgerError('Caller census found external directory link: '+relative)
                aliases[relative] = target.relative_to(root).as_posix()
                dirs.remove(name)
        for name in names:
            count += 1
            if count > 250000:
                raise LedgerError('Caller census entry bound exceeded; coverage incomplete.')
            if not name.lower().endswith('.dart'):
                continue
            path = current/name; relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                raise LedgerError('Caller census found a Dart file link: '+relative)
            if path.stat().st_size > 4000000:
                raise LedgerError('Caller census Dart file exceeds read bound: '+relative)
            data = path.read_bytes(); files[relative] = bytes_hash(data)
            lines = [i for i, line in enumerate(data.splitlines(), 1) if pattern.search(line)]
            if lines: hits[relative] = lines
    # An alias into an excluded tree is not covered by the ordinary traversal.
    for target in aliases.values():
        if any(target == p or target.startswith(p+'/') for p in excluded):
            raise LedgerError('Caller alias resolves into excluded source; coverage incomplete.')
    return dict(symbol=symbol, files=files, hits=hits, aliases=aliases, excluded=sorted(excluded),
                dart_files=len(files), scope='Project Dart source excluding listed generated/cache/control directories')


def collect(runtime, state, recipe):
    result = census(runtime.ledger.project, recipe['caller_symbol'])
    manifest = json.loads(runtime.store.read_blob(state['native_change']['manifest']))['files']
    missing = set(result['hits']) - set(manifest)
    if missing:
        raise LedgerError('Caller files need read capture before review: '+', '.join(sorted(missing)))
    digest = runtime.store.blob(canonical(result).encode())
    state['native_change']['caller_census'] = digest
    return {k:v for k,v in result.items() if k != 'files'}


def check_census(runtime, state, recipe):
    if not recipe.get('caller_symbol'): return
    old = json.loads(runtime.store.read_blob(state['native_change']['caller_census']))
    new = census(runtime.ledger.project, recipe['caller_symbol'])
    if old != new:
        raise LedgerError('Project Dart source changed since caller census; preserve candidate for reconciliation.')


def build_inputs(runtime, state, recipe):
    project = runtime.ledger.project
    for name, digest in state['files'].items():
        if bytes_hash(safe_file(project, name).read_bytes()) != digest:
            raise LedgerError('Applied candidate changed before/during APK build: '+name)
    result = census(project, recipe.get('caller_symbol', '__onecrew_build_inputs__'))
    inputs = dict(result['files'])
    app = safe_file(project, recipe['apk_build']['package'])
    config_path = app/'.dart_tool/package_config.json'
    config = json.loads(config_path.read_text(encoding='utf-8'))
    packages = [p for p in config['packages'] if p['name'] == recipe['apk_build']['base_package_name']]
    if len(packages) != 1: raise LedgerError('APK dependency graph missing unique base package.')
    uri = urlparse(urljoin(config_path.as_uri(), packages[0]['rootUri']))
    if uri.scheme != 'file' or uri.netloc not in ('', 'localhost'):
        raise LedgerError('APK base dependency must use current local source.')
    if Path(url2pathname(uri.path)).resolve() != (project/recipe['package']).resolve():
        raise LedgerError('APK base dependency does not resolve to applied main-project source.')
    for root in recipe['source_roots']:
        for name in ('pubspec.yaml', 'pubspec.lock', '.dart_tool/package_config.json'):
            path = safe_file(project, root+'/'+name)
            if path.is_file(): inputs[root+'/'+name] = bytes_hash(path.read_bytes())
    for directory, dirs, names in os.walk(app/'android'):
        dirs[:] = [d for d in dirs if d.lower() not in ('build', '.gradle', '.cxx')]
        for name in names:
            path = Path(directory)/name
            # Generated SDK-local metadata is not product source.
            if name == 'local.properties': continue
            safe_file(project, path.relative_to(project).as_posix())
            inputs[path.relative_to(project).as_posix()] = bytes_hash(path.read_bytes())
    return inputs


def build(runtime, task_id, seq, state, recipe):
    """One bounded build; durable intent prevents replay after an ambiguous crash."""
    native = state['native_change']
    if native.get('apk_build'):
        raise LedgerError('APK attempt already recorded; inspect preserved evidence before any retry.')
    if 'android.build' not in runtime.ledger.task(task_id, full=True)['handoff']['grant']['permissions']:
        raise LedgerError('APK build grant missing.')
    guard = task_guard(runtime.control, task_id); guard()
    before = build_inputs(runtime, state, recipe)
    app = safe_file(runtime.ledger.project, recipe['apk_build']['package'])
    sdk = Path(recipe['flutter_root'])
    argv = [str(sdk/'bin/cache/dart-sdk/bin/dart.exe'),
            '--packages='+str(sdk/'packages/flutter_tools/.dart_tool/package_config.json'),
            str(sdk/'bin/cache/flutter_tools.snapshot'), '--no-version-check', 'build', 'apk', '--debug', '--no-pub']
    output = safe_file(runtime.ledger.project, recipe['apk_build']['package']+'/build/app/outputs/flutter-apk/app-debug.apk')
    artifact_dir = Path(__file__).resolve().parent.parent/'.onecrew/artifacts'/task_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    lock = app/'.onecrew-apk.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise LedgerError('Another or interrupted APK build owns this package; inspect lock.') from None
    os.close(fd)
    try:
        receipt = dict(status='running', argv=argv, package=str(app), input_manifest=runtime.store.blob(canonical(before).encode()),
                       snapshot=state['snapshot'], variant='debug', pub_get_ran=False)
        native['apk_build'] = receipt
        seq = runtime.persist(task_id, seq, state)
        if output.exists():
            shutil.copyfile(output, artifact_dir/'previous-app-debug.apk')
            output.unlink()  # Only the exact generated APK, after preserving it.
        env = {'ANDROID_HOME':recipe['apk_build']['android_sdk'], 'ANDROID_SDK_ROOT':recipe['apk_build']['android_sdk'],
               'FLUTTER_ROOT':str(sdk), 'CI':'true', 'FLUTTER_SUPPRESS_ANALYTICS':'true', 'DART_SUPPRESS_ANALYTICS':'true'}
        if os.environ.get('JAVA_HOME'): env['JAVA_HOME'] = os.environ['JAVA_HOME']
        code, out, err = command(argv, app, recipe['apk_build']['max_seconds'], guard, env)
        log = out+'\n'+err
        try: scan_text(log.encode())
        except LedgerError: log = 'Build output withheld by credential policy; inspect native local command logs.'
        receipt.update(exit_code=code, log=runtime.store.blob(log.encode()), detail=log[-6000:])
        guard()
        if build_inputs(runtime, state, recipe) != before:
            raise LedgerError('Main source/dependency inputs changed during APK build; artifact not accepted.')
        if code: raise LedgerError('Debug APK build failed; see preserved build evidence.')
        apk = verify_apk(output)
        archive = artifact_dir/'app-debug.apk'
        shutil.copyfile(output, archive)
        verified = verify_apk(archive)
        if verified['sha256'] != apk['sha256']: raise LedgerError('APK changed while archiving.')
        receipt.update(status='passed', artifact=verified, main_output=apk)
    except (LedgerError, OSError, ValueError, zipfile.BadZipFile) as error:
        if native.get('apk_build'): native['apk_build'].update(status='blocked', error=str(error))
        state.update(phase='blocked', message='Applied/reviewed changes preserved; APK gate blocked: '+str(error),
                     recovery={'kind':'apk_build', 'automatic_retry':False})
    finally:
        lock.unlink(missing_ok=True)
    return seq
