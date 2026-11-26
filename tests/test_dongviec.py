"""DONGVIEC: the owner closes an old plan with `onecrew owner close <plan> --reference R [--dry-run]` (= plan close --by owner).

A proposed, approved or stopped plan is closed by one plan.closed event by the owner (the owner's words, the status it had, closed_by owner_close);
an accepted or already closed plan is refused with nothing written; an AI session is refused; --dry-run writes nothing. A closed plan leaves the open
lists (plan digest, tracking page) and the engine runs nothing for it. Option dong-bo-giam-sat: the hooks stop governing a plan the owner closed
this way; a plan closed by the stop answer (owner answer --choice stop) keeps the old behaviour.

Rule of these cases (contract DONGVIEC, checker kiem-dongviec.py): a case of new behaviour fails BY ASSERTION on the base 2.5.0.dev33 (191a58f):
the missing verb or a refusal is turned into self.fail, never an error. Real temporary ledgers and Git (tests.v2_fixture); the hook runs as a real
subprocess (tests.test_v2_l2.HookFixture).
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))          # test_v2_l2 imports test_v2_l1 by its plain name
from test_v2_l2 import HookFixture, owned_plan                      # noqa: E402

from onecrew.ledger import LedgerError                              # noqa: E402
from onecrew.v2 import active_plan, engine, namespaces, plan as plans, questions, report, tracking, verdict   # noqa: E402
from onecrew.v2.ownership import AI_MARKERS                         # noqa: E402
from tests.test_wf_engine import node                                # noqa: E402
from tests.v2_fixture import BAD, milestone, plan_json               # noqa: E402

REPO = Path(__file__).resolve().parents[1]
WORDS = 'dọn sổ 26/11: việc cũ không làm nữa'


def owner_env():
    """The environment of the owner's own terminal: no AI-session marker, no declared AI actor."""
    return {k: v for k, v in os.environ.items() if k not in (*AI_MARKERS, 'CLAUDECODE', 'ONECREW_ACTOR')}


class Closing:
    """Shared helpers: the verb under test, and the ledger's bytes for 'nothing was written'."""

    def close_or_fail(self, name='P1', reference=WORDS, **kw):
        close = getattr(plans, 'close', None)
        if close is None: self.fail('there is no owner close (plan.close) to close a plan')
        try:
            return close(self.ledger, name, 'owner', reference, **kw)
        except LedgerError as error:
            self.fail('owner close refused a plan it should close: ' + str(error)[:300])

    def closed_events(self, name='P1'):
        return [p for k, p in self.events(name) if k == 'plan.closed']

    def ledger_bytes(self):
        path = Path(self.ledger.state_root) / 'ledger.sqlite3'
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None

    def stopped_plan(self, name='P1', workflow=False, value=None):
        """A plan whose milestone failed with no repair left: stopped_with_report, with the stop question pending."""
        raw = value or plan_json(milestones=[milestone(argv=BAD, max_repairs=0)])
        plans.propose(self.ledger, name, raw, 'codex', workflow=workflow, capabilities=list(namespaces.CAPABILITIES) if workflow else None)
        plans.approve(self.ledger, name, 'owner', 'fixture approval')
        verdict.run(self.ledger, name, 'M1')
        self.assertEqual(plans.show(self.ledger, name)['status'], 'stopped_with_report')
        return self.ledger.requests(plans.show(self.ledger, name)['anchor_task'], pending=True)[0]

    def cli(self, *words, env=None):
        done = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'onecrew', '--project', str(self.root), '--state-root', str(self.ledger.state_root),
                               'owner', 'close', *words], capture_output=True, cwd=REPO, timeout=120,
                              env=dict(env if env is not None else owner_env(), PYTHONUTF8='1'))
        return done.returncode, done.stdout.decode('utf-8', 'replace'), done.stderr.decode('utf-8', 'replace')


class TestDongViec(Closing, HookFixture):
    # ---- I1: owner close --------------------------------------------------------------------------------------------------------------
    def test_owner_close_closes_an_approved_plan(self):
        self.approved('P1')
        result = self.close_or_fail('P1')
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'closed')
        self.assertEqual(result.get('status'), 'closed')
        events = self.closed_events()
        self.assertEqual(len(events), 1, 'one plan.closed event')
        self.assertEqual((events[0].get('by'), events[0].get('reference'), events[0].get('previous_status'), events[0].get('closed_by')),
                         ('owner', WORDS, 'approved', 'owner_close'))
        self.assertNotIn('plan.accepted', self.kinds())                    # closing is not accepting
        with self.assertRaises(LedgerError): verdict.run(self.ledger, 'P1', 'M1')       # nothing runs for it any more
        with self.assertRaises(LedgerError): plans.approve(self.ledger, 'P1', 'owner', 'cannot reopen')

    def test_owner_close_closes_proposed_and_stopped(self):
        self.propose('P1')
        self.close_or_fail('P1', 'đề xuất cũ, không làm')
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'closed')
        self.assertEqual(self.closed_events('P1')[0].get('previous_status'), 'proposed')
        self.stopped_plan('P2')
        self.close_or_fail('P2', 'đã dừng, không làm tiếp')
        self.assertEqual(plans.show(self.ledger, 'P2')['status'], 'closed')
        self.assertEqual(self.closed_events('P2')[0].get('previous_status'), 'stopped_with_report')
        self.assertIn('ĐÃ ĐÓNG', report.render_present(self.ledger.state_root, 'P2'))

    def test_close_refused_for_accepted_or_closed(self):
        self.approved('P1')
        verdict.run(self.ledger, 'P1', 'M1')
        plans.accept(self.ledger, 'P1', 'owner', 'fixture acceptance', self.tree())
        before = self.ledger_bytes()
        with self.assertRaisesRegex(LedgerError, 'accepted'):
            plans.close(self.ledger, 'P1', 'owner', WORDS)
        self.assertEqual(self.ledger_bytes(), before, 'a refused close wrote something')
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'accepted')
        self.approved('P2')
        plans.close(self.ledger, 'P2', 'owner', WORDS)
        before = self.ledger_bytes()
        with self.assertRaisesRegex(LedgerError, 'closed'):
            plans.close(self.ledger, 'P2', 'owner', 'again')
        self.assertEqual(self.ledger_bytes(), before)
        self.assertEqual(len(self.closed_events('P2')), 1)

    # ---- I2: owner only; the dry run -------------------------------------------------------------------------------------------------
    def test_close_refused_in_ai_session(self):
        self.approved('P1')
        before = self.ledger_bytes()
        for marker in AI_MARKERS:
            with self.subTest(marker=marker), patch.dict(os.environ, {marker: '1'}):
                for dry in (False, True):
                    with self.assertRaisesRegex(LedgerError, 'refused'):
                        plans.close(self.ledger, 'P1', 'owner', WORDS, dry_run=dry)
        with patch.dict(os.environ, {'ONECREW_ACTOR': 'claude'}), self.assertRaises(LedgerError):
            plans.close(self.ledger, 'P1', 'owner', WORDS)
        with self.assertRaises(LedgerError):
            plans.close(self.ledger, 'P1', 'claude', WORDS)                 # only --by owner
        code, out, err = self.cli('P1', '--reference', WORDS, env=dict(owner_env(), **{AI_MARKERS[0]: '1'}))
        self.assertNotEqual(code, 0, out + err)
        self.assertIn('refused', out + err)
        self.assertEqual(self.ledger_bytes(), before)
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'approved')

    def test_close_dry_run_writes_nothing(self):
        self.approved('P1')
        active = self.root / '.onecrew' / 'active-plan.json'
        before, file_before = self.ledger_bytes(), active.read_bytes()
        shown = plans.close(self.ledger, 'P1', 'owner', WORDS, dry_run=True)
        self.assertEqual((shown.get('dry_run'), shown.get('written'), shown.get('status')), (True, False, 'approved'))
        self.assertEqual(shown['would_close']['previous_status'], 'approved')
        code, out, err = self.cli('P1', '--reference', WORDS, '--dry-run')
        self.assertEqual(code, 0, out + err)
        self.assertEqual(json.loads(out)['would_close']['plan'], 'P1')
        code, out, err = self.cli('P1', '--reference', WORDS, '--dry-run', '--human')
        self.assertEqual(code, 0, out + err)
        self.assertIn('Chạy thử', out)
        self.assertEqual(self.ledger_bytes(), before, 'the dry run wrote the ledger')
        self.assertEqual(active.read_bytes(), file_before, 'the dry run rewrote the active plan')
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'approved')
        code, out, err = self.cli('P1', '--reference', WORDS, '--human')            # then the real close through the same command
        self.assertEqual(code, 0, out + err)
        self.assertIn('Đã đóng P1', out)
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'closed')

    # ---- I3: out of the open lists; the engine runs nothing --------------------------------------------------------------------------
    def test_closed_plan_leaves_open_lists(self):
        self.approved('P1'); self.approved('P2')
        def open_lines():
            return [line.split()[0] for line in report.render_digest(self.ledger.state_root).splitlines()[1:] if line.split() and line.split()[0] in ('P1', 'P2')]
        self.assertEqual(sorted(open_lines()), ['P1', 'P2'])
        self.close_or_fail('P1')
        digest = report.render_digest(self.ledger.state_root)
        self.assertEqual(open_lines(), ['P2'], digest)
        self.assertIn('1 chủ sở hữu đóng', digest)
        tasks = {t['plan']: t for p in tracking.overview(self.ledger.state_root)['projects'] for t in p['tasks']}
        self.assertEqual(tasks['P1']['root_status'], 'closed')
        self.assertEqual((tasks['P1']['status']['kind'], tasks['P1']['status']['outcome']), ('done', 'closed'))
        self.assertEqual(tasks['P1']['needs_user'], [])
        self.assertEqual(tasks['P2']['root_status'], 'approved')

    # ---- I4: the hooks (option dong-bo-giam-sat) --------------------------------------------------------------------------------------
    def test_hook_lets_work_through_after_owner_close(self):
        self.enforce('P1')
        outside = self.edit('b.txt')
        self.assertEqual(self.run_hook('check', outside)[0], 2)                # enforced: outside the plan is refused
        self.close_or_fail('P1')
        document = json.loads((self.root / '.onecrew' / 'active-plan.json').read_text(encoding='utf-8'))
        self.assertEqual((document.get('status'), document.get('closed_by')), ('closed', 'owner_close'))
        for event in (self.edit('b.txt'), self.edit('a.txt'), self.shell('git status')):
            code, out, err = self.run_hook('check', event)
            self.assertEqual(code, 0, f'the hook still governs a plan the owner closed: {out} {err}')

    def test_stop_answer_still_closes(self):
        request = self.stopped_plan('P1', workflow=True)                    # owns a.txt
        active_plan.set_mode(self.ledger, 'enforce'); active_plan.export(self.ledger, 'P1')
        questions.answer(self.ledger, request['id'], request['revision'], 'stop', 'Không làm tiếp việc này.')
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'closed')
        closed = self.closed_events()
        self.assertEqual(len(closed), 1)
        self.assertIsNone(closed[0].get('closed_by'))                         # the stop answer is not owner close
        active_plan.export(self.ledger, 'P1')
        code, out, err = self.run_hook('check', self.edit('a.txt'))
        self.assertEqual(code, 2, 'a plan closed by the stop answer still refuses edits in its repository: ' + out + err)

    def test_engine_runs_nothing_on_closed_plan(self):
        """An engine root, made as tests.test_wf_engine.EngineFixture makes one, that is closed: no ready node, no step, the next action says stopped."""
        from onecrew.control import Control, migrate
        from onecrew.v2 import internal_plan
        value = plan_json(scope={'owned': ['a.txt', 'b.txt']}, authority={
            'edit': True, 'commands': True, 'edit_tests': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']})
        plans.propose(self.ledger, 'E1', value, 'codex', workflow=True, capabilities=['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine'])
        plans.approve(self.ledger, 'E1', 'owner', 'fixture engine approval')
        os.environ['ONECREW_ACTOR'] = 'codex'                            # the engine's own steps are the AI's (the fixture env is restored after)
        migrate(self.ledger); control = Control(self.ledger)
        internal_plan.revise(self.ledger, 'E1', [node('C'), node('I', ['C'], integration=True, write=())], reason='Split work inside the approved scope',
                             evidence=['a.txt:1'])
        self.assertEqual([t['id'] for t in engine.ready(self.ledger, 'E1')], ['C'])
        with self.ledger.transaction(write=True) as conn:               # a closed engine root, as the stop answer leaves it
            state = plans.derive(self.ledger, conn, 'E1')
            plans.emit(self.ledger, conn, state['task_id'], 'plan.closed', {'plan': 'E1', 'revision': state['latest'], 'by': 'owner',
                                                                              'reference': WORDS, 'reason': WORDS, 'effect': 'closed'})
        self.assertEqual(plans.show(self.ledger, 'E1')['status'], 'closed')
        self.assertEqual(engine.ready(self.ledger, 'E1'), [])
        ran = []
        try:
            stepped = engine.step(self.ledger, 'E1', lambda *a: ran.append(a), control=control)
        except LedgerError:
            stepped = None                                                # refused outright: the root is not open
        self.assertEqual((ran, stepped), ([], None), 'the engine ran a node of a closed root')
        self.assertEqual(engine.next_action(self.ledger, 'E1')['state'], 'stopped')
