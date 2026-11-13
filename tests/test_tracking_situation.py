"""UX 13/11: the stage, the reason, the next step and who takes it come from one model (tracking_situation); the page renders them.

Unit cases on the model with the inputs tracking._item hands it, the shipped page script on real items, and real temporary ledgers for the
milestone checks (verdict runs with their own times). No browser here: the layout is checked in the browser harness and on the wheel."""
import json
import os
import shutil
import subprocess
import sys
import time
import unittest

from onecrew.v2 import tracking, tracking_situation as ts, verdict, plan as plans
from onecrew.v2.tracking_web import PAGE
from tests.test_v2_l1 import Fixture, plan_json, milestone

OK = [sys.executable, '-c', 'print("ok")']
BAD = [sys.executable, '-c', 'import sys; sys.exit(1)']


def state(status='approved', **extra):
    return dict({'status': status, 'latest': 1, 'stopped': {}, 'verdicts': []}, **extra)


def view(mid, st='pending', **extra):
    return dict({'id': mid, 'title': 'Mốc ' + mid, 'state': st}, **extra)


def call(**kw):
    base = dict(state=state(), views=[], checks=None, engine_view=None, attempts=[], active=[], requests=[], needs=[], acceptance={}, level='none',
                has_started=False, guidance=None, status_kind='waiting', status_reason='')
    base.update(kw)
    return ts.situation(**base)


def rows(views, runs=()):
    """milestone_checks rows from views + (milestone, result, started, ended) runs on revision 1, as the ledger writes them."""
    history, seq = [], 0
    for mid, result, started, ended in runs:
        seq += 1; rid = 'r%d' % seq
        history.append((seq, 'verdict.run_started', {'revision': 1, 'milestone': mid, 'run_id': rid, 'started': started, 'pid': 1, 'host': 'h', 'deadline': '2099-01-01T00:00:00+00:00'}, started))
        if ended:
            history.append((seq + 100, 'verdict.receipt_issued', {'revision': 1, 'milestone': mid, 'run_id': rid, 'receipt': 'k%d' % seq}, ended))
            history.append((seq + 200, 'verdict.recorded', {'revision': 1, 'milestone': mid, 'receipt': 'k%d' % seq, 'result': result, 'by': 'command'}, ended))
    history.sort(key=lambda e: e[0])
    return ts.milestone_checks(views, history, 1, None, lambda run: None)


class Model(unittest.TestCase):
    def test_owner_sample_a_failed_milestone_needs_a_fix_and_names_no_invented_handler(self):
        vs = [view('M1', 'passed'), view('M2', 'failed'), view('M3'), view('M4')]
        c = rows(vs, [('M1', 'pass', '2026-11-13T01:00:00+00:00', '2026-11-13T01:00:30+00:00'), ('M2', 'fail', '2026-11-13T01:05:00+00:00', '2026-11-13T01:06:00+00:00')])
        s = call(views=vs, checks=c, has_started=True)
        self.assertEqual((s['stage'], s['label']), ('fix', 'Cần sửa'))
        self.assertEqual(s['reason'], 'Mốc M2 kiểm không đạt')
        self.assertEqual(s['next'], 'Sửa và kiểm lại mốc M2')
        self.assertIsNone(s['next_by'])
        self.assertEqual(s['next_by_text'], 'Chưa có thông tin người xử lý')
        self.assertFalse(s['activity']['running'])
        self.assertNotIn('đang sửa', json.dumps(s, ensure_ascii=False).lower())          # a failed check is not "AI is fixing"
        self.assertEqual(s['milestones']['text'], 'Đạt 1/4 mốc')
        self.assertNotIn('%', s['milestones']['text'] + s['milestones']['note'])
        self.assertTrue(s['no_owner_decision'])

    def test_milestone_root_stages(self):
        self.assertEqual(call(views=[view('M1')], checks=rows([view('M1')]))['stage'], 'todo')
        fixed = [view('M1', 'passed'), view('M2')]
        c = rows(fixed, [('M1', 'fail', '2026-11-13T01:00:00+00:00', '2026-11-13T01:01:00+00:00'), ('M1', 'pass', '2026-11-13T02:00:00+00:00', '2026-11-13T02:01:00+00:00')])
        s = call(views=fixed, checks=c, has_started=True)
        self.assertEqual(s['stage'], 'doing'); self.assertEqual(s['next'], 'Làm và kiểm mốc M2')
        self.assertEqual(c['rows'][0]['failures'], 1); self.assertEqual(c['rows'][0]['label'], 'Đạt')
        stale = [view('M1', 'pending', stale=True, needs_recheck=True, recheck_note='cần kiểm lại'), view('M2')]
        s = call(views=stale, checks=rows(stale), has_started=True)
        self.assertEqual(s['stage'], 'check'); self.assertIn('cần kiểm lại', s['reason'])
        done = [view('M1', 'passed'), view('M2', 'passed')]
        s = call(views=done, checks=rows(done), has_started=True, level='verified', acceptance={'ready': True},
                 needs=[{'kind': 'accept', 'owner_ask': 'Nghiệm thu: mở báo cáo'}])
        self.assertEqual((s['stage'], s['next_by'], s['next_by_text'], s['next']), ('accept', 'owner', 'Bạn', 'Nghiệm thu: mở báo cáo'))
        s = call(views=done, checks=rows(done), has_started=True, level='verified', acceptance={'ready': False, 'reason': 'Chờ kiểm bàn giao'})
        self.assertEqual(s['stage'], 'check')                                                  # verified, not ready: never "Chờ nghiệm thu"

    def test_a_check_in_flight_and_a_lost_one(self):
        vs = [view('M1', 'passed'), view('M2')]
        history = [(1, 'verdict.run_started', {'revision': 1, 'milestone': 'M2', 'run_id': 'x', 'started': '2026-11-13T01:00:00+00:00'}, '2026-11-13T01:00:00+00:00')]
        live = ts.milestone_checks(vs, history, 1, None, lambda run: None)
        s = call(views=vs, checks=live, has_started=True)
        self.assertEqual((s['stage'], s['activity']['running']), ('check', True)); self.assertIn('M2', s['activity']['text'])
        lost = ts.milestone_checks(vs, history, 1, None, lambda run: 'process_gone')
        s = call(views=vs, checks=lost, has_started=True)
        self.assertEqual(s['stage'], 'unknown'); self.assertIn('mất tín hiệu', s['reason']); self.assertFalse(s['activity']['running'])

    def test_checks_have_their_own_time_and_untimed_ones_draw_nothing(self):
        vs = [view('M1', 'passed')]
        c = rows(vs, [('M1', 'pass', '2026-11-13T01:00:00+00:00', '2026-11-13T01:02:00+00:00')])
        self.assertTrue(c['timed']); self.assertEqual(c['rows'][0]['check_seconds'], 120.0)
        self.assertIn('không phải thời gian làm việc', c['basis'])
        loose = ts.milestone_checks(vs, [(5, 'verdict.recorded', {'revision': 1, 'milestone': 'M1', 'result': 'pass', 'by': 'owner'}, '2026-11-13T03:00:00+00:00')], 1, None, lambda r: None)
        self.assertFalse(loose['timed']); self.assertIsNone(loose['rows'][0]['check_seconds']); self.assertEqual(loose['rows'][0]['untimed_checks'], 1)
        other = ts.milestone_checks(vs, [(5, 'verdict.recorded', {'revision': 2, 'milestone': 'M1', 'result': 'fail'}, '2026-11-13T03:00:00+00:00')], 1, None, lambda r: None)
        self.assertEqual(other['rows'][0]['checks'], [])                                      # another revision's verdict is not this contract's check

    def test_engine_root_stages_and_handlers(self):
        definition = {'nodes': [{'id': 'C', 'goal': 'Code', 'executor': {'provider': 'claude', 'model': 'opus'}}, {'id': 'I', 'goal': 'Integrate'}]}
        ev = lambda **nodes: {'nodes': nodes, 'definition': definition}
        s = call(engine_view=ev(C={'phase': 'running', 'attempt': 'a1'}, I={'phase': 'pending'}), active=[{'attempt': 'a1', 'status': 'running', 'node': 'C', 'since': 't'}], has_started=True)
        self.assertEqual((s['stage'], s['activity']['running']), ('doing', True)); self.assertEqual(s['next_by_text'], 'Được giao theo kế hoạch: claude · opus')
        blocked = call(engine_view=ev(C={'phase': 'running', 'attempt': 'a1'}), active=[{'attempt': 'a1', 'status': 'running', 'node': 'C', 'since': '2026-11-13T01:00:00+00:00'}], has_started=True,
                       progress={'C': {'status': 'blocked', 'reason': 'chờ khóa USB', 'observed_at': '2026-11-13T01:05:00+00:00'}})
        self.assertEqual(blocked['stage'], 'doing'); self.assertIn('báo bị chặn: chờ khóa USB', blocked['reason'])
        self.assertEqual(blocked['activity']['last_signal'], '2026-11-13T01:05:00+00:00')   # the newest sourced signal, shown with its age; never called lost without a source
        s = call(engine_view=ev(C={'phase': 'complete', 'state': 'produced'}, I={'phase': 'pending'}), has_started=True)
        self.assertEqual((s['stage'], s['next_by_text']), ('check', 'Bộ kiểm OneCrew')); self.assertFalse(s['activity']['running'])
        s = call(engine_view=ev(C={'phase': 'held', 'reason': 'kiểm không đạt'}, I={'phase': 'pending'}), has_started=True)
        self.assertEqual(s['stage'], 'fix'); self.assertIn('bị giữ', s['reason'])
        s = call(engine_view=ev(C={'phase': 'running', 'attempt': 'a1'}), attempts=[{'id': 'a1', 'status': 'unknown'}], active=[{'attempt': 'a1', 'status': 'unknown', 'node': 'C'}], has_started=True)
        self.assertEqual(s['stage'], 'unknown'); self.assertFalse(s['activity']['running'])
        s = call(engine_view=ev(C={'phase': 'complete', 'state': 'verified'}, I={'phase': 'pending'}), has_started=True)
        self.assertEqual(s['stage'], 'doing')                                                 # resumed work between nodes is not "never started"
        s = call(engine_view=ev(C={'phase': 'pending'}, I={'phase': 'pending'}))
        self.assertEqual(s['stage'], 'todo')

    def test_owner_decisions_name_the_owner_without_moving_the_stage(self):
        definition = {'nodes': [{'id': 'C', 'goal': 'Code'}]}
        running = dict(engine_view={'nodes': {'C': {'phase': 'running', 'attempt': 'a1'}}, 'definition': definition},
                       active=[{'attempt': 'a1', 'status': 'running', 'node': 'C'}], has_started=True)
        s = call(state=state('proposed', latest=2), needs=[{'kind': 'approve', 'owner_ask': 'Duyệt việc: X'}], **running)
        self.assertEqual((s['stage'], s['next_by_text'], s['next']), ('doing', 'Bạn', 'Duyệt việc: X'))   # a pending amendment keeps running work in progress
        s = call(needs=[{'kind': 'request', 'question': 'Giữ khóa cũ?'}], **running)
        self.assertEqual(s['stage'], 'doing'); self.assertIn('Giữ khóa cũ?', s['next']); self.assertFalse(s['no_owner_decision'])
        self.assertEqual(call(state=state('proposed'), needs=[{'kind': 'approve'}])['stage'], 'todo')
        self.assertEqual(call(state=state('accepted'))['stage'], 'done')
        closed = call(state=state('closed'))
        self.assertEqual(closed['stage'], 'closed'); self.assertIn('không phải nghiệm thu', closed['reason']); self.assertIsNone(closed['next'])
        stopped = call(state=state('stopped_with_report', stopped={1: {'milestone': 'M2'}}), needs=[{'kind': 'stopped'}])
        self.assertEqual((stopped['stage'], stopped['next_by_text']), ('stopped', 'Bạn'))


class Ledgers(Fixture):
    def plan(self, name, ms, title='Sửa lỗi đăng nhập'):
        v = plan_json(milestones=ms, title=title); v['items'] = [{'id': 'I1', 'title': 'Do it', 'tier': 'must', 'milestone': ms[0]['id']}]
        plans.propose(self.ledger, name, v, 'claude', workflow=True)
        os.environ.pop('ONECREW_ACTOR', None); plans.approve(self.ledger, name, 'owner', 'test fixture')

    def test_owner_sample_on_a_real_ledger_lists_every_milestone_with_sourced_check_times(self):
        self.plan('P1', [milestone('M1', OK), milestone('M2', BAD), milestone('M3', OK), milestone('M4', OK)])
        verdict.run(self.ledger, 'P1', 'M1'); verdict.run(self.ledger, 'P1', 'M2')
        item = next(t for p in tracking.overview(self.ledger.state_root)['projects'] for t in p['tasks'] if t['plan'] == 'P1')
        s = item['situation']
        self.assertEqual((s['stage'], s['next'], s['next_by_text']), ('fix', 'Sửa và kiểm lại mốc M2', 'Chưa có thông tin người xử lý'))
        self.assertFalse(s['activity']['running'])
        d = tracking.detail(self.ledger.state_root, 'P1')
        c = d['milestone_checks']
        self.assertEqual([r['id'] for r in c['rows']], ['M1', 'M2', 'M3', 'M4'])
        self.assertEqual([r['state'] for r in c['rows']], ['passed', 'failed', 'pending', 'pending'])
        self.assertTrue(all(isinstance(r['checks'][0]['seconds'], float) for r in c['rows'][:2]))
        self.assertEqual(c['rows'][2]['checks'], [])
        self.assertTrue(c['timed'])
        self.assertEqual(d['situation'], s)

    def test_a_fix_then_recheck_reads_as_passed_with_its_history(self):
        # the fix is a real change of the project (a pass on the same tree after a fail is not a fix); the verifier's condition is a flag outside
        # the project so the changed file is not one the command line names (that would make the pass inconclusive by the integrity rule)
        flag = self.root.parent / 'fixed.flag'
        flip = [sys.executable, '-c', f'import os,sys,time; ok=os.path.exists({str(flag)!r}); time.sleep(1.5); print("3 tests passed" if ok else "1 test failed: test_export"); sys.exit(0 if ok else 1)']   # a real suite prints; a fast silent pass after a fail is suspicious by rule
        self.plan('P2', [milestone('M1', flip), milestone('M2', OK)])
        verdict.run(self.ledger, 'P2', 'M1')
        (self.root / 'a.txt').write_text('fixed'); self.git('commit', '-qam', 'the fix'); flag.write_text('x')
        verdict.run(self.ledger, 'P2', 'M1')
        d = tracking.detail(self.ledger.state_root, 'P2')
        row = d['milestone_checks']['rows'][0]
        self.assertEqual((row['state'], row['failures'], [c['result'] for c in row['checks']]), ('passed', 1, ['fail', 'pass']))
        self.assertEqual(d['situation']['stage'], 'doing')


class Script(unittest.TestCase):
    def js(self, expr, extra=''):
        node = shutil.which('node')
        if not node: self.skipTest('Node unavailable; not verified')
        start = PAGE.index('<script>') + 8; body = PAGE[start:PAGE.rindex('</script>')].replace('@@INTERVAL@@', '2000')
        body = body.replace('(function(){', '', 1); body = body[:body.rindex('})();')]
        stub = ("var document={querySelector:function(){return {addEventListener:function(){},value:'',options:[],style:{}}},querySelectorAll:function(){return []},addEventListener:function(){}};"
                "var window={matchMedia:function(){return {matches:false,addEventListener:function(){}}},addEventListener:function(){},scrollTo:function(){},scrollY:0};"
                "var location={search:'',pathname:'/'};var history={pushState:function(){}};var localStorage={getItem:function(){return null},setItem:function(){}};"
                "function setInterval(){};function setTimeout(){};function fetch(){return {then:function(){return {then:function(){return {catch:function(){return {then:function(){}}}}}}}}};")
        result = subprocess.run([node, '-'], input=stub + body + extra + '\nconsole.log(JSON.stringify(' + expr + '));', text=True, encoding='utf8', capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_the_page_renders_the_model_and_derives_no_stage(self):
        t = {'plan': 'P1', 'selector': 'plan:P1', 'project': 'D:/x', 'project_id': 'p', 'situation': {'stage': 'fix', 'label': 'Cần sửa', 'reason': 'Mốc M2 kiểm không đạt',
             'next': 'Sửa và kiểm lại mốc M2', 'next_by': None, 'next_by_text': 'Chưa có thông tin người xử lý', 'activity': {'running': False, 'text': 'Không có lượt chạy'},
             'milestones': {'passed': 1, 'total': 4, 'text': 'Đạt 1/4 mốc', 'note': 'số mốc đạt, không phải phần trăm công việc'}},
             'status': {'kind': 'running', 'label': 'đang thực hiện'}, 'level': {'label': 'chưa có đầu ra'}, 'last_update': {'at': '2026-11-13T01:00:00Z', 'summary': 'mốc M2 không đạt'}}
        self.assertEqual(self.js('[workStage(t),workStatus(t)]', '\nvar t=' + json.dumps(t) + ';'), ['fix', 'Cần sửa'])     # status.kind 'running' does not win
        html = self.js('workItem(t)', '\nvar t=' + json.dumps(t) + ';')
        for wanted in ('Cần sửa', 'Mốc M2 kiểm không đạt', 'Sửa và kiểm lại mốc M2', 'Chưa có thông tin người xử lý', 'Đạt 1/4 mốc'):
            self.assertIn(wanted, html)
        self.assertNotIn('%', html)
        self.assertEqual(self.js('workStage({})'), 'unknown')
        board = self.js('workBoard([t,c])', '\nvar t=' + json.dumps(t) + ';var c=' + json.dumps(dict(t, plan='P2', selector='plan:P2', situation=dict(t['situation'], stage='closed', label='Đã đóng'))) + ';')
        self.assertIn('closed-fold', board); self.assertNotIn('data-stage="attn"', board)
        lost = self.js('workBoard([u])', '\nvar u=' + json.dumps(dict(t, situation=dict(t['situation'], stage='unknown', label='Chưa xác định'))) + ';')
        self.assertIn('data-stage="attn"', lost)                                                # an unknown task is shown apart from closed ones

    def test_progress_lists_every_milestone_and_draws_no_axis_without_times(self):
        c = {'revision': 1, 'timed': False, 'rows': [{'id': 'M1', 'title': 'A', 'state': 'passed', 'label': 'Đạt', 'checks': [{'result': 'pass', 'state': 'done', 'recorded': '2026-11-13T01:00:00Z'}], 'failures': 0, 'check_seconds': None},
                                                      {'id': 'M2', 'title': 'B', 'state': 'pending', 'label': 'Chưa kiểm', 'checks': [], 'failures': 0, 'check_seconds': None}]}
        d = {'plan': 'P1', 'milestone_checks': c, 'situation': {'stage': 'doing', 'label': 'Đang thực hiện', 'milestones': {'text': 'Đạt 1/2 mốc', 'note': 'số mốc đạt, không phải phần trăm công việc'}}}
        html = self.js('msProgress(d)', '\nvar d=' + json.dumps(d) + ';')
        self.assertIn('data-k="ms:M1"', html); self.assertIn('data-k="ms:M2"', html); self.assertIn('msnotime', html)
        self.assertNotIn('gaxis', html)
        c['timed'] = True; c['rows'][0]['checks'][0].update(started='2026-11-13T01:00:00Z', ended='2026-11-13T01:03:00Z', seconds=180)
        html = self.js('msProgress(d)', '\nvar d=' + json.dumps(d) + ';')
        self.assertIn('gaxis', html); self.assertIn('seg chk pass', html); self.assertIn('chưa kiểm', html)
        self.assertIn('không phải thời gian chờ hay thời gian làm việc', html)

    def test_axis_end_label_never_sits_on_the_last_tick(self):
        for span in (417000, 60500, 3900, 7260000, 1000, 86400000 * 2.3):
            ticks = self.js('gTicks({w0:0,w1:%d})' % span)
            pcts = [t['pct'] for t in ticks]
            self.assertEqual(pcts[-1], 100, span)
            gaps = [b - a for a, b in zip(pcts, pcts[1:])]
            self.assertGreaterEqual(min(gaps), 15, (span, ticks))
            self.assertEqual(len({t['label'] for t in ticks}), len(ticks), span)

    def test_times_are_24_hour(self):
        self.assertNotRegex(self.js("when('2026-11-13T15:04:05Z')"), r'(?i)\b(am|pm|SA|CH)\b')
