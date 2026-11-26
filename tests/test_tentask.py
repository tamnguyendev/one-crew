"""TENTASK: the "Danh sách task" block of the tracking page made readable. A sub-task of an internal plan may carry a short name for people
("title": "Rà mã phần 2/34", one line, 1 to 80 characters, display only like the NHANVAI role label); without one the page takes the head of
its goal (up to the first ": " or ". ", at most 70 characters, cut with "…"); one summary line from ledger figures sits above the rows; opening a
row shows the whole goal, the instruction given to the AI; @role stays under the name of every row.

Rule of these cases (contract TENTASK, checker kiem-tentask.py): a case of new behaviour fails BY ASSERTION on the base a9b4333 (NHANVAI
accepted): a refused field or a missing key is turned into self.fail, never an error. Real temporary ledger, Git and Control attempts
(tests.test_wf_engine.EngineFixture); the page cases run the shipped page script under node, as tests.test_nhanvai does.
"""
import json
import shutil
import subprocess

from onecrew.ledger import LedgerError
from onecrew.v2 import engine, tracking
from onecrew.v2.tracking_web import PAGE
from tests.test_wf_engine import EngineFixture, node

LONG_GOAL = ('Cụm 2 review vn-sign-sdk @bef6476 (node độc lập): đọc các tệp của cụm 2, ghi mọi phát hiện có dòng và bằng chứng, '
             'không sửa mã, không chạy lại cụm khác. ' + 'Chi tiết thêm cho AI. ' * 30).strip()


def named(nid, title=None, dependencies=(), integration=False, write=('a.txt',), goal=None, role=None):
    """node() of test_wf_engine with the TENTASK short name (and the NHANVAI label); dependencies are upstream ids (requires verified)."""
    value = node(nid, dependencies, integration=integration, write=write)
    if goal is not None: value['goal'] = goal
    if title is not None: value['title'] = title
    if role is not None: value['role'] = role
    return value


class TestTenTask(EngineFixture):
    def revise_or_fail(self, nodes):
        """The base refuses a node field it does not know: that is the missing behaviour, so a FAILURE, not an error."""
        try:
            return self.revise(nodes)
        except LedgerError as error:
            self.fail('an internal plan with a short name ("title") is not accepted: ' + str(error)[:300])

    def definition(self):
        return self.ip.current(self.ledger, 'P1')['definition']

    def detail(self):
        return tracking.detail(self.ledger.state_root, 'P1')

    def js(self, expr, extra=''):
        runner = shutil.which('node')
        if not runner: self.skipTest('Node unavailable; not verified')
        start = PAGE.index('<script>') + 8; body = PAGE[start:PAGE.rindex('</script>')].replace('@@INTERVAL@@', '2000')
        body = body.replace('(function(){', '', 1); body = body[:body.rindex('})();')]
        stub = ("var document={querySelector:function(){return {addEventListener:function(){},value:'',options:[],style:{}}},querySelectorAll:function(){return []},addEventListener:function(){}};"
                "var window={matchMedia:function(){return {matches:false,addEventListener:function(){}}},addEventListener:function(){},scrollTo:function(){},scrollY:0};"
                "var location={search:'',pathname:'/'};var history={pushState:function(){}};var localStorage={getItem:function(){return null},setItem:function(){}};"
                "function setInterval(){};function setTimeout(){};function fetch(){return {then:function(){return {then:function(){return {catch:function(){return {then:function(){}}}}}}}}};")
        result = subprocess.run([runner, '-'], input=stub + body + extra + '\nconsole.log(JSON.stringify(' + expr + '));', text=True, encoding='utf8',
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        return json.loads(result.stdout.strip().splitlines()[-1])

    def task_list(self, d):
        html = self.js("typeof taskList==='function'?taskList(d):null", '\nvar d=' + json.dumps(d) + ';')
        if html is None: self.fail('the page has no "Danh sách task" block')
        return html

    def page_data(self):
        """The owner's picture of 25/11 22:34 with short names: two backend sub-tasks done, the frontend one running, the lead's waiting."""
        return {'plan': 'NHANVAITHU', 'row_title': 'NHANVAI thử',
                'node_titles': {'BE1': 'BE viết hợp đồng API', 'BE2': 'BE làm API', 'FE': 'FE làm giao diện', 'LEAD': 'Lead kiểm tích hợp, ghi quyết định'},
                'node_goals': {'BE1': 'Viết hợp đồng API: <các điểm cuối> & mã lỗi', 'BE2': 'Làm API theo hợp đồng', 'FE': 'Làm giao diện',
                               'LEAD': 'Kiểm tích hợp, ghi quyết định'},
                'nodes': {'BE1': {'phase': 'complete', 'state': 'verified', 'generation': 0, 'role': 'backend', 'waits_for': []},
                          'BE2': {'phase': 'complete', 'state': 'accepted', 'generation': 0, 'role': 'backend', 'waits_for': []},
                          'FE': {'phase': 'running', 'state': 'none', 'generation': 0, 'role': 'frontend', 'waits_for': []},
                          'LEAD': {'phase': 'pending', 'state': 'none', 'generation': 0, 'role': 'lead', 'waits_for': ['BE2', 'FE']}}}

    # ---- I1: the short name ---------------------------------------------------------------------------------------------------------
    def test_node_with_title_is_accepted(self):
        self.revise_or_fail([named('C', 'Rà mã phần 2/34', goal=LONG_GOAL), named('I', 'x' * 80, ['C'], integration=True, write=())])
        nodes = {n['id']: n for n in self.definition()['nodes']}
        self.assertEqual((nodes['C'].get('title'), nodes['I'].get('title')), ('Rà mã phần 2/34', 'x' * 80))
        self.assertEqual(nodes['C']['goal'], LONG_GOAL)                    # the goal stays the AI's instruction, whole
        self.step(); self.verify('C')                                     # it runs exactly as a node without a name
        self.assertEqual(engine.state(self.ledger, 'P1')['nodes']['C']['state'], 'verified')

    def test_bad_title_is_refused(self):
        for bad in ('', '   ', 'x' * 81, 'hai\ndòng', 'hai\rdòng', 'a b', 5, None, ['Rà mã']):
            with self.subTest(title=bad):
                with self.assertRaisesRegex(LedgerError, 'title'):
                    self.revise([named('C') | {'title': bad}, named('I', None, ['C'], integration=True, write=())])
        self.assertEqual(self.ip.current(self.ledger, 'P1')['internal_revision'], 0)      # nothing was published

    def test_plan_without_title_unchanged(self):
        self.revise([node('C'), node('I', ['C'], integration=True, write=())])
        definition = self.definition()
        self.assertEqual(set(definition), {'version', 'nodes', 'acceptance'})
        self.assertFalse(any('title' in n for n in definition['nodes']))
        self.step(); self.verify('C')
        view = engine.state(self.ledger, 'P1')
        self.assertEqual((view['nodes']['C']['state'], view['nodes']['C']['generation']), ('verified', 0))
        self.assertEqual([t['id'] for t in engine.ready(self.ledger, 'P1')], ['I'])
        self.assertEqual(set(self.detail()['node_titles']), {'C', 'I'})

    # ---- I2: a short name is display only -------------------------------------------------------------------------------------------
    def test_title_change_does_not_bump_generation(self):
        first = [named('C', 'Rà mã phần 2/34'), named('I', 'Tổng hợp báo cáo', ['C'], integration=True, write=())]
        self.revise_or_fail(first)
        self.step(); self.verify('C')
        before = engine.state(self.ledger, 'P1')['nodes']['C']
        renamed = [dict(first[0], title='Rà mã cụm 2'), dict(first[1])]
        renamed[1].pop('title')                                           # a name removed is also only a name
        self.revise_or_fail(renamed)
        after = engine.state(self.ledger, 'P1')
        self.assertEqual(after['internal_revision'], 2)
        self.assertEqual((after['nodes']['C']['generation'], after['nodes']['C']['state'], after['nodes']['C']['artifact']),
                         (before['generation'], 'verified', before['artifact']), 'renaming moved the node: it would run again')
        self.assertEqual(after['nodes']['I']['generation'], 0)
        self.assertEqual([n.get('title') for n in after['definition']['nodes']], ['Rà mã cụm 2', None])
        self.revise([dict(renamed[0], goal='Produce other evidence for O1'), renamed[1]])   # control: a real change still moves the node
        self.assertEqual(engine.state(self.ledger, 'P1')['nodes']['C']['generation'], 1)

    # ---- I3: the names in the tracking detail ---------------------------------------------------------------------------------------
    def test_tracking_node_titles_prefer_title(self):
        self.revise_or_fail([named('C', 'Rà mã phần 2/34', goal=LONG_GOAL), named('I', None, ['C'], integration=True, write=(), goal='Tổng hợp báo cáo')])
        d = self.detail()
        self.assertEqual(d['node_titles'], {'C': 'Rà mã phần 2/34', 'I': 'Tổng hợp báo cáo'})
        self.assertEqual(d.get('node_goals', {}).get('C'), LONG_GOAL, 'the detail must still carry the whole goal')

    def test_short_name_from_goal_without_title(self):
        # rev 3: a short goal head that is not machine text is the name (a machine head is named from the work: the cases further down)
        long_goal = ' '.join(['Rà phần ký số: đọc các tệp của phần ký số, ghi mọi phát hiện có dòng và bằng chứng, không sửa mã.'] * 5)
        self.revise([named('A', goal=long_goal), named('B', goal='Gom kết quả. Sau đó ghi báo cáo: mục 1'),
                     named('D', goal='Tỷ lệ 3.5:1 theo mục 2'),
                     named('I', None, ['A', 'B', 'D'], integration=True, write=(), goal='Tích hợp')])
        d = self.detail()
        titles = d['node_titles']
        self.assertEqual(titles['A'], 'Rà phần ký số')                                        # up to the first ": "
        self.assertEqual(titles['B'], 'Gom kết quả')                                          # ". " comes before ": "
        self.assertEqual(titles['D'], 'Tỷ lệ 3.5:1 theo mục 2')                              # "." and ":" without a space do not cut
        self.assertEqual(titles['I'], 'Tích hợp')
        self.assertEqual(d.get('node_goals', {}).get('A'), ' '.join(long_goal.split()), 'the detail must still carry the whole goal')

    # ---- I4: the block -------------------------------------------------------------------------------------------------------------
    def test_page_task_list_summary_line(self):
        html = self.task_list(self.page_data())
        summary = html[html.find('</h3>') + 5:html.find('<ol>')] if '</h3>' in html and '<ol>' in html else ''
        self.assertIn('class="tl-sum"', summary, 'no summary line between the heading and the rows')
        for wanted in ('NHANVAI thử', '2/4 phần xong, cổng đạt', '1 đang làm', '0 bị giữ', '2 @backend, 1 @frontend, 1 @lead'):
            self.assertIn(wanted, summary)
        self.assertNotIn('<li', summary)
        d = {'plan': 'sdk-trial', 'nodes': {}}                               # 34 review sub-tasks and the lead's: most first
        for i in range(1, 35):
            d['nodes']['K%02d' % i] = {'phase': 'held' if i == 3 else 'running' if i < 3 else 'complete', 'state': 'verified' if i > 30 else 'none', 'role': 'review'}
        d['nodes']['KZ'] = {'phase': 'pending', 'state': 'none', 'role': 'lead', 'waits_for': ['K01']}
        html = self.task_list(d)
        summary = html[html.find('</h3>') + 5:html.find('<ol>')]
        for wanted in ('sdk-trial', '4/35 phần xong, cổng đạt', '2 đang làm', '1 bị giữ', '34 @review, 1 @lead'):
            self.assertIn(wanted, summary)
        bare = self.page_data()
        for n in bare['nodes'].values(): n.pop('role')
        self.assertNotIn('@', self.task_list(bare).split('<ol>')[0])        # no role at all: no role count

    def test_page_row_shows_full_goal_on_open(self):
        d = self.page_data()
        d['node_goals']['FE'] = LONG_GOAL
        rows = self.task_list(d).split('<li')[1:]
        self.assertEqual(len(rows), 4)
        for row in rows: self.assertIn('<details', row, 'a row does not open')
        fe = rows[2]
        self.assertIn(LONG_GOAL, fe)                                          # the whole instruction, not cut
        self.assertLess(fe.index('</summary>'), fe.index(LONG_GOAL))         # hidden until the row is opened
        self.assertLess(fe.index('FE làm giao diện'), fe.index('</summary>'))  # the short name is what the closed row shows
        self.assertIn('&lt;các điểm cuối&gt; &amp; mã lỗi', rows[0])          # escaped
        self.assertNotIn('<các', rows[0])

    def test_role_label_under_each_row_kept(self):
        d = self.page_data()
        html = self.task_list(d)
        rows = html.split('<li')[1:]
        self.assertEqual(len(rows), 4)
        for row, (nid, role) in zip(rows, [('BE1', 'backend'), ('BE2', 'backend'), ('FE', 'frontend'), ('LEAD', 'lead')]):
            self.assertIn('<code class="tl-role">@' + role + '</code>', row)
            self.assertLess(row.index(d['node_titles'][nid]), row.index('@' + role))     # the label under the name
        self.assertEqual(html.count('class="tl-role"'), 4)
        self.assertEqual(html.count('xong · cổng đạt'), 2)                   # the status words of the rows as NHANVAI shows them

    # ---- rev 3 (I3, D10): a machine goal head is named from the work ------------------------------------------------------------------
    def names_or_fail(self, nodes):
        names = getattr(tracking, 'node_names', None)
        if names is None: self.fail('the tracking detail has no naming of sub-tasks from their work (node_names)')
        return names(nodes)

    def review(self, nid, reads, writes, goal=None, **extra):
        """A review sub-task as the real 35-node plan has them: a machine goal head, its own files to read, one report to write."""
        return dict({'id': nid, 'goal': goal or f'Cụm {nid[1:]} review vn-sign-sdk @bef6476 (node độc lập): đọc các tệp, ghi phát hiện',
                     'read': list(reads), 'write': list(writes)}, **extra)

    def test_name_from_work_for_machine_goal(self):
        shared = 'docs/huong-dan.md'                                          # every sub-task reads it: not its own
        nodes = [self.review('K01', [shared, 'src/Signature.Api/a.cs'], ['reviews/K01.md']),
                 self.review('K02', [shared, 'src/Signature.Domain/A1.cs', 'src/Signature.Domain/A2.cs', 'src/Signature.Domain/sub/A3.cs'], ['reviews/K02.md']),
                 self.review('K03', [shared, 'src/Signature.Infra/b.cs'], ['reviews/K03.md'], goal='Rà 1a2b3c4 phần hạ tầng'),
                 self.review('K04', [shared, 'src/Signature.Web/c.cs', 'src/Signature.Web/d.cs'], ['reviews/K04.md'],
                             goal='Rà toàn bộ phần web của bộ ký số theo danh sách lỗi đã biết'),
                 self.review('K05', [shared, 'src/Signature.Cli/e.cs'], ['reviews/K05.md'], title='Rà dòng lệnh ký số'),
                 {'id': 'KZ', 'goal': 'Tích hợp', 'read': [shared, 'reviews/'], 'write': ['reviews/README.md']}]
        names = self.names_or_fail(nodes)
        self.assertEqual(names['K02'], 'Signature.Domain — 3 tệp → K02.md')          # "@": named from its work
        self.assertEqual(names['K01'], 'Signature.Api — 1 tệp → K01.md')
        self.assertEqual(names['K03'], 'Signature.Infra — 1 tệp → K03.md')           # a commit id (7-40 hex) is machine text
        self.assertEqual(names['K04'], 'Signature.Web — 2 tệp → K04.md')             # longer than 40 characters is machine text
        self.assertEqual(names['K05'], 'Rà dòng lệnh ký số')                          # a title always wins
        self.assertEqual(names['KZ'], 'Tích hợp')                                     # a short head that is not machine text stays
        self.assertNotIn('@', ' '.join(names.values()))

    def test_name_from_work_ignores_shared_reads(self):
        nodes = [self.review('K01', ['docs/chung.md', 'src/Core/a.cs', 'src/Core/b.cs'], ['reviews/K01.md']),
                 self.review('K02', ['docs/chung.md', 'src/Core/c.cs'], ['reviews/K02.md']),
                 self.review('K03', ['src/Core/a.cs'], ['reviews/K03.md']),
                 self.review('K04', ['notes/rieng.md'], ['reviews/K04.md'])]
        names = self.names_or_fail(nodes)
        # docs/chung.md is read by 2 of 4 (not fewer than half): shared, so it neither counts nor pulls the folder up to the repository root;
        # src/Core/a.cs is read by 2 of 4 as well
        self.assertEqual(names['K01'], 'Core — 1 tệp → K01.md')
        self.assertEqual(names['K02'], 'Core — 1 tệp → K02.md')
        self.assertEqual(names['K03'], 'reviews → K03.md')                            # nothing of its own read: the folder of what it writes
        self.assertEqual(names['K04'], 'notes — 1 tệp → K04.md')

    def test_name_from_work_falls_back_to_goal_head(self):
        head = 'Cụm 3 review vn-sign-sdk @bef6476 (node độc lập)'
        long = 'Cụm 4 rà soát toàn bộ mã nguồn bộ ký số vn-sign-sdk ở commit bef6476 theo danh sách kiểm tra số 7 của nhóm'
        nodes = [self.review('K03', [], [], goal=head + ': đọc các tệp'), self.review('K04', [], [], goal=long + ': rồi ghi'),
                 self.review('K05', ['a.txt'], [], goal=head + ': x'), self.review('K06', ['a.txt'], [], goal=head + ': y')]
        names = self.names_or_fail(nodes)
        self.assertEqual(names['K03'], head)                                          # reads nothing, writes nothing: the goal head
        self.assertLessEqual(len(names['K04']), 70)                                  # at most 70, "…" included
        self.assertGreater(len(names['K04']), 60)
        self.assertTrue(names['K04'].endswith('…') and long.startswith(names['K04'][:-1].rstrip()), names['K04'])
        self.assertEqual((names['K05'], names['K06']), (head, head))                  # only shared reads and no write: the goal head too

    # ---- rev 3 (I7): the "Phần việc" table ---------------------------------------------------------------------------------------------
    def test_part_table_uses_short_names(self):
        import re
        d = self.page_data()
        d['node_goals']['FE'] = LONG_GOAL
        d['work'] = {'nodes': {nid: {'title': goal} for nid, goal in d['node_goals'].items()}}      # tracking_work's view: the whole goal
        html = self.js("legacyNodes(d)", '\nvar d=' + json.dumps(d) + ';')
        self.assertIn('<h3>Phần việc</h3>', html)
        table = html[html.index('<h3>Phần việc</h3>'):]
        rows = table.split('<tbody>', 1)[-1].split('<tr')[1:]
        self.assertEqual(len(rows), 4)
        for row, nid in zip(rows, ['BE1', 'BE2', 'FE', 'LEAD']):
            self.assertIn('</summary>', row, nid + ': the row does not open on the whole goal')
            shown = re.sub(r'\s[a-z-]+="[^"]*"', '', row.split('</summary>', 1)[0])       # what the closed row shows (attributes aside)
            self.assertIn(d['node_titles'][nid], shown, nid)                              # the same short name as the Danh sách task block
            self.assertNotIn(d['node_goals'][nid].split(':')[0] + ':', shown, nid)
        fe = rows[2]
        self.assertNotIn(LONG_GOAL, re.sub(r'\s[a-z-]+="[^"]*"', '', fe.split('</summary>', 1)[0]))
        self.assertIn(LONG_GOAL, fe.split('</summary>', 1)[1])                         # the whole goal when the row is opened
        self.assertRegex(PAGE, r'td\.pv-name\{white-space:normal')                    # a long name wraps in this table instead of widening the page
