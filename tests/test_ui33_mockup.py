"""UI33/UI58 mockup: the task-first tracking page (docs/mockups/ui33/index.html), run under Node with no DOM; stdlib only.

The page's render functions take data in the shape of the real tracking model (tracking.overview items + tracking.detail of the same root +
host_work + shared_resources), so the same code draws the synthetic sample committed here and a real export built outside the repo. These
tests read only this file and the page; they fail (never skip) without Node.
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parents[1] / 'docs' / 'mockups' / 'ui33' / 'index.html'
NODE_FALLBACK = r'C:\Program Files\nodejs\node.exe'
FILTERS = ('all', 'need', 'doing', 'check', 'done')
KINDS = ['scope', 'checks', 'repair', 'plan', 'wait', 'evidence', 'agents', 'res', 'tech']
SAMPLE_LABEL = 'Dữ liệu mẫu — không phải sổ thật'
INTERNAL = r'\b(M\d+|verdict|receipt|rev\d*|plan-ns)\b'


def node():
    found = shutil.which('node') or (NODE_FALLBACK if Path(NODE_FALLBACK).is_file() else None)
    if not found:
        raise AssertionError('Node.js is required for this test (not found on PATH or at %s)' % NODE_FALLBACK)
    return found


def html():
    return HTML_PATH.read_text(encoding='utf8')


def script_and_data():
    text = html()
    data = re.search(r'<script id="page-data" type="application/json">(.*?)</script>', text, re.S).group(1)
    script = re.search(r'<script>(.*?)</script>', text, re.S).group(1)
    return script, data


def run(expr, data=None):
    """Evaluate `expr` after the page script with `DATA` = the embedded sample (or `data`); the value as JSON."""
    script, sample = script_and_data()
    program = script + '\nvar DATA=' + (sample if data is None else json.dumps(data)) + ';\nconsole.log(JSON.stringify(' + expr + '));'
    result = subprocess.run([node(), '-'], input=program, text=True, encoding='utf8', capture_output=True, timeout=60)
    if result.returncode:
        raise AssertionError('node failed: ' + result.stderr[-2000:])
    return json.loads(result.stdout.strip().splitlines()[-1])


def tasks():
    return run('itemsOf(DATA)')


def case(name):
    return next(t for t in tasks() if t.get('case') == name)


def page(name):
    return run('renderTask(DATA,findTask(DATA,%s))' % json.dumps(case(name)['id']))


def panel(name, kind):
    return run('renderDetail(DATA,findTask(DATA,%s),%s)' % (json.dumps(case(name)['id']), json.dumps(kind)))


def without_details(markup):
    return re.sub(r'<details[\s\S]*?</details>', '', markup)


def text_of(markup):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', markup)).strip()


def block(markup, start, end='</section>'):
    part = markup[markup.index(start):]
    return part[:part.index(end) + len(end)]


class Ui33Mockup(unittest.TestCase):
    def test_sample_data_labeled(self):
        data = run('DATA')
        self.assertIs(data['sample'], True)
        self.assertEqual(data['label'], SAMPLE_LABEL)
        head = html().split('<script')[0]
        self.assertEqual(head.count(SAMPLE_LABEL), 1)                       # the header badge, on every screen; the build swaps exactly this one
        self.assertIn('id="srcbadge"', head)
        self.assertEqual(html().count('<script id="page-data" type="application/json">'), 1)
        self.assertEqual(run('typeof document'), 'undefined')               # Node loads the script without touching a DOM
        self.assertEqual(run('typeof wire'), 'function')
        self.assertNotRegex(html(), r'(src|href)="https?://')               # self-contained
        # the sample is synthetic: no real ledger ids, machine paths or real plan names (the repo is public)
        _, raw = script_and_data()
        for leak in ('TASK-', 'TamNT', 'OneCrewRuns', 'state-v2-real', 'D:\\\\', 'onecrew-development', 'wf-dev30'):
            self.assertNotIn(leak, raw, leak)
        # the same page shows a real export under its own label
        real = dict(data, sample=False, label='Dữ liệu thật của sổ phát triển — đọc lúc 19/11/2026 10:00')
        od = case('owner_decision')['id']
        self.assertNotIn('Lệnh mẫu chỉ để minh họa', run('renderTask(DATA,findTask(DATA,%s))' % json.dumps(od), real))
        self.assertIn('Lệnh mẫu chỉ để minh họa', run('renderTask(DATA,findTask(DATA,%s))' % json.dumps(od)))
        self.assertIn("if(!D.sample)badge.classList.add('real')", html())

    def test_four_sample_cases(self):
        all_tasks = tasks()
        cases = {t.get('case') for t in all_tasks}
        self.assertLessEqual({'pass_then_edit', 'timeout', 'real_fail', 'owner_decision', 'engine_parts', 'plain_between_checks'}, cases)
        self.assertGreaterEqual(len({t['project'] for t in all_tasks}), 2)
        # a pass followed by an edit: "Cần kiểm lại", not counted, not in Xong
        pe = case('pass_then_edit')
        self.assertEqual(run('statusLine(%s)' % json.dumps(pe)), 'Cần kiểm lại')
        self.assertNotEqual(run('groupOf(%s)' % json.dumps(pe)), 'done')
        self.assertNotIn(pe['id'], [t['id'] for t in run('filterTasks(itemsOf(DATA),"done")')])
        self.assertEqual(run('msTally(findTask(DATA,%s)).passed' % json.dumps(pe['id'])), 0)
        pp = page('pass_then_edit')
        self.assertIn('data-validity="recheck"', pp)
        self.assertIn('<i class="b-wait"', block(pp, 'id="b-out"'))
        self.assertNotIn('<i class="b-ok"', block(pp, 'id="b-out"'))
        # a timeout: "Chưa kết luận", never "không đạt"
        to = case('timeout')
        self.assertEqual(run('statusLine(%s)' % json.dumps(to)), 'Chưa kết luận')
        tp = page('timeout')
        for part in (block(tp, 'id="b-trust"'), block(tp, 'id="b-next"'), run('renderList(DATA,"all")')):
            self.assertNotIn('không đạt', text_of(part).lower().replace('chưa kết luận', ''))
        self.assertIn('Kiểm môi trường chạy', tp)
        # a real failure: "Cần sửa", its error line, repairs, and it is not an owner decision
        rf = case('real_fail')
        self.assertEqual(run('statusLine(%s)' % json.dumps(rf)), 'Cần sửa')
        self.assertFalse(run('ownerNeeded(%s)' % json.dumps(rf)))
        self.assertEqual(rf['situation']['repairs']['left'], 0)
        self.assertIn('AssertionError', page('real_fail'))
        # the owner's decision
        od = case('owner_decision')
        self.assertTrue(run('ownerNeeded(%s)' % json.dumps(od)))
        self.assertEqual(run('statusLine(%s)' % json.dumps(od)), 'Cần bạn quyết')
        # everything in Xong is still trusted
        for t in run('filterTasks(itemsOf(DATA),"done")'):
            self.assertIn(t['validity']['kind'], ('accepted', 'valid'))

    def test_owner_first(self):
        all_tasks = tasks()
        owner_ids = [t['id'] for t in all_tasks if run('ownerNeeded(%s)' % json.dumps(t))]
        self.assertGreaterEqual(len(owner_ids), 2)
        for expr in ('orderTasks(itemsOf(DATA))', 'orderTasks(itemsOf(DATA).slice().reverse())'):
            ordered = run(expr)
            flags = [t['id'] in owner_ids for t in ordered]
            self.assertEqual(flags, sorted(flags, reverse=True), expr)
            self.assertEqual(len(ordered), len(all_tasks))
        for filt in FILTERS:
            got = [t['id'] in owner_ids for t in run('filterTasks(itemsOf(DATA),%s)' % json.dumps(filt))]
            self.assertEqual(got, sorted(got, reverse=True), filt)
        self.assertEqual(sorted(t['id'] for t in run('filterTasks(itemsOf(DATA),"need")')), sorted(owner_ids))
        # newest first after the owner's tasks
        rest = [t for t in run('orderTasks(itemsOf(DATA))') if t['id'] not in owner_ids]
        stamps = [t['last_update']['at'] for t in rest]
        self.assertEqual(stamps, sorted(stamps, reverse=True))
        # the list: summary first, the owner's group before the others
        listing = run('renderList(DATA,"all")')
        self.assertLess(listing.index('việc cần bạn'), listing.index('class="filters"'))
        self.assertIn('<b>%d</b> việc cần bạn' % len(owner_ids), listing)
        owner_part = listing.split('Các việc khác')[0]
        for t in all_tasks:
            self.assertEqual('data-id="%s"' % t['id'] in owner_part, t['id'] in owner_ids, t['id'])
        counts = run('countTasks(itemsOf(DATA))')
        self.assertEqual(counts['all'], len(all_tasks))
        self.assertEqual(counts['need'], len(owner_ids))
        for filt, label in (('need', 'Cần bạn'), ('doing', 'Đang làm'), ('check', 'Chờ kiểm'), ('done', 'Xong'), ('all', 'Tất cả')):
            self.assertRegex(listing, r'data-filter="%s"[^>]*>%s <b>%d</b>' % (filt, label, counts[filt]))
        # the owner flag comes from the real fields only: situation.no_owner_decision or an owner-kind need
        self.assertTrue(run('ownerNeeded({situation:{no_owner_decision:false}})'))
        self.assertTrue(run('ownerNeeded({needs_user:[{kind:"approve"}]})'))
        self.assertFalse(run('ownerNeeded({needs_user:[{kind:"other"}],situation:{no_owner_decision:true}})'))
        self.assertFalse(run('ownerNeeded({})'))
        # nobody waiting on the owner: the summary says so instead of hiding
        calm = run('(function(){var d=JSON.parse(JSON.stringify(DATA));itemsOf(d).forEach(function(t){t.needs_user=[];t.situation.no_owner_decision=true});return renderList(d,"all")})()')
        self.assertIn('Không có việc nào cần bạn', calm)
        self.assertNotIn('Các việc khác', calm)

    def test_one_status_line(self):
        listing = run('renderList(DATA,"all")')
        rows = re.findall(r'<a class="row"[\s\S]*?</a>', listing)
        self.assertEqual(len(rows), len(tasks()))
        for row, t in zip(rows, run('filterTasks(itemsOf(DATA),"all")')):
            self.assertEqual(row.count('class="sline"'), 1)
            self.assertEqual(row.count('class="chip'), 1)
            self.assertEqual(row.count('class="mk '), 1)                     # a shape, not a sentence
            for tag in ('<p', '<br', '<div', '<ul'):
                self.assertNotIn(tag, row)
            self.assertIn('>%s<' % run('statusLine(%s)' % json.dumps(t)), row)
            self.assertNotRegex(text_of(row), INTERNAL)
            self.assertNotIn(t['plan'], text_of(row))
            self.assertLessEqual(len(text_of(row).split()), 22, row)
        lines = {t['case']: run('statusLine(%s)' % json.dumps(t)) for t in tasks() if t.get('case')}
        self.assertEqual(lines['owner_decision'], 'Cần bạn quyết')
        self.assertEqual(lines['pass_then_edit'], 'Cần kiểm lại')
        self.assertEqual(lines['timeout'], 'Chưa kết luận')
        self.assertEqual(lines['real_fail'], 'Cần sửa')
        for t in tasks():
            line = run('statusLine(%s)' % json.dumps(t))
            self.assertTrue(line.strip())
            self.assertNotIn('\n', line)
        css = re.search(r'<style>(.*?)</style>', html(), re.S).group(1)
        self.assertRegex(css, r'\.tname\{[^}]*white-space:nowrap[^}]*text-overflow:ellipsis')
        # the project shows only as the row's hover title, and only when the list holds more than one project
        self.assertTrue(run('needsProject(itemsOf(DATA))'))
        self.assertIn('data-proj="phieu-kham"', listing)
        one = run('(function(){var d=JSON.parse(JSON.stringify(DATA));d.overview.projects=d.overview.projects.slice(0,1);return renderList(d,"all")})()')
        self.assertNotIn('data-proj=', one)

    def test_task_page_fields(self):
        for t in tasks():
            markup = run('renderTask(DATA,findTask(DATA,%s))' % json.dumps(t['id']))
            main = without_details(markup)
            order = [markup.index(x) for x in ('<h2>', 'id="b-out"><h3>Đầu ra</h3>', 'id="b-trust"><h3>Còn tin được không</h3>',
                                               'id="b-next"><h3>Bước tiếp theo</h3>', 'id="b-dec"><h3>Bạn cần quyết gì</h3>', 'class="more"')]
            self.assertEqual(order, sorted(order), t['id'])
            words = text_of(main)
            self.assertNotRegex(words, INTERNAL, t['id'])
            self.assertNotIn(t['selector'], words)
            # scanned, not read: short outside the owner's options, each option one sentence plus one consequence (Vietnamese syllables)
            self.assertLessEqual(len(text_of(re.sub(r'<ul class="opts">[\s\S]*?</ul>', '', main)).split()), 130, t['id'])
            for opt in re.findall(r'<li class="opt">([\s\S]*?)</li>', main):
                self.assertLessEqual(len(text_of(opt).split()), 40, t['id'])
            self.assertNotIn('<p class="one">' + '<p', main)
            v = run('validityOf(findTask(DATA,%s))' % json.dumps(t['id']))
            self.assertIn('data-validity="%s"' % v['kind'], main)
            self.assertIn(v['label'], block(main, 'id="b-trust"'))
            who = run('whoOf(findTask(DATA,%s))' % json.dumps(t['id']))
            if who:
                self.assertIn(who, ('Bạn', 'AI', 'Bộ kiểm', 'Chưa rõ'))
                self.assertIn('Ai làm: <span class="chip', block(main, 'id="b-next"'))
                self.assertIn('>%s</span>' % who, block(main, 'id="b-next"'))
            # every deeper part is behind its own labelled disclosure, closed, never nested
            kinds = re.findall(r'<details class="d" data-kind="(\w+)"([^>]*)>', markup)
            self.assertEqual([k for k, _ in kinds], KINDS)
            self.assertTrue(all('open' not in rest for _, rest in kinds))
            depth = 0
            for tag in re.finditer(r'<(/?)details\b', markup):
                depth += -1 if tag.group(1) else 1
                self.assertLessEqual(depth, 1)
            self.assertEqual(depth, 0)
        # milestone ids become positions on the main surface
        self.assertEqual(run('human("Mốc M2 kiểm không đạt; mốc M1, M3 và M2 đạt",findTask(DATA,"t01"))'), 'Mốc 2 kiểm không đạt; mốc 1, 3 và 2 đạt')
        self.assertEqual(run('human("Mốc MX lạ",findTask(DATA,"t01"))'), 'Mốc MX lạ')
        self.assertEqual(run('human("Các mốc đã đạt (M1, M2) còn khớp",findTask(DATA,"t01"))'), 'Các mốc đã đạt (1, 2) còn khớp')
        rf = page('real_fail')
        self.assertIn('Từ chối thẻ hết hạn', run('renderDetail(DATA,findTask(DATA,"t02"),"checks")'))
        self.assertIn('Mốc 2 kiểm không đạt trên lần kiểm mới nhất', text_of(block(rf, 'id="b-trust"')))
        self.assertIn('1/2', block(rf, 'id="b-out"'))
        self.assertIn('Sửa và kiểm lại mốc 2', block(rf, 'id="b-next"'))
        done = run('renderTask(DATA,findTask(DATA,"t09"))')
        self.assertIn('Không còn bước nào', block(done, 'id="b-next"'))
        self.assertNotIn('Ai làm', block(done, 'id="b-next"'))

    def test_decision_and_consequences(self):
        od = case('owner_decision')
        markup = page('owner_decision')
        dec = block(markup, 'id="b-dec"')
        self.assertIn('class="blk need decision"', markup)
        options = od['needs_user'][0]['options']
        self.assertTrue(2 <= len(options) <= 3)
        self.assertEqual(dec.count('<li class="opt">'), len(options))
        self.assertEqual(dec.count('<button'), len(options))
        self.assertEqual(dec.count('Hệ quả: '), len(options))
        for option in options:
            self.assertGreaterEqual(len(option['label'].split()), 6)        # a full sentence, not a bare verb
            self.assertIn('<b>%s</b><span class="cons">Hệ quả: %s</span>' % (option['label'], option['consequence']), dec)
            self.assertIn('data-copy="%s"' % run('esc(%s)' % json.dumps(option['human_command'])), dec)
        self.assertIn('thêm khoảng 1 ngày', dec)
        # the question is the owner's words from the situation, not the verifier's English
        self.assertIn('Quyết định sau khi dừng: duyệt bản sửa để đi tiếp, hoặc kết thúc', dec)
        self.assertNotIn('Milestone M3 stopped', without_details(markup))
        self.assertIn('Sao chép chưa phải là duyệt', dec)
        # the last-try warning is a warning beside the next step, not a decision, not on the list
        rf = page('real_fail')
        self.assertNotIn('decision', block(rf, 'id="b-dec"'))
        self.assertIn('Không có gì', block(rf, 'id="b-dec"'))
        warn = block(rf, 'id="b-next"')
        self.assertIn('<p class="warn" role="note"', warn)
        self.assertIn('Lần kiểm tới là lần thử cuối. Chỉ là cảnh báo, bạn chưa cần làm gì.', warn)
        self.assertNotIn('thử cuối', run('renderList(DATA,"all")'))
        for name in ('timeout', 'owner_decision', 'pass_then_edit'):
            self.assertNotIn('class="warn"', page(name), name)
        # approve and accept: one command each; no command is said plainly, never a dead button
        for tid in ('t08', 't07'):
            self.assertEqual(block(run('renderTask(DATA,findTask(DATA,%s))' % json.dumps(tid)), 'id="b-dec"').count('data-copy="'), 1, tid)
        bare = run('(function(){var t=findTask(DATA,"t08");t.needs_user[0].human_command=null;return renderTask(DATA,t)})()')
        self.assertIn('Chưa có lệnh', block(bare, 'id="b-dec"'))
        self.assertNotIn('<button', block(bare, 'id="b-dec"'))

    def test_plan_change_before_after(self):
        od = case('owner_decision')
        diff = run('findTask(DATA,%s).work.changes[0].diff' % json.dumps(od['id']))
        self.assertGreaterEqual(len(diff), 2)
        markup = panel('owner_decision', 'plan')
        self.assertIn('Bản 2', markup)
        self.assertIn('đã duyệt', markup)
        pairs = re.findall(r'<div class="ba"><div class="before"><span class="bl">Trước</span><span class="bv">(.*?)</span></div>'
                           r'<div class="after"><span class="bl">Sau</span><span class="av">(.*?)</span></div></div>', markup)
        self.assertEqual(pairs, [(d['before'], d['after']) for d in diff])
        self.assertIn('Mục M3', markup)                                     # the changed field is named
        # closed by default, with its count on the summary
        self.assertRegex(page('owner_decision'), r'<details class="d" data-kind="plan"><summary><span>Thay đổi kế hoạch</span><span class="cnt">1 lần sửa</span>')
        self.assertIn('Kế hoạch chưa sửa lần nào.', panel('real_fail', 'plan'))
        more = run('renderDetail(DATA,{work:{changes:[{kind:"contract",revision:3,diff_total:5,diff:[{path:"title",change:"changed",before:"a",after:"b"}]}]}},"plan")')
        self.assertIn('Còn 4 thay đổi nữa không hiện.', more)
        self.assertIn('Tên việc', more)
        css = html()
        self.assertRegex(css, r'\.ba\{display:grid;grid-template-columns:minmax\(0,1fr\) minmax\(0,1fr\)')    # side by side on wide
        mobile = re.search(r'@media \(max-width:899px\)\{(.*?)\n\}', css, re.S).group(1)
        self.assertRegex(mobile, r'\.ba\{grid-template-columns:minmax\(0,1fr\)\}')                          # stacked on a phone

    def test_finding_repair_recheck(self):
        markup = panel('real_fail', 'repair')
        self.assertIn('Đã dùng 3/3 lượt sửa', markup)
        self.assertIn('Lỗi: AssertionError: thẻ hết hạn vẫn đăng nhập được', markup)
        steps = [text_of(s) for s in re.findall(r'<li class="\w+">(.*?)</li>', markup)]
        expected = ['Lần kiểm 1: không đạt', 'Sửa (lượt 1)', 'Lần kiểm 2: không đạt', 'Sửa (lượt 2)', 'Lần kiểm 3: không đạt', 'Lần kiểm tới là lần thử cuối']
        self.assertEqual(len(steps), len(expected))
        for got, want in zip(steps, expected):
            self.assertTrue(got.startswith(want), (got, want))
        rf = run('findTask(DATA,"t02")')
        for c in rf['milestone_checks']['rows'][1]['checks']:
            self.assertIn(run('fmtTime(%s)' % json.dumps(c['recorded'])), markup)      # every check carries its time
        self.assertIn('Đã dừng: hết lượt sửa, chờ bạn quyết', panel('owner_decision', 'repair'))
        to = panel('timeout', 'repair')
        self.assertIn('Lần kiểm 1: chưa kết luận', to)
        self.assertIn('Còn 2 lượt sửa', to)
        self.assertIn('Chưa có lần kiểm nào không đạt.', panel('pass_then_edit', 'repair'))
        self.assertIn('chưa kiểm lại', panel('engine_parts', 'repair'))
        # the recheck: the old pass stays visible but marked, with why
        checks = panel('pass_then_edit', 'checks')
        self.assertIn('Cần kiểm lại', checks)
        self.assertIn('mã đã đổi sau lần kiểm', checks)
        self.assertRegex(page('real_fail'), r'<details class="d" data-kind="repair"><summary><span>Vòng sửa</span><span class="cnt">3 lần không đạt</span>')
        # the loop is built from the real check history only
        self.assertEqual(run('repairLoop({checks:[{result:"pass"}],repairs:{left:3}})'), [{'kind': 'check', 'tone': 'ok', 'text': 'Lần kiểm 1: đạt', 't': '', 'd': ''}])

    def test_wait_opens_timeline(self):
        od = run('findTask(DATA,"t01")')
        markup = panel('owner_decision', 'wait')
        self.assertIn('Việc đang chờ bạn', markup)
        since = od['requests'][0]['created_at']
        self.assertIn(run('fmtTime(%s)' % json.dumps(since)), markup)
        self.assertIn('(%s)' % run('dur(since(%s,DATA.read_at))' % json.dumps(since)), markup)
        items = re.findall(r'<li><time>(.*?)</time><span>(.*?)</span></li>', markup)
        self.assertEqual(len(items), len(od['timeline']))
        self.assertEqual(items[0][0], run('fmtTime(%s)' % json.dumps(od['timeline'][-1]['at'])))  # newest first
        self.assertIn('kết quả kiểm mốc 3: không đạt', markup)
        self.assertNotIn('verdict', markup)
        engine = panel('engine_parts', 'wait')
        self.assertIn('<b>Agent chờ</b>: chờ máy thử Android rảnh', engine)
        self.assertIn('đã chờ 8 phút', engine)
        self.assertRegex(page('owner_decision'), r'<details class="d" data-kind="wait"><summary><span>Thời gian và ai chờ ai</span>')
        bare = run('renderDetail(DATA,itemsOf(DATA)[0],"wait")')                   # an overview item without its detail
        self.assertIn('Chưa đọc chi tiết của việc này.', bare)
        self.assertIn('Sổ không ghi lần chờ nào.', panel('real_fail', 'wait'))

    def test_result_opens_evidence(self):
        rf = run('findTask(DATA,"t02")')
        markup = panel('real_fail', 'evidence')
        run_row = rf['work']['checks']['runs'][0]
        self.assertIn('mã: 1', markup)
        self.assertIn(run_row['receipt'][:12], markup)
        self.assertIn('Mốc 2', markup)
        self.assertIn('Không đạt (bản cũ)', markup)
        self.assertIn('hết giờ', panel('timeout', 'evidence'))
        self.assertIn('5 mục bằng chứng', markup)
        # technical identifiers only inside the opened panels
        main = without_details(page('real_fail'))
        self.assertNotIn(run_row['receipt'][:12], main)
        tech = panel('real_fail', 'tech')
        for value in (rf['plan'], rf['selector'], rf['id']):
            self.assertIn(value, tech)
        # nothing is rendered as markup: a hostile value cannot inject
        hostile = run('renderDetail(DATA,{work:{checks:{runs:[{id:"<b>x</b>",node:"<script>1</script>",status:"fail",receipt:"<img src=x>",outputs:{exit_code:"<i>"}}]}},'
                      'evidence_index:[{label:"<script>2</script>",key:"k"}]},"evidence")')
        for bad in ('<script>', '<b>x</b>', '<img', '<i>'):
            self.assertNotIn(bad, hostile)
        self.assertNotIn('<script>', run('renderList({overview:{projects:[{path:"p",tasks:[{id:"x",short_title:"<script>1</script>"}]}]}},"all")'))

    def test_back_keeps_filter_and_position(self):
        # plain hash names only: #viec, #viec-<filter>, #viec-<filter>-<id>
        self.assertEqual(run('routeOf("#viec-need")'), {'view': 'list', 'id': None, 'filter': 'need'})
        self.assertEqual(run('routeOf("#viec-all-t04")'), {'view': 'task', 'id': 't04', 'filter': 'all'})
        self.assertEqual(run('routeOf("#viec-done-TASK-31ba8c8e")'), {'view': 'task', 'id': 'TASK-31ba8c8e', 'filter': 'done'})
        self.assertEqual(run('routeOf("")'), {'view': 'list', 'id': None, 'filter': 'all'})
        self.assertEqual(run('routeOf("#viec-bogus")')['filter'], 'all')
        self.assertEqual(run('routeOf("#/viec/need?x=1")')['view'], 'list')
        for t in tasks():
            for filt in FILTERS:
                href = run('hrefOf({view:"task",id:%s,filter:%s})' % (json.dumps(t['id']), json.dumps(filt)))
                self.assertRegex(href, r'^#[A-Za-z0-9-]+$')
                self.assertEqual(run('routeOf(%s)' % json.dumps(href)), {'view': 'task', 'id': t['id'], 'filter': filt})
        self.assertEqual(run('hrefOf({view:"list",filter:"need"})'), '#viec-need')
        # a row opened from a filter links back to that same filter; the active filter is marked
        listing = run('renderList(DATA,"check")')
        self.assertIn('href="#viec-check-t04"', listing)
        self.assertRegex(listing, r'data-filter="check" aria-current="true"')
        self.assertIn('aria-current="page"', run('renderList(DATA,"all","t04")'))
        # each filter keeps its own scroll position; a broken store answers 0
        got = run('(function(){var m={};var s={getItem:function(k){return k in m?m[k]:null},setItem:function(k,v){m[k]=v}};'
                  'saveListState(s,"need",0);saveListState(s,"check",734);saveListState(s,"all",120.4);'
                  'return [loadListState(s,"check"),loadListState(s,"all"),loadListState(s,"need"),loadListState(s,"done")]})()')
        self.assertEqual(got, [{'filter': 'check', 'scrollTop': 734}, {'filter': 'all', 'scrollTop': 120}, {'filter': 'need', 'scrollTop': 0}, {'filter': 'done', 'scrollTop': 0}])
        self.assertEqual(run('(function(){var s={getItem:function(){throw 1},setItem:function(){throw 1}};saveListState(s,"all",5);return loadListState(s,"all")})()'),
                         {'filter': 'all', 'scrollTop': 0})
        self.assertEqual(run('loadListState(null,"all")'), {'filter': 'all', 'scrollTop': 0})
        # the wiring saves the position when leaving, restores it after the list shows again, and goes back in history when it came from the list
        text = html()
        self.assertIn("lp.addEventListener('click',function(e){if(e.target.closest('a.row')){saveListState(store,cur.filter,lp.scrollTop);fromList=true}})", text)
        self.assertIn('var top=loadListState(store,r.filter).scrollTop;lp.scrollTop=top', text)
        self.assertIn('if(fromList){fromList=false;history.back()}else location.hash=hrefOf({view:\'list\',filter:r.filter})', text)
        self.assertIn("window.addEventListener('hashchange',render)", text)
        self.assertIn('‹ Quay lại', run('renderTask(DATA,findTask(DATA,"t01"))'))
        # the list is not redrawn when only the selected task changes (its scroll stays where it is)
        self.assertIn('if(r.filter!==cur.filter){lp.innerHTML=renderList(D,r.filter,r.id);cur.filter=r.filter}', text)

    def test_mobile_layout(self):
        text = html()
        self.assertIn('<meta name="viewport" content="width=device-width, initial-scale=1">', text)
        css = re.search(r'<style>(.*?)</style>', text, re.S).group(1)
        body = re.search(r'@media \(max-width:899px\)\{(.*?)\n\}', css, re.S).group(1)
        self.assertIn('body.view-task #listpane{display:none}', body)
        self.assertIn('body.view-list #taskpane{display:none}', body)
        self.assertIn('#back{display:inline-block}', body)
        self.assertIn('main{grid-template-columns:minmax(0,1fr)}', body)
        self.assertIn('.four{grid-template-columns:minmax(0,1fr)}', body)
        self.assertRegex(css, r'#back\{display:none[;}]')
        self.assertRegex(css, r'main\{display:grid;grid-template-columns:minmax\(0,380px\) minmax\(0,1fr\)')   # list | task side by side on wide
        self.assertEqual(run('bodyClass({view:"task"})'), 'view-task')
        self.assertEqual(run('bodyClass({view:"list"})'), 'view-list')
        # 16px gutters, long text wraps, nothing wider than a 375px phone
        self.assertIn('.pane{overflow:auto;min-width:0;padding:12px 16px}', css)
        self.assertRegex(css, r'header\{padding:8px 16px')
        self.assertIn('overflow-wrap:anywhere', css)
        for match in re.finditer(r'(?<![\w-])(?:min-)?width:\s*(\d+)px', css):
            self.assertLessEqual(int(match.group(1)), 375, match.group(0))
        self.assertNotRegex(css, r'(?<![\w-])(?:min-)?width:\s*\d+(?:vw|em|rem)')
        self.assertNotIn('overflow-x:scroll', css)
        self.assertRegex(css, r'\.scroll\{overflow-x:auto')
        for t in tasks():
            markup = run('renderTask(DATA,findTask(DATA,%s))' % json.dumps(t['id']))
            for table in re.finditer(r'<table', markup):
                self.assertTrue(markup[:table.start()].endswith('<div class="scroll">'), t['id'])
        # light and dark through tokens
        self.assertRegex(css, r'^\s*:root\{--paper:')
        self.assertIn('@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--paper:', css)
        self.assertIn(':root[data-theme=dark]{--paper:', css)
        self.assertRegex(css, r'body\{background:var\(--paper\)')
        self.assertIn('@media (prefers-reduced-motion:reduce)', css)

    def test_every_root_of_real_shaped_detail_renders(self):
        """Every root renders with its detail, without it (overview only), and with missing or empty parts, as a real export may have."""
        result = run('''(function(){var out=[];function chk(d,t,tag){var h=renderTask(d,t);if(!/id="b-dec"/.test(h))out.push(tag+": no blocks");
            if(/Không vẽ được/.test(h))out.push(tag+": "+h.match(/Không vẽ được phần này: ([^<]*)/)[1]);
            ["scope","checks","repair","plan","wait","evidence","agents","res","tech"].forEach(function(k){var p=renderDetail(d,t,k);if(/Không vẽ được/.test(p))out.push(tag+" "+k)})}
          itemsOf(DATA).forEach(function(t){chk(DATA,findTask(DATA,t.id),t.id+" detail");chk(DATA,t,t.id+" overview")});
          var bare={overview:{projects:[{path:null,tasks:[{id:"x"},{id:"y",situation:null,needs_user:null,milestones:null,tracking:{adapter:"engine"},nodes:null,work:{changes:null,checks:null}}]}]},details:{y:{milestone_checks:{rows:null},timeline:null,gantt:{rows:[{node:"A",segments:null}]}}}};
          itemsOf(bare).forEach(function(t){chk(bare,findTask(bare,t.id),t.id+" bare")});
          ["all","need","doing","check","done","bogus"].forEach(function(f){renderList(bare,f);renderList({},f);renderList(DATA,f)});
          renderTask(DATA,null);return out})()''')
        self.assertEqual(result, [])
        self.assertIn('Chọn một việc', run('renderTask(DATA,null)'))
        self.assertIn('Không có việc nào trong mục này.', run('renderList({},"all")'))

    def test_agents_engine_and_plain(self):
        eng = run('findTask(DATA,"t05")')
        markup = panel('engine_parts', 'agents')
        parts = re.findall(r'<article class="part" data-part="(\w+)">([\s\S]*?)</article>', markup)
        self.assertEqual([p for p, _ in parts], ['A', 'B', 'C'])
        agents = [re.search(r'<b class="agent-who">(.*?)</b>', body).group(1) for _, body in parts]
        self.assertEqual(agents, ['claude-sonnet', 'claude-opus', 'chưa biết'])
        self.assertIn('2 lượt', parts[1][1])
        self.assertIn('đã đối chiếu 140/200 dòng', parts[1][1])
        self.assertIn('tín hiệu cuối chưa có', parts[2][1])
        self.assertEqual(markup.count('<i class="s-'), sum(len(r['segments']) for r in eng['gantt']['rows']))
        self.assertIn('<i class="s-to_now"', markup)
        nxt = block(page('engine_parts'), 'id="b-next"')
        self.assertIn('class="act run"', nxt)
        self.assertIn('tín hiệu cuối 4 phút trước', nxt)
        self.assertIn('>AI</span>', nxt)
        self.assertIn('1/3', block(page('engine_parts'), 'id="b-out"'))
        self.assertIn('Theo từng phần', block(page('engine_parts'), 'id="b-trust"'))
        # a plain plan says briefly what the page cannot see; the engine task does not
        plain = page('plain_between_checks')
        self.assertIn('data-honest="1"', block(plain, 'id="b-next"'))
        self.assertIn(run('BETWEEN_CHECKS'), panel('plain_between_checks', 'agents'))
        self.assertNotIn('data-honest', page('engine_parts'))
        self.assertNotIn('data-honest', run('renderTask(DATA,findTask(DATA,"t09"))'))          # finished: nothing to watch
        # host background work: only this task's own lines
        own = panel('plain_between_checks', 'agents')
        self.assertEqual(own.count('<li class="host-item"'), 2)
        self.assertIn('Viết test cho mã vạch lạ', own)
        self.assertNotIn('Đối chiếu danh mục với kho', own)
        self.assertIn('Hook chưa báo việc nền nào của việc này', panel('timeout', 'agents'))
        listing = run('renderList(DATA,"all")')
        self.assertIn('Agent và việc nền: 2 đang chạy, 1 đã xong', listing)
        self.assertIn('Không có dòng nào không có nghĩa là không có việc nền', block(listing, 'id="hostbox"', '</details>'))
        quiet = run('(function(){var d=JSON.parse(JSON.stringify(DATA));d.host_work.projects.forEach(function(p){p.view.items=[];p.view.hooks_seen=[]});return renderList(d,"all")})()')
        self.assertIn('Agent và việc nền: hook chưa báo tín hiệu nào', quiet)
        # shared resources: holder and waiter with its place in the queue
        self.assertIn('chờ, vị trí <b>1</b>', panel('plain_between_checks', 'res'))
        self.assertIn('data-res-role="holder"', panel('engine_parts', 'res'))
        self.assertIn('Việc này không giữ hay chờ tài nguyên nào.', panel('real_fail', 'res'))
        self.assertIn('Tài nguyên dùng chung: 1 đang được giữ, 1 đang chờ', listing)
        self.assertIn('Máy này chưa khai báo', run('renderDetail({shared_resources:{declared:false,resources:[]}},findTask(DATA,"t02"),"res")'))

    def test_read_only_buttons(self):
        allowed = re.compile(r'data-copy="|id="(back|theme)"')
        pages = [html()] + run('itemsOf(DATA).map(function(t){return renderTask(DATA,findTask(DATA,t.id))})') + [run('renderList(DATA,"all")')]
        seen = set()
        for markup in pages:
            for tag in re.findall(r'<button\b[^>]*>', markup):
                match = allowed.search(tag)
                self.assertIsNotNone(match, tag)
                seen.add(match.group(1) or 'copy')
        self.assertEqual(seen, {'copy', 'back', 'theme'})
        script = script_and_data()[0]
        for banned in ('fetch(', 'XMLHttpRequest', 'sendBeacon', 'WebSocket', '<form', '.submit(', 'method=', 'execCommand', 'eval('):
            self.assertNotIn(banned, script + html().split('<script')[0])
        handler = re.search(r"document\.addEventListener\('click',function\(e\)\{([\s\S]*?)\}\);\n", script).group(1)
        self.assertEqual(re.findall(r"closest\('([^']+)'\)", handler), ['[data-copy]', '#back', '#theme'])
        copy = script[script.index('function copyText(text){'):script.index("lp.addEventListener('scroll'")]
        self.assertIn('navigator.clipboard.writeText(text)', copy)                  # copy only copies
        self.assertNotRegex(copy, r'location\.|history\.|innerHTML')
        self.assertIn('Chỉ đọc: trang không duyệt, không trả lời', run('renderList(DATA,"all")'))


if __name__ == '__main__':
    unittest.main()
