"""Verify a handover package FROM THE ARTIFACT, and judge the result from the recorded facts (Codex review P1).

Two halves:

  judge(report)  pure. Recomputes the overall result from the MANDATORY steps only. It never trusts the report's own `result`: a report that
                 claims `pass` while a mandatory step is ok=false (or a rollback fact is wrong) is REFUSED as incoherent. A deliberate negative
                 test is modelled as an expectation (exit codes + the reason text it must show); failing for a DIFFERENT reason (encoding
                 error, missing exe, traceback) is a failure, never a pass.
  run(pkg, work) the runner: clean venv outside the checkout, wheel installed after a hash check, one code root through the venv console
                 script, every onecrew module loaded from the venv, then the rollback drill on TWO ledger copies: `state-blocked` (the scan
                 reports a block, so rollback must be REFUSED with zero pip install/uninstall) and `state-clear` (0 blocks, rollback allowed,
                 old build reads, roll-forward restores the same installed build).

Every child runs with a UTF-8 environment; stdout/stderr tails are recorded; an unexpected nonzero exit or a traceback in any step fails the check.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

CHECKOUT = Path(__file__).resolve().parents[1]

# Markers that are never an acceptable outcome of any child (a negative test must not "pass" by crashing).
FORBIDDEN_MARKERS = ('UnicodeEncodeError', 'UnicodeDecodeError', 'Traceback (most recent call last)', "codec can't encode", "codec can't decode")
TAIL_KEYS = ('tail', 'stdout_tail', 'stderr_tail')

BASE_REQUIRED = ('sha256sums', 'wheel_sha', 'venv', 'pip_install', 'help', 'smoke_body', 'verdict_run', 'plan_report', 'modules_from_venv',
                 'checkout_not_on_path')
ROLLBACK_REQUIRED = ('blocked_copy_built', 'blocked_scan', 'blocked_refused_no_pip', 'blocked_installed_unchanged', 'blocked_copy_unchanged',
                     'clear_scan', 'clear_uninstall_current', 'clear_install_previous', 'clear_old_digest', 'clear_old_cannot_read_plan_ns',
                     'clear_old_copy_unchanged', 'clear_uninstall_previous', 'clear_reinstall_current', 'clear_same_build_restored',
                     'clear_roll_forward_reads', 'clear_roll_forward_copy_unchanged')


def rollback_decision(blocking_total):
    """The one rule: any block in the scan refuses the rollback."""
    return 'refused' if blocking_total > 0 else 'allowed'


def _text(step):
    return '\n'.join(str(step.get(k, '')) for k in TAIL_KEYS)


def judge(report):
    """-> {'result': 'pass'|'refused', 'reasons': [...]}. Derived from mandatory steps only; the report's own `result` is only compared."""
    reasons = []
    steps = report.get('steps')
    if not isinstance(steps, list) or not steps:
        return {'result': 'refused', 'reasons': ['report has no steps']}
    by_id = {}
    for s in steps:
        if isinstance(s, dict) and s.get('id'):
            by_id.setdefault(s['id'], s)
    required = list(BASE_REQUIRED)
    if report.get('previous_wheel_present') is True:
        required += list(ROLLBACK_REQUIRED)
    elif report.get('previous_wheel_present') is not False:
        reasons.append('report does not say whether the package carries a previous wheel (previous_wheel_present)')
    required += [i for i in (report.get('expected_steps') or []) if i not in required]
    for rid in required:
        if rid not in by_id:
            reasons.append(f'expected step missing: {rid}')
    for s in steps:
        if not isinstance(s, dict):
            reasons.append('malformed step entry')
            continue
        name = s.get('step') or s.get('id') or '?'
        mandatory = s.get('mandatory', True) is not False       # a step without the flag is mandatory
        if not mandatory:
            continue
        text = _text(s)
        for marker in FORBIDDEN_MARKERS:
            if marker in text:
                reasons.append(f'step "{name}" shows "{marker}" in its output')
                break
        if s.get('ok') is not True:
            reasons.append(f'mandatory step failed: {name}')
        expect = s.get('expect')
        if s.get('kind') == 'negative':
            if not isinstance(expect, dict) or not expect.get('exits') or not expect.get('reason_any'):
                reasons.append(f'negative test "{name}" has no expectation (exits + reason_any)')
            else:
                if s.get('exit') not in expect['exits']:
                    reasons.append(f'negative test "{name}" exited {s.get("exit")}, expected one of {expect["exits"]}')
                if not any(m in text for m in expect['reason_any']):
                    reasons.append(f'negative test "{name}" failed for a different reason (none of {expect["reason_any"]} in its output)')
        elif 'exit' in s and s['exit'] != 0:
            reasons.append(f'unexpected nonzero exit {s["exit"]} in step "{name}"')
    reasons += _judge_rollback(report.get('rollback'), report.get('previous_wheel_present'))
    result = 'refused' if reasons else 'pass'
    claimed = report.get('result')
    if claimed in ('pass', 'refused') and claimed != result:
        reasons.append(f'incoherent report: it claims "{claimed}" but the recorded facts give "{result}"')
        result = 'refused'
    return {'result': result, 'reasons': reasons}


def _judge_rollback(rb, present):
    if present is not True:
        return []
    if not isinstance(rb, dict):
        return ['rollback facts missing although the package carries a previous wheel']
    out = []
    blocked, clear = rb.get('blocked'), rb.get('clear')
    if not isinstance(blocked, dict):
        out.append('rollback: the blocked branch was not exercised')
    else:
        total = blocked.get('scan_total')
        if not (isinstance(total, int) and total > 0):
            out.append('rollback: the blocked copy has no block (scan total must be > 0)')
        if blocked.get('decision') != 'refused' or blocked.get('decision') != rollback_decision(total if isinstance(total, int) else 0):
            out.append('rollback: a scan with blocks must REFUSE the rollback')
        if blocked.get('pip_invocations') != 0:
            out.append(f'rollback refused branch ran {blocked.get("pip_invocations")} pip install/uninstall (must be 0)')
        if not blocked.get('installed_before') or blocked.get('installed_before') != blocked.get('installed_after'):
            out.append('rollback refused branch changed the installed build')
        if not blocked.get('copy_before') or blocked.get('copy_before') != blocked.get('copy_after'):
            out.append('rollback refused branch changed the ledger copy')
    if not isinstance(clear, dict):
        out.append('rollback: the allowed branch was not exercised')
    else:
        if clear.get('scan_total') != 0:
            out.append('rollback: the clear copy must have 0 blocks')
        if clear.get('decision') != 'allowed':
            out.append('rollback: a scan with 0 blocks must allow the rollback')
        if not isinstance(clear.get('pip_invocations'), int) or clear['pip_invocations'] < 4:
            out.append('rollback allowed branch must uninstall/install twice (previous, then current)')
        if not clear.get('installed_before') or clear.get('installed_before') != clear.get('installed_after'):
            out.append('roll-forward did not restore the same installed build')
        if not clear.get('copy_before') or clear.get('copy_before') != clear.get('copy_after'):
            out.append('rollback allowed branch changed the ledger copy')
    return out


# ---------------------------------------------------------------------------------------------------------------------------------
# runner

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree_sha(root):
    """Content hash of every file under root (names + bytes)."""
    h = hashlib.sha256()
    root = Path(root)
    for p in sorted(x for x in root.rglob('*') if x.is_file()):
        h.update(p.relative_to(root).as_posix().encode('utf-8'))
        h.update(b'\0')
        h.update(sha(p).encode())
        h.update(b'\n')
    return h.hexdigest()


def installed_fingerprint(venv):
    """Hash of the installed onecrew build: its package .py files and dist-info metadata under the venv's site-packages."""
    h = hashlib.sha256()
    sites = [p for p in [Path(venv) / 'Lib' / 'site-packages', *Path(venv).glob('lib/python*/site-packages')] if p.is_dir()]
    for site in sites:
        files = list((site / 'onecrew').rglob('*.py')) if (site / 'onecrew').is_dir() else []
        for d in site.glob('onecrew-*.dist-info'):
            files += [d / 'METADATA', d / 'WHEEL', d / 'entry_points.txt']      # not RECORD: it lists the .pyc files each run compiled
        for p in sorted(f for f in files if f.is_file()):
            h.update(p.relative_to(site).as_posix().encode('utf-8'))
            h.update(b'\0')
            h.update(sha(p).encode())
            h.update(b'\n')
    return h.hexdigest()


class Runner:
    """Runs children with a UTF-8 environment, keeps tails, and counts pip install/uninstall invocations."""

    def __init__(self):
        self.pip_invocations = 0
        env = dict(os.environ)
        for key in ('ONECREW_ACTOR', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'PYTHONPATH', 'PYTHONHOME'):
            env.pop(key, None)
        env.update({'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'})
        self.env = env

    def run(self, cmd, **kw):
        argv = [str(c) for c in cmd]
        if len(argv) > 3 and argv[1:3] == ['-m', 'pip'] and ('install' in argv[3:] or 'uninstall' in argv[3:]):
            self.pip_invocations += 1
        r = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8', errors='replace', env=self.env, **kw)
        return r.returncode, r.stdout, r.stderr


class Abort(Exception):
    pass


def run(pkg, work, out=print):
    pkg, work = Path(pkg).resolve(), Path(work).resolve()
    if work.exists():
        raise SystemExit('work dir must be new')
    if work.is_relative_to(CHECKOUT):
        raise SystemExit('work dir must be OUTSIDE the checkout')
    work.mkdir(parents=True)
    report = {'package': str(pkg), 'work': str(work), 'steps': [], 'result': None, 'previous_wheel_present': None}
    runner = Runner()

    def tails(code=None, so='', se=''):
        d = {'stdout_tail': so[-500:], 'stderr_tail': se[-500:]}
        if code is not None:
            d['exit'] = code
        return d

    def step(sid, name, ok, **facts):
        report['steps'].append({'id': sid, 'step': name, 'ok': bool(ok), 'mandatory': True, **facts})
        out(('OK   ' if ok else 'FAIL ') + name)
        if not ok:
            raise Abort(name)

    try:
        _verify(pkg, work, report, runner, step, tails, out)
    except Abort as stop:
        out(f'ABORT after failed step: {stop}')
    j = judge(report)
    report['result'], report['judge'] = j['result'], j
    (work / 'verification').mkdir(exist_ok=True)
    (work / 'verification' / 'verify-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    out(json.dumps({'result': j['result'], 'reasons': j['reasons'], 'report': str(work / 'verification' / 'verify-report.json')}, ensure_ascii=False))
    return report


def _verify(pkg, work, report, runner, step, tails, out):
    manifest = json.loads((pkg / 'manifest.json').read_text(encoding='utf-8'))
    sums = dict(line.split('  ', 1)[::-1] for line in (pkg / 'SHA256SUMS').read_text(encoding='utf-8').splitlines() if line.strip())
    bad = [f for f, h in sums.items() if not (pkg / f).exists() or sha(pkg / f) != h]
    step('sha256sums', 'SHA256SUMS: every listed file present and unchanged', not bad, files=len(sums), bad=bad[:5])
    wheel = pkg / manifest['wheel']['file']
    step('wheel_sha', 'wheel sha256 == manifest', sha(wheel) == manifest['wheel']['sha256'], sha256=manifest['wheel']['sha256'])
    venv = work / 'venv'
    code, so, se = runner.run([sys.executable, '-m', 'venv', venv])
    step('venv', 'venv created outside the checkout', code == 0 and not venv.resolve().is_relative_to(CHECKOUT), path=str(venv), **tails(code, so, se))
    win = os.name == 'nt'
    py = venv / ('Scripts' if win else 'bin') / ('python.exe' if win else 'python')
    exe = py.with_name('onecrew' + ('.exe' if win else ''))
    pip_cur = [py, '-m', 'pip', 'install', '--no-index', '--no-build-isolation', wheel]
    code, so, se = runner.run(pip_cur)
    step('pip_install', 'pip install --no-index from the package wheel', code == 0, **tails(code, so, se))
    code, so, se = runner.run([exe, '--help'])
    step('help', 'onecrew --help from the venv console script', code == 0 and 'plan' in so, **tails(code, so, se))

    project, state = work / 'project', work / 'state'
    project.mkdir()
    for args in (['init', '-q'], ['config', 'user.name', 'verify'], ['config', 'user.email', 'verify@localhost']):
        subprocess.run(['git', '-C', str(project), *args], check=True, capture_output=True)
    (project / 'a.txt').write_text('base\n')
    subprocess.run(['git', '-C', str(project), 'add', '.'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(project), 'commit', '-qm', 'base'], check=True, capture_output=True)
    contract = {'schema_version': 2, 'title': 'Package smoke', 'size': 'S',
                'understanding': {'restated_goal': 'Smoke the installed build.', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']}, 'assumptions': [], 'confidence': 'high', 'unknowns': []},
                'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'the file is there'}],
                'output': ['The sample exists'], 'scope': {'owned': ['a.txt']}, 'non_goals': ['Nothing else'],
                'items': [{'id': 'I1', 'title': 'Do it', 'tier': 'must', 'milestone': 'M1'}],
                'milestones': [{'id': 'M1', 'title': 'Milestone M1', 'verifier': {'type': 'command', 'config': {'argv': [str(py), '-c', 'print("ok")']}}, 'covers': ['O1']}],
                'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1}, 'profile_version': None}
    (work / 'contract.json').write_text(json.dumps(contract), encoding='utf-8')
    body = f'''
import json, os, sys, subprocess
for key in ('ONECREW_ACTOR', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(key, None)
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.v2 import plan, verdict, report
ledger = Ledger(Path({str(project)!r}), Path({str(state)!r}))
plan.propose(ledger, 'smoke', json.load(open({str(work / 'contract.json')!r}, encoding='utf-8')), 'package-verify', workflow=True)
plan.approve(ledger, 'smoke', 'owner', 'package smoke on a temporary ledger; not an owner action')
done = subprocess.run([{str(exe)!r}, '--project', {str(project)!r}, '--state-root', {str(state)!r}, 'verdict', 'run', '--plan', 'smoke', '--milestone', 'M1'],
                      capture_output=True, text=True, encoding='utf-8', errors='replace', env={{**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}})
state_m1 = plan.show(ledger, 'smoke')['milestones'][0]['state']
page = report.render_report(Path({str(state)!r}), 'smoke')
mods = {{n: getattr(m, '__file__', None) for n, m in sys.modules.items() if n == 'onecrew' or n.startswith('onecrew.')}}
print('@@' + json.dumps({{'verdict_exit': done.returncode, 'tail': (done.stdout + done.stderr)[-300:], 'm1': state_m1, 'report_ok': 'smoke' in page, 'modules': mods, 'sys_path': sys.path}}))
'''
    code, so, se = runner.run([py, '-I', '-c', body], cwd=str(work))
    line = next((l for l in so.splitlines() if l.startswith('@@')), None)
    step('smoke_body', 'smoke body ran', code == 0 and line is not None, **tails(code, so, se))
    obs = json.loads(line[2:])
    step('verdict_run', 'verdict run through the venv console script passed M1', obs['verdict_exit'] == 0 and obs['m1'] == 'passed',
         m1=obs['m1'], tail=obs['tail'], exit=obs['verdict_exit'])
    step('plan_report', 'plan report renders', obs['report_ok'])
    outside = {n: p for n, p in obs['modules'].items() if p and not Path(p).resolve().is_relative_to(venv.resolve())}
    step('modules_from_venv', 'every onecrew module loaded from the venv, none from a checkout', not outside and len(obs['modules']) > 5,
         modules=len(obs['modules']), outside=outside)
    step('checkout_not_on_path', 'checkout is not on sys.path', not any(Path(p).resolve().is_relative_to(CHECKOUT) for p in obs['sys_path'] if p),
         sys_path=obs['sys_path'][:6])

    prev = manifest.get('previous_wheel')
    report['previous_wheel_present'] = bool(prev)
    if not prev:
        report['rollback'] = {'skipped': 'package carries no previous wheel'}
        return
    _rollback(pkg, work, report, runner, step, tails, out, venv=venv, py=py, exe=exe, project=project, state=state, prev=prev, pip_cur=pip_cur)


def _scan(runner, exe, project, copy):
    code, so, se = runner.run([exe, '--project', project, '--state-root', copy, 'compat', 'scan', '--json'])
    scan = {}
    if code == 0 and '{' in so:
        try:
            scan = json.loads(so[so.index('{'):])
        except ValueError:
            scan = {}
    return code, so, se, scan


def _rollback(pkg, work, report, runner, step, tails, out, *, venv, py, exe, project, state, prev, pip_cur):
    rb = report['rollback'] = {}
    blocked_dir, clear_dir = work / 'state-blocked', work / 'state-clear'
    shutil.copytree(state, clear_dir)
    shutil.copytree(state, blocked_dir)
    # (a) a REAL block built with the installed build's own APIs: a second plan, approved and not accepted, exports an approved active plan
    # the previous build cannot see (compat_scan B1). The venv body is the product itself; nothing is edited by hand.
    body = f'''
import json
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.v2 import plan
ledger = Ledger(Path({str(project)!r}), Path({str(blocked_dir)!r}))
c = json.load(open({str(work / 'contract.json')!r}, encoding='utf-8')); c['title'] = 'Open plan that blocks rollback'
plan.propose(ledger, 'blocked-open', c, 'package-verify', workflow=True)
plan.approve(ledger, 'blocked-open', 'owner', 'package verify: an approved, unaccepted root on a temporary ledger copy; not an owner action')
print('built')
'''
    code, so, se = runner.run([py, '-I', '-c', body], cwd=str(work))
    step('blocked_copy_built', 'state-blocked: approved, unaccepted root added with the installed build', code == 0 and 'built' in so, **tails(code, so, se))

    # ---- refused branch (blocked copy) ----
    code, so, se, scan = _scan(runner, exe, project, blocked_dir)
    total = (scan.get('blocking') or {}).get('total', 0) if scan else 0
    step('blocked_scan', 'compat scan on state-blocked reports blocks', code == 0 and total > 0, blocking=scan.get('blocking'),
         block_ids=sorted({b['id'] for r in scan.get('roots', []) for b in r.get('blocks', [])}), **tails(code, so, se))
    decision = rollback_decision(total)
    fp_before, copy_before, pips_before = installed_fingerprint(venv), tree_sha(blocked_dir), runner.pip_invocations
    if decision == 'refused':
        out('rollback refused: the scan has blockers; no uninstall/install runs in this branch')
    else:                                            # unreachable: the step above fails first
        raise Abort('blocked copy has no block; the refused branch cannot be shown')
    fp_after, copy_after, pips = installed_fingerprint(venv), tree_sha(blocked_dir), runner.pip_invocations - pips_before
    rb['blocked'] = {'copy': str(blocked_dir), 'scan_total': total, 'decision': decision, 'pip_invocations': pips,
                     'installed_before': fp_before, 'installed_after': fp_after, 'copy_before': copy_before, 'copy_after': copy_after}
    step('blocked_refused_no_pip', 'rollback refused on the blocked copy: 0 pip uninstall/install invocations', decision == 'refused' and pips == 0, pip_invocations=pips)
    step('blocked_installed_unchanged', 'refused branch: installed build unchanged', fp_before == fp_after, installed=fp_after)
    step('blocked_copy_unchanged', 'refused branch: nothing in state-blocked changed', copy_before == copy_after, tree_sha=copy_after)

    # ---- allowed branch (clear copy) ----
    code, so, se, scan = _scan(runner, exe, project, clear_dir)
    total = (scan.get('blocking') or {}).get('total', 1) if scan else 1
    step('clear_scan', 'compat scan on state-clear reports 0 blocks', code == 0 and total == 0, blocking=scan.get('blocking'), **tails(code, so, se))
    decision = rollback_decision(total)
    fp_before, copy_before, pips_before = installed_fingerprint(venv), tree_sha(clear_dir), runner.pip_invocations
    code, so, se = runner.run([py, '-m', 'pip', 'uninstall', '--yes', 'onecrew'])
    step('clear_uninstall_current', 'uninstall current', code == 0, **tails(code, so, se))
    prev_wheel = pkg / prev['file']
    code, so, se = runner.run([py, '-m', 'pip', 'install', '--no-index', '--no-build-isolation', prev_wheel])
    step('clear_install_previous', 'install previous wheel from the package', code == 0 and sha(prev_wheel) == prev['sha256'], **tails(code, so, se))
    # The previous build predates plan namespaces: `plan digest` lists only legacy roots, so it exits 0 and the namespaced root is NOT listed.
    code, so, se = runner.run([exe, '--project', project, '--state-root', clear_dir, 'plan', 'digest'])
    step('clear_old_digest', 'previous build: plan digest exits 0 (legacy roots only; the namespaced smoke root is not listed)',
         code == 0 and 'smoke' not in so, **tails(code, so, se))
    # Deliberate negative test: the previous build cannot read the plan-ns root. It must fail BECAUSE no such plan exists for it.
    code, so, se = runner.run([exe, '--project', project, '--state-root', clear_dir, 'plan', 'show', 'smoke'])
    expect = {'exits': [1, 2], 'reason_any': ['No plan named']}
    ok = code in expect['exits'] and any(m in so + se for m in expect['reason_any']) and not any(m in so + se for m in FORBIDDEN_MARKERS)
    step('clear_old_cannot_read_plan_ns', 'previous build cannot read the plan-ns root (plan show smoke refused: No plan named)', ok,
         kind='negative', expect=expect, **tails(code, so, se))
    step('clear_old_copy_unchanged', 'previous build changed nothing in state-clear', tree_sha(clear_dir) == copy_before)
    code, so, se = runner.run([py, '-m', 'pip', 'uninstall', '--yes', 'onecrew'])
    step('clear_uninstall_previous', 'uninstall previous', code == 0, **tails(code, so, se))
    code, so, se = runner.run(pip_cur)
    step('clear_reinstall_current', 'roll-forward: current wheel reinstalled', code == 0, **tails(code, so, se))
    fp_after = installed_fingerprint(venv)
    step('clear_same_build_restored', 'roll-forward restored the identical installed build', fp_after == fp_before, installed=fp_after)
    code, so, se = runner.run([exe, '--project', project, '--state-root', clear_dir, 'plan', 'show', 'smoke'])
    step('clear_roll_forward_reads', 'roll-forward reads the root again', code == 0 and 'smoke' in so, **tails(code, so, se))
    copy_after = tree_sha(clear_dir)
    step('clear_roll_forward_copy_unchanged', 'roll-forward changed nothing in state-clear', copy_after == copy_before)
    rb['clear'] = {'copy': str(clear_dir), 'scan_total': total, 'decision': decision, 'pip_invocations': runner.pip_invocations - pips_before,
                   'installed_before': fp_before, 'installed_after': fp_after, 'copy_before': copy_before, 'copy_after': copy_after}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        sys.exit('usage: verify_package.py <package dir> <work dir (new, outside the checkout)>')
    return 0 if run(argv[0], argv[1])['result'] == 'pass' else 1
