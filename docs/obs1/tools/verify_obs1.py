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
                    screenshots to <work>/evidence/ux-*.png. No browser -> skipped (partial). dev12 (Codex release review of dev11): stale_detail
                    at 1280 and 390 (R4: a dropped, 503 or late detail request never leaves another task's content or reply commands under the
                    selection), slow_detail (a detail read slower than the poll still paints; an unrenderable 200 ends in the error state) and
                    prov LAST (R1 on P9: identical bytes of generations 0/1 keep their own labels; 310 newer events written through scenario
                    `prov_history` and generation 2 resumed from generation 1's artifact through `prov_same`, both on THIS run's ledger)
  V15 open-identity `track open` from the installed wheel: a second open reuses the same instance; a marker whose instance does not match the server
                    answering on its port is NOT reused (a new server starts, the other one is not killed); two concurrent opens share one server;
                    `track stop` stops only the matching server and removes the marker; a second stop refuses
  V16 reply-template (dev9, P2-B) the reply template the page offers for a pending question, run through the installed `onecrew` from a terminal in
                    another folder (with a space): without --reference the parser refuses (exit 2, ledger untouched); with the placeholder filled the
                    answer is recorded on the TRIAL ledger and the question leaves "cần bạn" (fixture owner, never a real ledger)
  V17 release-review (dev12: the five findings of Codex's release review of dev11) on a root R15 of its OWN project and ledger (scenario
                    `release`; independent of V14, no browser needed), through the installed CLI, real `track serve` processes and the packaged
                    open/stop wrappers. R1: the byte-identical output of three generations stays one occurrence per (event, key) with that
                    event's own seq, time, generation and attempt; generation 2 lists the artifact it resumed from as inherited (source_occurrence
                    = generation 1's production) AND as its own output; after 310 newer events the windows 300 and 200 say timeline_complete=false
                    while generations 0/1 keep their outputs (never "no output"), an old event's eight keys stay indexed and the evidence door
                    (CLI + /api/evidence) opens them; evidence_index is the same at windows 5/300/5000; the CLI JSON equals /api/task.
                    R2: an isolated registry (this run's LOCALAPPDATA, never the real one) naming OTHER-PRIVATE-PROJECT -> OTHER-PRIVATE-LEDGER
                    and a sibling path sharing the project's prefix, plus a project R15B in the same ledger: the project-scoped CLI and a
                    --project-only server (overview, task, health, refused evidence, error bodies) name none of them, another project_id -> 403;
                    control: --all-projects and an all-projects server list them, ?project_id=<own> hides them; the registry file is restored.
                    R3: wait references with secret shapes (synthetic values) come out [withheld] in CLI JSON/text and HTTP, a read-only sqlite
                    query still finds the raw reference in the ledger, normal references and the reply template come out byte-identical.
                    R5: mo-/dung-trang-obs1.ps1 -PinFile (filtered env, -NoBrowser): the stop with pin A stops A only (viewer B on a sqlite backup
                    copy of the ledger keeps answering), the same pin again stops nothing, a stale pin of A leaves the reopened A2 alive, opening
                    state root A with the pin file of the live B is refused and starts no server; then no viewer process is left. The R15
                    ledger's last seq is unchanged by all these reads.
Writes <work>/verify-report.json; prints RESULT pass|partial|fail. Exit 0 only on pass.
`verify_obs1.py --release-review <venv> <new work dir>` runs V17 alone against the onecrew of an EXISTING venv (for example a frozen older wheel:
red-before-green evidence), with the same isolation; writes <work>/release-review-report.json.
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


def up(url):
    """True when something answers /api/health at url (a stopped server refuses the connection)."""
    try: return get(url + 'api/health', timeout=3)[0] == 200
    except OSError: return False


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


def _chrome(argv, timeout=120, **kw):
    """One headless Chrome run; a hung Chrome (TimeoutExpired, seen once in ~40 runs) is retried once before the step is failed."""
    for attempt in (1, 2):
        try: return run(argv, timeout=timeout, **kw)
        except subprocess.TimeoutExpired:
            if attempt == 2: raise
            time.sleep(2)


def dump_dom(exe, url, profile, budget=4000):
    done = _chrome([exe, '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', f'--user-data-dir={profile}', '--window-size=1400,1000',
                    f'--virtual-time-budget={budget}', '--dump-dom', url], text=True, encoding='utf-8', errors='replace', timeout=120)
    return done.stdout


def screenshot(exe, url, profile, path, budget=4000):
    _chrome([exe, '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', f'--user-data-dir={profile}', '--window-size=1400,1000',
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


def powershell_template(line, script):
    """Run one PowerShell template line through the REAL powershell.exe from a script file (the shell the templates are written for), with $SDK set
    to something else first: a correctly quoted path must not change."""
    script = Path(script); script.write_text('$SDK = "CHANGED"\n' + line + '\nexit $LASTEXITCODE\n', encoding='utf-8-sig')
    env = PS_ENV[0] or {k: v for k, v in os.environ.items() if k.upper() not in AI_MARKERS}   # the filtered env ONLY (never the caller's raw one: a shell carrying CLAUDECODE made the owner verb refuse, 03/11)
    return run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)], env=env, cwd=str(script.parent), text=True, encoding='utf-8', errors='replace', timeout=180)


PS_ENV = [{}]


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


# ---- V17: the five findings of Codex's release review of dev11 (R1, R2, R3, R5; R4 is the browser's: V14 stale_detail) ----------------------

REFERENCE_PLACEHOLDER = '<lý do hoặc bằng chứng của bạn>'          # a reply template's marked placeholder (tracking.REFERENCE_PLACEHOLDER), compared byte for byte
SHAPE = ('seq', 'key', 'kind', 'role', 'at', 'node', 'generation', 'attempt', 'attempt_basis', 'output')
LIST_VIEWERS = ("$ErrorActionPreference = 'Stop'\n"                    # a failed listing exits non-zero (None), never an empty list that reads as "no viewer"
                "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false\n"
                "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -and $_.CommandLine -like '*track serve*' } | "
                "ForEach-Object { [Console]::Out.WriteLine([string]$_.ProcessId + '|' + $_.CommandLine) }\n")   # one raw line per process: no host line wrapping


def canon(items):
    """A list of tuples in a stable order whatever their value types (a missing field is None)."""
    return sorted((tuple(i) for i in items), key=lambda t: json.dumps(t, default=str))


def _forms(needle):
    """The ways a value can be spelled in a body: as is, JSON-escaped (a Windows path doubles its backslashes) and with forward slashes."""
    return {needle.casefold(), json.dumps(needle, ensure_ascii=False)[1:-1].casefold(), needle.replace('\\', '/').casefold()}


def leaks(text, needles):
    low = (text or '').casefold()
    return sorted({n for n in needles if any(f in low for f in _forms(n))})


def health_of(url):
    """The /api/health record of the tracking server answering at `url`, or None."""
    try:
        code, body, _ = get(url + 'api/health', timeout=3)
        value = json.loads(body) if code == 200 else None
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) and value.get('ok') is True else None


def viewer_processes(roots, env, script):
    """{pid: command line} of the python processes running `track serve` for one of the state roots `roots` (Win32_Process through PowerShell
    CIM; a venv launcher and its interpreter both count), or None when the process list cannot be read."""
    script = Path(script)
    if not script.is_file(): script.write_text(LIST_VIEWERS, encoding='utf-8-sig')
    try:
        done = run(['powershell', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(script)], env=env, text=True, encoding='utf-8', errors='replace', timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0: return None
    wanted = [str(r).casefold() for r in roots]
    out = {}
    for line in done.stdout.splitlines():
        pid, _, command = line.partition('|')
        if pid.strip().isdigit() and any(w in command.casefold() for w in wanted): out[int(pid)] = command.strip()
    return out


def _ledger_rows(state_root, sql, args=()):
    """Rows of a read-only query on the ledger of `state_root` (sqlite mode=ro + query_only), outside the product: what the ledger itself holds."""
    import sqlite3
    conn = sqlite3.connect((Path(state_root) / 'ledger.sqlite3').as_uri() + '?mode=ro', uri=True)
    try:
        conn.execute('PRAGMA query_only=1')
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _r1(rel, rcli, exe, env, work, **_):
    """R1: evidence identity per occurrence (event, key) with that event's own generation/attempt; inherited and produced roles of one key
    together; a bounded history that never reads as "no output"; the door opens old keys; CLI JSON = GET /api/task."""
    problems, facts = [], {}
    plan, K, R, old = rel['plan'], rel['artifact'], rel['receipt'], rel['old_decision']
    gens = {g['generation']: g for g in rel['generations']}
    att = {g: gens[g]['attempt'] for g in gens}
    process, record = start_server(exe, rel['project_dir'], rel['state_root'], env, work)
    try:
        url = record['url']

        def show(*extra):
            done = rcli('track', 'show', plan, '--json', *extra)
            return (first_json(done.stdout) or {'_error': 'no JSON'}) if done.returncode == 0 else {'_error': f'exit {done.returncode}: ' + text_of(done)[-300:]}

        def api(path):
            code, body, _ = get(url + path, timeout=60)
            try: return json.loads(body) if code == 200 else {'_error': f'{code}: {body[:300]}'}
            except ValueError: return {'_error': body[:300]}
        views = {'cli 5000': show('--timeline', '5000'), 'cli 300': show('--timeline', '300'), 'cli 5': show('--timeline', '5'), 'cli default': show(),
                 'api 300': api(f'api/task?plan={plan}&timeline=300'), 'api default': api(f'api/task?plan={plan}')}
        door = {}
        for i in (0, 7):
            key, text = old['keys'][i], f'r15 old evidence blob {i}'
            done = rcli('track', 'evidence', plan, key)
            code, body, _ = get(url + f'api/evidence?plan={plan}&key={key}&format=text', timeout=60)
            door[f'old key {i}'] = {'cli_exit': done.returncode, 'cli_opened': text in done.stdout, 'http': code, 'http_opened': code == 200 and text in body}
        done = rcli('track', 'evidence', plan, rel['unnamed_key'])
        code, body, _ = get(url + f'api/evidence?plan={plan}&key={rel["unnamed_key"]}', timeout=60)
        door['key no event names'] = {'cli_exit': done.returncode, 'cli_refused': '"refused"' in done.stdout, 'http': code}
    finally:
        stop_server(process)
    facts['door'] = door
    for name, d in door.items():
        if name.startswith('old key') and not (d['cli_exit'] == 0 and d['cli_opened'] and d['http'] == 200 and d['http_opened']):
            problems.append(f'R1 door: the {name} of the old decision (older than every window) does not open: {d}')
    if door['key no event names'] != {'cli_exit': 3, 'cli_refused': True, 'http': 403}:
        problems.append(f"R1 door: a key no event of {plan} names is not refused: {door['key no event names']}")
    broken = {k: v.get('_error') for k, v in views.items() if v.get('_error')}
    if broken: return problems + [f'R1: no detail JSON from {broken}'], facts

    def occ(v, **kw):
        return [x for x in v.get('evidence_index') or [] if all(x.get(k) == want for k, want in kw.items())]
    both = canon([(K, 'artifact'), (R, 'receipt')])
    # (a) the byte-identical output of three generations: one occurrence per (event, key), each with ITS event's seq, time, generation and attempt
    for label in ('cli 5000', 'api 300'):
        v = views[label]
        for g in (0, 1, 2):
            e = gens[g]
            have = canon((x.get('key'), x.get('kind'), x.get('role'), x.get('node'), x.get('generation'), x.get('attempt'), x.get('at'), x.get('output')) for x in occ(v, seq=e['produced_seq']))
            want = canon([(K, 'node.produced', 'artifact', 'C', g, e['attempt'], e['produced_at'], True), (R, 'node.produced', 'receipt', 'C', g, e['attempt'], e['produced_at'], True)])
            if have != want: problems.append(f'R1 identical bytes ({label}): node.produced #{e["produced_seq"]} of generation {g} has the occurrences {have}; want {want}')
        uses = canon((x.get('generation'), x.get('attempt'), x.get('seq')) for x in occ(v, key=R, kind='node.produced'))
        if uses != canon((g, att[g], gens[g]['produced_seq']) for g in (0, 1, 2)):
            problems.append(f'R1 identical bytes ({label}): the receipt key all three generations wrote has the node.produced occurrences {uses}; want one per generation')
    facts['produced'] = {f'generation {g}': {'seq': gens[g]['produced_seq'], 'attempt': att[g], 'occurrences': len(occ(views['api 300'], seq=gens[g]['produced_seq']))} for g in (0, 1, 2)}
    # (b) generation 2 resumed from generation 1's artifact and wrote the same bytes: inherited (with its source occurrence) AND its own output
    for label in ('cli 5000', 'api 300'):
        v = views[label]
        cur = next((r for r in (v.get('gantt') or {}).get('rows') or [] if r.get('current') and r.get('node') == 'C'), None)
        if not cur or (cur.get('attempt'), cur.get('generation')) != (att[2], 2):
            problems.append(f'R1 inherited+produced ({label}): the current Gantt row of node C is {cur and (cur.get("attempt"), cur.get("generation"))}; want ({att[2]}, 2)'); continue
        inh = [x for x in cur.get('inherits') or [] if x.get('key') == K]
        got = [(x.get('kind'), x.get('from_generation'), x.get('from_attempt')) for x in inh]
        if got != [('resume_artifact', 1, att[1])]: problems.append(f'R1 inherited+produced ({label}): the current row inherits {got} for the artifact; want [(resume_artifact, 1, {att[1]})]')
        src = (inh[0].get('source_occurrence') or {}) if inh else {}
        want_src = {'seq': gens[1]['produced_seq'], 'kind': 'node.produced', 'role': 'artifact', 'generation': 1, 'attempt': att[1]}
        if {k: src.get(k) for k in want_src} != want_src: problems.append(f'R1 inherited+produced ({label}): source_occurrence {src}; want the production of generation 1 {want_src}')
        own = canon((x.get('key'), x.get('role')) for x in occ(v, attempt=att[2], kind='node.produced', output=True))
        if own != both: problems.append(f'R1 inherited+produced ({label}): the outputs of generation 2 are {own}; the artifact it inherited is also its own output')
        resumed = [(x.get('role'), x.get('generation'), x.get('attempt')) for x in occ(v, key=K, kind='node.resumed')]
        if resumed != [('resume_artifact', 1, att[1])]: problems.append(f'R1 inherited+produced ({label}): the inheritance occurrence (node.resumed) is {resumed}; want [(resume_artifact, 1, {att[1]})]')
        if label == 'api 300': facts['inherited'] = {'inherits': got, 'source_occurrence': src, 'own_outputs': own}
    # (c) 310 newer events: windows 300 and 200 are not the whole history, and nothing older than them reads as "no output"
    for label, limit in (('cli 300', 300), ('api 300', 300), ('cli default', 200), ('api default', 200)):
        v = views[label]
        shown = [e.get('seq') for e in v.get('timeline') or []]
        window = {'timeline_limit': v.get('timeline_limit'), 'timeline_complete': v.get('timeline_complete'), 'timeline_total': v.get('timeline_total'), 'shown': len(shown)}
        facts.setdefault('window', {})[label] = window
        if (window['timeline_limit'] != limit or window['timeline_complete'] is not False or not isinstance(window['timeline_total'], int)
                or window['timeline_total'] <= 300 or window['shown'] != limit):
            problems.append(f'R1 bounded history ({label}): {window}; want limit {limit}, timeline_complete false, {limit} events shown of more than 300')
        inside = sorted(set(shown) & ({gens[g]['produced_seq'] for g in gens} | {old['seq']}))
        if inside: problems.append(f'R1 setup ({label}): events {inside} (productions, old decision) are inside the window: the data set does not test the window')
        for g in (0, 1):
            out = canon((x.get('key'), x.get('seq')) for x in occ(v, node='C', generation=g, kind='node.produced'))
            if out != canon([(K, gens[g]['produced_seq']), (R, gens[g]['produced_seq'])]):
                problems.append(f'R1 bounded history ({label}): generation {g} (older than the window) has the produced occurrences {out}; its outputs must stay in evidence_index')
        for g in (0, 1, 2):
            row = next((r for r in (v.get('gantt') or {}).get('rows') or [] if r.get('attempt') == att[g]), None)
            outs = canon((x.get('key'), x.get('role')) for x in occ(v, attempt=att[g], kind='node.produced', output=True))
            if not row or not any(m.get('kind') == 'node.produced' for m in row.get('marks') or []) or outs != both:
                problems.append(f'R1 bounded history ({label}): the Gantt row of generation {g} ({att[g]}) is {"there" if row else "missing"} with the outputs {outs}: it would read as "no output"')
        named = canon((x.get('key'), x.get('role')) for x in occ(v, seq=old['seq']))
        if named != canon((k, f'evidence[{i}]') for i, k in enumerate(old['keys'])):
            problems.append(f'R1 bounded history ({label}): the old decision #{old["seq"]} names 8 keys; evidence_index holds {len(named)} of them with their roles')
        if not isinstance(v.get('evidence_basis'), str) or not v['evidence_basis'].strip(): problems.append(f'R1 ({label}): no evidence_basis')
    # (d) the provenance does not depend on the window; the 6-key display cap of a timeline row is not the index
    shape = lambda v: [{k: x.get(k) for k in SHAPE} for x in v.get('evidence_index') or []]
    base = shape(views['cli 5000']); facts['evidence_index_entries'] = len(base)
    for label in ('cli 5', 'cli 300', 'cli default', 'api 300', 'api default'):
        if shape(views[label]) != base: problems.append(f'R1: evidence_index at {label} ({len(shape(views[label]))} entries) differs from the full history ({len(base)}): provenance must not depend on the window')
    row = next((e for e in views['cli 5000'].get('timeline') or [] if e.get('seq') == old['seq']), None)
    facts['old_decision_row'] = row and {'evidence_count': row.get('evidence_count'), 'evidence_shown': len(row.get('evidence') or [])}
    if facts['old_decision_row'] != {'evidence_count': 8, 'evidence_shown': 6}:
        problems.append(f'R1: the timeline row of the old decision (window 5000) is {facts["old_decision_row"]}; want evidence_count 8 with 6 keys shown (display cap, not the index)')
    # (e) one model: the CLI JSON and GET /api/task agree on these fields (window 300)
    def fields(v):
        return {'evidence_index': v.get('evidence_index'), 'evidence_keys': v.get('evidence_keys'), 'evidence_basis': v.get('evidence_basis'), 'timeline_limit': v.get('timeline_limit'),
                'timeline_complete': v.get('timeline_complete'), 'timeline_total': v.get('timeline_total'),
                'timeline': [(e.get('seq'), e.get('evidence_count'), e.get('evidence')) for e in v.get('timeline') or []],
                'inherits': [(r.get('attempt'), r.get('inherits')) for r in (v.get('gantt') or {}).get('rows') or []]}
    a, b = fields(views['cli 300']), fields(views['api 300'])
    facts['cli_http_differ'] = [k for k in a if a[k] != b[k]]
    if facts['cli_http_differ']: problems.append(f'R1: the CLI JSON and GET /api/task (window 300) differ in {facts["cli_http_differ"]}')
    return problems, facts


def _r3(rel, rcli, exe, env, work, **_):
    """R3: one outbound guard: no secret shape leaves through any projection, the ledger keeps the raw text, normal values stay byte-identical."""
    problems, facts = [], {}
    plan, r3, req = rel['plan'], rel['r3'], rel['request']
    raw, names = list(r3['raw']) + [r3['question_raw']], list(r3['shapes']) + ['question']
    process, record = start_server(exe, rel['project_dir'], rel['state_root'], env, work)
    try:
        url = record['url']
        outs = {'cli show --json': rcli('track', 'show', plan, '--json').stdout, 'cli show --json --timeline 5000': rcli('track', 'show', plan, '--json', '--timeline', '5000').stdout,
                'cli show (text)': rcli('track', 'show', plan).stdout, 'cli list --json': rcli('track', 'list', '--json').stdout,
                'cli list --json --all-projects': rcli('track', 'list', '--json', '--all-projects').stdout, 'cli list (text)': rcli('track', 'list').stdout}
        for path in (f'api/task?plan={plan}', f'api/task?plan={plan}&timeline=5000', 'api/overview', 'api/health'):
            outs['GET /' + path] = get(url + path, timeout=60)[1]
    finally:
        stop_server(process)
    found = {label: [names[i] for i, value in enumerate(raw) if value in text] for label, text in outs.items()}
    facts['raw_secret_found_in'] = found = {k: v for k, v in found.items() if v}
    if found: problems.append(f'R3: a raw secret value leaves through {found} (shape names; the values are not repeated here)')
    q = lambda s: "'" + str(s).replace("'", "''") + "'"
    prefix = f"& {q(exe)} --project {q(rel['project_path'])} --state-root {q(rel['state_root'])} question answer {req['id']} --revision {req['revision']} --choice "
    want_options, generic = {o: prefix + o + ' --reference ' + q(REFERENCE_PLACEHOLDER) for o in req['options']}, prefix + '<option-id> --reference ' + q(REFERENCE_PLACEHOLDER)
    for label in ('cli show --json', f'GET /api/task?plan={plan}'):
        d = first_json(outs[label]) or {}
        waits = [w.get('ref') for w in d.get('waits') or [] if w.get('source') == 'executor.observed']
        ew = [w.get('ref') for w in (d.get('measure') or {}).get('executor_waits') or []]
        for field, got in (('waits[].ref', waits), ('measure.executor_waits[].ref', ew)):
            masked, kept = [r for r in got if isinstance(r, str) and '[withheld]' in r], [r for r in got if r in r3['normal_refs']]
            facts.setdefault('refs', {})[f'{label}: {field}'] = {'masked': masked, 'normal_byte_identical': len(kept), 'total': len(got)}
            if 'password=[withheld]' not in got: problems.append(f'R3 ({label}): {field} has no "password=[withheld]" (the reference of the Codex probe)')
            if len(masked) != len(r3['secret_refs']) or len(got) != len(r3['secret_refs']) + len(r3['normal_refs']):
                problems.append(f'R3 ({label}): {field}: {len(masked)} of {len(got)} references masked; want {len(r3["secret_refs"])} masked of {len(r3["secret_refs"]) + len(r3["normal_refs"])}')
            if sorted(kept) != sorted(r3['normal_refs']): problems.append(f'R3 ({label}): {field}: normal references not byte-identical, missing {sorted(set(r3["normal_refs"]) - set(kept))}')
        need = next((n for n in d.get('needs_user') or [] if n.get('id') == req['id']), None) or {}
        options = {o.get('id'): o.get('reply_command') for o in need.get('options') or []}
        facts.setdefault('reply_template_byte_identical', {})[label] = options == want_options and need.get('reply_command') == generic
        if not facts['reply_template_byte_identical'][label]:
            problems.append(f'R3 ({label}): the reply template is not byte-identical: {need.get("reply_command")!r} {options}; want {generic!r}')
    facts['text'] = {'withheld_shown': '[withheld]' in outs['cli show (text)'], 'template_byte_identical': generic in outs['cli show (text)']}
    if not facts['text']['withheld_shown']: problems.append('R3: `track show` (text) shows no [withheld] (the question of R15 carries a password)')
    if not facts['text']['template_byte_identical']: problems.append('R3: `track show` (text) does not carry the reply template byte-identical')
    refs = {((json.loads(p) or {}).get('basis') or {}).get('ref') for (p,) in _ledger_rows(rel['state_root'], "SELECT payload FROM events WHERE kind='executor.observed'")}
    question = [p for (p,) in _ledger_rows(rel['state_root'], 'SELECT payload FROM requests WHERE id=?', (req['id'],))]
    facts['ledger_keeps_raw'] = {'references': [names[i] for i, ref in enumerate(r3['secret_refs']) if ref in refs], 'question': any(r3['question_raw'] in p for p in question)}
    if facts['ledger_keeps_raw'] != {'references': list(r3['shapes']), 'question': True}:
        problems.append(f'R3: the ledger no longer holds the raw text it was given ({facts["ledger_keeps_raw"]}): the view redacts, never the ledger')
    return problems, facts


def _r2(rel, rcli, exe, env, work, **_):
    """R2: under a project scope the WHOLE returned model holds nothing of another project, the untracked registry list included; the
    all-projects view keeps listing them. The registry is this run's isolated one and is restored byte for byte afterwards."""
    problems, facts = [], {}
    plan, own, b, unnamed = rel['plan'], rel['project_id'], rel['other'], rel['unnamed_key']
    work = Path(work).resolve()
    registry = Path(env['LOCALAPPDATA']).resolve() / 'OneCrew' / 'hook-projects.json'
    if not str(registry).casefold().startswith(str(work).casefold() + os.sep):
        return [f"R2: the registry {registry} is not under the work folder (not this run's LOCALAPPDATA): nothing written"], facts
    saved = registry.read_bytes() if registry.is_file() else None
    other, other_ledger = work / 'OTHER-PRIVATE-PROJECT', work / 'OTHER-PRIVATE-LEDGER'
    sibling = rel['project_dir'] + '-sibling-private'                      # shares the project's path as a prefix: a prefix match would let it through
    needles = [str(other), str(other_ledger), 'OTHER-PRIVATE', sibling, 'sibling-private', b['project_dir'], b['project_id'], b['project_id'][:12], 'R15B OTHER PROJECT PRIVATE']
    facts['registry'] = {'file': str(registry), 'projects': [rel['project_dir'], str(other), sibling]}
    try:
        registry.parent.mkdir(parents=True, exist_ok=True)
        registry.write_text(json.dumps({'projects': {rel['project_dir']: rel['state_root'], str(other): str(other_ledger), sibling: rel['state_root']}}), encoding='utf-8')
        scoped = {'track list --json': rcli('track', 'list', '--json'), 'track list': rcli('track', 'list'), f'track show {plan} --json': rcli('track', 'show', plan, '--json'),
                  f'track show {plan}': rcli('track', 'show', plan), f'track show {b["plan"]}': rcli('track', 'show', b['plan']),
                  'track evidence (a key no event names)': rcli('track', 'evidence', plan, unnamed)}
        for label, done in scoped.items():
            bad = leaks(text_of(done), needles)
            if bad: problems.append(f'R2 project-scoped `{label}` (exit {done.returncode}) names {bad}')
        listed = first_json(scoped['track list --json'].stdout) or {}
        plans = [t.get('plan') for p in listed.get('projects') or [] for t in p.get('tasks') or []]
        facts['scoped_cli'] = {'plans': plans, 'registry_projects_without_plan': (listed.get('untracked') or {}).get('registry_projects_without_plan'),
                               'show_other_plan_exit': scoped[f'track show {b["plan"]}'].returncode, 'evidence_exit': scoped['track evidence (a key no event names)'].returncode}
        if plans != [plan] or facts['scoped_cli']['registry_projects_without_plan'] != []:
            problems.append(f"R2 project-scoped `track list --json`: plans {plans}, registry projects without plan {facts['scoped_cli']['registry_projects_without_plan']}; want [{plan}] and []")
        if facts['scoped_cli']['show_other_plan_exit'] != 2: problems.append(f"R2: `track show {b['plan']}` scoped to {plan}'s project exits {facts['scoped_cli']['show_other_plan_exit']} (want 2)")
        if facts['scoped_cli']['evidence_exit'] != 3: problems.append(f"R2: `track evidence` of a key no event names exits {facts['scoped_cli']['evidence_exit']} (want 3, refused)")
        process, record = start_server(exe, rel['project_dir'], rel['state_root'], env, work, project_only=True)
        try:
            url, codes = record['url'], {}
            want = {'api/overview': 200, f'api/overview?project_id={own}': 200, f'api/task?plan={plan}': 200, f'api/task?plan={plan}&timeline=5000': 200, 'api/health': 200,
                    f'api/task?plan={b["plan"]}': 404, 'api/task?plan=NOPE': 404, f'api/evidence?plan={plan}&key={unnamed}': 403, f'api/evidence?plan={plan}&key=zz': 404,
                    'api/task': 400, 'api/nowhere': 404, f'api/overview?project_id={b["project_id"]}': 403, f'api/task?plan={b["plan"]}&project_id={b["project_id"]}': 403,
                    'api/overview?project_id=' + 'f' * 64: 403}
            for path, code_want in want.items():
                code, body, _ = get(url + path, timeout=60); codes[path] = code
                if code != code_want: problems.append(f'R2 --project-only server: GET /{path} -> {code}, want {code_want}')
                bad = leaks(body, needles)
                if bad: problems.append(f'R2 --project-only server: GET /{path} ({code}) names {bad}')
            code, body, _ = get(url + 'api/overview', timeout=60)
            without = (json.loads(body).get('untracked') or {}).get('registry_projects_without_plan') if code == 200 else None
            facts['project_only_server'] = {'scope': record.get('project_id'), 'codes': codes, 'registry_projects_without_plan': without}
            if record.get('project_id') != own: problems.append(f"R2: the --project-only server's scope is {record.get('project_id')}, want {own}")
            if without != []: problems.append(f'R2 --project-only server: /api/overview lists registry projects without plan {without}; want []')
        finally:
            stop_server(process)
        # controls: all projects is the authorized view that lists them; ?project_id=<own> narrows it like the project scope
        listed = first_json(rcli('track', 'list', '--json', '--all-projects').stdout) or {}
        reg = {os.path.normcase(r.get('project') or ''): r for r in (listed.get('untracked') or {}).get('registry_projects_without_plan') or []}
        o, s = reg.get(os.path.normcase(str(other))) or {}, reg.get(os.path.normcase(sibling)) or {}
        facts['all_projects_cli'] = {'plans': sorted(t.get('plan') for p in listed.get('projects') or [] for t in p.get('tasks') or []),
                                     'registry_projects_without_plan': [r.get('project') for r in reg.values()], 'other_state_root': o.get('state_root'),
                                     'other_same_state_root': o.get('same_state_root'), 'sibling_same_state_root': s.get('same_state_root')}
        if o.get('state_root') != str(other_ledger) or o.get('same_state_root') is not False or s.get('same_state_root') is not True or os.path.normcase(rel['project_dir']) in reg:
            problems.append(f"R2 control: `track list --json --all-projects` must list OTHER-PRIVATE-PROJECT -> OTHER-PRIVATE-LEDGER and the sibling (not the project with a plan): {facts['all_projects_cli']}")
        if facts['all_projects_cli']['plans'] != sorted([plan, b['plan']]): problems.append(f"R2 control: all projects list the plans {facts['all_projects_cli']['plans']}")
        process, record = start_server(exe, rel['project_dir'], rel['state_root'], env, work)
        try:
            url = record['url']
            c1, b1, _ = get(url + 'api/overview', timeout=60)
            c2, b2, _ = get(url + f'api/overview?project_id={own}', timeout=60)
            c3, b3, _ = get(url + f'api/task?plan={plan}&project_id={own}', timeout=60)
            c4, _b4, _ = get(url + f'api/task?plan={b["plan"]}&project_id={b["project_id"]}', timeout=60)
            narrowed = (json.loads(b2).get('untracked') or {}).get('registry_projects_without_plan') if c2 == 200 else None
            facts['all_projects_server'] = {'overview': c1, 'lists_other_and_sibling': 'OTHER-PRIVATE-PROJECT' in b1 and 'sibling-private' in b1, 'narrowed_to_own': c2,
                                            'narrowed_registry': narrowed, 'narrowed_names': leaks(b2, needles), 'task_own': c3, 'task_own_names': leaks(b3, needles), 'task_other_by_its_id': c4}
            f = facts['all_projects_server']
            if c1 != 200 or not f['lists_other_and_sibling']: problems.append(f'R2 control: the all-projects server does not list OTHER-PRIVATE-PROJECT and the sibling: {f}')
            if c2 != 200 or narrowed != [] or f['narrowed_names'] or c3 != 200 or f['task_own_names']: problems.append(f'R2: the all-projects server narrowed with ?project_id=<own> still names other projects: {f}')
            if c4 != 200: problems.append(f'R2 control: the all-projects server refuses {b["plan"]} named with its own project_id: {c4}')
        finally:
            stop_server(process)
    finally:
        if saved is None:
            try: registry.unlink()
            except OSError: pass
        else:
            registry.write_bytes(saved)
        facts['registry_restored'] = (registry.read_bytes() if registry.is_file() else None) == saved
    if not facts['registry_restored']: problems.append('R2: the isolated registry file was not restored')
    return problems, facts


def _r5(rel, rcli, exe, env, work, venv, **_):
    """R5: the packaged open/stop wrappers with -PinFile stop exactly the viewer they opened (instance + pid of the marker and of /api/health),
    never another one; an open never overwrites the pin of a live viewer of another state root and then starts nothing."""
    import sqlite3
    problems, facts = [], {}
    here = Path(__file__).resolve().parent
    mo, dung = here / 'mo-trang-obs1.ps1', here / 'dung-trang-obs1.ps1'
    if not (mo.is_file() and dung.is_file()): return [f'R5: {mo.name} / {dung.name} are not next to the verifier ({here})'], facts
    ps_env, work = PS_ENV[0] or env, Path(work).resolve()
    proj, state_a, state_b = rel['project_dir'], Path(rel['state_root']), work / 'r15 copy'
    state_b.mkdir()                                                        # B: a sqlite backup copy of the ledger (+ plans, snapshots) = its own state root
    src, dst = sqlite3.connect((state_a / 'ledger.sqlite3').as_uri() + '?mode=ro', uri=True), sqlite3.connect(str(state_b / 'ledger.sqlite3'))
    try: src.backup(dst)
    finally: src.close(); dst.close()
    for name in ('plans', 'snapshots'):
        if (state_a / name).is_dir(): shutil.copytree(state_a / name, state_b / name)
    pins = work / 'r15 pins'; pins.mkdir(exist_ok=True)
    pa, pb, pa2 = pins / 'pin A.json', pins / 'pin B.json', pins / 'pin A2.json'
    lister, roots = work / 'r15 list viewers.ps1', [state_a, state_b]

    def ps(script, *args):
        done = run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script), *[str(a) for a in args]], env=ps_env, cwd=str(work),
                   text=True, encoding='utf-8', errors='replace', timeout=180)
        return done.returncode, (done.stdout or '') + (done.stderr or '')

    def opened(state, pin): return ps(mo, '-Venv', venv, '-Project', proj, '-StateRoot', state, '-NoBrowser', '-Interval', '1', '-PinFile', pin)

    def stopped(state, pin): return ps(dung, '-Venv', venv, '-Project', proj, '-StateRoot', state, '-PinFile', pin)

    def pin_of(path):
        try: value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        except (OSError, ValueError): return None
        return value if isinstance(value, dict) else None

    def alive(pin):
        h = health_of(pin['url']) if pin and pin.get('url') else None
        return bool(h and h.get('instance') == pin.get('instance') and h.get('pid') == pin.get('pid'))

    def marker(state):
        done = run([exe, '--project', proj, '--state-root', str(state), 'track', 'status'], env=env, cwd=work, text=True, encoding='utf-8', errors='replace', timeout=120)
        record = (first_json(done.stdout) or {}).get('marker') or {}
        return (record.get('instance'), record.get('pid')) if record else None

    def short(pin): return pin and {k: pin.get(k) for k in ('url', 'pid', 'instance', 'state_root')}
    viewers = []                                                           # every viewer opened here: stopped in `finally` if it still answers as itself
    try:
        before = viewer_processes(roots, ps_env, lister)
        facts['processes_before'] = sorted(before) if before is not None else None
        if before is None: return problems + ['R5: the viewer processes cannot be listed (PowerShell Get-CimInstance Win32_Process)'], facts
        if before: problems.append(f'R5 setup: viewers of the V17 ledgers already run: {sorted(before)}')
        code, out = opened(state_a, pa); A = pin_of(pa)
        if A: viewers.append(A)
        facts['open_A'] = {'exit': code, 'pin': short(A), 'alive': alive(A), 'marker_is_A': bool(A) and marker(state_a) == (A.get('instance'), A.get('pid'))}
        if code != 0 or not A or A.get('kind') != 'obs1-viewer-pin' or not facts['open_A']['alive'] or not facts['open_A']['marker_is_A']:
            return problems + [f"R5: open A with -PinFile: {facts['open_A']}: " + out[-400:]], facts
        code, out = opened(state_b, pb); B = pin_of(pb)
        if B: viewers.append(B)
        facts['open_B'] = {'exit': code, 'pin': short(B), 'alive': alive(B)}
        if code != 0 or not B or not facts['open_B']['alive'] or B.get('instance') == A.get('instance') or B.get('url') == A.get('url'):
            return problems + [f"R5: open B (a backup copy of the ledger) with -PinFile: {facts['open_B']}: " + out[-400:]], facts
        stale = pa.read_bytes()
        code, out = stopped(state_a, pa)                                   # (1) the stop with pin A stops A, and only A
        facts['stop_A'] = {'exit': code, 'A_alive': alive(A), 'B_alive': alive(B), 'pin_A_removed': not pa.exists()}
        if facts['stop_A'] != {'exit': 0, 'A_alive': False, 'B_alive': True, 'pin_A_removed': True}: problems.append(f"R5: stop with pin A: {facts['stop_A']}: " + out[-300:])
        code, out = stopped(state_a, pa)                                   # (2) the same pin again: nothing to stop
        facts['stop_A_again'] = {'exit': code, 'refused': 'KHONG DUNG GI' in out, 'B_alive': alive(B)}
        if facts['stop_A_again'] != {'exit': 2, 'refused': True, 'B_alive': True}: problems.append(f"R5: a second stop with pin A: {facts['stop_A_again']}: " + out[-300:])
        code, out = opened(state_a, pa2); A2 = pin_of(pa2)                 # (3) A reopened (A2); the stale pin of A stops nothing and A2 stays
        if A2: viewers.append(A2)
        facts['reopen_A2'] = {'exit': code, 'pin': short(A2), 'alive': alive(A2)}
        if code != 0 or not A2 or not facts['reopen_A2']['alive'] or A2.get('instance') == A.get('instance'):
            return problems + [f"R5: reopen A with a new pin: {facts['reopen_A2']}: " + out[-400:]], facts
        pa.write_bytes(stale)
        code, out = stopped(state_a, pa)
        facts['stale_pin'] = {'exit': code, 'refused': 'KHONG DUNG GI' in out, 'A2_alive': alive(A2), 'B_alive': alive(B), 'marker_is_A2': marker(state_a) == (A2.get('instance'), A2.get('pid'))}
        if facts['stale_pin'] != {'exit': 2, 'refused': True, 'A2_alive': True, 'B_alive': True, 'marker_is_A2': True}: problems.append(f"R5: stop with the stale pin of A: {facts['stale_pin']}: " + out[-300:])
        try: pa.unlink()                                                   # the stale pin is this check's own fixture file
        except OSError: pass
        procs, kept = viewer_processes(roots, ps_env, lister), pb.read_bytes()   # (4) state root A opened with the pin file of the live B: refused, nothing started
        code, out = opened(state_a, pb)
        after = viewer_processes(roots, ps_env, lister)
        f4 = facts['open_A_with_pin_of_B'] = {'exit': code, 'refused': 'KHONG DAT' in out and 'so khac' in out, 'pin_B_unchanged': pb.read_bytes() == kept, 'B_alive': alive(B),
                                              'A2_alive': alive(A2), 'marker_is_A2': marker(state_a) == (A2.get('instance'), A2.get('pid')),
                                              'processes_before': sorted(procs) if procs is not None else None, 'processes_after': sorted(after) if after is not None else None}
        if code == 0 or not (f4['refused'] and f4['pin_B_unchanged'] and f4['B_alive'] and f4['A2_alive'] and f4['marker_is_A2']) or procs is None or after != procs:
            problems.append(f'R5: open of state root A with the pin file of the live viewer B: {f4}: ' + out[-300:])
        code_b, out_b = stopped(state_b, pb); code_a, out_a = stopped(state_a, pa2)   # (5) each viewer stopped with its own pin
        facts['stop_B_and_A2'] = {'exit_B': code_b, 'exit_A2': code_a, 'B_alive': alive(B), 'A2_alive': alive(A2), 'pins_removed': not pb.exists() and not pa2.exists()}
        if facts['stop_B_and_A2'] != {'exit_B': 0, 'exit_A2': 0, 'B_alive': False, 'A2_alive': False, 'pins_removed': True}:
            problems.append(f"R5: stop B and A2 with their own pins: {facts['stop_B_and_A2']}: " + (out_b + out_a)[-400:])
    finally:
        for pin in viewers:
            if alive(pin):
                try: os.kill(int(pin['pid']), signal.SIGTERM)
                except (OSError, ValueError, TypeError): pass
    left = None                                                            # (6) nothing left: no process, no marker, nothing answering as one of them
    for _ in range(20):
        left = viewer_processes(roots, ps_env, lister)
        if left == {}: break
        time.sleep(0.5)
    facts['left'] = {'processes': sorted(left) if left is not None else 'cannot be listed', 'markers': {'A': marker(state_a), 'B': marker(state_b)},
                     'answering': [p.get('url') for p in viewers if health_of(p.get('url') or '')]}
    if left != {} or any(facts['left']['markers'].values()) or facts['left']['answering']: problems.append(f"R5: viewers left after the check: {facts['left']}")
    return problems, facts


def release_review(exe, py, scenario, env, work, venv):
    """V17 (module docstring): scenario `release` builds R15 in its own project and ledger; then R1, R3, R2 (rewrites this run's isolated registry
    and restores it) and R5 (opens and stops viewers). Returns (problems, facts); a sub-check that raises is reported as a problem of that
    sub-check while the others still run; the R15 ledger's last seq must not move while only CLIs and viewers read it."""
    problems, facts = [], {}
    done = run([py, '-I', scenario, work, 'release'], env=env, cwd=work, text=True, encoding='utf-8', errors='replace', timeout=900)
    rel = first_json(done.stdout) or {}
    if done.returncode != 0 or not rel.get('state_root'):
        return ['scenario release: exit ' + str(done.returncode) + ': ' + text_of(done)[-600:]], facts
    facts['data'] = {'project': rel['project_dir'], 'state_root': rel['state_root'], 'plan': rel['plan'], 'artifact': rel['artifact'], 'receipt': rel['receipt'],
                     'generations': rel['generations'], 'old_decision': rel['old_decision'], 'observations': rel['observations'], 'request': rel['request'],
                     'other_project': {k: rel['other'][k] for k in ('project_dir', 'project_id', 'plan')}}

    def rcli(*args):
        return run([exe, '--project', rel['project_dir'], '--state-root', rel['state_root'], *args], env=env, cwd=work, text=True, encoding='utf-8', errors='replace', timeout=300)
    for name, check in (('R1', _r1), ('R3', _r3), ('R2', _r2), ('R5', _r5)):
        try:
            found, sub = check(rel, rcli, exe=exe, env=env, work=work, venv=venv)
        except Exception as error:                                         # noqa: BLE001 - a precise problem of that sub-check, never an aborted run
            import traceback
            found, sub = [f'{name}: the check raised {type(error).__name__}: {str(error)[:300]} | ' + traceback.format_exc()[-600:]], {}
        problems += found; facts[name.lower()] = sub
    try:
        last = _ledger_rows(rel['state_root'], 'SELECT COALESCE(MAX(seq),0) FROM events')[0][0]
    except Exception as error:                                             # noqa: BLE001
        last = f'unreadable: {error}'
    facts['ledger_last_seq'] = {'after_scenario': rel.get('ledger_last_seq'), 'after_the_checks': last}
    if last != rel.get('ledger_last_seq'): problems.append(f"V17 isolation: the R15 ledger moved from seq {rel.get('ledger_last_seq')} to {last} while only CLIs and viewers read it")
    return problems, facts


def release_only(venv, work):
    """`verify_obs1.py --release-review <venv> <new work dir>`: V17 alone against the onecrew of an EXISTING venv (for example a frozen older
    wheel: red-before-green evidence), with the package run's isolation (filtered env, LOCALAPPDATA/APPDATA/TEMP in <work>). The scenario and the
    open/stop wrappers are the ones next to this file. Writes <work>/release-review-report.json; exit 0 only when V17 passes."""
    for stream in (sys.stdout, sys.stderr):
        try: stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError, OSError): pass
    venv, work = Path(venv).resolve(), Path(work).resolve()
    if work.exists() and any(work.iterdir()): raise SystemExit(f'{work} is not empty: a work folder is never reused')
    work.mkdir(parents=True, exist_ok=True); os.chdir(work)
    real_registry = Path(os.environ.get('LOCALAPPDATA', '')) / 'OneCrew' / 'hook-projects.json'
    registry_before = sha256(real_registry) if real_registry.is_file() else 'absent'
    py, exe = venv / 'Scripts' / 'python.exe', venv / 'Scripts' / 'onecrew.exe'
    env = {k: v for k, v in os.environ.items() if k.upper() not in AI_MARKERS}
    local, roaming, temp = work / 'localappdata', work / 'appdata', work / 'temp'
    for d in (local, roaming, temp): d.mkdir(exist_ok=True)
    env.update(PATH=str(venv / 'Scripts') + os.pathsep + env.get('PATH', ''), LOCALAPPDATA=str(local), APPDATA=str(roaming), TEMP=str(temp), TMP=str(temp), ONECREW_LANG='vi')
    PS_ENV[0] = env
    version = run([exe, '--version'], env=env, cwd=work, text=True, encoding='utf-8', errors='replace').stdout.strip()
    started = time.monotonic()
    problems, facts = release_review(exe, py, Path(__file__).resolve().with_name('scenario_obs1.py'), env, work, venv)
    registry_after = sha256(real_registry) if real_registry.is_file() else 'absent'
    report = {'kind': 'obs1-release-review-report', 'venv': str(venv), 'version': version, 'verifier': str(Path(__file__).resolve()), 'work': str(work),
              'seconds': round(time.monotonic() - started, 1), 'real_registry_unchanged': registry_before == registry_after,
              'result': 'pass' if not problems and registry_before == registry_after else 'fail', 'problems': problems, 'facts': facts}
    (work / 'release-review-report.json').write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding='utf-8')
    print('V17-release-review', report['result'], version, f"{report['seconds']}s", 'real_registry_unchanged=' + str(report['real_registry_unchanged']), flush=True)
    for problem in problems: print('   -', problem[:600], flush=True)
    return 0 if report['result'] == 'pass' else 1


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
    PS_ENV[0] = env
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
        writes, prov = [], []
        def on_signal(name, params=None):
            if name == 'write':
                done = run([py, '-I', scenario, work, 'request'], env=dict(env, OBS1_REQUEST_KEY=f'ux-write-{len(writes) + 1}'), cwd=work, text=True, encoding='utf-8', errors='replace', timeout=120)
                writes.append((first_json(done.stdout) or {}).get('request')); return writes[-1]
            if name == 'answer':                             # the owner answers THIS question with the page's own template, through the installed CLI in real PowerShell
                shown = first_json(cli('track', 'show', 'P1', '--json').stdout) or {}
                need = next((n for n in shown.get('needs_user', []) if n.get('id') == (params or {}).get('id')), None)
                if not need: return 'no such pending question'
                return powershell_template(need['options'][0]['reply_command'].replace(need['reference_placeholder'], 'fixture owner answered while reading'), work / 'answer while reading.ps1').returncode
            if name in ('prov_history', 'prov_same'):             # R1 (`prov`): written by the scenario into THIS run's P9, as `write` does into P1
                done = run([py, '-I', scenario, work, name], env=env, cwd=work, text=True, encoding='utf-8', errors='replace', timeout=300)
                value = first_json(done.stdout) or {}
                prov.append(dict(value, signal=name, exit=done.returncode, **({} if done.returncode == 0 else {'tail': text_of(done)[-400:]})))
                return value.get('attempt') if name == 'prov_history' else value.get('key')
            return None
        proxy = ux.Proxy(record['url'], on_signal=on_signal)
        results = {}
        try:
            scenarios = [('ux01', 'desktop'), ('ux02', 'desktop'), ('ux03', 'desktop'), ('ux04', 'desktop'), ('ux05', 'desktop'), ('ux06', 'desktop'), ('ux07', 'desktop'),
                         ('ux08', 'desktop'), ('ux08', 'split'), ('ux08', 'mobile'), ('ux04', 'mobile'), ('ux01', 'mobile'), ('race', 'desktop'), ('disc', 'desktop'),
                         ('clock', 'desktop'), ('ux03b', 'desktop'), ('ux03b', 'mobile'), ('gantt', 'desktop'), ('gantt', 'mobile'), ('p2a', 'desktop'), ('gantt_now', 'desktop'), ('evid', 'desktop'),
                         ('stale_detail', 'desktop'), ('stale_detail', 'mobile'), ('slow_detail', 'desktop'), ('prov', 'desktop')]   # dev12 (R4, R4xR1, R1); prov LAST: it writes into P9
            for name, size in scenarios:
                width, height = ux.SIZES[size]
                result = ux.run(browser, proxy.url, name, width, height, profile,
                                budget=150000 if name == 'stale_detail' else 45000 if name in ('ux01', 'disc', 'clock', 'gantt', 'p2a', 'gantt_now', 'evid', 'slow_detail', 'prov') else 30000)
                results[f'{name}@{size}'] = {'ok': result.get('ok'), 'polls': result.get('polls'), 'checks': result.get('checks'), 'notes': result.get('notes'), 'error': result.get('error'),
                                             'scrollWidth': result.get('scrollWidth'), 'innerWidth': result.get('innerWidth')}
                if not result.get('ok'): problems.append(f'{name}@{size}: ' + str(result.get('error') or result.get('notes'))[:300])
            if len(writes) != 2 or not all(writes): problems.append(f'the ledger writes during ux01 did not happen: {writes}')
            facts['prov_signals'] = prov
            if [p.get('signal') for p in prov] != ['prov_history', 'prov_same'] or any(p.get('exit') != 0 for p in prov):
                problems.append(f'the R1 writes into P9 during prov did not happen as the harness asked: {prov}')
            shots = {}
            for name, scen_name, size, extra in (('overview-desktop', 'shot-list', 'desktop', ''), ('detail-P4-desktop', 'shot-detail', 'desktop', '&plan=P4'), ('detail-P1-desktop', 'shot-detail', 'desktop', '&plan=P1'),
                                                 ('detail-P1-questions-desktop', 'shot-detail', 'desktop', '&plan=P1&open=need'), ('detail-P1-questions-mobile', 'shot-detail', 'mobile', '&plan=P1&open=need'),
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
        alive = up(first['url'])
        if code != 0 or third.get('reused') or third.get('url') == first.get('url') or not alive or not (third.get('refused') or {}).get('reason', '').startswith('định danh khác'):
            problems.append(f'tampered marker: {third} alive={alive}')
        facts['tampered'] = {'new_url': third.get('url'), 'refused': (third.get('refused') or {}).get('reason'), 'old_server_alive': alive}
        # stop: only the server the marker names (the new one); the first one is still alive afterwards
        stopped = first_json(cli('track', 'stop').stdout) or {}
        if not stopped.get('stopped') or stopped.get('pid') != third.get('pid') or marker.exists() or not up(first['url']) or up(third['url']):
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
    # V16 (P2-B): the reply template the page offers, through the INSTALLED onecrew from a terminal elsewhere (cwd with a space)
    problems, facts = [], {}
    shown = first_json(cli('track', 'show', 'P1', '--json').stdout) or {}
    needs = [n for n in shown.get('needs_user', []) if n.get('kind') == 'request']
    elsewhere = work / 'terminal cua chu'; elsewhere.mkdir(exist_ok=True)
    def owner_shell(command):
        return powershell_template(command, elsewhere / 'owner.ps1')
    if not needs: problems.append('no pending question on P1 to answer')
    else:
        template = needs[0]['options'][0]['reply_command']; placeholder = needs[0].get('reference_placeholder') or ''
        facts['template'] = template
        if not ((template.startswith("& '") or template.startswith('onecrew ')) and " --project '" in template and " --state-root '" in template and " --reference '" in template and placeholder and placeholder in template):
            problems.append('template incomplete: ' + template)
        if needs[0].get('reply_shell') != 'PowerShell': problems.append('reply_shell is not PowerShell')
        missing = owner_shell(template.split(' --reference ')[0])                                  # the dev8 shape: refused by the parser, nothing written
        if missing.returncode != 2 or '--reference' not in missing.stdout + missing.stderr: problems.append(f'without --reference: exit {missing.returncode}: ' + (missing.stdout + missing.stderr)[-300:])
        still = first_json(cli('track', 'show', 'P1', '--json').stdout) or {}
        if len([n for n in still.get('needs_user', []) if n.get('kind') == 'request']) != len(needs): problems.append('a refused command changed the ledger')
        filled = owner_shell(template.replace(placeholder, 'chu chon sau khi doc ho so (fixture, so thu)'))
        after = first_json(cli('track', 'show', 'P1', '--json').stdout) or {}
        left = [n for n in after.get('needs_user', []) if n.get('kind') == 'request']
        if filled.returncode != 0 or len(left) != len(needs) - 1 or any(n['id'] == needs[0]['id'] for n in left):
            problems.append(f'filled template: exit {filled.returncode}, questions left {len(left)}/{len(needs)}: ' + (filled.stdout + filled.stderr)[-400:])
        facts.update(questions_before=len(needs), questions_after=len(left), cwd=str(elsewhere))
        # P2-B: the project whose path holds $SDK, a quote, a backtick, & and (: through real PowerShell with $SDK="CHANGED" set first
        shown_ps = first_json(cli('track', 'show', 'PS', '--json', '--all-projects').stdout) or {}
        ps_needs = [n for n in shown_ps.get('needs_user', []) if n.get('kind') == 'request']
        if not ps_needs: problems.append('no pending question on PS (hostile path)')
        else:
            t2 = ps_needs[0]['options'][0]['reply_command']
            if '$sdk' not in t2.lower() or "''q''" not in t2 or "`t" not in t2: problems.append('hostile path not quoted as expected: ' + t2)
            done_ps = owner_shell(t2.replace(ps_needs[0]['reference_placeholder'], 'fixture owner (hostile path)'))
            after_ps = first_json(cli('track', 'show', 'PS', '--json', '--all-projects').stdout) or {}
            if done_ps.returncode != 0 or 'CHANGED' in done_ps.stdout + done_ps.stderr or any(n.get('kind') == 'request' for n in after_ps.get('needs_user', [])):
                problems.append(f'hostile path through PowerShell: exit {done_ps.returncode}: ' + (done_ps.stdout + done_ps.stderr)[-400:])
            facts['hostile_path'] = {'template': t2, 'exit': done_ps.returncode}
    if not step('V16-reply-template', not problems, problems=problems, **facts): return finish()
    # V17 (dev12): Codex's release review of dev11 (R1, R2, R3, R5) on a root R15 of its OWN project and ledger: independent of V14 (no browser
    # needed), through the installed CLI, real `track serve` processes and the packaged open/stop wrappers
    problems, facts = release_review(exe, py, scenario, env, work, venv)
    if not step('V17-release-review', not problems, problems=problems, **facts): return finish()
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
            if 'class="st waiting"' not in dom or 'đang chờ</span>' not in dom: problems.append('status word missing')
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
    if len(sys.argv) == 4 and sys.argv[1] == '--release-review': sys.exit(release_only(sys.argv[2], sys.argv[3]))
    if len(sys.argv) != 3: raise SystemExit('usage: verify_obs1.py <package dir> <work dir> | verify_obs1.py --release-review <venv> <new work dir>')
    sys.exit(main(sys.argv[1], sys.argv[2]))
