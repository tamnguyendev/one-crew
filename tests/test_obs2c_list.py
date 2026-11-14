"""OBS-2C acceptance on the model: the work list over a real temporary ledger (tests/obs2c_fixture: 150+ plan roots, an engine root with a
repair and child tasks, finished work, receipts, two projects, a secret).

Each test checks the result AND the reason the ledger gives for it: the order is the creation seq, paging is by floor/more, a source
comes from a recorded author/origin/approval, a relation from a recorded event; a value without a record is "unknown"/"chưa theo dõi".
The page that renders this model is checked in tests/test_obs2c_browser.py."""
import html as htmls
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import plan as plans, tracking, tracking_list, tracking_web
from onecrew.v2.tracking_work_web import SCRIPT
from tests import obs2c_fixture as fx

COUNT = 150
AI_SOURCE_WORDS = {'AI giao', 'AI phát sinh'}       # the only labels allowed to start with "AI"/"Ai": they name the AI source
PRELUDE = r'''
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function when(v){return v||''} function hms(n){return typeof n==='number'?n+'s':'chưa xác định'} function gantt(d){return ''}
function openBtn(k){return '<button type="button" class="ev-open" data-key="'+k+'">xem nội dung</button>'}
'''


def render(expr, data):
    """The shipped page script (tracking_work_web.SCRIPT) run by node on a model value; only the page-level helpers it borrows are given."""
    node = shutil.which('node')
    if not node: raise unittest.SkipTest('Node needed to render the shipped page script')
    code = PRELUDE + SCRIPT + '\nvar d=' + json.dumps(data, ensure_ascii=False) + ';console.log(JSON.stringify(' + expr + '));'
    done = subprocess.run([node, '-'], input=code, text=True, encoding='utf-8', capture_output=True, timeout=60)
    if done.returncode: raise AssertionError(done.stderr[-2000:])
    return json.loads(done.stdout.strip().splitlines()[-1])


def visible(markup):
    return htmls.unescape(re.sub(r'<[^>]+>', '', markup))


def rows(page):
    return [t for p in page['projects'] for t in p['tasks']]


def names(page):
    return [t['plan'] for t in rows(page)]


def newest_first(page):
    """The rows keep the scan order (creation seq, newest first) inside each project group of the overview shape."""
    return all([t['list']['seq'] for t in p['tasks']] == sorted((t['list']['seq'] for t in p['tasks']), reverse=True) for p in page['projects'])


class Shared:
    """One data set for the module (building 160 roots takes a while); every test reads it, the paging test writes its own new roots."""
    work = info = None

    @classmethod
    def get(cls):
        if cls.info is None:
            cls.work = tempfile.mkdtemp(prefix='obs2c-')
            cls.info = fx.create(cls.work, COUNT)
        return cls.info


def tearDownModule():
    if Shared.work: shutil.rmtree(Shared.work, ignore_errors=True)


class ListModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.info = Shared.get()
        cls.root = cls.info['state_root']
        cls.total = COUNT + 10          # W001..W150, REPAIR, SAME x2, APPROVED-OWNER/-UNKNOWN, CLOSED, ACCEPTED, RCPT-OK/-GONE, SECRET

    def page(self, **query):
        return tracking_list.page(self.root, dict({'list': '1'}, **{k: str(v) for k, v in query.items()}))

    def item(self, plan, **query):
        found = [t for t in rows(self.page(q=plan, limit=200, **query)) if t['plan'] == plan]
        self.assertTrue(found, plan)
        return found[0]

    # ---- 1. more than one page: total, shown, coverage; a search reaches a root that is not on the first page -----------------------
    def test_more_roots_than_a_page_report_total_shown_coverage_and_search_reaches_an_old_one(self):
        first = self.page(limit=50)
        L = first['list']
        self.assertEqual((L['total'], L['shown'], L['scanned'], L['complete']), (self.total, 50, 50, False))
        self.assertEqual(L['remaining'], self.total - 50)                    # coverage: what is not loaded yet, counted on the ledger
        self.assertEqual(L['next_cursor'], L['floor'])
        self.assertTrue(newest_first(first))                                 # newest first, by creation seq
        self.assertEqual(len({t['list']['seq'] for t in rows(first)}), 50)
        self.assertTrue(all(t['list']['seq'] >= L['floor'] for t in rows(first)))
        self.assertNotIn(fx.OLD, names(first))
        self.assertIn('không đổi khi có sự kiện mới', L['order_basis'])
        found = self.page(q=fx.OLD_WORDS)                                    # the text of a contract, judged on the index of every root
        self.assertEqual(names(found), [fx.OLD])
        self.assertEqual((found['list']['matched'], found['list']['complete']), (1, True))
        self.assertEqual(names(self.page(q='w007')), [fx.OLD])                # the plan name, case-insensitive
        self.assertEqual(first['tasks_total'], self.total)
        full = tracking.overview(self.root)                                  # without list parameters: the full overview, as before
        self.assertNotIn('list', full)
        self.assertEqual(sum(len(p['tasks']) for p in full['projects']), self.total)

    # ---- 2. load more while new roots and events arrive: no duplicate, no lost row ---------------------------------------------------
    def test_loading_more_while_events_arrive_never_doubles_or_loses_a_row(self):
        work = tempfile.mkdtemp(prefix='obs2c-paging-')
        self.addCleanup(shutil.rmtree, work, True)
        info = fx.create(work, 60, repair=False)
        root, ledger = info['state_root'], Ledger(info['project_a'], info['state_root'])
        page = lambda **q: tracking_list.page(root, dict({'list': '1'}, **{k: str(v) for k, v in q.items()}))
        def ids(answer): return [t['id'] for t in rows(answer)]
        with tracking._source(root)[0].transaction() as conn:
            before = {r['id'] for r in conn.execute('SELECT id, request_key FROM tasks') if r['request_key'].startswith(('plan:', 'plan-ns:'))}
        answer = page(limit=15)
        loaded = ids(answer)
        floor, step = answer['list']['floor'], 0
        while True:
            step += 1
            with fx.owner_shell():                                            # meanwhile: a new root, and new events on a loaded and an unloaded root
                plans.propose(ledger, f'NEW{step}', fx.contract(f'Việc mới {step}'), 'claude')
                for target in sorted({names(answer)[-1], f'W{max(1, 60 - step * 7):03d}'}):
                    if target.startswith('W'): plans.amend(ledger, target, fx.contract(f'{target} sửa lần {step}'), 'đổi tên khi danh sách đang được đọc', 'claude')
            answer = page(floor=floor, more=15)
            got = ids(answer)
            self.assertEqual(len(got), len(set(got)), 'a row twice in one answer')
            self.assertTrue(set(loaded) <= set(got), 'a loaded row was lost')
            self.assertTrue(newest_first(answer))
            self.assertIn(f'NEW{step}', names(answer))                         # a root created meanwhile comes on top, nothing shifts below
            self.assertLess(answer['list']['floor'] or 0, floor)
            loaded, floor = got, answer['list']['floor']
            if answer['list']['complete']: break
            self.assertLess(step, 10)
        self.assertEqual(answer['list']['floor'], 0)
        self.assertEqual(set(loaded), before | {t['id'] for t in rows(answer) if t['plan'].startswith('NEW')})
        again = page(floor=0)                                                # the poll of a complete list: the same rows, read anew
        self.assertEqual(sorted(ids(again)), sorted(loaded))

    # ---- 3. source owner / AI / unknown, the approval session as recorded; time and status filters; the finished view ------------------
    def test_source_filter_is_owner_ai_or_unknown_from_records_and_an_unknown_session_is_not_ai(self):
        counts = self.page(limit=1)['list']['counts']['source']
        kinds = [i % 4 for i in range(1, COUNT + 1)]
        self.assertEqual(counts, {'owner': kinds.count(0) + kinds.count(1) + 10, 'ai': kinds.count(3), 'unknown': kinds.count(2)})
        for source in ('owner', 'ai', 'unknown'):
            answer = self.page(source=source, limit=200)
            self.assertTrue(rows(answer))
            self.assertEqual({t['origin']['source'] for t in rows(answer)}, {source})
            self.assertEqual(answer['list']['matched'], counts[source])
        quoted, authored, silent, coordinator = self.item('W004'), self.item('W001'), self.item('W002'), self.item('W003')
        self.assertEqual((quoted['origin']['source'], quoted['origin']['basis'], quoted['origin']['request']),
                         ('owner', ['contract.origin'], 'Chủ giao việc số 004'))
        self.assertEqual(quoted['origin']['request_source'], 'contract.origin.quote')
        self.assertEqual((authored['origin']['source'], authored['origin']['basis'], authored['origin']['author']), ('owner', ['plan.proposed:rev1.author'], 'owner'))
        self.assertEqual((silent['origin']['source'], silent['origin']['author']), ('unknown', 'claude'))   # an AI wrote it, nobody recorded who asked
        self.assertIn('chưa theo dõi', silent['origin']['why'])
        self.assertEqual(silent['origin']['request_source'], 'contract.title')
        self.assertIn('không phải lời chủ', silent['origin']['request_note'])
        self.assertEqual((coordinator['origin']['source'], coordinator['origin']['by']), ('ai', 'claude-coordinator'))
        unknown, declared = self.item('APPROVED-UNKNOWN')['origin']['approval'], self.item('APPROVED-OWNER')['origin']['approval']
        self.assertEqual(unknown['session'], 'unknown')
        self.assertIn('chưa rõ phiên', unknown['label'])
        self.assertNotIn('phiên AI', unknown['label'].replace('không suy là phiên AI', ''))
        self.assertIs(declared['session'], False)
        self.assertIn('tự khai là của chủ sở hữu', declared['label'])
        self.assertEqual(self.item('APPROVED-UNKNOWN')['origin']['source'], 'owner')   # the owner's quote, whatever the approval session
        self.assertEqual(tracking_list.approval({'by': 'owner', 'revision': 1})['session'], 'unknown')   # an old approval without the field
        self.assertEqual(tracking_list.approval({'by': 'owner', 'revision': 1, 'ai_session': 'maybe'})['session'], 'unknown')

    def test_status_time_filters_and_the_finished_view_where_closed_is_not_success(self):
        finished = self.page(stage='ended', limit=200)
        self.assertEqual(sorted(names(finished)), ['ACCEPTED', 'CLOSED'])
        by = {t['plan']: t for t in rows(finished)}
        self.assertEqual((by['ACCEPTED']['list']['ended']['kind'], by['ACCEPTED']['list']['ended']['accepted']), ('accepted', True))
        closed = by['CLOSED']
        self.assertEqual((closed['list']['ended']['kind'], closed['list']['ended']['accepted']), ('closed', False))
        self.assertEqual((closed['status']['outcome'], closed['situation']['stage']), ('closed', 'closed'))
        self.assertNotIn('nghiệm thu', closed['status']['label'])
        self.assertIn('đóng không phải nghiệm thu', closed['status']['reason'])
        self.assertEqual(by['ACCEPTED']['situation']['stage'], 'done')
        self.assertEqual(self.page(limit=1)['list']['counts']['ended'], 2)
        detail = tracking.detail(self.root, 'CLOSED')['relations']['end']
        self.assertEqual((detail['kind'], detail['accepted']), ('closed', False))
        self.assertIn('không phải thành công', detail['label'])
        # time: created in a range (instants), and ended in a range
        every = rows(self.page(limit=200))
        cut = sorted(t['created_at'] for t in every)[len(every) // 2]
        later = self.page(since=cut, limit=200)
        self.assertTrue(rows(later))
        self.assertTrue(all(tracking._at(t['created_at']) >= tracking._at(cut) for t in rows(later)))
        earlier = self.page(until=cut, limit=200)
        self.assertEqual(len(rows(later)) + len(rows(earlier)), self.total)
        self.assertEqual(sorted(names(self.page(time='ended', since='2000-01-01', limit=200))), ['ACCEPTED', 'CLOSED'])
        self.assertEqual(rows(self.page(time='ended', until='2000-01-01')), [])
        # a situation stage is judged row by row: what was scanned is said, matched is exact only once nothing remains
        need = self.page(stage='need', limit=10)
        self.assertEqual(len(rows(need)), 10)
        self.assertTrue(all(t['needs_user'] for t in rows(need)))
        self.assertFalse(need['list']['matched_exact'])
        self.assertGreaterEqual(need['list']['scanned'], 10)
        accept = self.page(stage='done', limit=50)
        self.assertEqual(names(accept), ['ACCEPTED'])
        self.assertTrue(accept['list']['matched_exact'])
        with self.assertRaises(ValueError): tracking_list.params({'stage': 'nothing'})
        with self.assertRaises(ValueError): tracking_list.params({'since': 'yesterday'})

    # ---- 4. same name in two projects; missing receipt is not green ---------------------------------------------------------------------
    def test_same_named_plans_in_two_projects_stay_apart(self):
        both = rows(self.page(q='SAME', limit=200))
        self.assertEqual(len(both), 2)
        self.assertEqual({t['project_id'] for t in both}, {self.info['a_id'], self.info['b_id']})
        self.assertEqual({t['origin']['request'] for t in both}, {'Làm việc trùng tên ở A', 'Làm việc trùng tên ở B'})
        path_b = next(p['path'] for p in self.page(limit=1)['list']['projects'] if p['project_id'] == self.info['b_id'])   # as the page's project filter offers it
        only_b = rows(self.page(q='SAME', project=path_b))
        self.assertEqual([(t['plan'], t['project_id']) for t in only_b], [('SAME', self.info['b_id'])])
        self.assertEqual(tracking.detail(self.root, 'SAME', project_id=self.info['b_id'])['origin']['request'], 'Làm việc trùng tên ở B')
        with self.assertRaises(LedgerError): tracking.detail(self.root, 'SAME')                # an ambiguous name is refused, never one picked
        scoped = tracking_list.page(self.root, {'list': '1', 'limit': '200'}, project_id=self.info['b_id'])
        self.assertEqual((names(scoped), scoped['list']['total']), (['SAME'], 1))
        self.assertNotIn(self.info['project_a'], json.dumps(scoped, ensure_ascii=False))

    def test_a_pass_whose_receipt_is_gone_is_not_counted_as_checked(self):
        ok, gone = self.item('RCPT-OK'), self.item('RCPT-GONE')
        self.assertEqual((ok['level']['kind'], ok['milestones'][0]['state'], ok['evidence_gaps']), ('verified', 'passed', []))
        self.assertEqual(gone['level']['kind'], 'none')
        self.assertEqual(gone['milestones'][0]['state'], 'pending')
        self.assertTrue(gone['milestones'][0]['needs_recheck'])
        self.assertIn('không còn trong kho', gone['milestones'][0]['note'])
        self.assertEqual([g['milestone'] for g in gone['evidence_gaps']], ['M1'])
        self.assertEqual(gone['situation']['stage'], 'check')
        self.assertIn('cần kiểm lại', gone['situation']['reason'])
        self.assertNotEqual(gone['status']['kind'], 'done')
        self.assertNotIn(gone['situation']['stage'], ('done', 'accept'))
        accepted = self.item('ACCEPTED')                                      # an accepted plan keeps its history: no gap, owner acceptance shown
        self.assertEqual((accepted['level']['kind'], accepted['evidence_gaps']), ('accepted', []))

    # ---- 5. spawned work with its source and reason, counted once; read only; secrets filtered --------------------------------------------
    def test_a_repair_and_child_tasks_show_source_reason_and_root_and_are_counted_once(self):
        detail = tracking.detail(self.root, 'REPAIR')
        rel = detail['relations']
        repairs = [s for s in rel['spawned'] if s['kind'] == 'repair']
        kids = [s for s in rel['spawned'] if s['kind'] == 'child']
        self.assertEqual(len(repairs), 1)
        r = repairs[0]
        self.assertIn('kiểm không đạt', r['reason'])
        self.assertEqual(r['failed_checks'], ['check-C'])
        self.assertEqual(r['root']['id'], detail['id'])
        self.assertEqual(r['source']['kind'], 'plan.revised')
        self.assertIsInstance(r['from_check']['seq'], int)
        self.assertIn(r['status'], ('partial', 'verified'))                   # C was rechecked and passed after the repair
        self.assertTrue(r['rechecks'])
        self.assertTrue(kids)
        self.assertEqual(len({k['id'] for k in kids}), len(kids))
        events = {e['seq']: e for e in detail['timeline']}
        for k in kids:
            self.assertEqual(k['source']['kind'], 'node.started')
            self.assertEqual(events[k['source']['seq']]['kind'], 'node.started')
            self.assertTrue(k['attempts'])
        listed = self.item('REPAIR')['list']['links']
        self.assertEqual((listed['repairs'], listed['children']), (rel['counts']['repairs'], rel['counts']['children']))
        self.assertEqual(listed['spawned'], len(rel['spawned']))
        self.assertEqual(names(self.page(source='spawned', limit=200)), ['REPAIR'])
        self.assertEqual(rel['origin']['source'], 'owner')
        self.assertEqual(rel['parent']['link'], 'chưa theo dõi')
        self.assertIn('chưa theo dõi', rel['not_tracked'])
        plain = tracking.detail(self.root, 'W010')['relations']
        self.assertEqual((plain['spawned'], plain['counts']['repairs'], plain['counts']['children']), ([], 0, 0))
        # one child named by two events (a replayed node.started) is one child, with the other event kept as a source
        twice = [(5, 'node.started', {'child': 'TASK-x', 'node': 'C', 'generation': 0, 'attempt': 'a1'}, 't1'),
                 (9, 'node.started', {'child': 'TASK-x', 'node': 'C', 'generation': 0, 'attempt': 'a1'}, 't2'),
                 (11, 'node.started', {'child': 'TASK-y', 'node': 'I', 'generation': 0, 'attempt': 'a2'}, 't3')]
        found = tracking_list.children(twice)
        self.assertEqual(sorted(found), ['TASK-x', 'TASK-y'])
        self.assertEqual((found['TASK-x']['seq'], found['TASK-x']['also']), (5, [9]))

    # ---- repair 1 of 14/11 (coordinator review of the dev28 wheel): plain words for the spawned items, no heading that reads as "AI" --
    def test_the_relation_section_names_each_spawned_item_by_kind_name_and_state_never_by_its_raw_id(self):
        detail = tracking.detail(self.root, 'REPAIR')
        spawned = {s['kind'] + ':' + s['id']: s for s in detail['relations']['spawned']}
        html = render('relSection(d)', detail)
        items = re.findall(r'<article class="rel-item" data-rel="([^"]+)">(.*?)</article>', html, re.S)
        self.assertEqual(sorted(k for k, _ in items), sorted(spawned))                    # every linked item once, and only those
        self.assertEqual(sorted(s['kind'] for s in spawned.values()), ['child', 'child', 'repair'])
        generations = set()
        for key, body in items:
            model, head = spawned[key], visible(re.search(r'<h4>(.*?)</h4>', body, re.S).group(1))
            words = visible(body)
            self.assertTrue(head.startswith(('Việc sửa · ', 'Phần việc con · ')), head)
            self.assertNotIn(model['id'][:8], head)                                        # the name line never carries the id
            self.assertNotIn('TASK-', head)
            self.assertIn(model['state_label'], words)                                     # its state, from the ledger
            self.assertIn('mã ' + model['short_id'], words)                                # the id: once, as a short secondary text
            self.assertEqual(words.count(model['id'][:12]), 1)
            self.assertIn('data-work-tab="' + model['opens'] + '"', body)                  # opens the tab of this detail that shows it
            if model['kind'] == 'repair':
                self.assertEqual(head, 'Việc sửa · cho phần việc Chuẩn bị nội dung đầu ra')   # the node's name in the definition
                self.assertIn(model['state_label'], tracking_list.REPAIR_STATES.values())
            else:
                self.assertEqual(head, 'Phần việc con · ' + (model['name'] or 'chưa có tên trong sổ'))
                self.assertEqual((model['state'], model['state_label']), ('settled', 'lượt chạy đã kết thúc'))
                generations.add(model['generation'])
                self.assertIn('thế hệ ' + str(model['generation']), words)
        self.assertEqual(generations, {0, 1})                                              # the two child parts are told apart
        nameless = dict(next(s for s in spawned.values() if s['kind'] == 'child'), name=None, title=None)
        shown = visible(render('relItem(d.x,d)', dict(detail, x=nameless)))
        self.assertIn('Phần việc con · chưa có tên trong sổ', shown)                     # no name recorded: said so, none invented

    def test_no_new_heading_or_chip_reads_as_the_ai_unless_it_names_the_ai_source(self):
        html = render('relSection(d)', tracking.detail(self.root, 'REPAIR'))
        grid = [visible(x) for x in re.findall(r'<div><b>(.*?)</b>', html)]
        self.assertEqual(grid, ['Nguồn giao việc', 'Yêu cầu ban đầu', 'Duyệt', 'Kết thúc'])
        self.assertNotIn('ai giao việc', visible(html).casefold())
        page = tracking_web.PAGE
        labels = grid + [visible(x) for x in re.findall(r'<(?:h3|h4|summary)[^>]*>(.*?)</(?:h3|h4|summary)>', html, re.S)]
        labels += [visible(x) for x in re.findall(r'<span class="org [a-z]+"[^>]*>(.*?)</span>', html)]
        labels += re.findall(r'<option value="[^"]*">([^<]+)</option>', page[page.index('id="origin"'):page.index('</select>', page.index('id="origin"'))])
        labels += re.findall(r"\['ended','([^']+)'\]", page) + list(tracking_list.SOURCE_WORDS.values()) + list(tracking_list.KIND_WORDS.values())
        self.assertIn('Nguồn giao việc', labels)
        for label in labels:
            if re.match(r'(?i)ai\b', label.strip()):
                self.assertIn(label.strip(), AI_SOURCE_WORDS, label)                       # upper-cased by CSS it must still mean the AI source

    def test_the_list_is_read_only_and_filters_secrets(self):
        ledger = tracking._source(self.root)[0].path
        def snapshot():
            blobs = os.path.join(self.root, 'snapshots', 'blobs')
            return (ledger.read_bytes(), ledger.stat().st_mtime_ns, sorted(os.listdir(blobs)) if os.path.isdir(blobs) else None)
        before = snapshot()
        answer = self.page(limit=60)
        tracking.detail(self.root, 'SECRET'); tracking.detail(self.root, 'REPAIR')
        self.assertEqual(snapshot(), before)                                  # the ledger and the store are only read
        self.assertTrue(answer['read_only'] and answer['list']['read_only'])
        text = json.dumps(answer, ensure_ascii=False) + json.dumps(tracking.detail(self.root, 'SECRET'), ensure_ascii=False)
        self.assertNotIn(fx.SECRET, text)
        self.assertNotIn(fx.SECRET[:24], text)
        secret = self.item('SECRET')
        self.assertIn('[withheld]', secret['origin']['request'])
        revisions = tracking.detail(self.root, 'SECRET')['relations']['revisions']
        self.assertEqual([v['kind'] for v in revisions], ['proposed', 'amended'])
        self.assertIn('[withheld]', revisions[1]['reason'])

    def test_the_server_answers_a_page_refuses_writes_and_bad_parameters(self):
        server = tracking_web.make_server(self.root, interval=1)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close()))
        base = tracking_web.url_of(server)
        def get(path):
            try:
                with urllib.request.urlopen(base + path, timeout=120) as r: return r.status, json.loads(r.read().decode('utf-8'))
            except urllib.error.HTTPError as error: return error.code, json.loads(error.read().decode('utf-8'))
        status, body = get('api/overview?list=1&limit=20')
        self.assertEqual((status, body['list']['shown'], body['list']['total']), (200, 20, self.total))
        status, body = get('api/overview?list=1&q=' + urllib.request.quote(fx.OLD_WORDS))
        self.assertEqual((status, [t['plan'] for p in body['projects'] for t in p['tasks']]), (200, [fx.OLD]))
        self.assertEqual(get('api/overview?list=1&source=robot')[0], 400)
        self.assertEqual(get('api/overview?list=1&limit=0')[0], 400)
        request = urllib.request.Request(base + 'api/overview?list=1', data=b'{}', method='POST')
        with self.assertRaises(urllib.error.HTTPError) as refused: urllib.request.urlopen(request, timeout=30)
        self.assertEqual(refused.exception.code, 405)


if __name__ == '__main__':
    unittest.main()
