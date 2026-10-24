"""R01 / W23a - the handover report by acceptance (T24a, T38b) and the minimal `plan present` page (T42).

Everything is read from a temporary ledger. No provider or model is called: the model counter below is a FAKE that only proves the
interface (nothing in the page path reaches it). Owner verbs (approve/accept) appear only on throw-away test data in a temp state root.

Fixture state root S (built once):
  hand  approved; outputs O1..O3 each covered by one command milestone. M1 passed on the artifact NOW, M2 passed on an OLDER artifact
        (stale), M3 never ran (only a testcase would exist)             -> O1 ok, O2 recheck, O3 none      (T24a E1-E3, T38b A/B/C)
  amd   approved revision 1 + amendment revision 2 waiting (with a reason, changed title/output/milestone/budget)   (T42 E3)
  acc   accepted
  prop  only proposed
  gone  approved, contract file removed (must not crash)
  and, in its own state root, OLD: a plan made by the real v2.1.0 code (the 2.1 format).
"""
import contextlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import contract as contracts, plan as plans, plan_cli, report, verdict

import tests.wf_oldversion as ov
import tests.wf_wheel as wh
from test_v2_l1 import milestone, plan_json

REPO = str(Path(__file__).resolve().parents[1])
HEADINGS = ['1. Yêu cầu', '2. Kết quả bàn giao', '3. Rủi ro', '4. Cách nghiệm thu', '5. Bằng chứng còn thiếu']
SHA40 = re.compile(r'[0-9a-f]{40}')


def three(**extra):
    return plan_json(milestones=[milestone('M1', covers=['O1']), milestone('M2', covers=['O2']), milestone('M3', covers=['O3'])],
                     output=['AC1 the first thing exists', 'AC2 the second thing exists', 'AC3 the third thing exists'], **extra)


class World:
    @classmethod
    def build(cls):
        cls.temp = tempfile.TemporaryDirectory()
        base = Path(cls.temp.name)
        cls.root, cls.elsewhere, cls.state = base / 'project', base / 'elsewhere', base / 'state'
        cls.root.mkdir(); cls.elsewhere.mkdir()
        cls.env = patch.dict(os.environ); cls.env.start()
        for name in ('ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(name, None)
        cls.git('init', '-q'); cls.git('config', 'user.name', 'T'); cls.git('config', 'user.email', 't@localhost')
        (cls.root / 'a.txt').write_text('one\n'); cls.git('add', '.'); cls.git('commit', '-q', '-m', 'base')
        cls.ledger = Ledger(cls.root, cls.state)

        def approved(name, value):
            plans.propose(cls.ledger, name, value, 'claude'); return plans.approve(cls.ledger, name, 'owner', 'test data: said yes')

        # acc: accepted on the artifact of the moment (own project is the same repo: take it before `hand` moves the tree)
        approved('acc', plan_json(title='Accepted plan', milestones=[milestone('M1')]))
        verdict.run(cls.ledger, 'acc', 'M1', cls.root)
        plans.accept(cls.ledger, 'acc', 'owner', 'test data: ok', cls.tree())
        # hand: M1, M2 pass on tree A1; the tree then moves (A2); M1 passes again on A2; M2 stays on A1 (stale); M3 never runs
        approved('hand', three(title='Handover by acceptance'))
        verdict.run(cls.ledger, 'hand', 'M1', cls.root); verdict.run(cls.ledger, 'hand', 'M2', cls.root)
        cls.old_tree = cls.tree()
        (cls.root / 'b.txt').write_text('two\n')
        verdict.run(cls.ledger, 'hand', 'M1', cls.root)
        cls.now_tree = cls.tree()
        # amd: revision 2 waits for the owner
        approved('amd', plan_json(title='Amend me', milestones=[milestone('M1', covers=['O1'])]))
        new = plan_json(title='Amend me, bigger', output=['The sample exists', 'A second thing exists'], non_goals=['Nothing else', 'No new dependency'],
                        milestones=[milestone('M1', covers=['O1']), milestone('M2', covers=['O2'])])
        new['budget'] = {'max_calls': 100, 'time': 240}
        plans.amend(cls.ledger, 'amd', new, 'the owner asked for a second thing', 'claude')
        plans.propose(cls.ledger, 'prop', plan_json(title='Only proposed'), 'claude')
        pres = plan_json(title='With presentation', presentation={
            'request': 'Chủ sở hữu muốn một trang dễ đọc.', 'user_sees': ['Một trang chữ.'], 'acceptance_steps': ['Mở trang.', 'Đọc năm mục.'],
            'risk': ['Có thể thiếu mục nếu sổ cũ.']}, origin={'by': 'owner', 'at': 'chat', 'quote': 'tôi muốn đọc ngắn'}, decisions=[])
        pres['items'] = [dict(i, source='origin') for i in pres['items']]
        plans.propose(cls.ledger, 'pres', pres, 'claude')
        approved('gone', plan_json(title='Contract gone'))
        contracts.revision_path(cls.ledger, 'gone', 1).unlink()
        # OLD: the real v2.1.0 code made this plan (schema 2, 2.1 format); the new code only reads it
        cls.runs = ov._short_runs()
        old = ov.OldVersion(ov.archive('v2.1.0', REPO, cls.runs))
        cls.old_proj, cls.old_state = ov.git_project(cls.runs, 'OP'), cls.runs / 'OS'
        file = cls.runs / 'old.json'; file.write_text(json.dumps(ov.contract('Old 2.1 plan')), encoding='utf-8')
        assert old.run(cls.old_proj, cls.old_state, 'plan', 'propose', 'oldp', '--file', str(file), '--author', 'claude-probe')[0] == 0
        ov.make_approved(cls.old_state, ov.anchor_id(cls.old_state, ov.project_id(cls.old_state, cls.old_proj), 'plan:oldp'), 'oldp')
        assert old.run(cls.old_proj, cls.old_state, 'verdict', 'run', '--plan', 'oldp', '--milestone', 'M1')[0] == 0

    @classmethod
    def close(cls):
        cls.env.stop(); cls.temp.cleanup(); shutil.rmtree(cls.runs, ignore_errors=True)

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


class Base(unittest.TestCase):
    def setUp(self):
        for name in ('temp', 'root', 'elsewhere', 'state', 'ledger', 'old_tree', 'now_tree', 'old_proj', 'old_state'): setattr(self, name, getattr(World, name))

    def run_cli(self, *argv, state=None, project=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = plan_cli.main(['--project', str(project or self.root), '--state-root', str(state or self.state), *argv])
        return code, out.getvalue()

    def present(self, name, **kw):
        code, text = self.run_cli('plan', 'present', name, *sum((['--' + k, str(v)] for k, v in kw.items()), []))
        self.assertEqual(code, 0, text)
        return text

    def show(self, name):
        code, text = self.run_cli('plan', 'show', name)
        self.assertEqual(code, 0, text)
        return json.loads(text)

    def block(self, text, number):
        """The lines of numbered section `number` (1-5) of a present page."""
        lines = text.splitlines()
        start = lines.index(HEADINGS[number - 1]) + 1
        end = lines.index(HEADINGS[number]) if number < 5 else len(lines)
        return [l for l in lines[start:end] if l.strip()]

    def ac_lines(self, text, oid):
        """The line that opens the acceptance `oid` in the handover block (and nothing of its evidence lines)."""
        found = [l for l in text.splitlines() if re.match(rf'  {oid} (đạt|cần kiểm lại|chưa có) «', l)]
        self.assertEqual(len(found), 1, (oid, found))
        return found[0]

    def ac_block(self, text, oid):
        """The acceptance line plus its indented evidence lines, up to the next acceptance."""
        lines, out, on = text.splitlines(), [], False
        for line in lines:
            if re.match(rf'  {oid} (đạt|cần kiểm lại|chưa có) «', line): on = True; out.append(line); continue
            if on and re.match(r'\s{2}O\d+ ', line): break
            if on and line.startswith('      '): out.append(line)
            elif on: break
        return out

    def db_verdicts(self, name):
        """Independent of the code under test: the verdict.recorded events straight from sqlite."""
        conn = sqlite3.connect(str(self.state / 'ledger.sqlite3')); conn.row_factory = sqlite3.Row
        try:
            task = conn.execute("SELECT id FROM tasks WHERE request_key=?", ('plan-ns:' + name,)).fetchone()['id']
            return [json.loads(r['payload']) for r in conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='verdict.recorded' ORDER BY seq", (task,))]
        finally:
            conn.close()


# ======================================================================================================================
class HandoverByAcceptanceTests(Base):
    """T24a (E1-E3) and T38b (E4, E7, E8): the handover report puts each acceptance in ok / recheck / none, with a link to real evidence."""

    def text(self):
        return report.render_handover(self.state, 'hand')

    def test_e1_each_acceptance_is_in_its_state_with_evidence_link(self):
        text = self.text()
        o1, o2, o3 = (self.ac_block(text, o) for o in ('O1', 'O2', 'O3'))
        self.assertIn('đạt', o1[0]); self.assertNotIn('cần kiểm lại', o1[0])
        self.assertIn('cần kiểm lại', o2[0]); self.assertIn('chưa có', o3[0])
        # AC1: a link to a receipt that exists in the ledger's blob store, and it belongs to plan hand / M1 / the artifact now
        link = re.search(r'biên nhận (\S+)', ' '.join(o1))
        self.assertIsNotNone(link, o1)
        path = Path(link.group(1)); self.assertTrue(path.is_file(), path)
        body = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual((body['plan'], body['milestone'], body['artifact_sha']), ('hand', 'M1', self.now_tree))
        self.assertIn(self.now_tree, ' '.join(o1))
        # AC2: the stale evidence is named - the old artifact it passed on and the artifact now
        joined = ' '.join(o2)
        self.assertIn(self.old_tree, joined); self.assertIn(self.now_tree, joined)
        # AC3: nothing ran
        self.assertIn('M3', ' '.join(o3)); self.assertNotIn('biên nhận', ' '.join(o3))

    def test_e3_nothing_but_fresh_evidence_is_reported_as_ok(self):
        """Compare the status of every acceptance with the verdicts read straight from sqlite (not through the code under test)."""
        verdicts = self.db_verdicts('hand')
        expected = {}
        for oid, mid in (('O1', 'M1'), ('O2', 'M2'), ('O3', 'M3')):
            mine = [v for v in verdicts if v['milestone'] == mid]
            expected[oid] = 'đạt' if mine and mine[-1]['result'] == 'pass' and mine[-1]['artifact_sha'] == self.now_tree else 'other'
        self.assertEqual(expected, {'O1': 'đạt', 'O2': 'other', 'O3': 'other'})
        # the counter-fixture is meaningful: a naive "has a pass verdict" reading WOULD call O2 ok
        self.assertEqual([v['result'] for v in verdicts if v['milestone'] == 'M2'], ['pass'])
        text = self.text()
        for oid, want in expected.items():
            line = self.ac_lines(text, oid)
            self.assertEqual('đạt' in line, want == 'đạt', line)
        # E8 / E3: no line that belongs to AC2 or AC3 says đạt
        for oid in ('O2', 'O3'): self.assertNotIn('đạt', ' '.join(self.ac_block(text, oid)))

    def test_counter_a_report_that_ignores_the_artifact_would_call_ac2_ok(self):
        """The fixture discriminates: with the milestone views taken WITHOUT the artifact check (what a naive 'has a pass verdict' reading sees),
        AC2 reads ok - the assertion of the E3 test would go red."""
        naive = lambda ledger, contract, state, revision: plans.milestone_views(contract, state, revision)
        with patch.object(plans, 'views_for', naive):
            text = report.render_handover(self.state, 'hand')
        self.assertIn('đạt', self.ac_lines(text, 'O2'))
        self.assertNotIn('đạt', self.ac_lines(report.render_handover(self.state, 'hand'), 'O2'))

    def test_e2_limits_are_listed_and_name_the_open_acceptances(self):
        lines = report.render_handover(self.state, 'hand').splitlines()
        start = lines.index('Hạn chế còn lại:')
        limits = [l for l in lines[start + 1:] if l.strip()]
        self.assertTrue(limits)
        joined = ' '.join(limits)
        self.assertIn('O2', joined); self.assertIn('O3', joined); self.assertNotIn('O1 ', joined)
        self.assertNotIn('đạt', ' '.join(l for l in limits if 'O2' in l or 'O3' in l))

    def test_a_receipt_that_cannot_be_read_does_not_count_as_evidence(self):
        copy = Path(self.temp.name) / 'state-copy'
        shutil.copytree(self.state, copy)
        key = [v for v in self.db_verdicts('hand') if v['milestone'] == 'M1'][-1]['receipt']
        (copy / 'snapshots' / 'blobs' / key).unlink()
        text = report.render_handover(copy, 'hand')
        self.assertNotIn('đạt', self.ac_lines(text, 'O1'))
        self.assertIn('cần kiểm lại', self.ac_lines(text, 'O1'))
        shutil.rmtree(copy)

    def test_an_accepted_plan_reads_ok_on_the_artifact_accepted(self):
        text = report.render_handover(self.state, 'acc')
        self.assertIn('đạt', self.ac_lines(text, 'O1'))
        self.assertIn('trạng thái accepted', text)

    def test_the_report_does_not_read_the_register_it_does_not_have_yet(self):
        """Finding lists belong to W23d (R05): the page says so instead of implying there are none."""
        self.assertIn('Finding còn mở', report.render_handover(self.state, 'acc'))

    def test_cli_report_handover_flag_and_default_report_unchanged(self):
        code, text = self.run_cli('plan', 'report', 'hand', '--handover')
        self.assertEqual((code, text), (0, report.render_handover(self.state, 'hand') + '\n'))
        code, plain = self.run_cli('plan', 'report', 'hand')
        self.assertEqual((code, plain), (0, report.render_report(self.state, 'hand') + '\n'))
        self.assertNotIn('Hạn chế còn lại', plain)


# ======================================================================================================================
class PlanPresentTests(Base):
    """T42: a plain-text page from the ledger, five sections, the diff of a pending revision, old plans readable, equal to `plan show`."""

    NAMES = ('hand', 'amd', 'acc', 'prop', 'gone')

    def test_e1_e4_plain_text_page_for_every_plan_exit_zero(self):
        for name in self.NAMES:
            code, text = self.run_cli('plan', 'present', name)
            self.assertEqual(code, 0, (name, text))
            self.assertTrue(text.strip(), name)
            self.assertNotIn('Traceback', text)

    def test_e2_five_sections_in_order_for_every_plan(self):
        for name in self.NAMES:
            lines = self.present(name).splitlines()
            positions = [lines.index(h) for h in HEADINGS]
            self.assertEqual(positions, sorted(positions), name)
            self.assertEqual([l for l in lines if re.match(r'\d\. ', l)], HEADINGS, name)

    def test_e10_no_html_graph_or_timeline(self):
        for name in self.NAMES:
            text = self.present(name)
            self.assertIsNone(re.search(r'<\s*/?[A-Za-z!][^>]*>', text), name)
            for token in ('```', 'mermaid', 'timeline', 'digraph', '<svg'): self.assertNotIn(token, text.lower(), (name, token))

    def test_e1_e7_no_model_is_called(self):
        calls = []
        real = subprocess.run

        def guard(argv, *a, **k):
            calls.append(Path(argv[0]).stem)
            return real(argv, *a, **k)
        counter = {'n': 0}

        def fake_model(*a, **k):                       # a FAKE adapter that only counts: the page path must never reach it
            counter['n'] += 1
            raise AssertionError('a model was called')
        with patch('subprocess.run', side_effect=guard), patch('onecrew.v2.claude_cli.ask', fake_model, create=True), \
                patch('onecrew.v2.claude_cli.run', fake_model, create=True):
            for name in self.NAMES: self.present(name)
        self.assertEqual(counter['n'], 0)
        self.assertEqual(set(calls), {'git'})          # the one outside look (the artifact now); no other program

    def test_e5_e8_every_fact_matches_plan_show(self):
        for name in ('hand', 'amd', 'acc', 'prop'):
            text, shown = self.present(name), self.show(name)
            lines = text.splitlines()
            self.assertEqual(lines[0], f'TRÌNH: {name} — bản {shown["revision"]}/{shown["latest_revision"]}, trạng thái {shown["status"]}', name)
            self.assertIn(f'Bản đã duyệt: {shown["approved_revision"] if shown["approved_revision"] else "chưa có"}', lines, name)
            self.assertIn(f'Sha bản: {shown["sha"]}', lines, name)
            self.assertIn(f'Mã việc: {shown["anchor_task"]}', lines, name)
            for m in shown['milestones']:
                row = next(l for l in lines if re.match(rf'\s+{m["id"]} (passed|pending|failed|stopped)', l))
                self.assertTrue(row.strip().startswith(f'{m["id"]} {m["state"]}'), (name, row))
                if m['last_verdict']: self.assertIn(m['last_verdict']['artifact_sha'], row, (name, row))

    def test_e5_milestone_facts_on_the_stale_plan_are_the_plan_show_ones(self):
        shown = {m['id']: m for m in self.show('hand')['milestones']}
        self.assertEqual({k: v['state'] for k, v in shown.items()}, {'M1': 'passed', 'M2': 'pending', 'M3': 'pending'})   # show itself calls M2 stale-pending
        self.assertTrue(shown['M2'].get('stale'))
        text = self.present('hand')
        row = next(l for l in text.splitlines() if re.match(r'\s+M2 pending', l))
        self.assertIn('cũ', row)                                                    # and the page spells the staleness `plan show` carries as a flag
        self.assertIn(shown['M2']['last_verdict']['artifact_sha'], row)

    def test_e3_a_pending_revision_shows_the_diff_and_the_reason(self):
        text = self.present('amd')
        with self.ledger.transaction() as conn:
            state = plans.derive(self.ledger, conn, 'amd')
        self.assertEqual((state['latest'], state['approved']['revision']), (2, 1))
        old = contracts.read_revision(self.ledger, 'amd', 1)[0]
        new = contracts.read_revision(self.ledger, 'amd', 2)[0]
        changed = {k for k in set(old) | set(new) if old.get(k) != new.get(k)}
        self.assertGreaterEqual(len(changed), 4)
        head = text.splitlines().index('ĐỔI SO VỚI BẢN ĐÃ DUYỆT (bản 1 → bản 2)')
        block = text.splitlines()[head + 1:text.splitlines().index(HEADINGS[0])]
        shown_keys = {m.group(1) for l in block if (m := re.match(r'  - (\w+)', l))}
        self.assertEqual(shown_keys, changed)                                  # every changed top-level field, and only those
        # the reason is the plan.amended payload's, word for word
        conn = sqlite3.connect(str(self.state / 'ledger.sqlite3'))
        reason = json.loads(conn.execute("SELECT payload FROM events WHERE kind='plan.amended'").fetchone()[0])['reason']
        conn.close()
        self.assertEqual(reason, 'the owner asked for a second thing')
        self.assertIn(f'Lý do amend: «{reason}»', block)
        # the content of the diff: the new output, the new non-goal and the budget change are named with their values
        joined = ' '.join(block)
        for needle in ('A second thing exists', 'No new dependency', '240', 'Amend me, bigger'): self.assertIn(needle, joined)

    def test_e3_counter_a_plan_without_a_pending_revision_has_no_diff_block(self):
        for name in ('hand', 'acc', 'prop', 'gone'): self.assertNotIn('ĐỔI SO VỚI BẢN ĐÃ DUYỆT', self.present(name))

    def test_e4_an_old_2_1_plan_is_presented(self):
        code, text = self.run_cli('plan', 'present', 'oldp', state=self.old_state, project=self.old_proj)
        self.assertEqual(code, 0, text)
        lines = text.splitlines()
        self.assertEqual([l for l in lines if re.match(r'\d\. ', l)], HEADINGS)
        self.assertIn('trạng thái approved', lines[0])
        self.assertIn('Old 2.1 plan', text)
        # same facts as the OLD binary's own `plan show`
        old = ov.OldVersion(Path(World.runs) / 'base-v2.1.0')
        shown = json.loads(old.run(self.old_proj, self.old_state, 'plan', 'show', 'oldp')[1])
        self.assertIn(f'Sha bản: {shown["sha"]}', lines)
        self.assertTrue(any(l.strip().startswith('M1 passed') for l in lines))

    def test_e4_an_unreadable_contract_prints_no_data_instead_of_crashing(self):
        text = self.present('gone')
        self.assertIn(report.NO_DATA, text)
        self.assertEqual([l for l in text.splitlines() if re.match(r'\d\. ', l)], HEADINGS)

    def test_unknown_plan_is_refused_without_a_traceback(self):
        code, text = self.run_cli('plan', 'present', 'nope')
        self.assertEqual(code, 2); self.assertIn('nope', text); self.assertNotIn('Traceback', text)

    def test_e6_plan_report_is_the_full_page_and_present_does_not_change_it(self):
        before = {n: self.run_cli('plan', 'report', n) for n in self.NAMES}
        for n in self.NAMES: self.present(n)
        self.assertEqual({n: self.run_cli('plan', 'report', n) for n in self.NAMES}, before)
        for n in self.NAMES: self.assertEqual(before[n], (0, report.render_report(self.state, n) + '\n'))
        self.assertGreater(len(before['hand'][1].splitlines()), len(self.present('hand').splitlines()) // 2)
        self.assertIn('1. Output đạt tới đâu', before['hand'][1])

    def test_present_writes_nothing_and_out_is_the_only_write(self):
        def snapshot():
            files = sorted(str(p.relative_to(self.state)) for p in self.state.rglob('*') if p.is_file())
            return files, (self.state / 'ledger.sqlite3').read_bytes()
        before = snapshot()
        for n in self.NAMES: self.present(n)
        self.assertEqual(snapshot(), before)
        target = Path(self.temp.name) / 'out' / 'present.txt'
        code, text = self.run_cli('plan', 'present', 'hand', '--out', str(target))
        self.assertEqual(code, 0); self.assertIn('Đã ghi', text)
        self.assertEqual(target.read_text(encoding='utf-8'), report.render_present(self.state, 'hand'))
        self.assertEqual(self.run_cli('plan', 'present', 'hand', '--out', str(self.state / 'x.txt'))[0], 2)
        self.assertFalse((self.state / 'x.txt').exists())
        self.assertEqual(snapshot(), before)

    def test_section_2_carries_the_handover_by_acceptance(self):
        text = self.present('hand')
        self.assertIn('đạt', self.ac_lines(text, 'O1')); self.assertIn('cần kiểm lại', self.ac_lines(text, 'O2'))
        self.assertIn('chưa có', self.ac_lines(text, 'O3'))
        self.assertNotIn('đạt', ' '.join(self.ac_block(text, 'O3')))
        # section 5 names the missing evidence of AC2 and AC3 and not AC1
        missing = ' '.join(self.block(text, 5))
        self.assertIn('O2', missing); self.assertIn('O3', missing); self.assertNotIn('O1', missing)

    def test_section_5_says_nothing_is_missing_when_everything_is_proven(self):
        self.assertIn('không thiếu', ' '.join(self.block(self.present('acc'), 5)))

    def test_presentation_words_of_the_owner_are_used_when_the_contract_has_them(self):
        text = self.present('pres')
        self.assertIn('Chủ sở hữu muốn một trang dễ đọc.', ' '.join(self.block(text, 1)))
        self.assertIn('Một trang chữ.', ' '.join(self.block(text, 2)))
        self.assertIn('Có thể thiếu mục nếu sổ cũ.', ' '.join(self.block(text, 3)))
        steps = self.block(text, 4)
        self.assertTrue(any('1. Mở trang.' in l for l in steps)); self.assertTrue(any('2. Đọc năm mục.' in l for l in steps))


# ======================================================================================================================
@unittest.skipUnless(shutil.which('git'), 'git required')
class InstalledCommandTests(Base):
    """The command works from the INSTALLED wheel (hand-built, offline venv), not only from the checkout."""

    @classmethod
    def setUpClass(cls):
        cls.runs = wh._runs()
        cls.whl, _, (cls.modules, cls.packages) = wh.build_wheel(cls.runs)
        cls.py = wh.make_venv(cls.runs)
        wh.install(cls.py, cls.whl)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    def installed(self, *argv):
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONSTARTUP', 'PYTHONHOME', 'ONECREW_ACTOR')}
        script = self.py.parent / ('onecrew.exe' if os.name == 'nt' else 'onecrew')
        r = subprocess.run([str(script), '--project', str(self.elsewhere), '--state-root', str(self.state), *argv],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', env=env, cwd=str(self.elsewhere))
        return r.returncode, r.stdout + r.stderr

    def test_present_and_handover_run_from_the_installed_entry_point(self):
        script = self.py.parent / ('onecrew.exe' if os.name == 'nt' else 'onecrew')
        self.assertTrue(script.exists(), script)
        code, text = self.installed('plan', 'present', 'hand')
        self.assertEqual(code, 0, text)
        self.assertEqual([l for l in text.splitlines() if re.match(r'\d\. ', l)], HEADINGS)
        self.assertEqual(text.strip(), report.render_present(self.state, 'hand').strip())      # the installed page is the checkout page
        code, text = self.installed('plan', 'report', 'hand', '--handover')
        self.assertEqual(code, 0, text)
        self.assertIn('Hạn chế còn lại:', text)
        self.assertEqual(self.installed('plan', 'present', 'nope')[0], 2)

    def test_the_installed_modules_stay_inside_the_boundary(self):
        """T33a still holds: running the command from the install loads only shipped modules, stdlib and declared dependencies."""
        from onecrew.v2 import boundary
        body = ('import sys' + chr(10) + 'from onecrew.v2 import cli' + chr(10) +
                f'rc = cli.main(["--project", {str(self.elsewhere)!r}, "--state-root", {str(self.state)!r}, "plan", "present", "hand"])' + chr(10) +
                'assert rc == 0' + chr(10))
        data, tail = wh.run_case(self.py, body)
        self.assertIsNotNone(data, tail)
        ctx = wh.build_ctx(self.py, self.modules, self.packages)
        bad = boundary.violations(data['end'], ctx)
        self.assertEqual([n for n, _ in bad if n.startswith('onecrew')], [], bad)


if __name__ == '__main__':
    unittest.main()
