"""verify_milestone.py <package dir> <work dir> - check a OneCrew 2.3 milestone package FROM THE ARTIFACT (stdlib only; run it with
`python -I` from anywhere: it never imports the checkout). Steps, each recorded in <work>/verify-report.json:
  V1 identity     every SHA256SUMS line matches, no file missing or extra; manifest names the shipped wheel and its sha256
  V2 install      fresh venv under a path with spaces; pip install --no-index the wheel and the fake claude test double
  V3 origins      the wiki/knowledge/executor modules load from the venv (not from any checkout); `onecrew --help` lists `wiki`
  V4 first task   examples/first-task: a project with a wiki rule, plan approved in this temporary ledger, engine step through the
                  real NativeExecutor -> ClaudeArtifact -> Supervisor -> fake claude process, the node's real command check passes,
                  the receipt seals the delivered package (the rule is in it), the wiki page is unchanged
  V5 counter      (a) the rule's source outside the node's read scope -> not delivered and not named; (b) the rule's source changed
                  -> delivered as a lead (recheck), not a fact; (c) a mandatory rule over the cap -> the step stops before any provider
                  process (fake log empty) and the attempt is recorded not-started
  V6 console      the installed onecrew.exe under PYTHONIOENCODING=cp1252, PYTHONUTF8=0: --help exit 0; `wiki pages` prints Vietnamese
  V7 rollback     the previous wheel (2.2) installed over the ledger written in V4: `plan show` and `engine state` work, `compat scan`
                  has no READ block, and its continue blocks are the same as on a control ledger the 2.2 install writes itself for
                  the same flow (compat scan judges a return to the binary BEFORE 2.2; an engine root with an active plan is a B1
                  continue block there whatever wrote it); then 2.3 again: `wiki show` works on the same project/ledger
Exit 0 when every step passes, 1 otherwise. The fake claude is a test double (no model): V4/V5 prove the plumbing, not model use."""
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

AI_MARKERS = ('CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'ONECREW_ACTOR', 'PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONUTF8', 'PYTHONIOENCODING')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def env_for(work, venv_scripts, **extra):
    env = {k: v for k, v in os.environ.items() if k.upper() not in AI_MARKERS}
    local, roaming = work / 'localappdata', work / 'appdata'
    local.mkdir(exist_ok=True); roaming.mkdir(exist_ok=True)
    env.update(PATH=str(venv_scripts) + os.pathsep + env.get('PATH', ''), LOCALAPPDATA=str(local), APPDATA=str(roaming))
    env.update(extra)
    return env


def fake_wheel(source, into):
    info = 'onecrew_fake_claude-0.1.dist-info'
    files = {'onecrew_fake_claude.py': Path(source).read_bytes(),
             f'{info}/METADATA': b'Metadata-Version: 2.1\nName: onecrew-fake-claude\nVersion: 0.1\n',
             f'{info}/WHEEL': b'Wheel-Version: 1.0\nGenerator: verify_milestone\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
             f'{info}/entry_points.txt': b'[console_scripts]\nclaude = onecrew_fake_claude:main\n'}
    lines = [f'{n},sha256={base64.urlsafe_b64encode(hashlib.sha256(d).digest()).decode().rstrip("=")},{len(d)}' for n, d in files.items()]
    files[f'{info}/RECORD'] = ('\n'.join(lines + [f'{info}/RECORD,,']) + '\n').encode()
    path = Path(into) / 'onecrew_fake_claude-0.1-py3-none-any.whl'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items(): archive.writestr(name, data)
    return path


def run(argv, **kw):
    return subprocess.run([str(a) for a in argv], capture_output=True, **kw)


def main(pkg, work):
    pkg, work = Path(pkg).resolve(), Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    os.chdir(work)               # every child starts in the neutral work folder: a checkout or egg-info in the caller's folder never answers
    steps = []
    report = {'kind': 'v23-milestone-verify-report', 'package': str(pkg), 'started': time.strftime('%Y-%m-%dT%H:%M:%S'), 'steps': steps}
    def step(sid, ok, **facts):
        steps.append(dict(id=sid, result='pass' if ok else 'fail', **facts)); print(sid, 'pass' if ok else 'FAIL', flush=True)
        return ok
    manifest = json.loads((pkg / 'manifest.json').read_text(encoding='utf-8'))
    report['manifest'] = {k: manifest.get(k) for k in ('milestone', 'version', 'code_commit', 'wheel', 'previous_wheel', 'claims')}
    # V1
    listed, problems = {}, []
    for line in (pkg / 'SHA256SUMS').read_text(encoding='utf-8').splitlines():
        digest, name = line.split('  ', 1); listed[name] = digest
    present = {p.relative_to(pkg).as_posix() for p in pkg.rglob('*') if p.is_file() and p.name != 'SHA256SUMS'}
    problems += [f'missing {n}' for n in sorted(set(listed) - present)] + [f'not listed {n}' for n in sorted(present - set(listed))]
    problems += [f'hash {n}' for n in sorted(set(listed) & present) if sha256(pkg / n) != listed[n]]
    wheel = pkg / 'wheel' / manifest['wheel']['name']
    previous = pkg / 'wheel' / 'previous' / manifest['previous_wheel']['name']
    if sha256(wheel) != manifest['wheel']['sha256']: problems.append('wheel sha differs from manifest')
    if sha256(previous) != manifest['previous_wheel']['sha256']: problems.append('previous wheel sha differs from manifest')
    if not step('V1-identity', not problems, files=len(listed), problems=problems): return finish(report, work)
    # V2
    venv = work / 'venv with space'
    if venv.exists(): shutil.rmtree(venv)
    run([sys.executable, '-m', 'venv', venv], check=True)
    py, scripts = venv / 'Scripts' / 'python.exe', venv / 'Scripts'
    a = run([py, '-I', '-m', 'pip', 'install', '--no-index', '--no-build-isolation', wheel])
    b = run([py, '-I', '-m', 'pip', 'install', '--no-index', '--no-build-isolation', fake_wheel(pkg / 'verify' / 'onecrew_fake_claude.py', work)])
    version = run([py, '-I', '-c', 'import importlib.metadata as m; print(m.version("onecrew"))'], text=True, cwd=work).stdout.strip()   # -I + neutral cwd: an egg-info in the caller's folder must not answer
    if not step('V2-install', a.returncode == 0 and b.returncode == 0 and version == manifest['version'], version=version,
                pip_tail=(a.stdout + a.stderr)[-300:].decode('utf-8', 'replace')): return finish(report, work)
    # V3
    names = ['onecrew.v2.knowledge', 'onecrew.v2.wiki', 'onecrew.v2.context', 'onecrew.common_executor', 'onecrew.artifact_provider_core', 'onecrew.paging']
    names = [n for n in names if n != 'onecrew.paging' or manifest.get('ships_paging')]
    code = 'import importlib, json; print(json.dumps({n: importlib.import_module(n).__file__ for n in ' + repr(names) + '}))'
    origins = json.loads(run([py, '-I', '-c', code], text=True, cwd=work, env=env_for(work, scripts)).stdout)
    outside = {n: f for n, f in origins.items() if not str(f).casefold().startswith(str(venv).casefold())}
    helped = run([scripts / 'onecrew.exe', '--help'], cwd=work, env=env_for(work, scripts))
    step('V3-origins', not outside and helped.returncode == 0 and b'wiki' in helped.stdout, origins=origins, outside=outside)
    # V4 / V5
    scenario = pkg / 'verify' / 'scenario_a1.py'
    results = {}
    for case in ('first', 'outside_scope', 'stale_source', 'mandatory_over_cap'):
        case_work = work / f'case {case}'
        if case_work.exists(): shutil.rmtree(case_work)
        case_work.mkdir()
        done = run([py, '-I', scenario, case, case_work], text=True, encoding='utf-8', errors='replace', cwd=case_work, env=env_for(case_work, scripts))
        try:
            results[case] = json.loads((case_work / 'result.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            results[case] = {'error': (done.stdout + done.stderr)[-600:]}
    first = results['first']
    step('V4-first-task', first.get('verdict') == 'pass' and 'a-value' in first.get('delivered', []) and first.get('fake_runs') == 1
         and first.get('page_unchanged') is True and first.get('use_violations') == [], **first)
    outside_ok = results['outside_scope'].get('delivered') == [] and 'PRIVATE' not in json.dumps(results['outside_scope'].get('package_text', ''))
    stale_ok = results['stale_source'].get('uses') == [['a-value', 'lead', 'recheck']]
    cap_ok = results['mandatory_over_cap'].get('state') == 'refused_before_model' and results['mandatory_over_cap'].get('fake_runs') == 0
    step('V5-counter', outside_ok and stale_ok and cap_ok, outside_scope=results['outside_scope'], stale_source=results['stale_source'],
         mandatory_over_cap=results['mandatory_over_cap'])
    # V6
    cp = env_for(work, scripts, PYTHONIOENCODING='cp1252', PYTHONUTF8='0', ONECREW_LANG='vi')
    h = run([scripts / 'onecrew.exe', '--help'], cwd=work, env=cp)
    project = Path(first.get('project', work))
    pages = run([scripts / 'onecrew.exe', '--project', project, '--state-root', first.get('state', work / 'none'), 'wiki', 'pages'], cwd=work, env=cp)
    try:
        title = json.loads(pages.stdout.decode('utf-8'))['pages'][0]['entries'][0]['title']
    except (ValueError, KeyError, IndexError):
        title = None
    step('V6-console-cp1252', h.returncode == 0 and pages.returncode == 0 and title == 'Giá trị của a.txt', help_exit=h.returncode, pages_exit=pages.returncode, title=title)
    # V7
    state = first.get('state')
    down = run([py, '-I', '-m', 'pip', 'install', '--no-index', '--no-build-isolation', '--force-reinstall', previous])
    old_version = run([py, '-I', '-c', 'import importlib.metadata as m; print(m.version("onecrew"))'], text=True, cwd=work).stdout.strip()
    old_env = env_for(work, scripts, PYTHONUTF8='1')
    def scan(project_dir, state_dir):
        done = run([scripts / 'onecrew.exe', '--project', project_dir, '--state-root', state_dir, 'compat', 'scan', '--json'], cwd=work, env=old_env)
        try:
            value = json.loads(done.stdout.decode('utf-8'))
            return value['blocking'], sorted({b['id'] for r in value.get('roots', []) for b in r.get('blocks', []) if b.get('type') == 'continue'})
        except (ValueError, KeyError, TypeError):
            return None, (done.stdout + done.stderr)[-300:].decode('utf-8', 'replace')
    blocking, continue_ids = scan(project, state)
    show = run([scripts / 'onecrew.exe', '--project', project, '--state-root', state, 'plan', 'show', 'P1'], cwd=work, env=old_env)
    engine_state = run([scripts / 'onecrew.exe', '--project', project, '--state-root', state, 'engine', 'state', 'P1'], cwd=work, env=old_env)
    control_work = work / 'case control22'
    if control_work.exists(): shutil.rmtree(control_work)
    control_work.mkdir()
    run([py, '-I', scenario, 'control22', control_work], cwd=control_work, env=env_for(control_work, scripts, PYTHONUTF8='1'))
    try:
        control = json.loads((control_work / 'result.json').read_text(encoding='utf-8'))
        control_blocking, control_ids = scan(control['project'], control['state'])
    except (OSError, ValueError, KeyError):
        control, control_blocking, control_ids = None, None, None
    up = run([py, '-I', '-m', 'pip', 'install', '--no-index', '--no-build-isolation', '--force-reinstall', wheel])
    again = run([scripts / 'onecrew.exe', '--project', project, '--state-root', state, 'wiki', 'show', '--plan', 'P1', '--node', 'C'], cwd=work, env=env_for(work, scripts))
    ok = (down.returncode == 0 and old_version == manifest['previous_wheel']['version'] and show.returncode == 0 and engine_state.returncode == 0
          and isinstance(blocking, dict) and blocking.get('read') == 0 and control is not None and control.get('step_state') == 'produced'
          and isinstance(control_blocking, dict) and control_ids == continue_ids and up.returncode == 0 and again.returncode == 0 and b'a-value' in again.stdout)
    step('V7-rollback', ok, previous_version=old_version, compat_blocking=blocking, continue_blocks=continue_ids,
         control_compat_blocking=control_blocking, control_continue_blocks=control_ids, control_state=(control or {}).get('step_state'), control_reason=(control or {}).get('reason'),
         plan_show_exit=show.returncode, engine_state_exit=engine_state.returncode, forward_exit=again.returncode,
         show_tail=(show.stdout + show.stderr)[-200:].decode('utf-8', 'replace'))
    return finish(report, work)


def finish(report, work):
    report['finished'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    report['result'] = 'pass' if report['steps'] and all(s['result'] == 'pass' for s in report['steps']) and len(report['steps']) == 7 else 'fail'
    (work / 'verify-report.json').write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding='utf-8')
    print('RESULT', report['result'], f'{sum(s["result"] == "pass" for s in report["steps"])}/7')
    return 0 if report['result'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2]))
