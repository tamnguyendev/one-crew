"""Fast view acceptance tests; browser and installed artifact are separate checks."""
import json
import shutil
import subprocess
import unittest

from onecrew.v2 import tracking_web
from onecrew.v2.tracking_work_web import SCRIPT


class WorkViews(unittest.TestCase):
    def render(self, tab, work, measure=None):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node needed for JS rendering acceptance; browser checks still required')
        # Only view helpers are substituted; the shipped renderer itself is run unchanged.
        prelude = r'''
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function hms(n){return typeof n==='number'?n+'s':'chưa xác định'}
function when(v){return v||'chưa xác định'}
function openBtn(k){return '<button data-evidence="'+esc(k)+'">Mở bằng chứng</button>'}
function gantt(d){return '<section class="gantt">Timeline dependency (tested separately)</section>'}
'''
        detail = {'status': {'kind': 'waiting', 'label': 'Đang chờ', 'reason': 'Cần trả lời'},
                  'current_step': 'Đối chiếu điều kiện đăng nhập', 'goal': 'Review đăng nhập',
                  'needs_user': [], 'eta': {'label': 'Chưa đủ dữ liệu'}, 'elapsed': {'seconds': 30},
                  'measure': measure or {}, 'evidence_keys': ['allowed'], 'work': work}
        code = prelude + SCRIPT + '\nworkTab=' + json.dumps(tab) + '; console.log(workDashboard(' + json.dumps(detail) + '));'
        result = subprocess.run([node, '-'], input=code, text=True, encoding='utf-8', capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_pending_solution_is_not_presented_as_authorized(self):
        out = self.render('solution', {'solution': {'latest_revision': 2, 'approved_revision': 1,
                         'effective_revision': 1, 'contract': {'goal': 'Read source'}, 'card': None}})
        self.assertIn('Có bản chưa được duyệt', out)
        self.assertIn('Bản có thể thực hiện', out)
        self.assertIn('không có SOL v1 liên kết', out)
        self.assertNotIn('Đã chốt bản 2', out)

    def test_old_approval_is_not_current_permission_when_stopped(self):
        out = self.render('solution', {'solution': {'latest_revision': 1, 'approved_revision': 1,
                         'effective_revision': 1, 'runnable_revision': None, 'contract': {}}})
        self.assertIn('Bản có thể thực hiện</div><div class="answer">chưa có dữ liệu', out)

    def test_missing_receipts_are_not_zero_bugs_or_success(self):
        out = self.render('results', {'outputs': [], 'checks': {}, 'findings': [], 'repairs': [], 'actors': []})
        self.assertIn('không thể kết luận không có lỗi', out)
        self.assertIn('Không coi mỗi attempt là một vòng sửa', out)
        self.assertIn('Không suy từ tên phiên chat', out)

    def test_per_output_evidence_and_stale_are_preserved(self):
        out = self.render('results', {'outputs': [
            {'title': 'Báo cáo cũ', 'artifact': 'allowed', 'level': 'verified', 'stale': True, 'generation': 0},
            {'title': 'Bản mới', 'artifact': 'not-authorized', 'level': 'produced', 'generation': 1}]})
        self.assertIn('Báo cáo cũ · Đã kiểm', out)
        self.assertIn('Bản mới · Đã tạo', out)
        self.assertIn('Bản cũ / cần kiểm lại', out)
        self.assertIn('data-evidence="allowed"', out)
        self.assertNotIn('data-evidence="not-authorized"', out)

    def test_hostile_diff_is_text_not_html(self):
        attack = '<img src=x onerror=alert(1)>'
        out = self.render('changes', {'changes': [{'id': 'a', 'kind': 'contract', 'reason': attack,
                    'diff': [{'path': attack, 'before': 'old', 'after': attack}]}]})
        self.assertNotIn('<img', out)
        self.assertIn('&lt;img', out)
        self.assertIn('Trước', out)
        self.assertIn('Sau', out)

    def test_assignment_and_execution_remain_distinct(self):
        out = self.render('results', {'actors': [
            {'role': 'assigned', 'node': 'C', 'provider': 'claude', 'model': 'pinned'},
            {'role': 'executed', 'node': 'C', 'provider': None, 'model': None}],
            'nodes': {'C': {'title': 'Đọc hợp đồng'}}})
        self.assertIn('Được giao', out)
        self.assertIn('Đã thực hiện', out)
        self.assertIn('chưa có dữ liệu', out)
        self.assertIn('Đọc hợp đồng (C)', out)

    def test_navigation_has_named_panels_and_unknown_eta(self):
        out = self.render('overview', {'outputs': [], 'findings': []})
        for title in ('Tổng quan', 'Solution', 'Thay đổi', 'Kết quả & kiểm chứng', 'Tiến độ'):
            self.assertIn(title, out)
        self.assertIn('Chưa đủ dữ liệu', out)
        self.assertIn('aria-labelledby="work-tab-overview"', out)

    def test_the_summary_answers_the_five_questions_from_the_model(self):
        # 13/11: the current step left the Tổng quan cards for the summary above the tabs (sitPanel), worded by the model
        node = shutil.which('node')
        if not node: self.skipTest('Node needed for JS rendering acceptance')
        d = {'situation': {'stage': 'fix', 'label': 'Cần sửa', 'reason': 'Đối chiếu điều kiện đăng nhập không đạt', 'next': 'Sửa và kiểm lại mốc M2', 'next_by_text': 'Chưa có thông tin người xử lý',
                           'activity': {'running': False, 'text': 'Không có lượt chạy hay lần kiểm nào đang diễn ra trong sổ.'}},
             'needs_user': [], 'level': {'label': 'chưa có đầu ra'}, 'last_update': {'at': 'T1', 'summary': 'mốc M2 không đạt'}, 'generated_at': 'T2'}
        code = 'function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"}[c]))}function when(v){return v}function needTitle(n){return n.kind}\n' + SCRIPT + '\nconsole.log(sitPanel(' + json.dumps(d) + '));'
        out = subprocess.run([node, '-'], input=code, text=True, encoding='utf-8', capture_output=True, timeout=10).stdout
        for text in ('Đang ở đâu', 'Vướng gì', 'Ai làm tiếp', 'Bạn cần làm gì', 'Kết quả ở đâu', 'Cần sửa', 'Đối chiếu điều kiện đăng nhập không đạt',
                     'Sửa và kiểm lại mốc M2', 'Chưa có thông tin người xử lý', 'Không có quyết định nào đang chờ bạn. Điều này không có nghĩa là việc đang tiến triển.',
                     'Hoạt động cuối của việc: ', '>T1</time> · mốc M2 không đạt', 'Sổ đọc lúc T2'):
            self.assertIn(text, out)

    def test_solution_payload_is_visible_and_unavailable_payload_is_not(self):
        ref = {'id': 'SOL-1', 'revision': 3, 'status': 'available',
               'payload': {'brief': 'Chỉ ẩn menu', 'detail': 'Giữ service hiện hành', 'why': '<img src=x>'}}
        out = self.render('solution', {'solution': {'source_solution': ref}})
        self.assertIn('Chỉ ẩn menu', out)
        self.assertIn('Giữ service hiện hành', out)
        self.assertNotIn('<img', out)
        ref['status'] = 'unavailable'
        self.assertNotIn('Chỉ ẩn menu', self.render('solution', {'solution': {'source_solution': ref}}))

    def test_case_counts_and_finding_closure_have_evidence(self):
        out = self.render('results', {'checks': {'summary': {'unique_checks': 1, 'check_executions': 2,
            'testcases': {'unique': 3, 'executions': 6, 'pass': 4, 'fail': 1, 'skip': 1, 'error': 0, 'unknown': 0}},
            'runs': [{'node': 'C', 'testcases': [{'id': 'CASE-A', 'status': 'fail'}]}]},
            'findings': [{'id': 'RF1', 'status': 'resolved', 'source': {'receipt': 'allowed', 'verdict_seq': 11},
                          'resolution': {'receipt': 'forbidden', 'reason': 'Đã kiểm lỗi cũ'}}]})
        self.assertIn('3 / 6', out)
        self.assertIn('CASE-A: fail', out)
        self.assertIn('Đã kiểm lỗi cũ', out)
        self.assertIn('#11', out)
        self.assertIn('data-evidence="allowed"', out)
        self.assertNotIn('data-evidence="forbidden"', out)

    def test_historical_repair_links_checks_and_order_rebinding_is_not_new_round(self):
        out = self.render('results', {'checks': {'runs': [{'id': 'check:10', 'node': 'I', 'status': 'pass', 'receipt': 'allowed'}]},
            'repairs': [{'node': 'C', 'status': 'verified', 'applicable': False, 'affected_nodes': ['C', 'I'],
                         'verification': ['check:10'], 'rebindings': [{'id': 'rebind1'}]}]})
        self.assertIn('Vòng sửa lịch sử', out)
        self.assertIn('Kiểm lại sau sửa', out)
        self.assertIn('I · pass', out)
        self.assertIn('1 lần nối lại thứ tự', out)
        self.assertNotIn('Vòng sửa 2', out)

    def test_verified_rebinding_is_visible_inside_original_unverified_round(self):
        out = self.render('results', {'checks': {'runs': [{'id': 'new-proof', 'node': 'I', 'status': 'pass', 'receipt': 'allowed'}]},
            'repairs': [{'id': 'repair1', 'node': 'C', 'status': 'unverified', 'applicable': False,
                'rebindings': [{'status': 'verified', 'applicable': True, 'verification': ['new-proof']}]}]})
        self.assertIn('Nối lại 1 · Đã kiểm đủ · áp dụng hiện tại', out)
        self.assertIn('I · pass', out)
        self.assertIn('data-evidence="allowed"', out)
        self.assertNotIn('Vòng sửa 2', out)

    def test_time_between_output_and_check_is_not_claimed_as_active_test_duration(self):
        out = self.render('progress', {})
        self.assertIn('có thể gồm thời gian chờ trước kiểm', out)
        self.assertIn('thời gian chạy bộ kiểm và hàng đợi riêng đều chưa xác định', out)
        self.assertIn('không cộng đôi', out)

    def test_sourced_admission_and_preparation_remain_distinct_from_scheduler_queue(self):
        out = self.render('progress', {}, {'attempts': [{'node': 'C', 'attempt': 'ATT-abc', 'generation': 1,
            'admission_seconds': 3, 'preparation_seconds': 2, 'execution_seconds': 'unknown'}]})
        self.assertIn('<td>3s</td><td>2s</td><td>chưa xác định</td>', out)
        self.assertIn('chưa phải thời gian hàng đợi scheduler riêng', out)

    def test_empty_frozen_set_is_not_unknown(self):
        out = self.render('solution', {'solution': {'frozen': {'runnable': ['M1'], 'frozen': []}}})
        self.assertIn('phần chờ bản mới: không có', out)

    def test_shipping_page_includes_views_and_preserves_request_guards(self):
        page = tracking_web._page(2)
        self.assertNotIn('@@WORK_', page)
        self.assertIn('function workDashboard', page)
        self.assertIn('DETAIL_TIMEOUT=45000', page)
        self.assertIn('sameSel(detailInflight.sel,selected)', page)


if __name__ == '__main__':
    unittest.main()
