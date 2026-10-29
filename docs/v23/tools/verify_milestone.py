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
  V13 collision   (FINAL) verify/scenario_codex.py, Codex review of 2.3.0.dev5 P2-B, installed CLI: a second project of the same state
                  root reuses `--key retry-policy` for a general record. Each project's own record is `ctx-retry-policy` to itself and
                  the other's is `ctx-retry-policy@<12 hex>`; both are listed, ours verified; the other project's withdrawal of its own
                  record removes only that one; withdrawing the other project's record is refused; withdrawing our own works and
                  removes only ours, for both projects
  V14 docverify   (FINAL) verify/scenario_codex.py, Codex review of 2.3.0.dev5 P2-C/P2-D, the installed doc verifier: a `.env.example`
                  at the root changes nothing (never read, its text never in the report); `[S1][S2]` are two citations; controls: the
                  plain sample passes, a real undefined reference link next to them fails (exactly that one), a link to a missing
                  `.env-sample` is a broken link, and reading `.env.example` is refused with its real reason (a credential path)
Exit 0 when every step passes, 1 otherwise. The fake claude is a test double (no model): V4/V5 prove the plumbing, not model use."""
import base64
import re
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
        for case in ('beyond_pages', 'undeliverable', 'optional_broken', 'continue', 'general', 'collision', 'docverify'):
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
        problems = collision_problems(codex['collision'])
        step('V13-collision', not problems, problems=problems, **codex['collision'])
        problems = docverify_problems(codex['docverify'])
        step('V14-docverify', not problems, problems=problems, **codex['docverify'])
        try:
            facts = init_wiki_cases(work, scripts, previous)
            problems = initwiki_problems(facts)
        except Exception as error:                     # an environment failure (git, venv) is a failed step, never a crash of the verifier
            facts, problems = {'error': f'{type(error).__name__}: {str(error)[:300]}'}, ['V15 could not run']
        step('V15-init-wiki', not problems, problems=problems, **facts)
        try:
            facts = old_work_cases(work, previous, wheel, pkg)
            problems = oldwork_problems(facts, manifest)
        except Exception as error:                     # an environment failure (git, venv) is a failed step, never a crash of the verifier
            facts, problems = {'error': f'{type(error).__name__}: {str(error)[:300]}'}, ['V16 could not run']
        step('V16-old-work', not problems, problems=problems, **facts)
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


def collision_problems(c):
    """What the installed CLI got wrong in scenario_codex.py `collision` (Codex review of 2.3.0.dev5, P2-B); [] when nothing."""
    problems = []
    if c.get('error') or not all((c.get('recorded') or {}).get(side, {}).get('id') == 'ctx-retry-policy' for side in ('A', 'B')):
        return ['recording failed: ' + str(c.get('error') or c.get('recorded'))[:300]]
    mine, theirs = 'Valid retry rule of project one', 'Retry rule of project two'
    before = c.get('before') or {}
    qualified = {}
    for side, own, other in (('A', mine, theirs), ('B', theirs, mine)):
        history = (before.get(side) or {}).get('history') or {}
        own_id, other_id = (history.get(own) or [None])[0], (history.get(other) or [None])[0]
        if own_id != 'ctx-retry-policy': problems.append(f'{side}: its own record is {own_id}, not ctx-retry-policy')
        if not (isinstance(other_id, str) and re.fullmatch(r'ctx-retry-policy@[0-9a-f]{12}', other_id)):
            problems.append(f'{side}: the other project\'s record is {other_id}, not ctx-retry-policy@<12 hex>')
        qualified[side] = other_id
        for form in ('general', 'plan general'):
            rows = (before.get(side) or {}).get(form) or {}
            if rows.get(own) != ['verified', None] or rows.get(other) != ['verified', None]:
                problems.append(f'{side} {form} before: {rows}')
    if qualified.get('A') == qualified.get('B'): problems.append(f'both projects see the same qualified id {qualified.get("A")}')
    if (c.get('B_withdraws_own') or {}).get('exit') != 0: problems.append(f'B could not withdraw its own record: {c.get("B_withdraws_own")}')
    after = c.get('after_B') or {}
    for form in ('general', 'plan general'):
        a, b = (after.get('A') or {}).get(form) or {}, (after.get('B') or {}).get(form) or {}
        if a.get(mine) != ['verified', None] or theirs in a: problems.append(f'A {form} after B withdrew its own: {a}')
        if theirs in b or b.get(mine) != ['verified', None]: problems.append(f'B {form} after B withdrew its own: {b}')
    refused = c.get('A_withdraws_theirs') or {}
    if refused.get('exit') in (0, None) or 'only the project that wrote a general entry' not in refused.get('message', ''):
        problems.append(f'withdrawing the other project\'s record was not refused: {refused}')
    if (c.get('A_withdraws_own') or {}).get('exit') != 0: problems.append(f'A could not withdraw its own record: {c.get("A_withdraws_own")}')
    final = c.get('after_A') or {}
    for side in ('A', 'B'):
        for form in ('general', 'plan general'):
            rows = (final.get(side) or {}).get(form) or {}
            if mine in rows or theirs in rows: problems.append(f'{side} {form} after both withdrawals: {rows}')
        history = (final.get(side) or {}).get('history') or {}
        if [row[1] for text, row in sorted(history.items())] != ['withdrawn', 'withdrawn']: problems.append(f'{side} history at the end: {history}')
    return problems


def docverify_problems(d):
    """What the installed doc verifier got wrong in scenario_codex.py `docverify` (Codex review of 2.3.0.dev5, P2-C/P2-D); [] when nothing."""
    problems = []
    runs = d.get('docverify') or {}
    if not str(d.get('doc_module', '')).replace('\\', '/').lower().count('site-packages/onecrew/v2/verifiers/doc.py'):
        problems.append(f'the doc verifier was not the installed one: {d.get("doc_module")}')
    clean = runs.get('control') or {}
    if clean.get('error') or clean.get('failed') != {}: problems.append(f'control: {clean}')
    env = runs.get('env-file') or {}
    if env.get('error') or env.get('failed') != {} or env.get('read_kept') or env.get('violations') or env.get('secret_in_report'):
        problems.append(f'.env.example at the root: {env}')
    if not env.get('error') and env.get('unverified') != clean.get('unverified'): problems.append(f'.env.example changed the report: {env} vs {clean}')
    adjacent = runs.get('adjacent') or {}
    if adjacent.get('error') or adjacent.get('failed') != {}: problems.append(f'[S1][S2]: {adjacent}')
    missing = runs.get('missing-ref') or {}
    links = (missing.get('failed') or {}).get('links') or []
    if set(missing.get('failed') or {}) != {'links'} or len(links) != 1 or 'khong-dinh-nghia' not in links[0]:
        problems.append(f'a real undefined reference link next to [S1][S2]: {missing}')
    kept = runs.get('missing-kept-link') or {}
    links = (kept.get('failed') or {}).get('links') or []
    if len(links) != 1 or '.env-sample' not in links[0] or 'does not exist' not in links[0]: problems.append(f'a link to a missing .env-sample: {kept}')
    if not (str(d.get('read_refusal', '')).startswith('AdapterViolation') and 'control or credential' in str(d.get('read_refusal'))):
        problems.append(f'reading .env.example: {d.get("read_refusal")}')
    return problems


SKELETON_MARK = '<!-- onecrew:wiki-skeleton 1 -->'
SKELETON = ['README.md', 'lessons.md', 'project.md']


def _files(folder):
    folder = Path(folder)
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else None


def _tree(folder):
    folder = Path(folder)
    return {p.relative_to(folder).as_posix(): sha256(p) for p in sorted(folder.rglob('*')) if p.is_file()} if folder.is_dir() else {}


def init_wiki_cases(work, scripts, previous):
    """V15 facts: `onecrew init` of the installed wheel on new Git repositories in a folder with spaces, LOCALAPPDATA/APPDATA per case
    (HOP-DONG-2.3 §10.3): KW-01 a new repository, KW-02 a second init after a page was edited, KW-04 one configured folder, KW-06 an
    unreadable config.json, KW-07 a junction to a folder outside, KW-09 an interrupted skeleton, KW-13 a project set up by the previous
    (2.2) wheel. Judged by initwiki_problems."""
    base = work / 'init wiki'
    if base.exists(): shutil.rmtree(base)
    base.mkdir()
    exe = scripts / 'onecrew.exe'
    def repo(name):
        project = base / name
        project.mkdir()
        for args in (['init', '-q'], ['config', 'user.name', 'v15'], ['config', 'user.email', 'v15@localhost'], ['config', 'core.autocrlf', 'false']):
            run(['git', '-C', project, *args], check=True)
        (project / 'a.txt').write_text('base\n', encoding='utf-8')
        run(['git', '-C', project, 'add', '.'], check=True); run(['git', '-C', project, 'commit', '-qm', 'base'], check=True)
        return project
    def state(project):
        return base / ('state ' + project.name)
    def env(project):
        folder = base / ('env ' + project.name); folder.mkdir(exist_ok=True)
        return env_for(folder, scripts)
    def init(project, command=exe):
        done = run([command, 'init', '--project', project, '--state-root', state(project), '--yes'], cwd=base, env=env(project))
        return done.returncode, (done.stdout + done.stderr).decode('utf-8', 'replace')
    def pages(project):
        done = run([exe, '--project', project, '--state-root', state(project), 'wiki', 'pages'], cwd=base, env=env(project))
        try:
            value = json.loads(done.stdout.decode('utf-8'))
            return {'pages': sorted(p['path'] for p in value['pages']), 'entries': sum(len(p['entries']) for p in value['pages']), 'problems': value['problems']}
        except (ValueError, KeyError, TypeError):
            return {'error': (done.stdout + done.stderr)[-300:].decode('utf-8', 'replace')}
    facts = {}
    project = repo('new one')
    folder = project / 'docs' / 'wiki'
    code, out = init(project)
    files = _files(folder) or []
    facts['new'] = {'exit': code, 'files': files, 'marked': [n for n in files if (folder / n).read_text(encoding='utf-8').startswith(SKELETON_MARK)],
                    'plan_line': 'create the wiki skeleton in docs/wiki' in out, 'pages': pages(project), 'tail': out[-300:]}
    page = folder / 'project.md'
    if page.is_file(): page.write_text(page.read_text(encoding='utf-8') + '\n## A rule of the project\nKeep a.txt short.\n', encoding='utf-8')
    before = _tree(project / 'docs')
    code, out = init(project)
    facts['again'] = {'exit': code, 'unchanged': _tree(project / 'docs') == before, 'nothing': 'nothing to change' in out, 'pages': pages(project)}
    project = repo('configured')
    (project / '.onecrew').mkdir(); (project / '.onecrew' / 'config.json').write_text(json.dumps({'wiki': {'paths': ['kb']}}), encoding='utf-8')
    code, out = init(project)
    try:
        kept = json.loads((project / '.onecrew' / 'config.json').read_text(encoding='utf-8')).get('wiki')
    except (OSError, ValueError):
        kept = None
    facts['configured'] = {'exit': code, 'kb': _files(project / 'kb'), 'docs': (project / 'docs').exists(), 'wiki_config': kept}
    project = repo('bad config')
    (project / '.onecrew').mkdir(); config = project / '.onecrew' / 'config.json'; config.write_bytes(b'{ not json')
    code, out = init(project)
    facts['bad_config'] = {'exit': code, 'config_unchanged': config.read_bytes() == b'{ not json', 'said': 'Nothing was changed' in out,
                           'wrote': [str(p) for p in (project / '.claude', project / 'docs', state(project) / 'ledger.sqlite3') if p.exists()]}
    project = repo('junction')
    outside = base / 'outside folder'; outside.mkdir(); (project / 'docs').mkdir()
    made = run(['cmd', '/c', 'mklink', '/J', project / 'docs' / 'wiki', outside]) if os.name == 'nt' else None
    if made is None: os.symlink(outside, project / 'docs' / 'wiki')
    code, out = init(project)
    facts['junction'] = {'made': made is None or made.returncode == 0, 'exit': code, 'outside': _files(outside),
                         'ledger': (state(project) / 'ledger.sqlite3').exists()}
    project = repo('interrupted')
    folder = project / 'docs' / 'wiki'; folder.mkdir(parents=True)
    (folder / 'README.md').write_text(SKELETON_MARK + '\n# kept as it was\n', encoding='utf-8')
    kept = sha256(folder / 'README.md')
    code, out = init(project)
    facts['interrupted'] = {'exit': code, 'files': _files(folder), 'kept': sha256(folder / 'README.md') == kept}
    old = work / 'venv previous wheel'
    if old.exists(): shutil.rmtree(old)
    run([sys.executable, '-m', 'venv', old], check=True)
    installed = run([old / 'Scripts' / 'python.exe', '-I', '-m', 'pip', 'install', '--no-index', '--no-build-isolation', previous])
    old_version = run([old / 'Scripts' / 'python.exe', '-I', '-c', 'import importlib.metadata as m; print(m.version("onecrew"))'], text=True, cwd=work).stdout.strip()
    project = repo('old project')
    old_code, _ = init(project, old / 'Scripts' / 'onecrew.exe')
    config = project / '.onecrew' / 'config.json'
    value = json.loads(config.read_text(encoding='utf-8')); value['custom'] = {'kept': True}; config.write_text(json.dumps(value), encoding='utf-8')
    ledger = state(project) / 'ledger.sqlite3'
    ledger_before = sha256(ledger) if ledger.is_file() else None
    had_wiki = (project / 'docs').exists()
    code, out = init(project)
    after = json.loads(config.read_text(encoding='utf-8'))
    settings = json.loads((project / '.claude' / 'settings.local.json').read_text(encoding='utf-8'))
    commands = sorted({h.get('command') for entries in settings.get('hooks', {}).values() for e in entries for h in e.get('hooks', [])})
    facts['old_project'] = {'previous_install': installed.returncode, 'previous_version': old_version, 'old_exit': old_code, 'old_had_wiki': had_wiki,
                            'exit': code, 'ledger_unchanged': ledger_before is not None and sha256(ledger) == ledger_before,
                            'custom_kept': after.get('custom') == {'kept': True}, 'state_root_kept': after.get('state_root') == value.get('state_root'),
                            'hook_commands': commands, 'new_exe': str(exe.resolve()), 'wiki': _files(project / 'docs' / 'wiki')}
    return facts


def initwiki_problems(f):
    """What the installed `onecrew init` got wrong in V15 (WI-01..05); [] when nothing."""
    problems, done = [], (0, 1)                        # 1 = done but the Claude CLI is not logged in: init's own code for that
    new, again, conf, bad, link, part, old = (f.get(k) or {} for k in ('new', 'again', 'configured', 'bad_config', 'junction', 'interrupted', 'old_project'))
    if new.get('exit') not in done or new.get('files') != SKELETON or new.get('marked') != SKELETON or not new.get('plan_line'):
        problems.append(f'KW-01 new repository: {new}')
    if (new.get('pages') or {}) != {'pages': ['docs/wiki/' + n for n in SKELETON], 'entries': 0, 'problems': []}:
        problems.append(f'KW-01/KW-11 the empty skeleton as read: {new.get("pages")}')
    if again.get('exit') not in done or not again.get('unchanged') or not again.get('nothing') or (again.get('pages') or {}).get('entries') != 1:
        problems.append(f'KW-02 second init: {again}')
    if conf.get('exit') not in done or conf.get('kb') != SKELETON or conf.get('docs') or conf.get('wiki_config') != {'paths': ['kb']}:
        problems.append(f'KW-04 configured folder: {conf}')
    if bad.get('exit') != 2 or not bad.get('config_unchanged') or bad.get('wrote') or not bad.get('said'):
        problems.append(f'KW-06 unreadable config.json: {bad}')
    if not link.get('made') or link.get('exit') != 2 or link.get('outside') != [] or link.get('ledger'):
        problems.append(f'KW-07 junction: {link}')
    if part.get('exit') not in done or part.get('files') != SKELETON or not part.get('kept'):
        problems.append(f'KW-09 interrupted skeleton: {part}')
    if (old.get('previous_install') != 0 or old.get('old_exit') not in done or old.get('old_had_wiki') or old.get('exit') not in done
            or not old.get('ledger_unchanged') or not old.get('custom_kept') or not old.get('state_root_kept')
            or old.get('hook_commands') != [old.get('new_exe')] or old.get('wiki') != SKELETON):
        problems.append(f'KW-13 a project set up by the previous wheel: {old}')
    return problems


def _events(state):
    """[(seq, kind, sha256 of the payload)] of every event of a ledger, read-only."""
    import sqlite3
    conn = sqlite3.connect((Path(state) / 'ledger.sqlite3').as_uri() + '?mode=ro', uri=True)
    try:
        return [(r[0], r[1], hashlib.sha256((r[2] or '').encode('utf-8')).hexdigest()) for r in conn.execute('SELECT seq, kind, payload FROM events ORDER BY seq')]
    finally:
        conn.close()


def _first_json(data):
    text = data.decode('utf-8', 'replace') if isinstance(data, bytes) else data
    start = text.find('{')
    try:
        return json.loads(text[start:]) if start >= 0 else None
    except ValueError:
        try:
            return json.JSONDecoder().raw_decode(text[start:])[0]
        except ValueError:
            return None


def old_work_cases(work, previous, wheel, pkg):
    """V16 facts: OLD WORK CONTINUED. With the previous (2.2) wheel, in one venv with spaces: `onecrew init`, the first-task contract proposed and
    approved (the fixture approval of V4/V8 on the temporary ledger, not an owner approval), the nodes revised, node C stepped by the fake
    claude and verified. Then this wheel is installed over it (`pip install --force-reinstall`) and `onecrew init` runs again; node I is
    stepped and verified by this wheel. Every event the 2.2 run wrote must still be there byte for byte, and this wheel's compat scan finds
    the blocks the 2.2 scanner found on the same ledger before the upgrade, no more (they concern the archived pre-namespace baseline d3120c6)."""
    base = work / 'old work'
    if base.exists(): shutil.rmtree(base)
    base.mkdir()
    venv = base / 'venv old work'
    run([sys.executable, '-m', 'venv', venv], check=True)
    py, scripts = venv / 'Scripts' / 'python.exe', venv / 'Scripts'
    exe = scripts / 'onecrew.exe'
    installs = [run([py, '-I', '-m', 'pip', 'install', '--no-index', '--no-build-isolation', w]).returncode
                for w in (previous, fake_wheel(pkg / 'verify' / 'onecrew_fake_claude.py', base))]
    project, state = base / 'project old work', base / 'state old work'
    project.mkdir()
    for args in (['init', '-q'], ['config', 'user.name', 'v16'], ['config', 'user.email', 'v16@localhost'], ['config', 'core.autocrlf', 'false']):
        run(['git', '-C', project, *args], check=True)
    (project / 'a.txt').write_text('base\n', encoding='utf-8'); (project / '.gitignore').write_text('.onecrew/\n.claude/\n', encoding='utf-8')
    run(['git', '-C', project, 'add', '.'], check=True); run(['git', '-C', project, 'commit', '-qm', 'base'], check=True)
    policy = base / 'policy right.json'
    policy.write_text(json.dumps({'target': 'a.txt', 'default': 'right', 'careful': True}), encoding='utf-8')   # 2.2 delivers no knowledge
    log = base / 'fake.jsonl'
    env = env_for(base, scripts, ONECREW_FAKE_POLICY=str(policy), ONECREW_FAKE_LOG=str(log))
    cli = lambda *args: run([exe, '--project', project, '--state-root', state, *args], cwd=base, env=env)
    version = lambda: run([py, '-I', '-c', 'import importlib.metadata as m; print(m.version("onecrew"))'], text=True, cwd=base).stdout.strip()
    facts = {'installs_previous': installs, 'version_before': version()}
    facts['init_previous'] = run([exe, 'init', '--project', project, '--state-root', state, '--yes'], cwd=base, env=env).returncode
    contract = (pkg / 'examples' / 'first-task' / 'contract.json').read_text(encoding='utf-8').replace('PYTHON_EXE', str(py).replace(chr(92), '/'))
    (base / 'contract.json').write_text(contract, encoding='utf-8')
    facts['propose'] = cli('plan', 'propose', 'P1', '--file', base / 'contract.json', '--author', 'v16-old-work', '--workflow', '--capability',
                           'namespaced-storage', '--capability', 'root-budget', '--capability', 'internal-plan', '--capability', 'sequential-engine').returncode
    approve = ('import sys; from pathlib import Path; from onecrew.ledger import Ledger; from onecrew.v2 import plan; '
               'shown = plan.approve(Ledger(Path(sys.argv[1]), Path(sys.argv[2])), "P1", "owner", '
               '"package step V16 fixture on a temporary ledger, not an owner approval"); print(shown["status"])')
    facts['approve'] = run([py, '-I', '-c', approve, project, state], cwd=base, env=env, text=True).stdout.strip()
    facts['revise'] = cli('engine', 'revise', 'P1', '--file', pkg / 'examples' / 'first-task' / 'nodes.json').returncode
    step = _first_json(cli('engine', 'step', 'P1').stdout) or {}
    facts['step_c_previous'] = [step.get('node'), step.get('state')]
    facts['verify_c_previous'] = (_first_json(cli('engine', 'verify', 'P1', 'C').stdout) or {}).get('result')
    facts['compat_previous'] = (_first_json(cli('compat', 'scan', '--json').stdout) or {}).get('blocking')     # the 2.2 scanner on its own ledger
    before = _events(state)
    facts['upgrade'] = run([py, '-I', '-m', 'pip', 'install', '--no-index', '--no-build-isolation', '--force-reinstall', wheel]).returncode
    facts['version_after'] = version()
    facts['init_this'] = run([exe, 'init', '--project', project, '--state-root', state, '--yes'], cwd=base, env=env).returncode
    facts['wiki'] = _files(project / 'docs' / 'wiki')
    scan = _first_json(cli('compat', 'scan', '--json').stdout) or {}
    facts['compat_blocking'] = scan.get('blocking')
    step = _first_json(cli('engine', 'step', 'P1').stdout) or {}
    facts['step_i_this'] = [step.get('node'), step.get('state')]
    facts['verify_i_this'] = (_first_json(cli('engine', 'verify', 'P1', 'I').stdout) or {}).get('result')
    shown = cli('engine', 'state', 'P1').stdout.decode('utf-8', 'replace')
    facts['state_counts'] = {'verified': shown.count('"verified"'), 'pass': shown.count('"pass"')}
    after = _events(state)
    facts['events_previous'] = len(before)
    facts['previous_events_kept'] = after[:len(before)] == before
    facts['events_added'] = len(after) - len(before)
    try:
        facts['fake_nodes'] = [json.loads(line)['node'] for line in log.read_text(encoding='utf-8').splitlines()]
    except (OSError, ValueError, KeyError):
        facts['fake_nodes'] = None
    return facts


def oldwork_problems(f, manifest):
    """What went wrong in V16; [] when nothing."""
    problems, done = [], (0, 1)
    if f.get('installs_previous') != [0, 0] or f.get('version_before') != manifest['previous_wheel']['version'] or f.get('init_previous') not in done:
        problems.append(f'the previous wheel did not set the project up: {[f.get(k) for k in ("installs_previous", "version_before", "init_previous")]}')
    if (f.get('propose'), f.get('approve'), f.get('revise'), f.get('step_c_previous'), f.get('verify_c_previous')) != (0, 'approved', 0, ['C', 'produced'], 'pass'):
        problems.append(f'the 2.2 half of the work: {[f.get(k) for k in ("propose", "approve", "revise", "step_c_previous", "verify_c_previous")]}')
    if f.get('upgrade') != 0 or f.get('version_after') != manifest['version'] or f.get('init_this') not in done or f.get('wiki') != SKELETON:
        problems.append(f'the upgrade: {[f.get(k) for k in ("upgrade", "version_after", "init_this", "wiki")]}')
    blocking = f.get('compat_blocking')
    if not isinstance(blocking, dict) or blocking != f.get('compat_previous') or blocking.get('read'):
        problems.append(f'compat scan after the upgrade {blocking} differs from the 2.2 scan before it {f.get("compat_previous")} or blocks reading')
    if (f.get('step_i_this'), f.get('verify_i_this')) != (['I', 'produced'], 'pass'): problems.append(f'node I with this wheel: {[f.get("step_i_this"), f.get("verify_i_this")]}')
    counts = f.get('state_counts') or {}
    if counts.get('verified', 0) < 2 or counts.get('pass', 0) < 2: problems.append(f'engine state after: {counts}')
    if not f.get('previous_events_kept') or not f.get('events_added'): problems.append(f'the 2.2 events: kept {f.get("previous_events_kept")}, added {f.get("events_added")}')
    if f.get('fake_nodes') != ['C', 'I']: problems.append(f'worker runs: {f.get("fake_nodes")}')
    return problems


EXPECTED = {'A1': 7, 'A2': 8, 'B': 8, 'FINAL': 16}


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
