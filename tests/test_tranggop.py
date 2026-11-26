"""TRANGGOP: one tracking page over several ledgers.

Rule of these cases (contract TRANGGOP, checker kiem-tranggop-b3.py): a case of new behaviour fails BY ASSERTION on the base 7beae71: a missing
module, flag or answer is turned into self.fail, never an import error. Real temporary ledgers and Git (tests.v2_fixture); the page is served by
a real server on a free port in this process. No test opens a browser or writes a real ledger.
"""
import contextlib
import datetime as dt
import hashlib
import io
import json
import os
import re
import sqlite3
import threading
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from onecrew.ledger import Ledger
from onecrew.v2 import plan as plans, tracking_cli, tracking_web
from tests.v2_fixture import Fixture, plan_json

NOW = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class TestTrangGop(Fixture):
    def setUp(self):
        super().setUp()
        self.base = Path(self.temp.name)
        self.state = Path(self.ledger.state_root)
        self.other = Ledger(self.root, self.base / 'so-phat-trien')

    # ---- helpers -----------------------------------------------------------------------------------------------------------------------
    def gop(self):
        try:
            from onecrew.v2 import tracking_gop
        except ImportError:
            self.fail('there is no merged view over several ledgers (onecrew.v2.tracking_gop)')
        return tracking_gop

    def make(self, ledger, name, status='approved'):
        plans.propose(ledger, name, plan_json(), 'claude')
        if status in ('approved', 'closed'):
            plans.approve(ledger, name, 'owner', 'fixture approval')
        if status == 'closed':
            if not hasattr(plans, 'close'): self.fail('no owner close')
            plans.close(ledger, name, 'owner', 'fixture close')

    def make_old(self, ledger, name):
        """A plan under an old "plan:" anchor, as an older OneCrew left it (the fixture's own temporary ledger)."""
        self.make(ledger, name, 'proposed')
        db = sqlite3.connect(str(Path(ledger.state_root) / 'ledger.sqlite3'))
        try:
            db.execute('UPDATE tasks SET request_key=? WHERE request_key=?', ('plan:' + name, 'plan-ns:' + name)); db.commit()
        finally:
            db.close()

    def config(self, **value):
        self.state.mkdir(parents=True, exist_ok=True)       # a fixture that proposed nothing has no state folder yet
        (self.state / 'tracking.json').write_text(json.dumps(value), encoding='utf-8')

    def folder(self, step='doc-tep-mau', plain='cau thuong khong phai buoc', name='phien-a'):
        """A transcript folder: one session with a title, a hand-over, a BUOC line (main and a sub-agent) and ordinary text."""
        folder = self.base / name
        (folder / 's1' / 'subagents').mkdir(parents=True)
        def said(text, *blocks):
            return {'type': 'assistant', 'sessionId': 's1', 'timestamp': NOW,
                    'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': text}, *blocks]}}
        rows = [{'type': 'custom-title', 'customTitle': 'Phiên thử ' + name},
                {'type': 'user', 'sessionId': 's1', 'timestamp': NOW, 'message': {'role': 'user', 'content': 'LOICHU-khong-duoc-hien'}},
                said('BƯỚC: ' + step + '\n' + plain, {'type': 'tool_use', 'id': 't1', 'name': 'Read', 'input': {'description': 'doc tep'}}),
                said(plain, {'type': 'tool_use', 'id': 't2', 'name': 'SendMessage',
                             'input': {'to': 'uds:ong', 'summary': 'P-MO: xin lượt ' + name, 'message': 'noi dung'}},
                     {'type': 'tool_use', 'id': 't3', 'name': 'Agent', 'input': {'prompt': 'xem tệp C:\\Users\\ten\\bi mat\\a.txt và D:\\kho\\b.py\n'
                                                                                 'khóa ghp_ABCDEFabcdef123456, thư ai@vi.du\ntoken=abc123xyz'}})]
        (folder / 's1.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
        (folder / 's1' / 'subagents' / 'agent-x1.jsonl').write_text(json.dumps(said('BƯỚC: buoc-cua-agent-con'), ensure_ascii=False) + '\n',
                                                                    encoding='utf-8')
        return folder

    def serve(self, **kw):
        server = tracking_web.make_server(self.state, **kw)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        return tracking_web.url_of(server)

    def get(self, url):
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=60) as answer:
                return answer.status, answer.read().decode('utf-8')
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode('utf-8')

    def files(self, root):
        return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(Path(root).rglob('*')) if p.is_file()}

    def block(self, page, name):
        found = re.search(r'data-khoi="' + name + r'"(.*?)(?=data-khoi="|<main |$)', page, re.S)
        if not found: self.fail('the page has no block data-khoi="%s"' % name)
        return found.group(1)

    def strip(self, page):
        return set(re.findall(r'data-viec="([^"]+)"', page))

    def page(self):
        status, text = self.get(self.serve())
        self.assertEqual(status, 200)
        return text

    # ---- I1, I2: more ledgers ------------------------------------------------------------------------------------------------------------
    def test_serve_accepts_more_ledgers_with_so(self):
        self.make(self.other, 'P-KHAC')
        argv = ['--project', str(self.root), '--state-root', str(self.state), 'track']
        for verb, extra, patched in (('serve', [], 'serve'), ('open', ['--no-browser'], 'open_page')):
            with mock.patch.object(tracking_web, patched, return_value=0 if verb == 'serve' else {'url': 'x'}) as target, \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                try:
                    code = tracking_cli.main([*argv, verb, *extra, '--so', str(self.other.state_root), '--so', str(self.base / 'so-ba')])
                except SystemExit:
                    self.fail('track %s does not take --so' % verb)
            self.assertEqual(code, 0)
            self.assertEqual(len(target.call_args.kwargs.get('so') or []), 2, verb)

    def test_tracking_json_lists_ledgers_and_proposals(self):
        gop = self.gop()
        self.make(self.other, 'P-KHAC')
        proposals = self.base / 'de-xuat.md'; proposals.write_text('- mot\n', encoding='utf-8')
        self.config(so=[str(self.other.state_root)], de_xuat_tu=str(proposals))
        view = gop.settings(self.state)
        self.assertTrue(view['active'])
        self.assertEqual(len(view['ledgers']), 2)
        self.assertEqual((view['ledgers'][0]['own'], view['ledgers'][1]['label']), (True, 'so-phat-trien'))
        self.assertEqual(view['proposals'], proposals.resolve())
        self.assertEqual(tracking_web.default_port(self.state), 0, 'a tracking.json without "port" keeps a free port')
        self.assertIn('data-khoi="de-xuat"', self.page())

    def test_overview_marks_each_task_with_its_ledger(self):
        self.gop()
        self.make(self.ledger, 'P-MOT'); self.make(self.other, 'P-HAI')
        url = self.serve(so=[str(self.other.state_root)])
        value = json.loads(self.get(url + 'api/overview?list=1&limit=50')[1])
        tasks = {t['plan']: t for p in value['projects'] for t in p['tasks']}
        self.assertEqual(set(tasks), {'P-MOT', 'P-HAI'})
        self.assertTrue(tasks['P-MOT']['so']['own']); self.assertFalse(tasks['P-HAI']['so']['own'])
        self.assertEqual(tasks['P-HAI']['so']['label'], 'so-phat-trien')
        so = tasks['P-HAI']['so']['id']
        status, head = self.get(url + 'api/task?part=head&plan=plan-ns%3AP-HAI&so=' + so)
        self.assertEqual(status, 200, head[:300])
        self.assertEqual(json.loads(head)['plan'], 'P-HAI')
        self.assertEqual(self.get(url + 'api/task?plan=plan-ns%3AP-HAI&so=0000000000')[0], 404, 'only a shown ledger')
        page = self.get(url)[1]
        self.assertIn('data-khoi="loc-so"', page)
        self.assertGreaterEqual(len(set(re.findall(r'data-so="([^"]+)"', page))), 2)

    def test_other_ledgers_opened_read_only(self):
        self.make(self.ledger, 'P-MOT'); self.make(self.other, 'P-HAI')
        before = self.files(self.other.state_root)
        try:
            url = self.serve(so=[str(self.other.state_root)])
        except TypeError:
            self.fail('the server takes no extra ledger')
        for path in ('', 'api/overview'):
            self.assertEqual(self.get(url + path)[0], 200)
        self.assertEqual(self.files(self.other.state_root), before, 'the extra ledger was written')

    # ---- I4: the "Việc" strip ------------------------------------------------------------------------------------------------------------
    def test_strip_is_exactly_open_plans_of_shown_ledgers(self):
        self.gop()
        self.make(self.ledger, 'P-MO'); self.make(self.ledger, 'P-DE-XUAT', 'proposed'); self.make(self.other, 'P-KHAC')
        self.approved('P-XONG')
        from onecrew.v2 import verdict
        verdict.run(self.ledger, 'P-XONG', 'M1')
        plans.accept(self.ledger, 'P-XONG', 'owner', 'fixture acceptance', self.tree())
        self.config(so=[str(self.other.state_root)])
        page = self.page()
        self.assertEqual(self.strip(page), {'P-MO', 'P-DE-XUAT', 'P-KHAC'})
        self.assertIn('P-KHAC', self.block(page, 'dai-viec'))
        for name in ('lan', 'the-luoi', 'luong'):
            self.block(page, name)

    def test_closed_plans_not_in_strip(self):
        self.gop()
        self.make(self.ledger, 'P-MO'); self.make(self.ledger, 'P-DONG', 'closed')
        self.config(de_xuat_tu='khong-co.md')
        self.assertEqual(self.strip(self.page()), {'P-MO'})

    def test_old_plans_out_of_strip_in_work_tab(self):
        self.gop()
        self.make(self.ledger, 'P-MOI'); self.make_old(self.ledger, 'P-CU')
        self.config(de_xuat_tu='khong-co.md')
        url = self.serve()
        page = self.get(url)[1]
        self.assertEqual(self.strip(page), {'P-MOI'})
        tasks = {t['selector'].split(':', 1)[1]: t for p in json.loads(self.get(url + 'api/overview?list=1')[1])['projects'] for t in p['tasks']}
        self.assertIn('P-CU', tasks, 'the old plan stays in the Công việc list')
        self.assertTrue(tasks['P-CU']['so']['old']); self.assertFalse(tasks['P-MOI']['so']['old'])
        self.assertIn('kiểu cũ', page)

    # ---- I5: proposals -------------------------------------------------------------------------------------------------------------------
    def test_proposals_read_from_file_never_written(self):
        self.gop()
        proposals = self.base / 'lo-trinh.md'
        proposals.write_text('# Lộ trình\n\nchữ thường\n- DEXUAT-MOT\n  * DEXUAT-HAI\n1. khong phai gach dau dong\n', encoding='utf-8')
        before = (proposals.read_bytes(), proposals.stat().st_mtime_ns)
        self.config(de_xuat_tu=str(proposals))
        block = self.block(self.page(), 'de-xuat')
        self.assertIn('DEXUAT-MOT', block); self.assertIn('DEXUAT-HAI', block); self.assertNotIn('khong phai gach', block)
        self.assertEqual((proposals.read_bytes(), proposals.stat().st_mtime_ns), before)

    # ---- I6: transcripts of listed folders only --------------------------------------------------------------------------------------------
    def test_session_stream_reads_only_listed_folders(self):
        self.gop()
        self.make(self.ledger, 'P-MO')
        listed = self.folder(name='phien-liet-ke'); self.folder(name='phien-khac-du-an', step='BUOC-DU-AN-KHAC')
        self.config(phien_claude_thu_muc=[str(listed)])
        page = self.page()
        flow = self.block(page, 'luong')
        self.assertIn('P-MO: xin lượt phien-liet-ke', flow)
        self.assertIn('việc (đoán): P-MO', flow)
        self.assertIn('Phiên thử phien-liet-ke', flow)
        self.assertNotIn('phien-khac-du-an', page); self.assertNotIn('BUOC-DU-AN-KHAC', page)
        self.assertNotIn('LOICHU-khong-duoc-hien', page)

    def test_stream_text_is_masked(self):
        listed = self.folder()
        self.config(phien_claude_thu_muc=[str(listed)])
        page = self.page()
        for secret in ('C:\\Users', 'bi mat', 'D:\\kho', 'ghp_ABCDEF', 'ai@vi.du', 'abc123xyz'):
            self.assertNotIn(secret, page, secret)

    # ---- I9: BƯỚC lines ------------------------------------------------------------------------------------------------------------------
    def test_step_lines_read_from_assistant_text(self):
        self.gop()
        self.config(phien_claude_thu_muc=[str(self.folder())])
        block = self.block(self.page(), 'buoc')
        self.assertIn('doc-tep-mau', block); self.assertIn('buoc-cua-agent-con', block)
        self.assertIn('Lệnh ngay sau: Read: doc tep', block)
        self.assertIn('chưa xác thực', block)
        self.assertNotIn('cau thuong khong phai buoc', block)

    def test_step_lines_unverified_and_never_counted(self):
        self.make(self.ledger, 'P-MO')
        self.config(phien_claude_thu_muc=[str(self.folder(step='XONG het moi moc'))])
        url = self.serve()
        page = self.get(url)[1]
        overview = self.get(url + 'api/overview')[1]
        self.assertNotIn('XONG het moi moc', overview, 'a step line is display only, never part of the task data')
        if 'XONG het moi moc' in page:
            self.assertIn('chưa xác thực', self.block(page, 'buoc'))
        self.assertEqual(plans.show(self.ledger, 'P-MO')['status'], 'approved')

    def test_no_step_lines_without_listed_folders(self):
        self.folder(step='BUOC-KHONG-LIET-KE')
        proposals = self.base / 'p.md'; proposals.write_text('- a\n', encoding='utf-8')
        self.config(de_xuat_tu=str(proposals), port=1)
        page = self.page()
        self.assertNotIn('BUOC-KHONG-LIET-KE', page)
        self.assertNotIn('Phiên thử', page)

    # ---- without --so and without the new keys -------------------------------------------------------------------------------------------
    def test_single_ledger_page_unchanged_without_so(self):
        self.make(self.ledger, 'P-MOT')
        url = self.serve()
        self.assertEqual(self.get(url)[1], tracking_web._page(2.0))
        value = json.loads(self.get(url + 'api/overview?list=1&limit=50')[1])
        self.assertIn('list', value)
        self.assertNotIn('so', value['projects'][0]['tasks'][0])
        self.assertNotIn('so', json.loads(self.get(url + 'api/health')[1]))
