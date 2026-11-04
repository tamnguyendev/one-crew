"""Small installed-wheel trial, not a full gate or a browser/pilot claim.

python -I <package>/verify/verify_obs2.py <package> <NEW work directory>
All fixture state, venv, marker, app-data and result files stay under work.
Uses installed identity open/stop and live HTTP; no provider is launched.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import statistics
import time
import urllib.parse
import urllib.request
import zipfile

MODULES = {'onecrew/v2/' + name + '.py' for name in ('engine', 'tracking', 'tracking_web', 'tracking_work', 'tracking_work_web', 'owner_cli', 'cli', 'plan', 'plan_cli')}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest_tree(path):
    return {p.relative_to(path).as_posix(): sha(p) for p in sorted(path.rglob('*')) if p.is_file()}


def package_identity(package):
    package = Path(package).resolve()
    manifest = json.loads((package / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('kind') != 'obs2-local-trial': raise ValueError('Not an OBS-2 local trial package.')
    if set(manifest.get('module_sha256') or {}) != MODULES: raise ValueError('Required OBS-2 module identities are missing.')
    listed = {}
    for line in (package / 'SHA256SUMS').read_text(encoding='utf-8').splitlines():
        checksum, rel = line.split('  ', 1)
        path = (package / rel).resolve()
        if not path.is_relative_to(package) or rel in listed: raise ValueError('Unsafe/duplicate checksum path.')
        if sha(path) != checksum: raise ValueError('Package hash mismatch: ' + rel)
        listed[rel] = checksum
    actual = {p.relative_to(package).as_posix() for p in package.rglob('*') if p.is_file() and p.name != 'SHA256SUMS'}
    if set(listed) != actual: raise ValueError('SHA256SUMS does not cover exactly the package files.')
    wheel = package / 'wheel' / manifest['wheel']['name']
    if not wheel.resolve().is_relative_to(package / 'wheel'): raise ValueError('Invalid wheel name.')
    if sha(wheel) != manifest['wheel']['sha256']: raise ValueError('Wheel differs from manifest.')
    with zipfile.ZipFile(wheel) as zipped:
        for name, expected in manifest['module_sha256'].items():
            if hashlib.sha256(zipped.read(name)).hexdigest() != expected: raise ValueError('Module differs from fixed snapshot: ' + name)
    return manifest, wheel


def isolated_env(work):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(('ONECREW_', 'CLAUDE_', 'CLAUDECODE', 'WF_WHEEL'))
           and k.upper() not in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONUTF8', 'PYTHONIOENCODING', 'CLAUDE_PROJECT_DIR')
           and not any(part in k.upper() for part in ('API_KEY', 'ACCESS_TOKEN', 'SECRET', 'PASSWORD'))}
    for key, name in (('LOCALAPPDATA', 'local'), ('APPDATA', 'roaming'), ('TEMP', 'temp'), ('TMP', 'temp'), ('USERPROFILE', 'home'), ('HOME', 'home')):
        folder = work / name; folder.mkdir(exist_ok=True); env[key] = str(folder)
    env.update(ONECREW_TRACK_MARKER_DIR=str(work / 'markers'), ONECREW_LANG='vi',
               GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    return env


def run(args, *, env, cwd, timeout=120):
    result = subprocess.run([str(a) for a in args], env=env, cwd=cwd, capture_output=True,
                            text=True, encoding='utf-8', errors='replace', timeout=timeout)
    if result.returncode: raise RuntimeError('Command failed: ' + str(args[1:3]) + '\n' + (result.stdout + result.stderr)[-1600:])
    return result.stdout


def check(package, work):
    package, work = Path(package).resolve(), Path(work).resolve()
    if work.exists(): raise ValueError('Work exists; use a fresh directory.')
    if work == package or package in work.parents: raise ValueError('Work must be outside package.')
    # A synthetic trial is never permitted to create project/state folders inside an existing checkout.
    if any((parent / '.git').exists() for parent in (work, *work.parents)):
        raise ValueError('Work must be outside a Git checkout.')
    manifest, wheel = package_identity(package)
    original_registry = Path(os.environ.get('LOCALAPPDATA') or Path.home() / '.onecrew')
    if os.environ.get('LOCALAPPDATA'): original_registry /= 'OneCrew'
    original_registry /= 'hook-projects.json'
    registry_before = sha(original_registry) if original_registry.is_file() else None
    package_before = digest_tree(package)
    work.mkdir(parents=True); env = isolated_env(work)
    report = {'kind': 'obs2-installed-trial-report', 'package': str(package), 'manifest': manifest,
              'label': 'DỮ LIỆU THỬ TỔNG HỢP — không phải pilot/provider thật', 'steps': [],
              'verifier': {'path': str(Path(__file__).resolve()), 'sha256': sha(__file__),
                           'in_package': Path(__file__).resolve() == package / 'verify/verify_obs2.py'},
              'browser_verified': False, 'result': 'fail'}
    python = work / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    opened = None
    def step(name, data): report['steps'].append({'name': name, 'result': 'pass', 'data': data})
    def cli(*args):
        return json.loads(run([python, '-I', '-X', 'utf8', '-m', 'onecrew.v2.tracking_cli', '--project', work / 'project',
                              '--state-root', work / 'state', 'track', *args], env=env, cwd=work))
    http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def get(path):
        with http.open(opened['url'] + path, timeout=20) as response: return json.load(response)
    try:
        step('fixed-snapshot-package-hashes', {'commit': manifest['code_commit'], 'wheel_sha256': sha(wheel)})
        run([sys.executable, '-X', 'utf8', '-m', 'venv', work / 'venv'], env=env, cwd=work)
        run([python, '-I', '-X', 'utf8', '-m', 'pip', 'install', '--no-index', '--no-deps', '--no-build-isolation', wheel], env=env, cwd=work)
        code = ('import hashlib,importlib,importlib.metadata,json,sys\nfrom pathlib import Path\n'
                'd=importlib.metadata.distribution("onecrew")\n'
                'names=("engine","tracking","tracking_web","tracking_work","tracking_work_web","owner_cli","cli","plan","plan_cli")\n'
                'mods={n:Path(importlib.import_module("onecrew.v2."+n).__file__).resolve() for n in names}\n'
                'assert all(p.is_relative_to(Path(sys.prefix).resolve()) for p in mods.values())\n'
                'print(json.dumps({"version":d.version,"origins":{n:str(p) for n,p in mods.items()},'
                '"module_sha256":{"onecrew/v2/"+n+".py":hashlib.sha256(p.read_bytes()).hexdigest() for n,p in mods.items()},'
                '"direct_url":json.loads(d.read_text("direct_url.json"))}))')
        origins = json.loads(run([python, '-I', '-X', 'utf8', '-c', code], env=env, cwd=work))
        assert origins['version'] == manifest['version']
        assert origins['module_sha256'] == manifest['module_sha256']
        assert origins['direct_url']['archive_info']['hashes']['sha256'] == manifest['wheel']['sha256']
        step('offline-installed-origins', origins)
        trial = json.loads(run([python, '-I', '-X', 'utf8', package / 'verify/scenario_obs2.py', work], env=env, cwd=work))
        trial.update(package=str(package), code_commit=manifest['code_commit'], version=manifest['version'], wheel_sha256=manifest['wheel']['sha256'])
        (work / 'trial.json').write_text(json.dumps(trial, ensure_ascii=False, indent=2), encoding='utf-8')
        step('synthetic-code-document-fixture', trial)
        before = digest_tree(work / 'state'); project_before = digest_tree(work / 'project')
        isolated_registry = work / 'local/OneCrew/hook-projects.json'
        assert not isolated_registry.exists()
        opened = cli('open', '--no-browser', '--project-only')
        assert opened.get('url') and not opened.get('reused')
        health = get('api/health')
        assert health['instance'] == opened['instance'] and health['pid'] == opened['pid'] and health['version'] == manifest['version']
        assert health['project_id'] == trial['project_id'] and health['read_only']
        again = cli('open', '--no-browser', '--project-only')
        assert again['instance'] == opened['instance'] and again['reused']
        step('installed-viewer-identity-and-reuse', {k: health[k] for k in ('instance', 'pid', 'version', 'project_id', 'state_root_id')})
        for name in trial['plans']:
            detail = get('api/task?' + urllib.parse.urlencode({'plan': name, 'timeline': 1}))
            direct = cli('show', name, '--json', '--timeline', '1')
            assert detail['work'] == direct['work'], 'CLI and live API work projection differ'
            assert detail['work']['schema_version'] == 1 and detail['read_only']
            assert detail['work']['outputs'] and detail['work']['checks']['runs']
            assert detail['work']['history_complete'] and not detail['timeline_complete']
            if name == 'CODE':
                assert detail['work']['solution']['latest_revision'] == 2
                assert detail['work']['solution']['approved_revision'] == detail['work']['solution']['effective_revision'] == 1
                assert detail['work']['repairs'][0]['status'] == 'verified'
                assert detail['work']['findings'][0]['state'] == 'resolved'
            else:
                assert detail['work']['outputs'][-1]['level'] == 'produced'
                assert detail['work']['outputs'][-1]['stale'] is False
            key = next(o['artifact'] for o in detail['work']['outputs'] if o.get('openable'))
            evidence = get('api/evidence?' + urllib.parse.urlencode({'plan': name, 'key': key}))
            assert evidence['key'] == key and evidence['read_only']
            (work / (name.lower() + '-detail.json')).write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding='utf-8')
            step('live-read-only-work-' + name, {'outputs': len(detail['work']['outputs']), 'runs': len(detail['work']['checks']['runs']),
                                               'evidence_key': key})
        timings = []
        for index in range(10):
            name = trial['plans'][index % len(trial['plans'])]
            started = time.perf_counter()
            value = get('api/task?' + urllib.parse.urlencode({'plan': name}))
            elapsed = time.perf_counter() - started
            assert value['work']['schema_version'] == 1
            timings.append({'plan': name, 'seconds': round(elapsed, 6)})
        report['detail_latency'] = {'fixture': 'small CODE/DOC synthetic state only', 'reads': timings,
            'p50_seconds': statistics.median(v['seconds'] for v in timings), 'max_seconds': max(v['seconds'] for v in timings),
            'threshold_each_seconds': 2.0}
        assert report['detail_latency']['max_seconds'] <= 2.0, 'Small-fixture detail exceeded agreed 2s threshold'
        step('small-fixture-detail-latency', report['detail_latency'])
        assert digest_tree(work / 'state') == before, 'Viewer/CLI changed fixture state bytes'
        assert digest_tree(work / 'project') == project_before, 'Viewer/CLI changed fixture project bytes'
        assert not isolated_registry.exists(), 'Trial mutated its registry'
        step('state-project-registry-unchanged', {'state_files': len(before), 'project_files': len(project_before)})
        report['result'] = 'pass'
    except Exception as error:
        report['error'] = str(error)
    finally:
        if opened:
            try:
                stopped = cli('stop', '--url', opened['url'], '--instance', opened['instance'], '--pid', str(opened['pid']),
                              '--started-at', opened['started_at'])
                assert stopped['stopped'] and stopped['instance'] == opened['instance'] and stopped['pid'] == opened['pid']
                step('identity-based-stop', stopped)
            except Exception as error:
                report['stop_error'] = str(error); report['result'] = 'fail'
        registry_after = sha(original_registry) if original_registry.is_file() else None
        report['real_registry'] = {'requested_path': str(original_registry), 'resolved_path': str(original_registry.resolve()),
                                   'interpreter': sys.executable, 'before': registry_before, 'after': registry_after}
        if registry_after != registry_before: report['result'] = 'fail'; report['isolation_error'] = 'Real registry changed'
        if digest_tree(package) != package_before: report['result'] = 'fail'; report['package_error'] = 'Package changed'
        (work / 'verify-report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'result': report['result'], 'steps': len(report['steps']), 'report': str(work / 'verify-report.json')}, ensure_ascii=False))
    return 0 if report['result'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(check(sys.argv[1], sys.argv[2]))
