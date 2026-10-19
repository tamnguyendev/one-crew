"""v2 item 4: `plan report` and `plan digest` read the ledger and nothing else (docs/v2-report.vi.md).

One fixture state root holds an accepted plan, a failed plan (a failure with no repair left, not stopped), a stopped plan and a
plan with an unreadable contract file. It is built once; the tests only read it.
"""
import contextlib
import datetime as dt
import io
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import contract as contracts, plan as plans, plan_cli, report, verdict

from test_v2_l1 import BAD, OK, milestone, plan_json

SECTIONS = ['1. Output đạt tới đâu', '2. Mốc và verdict', '3. Phút so ngân sách', '4. Lần chặn', '5. Câu hỏi', '6. Chạy ngoài kiểm soát', '7. Bãi đỗ']


def two_milestones(**extra):
    return plan_json(milestones=[milestone('M1', covers=['O1']), milestone('M2', covers=['O2'])],
                     output=['The sample exists', 'The sample is proven'], **extra)


class World:
    """The fixture state root, built once for the whole module (each verdict runs git on a clean checkout)."""
    @classmethod
    def build(cls):
        cls.temp = tempfile.TemporaryDirectory()
        base = Path(cls.temp.name)
        cls.root, cls.elsewhere, cls.state = base / 'project', base / 'elsewhere', base / 'state'
        cls.root.mkdir(); cls.elsewhere.mkdir()
        cls.env = patch.dict(os.environ); cls.env.start()
        for name in ('ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(name, None)
        cls.git('init', '-q'); cls.git('config', 'user.name', 'T'); cls.git('config', 'user.email', 't@localhost')
        (cls.root / 'a.txt').write_text('one\n'); cls.git('add', '.')
        subprocess.check_call(['git', '-C', str(cls.root), 'commit', '-q', '-m', 'base'],
                              env=dict(os.environ, GIT_COMMITTER_DATE='2020-01-01T00:00:00+00:00', GIT_AUTHOR_DATE='2020-01-01T00:00:00+00:00'))
        cls.ledger = Ledger(cls.root, cls.state)

        def approved(name, value):
            plans.propose(cls.ledger, name, value, 'claude'); return plans.approve(cls.ledger, name, 'owner', 'said yes in chat')

        # accepted: two milestones pass, the owner accepts; a second sentence of the output is quoted verbatim in the page
        approved('acc', two_milestones(title='Accepted plan — dấu tiếng Việt'))
        verdict.run(cls.ledger, 'acc', 'M1', cls.root); verdict.run(cls.ledger, 'acc', 'M2', cls.root)
        cls.accepted_tree = cls.tree()
        plans.accept(cls.ledger, 'acc', 'owner', 'ok', cls.accepted_tree)
        # failed: one failure with max_repairs 1 leaves no repair, and it is not stopped (the job5 shape)
        approved('bad', plan_json(milestones=[milestone(argv=BAD, max_repairs=1)], title='Failed plan'))
        verdict.run(cls.ledger, 'bad', 'M1', cls.root)
        # stopped: max_repairs 0 stops at once and asks the owner one question
        approved('stp', plan_json(milestones=[milestone(argv=BAD, max_repairs=0)], title='Stopped plan'))
        verdict.run(cls.ledger, 'stp', 'M1', cls.root)
        # a plan only proposed (waits for the owner)
        plans.propose(cls.ledger, 'prop', plan_json(title='Only proposed'), 'claude')
        # a plan whose contract file is gone: the report says so instead of guessing
        approved('gone', plan_json(title='Contract gone'))
        contracts.revision_path(cls.ledger, 'gone', 1).unlink()
        # an approved plan with a commit made after approval that no receipt saw
        time.sleep(1.2)
        approved('rogue', plan_json(title='Out of control', milestones=[milestone(max_repairs=2)]))
        (cls.root / 'rogue.txt').write_text('x\n'); cls.git('add', '.'); cls.git('commit', '-q', '-m', 'sneaky commit nobody verified')
        (cls.root / 'later.txt').write_text('y\n')                           # uncommitted change: the artifact differs from the commit tree
        verdict.run(cls.ledger, 'rogue', 'M1', cls.root)

    @classmethod
    def close(cls):
        cls.env.stop(); cls.temp.cleanup()

    @classmethod
    def git(cls, *args):
        return subprocess.check_output(['git', '-C', str(cls.root), *args], stderr=subprocess.PIPE).decode().strip()

    @classmethod
    def tree(cls):
        from onecrew.v2.verifiers import command
        return command.artifact_sha(cls.root)


def setUpModule():
    World.build()


def tearDownModule():
    World.close()


class Scenario(unittest.TestCase):
    def setUp(self):
        for name in ('temp', 'root', 'elsewhere', 'state', 'ledger', 'accepted_tree'): setattr(self, name, getattr(World, name))

    def report(self, name, **kw):
        return report.render_report(self.state, name, **kw)

    def section(self, text, number):
        lines = text.splitlines()
        start = lines.index(SECTIONS[number - 1]) + 1
        end = lines.index(SECTIONS[number]) if number < 7 else len(lines)
        return [line for line in lines[start:end] if line.strip()]


class ReportTests(Scenario):
    def test_the_seven_sections_come_in_order_for_an_accepted_failed_and_stopped_plan(self):
        for name in ('acc', 'bad', 'stp'):
            text = self.report(name)
            lines = text.splitlines()
            positions = [lines.index(title) for title in SECTIONS]
            self.assertEqual(positions, sorted(positions), name)
            self.assertEqual([line for line in lines if line[:2] in [f'{n}.' for n in range(1, 10)]], SECTIONS)
            self.assertLess(len(lines), 60, name)

    def test_contract_and_ledger_text_is_quoted_verbatim(self):
        text = self.report('acc')
        self.assertIn('«Accepted plan — dấu tiếng Việt»', text)
        self.assertIn('«The sample exists»', text)
        self.assertIn('«The sample is proven»', text)
        self.assertIn('trạng thái accepted', text)
        stopped = self.report('stp')
        with self.ledger.transaction() as conn:
            task = plans.derive(self.ledger, conn, 'stp')['task_id']
        question = self.ledger.requests(task)[0]['question']['question']
        self.assertIn(f'«{question}»', stopped)                     # the stop question, word for word
        self.assertIn('[mở]', stopped)

    def test_section_1_and_2_follow_the_verdicts(self):
        accepted = self.report('acc')
        self.assertEqual([l.split()[:2] for l in self.section(accepted, 1)], [['O1', 'ĐẠT'], ['O2', 'ĐẠT']])
        milestones = self.section(accepted, 2)
        self.assertEqual(len(milestones), 2)
        self.assertIn(f'M1 pass · by command · {self.accepted_tree[:7]} · sửa 0/1', milestones[0])
        failed = self.report('bad')
        self.assertEqual(self.section(failed, 1)[0].split()[:2], ['O1', 'CHƯA'])
        self.assertIn('M1 fail · by command', self.section(failed, 2)[0])
        self.assertIn('sửa 1/1', self.section(failed, 2)[0])
        stopped = self.section(self.report('stp'), 2)[0]
        self.assertIn('DỪNG', stopped); self.assertIn('sửa 1/0', stopped)
        self.assertIn('chưa có verdict', self.section(self.report('prop'), 2)[0])

    def test_section_3_minutes_against_budget_and_the_uncounted_calls(self):
        lines = self.section(self.report('acc'), 3)
        self.assertRegex(lines[0], r'đã chạy \d+ phút .* / ngân sách 120 phút$')
        self.assertEqual(lines[1], '  Lệnh: chưa đếm được')

    def test_section_4_without_a_hook_log_says_so_then_counts_the_three_kinds(self):
        self.assertIn(report.NO_HOOK_LOG, self.report('acc'))
        folder = self.root / '.onecrew'; folder.mkdir(exist_ok=True)
        reasons = ['Milestone M1 has no passing verdict; run verdict', 'stop block cap (2) reached; the session is let go',
                   'Edit outside the owned paths: x.py is not in scope', 'Writing outside scope is refused: y', 'refused: z is outside the owned list',
                   'The file is not owned by this plan', 'something unrelated happened']
        with (folder / 'violations.jsonl').open('w', encoding='utf-8') as stream:
            for reason in reasons: stream.write(json.dumps({'plan': 'acc', 'reason': reason}) + '\n')
            stream.write(json.dumps({'plan': 'bad', 'reason': 'Milestone M9 belongs to another plan'}) + '\n')
            stream.write('not json\n')
        self.addCleanup(lambda: (folder / 'violations.jsonl').unlink())
        lines = self.section(self.report('acc'), 4)
        self.assertEqual(lines[0], '  chờ kiểm: 2 · ngoài phạm vi: 4 · khác: 1')
        self.assertEqual([l.strip() for l in lines[1:]], [f'ngoài phạm vi: «{r}»' for r in reasons[3:6]])    # the last three of the scope kind, verbatim
        self.assertNotIn('M9', '\n'.join(lines))
        self.assertIn('chờ kiểm: 1', self.section(self.report('bad'), 4)[0])

    def test_section_6_flags_a_commit_no_receipt_saw_and_not_the_verified_tree(self):
        text = self.report('rogue')
        lines = self.section(text, 6)
        self.assertIn('nghi ngờ', lines[1])
        self.assertIn('«sneaky commit nobody verified»', lines[1])
        self.assertEqual(len(lines), 2)
        clean = self.section(self.report('acc'), 6)
        self.assertNotIn('nghi ngờ', '\n'.join(clean))
        self.assertIn('0 commit', clean[0])

    def test_section_6_has_no_data_without_a_receipt_directory(self):
        self.assertEqual(self.section(self.report('prop'), 6), [f'  {report.NO_DATA} (sổ không ghi thư mục của biên nhận)'])

    def test_section_5_lists_open_and_answered_questions(self):
        self.assertEqual(self.section(self.report('prop'), 5), ['  hạn mức hỏi chủ sở hữu: đã dùng 0/1', '  không có câu hỏi nào'])
        with self.ledger.transaction() as conn:
            task = plans.derive(self.ledger, conn, 'stp')['task_id']
        request = self.ledger.requests(task)[0]
        self.assertEqual(request['state'], 'pending')
        self.assertIn('hạn mức hỏi chủ sở hữu: đã dùng 1/1', self.report('stp'))

    def test_section_7_parks_should_items_unknowns_and_attention(self):
        lines = self.section(self.report('acc'), 7)
        self.assertEqual(lines[0], '  should chưa có mốc đạt: S1 «Nice to have»')          # the should item has no milestone
        self.assertEqual(lines[1], '  vượt hạn mức chú ý: 0 lần')
        self.assertEqual(lines[2], '  unknown còn mở: không có')

    def test_an_unreadable_contract_prints_no_data_and_the_ledger_sections_still_come(self):
        text = self.report('gone')
        self.assertIn(report.NO_DATA, self.section(text, 1)[0])
        self.assertEqual(self.section(text, 2), [report.NO_DATA]); self.assertEqual(self.section(text, 7), [report.NO_DATA])
        self.assertEqual(self.section(text, 3)[1], '  Lệnh: chưa đếm được')
        self.assertIn(f'ngân sách: {report.NO_DATA}', text)

    def test_unknown_plan_and_unknown_revision_are_refused(self):
        with self.assertRaises(LedgerError): self.report('nope')
        with self.assertRaises(LedgerError): self.report('acc', revision=9)
        self.assertIn('bản 1/1', self.report('acc', revision=1).splitlines()[0])

    def test_the_report_is_found_from_any_project_and_a_missing_ledger_is_refused(self):
        other = Ledger(self.elsewhere, self.state)
        self.assertEqual(report.render_report(other.state_root, 'acc'), self.report('acc'))
        with self.assertRaises(LedgerError): report.render_report(Path(self.temp.name) / 'no-state', 'acc')


class DigestTests(Scenario):
    def lines(self):
        return report.render_digest(self.state).splitlines()

    def test_open_plans_come_first_newest_event_first_and_closed_plans_make_one_line(self):
        lines = self.lines()
        opened = [l for l in lines if 'chờ:' in l]
        self.assertEqual([l.split()[0] for l in opened], ['rogue', 'gone', 'prop'])      # latest event first
        self.assertEqual(lines[-1], '3 việc đã đóng: 1 nghiệm thu, 1 dừng, 1 hỏng')
        self.assertEqual(len(lines), 1 + len(opened) + 1)
        self.assertIn('prop', opened[2]); self.assertTrue(opened[2].endswith('chờ: chủ sở hữu'))
        self.assertIn('rogue', opened[0]); self.assertIn('mốc 1/1', opened[0]); self.assertTrue(opened[0].endswith('chờ: chủ sở hữu'))
        self.assertTrue(opened[1].endswith(f'chờ: {report.NO_DATA}'))                      # the contract file is gone

    def test_who_the_plan_waits_on(self):
        waits = {}
        for name in ('acc', 'bad', 'stp', 'prop', 'rogue'):
            waits[name] = report._standing(report._lookup(self.state, name))
        self.assertEqual(waits, {'acc': ('accepted', '—'), 'bad': ('failed', '—'), 'stp': ('stopped', '—'),
                                 'prop': ('open', 'chủ sở hữu'), 'rogue': ('open', 'chủ sở hữu')})

    def test_a_plan_with_a_verdict_still_to_run_waits_on_the_check_and_one_without_waits_on_the_ai(self):
        f = report._lookup(self.state, 'rogue')
        view = dict(f['views'][0], state='pending')
        self.assertEqual(report._standing(dict(f, views=[view], state=dict(f['state'], verdicts=[{'revision': 1}])))[1], 'kiểm')
        self.assertEqual(report._standing(dict(f, views=[view], state=dict(f['state'], verdicts=[])))[1], 'AI')

    def test_at_most_ten_open_lines_and_a_note_for_the_rest(self):
        rows = [({'id': f'T{n}', 'project_id': 'p', 'project_path': '', 'request_key': f'plan:p{n}', 'created_at': f'2026-01-01T00:{n:02d}:00+00:00'},
                 f'2026-01-01T00:{n:02d}:00+00:00') for n in range(14)]
        fake = {'name': 'x', 'state': {'status': 'proposed'}, 'views': [], 'contract': {'x': 1}, 'requests': [], 'revision': 1}

        def gather(root, row, revision=None): return dict(fake, name=row['request_key'][5:])
        with patch.object(report, '_anchors', lambda root: rows), patch.object(report, '_gather', gather):
            lines = report.render_digest(self.state).splitlines()
        opened = [l for l in lines if 'chờ:' in l]
        self.assertEqual(len(opened), 10)
        self.assertEqual([l.split()[0] for l in opened], [f'p{n}' for n in range(13, 3, -1)])      # newest first
        self.assertIn('… còn 4 việc mở nữa', lines[-2]); self.assertEqual(lines[-1], '0 việc đã đóng: 0 nghiệm thu, 0 dừng, 0 hỏng')


class ReadOnlyTests(Scenario):
    def snapshot(self):
        files = sorted(p.relative_to(self.state).as_posix() + ':' + str(p.stat().st_size) for p in self.state.rglob('*') if p.is_file())
        with self.ledger.transaction() as conn:
            events = conn.execute('SELECT COUNT(*), MAX(seq) FROM events').fetchone()
        return files, tuple(events), (self.state / 'ledger.sqlite3').read_bytes()

    def test_report_and_digest_change_nothing_in_the_state_root(self):
        before = self.snapshot()
        for name in ('acc', 'bad', 'stp', 'prop', 'gone', 'rogue'): self.report(name)
        report.render_digest(self.state)
        self.assertEqual(self.snapshot(), before)

    def test_the_reader_refuses_to_write_and_needs_no_model(self):
        reader = report._Reader(self.state)
        with self.assertRaises(LedgerError):
            with reader.transaction(write=True): pass
        calls = []
        with patch('subprocess.run', side_effect=lambda argv, *a, **k: calls.append(argv[0]) or subprocess.CompletedProcess(argv, 1, '', 'x')):
            text = self.report('rogue')
        self.assertEqual(set(calls), {'git'})                                              # the one outside look; no other program
        self.assertIn(report.NO_DATA, self.section(text, 6)[0])                           # an unreadable repository is "no data", not a guess

    def test_cli_prints_the_page_and_out_is_the_only_write(self):
        def run(*argv):
            out = io.StringIO()
            with contextlib.redirect_stdout(out): code = plan_cli.main(['--project', str(self.elsewhere), '--state-root', str(self.state), *argv])
            return code, out.getvalue()
        before = self.snapshot()
        code, text = run('plan', 'report', 'acc')
        self.assertEqual((code, text), (0, self.report('acc') + '\n'))
        target = Path(self.temp.name) / 'out' / 'digest.txt'
        code, text = run('plan', 'digest', '--out', str(target))
        self.assertEqual(code, 0); self.assertIn('Đã ghi', text)
        self.assertEqual(target.read_text(encoding='utf-8'), report.render_digest(self.state))
        self.assertEqual(run('plan', 'report', 'acc', '--out', str(self.state / 'x.txt'))[0], 2)      # never into the state root
        self.assertFalse((self.state / 'x.txt').exists())
        self.assertEqual(run('plan', 'report', 'nope')[0], 2)
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
