"""UI33 mockup: the task-first tracking page (docs/mockups/ui33/index.html) run under Node with a tiny stub; no browser, stdlib only."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parents[1] / 'docs' / 'mockups' / 'ui33' / 'index.html'
NODE_FALLBACK = r'C:\Program Files\nodejs\node.exe'
OWNER_FILTERS = ('all', 'need', 'doing', 'check', 'done')


def node():
    return shutil.which('node') or NODE_FALLBACK


def html():
    return HTML_PATH.read_text(encoding='utf8')


def script_and_data():
    text = html()
    data = re.search(r'<script id="sample-data" type="application/json">(.*?)</script>', text, re.S).group(1)
    script = re.search(r'<script>(.*?)</script>', text, re.S).group(1)
    return script, data


def run(expr):
    """Evaluate `expr` after the page script and the sample data (`DATA`); the value as JSON. Fails (never skips) without Node."""
    script, data = script_and_data()
    program = script + '\nvar DATA=' + data + ';\nconsole.log(JSON.stringify(' + expr + '));'
    result = subprocess.run([node(), '-'], input=program, text=True, encoding='utf8', capture_output=True, timeout=60)
    if result.returncode:
        raise AssertionError('node failed: ' + result.stderr[-2000:])
    return json.loads(result.stdout.strip().splitlines()[-1])


def case(name):
    return next(t for t in run('DATA.tasks') if t.get('case') == name)


def without_details(markup):
    return re.sub(r'<details[\s\S]*?</details>', '', markup)


def text_of(markup):
    return re.sub(r'<[^>]+>', ' ', markup)


class Ui33Mockup(unittest.TestCase):
    def test_sample_data_labeled(self):
        data = run('DATA')
        self.assertIs(data['sample'], True)
        label = 'Dữ liệu mẫu — không phải sổ thật'
        self.assertIn(label, html().split('<script')[0])  # the header, present on every screen
        self.assertIn(label, run('renderList(DATA,"all")'))
        self.assertIn(label, run('renderTask(DATA.tasks[0])'))
        self.assertEqual(run('typeof document'), 'undefined')  # Node loads the script without touching the DOM
        self.assertEqual(run('(function(){return typeof ui33Wire})()'), 'function')
        text = html()
        self.assertNotRegex(text, r'(src|href)="https?://')  # self-contained

    def test_four_sample_cases(self):
        tasks = run('DATA.tasks')
        cases = [t['case'] for t in tasks if t.get('case')]
        self.assertEqual(sorted(cases), ['owner_decision', 'pass_then_edit', 'real_fail', 'timeout'])
        self.assertGreaterEqual(len(tasks), 12)
        self.assertGreaterEqual(len({t['project'] for t in tasks}), 2)
        self.assertGreaterEqual(len([t for t in tasks if not t.get('case')]), 8)
        pe = case('pass_then_edit')
        self.assertEqual(pe['validity']['state'], 'recheck')
        self.assertIn('không còn được tính vì mã đã đổi', pe['validity']['reason'])
        self.assertIn('chạy lại bộ kiểm', pe['next'].lower())
        # never counted as passed: not in the done filter, not in the Xong count
        self.assertNotIn(pe['id'], [t['id'] for t in run('filterTasks(DATA.tasks,"done")')])
        done = run('countTasks(DATA.tasks).done')
        self.assertEqual(done, len([t for t in tasks if t['group'] == 'done']))
        self.assertTrue(all(t['validity']['state'] == 'valid' for t in tasks if t['group'] == 'done'))
        to = case('timeout')
        self.assertIn('Chưa kết luận', run('statusLine(%s)' % json.dumps(to)))
        self.assertNotIn('không đạt', run('statusLine(%s)' % json.dumps(to)).lower())
        rf = case('real_fail')
        self.assertEqual(run('statusLine(%s)' % json.dumps(rf)).split(':')[0], 'Kiểm không đạt')
        self.assertEqual(rf['repairs'], {'used': 3, 'left': 0, 'total': 3})     # the next check is its last try (verdict.stop_reason)
        self.assertTrue(case('owner_decision')['owner_needed'])
        states = {t['validity']['state'] for t in tasks}
        self.assertIn('valid', states)
        self.assertTrue(any(t['validity']['reason'].startswith('Chưa biết:') for t in tasks))

    def test_owner_first(self):
        tasks = run('DATA.tasks')
        owner_ids = [t['id'] for t in tasks if t['owner_needed']]
        self.assertTrue(owner_ids)
        ordered = run('orderTasks(DATA.tasks)')
        flags = [t['owner_needed'] for t in ordered]
        self.assertEqual(flags, sorted(flags, reverse=True))
        self.assertEqual(len(ordered), len(tasks))
        for filt in OWNER_FILTERS:
            got = run('filterTasks(DATA.tasks,%s)' % json.dumps(filt))
            flags = [t['owner_needed'] for t in got]
            self.assertEqual(flags, sorted(flags, reverse=True), filt)
        need = run('filterTasks(DATA.tasks,"need")')
        self.assertEqual([t['id'] for t in need], owner_ids)
        # an owner-needing task sitting in a later position of the source still comes first
        shuffled = run('orderTasks(DATA.tasks.slice().reverse())')
        self.assertTrue(shuffled[0]['owner_needed'])
        listing = run('renderList(DATA,"all")')
        self.assertLess(listing.index('Cần bạn'), listing.index('class="tname"'))
        owner_part = listing.split('Các việc còn lại')[0]
        for t in tasks:
            self.assertEqual('data-id="%s"' % t['id'] in owner_part, t['owner_needed'], t['id'])
        counts = run('countTasks(DATA.tasks)')
        self.assertEqual(counts['all'], len(tasks))
        self.assertEqual(counts['need'], len(owner_ids))
        for filt, label in (('need', 'Cần bạn'), ('doing', 'Đang làm'), ('check', 'Chờ kiểm'), ('done', 'Xong'), ('all', 'Tất cả')):
            self.assertIn('%s (%d)' % (label, counts[filt]), listing)

    def test_one_status_line(self):
        listing = run('renderList(DATA,"all")')
        rows = listing.split('<a class="task')[1:]
        self.assertEqual(len(rows), len(run('DATA.tasks')))
        for row in rows:
            self.assertEqual(row.count('class="sline'), 1)
        for t in run('DATA.tasks'):
            line = run('statusLine(%s)' % json.dumps(t))
            self.assertNotIn('\n', line)
            self.assertTrue(line.strip())
        lines = {t['case']: run('statusLine(%s)' % json.dumps(t)) for t in run('DATA.tasks') if t.get('case')}
        self.assertEqual(lines['owner_decision'], 'Cần bạn quyết: hết lượt sửa, chờ bạn quyết')
        self.assertEqual(lines['pass_then_edit'], 'Cần kiểm lại: mã đổi sau lần kiểm')
        self.assertEqual(lines['timeout'], 'Chưa kết luận: bộ kiểm hết giờ')
        self.assertNotIn('không đạt', lines['timeout'].lower())
        # project name only when the visible list holds more than one project
        self.assertTrue(run('needsProject(DATA.tasks)'))
        self.assertIn('class="proj"', listing)
        one = run('(function(){var t=DATA.tasks.filter(function(x){return x.project===DATA.projects[0]});'
                  'return {need:needsProject(t),html:renderList({tasks:t},"all")}})()')
        self.assertFalse(one['need'])
        self.assertNotIn('class="proj"', one['html'])
        # user words only on the list
        self.assertNotRegex(listing, r'\b(M\d+|verdict|receipt|rev\d*)\b')

    def test_task_page_fields(self):
        for t in run('DATA.tasks'):
            page = run('renderTask(%s)' % json.dumps(t))
            main = without_details(page)
            order = [page.index(x) for x in ('<h2>', 'Đầu ra mới nhất', 'Kết quả còn tin được không', 'Bước tiếp theo')]
            self.assertEqual(order, sorted(order), t['id'])
            self.assertIn('>Mở<', page)
            self.assertIn('Ai làm: ' + t['who'], page)
            self.assertIn(t['who'], ('Bạn', 'AI', 'Bộ kiểm', 'Chưa biết'))
            self.assertIn(run('VALID_LABEL')[t['validity']['state']], page)
            self.assertIn(t['validity']['reason'], text_of(page))
            self.assertNotRegex(main, r'\b(M\d+|verdict|receipt|rev\d*)\b', t['id'])
        pe = run('renderTask(%s)' % json.dumps(case('pass_then_edit')))
        self.assertIn('Cần kiểm lại', pe)
        self.assertIn('không còn được tính', pe)
        self.assertIn('Chạy lại bộ kiểm', pe)
        to = run('renderTask(%s)' % json.dumps(case('timeout')))
        self.assertIn('Chưa kết luận', to)
        self.assertIn('hết giờ sau 20 phút', to)
        self.assertIn('Kiểm môi trường', to)
        unknown = [t for t in run('DATA.tasks') if t['validity']['reason'].startswith('Chưa biết:')]
        self.assertIn('Chưa biết: ', run('renderTask(%s)' % json.dumps(unknown[0])))
        valid = next(t for t in run('DATA.tasks') if t['validity']['state'] == 'valid')
        self.assertIn('Còn đúng với bản hiện tại', run('renderTask(%s)' % json.dumps(valid)))

    def test_decision_and_consequences(self):
        od = case('owner_decision')
        page = run('renderTask(%s)' % json.dumps(od))
        self.assertIn('class="decision"', page)
        options = od['decision']['options']
        self.assertTrue(2 <= len(options) <= 3)
        block = page[page.index('class="decision"'):]
        block = block[:block.index('</section>')]
        self.assertEqual(block.count('<button'), len(options))
        self.assertEqual(block.count('Hệ quả:'), len(options))
        for option in options:
            self.assertTrue(option['label'].strip() and option['consequence'].strip())
            self.assertGreaterEqual(len(option['label'].split()), 6)  # a full sentence, not a bare verb
            self.assertIn(option['consequence'], block)
        self.assertIn('Duyệt bản sửa kế hoạch: AI làm tiếp theo phạm vi mới', block)
        self.assertIn('thêm khoảng 1 ngày', block)
        self.assertIn('Kết thúc việc: giữ kết quả hiện có, không làm tiếp', block)
        self.assertIn('data-toast', block)
        self.assertIn('Mockup: chưa ghi gì', html())
        # the last-repair warning is a warning, not a decision, and not in the owner group
        rf = case('real_fail')
        rpage = run('renderTask(%s)' % json.dumps(rf))
        self.assertIn('nếu lần kiểm tới vẫn không đạt, việc sẽ dừng và chờ bạn quyết. Đây là cảnh báo, bạn chưa cần làm gì.', rpage)
        self.assertIn('class="warn"', rpage)
        self.assertNotIn('class="decision"', rpage)
        self.assertIn('đã dùng 3/3, lần kiểm tới là lần thử cuối', rpage)
        self.assertFalse(rf['owner_needed'])
        listing = run('renderList(DATA,"all")')
        owner_part = listing.split('Các việc còn lại')[0]
        self.assertNotIn('data-id="%s"' % rf['id'], owner_part)
        self.assertNotIn('Đây là cảnh báo', listing)
        self.assertEqual(run('lastRepairWarning(%s)' % json.dumps(case('owner_decision'))), '')     # a stopped task asks a decision instead
        # the warning appears only on the last repair
        self.assertNotIn('class="warn"', page)
        self.assertEqual(run('lastRepairWarning({repairs:{used:1,left:2,total:3},validity:{state:"fail"}})'), '')

    def test_plan_change_before_after(self):
        od = case('owner_decision')
        fields = od['detail']['plan']['fields']
        panel = run('renderDetail(%s,"plan")' % json.dumps(od))
        self.assertIn('class="before"', panel)
        self.assertIn('class="after"', panel)
        before, after = panel.split('class="after"')
        for f in fields:
            self.assertIn(f['before'], before)
            self.assertIn('<span class="av">%s</span>' % f['after'], after)
            self.assertIn('<span class="bv">%s</span>' % f['before'], before)
            self.assertNotIn('class="av"', before)
        self.assertGreaterEqual(len(fields), 2)
        # closed by default, opened by a click on its own summary
        page = run('renderTask(%s)' % json.dumps(od))
        detail = re.search(r'<details class="d" data-kind="plan"([^>]*)>', page)
        self.assertIsNotNone(detail)
        self.assertNotIn('open', detail.group(1))
        # side by side on wide, stacked below 900px
        css = html()
        self.assertRegex(css, r'\.ba\{display:grid;grid-template-columns:minmax\(0,1fr\) minmax\(0,1fr\)')
        mobile = re.search(r'@media \(max-width:899px\)\{(.*?)\n\}', css, re.S).group(1)
        self.assertRegex(mobile, r'\.ba\{grid-template-columns:minmax\(0,1fr\)\}')
        self.assertIn('Chưa có dữ liệu', run('renderDetail(DATA.tasks[6],"plan")'))

    def test_finding_repair_recheck(self):
        rf = case('real_fail')
        panel = run('renderDetail(%s,"error")' % json.dumps(rf))
        self.assertIn('Đã dùng 3/3 lượt sửa', panel)
        steps = re.findall(r'<li>(.*?)</li>', panel)
        self.assertEqual(len(steps), len(rf['detail']['error']['loop']))
        joined = ' '.join(steps)
        order = [joined.index(x) for x in ('Lần kiểm 1 không đạt', 'Sửa (lượt 1)', 'Lần kiểm 2 không đạt', 'Sửa (lượt 2)', 'Lần kiểm 3 không đạt', 'lần thử cuối')]
        self.assertEqual(order, sorted(order))
        for step in rf['detail']['error']['loop']:
            self.assertIn(step['t'], panel)  # every step carries its time
        od = case('owner_decision')
        self.assertIn('Đã dùng 3/3 lượt sửa, còn 0', run('renderDetail(%s,"error")' % json.dumps(od)))
        page = run('renderTask(%s)' % json.dumps(rf))
        self.assertRegex(page, r'<details class="d" data-kind="error">')
        self.assertIn('hết lượt', run('renderTask(%s)' % json.dumps(od)))

    def test_wait_opens_timeline(self):
        od = case('owner_decision')
        panel = run('renderDetail(%s,"wait")' % json.dumps(od))
        for entry in od['detail']['wait']['timeline']:
            for key in ('who', 'waiting_for', 'since', 'how_long'):
                self.assertIn(entry[key], panel)
        self.assertEqual(panel.count('<li>'), len(od['detail']['wait']['timeline']))
        page = run('renderTask(%s)' % json.dumps(od))
        match = re.search(r'<details class="d" data-kind="wait"([^>]*)><summary>([^<]*)</summary>', page)
        self.assertIsNotNone(match)
        self.assertNotIn('open', match.group(1))
        self.assertIn('ai đang chờ ai', match.group(2).lower())
        to = case('timeout')
        self.assertIn('20 phút', run('renderDetail(%s,"wait")' % json.dumps(to)))

    def test_result_opens_evidence(self):
        rf = case('real_fail')
        ev = rf['detail']['result']
        panel = run('renderDetail(%s,"result")' % json.dumps(rf))
        self.assertIn(ev['command'], panel)
        self.assertIn('mã: 1', panel)
        self.assertIn('AssertionError', panel)
        self.assertIn(ev['file'], panel)
        self.assertIn(ev['hash'], panel)
        # technical identifiers live only inside the opened panel
        page = run('renderTask(%s)' % json.dumps(rf))
        main = without_details(page)
        self.assertNotIn(ev['hash'], main)
        self.assertNotIn(ev['command'], main)
        self.assertRegex(page, r'<details class="d" data-kind="result">')
        # the output panel behind "Mở" is closed by default too
        self.assertRegex(page, r'<details class="d out"><summary>Mở</summary>')
        # nothing is escaped away: a hostile log line cannot inject markup
        hostile = run('renderDetail({detail:{result:{command:"<b>x</b>",exit:0,log:"<script>1</script>",file:"f",hash:"h"}}},"result")')
        self.assertNotIn('<script>', hostile)
        self.assertNotIn('<b>x</b>', hostile)

    def test_back_keeps_filter_and_position(self):
        # plain hash names only (the artifact viewer passes #name, never #/path or a query): #viec, #viec-<filter>, #viec-<filter>-<task>
        self.assertEqual(run('routeOf("#viec-need")'), {'view': 'list', 'id': None, 'filter': 'need'})
        self.assertEqual(run('routeOf("#viec-all-t04")'), {'view': 'task', 'id': 't04', 'filter': 'all'})
        self.assertEqual(run('routeOf("#viec-done-t04")'), {'view': 'task', 'id': 't04', 'filter': 'done'})
        self.assertEqual(run('routeOf("")')['view'], 'list')
        self.assertEqual(run('routeOf("#viec-bogus")')['filter'], 'all')
        self.assertEqual(run('routeOf(hrefOf({view:"task",id:"t03",filter:"doing"}))'), {'view': 'task', 'id': 't03', 'filter': 'doing'})
        self.assertEqual(run('hrefOf({view:"list",filter:"need"})'), '#viec-need')
        self.assertRegex(run('hrefOf({view:"task",id:"t03",filter:"doing"})'), r'^#[A-Za-z0-9-]+$')
        # a row opened from a filter links back to that same filter
        listing = run('renderList(DATA,"check")')
        self.assertIn('href="#viec-check-t01"', listing)
        self.assertIn('data-filter="check"', listing)
        self.assertRegex(listing, r'data-filter="check" aria-current="true"')
        # save list state, leave, come back: same filter and scrollTop; each filter keeps its own
        got = run('(function(){var m={};var store={getItem:function(k){return k in m?m[k]:null},setItem:function(k,v){m[k]=v}};'
                  'saveListState(store,"need",0);saveListState(store,"check",734);saveListState(store,"all",120.4);'
                  'return {a:loadListState(store,"check"),b:loadListState(store,"all"),c:loadListState(store,"need"),d:loadListState(store,"done"),k:listStateKey("check")}})()')
        self.assertEqual(got['a'], {'filter': 'check', 'scrollTop': 734})
        self.assertEqual(got['b'], {'filter': 'all', 'scrollTop': 120})
        self.assertEqual(got['c'], {'filter': 'need', 'scrollTop': 0})
        self.assertEqual(got['d'], {'filter': 'done', 'scrollTop': 0})
        self.assertNotEqual(run('listStateKey("check")'), run('listStateKey("need")'))
        # the wiring does restore the saved position after a render and keeps a back path
        text = html()
        self.assertIn('lp.scrollTop=top', text)
        self.assertIn('history.back()', text)
        self.assertIn('‹ Quay lại', text)
        self.assertIn("addEventListener('hashchange',render)", text)
        broken = run('(function(){var s={getItem:function(){throw 1},setItem:function(){throw 1}};saveListState(s,"all",5);return loadListState(s,"all")})()')
        self.assertEqual(broken, {'filter': 'all', 'scrollTop': 0})

    def test_mobile_layout(self):
        text = html()
        self.assertRegex(text, r'<meta name="viewport" content="width=device-width, initial-scale=1">')
        css = re.search(r'<style>(.*?)</style>', text, re.S).group(1)
        media = re.search(r'@media \(max-width:899px\)\{(.*?)\n\}', css, re.S)
        self.assertIsNotNone(media)
        body = media.group(1)
        self.assertRegex(body, r'body\.view-task #listpane\{display:none\}')
        self.assertRegex(body, r'body\.view-list #taskpane\{display:none\}')
        self.assertRegex(body, r'#back\{display:inline-block\}')
        self.assertRegex(css, r'#back\{display:none[;}]')  # hidden on wide screens
        self.assertRegex(css, r'main\{[^}]*grid-template-columns:minmax\(0,380px\) minmax\(0,1fr\)')  # side by side on wide
        # 16px side gutters and wrapping of long text
        self.assertRegex(css, r'\.pane\{[^}]*padding:12px 16px')
        self.assertRegex(css, r'header\{padding:8px 16px')
        self.assertIn('overflow-wrap:anywhere', css)
        # no fixed width above 375px on any container
        for match in re.finditer(r'(?<![\w-])(?:min-)?width:\s*(\d+)px', css):
            self.assertLessEqual(int(match.group(1)), 375, match.group(0))
        self.assertNotRegex(css, r'(?<![\w-])(?:min-)?width:\s*\d+(?:vw|em|rem)')
        # the wide split breakpoint is the same 900px the existing page uses, and the page body does not scroll sideways
        self.assertNotIn('overflow-x:scroll', css)
        self.assertIn('min-width:0', css)


if __name__ == '__main__':
    unittest.main()
