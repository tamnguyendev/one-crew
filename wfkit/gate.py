"""The delivery gate (WK00 / T45a): `python wfkit/gate.py <release> --out <receipt folder>`.

What one run does, in order:
  (a) kit-guard verify: refuse when a pinned kit or test file changed or vanished (unless a U1 covers it);
  (b) build the wheel ONCE from the current commit (tests/wf_wheel.py) and take its sha256;
  (c) run every testcase of the release (wfkit/testcases.json), each into its own receipt JSON: testcase, release, commit, wheel sha256,
      command, tests run / passed / errors / skipped, result, time. Tests that build a wheel get THAT wheel through WF_WHEEL (+ WF_WHEEL_SHA256),
      and WF_WHEEL_USED_LOG records which wheel they really used;
  (d) decide: the gate passes only when every required testcase of the release has a receipt, passed, on the same commit and the same wheel hash;
      otherwise it refuses and names every reason (missing receipt, not pass, different hash, kit-guard, ...);
  (e) the install scenario: the built wheel is installed offline into a fresh venv and the scenario runs from the INSTALLED command; the
      path of every onecrew module actually loaded is recorded. A run that loads onecrew from the checkout is refused (T45a E5, E7), and a
      control run from the checkout must be refused too, or the check proves nothing.

`--decide-only` re-judges receipts already in the folder (no test is run). `--allow-simulated` is for the kit's self-test only: a real gate
refuses receipts marked "simulated", which prove the RULE and nothing about a build.

The gate asks for no testcase of a later release.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wfkit import doccheck, kitguard                      # noqa: E402

TEST_TIMEOUT = 3000                                       # seconds per test command; a hang is an 'error' receipt, not a silent pass

_SCENARIO = (
    'import json, sys, sysconfig\n'
    'import onecrew, onecrew.v2, onecrew.v2.cli, onecrew.v2.compat, onecrew.v2.plan\n'
    'mods = {n: getattr(m, "__file__", None) for n, m in sorted(sys.modules.items()) if n == "onecrew" or n.startswith("onecrew.")}\n'
    'site = sorted({sysconfig.get_paths()[k] for k in ("purelib", "platlib")})\n'
    'print("@@" + json.dumps({"modules": mods, "site": site, "sys_path": sys.path, "executable": sys.executable}))\n')


def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _norm(path):
    return os.path.normcase(os.path.normpath(str(path)))


def _under(path, base):
    p, b = _norm(path), _norm(base)
    return p == b or p.startswith(b.rstrip('\\/') + os.sep)


def _write(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=True) + '\n', encoding='utf-8', newline='\n')


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


# ---- (e) install origin ------------------------------------------------------------------------------------------------------

def install_scenario(python, *, cwd=None, flags=('-I',), env_extra=None):
    """Run the install scenario with `python` and report which onecrew module files were really loaded."""
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONSTARTUP', 'PYTHONHOME') and not k.startswith('WF_')}
    env.update(env_extra or {})
    r = subprocess.run([str(python), *flags, '-c', _SCENARIO], capture_output=True, text=True, encoding='utf-8', errors='replace',
                       env=env, cwd=str(cwd) if cwd else None)
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith('@@')), None)
    if line is None:
        return {'modules': {}, 'site': [], 'returncode': r.returncode, 'stderr': (r.stdout + r.stderr)[-600:]}
    rep = json.loads(line[2:])
    rep['returncode'] = r.returncode
    return rep


def judge_origin(report, checkout):
    """Problems (empty = accepted) with where the onecrew modules of a scenario run were loaded from: all of them must lie under the
    installed site-packages; anything under the checkout (or anywhere else) is a refusal."""
    mods = report.get('modules') or {}
    if not mods:
        return ['no onecrew module was loaded: ' + str(report.get('stderr') or 'nothing to judge')[-200:]]
    site = report.get('site') or []
    problems = []
    for name, path in sorted(mods.items()):
        if not path:
            problems.append(f'{name}: no file (cannot tell where it was loaded from)')
        elif any(_under(path, s) for s in site):
            continue
        elif _under(path, checkout):
            problems.append(f'{name} loaded from the checkout: {path}')
        else:
            problems.append(f'{name} loaded from neither the installed site-packages nor the checkout: {path}')
    return problems


def check_install(python, checkout, workdir):
    """The installed scenario must be accepted AND the same scenario run from the checkout must be refused (the control)."""
    wd = Path(workdir)
    installed = install_scenario(python, cwd=wd)
    problems = judge_origin(installed, checkout)
    control = install_scenario(python, cwd=wd, flags=(), env_extra={'PYTHONPATH': str(checkout)})
    control_problems = judge_origin(control, checkout)
    return {'ok': not problems, 'problems': problems, 'loaded': installed.get('modules', {}), 'site': installed.get('site', []),
            'control_refused': bool(control_problems), 'control_problems': control_problems[:5], 'control_loaded': control.get('modules', {}),
            'checkout': str(checkout)}


# ---- (d) the decision --------------------------------------------------------------------------------------------------------

def _counts_pass(r, allow_skips, allow_expected=0):
    """A receipt passes on its counts: no failure or error, no unexpected success, skips and expected failures only as far as its testcase allows
    (`allow_skips`, `allow_expected_failures`, both 0 when absent), and every other test passed. An expected failure is not a passed test (Codex review
    of beta 2.3.0.dev9, P2)."""
    run, passed, errors, skipped, expected, unexpected = (int(r.get(k) or 0) for k in (
        'tests_run', 'tests_passed', 'tests_errors', 'tests_skipped', 'tests_expected_failures', 'tests_unexpected_successes'))
    return (r.get('result') == 'pass' and run > 0 and errors == 0 and unexpected == 0 and skipped <= allow_skips and expected <= allow_expected
            and passed >= 1 and passed == run - skipped - expected)


def decide(release, config, build, receipts, install, kit, *, allow_simulated=False):
    """Judge a release gate from facts only. Returns {'decision': 'pass'|'refused', 'reasons': [{code, testcase?, detail}], ...}."""
    reasons = []

    def why(code, detail, testcase=None):
        reasons.append({'code': code, 'testcase': testcase, 'detail': detail})

    rel = (config.get('releases') or {}).get(release)
    ref = build.get('wheel_sha256')
    if rel is None:
        why('unknown-release', f'{release} is not in testcases.json')
        rel = {'testcases': {}}
    if build.get('release') not in (None, release):
        why('build-release', f"the build was made for {build.get('release')}, not {release}")
    if not ref:
        why('no-wheel', 'no wheel hash from the build')
    if build.get('dirty'):
        why('dirty', 'the working tree differs from the commit; the wheel is not the commit: ' + '; '.join(build['dirty'][:5]))
    if not kit.get('ok'):
        for p in kit.get('problems') or [{'code': 'unknown'}]:
            why('kit-guard', json.dumps(p, ensure_ascii=False, sort_keys=True))
    simulated = False
    for tc, entry in rel['testcases'].items():
        if entry.get('optional'):
            continue
        r = receipts.get(tc)
        if r is None or r.get('release') != release or r.get('testcase') != tc:
            why('missing-receipt', f'no receipt for {tc} on {release}', tc)
            continue
        if r.get('simulated'):
            simulated = True
            if not allow_simulated:
                why('simulated-receipt', 'a simulated receipt proves the rule only, not a build', tc)
        if r.get('commit') != build.get('commit'):
            why('commit', f"{tc} ran on commit {r.get('commit')}, the gate is on {build.get('commit')}", tc)
        if r.get('wheel_sha256') != ref:
            why('wheel-hash', f"{tc} receipt is for wheel {r.get('wheel_sha256')}, the gate built {ref}", tc)
        for used in r.get('wheel_used') or []:
            if used != ref:
                why('wheel-hash', f'{tc} actually used wheel {used}, the gate built {ref}', tc)
        if entry.get('kind') == 'doccheck':
            kg = r.get('kit_guard') or {}
            cx = r.get('counterexamples') or {}
            if not (r.get('result') == 'pass' and r.get('problems') == 0 and kg.get('ok') and r.get('block_sha256')
                    and not cx.get('missed') and not cx.get('wrong_reason')):
                why('not-pass', f"{tc}: {r.get('reason') or r.get('result')}", tc)
        elif not _counts_pass(r, int(entry.get('allow_skips', 0)), int(entry.get('allow_expected_failures', 0))):
            why('not-pass', f"{tc}: result={r.get('result')} run={r.get('tests_run')} passed={r.get('tests_passed')} "
                            f"errors={r.get('tests_errors')} skipped={r.get('tests_skipped')} expected_failures={r.get('tests_expected_failures')} "
                            f"unexpected_successes={r.get('tests_unexpected_successes')}", tc)
    if not install or not install.get('ok'):
        why('run-from-checkout', 'install scenario not accepted: ' + '; '.join((install or {}).get('problems') or ['no install scenario recorded']))
    else:
        if not install.get('control_refused'):
            why('run-from-checkout', 'the control run from the checkout was not refused, so the origin check cannot tell install from checkout')
        if install.get('wheel_sha256') not in (None, ref):
            why('wheel-hash', f"the installed wheel is {install.get('wheel_sha256')}, the gate built {ref}")
    # 'gate' is the delivery-gate id (CG-<release>) that wfkit.release_check's gate_history rule requires; commit + wheel_sha256 are the
    # finalgate.identity fields of the build this gate judged.
    return {'gate': 'CG-' + str(release), 'release': release, 'decision': 'refused' if reasons else 'pass', 'reasons': reasons, 'commit': build.get('commit'),
            'wheel_sha256': ref, 'u1_used': kit.get('u1_used') or [], 'manifest_sha256': kit.get('manifest_sha256'),
            'simulated_receipts_used': simulated, 'simulated': simulated,
            'provenance': {'kind': 'fixture' if simulated else 'real', 'source': 'wfkit.gate decide (release delivery gate)'},
            'proves': 'the gate rule only (simulated receipts)' if simulated else 'the release gate on real receipts of this build',
            'installed_modules': (install or {}).get('loaded', {}), 'at': _now()}


# ---- (c) running the testcases -----------------------------------------------------------------------------------------------

def parse_unittest(text):
    """The counts of a unittest run from its summary line: failures and errors together, skipped, expected failures and unexpected successes apart,
    and passed = the rest. `failures=` is matched as a whole key, never inside `expected failures=` (Codex review of beta 2.3.0.dev9, P2)."""
    run = re.search(r'^Ran (\d+) tests? in', text, re.M)
    n = int(run.group(1)) if run else 0
    m = re.search(r'^FAILED \((.*)\)\s*$', text, re.M) or re.search(r'^OK(?: \((.*)\))?\s*$', text, re.M)
    summary = (m.group(1) or '') if m else ''

    def count(key):
        return sum(int(x) for x in re.findall(r'(?:^|, )' + key + r'=(\d+)', summary))
    errors, skipped = count('failures') + count('errors'), count('skipped')
    expected, unexpected = count('expected failures'), count('unexpected successes')
    return {'ran': bool(run), 'run': n, 'errors': errors, 'skipped': skipped, 'expected_failures': expected, 'unexpected_successes': unexpected,
            'passed': max(0, n - errors - skipped - expected - unexpected)}


def _git(root, *args):
    r = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8', errors='replace')
    return r.stdout.strip() if r.returncode == 0 else None


def run_unittests(root, modules, wheel, wheel_sha, out_dir, tag, python):
    root = Path(root)
    used_log = Path(out_dir) / 'runs' / f'{tag}.wheel-used'
    used_log.parent.mkdir(parents=True, exist_ok=True)
    if used_log.exists():
        used_log.unlink()
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join([str(root), str(root / 'tests')])
    env.update({'WF_WHEEL': str(wheel), 'WF_WHEEL_SHA256': wheel_sha, 'WF_WHEEL_USED_LOG': str(used_log)})
    cmd = [str(python), '-m', 'unittest', *modules]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=str(root), env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=TEST_TIMEOUT)
        text, code = r.stdout + r.stderr, r.returncode
    except subprocess.TimeoutExpired as e:
        text = ((e.stderr or b'').decode('utf-8', 'replace') if isinstance(e.stderr, bytes) else (e.stderr or '')) + f'\nTIMEOUT after {TEST_TIMEOUT}s'
        code = None
    (Path(out_dir) / 'runs' / f'{tag}.log').write_text(text, encoding='utf-8')
    p = parse_unittest(text)
    used = sorted(set(used_log.read_text(encoding='utf-8').split())) if used_log.exists() else []
    result = ('pass' if (code == 0 and p['ran'] and p['run'] > 0 and p['errors'] == 0 and p['unexpected_successes'] == 0)
              else ('error' if (code is None or not p['ran']) else 'fail'))
    return {'command': ' '.join(['python', '-m', 'unittest', *modules]), 'python': str(python), 'exit_code': code, 'seconds': round(time.time() - t0, 1),
            'tests_run': p['run'], 'tests_passed': p['passed'], 'tests_errors': p['errors'], 'tests_skipped': p['skipped'],
            'tests_expected_failures': p['expected_failures'], 'tests_unexpected_successes': p['unexpected_successes'],
            'result': result, 'wheel_used': used, 'output_tail': text[-800:], 'log': f'runs/{tag}.log'}


def config_path(root):
    return Path(root) / kitguard.CONFIG


def load_receipts(out_dir):
    d = Path(out_dir) / 'receipts'
    return {p.stem: _read(p) for p in sorted(d.glob('*.json'))} if d.is_dir() else {}


def dirty_files(root, out_dir):
    status = _git(root, 'status', '--porcelain', '--untracked-files=normal')
    if status is None:
        return ['git status unavailable']
    out = []
    for line in status.splitlines():
        rel = line[3:].strip().strip('"')
        if rel and not _under(Path(root) / rel, out_dir):
            out.append(line.strip())
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog='gate', description='release delivery gate: kit-guard, one wheel, every testcase receipted, decision')
    ap.add_argument('release')
    ap.add_argument('--out', required=True, help='folder for the receipts and the decision (outside the repository)')
    ap.add_argument('--root', default=str(ROOT), help='repository root (only for --decide-only; a run always uses this checkout)')
    ap.add_argument('--doc-dir', default=os.environ.get('WF_DOC_DIR', doccheck.DEFAULT_DOC_DIR))
    ap.add_argument('--decide-only', action='store_true', help='judge the receipts already in --out; run nothing')
    ap.add_argument('--allow-simulated', action='store_true', help='kit self-test only: accept receipts marked simulated')
    ap.add_argument('--only', default=None, help='development aid: run only these testcases (comma separated); the gate then cannot pass')
    ap.add_argument('--allow-dirty', action='store_true', help='run on a dirty tree for development; the decision still refuses')
    a = ap.parse_args(argv)
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    root = Path(a.root).resolve()
    if not a.decide_only and root != ROOT:
        print(f'refused: a gate run uses its own checkout ({ROOT}); --root is for --decide-only', file=sys.stderr)
        return 2
    config = _read(config_path(root))
    if a.release not in config.get('releases', {}):
        print(f'refused: {a.release} is not in {kitguard.CONFIG}', file=sys.stderr)
        return 2
    rel = config['releases'][a.release]
    doc_dir = a.doc_dir if a.doc_dir and Path(a.doc_dir).is_dir() else None

    # (a) kit-guard
    kit = kitguard.verify(root, [a.release], doc_dir=doc_dir)
    _write(out / 'kitguard.json', kit)
    print(f"kit-guard: {'ok' if kit['ok'] else 'REFUSED'} ({kit['pinned']} pins, {len(kit['u1_used'])} U1 used)")
    for p in kit['problems']:
        print('  ', p['code'], p.get('pin'), p.get('detail') or '')

    if not a.decide_only:
        # (b) one wheel
        os.environ.pop('WF_WHEEL', None)
        import tests.wf_wheel as wh
        commit = _git(root, 'rev-parse', 'HEAD')
        dirty = dirty_files(root, out)
        if dirty and not a.allow_dirty:
            print('the working tree is dirty; the wheel would not be the commit:', *dirty[:8], sep='\n  ')
        wheel_dir = out / 'wheel'
        wheel_dir.mkdir(exist_ok=True)
        for old in wheel_dir.glob('*.whl'):
            old.unlink()
        wheel, version, _ = wh.build_wheel(wheel_dir)
        wheel_sha = hashlib.sha256(Path(wheel).read_bytes()).hexdigest()
        build = {'release': a.release, 'commit': commit, 'dirty': dirty, 'wheel': str(wheel), 'wheel_sha256': wheel_sha, 'version': version,
                 'built_at': _now(), 'python': sys.executable}
        _write(out / 'build.json', build)
        print(f'build: commit {commit} wheel {Path(wheel).name} sha256 {wheel_sha}')
        if dirty and not a.allow_dirty:
            _write(out / 'decision.json', decide(a.release, config, build, {}, {}, kit, allow_simulated=a.allow_simulated))
            return 1

        # (e) the install scenario on a fresh venv, with the control from the checkout
        work = Path(tempfile.gettempdir()) / 'wfgate' / uuid.uuid4().hex[:6]
        work.mkdir(parents=True)
        try:
            py = wh.make_venv(work)
            wh.install(py, wheel)
            install = check_install(py, root, work)
        except Exception as e:                                   # noqa: BLE001 - an unusable install is a refusal with its reason
            install = {'ok': False, 'problems': [f'install scenario failed: {type(e).__name__}: {e}'], 'control_refused': False}
        install['wheel_sha256'] = wheel_sha
        _write(out / 'install-scenario.json', install)
        print(f"install scenario: {'accepted' if install['ok'] else 'REFUSED'}; control from checkout "
              f"{'refused' if install.get('control_refused') else 'NOT refused'}; loaded {len(install.get('loaded') or {})} onecrew modules")

        # (c) every testcase, one receipt each
        only = set(a.only.split(',')) if a.only else None
        done_groups = {}
        for tc, entry in rel['testcases'].items():
            if only and tc not in only:
                continue
            stamp = {'testcase': tc, 'release': a.release, 'commit': commit, 'wheel_sha256': wheel_sha, 'at': _now(),
                     'manifest_sha256': kit.get('manifest_sha256'), 'u1_used': [u['id'] for u in kit['u1_used']]}
            if entry.get('kind') == 'doccheck':
                rec = doccheck.run(a.doc_dir, root)
                rec.update(stamp)
            else:
                mods = tuple(entry['modules'])
                if mods not in done_groups:
                    print(f"run {' '.join(mods)} ...", flush=True)
                    done_groups[mods] = run_unittests(root, mods, wheel, wheel_sha, out, '+'.join(m.split('.')[-1] for m in mods), sys.executable)
                rec = dict(done_groups[mods])
                rec.update(stamp)
                rec['shared_run_with'] = [t for t, e in rel['testcases'].items() if tuple(e.get('modules', ())) == mods and t != tc]
            _write(out / 'receipts' / f'{tc}.json', rec)
            print(f"  {tc}: {rec['result']}" + (f" ({rec.get('tests_passed')}/{rec.get('tests_run')})" if 'tests_run' in rec else ''))
        if only:
            print('--only was used: no decision is written')
            return 1

    # (d) the decision
    build = _read(out / 'build.json')
    install = _read(out / 'install-scenario.json') if (out / 'install-scenario.json').is_file() else {}
    dec = decide(a.release, config, build, load_receipts(out), install, kit, allow_simulated=a.allow_simulated)
    _write(out / 'decision.json', dec)
    print(f"GATE {a.release}: {dec['decision'].upper()}  commit {dec['commit']}  wheel {dec['wheel_sha256']}")
    for r in dec['reasons']:
        print(f"  - {r['code']}" + (f" [{r['testcase']}]" if r.get('testcase') else '') + f": {r['detail']}")
    for u in dec['u1_used']:
        print(f"  U1 used: {u['id']} {u['file']}")
    return 0 if dec['decision'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
