# Legacy-root continuation, tested FROM THE PACKAGE ARTIFACT (review a2476ab P1-D; directive 25/10 "kiểm chính gói: legacy-root continuation").
#   python docs/wf/audit/tools/legacy_continuation.py <package dir> <work dir (new, outside the checkout)>
#
# What it proves on the installed wheel of the package, in a clean venv outside the checkout, on a throw-away ledger:
#   1. a root approved in the OLD shape (approval row without `at` and without `base_artifact`, ledger time before every commit of the
#      project) is NOT passed by default: the command verdict is `inconclusive`, the milestone is not passed, and the owner's handover
#      page names the route (`onecrew verdict baseline ...`);
#   2. an AI session cannot record the baseline (ONECREW_ACTOR=claude is refused); a commit that is not in the repository is refused;
#   3. the OWNER records the baseline with a reference; the same milestone then passes; recording again is idempotent;
#   4. nothing else about the root changed: ID, revision, the approval rows, the earlier inconclusive verdict stay as they were;
#   5. every onecrew module came from the venv (no checkout shadowing).
# The verdict comes from `judge()` (mandatory steps + negative reasons + encoding-clean tails); the report's own `result` is never trusted,
# and each mandatory step's `ok` is recomputed from its recorded facts (ORACLE): the report supplies observations, never the oracle.
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

REQUIRED = ('wheel_sha', 'venv', 'pip_install', 'old_venv_previous_wheel', 'legacy_root_by_old_build', 'legacy_root_built', 'legacy_inconclusive_not_passed', 'legacy_route_in_handover',
            'baseline_ai_refused', 'baseline_bad_commit_refused', 'baseline_owner_recorded', 'legacy_passed_after_baseline',
            'legacy_identity_unchanged', 'modules_from_venv')
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


def _inconclusive(f):
    integ = f('integrity')
    integ = integ if isinstance(integ, dict) else {}
    return (f('result') == 'inconclusive' and f('m1') != 'passed' and integ.get('classification') == 'insufficient'
            and 'no approved baseline' in str(integ.get('error', '')))


def _owner_recorded(f):
    rec = f('recorded')
    first = rec[0] if isinstance(rec, list) and len(rec) == 1 and isinstance(rec[0], dict) else {}
    return (_exit0(f) and f('baselines') == 1 and _same(first.get('tree'), f('tree')) and _same(first.get('from_commit'), f('head')))


def _identity(f):
    verdicts = f('verdicts')
    return (_exit0(f) and _same(f('anchor'), f('anchor_built'), f('anchor_counted_before'))
            and f('revision') == f('revision_built') == 1 and f('approved_rows') == f('approved_rows_built') == 1
            and isinstance(verdicts, list) and verdicts[:1] == ['inconclusive'] and verdicts[-1:] == ['pass'] and f('baselines') == 1)


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
    'legacy_inconclusive_not_passed': _inconclusive,
    'legacy_route_in_handover': lambda f: f('route_in_page') is True and isinstance(f('o1_line'), str) and ' đạt ' not in f('o1_line'),
    'baseline_ai_refused': _negative_ok,
    'baseline_bad_commit_refused': _negative_ok,
    'baseline_owner_recorded': _owner_recorded,
    'legacy_passed_after_baseline': lambda f: f('m1') == 'passed' and f('result') == 'pass',
    'legacy_identity_unchanged': _identity,
    'modules_from_venv': lambda f: isinstance(f('modules'), int) and f('modules') > 5 and f('outside') == {},
}
assert set(ORACLE) == set(REQUIRED) and set(NEGATIVE) <= set(REQUIRED)


def judge(report):
    """-> {'result': 'pass'|'refused', 'reasons': [...]}. Pure. Mandatory steps and their meaning are REQUIRED/ORACLE/NEGATIVE (this module's);
    each mandatory `ok` is recomputed from the step's recorded facts and must agree with the recorded `ok`. Refused: a missing, demoted
    (mandatory != True) or duplicated required step, a step without id, a missing fact, a negative step that did not fail for the expected
    reason, an encoding error in any tail. The report's own `result` is only compared."""
    steps = report.get('steps')
    if not isinstance(steps, list) or not steps:
        return {'result': 'refused', 'reasons': ['report has no steps']}
    by_id, reasons = {}, []
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


def run(pkg, work, out=print):
    pkg, work = Path(pkg).resolve(), Path(work).resolve()
    if work.exists():
        raise SystemExit('work dir must be new')
    if work.is_relative_to(CHECKOUT):
        raise SystemExit('work dir must be OUTSIDE the checkout')
    work.mkdir(parents=True)
    report = {'tool': 'legacy_continuation', 'package': str(pkg), 'work': str(work), 'steps': [], 'result': None}
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

    try:
        _steps(pkg, work, report, runner, step, tails)
    except Abort as stop:
        out(f'ABORT after failed step: {stop}')
    j = judge(report)
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
      'first': first, 'route_in_page': ('verdict baseline' in page) and ('baseline' in page), 'o1_line': next((l for l in page.splitlines() if l.strip().startswith('O1 ')), ''),
      'modules': mods})
'''
    code, so, se = runner.run([py, '-I', '-c', body_a, str(work / 'contract.json')], cwd=str(work))
    line = next((l for l in so.splitlines() if l.startswith('@@')), None)
    step('legacy_root_built', 'legacy root (old approval shape, approval before every commit) built on the installed wheel', code == 0 and line is not None,
         observation=line is not None, **tails(code, so, se))
    a = json.loads(line[2:])
    first = a['first']
    step('legacy_inconclusive_not_passed', 'first verdict is inconclusive (insufficient integrity, no approved baseline) and M1 is NOT passed',
         first['result'] == 'inconclusive' and first['m1'] != 'passed' and (first.get('integrity') or {}).get('classification') == 'insufficient'
         and 'no approved baseline' in str((first.get('integrity') or {}).get('error', '')), **first)
    step('legacy_route_in_handover', 'handover page names the owner route (`onecrew verdict baseline`) and does not mark O1 as achieved',
         a['route_in_page'] and ' đạt ' not in a['o1_line'], o1_line=a['o1_line'], route_in_page=a['route_in_page'] is True)

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
      'anchor': anchor(), 'revision': state_of()['latest'], 'verdicts': [v.get('result') for v in state_of()['verdicts']]})
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
    body_run = common + '''
emit(verdict_run())
'''
    code, so, se = runner.run([py, '-I', '-c', body_run], cwd=str(work))
    line = next((l for l in so.splitlines() if l.startswith('@@')), None)
    if code != 0 or line is None:
        raise Abort('second verdict run failed: ' + (so + se)[-300:])
    second = json.loads(line[2:])
    step('legacy_passed_after_baseline', 'the same milestone passes once the baseline is recorded', second['m1'] == 'passed' and second['result'] == 'pass', **second)
    code, so, se = baseline(head, 'recorded again (idempotent)')
    final = count()
    step('legacy_identity_unchanged', 'root ID, revision and approval rows unchanged; the earlier inconclusive verdict is kept; recording again adds nothing',
         final['anchor'] == a['anchor'] == before['anchor'] and final['revision'] == a['revision'] == 1 and final['approved_rows'] == a['approved_rows'] == 1
         and final['verdicts'][:1] == ['inconclusive'] and final['verdicts'][-1] == 'pass' and len(final['baselines']) == 1 and code == 0,
         anchor=final['anchor'], revision=final['revision'], verdicts=final['verdicts'], baselines=len(final['baselines']),
         approved_rows=final['approved_rows'], anchor_built=a['anchor'], anchor_counted_before=before['anchor'], revision_built=a['revision'],
         approved_rows_built=a['approved_rows'], **tails(code, so, se))
    outside = {n: p for n, p in a['modules'].items() if p and not Path(p).resolve().is_relative_to(venv.resolve())}
    step('modules_from_venv', 'every onecrew module loaded from the venv, none from a checkout', not outside and len(a['modules']) > 5, modules=len(a['modules']), outside=outside)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(__doc__ or 'usage: legacy_continuation.py <package dir> <work dir>')
        return 2
    rep = run(argv[0], argv[1])
    return 0 if rep['result'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
