"""MH through the read-only HTTP routes and real hook row format on temporary ledgers."""
import re
import tempfile
import tomllib
import unittest
from datetime import datetime, timezone
from html import unescape
from importlib.metadata import files
from pathlib import Path
from urllib.parse import urlencode

from onecrew.snapshots import Snapshots
from onecrew.v2 import plan, session_observe, tracking_direction
from tests.test_ui33_task_first import Project, Served, milestone


class Packaging(unittest.TestCase):
    def test_obs3_modules_in_source_manifest_and_installed_distribution(self):
        modules = {'session_observe', 'session_transcript', 'tracking_dashboard',
                   'tracking_direction', 'tracking_sessions'}
        manifest = Path(__file__).resolve().parents[1] / 'pyproject.toml'
        if manifest.exists():
            config = tomllib.loads(manifest.read_text(encoding='utf-8'))
            declared = config['tool']['setuptools']['py-modules']
            self.assertLessEqual({'onecrew.v2.' + name for name in modules}, set(declared))
        else:  # The wheel verifier copies the tests to a directory outside the checkout.
            installed = {path.as_posix() for path in files('onecrew')}
            self.assertLessEqual({f'onecrew/v2/{name}.py' for name in modules}, installed)


class Direction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        base = Path(temp.name)
        state = base / 'state'
        project = Project(base, 'first', state)
        other = Project(base, 'other', state)
        for repo in (project, other):
            repo.plan('PLAN', [milestone()], approve=False)
        other.emit('PLAN', 'hook.observed', {'observation': 'owner_prompt', 'text': 'only-in-other-project'})
        cls.words = 'Đúng  từng chữ <b>.\n' + 'Chữ ' * 160
        cls.blob = Snapshots(state).blob(b'public fixture output')
        cls.tree = 'b' * 40
        root = project.state('PLAN')['task_id']
        with project.ledger.transaction(write=True) as conn:
            def emit(kind, **p):
                plan.emit(project.ledger, conn, root, kind, p)

            def obs(kind, text, session='first-session', **p):
                emit('hook.observed', observation=kind, text=text, session=session, revision=2, **p)

            emit('plan.amended', revision=2, author='codex', reason='Gộp hai màn hình', title='Lịch sử')
            obs('owner_prompt', cls.words + '\npassword="sample-secret"')
            obs('ai_question', 'Còn câu nào?', options=['Giữ', 'Đổi'], question_id='unanswered')
            obs('ai_question', 'Chọn thứ tự nào?', options=['A', 'B'], question_id='answered')
            obs('owner_choice', 'Giữ', session='other-session', question_id='unanswered')
            obs('owner_choice', 'B', question_id='answered')
            obs('owner_prompt', 'Chuyển sang giao diện mới')
            obs('owner_prompt', 'Không chuyển sang trang khác.')
            obs('owner_prompt', 'Mở rộng phạm vi để làm gì?')
            emit('node.produced', node='N1', artifact=cls.blob)
            emit('verdict.recorded', milestone='M1', revision=2, artifact_sha='a' * 40, result='pass')
            emit('verdict.recorded', milestone='M1', revision=2, artifact_sha=cls.tree, result='pass')
            event = {'hook_event_name': 'PostToolUse', 'tool_name': 'Write', 'tool_use_id': 'ext', 'cwd': str(project.root),
                     'tool_input': {'file_path': '../draft/design.html', 'content': 'not-observed'}}
            target = {'project': str(project.root), 'plan': 'PLAN', 'task': root, 'anchor': 'plan-ns:PLAN', 'revision': 2}
            row, = session_observe._rows(event, 'first-session', target)
            assert 'not-observed' not in str(row)
            emit('hook.observed', **row)
            event['tool_input']['file_path'] = 'inside.html'
            assert next(session_observe._rows(event, 'first-session', target))['observation'] == 'tool_call'
            for i in range(tracking_direction.PAGE_SIZE + 3):
                obs('owner_prompt', f'Nhật ký riêng {i:03}')
        cls.server = Served(state)
        cls.server.__enter__()
        cls.addClassCleanup(cls.server.__exit__, None, None, None)
        cls.scope = {'plan': 'PLAN', 'project_id': project.ledger.project_id}

    def html(self, **query):
        status, raw = self.server.get('/direction?' + urlencode(dict(self.scope, **query)))
        self.assertEqual(status, 200, raw[:200])
        return raw.decode()

    def test_phases_default_view(self):
        page = self.html()
        self.assertIn('aria-current="page"', page.split('>Giai đoạn</a>')[0].rsplit('<a', 1)[1])
        self.assertIn('<h2>Bản 2</h2>', page)
        self.assertIn('<h2>Điểm rẽ #', page)
        self.assertNotIn('only-in-other-project', page)
        self.assertEqual(self.server.get('/direction?plan=PLAN')[0], 404)
        self.assertIn(self.scope['project_id'], unescape(re.search(r'href="(/sessions[^"]*)"', page)[1]))

    def test_turning_points_keep_open_questions(self):
        page = self.html(view='turns')
        self.assertIn('Còn câu nào?', page)
        self.assertNotIn('Nhật ký riêng', page)
        self.assertIn('Còn mở', page)
        self.assertIn('Chưa gắn với câu hỏi', page)

    def test_owner_words_verbatim(self):
        page = self.html()
        self.assertIn(self.words, unescape(page))
        self.assertIn('&lt;b&gt;', page)
        self.assertNotIn('sample-secret', page)
        self.assertIn('password=[withheld]', page)

    def test_ai_proposal_labelled(self):
        page = self.html(view='turns', q='Còn câu nào')
        self.assertIn('<h3>AI hỏi</h3>', page)
        self.assertIn('<li>Giữ</li><li>Đổi</li>', page)
        self.assertNotIn('<h3>Chủ chọn</h3>', page)
        self.assertIn('Đề xuất của AI', self.html(q='Lịch sử'))

    def test_choice_answered_or_open(self):
        self.assertIn('Đã trả lời · B', self.html(q='Chọn thứ tự'))
        question = self.html(q='Còn câu nào')
        self.assertIn('Còn mở', question)
        self.assertNotIn('Đã trả lời', question)

    def test_artifact_linked(self):
        page = self.html(q=self.blob)
        link = unescape(re.search(r'href="(/api/evidence[^"]+)"', page)[1])
        status, body = self.server.get(link)
        self.assertEqual(status, 200)
        self.assertIn(b'public fixture output', body)
        tree = self.html(q=self.tree)
        self.assertIn('chỉ có mã trong sổ', tree)
        self.assertNotIn('/api/evidence', tree)

    def test_drift_flag_without_amend(self):
        self.assertIn('Chưa thấy bản sửa sau lời này', self.html(q='Chuyển sang'))
        self.assertIn('sau khi mốc đã đạt', self.html(q=self.tree))
        page = self.html(q='design.html')
        self.assertIn('Sản phẩm ngoài repo', page)
        self.assertIn('Nhắc phạm vi', page)
        self.assertNotIn('not-observed', page)
        self.assertNotIn('method="post"', page.lower())
        self.assertNotIn('Không chuyển sang trang khác.', self.html(view='turns'))
        self.assertNotIn('Mở rộng phạm vi để làm gì?', self.html(view='turns'))

    def test_same_time_amend_only_covers_earlier_direction_changes(self):
        when = datetime(2026, 11, 20, tzinfo=timezone.utc)
        prompt = {'observation': 'owner_prompt', 'text': 'Chuyển sang giao diện mới'}
        before, _, after = tracking_direction._entries([
            (when, 1, 'hook.observed', prompt),
            (when, 2, 'plan.amended', {'revision': 2}),
            (when, 3, 'hook.observed', prompt),
        ])
        self.assertNotIn('Chưa thấy bản sửa sau lời này', before.note)
        self.assertIn('Chưa thấy bản sửa sau lời này', after.note)

    def test_long_history_paged_and_searchable(self):
        first = self.html(view='all', q='Nhật ký riêng')
        self.assertEqual(first.count('<article id='), tracking_direction.PAGE_SIZE)
        link = unescape(re.search(r'href="([^"]+)">Trang sau', first)[1])
        status, raw = self.server.get(link)
        self.assertEqual(status, 200)
        self.assertIn('Trang 2/2', raw.decode())
        self.assertNotIn('Nhật ký riêng 000', raw.decode())
        self.assertIn('Nhật ký riêng 027', self.html(q='riêng 027'))

    def test_phase_summary_marked_ai(self):
        self.assertIn('AI tóm tắt · Gộp hai màn hình', self.html())
        page = self.html(q='Còn câu nào')
        self.assertNotIn('AI tóm tắt', page)
