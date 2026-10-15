"""Prompt budget and paging under the provider cap (P5, after live task S1 of 14/10/2026 on 1ae7782).

S1 (TASK-04129bfc…, the SRM money formatter) was blocked at step 8: the fixed part of the work prompt (tool guide 4,424
characters, the work contract 6,120, environment, recovery, evidence) left ~600 of Kiro's 15,000 for the latest tool result, so
no page of a 2,761-character read ever fitted: the worker received 0 characters of the file in 7 results, asked for receipts of
receipts, and the core finally refused the prompt. These tests drive the real runtime (the real _work_prompt/_fit under the Kiro
cap, real reads in the isolated workspace) with a scripted worker that obeys the paging contract, and check that every character
arrives, in order, without a gap; that a job that cannot be served is refused before any model call; and that a normal job keeps
its full contract. Fixtures are temporary; no task, host or ledger of the machine is used."""
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import canonical
from onecrew.owned import Owned
from onecrew.owned_intake import submit
from tests.test_review_p3 import CAP, PagingFixture, context
from tests.test_work_contract import ACCEPT, action, python
from tests.test_workflow import FixtureWorker

VI_WORDS = ('định dạng', 'số tiền', 'đơn vị', 'làm tròn', 'nghìn', 'triệu', 'tỷ', 'đồng', 'phần thập phân', 'dấu chấm',
            'dấu phẩy', 'giá trị âm', 'ngân sách', 'hợp đồng', 'đề tài', 'kinh phí', 'quyết toán', 'giải ngân')


def vietnamese_source(size, marker):
    """A Dart-like source file with Vietnamese comments and strings, `size` characters, ending with a marker."""
    lines, total, n = ['/// Tiện ích định dạng số tiền cho các màn hình ngân sách (dữ liệu thử).\n'], 0, 0
    while total < size:
        word = VI_WORDS[n % len(VI_WORDS)]
        line = f"  // {n:04d}: {word} — kiểm tra “{word}” với giá trị {n * 1000}.\n" if n % 3 else \
               f"  static const t{n:04d} = '{word} {n} đồng';\n"
        lines.append(line); total += len(line); n += 1
    return ''.join(lines) + f'// {marker}\n'


def s1_contract(pad=0, **authority):
    """The shape of S1's contract: a long Vietnamese goal with environment notes, 8 detailed acceptance items, 5 preserve items,
    a command check (about 6,000 characters in the prompt, like S1's 6,120). pad: characters added to the check (never cut);
    300 makes its most compact prompt as large as the real S1 contract's (first-call margin ~30 on round 2)."""
    goal = ('Ứng dụng (package app/ của repo này): bộ định dạng tiền hiển thị sai phần rút gọn của số tiền ở các màn hình ngân '
            'sách và tài chính. Sửa theo các tiêu chí nghiệm thu, thêm test hồi quy, bàn giao trên nhánh local fix/money. ' * 11 +
            'Môi trường (đã đo trước khi giao): công cụ của nền tảng không chạy được trong ranh giới lệnh; chỉ trình thông dịch '
            'chạy trực tiếp một tệp là chạy được; kiểm chứng tự động là một chương trình độc lập. Quyết định của người dùng (đã '
            'chốt, không hỏi lại): không cấp quyền chạy lệnh ngoài ranh giới; không khai báo lệnh không chạy được trong finish.')
    acceptance = [f'C{i} ' + ('Tiêu chí chi tiết số ' + str(i) + ': đơn vị rút gọn chọn sau khi làm tròn 2 chữ số thập phân; '
                              'ví dụ formatDisplay(999999999) == "999.999.999 (1 tỷ đồng)", formatCompactWords(999994000) == '
                              '"999,99 triệu đồng"; số âm làm tròn về 0 hiển thị "0"; phần rút gọn nhóm nghìn bằng dấu chấm. ')
                  for i in range(1, 9)]
    preserve = ['Checkout của người dùng (main, sạch, 2 stash) và mọi nhánh khác giữ nguyên; không push, không tag',
                'Không sửa hoặc xoá test hiện có (test cũ và mọi test khác)',
                'Giữ nguyên API công khai (tên, tham số, kiểu trả về) và mọi hành vi không nêu trong tiêu chí',
                'Không đổi file nào ngoài các file trong scope', 'Mã mới hợp lệ với phiên bản ngôn ngữ của package']
    return {'schema_version': 1, 'goal': goal, 'acceptance': acceptance, 'preserve': preserve,
            'checks': [{'kind': 'command', 'argv': ['python', '-c', 'print(1)' + ('  # ' + 'kiểm tra ' * (pad // 9) if pad else '')], 'cwd': ''}],
            'authority': dict({'edit': True, 'commands': True, 'local_branches': ['fix/money']}, **authority),
            'authorized_by': {'source': 'user (fixture of the S1 shape)', 'reference': 'P5 regression: ' + 'lý do ' * 30}}


class PlanFollower(FixtureWorker):
    """Obeys the paging contract like test_review_p3.Follower: scripted first actions, then the `next` of the latest result's
    pages (or the tool's own cursor when a result arrives whole). It writes `plan` (a long plan models the growing history), and
    records the prompts, every latest_result and every delivered piece."""
    def __init__(self, ledger, first, plan='Follow the page continuation.'):
        super().__init__(ledger, [])
        self.first, self.plan, self.prompts, self.latest, self.pieces, self.done = list(first), plan, [], [], [], False

    def run(self, attempt, prompt, schema, profile):
        self.prompts.append((prompt, canonical(schema)))
        latest = context(prompt).get('latest_result') or {}
        self.latest.append(latest)
        result, pages = latest.get('result') or {}, latest.get('page') or []
        for page in pages:
            self.pieces.append({'action': latest.get('action'), 'field': page['field'], 'offset': page['offset'],
                                'value': result.get(page['field']), 'cursor': result.get('cursor'), 'page': page,
                                'path': result.get('path'), 'section': result.get('section'), 'index': result.get('index')})
        whole = None
        if not pages and isinstance(latest.get('result'), dict) and latest.get('action') in ('read', 'list', 'contract'):
            field = {'read': 'text', 'list': 'entries', 'contract': 'text'}[latest['action']]
            if latest['action'] != 'contract' and result.get('next_cursor') is not None:
                whole = {'action': latest['action'], 'arguments': {**{k: v for k, v in (latest.get('arguments') or {}).items()
                                                                      if k != 'cursor'}, 'cursor': result.get('next_cursor')}}
            self.pieces.append({'action': latest['action'], 'field': field, 'offset': 0, 'value': result.get(field),
                                'cursor': result.get('cursor'), 'page': {'eof': whole is None, 'whole': True},
                                'path': result.get('path'), 'section': result.get('section'), 'index': result.get('index')})
        value = self.decide(pages, whole)
        if isinstance(value, dict) and value.get('plan') == 'fixture': value = dict(value, plan=self.plan)
        self.calls.append('owned')
        self.control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        self.control.finish(attempt['id'], attempt['generation'], {'fixture': value})

    def decide(self, pages, whole):
        if self.first:
            value = self.first.pop(0)
            return value(self) if callable(value) else value  # a callable step needs the job's state (a file's hash)
        follow = next((p.get('next') for p in pages if p.get('next')), None) or whole
        if follow is None:
            self.done = True; follow = {'action': 'git_status', 'arguments': {}}
        return {'plan': self.plan, 'action': follow['action'], 'arguments': json.dumps(follow['arguments'])}


class FlowWorker(PlanFollower):
    """Follows every page of the latest result to its end, then takes its next scripted step; answers the completion review
    with `review` and records each review prompt."""
    def __init__(self, ledger, script, review):
        super().__init__(ledger, [])
        self.script, self.review, self.reviews = list(script), review, []

    def run(self, attempt, prompt, schema, profile):
        if not prompt.startswith('COMPLETION REVIEW'): return super().run(attempt, prompt, schema, profile)
        self.reviews.append((prompt, canonical(schema))); self.calls.append('owned_review')
        self.control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        self.control.finish(attempt['id'], attempt['generation'], {'fixture': self.review})

    def decide(self, pages, whole):
        value = super().decide(pages, whole)
        if self.done and self.script:  # every page is at its end: the next scripted step
            self.done = False
            step = self.script.pop(0)
            value = step(self) if callable(step) else step
        return value


class BudgetFixture(PagingFixture):
    def run_job(self, contract, first, steps=80, plan='Follow the page continuation.', worker=None):
        task = submit(self.ledger, None, 'budget-' + str(len(first)), mode='work', provider='kiro', model='claude-sonnet-5',
                      contract=contract)['id']
        worker = worker or PlanFollower(self.ledger, first, plan)
        runtime = Owned(self.ledger, worker); runtime.enable(task)
        worker.runtime, worker.task = runtime, task
        state = runtime.state(task)[1]
        for _ in range(steps):
            state = runtime.run(task, steps=1)
            if worker.done or state['phase'] != 'running': break
        for prompt, schema in worker.prompts:  # the real _fit kept every prompt within Kiro's cap
            self.assertLessEqual(len(prompt) + len(schema) + 40, CAP)
        return runtime, task, worker, state

    def ws_text(self, runtime, task, name):
        from onecrew import work_tools as wt
        return (wt.ws_root(runtime.state(task)[1]) / name).read_bytes().decode('utf-8-sig')

    def starved(self, worker):
        return [i for i, latest in enumerate(worker.latest) if latest.get('does_not_fit')]

    def delivered(self, worker, path):
        text, pieces = self.text_of(worker, path=path)
        return text, pieces


class PromptBudgetTests(BudgetFixture):
    def test_s1_shape_a_long_contract_still_delivers_the_whole_file(self):
        source = vietnamese_source(2700, 'KẾT-THÚC-TỆP')
        self.commit({'app/lib/utils/dinh_dang_tien.dart': source})
        runtime, task, worker, state = self.run_job(s1_contract(), [action('read', path='app/lib/utils/dinh_dang_tien.dart')])
        self.assertEqual(self.starved(worker), [], 'RED-P5: results did not fit: ' + str([l.get('note') for l in worker.latest]))
        text, pieces = self.delivered(worker, 'app/lib/utils/dinh_dang_tien.dart')
        self.assertEqual(text, self.ws_text(runtime, task, 'app/lib/utils/dinh_dang_tien.dart'), 'RED-P5: the worker did not receive the whole file')
        self.assertIn('KẾT-THÚC-TỆP', text)
        self.assertEqual(state['phase'], 'running', str(state.get('message')))
        self.assertLessEqual(len(worker.prompts), 6, 'a 2.7 KB file must not cost more than a few pages')
        first, later = context(worker.prompts[0][0])['work_contract'], context(worker.prompts[1][0])['work_contract']
        self.assertEqual(first['acceptance'], s1_contract()['acceptance'], 'the first prompt shows the full contract when it fits')
        self.assertIn('cut', later, 'later prompts cut long texts, each with a pointer to its full text')

    def test_a_growing_history_and_a_long_plan_still_leave_room_for_results(self):
        smalls = {f'docs/n{i:02d}.txt': f'ghi chú {i}: ' + 'nội dung ngắn. ' * 20 for i in range(25)}
        source = vietnamese_source(2700, 'KẾT-THÚC-TỆP')
        self.commit(dict(smalls, **{'app/lib/utils/dinh_dang_tien.dart': source}))
        plan = ('Kế hoạch: ' + 'đã đọc tệp, còn lại kiểm tra đơn vị rút gọn và số âm; ' * 90)[:4900]  # near the 5,000 limit
        first = [action('read', path=name) for name in smalls] + [action('read', path='app/lib/utils/dinh_dang_tien.dart')]
        runtime, task, worker, state = self.run_job(s1_contract(), first, plan=plan)
        self.assertEqual(self.starved(worker), [], 'RED-P5: results starved as history grew')
        text, _ = self.delivered(worker, 'app/lib/utils/dinh_dang_tien.dart')
        self.assertEqual(text, self.ws_text(runtime, task, 'app/lib/utils/dinh_dang_tien.dart'))
        self.assertEqual(state['phase'], 'running', str(state.get('message')))

    def test_a_large_vietnamese_file_arrives_whole_in_order_under_the_long_contract(self):
        source = vietnamese_source(30000, 'KẾT-THÚC-TỆP-LỚN')
        self.commit({'docs/lon.dart': source})
        runtime, task, worker, state = self.run_job(s1_contract(), [action('read', path='docs/lon.dart')], steps=120)
        self.assertEqual(self.starved(worker), [])
        text, pieces = self.delivered(worker, 'docs/lon.dart')  # text_of fails on any gap or overlap
        self.assertEqual(text, self.ws_text(runtime, task, 'docs/lon.dart'), 'RED-P5: the large file was not delivered whole and in order')
        self.assertTrue(pieces[-1]['page']['eof'])
        self.assertLessEqual(len(pieces), 35, 'pages must carry real content, not slivers: ' + str([len(p['value']) for p in pieces]))

    def test_receipts_of_receipts_point_at_the_original_and_do_not_grow(self):
        source = vietnamese_source(2700, 'KẾT-THÚC-TỆP')
        self.commit({'app/lib/utils/dinh_dang_tien.dart': source})
        first = [action('read', path='app/lib/utils/dinh_dang_tien.dart'), action('receipt', index=0), action('receipt', index=1),
                 action('receipt', index=2)]
        runtime, task, worker, state = self.run_job(s1_contract(), first, steps=4)
        receipts = runtime.state(task)[1]['receipts']
        records = [json.loads(runtime.store.read_blob(r['blob'])) for r in receipts]
        sizes = [len(canonical(r)) for r in records[1:4]]
        self.assertEqual(len(set(sizes)), 1, 'RED-P5: each receipt of a receipt wraps the previous one: ' + str(sizes))
        self.assertTrue(all(r['arguments']['index'] == 0 for r in records[1:4]), 'a lookup names the original result')
        self.assertTrue(all((l.get('shows_receipt') in (None, 0)) for l in worker.latest[1:]))

    def test_a_contract_that_cannot_be_served_is_refused_before_any_model_call(self):
        # Scope, checks and authority are never cut (they decide what is permitted and verified): checks this long cannot fit.
        contract = s1_contract()
        contract['checks'] = [{'kind': 'command', 'argv': ['python', '-c'] + [f'print("kiểm tra {j} {i}")' + ' ' * 160 for i in range(30)],
                               'cwd': ''} for j in range(3)]
        runtime, task, worker, state = self.run_job(contract, [action('list', directory='')])
        self.assertEqual(state['phase'], 'blocked')
        self.assertEqual(worker.calls, [], 'no model call may be spent on a job that cannot be served')
        self.assertIn('Prompt budget', state['message'], 'RED-P5: the refusal does not say what does not fit: ' + state['message'])
        self.assertRegex(state['message'], r'work contract \(\d+ characters|work_contract \d+', 'the refusal names the contract size')
        self.assertRegex(state['message'], r'checks \d+', 'and the part that takes the room (checks are never cut)')
        self.assertEqual((state.get('recovery') or {}).get('kind'), 'prompt_budget')

    def test_a_result_no_valid_page_can_show_is_refused_before_the_next_call_naming_the_part(self):
        # Refined P5 spec: never a prompt whose latest result is a "does not fit" note; the job stops before the call instead.
        self.commit({'docs/a.txt': 'a\n'})
        real = Owned._work_tool
        def tool(self_, task_id, state, name, args, profile):
            if name == 'list':  # a result whose non-pageable part (a nested object) is larger than any page
                return {'directory': '', 'meta': {f'k{i:03d}': 'giá trị ' * 8 for i in range(90)}, 'entries': []}
            return real(self_, task_id, state, name, args, profile)
        with patch.object(Owned, '_work_tool', tool):
            runtime, task, worker, state = self.run_job(s1_contract(), [action('list', directory='')], steps=4)
        self.assertEqual(len(worker.calls), 1, 'RED-P5: a prompt without the result was sent: ' + str([l.get('note') for l in worker.latest]))
        self.assertEqual(self.starved(worker), [])
        self.assertEqual(state['phase'], 'blocked')
        self.assertEqual((state.get('recovery') or {}).get('kind'), 'prompt_budget')
        self.assertIn('Prompt budget', state['message']); self.assertIn('receipt 0, list', state['message'])
        self.assertRegex(state['message'], r'meta \d+ chars', 'the part that cannot be paged is named')
        self.assertIn('Nothing was sent to the model', state['message'])

    def test_context_that_grows_past_the_cap_mid_job_is_refused_before_its_call(self):
        self.commit({'docs/a.txt': 'a\n'})
        from onecrew import entry
        first = [action('read', path='docs/a.txt')]
        def notes(worker):  # five long entry notes arrive while the job runs (shown whole, as untrusted context)
            for i in range(5):
                entry.note(self.ledger, worker.task, entry.connect(self.ledger, worker.task)['revision'], f'n{i}', 'decision',
                           f'ghi chú {i}: ' + 'nội dung dài của người dùng. ' * 64, 'fixture', 'P5 growth')
            return action('read', path='docs/a.txt')
        runtime, task, worker, state = self.run_job(s1_contract(), first + [notes, action('list', directory='')], steps=5)
        self.assertEqual(len(worker.calls), 2, 'RED-P5: a call was made with a prompt that cannot carry its context')
        self.assertEqual(state['phase'], 'blocked'); self.assertEqual(state['recovery']['kind'], 'prompt_budget')
        self.assertRegex(state['message'], r'entry_notes_untrusted \d+', 'the part that grew is named: ' + state['message'])

    def test_a_command_result_with_many_fields_gives_its_output_real_room(self):
        self.commit({'docs/a.txt': 'a\n'})
        from tests.test_work_contract import python
        script = ("import sys; print('dong ket qua ' * 300 + 'KET-THUC-STDOUT'); "
                  "sys.stderr.write('loi chi tiet ' * 150 + 'KET-THUC-STDERR'); sys.exit(1)")
        runtime, task, worker, state = self.run_job(s1_contract(), [action('run', argv=[python(), '-c', script])], steps=2)
        latest = worker.latest[1]
        self.assertFalse(latest.get('does_not_fit'), 'RED-P5: ' + str(latest.get('note')))
        stdout = (latest.get('result') or {}).get('stdout') or ''
        self.assertIn('KET-THUC-STDOUT', stdout, 'the end of the output, where the outcome is, arrives first')
        self.assertGreaterEqual(len(stdout), 1000, 'RED-P5: the command output arrived as a sliver: ' + str(len(stdout)))

    def test_s1_contract_after_a_failed_core_verification_the_worker_gets_a_repair_step(self):
        source = vietnamese_source(2700, 'KẾT-THÚC-TỆP')
        self.commit({'app/lib/utils/dinh_dang_tien.dart': source})
        from tests.test_work_contract import python
        fail = "import sys; sys.stderr.write('AssertionError: formatCompactWords(999994000) expected 999,99 trieu dong ' * 14); sys.exit(1)"
        first = [action('read', path='app/lib/utils/dinh_dang_tien.dart'),
                 action('finish', report='Đã kiểm C1..C8 theo receipt 0.', setup=[], verification=[{'argv': [python(), '-c', fail], 'cwd': ''}]),
                 action('list', directory='')]
        runtime, task, worker, state = self.run_job(s1_contract(), first, steps=4)
        self.assertEqual(state['phase'], 'running', 'RED-P5: blocked right after the first failed verification: ' + str(state.get('message')))
        self.assertGreaterEqual(len(worker.prompts), 3)
        repair = context(worker.prompts[2][0])
        self.assertIn('Independent core verification failed', json.dumps(repair, ensure_ascii=False))
        self.assertFalse((repair.get('latest_result') or {}).get('does_not_fit'))

    def test_a_rejected_finish_with_long_feedback_keeps_a_normal_job_running(self):
        # Review of the P5 draft: a 1,056-character contract was blocked after a 2,000-character review rejection (regression).
        self.commit({'docs/a.txt': 'a\n'})
        from tests.test_work_contract import python
        contract = self.contract(edit=True, commands=True)
        reject = {'accepted': False, 'evidence_requests': [],
                  'feedback': ('C1 is not shown by any receipt; the report claims more than the diffs support. ' * 30)[:2000]}
        first = [action('write', path='new_file.txt', expected_sha256=None, text='// stub\n'),
                 action('finish', report='Implemented; see receipt 0.', verification=[{'argv': [python(), '-c', 'print(1)'], 'cwd': ''}]),
                 reject, action('list', directory='')]
        runtime, task, worker, state = self.run_job(contract, first, steps=5)
        self.assertEqual(state['phase'], 'running', str(state.get('message')))
        after = [context(p) for p, _ in worker.prompts if not p.startswith('COMPLETION')][-1]
        self.assertEqual(after['latest_review_feedback'][0]['feedback'], reject['feedback'])

    def test_an_item_offset_past_the_end_is_refused_when_asked_and_the_job_goes_on(self):
        self.commit({'docs/a.txt': 'a\n'})
        real = Owned._work_tool
        def tool(self_, task_id, state, name, args, profile):
            if name == 'list':
                return {'directory': '', 'entries': [{'path': 'x' * 25000, 'kind': 'file'}], 'next_cursor': None}
            return real(self_, task_id, state, name, args, profile)
        first = [action('list', directory=''), action('receipt', index=0, field='entries', offset=0, item_offset=99999),
                 action('read', path='docs/a.txt')]
        with patch.object(Owned, '_work_tool', tool):
            runtime, task, worker, state = self.run_job(self.contract(edit=True, commands=True), first, steps=4)
        receipts = runtime.state(task)[1]['receipts']
        self.assertFalse(receipts[1]['successful'], 'RED-P5: a request past the end of the item was stored as a page')
        self.assertEqual(state['phase'], 'running', str(state.get('message')))

    def test_a_finish_whose_report_the_review_cannot_carry_is_sent_back_to_shorten(self):
        self.commit({'docs/a.txt': 'a\n'})
        from tests.test_work_contract import python
        report = 'Báo cáo rất dài với chi tiết từng tiêu chí và từng receipt. ' * 220
        first = [action('write', path='new_file.txt', expected_sha256=None, text='// stub\n'),
                 action('finish', report=report, verification=[{'argv': [python(), '-c', 'print(1)'], 'cwd': ''}]),
                 action('list', directory='')]
        runtime, task, worker, state = self.run_job(s1_contract(), first, steps=4)
        self.assertEqual(state['phase'], 'running', 'RED-P5: a long report blocked the job: ' + str(state.get('message')))
        self.assertFalse(any(p.startswith('COMPLETION') for p, _ in worker.prompts), 'no review call for a finish it cannot carry')
        self.assertIn('Shorten the report', json.dumps(context(worker.prompts[-1][0]), ensure_ascii=False))

    def test_a_fallback_chain_to_kiro_is_checked_before_the_first_call(self):
        from onecrew.model_preferences import save
        save(self.ledger, 'claude', 'sonnet', fallbacks=[{'provider': 'kiro', 'model': 'claude-sonnet-5'}])
        contract = s1_contract()
        contract['checks'] = [{'kind': 'command', 'argv': ['python', '-c'] + [f'print("kiểm tra {j} {i}")' + ' ' * 160 for i in range(30)],
                               'cwd': ''} for j in range(3)]
        task = submit(self.ledger, None, 'fallback-chain', mode='work', contract=contract)['id']
        worker = PlanFollower(self.ledger, [action('list', directory='')])
        runtime = Owned(self.ledger, worker); runtime.enable(task)
        state = runtime.run(task, steps=1)
        self.assertEqual(worker.calls, [], 'RED-P5: calls were spent on a job its kiro fallback can never carry')
        self.assertEqual(state['phase'], 'blocked'); self.assertIn('kiro', state['message'])

    def test_a_cut_contract_item_is_returned_whole_by_the_contract_action(self):
        contract = s1_contract()
        contract['acceptance'][3] = 'C4 ' + 'Kỳ vọng nguyên văn: "1.234.567.890.123 (1.234,57 tỷ đồng)". ' * 12 + 'HẾT-C4'
        self.commit({'docs/a.txt': 'a\n'})
        runtime, task, worker, state = self.run_job(contract, [action('read', path='docs/a.txt'),
                                                               action('contract', section='acceptance', index=3)], steps=8)
        self.assertGreaterEqual(len(worker.prompts), 2, 'RED-P5: the job stopped before the worker was asked again: '
                                + str(state.get('message')))
        shown = context(worker.prompts[1][0])['work_contract']
        self.assertIn('…[cut:', json.dumps(shown, ensure_ascii=False), 'RED-P5: the long item was not shown cut with a pointer')
        self.assertIn('contract', shown.get('cut', ''))
        pieces = [p for p in worker.pieces if p['action'] == 'contract']
        self.assertEqual(''.join(p['value'] for p in pieces), contract['acceptance'][3], 'the full item text, exactly')

    def test_the_completion_review_must_carry_the_full_contract_or_the_job_is_refused_first(self):
        contract = s1_contract()
        contract['acceptance'] = [f'C{i} ' + 'Tiêu chí dài cần nguyên văn khi review hoàn tất. ' * 13 for i in range(20)]
        runtime, task, worker, state = self.run_job(contract, [action('list', directory='')])
        self.assertEqual(worker.calls, [], 'a job whose completion review cannot fit is refused before it spends calls')
        self.assertIn('completion review', state['message'], 'RED-P5: ' + state['message'])

    def test_other_shape_long_english_contract_and_a_300_entry_listing(self):
        names = {f'data/item_{i:03d}.json': '{}\n' for i in range(300)}
        self.commit(names)
        contract = {'schema_version': 1,
                    'goal': 'Normalise every data file listed under data/ and report the result per file. ' * 34,
                    'acceptance': ['Every file under data/ is listed in the report with its size, checksum and normalised form. ' * 3] * 6,
                    'preserve': ['Keep every other file of the repository unchanged, including generated outputs and caches. ' * 2] * 8,
                    'authority': {'edit': True, 'commands': True}, 'authorized_by': {'source': 'user', 'reference': 'fixture ' * 40}}
        runtime, task, worker, state = self.run_job(contract, [action('list', directory='data')], steps=120)
        self.assertEqual(self.starved(worker), [])
        listed = [e['path'] for p in worker.pieces if p['field'] == 'entries' for e in (p['value'] or [])]
        self.assertEqual(listed, sorted(names), 'RED-P5: entries lost or repeated across pages under the long contract')
        self.assertLessEqual(len(worker.prompts), 20, 'RED-P5: 300 entries paged in slivers cost ' + str(len(worker.prompts)) + ' calls')

    def test_escape_heavy_text_is_paged_and_concatenates_to_the_exact_file(self):
        # Quotes, backslashes, tabs, control characters and markup cost several JSON characters each: pages are cut by the
        # encoded size, never inside an escape, and nothing is lost or repeated.
        unit = 'chuỗi "trích dẫn" \\ gạch ngược \\\\ \t tab \x01\x1f điều khiển </script> {"json": [1, 2]} đồng\n'
        self.commit({'docs/thoat.txt': unit * 260 + 'KẾT-THÚC-THOÁT\n'})
        runtime, task, worker, state = self.run_job(s1_contract(), [action('read', path='docs/thoat.txt')], steps=120)
        self.assertEqual(self.starved(worker), [])
        text, pieces = self.delivered(worker, 'docs/thoat.txt')
        expected = self.ws_text(runtime, task, 'docs/thoat.txt')
        self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), hashlib.sha256(expected.encode()).hexdigest(),
                         'RED-P5: the escape-heavy file was not delivered exactly')
        self.assertTrue(pieces[-1]['page']['eof']); self.assertGreater(len(pieces), 2)

    def test_the_last_page_and_a_page_at_the_end_are_valid_and_the_job_goes_on(self):
        self.commit({'docs/lon.dart': vietnamese_source(9000, 'KẾT-THÚC-TỆP')})
        def at(back):
            return lambda w: action('receipt', index=0, field='text',
                                    offset=len(json.loads(w.runtime.store.read_blob(w.runtime.state(w.task)[1]['receipts'][0]['blob']))
                                               ['result']['text']) - back)
        first = [action('read', path='docs/lon.dart'), at(80), at(0), action('git_status')]
        runtime, task, worker, state = self.run_job(s1_contract(), first, steps=5)
        self.assertEqual(state['phase'], 'running', str(state.get('message')))
        tail, end = worker.latest[2], worker.latest[3]
        self.assertEqual((tail['page'][0]['delivered'], tail['page'][0]['eof']), (80, True), 'the last 80 characters are a valid last page')
        self.assertEqual(tail['result']['text'], self.ws_text(runtime, task, 'docs/lon.dart')[-80:])
        self.assertEqual((end['page'][0]['delivered'], end['page'][0]['eof']), (0, True), 'a page at the end says so; nothing is invented')


@unittest.skipIf(python() is None, 'needs a real Python interpreter on PATH')
class FullFlowTests(BudgetFixture):
    """Read -> edit -> test -> commit -> export -> finish -> completion review -> handover, through the real core paths under the
    Kiro cap with the S1-shape contract; only the model is scripted (it follows every page to its end before its next step). It
    proves the mechanism, not the model's autonomy."""

    def test_read_edit_test_review_and_handover_under_the_s1_shape_contract(self):
        py = python()
        source = vietnamese_source(9000, 'KẾT-THÚC-TỆP')
        self.commit({'app/lib/utils/dinh_dang_tien.dart': source})
        contract = s1_contract()
        contract['checks'] = [{'kind': 'command', 'argv': [py, '-c', 'print(1)'], 'cwd': ''}]
        path = 'app/lib/utils/dinh_dang_tien.dart'
        def edit(w):
            from onecrew import work_tools as wt
            data = (wt.ws_root(w.runtime.state(w.task)[1]) / path).read_bytes()
            return action('edit', path=path, expected_sha256=hashlib.sha256(data).hexdigest(), old='// KẾT-THÚC-TỆP', new='// KẾT-THÚC-ĐÃ-SỬA')
        check = ('import pathlib\ntext = pathlib.Path("app/lib/utils/dinh_dang_tien.dart").read_text(encoding="utf-8")\n'
                 'assert "KẾT-THÚC-ĐÃ-SỬA" in text\nprint(("so tien \\"1.234,57\\" \\\\ dat; " * 160) + "KET-QUA-CUOI")\n')
        verification = [{'argv': [py, 'kiem_tra_tien.py'], 'cwd': ''}]
        script = [action('read', path=path), edit, action('write', path='kiem_tra_tien.py', expected_sha256=None, text=check),
                  action('run', argv=[py, 'kiem_tra_tien.py']), action('workspace_commit', message='Sửa định dạng tiền (fixture)'),
                  action('export_branch', name='fix/money'),
                  action('finish', report='C1..C8: receipt 1 (edit), 3 (test passed); branch fix/money (5).', verification=verification)]
        worker = FlowWorker(self.ledger, script, ACCEPT)
        runtime, task, worker, state = self.run_job(contract, [], steps=120, worker=worker)
        self.assertEqual(state['phase'], 'completed', str(state.get('message')))
        self.assertEqual(self.starved(worker), [])
        text, _ = self.delivered(worker, path)  # every character of the file reached the worker, in order
        self.assertEqual(text, self.ws_text(runtime, task, path).replace('KẾT-THÚC-ĐÃ-SỬA', 'KẾT-THÚC-TỆP'))
        output = ''.join(p['value'] or '' for p in worker.pieces if p['action'] == 'run' and p['field'] == 'stdout')
        self.assertIn('KET-QUA-CUOI', output, 'the test output reached the worker')
        self.assertEqual(len(worker.reviews), 1, 'one completion review')
        review_prompt, review_schema = worker.reviews[0]
        self.assertLessEqual(len(review_prompt) + len(review_schema) + 40, CAP, 'the review prompt is within the cap')
        shown = context(review_prompt)['work_contract']
        self.assertEqual((shown['goal'], shown['acceptance'], shown['preserve']), (contract['goal'], contract['acceptance'], contract['preserve']),
                         'the completion review judges against the FULL contract')
        self.assertNotIn('cut', shown)
        self.assertTrue(self.git('rev-parse', 'refs/heads/fix/money').strip())
        handover = state['work']['handover']
        self.assertTrue(Path(handover['summary']).is_file())
        self.assertIn('KẾT-THÚC-ĐÃ-SỬA', Path(handover['patch']).read_text(encoding='utf-8'))
        for prompt, _ in worker.prompts:  # no prompt carried a note in place of its result
            self.assertNotIn('does_not_fit', prompt)

    def test_a_runner_restart_mid_paging_continues_at_the_next_page_with_the_same_counters(self):
        source = vietnamese_source(30000, 'KẾT-THÚC-TỆP-LỚN')
        self.commit({'docs/lon.dart': source})
        task = submit(self.ledger, None, 'restart', mode='work', provider='kiro', model='claude-sonnet-5', contract=s1_contract())['id']
        worker = PlanFollower(self.ledger, [action('read', path='docs/lon.dart')])
        runtime = Owned(self.ledger, worker); runtime.enable(task); worker.runtime, worker.task = runtime, task
        for _ in range(3): runtime.run(task, steps=1)
        real, crashed = Owned._tool, []
        def tool(self_, task_id, state, name, args, profile):
            if name == 'receipt' and not crashed:
                crashed.append(args); raise KeyboardInterrupt('runner stopped after the model answered, before the page')
            return real(self_, task_id, state, name, args, profile)
        with patch.object(Owned, '_tool', tool):
            with self.assertRaises(KeyboardInterrupt): runtime.run(task, steps=1)
        before, used = runtime.state(task)[1], runtime.control.status(task)['used_calls']
        self.assertIsNotNone(before['response'], 'the answered step is in the checkpoint')
        runtime = Owned(self.ledger, worker); worker.runtime = runtime  # a new runner process, from the durable checkpoint
        state = runtime.state(task)[1]
        self.assertEqual((state['step'], len(state['receipts']), state['progress']), (before['step'], len(before['receipts']), before['progress']))
        for _ in range(80):
            state = runtime.run(task, steps=1)
            if worker.done or state['phase'] != 'running': break
        self.assertEqual(state['phase'], 'running', str(state.get('message')))
        receipts = state['receipts']
        self.assertEqual(json.loads(runtime.store.read_blob(receipts[3]['blob']))['arguments'], crashed[0],
                         'the answered page request ran once after the restart, without a new model call')
        self.assertEqual(runtime.control.status(task)['used_calls'], len(worker.prompts), 'no call was repeated or lost')
        self.assertEqual(state['step'], len(receipts))
        text, pieces = self.delivered(worker, 'docs/lon.dart')  # fails on any gap or overlap at the restart
        self.assertEqual(text, self.ws_text(runtime, task, 'docs/lon.dart'))
        self.assertGreater(len(worker.prompts), used)


FAILING_CHECK = ('import sys\nsys.stdout.reconfigure(encoding="utf-8")\n'
                 'for i in range(%d): print("FAIL formatDisplay(999999999) case %%d: expected \\"999.999.999 (1 tỷ đồng)\\", got '
                 '\\"999.999.999 (1000 triệu đồng)\\"" %% i)\nprint("%d case(s) failed"); sys.exit(1)\n')


@unittest.skipIf(python() is None, 'needs a real Python interpreter on PATH')
class GrowthTests(BudgetFixture):
    """Review of round 2 (verified): the real S1 contract passed the first-call check and was then refused on its first repair
    step; core-added parts grew without bound; the review of a finish that cannot fit looped; contract fetches tripped the guard."""

    def test_real_s1_size_contract_repairs_after_a_failed_core_verification_and_rereads_the_file(self):
        py = python(); path = 'app/lib/utils/dinh_dang_tien.dart'
        source = vietnamese_source(2761, 'KẾT-THÚC-TỆP')
        self.commit({path: source, 'kiem_tra.py': FAILING_CHECK % (8, 8)})
        contract = s1_contract(pad=300)
        contract['checks'] = [{'kind': 'command', 'argv': [py, 'kiem_tra.py'], 'cwd': ''}]
        def edit(w):
            from onecrew import work_tools as wt
            data = (wt.ws_root(w.runtime.state(w.task)[1]) / path).read_bytes()
            return action('edit', path=path, expected_sha256=hashlib.sha256(data).hexdigest(), old='// KẾT-THÚC-TỆP', new='// KẾT-THÚC-TỆP (sửa)')
        plan = ('Đã đọc formatter; đã sửa chọn đơn vị sau làm tròn. Còn: số âm về 0, nhóm nghìn, chạy kiểm chứng C6. ' * 10)[:400]
        script = [action('read', path=path), edit,
                  action('finish', report='Đã sửa theo C1..C8 (receipt 0, 1).', setup=[], verification=[{'argv': [py, 'kiem_tra.py'], 'cwd': ''}]),
                  action('read', path=path), action('git_status')]
        worker = FlowWorker(self.ledger, script, ACCEPT); worker.plan = plan
        runtime, task, worker, state = self.run_job(contract, [], steps=20, worker=worker)
        self.assertEqual(state['phase'], 'running', 'RED-P5-R3: ' + str(state.get('message')))
        receipts = state['receipts']
        self.assertFalse(receipts[2]['successful'], 'the core verification failed (the repair situation)')
        reread = [p for p in worker.pieces if p['action'] in ('read', 'receipt') and p['field'] == 'text']
        start = max(i for i, p in enumerate(reread) if p['offset'] == 0 and (p['cursor'] or 0) == 0)
        text = ''.join(p['value'] for p in reread[start:])
        self.assertEqual(text, self.ws_text(runtime, task, path), 'the re-read file reached the worker whole, in order')

    def test_core_added_parts_stay_bounded_under_a_tight_cap(self):
        py = python()
        self.commit({'docs/a.txt': 'a\n'})
        first = []
        for i in range(4):  # stopped background processes accumulate
            first.append(action('run', argv=[py, '-c', f'import time; time.sleep({30 + i})'], background=True))
            first.append(lambda w: action('process', op='stop', id=next(k for k, v in w.runtime.state(w.task)[1]['work']['processes'].items()
                                                                        if v['status'] == 'running')))
        first.append(action('read', path='docs/a.txt'))
        try: runtime, task, worker, state = self.run_job(s1_contract(pad=300), first, steps=12)
        finally:
            from onecrew import work_tools as wt
            for task_id in list(wt._RUNNING): wt.stop_all(task_id, {'work': {}})
        self.assertEqual(state['phase'], 'running', str(state.get('message')))
        shown = context(worker.prompts[-1][0])['background_processes']
        self.assertLessEqual(len(canonical(shown)), 400, 'RED-P5-R3: stopped processes grew the prompt: ' + canonical(shown)[:300])
        self.assertEqual(shown['ended']['count'], 4)

    def test_a_review_that_cannot_fit_for_its_core_facts_blocks_once_before_any_call(self):
        # Review of round 2: the worker was told to shorten a 30-character report three times, then blocked as no_progress.
        py = python()
        self.commit({'docs/a.txt': 'a\n'})
        script = '; '.join(['import sys'] + [f"assert {i} + {i} == {2 * i}, 'case {i}'" for i in range(60)])[:1890]
        script = script[:script.rindex(';')]  # ~1,900 characters of one-line inline script (one argument)
        verification = [{'argv': [py, '-c', script + ' ' * j], 'cwd': ''} for j in range(3)]
        first = [action('write', path='new_file.txt', expected_sha256=None, text='// stub\n'),
                 action('finish', report='Xong; receipt 0.', verification=verification), action('list', directory='')]
        runtime, task, worker, state = self.run_job(self.contract(edit=True, commands=True), first, steps=6)
        self.assertFalse(any(p.startswith('COMPLETION') for p, _ in worker.prompts))
        self.assertEqual(state['phase'], 'blocked'); self.assertEqual(state['recovery']['kind'], 'prompt_budget', state['message'])
        self.assertIn('completion review', state['message'])
        self.assertEqual(len(worker.calls), 2, 'RED-P5-R3: finishes were sent back to shorten a report that is not the excess')

    def test_fetching_a_cut_contract_item_again_after_other_reads_is_not_a_repeat(self):
        contract = s1_contract()
        contract['acceptance'][2] = 'C3 ' + 'Kỳ vọng nguyên văn: "1.234.567.890.123 (1.234,57 tỷ đồng)". ' * 12 + 'HẾT-C3'
        self.commit({f'docs/t{i}.txt': f'tệp {i}\n' for i in range(3)})
        first = []
        for i in range(3):
            first += [action('read', path=f'docs/t{i}.txt'), action('contract', section='acceptance', index=2)]
        first.append(action('git_status'))
        runtime, task, worker, state = self.run_job(contract, first, steps=10)
        self.assertEqual(state['phase'], 'running', 'RED-P5-R3: ' + str(state.get('message')))
        fetched = [l for l in worker.latest if l.get('action') == 'contract']
        self.assertEqual(len(fetched), 3)
        self.assertTrue(all(l['result']['text'] == contract['acceptance'][2] for l in fetched))

    def test_a_long_plan_shown_cut_is_returned_whole_by_the_contract_action(self):
        self.commit({'docs/a.txt': 'a\n'})
        plan = ('Kế hoạch: ' + 'bước đã xong, bước còn lại, bằng chứng receipt; ' * 120)[:4900] + 'HẾT-KẾ-HOẠCH'
        # P5b (Codex review of P5): the asking response carries ANOTHER plan (a worker cannot repeat text it was never shown);
        # this test used to send the old plan back in the request, which hid that the core answered with the request's own plan.
        asking = 'Retrieve the previous plan before continuing.'
        first = [dict(action('read', path='docs/a.txt'), plan=plan), dict(action('contract', section='plan'), plan=asking)]
        runtime, task, worker, state = self.run_job(s1_contract(), first, steps=8, plan=plan)
        shown = context(worker.prompts[1][0])['plan']
        self.assertIn('contract plan', shown, 'the cut plan points at its full text')
        pieces = [p for p in worker.pieces if p['action'] == 'contract']
        self.assertEqual(''.join(p['value'] for p in pieces), plan, 'RED-P5-R3: the middle of the plan could not be recovered')

    def test_an_accepted_review_whose_finish_fails_in_the_core_is_shown_as_it_is(self):
        self.commit({'docs/a.txt': 'a\n'})
        accepted = dict(ACCEPT, feedback='Accepted. Keep for the report: C3 relies on receipt 0 only. ' * 3)
        first = [action('write', path='new_file.txt', expected_sha256=None, text='// stub\n'),
                 action('finish', report='Xong.', verification=[{'argv': [python(), '-c', 'print(1)'], 'cwd': ''}]),
                 accepted, action('git_status')]
        runtime, task, worker, state = self.run_job(s1_contract(), first, steps=4)
        after = [context(p) for p, _ in worker.prompts if not p.startswith('COMPLETION')][-1]
        self.assertEqual(after['latest_review_feedback'][0]['feedback'], accepted['feedback'],
                         'RED-P5-R3: an accepted review was replaced by a pointer to an error that does not contain it')

    def test_the_reviewer_and_an_uncapped_worker_see_an_earlier_rejection_whole(self):
        from onecrew.review_evidence import packet
        self.commit({'docs/a.txt': 'a\n'})
        reject = {'accepted': False, 'evidence_requests': [], 'feedback': ('C1 is not shown by any receipt. ' * 60)[:1800]}
        first = [action('write', path='new_file.txt', expected_sha256=None, text='// stub\n'),
                 action('finish', report='Implemented; see receipt 0.', verification=[{'argv': [python(), '-c', 'print(1)'], 'cwd': ''}]),
                 reject, action('git_status')]
        runtime, task, worker, state = self.run_job(self.contract(edit=True, commands=True), first, steps=4)
        state = runtime.state(task)[1]
        entry = lambda value: next(m for m in value['manifest'] if m['action'] == 'finish')
        self.assertIn(reject['feedback'], entry(packet(runtime, state))['error'], 'RED-P5-R3: the reviewer lost the earlier rejection')
        self.assertIn(reject['feedback'], entry(packet(runtime, state, worker=True))['error'])
        self.assertLessEqual(len(entry(packet(runtime, state, worker=True, compact=True))['error']), 340, 'the compact worker index is cut')

    def test_a_result_that_fits_whole_is_never_paged_for_the_partial_note(self):
        self.commit({'docs/vua.dart': vietnamese_source(1537, 'HẾT')})
        runtime, task, worker, state = self.run_job(s1_contract(), [action('read', path='docs/vua.dart')], steps=2)
        self.assertTrue(worker.latest[1].get('complete'), 'RED-P5-R3: a result that fits was paged: ' + str(worker.latest[1].get('page')))


class NormalJobControlTests(BudgetFixture):
    def test_a_normal_job_keeps_its_full_contract_and_gets_small_results_whole(self):
        self.commit({'docs/nho.txt': 'tệp nhỏ: định dạng số tiền\n'})
        contract = self.contract(edit=True, commands=True)
        runtime, task, worker, state = self.run_job(contract, [action('read', path='docs/nho.txt')], steps=3)
        shown = context(worker.prompts[0][0])['work_contract']
        self.assertNotIn('cut', shown); self.assertEqual(shown['acceptance'], contract['acceptance'])
        self.assertEqual(shown['goal'], contract['goal'])
        self.assertTrue(worker.latest[1].get('complete'))
        self.assertEqual(worker.latest[1]['result']['text'], self.ws_text(runtime, task, 'docs/nho.txt'))
