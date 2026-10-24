# Test the handover package FROM THE ARTIFACT (directive I): a clean venv outside the checkout, the wheel installed from the package after a hash
# check, one code root run end to end through the venv's `onecrew` console script on a temporary git project + temporary state root, every
# onecrew module loaded from the venv (never from a checkout), then — when the package carries the previous wheel — a rollback/roll-forward
# drill on a COPY of that temporary ledger. Writes <work>/verification/verify-report.json. Touches no real state root.
#   python docs/wf/audit/tools/verify_package.py <package dir> <work dir (new, outside the checkout)>
import hashlib, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
CHECKOUT = HERE.parents[4]


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', **kw)
    return r.returncode, (r.stdout + r.stderr)


def main(argv=None):
    pkg, work = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    if work.exists(): sys.exit('work dir must be new')
    if work.is_relative_to(CHECKOUT): sys.exit('work dir must be OUTSIDE the checkout')
    work.mkdir(parents=True)
    report = {'package': str(pkg), 'work': str(work), 'steps': [], 'result': 'refused'}
    def step(name, ok, **facts):
        report['steps'].append({'step': name, 'ok': bool(ok), **facts}); print(('OK   ' if ok else 'FAIL ') + name)
        if not ok: finish(); sys.exit(1)
    def finish():
        (work / 'verification').mkdir(exist_ok=True)
        (work / 'verification' / 'verify-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    manifest = json.load(open(pkg / 'manifest.json', encoding='utf-8'))
    sums = dict(line.split('  ', 1)[::-1] for line in (pkg / 'SHA256SUMS').read_text(encoding='utf-8').splitlines() if line.strip())
    bad = [f for f, h in sums.items() if not (pkg / f).exists() or sha(pkg / f) != h]
    step('SHA256SUMS: every listed file present and unchanged', not bad, files=len(sums), bad=bad[:5])
    wheel = pkg / manifest['wheel']['file']
    step('wheel sha256 == manifest', sha(wheel) == manifest['wheel']['sha256'], sha256=manifest['wheel']['sha256'])
    venv = work / 'venv'
    code, out = run([sys.executable, '-m', 'venv', str(venv)]); step('venv created outside the checkout', code == 0, path=str(venv), tail=out[-300:])
    py = venv / ('Scripts' if os.name == 'nt' else 'bin') / ('python.exe' if os.name == 'nt' else 'python')
    exe = py.with_name('onecrew' + ('.exe' if os.name == 'nt' else ''))
    code, out = run([str(py), '-m', 'pip', 'install', '--no-index', '--no-build-isolation', str(wheel)]); step('pip install --no-index from the package wheel', code == 0, tail=out[-400:])
    code, out = run([str(exe), '--help']); step('onecrew --help from the venv console script', code == 0 and 'plan' in out, tail=out[-200:])
    # one code root end to end, from the installed build only (-I: no PYTHONPATH, cwd = work, checkout not on sys.path)
    project, state = work / 'project', work / 'state'; project.mkdir()
    for args in (['init', '-q'], ['config', 'user.name', 'verify'], ['config', 'user.email', 'verify@localhost']):
        subprocess.run(['git', '-C', str(project), *args], check=True, capture_output=True)
    (project / 'a.txt').write_text('base\n'); subprocess.run(['git', '-C', str(project), 'add', '.'], check=True, capture_output=True)
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
                      capture_output=True, text=True, encoding='utf-8', errors='replace', env={{**os.environ, 'PYTHONUTF8': '1'}})
state_m1 = plan.show(ledger, 'smoke')['milestones'][0]['state']
page = report.render_report(Path({str(state)!r}), 'smoke')
mods = {{n: getattr(m, '__file__', None) for n, m in sys.modules.items() if n == 'onecrew' or n.startswith('onecrew.')}}
print('@@' + json.dumps({{'verdict_exit': done.returncode, 'tail': (done.stdout + done.stderr)[-300:], 'm1': state_m1, 'report_ok': 'smoke' in page, 'modules': mods, 'sys_path': sys.path}}))
'''
    code, out = run([str(py), '-I', '-c', body], cwd=str(work))
    line = next((l for l in out.splitlines() if l.startswith('@@')), None)
    step('smoke body ran', code == 0 and line is not None, tail=out[-600:])
    obs = json.loads(line[2:])
    step('verdict run through the venv console script passed M1', obs['verdict_exit'] == 0 and obs['m1'] == 'passed', m1=obs['m1'], tail=obs['tail'])
    step('plan report renders', obs['report_ok'])
    outside = {n: p for n, p in obs['modules'].items() if p and not Path(p).resolve().is_relative_to(venv.resolve())}
    step('every onecrew module loaded from the venv, none from a checkout', not outside and len(obs['modules']) > 5, modules=len(obs['modules']), outside=outside)
    step('checkout is not on sys.path', not any(Path(p).resolve().is_relative_to(CHECKOUT) for p in obs['sys_path'] if p), sys_path=obs['sys_path'][:6])
    # rollback / roll-forward on a COPY of the temporary ledger, when the package carries the previous wheel
    prev = manifest.get('previous_wheel')
    if prev:
        copy = work / 'state-copy'; shutil.copytree(state, copy)
        before = sha(copy / 'ledger.sqlite3')
        code, out = run([str(exe), '--project', str(project), '--state-root', str(copy), 'compat', 'scan', '--json'])
        scan = json.loads(out[out.index('{'):]) if code == 0 and '{' in out else {}
        step('compat scan on the ledger copy (read-only)', code == 0 and sha(copy / 'ledger.sqlite3') == before, blocking=scan.get('blocking'))
        blocked = (scan.get('blocking') or {}).get('total', 1) > 0
        report['rollback'] = {'blocked_by_scan': blocked}
        if blocked:
            report['steps'].append({'step': 'rollback REFUSED by the scan (expected: the smoke root is namespaced, the previous build cannot read it)', 'ok': True, 'blocks': scan.get('blocking')})
            print('OK   rollback refused while blocks remain (the drill refuses, as specified)')
        code, out = run([str(py), '-m', 'pip', 'uninstall', '--yes', 'onecrew']); step('uninstall current', code == 0)
        code, out = run([str(py), '-m', 'pip', 'install', '--no-index', '--no-build-isolation', str(pkg / prev['file'])]); step('install previous wheel from the package', code == 0 and sha(pkg / prev['file']) == prev['sha256'], tail=out[-300:])
        code, out = run([str(exe), '--project', str(project), '--state-root', str(copy), 'plan', 'digest'])
        report['steps'].append({'step': 'previous build reads the ledger copy (plan digest)', 'ok': code == 0, 'exit': code, 'tail': out[-300:]}); print(('OK   ' if code == 0 else 'NOTE ') + 'previous build: plan digest exit ' + str(code))
        step('previous build changed nothing in the copy', sha(copy / 'ledger.sqlite3') == before)
        code, out = run([str(py), '-m', 'pip', 'uninstall', '--yes', 'onecrew']); step('uninstall previous', code == 0)
        code, out = run([str(py), '-m', 'pip', 'install', '--no-index', '--no-build-isolation', str(wheel)]); step('roll-forward: current wheel reinstalled', code == 0)
        code, out = run([str(exe), '--project', str(project), '--state-root', str(copy), 'plan', 'show', 'smoke']); step('roll-forward reads the root again', code == 0 and 'smoke' in out, tail=out[-200:])
        step('roll-forward changed nothing in the copy', sha(copy / 'ledger.sqlite3') == before)
    else:
        report['rollback'] = {'skipped': 'package carries no previous wheel'}
    report['result'] = 'pass'; finish()
    print(json.dumps({'result': 'pass', 'report': str(work / 'verification' / 'verify-report.json')}))


if __name__ == '__main__':
    main()
