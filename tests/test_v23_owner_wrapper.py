"""Codex review of 2.3.0.dev5, finding P2-A: the owner's one-command test (thu-goi-dev5.ps1) printed DAT and exited 0 after the first-task drill had
REFUSED to run (its folder was not empty) and the script had read the OLD drill log. docs/v23/tools/thu_goi.ps1 replaces it. It reports PASS only
when the required steps of THIS run succeeded, from reports that belong to this run, this package and this wheel; a failing command, a missing
report or an old report never becomes PASS; the exit code is right for the person and for a calling tool (0 only on PASS, 1 = ran or checked and
failed, 2 = refused to start).

The wrapper runs here under Windows PowerShell 5.1 against a STUB package: a manifest, a wheel whose sha256 it states, and two stub tools that
behave at the interface of verify_milestone.py / first_task_drill.py as the test tells them through environment variables. Every case that must not
pass asserts the exit code AND that no `DAT:` line is printed, and that the output names the reason (so a case cannot fail by accident).
The Codex case is also run on a verbatim copy of the old script (only its hard-coded paths adapted): RED there (DAT, exit 0), GREEN on the wrapper.
Packaging: build_milestone.py ships the wrapper as verify/thu-goi.ps1 and its README names the command (test at the end, no PowerShell needed).
Each wrapper run costs seconds (PowerShell + two Python starts), so the table-driven cases run side by side."""
import collections
import concurrent.futures
import contextlib
import hashlib
import importlib.util
import io
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / 'docs' / 'v23' / 'tools' / 'thu_goi.ps1'
BUILD = ROOT / 'docs' / 'v23' / 'tools' / 'build_milestone.py'
POWERSHELL = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
WINDOWS = sys.platform == 'win32' and POWERSHELL.is_file()
PASS_LINE = re.compile(r'^DAT: ', re.M)           # "KHONG DAT: ..." contains "DAT:" but never starts a line with it
VERSION = '2.3.0.dev5'
WHEEL = f'onecrew-{VERSION}-py3-none-any.whl'
COMMIT = 'b3ecc57795713f57d01e77c4f26ff8ece20583df'
Run = collections.namedtuple('Run', 'code out work calls')
DEFAULT = object()

# The stub of both package tools. Role by file name; behaviour from STUB_<ROLE>_SPEC (JSON):
#   exit (int, default 0) - the exit code;  write (bool, default true) - write the report;  mtime - set the report's last-write time to this epoch value;
#   set {dotted.path: value} - change the report (list indexes allowed);  delete [dotted.path] - remove keys;  fail_steps [ids] - those steps fail
# like the real tools: the verifier accepts an existing folder, the drill refuses a folder that already holds anything (exit 1, no log).
STUB = r'''import json
import os
import sys
import time
from pathlib import Path

role = 'drill' if Path(__file__).stem == 'first_task_drill' else 'verify'
spec = json.loads(os.environ.get('STUB_%s_SPEC' % role.upper()) or '{}')
pkg, work = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
if os.environ.get('STUB_CALLS'):
    with open(os.environ['STUB_CALLS'], 'a', encoding='utf-8') as handle:
        handle.write(json.dumps({'role': role, 'argv': sys.argv[1:]}) + '\n')
print('stub %s start' % role, flush=True)
if role == 'drill' and work.exists() and any(work.iterdir()):
    raise SystemExit('%s is not empty; a drill folder is never reused.' % work)
work.mkdir(parents=True, exist_ok=True)
manifest = json.loads((pkg / 'manifest.json').read_text(encoding='utf-8'))


def stamp():
    return time.strftime('%Y-%m-%dT%H:%M:%S')


if role == 'verify':
    name = 'verify-report.json'
    steps = [{'id': 'V%d-stub' % n, 'result': 'pass'} for n in range(1, 13)]
    report = {'kind': 'v23-milestone-verify-report', 'package': str(pkg), 'started': stamp(), 'steps': steps,
              'manifest': {k: manifest.get(k) for k in ('milestone', 'version', 'code_commit', 'wheel', 'previous_wheel', 'claims')}}
    report.update(finished=stamp(), expected_steps=12, result='pass')
else:
    name = 'first-task-drill-log.json'
    mode = os.environ.get('STUB_OWNER_MODE', 'real')
    names = ['links', 'location', 'vars', 'venv', 'repo', 'wiki-page', 'wiki-pages', 'contract', 'propose', 'present']
    names += ['approve'] if mode == 'real' else ['approve-literal-refused', 'approve-parse', 'approve-fixture']
    names += ['revise', 'show-package', 'fake-install', 'fake-env', 'fake-check', 'real-check', 'step-c', 'verify-c', 'step-i', 'verify-i', 'state', 'drill-cmd']
    steps = [{'id': n, 'kind': 'info' if n in ('real-check', 'drill-cmd') else 'run', 'result': 'pass'} for n in names]
    report = {'kind': 'first-task-drill-log', 'package': str(pkg), 'work': str(work), 'started': stamp(), 'owner_step_mode': mode,
              'in_ai_session': mode == 'fixture', 'manifest': {k: manifest.get(k) for k in ('milestone', 'version', 'code_commit', 'claims')},
              'steps': steps, 'onecrew_version': manifest['version']}
    report.update(finished=stamp(), package_unchanged=True, result='pass')
for step in steps:
    if step['id'] in spec.get('fail_steps', []):
        step['result'] = 'fail'


def walk(path):
    node, keys = report, path.split('.')
    for key in keys[:-1]:
        node = node[int(key)] if isinstance(node, list) else node[key]
    return node, keys[-1]


for path, value in spec.get('set', {}).items():
    node, last = walk(path)
    node[int(last) if isinstance(node, list) else last] = value
for path in spec.get('delete', []):
    node, last = walk(path)
    del node[int(last) if isinstance(node, list) else last]
if spec.get('write', True):
    target = work / name
    target.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding='utf-8')
    if 'mtime' in spec:
        os.utime(target, (spec['mtime'], spec['mtime']))
print('RESULT stub %s' % role)
sys.exit(spec.get('exit', 0))
'''

# thu-goi-dev5.ps1 as the owner ran it (D:/OneCrewRuns/v23/thu-goi-dev5.ps1, review evidence), verbatim.
LEGACY_DEV5 = r"""# thu-goi-dev5.ps1 - owner test of OneCrew 2.3.0.dev5 FROM THE PACKAGE, on new folders and a temporary ledger.
# It never touches the real ledger, running roots, hook-projects.json, PATH or provider settings.
# Steps: 1 wheel hash, 2 the 12-step package verifier, 3 the first task from the package README (fake claude, temporary ledger;
# outside an AI session the README's "onecrew owner approve" runs as written, on that temporary ledger only).
param([string]$Work = '')
$py   = 'C:\Users\NUC\AppData\Local\Programs\Python\Python313\python.exe'
$pkg  = 'D:\OneCrewRuns\v23\pkg\onecrew-2.3.0.dev5-final'
$want = 'da500499a86daea1635b7ea61c9a77f40a203e2df87fd0653c1db707b7fd8b89'
if ($Work) { $work = $Work } else { $work = 'D:\OneCrewRuns\v23 thu cua anh dev5 ' + (Get-Date -Format 'yyyyMMdd-HHmmss') }
New-Item -ItemType Directory -Force $work | Out-Null

$h = (Get-FileHash -Algorithm SHA256 "$pkg\wheel\onecrew-2.3.0.dev5-py3-none-any.whl").Hash.ToLower()
Write-Host "1. wheel sha256 = $h"
if ($h -ne $want) { Write-Host 'KHONG DAT: hash wheel khac manifest'; exit 1 }

Write-Host '2. Bo kiem 12 buoc tu goi (khoang 3-6 phut)...'
& $py -I "$pkg\verify\verify_milestone.py" $pkg "$work\verify" | Out-Host
$v = Get-Content "$work\verify\verify-report.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$vpass = @($v.steps | Where-Object { $_.result -eq 'pass' }).Count
Write-Host ("   ket qua: {0}, buoc dat {1}/{2}" -f $v.result, $vpass, $v.expected_steps)

Write-Host '3. Task dau tien tu README cua goi (claude gia, so tam rieng; khoang 2-4 phut)...'
& $py -I "$pkg\verify\first_task_drill.py" $pkg "$work\task dau tien" --owner-step auto | Out-Host
$d = Get-Content "$work\task dau tien\first-task-drill-log.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$dreq  = @($d.steps | Where-Object { $_.kind -ne 'info' })
$dpass = @($dreq | Where-Object { $_.result -eq 'pass' }).Count
Write-Host ("   ket qua: {0}, buoc bat buoc dat {1}/{2}, buoc duyet plan: {3}" -f $d.result, $dpass, $dreq.Count, $d.owner_step_mode)

if ($v.result -eq 'pass' -and $d.result -eq 'pass') {
    Write-Host 'DAT: goi 2.3.0.dev5 qua bo kiem 12 buoc va task dau tien tu goi.'
} else {
    Write-Host 'KHONG DAT: xem verify-report.json va first-task-drill-log.json trong thu muc duoi.'
}
Write-Host "Thu muc ket qua: $work"
"""
LEGACY_HARDCODED = (r"C:\Users\NUC\AppData\Local\Programs\Python\Python313\python.exe", r"D:\OneCrewRuns\v23\pkg\onecrew-2.3.0.dev5-final",
                    'da500499a86daea1635b7ea61c9a77f40a203e2df87fd0653c1db707b7fd8b89')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(folder):
    """Every file (its sha256) and folder (None) below `folder`."""
    return {p.relative_to(folder).as_posix(): sha256(p) if p.is_file() else None for p in sorted(Path(folder).rglob('*'))}


def read_calls(path):
    """The tools the stubs recorded, in order: ['verify', 'drill', ...]."""
    if not Path(path).is_file():
        return []
    return [json.loads(line)['role'] for line in Path(path).read_text(encoding='utf-8').splitlines()]


def make_package(root, version=VERSION):
    """A package the wrapper accepts: manifest.json, the wheel it states (+ previous/), the two stub tools, and the wrapper where it ships."""
    wheel_name = f'onecrew-{version}-py3-none-any.whl'
    (root / 'wheel' / 'previous').mkdir(parents=True)
    (root / 'verify').mkdir()
    wheel = root / 'wheel' / wheel_name
    wheel.write_bytes(b'stub wheel of the owner wrapper test\n' * 40)
    previous = root / 'wheel' / 'previous' / 'onecrew-2.2.0.dev18-py3-none-any.whl'
    previous.write_bytes(b'stub previous wheel\n')
    manifest = {'kind': 'v23-milestone-package', 'milestone': 'FINAL', 'label': 'OneCrew 2.3 \u2014 A1 + A2 + B', 'version': version, 'code_commit': COMMIT,
                'built_at': '2026-10-29 11:41:09', 'ships_paging': False, 'wheel': {'name': wheel_name, 'sha256': sha256(wheel)},
                'previous_wheel': {'name': previous.name, 'sha256': sha256(previous), 'version': '2.2.0.dev18'},
                'claims': {'delivered': False, 'reviewed_by_codex': False, 'accepted_by_owner': False, 'released': False}}
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding='utf-8')
    for name in ('verify_milestone.py', 'first_task_drill.py'):
        (root / 'verify' / name).write_text(STUB, encoding='utf-8')
    shutil.copy2(WRAPPER, root / 'verify' / 'thu-goi.ps1')
    lines = [f'{sha256(p)}  {p.relative_to(root).as_posix()}' for p in sorted(root.rglob('*')) if p.is_file()]
    (root / 'SHA256SUMS').write_bytes(('\r\n'.join(lines) + '\r\n').encode('utf-8'))      # as build_milestone writes it on Windows
    return manifest


@unittest.skipUnless(WINDOWS, 'the owner wrapper is a Windows PowerShell 5.1 script: it needs Windows with powershell.exe')
class OwnerWrapperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='owner wrapper '))      # a space in the path, like the real folders
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.pkg = self.tmp / 'pkg dev5'
        self.manifest = make_package(self.pkg)
        self.ids = itertools.count(1)

    # ---- helpers
    def new_work(self):
        return self.tmp / f'work {next(self.ids)}'

    def env(self, calls_file, verify=None, drill=None, owner_mode='real'):
        env = dict(os.environ)
        env.update(STUB_CALLS=str(calls_file), STUB_VERIFY_SPEC=json.dumps(verify or {}), STUB_DRILL_SPEC=json.dumps(drill or {}), STUB_OWNER_MODE=owner_mode)
        return env

    def powershell(self, script_args, env):
        done = subprocess.run([str(POWERSHELL), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', *map(str, script_args)],
                              capture_output=True, env=env, cwd=str(self.tmp), timeout=600)
        return done.returncode, done.stdout.decode('utf-8', 'replace') + done.stderr.decode('utf-8', 'replace')

    def run_wrapper(self, work=DEFAULT, package=DEFAULT, python=DEFAULT, script=DEFAULT, verify=None, drill=None, owner_mode='real'):
        work = self.new_work() if work is DEFAULT else work
        package = self.pkg if package is DEFAULT else package
        python = sys.executable if python is DEFAULT else python
        args = [WRAPPER if script is DEFAULT else script]
        for flag, value in (('-Package', package), ('-Work', work), ('-Python', python)):
            if value is not None:
                args += [flag, value]
        calls_file = self.tmp / f'calls {next(self.ids)}.jsonl'
        code, out = self.powershell(args, self.env(calls_file, verify, drill, owner_mode))
        return Run(code, out, work, read_calls(calls_file))

    def run_side_by_side(self, jobs):
        """run_wrapper for every kwargs dict in `jobs` at the same time; the results in the same order."""
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(jobs))) as pool:
            futures = [pool.submit(self.run_wrapper, **job) for job in jobs]
            return [future.result() for future in futures]

    def assert_passed(self, res):
        self.assertEqual(res.code, 0, res.out)
        self.assertRegex(res.out, PASS_LINE, res.out)
        self.assertNotIn('KHONG DAT', res.out)

    def assert_not_passed(self, res, code, reason):
        self.assertEqual(res.code, code, res.out)
        self.assertIsNone(PASS_LINE.search(res.out), 'a failing run printed the pass line:\n' + res.out)
        self.assertIn('KHONG DAT', res.out)
        self.assertIn(reason, res.out, 'the failure is not for the expected reason:\n' + res.out)

    # ---- the pass
    def test_fresh_run_with_both_tools_passing_prints_the_result_and_exits_zero(self):
        res = self.run_wrapper()
        self.assert_passed(res)
        self.assertIn('wheel sha256 = ' + self.manifest['wheel']['sha256'], res.out)
        self.assertIn('ket qua: pass, buoc dat 12/12', res.out)
        self.assertIn('ket qua: pass, buoc bat buoc dat 21/21, buoc duyet plan: real', res.out)
        self.assertIn('(buoc duyet plan: real)', next(line for line in res.out.splitlines() if line.startswith('DAT: ')))
        self.assertIn(('Thu muc ket qua: ' + str(res.work)).lower(), res.out.lower())
        self.assertEqual(res.calls, ['verify', 'drill'])
        self.assertTrue((res.work / 'verify' / 'verify-report.json').is_file())
        self.assertTrue((res.work / 'task dau tien' / 'first-task-drill-log.json').is_file())

    def test_script_shipped_in_the_package_defaults_to_its_own_package(self):
        shipped = self.pkg / 'verify' / 'thu-goi.ps1'
        res = self.run_wrapper(package=None, script=shipped)           # no -Package: the parent of the script's folder, from another working folder
        self.assert_passed(res)
        self.assertIn(('goi            : ' + str(self.pkg)).lower(), res.out.lower())
        self.assertEqual(res.calls, ['verify', 'drill'])

    def test_fixture_owner_step_inside_an_ai_session_counts_all_required_steps_and_says_so(self):
        res = self.run_wrapper(owner_mode='fixture')
        self.assert_passed(res)
        self.assertIn('buoc bat buoc dat 23/23, buoc duyet plan: fixture', res.out)
        self.assertIn('fixture = buoc duyet plan duoc thay trong phien AI', res.out)

    def test_info_steps_are_not_required_steps(self):
        res = self.run_wrapper(drill={'fail_steps': ['real-check', 'drill-cmd']})          # the drill ignores them too: required = kind is not 'info'
        self.assert_passed(res)
        self.assertIn('buoc bat buoc dat 21/21', res.out)

    def test_relative_work_folder_is_made_in_the_current_folder(self):
        res = self.run_wrapper(work='relative work')                    # the helper runs PowerShell in self.tmp
        self.assert_passed(res)
        self.assertTrue((self.tmp / 'relative work' / 'verify' / 'verify-report.json').is_file())

    def test_default_work_folder_is_a_new_timestamped_folder_named_after_the_version(self):
        manifest = json.loads((self.pkg / 'manifest.json').read_text(encoding='utf-8'))
        manifest['wheel']['sha256'] = '0' * 64                           # stop at the hash check, so nothing is created on D:
        (self.pkg / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        res = self.run_wrapper(work=None)
        self.assert_not_passed(res, 1, 'hash wheel khac manifest')
        shown = re.search(r'thu muc ket qua: (.+)', res.out)
        self.assertRegex(shown.group(1).strip(), r'^D:\\OneCrewRuns\\v23 thu cua anh 2\.3\.0\.dev5 \d{8}-\d{6}$')
        self.assertFalse(Path(shown.group(1).strip()).exists())

    def test_empty_existing_work_folder_is_accepted(self):
        work = self.new_work()
        work.mkdir()
        self.assert_passed(self.run_wrapper(work=work))

    # ---- the Codex case: the work folder already holds passing logs
    def test_work_folder_with_old_passing_logs_is_refused_and_left_alone(self):
        work = self.new_work()
        first = self.run_wrapper(work=work)
        self.assert_passed(first)
        old = snapshot(work)
        res = self.run_wrapper(work=work)
        self.assert_not_passed(res, 2, 'khong dung lai')
        self.assertEqual(res.calls, [], 'no tool may run against a folder that already holds results')
        self.assertEqual(snapshot(work), old, 'the old results were touched')

    def test_work_folder_holding_any_file_is_refused(self):
        with_report = self.new_work()
        (with_report / 'verify').mkdir(parents=True)
        (with_report / 'verify' / 'verify-report.json').write_text(json.dumps({'result': 'pass'}), encoding='utf-8')
        stray = self.new_work()
        stray.mkdir()
        (stray / 'notes.txt').write_text('x', encoding='utf-8')
        for res in self.run_side_by_side([dict(work=with_report), dict(work=stray)]):
            self.assert_not_passed(res, 2, 'khong dung lai')
            self.assertEqual(res.calls, [])

    def test_codex_case_old_script_is_red_and_the_wrapper_is_green(self):
        work = self.new_work()
        text = LEGACY_DEV5
        for original, now in zip(LEGACY_HARDCODED, (sys.executable, str(self.pkg), self.manifest['wheel']['sha256'])):
            self.assertEqual(text.count(original), 1, original)
            text = text.replace(original, now)
        legacy = self.tmp / 'thu-goi-dev5-copy.ps1'
        legacy.write_text(text, encoding='ascii')
        calls_file = self.tmp / 'legacy calls.jsonl'
        env = self.env(calls_file)
        code, out = self.powershell([legacy, '-Work', work], env)
        self.assertEqual(code, 0, out)                                      # a fresh folder: the old script works
        self.assertRegex(out, PASS_LINE)
        code, out = self.powershell([legacy, '-Work', work], env)           # the Codex case: the same folder again, logs already passing
        self.assertIn('is not empty', out)                                  # the drill refused to run ...
        self.assertEqual(read_calls(calls_file), ['verify', 'drill', 'verify', 'drill'])
        self.assertEqual((code, bool(PASS_LINE.search(out))), (0, True), 'RED expected: the old script no longer reproduces the defect\n' + out)
        self.assertIn('buoc bat buoc dat 21/21', out)                       # ... and the old script printed the OLD log's 21/21, DAT, exit 0
        green = self.run_wrapper(work=work)                                 # the same case on the wrapper
        self.assert_not_passed(green, 2, 'khong dung lai')
        self.assertEqual(green.calls, [])

    # ---- a tool that fails, or a report that is not this run's, never becomes DAT
    VERIFY_CASES = [
        ('verifier exits 1 with a failing report', {'exit': 1, 'set': {'result': 'fail'}, 'fail_steps': ['V4-stub']}, 'bo kiem thoat voi ma 1'),
        ('verifier exits 1 although its report says pass', {'exit': 1}, 'bo kiem thoat voi ma 1'),
        ('verifier exits 1 and writes no report', {'exit': 1, 'write': False}, 'khong co bao cao cua lan chay nay'),
        ('verifier exits 0 and writes no report', {'write': False}, 'khong co bao cao cua lan chay nay'),
        ('report says fail, exit 0', {'set': {'result': 'fail'}}, 'bao cao ghi result = fail'),
        ('a step failed while the summary says pass', {'fail_steps': ['V5-stub']}, 'buoc khong dat trong bao cao'),
        ('fewer steps than expected', {'set': {'expected_steps': 13}}, 'bao cao co 12 buoc, can 13'),
        ('report names another package', {'set': {'package': 'C:/somewhere/else/onecrew-9.9.9'}}, 'bao cao ghi goi khac'),
        ('report names another wheel hash', {'set': {'manifest.wheel.sha256': 'f' * 64}}, 'bao cao ghi sha256 wheel'),
        ('report names another wheel file', {'set': {'manifest.wheel.name': 'onecrew-9.9.9-py3-none-any.whl'}}, 'bao cao ghi wheel'),
        ('report names another commit', {'set': {'manifest.code_commit': '0' * 40}}, 'bao cao ghi commit'),
        ('report names another version', {'set': {'manifest.version': '2.3.0.dev4'}}, 'bao cao ghi phien ban'),
        ('report is of another kind', {'set': {'kind': 'first-task-drill-log'}}, 'bao cao khong phai loai'),
        ('report started before the run', {'set': {'started': '2020-01-01T00:00:00'}}, 'bao cao cu'),
        ('report started in the future', {'set': {'started': '2099-01-01T00:00:00'}}, 'o tuong lai'),
        ('report has no readable start time', {'set': {'started': 'yesterday'}}, 'gio bat dau doc duoc'),
        ('report file written before the run', {'mtime': 1600000000}, 'file bao cao duoc ghi luc'),
    ]
    DRILL_CASES = [
        ('drill refuses and writes no log, exit 1', {'write': False, 'exit': 1}, 'task dau tien thoat voi ma 1'),
        ('drill exits 1 although its log says pass', {'exit': 1}, 'task dau tien thoat voi ma 1'),
        ('drill exits 0 and writes no log', {'write': False}, 'khong co bao cao cua lan chay nay'),
        ('log says fail, exit 0', {'set': {'result': 'fail'}}, 'bao cao ghi result = fail'),
        ('a required step failed while the summary says pass and info steps pass', {'fail_steps': ['step-c']}, 'buoc bat buoc khong dat trong bao cao'),
        ('every required step failed, only info steps pass', {'fail_steps': ['links', 'venv', 'step-c', 'state']}, 'buoc bat buoc khong dat trong bao cao'),
        ('no required step at all', {'set': {'steps': [{'id': 'drill-cmd', 'kind': 'info', 'result': 'pass'}]}}, 'khong co buoc bat buoc nao'),
        ('package changed during the drill', {'set': {'package_unchanged': False}}, 'khong xac nhan goi nguyen ven'),
        ('log names another package', {'set': {'package': 'C:/somewhere/else/onecrew-9.9.9'}}, 'bao cao ghi goi khac'),
        ('log names another commit', {'set': {'manifest.code_commit': '0' * 40}}, 'bao cao ghi commit'),
        ('log names another version', {'set': {'manifest.version': '2.3.0.dev4'}}, 'bao cao ghi phien ban'),
        ('another wheel was installed', {'set': {'onecrew_version': '2.3.0.dev4'}}, 'bao cao cai onecrew'),
        ('log is of another folder', {'set': {'work': 'C:/somewhere/else/task dau tien'}}, 'thu muc lam viec khac'),
        ('log is of another kind', {'set': {'kind': 'v23-milestone-verify-report'}}, 'bao cao khong phai loai'),
        ('unknown owner step mode', {'set': {'owner_step_mode': 'skipped'}}, 'buoc duyet plan khong ro'),
        ('log started before the run', {'set': {'started': '2020-01-01T00:00:00'}}, 'bao cao cu'),
        ('log started in the future', {'set': {'started': '2099-01-01T00:00:00'}}, 'o tuong lai'),
        ('log file written before the run', {'mtime': 1600000000}, 'file bao cao duoc ghi luc'),
        ('log lacks the steps', {'delete': ['steps']}, 'khong co buoc bat buoc nao'),
    ]

    def test_verifier_failures_and_foreign_reports_never_print_dat(self):
        results = self.run_side_by_side([dict(verify=spec) for _, spec, _ in self.VERIFY_CASES])
        for (name, spec, reason), res in zip(self.VERIFY_CASES, results):
            with self.subTest(name):
                self.assert_not_passed(res, 1, reason)
                self.assertNotIn('ket qua: pass, buoc dat', res.out)
                self.assertEqual(res.calls, ['verify', 'drill'])                  # the drill still runs: both results are shown

    def test_drill_failures_and_foreign_logs_never_print_dat(self):
        results = self.run_side_by_side([dict(drill=spec) for _, spec, _ in self.DRILL_CASES])
        for (name, spec, reason), res in zip(self.DRILL_CASES, results):
            with self.subTest(name):
                self.assert_not_passed(res, 1, reason)
                self.assertNotIn('ket qua: pass, buoc bat buoc', res.out)
                self.assertIn('ket qua: pass, buoc dat 12/12', res.out)           # the verifier's own pass is still reported as such
                self.assertEqual(res.calls, ['verify', 'drill'])

    def test_both_tools_failing_reports_both(self):
        res = self.run_wrapper(verify={'exit': 1}, drill={'write': False, 'exit': 1})
        self.assert_not_passed(res, 1, 'bo kiem thoat voi ma 1')
        self.assertIn('task dau tien thoat voi ma 1', res.out)
        self.assertIn('KHONG DAT: 3 van de', res.out)          # the verifier's exit code, the drill's exit code, the drill's missing log

    # ---- the package itself
    def test_wheel_hash_different_from_the_manifest_stops_before_any_tool(self):
        manifest = json.loads((self.pkg / 'manifest.json').read_text(encoding='utf-8'))
        manifest['wheel']['sha256'] = '0' * 64
        (self.pkg / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        res = self.run_wrapper()
        self.assert_not_passed(res, 1, 'hash wheel khac manifest')
        self.assertEqual(res.calls, [])
        self.assertFalse(res.work.exists(), 'nothing is created for a package that fails its hash')

    def test_wheel_changed_after_the_manifest_was_written_stops_before_any_tool(self):
        with open(self.pkg / 'wheel' / WHEEL, 'ab') as handle:
            handle.write(b'tampered')
        res = self.run_wrapper()
        self.assert_not_passed(res, 1, 'hash wheel khac manifest')
        self.assertEqual(res.calls, [])

    def test_package_files_that_differ_from_sha256sums_stop_before_any_tool(self):
        def edit(root, relative, mutate):
            path = root / relative
            path.write_bytes(mutate(path.read_bytes()))

        def drop_line(root, relative):
            sums = root / 'SHA256SUMS'
            kept = [line for line in sums.read_bytes().decode('utf-8').split('\r\n') if not line.endswith('  ' + relative)]
            sums.write_bytes('\r\n'.join(kept).encode('utf-8'))
        cases = [('verifier changed after the package was built', lambda r: edit(r, 'verify/verify_milestone.py', lambda b: b + b'# changed\n'), 'file khac SHA256SUMS: verify/verify_milestone.py'),
                 ('drill changed after the package was built', lambda r: edit(r, 'verify/first_task_drill.py', lambda b: b + b'# changed\n'), 'file khac SHA256SUMS: verify/first_task_drill.py'),
                 ('manifest edited, wheel still the one it names', lambda r: edit(r, 'manifest.json', lambda b: b + b'\n'), 'file khac SHA256SUMS: manifest.json'),
                 ('SHA256SUMS does not list the drill', lambda r: drop_line(r, 'verify/first_task_drill.py'), 'SHA256SUMS khong liet ke verify/first_task_drill.py'),
                 ('SHA256SUMS missing', lambda r: (r / 'SHA256SUMS').unlink(), 'goi khong co SHA256SUMS')]
        packages = []
        for name, mutate, _ in cases:
            root = self.tmp / f'package {len(packages)}'
            shutil.copytree(self.pkg, root)
            mutate(root)
            packages.append(root)
        for (name, _, reason), res in zip(cases, self.run_side_by_side([dict(package=root) for root in packages])):
            with self.subTest(name):
                self.assert_not_passed(res, 1, reason)
                self.assertEqual(res.calls, [])

    def test_a_second_wheel_in_the_wheel_folder_stops_before_any_tool(self):
        (self.pkg / 'wheel' / 'onecrew-9.9.9-py3-none-any.whl').write_bytes(b'other')
        res = self.run_wrapper()
        self.assert_not_passed(res, 1, 'co 2 file onecrew-*.whl')
        self.assertEqual(res.calls, [])

    def test_wheel_missing_stops_before_any_tool(self):
        (self.pkg / 'wheel' / WHEEL).unlink()
        res = self.run_wrapper()
        self.assert_not_passed(res, 1, 'khong thay wheel cua manifest')
        self.assertEqual(res.calls, [])

    def test_refuses_to_start_on_bad_arguments(self):
        empty = self.tmp / 'not a package'
        empty.mkdir()
        no_drill = self.tmp / 'package without the drill'
        shutil.copytree(self.pkg, no_drill)
        (no_drill / 'verify' / 'first_task_drill.py').unlink()
        bad_commit = self.tmp / 'package with a bad commit'
        shutil.copytree(self.pkg, bad_commit)
        manifest = json.loads((bad_commit / 'manifest.json').read_text(encoding='utf-8'))
        manifest['code_commit'] = 'b3ecc57'
        (bad_commit / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        a_file = self.tmp / 'a file'
        a_file.write_text('x', encoding='utf-8')
        before = snapshot(self.pkg)
        cases = [('no manifest', dict(package=empty), 'khong thay manifest.json'),
                 ('no such package folder', dict(package=self.tmp / 'nowhere'), 'khong thay thu muc goi'),
                 ('a tool missing', dict(package=no_drill), 'goi thieu file'),
                 ('commit is not 40 hex', dict(package=bad_commit), 'code_commit'),
                 ('no such python', dict(python=self.tmp / 'no python.exe'), 'khong thay Python'),
                 ('work folder inside the package', dict(work=self.pkg / 'results'), 'nam trong goi'),
                 ('work path is a file', dict(work=a_file), 'la mot file')]
        for (name, kwargs, reason), res in zip(cases, self.run_side_by_side([kwargs for _, kwargs, _ in cases])):
            with self.subTest(name):
                self.assert_not_passed(res, 2, reason)
                self.assertEqual(res.calls, [])
        self.assertEqual(snapshot(self.pkg), before, 'the package was written to')

    def test_shipped_script_without_a_package_next_to_it_refuses(self):
        stray = self.tmp / 'loose' / 'verify'
        stray.mkdir(parents=True)
        shutil.copy2(WRAPPER, stray / 'thu-goi.ps1')
        self.assert_not_passed(self.run_wrapper(package=None, script=stray / 'thu-goi.ps1'), 2, 'khong thay manifest.json')

    def test_source_is_ascii_without_control_characters(self):
        data = WRAPPER.read_bytes()
        bad = [(i, b) for i, b in enumerate(data) if b > 0x7E or (b < 0x20 and b not in (9, 10, 13))]
        self.assertEqual(bad, [])


class PackagingTests(unittest.TestCase):
    """build_milestone.py ships the wrapper as verify/thu-goi.ps1, lists it in SHA256SUMS, and the README names the command (no PowerShell needed)."""

    def build(self, milestone):
        spec = importlib.util.spec_from_file_location('v23_build_milestone', BUILD)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        tmp = Path(tempfile.mkdtemp(prefix='build milestone '))
        self.addCleanup(shutil.rmtree, tmp, True)
        wheel = tmp / 'src' / WHEEL
        wheel.parent.mkdir()
        wheel.write_bytes(b'stub wheel')
        previous = wheel.parent / 'onecrew-2.2.0.dev18-py3-none-any.whl'
        previous.write_bytes(b'stub previous wheel')
        limits = wheel.parent / 'limits.md'
        limits.write_text('- none (packaging test)\n', encoding='utf-8')
        out = tmp / 'pkg'
        argv = ['build_milestone.py', str(out), '--milestone', milestone, '--previous-wheel', str(previous), '--previous-sha', sha256(previous), '--limits', str(limits)]
        git = lambda *args: '' if args[0] == 'status' else COMMIT          # a clean tree and a commit, whatever the state of this checkout
        with mock.patch.object(module, 'git', git), mock.patch.object(module.wh, 'build_wheel', lambda into: (str(wheel), None, None)), \
                mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
            module.main()
        return out

    def test_every_milestone_package_carries_the_wrapper_and_its_readme_names_the_command(self):
        for milestone in ('A1', 'FINAL'):
            with self.subTest(milestone):
                out = self.build(milestone)
                shipped = out / 'verify' / 'thu-goi.ps1'
                self.assertTrue(shipped.is_file())
                self.assertEqual(shipped.read_bytes(), WRAPPER.read_bytes())
                self.assertIn(f'{sha256(shipped)}  verify/thu-goi.ps1', (out / 'SHA256SUMS').read_text(encoding='utf-8').splitlines())
                readme = (out / 'README.md').read_text(encoding='utf-8')
                self.assertIn('powershell -ExecutionPolicy Bypass -File "' + str(out.resolve()) + '\\verify\\thu-goi.ps1"', readme)
                self.assertIn('`DAT:`', readme)
                self.assertIn('`KHONG DAT:`', readme)
                self.assertNotIn('{out}', readme)


if __name__ == '__main__':
    unittest.main()
