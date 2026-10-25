# Legacy-root continuation, tested FROM THE PACKAGE ARTIFACT (review a2476ab P1-D; directive 25/10 "kiểm chính gói: legacy-root continuation").
#   python docs/wf/audit/tools/legacy_continuation.py <package dir> <work dir (new, outside the checkout)>
#
# What it proves on the installed wheel of the package, in a clean venv outside the checkout, on a throw-away ledger:
#   1. a root created by the OLD build (the package's previous wheel) and approved in the OLD shape (approval row without `at` and without
#      `base_artifact`) continues on the NEW wheel under its OLD semantics (decision 25/10 round 6, verdict.integrity_applies: T19 test
#      integrity applies to workflow roots only; 00 §6 "plan schema 2 giữ nguyên nghĩa", 05 T25 [E4], T13b "root cũ chạy theo semantics cũ"):
#      `verdict run` judges the command result alone -> M1 `passed`, no integrity record, never `inconclusive`;
#   2. the owner's handover page shows O1 as achieved and does NOT name a baseline route as required;
#   3. `verdict baseline` still guards itself: an AI session (ONECREW_ACTOR=claude) and a commit not in the repository are refused, writing
#      nothing; the OWNER records it once with a reference and M1 stays passed with its one verdict; recording again adds nothing;
#   4. nothing else about the root changed: ID, revision, approval rows; the OLD build still reads the root afterwards;
#   5. every onecrew module came from the venv (no checkout shadowing).
# The verdict comes from `judge()` (mandatory steps + negative reasons + encoding-clean tails); the report's own `result` is never trusted,
# and each mandatory step's `ok` is recomputed from its recorded facts (ORACLE): the report supplies observations, never the oracle.
# Codex P1-3: the scope is the package's: judge(report, scope) with scope = package_scope(pkg) (manifest kind + previous wheel verified on disk);
# the report's package identity and previous_wheel_present must agree with it. A declared first-release package is 'not-applicable' (exit 5).
# This tool is deliberately OUTSIDE the pinned kit (wfkit/package_check.py is frozen in the snapshot gate); it reuses the kit's sha/Runner.
import json
import os
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if (_HERE / 'package_check.py').is_file():   # shipped in a handover package (verify/legacy_core.py): the sibling copy, never a checkout
    CHECKOUT = _HERE.parent                  # = the package folder; the work dir must be outside it
    sys.path.insert(0, str(_HERE))
    import package_check as pc  # noqa: E402
else:
    CHECKOUT = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(CHECKOUT))
    from wfkit import package_check as pc  # noqa: E402

REQUIRED = ('wheel_sha', 'venv', 'pip_install', 'old_venv_previous_wheel', 'legacy_root_by_old_build', 'legacy_root_built',
            'legacy_passed_old_semantics', 'legacy_handover_no_baseline_required',
            'baseline_ai_refused', 'baseline_bad_commit_refused', 'baseline_owner_recorded', 'baseline_leaves_verdict_unchanged',
            'legacy_identity_unchanged', 'old_build_reads_after', 'modules_from_venv')
NEGATIVE = {'baseline_ai_refused': 'AI cannot approve', 'baseline_bad_commit_refused': 'rev-parse --verify failed'}   # the product's own refusal texts (real run on wf-handover-6366137, 25/10)
BAD_TAIL = ('UnicodeEncodeError', 'UnicodeDecodeError', "can't encode", 'codec can')

# The oracle (Codex P1-1 principle): which steps are mandatory (REQUIRED) and what each step's `ok` means in terms of its recorded facts
# are fixed HERE. The report supplies observations only; its `mandatory` and `ok` are compared with the oracle and refused when they differ.
_MISSING = object()


class _Facts:
    def __init__(self, step):
        self.step, self.missing = step, []

    def __call__(self, key):
        v = self.step.get(key, _MISSING)
        if v is _MISSING:
            self.missing.append(key)
            return None
        return v


def _exit0(f):
    return f('exit') == 0


def _same(*vals):
    return all(isinstance(v, (str, int)) and not isinstance(v, bool) and v != '' for v in vals) and len(set(vals)) == 1


def _negative_ok(f):
    """A negative step: the command failed, wrote no event and recorded no baseline (the reason text is checked against the tails)."""
    code = f('exit')
    return isinstance(code, int) and code != 0 and f('events_added') == 0 and f('baselines') == 0


def _old_semantics(f):
    """The schema-2 root is judged by the command result alone: pass, M1 passed, NO integrity record (T19 is for workflow roots only)."""
    return _exit0(f) and f('result') == 'pass' and f('m1') == 'passed' and f('integrity') is None


def _o1_achieved(line):
    return isinstance(line, str) and line.strip().startswith('O1 ') and 'đạt' in line and 'chưa' not in line and 'cần kiểm lại' not in line


def _owner_recorded(f):
    rec = f('recorded')
    first = rec[0] if isinstance(rec, list) and len(rec) == 1 and isinstance(rec[0], dict) else {}
    return (_exit0(f) and f('baselines') == 1 and _same(first.get('tree'), f('tree')) and _same(first.get('from_commit'), f('head')))


def _verdict_unchanged(f):
    """After the owner's baseline (and a second, idempotent recording): M1 still passed, still exactly the one `pass` verdict, one baseline."""
    return _exit0(f) and f('m1') == 'passed' and f('verdicts') == ['pass'] and f('baselines') == 1


def _identity(f):
    return (_same(f('anchor'), f('anchor_built'), f('anchor_counted_before'))
            and f('revision') == f('revision_built') == 1 and f('approved_rows') == f('approved_rows_built') == 1)


def _previous(f):
    prev = f('previous')
    return (_exit0(f) and f('venv_exit') == 0 and isinstance(prev, dict) and _same(prev.get('sha256'), f('previous_actual_sha256')))


ORACLE = {
    'wheel_sha': lambda f: _same(f('sha256'), f('actual_sha256')),
    'venv': _exit0,
    'pip_install': _exit0,
    'old_venv_previous_wheel': _previous,
    'legacy_root_by_old_build': _exit0,
    'legacy_root_built': lambda f: _exit0(f) and f('observation') is True,
    'legacy_passed_old_semantics': _old_semantics,
    'legacy_handover_no_baseline_required': lambda f: f('baseline_in_page') is False and _o1_achieved(f('o1_line')),
    'baseline_ai_refused': _negative_ok,
    'baseline_bad_commit_refused': _negative_ok,
    'baseline_owner_recorded': _owner_recorded,
    'baseline_leaves_verdict_unchanged': _verdict_unchanged,
    'legacy_identity_unchanged': _identity,
    'old_build_reads_after': lambda f: _exit0(f) and f('needles') == {'legacy': True},
    'modules_from_venv': lambda f: isinstance(f('modules'), int) and f('modules') > 5 and f('outside') == {},
}
assert set(ORACLE) == set(REQUIRED) and set(NEGATIVE) <= set(REQUIRED)


def judge(report, scope):
    """-> {'result': 'pass'|'refused'|'not-applicable', 'reasons': [...]}. Pure. `scope` = pc.package_scope(pkg) (Codex P1-3): the SCOPE comes
    from the manifest + artifact, never from the report. The legacy root can only be built by the package's previous wheel, so REQUIRED is
    mandatory exactly when the scope says the package carries one; a package of a declared no-previous kind (first release) is
    'not-applicable' (never 'pass') and any step recorded for it is a contradiction (refused). The report's package identity and its
    previous_wheel_present observation must agree with the scope (pc.check_binding). Mandatory steps and their meaning are
    REQUIRED/ORACLE/NEGATIVE (this module's); each mandatory `ok` is recomputed from the step's recorded facts and must agree with the
    recorded `ok`. Refused: a missing, demoted (mandatory != True) or duplicated required step, a step without id, a missing fact, a negative
    step that did not fail for the expected reason, an encoding error in any tail, a step about another wheel than the manifest pins.
    The report's own `result` is only compared."""
    steps = report.get('steps')
    reasons, rollback = pc.check_binding(report, scope)
    if rollback is None:
        return {'result': 'refused', 'reasons': reasons}
    if rollback is False:
        if isinstance(steps, list) and steps:
            reasons.append('legacy continuation steps recorded although the package manifest declares no previous wheel (contradiction)')
        if report.get('result') == 'pass':
            reasons.append('report claims pass for a package without a previous wheel: incoherent')
        return {'result': 'refused', 'reasons': reasons} if reasons else {
            'result': 'not-applicable', 'reasons': [f'package kind {scope.get("kind")!r} declares no previous wheel: no old build can create a legacy root']}
    if not isinstance(steps, list) or not steps:
        return {'result': 'refused', 'reasons': reasons + ['report has no steps']}
    by_id = {}
    for s in steps:
        if not isinstance(s, dict):
            reasons.append('malformed step entry')
            continue
        if not s.get('id'):
            reasons.append('step without id: ' + str(s.get('step')))
            continue
        if s['id'] in by_id:
            reasons.append('duplicate step id (ambiguous): ' + s['id'])
            continue
        by_id[s['id']] = s
    for rid in REQUIRED:
        s = by_id.get(rid)
        if s is None:
            reasons.append('mandatory step missing: ' + rid)
            continue
        if s.get('mandatory', True) is not True:
            reasons.append(f'mandatory step demoted: {rid} (the report says mandatory={s.get("mandatory")!r}; the oracle requires it)')
        f = _Facts(s)
        computed = bool(ORACLE[rid](f))
        if f.missing:
            reasons.append(f'fact missing for step {rid}: {", ".join(dict.fromkeys(f.missing))}')
            continue
        if rid in NEGATIVE:
            if s.get('kind') != 'negative':
                reasons.append(f'negative step {rid} is not recorded as negative')
            if s.get('exit') in (None, 0):
                reasons.append(f'negative step {rid} did not fail the command')
            if NEGATIVE[rid] not in (str(s.get('stdout_tail', '')) + str(s.get('stderr_tail', ''))):
                reasons.append(f'negative step {rid} failed for another reason than expected ({NEGATIVE[rid]!r})')
                computed = False
            if s.get('events_added') != 0:
                reasons.append(f'negative step {rid} wrote events')
        if not computed:
            reasons.append('mandatory step failed: ' + rid)
        if not isinstance(s.get('ok'), bool):
            reasons.append(f'step {rid} records no boolean ok')
        elif s['ok'] != computed:
            reasons.append(f'step {rid}: recorded ok={s["ok"]} disagrees with the recorded facts (ok={computed})')
    w, p = by_id.get('wheel_sha'), by_id.get('old_venv_previous_wheel')
    if w is not None and w.get('sha256') != scope['wheel_sha256']:
        reasons.append('step wheel_sha checked a different wheel than the package manifest pins')
    if p is not None and (p.get('previous') if isinstance(p.get('previous'), dict) else {}).get('sha256') != scope['previous_wheel_sha256']:
        reasons.append('step old_venv_previous_wheel installed a different previous wheel than the package manifest pins')
    for s in steps:
        if not isinstance(s, dict):
            continue
        text = ' '.join(str(s.get(k, '')) for k in pc.TAIL_KEYS)
        if any(b in text for b in BAD_TAIL):
            reasons.append('encoding error in step output: ' + str(s.get('id')))
    claimed = report.get('result')
    if claimed == 'pass' and reasons:
        reasons.append('report claims pass while mandatory steps fail: incoherent')
    return {'result': 'pass' if not reasons else 'refused', 'reasons': reasons}


class Abort(Exception):
    pass


def run(pkg, work, out=print, expected_verifier=None):
    pkg, work = Path(pkg).resolve(), Path(work).resolve()
    if work.exists():
        raise SystemExit('work dir must be new')
    if work.is_relative_to(CHECKOUT):
        raise SystemExit('work dir must be OUTSIDE the checkout')
    work.mkdir(parents=True)
    scope = pc.package_scope(pkg, expected_verifier)        # P1-3: scope from the manifest + artifact, before anything runs
    report = {'tool': 'legacy_continuation', 'package': str(pkg), 'work': str(work), 'package_identity': pc.identity(scope), 'steps': [],
              'result': None, 'previous_wheel_present': None}
    runner = pc.Runner()

    def tails(code=None, so='', se='', **more):
        d = {'stdout_tail': so[-500:], 'stderr_tail': se[-500:]}
        if code is not None:
            d['exit'] = code
        d.update(more)
        return d

    def step(sid, name, ok, **facts):
        report['steps'].append({'id': sid, 'step': name, 'ok': bool(ok), 'mandatory': True, **facts})
        out(('OK   ' if ok else 'FAIL ') + name)
        if not ok:
            raise Abort(name)

    if scope['reasons']:
        out('REFUSED before running: the package manifest/artifact is unverifiable: ' + '; '.join(scope['reasons']))
    else:
        try:
            manifest = json.loads((pkg / 'manifest.json').read_text(encoding='utf-8'))
            report['previous_wheel_present'] = bool(manifest.get('previous_wheel'))      # observation; judge compares it with the scope
            if report['previous_wheel_present']:
                _steps(pkg, work, report, runner, step, tails)
            else:
                out('package carries no previous wheel: legacy continuation is not applicable (no old build can create a legacy root)')
        except Abort as stop:
            out(f'ABORT after failed step: {stop}')
    j = judge(report, scope)
    report['result'], report['judge'] = j['result'], j
    (work / 'verification').mkdir(exist_ok=True)
    path = work / 'verification' / 'legacy-continuation-report.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    out(json.dumps({'result': j['result'], 'reasons': j['reasons'], 'report': str(path)}, ensure_ascii=False))
    return report


def _steps(pkg, work, report, runner, step, tails):
    manifest = json.loads((pkg / 'manifest.json').read_text(encoding='utf-8'))
    wheel = pkg / manifest['wheel']['file']
    actual = pc.sha(wheel)
    step('wheel_sha', 'wheel sha256 == manifest', actual == manifest['wheel']['sha256'], sha256=manifest['wheel']['sha256'], actual_sha256=actual)
    venv = work / 'venv'
    code, so, se = runner.run([sys.executable, '-m', 'venv', venv])
    step('venv', 'venv created outside the checkout', code == 0 and not venv.resolve().is_relative_to(CHECKOUT), path=str(venv), **tails(code, so, se))
    win = os.name == 'nt'
    py = venv / ('Scripts' if win else 'bin') / ('python.exe' if win else 'python')
    exe = py.with_name('onecrew' + ('.exe' if win else ''))
    code, so, se = runner.run([py, '-m', 'pip', 'install', '--no-index', '--no-build-isolation', wheel])
    step('pip_install', 'pip install --no-index from the package wheel', code == 0, **tails(code, so, se))

    project, state = work / 'project', work / 'state'
    project.mkdir()
    for args in (['init', '-q'], ['config', 'user.name', 'verify'], ['config', 'user.email', 'verify@localhost']):
        subprocess.run(['git', '-C', str(project), *args], check=True, capture_output=True)
    (project / 'a.txt').write_text('base\n')
    subprocess.run(['git', '-C', str(project), 'add', '.'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(project), 'commit', '-qm', 'base'], check=True, capture_output=True)
    head = subprocess.run(['git', '-C', str(project), 'rev-parse', 'HEAD'], check=True, capture_output=True, text=True).stdout.strip()
    tree = subprocess.run(['git', '-C', str(project), 'rev-parse', 'HEAD^{tree}'], check=True, capture_output=True, text=True).stdout.strip()
    contract = {'schema_version': 2, 'title': 'Legacy root', 'size': 'S',
                'understanding': {'restated_goal': 'A root approved by an older build.', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']},
                                  'assumptions': [], 'confidence': 'high', 'unknowns': []},
                'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'the file is there'}],
                'output': ['The sample exists'], 'scope': {'owned': ['a.txt']}, 'non_goals': ['Nothing else'],
                'items': [{'id': 'I1', 'title': 'Do it', 'tier': 'must', 'milestone': 'M1'}],
                'milestones': [{'id': 'M1', 'title': 'Milestone M1', 'verifier': {'type': 'command', 'config': {'argv': [str(py), '-c', 'print("ok")']}}, 'covers': ['O1']}],
                'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1}, 'profile_version': None}
    (work / 'contract.json').write_text(json.dumps(contract), encoding='utf-8')

    # The legacy root is created by the OLD build (the package's previous wheel): the current build only creates namespaced roots, so a
    # `plan:` root with a pre-W05 approval can only come from a binary that predates namespaces — exactly the upgrade story being tested.
    prev = manifest.get('previous_wheel')
    old_venv = work / 'venv-old'
    code, so, se = runner.run([sys.executable, '-m', 'venv', old_venv])
    old_py = old_venv / ('Scripts' if win else 'bin') / ('python.exe' if win else 'python')
    old_exe = old_py.with_name('onecrew' + ('.exe' if win else ''))
    venv_exit = code
    prev_actual = pc.sha(pkg / prev['file']) if prev and (pkg / prev['file']).is_file() else None
    ok = bool(prev) and code == 0 and prev_actual == prev['sha256']
    if ok:
        code, so, se = runner.run([old_py, '-m', 'pip', 'install', '--no-index', '--no-build-isolation', pkg / prev['file']])
        ok = code == 0
    step('old_venv_previous_wheel', 'previous wheel of the package (sha256 == manifest) installed in a second venv', ok,
         previous=prev, venv_exit=venv_exit, previous_actual_sha256=prev_actual, **tails(code, so, se))
    code, so, se = runner.run([old_exe, '--project', str(project), '--state-root', str(state), 'plan', 'propose', 'legacy', '--file', str(work / 'contract.json'),
                               '--author', 'old-build-fixture'])
    step('legacy_root_by_old_build', 'the OLD build proposed the root (legacy `plan:` namespace)', code == 0, **tails(code, so, se))
    common = f'''
import json, os, sys, sqlite3, subprocess
for key in ('ONECREW_ACTOR', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(key, None)
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.v2 import plan, report
PROJECT, STATE, EXE = Path({str(project)!r}), Path({str(state)!r}), {str(exe)!r}
ledger = Ledger(PROJECT, STATE)
def db(): return sqlite3.connect(str(STATE / 'ledger.sqlite3'))
def anchor():
    return db().execute('SELECT id FROM tasks WHERE project_id=? AND request_key=?', (ledger.project_id, 'plan:legacy')).fetchone()[0]
def events():
    return [(r[0], json.loads(r[1])) for r in db().execute('SELECT kind, payload FROM events WHERE task_id=? ORDER BY seq', (anchor(),))]
def state_of():
    with ledger.transaction() as conn:
        return plan.anchor_events(ledger, conn, 'plan:legacy')
def verdict_run():
    done = subprocess.run([EXE, '--project', str(PROJECT), '--state-root', str(STATE), 'verdict', 'run', '--plan', 'plan:legacy', '--milestone', 'M1'],
                          capture_output=True, text=True, encoding='utf-8', errors='replace', env={{**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}})
    st = state_of(); last = st['verdicts'][-1] if st['verdicts'] else {{}}
    return {{'exit': done.returncode, 'tail': (done.stdout + done.stderr)[-300:], 'm1': plan.show(ledger, 'plan:legacy')['milestones'][0]['state'],
            'result': last.get('result'), 'integrity': last.get('test_integrity')}}
def emit(obj): print('@@' + json.dumps(obj))
'''
    body_a = common + '''
a = anchor()                                                    # created by the old build above; must be the legacy namespace
assert 'plan:legacy' in [r[0] for r in db().execute('SELECT request_key FROM tasks WHERE id=?', (a,))], 'not a legacy root'
proposed = next(p for k, p in events() if k == 'plan.proposed')
c = db()
c.execute('INSERT INTO events(task_id, kind, payload, created_at) VALUES (?,?,?,?)', (a, 'plan.approved',
          json.dumps({'plan': 'legacy', 'revision': 1, 'sha': proposed['sha'], 'by': 'owner', 'reference': 'fixture (pre-W05 approval shape)',
                      'ticked': [], 'chosen': None, 'base_artifact': None}), '2000-01-01T00:00:00+00:00'))
c.commit()
st = state_of()
first = verdict_run()
page = report.render_handover(STATE, 'legacy', project_id=ledger.project_id)
mods = {n: getattr(m, '__file__', None) for n, m in sys.modules.items() if n == 'onecrew' or n.startswith('onecrew.')}
emit({'anchor': a, 'revision': st['latest'], 'approved_rows': sum(1 for k, _ in events() if k == 'plan.approved'), 'kinds': [k for k, _ in events()],
      'first': first, 'baseline_in_page': 'baseline' in page, 'o1_line': next((l for l in page.splitlines() if l.strip().startswith('O1 ')), ''),
      'modules': mods})
'''
    code, so, se = runner.run([py, '-I', '-c', body_a, str(work / 'contract.json')], cwd=str(work))
    line = next((l for l in so.splitlines() if l.startswith('@@')), None)
    step('legacy_root_built', 'legacy root (old approval shape, approval before every commit) built on the installed wheel', code == 0 and line is not None,
         observation=line is not None, **tails(code, so, se))
    a = json.loads(line[2:])
    first = a['first']
    step('legacy_passed_old_semantics', 'new wheel: verdict run judges the schema-2 root by the command result (M1 passed, no integrity record, not inconclusive)',
         _old_semantics(_Facts(first)), **first)
    step('legacy_handover_no_baseline_required', 'handover page shows O1 achieved and names no baseline route',
         a['baseline_in_page'] is False and _o1_achieved(a['o1_line']), o1_line=a['o1_line'], baseline_in_page=a['baseline_in_page'])

    def baseline(commit, reference, extra_env=None):
        env = dict(runner.env)
        env.update(extra_env or {})
        r = subprocess.run([str(exe), '--project', str(project), '--state-root', str(state), 'verdict', 'baseline', '--plan', 'plan:legacy',
                            '--from-commit', commit, '--by', 'owner', '--reference', reference],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', env=env)
        return r.returncode, r.stdout, r.stderr

    body_count = common + '''
ev = events()
emit({'n': len(ev), 'baselines': [p for k, p in ev if k == 'plan.baseline_recorded'], 'approved_rows': sum(1 for k, _ in ev if k == 'plan.approved'),
      'anchor': anchor(), 'revision': state_of()['latest'], 'verdicts': [v.get('result') for v in state_of()['verdicts']],
      'm1': plan.show(ledger, 'plan:legacy')['milestones'][0]['state']})
'''

    def count():
        c, o, e = runner.run([py, '-I', '-c', body_count], cwd=str(work))
        l = next((x for x in o.splitlines() if x.startswith('@@')), None)
        if c != 0 or l is None:
            raise Abort('counting events failed: ' + (o + e)[-300:])
        return json.loads(l[2:])

    before = count()
    code, so, se = baseline(head, 'AI tries', {'ONECREW_ACTOR': 'claude'})
    after = count()
    step('baseline_ai_refused', 'an AI session (ONECREW_ACTOR=claude) cannot record the baseline', code != 0 and after['n'] == before['n'] and not after['baselines'],
         kind='negative', events_added=after['n'] - before['n'], baselines=len(after['baselines']), **tails(code, so, se))
    code, so, se = baseline('deadbeefdeadbeefdeadbeefdeadbeefdeadbeef', 'owner with a commit that is not in the repo')
    after = count()
    step('baseline_bad_commit_refused', 'a commit that is not in the repository is refused', code != 0 and after['n'] == before['n'] and not after['baselines'],
         kind='negative', events_added=after['n'] - before['n'], baselines=len(after['baselines']), **tails(code, so, se))
    code, so, se = baseline(head, 'legacy continuation check on a throw-away ledger (not an owner action)')
    after = count()
    step('baseline_owner_recorded', 'the owner records the baseline from a real commit with a reference (one plan.baseline_recorded, tree of that commit)',
         code == 0 and len(after['baselines']) == 1 and after['baselines'][0].get('tree') == tree and after['baselines'][0].get('from_commit') == head,
         recorded=after['baselines'][:1], baselines=len(after['baselines']), tree=tree, head=head, **tails(code, so, se))
    code, so, se = baseline(head, 'recorded again (idempotent)')
    final = count()
    step('baseline_leaves_verdict_unchanged', 'after the baseline (recorded twice): M1 still passed with its one verdict; one baseline only',
         code == 0 and final['m1'] == 'passed' and final['verdicts'] == ['pass'] and len(final['baselines']) == 1,
         m1=final['m1'], verdicts=final['verdicts'], baselines=len(final['baselines']), **tails(code, so, se))
    step('legacy_identity_unchanged', 'root ID, revision and approval rows unchanged',
         final['anchor'] == a['anchor'] == before['anchor'] and final['revision'] == a['revision'] == 1 and final['approved_rows'] == a['approved_rows'] == 1,
         anchor=final['anchor'], revision=final['revision'], approved_rows=final['approved_rows'], anchor_built=a['anchor'],
         anchor_counted_before=before['anchor'], revision_built=a['revision'], approved_rows_built=a['approved_rows'])
    code, so, se = runner.run([old_exe, '--project', str(project), '--state-root', str(state), 'plan', 'show', 'legacy'])
    step('old_build_reads_after', 'the OLD build still reads the root after the new build ran it (plan show legacy)', code == 0 and 'legacy' in so,
         needles={'legacy': 'legacy' in so}, **tails(code, so, se))
    outside = {n: p for n, p in a['modules'].items() if p and not Path(p).resolve().is_relative_to(venv.resolve())}
    step('modules_from_venv', 'every onecrew module loaded from the venv, none from a checkout', not outside and len(a['modules']) > 5, modules=len(a['modules']), outside=outside)


def main(argv=None, verifier_files=None):
    """Exit 0 = pass, 1 = refused, 5 = not applicable (the package kind declares no previous wheel; not a pass)."""
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(__doc__ or 'usage: legacy_continuation.py <package dir> <work dir>')
        return 2
    rep = run(argv[0], argv[1], expected_verifier=verifier_files)
    return {'pass': 0, 'not-applicable': 5}.get(rep['result'], 1)


if __name__ == '__main__':
    sys.exit(main())
