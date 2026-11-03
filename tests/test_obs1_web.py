"""OBS-1 web page / server (onecrew/v2/tracking_web.py) over the real engine fixture ledger.

Pinned here: GET only (anything else is 405); the evidence door refuses a key the root does not name (403) and a malformed one (404);
a new ledger event shows in the overview within the stated ceiling (LATENCY_CEILING seconds, poll + read); a restarted server shows the
same timeline with no duplicate seq; shutting the server down in the middle of a worker's attempt leaves the worker alone (the node is still
produced); a broken or missing ledger is shown as a source problem, not a blank page; and, in a real headless browser when one is on the
machine (Chrome, then Edge; skipped otherwise), the page renders the plan, its status word and the connection badge, and shows the
"MẤT KẾT NỐI" state when the API stops answering.
"""
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from onecrew.v2 import engine, tracking, tracking_web
from tests.test_obs1_tracking import _Blocking
from tests.test_wf_engine import EngineFixture, node
from tests.test_v2_l1 import Fixture

LATENCY_CEILING = 5.0          # seconds from the ledger write to its appearance in /api/overview (poll 1 s in these tests + one read)
BROWSERS = (r'C:\Program Files\Google\Chrome\Application\chrome.exe', r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
            r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', r'C:\Program Files\Microsoft\Edge\Application\msedge.exe')


def find_browser(profile_dir):
    """A headless browser that really executes a page's script here (some Edge builds dump nothing while Edge is open), or None."""
    for exe in [e for e in BROWSERS if Path(e).is_file()] + [shutil.which('chrome'), shutil.which('msedge')]:
        if not exe: continue
        try:
            dom = dump_dom(exe, 'data:text/html,<b id=x>static</b><script>document.getElementById("x").textContent="jsran"</script>', profile_dir, budget=500)
        except (OSError, subprocess.SubprocessError):
            continue
        if 'jsran' in dom: return exe
    return None


def dump_dom(exe, url, profile_dir, budget=4000):
    done = subprocess.run([exe, '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', f'--user-data-dir={profile_dir}',
                          '--window-size=1400,1000', f'--virtual-time-budget={budget}', '--dump-dom', url],
                         capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=90)
    return done.stdout


def badge(dom):
    """The connection badge as rendered (the page's script source also contains every badge text, so the DOM is parsed, not searched)."""
    import re
    found = re.search(r'id="conn" class="([a-z]*)">([^<]*)<', dom)
    return (found.group(1), found.group(2)) if found else (None, None)


def screenshot(exe, url, profile_dir, path, budget=4000):
    subprocess.run([exe, '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', f'--user-data-dir={profile_dir}',
                    '--window-size=1400,1000', f'--virtual-time-budget={budget}', f'--screenshot={path}', url], capture_output=True, timeout=90)
    return Path(path).is_file()


class WebFixture(EngineFixture):
    def setUp(self):
        super().setUp()
        self.server = tracking_web.make_server(self.ledger.state_root, interval=1.0)
        self.url = tracking_web.url_of(self.server)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.2}, daemon=True); self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        try: self.server.shutdown(); self.server.server_close()
        except OSError: pass

    def get(self, path, method='GET', data=None):
        request = urllib.request.Request(self.url + path.lstrip('/'), method=method, data=data)
        try:
            with urllib.request.urlopen(request, timeout=20) as r:
                return r.status, r.read().decode('utf-8'), r.headers.get('Content-Type')
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode('utf-8'), error.headers.get('Content-Type')

    def task(self):
        return json.loads(self.get('/api/overview')[1])['projects'][0]['tasks'][0]


class EndpointTests(WebFixture):
    def test_get_only_and_the_evidence_door(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        worker = _Blocking(self); worker.release.set(); self.step(worker)
        status, body, ctype = self.get('/')
        self.assertEqual(status, 200); self.assertIn('text/html', ctype); self.assertIn('theo dõi (chỉ đọc)', body); self.assertNotIn('http://', body.split('<script>')[0].replace('http://127', ''))
        status, body, _ = self.get('/api/health'); self.assertEqual(status, 200); self.assertTrue(json.loads(body)['ok']); self.assertTrue(json.loads(body)['read_only'])
        status, body, _ = self.get('/api/overview'); value = json.loads(body)
        self.assertEqual(status, 200); self.assertEqual(value['source']['status'], 'ok'); self.assertIn('read_ms', value['server']); self.assertEqual(value['controls'][:8], 'không có')
        status, body, _ = self.get('/api/task?plan=P1'); d = json.loads(body)
        self.assertEqual(status, 200); self.assertEqual(d['nodes']['A']['state'], 'produced')
        key = d['nodes']['A']['receipt']
        status, body, ctype = self.get(f'/api/evidence?plan=P1&key={key}&format=text')
        self.assertEqual(status, 200); self.assertIn('text/plain', ctype); self.assertIn('fixture-receipt', body); self.assertNotIn('sk-fixture-secret', body)
        self.assertEqual(self.get('/api/evidence?plan=P1&key=' + 'c' * 64)[0], 403)
        self.assertEqual(self.get('/api/evidence?plan=P1&key=zz')[0], 404)
        self.assertEqual(self.get('/api/evidence?plan=P1')[0], 400)
        self.assertEqual(self.get('/api/task?plan=NOPE')[0], 404)
        self.assertEqual(self.get('/api/task')[0], 400)
        self.assertEqual(self.get('/nothing')[0], 404)
        for method in ('POST', 'PUT', 'DELETE', 'PATCH'):
            status, body, _ = self.get('/api/overview', method=method, data=b'{}')
            self.assertEqual(status, 405, method); self.assertIn('read-only', body)
        self.assertEqual(self.task()['status']['kind'], 'waiting')                         # nothing above changed the task

    def test_a_refused_method_with_a_body_always_reads_a_clean_405(self):
        """Integration regression 04/11: a 405 sent before the request body was read made Windows reset the connection (WinError 10053
        on the client). Each refused request with a large body must still read a complete 405 answer."""
        body = b'x' * (768 * 1024)
        for i, method in enumerate(('POST', 'PUT', 'DELETE', 'PATCH') * 2):
            status, text, _ = self.get('/api/overview', method=method, data=body)
            self.assertEqual(status, 405, (i, method)); self.assertIn('read-only', text)

    def test_a_new_ledger_event_shows_within_the_latency_ceiling(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        before = json.loads(self.get('/api/overview')[1])['source']['last_seq']
        from tests.test_obs1_tracking import QUESTION
        written = time.perf_counter()
        request = self.ledger.create_request(self.root_view['anchor_task'], 'retention', QUESTION)
        seen = None
        while time.perf_counter() - written < LATENCY_CEILING + 5:
            value = json.loads(self.get('/api/overview')[1])
            if value['source']['last_seq'] > before and any(n.get('id') == request['id'] for n in value['projects'][0]['tasks'][0]['needs_user']):
                seen = time.perf_counter() - written; break
            time.sleep(0.2)
        self.assertIsNotNone(seen, 'the request never showed')
        self.assertLessEqual(seen, LATENCY_CEILING)
        self.assertLess(value['server']['read_ms'], 3000)

    def test_restart_shows_the_same_timeline_without_duplicates(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        worker = _Blocking(self); worker.release.set(); self.step(worker)
        first = json.loads(self.get('/api/task?plan=P1')[1])
        port = self.server.server_address[1]
        self.stop()
        with self.assertRaises((urllib.error.URLError, ConnectionError, OSError)): urllib.request.urlopen(self.url + 'api/health', timeout=2)
        engine.verify(self.ledger, 'P1', 'A', self.checker)                                   # work went on while the viewer was closed
        self.server = tracking_web.make_server(self.ledger.state_root, port=port, interval=1.0)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.2}, daemon=True); self.thread.start()
        second = json.loads(self.get('/api/task?plan=P1')[1])
        old = {e['seq'] for e in first['timeline']}; new = {e['seq'] for e in second['timeline']}
        self.assertTrue(old < new)                                                            # everything seen before is still there, plus the new events
        self.assertEqual(len(second['timeline']), len(new))                                   # no duplicate seq
        self.assertEqual(second['nodes']['A']['state'], 'verified')
        self.assertEqual(second['level']['kind'], 'produced' if second['nodes']['I']['state'] == 'none' else 'verified')

    def test_closing_the_server_leaves_a_running_worker_alone(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        worker = _Blocking(self)
        thread = threading.Thread(target=self.step, args=(worker,), daemon=True); thread.start()
        self.assertTrue(worker.started.wait(10))
        self.assertEqual(self.task()['status']['kind'], 'running')
        self.stop()                                                                           # the viewer goes away mid-attempt
        worker.release.set(); thread.join(20)
        d = tracking.detail(self.ledger.state_root, 'P1')
        self.assertEqual(d['nodes']['A']['state'], 'produced')
        self.assertEqual([a['status'] for a in d['attempts']], ['settled'])


class SourceProblemTests(Fixture):
    def test_missing_and_garbage_ledgers_are_shown_as_source_problems(self):
        for name, content in (('missing', None), ('garbage', b'x' * 4096)):
            root = Path(self.temp.name) / name; root.mkdir()
            if content: (root / 'ledger.sqlite3').write_bytes(content)
            server = tracking_web.make_server(root, interval=1.0)
            threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.2}, daemon=True).start()
            try:
                with urllib.request.urlopen(tracking_web.url_of(server) + 'api/overview', timeout=10) as r:
                    value = json.loads(r.read().decode('utf-8'))
                self.assertEqual(value['source']['status'], 'missing' if name == 'missing' else 'unreadable')
                self.assertTrue(value['source']['detail'])
            finally:
                server.shutdown(); server.server_close()


class BrowserTests(WebFixture):
    """The page in a real headless browser. Skipped (not passed) when no browser on this machine executes a page's script headlessly."""
    def setUp(self):
        super().setUp()
        self.profile = Path(self.temp.name) / 'browser profile'
        self.browser = find_browser(self.profile)
        if not self.browser: self.skipTest('no headless Chrome/Edge executes script on this machine')

    def test_the_page_renders_the_task_its_status_and_the_connection_state(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        self.ledger.create_request(self.root_view['anchor_task'], 'retention', __import__('tests.test_obs1_tracking', fromlist=['QUESTION']).QUESTION)
        dom = dump_dom(self.browser, self.url, self.profile)
        cls, text = badge(dom)
        self.assertEqual(cls, 'ok', text); self.assertIn('kết nối OK', text); self.assertIn('seq', text)
        body = dom.split('</script>')[-1] if '</script>' in dom else dom
        self.assertIn('P1', dom); self.assertIn('class="st waiting"', dom); self.assertIn('đang chờ</span>', dom); self.assertIn('class="needb">cần bạn', dom)
        self.assertNotIn('hunter2', dom)
        detail = dump_dom(self.browser, self.url + '?plan=P1', self.profile)              # the reply commands live in the task detail (UX-03), one per option
        self.assertIn('question answer', detail); self.assertIn('--choice seven', detail); self.assertIn('--choice thirty', detail); self.assertNotIn('hunter2', detail)
        self.assertIn('Sao chép mẫu lệnh', detail); self.assertIn('--reference', detail)
        self.assertIn('chưa được theo dõi', dom)
        evidence = Path(os.environ.get('OBS1_EVIDENCE_DIR') or self.temp.name)
        if screenshot(self.browser, self.url, self.profile, evidence / 'obs1-page.png'): pass

    def test_the_page_says_disconnected_when_the_api_stops_answering(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        self.server.track_stats['refuse_api'] = True            # test-only: the API connection is dropped without a response; the page itself still loads
        dom = dump_dom(self.browser, self.url, self.profile)
        cls, text = badge(dom)
        self.assertEqual(cls, 'bad', text); self.assertIn('MẤT KẾT NỐI', text); self.assertIn('worker không bị ảnh hưởng', text)
