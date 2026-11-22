"""UI58 MC, two regressions found on REAL ledger data (19/11), as checks on a temporary ledger and the shipped page script:

  1. a plain plan whose next milestone has an owner-manual verifier (every milestone before it passed) waits for the OWNER: the list row, the
     "Cần bạn" filter and chip, the counts, the task page's next step and "Bạn cần quyết gì" all say the owner tries and records that milestone,
     then accepts, as `plan report` does ("Cần bạn làm: nghiệm thu"); no command is invented;
  2. a list row is one short line: a short name (the first sentence of the owner's request, clipped) then state -> next step; the full request
     stays on the task page, in the row's title attribute and accessible name, and in what the search matches.

Self-contained (no sibling test import), so the verifier can rerun it from a copy of tests/ against the installed wheel. Node.js is required;
its absence FAILS the test, never skips it.
"""
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger
from onecrew.v2 import plan as plans, report, tracking, tracking_list, tracking_web, verdict

OK = [sys.executable, '-c', 'print("ok")']
NODE_FALLBACK = r'C:\Program Files\nodejs\node.exe'
REQUEST = ('Sửa trang theo dõi để mốc chờ chủ sở hữu tự thử hiện đúng là việc của chủ, trong danh sách và trong trang việc, kể cả khi mở trên '
           'dữ liệu thật của sổ. Mỗi dòng của danh sách chỉ còn một dòng ngắn. Không đổi gì khác.')
MO_TITLE = 'Chủ sở hữu thử trên dữ liệu thật'
STEPS = ['Mở trang theo dõi', 'Bấm vào việc và đọc bước tiếp theo']


def milestone(mid, verifier=None):
    return {'id': mid, 'title': 'Milestone ' + mid if mid != 'MO' else MO_TITLE, 'covers': ['O1'],
            'verifier': verifier or {'type': 'command', 'config': {'argv': OK}}}


def plan_json(milestones, title, presentation=None):
    body = {'schema_version': 2, 'title': title, 'size': 'S',
            'understanding': {'restated_goal': 'Do the sample and prove it.', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']},
                              'assumptions': [], 'confidence': 'high', 'unknowns': []},
            'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'the file to work on is there'}],
            'output': ['The sample exists'], 'scope': {'owned': ['a.txt']}, 'non_goals': ['Nothing else'],
            'items': [{'id': 'I1', 'title': 'Do it', 'tier': 'must', 'milestone': milestones[0]['id']}],
            'milestones': milestones, 'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1}, 'profile_version': None}
    if presentation:            # a contract that speaks to the owner says where it comes from (step 0 of approve)
        body.update(presentation=presentation, origin={'by': 'owner', 'at': '2026-11-19', 'quote': REQUEST})
        body['items'][0]['source'] = 'origin'
    return body


def node():
    found = shutil.which('node') or (NODE_FALLBACK if Path(NODE_FALLBACK).is_file() else None)
    if not found: raise AssertionError('Node.js is required for this test (not on PATH, not at %s)' % NODE_FALLBACK)
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
    return ' '.join(re.sub(r'<[^>]+>', ' ', markup).replace('&gt;', '>').replace('&lt;', '<').replace('&quot;', '"').replace('&amp;', '&').split())


class OwnerStep(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='ui33-owner-')
        base = Path(cls.temp.name)
        cls.env = patch.dict(os.environ, {'ONECREW_LEASE_HOME': str(base / 'leases')}); cls.env.start()
        for name in ('ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(name, None)
        root = cls.root = base / 'du-an'; root.mkdir()
        for args in (('init', '-q'), ('config', 'user.name', 'T'), ('config', 'user.email', 't@localhost')): cls.git(*args)
        (root / 'a.txt').write_text('one\n'); cls.git('add', '.'); cls.git('commit', '-q', '-m', 'base')
        cls.ledger = Ledger(root, base / 'state')
        manual = {'type': 'owner-manual', 'config': {}}
        shown = {'request': REQUEST, 'user_sees': ['Dòng việc ngắn'], 'acceptance_steps': STEPS, 'not_doing': 'Không đổi gì khác'}
        with contextlib.redirect_stderr(io.StringIO()):      # several plans on one project: the active-plan export warns, by design
            for name, ms, title, present in (('OWN', [milestone('MB'), milestone('MA'), milestone('MO', manual)], 'Tiêu đề hợp đồng của việc chờ chủ', shown),
                                             ('OWN1', [milestone('MO', manual)], 'Một mốc do chủ tự thử', None),
                                             ('AI', [milestone('MB'), milestone('MC')], 'Việc AI còn làm', None),
                                             ('MID', [milestone('MB'), milestone('MO', manual), milestone('MC')], 'Mốc chủ ở giữa', None)):
                plans.propose(cls.ledger, name, plan_json(ms, title, present), 'claude', workflow=True)
                os.environ.pop('ONECREW_ACTOR', None)
                plans.approve(cls.ledger, name, 'owner', 'test fixture')
        for name, mid in (('OWN', 'MB'), ('OWN', 'MA'), ('AI', 'MB'), ('MID', 'MB')): verdict.run(cls.ledger, name, mid)
        cls.state_root = cls.ledger.state_root

    @classmethod
    def tearDownClass(cls):
        cls.env.stop(); cls.temp.cleanup()

    @classmethod
    def git(cls, *args):
        return subprocess.check_output(['git', '-C', str(cls.root), *args], stderr=subprocess.PIPE).decode().strip()

    def detail(self, name):
        return tracking.detail(self.state_root, name, project_id=self.ledger.project_id)

    def listed(self, query=None):
        page = tracking_list.page(self.state_root, dict({'list': '1', 'limit': '50'}, **(query or {})))
        return page, {t['plan']: t for p in page['projects'] for t in p['tasks']}

    def test_owner_manual_milestone_is_owner_step(self):
        tracking._compared.clear()
        step = 'Bạn thử và ghi kết quả mốc MO: ' + MO_TITLE
        # plan report (the reference): the owner has to accept, it is the owner's move
        said = report.render_report(self.state_root, 'OWN', project_id=self.ledger.project_id)
        self.assertIn('Bạn cần làm: nghiệm thu', said)
        # the task page: the next step is the owner's, the stage says so honestly, the decision tile is not "nothing waits for you"
        d = self.detail('OWN')
        s = d['situation']
        self.assertEqual((s['stage'], s['label']), ('accept', 'Chờ bạn thử và nghiệm thu'))
        self.assertEqual((s['next'], s['next_by'], s['next_by_text']), (step, 'owner', 'Bạn'))
        self.assertFalse(s['no_owner_decision'])
        self.assertIn('MB, MA đã đạt', s['reason']); self.assertIn('rồi bạn nghiệm thu', s['reason'])
        self.assertEqual(s['milestones']['text'], 'Đạt 2/3 mốc')
        self.assertIn('chờ chủ sở hữu tự thử và ghi kết quả mốc MO', d['status']['reason'])
        needs = [n for n in d['needs_user'] if n['kind'] == 'owner_try']
        self.assertEqual(len(needs), 1)
        n = needs[0]
        self.assertEqual((n['owner_ask'], n['milestone']), (step, 'MO'))
        self.assertEqual(n['steps'], STEPS)
        self.assertIsNone(n['human_command']); self.assertIsNone(n['reply_command'])      # no invented command
        self.assertFalse(n['action']['enabled'])
        self.assertIn('phần bàn giao của kế hoạch', n['binding_reason'])
        tiles = text(js('taskTiles(d)', d=d))
        self.assertIn('Bước tiếp Bạn ' + step, tiles)                                     # UIMOCK: who (big), then the step
        self.assertIn('Ai làm: Bạn', tiles)
        self.assertIn('Bạn quyết', tiles); self.assertIn(step, text(js('tileDecide(d)', d=d)))   # UIMOCK: the tile names the one decision waiting
        self.assertNotIn('Không có quyết định nào đang chờ bạn', tiles)
        self.assertNotIn('Chưa có thông tin người xử lý', tiles)
        card = text(js('needCard(n,0)', n=n))
        self.assertIn(step, card)
        self.assertIn('Cách thử: ' + '; '.join(STEPS), card)
        self.assertIn('phần bàn giao của kế hoạch', card)
        self.assertNotIn('Sao chép lệnh', card.split('Chỉ xem trạng thái')[0])   # the only command box (if any) is the read-only report
        # the list row says the same, without the task page having compared first
        tracking._compared.clear()
        page, rows = self.listed()
        r = rows['OWN']
        self.assertEqual((r['situation']['stage'], r['situation']['next'], r['situation']['next_by']), ('accept', step, 'owner'))
        line = text(js('statusLine(t)', t=r))
        self.assertIn('Cần bạn', line); self.assertIn('Chờ bạn thử và nghiệm thu', line); self.assertIn('→ ' + step, line); self.assertIn('· Bạn', line)
        self.assertNotIn('chưa rõ ai làm', line); self.assertNotIn('Làm và kiểm mốc', line)
        self.assertIn('<span class="needb">Cần bạn</span>', js('workItem(t)', last=page, t=r))
        # a single owner-manual milestone, nothing before it: the owner's too; an AI milestone after a pass and an AI milestone after the owner's are not
        self.assertEqual(rows['OWN1']['situation']['next'], 'Bạn thử và ghi kết quả mốc MO: ' + MO_TITLE)
        self.assertEqual(rows['OWN1']['situation']['next_by'], 'owner')
        self.assertEqual(rows['AI']['needs_user'], [])
        self.assertEqual(rows['AI']['situation']['next'], 'Làm và kiểm mốc MC')
        self.assertEqual(rows['MID']['situation']['next_by'], 'owner')             # MB passed, MO (owner) is next, MC waits behind it
        # filter, chip and count agree with the rows: "Cần bạn quyết định" finds exactly the owner's
        need, _ = self.listed({'stage': 'need'})
        self.assertEqual(sorted(t['plan'] for p in need['projects'] for t in p['tasks']), ['MID', 'OWN', 'OWN1'])
        self.assertEqual(sorted(js('tasks().filter(function(t){return (t.needs_user||[]).length}).map(function(t){return t.plan})', last=page)), ['MID', 'OWN', 'OWN1'])
        accept, _ = self.listed({'stage': 'accept'})
        self.assertEqual(sorted(t['plan'] for p in accept['projects'] for t in p['tasks']), ['MID', 'OWN', 'OWN1'])
        self.assertEqual(js('workOrder(tasks(),"attention").slice(0,3).map(function(t){return t.plan}).sort()', last=page), ['MID', 'OWN', 'OWN1'])

    def test_row_title_short_full_on_task(self):
        page, rows = self.listed()
        r = rows['OWN']
        first = REQUEST.split('. ')[0]
        self.assertLessEqual(len(r['row_title']), 80)
        self.assertTrue(r['row_title'].endswith('…'))
        self.assertTrue(first.startswith(r['row_title'][:-1]))
        self.assertNotIn('Mỗi dòng', r['row_title'])                               # only the first sentence
        self.assertEqual(r['owner_view']['request'], REQUEST)                        # the full text is still in the model
        item = js('workItem(t)', last=page, t=r)
        self.assertIn('<span class="ttl" title="' + REQUEST + '">' + r['row_title'] + '</span>', item)
        row = js('row(t)', last=page, t=r)
        label = re.search(r'aria-label="([^"]*)"', row).group(1)
        self.assertTrue(label.startswith(REQUEST)); self.assertIn('Chờ bạn thử và nghiệm thu', label)
        self.assertNotIn(REQUEST, text(item))                                        # the visible row text is the short name, not the paragraph
        # a short first sentence is kept whole, without its full stop; no request -> the contract title (short_title)
        self.assertEqual(tracking.row_title('Sửa nút Lưu. Rồi kiểm lại.', 'T'), 'Sửa nút Lưu')
        self.assertEqual(tracking.row_title(None, 'Một mốc do chủ tự thử'), 'Một mốc do chủ tự thử')
        self.assertEqual(rows['OWN1']['row_title'], 'Một mốc do chủ tự thử')
        self.assertEqual(tracking.row_title('Bản v2.5.0 chạy ổn', None), 'Bản v2.5.0 chạy ổn')       # a dot inside a word is not a sentence end
        # the task page keeps the full request ("Việc này làm gì")
        d = self.detail('OWN')
        self.assertIn('Việc này làm gì ' + REQUEST, text(js('workOwnerSection(d)', d=d)))
        # search still matches words only in the full text (not in the short name)
        found, _ = self.listed({'q': 'Không đổi gì khác'})
        self.assertEqual([t['plan'] for p in found['projects'] for t in p['tasks']], ['OWN'])
        self.assertIn('kể cả khi mở trên', js('workSearch(t)', t=r))


if __name__ == '__main__':
    unittest.main()
