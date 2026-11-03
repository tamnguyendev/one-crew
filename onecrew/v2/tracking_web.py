"""OBS-1: the local read-only tracking page (stdlib http.server on 127.0.0.1) over onecrew/v2/tracking.py.

GET only: `/` (the page, one file, no external resource), `/api/health`, `/api/overview`, `/api/task?plan=…`, `/api/evidence?plan=…&key=…`.
Any other method is 405: the page has no control, and no request here can approve, answer, pause or resume a task. Each request reads the ledger
anew (sqlite read-only, no transaction kept between polls), so the page rebuilds from the durable source on every poll: a reconnect, a reopened
tab or a restarted server shows the same truth without a cursor to lose and without duplicating an event (the ledger's seq is the identity).

Closing the page or the server never stops a worker: workers are other processes that do not know this one exists. The server started by
`track open` runs detached and exits by itself after `idle_exit` seconds without a request.

Server identity (P2 of 03/11): every server carries an `instance` nonce, its wheel version, its state root and its project scope in `/api/health`
and in the marker `<state_root>/tracking/server.json` that `track serve --announce` writes. `track open` reuses a server only when the marker's
URL answers with the SAME instance, version, state root and scope (`reusable`): a marker of an older wheel, a port taken over by another process
or a server of another ledger is never "opened successfully", and no process is ever killed to make room. Concurrent `track open` calls serialise
on `tracking/open.lock`, so one server is started and the marker is not lost. `track stop` stops only the server whose health matches the marker.

Page (UX of 03/11, docs/obs1/UX-OBS-1.vi.md): overview → task detail → timeline grouped by phần việc/attempt → evidence of one step; the detail is
rebuilt only when the ledger seq moved, and open sections, focus and scroll positions survive a rebuild; the project filter, the selection and the
URL agree; the status words of the model (tracking.OUTCOME_WORDS) are the badges; nothing on the page runs a command — the reply commands are
text to copy.

Detail state per selection (R4 of 03/11, Codex release review): the detail data is kept together with the selection it was fetched for
(`detailFor`) and is shown, repainted, copied from or used for evidence links only while that selection is the current one. Selecting another
task shows that task's heading with "đang tải chi tiết…" at once, never the previous task's content. A failed detail request (network error or
HTTP error status) of a task never loaded shows the selected task's heading, the error and no reply command; of the task already shown keeps its
data with a freshness warning next to the heading and marks every reply template as from that time. The header shows the overview connection
(#conn) and, separately, the freshness of the selected task's detail (#dconn). The out-of-order guard (detailToken + selection) covers the
success and the failure paths.
"""
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..ledger import LedgerError, utcnow
from . import tracking

MARKER = 'tracking/server.json'
LOCK = 'tracking/open.lock'
MARKER_DIR_ENV = 'ONECREW_TRACK_MARKER_DIR'      # set: the marker and lock live under <dir>/<sha256 of the state root>[:16]/ instead of inside the state root


def marker_paths(state_root):
    """(marker, lock) of this state root: inside it (`tracking/`) unless ONECREW_TRACK_MARKER_DIR names a folder to keep them elsewhere — for a real
    ledger that must not be written at all, not even a server marker."""
    state_root = Path(state_root).resolve()
    outside = os.environ.get(MARKER_DIR_ENV)
    if outside:
        import hashlib
        base = Path(outside).resolve() / hashlib.sha256(os.path.normcase(str(state_root)).encode('utf-8')).hexdigest()[:16]
        return base / 'server.json', base / 'open.lock'
    return state_root / MARKER, state_root / LOCK
SERVER_NAME = 'OneCrewTrack/2'
LOCK_STALE_SECONDS = 60


def version():
    """The wheel version this process runs (importlib.metadata), else the checkout's pyproject version marked `+checkout`, else `unknown`."""
    try:
        import importlib.metadata
        return importlib.metadata.version('onecrew')
    except Exception:         # PackageNotFoundError or a broken metadata: fall through to the checkout
        pass
    try:
        text = (Path(__file__).resolve().parents[2] / 'pyproject.toml').read_text(encoding='utf-8', errors='replace')
        found = re.search(r'(?m)^version = "([^"]+)"', text)
        return (found.group(1) + '+checkout') if found else 'unknown'
    except OSError:
        return 'unknown'


def _page(interval):
    return PAGE.replace('@@INTERVAL@@', str(int(max(0.5, float(interval)) * 1000)))


def make_server(state_root, *, host='127.0.0.1', port=0, project_id=None, interval=2.0, idle_exit=None, instance=None):
    state_root = Path(state_root).resolve()
    identity = {'instance': instance or secrets.token_hex(8), 'version': version(), 'state_root': str(state_root), 'project_id': project_id, 'pid': os.getpid()}
    stats = {'requests': 0, 'last_read_ms': None, 'last_request': time.monotonic(), 'started_at': utcnow(), 'errors': 0}
    page = _page(interval).encode('utf-8')

    class Handler(BaseHTTPRequestHandler):
        server_version = SERVER_NAME
        protocol_version = 'HTTP/1.1'

        def log_message(self, format, *args):      # quiet: the console is the owner's, not a request log
            pass

        def _send(self, status, body, content_type='application/json; charset=utf-8'):
            # R3: every JSON body (model, health, error) passes the outbound guard; the model was already guarded, so that part is a no-op
            data = body if isinstance(body, bytes) else json.dumps(tracking.outward(body), ensure_ascii=False, default=str).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self'; frame-ancestors 'self'")
            self.end_headers()
            self.wfile.write(data)

        def _refuse(self):
            self._send(HTTPStatus.METHOD_NOT_ALLOWED, {'error': 'read-only: trang theo dõi chỉ nhận GET; không duyệt, trả lời, dừng hay tiếp tục task ở đây', 'read_only': True})

        do_POST = do_PUT = do_DELETE = do_PATCH = _refuse

        def do_GET(self):
            stats['requests'] += 1; stats['last_request'] = time.monotonic()
            url = urllib.parse.urlsplit(self.path)
            if stats.get('refuse_api') and url.path.startswith('/api/'):   # tests only: in-process flag, never settable over HTTP
                self.close_connection = True; self.connection.close(); return
            q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
            if project_id and q.get('project_id') and q['project_id'] != project_id:       # P2-04: a query may narrow the server's scope, never widen it
                return self._send(HTTPStatus.FORBIDDEN, {'error': f'ngoài phạm vi: server này chỉ theo dõi project {project_id[:12]}…; project_id khác không được mở',
                                                         'read_only': True, 'project_id': project_id})
            scope = q.get('project_id') or project_id
            try:
                if url.path in ('/', '/index.html'):
                    return self._send(HTTPStatus.OK, page, 'text/html; charset=utf-8')
                if url.path == '/api/health':
                    return self._send(HTTPStatus.OK, {'ok': True, 'generated_at': utcnow(), 'poll_seconds': interval, 'read_only': True, 'server': SERVER_NAME, **identity,
                                                      **{k: stats[k] for k in ('requests', 'last_read_ms', 'started_at', 'errors')}})
                if url.path == '/api/overview':
                    started = time.perf_counter()
                    value = tracking.overview(state_root, project_id=scope)
                    stats['last_read_ms'] = round((time.perf_counter() - started) * 1000, 1)
                    value['server'] = {'pid': os.getpid(), 'instance': identity['instance'], 'version': identity['version'], 'read_ms': stats['last_read_ms'],
                                       'poll_seconds': interval, 'started_at': stats['started_at'], 'requests': stats['requests'], 'project_id': project_id}
                    return self._send(HTTPStatus.OK, value)
                if url.path == '/api/task':
                    if not q.get('plan'): return self._send(HTTPStatus.BAD_REQUEST, {'error': 'thiếu plan'})
                    limit = int(q.get('timeline') or 200)
                    if not 1 <= limit <= 5000: return self._send(HTTPStatus.BAD_REQUEST, {'error': 'timeline: 1-5000'})
                    started = time.perf_counter()
                    value = tracking.detail(state_root, q['plan'], project_id=scope, timeline_limit=limit)
                    value['server'] = {'pid': os.getpid(), 'instance': identity['instance'], 'read_ms': round((time.perf_counter() - started) * 1000, 1), 'poll_seconds': interval}
                    return self._send(HTTPStatus.OK, value)
                if url.path == '/api/evidence':
                    if not q.get('plan') or not q.get('key'): return self._send(HTTPStatus.BAD_REQUEST, {'error': 'thiếu plan hoặc key'})
                    value = tracking.evidence(state_root, q['plan'], q['key'], project_id=scope)
                    if q.get('format') == 'text':
                        head = f"# blob {value['key']} ({value['bytes']} bytes{', cắt' if value['truncated'] else ''}); lọc bí mật: {value['redaction']['rule']}\n\n"
                        return self._send(HTTPStatus.OK, (head + value['text']).encode('utf-8'), 'text/plain; charset=utf-8')
                    return self._send(HTTPStatus.OK, value)
                return self._send(HTTPStatus.NOT_FOUND, {'error': 'không có đường dẫn này', 'paths': ['/', '/api/health', '/api/overview', '/api/task?plan=', '/api/evidence?plan=&key=']})
            except PermissionError as error:
                return self._send(HTTPStatus.FORBIDDEN, {'error': str(error), 'read_only': True})
            except LedgerError as error:
                return self._send(HTTPStatus.NOT_FOUND, {'error': str(error)})
            except (OSError, ValueError, KeyError, TypeError) as error:
                stats['errors'] += 1
                return self._send(HTTPStatus.SERVICE_UNAVAILABLE, {'error': 'nguồn lỗi: ' + tracking.clean(str(error), 300), 'generated_at': utcnow()})

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.track_stats = stats
    server.track_identity = identity
    if idle_exit:
        def watch():
            while True:
                time.sleep(5)
                if time.monotonic() - stats['last_request'] > idle_exit:
                    server.shutdown(); return
        threading.Thread(target=watch, daemon=True).start()
    return server


def url_of(server):
    host, port = server.server_address[:2]
    return f'http://{host}:{port}/'


def _write_marker(path, record):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + secrets.token_hex(4) + '.tmp')
    tmp.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, path)


def _read_marker(path):
    try:
        record = json.loads(Path(path).read_text(encoding='utf-8'))
        return record if isinstance(record, dict) and record.get('url') else None
    except (OSError, ValueError):
        return None


def serve(state_root, *, host='127.0.0.1', port=0, project_id=None, interval=2.0, announce=None, idle_exit=None):
    """Run in this process until Ctrl+C. Prints one JSON line with the URL first; with `announce`, also writes it to that marker file (atomically)."""
    server = make_server(state_root, host=host, port=port, project_id=project_id, interval=interval, idle_exit=idle_exit)
    record = {'url': url_of(server), 'pid': os.getpid(), 'instance': server.track_identity['instance'], 'version': server.track_identity['version'],
              'state_root': str(Path(state_root).resolve()), 'project_id': project_id, 'poll_seconds': interval,
              'read_only': True, 'started_at': utcnow(), 'note': 'Ctrl+C hay đóng cửa sổ này chỉ đóng trang theo dõi; worker không dừng.'}
    print(json.dumps(record, ensure_ascii=False), flush=True)
    if announce:
        _write_marker(announce, record)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if announce:
            current = _read_marker(announce)
            if current and current.get('instance') == record['instance']:     # only our own marker: a newer server's marker is left alone
                try: Path(announce).unlink()
                except OSError: pass
    return 0


def identity(url, timeout=1.5):
    """The /api/health record of whatever answers at `url`, or None."""
    try:
        with urllib.request.urlopen(url + 'api/health', timeout=timeout) as r:
            value = json.loads(r.read().decode('utf-8'))
            return value if isinstance(value, dict) and value.get('ok') is True else None
    except (OSError, ValueError):
        return None


def reusable(record, health, state_root, project_id, here=None):
    """(ok, reason): may `track open` reuse the server the marker `record` names, given what its URL answered (`health`)? Only when the server
    is the very one the marker was written for (instance), runs the same wheel, reads the same state root and has the same project scope."""
    here = here or version()
    if not record: return False, 'không có marker'
    if not record.get('instance'): return False, 'marker không có định danh (server của wheel cũ): không dùng lại'
    if not health: return False, 'server trong marker không trả lời'
    if health.get('instance') != record['instance']: return False, 'định danh khác: cổng trong marker đang do tiến trình khác trả lời; không dùng lại, không dừng tiến trình đó'
    if health.get('version') != here: return False, f"version khác: server chạy {health.get('version')}, lệnh này là {here}"
    if os.path.normcase(str(health.get('state_root') or '')) != os.path.normcase(str(Path(state_root).resolve())): return False, 'state-root khác'
    if (health.get('project_id') or None) != (project_id or None): return False, 'phạm vi project khác'
    if health.get('pid') != record.get('pid'): return False, 'PID khác với marker'
    return True, None


def _lock(path):
    """Create the open lock exclusively; a lock older than LOCK_STALE_SECONDS is a leftover and is taken over. Returns the fd or None."""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            return os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime > LOCK_STALE_SECONDS: path.unlink(); continue
            except OSError:
                continue
            return None
    return None


def _unlock(fd, path):
    try: os.close(fd)
    except OSError: pass
    try: Path(path).unlink()
    except OSError: pass


def open_page(state_root, *, host='127.0.0.1', port=0, project_id=None, interval=2.0, project=None, explicit_state_root=None, idle_exit=1800,
              browser=True, spawn=True, wait=8.0):
    """Reuse the live detached server of this state root when its identity matches (see `reusable`), else start one; then open the page.
    `spawn=False` only reports (no server is started). Concurrent calls serialise on the open lock."""
    state_root = Path(state_root).resolve()
    marker, lock = marker_paths(state_root)
    here = version()

    def check():
        record = _read_marker(marker)
        health = identity(record['url']) if record else None
        ok, why = reusable(record, health, state_root, project_id, here)
        return record, health, ok, why

    def opened(record, reused, **more):
        if browser:
            import webbrowser; webbrowser.open(record['url'])
        return dict(record, reused=reused, version_here=here, **more)

    record, health, ok, why = check()
    if ok: return opened(record, True)
    refused = {'marker': record, 'reason': why}
    fd = _lock(lock)
    if fd is None:                                   # another `track open` is starting a server right now: wait for its marker instead of a second server
        end = time.monotonic() + wait + 4
        while time.monotonic() < end:
            record, health, ok, why = check()
            if ok: return opened(record, True, waited_for_other_open=True)
            time.sleep(0.2)
        return {'error': 'một lần `track open` khác đang chạy và chưa để lại server dùng lại được', 'refused': refused}
    try:
        if not spawn:
            return {'error': 'không có server dùng lại được', 'refused': refused, 'version_here': here}
        old_instance = (record or {}).get('instance')
        if marker.exists():                          # a marker that failed `reusable` is stale for this call; the lock is held, nobody else writes it now
            try: marker.unlink()
            except OSError: pass
        args = [sys.executable, '-X', 'utf8', '-m', 'onecrew.v2.tracking_cli', '--project', str(project or Path.cwd())]
        args += ['--state-root', str(explicit_state_root if explicit_state_root is not None else state_root)]
        args += ['track', 'serve', '--host', host, '--port', str(port), '--interval', str(interval), '--announce', str(marker)]
        if project_id: args.append('--project-only')
        flags = (subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, 'DETACHED_PROCESS', 0)) if os.name == 'nt' else 0
        env = dict(os.environ, ONECREW_TRACK_IDLE_EXIT=str(idle_exit), PYTHONSAFEPATH='1')     # `-m` must not pick a stray `onecrew` from the caller's cwd
        import tempfile
        child = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, creationflags=flags, env=env,
                                 cwd=tempfile.gettempdir())
        end = time.monotonic() + wait
        while time.monotonic() < end:
            record, health, ok, why = check()
            if record and record.get('instance') and record['instance'] != old_instance and ok:
                return opened(record, False, idle_exit_seconds=idle_exit, refused=refused if refused['marker'] else None)
            if child.poll() is not None:
                return {'error': 'server theo dõi thoát ngay khi khởi động', 'exit_code': child.returncode, 'refused': refused}
            time.sleep(0.1)
        return {'error': f'server theo dõi không trả lời đúng định danh trong {wait:g} giây', 'pid': child.pid, 'last_reason': why, 'refused': refused}
    finally:
        _unlock(fd, lock)


def status_page(state_root):
    """What `track open` would find: the marker, what its URL answers, and whether that is reusable (and why not)."""
    state_root = Path(state_root).resolve()
    marker, lock = marker_paths(state_root)
    record = _read_marker(marker)
    health = identity(record['url']) if record else None
    ok, why = reusable(record, health, state_root, (record or {}).get('project_id'), None)
    return {'state_root': str(state_root), 'marker_file': str(marker), 'marker': record, 'health': health, 'reusable': ok, 'reason': why, 'version_here': version(),
            'lock': lock.exists()}


def _same_server(record, health, state_root):
    """For `track stop`: the process the marker names is the one answering (same pid and state root; same instance when the marker has one)."""
    return bool(record and health and health.get('pid') == record.get('pid') and str(health.get('server', '')).startswith('OneCrewTrack/')
                and os.path.normcase(str(health.get('state_root') or '')) == os.path.normcase(str(Path(state_root).resolve()))
                and (not record.get('instance') or health.get('instance') == record['instance']))


def stop_page(state_root, wait=5.0):
    """Stop the detached tracking server of this state root — only the process whose /api/health matches the marker. Never another process.
    A marker whose URL answers with another identity, or does not answer, is removed as stale (a file of ours; nothing is killed)."""
    state_root = Path(state_root).resolve()
    marker, _ = marker_paths(state_root)
    record = _read_marker(marker)
    if not record:
        return {'stopped': False, 'reason': 'không có marker: không có server nào được `track open` mở cho sổ này (server của `track serve` dừng bằng Ctrl+C)'}
    health = identity(record['url'])
    if not _same_server(record, health, state_root):
        try: marker.unlink(); removed = True
        except OSError: removed = False
        why = 'server trong marker không trả lời' if not health else 'tiến trình trả lời ở cổng đó không phải server của marker này (định danh/PID/sổ khác): không dừng tiến trình lạ'
        return {'stopped': False, 'reason': why, 'marker_removed': removed, 'marker': record, 'health': health}
    try:
        os.kill(int(record['pid']), signal.SIGTERM)
    except (OSError, ValueError) as error:
        return {'stopped': False, 'reason': 'không gửi được tín hiệu dừng: ' + str(error), 'marker': record}
    end = time.monotonic() + wait
    while time.monotonic() < end and identity(record['url'], timeout=0.5): time.sleep(0.1)
    gone = identity(record['url'], timeout=0.5) is None
    if gone:
        try: marker.unlink()
        except OSError: pass
    return {'stopped': gone, 'pid': record['pid'], 'url': record['url'], 'instance': record.get('instance'), 'version': record.get('version'),
            'note': 'chỉ trang theo dõi dừng; worker không bị ảnh hưởng' if gone else 'server vẫn trả lời sau tín hiệu dừng'}


PAGE = r'''<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>OneCrew — theo dõi (chỉ đọc)</title>
<style>
:root{--bg:#f4f6f8;--fg:#1c2230;--mut:#5b6572;--card:#fff;--line:#dde2e9;--run:#1d6fd6;--wait:#a86a0a;--blk:#c0392b;--acc:#2f855a;--ver:#0b7a75;--cls:#6b7280;--unk:#718096;--need:#fff4cc;--needfg:#5c4400;--sel:#e8f0fb;--focus:#1d6fd6}
@media (prefers-color-scheme:dark){:root{--bg:#12161d;--fg:#e6e9ef;--mut:#9aa4b2;--card:#1a2029;--line:#2b3442;--need:#3b3415;--needfg:#ffe9a8;--sel:#1f2d44;--focus:#79b0ff}}
*{box-sizing:border-box}html,body{margin:0}body{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,"Segoe UI",sans-serif;min-width:0}
:focus-visible{outline:3px solid var(--focus);outline-offset:2px}
header{padding:8px 16px;border-bottom:1px solid var(--line);background:var(--card)}
.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}h1{font-size:16px;margin:0}
#conn{padding:2px 8px;border-radius:12px;font-size:12px;border:1px solid var(--line);max-width:100%}
#conn.ok{background:#e6f4ea;color:#1e4620}#conn.bad{background:#fde2e2;color:#7a1f1f}#conn.src{background:#fff3cd;color:#5c4400}
.tools{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:6px}.tools label{font-size:12px;color:var(--mut);display:flex;gap:4px;align-items:center;min-width:0;max-width:100%}
input,select,button{font:inherit;padding:4px 8px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg);max-width:100%;min-width:0}
select{text-overflow:ellipsis}#chips{display:flex;gap:6px;flex-wrap:wrap;align-items:center}#chips button{font-size:12px;padding:2px 8px;border-radius:12px}#chips button[aria-pressed=true]{background:var(--sel);border-color:var(--run);font-weight:600}
.dsum{display:flex;gap:8px 14px;flex-wrap:wrap;margin:6px 0;align-items:baseline}.dsum .step{font-weight:600}.dsum a{color:var(--needfg);background:var(--need);padding:1px 8px;border-radius:10px;text-decoration:none;font-weight:600}
details.need{margin:6px 0}details.need>summary{color:var(--needfg);font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}details.need[open]>summary{white-space:normal}.need .q{font-weight:600;margin-top:4px}mark.ph{background:#ffd666;color:#3b2a00;padding:0 3px;border-radius:3px}
.dur{display:inline-block;height:8px;background:var(--run);border-radius:4px;vertical-align:middle;margin-right:6px}.st .g{margin-right:4px;font-size:11px}
li.task,.r2 span,.dhead,.dsum,#detail,#untracked{overflow-wrap:anywhere}.r2 span{min-width:0}
.gantt{margin:10px 0;border:1px solid var(--line);border-radius:8px;padding:8px;display:grid;grid-template-columns:minmax(0,1fr);gap:8px}.gantt>*{min-width:0}.gscroll{min-width:0}
.gtop{display:flex;gap:10px 14px;flex-wrap:wrap;align-items:center;font-size:12px;color:var(--mut)}.gtop select{padding:2px 6px;font-size:12px}
.legend{display:flex;gap:4px 12px;flex-wrap:wrap}.legend span{display:inline-flex;align-items:center;gap:4px;white-space:nowrap}.sw{display:inline-block;width:16px;height:8px;border-radius:2px}
.sw.execution,.seg.execution{background:var(--run)}.sw.reserved,.seg.reserved{background:repeating-linear-gradient(45deg,#9fb0cc 0 3px,#e3e9f3 3px 6px)}
.sw.wait,.seg.wait{background:var(--wait)}.sw.verification,.seg.verification{background:var(--ver)}
.sw.to_now,.seg.to_now{background:repeating-linear-gradient(-45deg,#c3c9d2 0 3px,#f2f4f7 3px 6px);border:1px dashed var(--mut);box-sizing:border-box}
.gscroll{overflow-x:auto;overflow-y:hidden}.gbody{display:grid;grid-template-columns:170px minmax(0,1fr)}
.gstale{color:var(--blk);font-weight:600}
.gaxis{height:22px;position:relative;border-bottom:1px solid var(--line);font-size:11px;color:var(--mut)}.gaxis span{position:absolute;top:3px;transform:translateX(-50%);white-space:nowrap}.gaxis span.first{transform:none}.gaxis span.last{transform:translateX(-100%)}.gchart{padding-right:8px;box-sizing:border-box}.gaxis i{position:absolute;top:0;bottom:0;border-left:1px solid var(--line)}
.grow{position:relative;height:28px;border-top:1px solid var(--line);box-sizing:border-box}.gtree .grow{padding:5px 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:12px}
.gtree .gh0{height:22px;border-top:0;color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.04em;padding:4px 6px}
.gtree .nodehead{font-weight:600;cursor:pointer}.gtree .att{padding-left:24px}.gtree .hist{padding-left:24px;color:var(--mut);cursor:pointer}.gtree .cur{color:var(--run)}
.gtree button.tg{border:0;background:none;padding:0 4px 0 0;cursor:pointer;color:inherit;font:inherit}
.gchart .grow{background:repeating-linear-gradient(90deg,transparent 0 calc(10% - 1px),var(--line) calc(10% - 1px) 10%)}
.seg{position:absolute;top:8px;height:12px;border-radius:3px;cursor:pointer;min-width:2px}.seg.wait{top:20px;height:5px}.seg.verification{top:3px;height:5px}
.seg:focus-visible,.mk:focus-visible{outline:3px solid var(--focus)}.seg.sel,.mk.sel{outline:2px solid var(--fg);outline-offset:1px}
.grow.old .seg,.grow.old .mk{opacity:.45}.mk{position:absolute;top:4px;transform:translateX(-50%);font-size:13px;line-height:1;cursor:pointer;color:var(--fg)}.mk.held{color:var(--blk)}.mk.pass{color:var(--ver)}.mk.fail{color:var(--blk)}.mk.plan{color:var(--mut)}
.nowline{position:absolute;top:0;bottom:0;border-left:2px dashed var(--mut);pointer-events:none}
.gside{border:1px solid var(--line);border-radius:8px;padding:8px;font-size:13px;min-width:0}.gside h4{margin:0 0 4px}.gside dl{display:grid;grid-template-columns:auto 1fr;gap:2px 10px;margin:4px 0;font-size:12px}.gside dt{color:var(--mut)}.gside dd{margin:0;overflow-wrap:anywhere}
.stale-need{background:#fde2e2;color:#7a1f1f;padding:6px 8px;border-radius:6px;margin:6px 0;font-size:12px}
#dconn{padding:2px 8px;border-radius:12px;font-size:12px;border:1px solid var(--line);max-width:100%;overflow-wrap:anywhere}#dconn.ok{color:var(--mut)}#dconn.bad{background:#fde2e2;color:#7a1f1f}#dconn.wait{color:var(--mut);border-style:dashed}
.dstatus{padding:6px 8px;border-radius:6px;margin:6px 0;font-size:12px;background:var(--sel)}.dstatus.err,.dstatus.stale{background:#fde2e2;color:#7a1f1f}.stale-tpl{background:#fde2e2;color:#7a1f1f;padding:2px 6px;border-radius:4px;margin-top:4px}.stale-need button{margin-left:8px;font-size:12px;padding:1px 6px}
@media (min-width:1400px){.gantt{grid-template-columns:minmax(0,1fr) 300px}.gside{align-self:start;max-height:60vh;overflow:auto}}
button{cursor:pointer}button.pri{background:var(--run);color:#fff;border-color:var(--run)}
.small{font-size:12px}.mut{color:var(--mut)}.note{margin:6px 0 0}code{font-family:ui-monospace,Consolas,monospace;font-size:12px;background:rgba(120,140,180,.14);padding:0 4px;border-radius:3px;word-break:break-all}
main{padding:12px 16px;display:grid;grid-template-columns:minmax(300px,2fr) minmax(360px,3fr);gap:12px;align-items:start}
section.pane{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;min-width:0}
#detailpane{position:sticky;top:8px;max-height:calc(100vh - 16px);overflow:auto}
h2{font-size:13px;margin:0 0 8px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}h3{font-size:13px;margin:14px 0 6px}h4{font-size:13px;margin:0}
#list{list-style:none;margin:0;padding:0}.task{padding:8px 8px;border-top:1px solid var(--line);cursor:pointer;border-left:4px solid transparent}
.task:first-child{border-top:0}.task:hover{background:rgba(120,140,180,.08)}.task[aria-selected=true]{background:var(--sel);border-left-color:var(--run)}.task.last{border-left-color:var(--line)}
.r1{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}.name{font-weight:600}.ttl{flex:1 1 180px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.r2{display:flex;gap:10px;flex-wrap:wrap;margin-top:2px}.r3{margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.st{display:inline-block;padding:1px 8px;border-radius:10px;color:#fff;font-size:12px;white-space:nowrap}
.st.running{background:var(--run)}.st.waiting{background:var(--wait)}.st.blocked{background:var(--blk)}.st.unknown{background:var(--unk)}
.st.done{background:var(--cls)}.st.done.accepted{background:var(--acc)}.st.done.verified{background:var(--ver)}.st.done.closed{background:var(--cls)}
.needb{background:var(--need);color:var(--needfg);padding:1px 7px;border-radius:10px;font-size:12px;font-weight:600}
.need{background:var(--need);color:var(--needfg);padding:8px 10px;border-radius:8px;margin:8px 0}.need .q{font-weight:600}.opt{margin:6px 0 0;padding:6px 8px;border:1px solid rgba(0,0,0,.08);border-radius:6px;background:rgba(255,255,255,.35)}
.opt .cmd{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:3px}.copied{font-size:12px;margin-top:4px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:6px;margin:8px 0}.tile{border:1px solid var(--line);border-radius:8px;padding:6px 8px;min-width:0}
.tile .l{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut)}.tile .v{font-weight:600;margin-top:2px;overflow-wrap:anywhere}.tile .s{font-size:12px;color:var(--mut);overflow-wrap:anywhere}
.scroll{overflow:auto;max-width:100%}table{border-collapse:collapse;font-size:13px;min-width:100%}th,td{text-align:left;vertical-align:top;padding:4px 6px;border-top:1px solid var(--line);white-space:nowrap}th{color:var(--mut);font-weight:600;border-top:0}td.wrap{white-space:normal}
.grp{border:1px solid var(--line);border-radius:8px;padding:6px 8px;margin:6px 0}.grp .gh{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
ol.ev{list-style:none;margin:4px 0 0;padding:0}.ev li{padding:3px 4px;border-top:1px solid var(--line);cursor:pointer;border-radius:4px}.ev li:hover{background:rgba(120,140,180,.08)}.ev li[aria-expanded=true]{background:var(--sel)}
.ev .t{color:var(--mut);font-size:12px;margin-right:6px;font-variant-numeric:tabular-nums}.ev .k{color:var(--mut);font-size:11px;margin-left:6px}.ev .clip{margin-left:6px;font-size:12px;color:var(--run)}
.stale{opacity:.7}.evbox{margin:4px 0 4px 10px;padding:6px 8px;border-left:3px solid var(--line);font-size:13px}.evbox pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:40vh;overflow:auto;background:rgba(120,140,180,.08);padding:6px;border-radius:6px;font-size:12px;margin:4px 0 0}
details{margin:6px 0}summary{cursor:pointer;color:var(--mut)}summary:focus-visible{outline:3px solid var(--focus)}
.dhead{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.dhead h2{margin:0;text-transform:none;letter-spacing:0;font-size:16px;color:var(--fg)}
#back{display:none}#empty,#nodetail{padding:8px;color:var(--mut)}.err{color:var(--blk)}.note .brief{display:none}
@media (min-width:900px){main[data-view=detail]{grid-template-columns:minmax(220px,1fr) minmax(420px,3.4fr)}main[data-view=detail] .task .r3{display:none}main[data-view=detail] .task{padding:6px 8px}}
@media (max-width:899px){main{display:block}main[data-view=list] #detailpane{display:none}main[data-view=detail] #listpane{display:none}#detailpane{position:static;max-height:none}#back{display:inline-block}
  .ttl{white-space:normal}.r3{white-space:normal}header{padding:6px 12px}main{padding:8px 12px}.note .long,#src{display:none}.note .brief{display:inline}.tools label span{display:none}
  .gbody{grid-template-columns:150px minmax(380px,1fr);min-width:540px}.gtree .grow{font-size:12px}.gaxis span.t1,.gaxis span.t3{display:none}}
</style></head><body>
<header>
<div class="bar"><h1>OneCrew · theo dõi công việc</h1><span id="conn">đang kết nối…</span><span id="dconn" role="status" hidden></span><span id="count" class="small mut"></span><span id="chips" role="group" aria-label="lọc nhanh"></span></div>
<div class="tools">
<label>project <select id="proj"><option value="">tất cả</option></select></label>
<label>trạng thái <select id="kind"><option value="">tất cả</option><option value="need">cần bạn</option><option value="running">đang thực hiện</option><option value="waiting">đang chờ</option><option value="blocked">bị chặn</option><option value="done">đã xong</option><option value="unknown">chưa xác định</option></select></label>
<label><span>tìm</span><input id="q" type="search" placeholder="tên plan, mục tiêu, bước" size="24" aria-label="tìm theo plan, mục tiêu, bước"></label>
</div>
<p class="note small mut"><span class="long">Chỉ đọc: không có nút duyệt, trả lời, dừng hay tiếp tục task; mở bằng chứng không phải là duyệt. Kết nối "OK" chỉ nói trang đang nhận dữ liệu, không nói việc đã xong. </span><span class="brief">Chỉ đọc; "kết nối OK" không có nghĩa việc đã xong. </span><span id="src"></span></p>
</header>
<main id="main" data-view="list">
<section class="pane" id="listpane" aria-label="Danh sách công việc"><h2>Danh sách công việc</h2><div id="empty"></div>
<ul id="list" role="listbox" aria-label="Danh sách công việc"></ul>
<details id="untrackedbox" data-k="untracked"><summary>Chưa được theo dõi</summary><div id="untracked" class="small"></div></details></section>
<section class="pane" id="detailpane" aria-label="Chi tiết task"><div id="detail"><div id="nodetail">Chọn một task ở danh sách để xem chi tiết, timeline và bằng chứng.</div></div></section>
</main>
<script>
(function(){
var INTERVAL=@@INTERVAL@@, last=null, lastOk=null, lostSince=null, selected=null, lastViewed=null, detailData=null, detailSeq=null, detailToken=0, listSig=null, selEv=null, evState={}, copied=null;
var selStep=null, gRange='all', gFold={}, staleNotes=[], knownNeeds={};
var detailFor=null, detailError=null, detailOkAt=null;   // R4: the selection detailData was fetched for; the current failure streak {since,last,message}; when it last loaded
var TECH=['attempt.','executor.managed','decision.recorded','execution.configured','budget.group','precondition.recorded','task.submitted','knowledge.delivered','estimate.','plan.step0_closed'];
var $=function(s){return document.querySelector(s)};
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function hms(s){if(typeof s!=='number')return 'chưa xác định';s=Math.floor(s);var h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=s%60;return h?h+'h'+String(m).padStart(2,'0')+'m':m?m+'m'+String(x).padStart(2,'0')+'s':x+'s'}
function when(t){if(!t)return '—';var d=new Date(t);return isNaN(d)?esc(t):d.toLocaleTimeString()+' '+d.toLocaleDateString()}
function clock(t){if(!t)return '—';var d=new Date(t);return isNaN(d)?esc(t):d.toLocaleTimeString()}
function relText(t){var d=new Date(t);if(isNaN(d))return esc(t);var s=Math.round((Date.now()-d.getTime())/1000);if(s<5)return 'vừa xong';if(s<60)return s+' giây trước';if(s<3600)return Math.floor(s/60)+' phút trước';if(s<86400)return Math.floor(s/3600)+' giờ trước';return Math.floor(s/86400)+' ngày trước'}
function rel(t){return t?'<time data-rel="'+esc(t)+'" title="'+when(t)+'">'+relText(t)+'</time>':'—'}
function tick(){document.querySelectorAll('[data-rel]').forEach(function(e){e.textContent=relText(e.getAttribute('data-rel'))});
  document.querySelectorAll('[data-live]').forEach(function(e){var s=parseFloat(e.getAttribute('data-live')),at=parseFloat(e.getAttribute('data-live-at'));if(!isNaN(s)&&!isNaN(at))e.textContent=hms(s+(Date.now()-at)/1000)})}
var GLYPH={running:'▶',waiting:'◔',blocked:'■',unknown:'?',done:'□',accepted:'✔',verified:'✓',closed:'□'};
function st(t){var g=t.outcome?GLYPH[t.outcome]:GLYPH[t.kind];return '<span class="st '+esc(t.kind)+(t.outcome?' '+esc(t.outcome):'')+'"><span class="g" aria-hidden="true">'+(g||'')+'</span>'+esc(t.label)+'</span>'}
var PHASE={pending:'chờ đến lượt',running:'đang chạy',held:'bị giữ',complete:'xong'},NSTATE={none:'chưa có đầu ra',produced:'đã tạo',verified:'đã kiểm',accepted:'đã nghiệm thu'};
function word(map,k){return '<span title="'+esc(k)+'">'+esc(map[k]||k||'—')+'</span>'}
function short(p){p=String(p||'');var parts=p.split(/[\\\/]/).filter(Boolean);return parts.length>2?'…'+parts.slice(-2).join('\\'):p}
function conn(cls,text){var c=$('#conn');c.className=cls;c.textContent=text}
function narrow(){return window.matchMedia('(max-width:899px)').matches}
function setView(){$('#main').setAttribute('data-view',selected?'detail':'list')}
function sameSel(a,b){return !!a&&!!b&&a.plan===b.plan&&(a.project||'')===(b.project||'')}
function urlOf(sel){return sel?'?plan='+encodeURIComponent(sel.plan)+(sel.project?'&project_id='+encodeURIComponent(sel.project):''):location.pathname}
function mine(){return detailData&&sameSel(detailFor,selected)?detailData:null}   // R4: the detail data only while it belongs to the CURRENT selection
function detailState(){return !selected?'none':mine()?(detailError?'stale':'ok'):(detailError?'error':'loading')}
function taskOf(sel){return sel?tasks().find(function(t){return t.selector===sel.plan&&(!sel.project||t.project_id===sel.project)})||null:null}
function nameOf(sel){var t=taskOf(sel);return t?t.plan:String(sel.plan||'').replace(/^plan(-ns)?:/,'')}
function clockMs(ms){return ms?new Date(ms).toLocaleTimeString():'?'}
function iso(ms){return ms?new Date(ms).toISOString():null}
function dind(){var e=$('#dconn'),k=detailState();if(k==='none'){e.hidden=true;e.className='';e.textContent='';return}   // the detail freshness, apart from the overview badge
  var n=nameOf(selected);e.hidden=false;
  if(k==='loading'){e.className='wait';e.textContent='chi tiết '+n+': đang tải…'}
  else if(k==='ok'){e.className='ok';e.textContent='chi tiết '+n+': cập nhật lúc '+clockMs(detailOkAt)}
  else{e.className='bad';e.textContent='chi tiết '+n+': lỗi tải từ '+clockMs(detailError.since)+(k==='stale'?' · đang hiện dữ liệu lúc '+clockMs(detailOkAt):' · chưa có dữ liệu')}}
function pendingPane(sel){var t=taskOf(sel),e=detailError;   // the selected task's own heading while its detail is loading or failed; nothing of any other task
  var h='<div class="dhead"><button type="button" id="back">← Danh sách</button><h2 id="dtitle" data-k="dtitle" tabindex="-1">'+esc(nameOf(sel))+(t?' '+st(t.status):'')+'</h2><button type="button" id="close" class="small" title="bỏ chọn task">Đóng</button></div>';
  h+=e?'<div id="dstatus" class="dstatus err" role="status" data-state="error">Không tải được chi tiết task này ('+esc(e.message)+') từ '+clockMs(e.since)+', lần thử gần nhất <span id="dlast">'+clockMs(e.last)+'</span>; trang tự thử lại mỗi '+(INTERVAL/1000)+' s. Chưa có dữ liệu chi tiết nào của task này nên không có câu hỏi hay mẫu lệnh nào để hiện.</div>'
      :'<div id="dstatus" class="dstatus" role="status" data-state="loading">đang tải chi tiết…</div>';
  if(t)h+='<div class="small mut">Theo danh sách: '+esc(t.current_step||t.status.reason||'')+'</div>';
  $('#detail').innerHTML=h}
function tasks(){var out=[];(last&&last.projects||[]).forEach(function(p){p.tasks.forEach(function(t){out.push(t)})});return out}
function visible(){var cur=$('#proj').value,kind=$('#kind').value,q=($('#q').value||'').toLowerCase();
  return tasks().filter(function(t){if(cur&&t.project!==cur)return false;
    if(kind==='need'&&!(t.needs_user||[]).length)return false;if(kind&&kind!=='need'&&t.status.kind!==kind)return false;
    if(q&&((t.plan||'')+' '+(t.goal||'')+' '+(t.title||'')+' '+(t.current_step||'')).toLowerCase().indexOf(q)<0)return false;return true})}
function row(t){var sel=sameSel(selected,{plan:t.selector,project:t.project_id}),lastv=!sel&&sameSel(lastViewed,{plan:t.selector,project:t.project_id});
  return '<li class="task'+(lastv?' last':'')+'" role="option" tabindex="0" aria-selected="'+sel+'" data-plan="'+esc(t.selector)+'" data-project="'+esc(t.project_id)+'" data-k="task:'+esc(t.project_id)+':'+esc(t.selector)+'">'
   +'<div class="r1">'+st(t.status)+'<span class="name">'+esc(t.plan)+'</span><span class="ttl" title="'+esc(t.goal||'')+'">'+esc(t.title||t.goal||'')+'</span>'+((t.needs_user||[]).length?'<span class="needb">cần bạn</span>':'')+'</div>'
   +'<div class="r2 small"><span>'+esc(t.current_step||t.status.reason||'')+'</span>'+(t.last_update?'<span class="mut">cập nhật '+rel(t.last_update.at)+'</span>':'')+'</div>'
   +'<div class="r3 small mut" title="'+esc(t.project)+'">'+esc(short(t.project))+' · '+esc(t.id.slice(0,12))+' · '+esc(t.tracking.adapter)+(t.tracking.errors&&t.tracking.errors.length?' · lỗi đọc':'')+'</div></li>'}
function render(force){
  if(!last)return;var ps=$('#proj'),cur=ps.value,opts='<option value="">tất cả</option>';
  (last.projects||[]).forEach(function(p){opts+='<option value="'+esc(p.path)+'"'+(p.path===cur?' selected':'')+'>'+esc(short(p.path))+'</option>'});if(ps.innerHTML!==opts)ps.innerHTML=opts;
  var vis=visible(),all=tasks(),need=all.filter(function(t){return (t.needs_user||[]).length}).length;
  $('#count').textContent=all.length+' task'+(vis.length!==all.length?' · hiện '+vis.length:'');
  var kindNow=$('#kind').value,counts={need:need,blocked:all.filter(function(t){return t.status.kind==='blocked'}).length,running:all.filter(function(t){return t.status.kind==='running'}).length};
  var chips=[['need','cần bạn'],['blocked','bị chặn'],['running','đang thực hiện']].map(function(c){return '<button type="button" class="chip" data-kind="'+c[0]+'" aria-pressed="'+(kindNow===c[0])+'">'+c[1]+' ('+counts[c[0]]+')</button>'}).join('')+(kindNow?'<button type="button" class="chip" data-kind="" aria-pressed="false">tất cả</button>':'');
  if($('#chips').innerHTML!==chips)$('#chips').innerHTML=chips;
  var sig=JSON.stringify(vis.map(function(t){return [t.selector,t.project_id,t.status.label,t.current_step,t.last_update&&t.last_update.seq,(t.needs_user||[]).length,t.title]}))+'|'+(selected?selected.plan+selected.project:'')+(lastViewed?lastViewed.plan:'');
  if(sig!==listSig||force){var foc=document.activeElement&&document.activeElement.getAttribute&&document.activeElement.getAttribute('data-k');
    $('#list').innerHTML=vis.map(row).join('');listSig=sig;
    if(foc){var again=document.querySelector('[data-k="'+foc.replace(/"/g,'\\"')+'"]');if(again)again.focus({preventScroll:true})}}
  $('#empty').textContent=vis.length?'':(all.length?'Không có task nào khớp bộ lọc.':'Không có plan nào trong sổ này.');
  var u=last.untracked||{},parts=['<div>'+esc(u.statement||'')+'</div>'],n=(u.other_tasks||[]).length+(u.registry_projects_without_plan||[]).length+(u.hook_sessions||[]).length;
  (u.other_tasks||[]).slice(0,10).forEach(function(o){parts.push('<div>· task <code>'+esc(o.id.slice(0,12))+'</code> '+esc(o.key)+' phase '+esc(o.phase)+' — '+esc(o.note)+'</div>')});
  (u.registry_projects_without_plan||[]).slice(0,10).forEach(function(r){parts.push('<div>· '+esc(r.project)+' — '+esc(r.note)+'</div>')});
  (u.hook_sessions||[]).slice(0,10).forEach(function(s){parts.push('<div>· phiên hook '+esc(s.session)+' @ '+esc(s.project)+' — '+esc(s.note)+'</div>')});
  var ub=parts.join('');if($('#untracked').innerHTML!==ub)$('#untracked').innerHTML=ub;$('#untrackedbox').querySelector('summary').textContent='Chưa được theo dõi ('+n+')';
}
function cmdHtml(c,ph){var t=esc(c);if(ph){var p=esc(ph);t=t.split(p).join('<mark class="ph">'+p+'</mark>')}return t}
function needTitle(n){return n.kind==='request'?'Câu hỏi: '+(n.question||'').slice(0,90)+((n.question||'').length>90?'…':''):n.kind==='approve'?'Duyệt kế hoạch':n.kind==='accept'?'Nghiệm thu':n.kind==='stopped'?'Quyết định sau khi dừng':(n.question||n.kind)}
function needKey(n){return n.kind==='request'?'need:'+n.id+':'+n.revision:'need:'+n.kind}
function needCard(n,i){var ph=n.reference_placeholder,nk=needKey(n);var h='<details data-k="'+esc(nk)+'" class="need" data-need-id="'+esc(n.id||'')+'" data-need-rev="'+esc(n.revision||'')+'"><summary>'+esc(needTitle(n))+(n.options&&n.options.length?' <span class="small">('+n.options.length+' lựa chọn)</span>':'')+(n.id?' <span class="small mut">· '+esc(String(n.id).slice(0,12))+'</span>':'')+'</summary><div class="q">'+esc(n.question||n.kind)+'</div>';
  if(n.reason)h+='<div class="small">Vì: '+esc(n.reason)+'</div>';if(n.impact)h+='<div class="small">Ảnh hưởng: '+esc(n.impact)+'</div>';
  if(detailError)h+='<div class="small stale-tpl" data-stale-template="1">Mẫu lệnh này lấy từ dữ liệu lúc '+clockMs(detailOkAt)+' (chi tiết chưa cập nhật): câu hỏi có thể đã được trả lời hoặc đổi bản; khi đó OneCrew từ chối lệnh nhờ --revision cũ.</div>';
  if(n.kind==='request')h+='<div class="small">Mẫu lệnh — phần <mark class="ph">'+esc(ph||'<…>')+'</mark> là lý do/bằng chứng BẠN tự điền; chưa điền thì lệnh chưa chạy được:</div>';
  (n.options||[]).forEach(function(o,j){h+='<div class="opt" data-k="opt:'+esc(nk)+':'+j+'"><b>'+esc(o.label)+'</b> <span class="small mut">('+esc(o.id)+')</span>'+(n.recommendation===o.id?' <span class="small">· khuyến nghị</span>':'')
    +'<div class="cmd"><code>'+cmdHtml(o.reply_command,ph)+'</code><button type="button" class="copy" data-copy="'+esc(o.reply_command)+'">Sao chép mẫu lệnh</button></div></div>'});
  if(!(n.options||[]).length&&n.reply_command)h+='<div class="cmd"><code>'+cmdHtml(n.reply_command,ph)+'</code><button type="button" class="copy" data-copy="'+esc(n.reply_command)+'">Sao chép mẫu lệnh</button></div>';
  h+='<div class="small">'+esc(n.reply_note||n.note||'Trang này không trả lời thay bạn: chạy lệnh ở máy có OneCrew.')+(n.reply_note&&n.note?' · '+esc(n.note):'')+'</div>';
  if(copied&&copied.k===nk){if(copied.ok)h+='<div class="copied" data-copied="'+esc(copied.text)+'">đã sao chép mẫu lệnh (chưa điền '+esc(ph||'')+'): <code>'+esc(copied.text)+'</code></div>';
    else h+='<div class="copied err" data-copy-failed="1">không sao chép được vào clipboard; chọn và sao chép thủ công: <textarea readonly rows="2" style="width:100%">'+esc(copied.text)+'</textarea></div>'}
  return h+'</details>'}
function kindWord(k){return k.replace('executor.observed','quan sát').replace('node.','phần việc: ').replace('plan.','plan: ').replace('attempt.','attempt: ').replace('request.','câu hỏi: ').replace('verdict.','verdict: ').replace('milestone.','mốc: ')}
function evLi(e,idx){var exp=selEv===e.seq;var h='<li tabindex="0" role="button" aria-expanded="'+exp+'" data-seq="'+e.seq+'" data-k="ev:'+e.seq+'" class="'+((e.stale_generation||e.stale_attempt)?'stale':'')+'"><span class="t" title="'+when(e.at)+'">'+clock(e.at)+(e.observed_at&&e.observed_at!==e.at?' (quan sát '+clock(e.observed_at)+')':'')+'</span>'
    +esc(e.summary)+(e.task!=='root'?' <span class="k">(task con)</span>':'')+(e.evidence&&e.evidence.length?'<span class="clip">bằng chứng '+e.evidence.length+'</span>':'')+'<span class="k">#'+e.seq+' '+esc(e.kind)+'</span>'+(e.note?' <b class="small">['+esc(e.note)+']</b>':'');
  if(exp){h+='<div class="evbox" data-k="evbox:'+e.seq+'">';if(!(e.evidence&&e.evidence.length))h+='<span class="mut">bước này không nêu bằng chứng nào</span>';
    (e.evidence||[]).forEach(function(k){var x=idx[k]||{label:'',kind:'',at:null};var open=evState[k];
      h+='<div data-k="evk:'+k+'"><b>'+esc(x.label||'bằng chứng')+'</b> <span class="small mut">'+esc(x.kind||'')+' · '+(x.at?when(x.at):'thời điểm chưa rõ')+' · <code>'+k.slice(0,12)+'…</code></span> '
        +'<button type="button" class="ev-open" data-key="'+k+'">'+(open?'ẩn nội dung':'xem nội dung')+'</button> <a class="small" target="_blank" href="'+evHref(k)+'">mở tab mới</a>'
        +(open?'<pre>'+esc(open.text)+'</pre>':'')+'</div>'});h+='</div>'}
  return h+'</li>'}
function evHref(k){var d=mine();if(!d)return '#';return '/api/evidence?plan='+encodeURIComponent(d.selector)+'&project_id='+encodeURIComponent(d.project_id)+'&key='+k+'&format=text'}
function groups(d){var g={},order=[];function add(key,title,e){if(!g[key]){g[key]={title:title,cur:[],old:[],tech:[]};order.push(key)}var tech=TECH.some(function(p){return e.kind.indexOf(p)===0});
    if(e.stale_generation||e.stale_attempt)g[key].old.push(e);else if(tech)g[key].tech.push(e);else g[key].cur.push(e)}
  add('plan','Plan '+d.plan,{kind:'',seq:-1,summary:''});g.plan.cur=[];
  Object.keys(d.nodes||{}).forEach(function(id){var n=d.nodes[id];add('n:'+id,'phần việc '+id,{kind:'',seq:-1,summary:''});g['n:'+id].cur=[];g['n:'+id].node=n});
  (d.timeline||[]).forEach(function(e){var n=e.node||e.node_of_attempt;if(n)add('n:'+n,'phần việc '+n,e);else add('plan','Plan '+d.plan,e)});return {g:g,order:order}}
function renderDetail(d){
  var idx={};(d.evidence_index||[]).forEach(function(x){idx[x.key]=x});
  var h=['<div class="dhead"><button type="button" id="back">← Danh sách</button><h2 id="dtitle" data-k="dtitle" tabindex="-1">'+esc(d.plan)+' '+st(d.status)+'</h2><button type="button" id="close" class="small" title="bỏ chọn task">Đóng</button></div>'];
  if(detailError)h.push('<div id="dstatus" class="dstatus stale" role="status" data-state="stale">Chi tiết chưa cập nhật từ '+clockMs(detailOkAt)+': lỗi tải chi tiết ('+esc(detailError.message)+', lần thử gần nhất <span id="dlast">'+clockMs(detailError.last)+'</span>); đang hiện dữ liệu lúc '+(d.generated_at?clock(d.generated_at):clockMs(detailOkAt))+'. Mẫu lệnh trả lời bên dưới là của lúc đó: nếu câu hỏi đã được trả lời hoặc đổi bản, OneCrew từ chối lệnh nhờ --revision. Trang tự thử lại.</div>');
  h.push('<div class="small mut">Đang xem task <b>'+esc(d.plan)+'</b> của project <span title="'+esc(d.project)+'">'+esc(short(d.project))+'</span> · <a href="'+esc(urlOf({plan:d.selector,project:d.project_id}))+'">liên kết tới task này</a></div>');
  var needs=d.needs_user||[],nq=needs.filter(function(n){return n.kind==='request'}).length,nother=needs.length-nq;
  h.push('<div class="dsum"><span class="step">'+esc(d.current_step||d.status.reason||'')+'</span>'+(needs.length?'<a href="#needs" class="small">'+(nq?nq+' câu hỏi chờ bạn':'')+(nq&&nother?' · ':'')+(nother?nother+' việc cần bạn':'')+'</a>':'<span class="small mut">không cần bạn lúc này</span>')+'</div>');
  if(d.goal)h.push('<p style="margin:6px 0">'+esc(d.goal)+'</p>');
  var done=d.status.kind==='done';
  var nowKeys={};needs.forEach(function(n){nowKeys[needKey(n)]=n});
  Object.keys(knownNeeds).forEach(function(k){var old=knownNeeds[k];if(nowKeys[k]||!old.open)return;
    var same=needs.find(function(n){return n.kind==='request'&&n.id===old.id});
    if(!staleNotes.some(function(x){return x.key===k}))staleNotes.push({key:k,id:old.id,title:old.title,why:same?'đã đổi bản (revision '+String(same.revision).slice(0,12)+'…): mẫu lệnh cũ không còn hiệu lực, đọc lại câu hỏi':'không còn chờ (đã được trả lời hoặc đóng): mẫu lệnh cũ không còn hiệu lực'});
    if(copied&&copied.k===k)copied=null});
  if(needs.length||staleNotes.length){h.push('<h3 id="needs">Cần bạn ('+needs.length+')</h3>');
    staleNotes.forEach(function(x){h.push('<div class="stale-need" data-k="stale:'+esc(x.key)+'" data-stale-id="'+esc(x.id||'')+'">Câu hỏi bạn đang đọc <b>'+esc(String(x.id||'').slice(0,12))+'…</b> ('+esc(x.title||'')+') '+esc(x.why)+'.<button type="button" class="stale-hide" data-key="'+esc(x.key)+'">ẩn</button></div>')});
    needs.forEach(function(n,i){h.push(needCard(n,i))})}
  h.push(gantt(d));
  function brief(t,n){t=String(t||'');return t.length>n?'<span title="'+esc(t)+'">'+esc(t.slice(0,n))+'…</span>':esc(t)}
  h.push('<div class="stats"><div class="tile"><div class="l">Trạng thái</div><div class="v">'+esc(d.status.label)+'</div><div class="s">'+brief(d.status.reason,140)+'</div></div>'
    +'<div class="tile"><div class="l">Đầu ra</div><div class="v">'+esc(d.level.label)+'</div><div class="s">'+brief(d.current_step||'',140)+'</div></div>'
    +'<div class="tile"><div class="l">Từ khi duyệt (lịch)</div><div class="v"'+(!done&&!d.elapsed.until&&typeof d.elapsed.seconds==='number'?' data-live="'+d.elapsed.seconds+'" data-live-at="'+Date.now()+'"':'')+'>'+hms(d.elapsed.seconds)+'</div><div class="s">'+(typeof d.elapsed.seconds==='number'?'gồm cả thời gian chờ'+(d.elapsed.until?' · kết thúc '+when(d.elapsed.until):' · đang tính theo đồng hồ máy này'):'chưa duyệt: chưa có mốc bắt đầu')+'</div></div>'
    +'<div class="tile"><div class="l">Thực hiện (attempt)</div><div class="v">'+hms(d.measure.attempts_wall_seconds)+'</div><div class="s">hợp các khoảng attempt, không cộng đôi</div></div>'
    +'<div class="tile"><div class="l">Chờ</div><div class="v">'+hms(d.measure.wait_seconds)+'</div><div class="s">'+((d.waits||[]).filter(function(w){return w.open}).length?'đang có khoảng chờ mở':'khoảng chờ đã đo; thiếu nguồn = chưa xác định')+'</div></div>'
    +'<div class="tile"><div class="l">Còn lại (ước lượng)</div><div class="v">'+esc(d.eta.label)+'</div><div class="s">'+brief(d.eta.reason||'',140)+(d.eta.deadline?' · hạn '+when(d.eta.deadline):'')+'</div></div></div>');
  var ow=(d.waits||[]).filter(function(w){return w.open}),cw=(d.waits||[]).filter(function(w){return !w.open});
  if(ow.length)h.push('<div class="small"><b>Đang chờ:</b> '+ow.map(function(w){return esc(w.reason||'không rõ')+' từ '+when(w.since)+(w.node?' (phần việc '+esc(w.node)+')':'')}).join('; ')+'</div>');
  if((d.holds||[]).length)h.push('<div class="small"><b>Giữ (finding):</b> '+d.holds.map(function(x){return esc(x.text||x.error)}).join('; ')+'</div>');
  var ns=Object.keys(d.nodes||{});if(ns.length){h.push('<h3>Phần việc</h3><div class="scroll"><table><thead><tr><th>Phần việc</th><th>Trạng thái</th><th>Đầu ra</th><th>Thế hệ</th><th>Quan sát gần nhất</th></tr></thead><tbody>');
    ns.forEach(function(id){var n=d.nodes[id],p=n.progress;h.push('<tr><td><b>'+esc(id)+'</b></td><td>'+word(PHASE,n.phase)+(n.phase==='held'?'<div class="small" style="color:var(--blk)">lý do (engine): '+esc(n.reason)+'</div>':'')+'</td><td>'+word(NSTATE,n.state)+(n.verification_result?' ('+esc(n.verification_result)+')':'')+'</td><td>'+n.generation+(n.continues?' <span class="small mut">tiếp từ '+esc(n.continues)+'</span>':'')+'</td><td class="wrap small">'+(p?esc(p.status)+' '+rel(p.observed_at||p.received_at)+(p.reason?'<br>'+esc(p.reason):''):'—')+'</td></tr>')});h.push('</tbody></table></div>')}
  var G=groups(d);h.push('<details data-k="log"><summary>Nhật ký sự kiện ('+d.timeline.length+'/'+d.timeline_total+', cũ → mới; bấm một bước để xem bằng chứng của bước đó)</summary>');
  G.order.forEach(function(key){var x=G.g[key];if(!x.cur.length&&!x.old.length&&!x.tech.length)return;
    h.push('<section class="grp" data-k="grp:'+esc(key)+'"><div class="gh"><h4>'+esc(x.title)+'</h4>'+(x.node?'<span class="small mut">thế hệ '+x.node.generation+(x.node.attempt?' · attempt <code>'+esc(x.node.attempt.slice(0,16))+'</code>':'')+'</span>':'')+'</div>');
    h.push('<ol class="ev">'+x.cur.map(function(e){return evLi(e,idx)}).join('')+'</ol>');
    if(x.old.length)h.push('<details data-k="old:'+esc(key)+'"><summary>lịch sử cũ ('+x.old.length+' sự kiện của thế hệ/attempt trước; không đổi trạng thái hiện tại)</summary><ol class="ev">'+x.old.map(function(e){return evLi(e,idx)}).join('')+'</ol></details>');
    if(x.tech.length)h.push('<details data-k="tech:'+esc(key)+'"><summary>chi tiết kỹ thuật ('+x.tech.length+')</summary><ol class="ev">'+x.tech.map(function(e){return evLi(e,idx)}).join('')+'</ol></details>');
    h.push('</section>')});
  h.push('</details>');
  h.push('<details data-k="evidence"><summary>Bằng chứng ('+(d.evidence_index||[]).length+' blob, lọc bí mật, chỉ đọc)</summary>'+(d.evidence_index||[]).map(function(x){return '<div class="small" data-k="evk:'+x.key+'"><b>'+esc(x.label)+'</b> · '+esc(x.kind)+' · '+(x.at?when(x.at):'thời điểm chưa rõ')+(x.node?' · phần việc '+esc(x.node):'')+' · <code>'+x.key.slice(0,12)+'…</code> <button type="button" class="ev-open" data-key="'+x.key+'">'+(evState[x.key]?'ẩn nội dung':'xem nội dung')+'</button> <a target="_blank" href="'+evHref(x.key)+'">mở tab mới</a>'+(evState[x.key]?'<pre>'+esc(evState[x.key].text)+'</pre>':'')+'</div>'}).join('')+'</details>');
  if(cw.length)h.push('<details data-k="waits"><summary>Đã chờ (lịch sử, '+cw.length+')</summary>'+cw.map(function(w){return '<div class="small">'+esc(w.reason||'không rõ')+' '+when(w.since)+' → '+(w.until==='unknown'?'chưa rõ kết thúc':when(w.until))+' ('+esc(w.source)+')</div>'}).join('')+'</details>');
  if((d.attempts||[]).length){var mx={};((d.measure&&d.measure.attempts)||[]).forEach(function(m){mx[m.attempt]=m});var top=0;Object.keys(mx).forEach(function(k){if(typeof mx[k].execution_seconds==='number')top=Math.max(top,mx[k].execution_seconds)});
    h.push('<details data-k="attempts"><summary>Attempt ('+d.attempts.length+')</summary><div class="scroll"><table><thead><tr><th>Attempt</th><th>Trạng thái</th><th>Thế hệ</th><th>Thời lượng (đo)</th><th>Từ</th><th>Cập nhật</th></tr></thead><tbody>'+d.attempts.map(function(a){var m=mx[a.id],sec=m&&typeof m.execution_seconds==='number'&&m.settled_at?m.execution_seconds:null;
      return '<tr><td><code>'+esc(a.id)+'</code></td><td>'+esc(a.status)+'</td><td>'+a.generation+'</td><td class="small">'+(sec!==null?'<span class="dur" style="width:'+Math.max(4,Math.round(sec/(top||1)*80))+'px"></span>'+hms(sec):'chưa xác định')+'</td><td class="small">'+when(a.created_at)+'</td><td class="small">'+when(a.updated_at)+'</td></tr>'}).join('')+'</tbody></table></div></details>')}
  if((d.notices||[]).length)h.push('<details data-k="notices"><summary>Thông báo ('+d.notices.length+')</summary>'+d.notices.map(function(n){return '<div class="small">'+when(n.at)+' '+esc(n.category)+': '+esc(n.reason)+(n.user_action?' — '+esc(n.user_action):'')+'</div>'}).join('')+'</details>');
  h.push('<details data-k="techinfo"><summary>Kỹ thuật</summary><div class="small">id <code>'+esc(d.id)+'</code> · selector <code>'+esc(d.selector)+'</code> · project <code>'+esc(d.project)+'</code> · project_id <code>'+esc(d.project_id)+'</code><br>root: '+esc(d.root_status)+' · hợp đồng bản '+esc(d.contract_revision)+' · adapter '+esc(d.tracking.adapter)+' — '+esc(d.tracking.coverage)+'<br>nguồn trạng thái: '+esc((d.status.source||[]).join(', '))+'<br>'+esc(d.elapsed.basis||'')+'<br>'+(d.measure.method?'đo: '+esc(JSON.stringify(d.measure.method)):'')+'<br>'+esc(d.controls)+'</div></details>');
  $('#detail').innerHTML=h.join('');
  knownNeeds={};needs.forEach(function(n){var el=document.querySelector('#detail details[data-k="'+needKey(n).replace(/"/g,'\\"')+'"]');knownNeeds[needKey(n)]={id:n.id,revision:n.revision,title:needTitle(n),open:!!(el&&el.open)}});
}
function noteOpen(){needs_open_sync()}
function needs_open_sync(){Object.keys(knownNeeds).forEach(function(k){var el=document.querySelector('#detail details[data-k="'+k.replace(/"/g,'\\"')+'"]');if(el)knownNeeds[k].open=el.open})}
// ---- Gantt / waterfall: tree (left) | shared time axis (centre) | step pane (right); every pixel comes from a sourced timestamp
function tms(t){var v=new Date(t).getTime();return isNaN(v)?null:v}
function gWindow(g){var a=g.axis,e0=tms(a.start),e1=tms(a.end);if(e0===null||e1===null)return null;if(e1<=e0)e1=e0+1000;
  var w0=e0,w1=e1;if(gRange==='1h')w0=Math.max(e0,e1-3600000);else if(gRange==='15m')w0=Math.max(e0,e1-900000);if(w1-w0<1000)w0=w1-1000;return {w0:w0,w1:w1,e0:e0,e1:e1}}
function pct(W,t){var v=tms(t);if(v===null)return null;return (v-W.w0)/(W.w1-W.w0)*100}
function segHtml(W,row,sg,i){var l=pct(W,sg.from),r=pct(W,sg.to);if(l===null||r===null)return '';if(r<0||l>100)return '';var L=Math.max(0,l),Rr=Math.min(100,r);
  var id='seg:'+row.attempt+':'+i,sel=selStep&&selStep.id===id;
  return '<div class="seg '+esc(sg.kind)+(sel?' sel':'')+'" tabindex="0" role="button" data-k="'+esc(id)+'" data-attempt="'+esc(row.attempt)+'" data-kind="'+esc(sg.kind)+'" data-from="'+esc(sg.from)+'" data-to="'+esc(sg.to)+'" data-confirmed="'+sg.confirmed+'" style="left:'+L.toFixed(3)+'%;width:'+Math.max(0.15,Rr-L).toFixed(3)+'%" title="'+esc(segWord(sg.kind))+': '+when(sg.from)+' → '+(sg.kind==='to_now'?'hiện tại (chưa xác nhận)':when(sg.to))+'"></div>'}
function markHtml(W,m,rowKey){var l=pct(W,m.at);if(l===null||l<0||l>100)return '';var id='mk:'+m.seq,sel=selStep&&selStep.id===id,cls=m.kind==='node.held'?' held':/pass/.test(m.label)?' pass':/fail/.test(m.label)?' fail':m.kind.indexOf('plan.')===0||m.kind.indexOf('request.')===0?' plan':'';
  return '<span class="mk'+cls+(sel?' sel':'')+'" tabindex="0" role="button" data-k="'+esc(id)+'" data-seq="'+m.seq+'" data-at="'+esc(m.at)+'" data-row="'+esc(rowKey)+'" style="left:'+l.toFixed(3)+'%" title="'+esc(m.label)+' · '+when(m.at)+'" aria-label="'+esc(m.label)+' '+when(m.at)+'">◆</span>'}
function segWord(k){return {execution:'thực thi',reserved:'đặt chỗ',wait:'chờ',verification:'kiểm',to_now:'tới hiện tại (chưa xác nhận)'}[k]||k}
function waitSeg(W,row,w,i){if(!w.until)return '';var l=pct(W,w.from),r=pct(W,w.until);if(l===null||r===null||r<0||l>100)return '';var id='wait:'+row.attempt+':'+i,sel=selStep&&selStep.id===id;
  return '<div class="seg wait'+(sel?' sel':'')+'" tabindex="0" role="button" data-k="'+esc(id)+'" data-attempt="'+esc(row.attempt)+'" data-kind="wait" data-from="'+esc(w.from)+'" data-to="'+esc(w.until)+'" style="left:'+Math.max(0,l).toFixed(3)+'%;width:'+Math.max(0.15,Math.min(100,r)-Math.max(0,l)).toFixed(3)+'%" title="chờ: '+esc(w.reason||'')+' '+when(w.from)+' → '+when(w.until)+'"></div>'}
function verSeg(W,row,v,i){var l=pct(W,v.from),r=pct(W,v.to);if(l===null||r===null||r<0||l>100)return '';var id='ver:'+row.attempt+':'+i,sel=selStep&&selStep.id===id;
  return '<div class="seg verification'+(sel?' sel':'')+'" tabindex="0" role="button" data-k="'+esc(id)+'" data-attempt="'+esc(row.attempt)+'" data-kind="verification" data-from="'+esc(v.from)+'" data-to="'+esc(v.to)+'" style="left:'+Math.max(0,l).toFixed(3)+'%;width:'+Math.max(0.15,Math.min(100,r)-Math.max(0,l)).toFixed(3)+'%" title="kiểm ('+esc(v.result)+'): '+when(v.from)+' → '+when(v.to)+'"></div>'}
function gantt(d){var g=d.gantt||{rows:[],plan_marks:[],axis:{}},W=gWindow(g);
  var h=['<section class="gantt" data-k="gantt" aria-label="Timeline">'];
  var legend='<span class="legend"><span><i class="sw execution"></i>thực thi</span><span><i class="sw reserved"></i>đặt chỗ</span><span><i class="sw wait"></i>chờ (có mốc kết thúc)</span><span><i class="sw verification"></i>kiểm</span><span><i class="sw to_now"></i>tới hiện tại, chưa xác nhận</span><span>◆ dấu mốc</span><span style="opacity:.45"><i class="sw execution"></i>lượt cũ</span></span>';
  if(!W){h.push('<div><div class="gtop"><b style="color:var(--fg)">Timeline</b>'+legend+'</div><div class="mut small" id="gempty">'+(g.rows&&g.rows.length?'chưa có mốc thời gian có nguồn':'chưa có lượt thực hiện nào (chưa có mốc thời gian)')+'</div></div><div class="gside" id="gside"><span class="mut">Chọn một thanh hoặc dấu mốc để xem số liệu chính xác.</span></div></section>');return h.join('')}
  var axisSec=(W.w1-W.w0)/1000;
  h.push('<div><div class="gtop"><b style="color:var(--fg)">Timeline</b><span>'+when(new Date(W.w0).toISOString())+' → '+(g.axis.extends_to_now&&gRange!=='x'?'hiện tại ('+when(g.axis.now)+' theo server)':when(new Date(W.w1).toISOString()))+' · '+hms(axisSec)+'</span>'+(lostSince?'<span class="gstale" id="gstale">mất kết nối: đang hiện dữ liệu cũ lúc '+(lastOk?new Date(lastOk).toLocaleTimeString():'?')+', đồng hồ dừng</span>':detailError?'<span class="gstale" id="gstale">chi tiết chưa cập nhật: đang hiện dữ liệu lúc '+clockMs(detailOkAt)+', đồng hồ dừng</span>':'')
    +'<label>khoảng <select id="grange"><option value="all"'+(gRange==='all'?' selected':'')+'>toàn khoảng</option><option value="1h"'+(gRange==='1h'?' selected':'')+'>1 giờ cuối</option><option value="15m"'+(gRange==='15m'?' selected':'')+'>15 phút cuối</option></select></label>'+legend+'</div>');
  var ticks=[];for(var i=0;i<=5;i++){var t=W.w0+(W.w1-W.w0)*i/5;ticks.push('<i style="left:'+(i*20)+'%"></i><span class="t'+i+(i===0?' first':i===5?' last':'')+'" style="left:'+(i*20)+'%">'+new Date(t).toLocaleTimeString()+'</span>')}
  var tree=['<div class="grow gh0">Phần việc › lượt</div>'],chart=['<div class="gaxis">'+ticks.join('')+'</div>'];
  var nowL=g.axis.extends_to_now?pct(W,g.axis.now):null;
  function chartRow(inner,cls){return '<div class="grow'+(cls?' '+cls:'')+'">'+inner+(nowL!==null&&nowL>=0&&nowL<=100?'<span class="nowline" style="left:'+nowL.toFixed(3)+'%"></span>':'')+'</div>'}
  // plan row
  tree.push('<div class="grow nodehead" data-k="grow:plan">Plan '+esc(d.plan)+'</div>');chart.push(chartRow((g.plan_marks||[]).map(function(m){return markHtml(W,m,'plan')}).join('')));
  var byNode={};(g.rows||[]).forEach(function(r){byNode[r.node||'?']=byNode[r.node||'?']||[];byNode[r.node||'?'].push(r)});
  Object.keys(d.nodes||{}).concat(Object.keys(byNode).filter(function(k){return !(k in (d.nodes||{}))})).forEach(function(nid){var rows=byNode[nid]||[],n=(d.nodes||{})[nid]||{},cur=rows.filter(function(r){return r.current||r.active}),old=rows.filter(function(r){return !(r.current||r.active)});
    var folded=gFold['n:'+nid]===true,hist=gFold['h:'+nid]!==false;
    tree.push('<div class="grow nodehead" data-k="grow:n:'+esc(nid)+'"><button type="button" class="tg" data-fold="n:'+esc(nid)+'" aria-expanded="'+(!folded)+'">'+(folded?'▸':'▾')+'</button>'+esc(nid)+' <span class="mut">'+esc(PHASE[n.phase]||n.phase||'')+(rows.length?' · '+rows.length+' lượt':' · chưa có lượt')+'</span></div>');
    chart.push(chartRow(folded?cur.map(function(r){return r.segments.map(function(sg,i){return segHtml(W,r,sg,i)}).join('')}).join(''):''));
    if(folded)return;
    cur.forEach(function(r){tree.push('<div class="grow att'+(r.current?' cur':'')+'" data-k="grow:'+esc(r.attempt)+'" title="'+esc(r.attempt)+'">'+(r.current?'● ':'')+'lượt '+esc(r.attempt.slice(4,12))+' <span class="mut">thế hệ '+r.generation+' · '+esc(r.status)+'</span></div>');
      chart.push(chartRow(r.segments.map(function(sg,i){return segHtml(W,r,sg,i)}).join('')+r.waits.map(function(w,i){return waitSeg(W,r,w,i)}).join('')+r.verification.map(function(v,i){return verSeg(W,r,v,i)}).join('')+r.marks.map(function(m){return markHtml(W,m,r.attempt)}).join('')))});
    if(old.length){tree.push('<div class="grow hist" data-k="grow:h:'+esc(nid)+'"><button type="button" class="tg" data-fold="h:'+esc(nid)+'" aria-expanded="'+(!hist)+'">'+(hist?'▸':'▾')+'</button>lịch sử ('+old.length+' lượt cũ)</div>');
      chart.push(chartRow(hist?old.map(function(r){return r.segments.map(function(sg,i){return segHtml(W,r,sg,i)}).join('')}).join(''):'','old'));
      if(!hist)old.forEach(function(r){tree.push('<div class="grow att" data-k="grow:'+esc(r.attempt)+'" title="'+esc(r.attempt)+'">lượt '+esc(r.attempt.slice(4,12))+' <span class="mut">thế hệ '+r.generation+' · '+esc(r.status)+'</span></div>');
        chart.push(chartRow(r.segments.map(function(sg,i){return segHtml(W,r,sg,i)}).join('')+r.waits.map(function(w,i){return waitSeg(W,r,w,i)}).join('')+r.verification.map(function(v,i){return verSeg(W,r,v,i)}).join('')+r.marks.map(function(m){return markHtml(W,m,r.attempt)}).join(''),'old'))})}});
  h.push('<div class="gscroll" data-k="gscroll"><div class="gbody"><div class="gtree">'+tree.join('')+'</div><div class="gchart" data-w0="'+new Date(W.w0).toISOString()+'" data-w1="'+new Date(W.w1).toISOString()+'">'+chart.join('')+'</div></div></div></div>');
  h.push('<div class="gside" id="gside">'+gside(d,g)+'</div></section>');return h.join('')}
function gside(d,g){if(!selStep)return '<span class="mut">Chọn một thanh hoặc dấu mốc (chuột hoặc Tab + Enter) để xem mốc chính xác, lý do, đầu ra và bằng chứng của bước đó.</span>';
  var idx={};(d.evidence_index||[]).forEach(function(x){idx[x.key]=x});
  function evRows(list,empty){return list.length?list.map(function(x){return '<div class="small" data-k="evk:'+x.key+'"><b>'+esc(x.label)+'</b> · '+esc(x.kind)+(typeof x.generation==='number'?' · thế hệ '+x.generation:'')+' · '+(x.at?when(x.at):'thời điểm chưa rõ')+' <button type="button" class="ev-open" data-key="'+x.key+'">'+(evState[x.key]?'ẩn nội dung':'xem nội dung')+'</button> <a target="_blank" href="'+evHref(x.key)+'">mở tab mới</a>'+(evState[x.key]?'<pre>'+esc(evState[x.key].text)+'</pre>':'')+'</div>'}).join(''):'<span class="mut small" id="evnone">'+(empty||'bước này không nêu bằng chứng')+'</span>'}
  var parts=selStep.id.split(':');
  if(parts[0]==='mk'){var seq=parseInt(parts[1],10),m=null;(g.plan_marks||[]).concat.apply([],(g.rows||[]).map(function(r){return r.marks})).forEach(function(x){if(x.seq===seq)m=x});if(!m)return '<span class="mut">dấu mốc không còn trong khoảng đang xem</span>';
    var ev=(d.timeline||[]).find(function(e){return e.seq===seq}),ex=(d.evidence_index||[]).filter(function(x){return x.seq===seq});
    return '<h4>◆ '+esc(m.label)+'</h4><dl><dt>thời điểm</dt><dd>'+when(m.at)+'</dd><dt>sự kiện</dt><dd><code>#'+seq+' '+esc(m.kind)+'</code></dd>'+(ev?'<dt>nội dung</dt><dd>'+esc(ev.summary)+'</dd>':'')+'</dl><div class="small"><b>Bằng chứng</b></div>'+evRows(ex)}
  var r=(g.rows||[]).find(function(x){return x.attempt===parts[1]});if(!r)return '<span class="mut">lượt không còn trong dữ liệu</span>';
  var which=parts[0],i=parseInt(parts[2],10),sg=which==='seg'?r.segments[i]:which==='wait'?r.waits[i]:which==='ver'?r.verification[i]:null;
  var inh=r.inherits||[],inhKeys=inh.map(function(x){return x.key});
  var ex=(d.evidence_index||[]).filter(function(x){if(inhKeys.indexOf(x.key)>=0)return false;if(x.attempt)return x.attempt===r.attempt;return x.node===r.node&&x.generation===r.generation});   // P2-B: this attempt's own evidence (or its node in ITS generation), never another generation's
  var h='<h4>Lượt <code>'+esc(r.attempt.slice(0,16))+'…</code> · phần việc '+esc(r.node||'?')+' · thế hệ '+r.generation+' · '+esc(r.status)+(r.current?' · hiện hành':r.active?'':' · lượt cũ')+'</h4>';
  if(sg)h+='<div class="small"><b>'+esc(which==='seg'?segWord(sg.kind):which==='wait'?'chờ'+(sg.reason?': '+esc(sg.reason):''):'kiểm ('+esc(sg.result)+')')+'</b> '+when(sg.from)+' → '+(which==='seg'&&sg.kind==='to_now'?'hiện tại (chưa xác nhận)':when(sg.to||sg.until))+(which==='seg'&&sg.kind!=='to_now'?' · '+hms((tms(sg.to)-tms(sg.from))/1000):'')+'</div>';
  h+='<dl><dt>đặt chỗ</dt><dd>'+when(r.reserved_at)+'</dd><dt>bắt đầu chạy</dt><dd>'+(r.launched_at?when(r.launched_at):'chưa xác định')+'</dd><dt>kết thúc</dt><dd>'+(r.settled_at?when(r.settled_at):r.active?'đang chạy · mốc dữ liệu mới nhất '+when(r.latest_mark_at):'chưa xác định')+'</dd><dt>thực thi</dt><dd>'+hms(r.execution_seconds)+'</dd><dt>chờ</dt><dd>'+(r.waits.length?r.waits.map(function(w){return esc(w.reason||'')+' '+when(w.from)+' → '+(w.until?when(w.until):'chưa rõ kết thúc')}).join('; '):'không ghi nhận')+'</dd><dt>kiểm</dt><dd>'+(r.verification.length?r.verification.map(function(v){return esc(v.result)+' ('+hms((tms(v.to)-tms(v.from))/1000)+')'}).join('; '):'chưa')+'</dd></dl>';
  var node=(d.nodes||{})[r.node]||{};if(node.phase==='held'&&r.current)h+='<div class="small" style="color:var(--blk)">bị giữ — lý do (engine): '+esc(node.reason)+'</div>';
  if(node.progress&&r.current)h+='<div class="small">quan sát gần nhất: '+esc(node.progress.status)+' '+when(node.progress.observed_at||node.progress.received_at)+(node.progress.reason?' — '+esc(node.progress.reason):'')+'</div>';
  if(r.marks.length)h+='<div class="small mut">dấu mốc: '+r.marks.map(function(m){return esc(m.label)+' '+clock(m.at)}).join(' · ')+'</div>';
  var isOut=function(x){return x.kind==='node.produced'||x.kind==='node.verification'||x.kind==='attempt.settled'||x.kind.indexOf('node.receipt')===0},outs=ex.filter(isOut),rest=ex.filter(function(x){return !isOut(x)});
  h+='<div class="small" style="margin-top:4px"><b>Đầu ra của lượt này</b> <span class="mut">(thế hệ '+r.generation+')</span></div>'+evRows(outs,r.active?'lượt này chưa có đầu ra (đang chạy)':'lượt này không có đầu ra');
  if(rest.length)h+='<div class="small" style="margin-top:4px"><b>Bằng chứng khác của lượt này</b></div>'+evRows(rest);
  if(inh.length)h+='<div class="small" style="margin-top:4px" id="inherit"><b>Kế thừa</b> <span class="mut">(hợp lệ, từ lượt trước)</span></div>'+inh.map(function(x){var e=x.key?idx[x.key]:null;return '<div class="small" data-k="inh:'+esc(x.key||x.kind)+'">'+esc(x.label)+(typeof x.from_generation==='number'?' từ thế hệ '+x.from_generation:'')+(x.from_attempt?' (lượt '+esc(String(x.from_attempt).slice(4,12))+')':'')+' · nguồn <code>'+esc(x.source)+'</code>'+(x.key?' <button type="button" class="ev-open" data-key="'+x.key+'">'+(evState[x.key]?'ẩn nội dung':'xem nội dung')+'</button> <a target="_blank" href="'+evHref(x.key)+'">mở tab mới</a>'+(evState[x.key]?'<pre>'+esc(evState[x.key].text)+'</pre>':''):'')+'</div>'}).join('');
  return h}
function repaintGantt(){var d=mine();if(!d)return;var s=snapshot();var el=document.querySelector('#detail .gantt');if(el){var t=document.createElement('div');t.innerHTML=gantt(d);el.replaceWith(t.firstChild)}restore(s)}
function snapshot(){var open={};document.querySelectorAll('#detail details[data-k]').forEach(function(x){open[x.getAttribute('data-k')]=x.open});
  var a=document.activeElement,foc=a&&a.closest&&a.closest('[data-k]'),inner=null;
  if(a&&foc){if(a.tagName==='SUMMARY')inner='summary';else if(a.classList.contains('copy'))inner='copy';else if(a.classList.contains('ev-open'))inner='ev-open:'+a.getAttribute('data-key');else if(a.tagName==='A')inner='a'}
  var gs=document.querySelector('#detail .gscroll');
  return {open:open,focus:foc?foc.getAttribute('data-k'):null,inner:inner,pane:$('#detailpane').scrollTop,win:window.scrollY,gs:gs?gs.scrollLeft:0}}
function restore(s){if(!s)return;Object.keys(s.open).forEach(function(k){var x=document.querySelector('#detail details[data-k="'+k.replace(/"/g,'\\"')+'"]');if(x)x.open=s.open[k]});
  if(s.focus){var f=document.querySelector('[data-k="'+s.focus.replace(/"/g,'\\"')+'"]');if(f){var t=null;
    if(s.inner==='summary'||f.tagName==='DETAILS')t=f.querySelector('summary');else if(s.inner==='copy')t=f.querySelector('button.copy');else if(s.inner&&s.inner.indexOf('ev-open:')===0)t=f.querySelector('.ev-open[data-key="'+s.inner.slice(8)+'"]');else if(s.inner==='a')t=f.querySelector('a');
    (t||f).focus({preventScroll:true})}}
  var gs=document.querySelector('#detail .gscroll');if(gs&&s.gs)gs.scrollLeft=s.gs;
  $('#detailpane').scrollTop=s.pane;if(Math.abs(window.scrollY-s.win)>2)window.scrollTo(0,s.win)}
function paint(d,sel,why){var s=snapshot();detailData=d;detailFor={plan:sel.plan,project:sel.project};renderDetail(d);restore(s);if(why==='select')afterSelect()}
function afterSelect(){setView();if(narrow())window.scrollTo(0,0);else{var r=$('#detailpane').getBoundingClientRect();if(r.top<0||r.top>window.innerHeight*0.8)$('#detailpane').scrollIntoView({block:'start'})}
  if(selected&&selected.focusDetail){selected.focusDetail=false;var t=$('#dtitle');if(t)t.focus({preventScroll:true})}}
function loadDetail(why){if(!selected)return;var token=++detailToken,sel={plan:selected.plan,project:selected.project};
  function current(){return token===detailToken&&sameSel(sel,selected)}      // a reply OR a failure of a superseded request / a task no longer selected never touches the page
  fetch('/api/task?plan='+encodeURIComponent(sel.plan)+(sel.project?'&project_id='+encodeURIComponent(sel.project):'')+'&timeline=300',{cache:'no-store'})
  .then(function(r){return r.text().then(function(t){var j=null;try{j=JSON.parse(t)}catch(e){}return {ok:r.ok,status:r.status,j:j}})})
  .then(function(x){if(!current())return;
      if(!x.ok||!x.j||typeof x.j!=='object')return detailFailed(sel,'HTTP '+x.status+(x.j&&x.j.error?': '+x.j.error:x.ok?': trả lời không đọc được':''));
      detailLoaded(sel,x.j,why)},
    function(){if(!current())return;detailFailed(sel,'mất kết nối khi tải chi tiết')})}
function detailLoaded(sel,j,why){var had=mine(),wasErr=!!detailError,seq=j.source&&j.source.last_seq;detailError=null;detailOkAt=Date.now();
  if(had&&!wasErr&&why!=='select'&&why!=='force'&&seq===detailSeq&&had.selector===j.selector&&had.project_id===j.project_id){detailData=j;if(j.gantt&&j.gantt.axis&&(j.gantt.axis.extends_to_now||$('#gstale')))repaintGantt();dind();return}   // nothing moved in the ledger: keep what the reader is looking at; only the server clock parts of the timeline move (P2-A)
  detailSeq=seq;paint(j,sel,had?why:'select');dind()}      // recovery from a stale state re-renders once (warning and template marks go; snapshot/restore keep the reader's place)
function detailFailed(sel,msg){var now=Date.now(),changed=!detailError||detailError.message!==msg,d=mine(),s;
  detailError={since:detailError?detailError.since:now,last:now,message:msg};
  if(d){if(changed){s=snapshot();renderDetail(d);restore(s)}else{var l=$('#dlast');if(l)l.textContent=clockMs(now)}}     // the task already shown: its data stays, marked stale
  else if(changed||!$('#dstatus')||$('#dstatus').getAttribute('data-state')!=='error'){s=snapshot();pendingPane(sel);restore(s)}   // never loaded: its own heading + the error, nothing else
  else{var l2=$('#dlast');if(l2)l2.textContent=clockMs(now)}
  dind()}
function select(sel,opts){opts=opts||{};if(!sel){if(selected){lastViewed=selected}selected=null;selEv=null;evState={};copied=null;detailData=null;detailFor=null;detailError=null;detailOkAt=null;detailSeq=null;$('#detail').innerHTML='<div id="nodetail">Chọn một task ở danh sách để xem chi tiết, timeline và bằng chứng.</div>';setView();render(true);dind();
    if(!opts.silent&&location.search)history.pushState({},'',location.pathname);return}
  var other=!sameSel(selected,sel);
  if(other){selEv=null;evState={};copied=null;detailSeq=null;selStep=null;gFold={};staleNotes=[];knownNeeds={};detailData=null;detailFor=null;detailError=null;detailOkAt=null}
  selected={plan:sel.plan,project:sel.project||'',focusDetail:!!opts.focusDetail};setView();render(true);
  if(!mine()){pendingPane(selected);afterSelect()}dind();     // another task: its heading + "đang tải" at once, never the previous task's content
  if(!opts.silent&&location.search!==urlOf(selected))history.pushState({plan:selected.plan,project:selected.project},'',urlOf(selected));
  loadDetail('select')}
function poll(){fetch('/api/overview',{cache:'no-store'}).then(function(r){return r.json()}).then(function(j){
    if(j.error&&!j.source){j.source={status:'lỗi',detail:j.error,ledger:''};j.projects=last?last.projects:[];j.untracked=last?last.untracked:{}}
    last=j;lastOk=Date.now();lostSince=null;var s=j.source||{};
    if(s.status!=='ok'){conn('src','NGUỒN '+(s.status||'?')+': '+(s.detail||''))}else{conn('ok','kết nối OK · dữ liệu lúc '+new Date(j.generated_at).toLocaleTimeString()+' · seq '+s.last_seq+' · đọc '+(j.server&&j.server.read_ms)+' ms')}
    $('#src').textContent='Sổ: '+(s.ledger||'')+' · poll '+(INTERVAL/1000)+' s · wheel '+(j.server&&j.server.version||'?');render();if(selected)loadDetail('poll');
  }).catch(function(e){if(!lostSince){lostSince=new Date();repaintGantt()}conn('bad','MẤT KẾT NỐI với server theo dõi từ '+lostSince.toLocaleTimeString()+(lastOk?' — đang hiện dữ liệu cũ lúc '+new Date(lastOk).toLocaleTimeString():' — chưa có dữ liệu')+'; worker không bị ảnh hưởng; trang tự thử lại')})
  .then(function(){setTimeout(poll,INTERVAL)})}
function copyText(text,k){copied={k:k,text:text,ok:false};var s=snapshot(),sel0=selected;           // the reader's focus at click time, restored after the re-render
  function done(){var d=mine();if(!d||!sameSel(selected,sel0))return;renderDetail(d);restore(s)}
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(text).then(function(){copied.ok=true;done()},function(){copied.ok=fallback();done()})}else{copied.ok=fallback();done()}
  function fallback(){var was=document.activeElement,ta=document.createElement('textarea'),ok=false;ta.value=text;ta.setAttribute('readonly','');ta.style.position='fixed';ta.style.left='-1000px';document.body.appendChild(ta);ta.select();try{ok=document.execCommand('copy')===true}catch(e){ok=false}document.body.removeChild(ta);if(was&&was.focus)was.focus({preventScroll:true});return ok}}
function openEvidence(key,btn){var d0=mine(),sel0=selected;if(!d0)return;if(evState[key]){delete evState[key];var s=snapshot();renderDetail(d0);restore(s);return}
  function show(text){var d=mine();if(!d||!sameSel(selected,sel0))return;evState[key]={text:text};var s=snapshot();renderDetail(d);restore(s)}   // a late blob of a task no longer selected is dropped
  btn.textContent='đang tải…';fetch(evHref(key).replace('&format=text',''),{cache:'no-store'}).then(function(r){return r.json().then(function(j){return [r.ok,j]})}).then(function(x){
    show(x[0]?x[1].text:'không mở được: '+(x[1].error||''))}).catch(function(){show('không mở được (mất kết nối)')})}
document.addEventListener('click',function(ev){var t=ev.target;
  var li=t.closest&&t.closest('li.task');if(li){select({plan:li.dataset.plan,project:li.dataset.project});return}
  if(t.id==='back'||t.id==='close'){var k=selected;select(null);var again=k&&document.querySelector('[data-k="task:'+k.project+':'+k.plan+'"]');if(again)again.focus();return}
  if(t.classList&&t.classList.contains('copy')){copyText(t.getAttribute('data-copy'),t.closest('.need').getAttribute('data-k'));return}
  if(t.classList&&t.classList.contains('chip')){$('#kind').value=t.getAttribute('data-kind');render(true);return}
  if(t.classList&&t.classList.contains('stale-hide')){var key=t.getAttribute('data-key');staleNotes=staleNotes.filter(function(x){return x.key!==key});var d0=mine();if(d0){var s0=snapshot();renderDetail(d0);restore(s0)}return}
  if(t.classList&&t.classList.contains('tg')){var fk=t.getAttribute('data-fold');if(fk.indexOf('h:')===0)gFold[fk]=gFold[fk]===false?true:false;else gFold[fk]=!gFold[fk];repaintGantt();var b=document.querySelector('[data-fold="'+fk+'"]');if(b)b.focus({preventScroll:true});return}
  var step=t.closest&&t.closest('.seg,.mk');if(step){var sid=step.getAttribute('data-k');selStep=(selStep&&selStep.id===sid)?null:{id:sid};repaintGantt();var again3=document.querySelector('[data-k="'+sid+'"]');if(again3)again3.focus({preventScroll:true});return}
  if(t.classList&&t.classList.contains('ev-open')){openEvidence(t.getAttribute('data-key'),t);return}
  var e=t.closest&&t.closest('ol.ev > li');if(e&&!(t.closest('.evbox'))){var seq=parseInt(e.dataset.seq,10),d1=mine();if(!d1)return;selEv=(selEv===seq)?null:seq;var s=snapshot();renderDetail(d1);restore(s);var again2=document.querySelector('[data-k="ev:'+seq+'"]');if(again2)again2.focus({preventScroll:true})}
});
document.addEventListener('keydown',function(ev){var t=ev.target;
  if(t.classList&&t.classList.contains('task')){var items=Array.prototype.slice.call(document.querySelectorAll('li.task')),i=items.indexOf(t);
    if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();select({plan:t.dataset.plan,project:t.dataset.project},{focusDetail:true})}
    else if(ev.key==='ArrowDown'&&items[i+1]){ev.preventDefault();items[i+1].focus()}else if(ev.key==='ArrowUp'&&items[i-1]){ev.preventDefault();items[i-1].focus()}
    else if(ev.key==='Home'&&items.length){ev.preventDefault();items[0].focus()}else if(ev.key==='End'&&items.length){ev.preventDefault();items[items.length-1].focus()}return}
  if(t.closest&&t.closest('ol.ev > li')&&(ev.key==='Enter'||ev.key===' ')&&!(t.tagName==='BUTTON'||t.tagName==='A')){ev.preventDefault();t.closest('ol.ev > li').click();return}
  if(t.classList&&(t.classList.contains('seg')||t.classList.contains('mk'))&&(ev.key==='Enter'||ev.key===' ')){ev.preventDefault();t.click();return}
  if(ev.key==='Escape'&&selected&&t.closest&&t.closest('#detailpane')){ev.preventDefault();var k=selected;select(null);var again=document.querySelector('[data-k="task:'+k.project+':'+k.plan+'"]');if(again)again.focus()}
});
document.addEventListener('change',function(ev){if(ev.target&&ev.target.id==='grange'){gRange=ev.target.value;repaintGantt()}});
document.addEventListener('toggle',function(ev){if(ev.target&&ev.target.classList&&ev.target.classList.contains('need'))needs_open_sync()},true);
$('#q').addEventListener('input',function(){render(true)});$('#kind').addEventListener('change',function(){render(true)});
$('#proj').addEventListener('change',function(){var v=$('#proj').value;if(selected&&v&&selected.project){var t=tasks().filter(function(x){return x.project===v&&x.project_id===selected.project});if(!t.length){select(null);$('#detail').innerHTML='<div id="nodetail">Đã đổi sang project '+esc(short(v))+': chọn một task của project này.</div>'}}render(true)});
window.addEventListener('popstate',function(){var qs=new URLSearchParams(location.search);if(qs.get('plan'))select({plan:qs.get('plan'),project:qs.get('project_id')||''},{silent:true});else select(null,{silent:true})});
window.matchMedia('(max-width:899px)').addEventListener('change',setView);
setInterval(tick,1000);
var qs=new URLSearchParams(location.search);if(qs.get('plan'))select({plan:qs.get('plan'),project:qs.get('project_id')||''},{silent:true});
poll();
window.__track={state:function(){return {selected:selected,detailSeq:detailSeq,selEv:selEv,evOpen:Object.keys(evState),copied:copied,lastOk:lastOk,lost:!!lostSince,selStep:selStep,gRange:gRange,stale:staleNotes.map(function(x){return x.id}),axisNow:mine()&&mine().gantt&&mine().gantt.axis?mine().gantt.axis.now:null,
  detailFor:mine()?{plan:detailFor.plan,project:detailFor.project}:null,detailState:detailState(),detailError:detailError?{since:iso(detailError.since),last:iso(detailError.last),message:detailError.message}:null,detailOkAt:iso(detailOkAt)}}};   // read-only inspection for tests; no control
})();
</script></body></html>
'''
