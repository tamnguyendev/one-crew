"""MP via the tracking HTTP server with a temporary ledger and Claude profile."""
import json
import os
import re
import tempfile
import unittest
from html import unescape
from pathlib import Path
from unittest.mock import patch

from onecrew.v2 import session_transcript, tracking, tracking_dashboard
from tests.test_ui33_task_first import Project, Served, drive, milestone


class SessionPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        cls.base = Path(temp.name)
        profile = cls.base / 'profile'
        env = patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(profile)})
        env.start()
        cls.addClassCleanup(env.stop)
        state = cls.base / 'state'
        cls.project = Project(cls.base, 'project', state)
        other = Project(cls.base, 'other', state)
        for project in (cls.project, other):
            project.plan('PLAN', [milestone()], approve=False)
        sid = 'session-A'
        stamp = '2026-11-19T10:00:00+00:00'
        for i, (kind, fields) in enumerate([
            ('session_start', {}), ('tool_call', {'tool': 'Read', 'tool_use_id': 'read', 'hook': 'PreToolUse'}),
            ('owner_prompt', {'text': 'Owner <script> token=ownersecret'}),
            ('subagent_start', {'agent_id': 'child'}), ('background_shell', {'tool': 'Bash', 'label': 'Run checks'}),
        ]):
            cls.project.emit('PLAN', 'hook.observed', dict(fields, observation=kind, session=sid,
                             recorded_at=stamp.replace(':00:00', f':0{i}:00')))
        other.emit('PLAN', 'hook.observed', {'observation': 'session_start', 'session': 'other-private-session'})
        cls.project.emit('PLAN', 'hook.logged', {'session': 'legacy', 'reason': 'Log original hook event'})
        cls.dir = profile / 'projects' / 'external-working-directory'
        cls.dir.mkdir(parents=True)
        cls.path = cls.dir / (sid + '.jsonl')
        childdir = cls.dir / sid / 'subagents'
        childdir.mkdir(parents=True)
        def msg(kind, content, **details):
            return {'type': kind, 'timestamp': stamp, 'message': dict(content=content, **details)}
        def call(name, tid, **args):
            return {'type': 'tool_use', 'name': name, 'id': tid, 'input': args}
        entries = [
            msg('assistant', [
                {'type': 'text', 'text': 'private assistant narrative'},
                {'type': 'thinking', 'thinking': 'private reasoning'},
                {'type': 'thinking_summary', 'text': 'Short summary password=summarysecret'},
                call('Read', 'read', file_path='notes/<b> password=pathsecret'),
                call('mcp__ccd_turn__update_plan', 'p', items=[{'content': 'Verify docs', 'status': 'in_progress'}])],
                id='msg', model='fixture-model', usage={'input_tokens': 90, 'output_tokens': 10}),
            msg('assistant', [], id='msg', usage={'input_tokens': 90, 'output_tokens': 12}),
            msg('user', [{'type': 'tool_result', 'tool_use_id': 'p', 'content': 'private tool output'}]),
            msg('assistant', [call('mcp__ccd_turn__update_plan', 'bad', items=[])]),
            msg('user', [{'type': 'tool_result', 'tool_use_id': 'bad', 'is_error': True}]),
            {'type': 'cost-state', 'totalCostUSD': 0.0123, 'startTime': 1735689600000}
        ]
        cls.path.write_text(''.join(json.dumps(r) + '\n' for r in entries), encoding='utf-8')
        child = msg('assistant', [], id='msg', model='child-model', usage={'cache_read_input_tokens': 30})
        (childdir / 'agent-child.jsonl').write_text(json.dumps(child), encoding='utf-8')
        cls.server = Served(state)
        cls.server.__enter__()
        cls.addClassCleanup(cls.server.__exit__, None, None, None)
        cls.index = '/sessions?plan=PLAN&project_id=' + cls.project.ledger.project_id
        cls.other = '/sessions?plan=PLAN&project_id=' + other.ledger.project_id
        status, html = cls.server.get(cls.index)
        assert status == 200, html
        cls.detail = unescape(re.search(r'<a href="([^"]+)">session-A</a>', html.decode())[1])
        cls.legacy = unescape(re.search(r'<a href="([^"]+)">legacy</a>', html.decode())[1])

    def html(self, path=None):
        status, result = self.server.get(path or self.detail)
        self.assertEqual(status, 200, result[:300])
        return result.decode()

    def test_session_list_by_task(self):
        with patch.object(session_transcript, 'read', side_effect=AssertionError('opened before selection')):
            index = self.html(self.index)
            self.assertIn('session-A', index)
            self.assertNotIn('other-private-session', index)
            self.assertIn('other-private-session', self.html(self.other))
            self.assertEqual(self.server.get(self.detail.replace(self.index, self.other))[0], 404)
            self.assertEqual(self.server.get('/sessions?plan=PLAN')[0], 404)
            self.assertIn('/sessions?plan=', self.html('/overview?project_id=' + self.project.ledger.project_id))

    def test_timeline_lanes_main_subagents_background(self):
        html = self.html()
        for lane in ('Phiên chính', 'Agent con · child', 'Lệnh nền'):
            self.assertIn(f'<h3>{lane}</h3>', html)
        self.assertLess(html.index('Mở phiên'), html.index('Gọi công cụ'))
        self.assertIn('Run checks', html)

    def test_overview_task_without_identity_has_no_session_link(self):
        state = self.base / 'state'
        model = tracking._overview(state, project_id=self.project.ledger.project_id, rhythm=True)
        del model['projects'][0]['tasks'][0]['id']
        with patch.object(tracking, '_overview', return_value=model):
            html = tracking_dashboard.page(state).decode()
        self.assertIn('Chưa có dữ liệu phiên', html)
        self.assertNotIn('href="/sessions?', html)

    def test_step_detail_filtered(self):
        html = self.html()
        self.assertIn('notes/&lt;b&gt;', html)
        self.assertIn('<summary>', html)
        self.assertNotIn('pathsecret', html)
        self.assertNotIn('private tool output', html)

    def test_reasoning_summary_only_when_present(self):
        html = self.html()
        self.assertIn('Short summary', html)
        self.assertNotIn('private reasoning', html)
        self.assertNotIn('private assistant narrative', html)
        self.assertIn('Bị che', self.html(self.legacy))

    def test_task_list_marked_self_report(self):
        html = self.html()
        self.assertIn('Danh sách bước · Claude tự báo', html)
        self.assertIn('Verify docs · Đang làm', html)
        self.assertIn('Lần cập nhật', html)
        # Every open reads the current file; an unsuccessful replacement keeps the previous list.
        with self.path.open('ab') as stream:
            original = stream.tell()
            stream.write(b'\n{"type":"assistant","message":{"content":[{"type":"tool_use","name":"mcp__ccd_turn__update_plan","id":"next","input":{"done":[1]}}]}}\n')
            stream.write(b'{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"next"}]}}\n')
        try:
            self.assertIn('Verify docs · Đã làm', self.html())
        finally:
            with self.path.open('r+b') as stream:
                stream.truncate(original)

    def test_tokens_model_cost_estimate_labelled(self):
        html = self.html()
        for value in ('Ước tính theo nhật ký', 'fixture-model', 'child-model', '132', 'Chi phí ước tính theo giá niêm yết',
                      '0.0123 USD', '2025-01-01'):
            self.assertIn(value, html)
        self.assertNotIn('0.0000 USD', self.html(self.legacy))

    def test_transcript_missing_said(self):
        self.assertIn('Không đọc được nhật ký', self.html(self.legacy))
        self.assertIn('Log original hook event', self.html(self.legacy))
        path = self.dir / 'legacy.jsonl'
        path.write_text('{"changed":"format"}\ninvalid\n', encoding='utf-8')
        try:
            self.assertIn('Không đọc được định dạng', self.html(self.legacy))
        finally:
            path.unlink()

    def test_duplicate_transcript_is_ambiguous(self):
        duplicate = self.dir.parent / 'second-project'
        duplicate.mkdir()
        copy = duplicate / self.path.name
        copy.write_text('{"type":"user","message":{}}', encoding='utf-8')
        try:
            html = self.html()
            self.assertIn('nhiều nhật ký trùng mã', html)
            self.assertNotIn('fixture-model', html)
            self.assertIn('Run checks', html)
        finally:
            copy.unlink()
            duplicate.rmdir()

    def test_secret_filter(self):
        with self.project.ledger.transaction() as conn:
            before = [tuple(r) for r in conn.execute('SELECT seq,payload FROM events')]
        html = self.html()
        for value in ('ownersecret', 'pathsecret', 'summarysecret', '<script>'):
            self.assertNotIn(value, html)
        self.assertIn('&lt;script&gt;', html)
        with self.project.ledger.transaction() as conn:
            self.assertEqual(before, [tuple(r) for r in conn.execute('SELECT seq,payload FROM events')])
        self.assertNotIn('Short summary', str(before))
        self.assertEqual(self.server.get(self.index + '&session=../other')[0], 404)

    def test_mobile_layout(self):
        url = self.server.url.rstrip('/') + self.detail
        steps = [{'nav': url}, {'eval': """return [innerWidth, document.documentElement.scrollWidth-document.documentElement.clientWidth,
                 $$('article').every(e=>e.scrollWidth<=e.clientWidth+1),
                 $('a[href*="project_id"]').getAttribute('href'), $$('details').length];"""}]
        width, excess, fits, back, details = drive(self.base, steps, 375, 800)[0]
        self.assertEqual((width, excess, fits), (375, 0, True))
        self.assertIn(self.project.ledger.project_id, back)
        self.assertGreater(details, 0)
