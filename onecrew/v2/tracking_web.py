"""OBS-1: the local read-only tracking page (stdlib http.server on 127.0.0.1) over onecrew/v2/tracking.py.

GET only: `/` (the page, one file, no external resource), `/api/health`, `/api/overview`, `/api/task?plan=…`, `/api/evidence?plan=…&key=…`.
Any other method is 405: the page has no control, and no request here can approve, answer, pause or resume a task. Each request reads the ledger
anew (sqlite read-only, no transaction kept between polls), so the page rebuilds from the durable source on every poll: a reconnect, a reopened
tab or a restarted server shows the same truth without a cursor to lose and without duplicating an event (the ledger's seq is the identity).

Closing the page or the server never stops a worker: workers are other processes that do not know this one exists. The server started by
`track open` runs detached and exits by itself after `idle_exit` seconds without a request.
"""
import json
import os
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


def _page(interval):
    return PAGE.replace('@@INTERVAL@@', str(int(max(0.5, float(interval)) * 1000)))


def make_server(state_root, *, host='127.0.0.1', port=0, project_id=None, interval=2.0, idle_exit=None):
    state_root = Path(state_root).resolve()
    stats = {'requests': 0, 'last_read_ms': None, 'last_request': time.monotonic(), 'started_at': utcnow(), 'errors': 0}
    page = _page(interval).encode('utf-8')

    class Handler(BaseHTTPRequestHandler):
        server_version = 'OneCrewTrack/1'
        protocol_version = 'HTTP/1.1'

        def log_message(self, format, *args):      # quiet: the console is the owner's, not a request log
            pass

        def _send(self, status, body, content_type='application/json; charset=utf-8'):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, default=str).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self'")
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
                    return self._send(HTTPStatus.OK, {'ok': True, 'pid': os.getpid(), 'generated_at': utcnow(), 'state_root': str(state_root), 'poll_seconds': interval,
                                                      'project_id': project_id, 'read_only': True, **{k: stats[k] for k in ('requests', 'last_read_ms', 'started_at', 'errors')}})
                if url.path == '/api/overview':
                    started = time.perf_counter()
                    value = tracking.overview(state_root, project_id=scope)
                    stats['last_read_ms'] = round((time.perf_counter() - started) * 1000, 1)
                    value['server'] = {'pid': os.getpid(), 'read_ms': stats['last_read_ms'], 'poll_seconds': interval, 'started_at': stats['started_at'], 'requests': stats['requests']}
                    return self._send(HTTPStatus.OK, value)
                if url.path == '/api/task':
                    if not q.get('plan'): return self._send(HTTPStatus.BAD_REQUEST, {'error': 'thiếu plan'})
                    limit = int(q.get('timeline') or 200)
                    if not 1 <= limit <= 5000: return self._send(HTTPStatus.BAD_REQUEST, {'error': 'timeline: 1-5000'})
                    started = time.perf_counter()
                    value = tracking.detail(state_root, q['plan'], project_id=scope, timeline_limit=limit)
                    value['server'] = {'pid': os.getpid(), 'read_ms': round((time.perf_counter() - started) * 1000, 1), 'poll_seconds': interval}
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


def serve(state_root, *, host='127.0.0.1', port=0, project_id=None, interval=2.0, announce=None, idle_exit=None):
    """Run in this process until Ctrl+C. Prints one JSON line with the URL first; with `announce`, also writes it to that marker file."""
    server = make_server(state_root, host=host, port=port, project_id=project_id, interval=interval, idle_exit=idle_exit)
    record = {'url': url_of(server), 'pid': os.getpid(), 'state_root': str(Path(state_root).resolve()), 'project_id': project_id, 'poll_seconds': interval,
              'read_only': True, 'started_at': utcnow(), 'note': 'Ctrl+C hay đóng cửa sổ này chỉ đóng trang theo dõi; worker không dừng.'}
    print(json.dumps(record, ensure_ascii=False), flush=True)
    if announce:
        path = Path(announce); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if announce:
            try: Path(announce).unlink()
            except OSError: pass
    return 0


def _alive(url):
    try:
        with urllib.request.urlopen(url + 'api/health', timeout=1.5) as r:
            return json.loads(r.read().decode('utf-8')).get('ok') is True
    except (OSError, ValueError):
        return False


def open_page(state_root, *, host='127.0.0.1', port=0, project_id=None, interval=2.0, project=None, explicit_state_root=None, idle_exit=1800, browser=True):
    """Reuse a live detached server of this state root (its marker answers /api/health) or start one, then open the page in the default browser."""
    state_root = Path(state_root).resolve()
    marker = state_root / MARKER
    if marker.exists():
        try:
            old = json.loads(marker.read_text(encoding='utf-8'))
            if old.get('project_id') == project_id and _alive(old['url']):
                if browser:
                    import webbrowser; webbrowser.open(old['url'])
                return dict(old, reused=True)
        except (OSError, ValueError, KeyError):
            pass
    args = [sys.executable, '-X', 'utf8', '-m', 'onecrew.v2.tracking_cli', '--project', str(project or Path.cwd())]
    if explicit_state_root is not None: args += ['--state-root', str(explicit_state_root)]
    else: args += ['--state-root', str(state_root)]
    args += ['track', 'serve', '--host', host, '--port', str(port), '--interval', str(interval), '--announce', str(marker)]
    if project_id: args.append('--project-only')
    flags = (subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, 'DETACHED_PROCESS', 0)) if os.name == 'nt' else 0
    env = dict(os.environ, ONECREW_TRACK_IDLE_EXIT=str(idle_exit))
    if marker.exists():
        try: marker.unlink()
        except OSError: pass
    child = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, creationflags=flags, env=env)
    end = time.monotonic() + 8
    while time.monotonic() < end:
        if marker.exists():
            try:
                record = json.loads(marker.read_text(encoding='utf-8'))
                if _alive(record['url']):
                    if browser:
                        import webbrowser; webbrowser.open(record['url'])
                    return dict(record, reused=False, idle_exit_seconds=idle_exit)
            except (OSError, ValueError, KeyError):
                pass
        if child.poll() is not None:
            return {'error': 'server theo dõi thoát ngay khi khởi động', 'exit_code': child.returncode}
        time.sleep(0.1)
    return {'error': 'server theo dõi không trả lời trong 8 giây', 'pid': child.pid}


PAGE = r'''<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>OneCrew — theo dõi (chỉ đọc)</title>
<style>
:root{--bg:#f6f7f9;--fg:#1d2330;--mut:#5c6675;--card:#fff;--line:#dfe3ea;--run:#1d6fd6;--wait:#b7791f;--blk:#c53030;--done:#2f855a;--unk:#718096;--need:#fff3cd}
@media (prefers-color-scheme:dark){:root{--bg:#141820;--fg:#e6e9ef;--mut:#9aa4b2;--card:#1c2230;--line:#2c3545;--need:#3b3415}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,Segoe UI,sans-serif}
header{padding:10px 16px;border-bottom:1px solid var(--line);background:var(--card);display:flex;gap:16px;align-items:center;flex-wrap:wrap}
h1{font-size:16px;margin:0}#conn{padding:3px 8px;border-radius:12px;font-size:12px;border:1px solid var(--line)}
#conn.ok{background:#e6f4ea;color:#1e4620}#conn.bad{background:#fde2e2;color:#7a1f1f}#conn.src{background:#fff3cd;color:#5c4400}
main{display:grid;grid-template-columns:1fr;gap:12px;padding:12px 16px}
section{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;min-width:0}
h2{font-size:14px;margin:0 0 8px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;vertical-align:top;padding:5px 6px;border-top:1px solid var(--line)}th{color:var(--mut);font-weight:600;border-top:0}
tr.task{cursor:pointer}tr.task:hover{background:rgba(120,140,180,.08)}tr.sel{outline:2px solid var(--run)}
.st{display:inline-block;padding:1px 7px;border-radius:10px;color:#fff;font-size:12px;white-space:nowrap}
.st.running{background:var(--run)}.st.waiting{background:var(--wait)}.st.blocked{background:var(--blk)}.st.done{background:var(--done)}.st.unknown{background:var(--unk)}
.mut{color:var(--mut)}.need{background:var(--need);padding:6px 8px;border-radius:6px;margin:4px 0}.small{font-size:12px}
.tl{list-style:none;margin:0;padding:0;max-height:60vh;overflow:auto}.tl li{padding:4px 0;border-top:1px solid var(--line)}.tl .stale{opacity:.6}
code{font-size:12px;background:rgba(120,140,180,.12);padding:0 4px;border-radius:3px}
input,select{font:inherit;padding:3px 6px;border:1px solid var(--line);border-radius:4px;background:var(--card);color:var(--fg)}
details{margin:4px 0}summary{cursor:pointer;color:var(--mut)}
#empty{padding:8px;color:var(--mut)}
</style></head><body>
<header><h1>OneCrew — theo dõi (chỉ đọc)</h1><span id="conn">đang kết nối…</span><span id="src" class="small mut"></span>
<label class="small">project <select id="proj"><option value="">tất cả</option></select></label>
<input id="q" placeholder="lọc theo plan / mục tiêu" size="28">
<span class="small mut">Không có nút điều khiển: đọc hay mở bằng chứng không duyệt, không trả lời, không dừng task.</span></header>
<main>
<section><h2>Danh sách công việc</h2><div id="empty"></div>
<table id="list"><thead><tr><th>Trạng thái</th><th>Plan · project</th><th>Mục tiêu</th><th>Đầu ra</th><th>Đã chạy</th><th>Cập nhật / bằng chứng cuối</th><th>Cần bạn</th></tr></thead><tbody></tbody></table>
<h2 style="margin-top:14px">Chưa được theo dõi</h2><div id="untracked" class="small"></div></section>
<section id="detail"><h2>Chi tiết và timeline</h2><div class="mut">Chọn một plan ở danh sách.</div></section>
</main>
<script>
(function(){
var INTERVAL=@@INTERVAL@@, last=null, lastOk=null, lostSince=null, selected=null, selProject=null, detailTimer=null;
var $=function(s){return document.querySelector(s)};
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function hms(s){if(typeof s!=='number')return 'chưa xác định';s=Math.floor(s);var h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=s%60;return h?h+'h'+String(m).padStart(2,'0')+'m':m+'m'+String(x).padStart(2,'0')+'s'}
function when(t){if(!t)return '—';var d=new Date(t);return isNaN(d)?esc(t):d.toLocaleTimeString()+' '+d.toLocaleDateString()}
function st(k,l){return '<span class="st '+esc(k)+'">'+esc(l)+'</span>'}
function elapsed(t){var s=t.elapsed&&t.elapsed.seconds;if(typeof s!=='number')return 'chưa xác định';
  if(t.status.kind!=='done'&&lastOk)s+= (Date.now()-lastOk)/1000; return hms(s)}
function conn(cls,text){var c=$('#conn');c.className=cls;c.textContent=text}
function render(){
  if(!last)return;var tb=$('#list tbody'),rows=[],q=($('#q').value||'').toLowerCase();
  var ps=$('#proj');var cur=ps.value;var opts='<option value="">tất cả</option>';
  (last.projects||[]).forEach(function(p){opts+='<option value="'+esc(p.path)+'"'+(p.path===cur?' selected':'')+'>'+esc(p.path)+'</option>'});ps.innerHTML=opts;
  (last.projects||[]).forEach(function(p){if(cur&&p.path!==cur)return;p.tasks.forEach(function(t){
    if(q&&((t.plan||'')+' '+(t.goal||'')).toLowerCase().indexOf(q)<0)return;
    var need=(t.needs_user||[]).map(function(n){return '<div class="need">'+esc(n.question||n.kind)+(n.reply_command?'<br><code>'+esc(n.reply_command)+'</code>':'')+'</div>'}).join('');
    var lu=t.last_update?when(t.last_update.at)+' <span class="mut">#'+t.last_update.seq+' '+esc(t.last_update.summary)+'</span>':'—';
    var le=t.last_evidence?'<br><span class="small">bằng chứng: '+when(t.last_evidence.at)+' '+esc(t.last_evidence.label)+' <span class="mut">('+esc(t.last_evidence.provenance)+')</span></span>':'<br><span class="small mut">chưa có bằng chứng</span>';
    var act=(t.active||[]).map(function(a){return '<div class="small">attempt <code>'+esc(a.attempt)+'</code> ['+esc(a.status)+']'+(a.node?' node '+esc(a.node):'')+'</div>'}).join('');
    rows.push('<tr class="task'+(selected&&selected.plan===t.selector&&selected.project===t.project_id?' sel':'')+'" data-plan="'+esc(t.selector)+'" data-project="'+esc(t.project_id)+'">'
      +'<td>'+st(t.status.kind,t.status.label)+'<div class="small mut">'+esc(t.status.reason)+'</div>'+act+'</td>'
      +'<td><b>'+esc(t.plan)+'</b><div class="small mut">'+esc(t.project)+'<br>'+esc(t.id.slice(0,12))+' · '+esc(t.tracking.adapter)+(t.tracking.errors&&t.tracking.errors.length?' · lỗi đọc':'')+'</div></td>'
      +'<td class="small">'+esc(t.goal||'')+'</td><td class="small">'+esc(t.level.label)+'</td><td class="small">'+elapsed(t)+'</td>'
      +'<td class="small">'+lu+le+'</td><td class="small">'+(need||'<span class="mut">không</span>')+'</td></tr>')})});
  tb.innerHTML=rows.join('');$('#empty').textContent=rows.length?'':'Không có plan nào trong phạm vi này.';
  var u=last.untracked||{},parts=['<div>'+esc(u.statement||'')+'</div>'];
  (u.other_tasks||[]).slice(0,10).forEach(function(o){parts.push('<div>· task <code>'+esc(o.id.slice(0,12))+'</code> '+esc(o.key)+' phase '+esc(o.phase)+' — '+esc(o.note)+'</div>')});
  (u.registry_projects_without_plan||[]).slice(0,10).forEach(function(r){parts.push('<div>· '+esc(r.project)+' — '+esc(r.note)+'</div>')});
  (u.hook_sessions||[]).slice(0,10).forEach(function(s){parts.push('<div>· phiên hook '+esc(s.session)+' @ '+esc(s.project)+' — '+esc(s.note)+'</div>')});
  $('#untracked').innerHTML=parts.join('');
}
function renderDetail(d){
  var h=['<h2>Chi tiết và timeline — '+esc(d.plan)+' <span class="mut small">'+esc(d.id)+'</span></h2>'];
  h.push('<div>'+st(d.status.kind,d.status.label)+' '+esc(d.status.reason)+' <span class="small mut">['+esc((d.status.source||[]).join(', '))+']</span></div>');
  h.push('<div class="small">Mức đầu ra: <b>'+esc(d.level.label)+'</b> · root: '+esc(d.root_status)+' · đã chạy: '+elapsed(d)+' <span class="mut">('+esc(d.elapsed.basis)+')</span></div>');
  if(d.goal)h.push('<div class="small">Mục tiêu: '+esc(d.goal)+'</div>');
  (d.needs_user||[]).forEach(function(n){h.push('<div class="need">CẦN BẠN: '+esc(n.question||n.kind)+(n.reply_command?'<br><code>'+esc(n.reply_command)+'</code>':'')+'<br><span class="small mut">'+esc(n.note||'')+'</span></div>')});
  h.push('<div class="small">ETA: '+esc(d.eta.label)+(d.eta.reason?' — '+esc(d.eta.reason):'')+(d.eta.deadline?' · deadline '+when(d.eta.deadline):'')+(typeof d.eta.wall_clock_remaining_seconds==='number'?' · còn '+hms(d.eta.wall_clock_remaining_seconds)+' lịch':'')+'</div>');
  h.push('<div class="small">Attempt (union): '+hms(d.measure.attempts_wall_seconds)+' · chờ (union): '+hms(d.measure.wait_seconds)+(d.measure.rework?' · làm lại: resumed '+d.measure.rework.resumed+', kiểm hỏng '+d.measure.rework.verification_failed+', giữ lại '+d.measure.rework.retained:'')+'</div>');
  var ns=Object.keys(d.nodes||{});if(ns.length){h.push('<table><thead><tr><th>Node</th><th>Thế hệ</th><th>Pha</th><th>Đầu ra</th><th>Attempt</th><th>Quan sát</th></tr></thead><tbody>');
    ns.forEach(function(id){var n=d.nodes[id],p=n.progress;h.push('<tr><td><b>'+esc(id)+'</b>'+(n.phase==='held'?'<div class="small" style="color:var(--blk)">giữ: '+esc(n.reason)+'</div>':'')+'</td><td>'+n.generation+(n.continues?' <span class="small mut">tiếp từ '+esc(n.continues)+'</span>':'')+'</td><td>'+esc(n.phase)+'</td><td>'+esc(n.state)+(n.verification_result?' ('+esc(n.verification_result)+')':'')+'</td><td class="small"><code>'+esc(n.attempt||'—')+'</code>'+(n.child?'<br>con '+esc(n.child.slice(0,12)):'')+'</td><td class="small">'+(p?esc(p.status)+' '+when(p.observed_at||p.received_at)+(p.reason?'<br>'+esc(p.reason):''):'—')+'</td></tr>')});h.push('</tbody></table>')}
  if((d.attempts||[]).length){h.push('<details><summary>Attempt ('+d.attempts.length+')</summary><table><thead><tr><th>Attempt</th><th>Trạng thái</th><th>Thế hệ</th><th>Đơn vị</th><th>Từ</th><th>Cập nhật</th></tr></thead><tbody>');
    d.attempts.forEach(function(a){h.push('<tr><td><code>'+esc(a.id)+'</code></td><td>'+esc(a.status)+'</td><td>'+a.generation+'</td><td>'+esc(a.unit)+'</td><td class="small">'+when(a.created_at)+'</td><td class="small">'+when(a.updated_at)+'</td></tr>')});h.push('</tbody></table></details>')}
  var ow=(d.waits||[]).filter(function(w){return w.open}),cw=(d.waits||[]).filter(function(w){return !w.open});
  if(ow.length){h.push('<div class="small"><b>Đang chờ:</b> '+ow.map(function(w){return esc(w.reason||'không rõ')+' từ '+when(w.since)+' ('+esc(w.source)+')'}).join('; ')+'</div>')}
  if(cw.length){h.push('<div class="small mut"><b>Đã chờ (lịch sử):</b> '+cw.map(function(w){return esc(w.reason||'không rõ')+' '+when(w.since)+' → '+(w.until==='unknown'?'chưa rõ kết thúc':when(w.until))+' ('+esc(w.source)+')'}).join('; ')+'</div>')}
  if((d.holds||[]).length){h.push('<div class="small"><b>Giữ (finding):</b> '+d.holds.map(function(x){return esc(x.text||x.error)}).join('; ')+'</div>')}
  if((d.notices||[]).length){h.push('<details><summary>Thông báo ('+d.notices.length+')</summary>'+d.notices.map(function(n){return '<div class="small">'+when(n.at)+' '+esc(n.category)+': '+esc(n.reason)+(n.user_action?' — '+esc(n.user_action):'')+'</div>'}).join('')+'</details>')}
  if((d.evidence_keys||[]).length){h.push('<details><summary>Bằng chứng ('+d.evidence_keys.length+' blob, lọc bí mật, chỉ đọc)</summary>'+d.evidence_keys.map(function(k){return '<div class="small"><a target="_blank" href="/api/evidence?plan='+encodeURIComponent(d.selector)+'&project_id='+encodeURIComponent(d.project_id)+'&key='+k+'&format=text">'+k.slice(0,16)+'…</a></div>'}).join('')+'</details>')}
  h.push('<h2 style="margin-top:10px">Timeline ('+d.timeline.length+'/'+d.timeline_total+', cũ → mới)</h2><ul class="tl">');
  d.timeline.slice().reverse().forEach(function(e){h.push('<li'+(e.stale_generation?' class="stale"':'')+'><span class="mut small">#'+e.seq+' '+when(e.at)+(e.observed_at&&e.observed_at!==e.at?' (quan sát '+when(e.observed_at)+')':'')+(e.task!=='root'?' con':'')+'</span> <code>'+esc(e.kind)+'</code> '+esc(e.summary)+(e.stale_generation?' <b class="small">[thế hệ cũ: không đổi trạng thái]</b>':'')+'</li>')});
  h.push('</ul>');$('#detail').innerHTML=h.join('');
}
function loadDetail(){if(!selected)return;fetch('/api/task?plan='+encodeURIComponent(selected.plan)+(selected.project?'&project_id='+encodeURIComponent(selected.project):'')+'&timeline=200',{cache:'no-store'}).then(function(r){return r.json().then(function(j){return [r.ok,j]})}).then(function(x){if(x[0])renderDetail(x[1]);else $('#detail').innerHTML='<h2>Chi tiết</h2><div style="color:var(--blk)">'+esc(x[1].error||'lỗi')+'</div>'}).catch(function(){})}
function poll(){fetch('/api/overview',{cache:'no-store'}).then(function(r){return r.json()}).then(function(j){
    if(j.error&&!j.source){j.source={status:'lỗi',detail:j.error,ledger:''};j.projects=last?last.projects:[];j.untracked=last?last.untracked:{}}
    last=j;lastOk=Date.now();lostSince=null;var s=j.source||{};
    if(s.status!=='ok'){conn('src','NGUỒN '+(s.status||'?')+': '+(s.detail||''))}else{conn('ok','kết nối OK · dữ liệu lúc '+new Date(j.generated_at).toLocaleTimeString()+' · seq '+s.last_seq+' · đọc '+(j.server&&j.server.read_ms)+' ms')}
    $('#src').textContent='sổ: '+(s.ledger||'')+' · poll '+(INTERVAL/1000)+' s';render();if(selected)loadDetail();
  }).catch(function(e){if(!lostSince)lostSince=new Date();conn('bad','MẤT KẾT NỐI với server theo dõi từ '+lostSince.toLocaleTimeString()+(lastOk?' — đang hiện dữ liệu cũ lúc '+new Date(lastOk).toLocaleTimeString():' — chưa có dữ liệu')+'; worker không bị ảnh hưởng')})
  .then(function(){setTimeout(poll,INTERVAL)})}
$('#list').addEventListener('click',function(ev){var tr=ev.target.closest('tr.task');if(!tr)return;selected={plan:tr.dataset.plan,project:tr.dataset.project};render();loadDetail()});
$('#q').addEventListener('input',render);$('#proj').addEventListener('change',render);
setInterval(function(){if(last&&!lostSince)render()},1000);
var qs=new URLSearchParams(location.search);if(qs.get('plan')){selected={plan:qs.get('plan'),project:qs.get('project_id')||''};loadDetail()}
poll();
})();
</script></body></html>
'''
