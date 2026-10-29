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
  V8 two roots    (A2, FINAL) verify/scenario_a2.py in two separate interpreters: root A publishes what its passing check proved while
                  open, then ends (fixture owner acceptance); a NEW root B in a NEW process receives exactly that entry as a fact and passes;
                  a root that cannot read the source does not receive it; a write on the ended root is refused; A's budget is unchanged
  V9 takeover     (B, FINAL) verify/scenario_b.py: an installed `engine step` controller really dies while its worker (with a
                  grandchild) runs; the installed `onecrew executor recover` confirms cleanup (no candidate, no replay); the next step
                  holds the node with cleanup confirmed, replays once (generation 1), budget not reset (2 calls used), 2 launches in all
  V10 mandatory   (FINAL) verify/scenario_codex.py, Codex review P2-02, through the real dispatch path: 2 000 pages sorting before the page
                  of a mandatory rule -> the rule is delivered as mandatory and the node runs; the page of the rule not UTF-8 -> the
                  step stops before any provider process (fake log empty, attempt not started); control: pages that cannot be read but
                  declare nothing mandatory -> the node runs, the record says the wiki was not read whole
  V11 continue    (FINAL) verify/scenario_codex.py, Codex review P2-01, installed CLI: `onecrew continue --json` and `context retrieve`
                  show a verified decision as verified, then `stale` with the reason once its pinned a.txt changes; a root note
                  superseded by a newer one is gone from the pack and `superseded` in `wiki history`; the newer note stays verified;
                  another root's note never appears
  V12 general     (FINAL) verify/scenario_codex.py, Codex review of 2.3.0.dev3 P2, installed CLI: a shared (general) record whose
                  condition is false here or cannot be checked is `stale` with the reason (original label kept) in every
                  `context retrieve` form that returns the general scope (no --plan / --plan, scope general / both), and left out
                  (false) or a lead (unknown) by `wiki show --plan`; controls: one whose condition holds stays verified, a withdrawn one
                  never comes back and is `withdrawn` in `wiki history`, one superseded by a project record that cites a file never
                  comes back (no --plan included) and is `superseded`, a project record whose condition is false stays stale, a 2.2
                  shared note keeps its 2.2 label
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
    if manifest['milestone'] in ('A2', 'FINAL'):
        two = work / 'two roots'
        if two.exists(): shutil.rmtree(two)
        (two / 'A').mkdir(parents=True); (two / 'B').mkdir()
        project, state2 = two / 'project', two / 'state'
        side = {}
        for name in ('A', 'B'):
            run([py, '-I', pkg / 'verify' / 'scenario_a2.py', name, two / name, project, state2], cwd=two / name, env=env_for(two / name, scripts))
            try:
                side[name] = json.loads((two / name / 'result.json').read_text(encoding='utf-8'))
            except (OSError, ValueError):
                side[name] = None
        a, b = side['A'] or {}, side['B'] or {}
        published = (a.get('published') or [{}])[0]
        ok = (a.get('steps') == ['produced', 'pass', 'produced', 'pass'] and len(a.get('published') or []) == 1
              and (published.get('label'), published.get('visibility')) == ('verified', 'project')
              and published.get('evidence', {}).get('cause') == 'not_established' and a.get('status_while_published') == 'approved'
              and a.get('final_status') == 'accepted' and b and b.get('pid') != a.get('pid')
              and b['b']['verdict'] == 'pass' and [published.get('id'), 'fact', 'verified'] in b['b']['delivered'] and b['b']['used'] == [published.get('id')]
              and b['narrow']['verdict'] == 'fail' and published.get('id') not in json.dumps(b['narrow']['delivered'])
              and b['narrow']['omitted'].get('source_outside_read_scope', 0) >= 1 and str(b.get('late_write_on_a', '')).startswith('refused')
              and b.get('a_status') == 'accepted' and b.get('a_budget') == a.get('budget'))
        step('V8-two-roots', ok, root_a=a, root_b=b)
    if manifest['milestone'] in ('B', 'FINAL'):
        bwork = work / 'takeover case'
        if bwork.exists(): shutil.rmtree(bwork)
        bwork.mkdir()
        done = run([py, '-I', pkg / 'verify' / 'scenario_b.py', bwork], cwd=bwork, env=env_for(bwork, scripts))
        try:
            b = json.loads((bwork / 'result.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            b = {'error': (done.stdout + done.stderr)[-600:].decode('utf-8', 'replace')}
        ok = (b.get('child_exit') == 41 and b.get('phase_after_crash') == 'running' and b.get('attempt_after_crash') == 'running'
              and b.get('recover_exit') == 0 and b.get('recover_cleanup') == 'confirmed' and b.get('recover_candidate') is None
              and b.get('recover_state') == 'unknown' and b.get('settled_status') == 'settled' and b.get('settled_reason') == 'supervisor_interrupted'
              and b.get('launches_before_takeover') == 1 and b.get('takeover_state') == 'produced' and b.get('generation') == 1
              and b.get('launches_total') == 2 and b.get('held') == [[b.get('first_attempt'), 'confirmed', 'executor_interrupted']]
              and b.get('resumed') == [[b.get('first_attempt'), False]] and b.get('used_calls') == 2)
        step('V9-takeover', ok, **b)
    if manifest['milestone'] == 'FINAL':
        codex = {}
        for case in ('beyond_pages', 'undeliverable', 'optional_broken', 'continue', 'general'):
            case_work = work / f'codex {case}'
            if case_work.exists(): shutil.rmtree(case_work)
            case_work.mkdir()
            done = run([py, '-I', pkg / 'verify' / 'scenario_codex.py', case, case_work], text=True, encoding='utf-8', errors='replace',
                       cwd=case_work, env=env_for(case_work, scripts))
            try:
                codex[case] = json.loads((case_work / 'result.json').read_text(encoding='utf-8'))
            except (OSError, ValueError):
                codex[case] = {'error': (done.stdout + done.stderr)[-600:]}
        beyond, broken, control = codex['beyond_pages'], codex['undeliverable'], codex['optional_broken']
        ok = (beyond.get('state') == 'produced' and beyond.get('mandatory') == ['a-value'] and beyond.get('fake_runs') == 1
              and broken.get('state') == 'held' and broken.get('reason', '').startswith('Mandatory knowledge cannot be established')
              and broken.get('fake_runs') == 0 and 'native_preflight' in json.dumps(broken.get('attempts'))
              and control.get('state') == 'produced' and control.get('mandatory') == ['a-value'] and control.get('fake_runs') == 1
              and (control.get('wiki') or {}).get('complete') is False and (control.get('wiki') or {}).get('unreadable') == 1)
        step('V10-mandatory', ok, beyond_pages=beyond, undeliverable=broken, optional_broken=control)
        c = codex['continue']
        before, after, history = c.get('before') or {}, c.get('after') or {}, c.get('history') or {}
        ok = (all((c.get('recorded') or {}).values()) and c.get('before_exit') == 0 and c.get('after_exit') == 0
              and before.get('Use the old a.txt convention', [None])[0] == 'verified' and after.get('Use the old a.txt convention', [None])[0] == 'stale'
              and 'a.txt' in str(after.get('Use the old a.txt convention', [None, ''])[1])
              and (c.get('retrieve_before') or {}).get('Use the old a.txt convention') == 'verified'
              and (c.get('retrieve_after') or {}).get('Use the old a.txt convention') == 'stale'
              and after.get('New private rule', [None])[0] == 'verified' and 'Old private rule' not in after and 'Old private rule' not in before
              and history.get('Old private rule') == 'superseded' and history.get('New private rule') == 'active'
              and 'P2 private working note' not in after and 'P2 private working note' not in before)
        step('V11-continue', ok, **c)
        problems = general_problems(codex['general'])
        step('V12-general', not problems, problems=problems, **codex['general'])
    return finish(report, work)


def general_problems(g):
    """What the installed CLI got wrong in scenario_codex.py `general` (Codex review of 2.3.0.dev3, P2); [] when nothing."""
    problems = []
    if not (g.get('recorded') and all(g['recorded'].values())) or any(g.get(k) != 0 for k in ('withdraw_exit', 'project_exit', 'legacy_exit', 'replaced_exit')):
        problems.append('recording failed: ' + str({k: g.get(k) for k in ('recorded', 'withdraw_exit', 'project_exit', 'legacy_exit', 'replaced_exit', 'error')})[:300])
    retrieved = g.get('retrieve') or {}
    for form in ('general', 'both', 'plan general', 'plan both'):
        rows = retrieved.get(form) or {}
        false, unknown, true = rows.get('Retry rule for elsewhere'), rows.get('Retry rule for a model'), rows.get('Retry rule here')
        if not (false and false[0] == 'stale' and str(false[1]).startswith('not applicable now') and false[2] == 'verified'):
            problems.append(f'{form}: a general record whose condition is false here is shown as {false}')
        if not (unknown and unknown[0] == 'stale' and str(unknown[1]).startswith('cannot be checked now') and unknown[2] == 'verified'):
            problems.append(f'{form}: a general record whose condition cannot be checked is shown as {unknown}')
        if not (true and true[0] == 'verified' and true[1] is None):
            problems.append(f'{form}: control, a general record whose condition holds is shown as {true}')
        if 'Withdrawn retry rule' in rows: problems.append(f'{form}: a withdrawn general record came back')
        if 'Replaced retry rule' in rows: problems.append(f'{form}: a superseded general record came back as {rows["Replaced retry rule"]}')
        if (rows.get('2.2 shared note') or [None, 'missing'])[:2] != ['observed', None]:
            problems.append(f'{form}: control, the 2.2 shared note is shown as {rows.get("2.2 shared note")}')
    for form in ('both', 'plan both', 'plan project'):
        project = (retrieved.get(form) or {}).get('Project rule for elsewhere')
        if not (project and project[0] == 'stale' and str(project[1]).startswith('not applicable now')):
            problems.append(f'{form}: control, a project record whose condition is false is shown as {project}')
    if g.get('wiki') != {'false': 'not delivered', 'true': 'fact', 'unknown': 'lead', 'withdrawn': 'not delivered'}:
        problems.append(f'wiki show: {g.get("wiki")}')
    if (g.get('wiki_left_out') or {}).get('not_applicable', 0) < 2: problems.append(f'wiki show left out: {g.get("wiki_left_out")}')
    history = g.get('history') or {}
    if (history.get('Withdrawn retry rule') != ['withdrawn', 'verified'] or history.get('Retry rule for elsewhere') != ['active', 'verified']
            or history.get('Replaced retry rule') != ['superseded', 'verified']):
        problems.append(f'wiki history: {history.get("Withdrawn retry rule")}, {history.get("Retry rule for elsewhere")}, {history.get("Replaced retry rule")}')
    return problems


EXPECTED = {'A1': 7, 'A2': 8, 'B': 8, 'FINAL': 12}


def finish(report, work):
    report['finished'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    expected = EXPECTED.get((report.get('manifest') or {}).get('milestone'), 7)
    report['expected_steps'] = expected
    report['result'] = 'pass' if report['steps'] and all(s['result'] == 'pass' for s in report['steps']) and len(report['steps']) == expected else 'fail'
    (work / 'verify-report.json').write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding='utf-8')
    print('RESULT', report['result'], f'{sum(s["result"] == "pass" for s in report["steps"])}/{expected}')
    return 0 if report['result'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2]))
