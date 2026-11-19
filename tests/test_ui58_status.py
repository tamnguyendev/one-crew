"""#58 (UI58 milestone A): the task card says the truth about a check's result, on real temporary ledgers.

Three cases on the SAME ledger and project, as Codex's counterexample of 19/11 (D:/OneCrewRuns/codex-dev31-roadmap-review-20261119/check.py):
  P1 pass-then-edit  M1 passes, then the code changes: the task page says a recheck is needed and does not count the old pass;
  P2 timeout         M1's check ran out of time (inconclusive): "chưa kết luận", the reason, an environment check or a rerun; never "không đạt";
  P3 real fail       M1's command exits 3: the error with its evidence line, the fix step and the repair rounds used/left.
Plus the last repair round (a warning, not a decision), the stop after it (a real owner decision), a project whose current artifact cannot be
read (said, not counted), an unknown handler said as unknown, agreement with `plan report`, and the card's short title."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger
from onecrew.snapshots import Snapshots
from onecrew.v2 import plan as plans, report, tracking, verdict
from onecrew.v2.verifiers import command

# Self-contained (the verifier reruns this module against the installed wheel, which has no onecrew.owned that tests/test_v2_l1 imports);
# the same smallest contract and project as tests/test_v2_l1.Fixture.
OK = [sys.executable, '-c', 'print("ok")']
BAD = [sys.executable, '-c', 'raise SystemExit(3)']


def milestone(mid='M1', argv=OK, **extra):
    return dict({'id': mid, 'title': 'Milestone ' + mid, 'verifier': {'type': 'command', 'config': {'argv': argv}}, 'covers': ['O1']}, **extra)


def plan_json(milestones):
    return {'schema_version': 2, 'title': 'Sample', 'size': 'S',
            'understanding': {'restated_goal': 'Do the sample and prove it.', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']},
                              'assumptions': [], 'confidence': 'high', 'unknowns': []},
            'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'the file to work on is there'}],
            'output': ['The sample exists'], 'scope': {'owned': ['a.txt']}, 'non_goals': ['Nothing else'],
            'items': [{'id': 'I1', 'title': 'Do it', 'tier': 'must', 'milestone': 'M1'}],
            'milestones': milestones, 'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1}, 'profile_version': None}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / 'project'; self.root.mkdir()
        self.git('init', '-q'); self.git('config', 'user.name', 'T'); self.git('config', 'user.email', 't@localhost')
        (self.root / 'a.txt').write_text('one\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'base')
        self.ledger = Ledger(self.root, base / 'state')
        env = patch.dict(os.environ); env.start(); self.addCleanup(env.stop)
        for name in ('ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(name, None)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.PIPE).decode().strip()

    def tree(self):
        return command.artifact_sha(self.root)

UI58_TITLE = 'UI58: trạng thái đúng trên thẻ (#58) và trang theo dõi lấy việc làm trung tâm (#33), một lần duyệt, giao từng phần'


class Status(Fixture):
    def plan(self, name, ms):
        value = plan_json(milestones=ms)
        with contextlib.redirect_stderr(io.StringIO()):        # several plans on one project: the active-plan export warns, by design
            plans.propose(self.ledger, name, value, 'claude', workflow=True)
            os.environ.pop('ONECREW_ACTOR', None)
            plans.approve(self.ledger, name, 'owner', 'test fixture')

    def timed_out(self, name, mid='M1'):
        """What verdict.run records when the command passes its max_minutes: a receipt with timed_out and no exit code, judged inconclusive."""
        with self.ledger.transaction() as conn:
            st = plans.derive(self.ledger, conn, name)
        body = {'kind': 'command-receipt', 'plan': name, 'revision': 1, 'milestone': mid, 'argv': OK, 'exit_code': None, 'timed_out': True,
                'error': None, 'artifact_sha': self.tree(), 'artifact_sha_after': self.tree(), 'plan_sha': st['revisions'][1]['sha']}
        blob = Snapshots(self.ledger.state_root).blob(json.dumps(body, sort_keys=True).encode())
        with self.ledger.transaction(write=True) as conn:
            plans.emit(self.ledger, conn, st['task_id'], 'verdict.receipt_issued', {'plan': name, 'revision': 1, 'milestone': mid, 'receipt': blob})
        verdict.record(self.ledger, name, mid, 'inconclusive', 'command', blob, body['artifact_sha'])

    def three(self):
        """The three #58 cases on one ledger and one project."""
        self.plan('P1', [milestone('M1', OK, max_repairs=3), milestone('M2')])
        self.plan('P2', [milestone('M1', OK, max_repairs=3), milestone('M2')])
        self.plan('P3', [milestone('M1', BAD, max_repairs=3), milestone('M2')])
        verdict.run(self.ledger, 'P1', 'M1')
        self.timed_out('P2')
        verdict.run(self.ledger, 'P3', 'M1')

    def page(self, name):
        return tracking.detail(self.ledger.state_root, name)

    def edit(self):
        (self.root / 'a.txt').write_text('changed after the pass\n')

    def report_lines(self, name):
        return [l.strip() for l in report.render_report(self.ledger.state_root, name).splitlines() if 'M1' in l]

    # ---- pass, then the code changes ----------------------------------------------------------------------------------------------

    def test_pass_then_edit_needs_recheck(self):
        self.three()
        before = self.page('P1')
        self.assertEqual(before['validity']['kind'], 'valid')
        self.assertEqual(before['compared'], 'compared')
        self.edit()
        d = self.page('P1')
        s = d['situation']
        self.assertEqual((s['stage'], s['label']), ('check', 'Cần kiểm lại'))
        self.assertIn('cần kiểm lại', s['reason'])
        self.assertIn('không còn được tính', s['reason'])
        self.assertEqual(s['next'], 'Kiểm lại mốc M1')
        self.assertTrue(d['milestones'][0]['stale'])
        self.assertEqual(d['milestone_checks']['rows'][0]['state'], 'recheck')
        self.assertEqual((d['validity']['kind'], d['validity']['label']), ('recheck', 'Cần kiểm lại'))

    def test_stale_not_counted(self):
        self.three()
        self.assertEqual(self.page('P1')['situation']['milestones']['text'], 'Đạt 1/2 mốc')
        self.edit()
        s = self.page('P1')['situation']
        self.assertEqual(s['milestones']['text'], 'Đạt 0/2 mốc')
        self.assertNotIn('M2', s['next'])                   # it does not point past the milestone that needs a recheck
        self.assertNotEqual(s['stage'], 'accept')

    # ---- a check that ran out of time -----------------------------------------------------------------------------------------------

    def test_timeout_not_failed(self):
        self.three()
        d = self.page('P2')
        s = d['situation']
        self.assertEqual(s['label'], 'Chưa kết luận')
        self.assertNotEqual(s['stage'], 'fix')
        self.assertNotIn('không đạt', s['label'].lower())
        self.assertIn('không phải kiểm không đạt', s['reason'])
        self.assertEqual(d['milestone_checks']['rows'][0]['state'], 'inconclusive')
        self.assertEqual(d['milestone_checks']['rows'][0]['label'], 'Chưa kết luận')
        self.assertEqual(d['validity']['kind'], 'inconclusive')

    def test_timeout_reason_and_next(self):
        self.three()
        s = self.page('P2')['situation']
        self.assertIn('hết giờ', s['reason'])
        self.assertIn('Kiểm môi trường', s['next'])
        self.assertIn('chạy lại bộ kiểm mốc M1', s['next'])

    # ---- a real failure -------------------------------------------------------------------------------------------------------------

    def test_real_fail_reason_and_next(self):
        self.three()
        d = self.page('P3')
        s = d['situation']
        self.assertEqual((s['stage'], s['label']), ('fix', 'Cần sửa'))
        self.assertIn('kiểm không đạt', s['reason'])
        self.assertIn('lệnh thoát mã 3', s['reason'])          # the evidence: the exit line of the receipt
        self.assertEqual(s['next'], 'Sửa và kiểm lại mốc M1')
        self.assertEqual(d['milestones'][0]['reason'], d['milestone_checks']['rows'][0]['reason'])
        self.assertEqual(d['validity']['kind'], 'failed')

    def test_repairs_shown(self):
        self.three()
        for name in ('P2', 'P3'):         # a timeout uses a repair round too (verdict.stop_reason counts every verdict that is not a pass)
            r = self.page(name)['situation']['repairs']
            self.assertEqual((r['milestone'], r['used'], r['max'], r['left']), ('M1', 1, 3, 2))
            self.assertEqual(r['text'], 'đã dùng 1/3 lượt sửa, còn 2')
        self.assertIsNone(self.page('P1')['situation']['repairs'])

    def test_last_repair_warning_not_decision(self):
        self.plan('P4', [milestone('M1', BAD, max_repairs=1), milestone('M2')])
        verdict.run(self.ledger, 'P4', 'M1')
        d = self.page('P4')
        s = d['situation']
        self.assertEqual(s['repairs']['left'], 0)
        self.assertIn('lần thử cuối', s['repairs']['text'])
        self.assertIn('đã dùng hết 1 lượt sửa', s['warning'])
        self.assertIn('chưa cần làm gì', s['warning'])
        self.assertEqual(s['stage'], 'fix')
        self.assertNotEqual(s['next_by'], 'owner')
        self.assertTrue(s['no_owner_decision'])
        self.assertEqual(d['needs_user'], [])
        self.assertNotIn(s['warning'], (s['next'] or ''))

    def test_out_of_repairs_owner_decision(self):
        self.plan('P4', [milestone('M1', BAD, max_repairs=1), milestone('M2')])
        verdict.run(self.ledger, 'P4', 'M1')
        (self.root / 'a.txt').write_text('a fix that does not help\n')       # a new artifact, so the stop is the repair cap and not max_stuck
        verdict.run(self.ledger, 'P4', 'M1')
        d = self.page('P4')
        s = d['situation']
        self.assertEqual(d['root_status'], 'stopped_with_report')
        self.assertEqual(s['stage'], 'stopped')
        self.assertIn('hết lượt sửa', s['reason'])
        self.assertEqual(s['next_by'], 'owner')
        self.assertFalse(s['no_owner_decision'])
        self.assertIsNone(s['warning'])                       # the decision replaces the warning
        asks = [n for n in d['needs_user'] if n['kind'] == 'request']
        self.assertTrue(asks and len(asks[0]['options']) >= 2)

    # ---- what is not known is said -------------------------------------------------------------------------------------------------

    def test_current_artifact_unknown_said(self):
        self.three()
        moved = self.root.with_name('project-moved')
        shutil.move(str(self.root), str(moved))
        self.addCleanup(lambda: moved.exists() and not self.root.exists() and shutil.move(str(moved), str(self.root)))
        d = self.page('P1')
        s = d['situation']
        self.assertEqual(d['compared'], 'unknown')
        self.assertEqual(s['label'], 'Chưa xác định bản hiện tại')
        self.assertIn('chưa được tính', s['reason'])
        self.assertEqual(s['milestones']['text'], 'Đạt 0/2 mốc')
        self.assertEqual(d['validity']['kind'], 'unknown')
        self.assertTrue(d['milestones'][0].get('current_unknown'))

    def test_handler_unknown_said(self):
        self.three()
        for name in ('P2', 'P3'):
            s = self.page(name)['situation']
            self.assertIsNone(s['next_by'])
            self.assertEqual(s['next_by_text'], 'Chưa có thông tin người xử lý')
        listed = {t['plan']: t for p in tracking.overview(self.ledger.state_root)['projects'] for t in p['tasks']}
        self.assertIsNone(listed['P1']['compared'])                        # the list does not hash each task (decision D4)
        self.assertEqual(listed['P1']['validity']['kind'], 'not_compared')
        self.assertIn('chưa so', listed['P1']['validity']['label'])

    def test_agrees_with_report(self):
        self.three()
        self.edit()
        stale = self.report_lines('P1')
        self.assertTrue(any('M1 cũ' in l for l in stale))
        self.assertTrue(self.page('P1')['milestones'][0]['stale'])
        timeout = self.report_lines('P2')
        self.assertTrue(any('lệnh hết giờ' in l for l in timeout) and any('M1 inconclusive' in l for l in timeout))
        self.assertIn('lệnh hết giờ', self.page('P2')['situation']['reason'])
        fail = self.report_lines('P3')
        self.assertTrue(any('lệnh thoát mã 3' in l for l in fail))
        self.assertIn('lệnh thoát mã 3', self.page('P3')['situation']['reason'])
        self.assertTrue(any('sửa 1/3' in l for l in fail))
        self.assertEqual(self.page('P3')['situation']['repairs']['used'], 1)

    def test_short_title(self):
        short = tracking.short_title(UI58_TITLE)
        self.assertLessEqual(len(short), 64)
        self.assertTrue(short.endswith('…'))
        self.assertTrue(short.startswith('UI58: trạng thái đúng trên thẻ'))
        self.assertEqual(tracking.short_title('Sửa lỗi đăng nhập'), 'Sửa lỗi đăng nhập')
        self.assertIsNone(tracking.short_title(''))
        self.plan('P5', [milestone('M1', OK)])
        d = self.page('P5')
        self.assertEqual((d['short_title'], d['headline']), ('Sample', 'Sample'))


if __name__ == '__main__':
    unittest.main()
