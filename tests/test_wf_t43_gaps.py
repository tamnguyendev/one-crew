"""T43b/T43c gaps (R03 W24/W24b/W30b): exception notice content, the question card behind a notice, open/close is not an answer,
v1 pull returns the notice.exception row, and a card answer on a legacy `plan:` root is recorded without an effect.

Fixture: as tests/test_wf_exceptions (real temporary ledger, the real v1 outbox and desktop records; the launcher and the Tk window are
fakes that only record). Fake clock: the `now` given to exceptions.observe. No real desktop window or host message is sent.
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from onecrew import desktop_notifications as desktop, desktop_window, notifications
from onecrew.v2 import compat, estimates, exceptions, plan, questions, verdict
from tests.test_v2_l1 import Fixture, plan_json, milestone
from tests.test_wf_exceptions import question
from tests.test_wf_t47_gaps import stopped_legacy, SELECTOR
from tests import wf_oldversion as ov

REPO = Path(__file__).resolve().parents[1]


def fake_tk(test, after_map=None):
    """The Tk stand-in of tests/test_wf_exceptions: maps the window, then the user closes it."""
    class Widget:
        def __init__(self, *args, **kwargs): pass
        def pack(self, **kwargs): pass
        def insert(self, *args): pass
        def configure(self, **kwargs): pass
    class Window(Widget):
        def title(self, *args): pass
        def geometry(self, *args): pass
        def attributes(self, *args): pass
        def after(self, *args): pass
        def destroy(self): pass
        def winfo_ismapped(self): return True
        def protocol(self, name, callback): self.close = callback
        def bind(self, name, callback): self.map = callback
        def mainloop(self):
            self.map(SimpleNamespace(widget=self))
            if after_map: after_map()
            self.close()
    return {'tkinter': SimpleNamespace(Tk=Window, Label=Widget, Frame=Widget, Button=Widget),
            'tkinter.scrolledtext': SimpleNamespace(ScrolledText=Widget)}


class NoticeGapTests(Fixture):
    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, ONECREW_DESKTOP_HOME=str(Path(self.temp.name) / 'desktop'))
        env.start(); self.addCleanup(env.stop)
        self.launch = patch.object(desktop, 'launch').start()
        self.addCleanup(patch.stopall)

    def start(self, deadline=None, value=None, span=(21600, 28800)):
        return self.approved(value=value, estimate={'execution_seconds': list(span), 'evidence': ['fixture:approved decomposition'],
                                                    'deadline': deadline, 'policy': {'relative_change': .25}})

    def notices(self):
        return [i['notice'] for i in exceptions.desktop_snapshots(self.ledger)]

    def payloads(self, kind='notice.exception'):
        return [(seq, p) for seq, (k, p) in enumerate(self.events()) if k == kind]

    def seq_of(self, kind, name='P1'):
        with self.ledger.transaction() as conn:
            task = plan.derive(self.ledger, conn, name)['task_id']
        return [e['seq'] for e in self.ledger.events(task) if e['kind'] == kind]

    # ---- T43c [E16]: one baseline notice with reason, acceptance, evidence ids, new ETA and the user action; same cause -> none -------
    def test_t43c_e16_baseline_notice_has_reason_evidence_eta_and_user_action_and_dedups(self):
        self.start()
        estimates.additional(self.ledger, 'P1', 'migration', 'mandatory', 'missing migration required by O1', ['O1'], [3600, 7200], ['evidence:migration'])
        exceptions.observe(self.ledger, 'P1', '2026-10-24T10:00:00+07:00')
        first = [p for k, p in self.events() if k == 'notice.exception']
        self.assertEqual(len(first), 1)
        payload = first[0]
        self.assertEqual(payload['category'], 'baseline')
        self.assertEqual(payload['reason'], 'missing migration required by O1')            # reason: the mandatory addition
        self.assertEqual(payload['acceptance'], ['O1'])                                     # ... and its acceptance
        baseline_seq, addition_seq = self.seq_of('estimate.baseline')[0], self.seq_of('work.additional')[0]
        self.assertIn(f'event:{baseline_seq}', payload['evidence'])                         # evidence: the baseline record id
        self.assertIn(f'event:{addition_seq}', payload['evidence'])                         # ... the addition record id
        self.assertIn('evidence:migration', payload['evidence'])
        self.assertEqual(payload['eta']['remaining_seconds'], [25200, 36000])               # the new ETA
        self.assertIn('baseline_upper_exceeded', payload['triggers'])
        self.assertIsNone(payload['user_action'])
        self.assertFalse(payload['grants_authority'])
        notice = self.notices()[0]
        self.assertEqual((notice['status'], notice['reason'], notice['evidence']), ('baseline', payload['reason'], payload['evidence']))
        self.assertIn('Không cần bạn làm gì.', notice['open_content'])                     # the user action ("nothing to do")
        # second increase from the same cause: no new notice
        estimates.reforecast(self.ledger, 'P1', 'eta2', [30000, 40000], 'migration estimate refined', ['evidence:migration'])
        self.assertEqual(exceptions.observe(self.ledger, 'P1', '2026-10-24T11:00:00+07:00'), [])
        self.assertEqual(self.kinds().count('notice.exception'), 1)
        self.assertEqual(len(self.notices()), 1)
        self.assertEqual(self.ledger.requests(), [])                                        # T43c [E24]

    # ---- T43c [E17]: exactly one notice when the promised milestone M2 is overdue, naming M2, the time, a reason and the ETA ---------
    def test_t43c_e17_overdue_promised_milestone_notice_names_milestone_time_reason_and_eta(self):
        promised = '2026-10-24T15:00:00+07:00'
        self.start(deadline=promised, value=plan_json(milestones=[milestone(), milestone('M2')]))
        verdict.run(self.ledger, 'P1', 'M1')                                                # M1 passes, M2 (promised) does not
        self.assertEqual(exceptions.observe(self.ledger, 'P1', '2026-10-24T14:59:00+07:00'), [])   # before the promised time: nothing
        recorded = exceptions.observe(self.ledger, 'P1', '2026-10-24T15:01:00+07:00')
        self.assertEqual([r['category'] for r in recorded], ['deadline'])
        payload = recorded[0]
        self.assertEqual(payload['milestone'], 'M2')
        self.assertEqual(payload['promised_at'], promised)
        self.assertIn('M2', payload['reason']); self.assertIn(promised, payload['reason'])
        self.assertTrue(payload['evidence'])
        self.assertEqual(payload['eta']['remaining_seconds'], [21600, 28800])               # the (current) ETA is carried
        self.assertEqual(exceptions.observe(self.ledger, 'P1', '2026-10-24T16:00:00+07:00'), [])   # exactly one
        notices = [n for n in self.notices() if n['status'] == 'deadline']
        self.assertEqual(len(notices), 1)
        self.assertIn('M2', notices[0]['open_content']); self.assertIn('ETA còn lại', notices[0]['open_content'])
        self.assertEqual(self.ledger.requests(), [])

    # ---- T43c [E22]: every exception notice (baseline, deadline, blocker) has a non-empty reason and evidence ------------------------
    def test_t43c_e22_every_exception_notice_has_reason_and_evidence(self):
        self.start(deadline='2026-10-24T15:00:00+07:00')
        estimates.additional(self.ledger, 'P1', 'migration', 'mandatory', 'missing migration required by O1', ['O1'], [3600, 7200], ['evidence:migration'])
        self.ledger.create_request(plan.show(self.ledger, 'P1')['anchor_task'], 'write', question(True))
        exceptions.observe(self.ledger, 'P1', '2026-10-24T15:01:00+07:00')
        payloads = [p for k, p in self.events() if k == 'notice.exception']
        self.assertEqual(sorted(p['category'] for p in payloads), ['baseline', 'blocker', 'deadline'])
        for p in payloads:
            self.assertTrue(p['reason'].strip(), p); self.assertTrue(p['evidence'], p)
            self.assertTrue(all(isinstance(e, str) and e.strip() for e in p['evidence']), p)
        self.assertEqual(len({(p['category'], p['cause']) for p in payloads}), len(payloads))   # one per cause
        for n in self.notices():
            self.assertTrue(n['reason'].strip()); self.assertTrue(n['evidence'])

    # ---- T43c [E25]: notice.exception is written on the anchor, class A for the old version, and v1 pull returns its row ------------
    def test_t43c_e25_notice_exception_is_class_a_and_v1_pull_returns_its_row(self):
        old = ov.OldVersion(ov.archive('d3120c6', REPO, self.temp.name))
        file = Path(self.temp.name) / 'old-contract.json'; file.write_text(json.dumps(ov.contract('old')), encoding='utf-8')
        code, out = old.run(self.root, self.ledger.state_root, 'plan', 'propose', 'OLD', '--file', str(file), '--author', 'fixture')
        self.assertEqual(code, 0, out)
        plan.approve(self.ledger, 'plan:OLD', 'owner', 'local fixture', estimate={'execution_seconds': [21600, 28800], 'evidence': ['fixture:baseline']})
        with patch.object(exceptions, 'observe'):                                          # the forecast change itself writes no notice yet
            estimates.reforecast(self.ledger, 'plan:OLD', 'migration', [28800, 32400], 'required migration', ['fixture:migration'])
        before = ov.read(old, self.root, self.ledger.state_root, 'OLD')
        recorded = exceptions.observe(self.ledger, 'plan:OLD')
        self.assertEqual([r['category'] for r in recorded], ['baseline'])
        task = plan.show(self.ledger, 'plan:OLD')['anchor_task']
        rows = [e for e in self.ledger.events(task) if e['kind'] == 'notice.exception']
        self.assertEqual(len(rows), 1)                                                      # written on the anchor
        self.assertEqual(compat.event_class('notice.exception'), 'A')
        after = ov.read(old, self.root, self.ledger.state_root, 'OLD')
        same = ov.compare(before, after)
        self.assertTrue(same['S'] and same['G'] and same['C'], (before, after))            # S, G, C identical with and without it
        batch = notifications.pull(self.ledger, 'e25-consumer')                             # the v1 outbox reads it from the ledger
        row = [n for n in batch['notifications'] if n.get('kind') == 'notice.exception']
        self.assertEqual(len(row), 1, batch)
        self.assertEqual((row[0]['event'], row[0]['status'], row[0]['task']), (rows[0]['seq'], 'baseline', task))
        self.assertEqual(row[0]['reason'], 'required migration')
        # the old binary's own pull still runs on this ledger
        child = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'onecrew', '--project', str(self.root), '--state-root', str(self.ledger.state_root),
                                'notifications', 'pull', '--consumer', 'old-fixture'], cwd=old.tree, env=old.env, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(child.returncode, 0, child.stderr + child.stdout)

    # ---- T43b [E6]: the question notice opens exactly that request's card ----------------------------------------------------------
    def test_t43b_e6_question_notice_opens_the_decision_card_of_that_request(self):
        self.approved()
        req = self.ledger.create_request(plan.show(self.ledger, 'P1')['anchor_task'], 'write', question())
        notice = next(n for n in self.notices() if n['status'] == 'question')
        self.assertEqual(notice['target'], {'type': 'request', 'request': req['id'], 'revision': req['revision']})
        card = json.loads(notice['open_content'])
        self.assertEqual((card['id'], card['revision']), (req['id'], req['revision']))
        stored = self.ledger.request(req['id'])['question']
        self.assertEqual({k: v for k, v in card.items() if k not in ('id', 'revision')}, stored)   # the whole card of that request
        for field in ('question', 'reason', 'impact', 'options', 'recommendation', 'action'):    # problem, evidence/reason, scope, choices, recommendation
            self.assertTrue(card.get(field), field)
        self.assertEqual([o['id'] for o in card['options']], ['yes', 'no'])

    # ---- T43b [E8]: opening and closing the question notice records no answer; the request stays pending ---------------------------
    def test_t43b_e8_open_and_close_of_a_pending_question_notice_is_not_an_answer(self):
        desktop.configure(self.ledger, True)
        self.approved()
        req = self.ledger.create_request(plan.show(self.ledger, 'P1')['anchor_task'], 'write', question())
        before = self.events()
        desktop.publish(self.ledger)
        records = desktop.status(self.ledger)['records']
        self.assertEqual(len(records), 1)
        self.assertIn(req['id'], Path(records[0]['report']).read_text(encoding='utf-8'))   # the window shows that request's card
        seen = {}
        def while_open():
            seen['pending'] = self.ledger.request(req['id'])['state']
        with patch.dict('sys.modules', fake_tk(self, while_open)):
            desktop_window.show(desktop.directory(self.ledger), records[0]['id'])
        self.assertEqual(seen['pending'], 'pending')                                       # open/read: still pending
        record = desktop.status(self.ledger)['records'][0]
        self.assertEqual(record['status'], 'closed')                                       # the notice state says "closed"
        self.assertFalse(record['answers_recorded'])
        self.assertFalse(record['user_attention_verified'])
        self.assertEqual(self.ledger.request(req['id'])['state'], 'pending')               # closed: still pending
        self.assertEqual(self.events(), before)                                            # no request.answered, no approval
        self.assertNotIn('request.answered', self.kinds())
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'approved')

    # ---- T43b [E26]: on a legacy `plan:` root the card answer records the choice; no apply and no close on the anchor --------------
    def test_t43b_e26_card_answer_on_plan_root_records_choice_without_apply_or_close(self):
        req, task = stopped_legacy(self)
        questions.answer(self.ledger, req['id'], req['revision'], 'stop', 'stop from the card')
        kinds = [e['kind'] for e in self.ledger.events(task)]
        answered = [e['payload'] for e in self.ledger.events(task) if e['kind'] == 'request.answered']
        self.assertEqual([a['choice'] for a in answered], ['stop'])
        self.assertEqual(kinds.count('request.applied'), 0)
        self.assertEqual(kinds.count('plan.closed'), 0)
        self.assertEqual(plan.show(self.ledger, SELECTOR)['status'], 'stopped_with_report')
