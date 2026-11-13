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

Detail reads (P2 of Codex's review of dev12): one read at a time for the selected task. A poll, or the same task selected again, waits for the
read in flight instead of replacing it (dev12 replaced a read older than 20 s, so answers slower than that were thrown away on every poll and
the pane said "đang tải" for ever). Each read is awaited up to DETAIL_TIMEOUT (45 s; the loading line counts the seconds); then it is
cancelled and the failure says so; after DETAIL_TRIES (3) timeouts with no answer shown in between, the page stops reading by itself and
offers a "Thử lại" button. Only an answer the page shows ends a series; a click on a task (the same one too), the button or a reconnection of
the overview starts a new one. Quick failures (network, HTTP) neither count nor end a series and are retried after the next overview poll as
before. While a retry is in flight the status line and the header say "đang thử lại" with the seconds waited. Selecting another task or
closing the selection cancels the read in flight (a new selection never inherits a nearly expired read). The overview read is awaited up to
OVERVIEW_TIMEOUT (5 minutes): a slow overview keeps working as before, one that never answers turns the badge to "MẤT KẾT NỐI" instead of
leaving it green while nothing updates.

Evidence on the page (R1): the page never maps a blob key to one entry. An event in the log lists the occurrences of THAT event (seq, key); the
step pane lists the occurrences of that attempt (outputs, other evidence) and, apart, what it inherits with the source occurrence of each key;
a mark shows that event's occurrences; the evidence list groups the uses of each blob. `evidence_index` comes from the full history, so an
event older than the loaded log window keeps its evidence, and the log says how many older events are not loaded. Every row (current or old)
shows what it inherits, read from the history (review round 2). Only a blob in the store is counted and opened; an identifier is not
evidence, and an output whose blob is gone stays listed as such without an open button; the door answers 404 for both.
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


def root_id(state_root):
    """The identity of a state root on the wire (R5 round 5): sha256 of its normcase'd resolved path. /api/health passes the R3 outbound guard,
    which masks a path that looks like it holds a secret ('token=1', 'Visual Basic Projects'), and two masked paths can be the same text; this
    fingerprint is exact, reveals nothing and is left as it is by the guard (plain hex)."""
    import hashlib
    return hashlib.sha256(os.path.normcase(str(Path(state_root).resolve())).encode('utf-8')).hexdigest()
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
    identity = {'instance': instance or secrets.token_hex(8), 'version': version(), 'state_root': str(state_root), 'state_root_id': root_id(state_root),
                'project_id': project_id, 'pid': os.getpid()}
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
            # the request body is read first (up to 8 MiB): on Windows a socket closed with unread data is reset, and the client then sees
            # WinError 10053 instead of this 405; a larger body is not read and the connection is closed after the answer
            try:
                length = max(int(self.headers.get('Content-Length') or 0), 0)
            except ValueError:
                length = 0
            left = min(length, 1 << 23)
            while left > 0:
                chunk = self.rfile.read(min(left, 65536))
                if not chunk: break
                left -= len(chunk)
            if length > (1 << 23) or left > 0: self.close_connection = True
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
                        head = (f"# {'ảnh chụp' if value.get('kind') == 'manifest' else 'blob'} {value['key']} ({value['bytes']} bytes"
                                + (f", {value.get('files')} tệp" if value.get('kind') == 'manifest' else '') + f"{', cắt' if value['truncated'] else ''}); lọc bí mật: {value['redaction']['rule']}\n\n")
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
              'state_root': str(Path(state_root).resolve()), 'state_root_id': server.track_identity['state_root_id'], 'project_id': project_id, 'poll_seconds': interval,
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
    """The /api/health record of whatever answers at `url`, or None. Asked directly, never through a proxy (R5 round 5): urllib's default opener
    sends 127.0.0.1 to HTTP(S)_PROXY / a manual system proxy, which would hide every local viewer from open, status and stop."""
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url + 'api/health', timeout=timeout) as r:
            value = json.loads(r.read().decode('utf-8'))
            return value if isinstance(value, dict) and value.get('ok') is True else None
    except (OSError, ValueError):
        return None


def _same_root(health, state_root):
    """Does the server that sent `health` read `state_root`? By the fingerprint `state_root_id` (root_id) when it sends one: its `state_root`
    passed the R3 outbound guard, so a path that looks like a secret arrives masked, and masked paths can be equal for two ledgers (R5 round 5).
    A server without the fingerprint (an older wheel) is compared by its path, as before."""
    if health.get('state_root_id'): return health.get('state_root_id') == root_id(state_root)
    return os.path.normcase(str(health.get('state_root') or '')) == os.path.normcase(str(Path(state_root).resolve()))


def reusable(record, health, state_root, project_id, here=None):
    """(ok, reason): may `track open` reuse the server the marker `record` names, given what its URL answered (`health`)? Only when the server
    is the very one the marker was written for (instance), runs the same wheel, reads the same state root and has the same project scope."""
    here = here or version()
    if not record: return False, 'không có marker'
    if not record.get('instance'): return False, 'marker không có định danh (server của wheel cũ): không dùng lại'
    if not health: return False, 'server trong marker không trả lời'
    if health.get('instance') != record['instance']: return False, 'định danh khác: cổng trong marker đang do tiến trình khác trả lời; không dùng lại, không dừng tiến trình đó'
    if health.get('version') != here: return False, f"version khác: server chạy {health.get('version')}, lệnh này là {here}"
    if not _same_root(health, state_root): return False, 'state-root khác'
    if (health.get('project_id') or None) != (project_id or None): return False, 'phạm vi project khác'
    if health.get('pid') != record.get('pid'): return False, 'PID khác với marker'
    return True, None


# ---- process identity (R5 round 4, 03/11) -----------------------------------------------------------------------------------------------------
# A pid alone is not an identity: Windows reuses pids. Every decision below holds the process by HANDLE first (no other process can get that pid
# while a handle to it is open), tells a recycled pid from the server by creation time (a server writes its own `started_at` after its process
# was created, so a process created later is another one) and terminates through that same handle. Elsewhere the pid is used as is (os.kill)
# and a creation time is unknown.
_LOOPBACK_URL = re.compile(r'http://(?:127\.0\.0\.1|localhost|\[::1\]):[0-9]{1,5}/')
_INSTANCE = re.compile(r'[0-9a-f]{8,64}')
_K32 = None


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_time(value):
    """An ISO 8601 time with its zone (as `utcnow()` writes `started_at`) as an aware datetime; None for anything else."""
    import datetime as _dt
    if not isinstance(value, str) or not value.strip(): return None
    try:
        when = _dt.datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    return when if when.tzinfo else None


def _k32():
    """kernel32 with the signatures used here, and the PROCESSENTRY32W structure (Windows only)."""
    global _K32
    if _K32 is None:
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL('kernel32', use_last_error=True)

        class Entry(ctypes.Structure):
            _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_void_p),
                        ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD), ('th32ParentProcessID', wintypes.DWORD),
                        ('pcPriClassBase', wintypes.LONG), ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR * 260)]
        for name, res, args in (('OpenProcess', wintypes.HANDLE, (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)),
                                ('GetProcessTimes', wintypes.BOOL, (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4),
                                ('TerminateProcess', wintypes.BOOL, (wintypes.HANDLE, wintypes.UINT)),
                                ('WaitForSingleObject', wintypes.DWORD, (wintypes.HANDLE, wintypes.DWORD)),
                                ('CloseHandle', wintypes.BOOL, (wintypes.HANDLE,)),
                                ('CreateToolhelp32Snapshot', wintypes.HANDLE, (wintypes.DWORD, wintypes.DWORD)),
                                ('Process32FirstW', wintypes.BOOL, (wintypes.HANDLE, ctypes.POINTER(Entry))),
                                ('Process32NextW', wintypes.BOOL, (wintypes.HANDLE, ctypes.POINTER(Entry)))):
            fn = getattr(k, name); fn.restype = res; fn.argtypes = args
        _K32 = (k, Entry)
    return _K32


class _Proc:
    """One process, held. On Windows by a HANDLE opened before any check, so its pid cannot pass to another process while we decide."""
    QUERY, SYNC, TERMINATE = 0x1000, 0x00100000, 0x0001          # PROCESS_QUERY_LIMITED_INFORMATION, SYNCHRONIZE, PROCESS_TERMINATE

    def __init__(self, pid, handle=None, can_terminate=True):
        self.pid, self.handle, self.can_terminate = pid, handle, can_terminate

    @classmethod
    def open(cls, pid):
        """The process that has `pid` now, held; None when no process has it (or one we may not even query: never a server of ours)."""
        pid = _int(pid)
        if not pid or pid <= 0: return None
        if os.name != 'nt':
            try:
                os.kill(pid, 0)
            except OSError:
                return None
            return cls(pid)
        k = _k32()[0]
        handle = k.OpenProcess(cls.QUERY | cls.SYNC | cls.TERMINATE, False, pid)
        if handle: return cls(pid, handle)
        handle = k.OpenProcess(cls.QUERY | cls.SYNC, False, pid)            # e.g. an elevated server seen from a normal shell: identified, not stoppable
        return cls(pid, handle, can_terminate=False) if handle else None

    def alive(self):
        if os.name != 'nt':
            try:
                os.kill(self.pid, 0); return True
            except OSError:
                return False
        return bool(self.handle) and _k32()[0].WaitForSingleObject(self.handle, 0) == 0x102     # WAIT_TIMEOUT: still running

    def created(self):
        """When the process was created (aware UTC datetime); None where unknown."""
        if os.name != 'nt' or not self.handle: return None
        import ctypes
        import datetime as _dt
        from ctypes import wintypes
        times = [wintypes.FILETIME() for _ in range(4)]
        if not _k32()[0].GetProcessTimes(self.handle, *(ctypes.byref(t) for t in times)): return None
        ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        return _dt.datetime(1601, 1, 1, tzinfo=_dt.timezone.utc) + _dt.timedelta(microseconds=ticks // 10)

    def terminate(self):
        if os.name != 'nt':
            try:
                os.kill(self.pid, signal.SIGTERM); return True
            except OSError:
                return False
        return bool(self.handle and self.can_terminate and _k32()[0].TerminateProcess(self.handle, 15))

    def wait(self, seconds):
        """True once the process has exited (waiting at most `seconds`)."""
        if os.name != 'nt':
            end = time.monotonic() + seconds
            while self.alive() and time.monotonic() < end: time.sleep(0.1)
            return not self.alive()
        return bool(self.handle) and _k32()[0].WaitForSingleObject(self.handle, int(max(0.0, seconds) * 1000)) == 0

    def close(self):
        if os.name == 'nt' and self.handle:
            _k32()[0].CloseHandle(self.handle)
        self.handle = None


def _same_process(proc, since):
    """True: `proc` runs and was created no later than `since` (the start stamp a server wrote itself), so it IS that server's process.
    False: it does not run, could not be held (no such pid), or is a newer process that got the pid. None: cannot tell (no stamp/creation time)."""
    if proc is None or not proc.alive(): return False
    if since is None: return None
    created = proc.created()
    if created is None: return None
    return created <= since


def _answer(url, proc=None, since=None, quick=2.0, patient=(5.0, 10.0)):
    """/api/health of `url`, asked again with longer timeouts while the process that should answer is exactly still the one that wrote `since`
    (R5 round 4: a server slowed down by load is not a dead server). A pid that no longer runs needs no second try."""
    health = identity(url, timeout=quick)
    for timeout in patient:
        if health is not None or _same_process(proc, since) is not True: break
        time.sleep(0.3)
        health = identity(url, timeout=timeout)
    return health


def _descendants(root, depth=4):
    """Windows: the processes `root` created (and theirs), held. A process counts only when its recorded parent pid is the parent's AND it was
    created no earlier than that parent: a process whose recorded parent pid is a recycled number is older than the parent and is left alone."""
    if os.name != 'nt' or root is None: return []
    import ctypes
    k, Entry = _k32()
    snap = k.CreateToolhelp32Snapshot(0x2, 0)                               # TH32CS_SNAPPROCESS
    if not snap or snap == ctypes.c_void_p(-1).value: return []
    pairs = []
    try:
        entry = Entry(); entry.dwSize = ctypes.sizeof(Entry)
        more = k.Process32FirstW(snap, ctypes.byref(entry))
        while more:
            pairs.append((entry.th32ProcessID, entry.th32ParentProcessID))
            more = k.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k.CloseHandle(snap)
    found, level = [], [root]
    for _ in range(depth):
        nxt = []
        for parent in level:
            born = parent.created()
            for pid, ppid in pairs:
                if ppid != parent.pid or pid in (parent.pid, root.pid) or any(p.pid == pid for p in found + nxt): continue
                kid = _Proc.open(pid)
                if kid is None: continue
                created = kid.created()
                if born is None or created is None or created < born:
                    kid.close(); continue
                nxt.append(kid)
        found += nxt; level = nxt
        if not nxt: break
    return found


def _brief(health):
    return {k: health.get(k) for k in ('server', 'instance', 'pid', 'state_root', 'version', 'project_id')} if health else None


def _marker_now(marker):
    current = _read_marker(marker)
    return {k: current.get(k) for k in ('url', 'pid', 'instance', 'project_id', 'started_at')} if current else None


def _remove_marker_of(marker, lock, instance):
    """Remove the marker only when it names `instance` — under the open lock, so a marker another `track open` writes meanwhile is never lost.
    No marker naming it: nothing is touched (not even the lock, so a stop never creates the tracking folder)."""
    first = _read_marker(marker)
    if first is None or first.get('instance') != instance: return False
    end = time.monotonic() + 3.0
    fd = _lock(lock)
    while fd is None and time.monotonic() < end:
        time.sleep(0.1); fd = _lock(lock)
    if fd is None: return False
    try:
        current = _read_marker(marker)
        if current is None or current.get('instance') != instance: return False
        try:
            Path(marker).unlink(); return True
        except OSError:
            return False
    finally:
        _unlock(fd, lock)


def _end(proc, url, instance, wait):
    """Terminate the held process, then wait until it has exited and `url` no longer answers as `instance`. Returns (stopped, reason)."""
    if proc is None: return False, 'không giữ được tiến trình đó để dừng'
    if not proc.terminate() and proc.alive():                         # a server that exited by itself meanwhile is simply over
        return False, 'không gửi được tín hiệu dừng (tiến trình chạy với quyền khác)'
    proc.wait(wait)
    still = identity(url, timeout=0.5)
    stopped = not proc.alive() and not (still and still.get('instance') == instance)
    return stopped, None if stopped else 'server vẫn trả lời sau tín hiệu dừng'


def _abandon(child, marker, old_instance):
    """Undo a `track open` that fails after starting a server (R5 round 4): the whole tree it started ends — our own Popen and what it created
    (on Windows the venv launcher runs the real python as its child) — and the marker is removed only when that tree wrote it, or when it names a
    server whose process is gone. Runs under the open lock (no other `track open` writes the marker meanwhile)."""
    root = _Proc.open(child.pid) if child.poll() is None else None      # the same process: Popen holds its handle, its pid is not reusable
    tree = _descendants(root)
    if root: root.close()
    if child.poll() is None:
        try:
            child.kill()
        except OSError:
            pass
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    ended, running = ([child.pid], []) if child.poll() is not None else ([], [child.pid])
    for proc in tree:                                    # the venv launcher's job usually ends them with it; made sure through the handles taken before
        if proc.alive(): proc.terminate()
        (ended if proc.wait(10) else running).append(proc.pid)
        proc.close()
    record, removed = _read_marker(marker), False
    if record and record.get('instance') != old_instance and record.get('pid') not in running:
        held = _Proc.open(record.get('pid')) if record.get('pid') not in ended else None
        try:
            gone = record.get('pid') in ended or _same_process(held, _parse_time(record.get('started_at'))) is False
        finally:
            if held: held.close()
        if gone:
            try:
                marker.unlink(); removed = True
            except OSError:
                pass
    return {'ended': ended, 'still_running': running, 'marker_removed': removed}


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
              browser=True, spawn=True, wait=30.0):
    """Reuse the live detached server of this state root when its identity matches (see `reusable`), else start one; then open the page.
    `spawn=False` only reports (no server is started). Concurrent calls serialise on the open lock.
    R5 round 4: the marker's server is asked again with longer timeouts while its process is exactly still running (a slow server is reused,
    not replaced); a started server has `wait` seconds (30: a loaded machine needs 4-10 s) to answer with its identity; and a failed open never
    leaves a server running — on a timeout, an early exit or an error the tree it started is ended and a marker that tree wrote is removed.
    R5 round 5: under the lock the marker is read again (a concurrent open may have handed over a reusable server meanwhile: reuse it) and only
    the marker that failed is removed; the child gets absolute paths; a failure note says which pids could not be ended, if any."""
    state_root = Path(state_root).resolve()
    marker, lock = marker_paths(state_root)
    here = version()

    def check(patient=False):
        record = _read_marker(marker)
        health = None
        if record and patient:
            proc = _Proc.open(record.get('pid'))
            try:
                health = _answer(record['url'], proc, _parse_time(record.get('started_at')))
            finally:
                if proc: proc.close()
        elif record:
            health = identity(record['url'])
        ok, why = reusable(record, health, state_root, project_id, here)
        return record, health, ok, why

    def opened(record, reused, **more):
        if browser:
            import webbrowser; webbrowser.open(record['url'])
        return dict(record, reused=reused, version_here=here, **more)

    record, health, ok, why = check(patient=True)
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
        current = _read_marker(marker)               # R5 round 5: the marker may have changed between the check above and this lock (another open finished)
        if (current or {}).get('instance') != (record or {}).get('instance') or (current is None) != (record is None):
            record, health, ok, why = check(patient=True)
            if ok: return opened(record, True, waited_for_other_open=True)
            refused = {'marker': record, 'reason': why}
        if not spawn:
            return {'error': 'không có server dùng lại được', 'refused': refused, 'version_here': here}
        old_instance = (record or {}).get('instance')
        current = _read_marker(marker)               # the lock is held: only a server can write it now; remove exactly the marker that failed `reusable`
        if (current is None and marker.exists()) or (current is not None and record is not None and current.get('instance') == old_instance):
            try: marker.unlink()
            except OSError: pass
        # R5 round 5: the child runs with cwd=TEMP, so it gets absolute paths (a relative --state-root/--project would name a folder under TEMP);
        # it always serves the state root resolved here, which the marker, the lock and the identity checks of this call are computed from
        args = [sys.executable, '-X', 'utf8', '-m', 'onecrew.v2.tracking_cli', '--project', str(Path(project).resolve() if project else Path.cwd().resolve())]
        args += ['--state-root', str(state_root)]
        args += ['track', 'serve', '--host', host, '--port', str(port), '--interval', str(interval), '--announce', str(marker)]
        if project_id: args.append('--project-only')
        flags = (subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, 'DETACHED_PROCESS', 0)) if os.name == 'nt' else 0
        env = dict(os.environ, ONECREW_TRACK_IDLE_EXIT=str(idle_exit), PYTHONSAFEPATH='1')     # `-m` must not pick a stray `onecrew` from the caller's cwd
        import tempfile
        child = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, creationflags=flags, env=env,
                                 cwd=tempfile.gettempdir())
        try:
            end = time.monotonic() + wait
            while True:
                record, health, ok, why = check()
                if record and record.get('instance') and record['instance'] != old_instance and ok:
                    return opened(record, False, idle_exit_seconds=idle_exit, refused=refused if refused['marker'] else None)
                if child.poll() is not None:
                    failure = {'error': 'server theo dõi thoát ngay khi khởi động', 'exit_code': child.returncode, 'refused': refused}
                    break
                if time.monotonic() >= end:
                    failure = {'error': f'server theo dõi không trả lời đúng định danh trong {wait:g} giây', 'pid': child.pid, 'last_reason': why, 'refused': refused}
                    break
                time.sleep(0.1)
        except BaseException:
            _abandon(child, marker, old_instance)
            raise
        undone = failure['undone'] = _abandon(child, marker, old_instance)
        if undone['still_running']:                  # R5 round 5: say what is really left, never "nothing left" when the tree could not be ended
            failure['note'] = ('track open thất bại và KHÔNG dừng được tiến trình nó vừa khởi động: pid ' + ', '.join(str(p) for p in undone['still_running'])
                               + ' vẫn chạy; marker do nó ghi (nếu có) được giữ để `track stop` (hoặc `track stop --url --instance --pid`) tìm thấy nó')
        else:
            failure['note'] = 'track open thất bại không để lại server nào: cây tiến trình nó vừa khởi động đã dừng; marker do cây đó ghi (nếu có) đã xóa'
        return failure
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
                and _same_root(health, state_root)
                and (not record.get('instance') or health.get('instance') == record['instance']))


def stop_page(state_root, wait=10.0):
    """Stop the detached tracking server of this state root — only the process whose /api/health matches the marker. Never another process.
    A marker whose URL answers with another identity, or does not answer while its process is gone, is removed as stale (a file of ours;
    nothing is killed). R5 round 4: a server that does not answer while its process exactly still runs (the marker's pid, created before the
    marker's `started_at`) is slow, not dead — nothing is stopped and its marker is kept; the process is held by handle from before the check
    to the termination, so its pid cannot pass to another process in between."""
    state_root = Path(state_root).resolve()
    marker, lock = marker_paths(state_root)
    record = _read_marker(marker)
    if not record:
        return {'stopped': False, 'reason': 'không có marker: không có server nào được `track open` mở cho sổ này (server của `track serve` dừng bằng Ctrl+C)'}
    proc = _Proc.open(record.get('pid'))
    try:
        since = _parse_time(record.get('started_at'))
        health = _answer(record['url'], proc, since)
        if not _same_server(record, health, state_root):
            if health is None and _same_process(proc, since) is True:
                return {'stopped': False, 'reason': 'server trong marker không trả lời /api/health (đã hỏi lại lâu hơn) nhưng tiến trình của nó vẫn chạy: '
                                                    'không dừng gì, giữ marker; thử lại sau', 'marker_removed': False, 'marker': record, 'health': None}
            removed = _remove_marker_of(marker, lock, record.get('instance'))
            why = 'server trong marker không trả lời' if not health else 'tiến trình trả lời ở cổng đó không phải server của marker này (định danh/PID/sổ khác): không dừng tiến trình lạ'
            return {'stopped': False, 'reason': why, 'marker_removed': removed, 'marker': record, 'health': health}
        stopped, why = _end(proc, record['url'], record.get('instance'), wait)
        if stopped: _remove_marker_of(marker, lock, record.get('instance'))
        return {'stopped': stopped, 'pid': record['pid'], 'url': record['url'], 'instance': record.get('instance'), 'version': record.get('version'),
                'note': 'chỉ trang theo dõi dừng; worker không bị ảnh hưởng' if stopped else why}
    finally:
        if proc: proc.close()


def _is_target(health, state_root, instance, pid):
    if not health: return False, 'không có server nào trả lời /api/health ở url đó (đã hỏi lại lâu hơn khi tiến trình còn chạy)'
    if not str(health.get('server', '')).startswith('OneCrewTrack/'): return False, 'url đó không phải server theo dõi OneCrew'
    if not _same_root(health, state_root): return False, 'server ở url đó đọc sổ khác, không phải sổ này'
    if health.get('instance') != instance: return False, f"định danh khác: url đó do server instance {health.get('instance')} trả lời"
    if health.get('pid') != pid: return False, f"PID khác: server ở url đó báo pid {health.get('pid')}"
    return True, None


def stop_target(state_root, url, instance, pid, started_at=None, wait=10.0):
    """`track stop --url U --instance I --pid P [--started-at T]` (R5 round 4): stop exactly the tracking server that answers at U as instance I
    with pid P for THIS state root, even when the marker of the state root names another server; nothing else. P is held (Windows: by handle)
    BEFORE /api/health is asked, so the pid cannot pass to another process between the check and the stop. U must answer as a OneCrewTrack
    server of this state root with instance I and pid P (asked again with longer timeouts while P is exactly still the process that started at
    T); then P is terminated and U must stop answering as I. The marker is removed only when it names I. Anything else stops nothing and says
    why. `gone` (for a caller holding a pin): True = that server is certainly over (P no longer runs, or now belongs to a process created after
    T), False = its process still runs, None = cannot tell (P runs and no T is known: neither --started-at nor a marker naming I)."""
    state_root = Path(state_root).resolve()
    marker, lock = marker_paths(state_root)
    target = {'url': url, 'instance': instance, 'pid': pid}

    def refuse(reason, **more):
        return dict({'stopped': False, 'reason': reason, **target, 'gone': None, 'marker_removed': False}, **more)

    if not isinstance(url, str) or not _LOOPBACK_URL.fullmatch(url):
        return refuse('--url phải là http://127.0.0.1:<cổng>/ (hoặc localhost, [::1]) của một server theo dõi: không dừng gì')
    if not isinstance(instance, str) or not _INSTANCE.fullmatch(instance):
        return refuse('--instance phải là định danh hex (8-64 ký tự) mà server báo ở /api/health: không dừng gì')
    pid = _int(pid)
    if not pid or pid <= 0:
        return refuse('--pid phải là số dương: không dừng gì')
    target['pid'] = pid
    since = _parse_time(started_at) if started_at else None
    if started_at and since is None:
        return refuse('--started-at phải là thời điểm ISO 8601 có múi giờ (started_at mà server tự ghi): không dừng gì')
    record = _read_marker(marker)
    if since is None and record and record.get('instance') == instance and record.get('pid') == pid:
        since = _parse_time(record.get('started_at'))
    proc = _Proc.open(pid)
    try:
        health = _answer(url, proc, since)
        ok, why = _is_target(health, state_root, instance, pid)
        if not ok:
            same = _same_process(proc, since)
            gone = None if same is None else not same
            removed = bool(gone and record and record.get('instance') == instance and _remove_marker_of(marker, lock, instance))
            return refuse(why + ': không dừng gì', gone=gone, marker_removed=removed, health=_brief(health), marker_now=_marker_now(marker))
        created, reported = (proc.created() if proc else None), _parse_time(health.get('started_at'))
        if proc is None or (created and reported and created > reported):
            return refuse('tiến trình đang mang PID đó không phải server vừa trả lời ở url (không mở được, hoặc tạo sau khi server đó khởi động): không dừng gì',
                          marker_now=_marker_now(marker))
        stopped, why = _end(proc, url, instance, wait)
        removed = bool(stopped and _remove_marker_of(marker, lock, instance))
        return {'stopped': stopped, 'gone': True if stopped else None, **target, 'version': health.get('version'), 'project_id': health.get('project_id'),
                'marker_removed': removed, 'marker_now': _marker_now(marker), 'reason': why,
                'note': 'chỉ đúng server theo dõi này dừng; worker không bị ảnh hưởng' if stopped else why}
    finally:
        if proc: proc.close()


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
ul.uses{margin:2px 0 6px 14px;padding:0}ul.uses li{margin:1px 0}
.stale{opacity:.7}.evbox{margin:4px 0 4px 10px;padding:6px 8px;border-left:3px solid var(--line);font-size:13px}.evbox pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:40vh;overflow:auto;background:rgba(120,140,180,.08);padding:6px;border-radius:6px;font-size:12px;margin:4px 0 0}
details{margin:6px 0}summary{cursor:pointer;color:var(--mut)}summary:focus-visible{outline:3px solid var(--focus)}
.dhead{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.dhead h2{margin:0;text-transform:none;letter-spacing:0;font-size:16px;color:var(--fg)}
#back{display:none}#empty,#nodetail{padding:8px;color:var(--mut)}.err{color:var(--blk)}.note .brief{display:none}
@media (min-width:900px){main[data-view=detail]{grid-template-columns:minmax(220px,1fr) minmax(420px,3.4fr)}main[data-view=detail] .task .r3{display:none}main[data-view=detail] .task{padding:6px 8px}}
@media (max-width:899px){main{display:block}main[data-view=list] #detailpane{display:none}main[data-view=detail] #listpane{display:none}#detailpane{position:static;max-height:none}#back{display:inline-block}
  .ttl{white-space:normal}.r3{white-space:normal}header{padding:6px 12px}main{padding:8px 12px}.note .long,#src{display:none}.note .brief{display:inline}.tools label span{display:none}
  .gbody{grid-template-columns:150px minmax(380px,1fr);min-width:540px}.gtree .grow{font-size:12px}.gaxis span.t1,.gaxis span.t3{display:none}}
@@WORK_STYLE@@

.gantt{padding:16px;gap:16px}.gantt:not(.has-selection){grid-template-columns:minmax(0,1fr)}.gside[hidden]{display:none}
.gintro b{font-size:17px}.gintro p{font-size:15px;margin:5px 0}.gintro>span,.ganchor,.gexplain{font-size:12px;color:var(--mut)}.ganchor{margin:7px 0 10px}.gexplain{line-height:1.5;margin:8px 0}
.gtop{font-size:13px;margin-top:12px}.legend{font-size:12px;margin:10px 0}.gbody{grid-template-columns:280px minmax(0,1fr)}
.gaxis{height:32px;font-size:12px}.gaxis span{top:6px}.gtree .gh0{height:32px;font-size:12px;padding:7px}
.grow{height:60px}.grow.nodehead{height:110px}.gtree .grow{white-space:normal;font-size:13px;padding:8px;overflow:hidden}.gtree .nodehead{display:flex;align-items:flex-start;gap:6px}
.gnselect{border:0;background:none;color:var(--fg);padding:0;text-align:left;flex:1;min-width:0;line-height:1.4}.gnselect strong{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-size:14px}.gnselect span,.gnselect small{display:block;font-size:12px;margin-top:4px;color:var(--mut)}.gnselect[aria-pressed=true]{color:var(--run)}.gtree .tg{min-width:24px;min-height:28px}
.grow.att small{display:block;font-size:11px;color:var(--mut)}.grow.hist,.grow.planrow{height:38px}.gchart .grow{background:none}.ggrid{position:absolute;top:0;bottom:0;border-left:1px solid var(--line);pointer-events:none}.goutput{padding:8px 0;border-bottom:1px solid var(--line)}.goutput>b{display:block;margin-bottom:5px}.gside>details{margin-top:12px}
.seg{top:28px;height:16px;min-width:3px}.seg:after{content:'';position:absolute;inset:-6px -3px}.seg.wait{top:49px;height:7px}.seg.verification{top:10px;height:7px}.nodehead .seg{top:48px}.nodehead .seg.wait{top:70px}.nodehead .seg.verification{top:28px}.nodehead .mk{top:8px}.gside{font-size:14px;padding:14px}.gside h4{font-size:16px}
@media(max-width:1100px){.gbody{grid-template-columns:240px minmax(0,1fr)}.gantt.has-selection{grid-template-columns:minmax(0,1fr)}}
@media(max-width:600px){.gantt{padding:10px}.gbody{grid-template-columns:190px minmax(300px,1fr);min-width:510px}.gaxis span{display:block!important}.gnselect strong{font-size:13px}.grow.nodehead{height:120px}}

</style></head><body>
<header>
<div class="bar"><h1>OneCrew · Công việc</h1><span id="health" role="status" class="small"></span><span id="dconn" role="status" hidden></span><span id="count" class="small mut"></span></div>
<div class="tools">
<label class="search"><input id="q" type="search" placeholder="Tìm công việc…" aria-label="Tìm theo tên việc, mục tiêu, bước"></label>
<div id="viewsw" role="group" aria-label="Cách xem danh sách"><button type="button" data-list-mode="list" aria-pressed="true">Danh sách</button><button type="button" data-list-mode="board" aria-pressed="false">Bảng</button></div>
<details id="filters" data-k="filters"><summary>Bộ lọc <span id="fcount" class="small mut"></span></summary><div class="fbody">
<label>Dự án <select id="proj"><option value="">tất cả</option></select></label>
<label>Trạng thái <select id="kind"><option value="">tất cả</option><option value="need">Cần bạn quyết định</option><option value="running">Đang có lượt chạy</option><option value="todo">Chưa bắt đầu</option><option value="doing">Đang thực hiện</option><option value="fix">Cần sửa</option><option value="check">Chờ kiểm</option><option value="accept">Chờ nghiệm thu</option><option value="done">Hoàn tất</option><option value="stopped">Đã dừng</option><option value="unknown">Chưa xác định</option><option value="closed">Đã đóng</option></select></label>
<label>Sắp xếp <select id="sort"><option value="attention">Cần xử lý trước</option><option value="updated">Cập nhật gần nhất</option><option value="created">Ngày tạo (cũ trước)</option><option value="deadline">Hạn hoàn thành (nếu có)</option></select></label>
</div></details>
<span id="chips" role="group" aria-label="lọc nhanh"></span>
</div>
<div id="factive" role="status" hidden></div>
<div id="sample" class="sample-banner" hidden>Các thẻ đang xem có nhãn “dữ liệu thử” trong tên. Kiểm tra đúng dự án và sổ trước khi chạy lệnh.</div>
<details class="connection-details"><summary>Thông tin kết nối và giới hạn</summary><span id="conn">đang kết nối…</span><p class="note small mut"><span class="long">Chỉ đọc: không có nút duyệt, trả lời, dừng hay tiếp tục task; mở bằng chứng không phải là duyệt. Kết nối "OK" chỉ nói trang đang nhận dữ liệu, không nói việc đã xong. </span><span class="brief">Chỉ đọc; "kết nối OK" không có nghĩa việc đã xong. </span><span id="src"></span></p></details>
</header>
<main id="main" data-view="list">
<section class="pane" id="listpane" aria-label="Danh sách công việc"><h2>Công việc</h2><p class="stage-note" id="stagenote">Mỗi dòng là một công việc: trạng thái, bước tiếp theo, kết quả và hoạt động cuối. Trạng thái do sổ tính; trang chỉ xem, không kéo thả hay đổi trạng thái.</p><div id="empty">Đang đọc sổ…</div>
<div id="list" role="group" aria-label="Bảng công việc"></div>
<details id="untrackedbox" data-k="untracked"><summary>Chưa được theo dõi</summary><div id="untracked" class="small"></div></details></section>
<section class="pane" id="detailpane" aria-label="Chi tiết task"><div id="detail"><div id="nodetail">Chọn một task ở danh sách để xem chi tiết, timeline và bằng chứng.</div></div></section>
</main>
<script>
(function(){
var INTERVAL=@@INTERVAL@@, last=null, lastOk=null, lostSince=null, selected=null, lastViewed=null, detailData=null, detailSeq=null, detailToken=0, detailInflight=null, listSig=null, selEv=null, evState={}, copied=null;
var selStep=null, gRange='current', gPinnedWindow=null, gFold={}, staleNotes=[], knownNeeds={};
var detailFor=null, detailError=null, detailOkAt=null;   // R4: the selection detailData was fetched for; the current failure streak {since,last,message}; when it last loaded
var DETAIL_TIMEOUT=45000, DETAIL_TRIES=3, OVERVIEW_TIMEOUT=300000, detailTimeouts=0;   // P2 (Codex, dev12): a detail read is awaited up to 45 s, never replaced by a poll; after 3 timeouts with no answer shown in between the page stops retrying and offers a retry button; an overview read is awaited up to 5 minutes (a slow overview keeps working as before; one that never answers is reported)
var TECH=['attempt.','executor.managed','decision.recorded','execution.configured','budget.group','precondition.recorded','task.submitted','knowledge.delivered','estimate.','plan.step0_closed'];
var $=function(s){return document.querySelector(s)};
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function hms(s){if(typeof s!=='number')return 'chưa xác định';if(s>0&&s<1)return 'dưới 1s';s=Math.floor(s);var h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=s%60;return h?h+'h'+String(m).padStart(2,'0')+'m':m?m+'m'+String(x).padStart(2,'0')+'s':x+'s'}
var TF={hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false},DF={day:'2-digit',month:'2-digit',year:'numeric'};
function when(t){if(!t)return '—';var d=new Date(t);return isNaN(d)?esc(t):d.toLocaleTimeString('vi-VN',TF)+' '+d.toLocaleDateString('vi-VN',DF)}
function clock(t){if(!t)return '—';var d=new Date(t);return isNaN(d)?esc(t):d.toLocaleTimeString('vi-VN',TF)}
function relText(t){var d=new Date(t);if(isNaN(d))return esc(t);var s=Math.round((Date.now()-d.getTime())/1000);if(s<5)return 'vừa xong';if(s<60)return s+' giây trước';if(s<3600)return Math.floor(s/60)+' phút trước';if(s<86400)return Math.floor(s/3600)+' giờ trước';return Math.floor(s/86400)+' ngày trước'}
function rel(t){return t?'<time data-rel="'+esc(t)+'" title="'+when(t)+'">'+relText(t)+'</time>':'—'}
function tick(){document.querySelectorAll('[data-rel]').forEach(function(e){e.textContent=relText(e.getAttribute('data-rel'))});
  document.querySelectorAll('[data-live]').forEach(function(e){var s=parseFloat(e.getAttribute('data-live')),at=parseFloat(e.getAttribute('data-live-at'));if(!isNaN(s)&&!isNaN(at))e.textContent=hms(s+(Date.now()-at)/1000)})}
var GLYPH={running:'▶',waiting:'◔',blocked:'■',unknown:'?',done:'□',accepted:'✔',verified:'✓',closed:'□'};
function st(t){var g=t.outcome?GLYPH[t.outcome]:GLYPH[t.kind];return '<span class="st '+esc(t.kind)+(t.outcome?' '+esc(t.outcome):'')+'"><span class="g" aria-hidden="true">'+(g||'')+'</span>'+esc(t.label)+'</span>'}
var PHASE={pending:'chờ đến lượt',running:'đang chạy',held:'bị giữ',complete:'xong'},NSTATE={none:'chưa có đầu ra',produced:'đã tạo',verified:'đã kiểm',accepted:'đã nghiệm thu'};
function word(map,k){return '<span title="'+esc(k)+'">'+esc(map[k]||k||'—')+'</span>'}
function short(p){p=String(p||'');var parts=p.split(/[\\\/]/).filter(Boolean);return parts.length>2?'…'+parts.slice(-2).join('\\'):p}
function conn(cls,text){var c=$('#conn');c.className=cls;c.textContent=text;var h=$('#health');h.className=cls==='ok'?'small mut':'err';h.textContent=cls==='ok'?'Đang cập nhật':text}
function narrow(){return window.matchMedia('(max-width:899px)').matches}
function setView(){var v=selected?'detail':'list';$('#main').setAttribute('data-view',v);document.body.setAttribute('data-view',v)}   // 13/11: the list's search and filters step aside on the detail page (kept, not reset)
function sameSel(a,b){return !!a&&!!b&&a.plan===b.plan&&(a.project||'')===(b.project||'')}
function urlOf(sel){return sel?'?plan='+encodeURIComponent(sel.plan)+(sel.project?'&project_id='+encodeURIComponent(sel.project):''):location.pathname}
function mine(){return detailData&&sameSel(detailFor,selected)?detailData:null}   // R4: the detail data only while it belongs to the CURRENT selection
function detailState(){return !selected?'none':mine()?(detailError?'stale':'ok'):(detailError?'error':'loading')}
function taskOf(sel){return sel?tasks().find(function(t){return t.selector===sel.plan&&(!sel.project||t.project_id===sel.project)})||null:null}
function nameOf(sel){var t=taskOf(sel);return t?t.plan:String(sel.plan||'').replace(/^plan(-ns)?:/,'')}
function clockMs(ms){return ms?new Date(ms).toLocaleTimeString('vi-VN',TF):'?'}
function iso(ms){return ms?new Date(ms).toISOString():null}
function dind(){var e=$('#dconn'),k=detailState();if(k==='none'){e.hidden=true;e.className='';e.textContent='';return}   // the detail freshness, apart from the overview badge
  var n=nameOf(selected);e.hidden=false;
  if(k==='loading'){e.className='wait';e.textContent='chi tiết '+n+': đang tải…'}
  else if(k==='ok'){e.className='ok';e.textContent='chi tiết '+n+': cập nhật lúc '+clockMs(detailOkAt)}
  else{e.className='bad';e.textContent='chi tiết '+n+': lỗi tải từ '+clockMs(detailError.since)+(k==='stale'?' · đang hiện dữ liệu lúc '+clockMs(detailOkAt):' · chưa có dữ liệu')
    +(reading()?' · đang thử lại':detailTimeouts>=DETAIL_TRIES?' · đã ngừng tự thử (bấm Thử lại)':'')}}   // P2: a read in flight or the stop, also in the header
function crumbs(title,tab){return '<nav class="crumbs" aria-label="Đường dẫn"><button type="button" id="back">← Tất cả công việc</button><span class="sep" aria-hidden="true">›</span><span class="here">'+esc(title)+'</span>'+(tab?'<span class="sep" aria-hidden="true">›</span><span id="crumbtab">'+esc(tab)+'</span>':'')+'</nav>'}
function pendingPane(sel){var t=taskOf(sel),e=detailError;   // the selected task's own heading while its detail is loading or failed; nothing of any other task
  var h=crumbs(t?workTitle(t):nameOf(sel),'')+'<div class="dhead"><h2 id="dtitle" data-k="dtitle" tabindex="-1">'+(t&&workNoOwner(t)?'<span class="work-id">'+esc(nameOf(sel))+' · </span>':'')+esc(t?workTitle(t):nameOf(sel))+(t?' '+workBadge(t):'')+'</h2><button type="button" id="close" class="small" title="bỏ chọn task">Đóng</button></div>';
  var since=detailInflight&&sameSel(detailInflight.sel,sel)?detailInflight.since:Date.now();
  h+=e?'<div id="dstatus" class="dstatus err" role="status" data-state="error" data-k="dstatus" tabindex="-1">Không tải được chi tiết task này ('+esc(e.message)+') từ '+clockMs(e.since)+', lần thử gần nhất <span id="dlast">'+clockMs(e.last)+'</span>; <span id="dnote">'+noteHtml()+'</span>. Chưa có dữ liệu chi tiết nào của task này nên không có câu hỏi hay mẫu lệnh nào để hiện.</div>'
      :'<div id="dstatus" class="dstatus" role="status" data-state="loading" data-k="dstatus" tabindex="-1">đang tải chi tiết… <span class="mut">(đã chờ <span data-live="0" data-live-at="'+since+'">0s</span>, tối đa '+DETAIL_TIMEOUT/1000+' s)</span></div>';
  if(t)h+='<div class="small mut">Theo danh sách: '+esc(workReason(t))+'</div>';
  $('#detail').innerHTML=h}
function tasks(){var out=[];(last&&last.projects||[]).forEach(function(p){p.tasks.forEach(function(t){out.push(t)})});return out}
function visible(){var cur=$('#proj').value,kind=$('#kind').value,q=($('#q').value||'').toLowerCase();
  return workOrder(tasks().filter(function(t){if(cur&&t.project!==cur)return false;
    if(kind==='need'&&!(t.needs_user||[]).length)return false;if(kind==='running'&&!(sit(t).activity||{}).running)return false;if(kind&&kind!=='need'&&kind!=='running'&&workStage(t)!==kind)return false;
    if(q&&workSearch(t).indexOf(q)<0)return false;return true}),$('#sort').value)}
function row(t){var sel=sameSel(selected,{plan:t.selector,project:t.project_id}),lastv=!sel&&sameSel(lastViewed,{plan:t.selector,project:t.project_id});
  return '<li class="task'+(lastv?' last':'')+'" role="option" tabindex="0" aria-selected="'+sel+'" data-plan="'+esc(t.selector)+'" data-project="'+esc(t.project_id)+'" data-stage="'+esc(workStage(t))+'" data-k="task:'+esc(t.project_id)+':'+esc(t.selector)+'">'+workItem(t)+'</li>'}
var listMode=(function(){try{return localStorage.getItem('onecrew-track-mode')==='board'?'board':'list'}catch(e){return 'list'}})();
function setMode(m){listMode=m==='board'?'board':'list';try{localStorage.setItem('onecrew-track-mode',listMode)}catch(e){}render(true)}
function filterSummary(){var parts=[],k=$('#kind'),p=$('#proj'),q=($('#q').value||'').trim();if(p.value)parts.push('dự án '+short(p.value));if(k.value)parts.push(k.options[k.selectedIndex].text);if(q)parts.push('tìm “'+q+'”');return parts}
function render(force){
  if(!last)return;var ps=$('#proj'),cur=ps.value,opts='<option value="">tất cả</option>';
  (last.projects||[]).forEach(function(p){opts+='<option value="'+esc(p.path)+'"'+(p.path===cur?' selected':'')+'>'+esc(short(p.path))+'</option>'});if(ps.innerHTML!==opts)ps.innerHTML=opts;
  var vis=visible(),all=tasks(),need=all.filter(function(t){return (t.needs_user||[]).length}).length;
  $('#count').textContent=all.length+' công việc'+(vis.length!==all.length?' · hiện '+vis.length:'');
  var kindNow=$('#kind').value,counts={need:need,fix:all.filter(function(t){return workStage(t)==='fix'}).length,unknown:all.filter(function(t){return workStage(t)==='unknown'}).length,running:all.filter(function(t){return (sit(t).activity||{}).running}).length};
  var chips=[['need','Cần bạn quyết định'],['fix','Cần sửa'],['unknown','Chưa xác định'],['running','Đang có lượt chạy']].filter(function(c){return counts[c[0]]||kindNow===c[0]}).map(function(c){return '<button type="button" class="chip" data-kind="'+c[0]+'" aria-pressed="'+(kindNow===c[0])+'">'+c[1]+' ('+counts[c[0]]+')</button>'}).join('');
  document.querySelectorAll('#viewsw [data-list-mode]').forEach(function(b){b.setAttribute('aria-pressed',String(b.getAttribute('data-list-mode')===listMode))});
  var fs=filterSummary(),fa=$('#factive');fa.hidden=!fs.length;var fh=fs.length?'<b>Đang lọc:</b> '+esc(fs.join(' · '))+' <button type="button" id="fclear">Bỏ lọc</button>':'';if(fa.innerHTML!==fh)fa.innerHTML=fh;$('#fcount').textContent=fs.length?'('+fs.length+' đang áp dụng)':'';
  if($('#chips').innerHTML!==chips)$('#chips').innerHTML=chips;
  var sig=JSON.stringify(vis.map(function(t){return [t.selector,t.project_id,t.status.label,JSON.stringify(t.situation||null),t.last_update&&t.last_update.seq,(t.needs_user||[]).length,t.title]}))+'|'+$('#sort').value+'|'+listMode+'|'+(selected?selected.plan+selected.project:'')+(lastViewed?lastViewed.plan:'');
  if(sig!==listSig||force){var foc=document.activeElement&&document.activeElement.getAttribute&&document.activeElement.getAttribute('data-k');
    $('#list').setAttribute('data-mode',listMode);$('#list').innerHTML=vis.length?(listMode==='board'?workBoard(vis):workRows(vis)):'';listSig=sig;
    if(foc){var again=document.querySelector('[data-k="'+foc.replace(/"/g,'\\"')+'"]');if(again)again.focus({preventScroll:true})}}
  $('#empty').textContent=vis.length?'':(all.length?'Không có task nào khớp bộ lọc.':'Không có plan nào trong sổ này.');
  var u=last.untracked||{},parts=['<div>'+esc(u.statement||'')+'</div>'],n=(u.other_tasks||[]).length+(u.registry_projects_without_plan||[]).length+(u.hook_sessions||[]).length;
  (u.other_tasks||[]).slice(0,10).forEach(function(o){parts.push('<div>· task <code>'+esc(o.id.slice(0,12))+'</code> '+esc(o.key)+' phase '+esc(o.phase)+' — '+esc(o.note)+'</div>')});
  (u.registry_projects_without_plan||[]).slice(0,10).forEach(function(r){parts.push('<div>· '+esc(r.project)+' — '+esc(r.note)+'</div>')});
  (u.hook_sessions||[]).slice(0,10).forEach(function(s){parts.push('<div>· phiên hook '+esc(s.session)+' @ '+esc(s.project)+' — '+esc(s.note)+'</div>')});
  var shown=selected?[taskOf(selected)].filter(Boolean):vis;$('#sample').hidden=!shown.length||!shown.every(function(t){return /dữ liệu thử/i.test(t.goal||t.title||'')});
  var ub=parts.join('');if($('#untracked').innerHTML!==ub)$('#untracked').innerHTML=ub;$('#untrackedbox').querySelector('summary').textContent='Chưa được theo dõi ('+n+')';
}
function cmdHtml(c,ph){var t=esc(c);(Array.isArray(ph)?ph:[ph]).filter(Boolean).forEach(function(v){var p=esc(v);t=t.split(p).join('<mark class="ph">'+p+'</mark>')});return t}
function needTitle(n){if(n.owner_ask&&(n.kind==='approve'||n.kind==='accept'))return n.owner_ask;return n.kind==='request'?'Câu hỏi: '+(n.question||'').slice(0,90)+((n.question||'').length>90?'…':''):n.kind==='approve'?'Duyệt kế hoạch':n.kind==='accept'?'Nghiệm thu':n.kind==='stopped'?'Quyết định sau khi dừng':(n.question||n.kind)}
function needKey(n){return 'need:'+n.kind+':'+(n.id||'')+':'+(n.revision||'')}
function commandBox(command,ph,label){return '<div class="command-box cmd"><div class="command-head"><span>PowerShell · '+esc(label||'Lệnh dành cho bạn')+'</span><button type="button" class="copy" data-copy="'+esc(command)+'">Sao chép lệnh</button></div><pre><code>'+cmdHtml(command,ph)+'</code></pre></div>'}
function needCard(n,i){var ph=n.reference_placeholder,nk=needKey(n),command=n.human_command||n.reply_command,hasCommand=!!command||(n.options||[]).some(function(o){return !!(o.human_command||o.reply_command)}),marks=(n.placeholders||[]).map(function(k){return k==='reference'?ph:'<'+k+'>'});if(!marks.length&&ph)marks=[ph];
  var h='<details data-k="'+esc(nk)+'" class="need" data-need-id="'+esc(n.id||'')+'" data-need-rev="'+esc(n.revision||'')+'"'+'><summary>'+esc(needTitle(n))+(n.kind==='approve'?' · bản '+esc(n.revision)+' — xem nội dung và lệnh':'')+'</summary><div class="q">'+esc(n.kind==='approve'?(n.title||'Phương án đang chờ quyết định'):(n.question||n.kind))+'</div>';
  if(n.reason)h+='<p><b>Vì sao:</b> '+esc(n.reason)+'</p>';if(n.impact)h+='<p><b>Ảnh hưởng:</b> '+esc(n.impact)+'</p>';
  if(n.kind==='approve')h+=(n.reason?'':'<p>Bản này chưa có quyết định duyệt trong sổ.</p>')+(n.impact?'':'<p class="small">Chưa có mô tả ảnh hưởng riêng. Hãy đối chiếu nội dung trước / sau.</p>')+'<button type="button" data-work-tab="changes">Xem thay đổi trước khi duyệt</button>';
  if(detailError){var pinned=[command].concat((n.options||[]).map(function(o){return o.human_command||o.reply_command})).some(function(c){return /--revision/.test(c||'')});h+='<p class="stale-tpl" '+(pinned?'data-stale-template="1"':'data-stale-data="1"')+'>Dữ liệu cũ từ '+clockMs(detailOkAt)+'. Đợi cập nhật hoặc kiểm lại trạng thái.'+(pinned?' Lệnh ghim --revision cũ sẽ bị từ chối nếu bản đã đổi. Sao chép không xác nhận yêu cầu còn hiệu lực.':'')+'</p>';}
  if(hasCommand){h+='<p><b>Mở PowerShell của bạn trên máy này.</b> Không dán vào ô chat để nhờ AI duyệt.</p>';
    if(ph)h+='<p class="small">Thay phần <mark class="ph">'+esc(ph)+'</mark> bằng lý do xác nhận của bạn trước khi chạy. Mẫu chưa điền không phải quyết định đã duyệt.</p>';}
  if(hasCommand&&(n.placeholders||[]).indexOf('option-id')>=0)h+='<p><b>Cần điền thêm:</b> thay <mark class="ph">&lt;option-id&gt;</mark> bằng ID phương án anh chọn trong danh sách bên dưới. Không tự chọn thay anh.</p>';
  (n.options||[]).forEach(function(o){var c=o.human_command||o.reply_command;h+='<div class="opt"><b>'+esc(o.label)+'</b>'+(n.recommendation===o.id?' <span class="small">· đề xuất</span>':'')+(c?commandBox(c,marks,'Trả lời lựa chọn này'):'')+'</div>'});
  if(!(n.options||[]).length&&command)h+=commandBox(command,marks,n.kind==='approve'?'Duyệt bản '+n.revision:'Ghi nhận quyết định');
  if(!hasCommand){h+='<p>'+esc(n.binding_reason||n.note||'Chưa có mẫu lệnh đủ dữ liệu để thực hiện an toàn.')+'</p>';if(n.inspect_command)h+=commandBox(n.inspect_command,null,'Chỉ xem trạng thái, chưa duyệt');}
  if((n.plan_choices||[]).length)h+='<p><b>Cần chọn phương án:</b> '+n.plan_choices.map(function(o){return esc(o.id)+' — '+esc(o.title||o.summary||'Chưa có mô tả')}).join('; ')+'</p>';
  if((n.optional_items||[]).length)h+='<details><summary>Hạng mục tùy chọn — chưa tự chọn</summary><p>'+n.optional_items.map(function(o){return esc(o.id)+' — '+esc(o.title||'Chưa có mô tả')}).join('; ')+'</p></details>';
  if(hasCommand)h+='<p class="small">Sao chép chưa phải duyệt. Chạy lệnh thành công mới ghi quyết định; trang cập nhật khi đọc được kết quả từ sổ.</p>';
  if(hasCommand&&n.reply_note)h+='<details><summary>Chi tiết lệnh và quyền</summary><p>'+esc(n.reply_note)+'</p></details>';
  if(hasCommand&&copied&&copied.k===nk){if(copied.ok)h+='<div class="copied" role="status" data-copied="'+esc(copied.text)+'">Đã sao chép lệnh. Chưa ghi nhận quyết định.</div>';
    else h+='<div class="copied err" role="status" data-copy-failed="1">Không sao chép được; chọn khối lệnh để sao chép thủ công.<textarea readonly rows="3" style="width:100%">'+esc(copied.text)+'</textarea></div>';}
  return h+'</details>'}

function kindWord(k){return k.replace('executor.observed','quan sát').replace('node.','phần việc: ').replace('plan.','plan: ').replace('attempt.','attempt: ').replace('request.','câu hỏi: ').replace('verdict.','verdict: ').replace('milestone.','mốc: ')}
function prov(d){if(d.__prov)return d.__prov;var bySeq={},byKey={},keys=[];      // R1: occurrences (seq, key) of the model, never key -> one entry
  (d.evidence_index||[]).forEach(function(x){if(typeof x.seq==='number')(bySeq[x.seq]=bySeq[x.seq]||[]).push(x);if(!byKey[x.key]){byKey[x.key]=[];keys.push(x.key)}byKey[x.key].push(x)});
  Object.defineProperty(d,'__prov',{value:{bySeq:bySeq,byKey:byKey,keys:keys},enumerable:false});return d.__prov}
function occMeta(x){return esc(x.kind||'')+(x.role?' · '+esc(x.role):'')+(typeof x.generation==='number'?' · thế hệ '+x.generation:' · thế hệ chưa xác định')+(x.attempt?' · lượt '+esc(String(x.attempt).slice(4,12)):' · lượt chưa xác định')+' · '+(x.at?when(x.at):'thời điểm chưa rõ')}
function occLine(x){return '<b>'+esc(x.label||'bằng chứng')+'</b> <span class="small mut">'+occMeta(x)+' · <code>'+x.key.slice(0,12)+'…</code></span>'}
function openBtn(k){var o=evState[k];return ' <button type="button" class="ev-open" data-key="'+k+'">'+(o?'ẩn nội dung':'xem nội dung')+'</button> <a class="small" target="_blank" href="'+evHref(k)+'">mở tab mới</a>'+(o?'<pre>'+esc(o.text)+'</pre>':'')}
function openOr(x){return x.blob===false?' <span class="small mut nob">không có trong kho: không mở được</span>':(x.stored==='manifest'?' <span class="small mut">ảnh chụp</span>':'')+openBtn(x.key)}     // R1 round 2: only a blob in the store opens
function occDiv(x){return '<div class="small" data-k="evk:'+x.key+':'+(typeof x.seq==='number'?x.seq:'s')+'">'+occLine(x)+openOr(x)+'</div>'}
function evLi(e,P){var exp=selEv===e.seq,occ=P.bySeq[e.seq]||[],n=occ.length||(e.evidence||[]).length;var h='<li tabindex="0" role="button" aria-expanded="'+exp+'" data-seq="'+e.seq+'" data-k="ev:'+e.seq+'" class="'+((e.stale_generation||e.stale_attempt)?'stale':'')+'"><span class="t" title="'+when(e.at)+'">'+clock(e.at)+(e.observed_at&&e.observed_at!==e.at?' (quan sát '+clock(e.observed_at)+')':'')+'</span>'
    +esc(e.summary)+(e.task!=='root'?' <span class="k">(task con)</span>':'')+(n?'<span class="clip">bằng chứng '+n+'</span>':'')+'<span class="k">#'+e.seq+' '+esc(e.kind)+'</span>'+(e.note?' <b class="small">['+esc(e.note)+']</b>':'');
  if(exp){h+='<div class="evbox" data-k="evbox:'+e.seq+'">';if(!n)h+='<span class="mut">bước này không nêu bằng chứng nào</span>';
    occ.forEach(function(x){h+='<div data-k="evk:'+x.key+':'+e.seq+'">'+occLine(x)+openOr(x)+'</div>'});h+='</div>'}      // each key with THIS event's own occurrence
  return h+'</li>'}
function evHref(k){var d=mine();if(!d)return '#';return '/api/evidence?plan='+encodeURIComponent(d.selector)+'&project_id='+encodeURIComponent(d.project_id)+'&key='+k+'&format=text'}
function groups(d){var g={},order=[];function add(key,title,e){if(!g[key]){g[key]={title:title,cur:[],old:[],tech:[]};order.push(key)}var tech=TECH.some(function(p){return e.kind.indexOf(p)===0});
    if(e.stale_generation||e.stale_attempt)g[key].old.push(e);else if(tech)g[key].tech.push(e);else g[key].cur.push(e)}
  add('plan','Plan '+d.plan,{kind:'',seq:-1,summary:''});g.plan.cur=[];
  Object.keys(d.nodes||{}).forEach(function(id){var n=d.nodes[id];add('n:'+id,'phần việc '+id,{kind:'',seq:-1,summary:''});g['n:'+id].cur=[];g['n:'+id].node=n});
  (d.timeline||[]).forEach(function(e){var n=e.node||e.node_of_attempt;if(n)add('n:'+n,'phần việc '+n,e);else add('plan','Plan '+d.plan,e)});return {g:g,order:order}}
@@WORK_SCRIPT@@
function renderDetail(d){
  var P=prov(d);
  var h=[crumbs(workTitle(d),d.work?crumbTab(d):''),'<div class="dhead"><h2 id="dtitle" data-k="dtitle" tabindex="-1">'+(workNoOwner(d)?'<span class="work-id">'+esc(d.plan)+' · </span>':'')+esc(workTitle(d))+' '+workBadge(d)+'</h2><button type="button" id="close" class="small" title="bỏ chọn task">Đóng</button></div>'];
  if(detailError)h.push('<div id="dstatus" class="dstatus stale" role="status" data-state="stale" data-k="dstatus" tabindex="-1">Chi tiết chưa cập nhật từ '+clockMs(detailOkAt)+': lỗi tải chi tiết ('+esc(detailError.message)+', lần thử gần nhất <span id="dlast">'+clockMs(detailError.last)+'</span>); đang hiện dữ liệu lúc '+(d.generated_at?clock(d.generated_at):clockMs(detailOkAt))+'. Mẫu lệnh trả lời bên dưới là của lúc đó: nếu câu hỏi đã được trả lời hoặc đổi bản, OneCrew từ chối lệnh nhờ --revision. <span id="dnote" data-cap="1">'+cap(noteHtml())+'</span>.</div>');
  h.push('<div class="small mut">Đang xem '+(workNoOwner(d)?'task <b>'+esc(d.plan)+'</b>':'việc này')+' của project <span title="'+esc(d.project)+'">'+esc(short(d.project))+'</span> · <a href="'+esc(urlOf({plan:d.selector,project:d.project_id}))+'">liên kết tới task này</a></div>');
  var needs=d.needs_user||[],nq=needs.filter(function(n){return n.kind==='request'}).length,nother=needs.length-nq;
  h.push(sitPanel(d));                                                  // UX 13/11: where it is, what blocks it, who acts next, what the owner does, where the results are
  var done=d.status.kind==='done';
  var nowKeys={};needs.forEach(function(n){nowKeys[needKey(n)]=n});
  if(copied&&!copiedStillValid(copied,d))copied=null;      // R7-1: feedback of a command this data no longer offers (binding lost, other runtime/state) is dropped, never shown again
  Object.keys(knownNeeds).forEach(function(k){var old=knownNeeds[k];if(nowKeys[k]||!old.open)return;
    var same=needs.find(function(n){return n.kind==='request'&&n.id===old.id});
    if(!staleNotes.some(function(x){return x.key===k}))staleNotes.push({key:k,id:old.id,title:old.title,why:same?'đã đổi bản (revision '+String(same.revision).slice(0,12)+'…): mẫu lệnh cũ không còn hiệu lực, đọc lại câu hỏi':'không còn chờ ở bản đang xem: mẫu lệnh cũ không còn hiệu lực'});
    if(copied&&copied.k===k)copied=null});
  if(needs.length||staleNotes.length){h.push('<h3 id="needs">Quyết định cần bạn ('+needs.length+')</h3>');
    staleNotes.forEach(function(x){h.push('<div class="stale-need" data-k="stale:'+esc(x.key)+'" data-stale-id="'+esc(x.id||'')+'">Yêu cầu bạn đang đọc <b>'+esc(String(x.id||'').slice(0,12))+'…</b> ('+esc(x.title||'')+') '+esc(x.why)+'.<button type="button" class="stale-hide" data-key="'+esc(x.key)+'">ẩn</button></div>')});
    needs.forEach(function(n,i){h.push(needCard(n,i))})}
  h.push(workDashboard(d));
  h.push('<div id="legacy-progress"'+(d.work&&workTab!=='overview'&&workTab!=='progress'?' hidden':'')+'>');
  if(!d.work||(workTab!=='progress'&&!d.milestone_checks))h.push(gantt(d));
  if(d.work)h.push('<details data-k="work-technical"><summary>Số đo và nhật ký kỹ thuật</summary>');
  function brief(t,n){t=String(t||'');return t.length>n?'<span title="'+esc(t)+'">'+esc(t.slice(0,n))+'…</span>':esc(t)}
  h.push('<div class="stats"><div class="tile"><div class="l">Trạng thái</div><div class="v">'+esc(d.status.label)+'</div><div class="s">'+brief(d.status.reason,140)+'</div></div>'
    +'<div class="tile"><div class="l">Đầu ra</div><div class="v">'+esc(d.level.label)+'</div><div class="s">'+brief(d.current_step||'',140)+'</div></div>'
    +'<div class="tile"><div class="l">Từ khi duyệt (lịch)</div><div class="v"'+(!done&&!d.elapsed.until&&typeof d.elapsed.seconds==='number'?' data-live="'+d.elapsed.seconds+'" data-live-at="'+(detailOkAt||Date.now())+'"':'')+'>'+hms(d.elapsed.seconds)+'</div><div class="s">'+(typeof d.elapsed.seconds==='number'?'gồm cả thời gian chờ'+(d.elapsed.until?' · kết thúc '+when(d.elapsed.until):' · đang tính theo đồng hồ máy này'):'chưa duyệt: chưa có mốc bắt đầu')+'</div></div>'
    +'<div class="tile"><div class="l">Thực hiện (attempt)</div><div class="v">'+hms(d.measure.attempts_wall_seconds)+'</div><div class="s">hợp các khoảng attempt, không cộng đôi</div></div>'
    +'<div class="tile"><div class="l">Chờ</div><div class="v">'+hms(d.measure.wait_seconds)+'</div><div class="s">'+((d.waits||[]).filter(function(w){return w.open}).length?'đang có khoảng chờ mở':'khoảng chờ đã đo; thiếu nguồn = chưa xác định')+'</div></div>'
    +'<div class="tile"><div class="l">Còn lại (ước lượng)</div><div class="v">'+esc(d.eta.label)+'</div><div class="s">'+brief(d.eta.reason||'',140)+(d.eta.deadline?' · hạn '+when(d.eta.deadline):'')+'</div></div></div>');
  var ow=(d.waits||[]).filter(function(w){return w.open}),cw=(d.waits||[]).filter(function(w){return !w.open});
  if(ow.length)h.push('<div class="small"><b>Đang chờ:</b> '+ow.map(function(w){return esc(w.reason||'không rõ')+' từ '+when(w.since)+(w.node?' (phần việc '+esc(w.node)+')':'')}).join('; ')+'</div>');
  if((d.holds||[]).length)h.push('<div class="small"><b>Giữ (finding):</b> '+d.holds.map(function(x){return esc(x.text||x.error)}).join('; ')+'</div>');
  var ns=Object.keys(d.nodes||{});if(ns.length){h.push('<h3>Phần việc</h3><div class="scroll"><table><thead><tr><th>Phần việc</th><th>Trạng thái</th><th>Đầu ra</th><th>Thế hệ</th><th>Quan sát gần nhất</th></tr></thead><tbody>');
    ns.forEach(function(id){var n=d.nodes[id],p=n.progress;h.push('<tr><td><b>'+esc(nodeName(d,id))+'</b></td><td>'+word(PHASE,n.phase)+(n.phase==='held'?'<div class="small" style="color:var(--blk)">lý do (engine): '+esc(n.reason)+'</div>':'')+'</td><td>'+word(NSTATE,n.state)+(n.verification_result?' ('+esc(n.verification_result)+')':'')+'</td><td>'+n.generation+(n.continues?' <span class="small mut">tiếp từ '+esc(n.continues)+'</span>':'')+'</td><td class="wrap small">'+(p?esc(p.status)+' '+rel(p.observed_at||p.received_at)+(p.reason?'<br>'+esc(p.reason):''):'—')+'</td></tr>')});h.push('</tbody></table></div>')}
  var G=groups(d),older=d.timeline_total-d.timeline.length;h.push('<details data-k="log"><summary>Nhật ký sự kiện ('+d.timeline.length+'/'+d.timeline_total+', cũ → mới; bấm một bước để xem bằng chứng của bước đó)</summary>');
  if(older>0)h.push('<div class="small mut" id="lognote">đang hiện '+d.timeline.length+'/'+d.timeline_total+' sự kiện mới nhất; '+older+' sự kiện cũ hơn chưa tải ở nhật ký này — bằng chứng của chúng vẫn có ở Gantt (chọn lượt hoặc dấu mốc) và mục Bằng chứng (toàn bộ lịch sử)</div>');
  G.order.forEach(function(key){var x=G.g[key];if(!x.cur.length&&!x.old.length&&!x.tech.length)return;
    h.push('<section class="grp" data-k="grp:'+esc(key)+'"><div class="gh"><h4>'+esc(x.title)+'</h4>'+(x.node?'<span class="small mut">thế hệ '+x.node.generation+(x.node.attempt?' · attempt <code>'+esc(x.node.attempt.slice(0,16))+'</code>':'')+'</span>':'')+'</div>');
    h.push('<ol class="ev">'+x.cur.map(function(e){return evLi(e,P)}).join('')+'</ol>');
    if(x.old.length)h.push('<details data-k="old:'+esc(key)+'"><summary>lịch sử cũ ('+x.old.length+' sự kiện của thế hệ/attempt trước; không đổi trạng thái hiện tại)</summary><ol class="ev">'+x.old.map(function(e){return evLi(e,P)}).join('')+'</ol></details>');
    if(x.tech.length)h.push('<details data-k="tech:'+esc(key)+'"><summary>chi tiết kỹ thuật ('+x.tech.length+')</summary><ol class="ev">'+x.tech.map(function(e){return evLi(e,P)}).join('')+'</ol></details>');
    h.push('</section>')});
  h.push('</details>');
  function use(x){return '<li>'+esc(x.label||'')+' <span class="mut">· '+occMeta(x)+(x.seq!=null?' · #'+x.seq:'')+'</span></li>'}
  var bk=P.keys.filter(function(k){return P.byKey[k][0].blob!==false}),mk=P.keys.filter(function(k){return P.byKey[k][0].blob===false}),nu=0;bk.forEach(function(k){nu+=P.byKey[k].length});
  function uses(u){return '<ul class="uses">'+(u.length>8?u.slice(0,4).map(use).join('')+'<li class="mut">… '+(u.length-8)+' lần khác …</li>'+u.slice(-4).map(use).join(''):u.map(use).join(''))+'</ul>'}
  h.push('<details data-k="evidence"><summary>Bằng chứng ('+bk.length+' mục trong kho, '+nu+' lần được nêu trong toàn bộ lịch sử'+(mk.length?'; '+mk.length+' khóa đầu ra không còn trong kho':'')+'; lọc bí mật, chỉ đọc)</summary>'+bk.map(function(k){var u=P.byKey[k];   // one stored key (blob or snapshot), its uses (generation / attempt / role)
    return '<div class="small" data-k="evk:'+k+'"><code>'+k.slice(0,12)+'…</code>'+(u[0].stored==='manifest'?' · ảnh chụp':'')+' · '+u.length+' lần được nêu'+openBtn(k)+uses(u)+'</div>'}).join('')
    +mk.map(function(k){var u=P.byKey[k];return '<div class="small" data-k="evm:'+k+'"><code>'+k.slice(0,12)+'…</code> · '+u.length+' lần được nêu · <span class="mut nob">không có trong kho: không mở được</span>'+uses(u)+'</div>'}).join('')+'</details>');
  if(cw.length)h.push('<details data-k="waits"><summary>Đã chờ (lịch sử, '+cw.length+')</summary>'+cw.map(function(w){return '<div class="small">'+esc(w.reason||'không rõ')+' '+when(w.since)+' → '+(w.until==='unknown'?'chưa rõ kết thúc':when(w.until))+' ('+esc(w.source)+')</div>'}).join('')+'</details>');
  if((d.attempts||[]).length){var mx={};((d.measure&&d.measure.attempts)||[]).forEach(function(m){mx[m.attempt]=m});var top=0;Object.keys(mx).forEach(function(k){if(typeof mx[k].execution_seconds==='number')top=Math.max(top,mx[k].execution_seconds)});
    h.push('<details data-k="attempts"><summary>Attempt ('+d.attempts.length+')</summary><div class="scroll"><table><thead><tr><th>Attempt</th><th>Trạng thái</th><th>Thế hệ</th><th>Thời lượng (đo)</th><th>Từ</th><th>Cập nhật</th></tr></thead><tbody>'+d.attempts.map(function(a){var m=mx[a.id],sec=m&&typeof m.execution_seconds==='number'&&m.settled_at?m.execution_seconds:null;
      return '<tr><td><code>'+esc(a.id)+'</code></td><td>'+esc(a.status)+'</td><td>'+a.generation+'</td><td class="small">'+(sec!==null?'<span class="dur" style="width:'+Math.max(4,Math.round(sec/(top||1)*80))+'px"></span>'+hms(sec):'chưa xác định')+'</td><td class="small">'+when(a.created_at)+'</td><td class="small">'+when(a.updated_at)+'</td></tr>'}).join('')+'</tbody></table></div></details>')}
  if((d.notices||[]).length)h.push('<details data-k="notices"><summary>Thông báo ('+d.notices.length+')</summary>'+d.notices.map(function(n){return '<div class="small">'+when(n.at)+' '+esc(n.category)+': '+esc(n.reason)+(n.user_action?' — '+esc(n.user_action):'')+'</div>'}).join('')+'</details>');
  h.push('<details data-k="techinfo"><summary>Kỹ thuật</summary><div class="small">id <code>'+esc(d.id)+'</code> · selector <code>'+esc(d.selector)+'</code> · project <code>'+esc(d.project)+'</code> · project_id <code>'+esc(d.project_id)+'</code><br>root: '+esc(d.root_status)+' · hợp đồng bản '+esc(d.contract_revision)+' · adapter '+esc(d.tracking.adapter)+' — '+esc(d.tracking.coverage)+'<br>nguồn trạng thái: '+esc((d.status.source||[]).join(', '))+'<br>'+esc(d.elapsed.basis||'')+'<br>'+(d.measure.method?'đo: '+esc(JSON.stringify(d.measure.method)):'')+'<br>'+esc(d.controls)+'</div></details>');
  if(d.work)h.push('</details>');h.push('</div>');
  $('#detail').innerHTML=h.join('');
  knownNeeds={};needs.forEach(function(n){var el=document.querySelector('#detail details[data-k="'+needKey(n).replace(/"/g,'\\"')+'"]');knownNeeds[needKey(n)]={id:n.id,revision:n.revision,title:needTitle(n),open:!!(el&&el.open)}});
}
function noteOpen(){needs_open_sync()}
// R7-1: what a reader can copy from a need comes from the project's hook binding too, which lives outside the ledger: an unchanged last_seq
// does not mean unchanged cards. needsSig is that copyable surface; copiedStillValid ties copy feedback to a command the data still offers.
function needCopyable(n){return [n.human_command||n.reply_command||null,n.inspect_command||null].concat((n.options||[]).map(function(o){return o.human_command||o.reply_command||null})).filter(Boolean)}
function needsSig(d){return JSON.stringify(((d&&d.needs_user)||[]).map(function(n){return [needKey(n),needCopyable(n),(n.runtime_binding||{}).verified===true,n.binding_reason||null]}))}
function copiedStillValid(c,d){if(!c||!c.text)return false;var n=((d&&d.needs_user)||[]).find(function(x){return needKey(x)===c.k});return !!n&&needCopyable(n).indexOf(c.text)>=0}
function needs_open_sync(){Object.keys(knownNeeds).forEach(function(k){var el=document.querySelector('#detail details[data-k="'+k.replace(/"/g,'\\"')+'"]');if(el)knownNeeds[k].open=el.open})}
// ---- Gantt / waterfall: tree (left) | shared time axis (centre) | step pane (right); every pixel comes from a sourced timestamp
function tms(t){if(t==null||t==='')return null;var v=new Date(t).getTime();return isNaN(v)?null:v}
function gDuration(seconds){if(typeof seconds!=='number'||!Number.isFinite(seconds)||seconds<0)return 'chưa đủ mốc đo';if(seconds===0)return '0s';if(seconds<1)return (seconds*1000<1?'<1':String(Math.round(seconds*1000)))+' ms';if(seconds<60)return Number(seconds.toFixed(2))+'s';if(seconds<3600)return Math.floor(seconds/60)+' phút'+(Math.round(seconds%60)?' '+Math.round(seconds%60)+'s':'');if(seconds>=86400)return Number((seconds/86400).toFixed(2))+' ngày';return Number((seconds/3600).toFixed(2))+' giờ'}
function gTicks(W){var span=W.w1-W.w0,target=span/4,power=Math.pow(10,Math.floor(Math.log10(target))),step=[.5,1,2,5,10,20,50,100,200,500,1000,2000,5000,10000,15000,30000,60000,120000,300000,600000,900000,1800000,3600000,7200000,21600000,43200000,86400000].find(function(x){return x>=target})||86400000*Math.pow(10,Math.floor(Math.log10(target/86400000)))*[1,2,2.5,5,10].find(function(x){return x>=target/86400000/Math.pow(10,Math.floor(Math.log10(target/86400000))) });
  var out=[];for(var t=0;t<=span+.0001&&out.length<8;t+=step)out.push({pct:t/span*100,label:gDuration(t/1000),at:W.w0+t});
  var rest=span-(out[out.length-1].at-W.w0);if(rest>0){if(rest<step*.8&&out.length>1)out.pop();out.push({pct:100,label:gDuration(span/1000),at:W.w1})}return out}   // UX 13/11: '6 phút6 phút 57s' — a near-end tick gives way to the end label
function gWindow(g){if(gPinnedWindow&&gPinnedWindow.range===gRange)return Object.assign({},gPinnedWindow);
  var a=g.axis||{},e0=tms(a.start),e1=tms(a.end);
  if(gRange==='current'){var ts=[];(g.rows||[]).filter(function(r){return r.current||r.active}).forEach(function(r){(r.segments||[]).forEach(function(x){ts.push(tms(x.from),tms(x.to))});(r.waits||[]).forEach(function(x){ts.push(tms(x.from),tms(x.until))});(r.verification||[]).forEach(function(x){ts.push(tms(x.from),tms(x.to))});(r.marks||[]).forEach(function(x){ts.push(tms(x.at))})});ts=ts.filter(function(x){return x!==null});if(ts.length){e0=Math.min.apply(null,ts);e1=Math.max.apply(null,ts)}}
  if(e0===null||e1===null)return null;var w0=e0,w1=e1;if(gRange==='1h')w0=Math.max(e0,e1-3600000);else if(gRange==='15m')w0=Math.max(e0,e1-900000);if(w1<=w0)w1=w0+1;return {w0:w0,w1:w1,e0:e0,e1:e1}}
function gNodeStatus(n){if(n.phase==='held')return 'Bị giữ'+(n.reason?' · '+n.reason:'');if(n.state==='accepted')return 'Đã nghiệm thu';if(n.state==='verified')return 'Đã kiểm đạt';if(n.state==='produced')return 'Đã tạo đầu ra · chờ kiểm';if(n.phase==='running')return 'Đang thực hiện';if(n.phase==='pending')return 'Chưa đến lượt';return 'Chưa xác định'}
function gNodeTime(rows){if(!rows.length)return 'Chưa khởi chạy';if(rows.length===1&&typeof rows[0].execution_seconds==='number')return 'Thực thi: '+gDuration(rows[0].execution_seconds);var intervals=[],unknown=false;rows.forEach(function(r){var a=tms(r.launched_at),b=tms(r.settled_at);if(a===null||b===null)unknown=true;else intervals.push([a,b])});if(unknown)return 'Thực thi: chưa đủ mốc đo';intervals.sort(function(a,b){return a[0]-b[0]});var total=0,end=null;intervals.forEach(function(x){total+=Math.max(0,x[1]-Math.max(x[0],end===null?x[0]:end));end=Math.max(end===null?x[1]:end,x[1])});return 'Thực thi: '+gDuration(total/1000)}
function pct(W,t){var v=tms(t);if(v===null)return null;return (v-W.w0)/(W.w1-W.w0)*100}
function segHtml(W,row,sg,i){var l=pct(W,sg.from),r=pct(W,sg.to);if(l===null||r===null)return '';if(r<0||l>100)return '';var L=Math.max(0,l),Rr=Math.min(100,r);
  var id='seg:'+row.attempt+':'+i,sel=selStep&&selStep.id===id;
  return '<div class="seg '+esc(sg.kind)+(sel?' sel':'')+'" tabindex="0" role="button" data-k="'+esc(id)+'" data-attempt="'+esc(row.attempt)+'" data-kind="'+esc(sg.kind)+'" data-from="'+esc(sg.from)+'" data-to="'+esc(sg.to)+'" data-confirmed="'+sg.confirmed+'" style="left:'+L.toFixed(3)+'%;width:'+Math.max(0.15,Rr-L).toFixed(3)+'%" title="'+esc(segWord(sg.kind))+': '+when(sg.from)+' → '+(sg.kind==='to_now'?'hiện tại (chưa xác nhận)':when(sg.to))+'"></div>'}
function markHtml(W,m,rowKey){var l=pct(W,m.at);if(l===null||l<0||l>100)return '';var id='mk:'+m.seq,sel=selStep&&selStep.id===id,cls=m.kind==='node.held'?' held':/pass/.test(m.label)?' pass':/fail/.test(m.label)?' fail':m.kind.indexOf('plan.')===0||m.kind.indexOf('request.')===0?' plan':'';
  return '<span class="mk'+cls+(sel?' sel':'')+'" tabindex="0" role="button" data-k="'+esc(id)+'" data-seq="'+m.seq+'" data-at="'+esc(m.at)+'" data-row="'+esc(rowKey)+'" style="left:'+l.toFixed(3)+'%" title="'+esc(m.label)+' · '+when(m.at)+'" aria-label="'+esc(m.label)+' '+when(m.at)+'">◆</span>'}
function segWord(k){return {execution:'thực thi',reserved:'Trước khởi chạy',wait:'chờ',verification:'Từ đầu ra đến kết quả kiểm',to_now:'tới hiện tại (chưa xác nhận)'}[k]||k}
function waitSeg(W,row,w,i){if(!w.until)return '';var l=pct(W,w.from),r=pct(W,w.until);if(l===null||r===null||r<0||l>100)return '';var id='wait:'+row.attempt+':'+i,sel=selStep&&selStep.id===id;
  return '<div class="seg wait'+(sel?' sel':'')+'" tabindex="0" role="button" data-k="'+esc(id)+'" data-attempt="'+esc(row.attempt)+'" data-kind="wait" data-from="'+esc(w.from)+'" data-to="'+esc(w.until)+'" style="left:'+Math.max(0,l).toFixed(3)+'%;width:'+Math.max(0.15,Math.min(100,r)-Math.max(0,l)).toFixed(3)+'%" title="chờ: '+esc(w.reason||'')+' '+when(w.from)+' → '+when(w.until)+'"></div>'}
function verSeg(W,row,v,i){var l=pct(W,v.from),r=pct(W,v.to);if(l===null||r===null||r<0||l>100)return '';var id='ver:'+row.attempt+':'+i,sel=selStep&&selStep.id===id;
  return '<div class="seg verification'+(sel?' sel':'')+'" tabindex="0" role="button" data-k="'+esc(id)+'" data-attempt="'+esc(row.attempt)+'" data-kind="verification" data-from="'+esc(v.from)+'" data-to="'+esc(v.to)+'" style="left:'+Math.max(0,l).toFixed(3)+'%;width:'+Math.max(0.15,Math.min(100,r)-Math.max(0,l)).toFixed(3)+'%" title="Từ đầu ra đến kết quả kiểm ('+esc(v.result)+'), có thể gồm chờ: '+when(v.from)+' → '+when(v.to)+'"></div>'}
function gantt(d){var g=d.gantt||{rows:[],plan_marks:[],axis:{}},W=gWindow(g),rows=g.rows||[];
  var h=['<section class="gantt'+(selStep?' has-selection':'')+'" data-k="gantt" aria-label="Tiến trình công việc">'];
  var shown=gRange==='current'?rows.filter(function(r){return r.current||r.active}):rows,types={};shown.forEach(function(r){(r.segments||[]).forEach(function(x){types[x.kind]=true});if((r.waits||[]).some(function(x){return x.until}))types.wait=true;if((r.verification||[]).length)types.verification=true});
  var legend='<div class="legend">'+Object.keys(types).map(function(k){return '<span><i class="sw '+esc(k)+'"></i>'+esc(segWord(k))+'</span>'}).join('')+'</div>';
  h.push('<div class="gmain"><div class="gintro"><b>Tiến trình các phần việc</b><p class="mut">Để xem lịch sử và tìm chỗ chậm; trạng thái của việc nằm ở phần tóm tắt phía trên.</p></div>');
  if(!W){h.push('<p id="gempty" class="mut">Chưa có mốc thời gian có nguồn. Không suy chưa có dữ liệu thành thời lượng 0.</p></div><div id="gside" hidden></div></section>');return h.join('')}
  h.push('<div class="gtop"><label>Xem <select id="grange">'+[['current','Hiện hành'],['all','Toàn bộ lịch sử'],['15m','15 phút cuối'],['1h','1 giờ cuối']].map(function(x){return '<option value="'+x[0]+'"'+(gRange===x[0]?' selected':'')+'>'+x[1]+'</option>'}).join('')+'</select></label><button type="button" id="gfit">Về hiện hành</button><span>Trục tương đối · cửa sổ '+gDuration((W.w1-W.w0)/1000)+'</span></div><div class="ganchor">Mốc 0: '+when(new Date(W.w0).toISOString())+(gPinnedWindow?' · Đang giữ khung lịch sử; bấm Về hiện hành để theo dữ liệu mới.':'')+'</div>');
  if(lostSince||detailError)h.push('<p class="gstale" id="gstale">Dữ liệu cũ · đồng hồ dừng. '+(lostSince?'Mất kết nối.':'Chi tiết chưa cập nhật.')+'</p>');
  h.push(legend);if(types.verification)h.push('<p class="gexplain">Khoảng từ đầu ra đến kết quả kiểm có thể gồm chờ. Chưa có mốc riêng để xác định thời gian chạy bộ kiểm.</p>');
  var ticks=gTicks(W),axis=ticks.map(function(t,i){return '<i style="left:'+t.pct+'%"></i><span class="'+(i===0?'first':t.pct>95?'last':'')+'" style="left:'+t.pct+'%">'+esc(t.label)+'</span>'}).join('');
  var tree=['<div class="grow gh0">Phần việc · trạng thái</div>'],chart=['<div class="gaxis">'+axis+'</div>'];
  var nowL=g.axis.extends_to_now?pct(W,g.axis.now):null;
  function chartRow(inner,cls,nid){return '<div class="grow '+(cls||'')+'"'+(nid?' data-node-row="'+esc(nid)+'"':'')+'>'+ticks.map(function(t){return '<i class="ggrid" style="left:'+t.pct.toFixed(3)+'%"></i>'}).join('')+inner+(nowL!==null&&nowL>=0&&nowL<=100?'<span class="nowline" style="left:'+nowL.toFixed(3)+'%"></span>':'')+'</div>'}
  function bars(r){return (r.segments||[]).map(function(sg,i){return segHtml(W,r,sg,i)}).join('')+(r.waits||[]).map(function(w,i){return waitSeg(W,r,w,i)}).join('')+(r.verification||[]).map(function(v,i){return verSeg(W,r,v,i)}).join('')+(r.marks||[]).map(function(m){return markHtml(W,m,r.attempt)}).join('')}
  var pm=(g.plan_marks||[]).map(function(m){return markHtml(W,m,'plan')}).join('');if(pm){tree.push('<div class="grow planrow">Mốc công việc</div>');chart.push(chartRow(pm,'planrow'))}
  var byNode={};rows.forEach(function(r){var nid=r.node||'?';(byNode[nid]||(byNode[nid]=[])).push(r)});
  Object.keys(d.nodes||{}).concat(Object.keys(byNode).filter(function(k){return !(k in (d.nodes||{}))})).forEach(function(nid){var all=byNode[nid]||[],n=(d.nodes||{})[nid]||{},cur=all.filter(function(r){return r.current||r.active}),old=all.filter(function(r){return !(r.current||r.active)}),folded=gFold['n:'+nid]!==false,hist=gFold['h:'+nid]!==false;
    var selected=selStep&&selStep.id==='node:'+nid;
    tree.push('<div class="grow nodehead'+(selected?' selected':'')+'" data-k="grow:n:'+esc(nid)+'"><button type="button" class="tg" data-fold="n:'+esc(nid)+'" aria-label="'+(folded?'Mở các lượt của ':'Thu gọn ')+esc(nodeName(d,nid))+'" aria-expanded="'+(!folded)+'">'+(folded?'▸':'▾')+'</button><button type="button" class="gnselect" title="'+esc(nodeName(d,nid))+'" data-node-select="'+esc(nid)+'" data-k="node:'+esc(nid)+'" aria-pressed="'+!!selected+'"><strong>'+esc(nodeName(d,nid))+'</strong><span>'+esc(gNodeStatus(n))+'</span><small>'+esc(gNodeTime(cur))+(old.length?' · '+old.length+' lượt cũ':'')+'</small></button></div>');
    chart.push(chartRow(folded?cur.map(bars).join(''):'','nodehead',nid));if(folded)return;
    cur.forEach(function(r){tree.push('<div class="grow att" data-k="grow:'+esc(r.attempt)+'"><b>Lượt hiện hành</b> · '+esc(r.status)+'<small>Mã '+esc(r.attempt.slice(4,12))+' · thế hệ '+r.generation+'</small></div>');chart.push(chartRow(bars(r),'att'))});
    if(old.length){tree.push('<div class="grow hist"><button type="button" class="tg" data-fold="h:'+esc(nid)+'" aria-expanded="'+(!hist)+'">'+(hist?'▸':'▾')+' Lịch sử · '+old.length+' lượt cũ</button></div>');chart.push(chartRow('','hist'));
      if(!hist)old.forEach(function(r){tree.push('<div class="grow att old"><b>Lượt cũ</b><small>'+esc(r.attempt.slice(4,12))+' · thế hệ '+r.generation+'</small></div>');chart.push(chartRow(bars(r),'att old'))})}
  });
  h.push('<div class="gscroll" data-k="gscroll"><div class="gbody"><div class="gtree">'+tree.join('')+'</div><div class="gchart" data-w0="'+new Date(W.w0).toISOString()+'" data-w1="'+new Date(W.w1).toISOString()+'">'+chart.join('')+'</div></div></div><p class="gexplain">Chọn tên bước hoặc thanh để xem kết quả và bằng chứng. Mũi tên mở từng lượt; khoảng trống không chứng minh AI đang làm việc.</p></div><div class="gside" id="gside"'+(!selStep?' hidden':'')+'>'+gside(d,g)+'</div></section>');return h.join('')}
function gIsOutput(x){return x.output&&!/(^|\.)receipt$/.test(x.role||'')}
function gOutputs(list,scope,empty){var grouped={};list.forEach(function(x){(grouped[x.key]||(grouped[x.key]=[])).push(x)});var keys=Object.keys(grouped);
  return keys.length?keys.map(function(k,i){var uses=grouped[k],x=uses[0];return '<div class="goutput" data-k="g-output:'+esc(scope)+':'+esc(k)+'"><b>Đầu ra '+(i+1)+'</b>'+openOr(x)+'<details data-k="g-output-source:'+esc(scope)+':'+esc(k)+'"><summary>Nguồn · '+uses.length+' lần ghi nhận</summary>'+uses.map(function(u){return '<div class="small" data-k="evk:'+esc(u.key)+':'+u.seq+'">'+occLine(u)+'</div>'}).join('')+'</details></div>'}).join(''):'<p class="mut" id="evnone">'+empty+'</p>'}
function gside(d,g){if(!selStep)return '<span class="mut">Chọn một thanh hoặc dấu mốc (chuột hoặc Tab + Enter) để xem mốc chính xác, lý do, đầu ra và bằng chứng của bước đó.</span>';
  var P=prov(d);
  function evRows(list,empty){return list.length?list.map(occDiv).join(''):'<span class="mut small" id="evnone">'+(empty||'bước này không nêu bằng chứng')+'</span>'}
  var parts=selStep.id.split(':');
  if(parts[0]==='node'){var nid=parts.slice(1).join(':'),n=(d.nodes||{})[nid]||{},current=(g.rows||[]).filter(function(r){return r.node===nid&&(r.current||r.active)}),keys=current.map(function(r){return r.attempt}),generations=current.map(function(r){return r.generation});
    var evs=(d.evidence_index||[]).filter(function(x){return x.attempt?keys.indexOf(x.attempt)>=0:x.node===nid&&generations.indexOf(x.generation)>=0});
    var actors=((d.work||{}).actors||[]).filter(function(x){return x.role==='executed'&&x.node===nid&&x.attempt&&keys.indexOf(x.attempt)>=0});
    return '<h4>'+esc(nodeName(d,nid))+'</h4><p>'+esc(gNodeStatus(n))+'</p><p>'+esc(gNodeTime(current))+'</p><p><b>Đã thực hiện:</b> '+(actors.length?actors.map(function(a){return esc(a.actor||a.provider||'chưa rõ')+(a.model?' · '+esc(a.model):'')}).join('; '):'chưa có định danh có nguồn')+'</p><p><b>Đầu ra hiện hành</b></p>'+gOutputs(evs.filter(gIsOutput),'node:'+nid,'Chưa có đầu ra được ghi nhận cho lượt hiện hành.')+'<details data-k="g-node-source:'+esc(nid)+'"><summary>Nguồn và lượt thực hiện</summary>'+current.map(function(r){return '<p>'+esc(r.attempt)+' · thế hệ '+r.generation+' · '+esc(r.launched_at||'chưa xác định')+' → '+esc(r.settled_at||'chưa xác định')+'</p>'}).join('')+evRows(evs.filter(function(x){return !gIsOutput(x)}))+'</details>'}

  if(parts[0]==='mk'){var seq=parseInt(parts[1],10),m=null;(g.plan_marks||[]).concat.apply([],(g.rows||[]).map(function(r){return r.marks})).forEach(function(x){if(x.seq===seq)m=x});if(!m)return '<span class="mut">dấu mốc không còn trong khoảng đang xem</span>';
    var ev=(d.timeline||[]).find(function(e){return e.seq===seq}),ex=P.bySeq[seq]||[];       // exactly this event's occurrences (full history, not the loaded log)
    return '<h4>◆ '+esc(m.label)+'</h4><dl><dt>thời điểm</dt><dd>'+when(m.at)+'<br><code>'+esc(m.at)+'</code></dd><dt>sự kiện</dt><dd><code>#'+seq+' '+esc(m.kind)+'</code></dd>'+(ev?'<dt>nội dung</dt><dd>'+esc(ev.summary)+'</dd>':'<dt>nội dung</dt><dd class="mut">sự kiện cũ hơn phần nhật ký đang tải; bằng chứng bên dưới lấy từ toàn bộ lịch sử</dd>')+'</dl><div class="small"><b>Bằng chứng</b></div>'+evRows(ex)}
  var r=(g.rows||[]).find(function(x){return x.attempt===parts[1]});if(!r)return '<span class="mut">lượt không còn trong dữ liệu</span>';
  var which=parts[0],i=parseInt(parts[2],10),sg=which==='seg'?r.segments[i]:which==='wait'?r.waits[i]:which==='ver'?r.verification[i]:null;
  var inh=r.inherits||[];
  var ex=(d.evidence_index||[]).filter(function(x){if(x.attempt)return x.attempt===r.attempt;return x.node===r.node&&x.generation===r.generation});   // P2-B/R1: the occurrences of this attempt (or of its node in ITS generation); a key it also inherits stays listed: the roles coexist
  var node=(d.nodes||{})[r.node]||{},attemptStatus=r.current?gNodeStatus(node):r.active?'Đang thực hiện':'Lượt trước · '+({settled:'Đã kết thúc',failed:'Không đạt',cancelled:'Đã dừng'}[r.status]||'Trạng thái chưa xác định');
  var h='<h4>'+esc(nodeName(d,r.node))+'</h4><p>'+esc(attemptStatus)+'</p><p><b>Thực thi:</b> '+gDuration(r.execution_seconds)+'</p>';
  var outs=ex.filter(gIsOutput),rest=ex.filter(function(x){return !gIsOutput(x)});
  h+='<p><b>Đầu ra của lượt này</b></p>'+gOutputs(outs,r.attempt,r.active?'Chưa có đầu ra (đang chạy).':'Chưa có đầu ra được ghi nhận.');
  h+='<details data-k="g-attempt-source:'+esc(r.attempt)+'"><summary>Chi tiết lượt và bằng chứng</summary><p>Mã '+esc(r.attempt)+' · thế hệ '+r.generation+' · '+esc(r.status)+(r.current?' · hiện hành':r.active?'':' · lượt cũ')+'</p>';
  if(sg)h+='<div class="small"><b>'+esc(which==='seg'?segWord(sg.kind):which==='wait'?'chờ'+(sg.reason?': '+esc(sg.reason):''):'Từ đầu ra đến kết quả kiểm ('+esc(sg.result)+'), có thể gồm chờ')+'</b> '+when(sg.from)+' → '+(which==='seg'&&sg.kind==='to_now'?'hiện tại (chưa xác nhận)':when(sg.to||sg.until))+(which==='seg'&&sg.kind!=='to_now'?' · '+gDuration((tms(sg.to)-tms(sg.from))/1000):'')+'</div>';
  h+='<dl><dt>đặt chỗ</dt><dd>'+when(r.reserved_at)+'</dd><dt>bắt đầu chạy</dt><dd>'+(r.launched_at?when(r.launched_at):'chưa xác định')+'</dd><dt>kết thúc</dt><dd>'+(r.settled_at?when(r.settled_at):r.active?'đang chạy · mốc dữ liệu mới nhất '+when(r.latest_mark_at):'chưa xác định')+'</dd><dt>thực thi</dt><dd>'+gDuration(r.execution_seconds)+'</dd><dt>chờ</dt><dd>'+(r.waits.length?r.waits.map(function(w){return esc(w.reason||'')+' '+when(w.from)+' → '+(w.until?when(w.until):'chưa rõ kết thúc')}).join('; '):'không ghi nhận')+'</dd><dt>Đầu ra → kết quả kiểm</dt><dd>'+(r.verification.length?r.verification.map(function(v){return esc(v.result)+' ('+gDuration((tms(v.to)-tms(v.from))/1000)+', có thể gồm chờ)'}).join('; '):'chưa')+'</dd></dl>';
  h+='<details data-k="g-attempt-time:'+esc(r.attempt)+'"><summary>Thời điểm chính xác (ISO, có múi giờ)</summary><p>Khởi chạy: <code>'+esc(r.launched_at||'chưa xác định')+'</code></p><p>Kết thúc: <code>'+esc(r.settled_at||'chưa xác định')+'</code></p>'+(sg?'<p>Khoảng chọn: <code>'+esc(sg.from)+'</code> → <code>'+esc(sg.to||sg.until||'chưa xác định')+'</code></p>':'')+'</details>';
  if(node.phase==='held'&&r.current)h+='<div class="small" style="color:var(--blk)">bị giữ — lý do (engine): '+esc(node.reason)+'</div>';
  if(node.progress&&r.current)h+='<div class="small">quan sát gần nhất: '+esc(node.progress.status)+' '+when(node.progress.observed_at||node.progress.received_at)+(node.progress.reason?' — '+esc(node.progress.reason):'')+'</div>';
  if(r.marks.length)h+='<div class="small mut">dấu mốc: '+r.marks.map(function(m){return esc(m.label)+' '+clock(m.at)}).join(' · ')+'</div>';
  if(rest.length)h+='<div class="small" style="margin-top:4px"><b>Bằng chứng khác của lượt này</b></div>'+evRows(rest);
  if(inh.length)h+='<div class="small" style="margin-top:4px" id="inherit"><b>Kế thừa</b> <span class="mut">(hợp lệ, từ lượt trước)</span></div>'+inh.map(function(x){var o=x.source_occurrence;return '<div class="small" data-k="inh:'+esc(x.key||x.kind)+'">'+esc(x.label)+(typeof x.from_generation==='number'?' từ thế hệ '+x.from_generation:'')+(x.from_attempt?' (lượt '+esc(String(x.from_attempt).slice(4,12))+')':'')+' · nguồn <code>'+esc(x.source)+'</code>'
    +(o?' · có từ <code>#'+o.seq+' '+esc(o.kind)+'</code> <span class="mut">('+esc(o.role||'')+(typeof o.generation==='number'?', thế hệ '+o.generation:'')+(o.attempt?', lượt '+esc(String(o.attempt).slice(4,12)):'')+', '+(o.at?when(o.at):'thời điểm chưa rõ')+')</span>':(x.key&&x.source_note?' · <span class="mut">'+esc(x.source_note)+'</span>':''))
    +(x.key?openOr(x):'')+'</div>'}).join('');
  return h+'</details>'}
function repaintGantt(){var d=mine();if(!d)return;var s=snapshot();var el=document.querySelector('#detail .gantt');if(el){var t=document.createElement('div');t.innerHTML=gantt(d);el.replaceWith(t.firstChild)}restore(s)}
function snapshot(){var open={};document.querySelectorAll('#detail details[data-k]').forEach(function(x){open[x.getAttribute('data-k')]=x.open});
  var a=document.activeElement,foc=a&&a.closest&&a.closest('[data-k]'),inner=null,copy=null;
  if(a&&foc){if(a.tagName==='SUMMARY')inner='summary';else if(a.classList.contains('copy')){inner='copy';copy=a.getAttribute('data-copy')}else if(a.classList.contains('ev-open'))inner='ev-open:'+a.getAttribute('data-key');else if(a.id==='dretry')inner='dretry';else if(a.tagName==='A')inner='a'}
  var gs=document.querySelector('#detail .gscroll');
  return {open:open,focus:foc?foc.getAttribute('data-k'):null,inner:inner,copy:copy,pane:$('#detailpane').scrollTop,win:window.scrollY,gs:gs?gs.scrollLeft:0}}
function restore(s){if(!s)return;Object.keys(s.open).forEach(function(k){var x=document.querySelector('#detail details[data-k="'+k.replace(/"/g,'\\"')+'"]');if(x)x.open=s.open[k]});
  if(s.focus){var f=document.querySelector('[data-k="'+s.focus.replace(/"/g,'\\"')+'"]');if(f){var t=null;
    // the element the reader was on comes first; a <details> container only decides when nothing more precise was focused (dev8 P3: summary won over the copy button)
    if(s.inner==='copy')t=Array.prototype.find.call(f.querySelectorAll('button.copy'),function(b){return b.getAttribute('data-copy')===s.copy})||null;   // the very command, never another option's button; gone (binding lost, revision changed): the card heading below
    else if(s.inner&&s.inner.indexOf('ev-open:')===0)t=f.querySelector('.ev-open[data-key="'+s.inner.slice(8)+'"]');else if(s.inner==='dretry')t=f.querySelector('#dretry');else if(s.inner==='a')t=f.querySelector('a');
    if(!t&&(s.inner==='summary'||s.inner==='copy'||f.tagName==='DETAILS'))t=f.querySelector('summary');
    (t||f).focus({preventScroll:true})}
    else if(s.focus==='dstatus'||s.focus.indexOf('need:')===0){var tt=$('#dtitle');if(tt)tt.focus({preventScroll:true})}}   // P2: the status line is gone (the detail loaded) / the need card itself is gone (answered, new revision): the reader lands on the task heading, not at the top of the page
  var gs=document.querySelector('#detail .gscroll');if(gs&&s.gs)gs.scrollLeft=s.gs;
  $('#detailpane').scrollTop=s.pane;if(Math.abs(window.scrollY-s.win)>2)window.scrollTo(0,s.win)}
function paint(d,sel,why){var s=snapshot();detailData=d;detailFor={plan:sel.plan,project:sel.project};renderDetail(d);restore(s);if(why==='select')afterSelect()}
var listY=0;
function afterSelect(){setView();window.scrollTo(0,0);
  if(selected&&selected.focusDetail){selected.focusDetail=false;var t=$('#dtitle');if(t)t.focus({preventScroll:true})}}
function restNote(){return detailTimeouts>=DETAIL_TRIES?'trang đã thử '+DETAIL_TRIES+' lần liền, mỗi lần chờ '+DETAIL_TIMEOUT/1000+' s, và ngừng tự thử: <button type="button" id="dretry">Thử lại</button>'
  :'trang tự thử lại'+(detailTimeouts?' (lần '+(detailTimeouts+1)+'/'+DETAIL_TRIES+', mỗi lần chờ tối đa '+DETAIL_TIMEOUT/1000+' s)':' sau mỗi lần làm mới danh sách (mỗi '+(INTERVAL/1000)+' s khi kết nối tốt)')}   // P2: what happens next, said with the failure
function reading(){return detailInflight&&selected&&sameSel(detailInflight.sel,selected)?detailInflight:null}   // the read in flight for the selected task, if any
function noteHtml(){var r=reading();return r?'đang thử lại… (đã chờ <span data-live="0" data-live-at="'+r.since+'">'+hms((Date.now()-r.since)/1000)+'</span>, tối đa '+DETAIL_TIMEOUT/1000+' s)':restNote()}
function refreshNote(){var n=$('#dnote');if(n){var a=document.activeElement,inside=!!(a&&n.contains(a)),h=noteHtml();n.innerHTML=n.getAttribute('data-cap')?cap(h):h;if(inside){var ds=$('#dstatus');if(ds)ds.focus({preventScroll:true})}}dind()}   // a read started or the series was reset: the status line says so (focus stays in the status line)
function cap(s){s=String(s);return s.charAt(0).toUpperCase()+s.slice(1)}
function loadDetail(why){if(!selected)return;
  if(detailInflight&&sameSel(detailInflight.sel,selected))return;   // P2 (Codex, dev12): one read at a time for the selected task: a poll (or the same task selected again) waits for the read in flight instead of replacing it. Replacing a read slower than 20 s threw its answer away on every poll and left "đang tải" for ever; the read ends by itself: its answer, its failure or DETAIL_TIMEOUT
  if(why==='poll'&&detailTimeouts>=DETAIL_TRIES)return;             // DETAIL_TRIES reads in a row without an answer: no more automatic reads; the reader's "Thử lại", another selection or a reconnection starts again
  if(detailInflight){clearTimeout(detailInflight.timer);detailInflight.ctl.abort()}   // the read of a task no longer selected is cancelled; its answer or failure never touches the page (token + selection below)
  var token=++detailToken,sel={plan:selected.plan,project:selected.project},ctl=new AbortController(),me={token:token,sel:sel,since:Date.now(),ctl:ctl,late:false};
  me.timer=setTimeout(function(){me.late=true;ctl.abort()},DETAIL_TIMEOUT);detailInflight=me;if(detailError)refreshNote();
  function current(){return token===detailToken&&sameSel(sel,selected)}
  function settle(){clearTimeout(me.timer);if(detailInflight&&detailInflight.token===token)detailInflight=null}      // a reply OR a failure of a superseded request / a task no longer selected never touches the page
  fetch('/api/task?plan='+encodeURIComponent(sel.plan)+(sel.project?'&project_id='+encodeURIComponent(sel.project):'')+'&timeline=300',{cache:'no-store',signal:ctl.signal})
  .then(function(r){return r.text().then(function(t){var j=null;try{j=JSON.parse(t)}catch(e){}return {ok:r.ok,status:r.status,j:j}})})
  .then(function(x){settle();if(!current())return;
      if(!x.ok||!x.j||typeof x.j!=='object')return detailFailed(sel,'HTTP '+x.status+(x.j&&x.j.error?': '+x.j.error:x.ok?': trả lời không đọc được':''));
      var prev=mine(),prevFor=detailFor,prevOk=detailOkAt,prevSeq=detailSeq,prevErr=detailError,prevNotes=staleNotes.slice(),prevKnown=Object.assign({},knownNeeds),prevCopied=copied;
      try{detailLoaded(sel,x.j,why);detailTimeouts=0}catch(e){if(!current())return;                 // only an answer the page shows ends a timeout series; a reply the page cannot show: the error path with everything as it was before it, never 'đang tải' forever
        detailData=prev;detailFor=prev?prevFor:null;detailOkAt=prevOk;detailSeq=prevSeq;detailError=prevErr;staleNotes=prevNotes;knownNeeds=prevKnown;copied=prevCopied;
        detailFailed(sel,'không hiển thị được chi tiết: '+String(e&&e.message||e).slice(0,160))}},
    function(){settle();if(!current())return;
      if(me.late){detailTimeouts++;return detailFailed(sel,'quá '+DETAIL_TIMEOUT/1000+' s không có trả lời')}    // P2: the wait ends with a clear reason; after DETAIL_TRIES of these the page stops (restNote)
      detailFailed(sel,'mất kết nối khi tải chi tiết')})}     // a quick failure neither counts nor ends a timeout series (alternating hang/error stops too)
function detailLoaded(sel,j,why){var had=mine(),wasErr=!!detailError,seq=j.source&&j.source.last_seq;detailError=null;detailOkAt=Date.now();
  if(had&&!wasErr&&why!=='select'&&why!=='force'&&seq===detailSeq&&had.selector===j.selector&&had.project_id===j.project_id&&needsSig(had)===needsSig(j)){detailData=j;if(j.gantt&&j.gantt.axis&&(j.gantt.axis.extends_to_now||$('#gstale')))repaintGantt();dind();return}   // nothing moved in the ledger: keep what the reader is looking at; only the server clock parts of the timeline move (P2-A)
  detailSeq=seq;paint(j,sel,had?why:'select');dind()}      // recovery from a stale state re-renders once (warning and template marks go; snapshot/restore keep the reader's place)
function detailFailed(sel,msg){var now=Date.now(),note=restNote(),changed=!detailError||detailError.message!==msg||detailError.note!==note,d=mine(),s;   // a new retry state (try 2/3, stopped) is shown too
  detailError={since:detailError?detailError.since:now,last:now,message:msg,note:note};
  if(d){if(changed){s=snapshot();renderDetail(d);restore(s)}else{var l=$('#dlast');if(l)l.textContent=clockMs(now)}}     // the task already shown: its data stays, marked stale
  else if(changed||!$('#dstatus')||$('#dstatus').getAttribute('data-state')!=='error'){s=snapshot();pendingPane(sel);restore(s)}   // never loaded: its own heading + the error, nothing else
  else{var l2=$('#dlast');if(l2)l2.textContent=clockMs(now)}
  dind()}
function select(sel,opts){opts=opts||{};if(!sel){if(detailInflight){clearTimeout(detailInflight.timer);detailInflight.ctl.abort();detailInflight=null}   // closing cancels the read: selecting the task again starts a fresh one (never a nearly expired one)
    if(selected){lastViewed=selected}selected=null;selEv=null;evState={};copied=null;detailData=null;detailFor=null;detailError=null;detailOkAt=null;detailSeq=null;detailTimeouts=0;$('#detail').innerHTML='<div id="nodetail">Chọn một task ở danh sách để xem chi tiết, timeline và bằng chứng.</div>';setView();render(true);dind();window.scrollTo(0,listY);
    if(!opts.silent&&location.search)history.pushState({},'',location.pathname);return}
  var other=!sameSel(selected,sel);if(other)workTab='overview';detailTimeouts=0;if(!selected)listY=window.scrollY;      // a click on a task (the same one too) is the reader asking again: a new series of tries
  if(other){selEv=null;evState={};copied=null;detailSeq=null;selStep=null;gRange='current';gPinnedWindow=null;gFold={};staleNotes=[];knownNeeds={};detailData=null;detailFor=null;detailError=null;detailOkAt=null;detailTimeouts=0}
  selected={plan:sel.plan,project:sel.project||'',focusDetail:!!opts.focusDetail};setView();render(true);
  if(!mine()){pendingPane(selected);afterSelect()}dind();     // another task: its heading + "đang tải" at once, never the previous task's content
  if(!opts.silent&&location.search!==urlOf(selected))history.pushState({plan:selected.plan,project:selected.project},'',urlOf(selected));
  loadDetail('select')}
function poll(){var ctl=new AbortController(),late=false,tm=setTimeout(function(){late=true;ctl.abort()},OVERVIEW_TIMEOUT);   // P2 (found with it): an overview read that never answers no longer freezes the page under a green badge
  fetch('/api/overview',{cache:'no-store',signal:ctl.signal}).then(function(r){return r.json()}).then(function(j){
    if(j.error&&!j.source){j.source={status:'lỗi',detail:j.error,ledger:''};j.projects=last?last.projects:[];j.untracked=last?last.untracked:{}}
    last=j;lastOk=Date.now();if(lostSince)detailTimeouts=0;lostSince=null;var s=j.source||{};    // reconnected: the detail of the selection is read again (a new, bounded series of tries)
    if(s.status!=='ok'){conn('src','NGUỒN '+(s.status||'?')+': '+(s.detail||''))}else{conn('ok','kết nối OK · dữ liệu lúc '+new Date(j.generated_at).toLocaleTimeString()+' · seq '+s.last_seq+' · đọc '+(j.server&&j.server.read_ms)+' ms')}
    $('#src').textContent='Sổ: '+(s.ledger||'')+' · poll '+(INTERVAL/1000)+' s · wheel '+(j.server&&j.server.version||'?');render();if(selected)loadDetail('poll');
  }).catch(function(e){if(!last)$('#empty').textContent='Chưa đọc được sổ: mất kết nối với server theo dõi; trang tự thử lại.';if(!lostSince){lostSince=new Date();repaintGantt()}conn('bad','MẤT KẾT NỐI với server theo dõi từ '+lostSince.toLocaleTimeString()+(late?' (không trả lời trong '+OVERVIEW_TIMEOUT/60000+' phút)':'')+(lastOk?' — đang hiện dữ liệu cũ lúc '+new Date(lastOk).toLocaleTimeString():' — chưa có dữ liệu')+'; worker không bị ảnh hưởng; trang tự thử lại')})
  .then(function(){clearTimeout(tm);setTimeout(poll,INTERVAL)})}
function copyText(text,k){var c=copied={k:k,text:text,ok:false};var sel0=selected;     // c: this copy's own record (copied is reset when the selection changes)
  function current(){return copied===c&&sameSel(selected,sel0)&&copiedStillValid(c,mine())}   // dev9 P2 (Codex): only the attempt the page still holds acts on its result. A newer copy, another task (even after coming back), a lost binding or a new revision/command in the CURRENT data makes it stale: its late result starts no fallback write and changes nothing (a clipboard call already sent to the browser cannot be taken back)
  function done(){var d=mine();if(!d||!sameSel(selected,sel0))return;var s=snapshot();renderDetail(d);restore(s)}   // dev8 P3: the reader's place when the result lands (focus, sections, scroll), not at the click: a late result never pulls them back
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(text).then(function(){if(!current())return;c.ok=true;done()},function(){if(!current())return;c.ok=fallback();done()})}else{c.ok=fallback();done()}
  function fallback(){var was=document.activeElement,ta=document.createElement('textarea'),ok=false;ta.value=text;ta.setAttribute('readonly','');ta.style.position='fixed';ta.style.left='-1000px';document.body.appendChild(ta);ta.select();try{ok=document.execCommand('copy')===true}catch(e){ok=false}document.body.removeChild(ta);if(was&&was.focus)was.focus({preventScroll:true});return ok}}
function openEvidence(key,btn){var d0=mine(),sel0=selected;if(!d0)return;if(evState[key]){delete evState[key];var s=snapshot();renderDetail(d0);restore(s);return}
  function show(text){var d=mine();if(!d||!sameSel(selected,sel0))return;evState[key]={text:text};var s=snapshot();renderDetail(d);restore(s)}   // a late blob of a task no longer selected is dropped
  btn.textContent='đang tải…';fetch(evHref(key).replace('&format=text',''),{cache:'no-store'}).then(function(r){return r.json().then(function(j){return [r.ok,j]})}).then(function(x){
    show(x[0]?x[1].text:'không mở được: '+(x[1].error||''))}).catch(function(){show('không mở được (mất kết nối)')})}
document.addEventListener('click',function(ev){var t=ev.target;
  if(t.id==='dretry'){detailTimeouts=0;loadDetail('retry');return}   // P2: the reader starts a new, bounded series of tries (the status line then says "đang thử lại…" and keeps the focus)
  var li=t.closest&&t.closest('li.task');if(li){select({plan:li.dataset.plan,project:li.dataset.project});return}
  if(t.id==='back'||t.id==='close'){var k=selected;select(null);var again=k&&document.querySelector('[data-k="task:'+k.project+':'+k.plan+'"]');if(again)again.focus();return}
  if(t.classList&&t.classList.contains('copy')){var ck=t.closest('.need').getAttribute('data-k'),ct=t.getAttribute('data-copy'),cd=mine();
    if(!cd||!copiedStillValid({k:ck,text:ct},cd)){if(cd){var cs=snapshot();renderDetail(cd);restore(cs)}return}   // R7-1: a card painted before the data changed never copies a command the latest data no longer offers
    copyText(ct,ck);return}
  if(t.classList&&t.classList.contains('chip')){var ck2=t.getAttribute('data-kind');$('#kind').value=$('#kind').value===ck2?'':ck2;render(true);return}
  var lm=t.closest&&t.closest('[data-list-mode]');if(lm){setMode(lm.getAttribute('data-list-mode'));lm.focus({preventScroll:true});return}
  if(t.id==='fclear'){$('#kind').value='';$('#proj').value='';$('#q').value='';render(true);var qq=$('#q');if(qq)qq.focus({preventScroll:true});return}
  var wt=t.closest&&t.closest('[data-work-tab]');if(wt){workTab=wt.getAttribute('data-work-tab');var wd=mine();if(wd){var ws=snapshot();renderDetail(wd);restore(ws);var wb=document.querySelector('[data-work-tab="'+workTab+'"]');if(wb){wb.focus({preventScroll:true});if(workTab==='progress')wb.closest('.work-nav').scrollIntoView({block:'start'})}}return}
  if(t.classList&&t.classList.contains('stale-hide')){var key=t.getAttribute('data-key');staleNotes=staleNotes.filter(function(x){return x.key!==key});var d0=mine();if(d0){var s0=snapshot();renderDetail(d0);restore(s0)}return}
  if(t.classList&&t.classList.contains('tg')){var fk=t.getAttribute('data-fold');if(fk.indexOf('h:')===0){gFold[fk]=gFold[fk]===false?true:false;if(gFold[fk]===false&&gRange==='current'){gRange='all';gPinnedWindow=null;var hd=mine();if(hd){gPinnedWindow=gWindow(hd.gantt);if(gPinnedWindow)gPinnedWindow.range='all'}}}else gFold[fk]=gFold[fk]===false?true:false;repaintGantt();var b=document.querySelector('[data-fold="'+fk+'"]');if(b)b.focus({preventScroll:true});return}
  if(t.id==='gfit'){gPinnedWindow=null;gRange='current';gFold={};repaintGantt();var fit=$('#gfit');if(fit)fit.focus({preventScroll:true});return}
  var ns=t.closest&&t.closest('[data-node-select]');if(ns){var nk='node:'+ns.getAttribute('data-node-select');selStep=selStep&&selStep.id===nk?null:{id:nk};repaintGantt();var nb=document.querySelector('[data-k="'+nk.replace(/"/g,'\\"')+'"]');if(nb)nb.focus({preventScroll:true});return}
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
  if(ev.key==='Escape'&&selected&&!(t.closest&&t.closest('input,select,textarea'))){ev.preventDefault();var k=selected;select(null);var again=document.querySelector('[data-k="task:'+k.project+':'+k.plan+'"]');if(again)again.focus()}
});
document.addEventListener('change',function(ev){if(ev.target&&ev.target.id==='grange'){gRange=ev.target.value;gPinnedWindow=null;var gd=mine();if(gRange==='all'&&gd){(gd.gantt.rows||[]).forEach(function(r){gFold['n:'+r.node]=false;gFold['h:'+r.node]=false});gPinnedWindow=gWindow(gd.gantt);if(gPinnedWindow)gPinnedWindow.range=gRange}repaintGantt()}});
document.addEventListener('toggle',function(ev){if(ev.target&&ev.target.classList&&ev.target.classList.contains('need'))needs_open_sync()},true);
$('#sort').addEventListener('change',function(){render(true)});
$('#q').addEventListener('input',function(){render(true)});$('#kind').addEventListener('change',function(){render(true)});
$('#proj').addEventListener('change',function(){var v=$('#proj').value;if(selected&&v&&selected.project){var t=tasks().filter(function(x){return x.project===v&&x.project_id===selected.project});if(!t.length){select(null);$('#detail').innerHTML='<div id="nodetail">Đã đổi sang project '+esc(short(v))+': chọn một task của project này.</div>'}}render(true)});
window.addEventListener('popstate',function(){var qs=new URLSearchParams(location.search);if(qs.get('plan'))select({plan:qs.get('plan'),project:qs.get('project_id')||''},{silent:true});else select(null,{silent:true})});
window.matchMedia('(max-width:899px)').addEventListener('change',setView);
if(!window.matchMedia('(max-width:760px)').matches)$('#filters').open=true;   // desktop: the filters are open; phone: folded, the active ones are listed under the search
setInterval(tick,1000);
var qs=new URLSearchParams(location.search);if(qs.get('plan'))select({plan:qs.get('plan'),project:qs.get('project_id')||''},{silent:true});
poll();
window.__track={state:function(){return {selected:selected,detailSeq:detailSeq,selEv:selEv,evOpen:Object.keys(evState),copied:copied,lastOk:lastOk,lost:!!lostSince,selStep:selStep,gRange:gRange,stale:staleNotes.map(function(x){return x.id}),axisNow:mine()&&mine().gantt&&mine().gantt.axis?mine().gantt.axis.now:null,
  detailFor:mine()?{plan:detailFor.plan,project:detailFor.project}:null,detailState:detailState(),detailError:detailError?{since:iso(detailError.since),last:iso(detailError.last),message:detailError.message}:null,detailOkAt:iso(detailOkAt),
  detailTimeouts:detailTimeouts,detailInflight:detailInflight?{plan:detailInflight.sel.plan,since:iso(detailInflight.since)}:null}}};   // read-only inspection for tests; no control
})();
</script></body></html>
'''

# Keep the adapter separately testable; it shares the existing read-only evidence door.
from .tracking_work_web import SCRIPT as _WORK_SCRIPT, STYLE as _WORK_STYLE
PAGE = PAGE.replace('@@WORK_SCRIPT@@', _WORK_SCRIPT).replace('@@WORK_STYLE@@', _WORK_STYLE)
