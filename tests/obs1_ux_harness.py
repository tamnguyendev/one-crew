"""OBS-1 interaction harness: the real tracking page, driven in a real headless Chrome/Edge by a same-origin harness page.

`Proxy(target_url, on_signal=None)` serves `/__ux?s=<scenario>` (the harness page) and forwards every other path to the tracking server, so the
harness and the page share one origin and the harness can click, type, focus, scroll, reload and read the page in its iframe exactly as a
user would; `/__signal?name=…` calls `on_signal(name)` in the Python process (a ledger write while the reader is looking); `/__drop?on=1|0`
makes the proxy drop `/api/*` connections (the disconnected state). `run(browser, proxy_url, scenario, width, height, profile, budget)` runs one
scenario with the page laid out at that size (the harness sizes its iframe: headless Chrome clamps its own window at 500 px wide) and returns the
JSON the harness wrote (`ok`, `checks`, `notes`, `innerWidth`/`scrollWidth` of the page); a scenario counts real polls of the page (the connection
badge changes on every poll) and waits for at least three before judging what was preserved.

Scenarios (docs/obs1/UX-OBS-1.vi.md): ux01 (open sections/focus/scroll survive ≥ 3 polls AND a ledger write), ux02 (project filter closes a task
of another project), ux03 (question options with their commands, copy), ux04 (mouse + keyboard selection, detail in view, URL, reload, back),
ux05 (three done words/badges, time labels), ux06 (timeline groups, old history folded, seq ascending, a step's evidence opens), ux07 (list rows
carry no hash and no raw path as main text), ux08 (narrow layout: no horizontal page scroll, list/detail switch), race (a late reply for the
previously selected task never overwrites the selected one), disc (disconnect then reconnect keeps the selection). Shared by the unit tests
(tests/test_obs1_browser.py) and the package verifier (V14).
"""
import json
import re
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SIZES = {'desktop': (1280, 720), 'split': (640, 720), 'mobile': (390, 844)}


def chrome_args(exe, profile, width, height, budget):
    return [exe, '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', f'--user-data-dir={profile}', '--hide-scrollbars',
            f'--window-size={width},{height}', f'--virtual-time-budget={budget}']


def run(exe, proxy_url, scenario, width, height, profile, budget=30000, extra=''):
    """One scenario in a window of width×height; returns the harness result dict (or {'ok': False, 'error': …})."""
    url = f'{proxy_url}__ux?s={scenario}&w={width}&h={height}{extra}'
    done = subprocess.run(chrome_args(exe, profile, width, height, budget) + ['--dump-dom', url], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=240)
    found = re.search(r'<pre id="out">(.*?)</pre>', done.stdout, re.S)
    if not found: return {'ok': False, 'error': 'harness wrote no result', 'tail': done.stdout[-600:] + done.stderr[-300:]}
    text = found.group(1).replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').replace('&quot;', '"')
    try: return json.loads(text)
    except ValueError: return {'ok': False, 'error': 'harness result is not JSON', 'tail': text[:600]}


def screenshot(exe, proxy_url, scenario, width, height, profile, path, budget=15000, extra=''):
    url = f'{proxy_url}__ux?s={scenario}&w={width}&h={height}&shot=1{extra}'
    subprocess.run(chrome_args(exe, profile, width, height, budget) + [f'--screenshot={path}', url], capture_output=True, timeout=240)
    return Path(path).is_file()


class Proxy:
    def __init__(self, target, on_signal=None):
        state = {'drop': False}
        self.state = state

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *a): pass

            def _send(self, status, data, ctype):
                self.send_response(status); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(data))); self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(data)

            def do_GET(self):
                url = urllib.parse.urlsplit(self.path)
                if url.path == '/__ux':
                    return self._send(200, HARNESS.encode('utf-8'), 'text/html; charset=utf-8')
                if url.path == '/__signal':
                    name = urllib.parse.parse_qs(url.query).get('name', [''])[0]
                    result = on_signal(name) if on_signal else None
                    return self._send(200, json.dumps({'signal': name, 'result': result}, default=str).encode('utf-8'), 'application/json')
                if url.path == '/__drop':
                    state['drop'] = urllib.parse.parse_qs(url.query).get('on', ['0'])[0] == '1'
                    return self._send(200, b'{"ok":true}', 'application/json')
                if state['drop'] and url.path.startswith('/api/'):
                    self.close_connection = True; self.connection.close(); return
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
        self.server.shutdown(); self.server.server_close()


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
async function select(plan){rowOf(plan).click();return await waitFor(()=>$('#dtitle')&&$('#dtitle').textContent.indexOf(plan)===0, 10000, 'detail '+plan)}
function key(el,k){el.dispatchEvent(new w.KeyboardEvent('keydown',{key:k,bubbles:true,cancelable:true}))}
function seqOf(){const m=/seq (\d+)/.exec($('#conn').textContent);return m?parseInt(m[1],10):null}
async function signal(name){await fetch('/__signal?name='+encodeURIComponent(name))}
await new Promise(r=>{if(f.contentDocument&&f.contentDocument.readyState==='complete'&&f.contentWindow.location.pathname==='/')r();else f.addEventListener('load',r,{once:true})});
await loaded();
try{
if(S==='ux01'){
  await select('P1'); const pane=$('#detailpane');
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
  await select('P1'); const need=$('.need'); check('question card', need);
  const opts=Array.from(need.querySelectorAll('.opt')); check('two options with label and id', opts.length===2 && opts.every(o=>o.querySelector('b').textContent && /\(.+\)/.test(o.textContent)), opts.map(o=>o.textContent.slice(0,60)));
  const cmds=opts.map(o=>o.querySelector('code').textContent); check('each option has its own command with --choice <id>', cmds.length===2 && cmds.every(c=>/question answer REQ-\S+ --revision \S+ --choice \S+$/.test(c)) && cmds[0]!==cmds[1], cmds);
  check('the question text is readable', /\?/.test(need.querySelector('.q').textContent) && need.textContent.indexOf('[withheld]')>=0, need.querySelector('.q').textContent);
  check('no element answers the question (no answer/approve button)', !$$('#detail button').some(b=>/trả lời|duyệt|answer|approve/i.test(b.textContent)));
  const btn=opts[1].querySelector('button.copy'); btn.focus(); btn.click(); const done=await waitFor(()=>$('.copied'),5000,'copied status');
  check('copy reports exactly the second option command', done && done.getAttribute('data-copied')===cmds[1], {copied:done&&done.getAttribute('data-copied'), want:cmds[1]});
  check('focus stays on the copy button after the re-render', d.activeElement && d.activeElement.classList.contains('copy'));
  const before=seqOf(); await morePolls(2); check('copying wrote nothing to the ledger', seqOf()===before, {before, now:seqOf()});
  check('the request is still pending on the page', $('.need') && st().selected.plan);
}
if(S==='ux04'){
  const rows=$$('li.task'); check('rows are keyboard reachable (tabindex=0, role=option)', rows.length>=2 && rows.every(r=>r.getAttribute('tabindex')==='0'&&r.getAttribute('role')==='option'));
  const target=rows[rows.length-1]; const plan=target.querySelector('.name').textContent; target.scrollIntoView(); target.click(); await waitFor(()=>$('#dtitle')&&$('#dtitle').textContent.indexOf(plan)===0, 8000, 'detail by click');
  const r=$('#detailpane').getBoundingClientRect(); check('the detail is in view right after the click', r.top>=-1 && r.top<w.innerHeight*0.8 && r.height>50, {top:r.top, h:r.height, inner:w.innerHeight});
  check('the clicked row keeps focus (mouse selection)', d.activeElement===rowOf(plan) || d.activeElement===d.body, d.activeElement&&d.activeElement.tagName);
  check('the URL names the task', w.location.search.indexOf('plan=')>=0 && w.location.search.indexOf('project_id=')>=0, w.location.search);
  if(w.innerWidth<900){$('#back').click(); await sleep(100)}                      // narrow: the list must be on screen before the keyboard part
  const first=rowOf('P1'); first.focus(); key(first,'ArrowDown'); const second=d.activeElement; check('ArrowDown moves focus to the next row', second && second.classList.contains('task') && second!==first);
  const plan2=second.querySelector('.name').textContent; key(second,'Enter'); await waitFor(()=>$('#dtitle')&&$('#dtitle').textContent.indexOf(plan2)===0, 8000, 'detail by Enter');
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
  const badge=p=>{const r=rowOf(p);return r?{cls:r.querySelector('.st').className, text:r.querySelector('.st').textContent}:null};
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
}
if(S==='ux06'){
  await select('P4'); const grp=$$('section.grp').find(g=>/phần việc C/.test(g.querySelector('h4').textContent)); check('a group for phần việc C', grp);
  const old=grp&&grp.querySelector('details[data-k^="old:"]'); check('old attempt history is folded with a count', old && !old.open && /lịch sử cũ \(\d+/.test(old.querySelector('summary').textContent), old&&old.querySelector('summary').textContent);
  const seqs=grp?Array.from(grp.querySelectorAll(':scope > ol.ev > li')).map(li=>parseInt(li.dataset.seq,10)):[]; check('current events ascend (old → new)', seqs.length>0 && seqs.every((v,i)=>i===0||v>seqs[i-1]), seqs);
  const stale=old?old.querySelectorAll('li.stale').length:0; check('old attempt events are marked stale', stale>0, stale);
  const tech=grp&&grp.querySelector('details[data-k^="tech:"]'); check('technical events (attempt.*) are folded under their node', tech && !tech.open && /chi tiết kỹ thuật/.test(tech.querySelector('summary').textContent) && tech.querySelectorAll('li').length>=2, tech&&tech.textContent.slice(0,120));
  const main=grp?grp.querySelectorAll(':scope > ol.ev > li').length:0; check('the main list has fewer events than the whole group', main>0 && main < grp.querySelectorAll('li').length, {main, all:grp&&grp.querySelectorAll('li').length});
  const first=$$('li.task')[0]; await select('P2'); const ev=$$('ol.ev > li').find(li=>li.querySelector('.clip')); check('P2 has a step with evidence', ev);
  const seq=ev.dataset.seq; ev.click(); const box=await waitFor(()=>$('.evbox'),5000,'evbox');
  check('clicking the step shows its evidence with label, kind and time', box && box.querySelector('b') && box.querySelector('b').textContent.length>3 && /\b\w+\.\w+\b/.test(box.querySelector('.mut').textContent) && !/thời điểm chưa rõ/.test(box.querySelector('div').textContent), box&&box.textContent.slice(0,200));
  const btn=box&&box.querySelector('.ev-open'); btn.click(); const pre=await waitFor(()=>$('.evbox pre'),8000,'evidence content'); check('evidence content opens inline, redacted', pre && pre.textContent.length>0 && pre.textContent.indexOf('hunter2')<0 && pre.textContent.indexOf('sk-fixture-secret')<0, pre&&pre.textContent.slice(0,80));
  $('[data-k="ev:'+seq+'"]').click(); check('clicking the same step again folds it', !$('.evbox'));
}
if(S==='ux07'){
  const rows=$$('li.task'); check('rows exist', rows.length>=5);
  check('no 64-hex hash as list text', !/\b[0-9a-f]{64}\b/.test($('#list').textContent));
  check('rows carry status, name, current step and a relative update time', rows.every(r=>r.querySelector('.st')&&r.querySelector('.name')&&r.querySelector('.r2')&&/trước|vừa xong/.test(r.querySelector('.r2').textContent)), rows.map(r=>r.querySelector('.r2').textContent));
  check('full paths and ids are muted secondary text', rows.every(r=>r.querySelector('.r3.mut')) && !rows.some(r=>/^[a-z]:\\/i.test(r.querySelector('.r1').textContent)));
  check('the needs-you rows are marked', rowOf('P1').querySelector('.needb'));
  check('the header counts tasks and needs', /\d+ task/.test($('#count').textContent) && /cần bạn/.test($('#count').textContent), $('#count').textContent);
  $('#kind').value='blocked'; $('#kind').dispatchEvent(new w.Event('change',{bubbles:true})); check('status filter keeps only blocked', $$('li.task').length>=1 && $$('li.task').every(r=>r.querySelector('.st').classList.contains('blocked')));
  $('#kind').value='need'; $('#kind').dispatchEvent(new w.Event('change',{bubbles:true})); check('"cần bạn" filter keeps only rows with a need', $$('li.task').length>=1 && $$('li.task').every(r=>r.querySelector('.needb')));
  $('#kind').value=''; $('#q').value='P4'; $('#q').dispatchEvent(new w.Event('input',{bubbles:true})); check('search narrows to P4', $$('li.task').length===1 && rowOf('P4'));
  $('#q').value='nothing-matches-xyz'; $('#q').dispatchEvent(new w.Event('input',{bubbles:true})); check('no match says so', $$('li.task').length===0 && /không có task nào khớp/i.test($('#empty').textContent));
  $('#q').value=''; $('#q').dispatchEvent(new w.Event('input',{bubbles:true}));
}
if(S==='ux08'){
  const de=d.documentElement; check('no horizontal page scroll on the list', de.scrollWidth<=w.innerWidth+1, {scrollWidth:de.scrollWidth, inner:w.innerWidth});
  const narrow=w.innerWidth<900; check('narrow layout detected when the window is narrow', narrow===w.matchMedia('(max-width:899px)').matches);
  await select('P4'); check('no horizontal page scroll on the detail', de.scrollWidth<=w.innerWidth+1, {scrollWidth:de.scrollWidth, inner:w.innerWidth});
  if(narrow){check('narrow: the list is hidden and the detail shown', $('#listpane').offsetParent===null && $('#detailpane').offsetParent!==null && $('#back').offsetParent!==null);
    check('narrow: the detail starts in the upper part of the page (below the compact header)', w.scrollY===0 && $('#detailpane').getBoundingClientRect().top<w.innerHeight/3 && $('#dtitle').getBoundingClientRect().bottom<w.innerHeight/2, {y:w.scrollY, top:$('#detailpane').getBoundingClientRect().top, title:$('#dtitle').getBoundingClientRect().bottom});
    $('#back').click(); await sleep(100); check('narrow: back shows the list again', $('#listpane').offsetParent!==null && st().selected===null);}
  else{check('wide: list and detail side by side', $('#listpane').offsetParent!==null && $('#detailpane').offsetParent!==null && $('#detailpane').getBoundingClientRect().left>$('#listpane').getBoundingClientRect().left);}
  await select('P1'); const att=$('details[data-k="attempts"]'); if(att){att.open=true} check('technical tables scroll in their own box, not the page', de.scrollWidth<=w.innerWidth+1 && $$('.scroll').length>0, de.scrollWidth);
}
if(S==='race'){
  const real=w.fetch; w.fetch=function(u,o){const p=real.apply(this,arguments); if(String(u).indexOf('plan=')>=0 && String(u).indexOf(encodeURIComponent(rowOf('P1').dataset.plan))>=0) return p.then(r=>new Promise(res=>setTimeout(()=>res(r),1500))); return p};
  rowOf('P1').click(); await sleep(30); rowOf('P2').click(); await waitFor(()=>$('#dtitle')&&$('#dtitle').textContent.indexOf('P2')===0, 8000, 'P2 detail'); await sleep(2200);
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
if(S==='shot-detail'){await select(qs.get('plan')||'P1'); const ev=$$('ol.ev > li').find(li=>li.querySelector('.clip')); if(ev){ev.click(); await waitFor(()=>$('.evbox'),3000)}}
if(S==='shot-list'){}
out.ok=Object.values(out.checks).every(Boolean)&&Object.keys(out.checks).length>0;
}catch(e){out.error=String(e&&e.stack||e); out.ok=false}
out.polls=polls; out.scrollWidth=d&&d.documentElement.scrollWidth; out.innerWidth=w&&w.innerWidth;
document.getElementById('out').textContent=JSON.stringify(out); document.title='done';
})();
</script></body></html>'''
