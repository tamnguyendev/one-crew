"""verify_milestone.py <package dir> <work dir> - check a OneCrew 2.4 milestone package FROM THE ARTIFACT (stdlib only; run it with
`python -I` from anywhere: it never imports the checkout). Every step is recorded in <work>/verify-report.json with pass/fail, seconds and facts.
The report names the manifest's `milestones_included`, the expected step count, and the steps SKIPPED because their milestone is not in the package.

V1-V16 are the 2.3 verifier, kept as the regression of every 2.4 package (2.3's V8-V16 ran only for FINAL; here they always run):
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
  V7 rollback     the REGRESSION wheel (2.2, wheel/regression/; the 2.3.0.dev10 wheel in wheel/previous/ is checked for identity only) installed over the ledger written in V4: `plan show` and `engine state` work, `compat scan`
                  has no READ block, and its continue blocks are the same as on a control ledger the 2.2 install writes itself for
                  the same flow (compat scan judges a return to the binary BEFORE 2.2; an engine root with an active plan is a B1
                  continue block there whatever wrote it); then 2.3 again: `wiki show` works on the same project/ledger
  V8 two roots    verify/scenario_a2.py in two separate interpreters: root A publishes what its passing check proved while
                  open, then ends (fixture owner acceptance); a NEW root B in a NEW process receives exactly that entry as a fact and passes;
                  a root that cannot read the source does not receive it; a write on the ended root is refused; A's budget is unchanged
  V9 takeover     verify/scenario_b.py: an installed `engine step` controller really dies while its worker (with a
                  grandchild) runs; the installed `onecrew executor recover` confirms cleanup (no candidate, no replay); the next step
                  holds the node with cleanup confirmed, replays once (generation 1), budget not reset (2 calls used), 2 launches in all
  V10 mandatory   verify/scenario_codex.py, Codex review P2-02, through the real dispatch path: 2 000 pages sorting before the page
                  of a mandatory rule -> the rule is delivered as mandatory and the node runs; the page of the rule not UTF-8 -> the
                  step stops before any provider process (fake log empty, attempt not started); control: pages that cannot be read but
                  declare nothing mandatory -> the node runs, the record says the wiki was not read whole
  V11 continue    verify/scenario_codex.py, Codex review P2-01, installed CLI: `onecrew continue --json` and `context retrieve`
                  show a verified decision as verified, then `stale` with the reason once its pinned a.txt changes; a root note
                  superseded by a newer one is gone from the pack and `superseded` in `wiki history`; the newer note stays verified;
                  another root's note never appears
  V12 general     verify/scenario_codex.py, Codex review of 2.3.0.dev3 P2, installed CLI: a shared (general) record whose
                  condition is false here or cannot be checked is `stale` with the reason (original label kept) in every
                  `context retrieve` form that returns the general scope (no --plan / --plan, scope general / both), and left out
                  (false) or a lead (unknown) by `wiki show --plan`; controls: one whose condition holds stays verified, a withdrawn one
                  never comes back and is `withdrawn` in `wiki history`, one superseded by a project record that cites a file never
                  comes back (no --plan included) and is `superseded`, a project record whose condition is false stays stale, a 2.2
                  shared note keeps its 2.2 label
  V13 collision   verify/scenario_codex.py, Codex review of 2.3.0.dev5 P2-B, installed CLI: a second project of the same state
                  root reuses `--key retry-policy` for a general record. Each project's own record is `ctx-retry-policy` to itself and
                  the other's is `ctx-retry-policy@<12 hex>`; both are listed, ours verified; the other project's withdrawal of its own
                  record removes only that one; withdrawing the other project's record is refused; withdrawing our own works and
                  removes only ours, for both projects
  V14 docverify   verify/scenario_codex.py, Codex review of 2.3.0.dev5 P2-C/P2-D, the installed doc verifier: a `.env.example`
                  at the root changes nothing (never read, its text never in the report); `[S1][S2]` are two citations; controls: the
                  plain sample passes, a real undefined reference link next to them fails (exactly that one), a link to a missing
                  `.env-sample` is a broken link, and reading `.env.example` is refused with its real reason (a credential path)
2.4 steps, run ONLY when the manifest's milestones_included contains the milestone (table MILESTONE_STEPS below; add a milestone = one entry), each from
the installed venv with python -I, a cwd outside the checkout, an isolated env and the fake claude on PATH:
  V17 S1 report   a healthy temporary ledger: `support report --text .. --key k1 --json` returns an FB id; the same key again returns the same id and the
                  ledger holds exactly one support.feedback (other content under the key is refused); `support bundle FB --out DIR` writes manifest.json whose
                  sources all have a status of the allowed set and whose runner/host logs are not_applicable; `support show --json` says reported true and
                  reproduced unknown; the report wrote no verification, finding, receipt or attempt
  V18 S1 spool    a garbage ledger.sqlite3: `python -I -m onecrew.v2.support_spool .. report` (and `onecrew support report`) prints spooled true + the path and no
                  traceback; with the garbage file out of the way `support import-spool` imports exactly that one (same id), a second import imports none
  V19 S1 counter  `support confirm` with CLAUDE_CODE_CHILD_SESSION=1 is refused and writes no support.user_confirmed (control: without it, it works on the
                  temporary ledger); a report naming an attempt id that does not exist keeps it as user-declared only (refs_unresolved says so, nothing
                  derived) and creates no attempt row
  V20 S2 target   `support target add` with CLAUDE_CODE_CHILD_SESSION=1 is refused (no support.target), without it accepted; a OneCrew-shaped fix
                  repository is built in the case folder from the package wheel's own files and committed; `support artifact` refuses a crafted wheel
                  (one extra file onecrew/evil.py) by name and binds the wheel built from that commit (files_checked = every shipped file, bound to
                  the fix plan's milestone.passed)
  V21 S2 install  an install for a feedback linked to a fix plan WITHOUT `support_install:lab` ends blocked_by_authority and leaves the hooks; with the
                  grant: a new venv beside the target (the verifier's venv), processes listed, an intent record before the confirmation of each
                  hook rewrite, the hook settings now name the new venv, `support status` says installed true
  V22 S2 recheck  `support recheck` at the target adds exactly one node.verification (pass, the new version) and status says verified_at_target true;
                  `support rollback` with CLAUDE_CODE_CHILD_SESSION=1 is refused (hooks unchanged); the owner rollback (no marker) repoints the hooks to
                  the target and status says installed false, rolled_back true, still_blocked true, verified_at_target false
  V23 A sources   a node with `sources` under a root with authority.read reads src/lib/value.txt (not in its read list) by request in two rounds through
                  the real Supervisor path and the v24 fake claude (verify/onecrew_fake_claude_v24.py in a venv of its own, first on PATH): receipt source
                  results, source_tree in node.started; with a scripted worker, three requests outside the scope are refused rows without text and no secret
                  reaches a prompt, a max_rounds=1 node that keeps continuing is held rounds_exhausted after two model calls, and a cursor of another pinned
                  tree is refused ("source changed; list again"). Control: a node without `sources` has exactly the 2.3 receipt and node.started keys and
                  no source_tools in its prompt
  V24 B context   a decision `must` on a.txt delivered to node C (one knowledge.delivered for its attempt) is withdrawn while the worker runs: the step
                  ends continuing (knowledge_changed names it), C is not published, `wiki consumers --plan P1 --json` lists C withdrawn; in a NEW process
                  the rechecked C is produced with the entry absent from its package entries and present in delta.withdrawn, node.resumed has
                  budget_reset false. Control: node D (b.txt, independent) is published
  V25 C step 0    `plan proposal check` with preserve, estimate, investigation and an open option_choice unknown -> `plan step0 show --json` enough false
                  with unknown_open:U1; `plan survey open` over the investigation cap is refused and writes nothing; after `plan unknown close --by doc` and
                  a new check, enough true (and the text card says so). A root with execution-mode + parallel-engine runs two independent nodes in two
                  slots (managed executor, a local worker process): both node.started carry mode, mode_reasons, mode_inputs_sha; `engine measure` names
                  unobserved values unknown. Control: the same nodes on a root without execution-mode have no mode fields
  V3 also checks that the modules of the included milestones (support, diagnostics, support_cli, support_spool for S1) load from the venv.
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
    env.update(PATH=str(venv_scripts) + os.pathsep + env.get('PATH', ''), LOCALAPPDATA=str(local), APPDATA=str(roaming),
               ONECREW_LANG='en')                  # review dev7 R7-13: the facts read English output whatever the machine says; V6 asks for vi
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
    report = {'kind': 'v24-milestone-verify-report', 'package': str(pkg), 'started': time.strftime('%Y-%m-%dT%H:%M:%S'), 'steps': steps}
    clock = [time.monotonic()]
    def step(sid, ok, **facts):
        now = time.monotonic()
        steps.append(dict(id=sid, result='pass' if ok else 'fail', seconds=round(now - clock[0], 1), **facts)); clock[0] = now
        print(sid, 'pass' if ok else 'FAIL', f'{steps[-1]["seconds"]}s', flush=True)
        return ok
    manifest = json.loads((pkg / 'manifest.json').read_text(encoding='utf-8'))
    report['manifest'] = {k: manifest.get(k) for k in ('kind', 'milestone', 'milestones_included', 'stage', 'version', 'code_commit', 'wheel', 'previous_wheel',
                                                        'regression_wheel', 'claims')}
    included = [m for m in manifest.get('milestones_included') or [] if m in MILESTONE_ORDER]
    report['milestones_included'] = included
    report['expected_steps'] = expected_steps(included)
    report['steps_skipped'] = [{'milestone': m, 'steps': [sid for sid, _, _ in MILESTONE_STEPS.get(m, [])], 'reason': 'milestone not in milestones_included'}
                               for m in MILESTONE_ORDER if m not in included]
    report['unchecked_milestones'] = [m for m in included if not MILESTONE_STEPS.get(m)]      # included but this verifier has no step for it: the report fails
    # V1
    listed, problems = {}, []
    for line in (pkg / 'SHA256SUMS').read_text(encoding='utf-8').splitlines():
        digest, name = line.split('  ', 1); listed[name] = digest
    present = {p.relative_to(pkg).as_posix() for p in pkg.rglob('*') if p.is_file() and p.name != 'SHA256SUMS'}
    problems += [f'missing {n}' for n in sorted(set(listed) - present)] + [f'not listed {n}' for n in sorted(present - set(listed))]
    problems += [f'hash {n}' for n in sorted(set(listed) & present) if sha256(pkg / n) != listed[n]]
    wheel = pkg / 'wheel' / manifest['wheel']['name']
    previous = pkg / 'wheel' / 'regression' / manifest['regression_wheel']['name']      # the 2.2 wheel V7/V15/V16 install first (regression)
    rollback = pkg / 'wheel' / 'previous' / manifest['previous_wheel']['name']         # the 2.3.0.dev10 wheel a user goes back to: identity only (not installed by a step)
    reg = manifest['regression_wheel']
    if sha256(wheel) != manifest['wheel']['sha256']: problems.append('wheel sha differs from manifest')
    if sha256(rollback) != manifest['previous_wheel']['sha256']: problems.append('previous wheel sha differs from manifest')
    if sha256(previous) != reg['sha256']: problems.append('regression wheel sha differs from manifest')
    with zipfile.ZipFile(wheel) as archive:
        if bool(manifest.get('ships_paging')) != ('onecrew/paging.py' in archive.namelist()):
            problems.append(f'manifest ships_paging is {manifest.get("ships_paging")!r} but the wheel ' + ('has' if 'onecrew/paging.py' in archive.namelist() else 'lacks') + ' onecrew/paging.py')
    if manifest.get('kind') != 'v24-milestone-package': problems.append(f'manifest kind is {manifest.get("kind")!r}, not v24-milestone-package')
    if not included or included != [m for m in MILESTONE_ORDER if m in included] or included != MILESTONE_ORDER[:len(included)]:
        problems.append(f'milestones_included {manifest.get("milestones_included")!r} is not a cumulative prefix of {MILESTONE_ORDER}')
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
    names = [n for n in names if n != 'onecrew.paging' or manifest.get('ships_paging') or 'A' in included]     # 2.4-A always needs paging
    names += [n for m in included for n in MILESTONE_MODULES.get(m, [])]            # the modules of the milestones this package contains must load from the venv too
    code = 'import importlib, json; print(json.dumps({n: importlib.import_module(n).__file__ for n in ' + repr(names) + '}))'
    probe = run([py, '-I', '-c', code], text=True, cwd=work, env=env_for(work, scripts))
    try:
        origins = json.loads(probe.stdout)
    except ValueError:
        step('V3-origins', False, error='the modules did not import from the venv: ' + (probe.stdout + probe.stderr)[-400:])
        origins = None
    if origins is None: return finish(report, work)
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
    ok = (down.returncode == 0 and old_version == reg['version'] and show.returncode == 0 and engine_state.returncode == 0
          and isinstance(blocking, dict) and blocking.get('read') == 0 and control is not None and control.get('step_state') == 'produced'
          and isinstance(control_blocking, dict) and control_ids == continue_ids and up.returncode == 0 and again.returncode == 0 and b'a-value' in again.stdout)
    step('V7-rollback', ok, previous_version=old_version, compat_blocking=blocking, continue_blocks=continue_ids,
         control_compat_blocking=control_blocking, control_continue_blocks=control_ids, control_state=(control or {}).get('step_state'), control_reason=(control or {}).get('reason'),
         plan_show_exit=show.returncode, engine_state_exit=engine_state.returncode, forward_exit=again.returncode,
         show_tail=(show.stdout + show.stderr)[-200:].decode('utf-8', 'replace'))
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
        problems = oldwork_problems(facts, dict(manifest, previous_wheel=reg))
    except Exception as error:                     # an environment failure (git, venv) is a failed step, never a crash of the verifier
        facts, problems = {'error': f'{type(error).__name__}: {str(error)[:300]}'}, ['V16 could not run']
    step('V16-old-work', not problems, problems=problems, **facts)
    ctx = Ctx(pkg=pkg, work=work, py=py, scripts=scripts, manifest=manifest)
    for milestone in included:                  # 2.4: the steps of the milestones this package contains, from the INSTALLED venv
        for sid, title, check in MILESTONE_STEPS.get(milestone, []):
            try:
                ok, facts = check(ctx)
            except Exception as error:          # an environment failure is a failed step, never a crash of the verifier
                ok, facts = False, {'error': f'{type(error).__name__}: {str(error)[:300]}'}
            step(sid, ok, milestone=milestone, title=title, **facts)
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


def _state_tree(state):
    """{path: sha256} of a state root without SQLite's side files (a read-only open may create them)."""
    return {k: v for k, v in _tree(state).items() if not k.endswith(('-wal', '-shm', '-journal'))}


def _project_tree(project):
    """{path: sha256} of every file of a project but its .git folder."""
    project = Path(project)
    return {p.relative_to(project).as_posix(): sha256(p) for p in sorted(project.rglob('*'))
            if p.is_file() and '.git' not in p.relative_to(project).parts[:1]}


def init_wiki_cases(work, scripts, previous):
    """V15 facts: `onecrew init` of the installed wheel on new Git repositories in a folder with spaces, LOCALAPPDATA/APPDATA per case, English
    output (HOP-DONG-2.3 §10.3): KW-01 a new repository, KW-02 a second init after a page was edited, KW-04 one configured folder, KW-05 several
    folders, KW-06 an unreadable config.json, KW-07 a junction to a folder outside, KW-08 a file where the folder should be, KW-09 an
    interrupted skeleton, R7-10 an edited skeleton page, KW-13 a project set up by the previous (2.2) wheel. Judged by initwiki_problems."""
    base = work / 'init wiki'
    if base.exists(): shutil.rmtree(base)
    base.mkdir()
    exe, py = scripts / 'onecrew.exe', scripts / 'python.exe'
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
        out = (done.stdout + done.stderr).decode('utf-8', 'replace')
        return done.returncode, out, ('Done.' in out and 'Traceback' not in out)       # R7-12: exit 1 is also an uncaught error
    def pages(project):
        done = run([exe, '--project', project, '--state-root', state(project), 'wiki', 'pages'], cwd=base, env=env(project))
        try:
            value = json.loads(done.stdout.decode('utf-8'))
            return {'pages': sorted(p['path'] for p in value['pages']), 'entries': sum(len(p['entries']) for p in value['pages']), 'problems': value['problems']}
        except (ValueError, KeyError, TypeError):
            return {'error': (done.stdout + done.stderr)[-300:].decode('utf-8', 'replace')}
    skeleton = {name: run([py, '-I', '-c', 'import sys; from onecrew.v2 import install; sys.stdout.buffer.write(install.skeleton_text(sys.argv[1], "en").encode())', name],
                          cwd=base).stdout for name in SKELETON}
    facts = {}
    project = repo('new one')
    folder = project / 'docs' / 'wiki'
    code, out, finished = init(project)
    files = _files(folder) or []
    facts['new'] = {'exit': code, 'finished': finished, 'files': files,
                    'marked': [n for n in files if (folder / n).read_text(encoding='utf-8').startswith(SKELETON_MARK)],
                    'plan_line': 'create the wiki skeleton in docs/wiki' in out, 'pages': pages(project), 'tail': out[-300:]}
    page = folder / 'project.md'
    if page.is_file(): page.write_text(page.read_text(encoding='utf-8') + '\n## A rule of the project\nKeep a.txt short.\n', encoding='utf-8')
    before = (_project_tree(project), _state_tree(state(project)))
    code, out, finished = init(project)
    facts['again'] = {'exit': code, 'finished': finished, 'unchanged': (_project_tree(project), _state_tree(state(project))) == before,
                      'nothing': 'nothing to change' in out, 'pages': pages(project)}
    project = repo('configured')
    (project / '.onecrew').mkdir(); (project / '.onecrew' / 'config.json').write_text(json.dumps({'wiki': {'paths': ['kb']}}), encoding='utf-8')
    code, out, finished = init(project)
    try:
        kept = json.loads((project / '.onecrew' / 'config.json').read_text(encoding='utf-8')).get('wiki')
    except (OSError, ValueError):
        kept = None
    facts['configured'] = {'exit': code, 'finished': finished, 'kb': _files(project / 'kb'), 'docs': (project / 'docs').exists(), 'wiki_config': kept}
    project = repo('several')
    (project / 'a').mkdir(); (project / 'b').mkdir(); (project / 'b' / 'page.md').write_text('# B\n\n## A rule\nText.\n', encoding='utf-8')
    (project / '.onecrew').mkdir(); config = project / '.onecrew' / 'config.json'
    config.write_text(json.dumps({'wiki': {'paths': ['a', 'b']}}), encoding='utf-8')
    before = _project_tree(project)
    code, out, finished = init(project)
    after = {k: v for k, v in _project_tree(project).items() if not k.startswith(('.onecrew/', '.claude/'))}
    reused = {'exit': code, 'finished': finished, 'unchanged': after == {k: v for k, v in before.items() if not k.startswith('.onecrew/')},
              'a': _files(project / 'a'), 'docs': (project / 'docs').exists()}
    project = repo('several missing')
    (project / 'a').mkdir(); (project / '.onecrew').mkdir(); config = project / '.onecrew' / 'config.json'
    config.write_text(json.dumps({'wiki': {'paths': ['a', 'missing']}}), encoding='utf-8')
    raw = config.read_bytes()
    code, out, finished = init(project)
    facts['several'] = {'reused': reused, 'missing': {'exit': code, 'config_unchanged': config.read_bytes() == raw, 'said': 'not found' in out,
                        'wrote': [str(p) for p in (project / '.claude', project / 'missing', state(project) / 'ledger.sqlite3') if p.exists()]}}
    project = repo('bad config')
    (project / '.onecrew').mkdir(); config = project / '.onecrew' / 'config.json'; config.write_bytes(b'{ not json')
    code, out, finished = init(project)
    facts['bad_config'] = {'exit': code, 'config_unchanged': config.read_bytes() == b'{ not json', 'said': 'Nothing was changed' in out,
                           'wrote': [str(p) for p in (project / '.claude', project / 'docs', state(project) / 'ledger.sqlite3') if p.exists()]}
    project = repo('junction')
    outside = base / 'outside folder'; outside.mkdir(); (project / 'docs').mkdir()
    made = run(['cmd', '/c', 'mklink', '/J', project / 'docs' / 'wiki', outside]) if os.name == 'nt' else None
    if made is None: os.symlink(outside, project / 'docs' / 'wiki')
    code, out, finished = init(project)
    facts['junction'] = {'made': made is None or made.returncode == 0, 'exit': code, 'outside': _files(outside),
                         'ledger': (state(project) / 'ledger.sqlite3').exists(), 'said': 'link or junction' in out}
    project = repo('file clash')
    (project / 'docs').mkdir(); (project / 'docs' / 'wiki').write_text('not a folder', encoding='utf-8')
    code, out, finished = init(project)
    facts['file_clash'] = {'exit': code, 'file_unchanged': (project / 'docs' / 'wiki').read_text(encoding='utf-8') == 'not a folder',
                           'ledger': (state(project) / 'ledger.sqlite3').exists(), 'said': 'is not a folder' in out}
    project = repo('interrupted')
    folder = project / 'docs' / 'wiki'; folder.mkdir(parents=True)
    (folder / 'README.md').write_bytes(skeleton['README.md'])          # what an init stopped after its first page left
    kept = sha256(folder / 'README.md')
    code, out, finished = init(project)
    facts['interrupted'] = {'exit': code, 'finished': finished, 'files': _files(folder), 'kept': sha256(folder / 'README.md') == kept,
                            'skeleton_read': len(skeleton['README.md'])}
    project = repo('edited')
    folder = project / 'docs' / 'wiki'
    init(project)
    page = folder / 'project.md'
    if page.is_file(): page.write_text(page.read_text(encoding='utf-8') + '\n## Our rule\nKeep a.txt short.\n', encoding='utf-8')
    for name in ('README.md', 'lessons.md'):
        if (folder / name).is_file(): (folder / name).unlink()
    code, out, finished = init(project)
    facts['edited'] = {'exit': code, 'finished': finished, 'files': _files(folder)}
    old = work / 'venv previous wheel'
    if old.exists(): shutil.rmtree(old)
    run([sys.executable, '-m', 'venv', old], check=True)
    installed = run([old / 'Scripts' / 'python.exe', '-I', '-m', 'pip', 'install', '--no-index', '--no-build-isolation', previous])
    old_version = run([old / 'Scripts' / 'python.exe', '-I', '-c', 'import importlib.metadata as m; print(m.version("onecrew"))'], text=True, cwd=work).stdout.strip()
    project = repo('old project')
    old_code, _, old_finished = init(project, old / 'Scripts' / 'onecrew.exe')
    config = project / '.onecrew' / 'config.json'
    value = json.loads(config.read_text(encoding='utf-8')); value['custom'] = {'kept': True}; config.write_text(json.dumps(value), encoding='utf-8')
    ledger = state(project) / 'ledger.sqlite3'
    ledger_before = sha256(ledger) if ledger.is_file() else None
    had_wiki = (project / 'docs').exists()
    code, out, finished = init(project)
    after = json.loads(config.read_text(encoding='utf-8'))
    settings = json.loads((project / '.claude' / 'settings.local.json').read_text(encoding='utf-8'))
    commands = sorted({h.get('command') for entries in settings.get('hooks', {}).values() for e in entries for h in e.get('hooks', [])})
    facts['old_project'] = {'previous_install': installed.returncode, 'previous_version': old_version, 'old_exit': old_code, 'old_finished': old_finished,
                            'old_had_wiki': had_wiki, 'exit': code, 'finished': finished,
                            'ledger_unchanged': ledger_before is not None and sha256(ledger) == ledger_before,
                            'custom_kept': after.get('custom') == {'kept': True}, 'state_root_kept': after.get('state_root') == value.get('state_root'),
                            'hook_commands': commands, 'new_exe': str(exe.resolve()), 'wiki': _files(project / 'docs' / 'wiki')}
    return facts


def initwiki_problems(f):
    """What the installed `onecrew init` got wrong in V15 (WI-01..05); [] when nothing."""
    problems = []
    done = lambda case: case.get('exit') in (0, 1) and case.get('finished') is True     # 1 = done but the Claude CLI is not logged in
    new, again, conf, several, bad, link, clash, part, edited, old = (f.get(k) or {} for k in (
        'new', 'again', 'configured', 'several', 'bad_config', 'junction', 'file_clash', 'interrupted', 'edited', 'old_project'))
    if not done(new) or new.get('files') != SKELETON or new.get('marked') != SKELETON or not new.get('plan_line'):
        problems.append(f'KW-01 new repository: {new}')
    if (new.get('pages') or {}) != {'pages': ['docs/wiki/' + n for n in SKELETON], 'entries': 0, 'problems': []}:
        problems.append(f'KW-01/KW-11 the empty skeleton as read: {new.get("pages")}')
    if not done(again) or not again.get('unchanged') or not again.get('nothing') or (again.get('pages') or {}).get('entries') != 1:
        problems.append(f'KW-02 second init: {again}')
    if not done(conf) or conf.get('kb') != SKELETON or conf.get('docs') or conf.get('wiki_config') != {'paths': ['kb']}:
        problems.append(f'KW-04 configured folder: {conf}')
    reused, missing = several.get('reused') or {}, several.get('missing') or {}
    if not done(reused) or not reused.get('unchanged') or reused.get('a') != [] or reused.get('docs'):
        problems.append(f'KW-05 several folders reused: {reused}')
    if missing.get('exit') != 2 or not missing.get('config_unchanged') or missing.get('wrote') or not missing.get('said'):
        problems.append(f'KW-05 a missing folder among several: {missing}')
    if bad.get('exit') != 2 or not bad.get('config_unchanged') or bad.get('wrote') or not bad.get('said'):
        problems.append(f'KW-06 unreadable config.json: {bad}')
    if not link.get('made') or link.get('exit') != 2 or link.get('outside') != [] or link.get('ledger') or not link.get('said'):
        problems.append(f'KW-07 junction: {link}')
    if clash.get('exit') != 2 or not clash.get('file_unchanged') or clash.get('ledger') or not clash.get('said'):
        problems.append(f'KW-08 a file where the folder should be: {clash}')
    if not done(part) or part.get('files') != SKELETON or not part.get('kept') or not part.get('skeleton_read'):
        problems.append(f'KW-09 interrupted skeleton: {part}')
    if not done(edited) or edited.get('files') != ['project.md']:
        problems.append(f'R7-10 an edited skeleton page is the user\'s: {edited}')
    if (old.get('previous_install') != 0 or old.get('old_exit') not in (0, 1) or not old.get('old_finished') or old.get('old_had_wiki') or not done(old)
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
    tree_before = (_project_tree(project), _state_tree(state))
    facts['upgrade'] = run([py, '-I', '-m', 'pip', 'install', '--no-index', '--no-build-isolation', '--force-reinstall', wheel]).returncode
    facts['install_wrote_nothing'] = (_project_tree(project), _state_tree(state)) == tree_before and _events(state) == before     # KW-14
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
    if not f.get('install_wrote_nothing'): problems.append('KW-14: installing the wheel changed the project or the ledger')
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


# ---- 2.4 milestone steps -----------------------------------------------------------------------------------------------------------------
# Each step runs ONLY when the manifest's milestones_included contains its milestone, from the installed venv (python -I, a cwd outside the
# checkout, an isolated env without AI markers, LOCALAPPDATA/APPDATA under the case folder, the fake claude first on PATH). A step is
# `(id, title, check)`; check(ctx) returns (ok, facts) and facts go into verify-report.json next to the step. To add a milestone's steps
# (S2, A, B, C) write the check functions and put ONE entry in MILESTONE_STEPS (and its text in build_milestone.MILESTONE_TRY). The builder
# refuses a package of a milestone that has no entry here; this verifier fails a package that includes one.
MILESTONE_ORDER = ['S1', 'S2', 'A', 'B', 'C']
REGRESSION_STEPS = 16                      # V1-V16: the 2.3 verifier, unchanged
MILESTONE_MODULES = {'S1': ['onecrew.v2.support', 'onecrew.v2.diagnostics', 'onecrew.v2.support_cli', 'onecrew.v2.support_spool'],
                     'S2': ['onecrew.v2.hotfix'], 'A': ['onecrew.v2.source_tools', 'onecrew.paging'], 'B': ['onecrew.v2.working_context'],
                     'C': ['onecrew.v2.execution_mode', 'onecrew.v2.step0', 'onecrew.v2.survey']}
FEEDBACK_ID = re.compile(r'^FB-[0-9a-f]{32}$')
BUNDLE_STATUSES = ('included', 'missing', 'truncated', 'withheld', 'unreadable', 'not_applicable', 'unknown')      # onecrew.v2.diagnostics.STATUSES
REPORT_TEXT = 'Bước kiểm M1 báo sai dù file đúng — lỗi được báo từ bản cài, không từ checkout'      # Vietnamese on purpose: the text must round-trip byte for byte


class Ctx:
    """What a milestone step gets: the package, the work folder, the venv's python and Scripts folder, the manifest."""
    def __init__(self, pkg, work, py, scripts, manifest):
        self.pkg, self.work, self.py, self.scripts, self.manifest = pkg, work, py, scripts, manifest

    def case(self, name):
        """A fresh folder for one case (its own LOCALAPPDATA/APPDATA/TEMP under it), never reused."""
        folder = self.work / name
        if folder.exists(): shutil.rmtree(folder)
        folder.mkdir(parents=True)
        (folder / 'temp').mkdir()
        return folder

    def project(self, folder):
        project = folder / 'project'
        project.mkdir()
        run(['git', 'init', '-q', project], check=True)
        return project

    def onecrew(self, folder, project, state, *args, module=False, **env):
        """The installed `onecrew --project P --state-root S support ...` (or `python -I -m onecrew.v2.support_spool`) from a cwd outside the checkout.
        Returns (exit code, parsed JSON or None, output text)."""
        argv = [self.py, '-I', '-m', 'onecrew.v2.support_spool'] if module else [self.scripts / 'onecrew.exe']
        argv += ['--project', project, '--state-root', state] + ([] if module else ['support']) + list(args)
        done = run(argv, cwd=folder, env=env_for(folder, self.scripts, TEMP=str(folder / 'temp'), TMP=str(folder / 'temp'), **env))
        text = done.stdout.decode('utf-8', 'replace') + done.stderr.decode('utf-8', 'replace')
        return done.returncode, _first_json(done.stdout), text


def expected_steps(included):
    return REGRESSION_STEPS + sum(len(MILESTONE_STEPS.get(m, [])) for m in included)


def _ledger(state):
    """sqlite3 read-only handle on a state root's ledger, or None when there is none."""
    import sqlite3
    path = Path(state) / 'ledger.sqlite3'
    if not path.is_file(): return None
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _kinds(state):
    """{kind: count} of the events of a ledger (empty when no ledger)."""
    conn = _ledger(state)
    if conn is None: return {}
    try:
        counts = {}
        for row in conn.execute('SELECT kind, COUNT(*) AS n FROM events GROUP BY kind'): counts[row['kind']] = row['n']
        return counts
    finally:
        conn.close()


def _attempt_rows(state, attempt=None):
    """Number of rows of the attempts table (0 when the table or the ledger does not exist); with `attempt`, only that id."""
    conn = _ledger(state)
    if conn is None: return 0
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='attempts'").fetchone(): return 0
        if attempt: return conn.execute('SELECT COUNT(*) FROM attempts WHERE id=?', (attempt,)).fetchone()[0]
        return conn.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]
    finally:
        conn.close()


def v17_support_report(ctx):
    """S1 one-shot report: the key makes a second report the same record, the bundle names every source with an allowed status, show says reported/unknown."""
    folder = ctx.case('s1 report')
    project, state, export = ctx.project(folder), folder / 'state', folder / 'export'
    problems, facts = [], {}
    code, made, text = ctx.onecrew(folder, project, state, 'report', '--text', REPORT_TEXT, '--expected', 'M1 đạt', '--key', 'k1', '--json')
    made = made or {}
    ident = made.get('id')
    runtime = made.get('runtime') or {}
    facts['report'] = {'exit': code, 'id': ident, 'recorded': made.get('recorded'), 'spooled': made.get('spooled'), 'duplicate': made.get('duplicate'),
                       'status': made.get('status'), 'dist_version': runtime.get('dist_version'), 'checkout': runtime.get('checkout')}
    if not (code == 0 and made.get('recorded') is True and made.get('spooled') is False and made.get('duplicate') is False and FEEDBACK_ID.match(str(ident))
            and made.get('status') == 'reported'):
        problems.append('the first report: ' + str(facts['report']) + ' ' + (text[-200:] if code else ''))
        return False, dict(facts, problems=problems)
    if runtime.get('dist_version') != ctx.manifest['version'] or runtime.get('checkout') is not False:
        problems.append('the report ran from ' + str(runtime.get('dist_version')) + ' (checkout ' + str(runtime.get('checkout')) + '), not from the installed ' + ctx.manifest['version'])
    code, again, text = ctx.onecrew(folder, project, state, 'report', '--text', REPORT_TEXT, '--expected', 'M1 đạt', '--key', 'k1', '--json')
    again = again or {}
    facts['again'] = {'exit': code, 'id': again.get('id'), 'duplicate': again.get('duplicate')}
    if not (code == 0 and again.get('id') == ident and again.get('duplicate') is True): problems.append('the same key again: ' + str(facts['again']))
    code, other, text = ctx.onecrew(folder, project, state, 'report', '--text', 'a different report', '--key', 'k1', '--json')
    facts['other_content_same_key'] = {'exit': code, 'recorded': (other or {}).get('recorded'), 'error': str((other or {}).get('error', text))[:160]}
    if not (code != 0 and (other or {}).get('recorded') is not True): problems.append('the same key with other content was not refused: ' + str(facts['other_content_same_key']))
    kinds = _kinds(state)
    facts['events'] = kinds
    if kinds.get('support.feedback') != 1: problems.append('the ledger holds ' + str(kinds.get('support.feedback')) + ' support.feedback events, need exactly 1')
    odd = [k for k in kinds if any(w in k for w in ('verification', 'finding', 'receipt')) or k.startswith('attempt')]
    if odd or _attempt_rows(state): problems.append('a report must write no verification, finding, receipt or attempt: ' + str(odd) + ', attempt rows ' + str(_attempt_rows(state)))
    code, shown, text = ctx.onecrew(folder, project, state, 'show', ident, '--json')
    shown = shown or {}
    feedback, status = shown.get('feedback') or {}, shown.get('status') or {}
    facts['show'] = {'exit': code, 'reported': (status.get('reported') or {}).get('value'), 'reproduced': (status.get('reproduced') or {}).get('value'),
                     'feedback_reproduced': feedback.get('reproduced'), 'stage': status.get('stage'), 'text_kept': feedback.get('text') == REPORT_TEXT}
    if not (code == 0 and facts['show']['reported'] is True and facts['show']['reproduced'] == 'unknown' and feedback.get('reproduced') == 'unknown'
            and status.get('stage') == 'reported' and facts['show']['text_kept']):
        problems.append('support show: ' + str(facts['show']))
    code, bundle, text = ctx.onecrew(folder, project, state, 'bundle', ident, '--out', export)
    bundle = bundle or {}
    folder_out = Path(bundle['export']) if bundle.get('export') else None
    manifest = {}
    try:
        manifest = json.loads((folder_out / 'manifest.json').read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        problems.append('support bundle wrote no readable manifest.json: exit ' + str(code) + ', ' + text[-200:])
    sources = manifest.get('sources') or []
    bad = [s.get('source') for s in sources if s.get('status') not in BUNDLE_STATUSES]
    na = {s.get('source'): s.get('status') for s in sources if s.get('source') in ('runner.logs', 'host.log')}
    outside = bool(folder_out) and not folder_out.resolve().is_relative_to(state.resolve())
    facts['bundle'] = {'exit': code, 'sources': len(sources), 'statuses': sorted({str(s.get('status')) for s in sources}), 'runner_host': na,
                       'uploaded': manifest.get('uploaded'), 'export_outside_state': outside, 'manifest': str(folder_out / 'manifest.json') if folder_out else None}
    if not (code == 0 and sources and not bad and na == {'runner.logs': 'not_applicable', 'host.log': 'not_applicable'} and manifest.get('uploaded') is False and outside):
        problems.append('support bundle: ' + str(facts['bundle']) + ', sources with a status outside the allowed set: ' + str(bad))
    return not problems, dict(facts, problems=problems, state=str(state), feedback=ident)


def v18_support_spool(ctx):
    """S1 spool: a garbage ledger.sqlite3 does not lose the report (python -I -m onecrew.v2.support_spool, and the onecrew.exe path), import-spool
    imports it once with the id printed at report time, a second import imports nothing."""
    folder = ctx.case('s1 spool')
    project, broken = ctx.project(folder), folder / 'broken-state'
    broken.mkdir()
    garbage = b'garbage, not sqlite ' * 50
    (broken / 'ledger.sqlite3').write_bytes(garbage)
    problems, facts = [], {}
    code, spooled, text = ctx.onecrew(folder, project, broken, 'report', '--text', REPORT_TEXT, '--json', module=True)
    spooled = spooled or {}
    path = Path(spooled['path']) if spooled.get('path') else None
    facts['module_report'] = {'exit': code, 'spooled': spooled.get('spooled'), 'recorded': spooled.get('recorded'), 'id': spooled.get('id'), 'path': str(path) if path else None,
                              'in_state_root_spool': bool(path) and path.is_relative_to(broken / 'support-spool'), 'traceback': 'Traceback' in text}
    if not (code == 0 and spooled.get('spooled') is True and spooled.get('recorded') is True and FEEDBACK_ID.match(str(spooled.get('id'))) and path and path.is_file()
            and facts['module_report']['in_state_root_spool'] and not facts['module_report']['traceback']):
        problems.append('python -I -m onecrew.v2.support_spool report: ' + str(facts['module_report']) + ' ' + text[-300:])
        return False, dict(facts, problems=problems)
    ident = spooled['id']
    if (broken / 'ledger.sqlite3').read_bytes() != garbage: problems.append('the spool step changed the garbage ledger')
    second = folder / 'broken-state-exe'          # the same through onecrew.exe on a second broken state root of the same project: the CLI falls back to the spool by itself
    second.mkdir()
    (second / 'ledger.sqlite3').write_bytes(garbage)
    code, via_exe, text = ctx.onecrew(folder, project, second, 'report', '--text', 'exe path with a broken ledger', '--json')
    via_exe = via_exe or {}
    facts['exe_report'] = {'exit': code, 'spooled': via_exe.get('spooled'), 'recorded': via_exe.get('recorded'), 'traceback': 'Traceback' in text,
                           'file': bool(via_exe.get('path')) and Path(via_exe['path']).is_file()}
    if not (code == 0 and via_exe.get('spooled') is True and via_exe.get('recorded') is True and facts['exe_report']['file'] and not facts['exe_report']['traceback']):
        problems.append('onecrew support report on a garbage ledger: ' + str(facts['exe_report']) + ' ' + text[-300:])
    (broken / 'ledger.sqlite3').rename(broken / 'ledger.garbage')         # the repair: the unreadable file is gone, the CLI creates a fresh ledger
    code, imported, text = ctx.onecrew(folder, project, broken, 'import-spool')
    imported = imported or {}
    facts['import'] = {'exit': code, 'imported': imported.get('imported'), 'skipped': imported.get('skipped')}
    if not (code == 0 and imported.get('imported') == [ident] and not imported.get('skipped')): problems.append('import-spool: ' + str(facts['import']) + ' ' + text[-200:])
    code, again, text = ctx.onecrew(folder, project, broken, 'import-spool')
    again = again or {}
    facts['import_again'] = {'exit': code, 'imported': again.get('imported'), 'already_recorded': again.get('already_recorded')}
    if not (code == 0 and again.get('imported') == []): problems.append('a second import-spool imported something: ' + str(facts['import_again']))
    kinds = _kinds(broken)
    facts['events'] = kinds
    if kinds.get('support.feedback') != 1: problems.append('after two imports the ledger holds ' + str(kinds.get('support.feedback')) + ' support.feedback events, need exactly 1')
    facts['spool_file_moved'] = not path.exists() and (path.parent / 'imported' / path.name).is_file()
    if not facts['spool_file_moved']: problems.append('the imported spool file was not moved to imported/')
    code, shown, text = ctx.onecrew(folder, project, broken, 'show', ident, '--json')
    feedback = (shown or {}).get('feedback') or {}
    facts['show'] = {'exit': code, 'id': feedback.get('id'), 'text_kept': feedback.get('text') == REPORT_TEXT, 'spooled_reason': (feedback.get('spooled') or {}).get('reason')}
    if not (code == 0 and feedback.get('id') == ident and facts['show']['text_kept'] and facts['show']['spooled_reason'] == spooled.get('reason')):
        problems.append('support show after the import: ' + str(facts['show']))
    return not problems, dict(facts, problems=problems, feedback=ident)


def v19_support_counter(ctx):
    """S1 counter-controls: `support confirm` inside an AI session is refused and writes nothing (control: outside it, it works - fixture owner
    on a temporary ledger); a report naming an attempt that does not exist is recorded without refs derived from it and creates no attempt."""
    folder = ctx.case('s1 counter')
    project, state = ctx.project(folder), folder / 'state'
    problems, facts = [], {}
    code, made, text = ctx.onecrew(folder, project, state, 'report', '--text', 'counter-control report', '--key', 'c1', '--json')
    ident = (made or {}).get('id')
    if code != 0 or not FEEDBACK_ID.match(str(ident)): return False, {'problems': ['could not record the report the controls need: ' + str(code) + ' ' + text[-200:]]}
    code, refused, text = ctx.onecrew(folder, project, state, 'confirm', ident, '--reference', 'in an AI session', CLAUDE_CODE_CHILD_SESSION='1')
    kinds = _kinds(state)
    facts['confirm_in_ai_session'] = {'exit': code, 'error': str((refused or {}).get('error', text))[:200], 'confirmed_events': kinds.get('support.user_confirmed', 0)}
    if not (code != 0 and 'refused' in str((refused or {}).get('error', text)) and not kinds.get('support.user_confirmed')):
        problems.append('support confirm inside an AI session: ' + str(facts['confirm_in_ai_session']))
    code, status, text = ctx.onecrew(folder, project, state, 'status', ident, '--json')
    if not (code == 0 and ((status or {}).get('user_confirmed') or {}).get('value') is False):
        problems.append('after the refused confirm, user_confirmed is ' + str((status or {}).get('user_confirmed')))
    code, ok, text = ctx.onecrew(folder, project, state, 'confirm', ident, '--reference', 'fixture owner on a temporary ledger, not an owner confirmation')      # control: no AI marker
    facts['confirm_control'] = {'exit': code, 'confirmed_events': _kinds(state).get('support.user_confirmed', 0)}
    if not (code == 0 and facts['confirm_control']['confirmed_events'] == 1): problems.append('control, support confirm outside an AI session: ' + str(facts['confirm_control']) + ' ' + text[-200:])
    absent = 'ATT-' + '0123456789abcdef' * 2
    code, made, text = ctx.onecrew(folder, project, state, 'report', '--text', 'report naming an attempt that does not exist', '--attempt', absent, '--key', 'c2', '--json')
    made = made or {}
    derived = sorted(set(made.get('refs') or {}) - {'attempt'})
    facts['absent_attempt'] = {'exit': code, 'recorded': made.get('recorded'), 'refs': made.get('refs'), 'refs_source': made.get('refs_source'),
                               'refs_unresolved': made.get('refs_unresolved'), 'attempt_rows': _attempt_rows(state), 'attempt_row_for_id': _attempt_rows(state, absent)}
    if not (code == 0 and made.get('recorded') is True and not derived and (made.get('refs_source') or {}) == {'attempt': 'user'}
            and str((made.get('refs_unresolved') or {}).get('attempt', '')).startswith('no such attempt') and facts['absent_attempt']['attempt_rows'] == 0):
        problems.append('a report naming an absent attempt: ' + str(facts['absent_attempt']) + ' (refs derived from it: ' + str(derived) + ')')
    return not problems, dict(facts, problems=problems, feedback=ident)


# ---- 2.4-S2 steps (V20-V22): one self-contained scenario, set up once and shared by the three steps --------------------------------------
# The fix project is a OneCrew-shaped git repository built in the case folder from the package wheel's own files (so the hotfix wheel built from
# it is a real, working OneCrew whose every file comes from that commit); the "old" runtime and install target is the verifier's own venv.

S2_SETUP = r'''
import json, os, subprocess, sys
from pathlib import Path
from onecrew.ledger import Ledger, canonical
from onecrew.snapshots import Snapshots
from onecrew.control_core import Control, migrate
from onecrew.v2 import plan, engine, internal_plan, verdict, hook_cli, where
args = json.loads(sys.argv[1])
root, state, repo = Path(args['customer']), Path(args['state']), Path(args['repo'])
def git(where_, *a): return subprocess.run(['git', '-C', str(where_), *a], check=True, capture_output=True, text=True).stdout.strip()
root.mkdir()
git(root, 'init', '-q'); git(root, 'config', 'user.name', 'T'); git(root, 'config', 'user.email', 't@localhost')
(root / 'a.txt').write_text('base\n'); git(root, 'add', '.'); git(root, 'commit', '-qm', 'base')
ledger = Ledger(root, state)
caps = ['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine']
plan.propose(ledger, 'P1', args['contract'], 'codex', workflow=True, capabilities=caps)
plan.approve(ledger, 'P1', 'owner', 'verifier fixture: the customer root, on a temporary ledger')
fix = Ledger(repo, state)
for name, grant in (('FIX1', ['support_install:lab']), ('FIX0', [])):
    value = dict(args['fix_contract'], authority=dict(args['fix_contract']['authority'], granted_actions=grant))
    plan.propose(fix, name, value, 'claude', workflow=True)
    plan.approve(fix, name, 'owner', 'verifier fixture: the OneCrew fix plan, on a temporary ledger')
    assert verdict.run(fix, name, 'M1', repo)['milestones'][0]['state'] == 'passed'
os.environ['ONECREW_ACTOR'] = 'codex'
migrate(ledger)
internal_plan.revise(ledger, 'P1', args['nodes'], reason='one producer and the integration', evidence=['a.txt:1'])
store = Snapshots(ledger.state_root)
def execute(ledger, control, task, item, attempt):
    control.launched(attempt['id'], attempt['generation'], {'fixture': True})
    artifact = store.overlay(store.capture(root, ['a.txt']), {'a.txt': b'candidate\n'}, ['a.txt'])
    receipt = store.blob(canonical({'kind': 'fixture-producer', 'artifact': artifact}).encode())
    control.finish(attempt['id'], attempt['generation'], {'artifact': artifact})
    return {'artifact': artifact, 'receipt': receipt}
def defect(item, artifact):           # the reported runtime defect: the check of a right file fails
    return {'artifact': artifact, 'checks': [{'id': c['id'], 'result': 'fail', 'evidence': store.blob(b'the old runtime failed this check')}
                                            for c in item['checks']]}
assert engine.step(ledger, 'P1', execute, control=Control(ledger))['state'] == 'produced'
first = engine.verify(ledger, 'P1', 'C', defect)['result']
settings = root / '.claude' / 'settings.local.json'
settings.parent.mkdir()
settings.write_text(json.dumps(hook_cli.portable_settings(Path(args['target_exe']), state), indent=2), encoding='utf-8')
where.register_project(root, state)
print(json.dumps({'first_verify': first, 'fix_project_id': fix.project_id, 'root': engine.state(ledger, 'P1')['root']}))
'''


def _plan(milestones, authority, paths=('a.txt',)):
    return {'schema_version': 2, 'title': 'S2 package fixture', 'size': 'S',
            'understanding': {'restated_goal': 'Prove the S2 hotfix chain on a temporary ledger.', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': list(paths)},
                              'assumptions': [], 'confidence': 'high', 'unknowns': []},
            'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'the file to work on is there'}],
            'output': ['The sample exists'], 'scope': {'owned': list(paths)}, 'non_goals': ['Nothing else'],
            'items': [{'id': 'I1', 'title': 'Do it', 'tier': 'must', 'milestone': 'M1'}],
            'milestones': milestones, 'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1}, 'profile_version': None,
            'authority': authority}


def _node(nid, depends=(), integration=False, write=('a.txt',)):
    return {'id': nid, 'goal': 'Produce evidence for O1', 'input': [], 'output': ['Evidence for O1'], 'acceptance': ['O1'],
            'depends': [{'node': d, 'requires': 'verified'} for d in depends], 'read': ['a.txt'], 'write': list(write), 'resources': [],
            'estimate_seconds': [1, 2], 'execution_cap_seconds': 60, 'budget_calls': 1,
            'checks': [{'id': 'M1', 'spec': 'The exact approved root command M1'}], 'integration': integration}


def _record_line(name, data):
    return f'{name},sha256={base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")},{len(data)}'


def _write_wheel(path, files):
    record = next(n for n in files if n.endswith('.dist-info/RECORD'))
    lines = [_record_line(n, d) for n, d in files.items() if n != record]
    files = dict(files); files[record] = ('\n'.join(lines + [f'{record},,']) + '\n').encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items(): archive.writestr(name, data)
    return path


def _s2_repo_and_wheels(ctx, folder):
    """(repo, version, good wheel, crafted wheel, manifests): a git repository holding exactly the package wheel's onecrew/ files and a pyproject that
    declares them, committed; a hotfix wheel built from that commit (version +hotfix) and a crafted copy with one extra file."""
    with zipfile.ZipFile(ctx.pkg / 'wheel' / ctx.manifest['wheel']['name']) as archive:
        members = {n: archive.read(n) for n in archive.namelist() if not n.endswith('/')}
    sources = {n: d for n, d in members.items() if n.startswith('onecrew/')}
    old_dist = next(n for n in members if n.endswith('.dist-info/METADATA')).split('/')[0]
    version = ctx.manifest['version'] + '+hotfix'       # a local version: a valid PEP 440 version of its own, whatever the package version is
    modules = sorted(n[:-3].replace('/', '.') for n in sources if n.endswith('.py') and not n.endswith('/__init__.py'))
    packages = ['onecrew.templates'] if any(n.startswith('onecrew/templates/') for n in sources) else []
    repo = folder / 'onecrew-repo'
    for name, data in sources.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True); (repo / name).write_bytes(data)
    (repo / 'pyproject.toml').write_text('[project]\nname = "onecrew"\nversion = "' + version + '"\n\n[project.scripts]\nonecrew = "onecrew.console:main"\n\n'
                                         '[tool.setuptools]\npackages = ' + json.dumps(packages) + '\npy-modules = [\n'
                                         + ''.join(f'    "{m}",\n' for m in modules) + ']\n', encoding='utf-8')
    (repo / 'a.txt').write_text('the fix\n'); (repo / '.gitignore').write_text('.onecrew/\n')
    for args in (('init', '-q'), ('config', 'user.name', 'T'), ('config', 'user.email', 't@localhost'), ('add', '-A'), ('commit', '-qm', 'the hotfix')):
        run(['git', '-C', repo, *args], check=True)
    commit = run(['git', '-C', repo, 'rev-parse', 'HEAD'], check=True).stdout.decode().strip()
    dist = f'onecrew-{version}.dist-info'
    files = {n: (repo / n).read_bytes() for n in sources}
    files[f'{dist}/METADATA'] = f'Metadata-Version: 2.1\nName: onecrew\nVersion: {version}\nRequires-Python: >=3.10\n'.encode()
    files[f'{dist}/WHEEL'] = b'Wheel-Version: 1.0\nGenerator: verify_milestone\nRoot-Is-Purelib: true\nTag: py3-none-any\n'
    if f'{old_dist}/entry_points.txt' in members: files[f'{dist}/entry_points.txt'] = members[f'{old_dist}/entry_points.txt']
    files[f'{dist}/RECORD'] = b''
    name = f'onecrew-{version}-py3-none-any.whl'
    good = _write_wheel(folder / 'hotfix' / name, files)
    crafted = _write_wheel(folder / 'crafted' / name, dict(files, **{'onecrew/evil.py': b'import os  # in no commit of the fix project\n'}))
    manifests = {}
    for label, wheel in (('good', good), ('crafted', crafted)):
        manifests[label] = wheel.parent / 'manifest.json'
        manifests[label].write_text(json.dumps({'kind': 'verifier-hotfix', 'version': version, 'code_commit': commit,
                                                'wheel': {'name': wheel.name, 'sha256': sha256(wheel)}}), encoding='utf-8')
    return repo, version, good, crafted, manifests, commit, len(sources)


def _s2(ctx):
    """The shared S2 scenario (built by V20, read by V21/V22)."""
    if getattr(ctx, 's2', None) is not None: return ctx.s2
    folder = ctx.case('s2 hotfix')
    repo, version, good, crafted, manifests, commit, shipped = _s2_repo_and_wheels(ctx, folder)
    customer, state = folder / 'customer', folder / 'state'
    check = [str(ctx.py), '-c', 'from pathlib import Path; assert Path("a.txt").read_text() == "candidate\\n"; print("candidate tested")']
    args = {'customer': str(customer), 'state': str(state), 'repo': str(repo), 'target_exe': str(ctx.scripts / 'onecrew.exe'),
            'contract': _plan([{'id': 'M1', 'title': 'Milestone M1', 'verifier': {'type': 'command', 'config': {'argv': check}}, 'covers': ['O1']}],
                              {'edit': True, 'commands': True, 'apply_to_project': True, 'unconfined_commands': True,
                               'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']}),
            'fix_contract': _plan([{'id': 'M1', 'title': 'Milestone M1', 'verifier': {'type': 'command', 'config': {'argv': [str(ctx.py), '-c', 'print("ok")']}},
                                    'covers': ['O1']}], {'edit': True, 'commands': True}),
            'nodes': [_node('C'), _node('I', ['C'], integration=True, write=())]}
    done = run([ctx.py, '-I', '-c', S2_SETUP, json.dumps(args)], cwd=folder,
               env=env_for(folder, ctx.scripts, TEMP=str(folder / 'temp'), TMP=str(folder / 'temp')))
    setup = _first_json(done.stdout) or {}
    if done.returncode != 0 or setup.get('first_verify') != 'fail':
        raise RuntimeError('the S2 scenario could not be set up: ' + (done.stdout + done.stderr).decode('utf-8', 'replace')[-400:])
    ctx.s2 = dict(folder=folder, repo=repo, version=version, good=good, crafted=crafted, manifests=manifests, commit=commit, shipped=shipped,
                  customer=customer, state=state, fix=setup['fix_project_id'], root=setup['root'],
                  settings=customer / '.claude' / 'settings.local.json', target_exe=str((ctx.scripts / 'onecrew.exe').resolve()))
    return ctx.s2


def _s2_cli(ctx, s, *args, **env):
    return ctx.onecrew(s['folder'], s['customer'], s['state'], *args, **env)


def _hook_programs(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    return sorted({h['command'] for entries in data['hooks'].values() for e in entries for h in e['hooks']})


def _support_installs(state):
    conn = _ledger(state)
    try:
        return [dict(json.loads(r['payload']), seq=r['seq']) for r in conn.execute("SELECT seq, payload FROM events WHERE kind='support.install' ORDER BY seq")]
    finally:
        conn.close()


def _feedback(ctx, s, text, plan_name):
    code, made, out = _s2_cli(ctx, s, 'report', '--text', text, '--plan', 'P1', '--json')
    ident = (made or {}).get('id')
    if code != 0 or not FEEDBACK_ID.match(str(ident)): raise RuntimeError('report: ' + out[-300:])
    for argv in (('classify', ident, '--class', 'onecrew_runtime', '--basis', 'the node C receipt'),
                 ('link', ident, '--plan', plan_name, '--project-id', s['fix'])):
        code, _, out = _s2_cli(ctx, s, *argv)
        if code != 0: raise RuntimeError(' '.join(argv[:1]) + ': ' + out[-300:])
    return ident


def v20_support_target_artifact(ctx):
    """S2 target and artifact: `support target add` refused under CLAUDE_CODE_CHILD_SESSION=1 and accepted without it; `support artifact` refuses a
    crafted wheel (one extra file) and binds the wheel built from the verified commit (every shipped file compared to it)."""
    s = _s2(ctx)
    problems, facts = [], {'fix_commit': s['commit'], 'hotfix_version': s['version'], 'shipped_files': s['shipped']}
    s['fb'] = _feedback(ctx, s, 'Node C fails although a.txt is right (reported from the installed package)', 'FIX1')
    code, refused, out = _s2_cli(ctx, s, 'target', 'add', '--id', 'lab', '--venv', ctx.scripts.parent, CLAUDE_CODE_CHILD_SESSION='1')
    targets = _kinds(s['state']).get('support.target', 0)
    facts['target_in_ai_session'] = {'exit': code, 'error': str((refused or {}).get('error', out))[:160], 'target_records': targets}
    if not (code != 0 and 'refused' in str((refused or {}).get('error', out)) and targets == 0): problems.append('target add in an AI session: ' + str(facts['target_in_ai_session']))
    code, made, out = _s2_cli(ctx, s, 'target', 'add', '--id', 'lab', '--venv', ctx.scripts.parent)
    facts['target_owner'] = {'exit': code, 'venv': (made or {}).get('venv'), 'target_records': _kinds(s['state']).get('support.target', 0)}
    if not (code == 0 and facts['target_owner']['target_records'] == 1): problems.append('target add without the marker: ' + str(facts['target_owner']) + ' ' + out[-200:])
    code, refused, out = _s2_cli(ctx, s, 'artifact', s['fb'], '--wheel', s['crafted'], '--manifest', s['manifests']['crafted'])
    facts['crafted'] = {'exit': code, 'error': str((refused or {}).get('error', out))[:200], 'artifact_records': _kinds(s['state']).get('support.artifact', 0)}
    if not (code != 0 and 'onecrew/evil.py' in facts['crafted']['error'] and facts['crafted']['artifact_records'] == 0):
        problems.append('the crafted wheel was not refused by name: ' + str(facts['crafted']))
    code, bound, out = _s2_cli(ctx, s, 'artifact', s['fb'], '--wheel', s['good'], '--manifest', s['manifests']['good'])
    bound = bound or {}
    facts['bound'] = {'exit': code, 'files_checked': bound.get('files_checked'), 'bound_to': (bound.get('bound_to') or {}).get('record'),
                      'code_commit': bound.get('code_commit'), 'wheel_sha256': bound.get('wheel_sha256'), 'version': bound.get('version')}
    if not (code == 0 and bound.get('files_checked') == s['shipped'] and facts['bound']['bound_to'] == 'milestone.passed' and bound.get('code_commit') == s['commit']
            and bound.get('wheel_sha256') == sha256(s['good']) and bound.get('version') == s['version']):
        problems.append('the wheel of the verified commit was not bound: ' + str(facts['bound']) + ' ' + out[-200:])
    return not problems, dict(facts, problems=problems, feedback=s['fb'])


def v21_support_install(ctx):
    """S2 install: without the support_install:<id> grant the install ends blocked_by_authority and switches nothing; with it, a NEW venv beside the
    target, the safe point, an intent record before and a confirmation after each hook rewrite, and `support status` says installed against the
    live hook settings."""
    s = _s2(ctx)
    if not s.get('fb'): return False, {'problems': ['V20 did not bind the artifact this step needs']}
    problems, facts = [], {}
    fb0 = _feedback(ctx, s, 'The same defect, linked to a fix plan without the install grant', 'FIX0')
    code, bound, out = _s2_cli(ctx, s, 'artifact', fb0, '--wheel', s['good'], '--manifest', s['manifests']['good'])
    if code != 0: return False, {'problems': ['artifact for the no-grant feedback: ' + out[-200:]]}
    before = _hook_programs(s['settings'])
    code, blocked, out = _s2_cli(ctx, s, 'install', fb0, '--target', 'lab', ONECREW_ACTOR='codex')
    blocked = blocked or {}
    facts['without_grant'] = {'exit': code, 'result': blocked.get('result'), 'reason': str(blocked.get('reason'))[:160], 'hooks_unchanged': _hook_programs(s['settings']) == before}
    if not (code == 0 and blocked.get('result') == 'blocked_by_authority' and facts['without_grant']['hooks_unchanged'] and 'support_install:lab' in str(blocked.get('reason'))):
        problems.append('the install without the grant: ' + str(facts['without_grant']) + ' ' + out[-200:])
    code, state0, _ = _s2_cli(ctx, s, 'status', fb0, '--json')
    if (((state0 or {}).get('installed') or {}).get('value') is not False): problems.append('the blocked install shows installed: ' + str((state0 or {}).get('installed')))
    code, made, out = _s2_cli(ctx, s, 'install', s['fb'], '--target', 'lab', ONECREW_ACTOR='codex')
    made = made or {}
    new_venv = Path(made['new_venv']) if made.get('new_venv') else None
    installs = [r for r in _support_installs(s['state']) if r.get('feedback') == s['fb']]
    intents = [r['seq'] for r in installs if r.get('phase') == 'intent']
    confirmed = [r['seq'] for r in installs if r.get('phase') == 'switched_one']
    hooks = _hook_programs(s['settings'])
    facts['install'] = {'exit': code, 'result': made.get('result'), 'new_venv': str(new_venv) if new_venv else None, 'version': (made.get('identity') or {}).get('version'),
                        'processes': made.get('processes'), 'intents': intents, 'confirmations': confirmed, 'hooks_now': hooks,
                        'beside_target': bool(new_venv) and new_venv.parent == ctx.scripts.parent.parent and new_venv != ctx.scripts.parent}
    if not (code == 0 and made.get('result') == 'switched' and facts['install']['beside_target'] and facts['install']['version'] == s['version']
            and intents and confirmed and min(intents) < min(confirmed) and made.get('processes') not in (None, 'unknown')
            and hooks == [str((new_venv / 'Scripts' / 'onecrew.exe').resolve())]):
        problems.append('the granted install: ' + str(facts['install']) + ' ' + out[-300:])
    code, status, _ = _s2_cli(ctx, s, 'status', s['fb'], '--json')
    facts['status'] = {'exit': code, 'installed': ((status or {}).get('installed') or {}).get('value'), 'trial_build': ((status or {}).get('trial_build') or {}).get('value')}
    if facts['status']['installed'] is not True: problems.append('support status after the switch: ' + str(facts['status']))
    s['new_venv'] = new_venv
    return not problems, dict(facts, problems=problems, feedback=s['fb'])


def _verifications(state, root):
    conn = _ledger(state)
    try:
        return conn.execute("SELECT COUNT(*) FROM events WHERE task_id=? AND kind='node.verification'", (root,)).fetchone()[0]
    finally:
        conn.close()


def v22_support_recheck_rollback(ctx):
    """S2 recheck and rollback: the recheck at the target is a real node.verification (pass) and status says verified_at_target; rollback is refused
    under an AI marker; after the owner's rollback status says installed false, rolled_back true, still_blocked true."""
    s = _s2(ctx)
    if not s.get('new_venv'): return False, {'problems': ['V21 did not switch the target this step needs']}
    problems, facts = [], {}
    before = _verifications(s['state'], s['root'])
    code, made, out = _s2_cli(ctx, s, 'recheck', s['fb'], ONECREW_ACTOR='codex')
    made = made or {}
    after = _verifications(s['state'], s['root'])
    facts['recheck'] = {'exit': code, 'environment': made.get('environment'), 'result': made.get('result'), 'version': made.get('version'),
                        'receipt': made.get('receipt'), 'node_verifications': [before, after]}
    if not (code == 0 and made.get('environment') == 'target' and made.get('result') == 'pass' and after == before + 1 and made.get('version') == s['version']):
        problems.append('the recheck at the target: ' + str(facts['recheck']) + ' ' + out[-300:])
    code, status, _ = _s2_cli(ctx, s, 'status', s['fb'], '--json')
    facts['verified'] = ((status or {}).get('verified_at_target') or {}).get('value')
    if facts['verified'] is not True: problems.append('verified_at_target after the recheck: ' + str((status or {}).get('verified_at_target')))
    hooks = _hook_programs(s['settings'])
    code, refused, out = _s2_cli(ctx, s, 'rollback', s['fb'], CLAUDE_CODE_CHILD_SESSION='1')
    facts['rollback_in_ai_session'] = {'exit': code, 'error': str((refused or {}).get('error', out))[:160], 'hooks_unchanged': _hook_programs(s['settings']) == hooks}
    if not (code != 0 and 'refused' in facts['rollback_in_ai_session']['error'] and facts['rollback_in_ai_session']['hooks_unchanged']):
        problems.append('rollback in an AI session: ' + str(facts['rollback_in_ai_session']))
    code, back, out = _s2_cli(ctx, s, 'rollback', s['fb'])
    back = back or {}
    facts['rollback'] = {'exit': code, 'result': back.get('result'), 'proven': back.get('proven'), 'hooks_now': _hook_programs(s['settings'])}
    if not (code == 0 and back.get('result') == 'rolled_back' and facts['rollback']['hooks_now'] == [s['target_exe']]):
        problems.append('the owner rollback: ' + str(facts['rollback']) + ' ' + out[-300:])
    code, status, _ = _s2_cli(ctx, s, 'status', s['fb'], '--json')
    status = status or {}
    facts['after_rollback'] = {k: (status.get(k) or {}).get('value') for k in ('installed', 'rolled_back', 'still_blocked', 'verified_at_target')}
    if facts['after_rollback'] != {'installed': False, 'rolled_back': True, 'still_blocked': True, 'verified_at_target': False}:
        problems.append('status after the rollback: ' + str(facts['after_rollback']))
    return not problems, dict(facts, problems=problems, feedback=s['fb'])


# ---- 2.4-A, B, C steps (V23-V25): scenario bodies run by the INSTALLED venv's python -I from the case folder ------------------------------

def _scenario(ctx, folder, code, args, **env):
    """Run `code` with the venv's python -I (argv[1] = args as JSON) from `folder`; the body prints one line '@@' + JSON. Returns (facts, tail)."""
    done = run([ctx.py, '-I', '-c', code, json.dumps(args)], cwd=folder,
               env=env_for(folder, ctx.scripts, TEMP=str(folder / 'temp'), TMP=str(folder / 'temp'), **env))
    text = done.stdout.decode('utf-8', 'replace')
    line = next((l for l in text.splitlines() if l.startswith('@@')), None)
    return (json.loads(line[2:]) if line else None), (text + done.stderr.decode('utf-8', 'replace'))[-1500:]


SCENARIO_COMMON = r'''
import copy, json, os, subprocess, sys
from pathlib import Path
from unittest.mock import patch
args = json.loads(sys.argv[1])
work = Path(args['work'])
def git(root, *a): return subprocess.run(['git', '-C', str(root), *a], check=True, capture_output=True, text=True).stdout.strip()
def project(name, files):
    root = work / name; root.mkdir()
    git(root, 'init', '-q'); git(root, 'config', 'user.name', 'fixture'); git(root, 'config', 'user.email', 'fixture@localhost')
    for rel, text in files.items():
        path = root / rel; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(text.encode('utf-8'))
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'base')
    return root
def node(nid, depends=(), integration=False, write=('a.txt',), read=('a.txt',), checks=None):
    return {'id': nid, 'goal': 'Produce evidence for O1', 'input': [], 'output': ['Evidence for O1'], 'acceptance': ['O1'],
            'depends': [{'node': d, 'requires': 'verified'} for d in depends], 'read': list(read), 'write': list(write), 'resources': [],
            'estimate_seconds': [1, 2], 'execution_cap_seconds': 60, 'budget_calls': 1,
            'checks': checks or [{'id': 'M1', 'spec': 'Check the declared O1 output of ' + nid}], 'integration': integration,
            'executor': {'role': 'worker', 'provider': 'claude', 'model': 'claude-haiku-5-5'}}
def contract(owned=('a.txt',), authority=None, title='Package fixture'):
    return {'schema_version': 2, 'title': title, 'size': 'S',
            'understanding': {'restated_goal': 'Prove the package fixture.', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']},
                              'assumptions': [], 'confidence': 'high', 'unknowns': []},
            'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'the file to work on is there'}],
            'output': ['The sample exists'], 'scope': {'owned': list(owned)}, 'non_goals': ['Nothing else'],
            'items': [{'id': 'I1', 'title': 'Do it', 'tier': 'must', 'milestone': 'M1'}],
            'milestones': [{'id': 'M1', 'title': 'Milestone M1', 'verifier': {'type': 'command', 'config': {'argv': [sys.executable, '-c', 'print("ok")']}},
                            'covers': ['O1']}],
            'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1}, 'profile_version': None,
            'authority': dict({'edit': True, 'commands': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']}, **(authority or {}))}
from onecrew.ledger import Ledger, content_hash
from onecrew.snapshots import Snapshots
from onecrew.v2 import plan, engine, internal_plan
CAPS = ['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine']
def root(ledger, name, value, caps=CAPS):
    os.environ.pop('ONECREW_ACTOR', None)
    plan.propose(ledger, name, value, 'codex', workflow=True, capabilities=caps)
    plan.approve(ledger, name, 'owner', 'verifier fixture on a temporary ledger')
    os.environ['ONECREW_ACTOR'] = 'codex'
def events(ledger, kind=None):
    with ledger.transaction() as conn:
        rows = conn.execute('SELECT seq, task_id, kind, payload FROM events ORDER BY seq').fetchall()
    return [dict(json.loads(r['payload']), _seq=r['seq'], _task=r['task_id'], _kind=r['kind']) for r in rows if kind is None or r['kind'] == kind]
def emit(out):
    print('@@' + json.dumps(out, ensure_ascii=False, default=str))
class Fixture:
    """A scripted worker (no model, no process): `values` are answers or callables(prompt, schema); the real NativeExecutor runs around it."""
    def __init__(self):
        self.calls, self.values = [], []
    def factory(self, control, provider):
        case = self
        class Worker:
            def capability(self): return {'provider': provider, 'mode': 'fixture-no-tools'}
            def run(self, attempt, prompt, schema, profile):
                case.calls.append({'prompt': prompt, 'schema': schema})
                control.launched(attempt['id'], attempt['generation'], {'fixture': True})
                control.finish(attempt['id'], attempt['generation'], {'exit_code': 0, 'fixture': True})
            def result(self, attempt):
                value = case.values.pop(0)
                value = value(case.calls[-1]['prompt'], case.calls[-1]['schema']) if callable(value) else value
                return copy.deepcopy(value), [{'source': 'fixture'}]
        return Worker()
'''

A_BODY = SCENARIO_COMMON + r'''
from onecrew.common_executor import NativeExecutor
from onecrew.control_core import migrate
from onecrew.v2 import source_tools
files = {'a.txt': 'base\n', 'out.txt': 'base\n', '.gitignore': '.onecrew/\n', 'src/main.py': 'from lib import value\n',
         'src/lib/value.txt': 'The configured VALUE: green\n', 'src/.env.local': 'TOKEN=never-shown\n', 'other/y.py': 'OUTSIDE = True\n'}
proj = project('project', files)
ledger = Ledger(proj, work / 'state')
migrate(ledger)
store = Snapshots(ledger.state_root)
out = {}
# 1. the real path: NativeExecutor -> ClaudeArtifact -> Supervisor -> the fake claude (v24) process; two rounds, a file read by request
item = node('C', write=('out.txt',), read=('src/main.py',), checks=[{'id': 'M1', 'spec': 'out.txt holds the configured value.'}])
item['sources'] = {'read': ['src/'], 'max_rounds': 2, 'max_chars_per_round': 8000}
root(ledger, 'P1', contract(owned=('a.txt', 'out.txt'), authority={'read': ['src/**']}))
internal_plan.revise(ledger, 'P1', [item, node('I', ['C'], integration=True, write=(), read=())], reason='source fixture', evidence=['a.txt:1'])
steps = [engine.step(ledger, 'P1', NativeExecutor(ledger))]
while steps[-1]['state'] == 'continuing' and len(steps) < 5: steps.append(engine.step(ledger, 'P1', NativeExecutor(ledger)))
receipt = json.loads(store.read_blob(steps[-1]['receipt'])) if steps[-1].get('receipt') else {}
started = [e for e in events(ledger, 'node.started') if e['node'] == 'C']
out['main'] = {'states': [s['state'] for s in steps], 'source': {k: (receipt.get('source') or {}).get(k) for k in ('capability', 'rounds_used', 'max_rounds', 'count')},
               'result_actions': [r.get('action') for r in (receipt.get('source') or {}).get('results') or []] if isinstance((receipt.get('source') or {}).get('results'), list) else None,
               'results_blob': (receipt.get('source') or {}).get('results') if isinstance((receipt.get('source') or {}).get('results'), str) else None,
               'candidate': store.context(steps[-1]['artifact'])['out.txt'] if steps[-1].get('artifact') else None,
               'source_tree_in_started': [bool(e.get('source_tree')) for e in started],
               'fake': [json.loads(l) for l in Path(args['log']).read_text(encoding='utf-8').splitlines()] if Path(args['log']).exists() else []}
# 2. scripted worker: outside-scope requests are refused rows; max_rounds=1 holds the node; an opt-out node has no source fields
fixture = Fixture()
with patch('onecrew.artifact_provider_core.make_worker', side_effect=fixture.factory):
    asked = [{'op': 'read', 'path': '../outside.txt'}, {'op': 'read', 'path': 'other/y.py'}, {'op': 'read', 'path': 'src/.env.local'}]
    d = node('D', write=('out.txt',), read=('src/main.py',)); d['sources'] = {'read': ['src/'], 'max_rounds': 4, 'max_chars_per_round': 8000}
    root(ledger, 'P2', contract(owned=('a.txt', 'out.txt'), authority={'read': ['src/**']}))
    internal_plan.revise(ledger, 'P2', [d, node('I', ['D'], integration=True, write=(), read=())], reason='refusals', evidence=['a.txt:1'])
    fixture.values += [{'summary': 'reading', 'files': [], 'backlog': [], 'continuation': {'remaining': 'more'}, 'source': {'requests': asked}},
                       {'summary': 'done', 'files': [{'path': 'out.txt', 'content': 'done\n'}], 'backlog': []}]
    states = [engine.step(ledger, 'P2', NativeExecutor(ledger))['state'], engine.step(ledger, 'P2', NativeExecutor(ledger))['state']]
    second = json.loads(fixture.calls[1]['prompt'].split('\n', 1)[1])['source_tools']['results']
    out['refused'] = {'states': states, 'rows': [{'action': r.get('action'), 'refused': (r.get('result') or {}).get('refused'),
                                                  'has_text': 'text' in (r.get('result') or {})} for r in second],
                      'secret_in_prompts': any('never-shown' in c['prompt'] or 'OUTSIDE = True' in c['prompt'] for c in fixture.calls)}
    e = node('E', write=('out.txt',), read=('src/main.py',)); e['sources'] = {'read': ['src/'], 'max_rounds': 1, 'max_chars_per_round': 8000}
    root(ledger, 'P3', contract(owned=('a.txt', 'out.txt'), authority={'read': ['src/**']}))
    internal_plan.revise(ledger, 'P3', [e, node('I', ['E'], integration=True, write=(), read=())], reason='round cap', evidence=['a.txt:1'])
    calls = len(fixture.calls)
    fixture.values += [{'summary': 'reading', 'files': [], 'backlog': [], 'continuation': {'remaining': 'more'}, 'source': {'requests': []}}] * 6
    rounds = []
    for _ in range(4):
        result = engine.step(ledger, 'P3', NativeExecutor(ledger)); rounds.append(result['state'])
        if result['state'] != 'continuing': break
    out['rounds'] = {'states': rounds, 'classification': result.get('classification'), 'model_calls': len(fixture.calls) - calls}
    f = node('F', write=('a.txt',))
    root(ledger, 'P4', contract())
    internal_plan.revise(ledger, 'P4', [f, node('I', ['F'], integration=True, write=(), read=())], reason='opt-out control', evidence=['a.txt:1'])
    fixture.values[:] = [{'summary': 'done', 'files': [{'path': 'a.txt', 'content': 'one\n'}], 'backlog': []}]
    produced = engine.step(ledger, 'P4', NativeExecutor(ledger))
    if not produced.get('receipt'): emit({'error': 'opt-out node not produced', 'result': produced}); sys.exit(0)
    receipt = json.loads(store.read_blob(produced['receipt']))
    started = [x for x in events(ledger, 'node.started') if x['node'] == 'F'][0]
    out['opt_out'] = {'state': produced['state'], 'receipt_keys': sorted(receipt), 'started_keys': sorted(k for k in started if not k.startswith('_')),
                      'prompt_has_source_tools': 'source_tools' in fixture.calls[-1]['prompt']}
# 3. a cursor of another pinned tree is refused
tree1 = source_tools.pin_now(proj)
scope = source_tools.Scope(['src/**'], ['src/'])
with patch.object(source_tools, 'LIST_ENTRIES', 1):
    first = source_tools.run(source_tools.Reader(proj, tree1['tree']), scope, {'op': 'list', 'path': 'src'})['result']
    (proj / 'src' / 'new.py').write_text('NEW = 1\n')
    tree2 = source_tools.pin_now(proj)
    stale = source_tools.run(source_tools.Reader(proj, tree2['tree']), scope, {'op': 'list', 'cursor': first.get('next_cursor')})['result']
out['cursor'] = {'had_cursor': bool(first.get('next_cursor')), 'trees_differ': tree1['tree'] != tree2['tree'], 'stale': stale.get('refused')}
out['origins'] = {n: getattr(sys.modules.get(n), '__file__', None) for n in ('onecrew.v2.source_tools', 'onecrew.paging', 'onecrew.common_executor')}
emit(out)
'''

OPT_OUT_RECEIPT_KEYS = ['artifact', 'attempt', 'base', 'changed_paths', 'content_sha', 'continuation', 'continues_attempt', 'elapsed_seconds', 'inputs',
                        'internal_model_call_cap', 'kind', 'knowledge', 'knowledge_use', 'model', 'node', 'partial', 'producer_chars', 'profile',
                        'prompt_chars', 'provider', 'response', 'resume_artifact', 'role', 'scope_enforced_by', 'task', 'usage']      # the 2.3 receipt (tests sa11)
OPT_OUT_STARTED_KEYS = ['at', 'attempt', 'child', 'early_dependencies', 'generation', 'inputs', 'internal_revision', 'node', 'plan', 'revision', 'source']


def _fake_v24_venv(ctx):
    """A separate venv holding only the v24 fake `claude` (verify/onecrew_fake_claude_v24.py) whose Scripts go first on PATH for V23: the v23 fake
    the other steps use stays as it is."""
    if getattr(ctx, 'fake_v24', None): return ctx.fake_v24
    folder = ctx.work / 'fake claude v24'
    if folder.exists(): shutil.rmtree(folder)
    folder.mkdir()
    source = Path(__file__).resolve().parent / 'onecrew_fake_claude_v24.py'
    info = 'onecrew_fake_claude_v24-0.1.dist-info'
    files = {'onecrew_fake_claude_v24.py': source.read_bytes(),
             f'{info}/METADATA': b'Metadata-Version: 2.1\nName: onecrew-fake-claude-v24\nVersion: 0.1\n',
             f'{info}/WHEEL': b'Wheel-Version: 1.0\nGenerator: verify_milestone\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
             f'{info}/entry_points.txt': b'[console_scripts]\nclaude = onecrew_fake_claude_v24:main\n', f'{info}/RECORD': b''}
    wheel = _write_wheel(folder / 'onecrew_fake_claude_v24-0.1-py3-none-any.whl', files)
    run([sys.executable, '-m', 'venv', folder / 'venv'], check=True)
    scripts = folder / 'venv' / ('Scripts' if os.name == 'nt' else 'bin')
    done = run([scripts / ('python.exe' if os.name == 'nt' else 'python'), '-m', 'pip', 'install', '--no-index', '--no-deps', '--disable-pip-version-check', wheel])
    if done.returncode != 0: raise RuntimeError('the v24 fake claude did not install: ' + done.stdout.decode('utf-8', 'replace')[-300:])
    ctx.fake_v24 = scripts
    return scripts


def v23_sources(ctx):
    """2.4-A: a node with `sources` under a root with authority.read reads a file not in its `read` list by request, in two rounds, on the pinned
    tree (receipt source results, source_tree in node.started) through the real Supervisor path and the v24 fake claude; requests outside scope
    are refused rows without bytes; a cursor of another tree is refused; max_rounds=1 holds the node rounds_exhausted after max_rounds+1 calls.
    Control: a node without `sources` has the 2.3 receipt and node.started keys and no source_tools in its prompt."""
    folder = ctx.case('a sources')
    fake = _fake_v24_venv(ctx)
    policy, log = folder / 'policy.json', folder / 'fake.jsonl'
    policy.write_text(json.dumps({'read': 'value.txt'}))
    facts, tail = _scenario(ctx, folder, A_BODY, {'work': str(folder), 'log': str(log)},
                            PATH=str(fake) + os.pathsep + str(ctx.scripts) + os.pathsep + os.environ.get('PATH', ''),
                            ONECREW_FAKE_POLICY=str(policy), ONECREW_FAKE_LOG=str(log))
    if facts is None or 'error' in facts: return False, {'problems': ['the scenario did not finish: ' + tail], 'facts': facts}
    problems, main = [], facts['main']
    if main['states'] != ['continuing', 'produced']: problems.append('two rounds expected: ' + str(main['states']))
    if [(r.get('how'), r.get('value')) for r in main['fake']] != [('ask', None), ('read', 'green')]: problems.append('the fake did not ask then read: ' + str(main['fake']))
    if main['candidate'] != 'green\n': problems.append('the value read by request was not written: ' + str(main['candidate']))
    if main['source'].get('capability') != 'git-tree' or main['source'].get('rounds_used') != 1: problems.append('receipt source: ' + str(main['source']))
    if not (main['result_actions'] or main['results_blob']): problems.append('the receipt carries no source results')
    if not main['source_tree_in_started'] or not all(main['source_tree_in_started']): problems.append('node.started without source_tree: ' + str(main['source_tree_in_started']))
    refused = facts['refused']
    if refused['states'] != ['continuing', 'produced'] or len(refused['rows']) != 3 or not all(r['refused'] and not r['has_text'] for r in refused['rows']) \
            or refused['secret_in_prompts']:
        problems.append('requests outside the scope: ' + str(refused))
    rounds = facts['rounds']
    if rounds['states'] != ['continuing', 'held'] or rounds['classification'] != 'rounds_exhausted' or rounds['model_calls'] != 2:
        problems.append('max_rounds=1: ' + str(rounds))
    cursor = facts['cursor']
    if not (cursor['had_cursor'] and cursor['trees_differ'] and 'source changed; list again' in str(cursor['stale'])): problems.append('cursor of another tree: ' + str(cursor))
    opt = facts['opt_out']
    if opt['state'] != 'produced' or opt['receipt_keys'] != OPT_OUT_RECEIPT_KEYS or opt['started_keys'] != OPT_OUT_STARTED_KEYS or opt['prompt_has_source_tools']:
        problems.append('opt-out control (2.3 keys expected): ' + str(opt))
    venv = str(ctx.scripts.parent).casefold()
    bad = {n: o for n, o in facts['origins'].items() if not (o and o.casefold().startswith(venv))}
    if bad: problems.append('modules not from the installed venv: ' + str(bad))
    return not problems, dict(facts, problems=problems)


B_BODY = SCENARIO_COMMON + r'''
from onecrew.common_executor import NativeExecutor
from onecrew.control_core import migrate
from onecrew.v2 import knowledge
phase = args['phase']
proj = work / 'project'
ledger = Ledger(proj, work / 'state') if phase == 2 else None
out = {'pid': os.getpid()}
if phase == 1:
    proj = project('project', {'a.txt': 'base\n', 'b.txt': 'base\n', '.gitignore': '.onecrew/\n'})
    ledger = Ledger(proj, work / 'state')
    migrate(ledger)
    root(ledger, 'P1', contract(owned=('a.txt', 'b.txt')))
    with ledger.transaction() as conn:
        event = conn.execute('SELECT MAX(seq) FROM events').fetchone()[0]
    rule = knowledge.record(ledger, 'P1', kind='decision', text='a.txt must hold VALUE: right', applies_to=['a.txt'], must=True,
                            evidence={'status': 'verified', 'property': 'decided in review', 'sources': [{'type': 'event', 'id': event}]})['id']
    nodes = [node('C', checks=[{'id': 'M1', 'spec': 'a.txt holds the value the knowledge requires.'}]),
             node('D', write=('b.txt',), read=('b.txt',), checks=[{'id': 'M1', 'spec': 'b.txt is written.'}]),
             node('I', ['C', 'D'], integration=True, write=(), read=(), checks=[{'id': 'M1', 'spec': 'Integration.'}])]
    internal_plan.revise(ledger, 'P1', nodes, reason='working-context fixture', evidence=['a.txt:1'])
    class Concurrent(NativeExecutor):
        withdrawn = False
        def finish(self, *a, **k):
            if not Concurrent.withdrawn:                    # another writer withdraws the delivered must while the worker runs
                Concurrent.withdrawn = True
                knowledge.withdraw(ledger, 'P1', rule, reason='a.txt keeps its value now', evidence={'sources': [{'type': 'event', 'id': event}]})
            return super().finish(*a, **k)
    first = engine.step(ledger, 'P1', Concurrent(ledger))
    attempt = [e for e in events(ledger, 'node.started') if e['node'] == 'C'][0]['attempt']
    delivered = [e for e in events(ledger, 'knowledge.delivered') if e.get('attempt') == attempt]
    cli = subprocess.run([str(Path(sys.executable).parent / ('onecrew.exe' if os.name == 'nt' else 'onecrew')), '--project', str(proj), '--state-root',
                          str(ledger.state_root), 'wiki', 'consumers', '--plan', 'P1', '--json'], capture_output=True, cwd=str(work))
    out.update(rule=rule, first={'node': first.get('node'), 'state': first.get('state'), 'critical': [c.get('id') for c in (first.get('knowledge_changed') or {}).get('critical') or []]},
               delivered=[{'attempt': e.get('attempt'), 'delivered': e.get('delivered')} for e in delivered],
               produced_after_first=[e['node'] for e in events(ledger, 'node.produced')],
               cli={'code': cli.returncode, 'consumers': [(c.get('node'), c.get('status')) for c in json.loads(cli.stdout.decode('utf-8')).get('consumers', [])]
                    if cli.returncode == 0 else cli.stderr.decode('utf-8', 'replace')[-300:]})
else:
    store = Snapshots(ledger.state_root)
    rule = args['rule']
    results = []
    for _ in range(4):
        result = engine.step(ledger, 'P1', NativeExecutor(ledger))
        results.append({'node': result.get('node'), 'state': result.get('state')})
        if result.get('node') == 'C' and result.get('receipt'):
            receipt = json.loads(store.read_blob(result['receipt']))
            package = json.loads(store.read_blob(receipt['knowledge']['package'])) if (receipt.get('knowledge') or {}).get('package') else {}
            out['c'] = {'state': result['state'], 'entries': [e.get('id') for e in package.get('entries', [])],
                        'requested': [e.get('id') for e in package.get('requested', [])],
                        'withdrawn': [w.get('id') for w in ((receipt.get('knowledge') or {}).get('delta') or {}).get('withdrawn', [])],
                        'candidate': store.context(result['artifact'])['a.txt'] if result.get('artifact') else None}
        if all(any(r['node'] == n and r['state'] == 'produced' for r in results) for n in ('C', 'D')): break
    retained = [e['node'] for e in events(ledger, 'node.result_retained')]
    out.update(results=results, produced=[e['node'] for e in events(ledger, 'node.produced')], retained=retained,
               resumed=[{'node': e.get('node'), 'budget_reset': e.get('budget_reset')} for e in events(ledger, 'node.resumed')])
out['origins'] = {n: getattr(sys.modules.get(n), '__file__', None) for n in ('onecrew.v2.working_context', 'onecrew.v2.knowledge')}
emit(out)
'''


def v24_context(ctx):
    """2.4-B: knowledge delivered to an attempt is a knowledge.delivered event of that attempt; a must withdrawn while the worker runs keeps the candidate
    from being published (rechecked) and `wiki consumers --plan P1 --json` lists the node as withdrawn; control: an independent node publishes; after a
    restart (a new process) the rechecked attempt gets the withdrawn entry only in delta.withdrawn, never in its entries."""
    folder = ctx.case('b context')
    policy, log = folder / 'policy.json', folder / 'fake.jsonl'
    policy.write_text(json.dumps({'default': 'naive', 'careful': True}))
    env = dict(ONECREW_FAKE_POLICY=str(policy), ONECREW_FAKE_LOG=str(log))
    first, tail = _scenario(ctx, folder, B_BODY, {'work': str(folder), 'phase': 1}, **env)
    if first is None: return False, {'problems': ['phase 1 did not finish: ' + tail]}
    second, tail = _scenario(ctx, folder, B_BODY, {'work': str(folder), 'phase': 2, 'rule': first['rule']}, **env)
    if second is None: return False, {'problems': ['phase 2 (a new process) did not finish: ' + tail], 'phase1': first}
    problems = []
    if not (first['first']['node'] == 'C' and first['first']['state'] == 'continuing' and first['first']['critical'] == [first['rule']]):
        problems.append('the withdrawn must did not keep the candidate from publication: ' + str(first['first']))
    if not (len(first['delivered']) == 1 and first['rule'] in (first['delivered'][0]['delivered'] or [])):
        problems.append('knowledge.delivered of the attempt: ' + str(first['delivered']))
    if 'C' in first['produced_after_first']: problems.append('the candidate built on the withdrawn fact was published')
    cli = first['cli']
    if cli['code'] != 0 or isinstance(cli['consumers'], str) or ('C', 'withdrawn') not in [tuple(x) for x in cli['consumers']]:
        problems.append('wiki consumers: ' + str(cli))
    c = second.get('c') or {}
    if not (c.get('state') == 'produced' and first['rule'] not in c.get('entries', []) + c.get('requested', []) and c.get('withdrawn') == [first['rule']]):
        problems.append('after the restart, the rechecked attempt: ' + str(c))
    if second['pid'] == first['pid']: problems.append('phase 2 ran in the same process')
    if 'D' not in second['produced'] or 'D' in second['retained']: problems.append('control: the independent node D did not publish: ' + str(second['results']))
    if second['produced'].count('C') != 1: problems.append('C must be published exactly once (the rechecked candidate): ' + str(second['produced']))
    if any(r['budget_reset'] for r in second['resumed']) or not second['resumed']: problems.append('node.resumed: ' + str(second['resumed']))
    return not problems, {'phase1': first, 'phase2': second, 'problems': problems}


C_BODY = SCENARIO_COMMON + r'''
import contextlib, io
from onecrew.control_core import migrate
from onecrew.v2.cli import main as cli_main
from onecrew.v2 import step0
def cli(*a):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer): code = cli_main(['--project', str(proj), '--state-root', str(work / 'state'), *a])
    text = buffer.getvalue()
    try: return code, json.loads(text)
    except ValueError: return code, text
files = {'a.txt': 'one\n', 'b.txt': 'two\n', 'routes.py': 'x\n', 'api.py': 'x\n', 'menu.js': 'x\n', 'reports_new.py': 'x\n', 'data/old_report.json': 'x\n',
         'x/y.py': 'x = 1\n' * 3, 'onecrew/conversations.py': 'x = 1\n' * 170, '.gitignore': '.onecrew/\n'}
proj = project('project', files)
ledger = Ledger(proj, work / 'state')
out = {}
# 1. step 0: the three optional card fields and a decision-changing unknown -> not enough; a survey over the cap refused; closing evidence -> enough
value = contract(owned=('a.txt',))
value['understanding']['unknowns'] = [{'id': 'U1', 'question': 'Is the old report data used by another job?', 'status': 'open', 'closed_by': None,
                                       'evidence': None, 'affected': ['O1'], 'required_by': 'option_choice'}]
os.environ.pop('ONECREW_ACTOR', None)
plan.propose(ledger, 'S0', value, 'codex')
os.environ['ONECREW_ACTOR'] = 'codex'
requirement = {'acceptance': [{'id': 'A1', 'text': 'No user can export the old report by any path (menu, URL, API)', 'semantic': {'unreachable_via': ['menu', 'url', 'api']}},
                              {'id': 'A2', 'text': 'The old report data is deleted permanently', 'semantic': {'removal': 'permanent'}}],
               'constraints': [{'id': 'K1', 'text': 'Keep the new report'}], 'dependencies': []}
def change(cid, kind, entries, links, target, **extra): return dict({'id': cid, 'title': f'{kind} {target}', 'kind': kind, 'entries': entries, 'links': links, 'target': target}, **extra)
def proposal_value(status):
    return {'preferred': {'id': 'P1', 'summary': 'Remove the old report route, handler, menu entry and data; leave the new report alone',
                          'before': 'The old report can be exported from the menu, by URL and by API; its data is stored.',
                          'after': 'No path exports the old report; its data is gone; the new report is unchanged.',
                          'rationale': 'Deleting the three entries and the data meets A1 and A2 and touches nothing else.',
                          'changes': [change('X1', 'delete', ['url'], ['A1'], 'routes.py'), change('X2', 'delete', ['api'], ['A1'], 'api.py'),
                                      change('X3', 'delete', ['menu'], ['A1'], 'menu.js'), change('X4', 'delete', ['storage'], ['A2'], 'data/old_report.json'),
                                      change('X5', 'modify', ['api'], ['K1'], 'reports_new.py')]},
            'covers': ['A1', 'A2'], 'in_authority': True, 'backlog': [],
            'preserve': [{'id': 'K1', 'text': 'The new report and its API stay unchanged'}],
            'estimate': {'range': [600, 1800], 'evidence': ['routes.py:1']},
            'investigation': {'cap': {'minutes': 4, 'calls': 4}, 'paths': ['x', 'onecrew'], 'stop_when': 'an answer citing file:line, or the cap'},
            'unknowns': [{'id': 'U1', 'question': 'Is the old report data used by another job?', 'affected': ['A2', 'X4'], 'required_by': 'option_choice', 'status': status}]}
body = work / 'proposal.json'
body.write_text(json.dumps({'requirement': requirement, 'proposal': proposal_value('open')}), encoding='utf-8')
code, checked = cli('plan', 'proposal', 'check', 'S0', '--file', str(body))
code, card = cli('plan', 'step0', 'show', 'S0', '--json')
out['open'] = {'check_exit': code, 'enough': card.get('enough') if isinstance(card, dict) else None, 'not_enough': card.get('not_enough') if isinstance(card, dict) else card}
before = len(events(ledger))
from onecrew.v2 import survey
question = {'id': 'U9', 'question': 'Another question beyond the investigation cap?', 'affected': ['A1'], 'required_by': 'option_choice', 'status': 'open'}
try:                                                 # the check opened the survey of U1 with the whole cap: a second one has no room left
    with ledger.transaction(write=True) as conn:
        survey.open_in(ledger, conn, plan.anchor_events(ledger, conn, 'S0'), question, {'cap': {'minutes': 5, 'calls': 1},
                       'end_condition': 'an answer citing file:line', 'scope': {'mode': 'read_only', 'paths': ['x']}})
    refused, code = 'opened', 0
except survey.InvestigationCapReached as error:
    refused, code = 'InvestigationCapReached: ' + str(error), 2
out['survey_over_cap'] = {'exit': code, 'answer': refused, 'events_added': len(events(ledger)) - before,
                          'surveys': [x.get('survey') for x in events(ledger, 'survey.opened')]}
code, closed = cli('plan', 'unknown', 'close', 'S0', 'U1', '--by', 'doc', '--evidence', 'x/y.py:1')
body.write_text(json.dumps({'requirement': requirement, 'proposal': proposal_value('closed')}), encoding='utf-8')
code2, checked2 = cli('plan', 'proposal', 'check', 'S0', '--file', str(body))
code3, card2 = cli('plan', 'step0', 'show', 'S0', '--json')
out['closed'] = {'close_exit': code, 'check_exit': code2, 'enough': card2.get('enough') if isinstance(card2, dict) else None,
                 'not_enough': card2.get('not_enough') if isinstance(card2, dict) else card2}
code, text = cli('plan', 'step0', 'show', 'S0')
out['text_card'] = {'exit': code, 'says_enough': 'đủ để làm: có' in str(text)}
# 2. execution mode: two independent nodes in two slots with the managed executor (a local worker process), then measure; control without the capability
from onecrew.v2.managed_executor import ManagedExecutor
from onecrew.process_core import Supervisor, native_python
from onecrew.subscription import environment
os.environ['ONECREW_HOST_HOME'] = str(work / 'host-home')
migrate(ledger)
def factory(control, provider):
    class LocalWorker:
        def capability(self): return {'provider': provider, 'mode': 'local-test-artifact-no-tools'}
        def run(self, attempt, prompt, schema, profile):
            directory = ledger.state_root / 'worker-io' / attempt['id']; directory.mkdir(parents=True)
            path = json.loads(prompt.split('\n', 1)[1])['node']['write'][0]
            value = {'summary': 'fixture', 'files': [{'path': path, 'content': 'candidate ' + path + '\n'}], 'backlog': []}
            script = 'import pathlib,sys\npathlib.Path("answer.json").write_text(sys.argv[1])\n'
            return Supervisor(control).run(attempt, [native_python(), '-c', script, json.dumps(value)], cwd=directory,
                                           timeout=min(20, profile['step_seconds']), env=environment())
        def result(self, attempt):
            return json.loads((ledger.state_root / 'worker-io' / attempt['id'] / 'answer.json').read_text()), []
    return LocalWorker()
def mode_root(name, caps):
    root(ledger, name, contract(owned=('a.txt', 'b.txt')), caps=caps)
    internal_plan.revise(ledger, name, [node('A', read=('a.txt',)), node('B', write=('b.txt',), read=('b.txt',)),
                                        node('I', ['A', 'B'], integration=True, write=(), read=())], reason='two independent nodes', evidence=['a.txt:1'])
    batch = engine.run_batch(ledger, name, ManagedExecutor(ledger, worker_factory=factory), slots=2)
    with ledger.transaction() as conn:
        task = plan.derive(ledger, conn, name)['task_id']
    started = [e for e in events(ledger, 'node.started') if e['_task'] == task]
    return {'results': {r.get('node'): r.get('state') for r in batch['results']},
            'started': [{'node': e['node'], 'mode': e.get('mode'), 'mode_reasons': e.get('mode_reasons'), 'has_mode_fields': bool({'mode', 'mode_reasons', 'mode_inputs_sha'} & set(e))}
                        for e in started]}
PARALLEL = CAPS + ['parallel-engine']
out['mode'] = mode_root('M1', PARALLEL + ['execution-mode'])
code, measured = cli('engine', 'measure', 'M1')
attempts = measured.get('attempts', []) if isinstance(measured, dict) else []
out['measure'] = {'exit': code, 'attempts': len(attempts), 'unknown_fields': sorted({k for a in attempts for k, v in a.items() if v == 'unknown'}
                                                                                  | {k for k, v in (measured.items() if isinstance(measured, dict) else []) if v == 'unknown'})}
out['control'] = mode_root('M0', PARALLEL)
out['origins'] = {n: getattr(sys.modules.get(n), '__file__', None) for n in ('onecrew.v2.execution_mode', 'onecrew.v2.step0', 'onecrew.v2.survey')}
emit(out)
'''


def v25_step0_mode(ctx):
    """2.4-C: `plan proposal check` with the three optional card fields and an open decision-changing unknown -> `plan step0 show` enough no with the
    reason; a survey over the investigation cap is refused and writes nothing; after closing evidence (plan unknown close) and a new check, enough
    yes. A root with `execution-mode` runs two independent nodes in two slots (managed executor, a local worker process): node.started carries the
    mode fields (overlap or run_now with reasons); `engine measure` keeps unobserved values `unknown`. Control: the same root without the
    capability has no mode fields."""
    folder = ctx.case('c step0 mode')
    facts, tail = _scenario(ctx, folder, C_BODY, {'work': str(folder)})
    if facts is None: return False, {'problems': ['the scenario did not finish: ' + tail]}
    problems = []
    if not (facts['open']['enough'] is False and any('unknown_open:U1' == r for r in facts['open']['not_enough'] or [])):
        problems.append('with U1 open the card must say not enough because of it: ' + str(facts['open']))
    if not (facts['survey_over_cap']['exit'] != 0 and facts['survey_over_cap']['events_added'] == 0 and 'cap' in str(facts['survey_over_cap']['answer'])): problems.append('a survey over the cap: ' + str(facts['survey_over_cap']))
    if not (facts['closed']['close_exit'] == 0 and facts['closed']['enough'] is True): problems.append('after closing evidence: ' + str(facts['closed']))
    if not facts['text_card']['says_enough']: problems.append('the text card does not say enough: ' + str(facts['text_card']))
    mode = facts['mode']
    rows = {r['node']: r for r in mode['started']}
    if not (mode['results'].get('A') == 'produced' and mode['results'].get('B') == 'produced' and all(rows.get(n, {}).get('has_mode_fields') for n in ('A', 'B'))
            and {rows['A']['mode'], rows['B']['mode']} <= {'overlap', 'run_now'} and all(rows[n]['mode_reasons'] for n in ('A', 'B'))):
        problems.append('execution-mode root: ' + str(mode))
    if not (facts['measure']['exit'] == 0 and facts['measure']['attempts'] >= 2 and facts['measure']['unknown_fields']):
        problems.append('engine measure: ' + str(facts['measure']))
    control = facts['control']
    if not (control['results'].get('A') == 'produced' and control['started'] and not any(r['has_mode_fields'] for r in control['started'])):
        problems.append('control without the capability: ' + str(control))
    return not problems, dict(facts, problems=problems)


MILESTONE_STEPS = {         # milestone -> [(step id, title, check)]; ONE entry per milestone's steps, in the order they run
    'S1': [('V17-s1-report', 'một lần báo lỗi: cùng key cùng một mã, đúng một sự kiện, bundle có trạng thái hợp lệ, show nói reported/unknown', v17_support_report),
           ('V18-s1-spool', 'sổ hỏng: báo cáo vào spool (cả python -I -m lẫn onecrew.exe), import-spool nhập đúng một lần', v18_support_spool),
           ('V19-s1-counter', 'phản chứng: support confirm bị từ chối trong phiên AI, attempt không tồn tại không tạo attempt', v19_support_counter)],
    'S2': [('V20-s2-target-artifact', 'đích cài là lệnh của chủ (bị từ chối trong phiên AI); wheel có file lạ bị từ chối, wheel của commit đã kiểm được ràng', v20_support_target_artifact),
           ('V21-s2-install', 'không có quyền support_install thì blocked_by_authority; có quyền thì venv mới, điểm an toàn, intent rồi xác nhận, installed theo hook đang chạy', v21_support_install),
           ('V22-s2-recheck-rollback', 'recheck tại đích là node.verification thật, verified_at_target; rollback bị từ chối trong phiên AI; sau rollback của chủ: installed false, rolled_back, still_blocked', v22_support_recheck_rollback)],
    'A': [('V23-a-sources', 'node có sources đọc file ngoài read qua hai lượt trên cây đã ghim; ngoài phạm vi bị từ chối; cursor cây khác bị từ chối; max_rounds giữ node; node không khai sources giữ đúng khóa 2.3', v23_sources)],
    'B': [('V24-b-context', 'knowledge.delivered cho attempt; must bị thu hồi lúc đang chạy thì candidate không được công bố, wiki consumers nêu node; node độc lập vẫn công bố; sau khởi động lại mục chỉ còn trong delta.withdrawn', v24_context)],
    'C': [('V25-c-step0-mode', 'thẻ bước 0: unknown mở thì chưa đủ, khảo sát quá trần bị từ chối, có bằng chứng đóng thì đủ; execution-mode: hai node độc lập có trường chế độ, measure giữ unknown; root không khai thì không có trường', v25_step0_mode)],
}


def finish(report, work):
    report['finished'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    expected = report.get('expected_steps') or REGRESSION_STEPS
    report['result'] = ('pass' if report['steps'] and all(s['result'] == 'pass' for s in report['steps']) and len(report['steps']) == expected
                        and not report.get('unchecked_milestones') else 'fail')
    (work / 'verify-report.json').write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding='utf-8')
    print('RESULT', report['result'], f'{sum(s["result"] == "pass" for s in report["steps"])}/{expected}')
    return 0 if report['result'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2]))
