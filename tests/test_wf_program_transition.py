"""T39 (R00, WK0): the program runs through its milestones on the EXISTING v2 supervisor with exactly the routine owner actions.

Temporary ledger and Git project. The owner's terminal is simulated (AI-session markers cleared for owner verbs only: this
proves the interface and rights of each verb, not a human). Kit-guard is a fixture script run through the sha256-pinned
bootstrap of the real program contract; the Codex review result of M5 is a sample file; the reviewer CLI of the
counterexample plan is a stub that counts calls. Nothing real (Codex review, provider, pilot) is proven here.
"""
import contextlib
import datetime as dt
import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from onecrew import cli
from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import active_plan, gate, hook_cli, plan as plans, verdict
from onecrew.v2.verifiers import advisor, reviewer
from tests.test_v2_l1 import Fixture
from tests.test_v2_advisor import answers
from tests.test_v2_reviewer import reviewer_milestone
from wfkit import owner_actions, program_contract

AI = {'CLAUDE_CODE_CHILD_SESSION': '1'}
KIT = ('import sys\n'
       'print("fixture kit-guard:", sys.argv[1:])\n'
       'sys.exit(0)\n')
REVIEW_RESULT = b'Codex review of the whole program (sample file for the owner-manual milestone): no blocking finding.\n'


@contextlib.contextmanager
def owner_terminal():
    """The owner's own shell: no AI-session marker, no AI actor."""
    saved = {k: os.environ.pop(k) for k in ('CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE', 'ONECREW_ACTOR') if k in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)


class ProgramTransitionTests(Fixture):
    def setUp(self):
        super().setUp()
        self.outside = Path(self.temp.name) / 'outside'; self.outside.mkdir()
        self.kit = self.outside / 'kitguard.py'; self.kit.write_text(KIT, encoding='utf-8')
        self.kit_sha = program_contract.sha256_file(self.kit)
        self.chat = []
        self.chat_log = self.outside / 'chat-log.json'
        self.task_plan = self.outside / '04-TASKS.md'; self.task_plan.write_text('| W01 | ... |\n', encoding='utf-8')
        self.journal = self.outside / 'decisions.jsonl'
        self.store = Snapshots(self.ledger.state_root)
        rules = Path(self.ledger.state_root) / 'plans' / 'owner-rules.md'; rules.parent.mkdir(parents=True, exist_ok=True)
        rules.write_bytes((Path(__file__).resolve().parents[1] / 'examples' / 'owner-rules.vi.md').read_bytes())   # the advisor reads the owner's rules

    # ---- helpers -------------------------------------------------------------------------------------------------
    def say(self, kind, text, who='owner'):
        at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
        self.chat.append({'at': at, 'from': who, 'kind': kind, 'text': text})
        self.chat_log.write_text(json.dumps(self.chat, ensure_ascii=False), encoding='utf-8')
        return self.chat[-1]

    def contract(self):
        assignment = next((m for m in self.chat if m['kind'] == 'assign'), None) or {'from': 'owner', 'at': 'chat', 'text': 'Trình chương trình.'}
        origin = {'by': assignment['from'], 'at': assignment['at'], 'quote': assignment['text']}
        value = program_contract.build(kitguard_script=self.kit, kitguard_sha256=self.kit_sha, owned=('a.txt',), origin=origin)
        value['preconditions'] = [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'the project file'}]
        value['understanding']['target']['paths'] = ['a.txt']
        return value

    def propose_and_advise(self, name, contract, author='claude-fable-5-1'):
        """The AI's step 0: propose, then run the advisor (fake CLI answers; the decisions D1/D2 need its three answers)."""
        with patch.dict(os.environ, AI):
            plans.propose(self.ledger, name, contract, author)
            with patch.object(reviewer, 'call', return_value=(answers(), {}, None, False, b'fixture')):
                advisor.advise(self.ledger, name)

    def owner_approve_script(self, name='P1'):
        """Step 1: ONE owner script approves the program and turns enforce on (03 §2.4 row 2)."""
        with owner_terminal():
            plans.approve(self.ledger, name, 'owner', 'duyệt chương trình và bật enforce trong một script')
            gate.set_enforced(self.ledger, True, 'owner', 'cùng script duyệt')
            active_plan.set_mode(self.ledger, 'enforce')
            active_plan.export(self.ledger, name)

    def hook(self, tool, **tool_input):
        event = {'cwd': str(self.root), 'session_id': 'worker-session', 'tool_name': tool, 'tool_input': tool_input,
                 'hook_event_name': 'PreToolUse', 'permission_mode': 'default', 'tool_use_id': 'toolu_1'}
        error = io.StringIO()
        with patch.object(hook_cli, 'read_stdin', return_value=(event, None)), contextlib.redirect_stderr(error), patch.dict(os.environ, AI):
            code = hook_cli.check(SimpleNamespace(project=self.root, state_root=self.ledger.state_root))
        return code, error.getvalue()

    def anchor(self, name='P1'):
        with self.ledger.transaction() as conn:
            return plans.anchor_events(self.ledger, conn, name)['task_id']

    # ---- the run ----------------------------------------------------------------------------------------------------
    def test_program_runs_through_its_milestones_with_exactly_the_routine_owner_actions(self):
        self.say('assign', 'Trình chương trình workflow chung để duyệt.')                    # row 1: lives in chat only
        contract = self.contract()
        self.assertEqual(program_contract.check(contract), [])                                  # [E10], [E11] shape of the real contract
        self.propose_and_advise('P1', contract)
        with patch.dict(os.environ, AI):
            with self.assertRaises(LedgerError): plans.approve(self.ledger, 'P1', 'owner', 'AI tries')            # [E9]
        self.owner_approve_script()                                                               # step 1
        exported = json.loads(active_plan.project_file(self.root).read_text(encoding='utf-8'))
        self.assertEqual((exported['mode'], exported['status']), ('enforce', 'approved'))
        # step 2: the AI runs M1..M4 (command milestones through the sha256-pinned kit-guard bootstrap)
        with patch.dict(os.environ, AI):
            shown = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(shown['milestones'][0]['state'], 'passed', shown['milestones'])
        receipts = [e for e in self.events() if e[0] == 'verdict.recorded']
        self.assertEqual(len(receipts), 1); self.assertNotEqual(receipts[0][1]['by'], 'owner')   # [E3] no refusal in the AI session
        # a kit-guard whose bytes changed is refused by the pinned argv before it runs ([E11]: the contract pins the script by sha256)
        import subprocess
        argv = contract['milestones'][0]['verifier']['config']['argv']
        self.kit.write_text(KIT + '# weakened\n', encoding='utf-8')
        weakened = subprocess.run(argv, capture_output=True, text=True, cwd=self.root)
        self.assertNotEqual(weakened.returncode, 0); self.assertIn('sha256 mismatch', weakened.stdout + weakened.stderr)
        self.kit.write_text(KIT, encoding='utf-8')
        self.assertEqual(subprocess.run(argv, capture_output=True, text=True, cwd=self.root).returncode, 0)
        # step 3: the coordinator edits the task plan three times (outside the repo): no amend, three Q1 journal lines
        for edit in ('split W01 into W01a/W01b', 'merge W02 into W01b', 'reorder W03 before W01b'):
            self.task_plan.write_text(self.task_plan.read_text(encoding='utf-8') + '| ' + edit + ' |\n', encoding='utf-8')
            with self.journal.open('a', encoding='utf-8') as out: out.write(json.dumps({'q': 'Q1', 'edit': edit}) + '\n')
        self.assertEqual(self.kinds().count('plan.amended'), 0)                                   # [E2], [E8]
        self.assertEqual(len(self.journal.read_text(encoding='utf-8').splitlines()), 3)
        # step 4: a worker tries to write outside the scope -> blocked by the hook; in-scope work continues; one U2 card
        code, text = self.hook('Edit', file_path=str(self.root / 'outside.txt'))
        self.assertEqual(code, 2); self.assertIn('outside.txt', text)                              # [E4]
        self.assertEqual(self.hook('Edit', file_path=str(self.root / 'a.txt'))[0], 0)
        task_id = self.anchor()
        card = self.say('card', 'U2: worker cần ghi outside.txt ngoài scope. Cho phép mở rộng scope hay từ chối?', who='coordinator')
        question = {'schema_version': 1, 'question': card['text'], 'reason': 'ghi ngoài scope bị hook chặn', 'impact': 'việc liên quan chờ',
                    'options': [{'id': 'deny', 'label': 'Từ chối, giữ scope'}, {'id': 'amend', 'label': 'Mở rộng scope qua amend'}],
                    'recommendation': 'deny', 'action': {'type': 'scope-decision', 'parameters': {}}}
        request = self.ledger.create_request(task_id, 'u2-scope-outside', question)
        answer = self.say('owner-answer', 'Từ chối, giữ scope như đã duyệt.')
        with owner_terminal():
            self.ledger.reply(request['id'], request['revision'], 'deny', source='chat', reference=answer['text'] + ' @ ' + answer['at'],
                              decided_by='user', by='owner')
        self.assertEqual(len(self.ledger.requests(task_id)), 1)                                   # [E14]
        with patch.dict(os.environ, AI):                                                          # other milestones go on after the block ([E4])
            for mid in ('M2', 'M3', 'M4'):
                shown = verdict.run(self.ledger, 'P1', mid, self.root)
                self.assertEqual(shown['milestones'][int(mid[1]) - 1]['state'], 'passed', (mid, shown['milestones']))
        receipts = [e for e in self.events() if e[0] == 'verdict.recorded']
        self.assertEqual(len(receipts), 4); self.assertTrue(all(e[1]['by'] != 'owner' for e in receipts))     # [E3]
        # step 5: the hook window expires; Edit/Write/Bash in the project are blocked; the coordinator re-exports, no owner
        past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).isoformat()
        for path in (active_plan.project_file(self.root), Path(self.ledger.state_root) / 'plans' / self.ledger.project_id / 'active-plan.json'):
            if path.is_file():
                value = json.loads(path.read_text(encoding='utf-8')); value['expires'] = past
                active_plan._write(path, value)
        for tool, data in (('Edit', {'file_path': str(self.root / 'a.txt')}), ('Write', {'file_path': str(self.root / 'a.txt')}),
                           ('Bash', {'command': 'echo x > a.txt'})):
            code, text = self.hook(tool, **data)
            self.assertEqual(code, 2, (tool, text)); self.assertIn('expired', text)             # [E13]
        before = [e for e in self.events() if e[0] in ('plan.approved', 'plan.accepted')]
        with patch.dict(os.environ, AI), contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'hook', 'export', 'P1'])
        self.assertEqual(code, 0)
        for tool, data in (('Edit', {'file_path': str(self.root / 'a.txt')}), ('Write', {'file_path': str(self.root / 'a.txt')}),
                           ('Bash', {'command': 'echo x > a.txt'})):
            self.assertEqual(self.hook(tool, **data)[0], 0, tool)                                 # [E13] recovered without an owner verb ([E15])
        self.assertEqual([e for e in self.events() if e[0] in ('plan.approved', 'plan.accepted')], before)
        # step 6: the owner records the Codex review result for M5 and accepts, in one go; accept before that is refused
        artifact = self.tree()
        with owner_terminal():
            with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'too early', artifact)     # [E5]
            blob = self.store.blob(REVIEW_RESULT)
            verdict.record(self.ledger, 'P1', 'M5', 'pass', 'owner', blob, artifact)
            with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'other artifact', 'a' * 40)  # [E5]
            accepted = plans.accept(self.ledger, 'P1', 'owner', 'nghiệm thu chương trình', artifact)
        self.assertEqual(accepted['status'], 'accepted')
        with patch.dict(os.environ, AI):
            with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'AI tries', artifact)        # [E9]
        # the counting script, from the ledger + chat log ([E1], [E7], [E16])
        counted = owner_actions.count(self.ledger, 'P1', self.chat_log)
        self.assertTrue(counted['ok'], counted)
        self.assertEqual((counted['approvals'], counted['enforces'], counted['approve_actions']), (1, 1, 1))
        self.assertEqual((counted['manual_records'], counted['accepts'], counted['final_actions']), (1, 1, 1))
        self.assertEqual(counted['routine_decisions'], 2)
        self.assertEqual([c['kind'] for c in counted['cards']], ['card'])
        self.assertEqual(counted['amended'], 0)
        self.assertEqual(counted['chat'], {'assignments': 1, 'cards': 1, 'answers_matched': 1})
        # step 8: counterexample, an "approve milestone" step slipped into the process -> the count refuses ([E6], [E7])
        gate_q = dict(question, question='Duyệt mốc M2 trước khi chạy tiếp?', reason='duyệt mốc', action={'type': 'approve-milestone', 'parameters': {}})
        extra = self.ledger.create_request(task_id, 'approve-milestone-m2', gate_q)
        self.say('card', gate_q['question'], who='coordinator'); ok_msg = self.say('owner-answer', 'Duyệt.')
        with owner_terminal():
            self.ledger.reply(extra['id'], extra['revision'], 'deny', source='chat', reference=ok_msg['text'] + ' @ ' + ok_msg['at'], decided_by='user', by='owner')
        counter = owner_actions.count(self.ledger, 'P1', self.chat_log)
        self.assertFalse(counter['ok'])
        self.assertTrue(any('approve or accept a milestone' in p for p in counter['problems']), counter['problems'])

    def test_a_second_approval_is_more_than_the_two_routine_decisions(self):
        """[E6] by the ledger alone: a plan approved twice (an amendment approved like a milestone gate) is over the routine count."""
        self.propose_and_advise('P1', self.contract())
        self.owner_approve_script()
        amended = self.contract(); amended['title'] = 'Chương trình workflow chung, bản 2'
        with patch.dict(os.environ, AI):
            plans.amend(self.ledger, 'P1', amended, 'đổi tiêu đề', 'claude-fable-5-1')
            with patch.object(reviewer, 'call', return_value=(answers(), {}, None, False, b'fixture')): advisor.advise(self.ledger, 'P1')
        with owner_terminal():
            plans.approve(self.ledger, 'P1', 'owner', 'duyệt lại')
        counted = owner_actions.count(self.ledger, 'P1')
        self.assertEqual(counted['approvals'], 2)
        self.assertFalse(counted['ok']); self.assertTrue(any('routine owner decisions' in p for p in counted['problems']))

    def test_reviewer_copy_of_m5_is_inconclusive_over_the_diff_cap_and_blocks_accept(self):
        """[E12]: why M5 is owner-manual. The same contract with M5 = reviewer, a diff over 120 000 bytes since approval."""
        contract = self.contract()
        contract['milestones'][-1] = dict(reviewer_milestone(), id='M5', covers=['O5'], max_repairs=1)
        self.assertTrue(any('reviewer' in p for p in program_contract.check(contract)))             # the counterexample contract is flagged
        self.propose_and_advise('P2', contract, 'codex')
        with owner_terminal(): plans.approve(self.ledger, 'P2', 'owner', 'copy for the counterexample')
        with patch.dict(os.environ, AI):
            for mid in ('M1', 'M2', 'M3', 'M4'): verdict.run(self.ledger, 'P2', mid, self.root)
        (self.root / 'a.txt').write_text('x' * 130000 + '\n', encoding='utf-8')
        self.git('add', 'a.txt'); self.git('commit', '-qm', 'a large change after approval')
        calls = []
        with patch.object(reviewer, 'call', side_effect=lambda *a, **k: calls.append(1) or ('', {}, None, False, b'')), patch.dict(os.environ, AI):
            shown = verdict.run(self.ledger, 'P2', 'M5', self.root)
        last = shown['milestones'][-1]['last_verdict']
        self.assertEqual(last['result'], 'inconclusive'); self.assertEqual(calls, [])
        receipt = json.loads(self.store.read_blob(last['receipt']))
        self.assertIn('over the 120000', receipt['error'])
        with owner_terminal():
            with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P2', 'owner', 'try', self.tree())
