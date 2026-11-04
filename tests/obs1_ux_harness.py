"""OBS-1 interaction harness: the real tracking page, driven in a real headless Chrome/Edge by a same-origin harness page.

`Proxy(target_url, on_signal=None)` serves `/__ux?s=<scenario>` (the harness page) and forwards every other path to the tracking server, so the
harness and the page share one origin and the harness can click, type, focus, scroll, reload and read the page in its iframe exactly as a
user would; `/__signal?name=…` calls `on_signal(name)` in the Python process (a ledger write while the reader is looking); `/__drop?on=1|0`
makes the proxy drop `/api/*` connections (the disconnected state); `/__fault?detail=drop|error|ok[&plan=<selector>][&delay=<ms>]` (TEST ONLY,
answered by the proxy and never by the product server) faults only `/api/task` (of that plan when `plan` is given), optionally after a delay:
`drop` closes the connection, `error` answers 503 JSON, `ok` forwards; `/__fault?status=1` reports the faulted/delayed requests answered so far. `run(browser, proxy_url, scenario, width, height, profile, budget)` runs one
scenario with the page laid out at that size (the harness sizes its iframe: headless Chrome clamps its own window at 500 px wide) and returns the
JSON the harness wrote (`ok`, `checks`, `notes`, `innerWidth`/`scrollWidth` of the page); a scenario counts real polls of the page (the connection
badge changes on every poll) and waits for at least three before judging what was preserved.

Scenarios (docs/obs1/UX-OBS-1.vi.md): ux01 (open sections/focus/scroll survive ≥ 3 polls AND a ledger write), ux02 (project filter closes a task
of another project), ux03 (question options with their commands, copy), ux04 (mouse + keyboard selection, detail in view, URL, reload, back),
ux05 (three done words/badges, time labels), ux06 (timeline groups, old history folded, seq ascending, a step's evidence opens), ux07 (list rows
carry no hash and no raw path as main text), ux08 (narrow layout: no horizontal page scroll, list/detail switch), race (a late reply for the
previously selected task never overwrites the selected one), disc (disconnect then reconnect keeps the selection), stale_detail (R4 of 03/11: a failed or late detail request never leaves another task's
content or reply commands under the selection; the overview badge and the detail freshness are shown apart). Shared by the unit tests
(tests/test_obs1_browser.py) and the package verifier (V14).

P2 of Codex's review of dev12 (detail reads slower than 20 s): `fk_*` scenarios load the page as `/?__fake=1`, which the proxy serves with FAKE
installed first (a test clock for the page's timers, Date and fetch; the bodies are the real server's answers, only their arrival time is
chosen), so 25-second answers, reads that never answer and late answers of a previous selection run in seconds and in an exact order;
`rt_slow` runs in REAL time (`run(..., realtime=True)`: no virtual clock; the proxy delays /api/task of P8 by `/__fault?...&delay=` with an
optional `count`, logs every API request with its start and end at `/__log`, and holds the harness page's load event with `/__hold` until
the harness calls `/__release`, so --dump-dom waits for the result).
"""
import json
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SIZES = {'desktop': (1280, 720), 'split': (640, 720), 'mobile': (390, 844)}


def chrome_args(exe, profile, width, height, budget):
    return [exe, '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', f'--user-data-dir={profile}', '--hide-scrollbars',
            f'--window-size={width},{height}', f'--virtual-time-budget={budget}']


def run(exe, proxy_url, scenario, width, height, profile, budget=30000, extra='', realtime=False):
    """One scenario in a window of width×height; returns the harness result dict (or {'ok': False, 'error': …}). `realtime=True` (P2, dev13):
    no virtual time at all - the page and the harness run on the real clock against the real server (through the proxy); the harness page holds
    its load event with an image the proxy answers only when the harness is done, so --dump-dom waits for the result; `budget` is then the
    longest the scenario may take, in real milliseconds."""
    url = f'{proxy_url}__ux?s={scenario}&w={width}&h={height}{extra}'
    args = chrome_args(exe, profile, width, height, budget)
    if realtime:
        args = [a for a in args if not a.startswith('--virtual-time-budget')]
        url += '&rt=1&hold=' + f'{scenario}-{time.monotonic_ns()}'
    done = None
    for attempt in (1, 2):                         # a hung headless Chrome (seen once in ~40 runs) is retried once
        try: done = subprocess.run(args + ['--dump-dom', url], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=(budget / 1000 + 120) if realtime else 240); break
        except subprocess.TimeoutExpired:
            if attempt == 2: return {'ok': False, 'error': 'headless Chrome did not finish twice (timeout)'}
    found = re.search(r'<pre id="out">(.*?)</pre>', done.stdout, re.S)
    if not found: return {'ok': False, 'error': 'harness wrote no result', 'tail': done.stdout[-600:] + done.stderr[-300:]}
    text = found.group(1).replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').replace('&quot;', '"')
    try: return json.loads(text)
    except ValueError: return {'ok': False, 'error': 'harness result is not JSON', 'tail': text[:600]}


def screenshot(exe, proxy_url, scenario, width, height, profile, path, budget=15000, extra=''):
    url = f'{proxy_url}__ux?s={scenario}&w={width}&h={height}&shot=1{extra}'
    for attempt in (1, 2):
        try: subprocess.run(chrome_args(exe, profile, width, height, budget) + [f'--screenshot={path}', url], capture_output=True, timeout=240); break
        except subprocess.TimeoutExpired:
            if attempt == 2: return False
    return Path(path).is_file()


class Proxy:
    def __init__(self, target, on_signal=None):
        state = {'drop': False, 'fault': None, 'faulted': 0, 'pending': 0, 'log': [], 'holds': {}}
        self.state = state
        lock = threading.Lock()

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *a): pass

            def _send(self, status, data, ctype):
                try:
                    self.send_response(status); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(data))); self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(data)
                    self._outcome = status
                except OSError:                                  # the page cancelled the request (its own timeout): recorded, never a traceback
                    self._outcome = 'client-gone'; self.close_connection = True

            def do_GET(self):
                url = urllib.parse.urlsplit(self.path)
                if url.path.startswith('/api/'):                 # P2 (dev13): every API request with its start and end (seconds since the epoch), so a run tells
                    params = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}   # "the server answered" apart from "the page showed it"
                    entry = {'t0': time.time(), 'kind': url.path[5:], 'plan': params.get('plan'), 'path': self.path}
                    with lock: state['log'].append(entry)
                    self._outcome = None
                    try: return self._get(url)
                    finally: entry['t1'] = time.time(); entry['outcome'] = self._outcome or 'closed'
                return self._get(url)

            def _get(self, url):
                if url.path == '/__ux':
                    params = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
                    page = HARNESS
                    if (params.get('s') or '').startswith('fk_'): page = page.replace('<iframe id="f" src="/">', '<iframe id="f" src="/?__fake=1">', 1)   # the page with the test clock
                    if params.get('rt') == '1':                  # real time: an image held until the harness is done keeps the load event (and --dump-dom) back
                        page = page.replace('<iframe id="f"', '<img id="hold" alt="" style="position:absolute;width:1px;height:1px" src="/__hold?id=' + urllib.parse.quote(params.get('hold') or '') + '"><iframe id="f"', 1)
                    return self._send(200, page.encode('utf-8'), 'text/html; charset=utf-8')
                if url.path == '/' and '__fake=1' in url.query:  # TEST ONLY: the real page with the fake clock (FAKE) installed before its own script
                    try:
                        with urllib.request.urlopen(target, timeout=30) as r: html = r.read().decode('utf-8')
                    except OSError:
                        self.close_connection = True; self.connection.close(); return
                    return self._send(200, html.replace('<head>', '<head><script>' + FAKE + '</script>', 1).encode('utf-8'), 'text/html; charset=utf-8')
                if url.path == '/__hold':
                    params = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
                    with lock: event = state['holds'].setdefault(params.get('id', ''), threading.Event())
                    event.wait(float(params.get('max') or 420))
                    return self._send(200, GIF, 'image/gif')
                if url.path == '/__release':
                    params = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
                    with lock: state['holds'].setdefault(params.get('id', ''), threading.Event()).set()
                    return self._send(200, b'{"ok":true}', 'application/json')
                if url.path == '/__log':
                    if 'clear=1' in url.query:
                        with lock: state['log'] = []
                    with lock: entries = [dict(e) for e in state['log']]
                    return self._send(200, json.dumps({'log': entries, 'now': time.time()}).encode('utf-8'), 'application/json')
                if url.path == '/__signal':
                    params = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
                    name = params.get('name', '')
                    try: result = on_signal(name, params) if on_signal else None
                    except TypeError: result = on_signal(name) if on_signal else None
                    return self._send(200, json.dumps({'signal': name, 'result': result}, default=str).encode('utf-8'), 'application/json')
                if url.path == '/__drop':
                    state['drop'] = urllib.parse.parse_qs(url.query).get('on', ['0'])[0] == '1'
                    return self._send(200, b'{"ok":true}', 'application/json')
                if url.path == '/__fault':                       # ---- R4 (stale_detail): TEST-ONLY detail fault, handled here, never by the product server
                    params = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
                    if not params.get('status'):
                        mode = params.get('detail', 'ok')
                        state['fault'] = None if mode == 'ok' and not params.get('delay') else {'mode': mode, 'plan': params.get('plan') or None, 'delay': int(params.get('delay') or 0),
                                                                                                'left': int(params['count']) if params.get('count') else None}   # count: only the next N matching requests (P2, dev13)
                    return self._send(200, json.dumps({'fault': state['fault'], 'faulted': state['faulted'], 'pending': state['pending']}).encode('utf-8'), 'application/json')
                if state['drop'] and url.path.startswith('/api/'):
                    self.close_connection = True; self.connection.close(); return
                fault = state['fault']
                if fault and url.path == '/api/task':
                    plan = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}.get('plan')
                    if not fault['plan'] or fault['plan'] == plan:
                        with lock:
                            if fault.get('left') is not None:
                                fault['left'] -= 1
                                if fault['left'] <= 0 and state['fault'] is fault: state['fault'] = None
                            state['pending'] += 1
                        try:
                            if fault['delay']: time.sleep(fault['delay'] / 1000)
                            if fault['mode'] == 'drop':
                                self.close_connection = True; self.connection.close(); return
                            if fault['mode'] == 'error':
                                return self._send(503, json.dumps({'error': 'nguồn lỗi: test fault (proxy)'}, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8')
                            return self._forward()                # mode ok with a delay: the late reply
                        finally:
                            with lock: state['pending'] -= 1; state['faulted'] += 1
                                                                 # ---- end R4
                return self._forward()

            def _forward(self):
                try:
                    with urllib.request.urlopen(target + self.path.lstrip('/'), timeout=30) as r:
                        return self._send(r.status, r.read(), r.headers.get('Content-Type') or 'application/octet-stream')
                except urllib.error.HTTPError as error:
                    return self._send(error.code, error.read(), error.headers.get('Content-Type') or 'application/json')
                except OSError:
                    self.close_connection = True; self.connection.close(); return

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}/'

    def stop(self):
        for event in list(self.state['holds'].values()): event.set()            # never leave a held image (and its Chrome) waiting
        self.server.shutdown(); self.server.server_close()


GIF = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'

# FAKE (P2 of Codex's review of dev12, TEST ONLY): installed by the proxy at the top of the real page (`/?__fake=1`) before the page's own script, so
# the page's timers, Date and fetch run on a test clock the harness moves with `__fake.advance(ms)`: a 25-second server answer, a read that never
# answers, a reply that arrives after another task was selected - in a few real seconds and in an exact order. The bodies are the REAL server's
# answers (fetched at once through the proxy); only WHEN the page receives them is decided here: per request `{delay: ms}`, `{hang: true}` (never
# answered: only the page's own abort ends it), `{fail: true}` (a network failure), `{status: 503}`, by `__fake.overview`, `__fake.task` or
# `__fake.plans[<selector>]` (an object or a function of the request). `__fake.reqs` records every request: kind, plan, start, end, state
# (pending, delivered, aborted, failed). The page's code is never changed.
FAKE = r'''(function(){'use strict';
var RD=Date, rST=window.setTimeout.bind(window), rFetch=window.fetch.bind(window), now=RD.now(), seq=0, timers=[], reqs=[], errors=[];
var F={reqs:reqs, errors:errors, overview:null, task:null, plans:{}, now:function(){return now}};
class FDate extends RD{constructor(...a){if(a.length===0)super(now);else super(...a)} static now(){return now}}
window.Date=FDate;
window.setTimeout=function(fn,ms){var id=++seq;timers.push({id:id,at:now+Math.max(0,+ms||0),fn:fn,a:[].slice.call(arguments,2),every:0,ord:id});return id};
window.setInterval=function(fn,ms){var id=++seq,e=Math.max(1,+ms||0);timers.push({id:id,at:now+e,fn:fn,a:[],every:e,ord:id});return id};
window.clearTimeout=window.clearInterval=function(id){for(var i=0;i<timers.length;i++)if(timers[i].id===id){timers.splice(i,1);return}};
function policy(r){var p=r.kind==='overview'?F.overview:r.kind==='task'?((r.plan&&F.plans&&F.plans[r.plan])||F.task):null;if(typeof p==='function')p=p(r);return p||{}}
window.fetch=function(u,o){o=o||{};var url=String(u),m=/[?&]plan=([^&]*)/.exec(url);
  var r={id:++seq,url:url,kind:url.indexOf('/api/task')===0?'task':url.indexOf('/api/overview')===0?'overview':'other',plan:m?decodeURIComponent(m[1]):null,start:now,end:null,state:'pending'};
  r.pol=policy(r);reqs.push(r);
  r.body=rFetch(url,{cache:'no-store'}).then(function(res){return res.text().then(function(t){return {status:res.status,type:res.headers.get('Content-Type')||'application/json',text:t}})},function(e){return {neterr:String(e)}});
  r.due=r.pol.hang?Infinity:now+(r.pol.delay||0);
  return new Promise(function(resolve,reject){r.resolve=resolve;r.reject=reject;var sig=o.signal;
    if(sig){var stop=function(){if(r.state!=='pending')return;r.state='aborted';r.end=now;reject(sig.reason!==undefined?sig.reason:new DOMException('The operation was aborted.','AbortError'))};
      if(sig.aborted)stop();else sig.addEventListener('abort',stop)}})};
async function flush(){for(var i=0;i<6;i++)await new Promise(function(res){rST(res,0)})}
async function deliver(r){var b=await r.body;if(r.state!=='pending')return;r.end=now;
  if(r.pol.fail||b.neterr){r.state='failed';r.reject(new TypeError('Failed to fetch'));return}
  if(r.pol.status){r.state='delivered';r.status=r.pol.status;r.resolve(new Response(JSON.stringify({error:'test fault (fake clock)'}),{status:r.pol.status,headers:{'Content-Type':'application/json'}}));return}
  r.state='delivered';r.status=b.status;r.resolve(new Response(b.text,{status:b.status,headers:{'Content-Type':b.type}}))}
F.failPending=function(kind){reqs.forEach(function(r){if(r.state==='pending'&&(!kind||r.kind===kind)){r.state='failed';r.end=now;r.reject(new TypeError('Failed to fetch'))}})};
F.advance=async function(ms){var target=now+Math.max(0,+ms||0);await flush();
  for(var guard=0;guard<200000;guard++){
    await Promise.all(reqs.filter(function(r){return r.state==='pending'&&r.due<=target}).map(function(r){return r.body}));
    var t=null,q=null;
    timers.forEach(function(x){if(x.at<=target&&(!t||x.at<t.at||(x.at===t.at&&x.ord<t.ord)))t=x});
    reqs.forEach(function(r){if(r.state==='pending'&&r.due<=target&&(!q||r.due<q.due||(r.due===q.due&&r.id<q.id)))q=r});
    if(q&&(!t||q.due<=t.at)){now=Math.max(now,q.due);await deliver(q);await flush();continue}
    if(t){now=Math.max(now,t.at);if(t.every){t.at+=t.every;t.ord=++seq}else timers.splice(timers.indexOf(t),1);
      try{t.fn.apply(window,t.a)}catch(e){errors.push(String(e&&e.message||e))}await flush();continue}
    break}
  now=Math.max(now,target);await flush()};
window.__fake=F;
})();'''


HARNESS = r'''<!doctype html><html><head><meta charset="utf-8"><title>OBS-1 UX harness</title>
<style>html,body{margin:0;height:100%}iframe{border:0;width:100%;height:calc(100% - 2px);display:block}#out{display:none}</style></head>
<body><iframe id="f" src="/"></iframe><pre id="out"></pre>
<script>
(async function(){
const qs=new URLSearchParams(location.search), S=qs.get('s'), shot=qs.get('shot')==='1';
const W=parseInt(qs.get('w')||'0',10), H=parseInt(qs.get('h')||'0',10);
const f=document.getElementById('f'); if(W){f.style.width=W+'px'} if(H){f.style.height=(H-2)+'px'}          // headless Chrome clamps the window at 500 px: the iframe carries the real size
const out={scenario:S, width:W||innerWidth, height:H||innerHeight, windowWidth:innerWidth, checks:{}, notes:[], ok:false};
let w, d;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function waitFor(fn, ms, what){const t0=Date.now();while(Date.now()-t0<(ms||8000)){try{const v=fn();if(v)return v}catch(e){}await sleep(50)}out.notes.push('timeout: '+(what||fn.toString().slice(0,80)));return null}
function check(name, value, detail){out.checks[name]=!!value; if(!value) out.notes.push('FAIL '+name+(detail!==undefined?': '+JSON.stringify(detail).slice(0,300):''));return !!value}
function $(s){return d.querySelector(s)} function $$(s){return Array.from(d.querySelectorAll(s))}
let polls=0, obs=null;
function watchPolls(){polls=0;if(obs)obs.disconnect();obs=new MutationObserver(()=>{polls++});obs.observe($('#conn'),{childList:true,characterData:true,subtree:true})}
async function morePolls(n){const base=polls;return await waitFor(()=>polls>=base+n, 30000, 'polls '+n)}
async function loaded(){w=f.contentWindow;d=w.document;await waitFor(()=>d.readyState==='complete'&&$('#conn')&&$('#conn').className==='ok'&&$$('li.task').length>0, 15000, 'page+first poll');watchPolls();w.focus()}
function rowOf(plan){return $$('li.task').find(li=>li.querySelector('.name').textContent===plan)}
function st(){return w.__track.state()}
function shown(plan){return $('#dtitle')&&$('#dtitle').textContent.indexOf(plan)===0&&$('#detail .dsum')}   // the LOADED detail of plan (a loading/error pane has a heading but no summary strip)
async function select(plan){rowOf(plan).click();return await waitFor(()=>shown(plan), 10000, 'detail '+plan)}
function key(el,k){el.dispatchEvent(new w.KeyboardEvent('keydown',{key:k,bubbles:true,cancelable:true}))}
function seqOf(){const m=/seq (\d+)/.exec($('#conn').textContent);return m?parseInt(m[1],10):null}
async function signal(name,params){var q='';Object.keys(params||{}).forEach(function(k){q+='&'+k+'='+encodeURIComponent(params[k])});return await (await fetch('/__signal?name='+encodeURIComponent(name)+q)).json()}
// ---- P2 of Codex's review of dev12: the test clock (fk_*, FAKE in the proxy) and the real-time run (rt_*) ----
const FK=(S||'').indexOf('fk_')===0, RT=qs.get('rt')==='1';
let fk=null, T0=0; const samples=[];
async function fakeLoaded(){w=f.contentWindow;d=w.document;fk=w.__fake;if(!fk)throw new Error('the fake clock is not installed in the page');
  for(let i=0;i<60&&!($('#conn')&&$('#conn').className==='ok'&&$$('li.task').length>0);i++)await fk.advance(0);
  if(!($('#conn')&&$('#conn').className==='ok'))throw new Error('fake clock: the first overview was never painted');watchPolls();w.focus()}
function P1cmds(){return $$('#detail code').map(c=>c.textContent).filter(c=>/question answer/.test(c)).length}
function snap(tag){const t=$('#dtitle'),ds=$('#dstatus'),s=st(),dc=$('#dconn');          // what the reader sees at this moment, with the page's own state
  const x={t:(fk?fk.now():Date.now())-T0,tag:tag||null,title:t?t.textContent.slice(0,24):'',loaded:!!$('#detail .dsum'),state:s.detailState,dstatus:ds?ds.getAttribute('data-state'):null,dtext:ds?ds.textContent.slice(0,260):null,
    dconn:dc&&!dc.hidden?dc.textContent.slice(0,160):null,conn:$('#conn').className,ctext:$('#conn').textContent.slice(0,160),sel:s.selected&&s.selected.plan,dfor:s.detailFor&&s.detailFor.plan,okAt:s.detailOkAt,cmds:P1cmds(),retry:!!$('#dretry'),
    inflight:fk?fk.reqs.filter(r=>r.kind==='task'&&r.state==='pending').length:null};
  samples.push(x);return x}
async function fadv(ms,step,tag){step=step||500;let left=ms;while(left>0){const s=Math.min(step,left);await fk.advance(s);left-=s;snap(tag)}}
async function fselect(plan){rowOf(plan).click();await fk.advance(0);for(let i=0;i<40&&!shown(plan);i++)await fk.advance(100);return shown(plan)}
function treqs(plan){return fk.reqs.filter(r=>r.kind==='task'&&(!plan||r.plan===plan))}
function ovreqs(){return fk.reqs.filter(r=>r.kind==='overview')}
function only(plan,list){const k=rowOf(plan).dataset.plan;return list.every(x=>x.title.indexOf(plan)===0&&(!x.dfor||x.dfor===k))}   // nothing of another task under this selection
function bad(plan,list){const k=rowOf(plan).dataset.plan;return list.filter(x=>x.title.indexOf(plan)!==0||(x.dfor&&x.dfor!==k)).slice(0,3)}
await new Promise(r=>{if(f.contentDocument&&f.contentDocument.readyState==='complete'&&f.contentWindow.location.pathname==='/')r();else f.addEventListener('load',r,{once:true})});
let loadErr=null; try{if(FK)await fakeLoaded();else await loaded()}catch(e){loadErr=e}
try{
if(loadErr)throw loadErr;
if(S==='ux01'){
  await select('P1'); const pane=$('#detailpane'); $('details[data-k="log"]').open=true;
  const ev=$$('ol.ev > li').find(li=>li.querySelector('.clip')); check('an event with evidence exists', ev);
  if(ev){ev.click(); await waitFor(()=>$('.evbox'),5000,'evbox'); const btn=$('.ev-open'); if(btn){btn.click(); await waitFor(()=>$('.evbox pre'),8000,'evidence text')}}
  const att=$('details[data-k="attempts"]'); if(att){att.querySelector('summary').click()}
  const evd=$('details[data-k="evidence"]'); evd.querySelector('summary').click(); evd.querySelector('summary').focus();
  pane.scrollTop=150; w.scrollTo(0,0);
  const before={att:att?att.open:null, evd:evd.open, evbox:!!$('.evbox pre'), focus:d.activeElement&&d.activeElement.closest('[data-k]')&&d.activeElement.closest('[data-k]').getAttribute('data-k'), scroll:pane.scrollTop, selEv:st().selEv, seq:seqOf()};
  check('setup: sections open and focus on evidence summary', before.evd && before.focus==='evidence' && before.evbox, before);
  await morePolls(3);
  const quiet={att:att?$('details[data-k="attempts"]').open:null, evd:$('details[data-k="evidence"]').open, evbox:!!$('.evbox pre'), focus:d.activeElement&&d.activeElement.closest('[data-k]')&&d.activeElement.closest('[data-k]').getAttribute('data-k'), scroll:$('#detailpane').scrollTop, selEv:st().selEv, seq:seqOf()};
  check('after 3 quiet polls: open sections, evidence text, focus, scroll, selected step kept', JSON.stringify(quiet)===JSON.stringify(before), {before,quiet});
  await signal('write'); const moved=await waitFor(()=>seqOf()>before.seq, 15000, 'seq moved after the write'); await morePolls(2);
  const after={att:att?$('details[data-k="attempts"]').open:null, evd:$('details[data-k="evidence"]').open, evbox:!!$('.evbox pre'), focus:d.activeElement&&d.activeElement.closest('[data-k]')&&d.activeElement.closest('[data-k]').getAttribute('data-k'), scroll:$('#detailpane').scrollTop, selEv:st().selEv};
  check('the ledger moved (detail re-rendered)', moved && st().detailSeq===seqOf(), {seq:seqOf(), detailSeq:st().detailSeq});
  const want={att:before.att,evd:before.evd,evbox:before.evbox,focus:before.focus,scroll:before.scroll,selEv:before.selEv};
  check('after the write: open sections, evidence text, focus, scroll, selected step kept', JSON.stringify(after)===JSON.stringify(want), {before:want,after});
  check('the new event is on the page', $$('ol.ev > li').length>0 && $('#dtitle').textContent.indexOf('P1')===0);
}
if(S==='ux02'){
  await select('P1'); const a=rowOf('P1').querySelector('.r3').title; const opts=$$('#proj option').filter(o=>o.value);
  check('two projects in the filter', opts.length>=2, opts.map(o=>o.value));
  const target=opts.find(o=>o.value!==a); check('a second project to switch to', target, opts.map(o=>o.value)); if(!target) throw new Error('no second project');
  const sel=$('#proj'); sel.value=target.value; sel.dispatchEvent(new w.Event('change',{bubbles:true})); await sleep(100);
  check('list shows only the other project', $$('li.task').length>0 && $$('li.task').every(li=>li.querySelector('.r3').title===target.value), $$('li.task').map(li=>li.querySelector('.r3').title));
  check('the detail of P1 is closed', !$('#dtitle') && st().selected===null && $('#nodetail'), {sel:st().selected, text:$('#detail').textContent.slice(0,120)});
  check('the URL no longer names P1', w.location.search.indexOf('plan=')<0, w.location.search);
  check('the placeholder names the project to pick from', /chọn một task/i.test($('#detail').textContent));
  sel.value=''; sel.dispatchEvent(new w.Event('change',{bubbles:true})); await sleep(100); check('all projects again', $$('li.task').length>=3);
}
if(S==='ux03'){
  await select('P1'); const need=$('details.need'); check('question card (folded)', need && !need.open);
  need.open=true; const opts=Array.from(need.querySelectorAll('.opt'));
  check('two options with label and id', opts.length===2 && opts.every(o=>o.querySelector('b').textContent && /\(.+\)/.test(o.textContent)), opts.map(o=>o.textContent.slice(0,60)));
  const cmds=opts.map(o=>o.querySelector('code').textContent);
  check('each option is a complete PowerShell template: & exe --project --state-root question answer --revision --choice --reference', cmds.length===2 && cmds.every(c=>/^(& '.+onecrew(\.exe)?'|onecrew) --project '.+' --state-root '.+' question answer REQ-\S+ --revision \S+ --choice \S+ --reference '<[^']+>'$/.test(c)) && cmds[0]!==cmds[1], cmds);
  check('the reference placeholder is marked as the part the owner fills', opts.every(o=>o.querySelector('code mark.ph')) && /BẠN tự điền/.test(need.textContent));
  check('the question text is readable and carries no raw secret', /\?/.test(need.querySelector('.q').textContent) && !/hunter2|must-not-show/.test(d.body.textContent) && (!/password=/.test($$('details.need').map(n=>n.textContent).join(' ')) || /\[withheld\]/.test($$('details.need').map(n=>n.textContent).join(' '))), need.querySelector('.q').textContent);
  check('no element answers the question (no answer/approve button)', !$$('#detail button').some(b=>/trả lời|duyệt|answer|approve/i.test(b.textContent)));
  const btn=opts[1].querySelector('button.copy'); btn.focus(); btn.click(); const done=await waitFor(()=>$('.copied'),5000,'copied status');
  let clip=null; try{clip=await w.navigator.clipboard.readText()}catch(e){clip='(readText unavailable: '+e.name+')'} out.clipboard_read=clip;
  if(done && done.hasAttribute('data-copied')){check('copy reports exactly the second option template', done.getAttribute('data-copied')===cmds[1], {copied:done.getAttribute('data-copied'), want:cmds[1]});
    check('the clipboard really holds the template (or readText is unavailable here)', clip===cmds[1] || /unavailable/.test(String(clip)), clip);
    check('the copied status says the template is not filled yet', /chưa điền/.test(done.textContent));}
  else{check('a failed copy is reported as failure with the text to copy by hand', done && done.hasAttribute('data-copy-failed') && done.querySelector('textarea') && done.querySelector('textarea').value===cmds[1], done&&done.textContent.slice(0,120));}
  check('focus stays on the copy button after the re-render', d.activeElement && d.activeElement.classList.contains('copy'));
  const nBefore=$$('details.need').length; await morePolls(2); check('copying answered nothing (the questions are all still pending)', $$('details.need').length===nBefore && new RegExp('Cần bạn \\('+nBefore+'\\)').test($('#needs').textContent), {nBefore, now:$$('details.need').length});
  check('the request is still pending on the page', $('details.need') && st().selected.plan);
}
if(S==='ux04'){
  const rows=$$('li.task'); check('rows are keyboard reachable (tabindex=0, role=option)', rows.length>=2 && rows.every(r=>r.getAttribute('tabindex')==='0'&&r.getAttribute('role')==='option'));
  const target=rows[rows.length-1]; const plan=target.querySelector('.name').textContent; target.scrollIntoView(); target.click(); await waitFor(()=>shown(plan), 8000, 'detail by click');
  const r=$('#detailpane').getBoundingClientRect(); check('the detail is in view right after the click', r.top>=-1 && r.top<w.innerHeight*0.8 && r.height>50, {top:r.top, h:r.height, inner:w.innerHeight});
  check('the clicked row keeps focus (mouse selection)', d.activeElement===rowOf(plan) || d.activeElement===d.body, d.activeElement&&d.activeElement.tagName);
  check('the URL names the task', w.location.search.indexOf('plan=')>=0 && w.location.search.indexOf('project_id=')>=0, w.location.search);
  if(w.innerWidth<900){$('#back').click(); await sleep(100)}                      // narrow: the list must be on screen before the keyboard part
  const first=rowOf('P1'); first.focus(); key(first,'ArrowDown'); const second=d.activeElement; check('ArrowDown moves focus to the next row', second && second.classList.contains('task') && second!==first);
  const plan2=second.querySelector('.name').textContent; key(second,'Enter'); await waitFor(()=>shown(plan2), 8000, 'detail by Enter');
  check('Enter selects the focused row and moves focus to the detail title', d.activeElement===$('#dtitle'), d.activeElement&&d.activeElement.id);
  key($('#dtitle'),'Escape'); await sleep(100); check('Escape closes the detail and returns focus to the row', st().selected===null && d.activeElement && d.activeElement.classList.contains('task') && d.activeElement.querySelector('.name').textContent===plan2, d.activeElement&&d.activeElement.textContent.slice(0,30));
  check('the row last viewed is marked', rowOf(plan2).classList.contains('last'));
  await select('P1'); const url=w.location.href; w.location.reload(); await new Promise(r=>f.addEventListener('load',r,{once:true})); await loaded();
  check('reload keeps the selected task', st().selected && st().selected.plan===rowOf('P1').dataset.plan && $('#dtitle') && $('#dtitle').textContent.indexOf('P1')===0, {sel:st().selected, url});
  await select('P2'); w.history.back(); await waitFor(()=>st().selected && st().selected.plan===rowOf('P1').dataset.plan, 8000, 'back to P1');
  check('browser Back returns to the previous task', st().selected && st().selected.plan===rowOf('P1').dataset.plan && $('#dtitle').textContent.indexOf('P1')===0, st().selected);
  w.history.back(); await waitFor(()=>st().selected===null, 8000, 'back to list'); check('Back again returns to the list', st().selected===null && $('#nodetail'));
}
if(S==='ux05'){
  const badge=p=>{const r=rowOf(p);if(!r)return null;const s=r.querySelector('.st'),g=s.querySelector('.g');return {cls:s.className, text:s.textContent.replace(g?g.textContent:'','').trim()}};
  check('closed plan: grey "đã đóng", not "hoàn tất"', badge('P3') && badge('P3').cls==='st done closed' && badge('P3').text==='đã đóng', badge('P3'));
  check('verified plan: "đã kiểm, chờ nghiệm thu"', badge('P6') && badge('P6').cls==='st done verified' && badge('P6').text==='đã kiểm, chờ nghiệm thu', badge('P6'));
  check('accepted plan: "đã nghiệm thu"', badge('P7') && badge('P7').cls==='st done accepted' && badge('P7').text==='đã nghiệm thu', badge('P7'));
  check('blocked plan: "bị chặn"', badge('P4') && badge('P4').cls==='st blocked', badge('P4'));
  check('the three done badges have three different colours', new Set(['P3','P6','P7'].map(p=>w.getComputedStyle(rowOf(p).querySelector('.st')).backgroundColor)).size===3);
  await select('P3'); const labels=$$('.tile .l').map(e=>e.textContent);
  check('time tiles name their measure', labels.some(l=>/từ khi duyệt \(lịch\)/i.test(l)) && labels.some(l=>/thực hiện \(attempt\)/i.test(l)) && labels.some(l=>/^chờ$/i.test(l)), labels);
  check('no "đã chạy" label anywhere', !/đã chạy/.test(d.body.textContent));
  check('the closed plan says it has no output and that closing is not accepting', /chưa có đầu ra/.test($('#detail').textContent) && /không phải nghiệm thu/.test($('#detail').textContent));
  check('the list has no percentage and no ETA number', !/\d+ ?%/.test($('#list').textContent));
  check('badges carry a glyph besides the colour', $$('li.task .st .g').length===$$('li.task .st').length && $$('li.task .st .g').every(g=>g.textContent.trim().length===1));
  await select('P4'); const cells=Array.from($('#detail table').querySelectorAll('td')).map(td=>td.textContent.trim());
  check('phase and output words are Vietnamese (raw code in title)', cells.some(c=>/^(đang chạy|bị giữ|chờ đến lượt|xong)/.test(c)) && cells.some(c=>/^(chưa có đầu ra|đã tạo|đã kiểm|đã nghiệm thu)/.test(c)) && !cells.some(c=>/^(running|held|pending|none|produced)$/.test(c)), cells.slice(0,8));
}
if(S==='ux06'){
  await select('P4'); $('details[data-k="log"]').open=true; const grp=$$('section.grp').find(g=>/phần việc C/.test(g.querySelector('h4').textContent)); check('a group for phần việc C', grp);
  const old=grp&&grp.querySelector('details[data-k^="old:"]'); check('old attempt history is folded with a count', old && !old.open && /lịch sử cũ \(\d+/.test(old.querySelector('summary').textContent), old&&old.querySelector('summary').textContent);
  const seqs=grp?Array.from(grp.querySelectorAll(':scope > ol.ev > li')).map(li=>parseInt(li.dataset.seq,10)):[]; check('current events ascend (old → new)', seqs.length>0 && seqs.every((v,i)=>i===0||v>seqs[i-1]), seqs);
  const stale=old?old.querySelectorAll('li.stale').length:0; check('old attempt events are marked stale', stale>0, stale);
  const tech=grp&&grp.querySelector('details[data-k^="tech:"]'); check('technical events (attempt.*) are folded under their node', tech && !tech.open && /chi tiết kỹ thuật/.test(tech.querySelector('summary').textContent) && tech.querySelectorAll('li').length>=2, tech&&tech.textContent.slice(0,120));
  const main=grp?grp.querySelectorAll(':scope > ol.ev > li').length:0; check('the main list has fewer events than the whole group', main>0 && main < grp.querySelectorAll('li').length, {main, all:grp&&grp.querySelectorAll('li').length});
  const first=$$('li.task')[0]; await select('P2'); $('details[data-k="log"]').open=true; const ev=$$('ol.ev > li').find(li=>li.querySelector('.clip')); check('P2 has a step with evidence', ev);
  const seq=ev.dataset.seq; ev.click(); const box=await waitFor(()=>$('.evbox'),5000,'evbox');
  check('clicking the step shows its evidence with label, kind and time', box && box.querySelector('b') && box.querySelector('b').textContent.length>3 && /\b\w+\.\w+\b/.test(box.querySelector('.mut').textContent) && !/thời điểm chưa rõ/.test(box.querySelector('div').textContent), box&&box.textContent.slice(0,200));
  const btn=box&&box.querySelector('.ev-open'); btn.click(); const pre=await waitFor(()=>$('.evbox pre'),8000,'evidence content'); check('evidence content opens inline, redacted', pre && pre.textContent.length>0 && pre.textContent.indexOf('hunter2')<0 && pre.textContent.indexOf('sk-fixture-secret')<0, pre&&pre.textContent.slice(0,80));
  $('[data-k="ev:'+seq+'"]').click(); check('clicking the same step again folds it', !$('.evbox'));
  const att=$('details[data-k="attempts"]'); att.open=true; check('a settled attempt shows a measured duration bar', att.querySelector('.dur') && /\d+s/.test(att.textContent));
  await select('P4'); const att4=$('details[data-k="attempts"]'); att4.open=true; const rows=Array.from(att4.querySelectorAll('tbody tr'));
  check('every attempt row either has a measured bar or says chưa xác định (never a guessed bar)', rows.length>0 && rows.every(r=>(r.querySelector('.dur') && /\d+s|\d+m/.test(r.textContent)) || (!r.querySelector('.dur') && /chưa xác định/.test(r.textContent))), rows.map(r=>r.textContent.slice(0,80)));
}
if(S==='ux07'){
  const rows=$$('li.task'); check('rows exist', rows.length>=5);
  check('no 64-hex hash as list text', !/\b[0-9a-f]{64}\b/.test($('#list').textContent));
  check('rows carry status, name, current step and a relative update time', rows.every(r=>r.querySelector('.st')&&r.querySelector('.name')&&r.querySelector('.r2')&&/trước|vừa xong/.test(r.querySelector('.r2').textContent)), rows.map(r=>r.querySelector('.r2').textContent));
  check('full paths and ids are muted secondary text', rows.every(r=>r.querySelector('.r3.mut')) && !rows.some(r=>/^[a-z]:\\/i.test(r.querySelector('.r1').textContent)));
  check('the needs-you rows are marked', rowOf('P1').querySelector('.needb'));
  check('the header counts tasks and the chips count needs', /\d+ task/.test($('#count').textContent) && /cần bạn \(\d+\)/.test($('#chips').textContent), $('#count').textContent+' | '+$('#chips').textContent);
  const chips=$$('#chips button'); check('quick-filter chips with counts', chips.length>=3 && chips.every(c=>/\(\d+\)/.test(c.textContent)), chips.map(c=>c.textContent));
  chips.find(c=>c.dataset.kind==='blocked').click(); check('the blocked chip keeps only blocked rows', $$('li.task').length>=1 && $$('li.task').every(r=>r.querySelector('.st').classList.contains('blocked')) && $('#chips button[data-kind="blocked"]').getAttribute('aria-pressed')==='true');
  $('#chips button[data-kind=""]').click(); check('tất cả chip restores the list', $$('li.task').length>=5);
  $('#kind').value='blocked'; $('#kind').dispatchEvent(new w.Event('change',{bubbles:true})); check('status filter keeps only blocked', $$('li.task').length>=1 && $$('li.task').every(r=>r.querySelector('.st').classList.contains('blocked')));
  $('#kind').value='need'; $('#kind').dispatchEvent(new w.Event('change',{bubbles:true})); check('"cần bạn" filter keeps only rows with a need', $$('li.task').length>=1 && $$('li.task').every(r=>r.querySelector('.needb')));
  $('#kind').value=''; $('#q').value='P4'; $('#q').dispatchEvent(new w.Event('input',{bubbles:true})); check('search narrows to P4', $$('li.task').length===1 && rowOf('P4'));
  $('#q').value='nothing-matches-xyz'; $('#q').dispatchEvent(new w.Event('input',{bubbles:true})); check('no match says so', $$('li.task').length===0 && /không có task nào khớp/i.test($('#empty').textContent));
  $('#q').value=''; $('#q').dispatchEvent(new w.Event('input',{bubbles:true}));
}
function clipped(e){for(let p=e.parentElement;p&&p!==d.body;p=p.parentElement){const o=w.getComputedStyle(p).overflow;if(o==='hidden'||o==='auto'||o==='scroll')return true}return false}
function overflowing(){return $$('body *').filter(e=>{const r=e.getBoundingClientRect();return r.width>0 && r.right>w.innerWidth+1 && !clipped(e) && !e.closest('.evbox pre')}).slice(0,8).map(e=>e.tagName+(e.id?'#'+e.id:'')+(e.className&&typeof e.className==='string'?'.'+e.className.split(' ')[0]:'')+'@'+Math.round(e.getBoundingClientRect().right))}
if(S==='ux08'){
  const de=d.documentElement; out.overflow_list=overflowing(); check('no horizontal page scroll on the list', de.scrollWidth<=w.innerWidth+1 && out.overflow_list.length===0, {scrollWidth:de.scrollWidth, inner:w.innerWidth, elements:out.overflow_list});
  check('the project filter never widens the page (long folder names)', $('#proj').getBoundingClientRect().right<=w.innerWidth+1 && $$('#proj option').some(o=>o.textContent.length>40), {right:$('#proj').getBoundingClientRect().right, longest:Math.max(...$$('#proj option').map(o=>o.textContent.length))});
  const narrow=w.innerWidth<900; check('narrow layout detected when the window is narrow', narrow===w.matchMedia('(max-width:899px)').matches);
  await select('P4'); out.overflow_detail=overflowing(); check('no horizontal page scroll on the detail', de.scrollWidth<=w.innerWidth+1 && out.overflow_detail.length===0, {scrollWidth:de.scrollWidth, inner:w.innerWidth, elements:out.overflow_detail});
  await select('P1'); const nd=$('details.need'); if(nd){nd.open=true} out.overflow_question=overflowing(); check('no overflow with the question templates open', de.scrollWidth<=w.innerWidth+1 && out.overflow_question.length===0, {scrollWidth:de.scrollWidth, elements:out.overflow_question});
  if(narrow){check('narrow: the list is hidden and the detail shown', $('#listpane').offsetParent===null && $('#detailpane').offsetParent!==null && $('#back').offsetParent!==null);
    check('narrow: the detail starts in the upper part of the page (below the compact header)', w.scrollY===0 && $('#detailpane').getBoundingClientRect().top<w.innerHeight/3 && $('#dtitle').getBoundingClientRect().bottom<w.innerHeight/2, {y:w.scrollY, top:$('#detailpane').getBoundingClientRect().top, title:$('#dtitle').getBoundingClientRect().bottom});
    $('#back').click(); await sleep(100); check('narrow: back shows the list again', $('#listpane').offsetParent!==null && st().selected===null);}
  else{check('wide: list and detail side by side', $('#listpane').offsetParent!==null && $('#detailpane').offsetParent!==null && $('#detailpane').getBoundingClientRect().left>$('#listpane').getBoundingClientRect().left);}
  await select('P1'); const att=$('details[data-k="attempts"]'); if(att){att.open=true} check('technical tables scroll in their own box, not the page', de.scrollWidth<=w.innerWidth+1 && $$('.scroll').length>0, de.scrollWidth);
}
if(S==='race'){
  const real=w.fetch; w.fetch=function(u,o){const p=real.apply(this,arguments); if(String(u).indexOf('plan=')>=0 && String(u).indexOf(encodeURIComponent(rowOf('P1').dataset.plan))>=0) return p.then(r=>new Promise(res=>setTimeout(()=>res(r),1500))); return p};
  rowOf('P1').click(); await sleep(30); rowOf('P2').click(); await waitFor(()=>shown('P2'), 8000, 'P2 detail'); await sleep(2200);
  check('the late P1 reply did not overwrite the selected P2', $('#dtitle').textContent.indexOf('P2')===0 && st().selected.plan===rowOf('P2').dataset.plan, $('#dtitle').textContent);
  w.fetch=real;
}
if(S==='disc'){
  await select('P2'); const seq=seqOf(); await fetch('/__drop?on=1'); const bad=await waitFor(()=>$('#conn').className==='bad', 20000, 'bad badge');
  check('the badge says disconnected and that workers are unaffected', bad && /MẤT KẾT NỐI/.test($('#conn').textContent) && /worker không bị ảnh hưởng/.test($('#conn').textContent), $('#conn').textContent);
  check('the old data and the selection stay on screen', $('#dtitle') && $('#dtitle').textContent.indexOf('P2')===0 && $$('li.task').length>0 && st().selected);
  await fetch('/__drop?on=0'); const ok=await waitFor(()=>$('#conn').className==='ok', 20000, 'ok badge again');
  check('reconnects by itself and shows the same seq', ok && seqOf()===seq && $('#dtitle').textContent.indexOf('P2')===0, {seq, now:seqOf()});
}
if(S==='clock'){
  await select('P2'); const tile=()=>$('.tile .v[data-live]'); check('the running task has a live calendar clock', tile(), $$('.tile .v').map(e=>e.textContent));
  const parse=t=>{const m=/(?:(\d+)h)?(?:(\d+)m)?(\d+)s?/.exec(t.replace(/\s/g,''));return m?(+(m[1]||0))*3600+(+(m[2]||0))*60+(+m[3]):NaN};
  async function serverNow(){const h=await (await fetch('/api/health',{cache:'no-store'})).json();return new Date(h.generated_at).getTime()/1000}
  const s0=parse(tile().textContent), t0=Date.now(), seq0=seqOf(), srv0=await serverNow(); await morePolls(3); await sleep(1200);
  const s1=parse(tile().textContent), real=(Date.now()-t0)/1000;
  check('seq did not move during the wait (no re-render involved)', seqOf()===seq0 && st().detailSeq===seq0, {seq0, now:seqOf()});
  check('the clock advanced with real time across polls (±2 s)', Math.abs((s1-s0)-real)<=2 && s1>s0, {s0,s1,real});
  w.location.reload(); await new Promise(r=>f.addEventListener('load',r,{once:true})); await loaded(); await waitFor(()=>$('.tile .v[data-live]'),8000,'detail after reload');
  const s2=parse(tile().textContent), real2=(await serverNow())-srv0; check('reload continues from the sourced value (no double counting; compared with server time)', Math.abs((s2-s0)-real2)<=3, {s0,s2,real2});
  await select('P3'); check('a closed task has no live clock', !$('.tile .v[data-live]') && /\d+s|\d+m/.test($$('.tile .v')[2].textContent)); const c0=$$('.tile .v')[2].textContent; await morePolls(2); check('and its value does not move', $$('.tile .v')[2].textContent===c0, {c0, now:$$('.tile .v')[2].textContent});
  await select('P2'); const s3=parse(tile().textContent), real3=(await serverNow())-srv0; check('switching back resumes the right task clock (compared with server time)', Math.abs((s3-s0)-real3)<=3, {s0,s3,real3});
  await select('PB'); check('an unapproved plan says chưa xác định, no clock', !$('.tile .v[data-live]') && /chưa xác định/.test($$('.tile .v')[2].textContent));
}
if(S==='ux03b'){
  await select('P1'); const needs=$$('details.need'), N=needs.length; check('at least three questions, each folded', N>=3 && needs.every(n=>!n.open), N);
  check('the heading counts them and the summary strip links to them', new RegExp('Cần bạn \\('+N+'\\)').test($('#needs').textContent) && new RegExp(N+' câu hỏi chờ bạn').test($('.dsum').textContent), $('#needs').textContent.slice(0,30)+' | '+$('.dsum').textContent);
  check('the summary strip shows the current step', new RegExp('chờ bạn trả lời '+N+' câu hỏi').test($('.dsum .step').textContent), $('.dsum .step').textContent);
  const stats=$('.stats'), nh=$('#needs'), gt=$('.gantt'); check('order: summary strip, questions (folded), timeline, tiles', nh && gt && stats && (nh.compareDocumentPosition(gt) & Node.DOCUMENT_POSITION_FOLLOWING) && (gt.compareDocumentPosition(stats) & Node.DOCUMENT_POSITION_FOLLOWING), 0);
  const titles=needs.map(n=>n.querySelector('summary').textContent); check('each question keeps its own title (no merging)', new Set(titles).size===N, titles);
  check('the summary strip and the start of the timeline are above the fold (folded questions do not push them down)', $('.dsum').getBoundingClientRect().bottom < w.innerHeight && gt.getBoundingClientRect().top < (w.innerWidth<900? w.innerHeight*1.5 : w.innerHeight*0.8), {strip:$('.dsum').getBoundingClientRect().bottom, gantt:gt.getBoundingClientRect().top, inner:w.innerHeight});
  check('folded questions take one line each', needs[N-1].getBoundingClientRect().bottom - needs[0].getBoundingClientRect().top < 44*N+20, needs[N-1].getBoundingClientRect().bottom - needs[0].getBoundingClientRect().top);
  needs[1].open=true; check('opening one shows reason, impact, options and templates', /Vì:/.test(needs[1].textContent) && /Ảnh hưởng:/.test(needs[1].textContent) && needs[1].querySelectorAll('.opt').length===2 && needs[1].querySelectorAll('mark.ph').length>=2);
  await morePolls(2); check('the opened question stays open across polls', $$('details.need')[1].open && !$$('details.need')[0].open);
  check('the list column is narrower than the detail while reading (wide)', w.innerWidth<900 || $('#listpane').getBoundingClientRect().width < $('#detailpane').getBoundingClientRect().width*0.6, {l:$('#listpane').getBoundingClientRect().width, r:$('#detailpane').getBoundingClientRect().width});
}
if(S==='gantt'){
  await select('P8'); const J=await (await fetch('/api/task?plan='+encodeURIComponent(st().selected.plan)+'&project_id='+encodeURIComponent(st().selected.project)+'&timeline=300',{cache:'no-store'})).json();
  const chart=$('.gchart'); check('a shared axis with a window', chart && chart.dataset.w0 && chart.dataset.w1 && $$('.gaxis span').length===6, chart&&chart.dataset);
  const w0=new Date(chart.dataset.w0).getTime(), w1=new Date(chart.dataset.w1).getTime(), cw=chart.getBoundingClientRect().width;
  const expPct=t=>(new Date(t).getTime()-w0)/(w1-w0)*100;
  let worst=0, n=0; J.gantt.rows.forEach(r=>r.segments.forEach((sg,i)=>{const el=$('.seg[data-k="seg:'+r.attempt+':'+i+'"]'); if(!el){worst=999;return} const L=Math.max(0,expPct(sg.from)), Rr=Math.min(100,expPct(sg.to)); const got=[parseFloat(el.style.left), parseFloat(el.style.width)]; worst=Math.max(worst, Math.abs(got[0]-L), Math.abs(got[1]-Math.max(0.15,Rr-L))); n++}));
  check('every segment left/width matches its sourced timestamps on the axis (≤0.6% of the window)', n>0 && worst<=0.6, {segments:n, worst});
  const execRows=J.gantt.rows.filter(r=>r.node==='A'||r.node==='B'); check('P8 has the two attempts of A and B, both settled', execRows.length===2 && execRows.every(r=>r.status==='settled'), execRows.map(r=>[r.node,r.status]));
  const rects=execRows.map(r=>{const el=$('.seg.execution[data-attempt="'+r.attempt+'"]'); const x=el.getBoundingClientRect(); return {node:r.node, left:x.left, right:x.right}});
  check('their execution bars overlap on the shared axis (they ran at the same time)', rects.length===2 && rects[0].left<rects[1].right && rects[1].left<rects[0].right && execRows.every(r=>new Date(r.launched_at)<new Date(execRows[1-execRows.indexOf(r)].settled_at)), rects);
  check('no to_now part on settled attempts and no now line when nothing runs', !$('.seg.to_now') && !J.gantt.axis.extends_to_now);
  check('plan marks are on the plan row', $$('.mk.plan').length>=1 && $$('.mk.plan').every(m=>m.dataset.row==='plan'));
  check('marks sit where their timestamps say', $$('.mk').every(m=>Math.abs(parseFloat(m.style.left)-expPct(m.dataset.at))<=0.6));
  const legend=$('.legend'); check('legend names execution/reserved/wait/verification/to_now/marks/old', legend && ['thực thi','đặt chỗ','chờ','kiểm','tới hiện tại','dấu mốc','lượt cũ'].every(w=>legend.textContent.indexOf(w)>=0));
  if(w.innerWidth>=1100){check('P3-D: at this width the whole axis of P8 fits without a horizontal scroll inside the chart, the tree is narrow and the text is not tiny', $('.gscroll').scrollWidth<=$('.gscroll').clientWidth+1 && $('.gtree').getBoundingClientRect().width<=180 && parseFloat(w.getComputedStyle($('.gtree .att')||$('.gtree .grow')).fontSize)>=12 && $('.gchart').getBoundingClientRect().width>=500, {sw:$('.gscroll').scrollWidth, cw:$('.gscroll').clientWidth, tree:$('.gtree').getBoundingClientRect().width, chart:$('.gchart').getBoundingClientRect().width, font:w.getComputedStyle($('.gtree .grow')).fontSize})}
  check('the timeline box, its side pane and the detail pane stay inside the viewport (the chart scrolls inside its own box)', $('.gantt').getBoundingClientRect().right<=w.innerWidth+1 && $('#gside').getBoundingClientRect().right<=w.innerWidth+1 && $('#detailpane').scrollWidth<=$('#detailpane').clientWidth+1, {gantt:$('.gantt').getBoundingClientRect().right, side:$('#gside').getBoundingClientRect().right, pane:[$('#detailpane').scrollWidth,$('#detailpane').clientWidth], inner:w.innerWidth});
  const seg=$('.seg.execution'); seg.focus(); key(seg,'Enter'); await sleep(50); check('Enter on a bar selects it and the side pane shows exact times', st().selStep && /Lượt/.test($('#gside').textContent) && /đặt chỗ/.test($('#gside').textContent) && /bắt đầu chạy/.test($('#gside').textContent) && $('.seg.sel'), $('#gside').textContent.slice(0,120));
  const sel=st().selStep.id; await morePolls(3); check('the selected step survives polls', st().selStep && st().selStep.id===sel && $('.seg.sel'));
  f.style.width='640px'; await sleep(200); check('the selection survives a resize and the gantt scrolls inside its own box', st().selStep.id===sel && $('.gscroll').scrollWidth>=$('.gscroll').clientWidth && d.documentElement.scrollWidth<=w.innerWidth+1, {sw:$('.gscroll').scrollWidth, cw:$('.gscroll').clientWidth, page:d.documentElement.scrollWidth, inner:w.innerWidth}); f.style.width=W+'px'; await sleep(200);
  await select('P4'); const hist=$('.gtree .hist'); check('P4: the old attempt(s) are folded under lịch sử (n)', hist && /lịch sử \(\d+ lượt cũ\)/.test(hist.textContent) && $$('.grow.old').length>=1, hist&&hist.textContent);
  hist.querySelector('button.tg').click(); await sleep(50); check('unfolding shows the old attempt row dimmed', $$('.gtree .att').length>=2 && $$('.gchart .grow.old .seg').length>=1);
  check('P4 shows a blocked mark on the current attempt', $$('.mk').some(m=>/blocked|bị giữ/.test(m.title)));
  const J4=await (await fetch('/api/task?plan='+encodeURIComponent(st().selected.plan)+'&project_id='+encodeURIComponent(st().selected.project),{cache:'no-store'})).json(); const cur4=J4.gantt.rows.find(r=>r.active);
  if(w.innerWidth>=1100)check('P3-D: P4 whole range fits too', $('.gscroll').scrollWidth<=$('.gscroll').clientWidth+1, {sw:$('.gscroll').scrollWidth, cw:$('.gscroll').clientWidth});
  check('P4: the running attempt has a confirmed part and a distinct to_now part up to now, with the now line', cur4 && $('.seg.to_now[data-attempt="'+cur4.attempt+'"]') && $('.seg.to_now').dataset.confirmed==='false' && $$('.nowline').length>0 && Math.abs(new Date($('.gchart').dataset.w1).getTime()-new Date(J4.gantt.axis.now).getTime())<1000, cur4&&cur4.segments.map(s=>s.kind));
  await select('P3'); check('a closed plan with no attempt draws only its plan marks (approved, closed), no bars, no attempt rows', !$('.seg') && !$('.gtree .att') && $$('.mk.plan').length>=2, {segs:$$('.seg').length, att:$$('.gtree .att').length, marks:$$('.mk').map(m=>m.title)});
  await select('PB'); check('an unapproved plan draws nothing invented', !$('.seg') && !$('.gtree .att') && ($('#gempty')||$$('.mk').length===0), {gempty:!!$('#gempty'), marks:$$('.mk').map(m=>m.title)});
  await select('P5'); check('P5: a closed executor wait is a wait bar under the execution bar', $('.seg.wait') && $('.seg.wait').dataset.to);
  const r5=$('#grange'); r5.value='15m'; r5.dispatchEvent(new w.Event('change',{bubbles:true})); await sleep(50); check('the window select narrows the axis', st().gRange==='15m' && (new Date($('.gchart').dataset.w1).getTime()-new Date($('.gchart').dataset.w0).getTime())<=900000+1);
}
if(S==='gantt_now'){                                   // P2-A: the clock parts of the timeline move with the server time while the ledger is quiet
  await select('P4'); await sleep(1100); const cur=()=>$('.seg.to_now'); check('P4 has a to_now part', !!cur());
  const settled=()=>$$('.seg.execution').filter(e=>e.dataset.attempt!==cur().dataset.attempt).map(e=>({k:e.dataset.k, from:e.dataset.from, to:e.dataset.to, right:e.getBoundingClientRect().right}));
  cur().focus(); key(cur(),'Enter'); await sleep(50); const selId=st().selStep&&st().selStep.id; check('the to_now part can be selected', !!selId && /tới hiện tại/.test($('#gside').textContent));
  const seq0=seqOf(); const samples=[]; const before=settled();
  async function sample(){const e=cur(); const direct=await (await fetch('/api/task?plan='+encodeURIComponent(st().selected.plan)+'&project_id='+encodeURIComponent(st().selected.project),{cache:'no-store'})).json();
    return {to:e.dataset.to, left:e.getBoundingClientRect().left, now:st().axisNow, w1:$('.gchart').dataset.w1, seq:seqOf(), nowline:$('.nowline')&&$('.nowline').getBoundingClientRect().left, settledRight:settled()[0]&&settled()[0].right, t:Date.now(), serverNow:direct.gantt.axis.now, readMs:direct.server&&direct.server.read_ms}}
  for(let i=0;i<3;i++){await sleep(1100); samples.push(await sample())}            // virtual time: polls run, the server clock moves a little; every check is relative to the server clock
  out.samples=samples; const scale=s=>$('.gchart .grow').getBoundingClientRect().width/(new Date(s.w1).getTime()-new Date($('.gchart').dataset.w0).getTime());
  samples.forEach(s=>{s.pxPerSec=scale(s)*1000});
  check('the ledger did not move during the samples (seq still)', samples.every(s=>s.seq===seq0), samples.map(s=>s.seq));
  const t=samples.map(s=>new Date(s.to).getTime()), srv=samples.map(s=>new Date(s.serverNow).getTime());   // headless Chrome runs on virtual time: only the server clock is real here
  check('the to_now end moves forward on every quiet poll, in step with the server clock (≥ half of what a direct read advanced), and is exactly the published server now of that reply', t[1]>t[0] && t[2]>t[1] && srv[2]>srv[0] && t[2]-t[0]>=0.5*(srv[2]-srv[0]) && samples.every(s=>s.to===s.now && s.w1 && Math.abs(new Date(s.w1).getTime()-new Date(s.now).getTime())<1000), samples);
  check('the page is not behind the server by more than one poll (the reply it shows is at most 2.5 s older than a direct read)', samples.every(s=>new Date(s.serverNow).getTime()-new Date(s.now).getTime()<2500), samples.map(s=>[s.now,s.serverNow,s.readMs]));
  check('the axis stretches in pixels (pixels per second fall as the end moves), the settled bar keeps its timestamps, and the now line stays at the axis end', before.length>=1 && samples[2].pxPerSec<samples[0].pxPerSec && JSON.stringify(before.map(o=>[o.k,o.from,o.to]))===JSON.stringify(settled().map(o=>[o.k,o.from,o.to])) && samples.every(s=>Math.abs(s.nowline-$('.gchart .grow').getBoundingClientRect().right)<=10), {before, after:settled(), samples:samples.map(s=>[s.pxPerSec,s.nowline])});
  check('nothing unconfirmed became confirmed and no other to_now part appeared', $$('.seg.to_now').length===1 && cur().dataset.confirmed==='false' && $$('.seg.execution[data-attempt="'+cur().dataset.attempt+'"]').every(e=>new Date(e.dataset.to).getTime()<=new Date(cur().dataset.from).getTime()+1), $$('.seg').map(e=>[e.dataset.kind,e.dataset.confirmed]));
  check('the selected step, folds and focus survive the quiet repaints', st().selStep && st().selStep.id===selId && $('.seg.sel') && d.activeElement===$('.seg.sel'), {sel:st().selStep, active:d.activeElement&&d.activeElement.className});
  await fetch('/__drop?on=1'); await waitFor(()=>$('#conn').className==='bad', 20000, 'bad badge'); await sleep(300); const frozen=cur().dataset.to; await sleep(2600);
  check('disconnected: the to_now end is frozen and the timeline says the data is old', cur().dataset.to===frozen && $('#gstale') && /dữ liệu cũ/.test($('#gstale').textContent), {frozen, now:cur().dataset.to, label:$('#gstale')&&$('#gstale').textContent});
  await fetch('/__drop?on=0'); await waitFor(()=>$('#conn').className==='ok', 20000, 'ok badge again'); await waitFor(()=>new Date(cur().dataset.to).getTime()>new Date(frozen).getTime(), 20000, 'the end moves again');
  const after=[]; for(let i=0;i<2;i++){await sleep(1100); after.push(await sample())} out.after=after;
  check('reconnected: the end follows the server time again, no stale label, no double count (it is the published now of its reply, within one poll of a direct read)', after[1].to>after[0].to && after[0].to>frozen && after.every(s=>s.to===s.now && new Date(s.serverNow).getTime()-new Date(s.now).getTime()<2500) && !$('#gstale') && st().selStep && st().selStep.id===selId, {frozen, after});
}
if(S==='evid'){                                        // P2-B: the evidence of a bar or mark is its own attempt's / generation's, inheritance shown apart
  await select('P4'); const J=await (await fetch('/api/task?plan='+encodeURIComponent(st().selected.plan)+'&project_id='+encodeURIComponent(st().selected.project)+'&timeline=300',{cache:'no-store'})).json();
  const cur=J.gantt.rows.find(r=>r.current), oldRow=J.gantt.rows.find(r=>!r.current && r.node===cur.node);
  check('P4: a current attempt of a newer generation and an old attempt of generation 0', cur && oldRow && cur.generation>oldRow.generation && oldRow.generation===0, {cur:cur&&cur.generation, old:oldRow&&oldRow.generation});
  check('every evidence entry of a phần việc names its generation', (J.evidence_index||[]).some(x=>x.node) && J.evidence_index.filter(x=>x.node).every(x=>typeof x.generation==='number'), J.evidence_index.map(x=>[x.kind,x.node,x.generation]));
  const seg=$('.seg[data-attempt="'+cur.attempt+'"]'); seg.focus(); key(seg,'Enter'); await sleep(50); const side=()=>$('#gside').textContent;
  check('the current attempt (no output yet) shows no output of generation 0 and says it has none of its own', !/thế hệ 0\) đã tạo đầu ra|receipt đầu ra của phần việc|đã tạo đầu ra/.test(side()) && $('#evnone') && /chưa có đầu ra/.test(side()) && $$('#gside [data-k^="evk:"]').every(e=>e.textContent.indexOf('thế hệ '+cur.generation)>=0), side().slice(Math.max(0,side().indexOf('Đầu ra'))).slice(0,700));   // the package data set has more generations of P4 than the unit fixture
  const hist=$('.gtree .hist'); if(hist&&hist.querySelector('button.tg')){hist.querySelector('button.tg').click(); await sleep(50)}
  const oseg=$('.seg[data-attempt="'+oldRow.attempt+'"]'); oseg.focus(); key(oseg,'Enter'); await sleep(50);
  check('the old attempt shows its own output of generation 0', /thế hệ 0/.test(side()) && $$('#gside [data-k^="evk:"]').some(e=>/đã tạo đầu ra|receipt/.test(e.textContent)) && /lượt cũ/.test(side()), side().slice(0,300));
  const mark=$$('.mk').find(m=>m.dataset.row===oldRow.attempt && /đã tạo đầu ra/.test(m.title)); if(mark){mark.focus(); key(mark,'Enter'); await sleep(50)}
  check('the produced mark of the old attempt leads to the same evidence', mark && $$('#gside [data-k^="evk:"]').length>=1 && /đã tạo đầu ra/.test(side()), side().slice(0,200));
  await select('P9'); const J9=await (await fetch('/api/task?plan='+encodeURIComponent(st().selected.plan)+'&project_id='+encodeURIComponent(st().selected.project)+'&timeline=300',{cache:'no-store'})).json();
  const cur9=J9.gantt.rows.find(r=>r.current); check('P9: the current attempt inherits a resume artifact from generation 0 (model)', cur9 && cur9.inherits && cur9.inherits.length===1 && cur9.inherits[0].kind==='resume_artifact' && cur9.inherits[0].from_generation===0 && /^[0-9a-f]{64}$/.test(cur9.inherits[0].key), cur9&&cur9.inherits);
  if(!cur9||!cur9.inherits){check('P9: no current attempt with inheritance in the model (nothing more to check on this page)', false, J9.gantt.rows.map(r=>[r.attempt,r.current,r.generation]))} else {
  const s9=$('.seg[data-attempt="'+cur9.attempt+'"]'); s9.focus(); key(s9,'Enter'); await sleep(50);
  check('P9: its own output of generation 1 is listed and the inherited one apart with its origin and source', $$('#gside [data-k^="evk:"]').length>=1 && side().indexOf('thế hệ '+cur9.generation)>=0 && $('#inherit') && /Kế thừa/.test(side()) && /từ thế hệ 0/.test(side()) && /nodes\[C\]\.resume_artifact/.test(side()) && $('#gside [data-k="inh:'+cur9.inherits[0].key+'"]'), side().slice(-400));
  $('#gside [data-k="inh:'+cur9.inherits[0].key+'"] .ev-open').click(); await waitFor(()=>$('#gside [data-k="inh:'+cur9.inherits[0].key+'"] pre'), 5000, 'inherited content'); check('the inherited artifact can be opened in place', /artifact-C|fixture/.test($('#gside [data-k="inh:'+cur9.inherits[0].key+'"] pre').textContent), $('#gside [data-k="inh:'+cur9.inherits[0].key+'"] pre').textContent.slice(0,80));}
}
if(S==='p2a'){
  await select('P1'); const cards=()=>$$('details.need'); check('at least two questions', cards().length>=2, cards().length);
  const firstId=cards()[0].dataset.needId, secondId=cards()[1].dataset.needId; const second=cards()[1]; second.open=true; second.querySelector('summary').focus(); second.querySelector('button.copy').focus(); second.querySelector('button.copy').click(); await sleep(100);
  const sec=()=>cards().find(c=>c.dataset.needId===secondId);
  check('the second question is open and focused, its copy status shown', sec().open && d.activeElement.closest('details.need')===sec() && st().copied && st().copied.k.indexOf(secondId)>0, {copied:st().copied&&st().copied.k, open:sec().open});
  const r1=await signal('answer',{id:firstId}); const nBefore=cards().length; await waitFor(()=>cards().length<nBefore, 20000, 'first question answered and gone'); await morePolls(2);
  const stillOpen=cards().filter(c=>c.open); check('after the first question was answered, the open one is still the second (by id)', stillOpen.length===1 && stillOpen[0].dataset.needId===secondId && !cards().some(c=>c.dataset.needId===firstId), {open:stillOpen.map(c=>c.dataset.needId), want:secondId, answered:r1});
  check('focus stayed inside the second question', d.activeElement && d.activeElement.closest('details.need') && d.activeElement.closest('details.need').dataset.needId===secondId, d.activeElement&&d.activeElement.tagName);
  check('the copy status still belongs to the second question', st().copied && st().copied.k.indexOf(secondId)>0 && $('.copied'));
  const r2=await signal('answer',{id:secondId}); await waitFor(()=>!cards().some(c=>c.dataset.needId===secondId), 20000, 'second question answered'); await morePolls(1);
  const note=$('.stale-need'); check('when the question being read is answered, a note says it is no longer pending and the old template is void', note && note.dataset.staleId===secondId && /không còn hiệu lực/.test(note.textContent), note&&note.textContent.slice(0,160));
  check('its old template and copy status are gone', !$('.copied') && !cards().some(c=>c.dataset.needId===secondId) && st().stale.indexOf(secondId)>=0, st().stale);
  note.querySelector('.stale-hide').click(); await sleep(50); check('the note can be hidden', !$('.stale-need'));
}
// ==== R4 stale_detail (03/11, Codex release review P2): a failed or late detail request never leaves another task under the selection ====
if(S==='stale_detail'){
  const P1=rowOf('P1').dataset.plan, P8=rowOf('P8').dataset.plan;
  const fault=async q=>await (await fetch('/__fault?'+q,{cache:'no-store'})).json();
  const vis=el=>!!el && el.offsetParent!==null && el.getBoundingClientRect().height>0;
  const ds=()=>$('#dstatus'), dst=()=>st().detailState, dfor=()=>st().detailFor;
  const progress=step=>{out.notes.push('step '+step+' at polls '+polls); document.getElementById('out').textContent=JSON.stringify(Object.assign({}, out, {partial:true, ok:false}))};   // a budget overrun still reports how far it got
  await fault('detail=ok'); await select('P1');
  const p1={reqs:$$('#detail details.need').map(n=>n.dataset.needId).filter(Boolean), cmds:$$('#detail .need code').map(c=>c.textContent)};
  check('setup: P1 shows questions with reply commands', p1.reqs.length>=2 && p1.cmds.length>=2 && p1.cmds.every(c=>/question answer REQ-/.test(c)), p1);
  function leak(){const t=$('#detail').textContent, h=$('#dtitle')?$('#dtitle').textContent:'';
    return {req:p1.reqs.filter(id=>t.indexOf(id.slice(0,12))>=0), cmd:$$('#detail code').map(c=>c.textContent).filter(c=>/question answer/.test(c)), copy:$$('#detail button.copy').length,
            need:$$('#detail details.need').length, head:/(^|\W)P1(\W|$)/.test(h)?h:null, dataOfP1:!!(dfor() && dfor().plan===P1)}}
  function clean(L){return !L.req.length && !L.cmd.length && !L.copy && !L.need && !L.head && !L.dataOfP1}
  function selRows(){return $$('li.task[aria-selected="true"]').map(li=>li.querySelector('.name').textContent)}
  async function noDataError(label){                    // P8 selected while its detail fails: P8's heading + an error, nothing of P1, overview still OK
    for(let i=1;i<=3;i++){ await morePolls(1);
      const head=$('#dtitle')?$('#dtitle').textContent:null, rows=selRows(), L=leak();
      check(label+' poll '+i+': URL, selected row, selection and heading say P8', w.location.search.indexOf(encodeURIComponent(P8))>=0 && rows.length===1 && rows[0]==='P8' && st().selected && st().selected.plan===P8 && head && head.indexOf('P8')===0, {url:w.location.search, rows, head});
      check(label+' poll '+i+': nothing of P1 in the detail pane (REQ id, reply command, copy button, question card, heading, data)', clean(L), L);
      check(label+' poll '+i+': a visible detail-error state for P8', vis(ds()) && /không tải được chi tiết/i.test(ds().textContent) && dst()==='error' && st().detailError, {text:ds()&&ds().textContent, state:dst(), err:st().detailError});
      check(label+' poll '+i+': the overview badge still says OK (it describes the overview only)', $('#conn').className==='ok' && /kết nối OK/.test($('#conn').textContent), $('#conn').textContent);
      check(label+' poll '+i+': a separate detail indicator says the detail failed', vis($('#dconn')) && /lỗi/i.test($('#dconn').textContent), $('#dconn')&&$('#dconn').textContent);
    }}
  async function recovered(plan, label){const ok=await waitFor(()=>shown(plan) && !ds() && dst()==='ok', 12000, label);
    check(label, ok && dfor() && dfor().plan===rowOf(plan).dataset.plan && !st().detailError && $('#detail .gantt') && (!$('#dconn') || !/lỗi/i.test($('#dconn').textContent)), {head:$('#dtitle')&&$('#dtitle').textContent, state:dst(), dfor:dfor(), dconn:$('#dconn')&&$('#dconn').textContent})}
  // A. network failure (connection dropped like the Codex probe) for P8, never loaded
  progress('A drop'); await fault('detail=drop'); rowOf('P8').click(); await noDataError('drop');
  await fault('detail=ok'); await recovered('P8', 'drop removed: P8 content appears and the error goes');
  check('recovered P8 carries nothing of P1', clean(leak()), leak());
  // B. HTTP error status (503) for P8, never loaded
  progress('B 503'); await select('P1'); await fault('detail=error'); rowOf('P8').click(); await noDataError('http 503');
  await fault('detail=ok'); await recovered('P8', '503 removed: P8 content appears and the error goes');
  // C. the same task, already shown, then its detail fails: its data stays, marked stale, the reader's place kept
  progress('C stale'); await select('P1'); const card=$('#detail details.need'); card.open=true; $('#detail details[data-k="log"]').open=true;
  const pane=$('#detailpane'); pane.scrollTop=60; const cbtn=card.querySelector('button.copy'); cbtn.focus({preventScroll:true});
  const place=()=>({open:$$('#detail details[data-k]').filter(x=>x.open).map(x=>x.getAttribute('data-k')).sort().join('|'), focus:(d.activeElement&&d.activeElement.closest('[data-k]')?d.activeElement.closest('[data-k]').getAttribute('data-k'):null)+(d.activeElement&&d.activeElement.classList.contains('copy')?'/copy':''), pane:pane.scrollTop, win:w.scrollY});
  const before=place(); check('setup: a question open, its copy button focused', before.focus && /\/copy$/.test(before.focus) && before.open.indexOf('log')>=0, before);
  await fault('detail=drop');
  for(let i=1;i<=3;i++){ await morePolls(1); const now=place(), cards=$$('#detail details.need').map(n=>n.dataset.needId);
    check('stale poll '+i+': P1 and its questions stay under the P1 selection', shown('P1') && st().selected.plan===P1 && dfor() && dfor().plan===P1 && p1.reqs.every(id=>cards.indexOf(id)>=0), {cards, dfor:dfor()});
    check('stale poll '+i+': a visible freshness warning next to the heading (since when, data time)', vis(ds()) && /chưa cập nhật/i.test(ds().textContent) && /\d{1,2}:\d{2}:\d{2}/.test(ds().textContent) && dst()==='stale' && ds().previousElementSibling && ds().previousElementSibling.classList.contains('dhead'), {text:ds()&&ds().textContent, state:dst()});
    check('stale poll '+i+': every reply template is marked as from that time (the --revision guard is named)', $$('#detail details.need').length>0 && $$('#detail details.need').every(n=>n.querySelector('[data-stale-template]')) && /--revision/.test((ds()?ds().textContent:'')+' '+($('#detail details.need [data-stale-template]')?$('#detail details.need [data-stale-template]').textContent:'')), $$('#detail details.need').map(n=>!!n.querySelector('[data-stale-template]')));
    check('stale poll '+i+': the overview badge still says OK', $('#conn').className==='ok', $('#conn').textContent);
    check('stale poll '+i+': open sections, focus and scroll kept', JSON.stringify(now)===JSON.stringify(before), {before, now});
  }
  await fault('detail=error'); await morePolls(2);
  check('stale with HTTP 503: still P1 data with the warning, place kept', shown('P1') && vis(ds()) && /chưa cập nhật/i.test(ds().textContent) && dst()==='stale' && JSON.stringify(place())===JSON.stringify(before), {text:ds()&&ds().textContent, now:place(), before});
  await fault('detail=ok'); await recovered('P1', 'stale removed: the warning goes on recovery');
  check('after recovery: no template marked stale, open sections/focus/scroll kept', !$('#detail [data-stale-template]') && JSON.stringify(place())===JSON.stringify(before), {before, now:place()});
  // D. out of order: a delayed reply for P1 (success, network failure, HTTP error) arrives after P8 was selected and loaded: it never shows
  async function proxy(){return await fault('status=1')}
  // virtual time stands still while a page fetch is held by the proxy, so these loops wait on real network round trips, not on sleep()
  async function waitPending(){for(let i=0;i<4000;i++){const x=await proxy(); if(x.pending>0) return x} return null}
  async function waitAnswered(n){for(let i=0;i<4000;i++){const x=await proxy(); if(x.pending===0 && x.faulted>=n) return x} return null}
  for(const mode of ['ok','drop','error']){ progress('D late '+mode);
    await fault('detail=ok'); await select('P1');
    const base=(await proxy()).faulted; await fault('detail='+mode+'&plan='+encodeURIComponent(P1)+'&delay=1500');
    const pend=await waitPending(); rowOf('P8').click(); const p8=await waitFor(()=>shown('P8') && !ds(), 15000, 'P8 loaded while the P1 reply is held');
    const done=await waitAnswered(base+1); await morePolls(1); await sleep(200);
    check('late P1 reply ('+mode+') held in flight while P8 was selected', pend && p8 && done, {pend, done});
    check('late P1 reply ('+mode+') never shows: P8 stays, no error, nothing of P1', shown('P8') && !ds() && st().selected.plan===P8 && clean(leak()), {state:dst(), head:$('#dtitle')&&$('#dtitle').textContent, L:leak()});
  }
  await fault('detail=ok');
}
// ==== end R4 stale_detail ====
// ==== integration R4 x R1 slow_detail (03/11): slow or unrenderable detail replies; a copy that finishes after the selection changed ====
if(S==='slow_detail'){
  const P8=rowOf('P8').dataset.plan, iv=w.INTERVAL||1000, slow=Math.round(iv*2.5), real=w.fetch, rejections=[];
  w.addEventListener('unhandledrejection',ev=>{rejections.push(String(ev.reason&&ev.reason.message||ev.reason))});
  w.addEventListener('error',ev=>{rejections.push('error: '+String(ev.message))});
  const ds=()=>$('#dstatus'), dst=()=>st().detailState;
  let mode=null, issued=0;
  w.fetch=function(u,o){const p=real.call(w,u,o); if(typeof u!=='string'||u.indexOf('/api/task')!==0||!mode)return p; issued++;
    if(mode==='slow')return p.then(r=>new Promise(res=>w.setTimeout(()=>res(r),slow)));                    // the reply arrives 2.5 poll intervals later
    if(mode==='bad'&&u.indexOf(encodeURIComponent(P8))>=0)return p.then(()=>new w.Response('{}',{status:200,headers:{'Content-Type':'application/json'}}));   // a 200 the page cannot render
    if(mode==='fail')return p.then(()=>Promise.reject(new w.TypeError('Failed to fetch')));                // a network failure of every detail read
    if(mode==='partial'&&u.indexOf(encodeURIComponent(st().selected.plan))>=0)return p.then(r=>r.json()).then(j=>{j.source=Object.assign({},j.source,{last_seq:(j.source&&j.source.last_seq||0)+1000});j.needs_user=[];delete j.elapsed;
      return new w.Response(JSON.stringify(j),{status:200,headers:{'Content-Type':'application/json'}})});   // a newer reply without the open question whose tiles cannot be drawn (no elapsed)
    return p};
  await select('P1');
  // (a) every detail read takes 2.5 poll intervals: the selected task must still appear (pre-fix: each poll superseded the read in flight)
  mode='slow'; issued=0; const p0=polls; rowOf('P8').click();
  const P1cmds=()=>$$('#detail code').map(c=>c.textContent).filter(c=>/question answer/.test(c)).length;
  check('right after the click, before any reply: P8 loading pane, nothing of P1', $('#dtitle') && $('#dtitle').textContent.indexOf('P8')===0 && dst()==='loading' && ds() && ds().getAttribute('data-state')==='loading' && !P1cmds() && !$$('#detail details.need').length, {head:$('#dtitle')&&$('#dtitle').textContent, state:dst(), cmds:P1cmds()});
  const a=await waitFor(()=>shown('P8') && dst()==='ok' && st().detailFor && st().detailFor.plan===P8, iv*14, 'P8 painted with slow detail reads');
  check('a detail read slower than the poll interval still paints the selected task', a, {state:dst(), issued, polls:polls-p0, head:$('#dtitle')&&$('#dtitle').textContent});
  const p1=polls, i1=issued; await morePolls(6);
  check('slow reads are waited for, not re-issued on every poll', (issued-i1) <= Math.ceil((polls-p1)/2)+1, {issued:issued-i1, polls:polls-p1});
  check('the page stays on P8 data while reads are slow (no loading pane, no error)', shown('P8') && dst()==='ok' && !ds(), {state:dst()});
  mode=null; await morePolls(2);
  // (b) a 200 reply the page cannot render: P8 never loaded -> its own heading + an error, not "đang tải" forever
  await select('P1'); mode='bad'; rowOf('P8').click(); await morePolls(3);
  check('an unrenderable 200 reply puts the selection in the error state (not loading forever)', dst()==='error' && ds() && /không (hiển thị|tải) được chi tiết/i.test(ds().textContent) && $('#dtitle') && $('#dtitle').textContent.indexOf('P8')===0, {state:dst(), text:ds()&&ds().textContent});
  check('nothing of P1 under the P8 selection after the unrenderable reply', !$$('#detail details.need').length && !(st().detailFor && st().detailFor.plan!==P8), {needs:$$('#detail details.need').length, dfor:st().detailFor});
  // (c) recovery
  mode=null; const c=await waitFor(()=>shown('P8') && dst()==='ok' && !ds(), iv*8, 'P8 recovered');
  check('recovery after the unrenderable reply: P8 content, no warning', c, {state:dst()});
  // (d) a copy that finishes after the selection changed (the clipboard promise settles later) throws nothing
  await select('P1'); const btn=$('#detail details.need button.copy'); if(btn){$('#detail details.need').open=true; btn.click(); rowOf('P8').click()}
  await waitFor(()=>shown('P8'), iv*8, 'P8 after the copy'); await morePolls(2);
  check('setup: a copy button was clicked on P1 just before selecting P8', !!btn);
  // (e) the live elapsed tile never jumps backwards when the detail turns stale (it used to re-anchor at the re-render with the older data)
  await select('P1'); const tv=()=>{const e=$('.tile [data-live]');return e?parseFloat(e.getAttribute('data-live'))+(w.Date.now()-parseFloat(e.getAttribute('data-live-at')))/1000:null};
  await morePolls(2); const v0=tv(); mode='fail'; await waitFor(()=>dst()==='stale', iv*6, 'P1 stale'); const v1=tv();
  const tile=$('.tile [data-live]'), at=tile?parseFloat(tile.getAttribute('data-live-at')):NaN, okAt=st().detailOkAt?Date.parse(st().detailOkAt):NaN;   // virtual time: compare anchors, not clock values
  check('the live elapsed tile stays anchored at the arrival of its data when the detail turns stale (never re-anchored at the re-render)', tile && Math.abs(at-okAt)<=1, {at, okAt, v0, v1});
  mode=null; await waitFor(()=>dst()==='ok', iv*6, 'P1 recovered');
  // (f) a need without a reply template gets a plain data-time note while stale, never the --revision template note
  const tplless=['P6','P7','P2','P3'].find(n=>rowOf(n)); await select(tplless); const cards0=$$('#detail details.need');
  mode='fail'; await waitFor(()=>dst()==='stale', iv*6, tplless+' stale');
  const plain=$$('#detail details.need').filter(n=>!n.querySelector('.cmd code'));
  check('setup: a stale task with need cards that carry no reply template', cards0.length>0 && plain.length>0, {task:tplless, cards:cards0.length, plain:plain.length});
  check('a card without a reply template never claims a --revision template is stale', plain.every(n=>!n.querySelector('[data-stale-template]') && !/--revision/.test(n.textContent) && n.querySelector('[data-stale-data]')), plain.map(n=>n.textContent.slice(0,200)));
  mode=null; await waitFor(()=>dst()==='ok', iv*6, tplless+' recovered');
  // (g) a newer reply that drops the open question and cannot be drawn: it is never applied, so it leaves no 'no longer pending' note and the
  //     error streak keeps its start across repeated failures (merge-lens review of the integrated candidate)
  await select('P1'); const qcard=$('#detail details.need'); if(qcard)qcard.open=true; await morePolls(1);
  check('setup (g): P1 shows an open question card and no stale-question note', !!qcard && !$('#detail .stale-need'), {cards:$$('#detail details.need').length});
  mode='partial'; await waitFor(()=>dst()==='stale', iv*6, 'P1 stale after an unrenderable newer reply'); const since1=st().detailError&&st().detailError.since; await morePolls(2); const since2=st().detailError&&st().detailError.since;
  check('(g) the unrenderable newer reply leaves P1 data shown as stale', dst()==='stale' && shown('P1'), {state:dst()});
  check('(g) no "no longer pending" note for a reply that was never applied', !$('#detail .stale-need'), $('#detail .stale-need')&&$('#detail .stale-need').textContent.slice(0,200));
  check('(g) the error streak keeps its start time across repeated failures', !!since1 && since1===since2, {since1, since2});
  mode=null; await waitFor(()=>dst()==='ok', iv*6, 'P1 recovered after (g)');
  w.fetch=real;
  check('no unhandled rejection or page error during the whole scenario', rejections.length===0, rejections.slice(0,5));
}
// ==== end slow_detail ====
// ---- R1 provenance (lane R1, Codex release review of dev11) begin ----
if(S==='prov'){                                        // R1: evidence is attributed per occurrence (event, key), never per blob key; a long history never reads as "no output"; inherited + produced coexist
  await select('P9'); const api=async lim=>await (await fetch('/api/task?plan='+encodeURIComponent(st().selected.plan)+'&project_id='+encodeURIComponent(st().selected.project)+'&timeline='+lim,{cache:'no-store'})).json();
  const side=()=>$('#gside').textContent, outs=()=>$$('#gside [data-k^="evk:"]'); let J=await api(5000);
  const prod=J.timeline.filter(e=>e.kind==='node.produced'&&e.node==='C'), p0=prod.find(e=>e.generation===0), p1=prod.find(e=>e.generation===1);
  check('setup: P9 produced in generations 0 and 1 with byte-identical output (the same blob keys)', p0 && p1 && p0.evidence.length>=2 && p0.evidence.join()===p1.evidence.join(), prod.map(e=>[e.seq,e.generation,e.evidence]));
  if(p0&&p1){
  $('details[data-k="log"]').open=true; const oldBox=$('details[data-k="old:n:C"]'); if(oldBox)oldBox.open=true;
  $('[data-k="ev:'+p0.seq+'"]').click(); const box=await waitFor(()=>$('[data-k="evbox:'+p0.seq+'"]'),5000,'evbox of generation 0 node.produced');
  const rows0=box?Array.from(box.querySelectorAll('[data-k^="evk:"]')):[];
  check('the event log: node.produced of generation 0 lists each of its keys with generation-0 labels (not those of generation 1, which shares the bytes)', rows0.length===p0.evidence.length && rows0.every(r=>/thế hệ 0/.test(r.textContent) && !/thế hệ 1/.test(r.textContent)), rows0.map(r=>r.textContent.slice(0,160)));
  $('[data-k="ev:'+p0.seq+'"]').click(); await sleep(50);
  const seq0=seqOf(); await signal('prov_history'); await waitFor(()=>seqOf()>seq0 && st().detailSeq===seqOf(), 20000, 'the page re-read P9 after 310 new events');
  J=await api(300); check('setup: the page window (300) no longer holds generation 0 production', J.timeline_total>300 && !J.timeline.some(e=>e.seq===p0.seq), {total:J.timeline_total, shown:J.timeline.length});
  const oldRow=J.gantt.rows.find(r=>r.node==='C'&&r.generation===0); const hb=$('.gtree .hist button.tg'); if(hb&&hb.getAttribute('aria-expanded')==='false'){hb.click(); await sleep(50)}
  const oseg=oldRow&&$('.seg[data-attempt="'+oldRow.attempt+'"]'); if(oseg){oseg.focus(); key(oseg,'Enter'); await sleep(50)}
  check('the old generation row (outside the 300-event window) lists its outputs with thế hệ 0, never "không có đầu ra"', oseg && !$('#evnone') && !/không có đầu ra/.test(side()) && outs().filter(e=>/thế hệ 0/.test(e.textContent) && /node\.produced/.test(e.textContent)).length>=p0.evidence.length, side().slice(0,600));
  const log=$('details[data-k="log"]'); check('the event log says older events are not loaded, and where their evidence still is', log && /đang hiện 300\/\d+ sự kiện mới nhất/.test(log.textContent) && /Gantt/.test(log.textContent) && /Bằng chứng/.test(log.textContent), log&&log.querySelector('summary').textContent);
  const mark=$$('.mk').find(m=>parseInt(m.dataset.seq,10)===p0.seq); if(mark){mark.focus(); key(mark,'Enter'); await sleep(50)}
  check('the produced mark of generation 0 (outside the window) shows exactly that event\'s evidence', mark && outs().length===p0.evidence.length && outs().every(e=>/thế hệ 0/.test(e.textContent) && /node\.produced/.test(e.textContent)), side().slice(0,500));
  const seq1=seqOf(); const K=(await signal('prov_same')).result;
  await waitFor(()=>seqOf()>seq1 && st().detailSeq===seqOf(), 30000, 'the page re-read P9 after generation 2');
  J=await api(300); const cur=J.gantt.rows.find(r=>r.current);
  check('setup: generation 2 resumed from generation 1 artifact and produced the same key (model)', cur && cur.generation===2 && cur.inherits.some(x=>x.key===K && x.kind==='resume_artifact' && x.from_generation===1), cur&&cur.inherits);
  const s2=cur&&await waitFor(()=>$('.seg[data-attempt="'+cur.attempt+'"]'), 10000, 'the generation-2 bar'); if(s2){s2.focus(); key(s2,'Enter'); await sleep(50)}
  const inh=$('#gside [data-k="inh:'+K+'"]');
  check('same artifact: the current row lists it under "Đầu ra của lượt này" (thế hệ 2) AND under "Kế thừa" with its source (thế hệ 1, the production event)', $$('#gside [data-k^="evk:'+K+'"]').some(e=>/thế hệ 2/.test(e.textContent) && /node\.produced/.test(e.textContent)) && $('#inherit') && inh && /từ thế hệ 1/.test(inh.textContent) && inh.textContent.indexOf('#'+p1.seq)>=0, side().slice(-700));
  const ev=$('details[data-k="evidence"]'); if(ev)ev.open=true; const g=ev&&ev.querySelector('[data-k="evk:'+K+'"]');
  check('the evidence list groups the uses of one blob: generations 0, 1 and 2 under one key', g && /thế hệ 0/.test(g.textContent) && /thế hệ 1/.test(g.textContent) && /thế hệ 2/.test(g.textContent), g&&g.textContent.slice(0,400));
  const hb2=$('.gtree .hist button.tg'); if(hb2&&hb2.getAttribute('aria-expanded')==='false'){hb2.click(); await sleep(50)}
  const wrong=[], settled=[];                            // review round 1: attempt.* events (attempt.settled is an output) carry the attempt's control generation, never shown as the node generation
  for(const r of J.gantt.rows.filter(x=>x.node==='C')){const sg=$('.seg[data-attempt="'+r.attempt+'"]'); if(!sg){wrong.push(['no bar',r.attempt,r.generation]); continue} sg.focus(); key(sg,'Enter'); await sleep(50);
    for(const e of outs()){const gens=(e.textContent.match(/thế hệ \d+/g)||[]); if(/attempt\.settled/.test(e.textContent))settled.push(r.generation); if(gens.some(x=>x!=='thế hệ '+r.generation))wrong.push([r.generation,e.textContent.slice(0,160)])}}
  check('every step pane of node C lists only evidence of its own generation (incl. attempt.settled of the child task)', wrong.length===0 && settled.length>0, {wrong:wrong.slice(0,6), settled_in_rows:settled});
  const und=J.evidence_index.filter(x=>typeof x.seq==='number' && !x.attempt);   // integration: occurrences with no determined attempt, read where every use of a blob is listed
  const evU=$('details[data-k="evidence"]'); if(evU)evU.open=true; await sleep(50);
  const undRows=und.map(x=>{const g=evU&&evU.querySelector('[data-k="evk:'+x.key+'"]');return g?Array.from(g.querySelectorAll('ul.uses li')).find(li=>li.textContent.indexOf('#'+x.seq)>=0):null}).filter(Boolean);
  out.notes.push('occurrences without a determined attempt: '+und.length+', their use rows in the evidence list: '+undRows.length);
  check('setup: an occurrence with no determined attempt has its own use row in the evidence list', undRows.length>0, {und:und.length});
  check('an occurrence whose attempt or generation is not determined says so on the page', undRows.length>0 && undRows.every(li=>/lượt chưa xác định/.test(li.textContent)), undRows.slice(0,3).map(li=>li.textContent.slice(0,200)));
  const seq3=seqOf(); await signal('prov_more');        // review round 2: one more plain generation; the generation-2 row (inherited K, produced K) becomes history
  await waitFor(()=>seqOf()>seq3 && st().detailSeq===seqOf(), 30000, 'the page re-read P9 after generation 3');
  J=await api(300); const g2=J.gantt.rows.find(r=>r.node==='C'&&r.generation===2);
  check('setup: generation 3 is current, the generation-2 row is history', g2 && !g2.current && J.gantt.rows.some(r=>r.node==='C'&&r.generation===3&&r.current), J.gantt.rows.filter(r=>r.node==='C').map(r=>[r.generation,r.current]));
  const hb3=$('.gtree .hist button.tg'); if(hb3&&hb3.getAttribute('aria-expanded')==='false'){hb3.click(); await sleep(50)}
  let s3=null;                                          // the bar is re-queried each try: a poll may repaint the Gantt between the query and the key press
  for(let i=0;g2&&i<20;i++){s3=$('.seg[data-attempt="'+g2.attempt+'"]'); if(s3){s3.focus(); key(s3,'Enter'); await sleep(50); if(side().indexOf(g2.attempt.slice(0,16))>=0)break} else await sleep(200)}
  const inh3=$('#gside [data-k="inh:'+K+'"]');
  check('the generation-2 row, now history, still lists K under "Đầu ra của lượt này" (thế hệ 2) AND under "Kế thừa" from generation 1 with its source event', !!s3 && $$('#gside [data-k^="evk:'+K+'"]').some(e=>/thế hệ 2/.test(e.textContent) && /node\.produced/.test(e.textContent)) && !!$('#inherit') && !!inh3 && /từ thế hệ 1/.test(inh3.textContent) && inh3.textContent.indexOf('#'+p1.seq)>=0, {bar:!!s3, inherits:g2&&g2.inherits, pane:side().slice(-700)});
  const ev3=$('details[data-k="evidence"]'); if(ev3)ev3.open=true;
  const listed=ev3?Array.from(ev3.querySelectorAll(':scope > div[data-k^="evk:"]')).map(x=>x.getAttribute('data-k').slice(4)):[], opened=[];
  const door=k=>'/api/evidence?plan='+encodeURIComponent(st().selected.plan)+'&project_id='+encodeURIComponent(st().selected.project)+'&key='+k+'&format=text';
  for(const k of listed){const r=await fetch(door(k),{cache:'no-store'}); opened.push([k.slice(0,12), r.status])}
  check('the evidence list counts and lists only blobs that open (an identifier such as project_id / revision / plan sha is not a blob)', listed.length>0 && listed.length===J.evidence_keys.length && opened.every(x=>x[1]===200) && ev3.querySelector('summary').textContent.indexOf('('+listed.length+' mục trong kho')>=0 && listed.indexOf(J.project_id)<0, {listed:listed.length, keys:J.evidence_keys.length, bad:opened.filter(x=>x[1]!==200), summary:ev3&&ev3.querySelector('summary').textContent});
  const idr=/^[0-9a-f]{64}$/.test(J.project_id)?(await fetch(door(J.project_id),{cache:'no-store'})).status:null;
  check('an identifier asked at the evidence door is "not in the store" (404), not a source error (503)', idr===404, {project_id:J.project_id, status:idr});
  }
}
// ---- R1 provenance (lane R1) end ----
// ---- P2 (Codex's review of dev12): detail reads slower than 20 s. fk_*: the page on the test clock (FAKE), answers carry the real server's data;
//      rt_slow: real time through the proxy (only /api/task of P8 slowed), the page sampled every 500 ms, every API request logged by the proxy ----
if(S==='fk_fast'){                                     // control: quick answers keep the selected task fresh on every poll
  await fselect('P1'); const P8=rowOf('P8').dataset.plan; T0=fk.now(); rowOf('P8').click(); await fk.advance(0); snap('click');
  await fadv(20000,500);
  const mine=treqs(P8), done=mine.filter(r=>r.state==='delivered'), okAts=new Set(samples.map(x=>x.okAt).filter(Boolean));
  check('control: P8 painted right after its quick answer', samples.some(x=>x.t<=500&&x.loaded&&x.state==='ok'&&x.title.indexOf('P8')===0), samples.slice(0,3));
  check('control: every poll refreshed the detail (one read per poll, each one applied)', done.length>=8 && okAts.size>=8, {reads:mine.length, delivered:done.length, okAts:okAts.size});
  check('control: the overview kept polling and stayed OK', ovreqs().filter(r=>r.start>=T0).length>=8 && samples.every(x=>x.conn==='ok'), ovreqs().length);
  check('control: no status line once painted, nothing of P1 under P8', only('P8',samples) && samples.every(x=>x.cmds===0) && samples.filter(x=>x.loaded).every(x=>!x.dstatus), bad('P8',samples));
}
if(S==='fk_slow25'){                                   // P2: every read of P8 takes 25 s (more than 20 s); the overview stays quick
  await fselect('P1'); const P8=rowOf('P8').dataset.plan; fk.plans[P8]={delay:25000}; T0=fk.now(); rowOf('P8').click(); await fk.advance(0); snap('click');
  await fadv(30000,500);
  const mine=treqs(P8), first=mine[0], before=mine.filter(r=>r.start<T0+25000), painted=samples.find(x=>x.loaded&&x.state==='ok'&&x.title.indexOf('P8')===0);
  check('setup: the server answered the first P8 read after 25 s', first && first.state==='delivered' && first.end-first.start===25000, first&&{state:first.state, took:first.end===null?null:first.end-first.start});
  check('the 25 s answer of the selected task is painted (not thrown away by later polls)', painted && painted.t>=25000 && painted.t<=25500, {painted:painted||null, last:samples[samples.length-1]});
  check('one read at a time: no second P8 read started while the first was pending', before.length===1 && samples.every(x=>x.inflight<=1), {started:before.map(r=>r.start-T0)});
  check('the overview kept polling during the slow read', ovreqs().filter(r=>r.start>=T0&&r.start<T0+25000).length>=10 && samples.every(x=>x.conn==='ok'), ovreqs().filter(r=>r.start>=T0).length);
  check('nothing of P1 under P8 at any moment', only('P8',samples) && samples.every(x=>x.cmds===0), bad('P8',samples));
}
if(S==='fk_cycles'){                                   // P2: 130 s with every P8 read taking 25 s, the selection unchanged
  await fselect('P1'); const P8=rowOf('P8').dataset.plan; fk.plans[P8]={delay:25000}; T0=fk.now(); rowOf('P8').click(); await fk.advance(0); snap('click');
  await fadv(130000,1000);
  const mine=treqs(P8), done=mine.filter(r=>r.state==='delivered'), i0=samples.findIndex(x=>x.loaded&&x.state==='ok');
  check('P8 painted after its first 25 s answer', i0>=0 && samples[i0].t<=26000, i0>=0?samples[i0]:samples[samples.length-1]);
  check('after the first paint P8 stays shown (no loading pane, no error) while every refresh takes 25 s', i0>=0 && samples.slice(i0).every(x=>x.loaded&&x.state==='ok'&&!x.dstatus&&x.title.indexOf('P8')===0), i0>=0?samples.slice(i0).filter(x=>!(x.loaded&&x.state==='ok'&&!x.dstatus)).slice(0,3):null);
  check('reads never overlap and stay bounded (about one every 26 s)', samples.every(x=>x.inflight<=1) && mine.length>=4 && mine.length<=6, {reads:mine.length, starts:mine.map(r=>r.start-T0)});
  const late=done.filter(r=>r.end<=T0+128000), applied=late.filter(r=>samples.some(x=>x.okAt&&Date.parse(x.okAt)>=r.end));
  check('every answer the server gave was applied by the page (none thrown away)', late.length>=4 && applied.length===late.length, {answers:late.map(r=>r.end-T0), applied:applied.length});
}
if(S==='fk_switch'){                                   // the selection changes while the old read is pending: its late or out-of-order answer never shows
  const P1=rowOf('P1').dataset.plan, P8=rowOf('P8').dataset.plan;
  // (a) P1 pending 25 s; P8 selected at 5 s answers at 8 s; P1's answer would come at 25 s
  fk.plans[P1]={delay:25000}; fk.plans[P8]={delay:3000}; T0=fk.now(); rowOf('P1').click(); await fk.advance(0); snap('P1');
  await fadv(5000,500); const ia=samples.length; rowOf('P8').click(); await fk.advance(0); snap('P8'); await fadv(25000,500);
  const a=samples.slice(ia);                           // from the P8 click on (the sample taken at 5 s BEFORE the click still shows P1, rightly)
  check('(a) P8 painted from its own 3 s answer', a.some(x=>x.t<=8500&&x.loaded&&x.state==='ok'&&x.title.indexOf('P8')===0), a.slice(0,8));
  check('(a) from the P8 click on only P8 under the selection: never P1 data, evidence or commands', only('P8',a) && a.every(x=>x.cmds===0), bad('P8',a));
  // (b) out of order: P1 answers at 4 s, after P8 was selected at 1 s; P8 answers at 11 s
  $('#close').click(); await fk.advance(0); samples.length=0; fk.plans[P1]={delay:4000}; fk.plans[P8]={delay:10000};
  T0=fk.now(); rowOf('P1').click(); await fk.advance(0); await fadv(1000,500); const ib=samples.length; rowOf('P8').click(); await fk.advance(0); snap('P8'); await fadv(14000,500);
  const b=samples.slice(ib), wait=b.filter(x=>x.t<11000);
  check('(b) while P8 waits and P1 answers first: P8 heading, loading, nothing of P1', wait.length>0 && only('P8',wait) && wait.every(x=>!x.loaded&&x.cmds===0), bad('P8',wait));
  check('(b) P8 painted from its own answer at 11 s', b.some(x=>x.t>=11000&&x.t<=11500&&x.loaded&&x.state==='ok'&&x.title.indexOf('P8')===0), b.filter(x=>x.t>=10500).slice(0,3));
  // (c) P1, P8, P1 again within 2 s, every read 25 s: the last selection P1 is painted from its own answer, nothing of P8 under it
  $('#close').click(); await fk.advance(0); samples.length=0; fk.plans[P1]={delay:25000}; fk.plans[P8]={delay:25000};
  T0=fk.now(); rowOf('P1').click(); await fk.advance(0); await fadv(1000,500); rowOf('P8').click(); await fk.advance(0); await fadv(1000,500); const ic=samples.length; rowOf('P1').click(); await fk.advance(0); snap('P1 again');
  await fadv(30000,500);
  const c=samples.slice(ic);
  check('(c) the last selection P1 is painted from its own 25 s answer', c.some(x=>x.t>=27000&&x.t<=27500&&x.loaded&&x.state==='ok'&&x.title.indexOf('P1')===0), c.filter(x=>x.t>=26500).slice(0,3));
  check('(c) after the last click only P1 under the selection, never P8 data', only('P1',c), bad('P1',c));
}
if(S==='fk_timeout'){                                  // a read that never answers: a clear timeout, a few automatic tries, then the reader's button; the overview goes on
  await fselect('P1'); const P8=rowOf('P8').dataset.plan; fk.plans[P8]={hang:true}; T0=fk.now(); rowOf('P8').click(); await fk.advance(0); snap('click');
  await fadv(50000,1000);
  const r1=treqs(P8)[0], s47=samples.find(x=>x.t>=47000);
  check('setup: the first P8 read never got an answer', r1 && r1.pol && r1.pol.hang===true);
  check('after 45 s without an answer the page ends the wait: the read is cancelled at 45 s', r1 && r1.state==='aborted' && r1.end-r1.start===45000, r1&&{state:r1.state, took:r1.end===null?null:r1.end-r1.start});
  check('the timeout is said under the P8 heading (error state, the 45 s limit named, no "đang tải")', s47 && s47.title.indexOf('P8')===0 && s47.state==='error' && s47.dstatus==='error' && /45 s/.test(s47.dtext||'') && !/đang tải/.test(s47.dtext||''), s47||null);
  const s48=samples.find(x=>x.t>=48000);
  check('while the next automatic try is in flight the status line and the header say "đang thử lại"', s48 && /đang thử lại/.test(s48.dtext||'') && /đang thử lại/.test(s48.dconn||''), s48||null);
  await fadv(600000,5000);
  const all=treqs(P8), last=samples[samples.length-1];
  check('automatic tries are bounded: 3 reads of P8 in 10 minutes, never two at once', all.length===3 && samples.every(x=>x.inflight<=1), {reads:all.length, starts:all.slice(0,8).map(r=>r.start-T0)});
  check('after the third timeout the page stops trying and offers a retry button with the reason (the header says it stopped)', last.retry && last.dstatus==='error' && /45 s/.test(last.dtext||'') && /Thử lại/.test(last.dtext||'') && /ngừng tự thử/.test(last.dconn||''), last);
  check('the overview kept polling and stayed OK through the timeouts', ovreqs().filter(r=>r.start>T0+590000).length>=3 && last.conn==='ok', ovreqs().length);
  check('nothing of P1 under P8 during the timeouts', only('P8',samples) && samples.every(x=>x.cmds===0), bad('P8',samples));
  check('the status with the retry button fits the width (no horizontal page scroll)', d.documentElement.scrollWidth<=w.innerWidth+1, {scrollWidth:d.documentElement.scrollWidth, innerWidth:w.innerWidth});
  fk.plans[P8]={}; const k=treqs(P8).length, btn=$('#dretry'); if(btn){btn.focus();btn.click()} const k1=treqs(P8).length; await fk.advance(0); await fadv(3000,500);   // a keyboard user: focus, then Enter (a click)
  const end=samples[samples.length-1];
  check('recovery: the retry button starts one read at once and P8 is painted (then the normal one read per poll)', !!btn && k1===k+1 && end.loaded && end.state==='ok' && end.title.indexOf('P8')===0 && !end.dstatus && samples.every(x=>x.inflight<=1), {btn:!!btn, byClick:k1-k, after3s:treqs(P8).length-k, end});
  check('after the retry from the keyboard the focus is on the task heading, not lost at the top of the page', d.activeElement && d.activeElement.id==='dtitle', {active:d.activeElement&&(d.activeElement.id||d.activeElement.tagName)});
}
if(S==='fk_timeout1'){                                 // only the first read hangs: the page ends it, and the next automatic try paints P8 (finite recovery)
  await fselect('P1'); const P8=rowOf('P8').dataset.plan; let n=0; fk.plans[P8]=function(){n++;return n===1?{hang:true}:{}};
  T0=fk.now(); rowOf('P8').click(); await fk.advance(0); snap('click'); await fadv(60000,500);
  const painted=samples.find(x=>x.loaded&&x.state==='ok'&&x.title.indexOf('P8')===0), reads=treqs(P8);
  check('the hung read is ended by the page (cancelled), never left pending', reads.length>=1 && reads[0].state==='aborted', reads.map(r=>[r.start-T0, r.state]));
  check('P8 is painted by a later automatic try within 48 s', painted && painted.t<=48000, painted||samples[samples.length-1]);
  check('after recovery: no warning left, nothing of P1 under P8', samples[samples.length-1].state==='ok' && !samples[samples.length-1].dstatus && only('P8',samples), bad('P8',samples));
}
if(S==='fk_disc'){                                     // the connection drops while a slow P8 read is pending; back with 25 s answers: the same task again
  await fselect('P8'); const P8=rowOf('P8').dataset.plan; fk.plans[P8]={delay:25000}; T0=fk.now(); await fadv(4000,500);
  check('setup: a slow P8 read is pending when the connection drops', treqs(P8).some(r=>r.state==='pending'), treqs(P8).map(r=>r.state));
  fk.overview={fail:true}; fk.plans[P8]={fail:true}; fk.failPending(); await fadv(20000,1000,'lost');
  const lost=samples.filter(x=>x.tag==='lost'), during=treqs(P8).filter(r=>r.start>T0+4000&&r.start<=T0+24000);
  check('disconnected: the badge says so; P8 stays selected with its data marked stale', lost.some(x=>x.conn==='bad') && lost.every(x=>x.sel===P8&&x.loaded) && lost.some(x=>x.state==='stale'), lost.slice(-2));
  check('no detail read storm while disconnected', during.length<=2, during.length);
  fk.overview=null; fk.plans[P8]={delay:25000}; const T1=fk.now()-T0; await fadv(40000,1000,'back');
  const back=samples.filter(x=>x.tag==='back'), ok=back.find(x=>x.state==='ok'&&x.loaded&&!x.dstatus&&x.conn==='ok');
  check('reconnected with 25 s answers: the same task P8 is fresh again (no warning) within 30 s', ok && ok.title.indexOf('P8')===0 && ok.sel===P8 && ok.t-T1<=30000, {ok:ok||null, last:back[back.length-1]});
  check('reads never overlap, nothing of another task under P8', samples.every(x=>x.inflight<=1) && only('P8',samples) && samples.every(x=>x.cmds===0), bad('P8',samples));
}
if(S==='fk_ovhang'){                                   // found with P2, same kind of endless wait: the overview request never answers; the badge stops saying OK after 5 minutes, polling goes on
  await fselect('P8'); T0=fk.now(); fk.overview={hang:true}; await fadv(320000,5000);
  const hung=ovreqs().filter(r=>r.start>=T0&&r.pol&&r.pol.hang), s310=samples.find(x=>x.t>=310000);   // a request made before the switch at T0 is answered normally
  check('the hung overview request is cancelled after 5 minutes and polling goes on', hung.length>=2 && hung[0].state==='aborted' && hung[0].end-hung[0].start===300000, hung.slice(0,4).map(r=>[r.start-T0, r.state, r.end===null?null:r.end-r.start]));
  check('after 5 minutes without an overview answer the badge no longer says OK and says why', s310 && s310.conn==='bad' && /5 phút/.test(s310.ctext||''), s310||null);
  fk.overview=null; await fadv(320000,5000);          // the request already hung waits out its own 5 minutes; the next one is answered
  const end=samples[samples.length-1];
  check('the overview answers again: badge OK, P8 still selected and shown', end.conn==='ok' && end.sel===rowOf('P8').dataset.plan && end.loaded, end);
}
if(S==='fk_ovslow'){                                   // the overview answers in 50 s every time (a slow server, not a dead one): the page keeps working, the detail keeps refreshing
  await fselect('P8'); const P8=rowOf('P8').dataset.plan; T0=fk.now(); fk.overview={delay:50000}; await fadv(160000,2000);
  const ov=ovreqs().filter(r=>r.start>=T0&&r.pol&&r.pol.delay===50000), done=ov.filter(r=>r.state==='delivered'), after=treqs(P8).filter(r=>r.start>T0+50000);
  check('every slow overview answer is received (none cancelled) and polling goes on', done.length>=2 && ov.every(r=>r.state!=='aborted'), ov.map(r=>[r.start-T0, r.state]));
  check('the badge never says the connection is lost while the overview is merely slow', samples.every(x=>x.conn==='ok'), samples.filter(x=>x.conn!=='ok').slice(0,2));
  check('the detail of P8 is read again after each slow overview answer and stays shown', after.length>=2 && samples[samples.length-1].loaded && samples[samples.length-1].state==='ok', after.map(r=>[r.start-T0, r.state]));
}
if(S==='fk_mixed'){                                    // the detail alternates a read that never answers and a quick 503: the timeouts still add up and the page stops after 3
  await fselect('P1'); const P8=rowOf('P8').dataset.plan; let n=0; fk.plans[P8]=function(){n++;return n%2===1?{hang:true}:{status:503}};
  T0=fk.now(); rowOf('P8').click(); await fk.advance(0); snap('click'); await fadv(600000,5000);
  const reads=treqs(P8), hung=reads.filter(r=>r.pol&&r.pol.hang), last=samples[samples.length-1];
  check('the page stops after 3 timeouts even with quick errors in between (reads stay bounded)', hung.length===3 && reads.length<=6 && last.retry, {reads:reads.map(r=>[r.start-T0, r.state, r.pol&&r.pol.hang?'hang':r.pol&&r.pol.status]), last});
  check('never two reads at once, nothing of P1 under P8', samples.every(x=>x.inflight<=1) && only('P8',samples) && samples.every(x=>x.cmds===0), bad('P8',samples));
}
if(S==='fk_reselect'){                                 // close the task while its read hangs and open it again: a fresh read, never the old nearly expired one
  await fselect('P1'); const P8=rowOf('P8').dataset.plan; let n=0; fk.plans[P8]=function(){n++;return n===1?{hang:true}:{}};
  T0=fk.now(); rowOf('P8').click(); await fk.advance(0); snap('click'); await fadv(30000,1000);
  $('#close').click(); await fk.advance(0); await fadv(5000,1000); const ir=samples.length; rowOf('P8').click(); await fk.advance(0); snap('again'); await fadv(15000,500);
  const after=samples.slice(ir), reads=treqs(P8), painted=after.find(x=>x.loaded&&x.state==='ok'&&x.title.indexOf('P8')===0);
  check('closing cancels the pending read; opening again starts a fresh one', reads.length>=2 && reads[0].state==='aborted' && reads[0].end-reads[0].start===30000 && reads[1].start-T0===35000, reads.slice(0,3).map(r=>[r.start-T0, r.state, r.end===null?null:r.end-T0]));
  check('after opening again P8 is painted at once from the fresh read, with no timeout message', painted && painted.t<=36000 && after.every(x=>!/quá 45 s/.test(x.dtext||'')), {painted:painted||null, msgs:after.filter(x=>/quá 45 s/.test(x.dtext||'')).slice(0,2)});
}
if(S==='fk_reconnect'){                                // stopped after 3 timeouts, then the connection drops and comes back: the stop note goes, one new read starts and is said
  await fselect('P1'); const P8=rowOf('P8').dataset.plan; fk.plans[P8]={hang:true}; T0=fk.now(); rowOf('P8').click(); await fk.advance(0); await fadv(160000,5000);
  const stopped=samples[samples.length-1];
  check('setup: stopped after 3 timeouts with the retry button', stopped.retry && treqs(P8).length===3, {reads:treqs(P8).length, stopped});
  fk.overview={fail:true}; await fadv(3000,1000,'lost'); fk.overview=null; const k=treqs(P8).length; await fadv(2000,500,'back');
  const nr=treqs(P8)[k], back=samples.filter(x=>x.tag==='back'&&nr&&x.t>=nr.start-T0);   // from the reconnection on (a sample before the next overview answer rightly still shows the stop)
  check('after the reconnection one new read starts by itself', treqs(P8).length===k+1, {reads:treqs(P8).length-k});
  check('while it runs the status line no longer says "ngừng tự thử" nor offers the button; it and the header say "đang thử lại"', back.length>0 && back.every(x=>!x.retry&&!/ngừng tự thử/.test(x.dtext||'')&&/đang thử lại/.test(x.dtext||'')&&/đang thử lại/.test(x.dconn||'')), back.slice(-2));
  fk.plans[P8]={}; await fadv(50000,1000,'end');       // the read in flight still hangs: it ends at its 45 s, the next try is answered
  const end=samples[samples.length-1];
  check('then P8 is painted, no warning left', end.loaded && end.state==='ok' && !end.dstatus && end.title.indexOf('P8')===0, end);
}
if(S==='rt_slow'){                                     // REAL TIME (no virtual time, no test clock): the proxy slows only /api/task of P8
  const P8=rowOf('P8').dataset.plan, now=()=>Date.now()-T0;
  const log=async()=>(await (await fetch('/__log')).json()).log;
  const reads=l=>l.filter(e=>e.kind==='task'&&e.plan===P8).sort((a,b)=>a.t0-b.t0);
  // two P8 reads open at once in the PAGE: the next read started before the previous one ended (proxy end) and before the page's own 45 s limit
  // (a read the page cancelled at 45 s may stay open in the proxy, which holds it longer and only then finds the page gone)
  const overlap=l=>{const r=reads(l);for(let i=1;i<r.length;i++)if(r[i].t0<Math.min(r[i-1].t1||Infinity,r[i-1].t0+45)-0.1)return [r[i-1],r[i]];return null};
  async function every(ms,tag,until){const t1=now()+ms;while(now()<t1){await sleep(500);const x=snap(tag);if(until&&until(x))return x}return null}
  await select('P1'); await fetch('/__log?clear=1'); await fetch('/__fault?detail=ok&plan='+encodeURIComponent(P8)+'&delay=25000');
  T0=Date.now(); rowOf('P8').click(); snap('click');
  await every(31000,'A');                              // A: every P8 read takes 25 s
  let L=await log(); const first=reads(L)[0], ansAt=first&&first.t1?first.t1*1000-T0:null, painted=samples.find(x=>x.tag==='A'&&x.loaded&&x.state==='ok'&&x.title.indexOf('P8')===0);
  check('A setup: the server (through the proxy) answered the first P8 read after at least 25 s', first && first.t1 && (first.t1-first.t0)>=25, first||null);
  check('A: the slow answer of the selected task is painted within 3 s of the server answering', painted && ansAt!==null && painted.t>=ansAt-100 && painted.t<=ansAt+3000, {painted:painted||null, ansAt});
  check('A: one P8 read at a time (none started while another was pending)', !overlap(L), overlap(L));
  check('A: the overview kept polling and stayed OK', L.filter(e=>e.kind==='overview'&&e.t0*1000>=T0).length>=10 && samples.every(x=>x.conn==='ok'), L.filter(e=>e.kind==='overview').length);
  await every(20000,'B');                              // B: 20 s more, every read still 25 s
  const B=samples.filter(x=>x.tag==='B');
  check('B: P8 stays shown while each refresh takes 25 s (no loading pane, no error)', B.length>0 && B.every(x=>x.loaded&&x.state==='ok'&&!x.dstatus), B.filter(x=>!(x.loaded&&x.state==='ok'&&!x.dstatus)).slice(0,3));
  // C: the next P8 read is held 70 s by the proxy (longer than the page waits), later ones are quick. Every render of the status line is recorded
  //    as it happens (MutationObserver): the timeout state lasts less than one 500 ms sample when the next try is answered at once
  const trans=[], rec=()=>{const ds=$('#dstatus'),k=ds?ds.getAttribute('data-state')+'|'+ds.textContent.slice(0,200):'none';
    if(!trans.length||trans[trans.length-1].k!==k)trans.push({t:now(),k:k,state:ds?ds.getAttribute('data-state'):null,text:ds?ds.textContent.slice(0,260):null,title:$('#dtitle')?$('#dtitle').textContent.slice(0,24):'',loaded:!!$('#detail .dsum')})};
  const mo=new w.MutationObserver(rec); mo.observe($('#detail'),{childList:true,subtree:true,characterData:true}); rec();
  await fetch('/__fault?detail=ok&plan='+encodeURIComponent(P8)+'&delay=70000&count=1'); const TC=now();
  let stale=null; for(const t1=now()+110000; now()<t1 && !stale;){await sleep(500); snap('C'); stale=trans.find(x=>x.t>=TC&&x.state==='stale'&&/45 s/.test(x.text||''))||null}
  check('C: a read held longer than 45 s ends with a timeout message under P8, its data kept (stale)', stale && stale.title.indexOf('P8')===0 && stale.loaded, stale||trans.slice(-3));
  { let l=[],held=null,next=null;                       // measured at the proxy: the page gave up on the held read after 45 s (the next read may start up to one poll after the timeout)
    for(let i=0;i<24&&!next;i++){l=reads(await log());held=l.find(e=>e.t1==null||e.t1-e.t0>=60)||null;next=held&&l.find(e=>e.t0>held.t0)||null;if(!next)await sleep(250)}
    check('C: the page cancelled the held read after its 45 s limit (the next P8 read starts 45-48 s after it)', held && next && next.t0-held.t0>=44.9 && next.t0-held.t0<=48.5, {held:held||null, next:next||null}) }
  let fresh=null; for(const t1=now()+20000; now()<t1 && !fresh;){await sleep(500); snap('D'); fresh=stale?trans.find(x=>x.t>stale.t&&x.state===null&&x.loaded&&x.title.indexOf('P8')===0)||null:null}
  mo.disconnect(); out.transitions=trans;
  check('D: the next quick answer makes P8 fresh again (no warning) within 15 s of the timeout', fresh && stale && fresh.t-stale.t<=15000, fresh||trans.slice(-3));
  const tagged=samples.filter(x=>x.tag);
  check('nothing of P1 under P8 at any moment (A-D)', only('P8',tagged) && tagged.every(x=>x.cmds===0), bad('P8',tagged));
  L=await log(); check('A-D: reads of P8 never overlapped', !overlap(L), overlap(L));
  out.requests=L.map(e=>Object.assign({}, e, {t0:Math.round(e.t0*1000-T0), t1:e.t1?Math.round(e.t1*1000-T0):null}));
}
if(S==='shot-detail'){await select(qs.get('plan')||'P1'); if(qs.get('open')==='need'){const n=$('details.need'); if(n)n.open=true} else {const ev=$$('ol.ev > li').find(li=>li.querySelector('.clip')); if(ev){ev.click(); await waitFor(()=>$('.evbox'),3000)}}}
if(S==='shot-list'){}
out.ok=Object.values(out.checks).every(Boolean)&&Object.keys(out.checks).length>0;
}catch(e){out.error=String(e&&e.stack||e); out.ok=false}
out.polls=polls; out.scrollWidth=d&&d.documentElement.scrollWidth; out.innerWidth=w&&w.innerWidth;
if(FK||RT)out.samples=samples;
if(fk)out.fake={reqs:fk.reqs.map(r=>({id:r.id,kind:r.kind,plan:r.plan,start:r.start-T0,end:r.end===null?null:r.end-T0,state:r.state,pol:r.pol})),errors:fk.errors};
document.getElementById('out').textContent=JSON.stringify(out); document.title='done';
if(RT)fetch('/__release?id='+encodeURIComponent(qs.get('hold')||''));
})();
</script></body></html>'''
