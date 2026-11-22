"""UI58 milestone C (#33): the Công việc page and the task page on REAL OneCrew data (temporary ledgers, the shipped page script, the real
tracking server and a real headless browser).

What the owner asked for (19/11), as checks:
  1. the list, its stage filter and the task page agree on validity and next step; a result the list did not compare with the project says so
     (the list never hashes every project: it reuses the task page's last comparison, with its time); UI58-like data reads "từng đạt trên bản
     trước, cần kiểm lại trên bản đang xem";
  2. every open ledger request of a task shows its whole question, each option with its consequence and its command — two on one task, and each
     alone; a scope change (amended plan) is told apart from a ledger request;
  3. two projects with the same plan name, one holding a lease: only the card with that project's identity says it holds; a lease record without
     a project id is "chưa xác định", never "đang giữ";
  4. one line per row with state and next step (and who when known), the project only when several are in view; the task page's four tiles
     (output with an open action or the reason, still valid, next step prominent even with no known actor, your decision), "Xem sâu" sections
     opened on demand; back by button, Escape and browser back keeps the filter, the scroll position and the focus on the row, at 1280 and 375 px.

Self-contained (no sibling test import): the verifier reruns this module from a copy of tests/ against the installed wheel. Node.js and a
Chromium browser (Chrome or Edge) are required; their absence FAILS the test, never skips it.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger
from onecrew.snapshots import Snapshots
from onecrew.v2 import plan as plans, report, tracking, tracking_list, tracking_web, verdict
from onecrew.v2.verifiers import command

OK = [sys.executable, '-c', 'print("ok")']
BAD = [sys.executable, '-c', 'raise SystemExit(3)']
FIXABLE = [sys.executable, '-c', "import sys; ok = open('a.txt').read().startswith('ok'); print('ok' if ok else 'not yet'); sys.exit(0 if ok else 3)"]
NODE_FALLBACK = r'C:\Program Files\nodejs\node.exe'
BROWSERS = (r'C:\Program Files\Google\Chrome\Application\chrome.exe', r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
            r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', r'C:\Program Files\Microsoft\Edge\Application\msedge.exe')
INTERNAL_WORDS = ('verdict', 'receipt', 'pending', 'inconclusive', 'stopped_with_report', 'plan-ns:', 'undefined', 'null')


# ---- the ledger fixture (the same smallest contract as tests/test_ui58_status) ---------------------------------------------------------------

def milestone(mid='M1', argv=OK, **extra):
    return dict({'id': mid, 'title': 'Milestone ' + mid, 'verifier': {'type': 'command', 'config': {'argv': argv}}, 'covers': ['O1']}, **extra)


def plan_json(milestones, title='Sample', output='The sample exists'):
    return {'schema_version': 2, 'title': title, 'size': 'S',
            'understanding': {'restated_goal': 'Do the sample and prove it.', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']},
                              'assumptions': [], 'confidence': 'high', 'unknowns': []},
            'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'the file to work on is there'}],
            'output': [output], 'scope': {'owned': ['a.txt']}, 'non_goals': ['Nothing else'],
            'items': [{'id': 'I1', 'title': 'Do it', 'tier': 'must', 'milestone': 'M1'}],
            'milestones': milestones, 'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1}, 'profile_version': None}


def question(text, options, impact='Ảnh hưởng chung của câu hỏi', recommendation=None):
    return {'schema_version': 1, 'question': text, 'reason': 'Cần bạn chọn trước khi làm tiếp', 'impact': impact,
            'options': [{'id': i, 'label': l} for i, l in options], 'recommendation': recommendation or options[0][0],
            'action': {'type': 'owner-choice', 'parameters': {}}}


class Project:
    """One git project with its ledger on a shared state root."""

    def __init__(self, base, name, state):
        self.root = base / name; self.root.mkdir()
        self.git('init', '-q'); self.git('config', 'user.name', 'T'); self.git('config', 'user.email', 't@localhost')
        (self.root / 'a.txt').write_text('one\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'base')
        self.ledger = Ledger(self.root, state)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.PIPE).decode().strip()

    def plan(self, name, ms, approve=True, **kw):
        with contextlib.redirect_stderr(io.StringIO()):        # several plans on one project: the active-plan export warns, by design
            plans.propose(self.ledger, name, plan_json(ms, **kw), 'claude', workflow=True)
            os.environ.pop('ONECREW_ACTOR', None)
            if approve: plans.approve(self.ledger, name, 'owner', 'test fixture')

    def state(self, name):
        with self.ledger.transaction() as conn:
            return plans.derive(self.ledger, conn, name)

    def timed_out(self, name, mid='M1'):
        """What verdict.run records when the command passes its max_minutes: a receipt with timed_out and no exit code, judged inconclusive."""
        st = self.state(name)
        tree = command.artifact_sha(self.root)
        body = {'kind': 'command-receipt', 'plan': name, 'revision': 1, 'milestone': mid, 'argv': OK, 'exit_code': None, 'timed_out': True,
                'error': None, 'artifact_sha': tree, 'artifact_sha_after': tree, 'plan_sha': st['revisions'][1]['sha']}
        blob = Snapshots(self.ledger.state_root).blob(json.dumps(body, sort_keys=True).encode())
        with self.ledger.transaction(write=True) as conn:
            plans.emit(self.ledger, conn, st['task_id'], 'verdict.receipt_issued', {'plan': name, 'revision': 1, 'milestone': mid, 'receipt': blob})
        verdict.record(self.ledger, name, mid, 'inconclusive', 'command', blob, body['artifact_sha'])

    def ask(self, name, key, q):
        return self.ledger.create_request(self.state(name)['task_id'], key, q)

    def emit(self, name, kind, payload):
        st = self.state(name)
        with self.ledger.transaction(write=True) as conn:
            plans.emit(self.ledger, conn, st['task_id'], kind, payload)


def node():
    found = shutil.which('node') or (NODE_FALLBACK if Path(NODE_FALLBACK).is_file() else None)
    if not found: raise AssertionError('Node.js is required for this test (not on PATH, not at %s)' % NODE_FALLBACK)
    return found


def browser(*, prefer_edge=False):
    if prefer_edge:
        edge = next((path for path in BROWSERS if path.lower().endswith('msedge.exe') and Path(path).is_file()), None)
        edge = edge or shutil.which('msedge')
        if edge:
            return edge
    found = next((b for b in BROWSERS if Path(b).is_file()), None) or shutil.which('chrome') or shutil.which('msedge')
    if not found: raise AssertionError('a Chromium browser (Chrome or Edge) is required for this test')
    return found


STUB = ("var document={querySelector:function(){return {addEventListener:function(){},value:'',options:[],style:{}}},querySelectorAll:function(){return []},addEventListener:function(){}};"
        "var window={matchMedia:function(){return {matches:false,addEventListener:function(){}}},addEventListener:function(){},scrollTo:function(){},scrollY:0};"
        "var location={search:'',pathname:'/'};var history={pushState:function(){}};var localStorage={getItem:function(){return null},setItem:function(){}};"
        "function setInterval(){};function setTimeout(){};function fetch(){return {then:function(){return {then:function(){return {catch:function(){return {then:function(){}}}}}}}}};")


def js(expr, **data):
    """`expr` evaluated in the shipped page script's own scope (Node, stubbed DOM), with each keyword bound as a JS variable; `last` may be set."""
    page = tracking_web._page(1)
    body = page[page.index('<script>') + 8:page.rindex('</script>')]
    body = body.replace('(function(){', '', 1); body = body[:body.rindex('})();')]
    extra = ''.join(f'\n{"last" if k == "last" else "var " + k}={json.dumps(v, ensure_ascii=False)};' for k, v in data.items())
    result = subprocess.run([node(), '-'], input=STUB + body + extra + '\nconsole.log(JSON.stringify(' + expr + '));', text=True, encoding='utf8',
                            capture_output=True, timeout=60)
    if result.returncode: raise AssertionError(result.stderr[-2000:])
    return json.loads(result.stdout.strip().splitlines()[-1])


def text(markup):
    import re
    return ' '.join(re.sub(r'<[^>]+>', ' ', markup).replace('&gt;', '>').replace('&lt;', '<').replace('&quot;', '"').replace('&amp;', '&').split())


class Served:
    def __init__(self, state_root):
        self.server = tracking_web.make_server(state_root, interval=1.0)
        self.server.handle_error = lambda *a: None       # a browser closed mid-poll resets its socket: not a failure of the page
        self.url = tracking_web.url_of(self.server)

    def __enter__(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start(); return self

    def __exit__(self, *exc):
        self.server.shutdown(); self.server.server_close(); self.thread.join(10)

    def get(self, path):
        try:
            with urllib.request.urlopen(self.url.rstrip('/') + path, timeout=60) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def json(self, path):
        status, body = self.get(path)
        return status, json.loads(body.decode('utf-8'))


# ---- the CDP driver: a real headless Chromium, driven over its DevTools port (Node 22+ has WebSocket and fetch built in) ---------------------

def local_chromium_flags(urls):
    """Allow headless fixture pages to render inside a restricted Windows CI process."""
    if os.name != 'nt' or os.environ.get('CI') != 'true' or not urls:
        return []
    for url in urls:
        target = urllib.parse.urlsplit(url)
        if target.scheme != 'http' or target.hostname not in ('localhost', '127.0.0.1', '::1'):
            return []
    import ctypes
    # Windows defines GetCurrentProcessToken() as the pseudo-handle ((HANDLE)-4).
    if not ctypes.windll.advapi32.IsTokenRestricted(ctypes.c_void_p(-4)):
        return []
    # Nested renderer startup fails with ACCESS_DENIED under this token. The disposable
    # browser inherits the restricted token and uses an unreachable proxy off loopback.
    return ['--no-sandbox', '--disable-background-networking', '--proxy-server=http://127.0.0.1:0']

CDP = r'''
const {spawn}=require('child_process'),fs=require('fs'),path=require('path');
const [exe,profile,width,height,...fixtureFlags]=process.argv.slice(2);
let input='';process.stdin.on('data',d=>input+=d);process.stdin.on('end',()=>main().catch(e=>{console.log(JSON.stringify({error:String(e&&e.stack||e)}));process.exit(3)}));
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function main(){
  const steps=JSON.parse(input),portFile=path.join(profile,'DevToolsActivePort');try{fs.unlinkSync(portFile)}catch(e){}
  const p=spawn(exe,['--headless=new',...fixtureFlags,'--disable-gpu','--no-first-run','--no-default-browser-check','--disable-extensions','--user-data-dir='+profile,'--remote-debugging-port=0','about:blank'],{stdio:'ignore'});
  const kill=setTimeout(()=>{console.log(JSON.stringify({error:'timeout'}));try{p.kill()}catch(e){}process.exit(2)},240000);
  let port=null;for(let i=0;i<400&&!port;i++){try{port=fs.readFileSync(portFile,'utf8').split(/\r?\n/)[0]||null}catch(e){}if(!port)await sleep(100)}
  if(!port)throw new Error('the browser wrote no DevToolsActivePort');
  let list=[];for(let i=0;i<100;i++){try{list=await (await fetch('http://127.0.0.1:'+port+'/json/list')).json();if(list.some(t=>t.type==='page'))break}catch(e){}await sleep(100)}
  const page=list.find(t=>t.type==='page');if(!page)throw new Error('no page target');
  const ws=new WebSocket(page.webSocketDebuggerUrl);await new Promise((res,rej)=>{ws.onopen=res;ws.onerror=rej});
  let id=0;const pending={};ws.onmessage=ev=>{const m=JSON.parse(ev.data);if(m.id&&pending[m.id]){pending[m.id](m);delete pending[m.id]}};
  const send=(method,params)=>new Promise((res,rej)=>{const i=++id;pending[i]=m=>m.error?rej(new Error(method+': '+JSON.stringify(m.error))):res(m.result);ws.send(JSON.stringify({id:i,method,params:params||{}}))});
  const results=[];
  try{
    await send('Page.enable');await send('Runtime.enable');
    await send('Emulation.setDeviceMetricsOverride',{width:+width,height:+height,deviceScaleFactor:1,mobile:false});
    for(const st of steps){
      if(st.nav){await send('Page.navigate',{url:st.nav});await sleep(500);results.push({nav:st.nav});continue}
      const r=await send('Runtime.evaluate',{expression:'(async()=>{'+st.eval+'\n})()',awaitPromise:true,returnByValue:true,userGesture:true});
      if(r.exceptionDetails){results.push({error:(r.exceptionDetails.exception&&r.exceptionDetails.exception.description)||r.exceptionDetails.text});break}
      results.push({value:r.result.value})}
  }catch(e){results.push({error:String(e&&e.message||e)})}
  clearTimeout(kill);console.log(JSON.stringify({results}));try{await send('Browser.close')}catch(e){}try{ws.close()}catch(e){}try{p.kill()}catch(e){}setTimeout(()=>process.exit(0),300)}
'''

PRELUDE = r'''
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const until=async(f,ms,what)=>{const t0=Date.now();while(Date.now()-t0<(ms||30000)){try{const v=f();if(v)return v}catch(e){}await sleep(60)}throw new Error('timeout: '+(what||''))};
const key=(el,k)=>el.dispatchEvent(new KeyboardEvent('keydown',{key:k,bubbles:true,cancelable:true}));
const $=s=>document.querySelector(s),$$=s=>Array.from(document.querySelectorAll(s));
const overflow=()=>document.documentElement.scrollWidth-window.innerWidth;
'''


def drive(temp, url_steps, width, height):
    """Run the steps ({'nav': url} or {'eval': js}) in a real headless browser of `width` x `height`; the list of results."""
    work = Path(temp) / f'cdp-{width}'
    work.mkdir(exist_ok=True)
    script = work / 'cdp.cjs'; script.write_text(CDP, encoding='utf-8')
    steps = [s if 'nav' in s else {'eval': PRELUDE + s['eval']} for s in url_steps]
    flags = local_chromium_flags([step['nav'] for step in steps if 'nav' in step])
    # Edge can open its DevTools port under the restricted Windows fixture token.
    done = subprocess.run([node(), str(script), browser(prefer_edge=bool(flags)), str(work / 'profile'), str(width), str(height), *flags],
                          input=json.dumps(steps), text=True,
                          encoding='utf-8', capture_output=True, timeout=300)
    lines = [l for l in done.stdout.strip().splitlines() if l.startswith('{')]
    if not lines: raise AssertionError('the browser driver returned nothing: ' + done.stderr[-1500:])
    out = json.loads(lines[-1])
    if out.get('error'): raise AssertionError(out['error'])
    errors = [r['error'] for r in out['results'] if 'error' in r]
    if errors: raise AssertionError(errors[0])
    return [r.get('value') for r in out['results'] if 'value' in r]


# ---- the shared ledger: project A (eleven plans) and project B (a plan with A's name) on one state root -----------------------------------

class _Built:
    """The shared ledger, built once per run of this module (setUpModule) and read by every class below."""
    @classmethod
    def build(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='ui33-mc-')
        base = Path(cls.temp.name)
        cls.env = patch.dict(os.environ, {'ONECREW_LEASE_HOME': str(base / 'leases')}); cls.env.start()
        for name in ('ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(name, None)
        state = base / 'state'
        a = cls.a = Project(base, 'du-an-a', state)
        b = cls.b = Project(base, 'du-an-b', state)
        cls.state_root = a.ledger.state_root
        a.plan('P1', [milestone('M1', OK, max_repairs=3), milestone('M2')], title='Một: đạt rồi mã đổi')
        a.plan('P2', [milestone('M1', OK, max_repairs=3), milestone('M2')], title='Hai: lần kiểm hết giờ')
        a.plan('P3', [milestone('M1', FIXABLE, max_repairs=3), milestone('M2')], title='Ba: không đạt, sửa, kiểm lại')
        a.plan('P4', [milestone('M1', BAD, max_repairs=3), milestone('M2')], title='Bốn: không đạt thật')
        a.plan('P5', [milestone('M1')], title='Năm: hợp đồng bản đầu', output='Bản đầu của đầu ra')
        a.plan('P6', [milestone('M1')], title='Sáu: hai câu hỏi')
        a.plan('P7', [milestone('M1')], title='Bảy: chỉ câu hỏi A')
        a.plan('P8', [milestone('M1')], title='Tám: chỉ câu hỏi B')
        a.plan('P9', [milestone('M1')], title='Chín: có lúc chờ')
        a.plan('P10', [milestone('M1')], title='Mười: chưa có gì')
        a.plan('P11', [milestone('M1')], title='Mười một: chưa làm')
        b.plan('P1', [milestone('M1')], title='Dự án B: cùng tên kế hoạch')
        verdict.run(a.ledger, 'P1', 'M1')                       # pass on 'one'
        a.timed_out('P2')                                       # inconclusive
        verdict.run(a.ledger, 'P3', 'M1')                       # fail: a.txt is not 'ok'
        verdict.run(a.ledger, 'P4', 'M1')                       # fail: exit 3
        (a.root / 'a.txt').write_text('ok after the fix\n')     # the fix: P1's pass is now on an earlier version
        verdict.run(a.ledger, 'P3', 'M1')                       # recheck after the fix: pass
        with contextlib.redirect_stderr(io.StringIO()):
            plans.amend(a.ledger, 'P5', plan_json([milestone('M1')], title='Năm: phạm vi mới sau khi đổi', output='Bản mới của đầu ra'),
                        'Chủ yêu cầu thêm phần xuất báo cáo', 'claude')
        cls.qa = question('Dùng máy kiểm nào cho lần chạy tới?', [('local', 'Máy này'), ('ci', 'Máy CI chung')], impact='Thời gian chờ của lần kiểm')
        cls.qb = question('Giữ hay bỏ màn hình cũ?', [('keep', 'Giữ màn hình cũ'), ('drop', 'Bỏ màn hình cũ'), ('later', 'Để sau')], impact='Phạm vi giao diện')
        a.ask('P6', 'qa', cls.qa); a.ask('P6', 'qb', cls.qb)
        a.ask('P7', 'qa', cls.qa)
        a.ask('P8', 'qb', cls.qb)
        a.emit('P9', 'workflow.mode', {'node': 'N1', 'mode': 'wait', 'mode_reasons': 'chờ máy kiểm thử rảnh'})
        a.emit('P9', 'workflow.mode', {'node': 'N1', 'mode': 'sequential', 'mode_reasons': 'máy đã rảnh'})
        a.emit('P9', 'workflow.mode', {'node': 'N2', 'mode': 'wait', 'mode_reasons': 'chờ chủ gửi dữ liệu mẫu'})
        # leases: A's P1 holds 'gpu'; a record of plan P1 with no project id waits for 'db'
        from onecrew.resource_lease import Leases
        leases = Leases(base / 'leases'); leases.declare(['gpu', 'db'])
        cls.a_id, cls.b_id = a.ledger.project_id, b.ledger.project_id
        leases.claim('gpu', plan='P1', state_root=str(cls.state_root), project_id=cls.a_id, project=str(a.root), session='s-a', pid=os.getpid())
        leases.claim('db', plan='P1', state_root=str(cls.state_root), session='s-x', pid=os.getpid())



def setUpModule():
    _Built.build()


def tearDownModule():
    if getattr(_Built, 'env', None): _Built.env.stop()
    if getattr(_Built, 'temp', None): _Built.temp.cleanup()


class Shared(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for name in ('temp', 'a', 'b', 'state_root', 'qa', 'qb', 'a_id', 'b_id'): setattr(cls, name, getattr(_Built, name))

    def detail(self, name, project=None):
        return tracking.detail(self.state_root, name, project_id=(project or self.a).ledger.project_id)

    def listed(self, query=None, project=None):
        page = tracking_list.page(self.state_root, dict({'list': '1', 'limit': '50'}, **(query or {})),
                                  project_id=project.ledger.project_id if project else None)
        return page, {(t['project_id'], t['plan']): t for p in page['projects'] for t in p['tasks']}

    def row(self, rows, name, project=None):
        return rows[((project or self.a).ledger.project_id, name)]


# ---- 1. one truth for validity and next step ------------------------------------------------------------------------------------------------

class Consistency(Shared):
    def test_list_not_compared_said(self):
        tracking._compared.clear()                         # nothing compared yet in this process
        page, rows = self.listed()
        p1 = self.row(rows, 'P1')
        self.assertIsNone(p1['compared'])
        self.assertEqual(p1['validity']['kind'], 'not_compared')
        self.assertIn('chưa so', p1['validity']['label'])
        self.assertNotIn('Còn đúng', p1['validity']['label'])
        self.assertEqual(self.row(rows, 'P3')['validity']['kind'], 'not_compared')     # P3 passed after its fix: still not compared by the list
        self.assertGreaterEqual(page['list']['validity']['not_compared'], 2)
        self.assertEqual(page['list']['validity']['recheck'], 0)
        self.assertIn('không băm', page['list']['validity']['note'])
        line = text(js('statusLine(t)', t=p1))
        self.assertIn('chưa so với bản hiện tại', line)
        foot = text(js('footHtml()', last=page))
        self.assertIn('chưa so kết quả kiểm với bản hiện tại', foot)
        self.assertIn('chỉ gồm việc đã so', foot)
        # the stage filter "Cần kiểm lại" finds nothing it could not compare, and says so in the counts it returns
        page, rows = self.listed({'stage': 'recheck'})
        self.assertEqual(page['list']['shown'], 0)

    def test_three_cases_same_ledger(self):
        tracking._compared.clear()
        pages = {name: self.detail(name) for name in ('P1', 'P2', 'P3', 'P4')}
        # the task page compares like plan report: P1 passed on the earlier version and needs a recheck on the current one
        p1 = pages['P1']
        self.assertEqual((p1['validity']['kind'], p1['validity']['label']), ('recheck', 'Cần kiểm lại'))
        self.assertIn('từng đạt trên bản trước', p1['validity']['text'])
        self.assertIn('cần kiểm lại trên bản này', p1['validity']['text'])
        self.assertIn('từng đạt trên bản trước, cần kiểm lại trên bản đang xem', p1['situation']['reason'])
        self.assertEqual(p1['situation']['next'], 'Kiểm lại mốc M1')
        self.assertEqual(pages['P2']['situation']['label'], 'Chưa kết luận')
        self.assertEqual(pages['P3']['validity']['kind'], 'valid')
        self.assertEqual(pages['P4']['situation']['label'], 'Cần sửa')
        # the list reuses those comparisons (no hash of its own) and says when they were made: same validity, same stage, same next step
        page, rows = self.listed()
        for name, d in pages.items():
            r = self.row(rows, name)
            self.assertEqual(r['validity']['kind'], d['validity']['kind'], name)
            self.assertEqual((r['situation']['label'], r['situation']['next']), (d['situation']['label'], d['situation']['next']), name)
            self.assertEqual(r['compared_by'], 'task_page', name)
            if r['validity']['kind'] in ('valid', 'recheck'):              # a result that depends on the comparison says when it was made
                self.assertIn('theo lần so của trang việc lúc', r['validity']['text'], name)
        self.assertEqual(page['list']['validity']['recheck'], 1)
        # the stage filter and the chip count the same thing the card says
        page, rows = self.listed({'stage': 'recheck'})
        self.assertEqual([t['plan'] for p in page['projects'] for t in p['tasks']], ['P1'])
        self.assertEqual(js('visible().length', last=self.listed()[0]), len(self.listed()[1]))
        self.assertEqual(js('tasks().filter(isRecheck).map(function(t){return t.plan})', last=self.listed()[0]), ['P1'])
        # a new ledger event drops the reused comparison: the list says "not compared" again rather than an old answer
        self.a.emit('P1', 'notice.exception', {'category': 'test', 'reason': 'một sự kiện mới'})
        r = self.row(self.listed()[1], 'P1')
        self.assertEqual(r['validity']['kind'], 'not_compared')
        self.assertIsNone(r['compared_at'])


# ---- 2. decisions -------------------------------------------------------------------------------------------------------------------------

BOUND = {'verified': True, 'runtime': 'onecrew.exe', 'reason': None}


class Decisions(Shared):
    def need_html(self, d):
        return ''.join(js('needCard(n,0)', n=n) for n in d['needs_user'])

    def test_two_decisions_same_task_and_each_alone(self):
        with patch.object(tracking, '_runtime_binding', return_value=BOUND):        # the hook binding exists only on a real install: assume it to see the templates
            both, only_a, only_b = self.detail('P6'), self.detail('P7'), self.detail('P8')
        asks = [n for n in both['needs_user'] if n['kind'] == 'request']
        self.assertEqual(len(asks), 2)
        self.assertEqual({n['question'] for n in asks}, {self.qa['question'], self.qb['question']})
        self.assertEqual(len({n['id'] for n in asks}), 2)
        html = self.need_html(both)
        words = text(html)
        for q, impact in ((self.qa, 'Thời gian chờ của lần kiểm'), (self.qb, 'Phạm vi giao diện')):
            self.assertIn(q['question'], words)
            for o in q['options']:
                self.assertIn(o['label'], words)
            self.assertIn(impact, words)
        self.assertEqual(html.count('<div class="opt"'), 5)                        # 2 + 3 options, none lost
        self.assertEqual(html.count('Hệ quả:'), 5)
        self.assertEqual(words.count('câu hỏi không ghi hệ quả riêng cho lựa chọn này'), 5)
        for n in asks:
            for o in n['options']:
                self.assertIn(n['id'], o['human_command'])
                self.assertIn("--choice '" + o['id'] + "'", o['human_command'])
            self.assertEqual(n['source_label'], 'Yêu cầu trong sổ (chờ bạn trả lời)')
        self.assertEqual(html.count('data-copy="'), 5)
        self.assertEqual(words.count('owner answer'), 5)                             # each option's own command, shown once
        self.assertEqual(html.count(' open>'), 2)                                    # a ledger request opens with everything in it
        tile = text(js('tileDecide(d)', d=both))
        self.assertIn('Bạn cần quyết gì (2)', tile)
        self.assertIn(self.qa['question'], tile); self.assertIn(self.qb['question'][:60], tile)
        # each alone: its own question, options and command; nothing of the other
        for d, mine, other in ((only_a, self.qa, self.qb), (only_b, self.qb, self.qa)):
            html = self.need_html(d); words = text(html)
            self.assertIn(mine['question'], words); self.assertNotIn(other['question'], words)
            self.assertEqual(html.count('<div class="opt"'), len(mine['options']))
            self.assertEqual(html.count('data-copy="'), len(mine['options']))

    def test_scope_change_told_apart_from_a_request(self):
        d = self.detail('P5')
        need = next(n for n in d['needs_user'] if n['kind'] == 'approve')
        self.assertEqual(need['source_kind'], 'scope_change')
        self.assertIn('Đề xuất đổi phạm vi: bản 2', need['source_label'])
        ask = next(n for n in self.detail('P7')['needs_user'] if n['kind'] == 'request')
        self.assertEqual(ask['source_kind'], 'ledger_request')
        self.assertIn('Đề xuất đổi phạm vi', text(js('tileDecide(d)', d=d)))
        self.assertNotIn('chat', text(js('tileDecide(d)', d=d)).lower())             # the page shows ledger requests only; it invents no chat question


# ---- 3. leases ------------------------------------------------------------------------------------------------------------------------------

class LeaseCards(Shared):
    def test_same_plan_name_two_projects_lease(self):
        with Served(self.state_root) as s:
            status, overview = s.json('/api/overview?list=1')
            self.assertEqual(status, 200)
            details = {}
            for who, pid in (('a', self.a_id), ('b', self.b_id)):
                status, details[who] = s.json('/api/task?plan=' + urllib.parse.quote(self.row(self.listed()[1], 'P1', getattr(self, who))['selector'])
                                               + '&project_id=' + pid)
                self.assertEqual(status, 200)
        self.assertEqual(details['a']['plan'], details['b']['plan'])
        self.assertNotEqual(details['a']['project_id'], details['b']['project_id'])
        a = js('hostPlanPanel(d)', last=overview, d=details['a'])
        b = js('hostPlanPanel(d)', last=overview, d=details['b'])
        self.assertIn('id="resplan"', a)
        self.assertIn('data-resource="gpu"', a.split('id="resunsure"')[0])
        self.assertIn('Giữ:', a)
        self.assertNotIn('id="resplan"', b)                                           # project B has the same plan name and holds nothing
        self.assertNotIn('data-resource="gpu"', b)
        for card in (a, b):                                                          # the record without a project id: said as unknown, never held
            self.assertIn('id="resunsure"', card)
            self.assertIn('chưa xác định có thuộc việc này không', card)
            self.assertNotIn('data-resource="db"', card)
        self.assertIn('chưa xác định dự án', js('resSectionHtml()', last=overview))          # the page's own section names it, as unknown
        m = js('leaseMatch(d,last.shared_resources)', last=overview, d=details['b'])
        self.assertEqual((len(m['mine']), [r['resource'] for r in m['unsure']]), (0, ['db']))
        m = js('leaseMatch(d,last.shared_resources)', last=overview, d=dict(details['a'], project_id=None))
        self.assertEqual(len(m['mine']), 0)                                            # a card without an identity never holds anything


# ---- 4. the list row and the task page -----------------------------------------------------------------------------------------------------

class TaskPage(Shared):
    def test_list_owner_first(self):
        page, rows = self.listed()
        order = js('workOrder(tasks(),"attention").map(function(t){return t.plan+"@"+t.project_id})', last=page)
        waiting = {t['plan'] + '@' + t['project_id'] for t in rows.values() if t['needs_user']}
        self.assertEqual(waiting, {p + '@' + self.a_id for p in ('P5', 'P6', 'P7', 'P8')})
        self.assertEqual(set(order[:len(waiting)]), waiting)                          # what waits for the owner comes first
        first = js('workItem(t)', last=page, t=rows[(self.a_id, order[0].split('@')[0])])
        self.assertIn('<span class="needb">Cần bạn</span>', first)
        # the filter "Cần bạn quyết định" on the server finds exactly those
        need, _ = self.listed({'stage': 'need'})
        self.assertEqual({t['plan'] + '@' + t['project_id'] for p in need['projects'] for t in p['tasks']}, waiting)

    def test_status_line_user_words(self):
        page, rows = self.listed()
        expect = {'P2': ('Chưa kết luận', 'Kiểm môi trường'), 'P4': ('Cần sửa', 'Sửa và kiểm lại mốc M1'), 'P6': ('Chưa bắt đầu', 'Trả lời câu hỏi'),
                  'P11': ('Chưa bắt đầu', 'Làm và kiểm mốc M1')}
        for name, (label, step) in expect.items():
            r = self.row(rows, name)
            line = text(js('statusLine(t)', t=r))
            self.assertIn(label, line, name); self.assertIn('→', line); self.assertIn(step, line, name)
            for word in INTERNAL_WORDS:
                self.assertNotIn(word, line, (name, word))
            item = js('workItem(t)', t=r)
            self.assertEqual(item.count('data-status-line="1"'), 1)
        self.assertIn('· Bạn', text(js('statusLine(t)', t=self.row(rows, 'P6'))))           # who, when the ledger names it
        self.assertIn('Cần bạn', text(js('statusLine(t)', t=self.row(rows, 'P6'))))
        self.assertIn('chưa rõ ai làm', text(js('statusLine(t)', t=self.row(rows, 'P4'))))     # the action is still read when no actor is known

    def test_project_shown_when_needed(self):
        page, rows = self.listed()
        self.assertEqual(len(page['list']['projects']), 2)
        self.assertIn('data-project-shown="1"', js('workItem(t)', last=page, t=self.row(rows, 'P1')))
        self.assertIn('du-an-b', js('workItem(t)', last=page, t=self.row(rows, 'P1', self.b)))
        one, rows1 = self.listed(project=self.a)                                       # one project in view: no project on the row
        self.assertEqual(len(one['list']['projects']), 1)
        self.assertNotIn('data-project-shown', js('workItem(t)', last=one, t=self.row(rows1, 'P1')))

    def test_task_page_output_validity_reason_next(self):
        tracking._compared.clear()
        d = self.detail('P4')
        tiles = js('taskTiles(d)', d=d); words = text(tiles)
        for title in ('Đầu ra', 'Còn tin được không', 'Bước tiếp theo', 'Bạn cần quyết gì'):
            self.assertIn(title, words)
        self.assertIn('Không đạt', words)
        self.assertIn('lệnh thoát mã 3', words)                                       # the reason, from the check's own receipt
        self.assertIn('data-next-action="1">Sửa và kiểm lại mốc M1<', tiles)          # the action stands out, before who does it
        self.assertLess(tiles.index('data-next-action'), tiles.index('Ai làm:'))
        self.assertIn('Ai làm: Chưa có thông tin người xử lý', words)
        self.assertIn('đã dùng 1/3 lượt sửa, còn 2', words)
        p1 = text(js('taskTiles(d)', d=self.detail('P1')))
        self.assertIn('Cần kiểm lại', p1)
        self.assertIn('từng đạt trên bản trước', p1)
        self.assertIn('Kiểm lại mốc M1', p1)
        self.assertIn('Đã so với bản hiện tại của dự án lúc', p1)

    def test_failed_check_precedes_its_open_finding_on_page_and_report(self):
        task = self.detail('P4')
        self.assertFalse(task['acceptance']['ready'])
        page = text(js('taskTiles(d)', d=task))
        conclusion = report.render_report(self.state_root, 'P4', project_id=self.a_id).split('\n\n', 1)[0]
        for surface in (page, conclusion):
            words = ' '.join(surface.split())
            with self.subTest(surface=words):
                positions = [words.index(part) for part in ('lệnh thoát mã 3', 'Sửa và kiểm lại mốc M1', 'còn 2',
                                                             'Cần xử lý finding còn mở trước khi nghiệm thu: RF1')]
                self.assertEqual(positions, sorted(positions))

    def test_open_latest_output(self):
        d = self.detail('P3')                                                          # two checks: fail, then pass after the fix
        runs = d['work']['checks']['runs']
        self.assertEqual([r['status'] for r in runs], ['fail', 'pass'])
        o = js('outputOf(d)', d=d)
        self.assertEqual(o['receipt'], runs[-1]['receipt'])                            # the newest check, not the first one
        self.assertEqual(o['output']['artifact'], runs[-1]['artifact'])
        self.assertIsNone(o['key'])                                                    # a milestone output is a git tree in the project: no target in the store
        tile = js('tileOut(d)', d=d)
        self.assertIn('data-missing="output-target"', tile)
        self.assertIn('không có đích để mở', text(tile))
        self.assertIn('data-open-check="' + runs[-1]['receipt'] + '"', tile)
        self.assertIn('class="ev-open" data-key="' + runs[-1]['receipt'] + '"', tile)
        with Served(self.state_root) as s:
            q = '/api/evidence?plan=' + urllib.parse.quote(d['selector']) + '&project_id=' + d['project_id'] + '&key='
            status, body = s.json(q + runs[-1]['receipt'])
            self.assertEqual(status, 200)
            self.assertIn('command-receipt', body['text'])
            if o['log']:
                self.assertEqual(s.get(q + o['log'] + '&format=text')[0], 200)
        # an output the store holds (an engine node's snapshot) opens directly; the newest current one is chosen, an old one is not
        synthetic = {'evidence_keys': ['a' * 64, 'b' * 64, 'c' * 64], 'work': {'outputs': [
            {'node': 'N1', 'title': 'Bản cũ', 'artifact': 'a' * 64, 'level': 'verified', 'stale': True, 'source': {'seq': 5}},
            {'node': 'N1', 'title': 'Bản mới', 'artifact': 'b' * 64, 'level': 'verified', 'stale': False, 'source': {'seq': 9}},
            {'node': 'N0', 'title': 'Bản trước nữa', 'artifact': 'c' * 64, 'level': 'produced', 'stale': False, 'source': {'seq': 3}}], 'checks': {'runs': []}}}
        self.assertEqual(js('outputOf(d).key', d=synthetic), 'b' * 64)
        self.assertIn('data-open-output="' + 'b' * 64 + '"', js('tileOut(d)', d=synthetic))

    def test_open_evidence(self):
        d = self.detail('P3')
        section = js('deepEvidence(d)', d=d)
        keys = [k for k in d['evidence_keys']]
        self.assertTrue(keys)
        first = section[section.index('data-evidence="') + 15:][:64]
        last_seq = {}
        for o in d['evidence_index']:
            if o.get('seq') is not None: last_seq[o['key']] = max(last_seq.get(o['key'], -1), o['seq'])
        self.assertEqual(last_seq[first], max(last_seq.values()))                       # newest first
        self.assertIn('class="ev-open" data-key="' + first + '"', section)
        self.assertIn('data-deep="evidence"', js('tileOut(d)', d=d))                     # the output tile opens this section
        with Served(self.state_root) as s:
            q = '/api/evidence?plan=' + urllib.parse.quote(d['selector']) + '&project_id=' + d['project_id'] + '&key='
            self.assertEqual(s.json(q + first)[0], 200)
            other = self.detail('P4')
            foreign = next(k for k in other['evidence_keys'] if k not in d['evidence_keys'])
            self.assertEqual(s.json(q + foreign)[0], 403)                               # another task's evidence never opens here

    def test_plan_change_before_after(self):
        d = self.detail('P5')
        section = js('deepPlan(d,d.work)', d=d); words = text(section)
        self.assertIn('Bản 1 → bản 2', words)
        self.assertIn('Chủ yêu cầu thêm phần xuất báo cáo', words)
        self.assertIn('Trước', words); self.assertIn('Sau', words)
        self.assertIn('Năm: hợp đồng bản đầu', words); self.assertIn('Năm: phạm vi mới sau khi đổi', words)
        self.assertIn('Bản đầu của đầu ra', words); self.assertIn('Bản mới của đầu ra', words)
        self.assertLess(section.index('Năm: hợp đồng bản đầu'), section.index('Năm: phạm vi mới sau khi đổi'))
        self.assertIn('data-work-tab="changes"', section)
        deep = js('deepSections(d)', d=d)
        self.assertIn('data-k="deep-plan"', deep)
        self.assertNotIn('data-k="deep-plan" id="deep-plan" open', deep)               # closed until the owner opens it
        self.assertIn('Sổ chưa ghi lần đổi hợp đồng nào', text(js('deepPlan(d,d.work)', d=self.detail('P11'))))

    def test_finding_repair_recheck(self):
        d = self.detail('P3')
        loop = text(js('deepLoop(d,d.work)', d=d))
        self.assertIn('Lần kiểm 1: Không đạt', loop)
        self.assertIn('Sửa (lượt 1) rồi kiểm lại', loop)
        self.assertIn('Lần kiểm 2: Đạt', loop)
        self.assertLess(loop.index('Lần kiểm 1'), loop.index('Sửa (lượt 1)')); self.assertLess(loop.index('Sửa (lượt 1)'), loop.index('Lần kiểm 2'))
        p1 = text(js('deepLoop(d,d.work)', d=self.detail('P1')))                       # a pass the code has left: the loop says a recheck is due
        self.assertIn('Lần kiểm 1: Đạt', p1)
        self.assertIn('cần kiểm lại trên bản đang xem', p1)
        p4 = text(js('deepLoop(d,d.work)', d=self.detail('P4')))
        self.assertIn('Lần kiểm 1: Không đạt — ', p4); self.assertIn('lệnh thoát mã 3', p4)
        self.assertIn('đã dùng 1/3 lượt sửa, còn 2', p4)
        self.assertIn('data-deep="loop"', js('tileTrust(d)', d=d))

    def test_wait_opens_timeline(self):
        d = self.detail('P9')
        self.assertEqual([w['open'] for w in d['waits']], [False, True])
        waits = js('deepWaits(d)', d=d); words = text(waits)
        self.assertIn('Chờ: chờ máy kiểm thử rảnh', words)
        self.assertIn('Chờ: chờ chủ gửi dữ liệu mẫu', words)
        self.assertIn('đang chờ', words)
        self.assertLess(words.index('chờ máy kiểm thử rảnh'), words.index('chờ chủ gửi dữ liệu mẫu'))
        self.assertIn('data-work-tab="progress"', waits)
        self.assertIn('data-deep="waits"', js('tileNext(d)', d=d))
        self.assertIn('Thời gian chờ và dòng thời gian (2)', text(js('deepSections(d)', d=d)))
        self.assertIn('Sổ không ghi khoảng chờ nào', text(js('deepWaits(d)', d=self.detail('P11'))))


class MissingData(unittest.TestCase):
    """A plan with nothing recorded yet, and a project whose folder cannot be read: each gap is said where it is."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ui33-mc-gap-'); self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'ONECREW_LEASE_HOME': str(Path(self.temp.name) / 'leases')}); env.start(); self.addCleanup(env.stop)
        for name in ('ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(name, None)
        self.p = Project(Path(self.temp.name), 'du-an', Path(self.temp.name) / 'state')

    def test_missing_data_said(self):
        p = self.p
        p.plan('E', [milestone('M1')], title='Chưa có gì')
        d = tracking.detail(p.ledger.state_root, 'E')
        tiles = js('taskTiles(d)', d=d); words = text(tiles)
        self.assertIn('data-missing="output"', tiles)
        self.assertIn('Sổ chưa ghi đầu ra nào', words)
        self.assertEqual(js('trustOf(d).kind', d=d), 'none')
        self.assertIn('Chưa có kết quả kiểm', words)
        self.assertIn('Không có quyết định nào đang chờ bạn', words)
        for word in INTERNAL_WORDS[:4]:
            self.assertNotIn(word, words)
        deep = text(js('deepSections(d)', d=d))
        self.assertIn('Sổ chưa ghi lần đổi hợp đồng nào', deep)
        self.assertIn('Sổ không ghi khoảng chờ nào', deep)
        self.assertIn('Chưa có lần kiểm nào', deep)
        self.assertIn('Sổ chưa nêu bằng chứng nào', text(js('deepEvidence(d)', d={'evidence_index': []})))
        # a pass whose project can no longer be read: not counted, and the page says the current version is unknown
        p.plan('F', [milestone('M1')], title='Đạt nhưng không đọc được dự án')
        verdict.run(p.ledger, 'F', 'M1')
        moved = p.root.with_name('du-an-moved'); shutil.move(str(p.root), str(moved))
        self.addCleanup(lambda: moved.exists() and not p.root.exists() and shutil.move(str(moved), str(p.root)))
        d = tracking.detail(p.ledger.state_root, 'F')
        words = text(js('taskTiles(d)', d=d))
        self.assertEqual(d['validity']['kind'], 'unknown')
        self.assertIn('Chưa xác định bản hiện tại', words)
        self.assertIn('lần đạt chưa được tính', words)
        # the receipt of the check is gone from the store: the output tile says why there is nothing to open
        d = tracking.detail(p.ledger.state_root, 'F')
        d['evidence_keys'] = []
        self.assertIn('biên nhận kiểm không còn trong kho', text(js('tileOut(d)', d=d)))
        # a next step the ledger cannot name is said, not left blank
        self.assertIn('Sổ không đủ để nói bước tiếp theo', text(js('tileNext(d)', d={'situation': {'stage': 'unknown', 'label': 'Chưa xác định', 'reason': 'x', 'activity': {}}})))


# ---- 4b. the real page in a real browser: owner first, open by keyboard, back three ways, 1280 and 375 px ----------------------------------

class Browser(Shared):
    SCENARIO = r'''
await until(()=>$$('li.task').length>=12,40000,'rows');
const out={firstNeeds:!!($('li.task')&&$('li.task').querySelector('.needb'))};
const kind=$('#kind');kind.value='todo';kind.dispatchEvent(new Event('change',{bubbles:true}));
await until(()=>{const r=$$('li.task');return r.length>=5&&r.every(x=>x.dataset.stage==='todo')},40000,'filtered');
await sleep(1500);
out.rows=$$('li.task').map(x=>x.dataset.plan);out.listOverflow=overflow();
window.scrollTo(0,document.documentElement.scrollHeight);await sleep(300);
const y=window.scrollY;out.y=y;
const rows=$$('li.task'),target=rows[rows.length-1],plan=target.dataset.plan,project=target.dataset.project;out.target=plan;
out.backs=[];
for(const how of ['escape','history','button']){
  window.scrollTo(0,y);await sleep(150);const before=window.scrollY;
  const row=$$('li.task').find(x=>x.dataset.plan===plan&&x.dataset.project===project);
  row.focus({preventScroll:true});key(row,'Enter');
  await until(()=>$('#detail .tiles4')&&$('#detail #t-next'),40000,'detail '+how);
  await sleep(300);
  const inDetail={focus:document.activeElement&&document.activeElement.id,search:location.search,overflow:overflow(),view:$('#main').getAttribute('data-view')};
  if(how==='escape')key(document.activeElement||document.body,'Escape');else if(how==='history')history.back();else $('#back').click();
  await until(()=>$('#main').getAttribute('data-view')==='list',20000,'back '+how);
  await sleep(400);
  const a=document.activeElement;
  out.backs.push({how,before,inDetail,kind:kind.value,y:window.scrollY,focusPlan:a&&a.dataset?a.dataset.plan:null,focusProject:a&&a.dataset?a.dataset.project:null,
                  focusIsRow:!!(a&&a.classList&&a.classList.contains('task')),search:location.search,overflow:overflow()});
}
return out;'''
    TASK = r'''
await until(()=>$('#detail .tiles4')&&$('#detail #t-dec'),40000,'task');
await sleep(500);
const out={overflow:overflow(),openNeeds:$$('#detail details.need[open]').length,needText:$$('#detail details.need').map(x=>x.textContent).join(' | ')};
const w=$('#t-next [data-deep="waits"]');w.click();await sleep(200);
out.waitsOpen=$('#deep-waits').open;out.waitsFocus=document.activeElement===$('#deep-waits summary');out.waitsText=$('#deep-waits').textContent;
return out;'''
    EVIDENCE = r'''
await until(()=>$('#detail #t-out .open-check .ev-open'),40000,'output tile');
$('#detail #t-out .open-check .ev-open').click();
await until(()=>$('#detail #t-out pre'),20000,'evidence text');
const out={text:$('#detail #t-out pre').textContent.includes('"kind": "command-receipt"')?'command-receipt':$('#detail #t-out pre').textContent.slice(0,300)};
$('#detail #t-out [data-deep="evidence"]').click();await sleep(200);
out.evidenceOpen=$('#deep-evidence').open;out.items=$$('#deep-evidence [data-evidence]').length;out.overflow=overflow();
return out;'''

    def scenario(self, width, height):
        page, rows = self.listed()
        p6 = self.row(rows, 'P6'); p3 = self.row(rows, 'P3')
        with Served(self.state_root) as s:
            url = s.url
            task = lambda t: url + '?plan=' + urllib.parse.quote(t['selector']) + '&project_id=' + t['project_id']
            return drive(self.temp.name, [{'nav': url}, {'eval': self.SCENARIO}, {'nav': task(p6)}, {'eval': self.TASK}, {'nav': task(p3)}, {'eval': self.EVIDENCE}],
                         width, height)

    def check(self, results, width):
        listing, task, evidence = results
        self.assertTrue(listing['firstNeeds'], 'the first row (sort: needs you first) waits for the owner')
        self.assertGreaterEqual(len(listing['rows']), 5)
        self.assertGreater(listing['y'], 0, 'the filtered list must scroll for this check')
        self.assertLessEqual(listing['listOverflow'], 1)
        self.assertEqual([b['how'] for b in listing['backs']], ['escape', 'history', 'button'])
        for b in listing['backs']:
            self.assertEqual(b['inDetail']['view'], 'detail', b)
            self.assertEqual(b['inDetail']['focus'], 'dtitle', b)                       # Enter opens the task with the focus on its heading
            self.assertIn('plan=', b['inDetail']['search'])
            self.assertLessEqual(b['inDetail']['overflow'], 1, b)
            self.assertEqual(b['kind'], 'todo', b)                                      # the filter is kept
            self.assertLessEqual(abs(b['y'] - b['before']), 2, b)                       # the scroll position is kept
            self.assertTrue(b['focusIsRow'], b)                                         # the focus is back on the row that was opened
            self.assertEqual(b['focusPlan'], listing['target'], b)
            self.assertNotIn('plan=', b['search'])
            self.assertLessEqual(b['overflow'], 1, b)
        self.assertEqual(task['openNeeds'], 2)                                           # two independent requests, both shown in full
        self.assertIn(self.qa['question'], task['needText']); self.assertIn(self.qb['question'], task['needText'])
        self.assertTrue(task['waitsOpen']); self.assertTrue(task['waitsFocus'])
        self.assertLessEqual(task['overflow'], 1)
        self.assertIn('command-receipt', evidence['text'])
        self.assertTrue(evidence['evidenceOpen']); self.assertGreater(evidence['items'], 0)
        self.assertLessEqual(evidence['overflow'], 1)

    def test_back_keeps_filter_and_position_desktop(self):
        self.check(self.scenario(1280, 600), 1280)

    def test_back_keeps_filter_and_position_phone_375(self):
        self.check(self.scenario(375, 640), 375)


if __name__ == '__main__':
    unittest.main()
