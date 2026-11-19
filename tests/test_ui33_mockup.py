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
        self.assertIn('<i class="seg-recheck"', block(pp, 'id="b-out"'))
        self.assertNotIn('<i class="seg-ok"', block(pp, 'id="b-out"'))
        self.assertIn('data-icon="refresh"', block(pp, 'id="b-trust"'))
        # a timeout: "Chưa kết luận", never "không đạt" (visible words, labels and tooltips alike; the model's own negation aside)
        to = case('timeout')
        self.assertEqual(run('statusLine(%s)' % json.dumps(to)), 'Chưa kết luận')
        tp = page('timeout')
        row = re.search(r'<a class="row"[^>]*data-id="%s"[\s\S]*?</a>' % to['id'], run('renderList(DATA,"all")')).group(0)
        for part in (block(tp, 'id="b-trust"'), block(tp, 'id="b-next"'), row):
            self.assertNotIn('không đạt', part.lower().replace('đây không phải kiểm không đạt', ''))
        self.assertIn('data-icon="hourglass"', row)
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
            self.assertRegex(listing, r'data-filter="%s"[^>]*>(?:(?!</a>)[\s\S])*?%s <b>%d</b></a>' % (filt, label, counts[filt]))
        # the owner flag comes from the real fields only: situation.no_owner_decision or an owner-kind need
        self.assertTrue(run('ownerNeeded({situation:{no_owner_decision:false}})'))
        self.assertTrue(run('ownerNeeded({needs_user:[{kind:"approve"}]})'))
        self.assertFalse(run('ownerNeeded({needs_user:[{kind:"other"}],situation:{no_owner_decision:true}})'))
        self.assertFalse(run('ownerNeeded({})'))
        # nobody waiting on the owner: the summary says so instead of hiding
        calm = run('(function(){var d=JSON.parse(JSON.stringify(DATA));itemsOf(d).forEach(function(t){t.needs_user=[];t.situation.no_owner_decision=true});return renderList(d,"all")})()')
        self.assertIn('<b>0</b> việc cần bạn', calm)
        self.assertNotIn('has-need', calm)
        self.assertNotIn('Các việc khác', calm)

    def test_one_status_line(self):
        listing = run('renderList(DATA,"all")')
        rows = re.findall(r'<a class="row"[\s\S]*?</a>', listing)
        self.assertEqual(len(rows), len(tasks()))
        for row, t in zip(rows, run('filterTasks(itemsOf(DATA),"all")')):
            self.assertEqual(row.count('class="sline"'), 1)
            self.assertEqual(row.count('<span class="gut">'), 1)
            gut = re.search(r'<span class="gut">(<span class="ic[^>]*>)', row).group(1)            # the state is an icon, its words are its label
            self.assertIn('aria-label="%s"' % run('statusLine(%s)' % json.dumps(t)), gut)
            self.assertIn('title="%s"' % run('statusLine(%s)' % json.dumps(t)), gut)
            self.assertLessEqual(row.count('class="mini"'), 1)
            for tag in ('<p', '<br', '<div', '<ul'):
                self.assertNotIn(tag, row)
            self.assertNotRegex(text_of(row), INTERNAL)
            self.assertNotIn(t['plan'], text_of(row))
            self.assertEqual(text_of(row), (t.get('short_title') or t['headline']) + ' ' + run('agoShort(%s,DATA.read_at)' % json.dumps(t['last_update']['at'])))
            self.assertLessEqual(len(text_of(row).split()), 16, row)       # title + short time, no sentence
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
            order = [markup.index(x) for x in ('<h2>', 'id="b-out"><h3>Đầu ra</h3>', 'id="b-trust"><h3>Còn tin được?</h3>',
                                               'id="b-next"><h3>Bước tiếp</h3>', 'id="b-dec"><h3>Bạn quyết</h3>', 'class="more"')]
            self.assertEqual(order, sorted(order), t['id'])
            words = text_of(main)
            self.assertNotRegex(words, INTERNAL, t['id'])
            self.assertNotIn(t['selector'], words)
            for attr in re.findall(r'(?:aria-label|title)="([^"]*)"', main):            # labels and tooltips speak the owner's words too
                self.assertNotRegex(attr, INTERNAL, (t['id'], attr))
            # scanned, not read: each tile is an icon, a 1-3 word label and a short value; long reasons sit behind "i" (Vietnamese syllables)
            self.assertLessEqual(len(text_of(re.sub(r'<ul class="opts">[\s\S]*?</ul>', '', main)).split()), 80, t['id'])
            for line in re.findall(r'<p class="one small clamp1"[^>]*>([^<]*)</p>', main):                 # the one long line per tile is clamped
                self.assertTrue(line.strip())
            for opt in re.findall(r'<li class="opt">([\s\S]*?)</li>', main):
                self.assertLessEqual(len(text_of(opt).split()), 40, t['id'])
            for tile in ('b-out', 'b-trust', 'b-next', 'b-dec'):
                self.assertRegex(block(main, 'id="%s"' % tile), r'<p class="val[^"]*"[^>]*><span class="ic lg[^"]*"')     # one big icon per tile
            self.assertNotIn('<p class="one">' + '<p', main)
            v = run('validityOf(findTask(DATA,%s))' % json.dumps(t['id']))
            self.assertIn('data-validity="%s"' % v['kind'], main)
            self.assertIn(v['label'], block(main, 'id="b-trust"'))
            who = run('whoOf(findTask(DATA,%s))' % json.dumps(t['id']))
            if who:
                self.assertIn(who, ('Bạn', 'AI', 'Bộ kiểm', 'Chưa rõ'))
                self.assertIn('aria-label="Ai làm: %s"' % who, block(main, 'id="b-next"'))
                self.assertIn('<span class="wl">%s</span>' % who, block(main, 'id="b-next"'))
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
        self.assertEqual(dec.count('aria-label="Hệ quả"'), len(options))
        self.assertEqual(len(re.findall(r'<li class="opt"><span class="ic[^>]*role="img" aria-label="[^"]+"', dec)), len(options))   # each option leads with its icon
        for option in options:
            self.assertGreaterEqual(len(option['label'].split()), 6)        # a full sentence, not a bare verb
            self.assertIn('<b class="clamp1" title="%s">%s</b>' % (option['label'], option['label']), dec)
            self.assertRegex(dec, r'aria-label="Hệ quả"[^<]*><svg[\s\S]*?</span><span class="clamp1" title="%s">%s</span>'
                             % (re.escape(option['consequence']), re.escape(option['consequence'])))
            self.assertIn('data-copy="%s"' % run('esc(%s)' % json.dumps(option['human_command'])), dec)
        self.assertIn('thêm khoảng 1 ngày', dec)
        # the question is the owner's words from the situation, not the verifier's English
        self.assertIn('Quyết định sau khi dừng: duyệt bản sửa để đi tiếp, hoặc kết thúc', dec)
        self.assertNotIn('Milestone M3 stopped', without_details(markup))
        self.assertIn('Sao chép chưa phải là duyệt', dec)
        # the last-try warning is a warning beside the next step, not a decision, not on the list
        rf = page('real_fail')
        self.assertNotIn('decision', block(rf, 'id="b-dec"'))
        self.assertIn('Không cần', block(rf, 'id="b-dec"'))
        warn = block(rf, 'id="b-next"')
        self.assertIn('<p class="warn" role="note" title="Mốc 2 đã dùng hết 3 lượt sửa: nếu lần kiểm tới vẫn không đạt, việc sẽ dừng và chờ bạn quyết định. '
                      'Đây là cảnh báo, bạn chưa cần làm gì."', warn)
        self.assertIn('<span>Lần thử cuối, chưa cần làm gì</span>', warn)
        self.assertIn('aria-label="Đã dùng 3/3 lượt sửa"', warn)
        self.assertEqual(warn.count('<i class="used">'), 3)                         # repairs as dots: used / left
        self.assertEqual(block(page('timeout'), 'id="b-next"').count('<i class="left">'), 2)
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
        self.assertRegex(page('owner_decision'), r'<details class="d" data-kind="plan"><summary>(?:(?!</summary>)[\s\S])*<span>Thay đổi kế hoạch</span><span class="cnt">1 lần sửa</span>')
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
        self.assertRegex(page('real_fail'), r'<details class="d" data-kind="repair"><summary>(?:(?!</summary>)[\s\S])*<span>Vòng sửa</span><span class="cnt">3 lần không đạt</span>')
        # the loop is built from the real check history only
        self.assertEqual(run('repairLoop({checks:[{result:"pass"}],repairs:{left:3}})'), [{'kind': 'check', 'tone': 'pass', 'text': 'Lần kiểm 1: đạt', 't': '', 'd': ''}])
        # the checks as a time chart: one bar per check, the result as fill + mark (× on a failure, hollow when not concluded)
        chart = re.search(r'<svg class="chart"[\s\S]*?</svg>', run('renderDetail(DATA,findTask(DATA,"t02"),"checks")')).group(0)
        self.assertEqual(re.findall(r'<g data-check="(\w+)">', chart), ['pass', 'fail', 'fail', 'fail'])
        self.assertEqual(chart.count('class="cc-x"'), 3)
        xs = [float(x) for x in re.findall(r'<rect class="cc-fail" x="([\d.]+)"', chart)]
        self.assertEqual(xs, sorted(xs))                                                  # x = time
        self.assertIn('<g data-check="inconclusive">', run('renderDetail(DATA,findTask(DATA,"t03"),"checks")'))
        self.assertNotIn('<svg class="chart"', run('renderDetail(DATA,findTask(DATA,"t08"),"checks")'))    # nothing checked yet: no empty chart

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
        self.assertRegex(page('owner_decision'), r'<details class="d" data-kind="wait"><summary>(?:(?!</summary>)[\s\S])*<span>Thời gian và ai chờ ai</span>')
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
        self.assertEqual(run('routeOf("#viec")'), {'view': 'list', 'id': None, 'filter': 'all'})
        self.assertEqual(run('routeOf("")'), {'view': 'dash'})                      # the dashboard is the landing page
        self.assertEqual(run('routeOf("#viec-bogus")')['filter'], 'all')
        self.assertEqual(run('routeOf("#/viec/need?x=1")'), {'view': 'dash'})       # a path or a query is never a route into a task
        # a project filter rides in the same plain hash and survives opening a task
        self.assertEqual(run('routeOf("#viec-need-duan-phieukham")'), {'view': 'list', 'id': None, 'filter': 'need', 'project': 'phieukham'})
        self.assertEqual(run('routeOf("#viec-all-duan-kyso-t05")'), {'view': 'task', 'id': 't05', 'filter': 'all', 'project': 'kyso'})
        self.assertEqual(run('hrefOf({view:"task",id:"t05",filter:"all",project:"kyso"})'), '#viec-all-duan-kyso-t05')
        self.assertIn('href="#viec-all-duan-kyso-t05"', run('renderList(DATA,"all",null,"kyso")'))
        self.assertNotEqual(run('listStateKey(listKeyOf({filter:"all",project:"kyso"}))'), run('listStateKey(listKeyOf({filter:"all"}))'))
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
        self.assertIn('var top=loadListState(store,listKeyOf(r)).scrollTop;lp.scrollTop=top', text)
        self.assertIn('if(fromList){fromList=false;history.back()}else location.hash=hrefOf({view:\'list\',filter:r.filter,project:r.project})', text)
        self.assertIn("window.addEventListener('hashchange',render)", text)
        self.assertIn('‹ Quay lại', run('renderTask(DATA,findTask(DATA,"t01"))'))
        # the list is not redrawn when only the selected task changes (its scroll stays where it is)
        self.assertIn('if(key!==cur.filter){lp.innerHTML=renderList(D,r.filter,r.id,r.project);cur.filter=key}', text)
        self.assertIn("if(r.view!=='dash')lastList={view:'list',filter:r.filter,project:r.project};", text)   # "Công việc" in the header returns to the same list

    def test_mobile_layout(self):
        text = html()
        self.assertIn('<meta name="viewport" content="width=device-width, initial-scale=1">', text)
        css = re.search(r'<style>(.*?)</style>', text, re.S).group(1)
        body = re.search(r'@media \(max-width:899px\)\{(.*?)\n\}', css, re.S).group(1)
        self.assertIn('body.view-task #listpane{display:none}', body)
        self.assertIn('body.view-list #taskpane{display:none}', body)
        self.assertIn('#back{display:inline-block}', body)
        self.assertIn('main{grid-template-columns:minmax(0,1fr)}', body)
        self.assertIn('.blk.decision{grid-column:1/-1', body)                       # tiles stay 2 x 2 on a phone; the decision takes the full row
        narrow = re.search(r'@media \(max-width:340px\)\{(.*?)\n\}', css, re.S).group(1)
        self.assertIn('.four{grid-template-columns:minmax(0,1fr)}', narrow)
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
        self.assertIn('class="line run"', nxt)
        self.assertIn('class="pulse"', nxt)
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
        self.assertIn('aria-label="Agent và việc nền: hook chưa báo tín hiệu nào"', quiet)
        self.assertIn('<b class="mut">?</b>', block(quiet, 'id="hostbox"', '</summary>'))     # no signal is "?" (unknown), never a reassuring 0
        # shared resources: holder and waiter with its place in the queue
        self.assertIn('chờ, vị trí <b>1</b>', panel('plain_between_checks', 'res'))
        self.assertIn('data-res-role="holder"', panel('engine_parts', 'res'))
        self.assertIn('Việc này không giữ hay chờ tài nguyên nào.', panel('real_fail', 'res'))
        self.assertIn('Tài nguyên dùng chung: 1 đang được giữ, 1 đang chờ', listing)
        self.assertIn('Máy này chưa khai báo', run('renderDetail({shared_resources:{declared:false,resources:[]}},findTask(DATA,"t02"),"res")'))

    def test_read_only_buttons(self):
        allowed = re.compile(r'data-copy="|id="(back|theme|legend-btn)"')
        pages = [html()] + run('itemsOf(DATA).map(function(t){return renderTask(DATA,findTask(DATA,t.id))})') + [run('renderList(DATA,"all")')]
        seen = set()
        for markup in pages:
            for tag in re.findall(r'<button\b[^>]*>', markup):
                match = allowed.search(tag)
                self.assertIsNotNone(match, tag)
                seen.add(match.group(1) or 'copy')
        self.assertEqual(seen, {'copy', 'back', 'theme', 'legend-btn'})
        script = script_and_data()[0]
        for banned in ('fetch(', 'XMLHttpRequest', 'sendBeacon', 'WebSocket', '<form', '.submit(', 'method=', 'execCommand', 'eval('):
            self.assertNotIn(banned, script + html().split('<script')[0])
        handler = re.search(r"document\.addEventListener\('click',function\(e\)\{([\s\S]*?)\}\);\n", script).group(1)
        self.assertEqual(re.findall(r"closest\('([^']+)'\)", handler), ['[data-copy]', '#back', '#theme', '#legend-btn', '#legend'])
        self.assertNotRegex(handler, r'innerHTML|\.submit|fetch')
        copy = script[script.index('function copyText(text){'):script.index("lp.addEventListener('scroll'")]
        self.assertIn('navigator.clipboard.writeText(text)', copy)                  # copy only copies
        self.assertNotRegex(copy, r'location\.|history\.|innerHTML')
        self.assertIn('Chỉ đọc: trang không duyệt, không trả lời', run('renderList(DATA,"all")'))

    # ---- the visual layer: icons, the summary chart, the milestone bars ----

    def test_each_state_has_distinct_icon_and_label(self):
        states = run('STATE_ICONS')
        icons = [s['icon'] for s in states.values()]
        labels = [s['label'] for s in states.values()]
        self.assertEqual(len(set(icons)), len(icons), icons)
        self.assertEqual(len(set(labels)), len(labels), labels)
        self.assertGreaterEqual(len(states), 11)
        expected = {'owner_decision': 'need', 'pass_then_edit': 'refresh', 'timeout': 'hourglass', 'real_fail': 'cross', 'engine_parts': 'play'}
        listing = run('renderList(DATA,"all")')
        for t in tasks():
            key = run('stateKey(%s)' % json.dumps(t))
            self.assertIn(key, states)
            row = re.search(r'<a class="row"[^>]*data-id="%s"[\s\S]*?</a>' % t['id'], listing).group(0)
            self.assertIn('data-state="%s"' % key, row)
            self.assertIn('data-icon="%s"' % states[key]['icon'], re.search(r'<span class="gut">[\s\S]*?</span></span>', row).group(0))
            if t.get('case') in expected:
                self.assertEqual(states[key]['icon'], expected[t['case']], t['case'])
        for t in run('filterTasks(itemsOf(DATA),"done")'):
            self.assertEqual(states[run('stateKey(%s)' % json.dumps(t))]['icon'], 'ok')
        # validity and who: the icons the owner asked for, each distinct
        valid = run('VALID_ICONS')
        five = [valid[k]['icon'] for k in ('valid', 'recheck', 'inconclusive', 'failed', 'unknown')]
        self.assertEqual(five, ['ok', 'refresh', 'hourglass', 'cross', 'question'])
        who = run('WHO_ICONS')
        self.assertEqual({k: v['icon'] for k, v in who.items()}, {'Bạn': 'person', 'AI': 'robot', 'Bộ kiểm': 'shield', 'Chưa rõ': 'question'})
        # every icon that is drawn exists in the inline sprite (no icon font, no request), and every labelled icon has its words
        text = html()
        rendered = [run('renderList(DATA,"all")'), run('legendHtml()')] + run('itemsOf(DATA).map(function(t){return renderTask(DATA,findTask(DATA,t.id))})')
        used = set()
        for markup in rendered:
            used |= set(re.findall(r'href="#i-([\w-]+)"', markup))
            for tag in re.findall(r'<span class="ic[^>]*>', markup):
                self.assertTrue('aria-hidden="true"' in tag or re.search(r'role="img" aria-label="[^"]+" title="[^"]+"', tag), tag)
        for name in used:
            self.assertIn('<symbol id="i-%s" viewBox="0 0 24 24">' % name, text)
        # the legend behind one "?" button names every state, every actor and every bar texture
        legend = run('legendHtml()')
        for s in states.values():
            self.assertIn('data-icon="%s"' % s['icon'], legend)
            self.assertIn('<span>%s</span>' % s['label'], legend)
        for name in who:
            self.assertIn('<span>%s</span>' % name, legend)
        for seg in set(run('MS_SEG').values()):
            self.assertIn('class="swatch seg-%s"' % seg, legend)
        self.assertIn('id="legend-btn" aria-expanded="false" aria-controls="legend"', text)
        self.assertIn('<div id="legend" class="legend" role="dialog" aria-label="Chú giải" hidden>', text)

    def test_summary_chart_counts_match_list(self):
        for data_expr in ('DATA', '(function(){var d=JSON.parse(JSON.stringify(DATA));itemsOf(d).forEach(function(t){t.needs_user=[];t.situation.no_owner_decision=true});return d})()'):
            got = run('(function(){var d=%s;return {list:renderList(d,"all"),counts:countTasks(itemsOf(d)),per:["need","doing","check","done","all"].map(function(f){return renderList(d,f)})}})()' % data_expr)
            listing, counts = got['list'], got['counts']
            bar = re.search(r'<div class="sbar"[\s\S]*?</div>', listing).group(0)
            segs = re.findall(r'<a class="sb sb-(\w+)" href="#viec-(\w+)" data-group="(\w+)" data-count="(\d+)" style="flex-grow:(\d+)"', bar)
            self.assertEqual([s[2] for s in segs], [g for g in ('need', 'doing', 'check', 'done') if counts[g]])   # zero groups are not drawn
            for seg, href, group, count, grow in segs:
                self.assertEqual(int(count), counts[group])
                self.assertEqual(grow, count)
                self.assertEqual(href, group)                                      # a segment opens its own filter
            self.assertEqual(sum(int(s[3]) for s in segs), counts['all'])
            self.assertIn('aria-label="Cần bạn %d, Đang làm %d, Chờ kiểm %d, Xong %d"' % (counts['need'], counts['doing'], counts['check'], counts['done']), bar)
            # the bar, the filter counts and the rows of each filter agree
            for f, markup in zip(('need', 'doing', 'check', 'done', 'all'), got['per']):
                self.assertEqual(markup.count('<a class="row"'), counts[f], f)
            # the "cần bạn" count is the big red number at the top
            if counts['need']:
                self.assertIn('<div class="hero has-need"><span class="ic lg x-need"', listing)
                self.assertIn('<b>%d</b> việc cần bạn' % counts['need'], listing)
            else:
                self.assertIn('<div class="hero"><span class="ic lg x-ok"', listing)
        # background work and shared resources: icon + number badges
        listing = run('renderList(DATA,"all")')
        host = re.search(r'<details class="badge" id="hostbox"><summary[^>]*>([\s\S]*?)</summary>', listing).group(1)
        self.assertIn('data-icon="robot"', host)
        self.assertIn('<b>2</b>', host)
        res = re.search(r'<details class="badge" id="resbox"><summary[^>]*>([\s\S]*?)</summary>', listing).group(1)
        self.assertIn('data-icon="lock"', res)
        self.assertIn('<b>1</b>', res)

    def test_milestone_bar_matches_milestones(self):
        ms_seg = run('MS_SEG')
        listing = run('renderList(DATA,"all")')
        for t in tasks():
            full = run('findTask(DATA,%s)' % json.dumps(t['id']))
            if full['tracking']['adapter'] == 'engine':
                want = [{'ok': 'ok', 'fail': 'fail', 'wait': 'wait', 'run': 'run', 'idle': 'pending'}[run('nodeTone(%s)' % json.dumps(n))] for n in full['nodes'].values()]
            else:
                want = [ms_seg[r['state']] for r in run('msRows(findTask(DATA,%s))' % json.dumps(t['id']))]
            row = re.search(r'<a class="row"[^>]*data-id="%s"[\s\S]*?</a>' % t['id'], listing).group(0)
            tile = block(run('renderTask(DATA,findTask(DATA,%s))' % json.dumps(t['id'])), 'id="b-out"')
            row_want = want
            if full['tracking']['adapter'] == 'engine':                            # the list row has only the overview's part counts
                ns = t['nodes_summary']
                row_want = (['ok'] * (ns['verified'] + ns['accepted']) + ['wait'] * ns['produced'] + ['run'] * ns['running']
                            + ['fail'] * ns['held'] + ['pending'] * ns['pending'])
                self.assertEqual(sorted(row_want), sorted(want))
            for markup, cls, want in ((tile, 'bar', want), (row, 'mini', row_want)):
                found = re.search(r'<span class="%s" role="img" aria-label="([^"]*)">([\s\S]*?)</span>' % cls, markup)
                if not want:
                    self.assertIsNone(found, t['id'])
                    continue
                self.assertEqual(re.findall(r'<i class="seg-(\w+)"', found.group(2)), want, (t['id'], cls))
                self.assertEqual(found.group(1), run('tallyText(findTask(DATA,%s))' % json.dumps(t['id'])))
            if want and full['tracking']['adapter'] != 'engine':
                titles = re.findall(r'<i class="seg-\w+" title="Mốc (\d+):', tile)
                self.assertEqual(titles, [str(i + 1) for i in range(len(want))])
        # counted the way the model counts: a pass that needs a recheck is not a pass
        pe = case('pass_then_edit')['id']
        self.assertEqual(run('tallyText(findTask(DATA,%s))' % json.dumps(pe)), '0/1 mốc đạt')
        self.assertIn('0/1 <small>mốc</small>', block(run('renderTask(DATA,findTask(DATA,%s))' % json.dumps(pe)), 'id="b-out"'))
        css = re.search(r'<style>(.*?)</style>', html(), re.S).group(1)
        for seg in set(ms_seg.values()) | {'wait'}:
            self.assertRegex(css, r'\.seg-%s\{' % seg)                             # every segment state has its own fill/texture

    # ---- the dashboard (#tong-quan): quick assessment from the same data ----

    def test_dashboard_route_and_switch(self):
        self.assertEqual(run('routeOf("#tong-quan")'), {'view': 'dash'})
        self.assertEqual(run('hrefOf({view:"dash"})'), '#tong-quan')
        self.assertEqual(run('bodyClass({view:"dash"})'), 'view-dash')
        head = html().split('<main>')[0]
        self.assertIn('<nav class="views" aria-label="Chế độ xem"><a href="#tong-quan" data-view="dash">Tổng quan</a><a href="#viec" data-view="list">Công việc</a></nav>', head)
        css = re.search(r'<style>(.*?)</style>', html(), re.S).group(1)
        for rule in ('#dashpane{display:none}', 'body.view-dash #listpane,body.view-dash #taskpane{display:none}', 'body.view-dash #dashpane{display:block}'):
            self.assertIn(rule, css)
        self.assertIn("if(r.view==='dash'){if(!dashDone){dp.innerHTML=renderDash(D);dashDone=true}", html())
        dash = run('renderDash(DATA)')
        order = [dash.index(x) for x in ('id="dash-attn"', 'id="dash-projects"', 'id="dash-rhythm"', 'id="dash-bg"', 'id="dash-missing"')]
        self.assertEqual(order, sorted(order))
        self.assertNotRegex(text_of(dash), INTERNAL)
        for markup in (dash, run('renderDash({})'), run('renderDash({overview:{projects:[{path:null,tasks:[{id:"x"}]}]}})')):    # never throws on thin data
            self.assertIn('id="dash-missing"', markup)
        # attention strip: icon + count, each opens the list filtered the same way
        listing_counts = {}
        for key, label, icon_name, _ in run('ATTN'):
            got = re.search(r'<a href="(#viec-%s)" data-attn="%s" data-count="(\d+)"[^>]*>([\s\S]*?)</a>' % (key, key), dash)
            self.assertIsNotNone(got, key)
            route = run('routeOf(%s)' % json.dumps(got.group(1)))
            self.assertEqual(route, {'view': 'list', 'id': None, 'filter': key})
            rows = run('renderList(DATA,%s)' % json.dumps(key)).count('<a class="row"')
            self.assertEqual(int(got.group(2)), rows, key)
            self.assertIn('data-icon="%s"' % icon_name, got.group(3))
            listing_counts[key] = rows
        self.assertEqual(listing_counts['need'], 3)
        self.assertEqual(listing_counts['fail'], 1)
        self.assertEqual(listing_counts['timeout'], 1)
        self.assertEqual(listing_counts['recheck'], 1)
        # background work and shared resources as icon + number
        bg = block(dash, 'id="dash-bg"')
        self.assertRegex(bg, r'<span data-host="running">[\s\S]*?<b>2</b>đang chạy</span>')
        self.assertRegex(bg, r'<span data-host="finished">[\s\S]*?<b>1</b>đã xong</span>')
        self.assertRegex(bg, r'<span data-res="held">[\s\S]*?<b>1</b>đang giữ</span>')
        self.assertRegex(bg, r'<span data-res="wait">[\s\S]*?<b>1</b>đang chờ</span>')
        quiet = run('renderDash({overview:DATA.overview,details:DATA.details,host_work:{projects:[]},shared_resources:{declared:false,resources:[]}})')
        self.assertIn('<span data-host="none">', quiet)                               # no signal is "?", never 0
        self.assertIn('<span data-res="none">', quiet)

    def test_dashboard_project_tiles_match_list(self):
        dash = run('renderDash(DATA)')
        tiles = re.findall(r'<article class="panel ptile" data-project="(\w+)">([\s\S]*?)</article>', dash)
        projects = run('projectsOf(DATA)')
        self.assertEqual([k for k, _ in tiles], [p['key'] for p in projects])
        self.assertEqual(len(tiles), len({t['project'] for t in tasks()}))
        for key, tile in tiles:
            members = [t['id'] for t in tasks() if run('projKey(%s)' % json.dumps(t['project'])) == key]
            numbers = re.findall(r'<a [^>]*href="([^"]+)" data-f="(\w+)" data-count="(\d+)"', tile)
            self.assertEqual([n[1] for n in numbers], ['need', 'doing', 'issue', 'done'])
            for href, f, count in numbers:
                route = run('routeOf(%s)' % json.dumps(href))
                self.assertEqual(route, {'view': 'list', 'id': None, 'filter': f, 'project': key})       # a click opens the filtered list
                listing = run('renderList(DATA,%s,null,%s)' % (json.dumps(f), json.dumps(key)))
                ids = re.findall(r'<a class="row"[^>]*data-id="([\w-]+)"', listing)
                self.assertEqual(len(ids), int(count), (key, f))
                self.assertTrue(set(ids) <= set(members), (key, f))
                self.assertIn('data-project="%s"' % key, listing)                       # the list says it is filtered, with a way out
            # the need count is the big one, red when not zero
            need = int(numbers[0][2])
            self.assertIn('class="pneed%s"' % (' has-need' if need else ''), tile)
            # the tile title opens the whole project
            title = re.search(r'<h3><a href="([^"]+)"', tile).group(1)
            self.assertEqual(run('routeOf(%s)' % json.dumps(title)), {'view': 'list', 'id': None, 'filter': 'all', 'project': key})
            self.assertEqual(run('renderList(DATA,"all",null,%s)' % json.dumps(key)).count('<a class="row"'), len(members))
            # its stacked bar adds up to the project's tasks
            self.assertEqual(sum(int(c) for c in re.findall(r'data-count="(\d+)" style="flex-grow', tile)), len(members))
        self.assertEqual(sum(len([t for t in tasks() if run('projKey(%s)' % json.dumps(t['project'])) == k]) for k, _ in tiles), len(tasks()))

    def test_dashboard_checks_per_day_totals(self):
        data = run('DATA')
        expected = {'pass': 0, 'fail': 0, 'inconclusive': 0}
        for t in tasks():
            detail = data['details'].get(t['id']) or {}
            if t['tracking']['adapter'] == 'engine':
                for r in (detail.get('work') or {}).get('checks', {}).get('runs', []):
                    if r['status'] in ('pass', 'fail') and r.get('at'):
                        expected[r['status']] += 1
            else:
                for row in (detail.get('milestone_checks') or {}).get('rows', []):
                    for c in row.get('checks', []):
                        if c.get('result') in expected and (c.get('recorded') or c.get('ended') or c.get('started')):
                            expected[c['result']] += 1
        total = sum(expected.values())
        self.assertGreater(total, 10)
        pd = run('checksPerDay(DATA,14)')
        self.assertEqual(len(pd['days']), 14)
        self.assertEqual(pd['outside'], 0)
        self.assertEqual(sum(d['total'] for d in pd['days']), total)
        for k, n in expected.items():
            self.assertEqual(sum(d[k] for d in pd['days']), n, k)
        for d in pd['days']:
            self.assertEqual(d['total'], d['pass'] + d['fail'] + d['inconclusive'])
        # the chart draws exactly those numbers, one column per day, scale-true (bar height proportional to the count)
        dash = run('renderDash(DATA)')
        chart = re.search(r'<svg class="rchart"[\s\S]*?</svg>', dash).group(0)
        cols = re.findall(r'<g data-day="([\d-]+)" data-total="(\d+)" data-pass="(\d+)" data-fail="(\d+)" data-inconclusive="(\d+)">([\s\S]*?)</g>', chart)
        self.assertEqual(len(cols), 14)
        self.assertEqual(sum(int(c[1]) for c in cols), total)
        unit = None
        for day, tot, p, f, i, body in cols:
            heights = [float(h) for h in re.findall(r'<rect class="rc-\w+" x="[\d.]+" y="[\d.]+" width="[\d.]+" height="([\d.]+)"', body)]
            self.assertEqual(len(heights), sum(1 for v in (p, f, i) if int(v)))
            if int(tot):
                per = (sum(heights) + len(heights) - 1) / int(tot)                        # add back the 1-unit gaps between stacked segments
                unit = unit or per
                self.assertAlmostEqual(per, unit, delta=0.6)
        legend = re.search(r'<ul class="rlegend">([\s\S]*?)</ul>', dash).group(1)
        for (k, label) in run('SERIES'):
            self.assertIn('<span class="swatch sw-%s"></span>%s <b>%d</b>' % (k, label, expected[k]), legend)
        stats = block(dash, '<div class="stats">', '</div></div></section>')
        self.assertIn('<div class="stat" data-stat="checks"><b>%d</b>' % total, stats)
        self.assertIn('(%d/%d)' % (expected['pass'], total), stats)
        self.assertIn('<div class="stat" data-stat="milestones"><b>', stats)
        self.assertNotIn('% công việc', stats)                                           # milestones are counted, never a percent of the work
        self.assertIn('<b>4</b><span>vòng sửa</span>', stats)                           # t01: 2 rounds, t02: 2 rounds, t03: none yet

    def test_dashboard_placeholders_show_no_numbers(self):
        dash = run('renderDash(DATA)')
        tiles = re.findall(r'<article class="panel ph" data-placeholder="(\w+)" aria-disabled="true" title="([^"]+)">([\s\S]*?)</article>', dash)
        self.assertEqual([t[0] for t in tiles], ['session', 'cost'])
        for key, title, body in tiles:
            self.assertNotRegex(text_of(body), r'\d', key)                                # no fake numbers
            self.assertNotIn('<b>', body)
            self.assertIn('Chưa có', text_of(body))
            self.assertLessEqual(len(text_of(body).split()), 16)
        self.assertIn('Claude đang làm gì, theo phiên', tiles[0][2])
        self.assertIn('Token, model, chi phí', tiles[1][2])
        self.assertIn('D1', tiles[0][1])
        self.assertIn('#59', tiles[1][1])
        css = re.search(r'<style>(.*?)</style>', html(), re.S).group(1)
        self.assertRegex(css, r'\.ph\{border-style:dashed')                               # greyed, visibly not data


if __name__ == '__main__':
    unittest.main()
