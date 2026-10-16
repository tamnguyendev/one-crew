"""P6: the life of a review finding, from the moment a reviewer reports it to the handover (Codex review of d5a0c43, R1-R3).

R1. A rejected review's findings used to go with the review: the next finish was reviewed by a reviewer that had never heard of them and
    an acceptance with no findings completed the job. R2. Only 12 findings were tracked per review; the reviewer could close the 12 and
    the 13th, reported and never recorded, did not block. R3. The text of a finding or a note was cut to 2,000 characters in the
    checkpoint, two findings sharing a prefix were one, and no protocol returned a stored finding by its id.

Now a finding is the JOB's: it is registered with a stable id and its whole text in the blob store, it stays open through rejections,
new reviews, candidate changes and runner restarts, it leaves "open" only through a recorded resolution that names evidence the
reviewer was given, and it is returned page by page, byte for byte, by the reviewer's own evidence requests (index "RF3" / "N2").

The model responses are scripted (a synthetic reviewer, a synthetic worker); the tools, the core, the paging, the checkpoint, the
Git commits and the real test runs on a temporary repository are the product's. Nothing here is a run with a real model: it shows
that the core keeps its rules, not that a real reviewer will find or close the right things."""
import hashlib
import json
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew import review_evidence
from onecrew.ledger import canonical
from onecrew.owned import Owned
from tests import test_review_p6 as p6
from tests.test_review_p3 import CAP
from tests.test_review_p5 import s1_contract, vietnamese_source
from tests.test_work_contract import action, python

PATH = p6.PATH
FIRST_MARK, SECOND_MARK = 'KẾT-THÚC-ĐÃ-SỬA', 'ĐÃ-XỬ-LÝ-SỐ-ÂM'
LONG_FINDING = (p6.DEFECT + '. ' + ('Chi tiết: phần làm tròn của số âm bị bỏ qua ở các nhánh rút gọn, kiểm tra lại từng nhánh. ' * 28)
                + 'KẾT-ĐUÔI-CỦA-LỖI-DÀI')  # ~2,700 characters, its tail is what a 2,000-character cut loses
LONG_NOTE = 'Ghi chú đã đọc: ' + ('đã đối chiếu từng tiêu chí với trang tệp vừa nhận. ' * 50) + 'KẾT-ĐUÔI-CỦA-GHI-CHÚ'  # ~2,600 characters


def last_index(ev, name):
    return max(m['index'] for m in ev['manifest'] if m['action'] == name)


def shown_index(ev, index):
    return (any(r['index'] == index for r in ev.get('full_receipts') or [])
            or any(e.get('index') == index and 'error' not in e for e in ev.get('requested_pages') or []))


def retrieval(ev, ident, field):
    """The next request for the whole text of finding/note `ident`: its first page, then the `next` of the page it was given; None
    when it has been delivered up to its end."""
    for entry in ev.get('requested_pages') or []:
        if entry.get('index') != ident: continue
        if entry.get('error'):  # not served this round (ask it alone), or there is no such finding/note (do not ask again)
            return {'index': ident, 'field': field, 'offset': 0, 'item_offset': 0} if entry.get('deferred') else None
        for page in entry.get('page') or []:
            nxt = page.get('next')
            if nxt and nxt['action'] == 'receipt':
                a = nxt['arguments']
                return {'index': a['index'], 'field': a.get('field'), 'offset': a.get('offset', 0), 'item_offset': a.get('item_offset', 0)}
        return None
    return {'index': ident, 'field': field, 'offset': 0, 'item_offset': 0}


class Reviewer:
    """A completion reviewer that knows only the prompt it is given (the verdict it reaches in the n-th review is scripted).
    verdict kinds:
      reject   (finding strings in `findings`; `note`: a note written in an evidence round before it decides) accepted=false;
      accept   accepts at once and reports and closes nothing (a reviewer that lost track of what was found);
      report   reads receipt 0, reports `count` findings and rejects;
      close    reads what it needs (receipt 0 to its end, or the latest `run` receipt), `retrieve`s whole texts by id, then closes
               every open_findings id it is shown (at most `limit`) citing that receipt with `how`, and accepts."""
    def __init__(self, *verdicts):
        self.verdicts, self.finished, self.sweep, self.noted, self.calls = list(verdicts), 0, 0, set(), 0

    def __call__(self, worker, prompt, ctx):
        verdict = self.verdicts[min(self.finished, len(self.verdicts) - 1)]
        reply = self.decide(verdict, ctx)
        self.calls += 1
        if not reply['evidence_requests']: self.finished += 1; self.sweep = 0; self.calls = 0
        return reply

    @staticmethod
    def ask(requests, note='NOTE: reading.'):
        return {'accepted': False, 'evidence_requests': requests, 'feedback': note, 'findings': [], 'resolved': []}

    def decide(self, v, ctx):
        ev, kind = ctx['evidence'], v['kind']
        if kind == 'accept':
            return {'accepted': True, 'evidence_requests': [], 'feedback': 'Accepted.', 'findings': [], 'resolved': []}
        if kind == 'reject':
            if v.get('note') and self.finished not in self.noted:  # the note is kept from an evidence round: always make one
                self.noted.add(self.finished); return self.ask([0], v['note'])
            return {'accepted': False, 'evidence_requests': [], 'feedback': v.get('feedback', 'C3 is not met.'),
                    'findings': list(v['findings']), 'resolved': []}
        if kind == 'report':
            if p6.evidence_text(ev, 0) is None: return self.ask([0])
            findings = [f'r0: lỗi {n}: ' + 'x' * v.get('size', 20) for n in range(v['count'])]
            return {'accepted': False, 'evidence_requests': [], 'feedback': 'Many defects.', 'findings': findings, 'resolved': []}
        if kind == 'close_blind':  # closes with a receipt that no prompt of this review carried
            unseen = [m['index'] for m in ev['manifest'] if not shown_index(ev, m['index'])]
            assert unseen, 'premise: some receipt is not in the prompt'
            ids = p6.finding_ids(ctx)
            cited = v['cite'] if 'cite' in v else unseen[-1]
            return {'accepted': True, 'evidence_requests': [], 'feedback': 'Accepted.', 'findings': [],
                    'resolved': [f"{ident}:{cited}:{v.get('how', 'it looks fine')}" for ident in ids]}
        if kind == 'relist':  # asks for the list of findings, closes one, asks for the same list again, then closes the rest
            listing = {'index': 'RF', 'field': 'open', 'offset': 0, 'item_offset': 0}
            ids = p6.finding_ids(ctx)
            if self.calls == 0: return self.ask([0], 'NOTE: reading the file')
            if self.calls == 1: return self.ask([listing], 'NOTE: listing')
            if self.calls == 2:
                return {'accepted': False, 'evidence_requests': [listing], 'feedback': 'NOTE: closed one, listing again',
                        'findings': [], 'resolved': [f'{ids[0]}:0:refuted by the file']}
            return {'accepted': True, 'evidence_requests': [], 'feedback': 'The rest is refuted too.', 'findings': [],
                    'resolved': [f'{i}:0:refuted by the file' for i in ids]}
        if kind == 'again':  # records a defect and asks for the same page again: no verdict is possible
            return {'accepted': False, 'evidence_requests': [0], 'feedback': 'NOTE: again', 'findings': list(v['findings']), 'resolved': []}
        if kind == 'invalid':  # reports a defect and asks for evidence that does not exist: the answer cannot be used
            self.finished += 1
            return {'accepted': False, 'evidence_requests': [999], 'feedback': 'NOTE: need receipt 999.', 'findings': list(v['findings']),
                    'resolved': []}
        if kind == 'reject_feedback':  # rejects in words only: findings is empty
            return {'accepted': False, 'evidence_requests': [], 'feedback': v['feedback'], 'findings': [], 'resolved': []}
        assert kind == 'close', kind
        # what a stateless reviewer finished in earlier rounds it carries in its notes (they come back as review_notes)
        done = [i for i, _ in v.get('retrieve', ()) if any(f'DONE {i}' in n for n in ctx.get('review_notes') or [])]
        asked_now = any(e.get('index') in {i for i, _ in v.get('retrieve', ())} for e in ev.get('requested_pages') or [])
        if v.get('together') and not done and not asked_now:  # every cut text at once: the room serves what it can, in order
            return self.ask([{'index': i, 'field': f, 'offset': 0, 'item_offset': 0} for i, f in v['retrieve']], 'NOTE: all of them')
        for ident, field in v.get('retrieve', ()):
            if ident in done: continue
            request = retrieval(ev, ident, field)
            if request: return self.ask([request], 'NOTE: ' + ' '.join(f'DONE {i}' for i in done))
            done.append(ident)  # its last page is in this prompt
        note = 'NOTE: ' + ' '.join(f'DONE {i}' for i in done)
        cite = v.get('cite', 0)
        if cite == 'run':
            cite = last_index(ev, 'run')
            if not shown_index(ev, cite): return self.ask([cite], note)
        else:
            if not any('DONE FILE' in n for n in ctx.get('review_notes') or []):  # it read the file in an earlier round of this review
                if p6.evidence_text(ev, cite) is None: return self.ask([cite], note)
                request = p6.next_request(ev, cite)
                if request and v.get('read_all', True): return self.ask([request], note)
            note += ' DONE FILE'
        ids = v.get('ids') or p6.finding_ids(ctx)[:v.get('limit')]
        resolved = [f"{ident}:{cite}:{v.get('how', 'the evidence shown refutes it')}" for ident in ids]
        if ctx.get('open_more') and v.get('sweep'):  # a window of the open findings: close it, ask for something new, see the next
            self.sweep += 1
            return {'accepted': False, 'evidence_requests': [{'index': 'RF', 'field': 'open', 'offset': self.sweep, 'item_offset': 0}],
                    'feedback': note, 'findings': [], 'resolved': resolved}
        return {'accepted': True, 'evidence_requests': [], 'feedback': v.get('feedback', 'Each closure rests on a receipt shown.'),
                'findings': [], 'resolved': resolved}


def rewrite(path, text):
    def step(w):
        from onecrew import work_tools as wt
        data = (wt.ws_root(w.runtime.state(w.task)[1]) / path).read_bytes()
        return action('write', path=path, expected_sha256=hashlib.sha256(data).hexdigest(), text=text)
    return step


def replace(path, old, new):
    def step(w):
        from onecrew import work_tools as wt
        data = (wt.ws_root(w.runtime.state(w.task)[1]) / path).read_bytes()
        return action('edit', path=path, expected_sha256=hashlib.sha256(data).hexdigest(), old=old, new=new)
    return step


def check_script(*marks):
    return ('import pathlib\ntext = pathlib.Path("app/lib/utils/dinh_dang_tien.dart").read_text(encoding="utf-8")\n'
            + ''.join(f'assert "{mark}" in text\n' for mark in marks) + 'print("xong")\n')


class LifecycleBase(p6.ReviewRoundsBase):
    def verification(self):
        return [{'argv': [python(), 'kiem_tra_tien.py'], 'cwd': ''}]

    def candidate_script(self, finishes=1, deliver=False):
        """Read the file, make a change with its own check, run it, (deliver it on fix/money,) finish `finishes` times unchanged.
        A job that delivered a branch before the review cannot take a later change of the candidate (the core refuses: the delivered
        branch no longer carries the verified candidate), so the flows that fix after a rejection do not deliver first."""
        report = 'C1..C8: receipt 0 (the file), 1 (edit), 3 (test passed); branch fix/money (5).'
        steps = [action('read', path=PATH), replace(PATH, '// KẾT-THÚC-TỆP', '// ' + FIRST_MARK),
                 action('write', path='kiem_tra_tien.py', expected_sha256=None, text=check_script(FIRST_MARK)),
                 action('run', argv=[python(), 'kiem_tra_tien.py'])]
        if deliver: steps += [action('workspace_commit', message='Sửa định dạng tiền (fixture)'), action('export_branch', name='fix/money')]
        return steps + [action('finish', report=report, verification=self.verification())] * finishes

    def fix_script(self, finishes=1):
        """After a rejection: a real change to the file and to its check, run, finish."""
        report = 'C1..C8: receipt 0 (the file), the fix and its test run (see the latest receipts).'
        return [replace(PATH, '// ' + FIRST_MARK, '// ' + FIRST_MARK + '\n// ' + SECOND_MARK),
                rewrite('kiem_tra_tien.py', check_script(FIRST_MARK, SECOND_MARK)),
                action('run', argv=[python(), 'kiem_tra_tien.py'])] + [action('finish', report=report, verification=self.verification())] * finishes

    def start(self, script, reviewer, size=8000):
        self.commit({PATH: vietnamese_source(size, 'KẾT-THÚC-TỆP')})
        self.addCleanup(Owned.PROMPT_LIMITS.update, dict(Owned.PROMPT_LIMITS))
        worker = p6.ReviewerWorker(self.ledger, script, reviewer)
        task = self.make_job(worker)
        return worker, task

    def drive(self, worker, task, until=None, steps=400):
        state = worker.runtime.state(task)[1]
        for _ in range(steps):
            state = worker.runtime.run(task, steps=1)
            if (until and until(state)) or state['phase'] != 'running': break
            if worker.done and not until: break
        for prompt, schema in list(worker.prompts) + list(worker.reviews):
            self.assertLessEqual(len(prompt) + len(schema) + 40, CAP, 'every prompt of the job is within the provider cap')
        return state

    @staticmethod
    def finishes(state):
        return [r for r in state['receipts'] if r['action'] == 'finish']

    def result_of(self, runtime, receipt):
        return json.loads(runtime.store.read_blob(receipt['blob']))['result']

    def register(self, runtime, task):
        return runtime.state(task)[1].get('review_register') or {'findings': [], 'notes': []}

    def whole(self, runtime, entry):
        return runtime.store.read_blob(entry['blob']).decode('utf-8')

    def assembled(self, worker, ident, field):
        """What the reviewer was given of finding/note `ident`, page by page, in delivery order, put back together."""
        text, position = '', 0
        for ctx, _ in worker.review_log:
            for entry in ctx['evidence'].get('requested_pages') or []:
                if entry.get('index') != ident: continue
                if entry.get('complete'): return entry['result'][field]
                for page in entry.get('page') or []:
                    if page['field'] != field: continue
                    self.assertEqual(page['offset'], position, f'{ident}: a page starts at {page["offset"]} after {position} characters')
                    piece = entry['result'][field]; text += piece; position += len(piece)
        return text


class FindingLifecycleFlowTests(LifecycleBase):
    """The mandatory flow, through the real core: the reviewer finds a defect and rejects; the worker finishes again with nothing
    resolved and is blocked again; the runner restarts and the finding, its id and its whole text are still there and retrievable;
    the worker fixes and runs the test; the reviewer receives the evidence and records the closing conclusion; the core completes
    and the handover agrees with the candidate, the test result and the status of the finding."""

    def test_reject_resend_restart_fix_close_complete(self):
        reviewer = Reviewer({'kind': 'reject', 'findings': ['r0: ' + LONG_FINDING], 'note': LONG_NOTE},
                            {'kind': 'accept'},  # the resend: this reviewer accepts and closes nothing
                            {'kind': 'close', 'cite': 'run', 'retrieve': [('RF1', 'claim'), ('N1', 'text')],
                             'how': 'the fix handles the negative amounts; receipt of the test run that checks the new marker'})
        worker, task = self.start(self.candidate_script(finishes=2) + self.fix_script(), reviewer)
        runtime = worker.runtime
        # 1. the reviewer finds a defect and rejects
        state = self.drive(worker, task, until=lambda s: len(self.finishes(s)) >= 1)
        self.assertEqual(state['phase'], 'running', str(state.get('message')))
        register = self.register(runtime, task)
        self.assertEqual([(f['id'], f['status']) for f in register['findings']], [('RF1', 'open')])
        self.assertEqual(self.whole(runtime, register['findings'][0]), 'r0: ' + LONG_FINDING, 'stored whole, as written')
        rejection = self.result_of(runtime, self.finishes(state)[0])
        self.assertIn('1 finding(s)', rejection['error'])
        self.assertLess(len(rejection['error']), 400, 'the error is one line; the long text is in findings, so they do not compete for room')
        self.assertEqual([(f['id'], f['claim']) for f in rejection['findings']], [('RF1', 'r0: ' + LONG_FINDING)],
                         'the worker is given the whole finding')
        candidate_1 = state['work']['verification']['candidate']
        # 2. the worker finishes again with nothing resolved: blocked again (the reviewer here would accept; the core does not)
        state = self.drive(worker, task, until=lambda s: len(self.finishes(s)) >= 2)
        self.assertEqual(state['phase'], 'running', 'RED-P6: ' + str(state.get('message')))
        self.assertEqual(len(self.finishes(state)), 2)
        self.assertTrue(all(not f['successful'] for f in self.finishes(state)))
        second = worker.review_log[-1]
        self.assertEqual(p6.finding_ids(second[0]), ['RF1'], 'the second review was told of the finding')
        self.assertTrue(second[1]['accepted'], 'premise: that reviewer accepted')
        self.assertFalse(state['reviews'][-1]['accepted'])
        self.assertEqual([(f['id'], f['status']) for f in state['reviews'][-1]['findings']], [('RF1', 'open')])
        self.assertEqual(state['work']['verification']['candidate'], candidate_1, 'premise: nothing changed between the two finishes')
        # 3. the runner restarts: the finding, its id and its whole text are in the checkpoint and the reviewer can retrieve them
        before = canonical(self.register(runtime, task))
        runtime = Owned(self.ledger, worker); worker.runtime = runtime
        self.assertEqual(canonical(self.register(runtime, task)), before)
        self.assertEqual(self.whole(runtime, self.register(runtime, task)['findings'][0]), 'r0: ' + LONG_FINDING)
        # 4-6. the worker fixes and runs the test, the reviewer closes with that evidence, the core completes
        state = self.drive(worker, task, until=lambda s: s['phase'] == 'completed')
        self.assertEqual(state['phase'], 'completed', str(state.get('message')))
        self.assertEqual(len(self.finishes(state)), 3)
        retrieved = self.assembled(worker, 'RF1', 'claim')
        self.assertEqual(retrieved, 'r0: ' + LONG_FINDING, 'the finding came back byte for byte through the reviewer protocol')
        self.assertEqual(self.assembled(worker, 'N1', 'text'), LONG_NOTE, 'and so did the note, written two reviews earlier')
        self.assertIn('KẾT-ĐUÔI-CỦA-LỖI-DÀI', retrieved)
        final = state['reviews'][-1]
        self.assertTrue(final['accepted'])
        self.assertEqual([(f['id'], f['status']) for f in final['findings']], [('RF1', 'resolved')])
        run_receipts = [r for r in state['receipts'] if r['action'] == 'run']
        resolution = final['findings'][0]['resolution']
        self.assertEqual(resolution['receipt'], run_receipts[-1]['index'], 'closed by the test run of the fix')
        self.assertEqual((resolution['kind'], resolution['candidate_changed']), ('new_evidence', True))
        # the handover agrees with the candidate it describes, the test result and the status of the finding
        summary = json.loads(Path(state['work']['handover']['summary']).read_text(encoding='utf-8'))
        candidate_2 = state['work']['verification']['candidate']
        self.assertNotEqual(candidate_1, candidate_2)
        self.assertEqual(summary['candidate'], candidate_2)
        view = summary['review_findings']
        self.assertEqual((view['tracked'], view['open'], view['resolved']), (1, 0, 1))
        self.assertEqual(view['findings'][0]['resolution']['candidate'], candidate_2)
        self.assertEqual(view['findings'][0]['candidate'], candidate_1, 'it was found on the first candidate')
        self.assertEqual(self.whole(runtime, {'blob': view['findings'][0]['blob']}), 'r0: ' + LONG_FINDING)
        patch_text = Path(state['work']['handover']['patch']).read_text(encoding='utf-8')
        self.assertIn(SECOND_MARK, patch_text, 'the patch handed over is the fixed candidate, not the rejected one')
        self.assertTrue(summary['verification'].get('commands'), 'the re-run of the check is in the handover')
        self.assertTrue(all(c['passed'] for c in summary['verification']['commands']))
        self.assertEqual(runtime.control.status(task)['used_calls'], len(worker.calls), 'no call lost or repeated')

    def test_control_a_job_with_nothing_found_completes_as_before(self):
        worker, task = self.start(self.candidate_script(), Reviewer({'kind': 'close', 'cite': 0}))
        state = self.drive(worker, task, until=lambda s: s['phase'] == 'completed')
        self.assertEqual(state['phase'], 'completed', str(state.get('message')))
        self.assertEqual(self.register(worker.runtime, task)['findings'], [])


class FindingGateTests(LifecycleBase):
    """The three bypasses of the Codex probe, and what must stay possible."""

    def test_reject_then_unchanged_finish_then_empty_acceptance_cannot_complete(self):
        # R1: review 1 accepted=false with findings=["r0: Unresolved defect C3"]; the same finish again; review 2 accepted, no findings
        reviewer = Reviewer({'kind': 'reject', 'findings': ['r0: Unresolved defect C3']}, {'kind': 'accept'})
        worker, task = self.start(self.candidate_script(finishes=2), reviewer)
        state = self.drive(worker, task, until=lambda s: len(self.finishes(s)) >= 2)
        self.assertEqual(state['phase'], 'running', f'RED-P6: completed over an unresolved finding ({state.get("message")})')
        self.assertEqual([(f['id'], f['status']) for f in self.register(worker.runtime, task)['findings']], [('RF1', 'open')])
        self.assertEqual(p6.finding_ids(worker.review_log[1][0]), ['RF1'], 'the second prompt carries the open finding')
        self.assertIn('RF1', self.result_of(worker.runtime, self.finishes(state)[1])['error'])
        self.assertFalse(state['reviews'][-1]['accepted'], 'the review is recorded as the rejection the core made of that acceptance')

    def test_a_valid_resolution_completes_and_both_outcomes_survive_a_checkpoint_reload(self):
        reviewer = Reviewer({'kind': 'reject', 'findings': ['r0: Unresolved defect C3']}, {'kind': 'accept'}, {'kind': 'close', 'cite': 0})
        worker, task = self.start(self.candidate_script(finishes=3), reviewer)
        state = self.drive(worker, task, until=lambda s: len(self.finishes(s)) >= 2)
        self.assertEqual(state['phase'], 'running')
        worker.runtime = Owned(self.ledger, worker)  # reload: the open finding comes from the checkpoint
        self.assertEqual([f['status'] for f in self.register(worker.runtime, task)['findings']], ['open'])
        state = self.drive(worker, task, until=lambda s: s['phase'] == 'completed')
        self.assertEqual(state['phase'], 'completed', str(state.get('message')))
        worker.runtime = Owned(self.ledger, worker)
        self.assertEqual([f['status'] for f in self.register(worker.runtime, task)['findings']], ['resolved'])

    def test_a_wrong_finding_is_closed_with_evidence_and_no_code_change(self):
        reviewer = Reviewer({'kind': 'reject', 'findings': ['r0: the rounding of negative amounts is ignored']},
                            {'kind': 'close', 'cite': 0, 'how': 'the file read in this review has no such path; the finding was wrong'})
        worker, task = self.start(self.candidate_script(finishes=2, deliver=True), reviewer)  # delivered: nothing changes after it
        state = self.drive(worker, task, until=lambda s: s['phase'] == 'completed')
        self.assertEqual(state['phase'], 'completed', str(state.get('message')))
        resolution = state['reviews'][-1]['findings'][0]['resolution']
        self.assertEqual((resolution['kind'], resolution['candidate_changed']), ('earlier_evidence', False),
                         'closed on the candidate it was found on: the reviewer was wrong, the work did not change')
        self.assertEqual([r['action'] for r in state['receipts']].count('edit'), 1, 'no edit was made after the rejection')

    def not_completed(self, label, second):
        reviewer = Reviewer({'kind': 'reject', 'findings': ['r0: Unresolved defect C3']}, second)
        worker, task = self.start(self.candidate_script(finishes=2), reviewer)
        state = self.drive(worker, task, until=lambda s: len(self.finishes(s)) >= 2)
        self.assertEqual(state['phase'], 'running', f'RED-P6: {label}: ' + str(state.get('message')))
        self.assertEqual(len(self.finishes(state)), 2)
        self.assertTrue(worker.review_log[-1][1]['accepted'], 'premise: the reviewer accepted with a closure that is not evidence')
        self.assertFalse(state['reviews'][-1]['accepted'])
        self.assertEqual([f['status'] for f in self.register(worker.runtime, task)['findings']], ['open'])
        self.assertIn('RF1', self.result_of(worker.runtime, self.finishes(state)[1])['error'])
        return worker, task

    def test_a_closure_citing_a_receipt_the_review_was_never_shown_does_not_complete(self):
        worker, task = self.not_completed('unseen receipt', {'kind': 'close_blind'})
        found = self.register(worker.runtime, task)['findings'][0]
        self.assertIn('was not shown in this review', found['closure_refused'])

    def test_a_closure_without_a_reason_does_not_complete(self):
        self.not_completed('no reason', {'kind': 'close', 'cite': 0, 'how': ''})

    def test_a_closure_of_an_id_that_is_not_an_open_finding_does_not_complete(self):
        self.not_completed('unknown id', {'kind': 'close', 'cite': 0, 'ids': ['RF9']})

    def test_a_finding_the_reviewer_reports_again_is_one_finding_through_every_review(self):
        reviewer = Reviewer({'kind': 'reject', 'findings': ['r0: Unresolved defect C3']},
                            {'kind': 'reject', 'findings': ['Unresolved   defect C3', 'r0: Unresolved defect C3']})
        worker, task = self.start(self.candidate_script(finishes=2), reviewer)
        state = self.drive(worker, task, until=lambda s: len(self.finishes(s)) >= 2)
        self.assertEqual([f['id'] for f in self.register(worker.runtime, task)['findings']], ['RF1'])
        self.assertEqual(state['phase'], 'running')


class FindingUnusableAnswerTests(LifecycleBase):
    """What a reviewer reported binds even when the answer that carried it could not be used, and even when it rejected in words."""

    def test_an_answer_with_an_invalid_evidence_request_still_registers_its_findings(self):
        # the answer reports a defect and asks for receipt 999; the provider-failure handler asks the reviewer again, and that reviewer
        # accepts with nothing: before, the defect existed only in the discarded answer and the job completed
        reviewer = Reviewer({'kind': 'invalid', 'findings': ['r0: số âm bị bỏ qua (C3)']}, {'kind': 'accept'})
        worker, task = self.start(self.candidate_script(finishes=1), reviewer)
        state = self.drive(worker, task, until=lambda s: len(self.finishes(s)) >= 1)
        self.assertEqual(state['phase'], 'running', f'RED-P6: completed over a reported defect ({state.get("message")})')
        self.assertEqual([(f['id'], f['status']) for f in self.register(worker.runtime, task)['findings']], [('RF1', 'open')])
        self.assertTrue(worker.review_log[-1][1]['accepted'], 'premise: the reviewer asked again accepted')
        self.assertEqual(p6.finding_ids(worker.review_log[-1][0]), ['RF1'], 'and it was told of the finding')

    def test_a_rejection_in_words_only_is_a_finding_that_an_unchanged_finish_cannot_forget(self):
        reviewer = Reviewer({'kind': 'reject_feedback', 'feedback': 'C3 is not met: the rounding of negative amounts is ignored.'},
                            {'kind': 'accept'})
        worker, task = self.start(self.candidate_script(finishes=2), reviewer)
        state = self.drive(worker, task, until=lambda s: len(self.finishes(s)) >= 2)
        self.assertEqual(state['phase'], 'running', f'RED-P6: a rejected, unchanged candidate was completed ({state.get("message")})')
        found = self.register(worker.runtime, task)['findings']
        self.assertEqual([(f['id'], f['status']) for f in found], [('RF1', 'open')])
        self.assertEqual(self.whole(worker.runtime, found[0]), 'C3 is not met: the rounding of negative amounts is ignored.')
        # the worker still gets the reviewer's words as they were (no id prefix on its own feedback)
        first = state['reviews'][0]
        self.assertEqual(first['feedback'], 'C3 is not met: the rounding of negative amounts is ignored.')

    def test_a_rejection_in_words_only_is_closed_by_a_later_review_with_evidence(self):
        reviewer = Reviewer({'kind': 'reject_feedback', 'feedback': 'C3 is not met: the rounding of negative amounts is ignored.'},
                            {'kind': 'close', 'cite': 0, 'how': 'the file read in this review does not have the problem'})
        worker, task = self.start(self.candidate_script(finishes=2), reviewer)
        state = self.drive(worker, task, until=lambda s: s['phase'] == 'completed')
        self.assertEqual(state['phase'], 'completed', str(state.get('message')))
        self.assertEqual([f['status'] for f in self.register(worker.runtime, task)['findings']], ['resolved'])


class FindingRetrievalTests(LifecycleBase):
    """The reviewer's retrieval of findings and notes, as it will really be used: several at once, a wrong id, the list again."""

    def three_long(self):
        return ['r0: ' + (f'Lỗi {n}: ' + 'chi tiết của lỗi này, ' * 140)[:1500] + f' ĐUÔI-{n}' for n in (1, 2, 3)]

    def test_several_cut_findings_asked_in_one_answer_are_served_in_turn_and_never_block_the_job(self):
        findings = self.three_long()
        reviewer = Reviewer({'kind': 'reject', 'findings': findings}, {'kind': 'accept'},
                            {'kind': 'close', 'cite': 0, 'read_all': False, 'together': True,
                             'retrieve': [('RF1', 'claim'), ('RF2', 'claim'), ('RF3', 'claim')]})
        worker, task = self.start(self.candidate_script(finishes=3), reviewer)
        state = self.drive(worker, task, until=lambda s: s['phase'] == 'completed')
        self.assertEqual(state['phase'], 'completed', f'RED-P6: asking for three at once blocked the job ({state.get("message")})')
        self.assertNotEqual((state.get('recovery') or {}).get('kind'), 'prompt_budget')
        for n, text in enumerate(findings, 1):
            self.assertEqual(self.assembled(worker, f'RF{n}', 'claim'), text, f'RF{n} came back whole, in turn')
        deferred = [e for ctx, _ in worker.review_log for e in ctx['evidence'].get('requested_pages') or [] if e.get('deferred')]
        self.assertTrue(deferred, 'premise: the room did not hold all three, so some were deferred with a message')

    def test_an_id_that_names_nothing_is_answered_in_the_prompt_and_costs_no_failed_call(self):
        reviewer = Reviewer({'kind': 'reject', 'findings': ['r0: Unresolved defect C3']},
                            {'kind': 'close', 'cite': 0, 'read_all': False, 'retrieve': [('RF99', 'claim')]})
        worker, task = self.start(self.candidate_script(finishes=2), reviewer)
        state = self.drive(worker, task, until=lambda s: s['phase'] == 'completed')
        self.assertEqual(state['phase'], 'completed', str(state.get('message')))
        self.assertFalse(state.get('provider_failures'), 'no bounded retry after a settled provider failure was spent on it')
        answered = [e for ctx, _ in worker.review_log for e in ctx['evidence'].get('requested_pages') or [] if e.get('index') == 'RF99']
        self.assertTrue(answered and 'no finding or note' in answered[0]['error'])

    def test_the_list_of_findings_can_be_asked_again_after_a_closure(self):
        reviewer = Reviewer({'kind': 'report', 'count': 3, 'size': 0}, {'kind': 'relist'})
        worker, task = self.start(self.candidate_script(finishes=2), reviewer)
        state = self.drive(worker, task, until=lambda s: s['phase'] == 'completed')
        self.assertEqual(state['phase'], 'completed', f'RED-P6: the same list asked after a closure was refused ({state.get("message")})')
        self.assertEqual({f['status'] for f in self.register(worker.runtime, task)['findings']}, {'resolved'})


class FindingStateTests(LifecycleBase):
    """Things that must survive or be refused in the checkpoint around a review."""

    def test_a_closure_citing_a_receipt_shown_only_to_an_earlier_review_is_refused(self):
        # review 1 is shown receipt 0 (the file read) and rejects; review 2 closes citing receipt 0 although ITS prompts do not carry it
        reviewer = Reviewer({'kind': 'reject', 'findings': ['r0: Unresolved defect C3'], 'note': 'NOTE: read it'},
                            {'kind': 'close_blind', 'cite': 0})
        worker, task = self.start(self.candidate_script(finishes=2), reviewer)
        state = self.drive(worker, task, until=lambda s: len(self.finishes(s)) >= 2)
        self.assertEqual(state['phase'], 'running', f'RED-P6: closed with a receipt this review was not given ({state.get("message")})')
        self.assertFalse(p6.evidence_text(worker.review_log[-1][0]['evidence'], 0), 'premise: review 2 was not given receipt 0')
        found = self.register(worker.runtime, task)['findings']
        self.assertEqual([f['status'] for f in found], ['open'])
        self.assertIn('receipt 0 was not shown in this review', found[0]['closure_refused'])

    def test_a_fix_that_changes_the_candidate_does_not_close_the_finding_by_itself(self):
        reviewer = Reviewer({'kind': 'reject', 'findings': ['r0: Unresolved defect C3']}, {'kind': 'accept'})
        worker, task = self.start(self.candidate_script(finishes=1) + self.fix_script(finishes=1), reviewer)
        first = self.drive(worker, task, until=lambda s: len(self.finishes(s)) >= 1)
        candidate_1 = first['work']['verification']['candidate']
        state = self.drive(worker, task, until=lambda s: len(self.finishes(s)) >= 2)
        self.assertEqual(state['phase'], 'running', f'RED-P6: a changed candidate closed a finding ({state.get("message")})')
        self.assertNotEqual(state['work']['verification']['candidate'], candidate_1, 'premise: the candidate changed')
        self.assertFalse(state['reviews'][-1]['accepted'])
        self.assertEqual([f['status'] for f in self.register(worker.runtime, task)['findings']], ['open'])

    def test_a_note_too_long_to_keep_whole_ends_the_review_incomplete_after_one_reviewer_call(self):
        reviewer = Reviewer({'kind': 'reject', 'findings': ['r0: Unresolved defect C3'], 'note': 'N' * 700})
        worker, task = self.start(self.candidate_script(finishes=1), reviewer)
        with patch.object(review_evidence, 'MAX_TEXT', 400):
            state = self.drive(worker, task)
        self.assertEqual((state['phase'], (state.get('recovery') or {}).get('kind')), ('blocked', 'review_evidence'), str(state.get('message')))
        self.assertIn('nothing was accepted', state['message'])
        self.assertEqual(len(worker.review_log), 1, 'the settled attempt was not taken for a failed call and asked again')

    def test_a_blocked_job_hands_over_its_findings_by_id_and_blob(self):
        from onecrew import work_tools as wt
        reviewer = Reviewer({'kind': 'reject', 'findings': ['r0: ' + LONG_FINDING], 'note': 'NOTE'})
        worker, task = self.start(self.candidate_script(finishes=1), reviewer)
        # a reviewer that asks for the same page again: the review is incomplete and the job is blocked with its findings open
        reviewer.verdicts = [{'kind': 'again', 'findings': ['r0: ' + LONG_FINDING]}]
        state = self.drive(worker, task)
        self.assertEqual((state['phase'], (state.get('recovery') or {}).get('kind')), ('blocked', 'review_evidence'), str(state.get('message')))
        files = sorted((wt.home(worker.runtime, task) / 'handover').glob('blocker-*.json'))
        self.assertTrue(files, 'a blocker handover was written')
        summary = json.loads(files[-1].read_text(encoding='utf-8'))
        view = summary['review_findings']
        self.assertEqual((view['open'], [f['id'] for f in view['findings']]), (1, ['RF1']))
        self.assertTrue(view['findings'][0]['blob'])

    def test_a_checkpoint_of_the_unreleased_d5a0c43_resumes_with_its_finding_adopted_and_closable(self):
        reviewer = Reviewer({'kind': 'reject', 'findings': ['r0: Unresolved defect C3']}, {'kind': 'close', 'cite': 0})
        worker, task = self.start(self.candidate_script(finishes=2), reviewer)
        state = self.drive(worker, task, until=lambda s: len(self.finishes(s)) >= 1)
        seq, stored = worker.runtime.state(task)
        register = stored.pop('review_register')  # the shape d5a0c43 wrote: findings of a review under review_findings
        stored['review_findings'] = [{'id': f['id'], 'status': 'open', 'round': f['round'], 'claim': 'r0: Unresolved defect C3',
                                      'chars': f['chars'], 'source': f['source']} for f in register['findings']]
        worker.runtime.persist(task, seq, stored)
        state = self.drive(worker, task, until=lambda s: s['phase'] == 'completed')
        self.assertEqual(state['phase'], 'completed', str(state.get('message')))
        view = worker.runtime.state(task)[1]['review_register']['findings']
        self.assertEqual([(f['id'], f['status']) for f in view], [('RF1', 'resolved')])
        self.assertNotIn('review_findings', worker.runtime.state(task)[1])


class FindingCapacityTests(LifecycleBase):
    """R2: no finding is dropped for a count, and what cannot be held is an incomplete review, never an acceptance."""

    def test_thirteen_findings_are_all_tracked_and_closing_twelve_does_not_complete(self):
        reviewer = Reviewer({'kind': 'report', 'count': 13, 'size': 0}, {'kind': 'close', 'cite': 0, 'limit': 12}, {'kind': 'close', 'cite': 0})
        worker, task = self.start(self.candidate_script(finishes=3), reviewer)
        state = self.drive(worker, task, until=lambda s: len(self.finishes(s)) >= 2)
        self.assertEqual(state['phase'], 'running', f'RED-P6: completed with the 13th finding open ({state.get("message")})')
        findings = self.register(worker.runtime, task)['findings']
        self.assertEqual(len(findings), 13)
        self.assertEqual([f['status'] for f in findings], ['resolved'] * 12 + ['open'])
        rejection = self.result_of(worker.runtime, self.finishes(state)[1])
        told = [f['id'] for f in rejection.get('findings') or []] or re.findall(r'RF\d+', rejection['error'])
        self.assertIn('RF13', told, 'the worker is told of the open one by id')
        state = self.drive(worker, task, until=lambda s: s['phase'] == 'completed')
        self.assertEqual(state['phase'], 'completed', str(state.get('message')))
        self.assertEqual({f['status'] for f in self.register(worker.runtime, task)['findings']}, {'resolved'})

    def test_far_more_findings_than_the_prompt_lists_are_all_closed_through_the_window(self):
        count = 150  # their ids alone do not fit the smallest memory tier: the prompt carries a window and open_more
        reviewer = Reviewer({'kind': 'report', 'count': count}, {'kind': 'close', 'cite': 0, 'sweep': True, 'read_all': False, 'how': 'refuted by the file'})
        worker, task = self.start(self.candidate_script(finishes=2), reviewer)
        state = self.drive(worker, task, until=lambda s: s['phase'] == 'completed', steps=500)
        self.assertEqual(state['phase'], 'completed', str(state.get('message')))
        findings = self.register(worker.runtime, task)['findings']
        self.assertEqual((len(findings), {f['status'] for f in findings}), (count, {'resolved'}))
        windows = [ctx for ctx, _ in worker.review_log if ctx.get('open_more')]
        self.assertTrue(windows, 'premise: the prompt had to name how many open findings it did not list')
        self.assertTrue(all(len(canonical({k: c[k] for k in ('open_findings', 'open_more', 'review_notes') if k in c})) <= review_evidence.MEMORY_TIERS[0]
                            for c in windows), 'the window stays within the memory budget: the prompt cap was not widened')

    def test_a_full_register_is_an_incomplete_review_and_nothing_is_accepted(self):
        reviewer = Reviewer({'kind': 'report', 'count': 8}, {'kind': 'close', 'cite': 0})
        worker, task = self.start(self.candidate_script(finishes=1), reviewer)
        with patch.object(review_evidence, 'MAX_TRACKED', 5, create=True), patch.object(review_evidence, 'MAX_FINDINGS', 5, create=True):
            state = self.drive(worker, task)
        self.assertEqual((state['phase'], (state.get('recovery') or {}).get('kind')), ('blocked', 'review_evidence'), str(state.get('message')))
        self.assertIn('nothing was accepted', state['message'])
        # R4: the response cannot be fully recorded, so NONE of the reviewer's reported findings is recorded as its own finding -
        # but the response is not forgotten: exactly one durable 'unrecorded' block is kept (open, with the evidence blob) so a
        # resume cannot accept over it. Nothing of what the reviewer reported was accepted or resolved.
        recorded = self.register(worker.runtime, task)['findings']
        self.assertEqual([(f['status'], f['source'].get('kind')) for f in recorded], [('open', 'unrecorded_overflow')],
                         'only the durable unrecorded-findings block is recorded, not the 8 reported findings')
        self.assertFalse([r for r in state.get('reviews') or [] if r.get('accepted')])
        self.assertEqual(len(worker.review_log), 2, 'a reviewer call for the file and one for its answer; the worker was not called for it')


class FindingTextTests(LifecycleBase):
    """R3: the whole text of a finding or a note is kept and returned; distinct findings stay distinct."""

    def test_two_long_findings_that_share_their_first_2000_characters_are_two_findings_each_retrievable_whole(self):
        common = ('Phần chung của lỗi: ' + 'đoạn lặp ' * 300)[:2100]
        first, second = common + ' ĐUÔI-MỘT', common + ' ĐUÔI-HAI'
        reviewer = Reviewer({'kind': 'reject', 'findings': ['r0: ' + first, 'r0: ' + second]}, {'kind': 'accept'},
                            {'kind': 'close', 'cite': 0, 'read_all': False, 'retrieve': [('RF1', 'claim'), ('RF2', 'claim')]})
        worker, task = self.start(self.candidate_script(finishes=3), reviewer)
        state = self.drive(worker, task, until=lambda s: len(self.finishes(s)) >= 2)
        findings = self.register(worker.runtime, task)['findings']
        self.assertEqual([f['id'] for f in findings], ['RF1', 'RF2'], 'RED-P6: merged by their shared prefix')
        self.assertEqual([self.whole(worker.runtime, f) for f in findings], ['r0: ' + first, 'r0: ' + second])
        worker.runtime = Owned(self.ledger, worker)
        state = self.drive(worker, task, until=lambda s: s['phase'] == 'completed')
        self.assertEqual(state['phase'], 'completed', str(state.get('message')))
        self.assertEqual(self.assembled(worker, 'RF1', 'claim'), 'r0: ' + first)
        self.assertEqual(self.assembled(worker, 'RF2', 'claim'), 'r0: ' + second)

    def test_a_cut_claim_in_the_prompt_says_so_and_the_rule_for_asking_is_there(self):
        reviewer = Reviewer({'kind': 'reject', 'findings': ['r0: ' + LONG_FINDING]}, {'kind': 'accept'})
        worker, task = self.start(self.candidate_script(finishes=2), reviewer)
        self.drive(worker, task, until=lambda s: len(self.finishes(s)) >= 2)
        ctx = worker.review_log[1][0]
        entry = ctx['open_findings'][0]
        self.assertEqual(entry['id'], 'RF1'); self.assertEqual(entry['chars'], len('r0: ' + LONG_FINDING))
        self.assertLess(len(entry['claim']), entry['chars'])
        self.assertIn('evidence_requests', ctx['findings_rule']); self.assertIn('"RF3"', ctx['findings_rule'])


class FindingDefenceTests(LifecycleBase):
    def test_a_job_is_never_completed_over_an_open_finding_whatever_stored_acceptance_leads_there(self):
        reviewer = Reviewer({'kind': 'reject', 'findings': ['r0: Unresolved defect C3']})
        worker, task = self.start(self.candidate_script(finishes=2), reviewer)
        state = self.drive(worker, task, until=lambda s: len(self.finishes(s)) >= 1)
        self.assertEqual(state['phase'], 'running')
        seq, stored = worker.runtime.state(task)
        # a stored acceptance (a review answered before a restart, a record from an older runtime) with a finding still open
        stored['review'] = {'accepted': True, 'feedback': 'accepted'}; stored['review_prompt'] = None
        stored['work']['verification']['step'] = stored['step']; stored['work']['verification']['findings'] = []  # nothing else refuses
        worker.runtime.persist(task, seq, stored)
        before = len(worker.review_log)
        state = self.drive(worker, task, until=lambda s: len(self.finishes(s)) >= 2)
        self.assertEqual(state['phase'], 'running', f'RED-P6: completed over an open finding ({state.get("message")})')
        self.assertEqual(len(worker.review_log), before, 'no reviewer call: the stored acceptance was the one used')
        error = self.result_of(worker.runtime, self.finishes(state)[1])['error']
        self.assertIn('completion refused', error); self.assertIn('RF1', error)


class R4ResumeUnrecordedTests(LifecycleBase):
    """R4 (Codex 2026-10-15): a response that could not be fully recorded (count over MAX_TRACKED, or a text over MAX_TEXT) raised
    ReviewEvidenceIncomplete and blocked the job, but left NO durable finding in the register. A resume started the review afresh
    with an empty register, so a later generic acceptance completed the job over the findings that were never recorded. The fix is a
    durable blocking finding that keeps a reference to the original evidence blob, survives the reload, and leaves 'open' only through
    a valid resolution. It must NOT be fixed by raising the limit or auto-closing anything, and a valid path must still finish."""

    def _block_over_capacity(self, worker, task):
        """Drive the over-capacity report so the response cannot be fully recorded, and assert the block + the durable finding."""
        with patch.object(review_evidence, 'MAX_TRACKED', 5, create=True), patch.object(review_evidence, 'MAX_FINDINGS', 5, create=True):
            state = self.drive(worker, task)
        self.assertEqual((state['phase'], (state.get('recovery') or {}).get('kind')), ('blocked', 'review_evidence'),
                         str(state.get('message')))
        self.assertIn('nothing was accepted', state['message'])
        found = self.register(worker.runtime, task)['findings']
        self.assertTrue(found, 'RED-R4: the over-capacity response left no durable finding in the register')
        self.assertEqual([f['status'] for f in found], ['open'])
        self.assertTrue(all(f.get('blob') for f in found), 'the unrecorded evidence is kept whole in the blob store')
        return found

    def test_an_over_capacity_response_blocks_and_a_resumed_stored_acceptance_cannot_complete(self):
        # the over-capacity response blocks and leaves a durable open finding. A later runner reloads the checkpoint and reaches a
        # stored acceptance (a review answered before the restart, a record from an older runtime) with that finding still open.
        # On the baseline the register was empty after the block, so the acceptance completed the job; the durable block refuses it.
        reviewer = Reviewer({'kind': 'report', 'count': 8, 'size': 0})
        worker, task = self.start(self.candidate_script(finishes=2), reviewer)
        self._block_over_capacity(worker, task)
        durable_id = self.register(worker.runtime, task)['findings'][0]['id']
        worker.runtime = Owned(self.ledger, worker)  # restart: the block comes from the checkpoint
        self.assertEqual([f['status'] for f in self.register(worker.runtime, task)['findings']], ['open'], 'the block survived the reload')
        # on resume the reviewer only accepts, closing nothing: the 'generic accept' R4 is about. It must not complete.
        reviewer.verdicts = [{'kind': 'accept'}]; reviewer.finished = 0; reviewer.calls = 0; reviewer.sweep = 0
        state = self.drive(worker, task, until=lambda s: len(self.finishes(s)) >= 2)
        self.assertNotEqual(state['phase'], 'completed',
                            f'RED-R4: a resume + generic accept completed over the unrecorded-findings block ({state.get("message")})')
        reg = self.register(worker.runtime, task)['findings']
        durable = next(f for f in reg if f['id'] == durable_id)
        self.assertEqual(durable['status'], 'open', 'the durable unrecorded-findings block is still open across the restart')
        self.assertFalse(any(f['status'] == 'resolved' for f in reg), 'the generic accept resolved nothing')

    def test_a_text_too_long_to_record_also_leaves_a_durable_block_that_survives_a_restart(self):
        # the length-overflow sibling: a finding over MAX_TEXT cannot be stored whole, so the response cannot be recorded. The same
        # durable open finding must appear and survive a reload (the fix applies to both 'cannot fully record' paths).
        reviewer = Reviewer({'kind': 'report', 'count': 1, 'size': 600})
        worker, task = self.start(self.candidate_script(finishes=2), reviewer)
        with patch.object(review_evidence, 'MAX_TEXT', 400):
            state = self.drive(worker, task)
        self.assertEqual((state['phase'], (state.get('recovery') or {}).get('kind')), ('blocked', 'review_evidence'),
                         str(state.get('message')))
        found = self.register(worker.runtime, task)['findings']
        self.assertTrue(found, 'RED-R4: the length-overflow response left no durable finding')
        self.assertEqual([f['status'] for f in found], ['open'])
        self.assertEqual(found[0]['source'].get('kind'), 'unrecorded_length', 'recorded as the length-overflow block')
        self.assertGreaterEqual(found[0]['chars'], 600, 'it keeps the length of the evidence it could not hold whole')
        self.assertFalse(found[0].get('blob'), 'the over-long text could not be stored whole; the block keeps its head and length')
        worker.runtime = Owned(self.ledger, worker)  # restart: the block survives
        self.assertEqual([f['status'] for f in self.register(worker.runtime, task)['findings']], ['open'])

    def test_control_a_valid_path_after_the_block_still_completes_with_no_permanent_artifact(self):
        # the over-capacity response blocks and leaves one durable finding; after the block the reviewer reads the file and closes
        # it with evidence. The block is NOT permanent: a valid resolution still finishes, and no finding is left open.
        reviewer = Reviewer({'kind': 'report', 'count': 8, 'size': 0})
        worker, task = self.start(self.candidate_script(finishes=3), reviewer)
        self._block_over_capacity(worker, task)
        worker.runtime = Owned(self.ledger, worker)  # resume with the real limit back: the reviewer closes the durable finding
        seq, stored = worker.runtime.state(task)
        stored['phase'] = 'running'; stored.pop('recovery', None); stored['review'] = None; stored['review_prompt'] = None
        worker.runtime.persist(task, seq, stored)
        reviewer.verdicts = [{'kind': 'close', 'cite': 0}]; reviewer.finished = 0; reviewer.calls = 0; reviewer.sweep = 0
        state = self.drive(worker, task, until=lambda s: s['phase'] == 'completed', steps=500)
        self.assertEqual(state['phase'], 'completed', f'the valid path after the block did not finish ({state.get("message")})')
        findings = self.register(worker.runtime, task)['findings']
        self.assertTrue(findings, 'premise: the durable finding was there to close')
        self.assertEqual({f['status'] for f in findings}, {'resolved'}, 'the durable block is resolved; nothing is a permanent artifact')


class R5NewRejectionWhileOpenTests(LifecycleBase):
    """R5 (Codex 2026-10-15): record_rejection returned None whenever any finding was already open, so a new rejection whose
    findings=[] but whose feedback named an INDEPENDENT defect B was dropped. Closing the first finding A then let an acceptance
    complete while B lived only in history. The fix registers the new rejection's feedback as its own finding even when another is
    open, dedup by whole normalized content (no infinite duplicates on repeated identical feedback), never from a core-generated
    message, and closing A does not touch B."""

    def test_a_new_rejection_feedback_binds_even_when_another_finding_is_open(self):
        reviewer = Reviewer({'kind': 'reject', 'findings': ['r0: defect A: negative amounts rounded wrong']},
                            {'kind': 'reject_feedback', 'feedback': 'defect B: the thousands separator is dropped for large amounts'},
                            {'kind': 'close', 'cite': 0, 'ids': ['RF1']})
        worker, task = self.start(self.candidate_script(finishes=3), reviewer)
        # closing ONLY A can never complete the job while B is open: it reaches the end of its finishes without completing. On the
        # baseline B was dropped and the same sequence completed; the register is the decisive evidence either way.
        state = self.drive(worker, task, until=lambda s: s['phase'] == 'completed' or len(self.finishes(s)) >= 3)
        self.assertNotEqual(state['phase'], 'completed',
                            f'RED-R5: a new independent rejection B was dropped because A was open, and the job completed ({state.get("message")})')
        statuses = [(f['id'], f['status']) for f in self.register(worker.runtime, task)['findings']]
        self.assertEqual(statuses, [('RF1', 'resolved'), ('RF2', 'open')], 'B is its own open finding; closing A did not touch it')
        found_b = self.register(worker.runtime, task)['findings'][1]
        self.assertEqual(self.whole(worker.runtime, found_b), 'defect B: the thousands separator is dropped for large amounts',
                         'B is kept whole, with its source')
        self.assertEqual(found_b['source'].get('kind'), 'feedback')

    def test_control_closing_both_findings_with_evidence_completes(self):
        reviewer = Reviewer({'kind': 'reject', 'findings': ['r0: defect A: negative amounts rounded wrong']},
                            {'kind': 'reject_feedback', 'feedback': 'defect B: the thousands separator is dropped for large amounts'},
                            {'kind': 'close', 'cite': 0})
        worker, task = self.start(self.candidate_script(finishes=3), reviewer)
        state = self.drive(worker, task, until=lambda s: s['phase'] == 'completed', steps=500)
        self.assertEqual(state['phase'], 'completed', f'closing A and B with evidence did not complete ({state.get("message")})')
        self.assertEqual({f['status'] for f in self.register(worker.runtime, task)['findings']}, {'resolved'})
        self.assertEqual(len(self.register(worker.runtime, task)['findings']), 2, 'both A and B were tracked')

    def test_repeated_identical_rejection_feedback_does_not_create_duplicate_findings(self):
        # the SAME defect rejected in words twice (the second differs only in whitespace) is ONE finding, not two - dedup by whole
        # normalized content. Two feedback-only rejections stay within the rejection limit, then a closure completes the job.
        same = 'defect B: the thousands separator is dropped for large amounts'
        reviewer = Reviewer({'kind': 'reject_feedback', 'feedback': same},
                            {'kind': 'reject_feedback', 'feedback': '   defect B:  the thousands  separator is dropped for large amounts  '},
                            {'kind': 'close', 'cite': 0})
        worker, task = self.start(self.candidate_script(finishes=3), reviewer)
        state = self.drive(worker, task, until=lambda s: s['phase'] == 'completed', steps=500)
        self.assertEqual(state['phase'], 'completed', str(state.get('message')))
        findings = self.register(worker.runtime, task)['findings']
        self.assertEqual(len(findings), 1, f'RED-R5: repeated identical feedback made a duplicate finding ({[f["id"] for f in findings]})')
        self.assertEqual([f['status'] for f in findings], ['resolved'])

    def test_control_an_accepted_or_core_review_does_not_become_a_feedback_finding(self):
        reviewer = Reviewer({'kind': 'close', 'cite': 0})
        worker, task = self.start(self.candidate_script(), reviewer)
        state = self.drive(worker, task, until=lambda s: s['phase'] == 'completed')
        self.assertEqual(state['phase'], 'completed', str(state.get('message')))
        self.assertEqual(self.register(worker.runtime, task)['findings'], [])


if __name__ == '__main__':
    unittest.main()
