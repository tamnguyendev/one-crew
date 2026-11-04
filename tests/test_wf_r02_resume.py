"""T46a (W23b, R02) — the read-only resume pack (`onecrew continue <plan>`).

Fixture (05 T46): four plans in one temp state root — P1 running (an approval with a reference and a chosen option, one milestone reached, one not,
one open question, one answered question), P2 with an amendment waiting for approval, P3 accepted, P4 stopped_with_report. Built with the real v2
functions; the owner's terminal is simulated the way tests/test_v2_report.py does (markers removed), the AI session by CLAUDE_CODE_CHILD_SESSION —
that only proves the interface/permission, not a real new session carrying on a real job (T35c E27).

Expected values are read from the ledger / `plan show`, never from the pack builder. Counter-examples: a pack without the open-question section is
caught by the section check; a pack that computes its own diff is caught by the amendment check (the pending change must equal the diff of the two
revision files); a pack builder that wrote anything (ledger, git refs, active-plan.json, hook config) is caught by the before/after hashes.
"""
import hashlib
import json
import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger
from onecrew.v2 import cli, contract as contracts, plan as plans, resume_pack, verdict
from wf_r02 import BAD, Sandbox, anchor, approved, events, git_log, milestone, model_calls, pass_all, plan_json, run_cli, tree
from test_v2_l3 import step0_json

REPO = Path(__file__).resolve().parents[1]
WRITE_VERBS = {'commit', 'update-ref', 'push', 'checkout', 'reset', 'merge', 'rebase', 'tag', 'branch', 'stash', 'clean', 'fetch', 'pull'}
TWO = dict(milestones=[milestone('M1', covers=['O1']), milestone('M2', covers=['O2'])], output=['The sample exists', 'The sample is proven'])


def question(text, key):
    return {'schema_version': 1, 'question': text, 'reason': 'the plan needs a decision that is the owner\'s', 'impact': 'the work waits',
            'options': [{'id': 'yes', 'label': 'Yes'}, {'id': 'no', 'label': 'No'}], 'recommendation': 'yes',
            'action': {'type': 'v2.note', 'parameters': {'key': key}}}


def digest_of(paths):
    return {str(p): (hashlib.sha256(Path(p).read_bytes()).hexdigest(), Path(p).stat().st_mtime_ns) for p in paths if Path(p).is_file()}


class ResumeBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sandbox = Sandbox()
        cls.root = cls.sandbox.project('P1', {'a.txt': 'one\n', 'x/y.py': 'x = 1\n' * 3})
        cls.state = cls.sandbox.state('S')
        cls.ledger = cls.sandbox.ledger(cls.root, cls.state)
        L = cls.ledger
        # P1: running
        approved(L, 'p1', step0_json(title='Running plan', **TWO), choose='B')
        pass_all(L, 'p1', cls.root, ('M1',))
        cls.req_open = L.create_request(anchor(L, 'p1'), 'q-open', question('Open: may the export also write CSV?', 'q-open'))
        answered = L.create_request(anchor(L, 'p1'), 'q-done', question('Answered: keep the old column order?', 'q-done'))
        cls.req_answered = answered
        L.reply(answered['id'], answered['revision'], 'yes', source='terminal', reference='owner said yes in chat 24/10')
        # P2: an amendment waits
        approved(L, 'p2', plan_json(title='Amended plan'))
        amended = plan_json(title='Amended plan', milestones=[milestone('M1', covers=['O1'], title='Milestone M1, now stricter')])
        plans.amend(L, 'p2', amended, 'the owner asked for a stricter milestone title', 'claude')
        # P3: accepted
        approved(L, 'p3', plan_json(title='Accepted plan'))
        pass_all(L, 'p3', cls.root)
        plans.accept(L, 'p3', 'owner', 'ok', tree(cls.root))
        # P4: stopped
        approved(L, 'p4', plan_json(title='Stopped plan', milestones=[milestone(argv=BAD, max_repairs=0)]))
        verdict.run(L, 'p4', 'M1', cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.sandbox.close()

    def cli(self, *args):
        return run_cli(['--project', str(self.root), '--state-root', str(self.state), *args])

    def pack(self, name):
        code, out, err = self.cli('continue', name, '--json')
        self.assertEqual(code, 0, out + err)
        return json.loads(out)

    def show(self, name):
        return plans.show(self.ledger, name)

    def events_total(self):
        with self.ledger.transaction() as conn:
            return conn.execute('SELECT COUNT(*) FROM events').fetchone()[0], conn.execute('SELECT COUNT(*) FROM requests').fetchone()[0]


def missing_sections(pack):
    """The five sections of T46a E1 as the owner's flow reads them; the names of the ones this pack lacks."""
    problems = []
    if not pack.get('requirement'): problems.append('requirement')
    if not pack.get('decided') or not pack['decided'].get('approved'): problems.append('decided')
    if 'open_questions' not in pack: problems.append('open_questions')
    if not pack.get('milestones'): problems.append('milestones')
    if 'missing_evidence' not in pack: problems.append('missing_evidence')
    return problems


class ResumePackTests(ResumeBase):
    # E1
    def test_e1_five_sections_with_the_facts_of_the_fixture(self):
        pack = self.pack('p1')
        self.assertEqual(missing_sections(pack), [])
        self.assertEqual(pack['requirement']['goal'], 'Prove the sample.')
        approval = pack['decided']['approved']
        self.assertEqual((approval['revision'], approval['reference'], approval['chosen']), (1, 'said yes in chat', 'B'))
        answered = pack['decided']['answered_questions']
        self.assertEqual([(q['request'], q['choice'], q['reference']) for q in answered],
                         [(self.req_answered['id'], 'yes', 'owner said yes in chat 24/10')])
        self.assertEqual([q['request'] for q in pack['open_questions']], [self.req_open['id']])
        states = {m['id']: m['state'] for m in pack['milestones']}
        self.assertEqual(states, {'M1': 'passed', 'M2': 'pending'})
        self.assertTrue(any('M2' in m['what'] for m in pack['missing_evidence']))
        self.assertFalse(any('M1' in m['what'] for m in pack['missing_evidence']))

    def test_e1_counter_a_pack_without_the_open_question_section_is_caught(self):
        pack = self.pack('p1'); del pack['open_questions']
        self.assertEqual(missing_sections(pack), ['open_questions'])

    # E2 / E11: the pending revision's change comes from the ledger (the two revision files and plan.amended)
    def test_e11_pending_change_and_reason_come_from_the_ledger(self):
        pack = self.pack('p2')
        change = pack['pending_change']
        amended = [p for _, _, p in events(self.ledger, 'p2', 'plan.amended')][-1]
        self.assertEqual(change['reason'], amended['reason'])
        self.assertEqual((change['from_revision'], change['to_revision']), (1, 2))
        old = contracts.read_revision(self.ledger, 'p2', 1, events(self.ledger, 'p2', 'plan.proposed')[0][2]['sha'])[0]
        new = contracts.read_revision(self.ledger, 'p2', 2, amended['sha'])[0]
        expected_paths = {'milestones[M1].title'}
        self.assertEqual({c['path'] for c in change['changes']}, expected_paths)
        only = change['changes'][0]
        self.assertEqual((only['before'], only['after']), (old['milestones'][0]['title'], new['milestones'][0]['title']))
        self.assertEqual(resume_pack.changes_vs_approved(old, new), change['changes'])        # one function; plan present (W23a) must call this one
        self.assertIsNone(self.pack('p1')['pending_change'])

    # E3
    def test_e3_all_four_plans_and_who_moves(self):
        for name in ('p1', 'p2', 'p3', 'p4'):
            code, out, err = self.cli('continue', name)
            self.assertEqual(code, 0, name + out + err)
        self.assertEqual(self.pack('p3')['remaining'], {'who': None, 'what': 'không còn việc'})
        self.assertEqual(self.pack('p4')['remaining']['who'], 'chủ sở hữu')
        self.assertEqual(self.pack('p2')['remaining']['who'], 'chủ sở hữu')
        self.assertEqual(self.pack('p1')['remaining']['who'], 'chủ sở hữu')                    # an open question is the owner's
        self.assertEqual(self.pack('p4')['status'], 'stopped_with_report')
        self.assertEqual(self.pack('p3')['missing_evidence'], [])

    # E4
    def test_e4_header_says_data_not_authority_with_the_largest_seq(self):
        for name in ('p1', 'p2', 'p3', 'p4'):
            pack = self.pack(name)
            self.assertIs(pack['is_authority'], False)
            self.assertEqual(pack['max_seq'], max(seq for seq, _, _ in events(self.ledger, name)))
            code, text, _ = self.cli('continue', name)
            lines = text.splitlines()
            self.assertEqual(lines[0], f'GÓI TIẾP TỤC — đây là dữ liệu đọc từ sổ, không phải quyền. seq lớn nhất của plan: {pack["max_seq"]}.')
            self.assertEqual(lines[1], 'Công cụ không chạy hook OneCrew thì các giới hạn trong gói này không được thực thi ở đó.')

    # E5
    def test_e5_a_read_only_verb_of_the_wheel_that_runs_in_an_ai_session(self):
        code, out, _ = run_cli(['--help'])
        self.assertIn('continue', out)
        self.assertIn('continue', cli.GROUPS)
        modules = re.findall(r'"(onecrew\.[\w.]+)"', (REPO / 'pyproject.toml').read_text(encoding='utf-8'))
        self.assertIn('onecrew.v2.resume_pack', modules); self.assertIn('onecrew.v2.evidence_cli', modules)
        with patch.dict(os.environ, {'CLAUDE_CODE_CHILD_SESSION': '1'}):
            code, out, err = self.cli('continue', 'p1')
        self.assertEqual(code, 0, out + err)

    # E6
    def test_e6_every_fact_matches_plan_show(self):
        for name in ('p1', 'p2', 'p3', 'p4'):
            pack, shown = self.pack(name), self.show(name)
            self.assertEqual((pack['plan'], pack['status'], pack['revision'], pack['latest_revision'], pack['approved_revision'], pack['anchor_task']),
                             (shown['plan'], shown['status'], shown['revision'], shown['latest_revision'], shown['approved_revision'], shown['anchor_task']), name)
            self.assertEqual({m['id']: m['state'] for m in pack['milestones']}, {m['id']: m['state'] for m in shown['milestones']}, name)
        self.assertEqual({q['request'] for q in self.pack('p1')['open_questions']} | {q['request'] for q in self.pack('p1')['decided']['answered_questions']},
                         {self.req_open['id'], self.req_answered['id']})

    # E7 / E8 / E10: nothing is written, no model, no worker; the questions stay as they were
    def test_e7_e8_e10_the_pack_writes_nothing_and_answers_nothing(self):
        watched = [p for p in self.state.rglob('active-plan.json')] + [p for d in ('.claude', '.onecrew') for p in (self.root / d).rglob('*')]
        head = lambda: (self.sandbox.git(self.root, 'rev-parse', 'HEAD'), self.sandbox.git(self.root, 'for-each-ref'), self.sandbox.git(self.root, 'status', '--porcelain'))
        ledger_file = self.state / 'ledger.sqlite3'
        before = (digest_of(watched), head(), self.events_total(), digest_of([ledger_file]))
        with model_calls() as calls, git_log() as git:
            for name in ('p1', 'p2', 'p3', 'p4'):
                self.assertEqual(self.cli('continue', name)[0], 0)
                self.assertEqual(self.cli('continue', name, '--json')[0], 0)
        after = (digest_of(watched), head(), self.events_total(), digest_of([ledger_file]))
        self.assertEqual(calls, [])
        self.assertEqual({a[0] for a in git} & WRITE_VERBS, set(), 'a git write command ran')
        self.assertEqual(before, after)
        with self.ledger.transaction() as conn:
            pending = [r['id'] for r in conn.execute("SELECT id FROM requests WHERE state='pending'")]
            kinds = {r['kind'] for r in conn.execute("SELECT DISTINCT kind FROM events WHERE seq > ?", (before[2][0],))}
        self.assertIn(self.req_open['id'], pending)
        self.assertEqual(kinds, set())

    def test_e10_the_code_starts_no_worker_and_calls_no_provider(self):
        for module in ('resume_pack.py', 'evidence_cli.py'):
            source = (REPO / 'onecrew' / 'v2' / module).read_text(encoding='utf-8')
            for pattern in (r'\bsubprocess\b', r'\bPopen\b', r'claude_cli', r'\badvisor\b', r'\breviewer\b', r'\bspawn', r'\bworker\b'):
                self.assertIsNone(re.search(pattern, source), f'{module}: {pattern}')

    # E9: after the pack an AI session still cannot approve or accept
    def test_e9_the_pack_is_not_authority(self):
        self.pack('p2')
        total = self.events_total()
        with patch.dict(os.environ, {'CLAUDE_CODE_CHILD_SESSION': '1'}):
            code1, out1, _ = self.cli('plan', 'approve', 'p2', '--by', 'owner', '--reference', 'from the pack')
            code2, out2, _ = self.cli('plan', 'accept', 'p1', '--by', 'owner', '--reference', 'from the pack', '--artifact-sha', tree(self.root))
        self.assertEqual((code1, code2), (2, 2), out1 + out2)
        self.assertEqual(self.events_total(), total)
        self.assertEqual(self.show('p2')['status'], 'proposed')
        self.assertEqual(self.show('p1')['status'], 'approved')


if __name__ == '__main__':
    unittest.main()
