"""verify_obs1.py <package dir> <work dir> - check an OBS-1 trial package FROM THE PACKAGE, outside any checkout (stdlib only; run with python -I).

Steps (every one from the installed venv, python -I, cwd = <work>, isolated LOCALAPPDATA/APPDATA/TEMP, the fake claude first on PATH):
  V1  identity      SHA256SUMS lists every file of the package and every hash matches; the wheel's hash is the manifest's
  V2  install       a fresh venv (path with a space) + the wheel + the fake claude; `onecrew --version` prints the manifest version
  V3  origins/help  onecrew.v2.tracking, tracking_cli, tracking_web import from the venv (never a checkout); `onecrew --help` lists `track`
  V4  real task     scenario setup: a plan proposed (tracking: waiting, needs approve), approved and revised (waiting, no worker yet), one engine.step
                    through the real NativeExecutor -> Supervisor -> fake claude.exe: node C produced, its attempt settled, the worktree untouched
  V5  cli           `track list --json` equals the model, `track show P1` names node C and its level, `track evidence` prints the receipt with
                    secrets withheld, an unknown plan is exit 2, `track list` text carries the sources
  V6  server+latency `track serve` as its own process: GET /, /api/health, /api/overview, /api/task; POST -> 405; a foreign key -> 403; a new owner
                    question written by ANOTHER process shows in /api/overview within LATENCY_CEILING seconds (measured, written to the report)
  V7  reconnect     the server is killed; node C is verified while no viewer runs; a new server on the same port shows the verified node, every
                    earlier event and no duplicate seq
  V8  viewer close  a second root P2 whose worker stays busy (fake claude sleeps): the page shows it running; the server is killed in the middle;
                    the worker's process finishes its step on its own (node produced)
  V9  secrets       the question's password and the receipt's key never appear in the overview JSON, the detail JSON, the evidence text or the page
  V10 untracked     a task outside any plan and a registry project without a plan are listed as "chưa được theo dõi"; the statement about
                    external Claude/Codex sessions is in the JSON and on the page
  V11 browser       a headless browser (Chrome, then Edge) renders the page: the badge says connected, the plans and their status words are in the
                    DOM, the detail of P1 opens through ?plan=P1 (timeline + node C), screenshots are written to <work>/evidence; through a local
                    proxy that drops /api/* the badge says "MẤT KẾT NỐI". No browser that executes script -> the step is `skipped` and the result
                    is `partial` (the page was not seen rendered on this machine)
  V12 isolation     the ledger's last event seq is the same after every read of V5-V7 viewers/CLIs (the viewer wrote nothing); the REAL registry
                    (%LOCALAPPDATA%\\OneCrew\\hook-projects.json of the caller) has the same hash before and after; the package tree is unchanged
  V13 p2-findings   the four Codex P2 counterexamples of 03/11 through the installed CLI and server (scenario `p2`)
  V14 ux            (03/11 UX round) the page driven in a headless browser by the same-origin harness (verify/obs1_ux_harness.py) over the states of
                    scenario `ux` (P6 verified, P7 accepted, P4 running+blocked with a stale attempt) plus P1..P5/PB: UX-01..08, race and disconnect
                    scenarios at 1280x720, 640x720 and 390x844 with real clicks, keyboard, >=3 polls, a ledger write while reading, reload and back;
                    screenshots to <work>/evidence/ux-*.png. No browser -> skipped (partial)
  V15 open-identity `track open` from the installed wheel: a second open reuses the same instance; a marker whose instance does not match the server
                    answering on its port is NOT reused (a new server starts, the other one is not killed); two concurrent opens share one server;
                    `track stop` stops only the matching server and removes the marker; a second stop refuses
Writes <work>/verify-report.json; prints RESULT pass|partial|fail. Exit 0 only on pass.
"""
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LATENCY_CEILING = 5.0
AI_MARKERS = ('CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'ONECREW_ACTOR', 'PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONUTF8', 'PYTHONIOENCODING')
BROWSERS = (r'C:\Program Files\Google\Chrome\Application\chrome.exe', r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
            r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', r'C:\Program Files\Microsoft\Edge\Application\msedge.exe')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree_digest(folder):
    h = hashlib.sha256()
    for p in sorted(Path(folder).rglob('*')):
        if p.is_file(): h.update(p.relative_to(folder).as_posix().encode() + b'\0' + sha256(p).encode() + b'\n')
    return h.hexdigest()


def run(argv, **kw):
    kw.setdefault('capture_output', True)
    return subprocess.run([str(a) for a in argv], **kw)


def text_of(done):
    return (done.stdout if isinstance(done.stdout, str) else done.stdout.decode('utf-8', 'replace')) + (done.stderr if isinstance(done.stderr, str) else done.stderr.decode('utf-8', 'replace'))


def first_json(text):
    """The first JSON object in `text` (one line or pretty-printed over many lines), or None."""
    text = text or ''
    start = text.find('{')
    while start >= 0:
        try: return json.JSONDecoder().raw_decode(text[start:])[0]
        except ValueError: start = text.find('{', start + 1)
    return None


def get(url, method='GET', data=None, timeout=20):
    request = urllib.request.Request(url, method=method, data=data)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as r:
            return r.status, r.read().decode('utf-8'), r.headers.get('Content-Type') or ''
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode('utf-8', 'replace'), error.headers.get('Content-Type') or ''


def fake_wheel(source, into):
    info = 'onecrew_fake_claude_v24-0.1.dist-info'
    files = {'onecrew_fake_claude_v24.py': Path(source).read_bytes(),
             f'{info}/METADATA': b'Metadata-Version: 2.1\nName: onecrew-fake-claude-v24\nVersion: 0.1\n',
             f'{info}/WHEEL': b'Wheel-Version: 1.0\nGenerator: verify_obs1\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
             f'{info}/entry_points.txt': b'[console_scripts]\nclaude = onecrew_fake_claude_v24:main\n'}
    import base64
    lines = [f'{n},sha256={base64.urlsafe_b64encode(hashlib.sha256(d).digest()).decode().rstrip("=")},{len(d)}' for n, d in files.items()]
    files[f'{info}/RECORD'] = ('\n'.join(lines + [f'{info}/RECORD,,']) + '\n').encode()
    path = Path(into) / 'onecrew_fake_claude_v24-0.1-py3-none-any.whl'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items(): archive.writestr(name, data)
    return path


def find_browser(profile):
    for exe in [e for e in BROWSERS if Path(e).is_file()] + [shutil.which('chrome'), shutil.which('msedge')]:
        if not exe: continue
        try:
            dom = dump_dom(exe, 'data:text/html,<b id=x>static</b><script>document.getElementById("x").textContent="jsran"</script>', profile, 500)
        except (OSError, subprocess.SubprocessError):
            continue
        if 'jsran' in dom: return exe
    return None


def dump_dom(exe, url, profile, budget=4000):
    done = run([exe, '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', f'--user-data-dir={profile}', '--window-size=1400,1000',
                f'--virtual-time-budget={budget}', '--dump-dom', url], text=True, encoding='utf-8', errors='replace', timeout=120)
    return done.stdout


def screenshot(exe, url, profile, path, budget=4000):
    run([exe, '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', f'--user-data-dir={profile}', '--window-size=1400,1000',
         f'--virtual-time-budget={budget}', f'--screenshot={path}', url], timeout=120)
    return Path(path).is_file()


def badge(dom):
    found = re.search(r'id="conn" class="([a-z]*)">([^<]*)<', dom)
    return (found.group(1), found.group(2)) if found else (None, None)


def load_harness():
    import importlib.util
    sys.dont_write_bytecode = True                      # never write __pycache__ into the package being checked (package_unchanged)
    spec = importlib.util.spec_from_file_location('obs1_ux_harness', Path(__file__).with_name('obs1_ux_harness.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def start_server(exe, project, state, env, work, port=0, project_only=False):
    """`onecrew track serve` as its own process; returns (process, record) from its first JSON line."""
    process = subprocess.Popen([str(exe), '--project', str(project), '--state-root', str(state), 'track', 'serve', '--port', str(port), '--interval', '1']
                               + (['--project-only'] if project_only else []),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=str(work), text=True, encoding='utf-8', errors='replace')
    line = process.stdout.readline()
    record = first_json(line)
    if not record or not record.get('url'):
        process.kill(); raise RuntimeError('track serve printed no URL: ' + line + process.stderr.read()[-500:])
    return process, record


def stop_server(process):
    process.kill()
    try: process.wait(10)
    except subprocess.TimeoutExpired: pass


class _Proxy:
    """Serves `/` from the real server and drops every /api/* connection: the page's disconnected state, seen from outside the process."""
    def __init__(self, target):
        target_url = target
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                if self.path.startswith('/api/'):
                    self.close_connection = True; self.connection.close(); return
                status, body, ctype = get(target_url + self.path.lstrip('/'))
                data = body.encode('utf-8')
                self.send_response(status); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}/'

    def stop(self):
        self.server.shutdown(); self.server.server_close()


def main(pkg, work):
    for stream in (sys.stdout, sys.stderr):                 # the caller's console may be cp1252: never die on a Vietnamese word
        try: stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError, OSError): pass
    pkg, work = Path(pkg).resolve(), Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True); os.chdir(work)
    real_registry = Path(os.environ.get('LOCALAPPDATA', '')) / 'OneCrew' / 'hook-projects.json'
    registry_before = sha256(real_registry) if real_registry.is_file() else 'absent'
    package_before = tree_digest(pkg)
    steps, measures = [], {}
    report = {'kind': 'obs1-verify-report', 'package': str(pkg), 'work': str(work), 'started': time.strftime('%Y-%m-%dT%H:%M:%S'), 'steps': steps, 'measures': measures,
              'proves': 'the tracking view, CLI, server and page of the INSTALLED wheel over a real root/node/attempt flow driven by the fake claude (a test double: no model)',
              'does_not_prove': ['that a real provider/model ran', 'the page on a browser other than the one named in V11', 'any gate or acceptance of the 2.4 release line']}
    clock = [time.monotonic()]

    def step(sid, ok, **facts):
        now = time.monotonic()
        steps.append(dict(id=sid, result='pass' if ok is True else 'skipped' if ok is None else 'fail', seconds=round(now - clock[0], 1), **facts)); clock[0] = now
        print(sid, steps[-1]['result'], f'{steps[-1]["seconds"]}s', flush=True)
        if ok is False:
            for key in ('problems', 'error', 'tail'):
                if facts.get(key): print('   -', str(facts[key])[:600], flush=True)
        return ok

    def finish():
        report['finished'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        report['package_unchanged'] = tree_digest(pkg) == package_before
        registry_after = sha256(real_registry) if real_registry.is_file() else 'absent'
        report['real_registry'] = {'path': str(real_registry), 'before': registry_before, 'after': registry_after, 'unchanged': registry_before == registry_after}
        results = [s['result'] for s in steps]
        report['result'] = 'fail' if 'fail' in results or not steps or not report['package_unchanged'] or not report['real_registry']['unchanged'] else ('partial' if 'skipped' in results else 'pass')
        (work / 'verify-report.json').write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding='utf-8')
        print('RESULT', report['result'], f'{results.count("pass")}/{len(steps)}', 'package_unchanged=' + str(report['package_unchanged']), 'real_registry_unchanged=' + str(report['real_registry']['unchanged']))
        return 0 if report['result'] == 'pass' else 1

    manifest = json.loads((pkg / 'manifest.json').read_text(encoding='utf-8'))
    report['manifest'] = {k: manifest.get(k) for k in ('kind', 'label', 'version', 'code_commit', 'branch', 'wheel', 'claims')}
    # V1
    listed, problems = {}, []
    for line in (pkg / 'SHA256SUMS').read_text(encoding='utf-8').splitlines():
        digest, name = line.split('  ', 1); listed[name] = digest
    present = {p.relative_to(pkg).as_posix() for p in pkg.rglob('*') if p.is_file() and p.name != 'SHA256SUMS'}
    problems += [f'missing {n}' for n in sorted(set(listed) - present)] + [f'not listed {n}' for n in sorted(present - set(listed))]
    problems += [f'hash {n}' for n in sorted(set(listed) & present) if sha256(pkg / n) != listed[n]]
    wheel = pkg / 'wheel' / manifest['wheel']['name']
    if sha256(wheel) != manifest['wheel']['sha256']: problems.append('wheel sha differs from manifest')
    if manifest.get('kind') != 'obs1-trial-package': problems.append(f'manifest kind {manifest.get("kind")!r}')
    if not step('V1-identity', not problems, files=len(listed), problems=problems): return finish()
    # V2
    venv = work / 'venv with space'
    if venv.exists(): shutil.rmtree(venv)
    run([sys.executable, '-m', 'venv', venv], check=True)
    py, scripts = venv / 'Scripts' / 'python.exe', venv / 'Scripts'
    exe = scripts / 'onecrew.exe'
    a = run([py, '-I', '-m', 'pip', 'install', '--no-index', '--no-build-isolation', '--disable-pip-version-check', wheel])
    b = run([py, '-I', '-m', 'pip', 'install', '--no-index', '--no-build-isolation', '--disable-pip-version-check', fake_wheel(pkg / 'verify' / 'onecrew_fake_claude_v24.py', work)])
    env = {k: v for k, v in os.environ.items() if k.upper() not in AI_MARKERS}
    local, roaming, temp = work / 'localappdata', work / 'appdata', work / 'temp'
    for d in (local, roaming, temp): d.mkdir(exist_ok=True)
    policy, log = work / 'policy.json', work / 'fake.jsonl'
    policy.write_text('{}', encoding='utf-8')
    env.update(PATH=str(scripts) + os.pathsep + env.get('PATH', ''), LOCALAPPDATA=str(local), APPDATA=str(roaming), TEMP=str(temp), TMP=str(temp),
               ONECREW_FAKE_POLICY=str(policy), ONECREW_FAKE_LOG=str(log), ONECREW_LANG='vi')
    version = run([exe, '--version'], env=env, cwd=work, text=True, encoding='utf-8', errors='replace').stdout.strip()
    if not step('V2-install', a.returncode == 0 and b.returncode == 0 and version == f'onecrew {manifest["version"]}', version=version, pip_tail=text_of(a)[-300:] + text_of(b)[-200:]): return finish()
    # V3
    probe = ('import json, sys; import onecrew.v2.tracking as t, onecrew.v2.tracking_cli as c, onecrew.v2.tracking_web as w; '
             'print(json.dumps({"tracking": t.__file__, "cli": c.__file__, "web": w.__file__}))')
    done = run([py, '-I', '-c', probe], env=env, cwd=work, text=True, encoding='utf-8', errors='replace')
    origins = first_json(done.stdout) or {}
    help_text = run([exe, '--help'], env=env, cwd=work, text=True, encoding='utf-8', errors='replace').stdout
    ok = bool(origins) and all(str(v).casefold().startswith(str(venv).casefold()) for v in origins.values()) and 'track' in help_text
    if not step('V3-origins-help', ok, origins=origins, help_has_track='track' in help_text, tail=text_of(done)[-300:]): return finish()
    # V4
    scenario = pkg / 'verify' / 'scenario_obs1.py'
    done = run([py, '-I', scenario, work, 'setup'], env=env, cwd=work, text=True, encoding='utf-8', errors='replace', timeout=600)
    setup = first_json(done.stdout) or {}
    problems = []
    if setup.get('before', {}).get('kind') != 'waiting' or setup.get('before_needs') != ['approve']: problems.append(f'before approval: {setup.get("before")} {setup.get("before_needs")}')
    if setup.get('idle', {}).get('kind') != 'waiting' or 'chưa có worker' not in setup.get('idle', {}).get('reason', ''): problems.append(f'idle: {setup.get("idle")}')
    if setup.get('step_state') != 'produced': problems.append(f'step {setup.get("step_state")}')
    if setup.get('after', {}).get('kind') != 'waiting' or setup.get('after_level', {}).get('kind') != 'produced': problems.append(f'after: {setup.get("after")} {setup.get("after_level")}')
    if (setup.get('nodes') or {}).get('C', [None])[:2] != ['complete', 'produced'] or setup.get('attempts') != ['settled']: problems.append(f'nodes {setup.get("nodes")} attempts {setup.get("attempts")}')
    if setup.get('worktree_out') != 'base\n': problems.append('the worktree was written by the worker (candidate isolation broken)')
    if not all(str(v).casefold().startswith(str(venv).casefold()) for v in (setup.get('origins') or {}).values()): problems.append(f'origins {setup.get("origins")}')
    for kind in ('plan.approved', 'node.started', 'attempt.launched', 'attempt.settled', 'node.produced'):
        if kind not in (setup.get('timeline_kinds') or []): problems.append('timeline lacks ' + kind)
    measures['engine_step_seconds'] = setup.get('step_seconds')
    if not step('V4-real-task', done.returncode == 0 and not problems, problems=problems, step_seconds=setup.get('step_seconds'), tail=text_of(done)[-400:]): return finish()
    project, state = setup['project'], setup['state_root']
    seq_after_task = setup['last_seq']

    def cli(*args, **kw):
        return run([exe, '--project', project, '--state-root', state, *args], env=env, cwd=work, text=True, encoding='utf-8', errors='replace', timeout=300, **kw)
    # V5
    listed_json = cli('track', 'list', '--json'); value = first_json(listed_json.stdout) or {}
    shown = cli('track', 'show', 'P1'); listed_text = cli('track', 'list'); nope = cli('track', 'show', 'NOPE')
    evidence = cli('track', 'evidence', 'P1', setup['receipt'])
    problems = []
    task = ((value.get('projects') or [{}])[0].get('tasks') or [{}])[0]
    if task.get('status') != setup['after']: problems.append(f'list status {task.get("status")} != {setup["after"]}')
    if value.get('source', {}).get('last_seq') != seq_after_task: problems.append('list changed or misread last_seq')
    if shown.returncode != 0 or 'node C' not in shown.stdout or 'đã tạo đầu ra' not in shown.stdout: problems.append('show P1: ' + text_of(shown)[-200:])
    if '[plan.approved' not in listed_text.stdout and 'node.produced' not in listed_text.stdout: problems.append('list text without sources: ' + listed_text.stdout[-300:])
    if nope.returncode != 2 or '"error"' not in nope.stdout: problems.append(f'show NOPE exit {nope.returncode}: {text_of(nope)[-200:]}')
    if evidence.returncode != 0 or 'blob ' + setup['receipt'][:8] not in evidence.stdout: problems.append('evidence: ' + text_of(evidence)[-300:])
    if not step('V5-cli', not problems, problems=problems): return finish()
    # V6
    process, record = start_server(exe, project, state, env, work)
    url = record['url']
    problems = []
    try:
        s, page, ctype = get(url); s2, health, _ = get(url + 'api/health'); s3, overview, _ = get(url + 'api/overview'); s4, detail, _ = get(url + 'api/task?plan=P1')
        if s != 200 or 'text/html' not in ctype or 'theo dõi' not in page: problems.append(f'page {s} {ctype}')
        if s2 != 200 or not (first_json(health) or {}).get('ok'): problems.append(f'health {s2}')
        if s3 != 200 or (json.loads(overview).get('projects') or [{}])[0].get('tasks', [{}])[0].get('level', {}).get('kind') != 'produced': problems.append(f'overview {s3}')
        if s4 != 200 or json.loads(detail)['nodes']['C']['state'] != 'produced': problems.append(f'task {s4}')
        for method in ('POST', 'PUT', 'DELETE'):
            code, body, _ = get(url + 'api/overview', method=method, data=b'{}')
            if code != 405 or 'read-only' not in body: problems.append(f'{method} -> {code}')
        code, body, _ = get(url + 'api/evidence?plan=P1&key=' + 'c' * 64)
        if code != 403: problems.append(f'foreign evidence -> {code}')
        code, body, _ = get(url + 'api/evidence?plan=P1&key=' + setup['receipt'] + '&format=text')
        if code != 200 or 'kind' not in body: problems.append(f'own evidence -> {code}')
        t0 = time.perf_counter()
        req = subprocess.Popen([str(py), '-I', str(scenario), str(work), 'request'], env=env, cwd=str(work), stdout=subprocess.PIPE, text=True, encoding='utf-8')
        seen, request_id = None, None
        while time.perf_counter() - t0 < LATENCY_CEILING + 10:
            if request_id is None and req.poll() is not None:
                request_id = (first_json(req.stdout.read()) or {}).get('request')
            code, body, _ = get(url + 'api/overview')
            needs = (json.loads(body).get('projects') or [{}])[0].get('tasks', [{}])[0].get('needs_user', []) if code == 200 else []
            if needs and any(n.get('kind') == 'request' for n in needs):
                seen = round(time.perf_counter() - t0, 2); break
            time.sleep(0.2)
        measures['latency_write_to_overview_seconds'] = seen; measures['latency_ceiling_seconds'] = LATENCY_CEILING
        measures['overview_read_ms'] = (json.loads(get(url + 'api/overview')[1]).get('server') or {}).get('read_ms')
        if seen is None or seen > LATENCY_CEILING: problems.append(f'latency {seen} > {LATENCY_CEILING}')
        status_now = (json.loads(get(url + 'api/overview')[1]).get('projects') or [{}])[0].get('tasks', [{}])[0].get('status', {})
        if status_now.get('kind') != 'waiting' or not any(src.startswith('request:') for src in status_now.get('source', [])): problems.append(f'status with the question: {status_now}')
        first_timeline = json.loads(get(url + 'api/task?plan=P1')[1])
    finally:
        stop_server(process)
    if not step('V6-server-latency', not problems, problems=problems, url=url, latency_seconds=measures.get('latency_write_to_overview_seconds'), read_ms=measures.get('overview_read_ms')): return finish()
    # V7
    try:
        urllib.request.urlopen(url + 'api/health', timeout=3); down = False
    except (OSError, urllib.error.URLError): down = True
    verified = run([py, '-I', scenario, work, 'verify'], env=env, cwd=work, text=True, encoding='utf-8', errors='replace', timeout=600)
    port = int(url.rsplit(':', 1)[1].rstrip('/'))
    process, record = start_server(exe, project, state, env, work, port=port)
    problems = []
    try:
        second = json.loads(get(url + 'api/task?plan=P1')[1])
        old = {e['seq'] for e in first_timeline['timeline']}; new = [e['seq'] for e in second['timeline']]
        if not down: problems.append('the first server still answered after kill')
        if verified.returncode != 0 or (first_json(verified.stdout) or {}).get('result') != 'pass': problems.append('verify: ' + text_of(verified)[-300:])
        if not old < set(new): problems.append('earlier events missing after restart')
        if len(new) != len(set(new)): problems.append('duplicate seq after restart')
        if second['nodes']['C']['state'] != 'verified': problems.append(f'node C {second["nodes"]["C"]["state"]} after verify')
        if second['level']['kind'] not in ('produced', 'verified'): problems.append(f'level {second["level"]}')
        seq_after_verify = second['source']['last_seq']
    finally:
        stop_server(process)
    if not step('V7-reconnect', not problems, problems=problems, verify=first_json(verified.stdout)): return finish()
    # V8
    policy.write_text(json.dumps({'sleep': 6}), encoding='utf-8')
    process, record = start_server(exe, project, state, env, work)
    worker = subprocess.Popen([str(py), '-I', str(scenario), str(work), 'second'], env=env, cwd=str(work), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
    problems, running_seen = [], None
    try:
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 30:
            code, body, _ = get(record['url'] + 'api/overview')
            tasks = {t['plan']: t for p in json.loads(body).get('projects', []) for t in p['tasks']} if code == 200 else {}
            if tasks.get('P2', {}).get('status', {}).get('kind') == 'running':
                running_seen = tasks['P2']['status']; break
            time.sleep(0.3)
        if running_seen is None: problems.append('P2 never showed as running while its worker was busy')
        elif not running_seen['source'] or not running_seen['source'][0].startswith('attempt:'): problems.append(f'running without an attempt source: {running_seen}')
    finally:
        stop_server(process)                                                     # the viewer goes away in the middle of the attempt
    out, err = worker.communicate(timeout=180)
    done_line = next((first_json(l) for l in out.splitlines() if '"done"' in l), None)
    if not done_line or done_line.get('step_state') != 'produced': problems.append('worker after viewer close: ' + (out + err)[-400:])
    listed = first_json(cli('track', 'list', '--json').stdout) or {}
    p2 = next((t for p in listed.get('projects', []) for t in p['tasks'] if t['plan'] == 'P2'), {})
    if p2.get('level', {}).get('kind') != 'produced' or p2.get('active'): problems.append(f'P2 after: {p2.get("status")} {p2.get("level")} active {p2.get("active")}')
    measures['long_step_seconds'] = (done_line or {}).get('seconds')
    policy.write_text('{}', encoding='utf-8')
    if not step('V8-viewer-close-worker-continues', not problems, problems=problems, running_seen=running_seen, worker=done_line): return finish()
    # V9
    process, record = start_server(exe, project, state, env, work)
    problems = []
    try:
        overview = get(record['url'] + 'api/overview')[1]; detail = get(record['url'] + 'api/task?plan=P1&timeline=5000')[1]
        evidence_text = get(record['url'] + 'api/evidence?plan=P1&key=' + setup['receipt'] + '&format=text')[1]
        page = get(record['url'])[1]
        for leak in ('hunter2-must-not-show',):
            for name, blob in (('overview', overview), ('detail', detail), ('evidence', evidence_text), ('page', page)):
                if leak in blob: problems.append(f'{leak} in {name}')
        if '[withheld]' not in detail: problems.append('no [withheld] marker in the detail (the question carried a password)')
    finally:
        stop_server(process)
    if not step('V9-secrets', not problems, problems=problems): return finish()
    # V10
    done = run([py, '-I', scenario, work, 'untracked'], env=env, cwd=work, text=True, encoding='utf-8', errors='replace', timeout=300)
    listed = first_json(cli('track', 'list', '--json', '--all-projects').stdout) or {}
    u = listed.get('untracked') or {}
    problems = []
    if done.returncode != 0: problems.append('scenario untracked: ' + text_of(done)[-300:])
    if [o.get('key') for o in u.get('other_tasks', [])] != ['v1-job']: problems.append(f'other tasks {u.get("other_tasks")}')
    if not u.get('registry_projects_without_plan') or 'chưa được theo dõi' not in u['registry_projects_without_plan'][0].get('note', ''): problems.append(f'registry {u.get("registry_projects_without_plan")}')
    if 'không biến một phiên chat' not in u.get('statement', ''): problems.append('statement missing')
    if sorted(t['plan'] for p in listed.get('projects', []) for t in p['tasks']) != ['P1', 'P2']: problems.append('plans listed: ' + str([t['plan'] for p in listed.get('projects', []) for t in p['tasks']]))
    if not step('V10-untracked', not problems, problems=problems): return finish()
    done = None
    # V13 (runs here, after V10, because V10 counts the plans): the four Codex P2 counterexamples of 03/11, through the installed CLI and server
    problems, facts = [], {}
    process, record = start_server(exe, project, state, env, work)
    url = record['url']
    p2_env = dict(env, OBS1_P2_HOLD='8')
    scen = subprocess.Popen([str(py), '-I', str(scenario), str(work), 'p2'], env=p2_env, cwd=str(work), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
    try:
        def phase(name, budget=240):
            t0 = time.monotonic()
            while time.monotonic() - t0 < budget:
                line = scen.stdout.readline()
                if not line:
                    break
                value = first_json(line)
                if value and value.get('phase') == name: return value
            return None
        window = phase('p4-window')
        if not window: problems.append('p2 scenario: no p4-window line: ' + scen.stderr.read()[-400:] if scen.poll() is not None else 'p2 scenario: no p4-window line')
        else:
            d4 = json.loads(get(url + 'api/task?plan=P4')[1])
            facts['p4_window'] = {'status': d4['status'], 'attempt': d4['nodes']['C']['attempt'], 'progress': d4['nodes']['C']['progress']}
            if d4['status']['kind'] != 'running': problems.append(f"P2-02: status with only the old attempt's observation is {d4['status']}")
            if d4['nodes']['C']['attempt'] != window['new'] or d4['nodes']['C']['progress'] is not None or 'C' in d4['progress']: problems.append("P2-02: the old attempt's observation is shown as current progress")
            stale = [e for e in d4['timeline'] if e['kind'] == 'executor.observed' and e.get('attempt') == window['old']]
            if not stale or not stale[-1].get('stale_attempt'): problems.append('P2-02: the old observation is not in the timeline as a stale attempt')
            current = phase('p4-current')
            if not current: problems.append('p2 scenario: no p4-current line')
            else:
                d4 = json.loads(get(url + 'api/task?plan=P4')[1])
                facts['p4_current'] = d4['status']
                if d4['status']['kind'] != 'blocked' or not any(s.startswith('executor.observed:') for s in d4['status']['source']): problems.append(f"P2-02: a blocked observation of the CURRENT attempt does not block: {d4['status']}")
        done = phase('done')
        scen.wait(300)
        if scen.returncode != 0 or not done: problems.append('p2 scenario exit ' + str(scen.returncode) + ': ' + scen.stderr.read()[-400:])
        else:
            facts['projects'] = done['projects']
            d3 = first_json(cli('track', 'show', 'P3', '--json').stdout) or {}
            if d3.get('root_status') != 'closed' or d3.get('level', {}).get('kind') != 'none' or 'không phải nghiệm thu' not in d3.get('status', {}).get('reason', ''):
                problems.append(f"P2-01: closed plan shows level {d3.get('level')} status {d3.get('status')}")
            d5 = first_json(cli('track', 'show', 'P5', '--json').stdout) or {}
            open_waits = [w for w in d5.get('waits', []) if w.get('open')]
            if open_waits or len(d5.get('waits', [])) != 1 or d5['waits'][0].get('until') != '2026-11-03T00:00:05+00:00': problems.append(f"P2-03: waits {d5.get('waits')}")
            if d5.get('status', {}).get('kind') == 'waiting' and any(s.startswith('executor.observed') for s in d5['status'].get('source', [])): problems.append(f"P2-03: status still waits on the closed wait: {d5['status']}")
            if [w.get('until') for w in d5.get('measure', {}).get('executor_waits', [])] != ['2026-11-03T00:00:05+00:00']: problems.append('P2-03: the closed wait is not in the measure')
            shown = cli('track', 'show', 'P5')
            if 'Đã chờ (lịch sử)' not in shown.stdout or 'Đang chờ:' in shown.stdout: problems.append('P2-03: the text view still lists the closed wait as current')
    finally:
        stop_server(process)
        if scen.poll() is None: scen.kill()
    if done:
        a, b, key_b = done['projects']['a'], done['projects']['b'], done['projects']['b_key']
        process, record = start_server(exe, project, state, env, work, project_only=True)
        try:
            url = record['url']
            if get(url + 'api/task?plan=PB')[0] != 404: problems.append('P2-04: the project-only server serves PB without override')
            for path in ('api/overview?project_id=' + b, 'api/task?plan=PB&project_id=' + b, f'api/evidence?plan=PB&key={key_b}&project_id={b}'):
                code, body, _ = get(url + path)
                if code != 403 or 'PRIVATE' in body: problems.append(f'P2-04: {path} -> {code}')
            code, body, _ = get(url + 'api/overview?project_id=' + a)
            if code != 200 or 'PB' in body or 'P1' not in body: problems.append(f'P2-04: naming the server own project -> {code}')
            facts['scope'] = {'project_only_server': record.get('project_id'), 'a': a, 'b': b}
        finally:
            stop_server(process)
        process, record = start_server(exe, project, state, env, work)
        try:
            url = record['url']
            code, body, _ = get(url + 'api/task?plan=PB&project_id=' + b)
            if code != 200: problems.append(f'P2-04: all-projects server with project_id=B -> {code}')
            code, body, _ = get(url + f'api/evidence?plan=PB&key={key_b}&project_id={b}')
            if code != 200 or 'PROJECT B PRIVATE EVIDENCE' not in body: problems.append(f'P2-04: all-projects evidence of B -> {code}')
        finally:
            stop_server(process)
    if not step('V13-p2-findings', not problems, problems=problems, **facts): return finish()
    # V14 (03/11 UX round): the page driven in a real headless browser by the same-origin harness, over the full UX data set
    profile = work / 'browser profile'
    browser = find_browser(profile)
    evidence_dir = work / 'evidence'; evidence_dir.mkdir(exist_ok=True)
    ux_env = dict(env, OBS1_UX_HOLD='900')
    scen = subprocess.Popen([str(py), '-I', str(scenario), str(work), 'ux'], env=ux_env, cwd=str(work), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
    ready, problems, facts = None, [], {}
    t0 = time.monotonic()
    while time.monotonic() - t0 < 300:
        line = scen.stdout.readline()
        if not line: break
        value = first_json(line)
        if value and value.get('phase') == 'ready': ready = value; break
    if not ready:
        try: scen.wait(30)
        except subprocess.TimeoutExpired: scen.kill()
        problems.append('ux scenario did not get ready: ' + (scen.stderr.read() or '')[-600:])
    else:
        facts['states'] = {'P6': ready['P6'], 'P7': ready['P7'], 'P4': ready['p4']['status']}
        if ready['P6'].get('outcome') != 'verified' or ready['P7'].get('outcome') != 'accepted' or ready['p4']['status'].get('kind') != 'blocked':
            problems.append(f"ux data set is not in the expected states: {facts['states']}")
    if not browser:
        step('V14-ux', None if not problems else False, problems=problems, note='no headless Chrome/Edge executes a page script on this machine: the interactions were NOT checked here', **facts)
    elif not problems:
        ux = load_harness()
        process, record = start_server(exe, project, state, env, work)
        writes = []
        def on_signal(name):
            if name == 'write':
                done = run([py, '-I', scenario, work, 'request'], env=dict(env, OBS1_REQUEST_KEY=f'ux-write-{len(writes) + 1}'), cwd=work, text=True, encoding='utf-8', errors='replace', timeout=120)
                writes.append((first_json(done.stdout) or {}).get('request')); return writes[-1]
            return None
        proxy = ux.Proxy(record['url'], on_signal=on_signal)
        results = {}
        try:
            scenarios = [('ux01', 'desktop'), ('ux02', 'desktop'), ('ux03', 'desktop'), ('ux04', 'desktop'), ('ux05', 'desktop'), ('ux06', 'desktop'), ('ux07', 'desktop'),
                         ('ux08', 'desktop'), ('ux08', 'split'), ('ux08', 'mobile'), ('ux04', 'mobile'), ('ux01', 'mobile'), ('race', 'desktop'), ('disc', 'desktop')]
            for name, size in scenarios:
                width, height = ux.SIZES[size]
                result = ux.run(browser, proxy.url, name, width, height, profile, budget=45000 if name in ('ux01', 'disc') else 30000)
                results[f'{name}@{size}'] = {'ok': result.get('ok'), 'polls': result.get('polls'), 'checks': result.get('checks'), 'notes': result.get('notes'), 'error': result.get('error'),
                                             'scrollWidth': result.get('scrollWidth'), 'innerWidth': result.get('innerWidth')}
                if not result.get('ok'): problems.append(f'{name}@{size}: ' + str(result.get('error') or result.get('notes'))[:300])
            if len(writes) != 2 or not all(writes): problems.append(f'the ledger writes during ux01 did not happen: {writes}')
            shots = {}
            for name, scen_name, size, extra in (('overview-desktop', 'shot-list', 'desktop', ''), ('detail-P4-desktop', 'shot-detail', 'desktop', '&plan=P4'), ('detail-P1-desktop', 'shot-detail', 'desktop', '&plan=P1'),
                                                 ('detail-P1-split', 'shot-detail', 'split', '&plan=P1'), ('overview-mobile', 'shot-list', 'mobile', ''), ('detail-P4-mobile', 'shot-detail', 'mobile', '&plan=P4')):
                width, height = ux.SIZES[size]
                shots[name] = ux.screenshot(browser, proxy.url, scen_name, width, height, profile, evidence_dir / f'ux-{name}.png', extra=extra)
            if not all(shots.values()): problems.append(f'screenshots missing: {shots}')
            facts['screenshots'] = {k: str(evidence_dir / f'ux-{k}.png') for k, v in shots.items() if v}
        finally:
            proxy.stop(); stop_server(process)
        (work / 'ux-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding='utf-8')
        facts['results'] = str(work / 'ux-results.json'); facts['scenarios'] = {k: v['ok'] for k, v in results.items()}
        step('V14-ux', not problems, problems=problems, browser=browser, **facts)
    else:
        step('V14-ux', False, problems=problems, **facts)
    try:
        scen.stdin.close()
    except OSError: pass
    try:
        scen.wait(180)
    except subprocess.TimeoutExpired:
        scen.kill()
    if steps[-1]['result'] == 'fail': return finish()
    # V15: `track open` identity from the installed wheel (the daily open scripts go through this path)
    problems, facts = [], {}
    marker = Path(state) / 'tracking' / 'server.json'
    pids = []
    def opened(*extra):
        done = cli('track', 'open', '--no-browser', '--interval', '1', *extra)
        value = first_json(done.stdout) or {}
        if value.get('pid'): pids.append(value['pid'])
        return done.returncode, value
    try:
        code, first = opened()
        if code != 0 or not first.get('url') or first.get('reused') or not first.get('instance'): problems.append(f'first open: {code} {first}')
        code, again = opened()
        if code != 0 or not again.get('reused') or again.get('instance') != first.get('instance') or again.get('url') != first.get('url'): problems.append(f'second open did not reuse: {again}')
        status = first_json(cli('track', 'status').stdout) or {}
        if not status.get('reusable') or (status.get('health') or {}).get('version') != manifest['version']: problems.append(f'status: {status}')
        facts['first'] = {k: first.get(k) for k in ('url', 'pid', 'instance', 'version')}
        # a marker whose instance is not the one answering on that port: the real server keeps running, it is NOT reused, a new one starts, nothing is killed
        tampered = json.loads(marker.read_text(encoding='utf-8')); tampered['instance'] = 'deadbeefdeadbeef'
        marker.write_text(json.dumps(tampered), encoding='utf-8')
        code, third = opened()
        alive = get(first['url'] + 'api/health')[0] == 200
        if code != 0 or third.get('reused') or third.get('url') == first.get('url') or not alive or not (third.get('refused') or {}).get('reason', '').startswith('định danh khác'):
            problems.append(f'tampered marker: {third} alive={alive}')
        facts['tampered'] = {'new_url': third.get('url'), 'refused': (third.get('refused') or {}).get('reason'), 'old_server_alive': alive}
        # stop: only the server the marker names (the new one); the first one is still alive afterwards
        stopped = first_json(cli('track', 'stop').stdout) or {}
        if not stopped.get('stopped') or stopped.get('pid') != third.get('pid') or marker.exists() or get(first['url'] + 'api/health')[0] != 200 or get(third['url'] + 'api/health')[0] == 200:
            problems.append(f'stop: {stopped}')
        facts['stop'] = stopped
        # concurrent opens (the first server has no marker any more): one server, one marker
        procs = [subprocess.Popen([str(exe), '--project', project, '--state-root', state, 'track', 'open', '--no-browser', '--interval', '1'], env=env, cwd=str(work), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace') for _ in range(2)]
        outs = [first_json(p.communicate(timeout=120)[0]) or {} for p in procs]
        for o in outs:
            if o.get('pid'): pids.append(o['pid'])
        if not all(o.get('url') for o in outs) or outs[0].get('url') != outs[1].get('url') or sorted(bool(o.get('reused')) for o in outs) != [False, True]: problems.append(f'concurrent opens: {outs}')
        facts['concurrent'] = [{k: o.get(k) for k in ('url', 'pid', 'reused', 'waited_for_other_open')} for o in outs]
        stopped2 = first_json(cli('track', 'stop').stdout) or {}
        if not stopped2.get('stopped') or marker.exists(): problems.append(f'stop after concurrent: {stopped2}')
        done = cli('track', 'stop')
        if done.returncode != 2 or 'không có marker' not in done.stdout: problems.append('a second stop did not refuse: ' + done.stdout[-200:])
    finally:
        for pid in set(pids):
            try: os.kill(pid, signal.SIGTERM)
            except OSError: pass
        if marker.exists():
            try: marker.unlink()
            except OSError: pass
    if not step('V15-open-identity', not problems, problems=problems, **facts): return finish()
    # V11
    profile = work / 'browser profile'
    browser = find_browser(profile)
    evidence_dir = work / 'evidence'; evidence_dir.mkdir(exist_ok=True)
    if not browser:
        step('V11-browser', None, note='no headless Chrome/Edge executes a page script on this machine: the page was NOT seen rendered here')
    else:
        process, record = start_server(exe, project, state, env, work)
        problems, shots = [], {}
        try:
            dom = dump_dom(browser, record['url'], profile)
            cls, text = badge(dom)
            if cls != 'ok' or 'kết nối OK' not in (text or ''): problems.append(f'badge {cls} {text}')
            for plan_name in ('P1', 'P2'):
                if plan_name not in dom: problems.append('plan missing ' + plan_name)
            if '<span class="st waiting">đang chờ</span>' not in dom: problems.append('status word missing')
            if 'chưa được theo dõi' not in re.sub(r'<script>.*?</script>', '', dom, flags=re.S): problems.append('untracked section missing')   # the rendered body, not the page script
            detail_dom = dump_dom(browser, record['url'] + '?plan=P1', profile)
            if 'Timeline' not in detail_dom or 'node.produced' not in detail_dom or '<b>C</b>' not in detail_dom: problems.append('detail/timeline of P1 did not render')
            if 'hunter2-must-not-show' in dom + detail_dom: problems.append('password in the page')
            shots['list'] = screenshot(browser, record['url'], profile, evidence_dir / 'obs1-list.png')
            shots['detail'] = screenshot(browser, record['url'] + '?plan=P1', profile, evidence_dir / 'obs1-detail-P1.png')
            proxy = _Proxy(record['url'])
            try:
                lost = dump_dom(browser, proxy.url, profile)
                cls, text = badge(lost)
                if cls != 'bad' or 'MẤT KẾT NỐI' not in (text or ''): problems.append(f'disconnected badge {cls} {text}')
                shots['disconnected'] = screenshot(browser, proxy.url, profile, evidence_dir / 'obs1-disconnected.png')
            finally:
                proxy.stop()
        finally:
            stop_server(process)
        step('V11-browser', not problems, problems=problems, browser=browser, screenshots={k: str(evidence_dir / f'obs1-{n}.png') for k, n in (('list', 'list'), ('detail', 'detail-P1'), ('disconnected', 'disconnected'))}, written=shots)
    # V12
    final = first_json(cli('track', 'list', '--json', '--all-projects').stdout) or {}
    problems = []
    seq_now = final.get('source', {}).get('last_seq')
    # the viewers and CLIs of V5-V7 read between seq_after_task and seq_after_verify: only the scenario's own writes (request, verify, P2, untracked) moved the seq
    if seq_now is None or seq_now < seq_after_verify: problems.append(f'seq went backwards {seq_now} < {seq_after_verify}')
    marker = Path(state) / 'tracking' / 'server.json'
    if marker.exists(): problems.append('a server marker is left in the state root although no `track open` ran')
    step('V12-isolation', not problems, problems=problems, last_seq=seq_now, real_registry_before=registry_before)
    return finish()


if __name__ == '__main__':
    if len(sys.argv) != 3: raise SystemExit('usage: verify_obs1.py <package dir> <work dir>')
    sys.exit(main(sys.argv[1], sys.argv[2]))
