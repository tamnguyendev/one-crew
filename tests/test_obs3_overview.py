"""MT on a temporary shared ledger, including the list links of the served dashboard."""
import datetime as dt
import os
import re
import sqlite3
import tempfile
import unittest
from html import unescape
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from onecrew.v2 import diagnostics, tracking, tracking_dashboard as dash, tracking_list
from tests.test_ui33_task_first import Project, Served, drive, js, milestone


class Overview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        cls.base = Path(temp.name)
        cls.state = cls.base / 'ledger'
        env = patch.dict(os.environ, {'ONECREW_LEASE_HOME': str(cls.base / 'leases')})
        env.start()
        cls.addClassCleanup(env.stop)
        for key in ('ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'):
            os.environ.pop(key, None)
        cls.project = Project(cls.base, 'example', cls.state)
        cls.project.plan('ASK', [milestone()], approve=False, title='Owner decision')
        cls.project.plan('RUN', [milestone()], title='Checked work')
        cls.project.timed_out('RUN')
        cls.server = Served(cls.state)
        cls.server.__enter__()
        cls.addClassCleanup(cls.server.__exit__, None, None, None)
        status, body = cls.server.get('/overview')
        if status != 200:
            raise AssertionError(body)
        cls.html = body.decode('utf-8')

    def test_owner_items_first(self):
        owner_link = self.html.index('Owner decision')
        self.assertLess(self.html.index('Cần bạn quyết định'), owner_link)
        self.assertLess(owner_link, self.html.index('Theo repo'))
        self.assertNotIn('Checked work', self.html[:self.html.index('Theo repo')])

    def test_per_repo_worktrees(self):
        other = self.base / 'linked'
        self.project.git('worktree', 'add', '-q', '--detach', str(other))
        trees = [dict(path=str(path), tasks=[{'project_id': name}]) for path, name in ((self.project.root, 'a'), (other, 'b'))]
        markup = dash.projects_html(trees)
        self.assertEqual(markup.count('<article>'), 1)
        self.assertIn('linked · 1 việc', markup)
        self.assertIn('example · 1 việc', markup)
        self.assertIn('project=repo%3Aa%2Cb', markup)
        self.assertIsNone(dash.repo_dir(self.base / 'removed'))

    def test_attention_counts_match_list(self):
        tiles = re.findall(r'href="/\?stage=(\w+)"><strong>(\d+)</strong>', self.html)
        self.assertEqual([stage for stage, _ in tiles], [stage for stage, _ in dash.ATTENTION])
        for stage, count in tiles:
            actual = tracking_list.page(self.state, {'stage': stage})['list']
            self.assertEqual(int(count), actual['matched'], stage)
        self.assertEqual(dict(tiles)['need'], '1')
        self.assertEqual(dict(tiles)['inconclusive'], '1')

    def test_tile_opens_filtered_list(self):
        href = unescape(re.search(r'href="(/\?project=(?!repo%3A)[^"]+&amp;stage=need)"', self.html)[1])
        filters = parse_qs(urlsplit(href).query)
        self.assertEqual(filters, {'project': [os.path.normcase(str(self.project.root))], 'stage': ['need']})
        steps = [{'nav': self.server.url.rstrip('/') + href},
                 {'eval': """await until(()=>window.__track.state().list.answer,30000,'filtered list');
                            return [$('#kind').value,$('#proj').value,$$('li.task').map(t=>t.dataset.plan)];"""}]
        stage, project, rows = drive(self.base, steps, 900, 700)[0]
        self.assertEqual((stage, project, len(rows)), ('need', filters['project'][0], 1))
        self.assertIn('ASK', rows[0])

    def test_checks_per_day_scale(self):
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE events(task_id, kind, created_at, payload)')
            now = dt.datetime.now().astimezone().replace(hour=12)
            def checks(task, kind, age, count, result):
                db.executemany('INSERT INTO events VALUES(?,?,?,?)',
                               [(task, kind, (now - dt.timedelta(days=age)).isoformat(), '{"result":"' + result + '"}')] * count)
            checks('A', 'verdict.recorded', 0, 4, 'pass')
            checks('B', 'node.verification', 1, 2, 'fail')
            checks('A', 'verdict.recorded', 14, 5, 'pass')
            checks('C', 'verdict.recorded', 0, 5, 'inconclusive')
            days = dash.check_days(db, {'repo': [{'id': 'A', 'tracking': {'adapter': 'milestones'}},
                                                 {'id': 'B', 'tracking': {'adapter': 'engine'}}]}, now)
        self.assertEqual(len(days), 14)
        self.assertEqual(sum(sum(counts.values()) for counts in days.values()), 6)
        chart = dash.rhythm_html(days)
        self.assertIn('Cao nhất 4', chart)
        self.assertIn('class="fail" style="height:50.000%"', chart)
        self.assertIn('class="pass" style="height:100.000%"', chart)

    def test_not_compared_said(self):
        task = {'project_id': 'a', 'validity': {'kind': 'not_compared'}, 'milestones': [{'id': 'M1', 'state': 'passed'}]}
        self.assertIn('chưa so với bản hiện tại', js('milestoneBar(t)', t=task))
        with patch.object(tracking, '_overview', return_value={
                'generated_at': '2026-11-20T12:00:00Z', 'source': {'status': 'ok'},
                'projects': [{'path': str(self.project.root), 'tasks': [task]}],
                'check_days': {'2026-11-20': dict.fromkeys(dash.SERIES, 0)}}):
            self.assertIn('1 việc chưa so với bản hiện tại', dash.page(self.state).decode())

    def test_background_and_leases(self):
        host = {'projects': [{'view': {'items': [{'state_label': 'đang chạy'}]}}]}
        leases = {'declared': True, 'resources': [{'resource': '<device>', 'state_label': 'đang giữ', 'waiters': [{}]}]}
        panel = dash.background_html(host, leases)
        for label in ('Host tự báo', '1 đang chạy', '&lt;device&gt;', 'đang giữ (1 chờ)'):
            self.assertIn(label, panel)
        self.assertIn('Chưa đọc được', dash.background_html(host, {'error': 'unavailable'}))

    def test_placeholder_no_numbers(self):
        panel = self.html.split('<h2>Phiên Claude</h2>', 1)[1].split('</article>', 1)[0]
        self.assertIn('Chưa có dữ liệu', panel)
        self.assertNotRegex(panel, r'\d')

    def test_mobile_layout(self):
        steps = [{'nav': self.server.url.rstrip('/') + '/overview'},
                 {'eval': """return [innerWidth,document.documentElement.scrollWidth-document.documentElement.clientWidth,$$('.attention a').length,
                            $$('.grid article').every(e=>e.scrollWidth<=e.clientWidth+1)];"""}]
        self.assertEqual(drive(self.base, steps, 375, 800), [[375, 0, len(dash.ATTENTION), True]])

    def test_mockup_look_list_and_task(self):
        t = {'milestones': [{'id': 'MT', 'state': 'pending'}], 'situation': {'stage': 'doing', 'label': 'Đang thực hiện'}}
        item = js('workItem(t)', t=t)
        self.assertIn('role="img" aria-label="Đang thực hiện"', item)
        self.assertIn('aria-label="MT · Chưa kiểm"', item)
        self.assertIn('class="tiles4"', js('taskTiles(t)', t=t))
        self.assertEqual(js('checkCls({result:"inconclusive"})'), 'inconclusive')

    def test_checks_section_named_with_reason(self):
        checks = [{'result': 'pass', 'artifact': 'a'}, {'result': 'inconclusive', 'artifact': 'b'}, {'result': 'fail'}, {'result': 'pass'}]
        detail = {'milestone_checks': {'rows': [{'id': 'M1', 'checks': checks}]}}
        section = js('deepSections(d)', d=detail)
        for label in ('Các lần kiểm', 'Kiểm lần đầu', 'Bản được kiểm đã đổi', 'Lần trước chưa kết luận', 'Lần trước không đạt'):
            self.assertIn(label, section)
        self.assertIn('Sổ chưa ghi lý do', js('loopSteps(r)', r={'checks': [{'result': 'pass'}, {'result': 'pass'}]})[-1]['t'])

    def test_no_false_redaction(self):
        gloss = 'pass = cần kiểm lại'
        self.assertEqual(diagnostics.redact_line(gloss), (gloss, False))
        line = f'Mốc ({gloss}), pass = hiddenvalue, DB_PASS=othersecret'
        redacted = tracking.outward(line)
        self.assertIn(gloss, redacted)
        self.assertEqual(redacted.count('[withheld]'), 2)
        self.assertNotRegex(redacted, 'hiddenvalue|othersecret')
        self.assertNotIn('cần', tracking.outward('pass = cần'))
