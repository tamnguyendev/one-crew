"""UIMOCK (plan of 23/11): the tracking pages look and read like the mockup approved on 19/11, on a temporary ledger; fast, no browser.

What is checked here is the page's own markup and the server's answers, the same behaviours the contract's page checks measure in a real
browser (kiem-trang.js at 1280 and 375 px): the shell (four destinations with icons, the i / ? / theme buttons, a legend of icons), the work
list (one-line rows with a status icon, a milestone bar and the time since the last change; six status chips with counts; no form filters on
the default screen, old filter links still open), the task page (four tiles in a 2x2 grid with the mockup's titles, "Xem sâu" as eleven
one-line rows with icons, no old tabs; the head read without the timeline, evidence or comparison: UIMOCK D4), Tổng quan, Phiên Claude and
Hướng đi (frames that say "chưa quan sát" when nothing was observed; numbers, lanes, stage letters and the owner's words when a session was),
and no internal code (plan-ns:, TASK-…, full hashes) in the words a reader sees.
"""
import contextlib
import io
import os
import re
import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

from onecrew.v2 import tracking, tracking_dashboard, tracking_list, tracking_web
from tests.test_ui33_task_first import Project, Served, js, milestone, text

INTERNAL = re.compile(r'plan-ns:\S+|TASK-[0-9a-f]{8}|(?:^|[\s·:(])[0-9a-f]{40,}(?=$|[\s·)])')


def visible(markup):
    """The words of a page a reader sees without opening anything: scripts, styles, closed <details> bodies, hidden parts and attributes out."""
    markup = re.sub(r'<(script|style)[^>]*>[\s\S]*?</\1>', ' ', markup)
    markup = re.sub(r'<details(?![^>]*\bopen\b)[^>]*>\s*<summary[^>]*>([\s\S]*?)</summary>[\s\S]*?</details>', r' \1 ', markup)
    markup = re.sub(r'<(\w+)[^>]*\bhidden\b[^>]*>[\s\S]*?</\1>', ' ', markup)
    return text(markup)


class Mockup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory(prefix='ui-mockup-')
        cls.addClassCleanup(temp.cleanup)
        cls.base = Path(temp.name)
        env = patch.dict(os.environ, {'ONECREW_LEASE_HOME': str(cls.base / 'leases'), 'CLAUDE_CONFIG_DIR': str(cls.base / 'claude')})
        env.start()
        cls.addClassCleanup(env.stop)
        for key in ('ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'):
            os.environ.pop(key, None)
        cls.state = cls.base / 'state'
        cls.project = p = Project(cls.base, 'du-an', cls.state)
        p.plan('ASK', [milestone()], approve=False, title='ASK: việc chờ bạn duyệt')
        p.plan('RUN', [milestone('M1'), milestone('M2')], title='RUN: việc có một phiên Claude đã quan sát')
        p.plan('NEW', [milestone()], title='NEW: việc chưa bắt đầu')
        p.timed_out('RUN')
        stamp = '2026-11-21T03:56:0{}+00:00'
        for i, (kind, fields) in enumerate([
                ('session_start', {}), ('owner_prompt', {'text': 'Chuyển sang xem báo cáo theo giai đoạn.'}),
                ('ai_question', {'text': 'Cần xem bản nào?', 'options': ['Bản trước', 'Bản mới'], 'question_id': 'q1'}),
                ('owner_choice', {'text': 'Bản mới', 'question_id': 'q1'}), ('tool_call', {'tool': 'Read', 'tool_use_id': 'r1', 'hook': 'PostToolUse'}),
                ('tool_call', {'tool': 'Edit', 'tool_use_id': 'e1', 'hook': 'PostToolUse'}), ('subagent_start', {'agent_id': 'soat'}),
                ('background_shell', {'tool': 'Bash', 'label': 'Kiểm tra bản mẫu'}), ('session_end', {})]):
            p.emit('RUN', 'hook.observed', dict(fields, observation=kind, session='phien-mau', revision=1, recorded_at=stamp.format(i)))
        cls.pid = p.ledger.project_id
        cls.server = Served(cls.state)
        cls.server.__enter__()
        cls.addClassCleanup(cls.server.__exit__, None, None, None)

    def get(self, path):
        status, body = self.server.get(path)
        self.assertEqual(status, 200, body[:300])
        return body.decode('utf-8')

    def scope(self, plan):
        return urllib.parse.urlencode({'plan': plan, 'project_id': self.pid})

    # ---- shell ------------------------------------------------------------------------------------------------------------------------

    def test_every_page_has_the_shell(self):
        for path, current in (('/', 'work'), ('/overview', 'overview'), ('/sessions?' + self.scope('RUN'), 'sessions'),
                              ('/direction?' + self.scope('RUN'), 'direction'), ('/sessions', 'sessions'), ('/direction', 'direction')):
            with self.subTest(path=path):
                page = self.get(path)
                nav = re.search(r'<nav class="views" id="nav"[^>]*>([\s\S]*?)</nav>', page)[1]
                links = re.findall(r'<a href="[^"]*" data-nav="(\w+)"([^>]*)>([\s\S]*?)</a>', nav)
                self.assertEqual([k for k, _, _ in links], ['overview', 'work', 'sessions', 'direction'])
                for key, attrs, inner in links:
                    self.assertIn('<svg', inner)                                                   # every destination has its icon
                    self.assertEqual('aria-current="page"' in attrs, key == current)               # the page the reader is on is marked
                self.assertEqual([text(inner).split(' ')[0] for _, _, inner in links], ['Tổng', 'Công', 'Phiên', 'Hướng'])
                for label in ('Dữ liệu này không cho thấy gì', 'Chú giải biểu tượng', 'Đổi nền'):
                    self.assertIn('aria-label="' + label, page)
                legend = re.search(r'<div id="legend"[^>]*>([\s\S]*?)</div>', page)[1]
                self.assertGreaterEqual(legend.count('<svg'), 8)
                self.assertIn('Trạng thái việc', legend); self.assertIn('Không đạt', legend)
                self.assertIn("localStorage.setItem('oc-theme'", page)                         # the theme button changes and keeps the theme
                self.assertIn(':root[data-theme=dark]', page)
                self.assertIn('.views{position:fixed;left:0;right:0;bottom:0', page)               # a phone: the four destinations at the bottom
                self.assertFalse(INTERNAL.search(visible(page)), INTERNAL.search(visible(page)))

    def test_page_script_is_one_script_the_node_tests_can_load(self):
        self.assertEqual((tracking_web.PAGE.count('<script>'), tracking_web.PAGE.count('</script>')), (1, 1))
        self.assertEqual(js('typeof shellInit'), 'function')                                        # the shell does not run without a document
        self.assertNotIn('@@', tracking_web._page(2).replace('@@INTERVAL@@', ''))

    def test_the_list_placeholder_says_in_words_that_the_list_is_still_being_read(self):
        # 23/11: the task tiles paint before the list (0f26e35); a text-less grey placeholder let a person, and a screenshot that waits until the page
        # no longer says "đang đọc/tải", take the empty rows for the list. The words say "đang đọc", not "đang tải": the open-time clock stops when the
        # four tiles are on screen and the page does not say "đang tải", so the list still being read does not count as the task being slow to open.
        box = re.search(r'<div id="empty">(.*?)</div>', tracking_web._page(2), re.S)
        self.assertTrue(box, 'the list placeholder is on the page')
        words = re.sub(r'<[^>]+>', ' ', box.group(1)).strip()
        self.assertTrue(re.search(r'đang (đọc|tải)', words, re.I), words)
        self.assertRegex(words, r'(?i)đang đọc danh sách')
        self.assertNotRegex(words, r'(?i)đang tải')

    # ---- the work list ----------------------------------------------------------------------------------------------------------------

    def test_list_rows_are_one_line_with_icon_bar_and_age(self):
        page = tracking_list.page(self.state, {'list': '1', 'limit': '50'})
        rows = {t['plan']: t for p in page['projects'] for t in p['tasks']}
        for name, t in rows.items():
            with self.subTest(plan=name):
                line = js('rowLine(t)', t=t)
                self.assertIn('<svg', line)                                                        # status icon
                self.assertRegex(line, r'<span class="mini"[^>]*>(<i class="seg-\w+"[^>]*></i>)+</span>')   # milestone cells
                self.assertRegex(text(line), r'(giờ|ngày|phút|vừa xong)$')                       # the time since the last change
                self.assertLessEqual(len(text(line)), 80)
                self.assertTrue(text(line).startswith(name + ':'))                                 # the plan's short name first
                row = js('row(t)', last=page, t=t)
                self.assertIn('class="rx" hidden', row)                                            # the older card's words stay out of sight
        self.assertIn('cần bạn', text(js('rowLine(t)', t=rows['ASK'])))

    def test_six_chips_count_every_root_once(self):
        page = tracking_list.page(self.state, {'list': '1', 'limit': '50'})
        groups = page['list']['groups']
        self.assertEqual(groups['all'], page['list']['total'])
        self.assertEqual(sum(groups[k] for k in ('need', 'doing', 'check', 'todo', 'done')), groups['all'])
        chips = js('chipsHtml()', last=page)
        names = [re.sub(r'\s+\d+$', '', text(c)) for c in re.findall(r'<button[^>]*class="fchip[^"]*"[^>]*>[\s\S]*?</button>', chips)]
        self.assertEqual(names, ['Cần bạn', 'Đang làm', 'Chờ kiểm', 'Chưa bắt đầu', 'Xong', 'Tất cả'])
        self.assertIn('Tất cả <b>' + str(groups['all']) + '</b>', chips)
        for stage, key in (('need', 'need'), ('g_doing', 'doing'), ('g_check', 'check'), ('g_todo', 'todo'), ('g_done', 'done')):
            with self.subTest(stage=stage):
                answer = tracking_list.page(self.state, {'list': '1', 'stage': stage})
                listed = [t for p in answer['projects'] for t in p['tasks']]
                self.assertEqual(len(listed), groups[key])
                self.assertTrue(all(tracking_list.group(t) == key for t in listed))
        self.assertEqual(groups['need'], 1)
        self.assertIn('<b>1</b> việc cần bạn', js('heroHtml()', last=page))

    def test_no_form_filters_on_the_default_screen_and_old_links_open(self):
        page = self.get('/')
        shown = re.sub(r'<(script|style)[^>]*>[\s\S]*?</(script|style)>', '', page)
        shown = re.sub(r'<div id="oldfilters" hidden>[\s\S]*?</div></details></div>', '', shown)
        self.assertNotIn('<select', shown); self.assertNotIn('type="date"', shown)
        self.assertNotIn('data-list-mode', shown); self.assertNotIn('Mỗi dòng là một công việc', page)
        for value in ('recheck', 'need', 'g_doing', 'g_done', 'ended', 'fix'):
            self.assertIn('<option value="' + value + '"', page)                                   # an old (or chip) filter link sets the same select
        for query in ('?stage=recheck&project=' + urllib.parse.quote(str(self.project.root)), '?stage=fix', '?stage=g_todo'):
            self.get('/' + query)
            status, answer = self.server.json('/api/overview?list=1&' + query[1:])
            self.assertEqual(status, 200, answer)

    # ---- the task page ------------------------------------------------------------------------------------------------------------------

    def test_head_read_has_the_tiles_data_and_nothing_heavy(self):
        status, head = self.server.json('/api/task?' + self.scope('RUN') + '&part=head')
        self.assertEqual(status, 200, head)
        self.assertEqual(head['kind'], 'onecrew-tracking-head')
        for heavy in ('timeline', 'evidence_index', 'gantt', 'work', 'milestone_checks'):
            self.assertNotIn(heavy, head)
        for needed in ('situation', 'validity', 'milestones', 'needs_user', 'headline'):
            self.assertIn(needed, head)
        status, full = self.server.json('/api/task?' + self.scope('RUN'))
        self.assertEqual(status, 200)
        self.assertIn('timeline', full); self.assertIn('work', full)

    def test_four_tiles_2x2_with_the_mockup_titles(self):
        for name in ('ASK', 'RUN', 'NEW'):
            with self.subTest(plan=name):
                d = tracking.head(self.state, name, project_id=self.pid)
                tiles = js('taskTiles(d)', d=d)
                self.assertIn('class="tiles4"', tiles)
                titles = re.findall(r'<h3>([^<]*)</h3>', tiles)
                self.assertEqual(titles, ['Đầu ra', 'Còn tin được?', 'Bước tiếp', 'Bạn quyết'])
                for tile in re.findall(r'<section class="tile4[\s\S]*?</section>', tiles):
                    self.assertIn('class="ic lg', tile)                                           # a big icon
                    self.assertRegex(tile, r'<p class="val[^"]*">')                                # one big conclusion
                self.assertLessEqual(len(visible(tiles)), 900)                                     # the long explanations sit behind (i)
                full = tracking.detail(self.state, name, project_id=self.pid)
                self.assertLessEqual(len(visible(js('taskTiles(d)', d=full))), 900)
        head = tracking.head(self.state, 'RUN', project_id=self.pid)
        self.assertIn(js('VALID_WORD[d.validity.kind]', d=head), text(js('tileTrust(d)', d=head)))     # one short word for the validity

    def test_deep_rows_and_no_old_tabs(self):
        for d in (tracking.head(self.state, 'RUN', project_id=self.pid), tracking.detail(self.state, 'RUN', project_id=self.pid)):
            deep = js('deepSections(d)', d=d)
            rows = re.findall(r'<details class="deep-d" data-k="deep-(\w+)" id="deep-\w+"><summary>([\s\S]*?)</summary>', deep)
            self.assertEqual([text(s).split('  ')[0] for _, s in rows][0], 'Yêu cầu và phạm vi')
            self.assertEqual(len(rows), 11)
            for key, summary in rows:
                self.assertIn('<svg', summary)
            names = ' | '.join(text(s) for _, s in rows)
            for want in ('Mốc và lần kiểm', 'Vòng sửa', 'Thay đổi kế hoạch', 'Lịch sử hướng đi', 'Thời gian và ai chờ ai', 'Bằng chứng',
                         'Agent và việc nền', 'Phiên Claude đã làm việc này', 'Tài nguyên dùng chung', 'Mã kỹ thuật'):
                self.assertIn(want, names)
            self.assertNotIn(' open>', deep.split('</summary>')[0])                               # closed until the reader opens one
        page = js('(function(){var out=[];selected={plan:d.selector,project:d.project_id};return taskTiles(d)+deepSections(d)})()',
                  d=tracking.detail(self.state, 'RUN', project_id=self.pid))
        for tab in ('>Solution<', '>Kết quả &amp; kiểm chứng<', '>Tiến độ<', 'Tóm tắt: đang ở đâu', 'role="tab"'):
            self.assertNotIn(tab, page)

    def test_task_title_and_meta_line(self):
        d = tracking.head(self.state, 'RUN', project_id=self.pid)
        head = js('thead(d)', d=d)
        self.assertRegex(head, r'<h2 id="dtitle"[^>]*>RUN: ')                                    # the title first, with the plan's short name
        meta = re.search(r'<p class="tmeta">([\s\S]*?)</p>', head)[1]
        self.assertGreaterEqual(meta.count('<svg'), 3)
        self.assertIn('/sessions?plan=', meta); self.assertIn('/direction?plan=', meta)
        self.assertIn('‹ Quay lại', head)
        self.assertFalse(INTERNAL.search(visible(head)))

    # ---- Tổng quan ------------------------------------------------------------------------------------------------------------------------

    def test_overview_sections(self):
        page = self.get('/overview')
        chips = re.findall(r'<a [^>]*data-(?:attn|chat)="\w+"[^>]*>([\s\S]*?)</a>', page)
        words = [text(c) for c in chips]
        for name, source in (('Câu hỏi chưa trả lời', 'chat'), ('Vượt hợp đồng', 'chat'), ('Bạn cần quyết', 'sổ'), ('Không đạt', 'sổ'),
                             ('Chưa kết luận', 'sổ'), ('Cần kiểm lại', 'sổ'), ('Lâu không động', 'sổ')):
            self.assertTrue(any(re.fullmatch(r'\d+ ' + name + ' ' + source, w) for w in words), (name, words))
        self.assertIn('0 Câu hỏi chưa trả lời chat', words)                                       # the RUN session's question was answered
        for card in ('Claude đang làm gì', 'Token, model, chi phí', 'Hướng đi RUN'):
            self.assertIn('<span>' + card + '</span>', page)
        self.assertIn('Theo repo (worktree bên trong)', page)
        self.assertIn('class="sbar"', page)
        self.assertIn('Nhịp kiểm 14 ngày', page)
        for stat in ('lần kiểm</span>', 'lần kiểm đạt (', 'vòng sửa</span>', 'mốc đạt</span>'):
            self.assertIn(stat, page)
        self.assertIn('Việc nền hook báo', page); self.assertIn('Tài nguyên dùng chung', page)
        self.assertRegex(text(page), r'Đạt \d+ Không đạt \d+')

    # ---- Phiên Claude ---------------------------------------------------------------------------------------------------------------------

    def test_sessions_data(self):
        page = self.get('/sessions?' + self.scope('RUN'))                                        # the task's only session: opened at once
        shown = visible(page)
        for n, word in ((9, 'bước'), (1, 'lệnh'), (1, 'sửa'), (1, 'nhánh agent'), (0, 'lệnh lỗi')):
            self.assertIn(f'<b>{n}</b><small>{word}</small>', page)
        self.assertIn('Lọc theo việc RUN', shown)
        self.assertIn('<svg class="lanes"', page)
        for lane in ('Phiên chính', 'Agent con · soat', 'Lệnh nền'):
            self.assertIn(f'<h3>{lane}</h3>', page)
        self.assertGreaterEqual(len(re.findall(r'<time title="[^"]*">\d\d:\d\d</time>', page)), 5)  # a phone: the steps with their time
        for button in ('1 giờ', '6 giờ', 'Cả khung'):
            self.assertRegex(page, r'<button type="button" data-window="\w+" aria-pressed="\w+">' + button + '</button>')
        self.assertIn('Danh sách việc</span>', page); self.assertIn('Claude tự báo', page)
        self.assertIn('Token, loại bước, suy luận', page)
        self.assertGreaterEqual(page.count('<svg class="chart"'), 2)
        self.assertFalse(INTERNAL.search(shown))

    def test_sessions_and_direction_not_observed_keep_their_frames(self):
        for path, frames in (('/sessions?' + self.scope('NEW'), ('Claude đã làm gì', 'Danh sách việc', 'Token, loại bước, suy luận')),
                             ('/direction?' + self.scope('NEW'), ('Phiên thấy gì, sổ thấy gì', 'tin chủ gõ', 'lần đổi hướng'))):
            with self.subTest(path=path):
                page = self.get(path)
                for frame in frames:
                    self.assertIn(frame, page)
                self.assertIn('hưa quan sát', visible(page))
                self.assertFalse(INTERNAL.search(visible(page)))

    # ---- Hướng đi -------------------------------------------------------------------------------------------------------------------------

    def test_direction_data(self):
        page = self.get('/direction?' + self.scope('RUN'))
        for value, word in (('1', 'tin chủ gõ'), ('1 / 1', 'AI hỏi / chủ bấm'), ('1', 'lần đổi hướng')):
            self.assertIn(f'<b>{value}</b><small>{word}', page)
        self.assertRegex(page, r'<b>\d+ / 0</b><small>dấu vết sổ / sửa plan')
        for row in ('Hướng', 'Phiên', 'Sổ'):
            self.assertIn(f'<div class="bl">{row}</div>', page)
        for tab in ('Giai đoạn', 'Điểm rẽ', 'Tất cả bước'):
            self.assertRegex(page, r'<a role="tab"[^>]*>' + tab + '</a>')
        self.assertIn('placeholder="Tìm trong lời chủ, câu hỏi, commit"', page)
        self.assertRegex(page, r'<span class="dtag" style="--d:[^"]+">[A-H]</span>')            # stage letters
        self.assertIn('lời chủ', visible(page))
        self.assertIn('Chuyển sang xem báo cáo theo giai đoạn.', page)                          # the owner's words, verbatim
        self.assertFalse(INTERNAL.search(visible(page)))

    # ---- speed ------------------------------------------------------------------------------------------------------------------------------

    def test_prewarm_and_head_is_quick(self):
        tracking.prewarm()
        started = time.perf_counter()
        tracking.head(self.state, 'RUN', project_id=self.pid)
        self.assertLess(time.perf_counter() - started, 3.0)


if __name__ == '__main__':
    unittest.main()
