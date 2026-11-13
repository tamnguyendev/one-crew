"""Cross-review regressions, real temporary ledgers and shipped JS; no live provider."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.v2 import tracking, tracking_work, hook_cli, plan
from tests import test_obs2_cards as cards, test_obs2_timeline as timeline
from tests.test_wf_engine import EngineFixture, node
from tests.test_obs1_tracking import QUESTION
from tests.test_v2_l1 import Fixture


class ReviewCards(unittest.TestCase):
    run_js = cards.Cards.run_js
    # 13/11: the stage is the model's (tracking_situation); same intents on the model
    def test_checked_output_with_unstarted_work_is_not_waiting_for_check(self):
        from tests.test_tracking_situation import call
        ev = {'nodes': {'C': {'phase': 'complete', 'state': 'verified', 'attempt': 'a'}, 'I': {'phase': 'pending'}}, 'definition': {'nodes': [{'id': 'C'}, {'id': 'I'}]}}
        s = call(engine_view=ev, has_started=True, level='produced', needs=[{'kind': 'request', 'question': 'Q?'}])
        self.assertEqual(s['stage'], 'doing'); self.assertEqual(s['next_by_text'], 'Bạn')

    def test_verified_nodes_without_acceptance_readiness_do_not_request_acceptance(self):
        from tests.test_tracking_situation import call
        ev = {'nodes': {'C': {'phase': 'complete', 'state': 'verified'}, 'I': {'phase': 'complete', 'state': 'verified'}}, 'definition': {'nodes': [{'id': 'C'}, {'id': 'I'}]}}
        s = call(engine_view=ev, has_started=True, level='verified', acceptance={'ready': False, 'reason': 'Chờ kiểm bàn giao'})
        self.assertNotEqual(s['stage'], 'accept'); self.assertNotEqual(s['next_by'], 'owner')

    def test_initial_plan_is_labelled_creation_not_change(self):
        out = self.run_js('workChanges({},'+json.dumps({'changes':[{'id':'1','kind':'initial','internal_revision':1,'diff':[]}]})+')')
        self.assertIn('Kế hoạch thực hiện ban đầu',out)


class ReviewTicks(unittest.TestCase):
    js = timeline.TimelineUX.js
    def test_many_day_axis_remains_readable(self):
        for days in (4.01,4.7,5,6,12,100,3650):
            ticks=self.js('gTicks({w0:0,w1:'+str(days*86400000)+'})')
            self.assertGreaterEqual(len(ticks),3,days)
            self.assertLessEqual(len(ticks),6,days)
            self.assertEqual(len(ticks),len({t['label'] for t in ticks}))
            self.assertTrue(all(0 <= t['pct'] <= 100 for t in ticks))
            self.assertIn('ngày',ticks[-1]['label'])


class EngineReadiness(EngineFixture):
    def test_all_nodes_verified_is_not_root_acceptance(self):
        self.revise([node('A'),node('I',['A'],integration=True,write=())])
        self.step(); self.verify('A'); self.step(); self.verify('I')
        db=self.ledger.state_root/'ledger.sqlite3'; before=db.read_bytes()
        # A viewer must never hash/write the project or invoke subprocesses to determine readiness.
        with patch('onecrew.v2.verifiers.command.artifact_sha',side_effect=AssertionError('viewer must not hash project')):
            t=tracking.detail(self.ledger.state_root,'P1')
        self.assertNotIn('accept',[n['kind'] for n in t['needs_user']])
        self.assertNotEqual(t['status']['kind'],'done')
        self.assertNotIn('chờ bạn nghiệm thu',t['current_step'] or '')
        self.assertFalse(t['acceptance']['ready'])
        self.assertIn('M1',t['acceptance']['reason'])
        self.assertEqual(t['work']['changes'][0]['kind'],'initial')
        self.assertEqual(before,db.read_bytes())


class RuntimeBinding(Fixture):
    def test_unknown_other_runtime_or_other_state_cannot_supply_write_commands(self):
        self.propose()
        exe=Path(self.temp.name)/'onecrew.exe'; exe.write_bytes(b'fixture, never executed')
        settings=self.root/'.claude'/'settings.local.json'; settings.parent.mkdir(exist_ok=True)
        for mode in ('missing','other-runtime','other-state','same'):
            if mode!='missing':
                settings.write_text(json.dumps(hook_cli.portable_settings(
                    str(exe) if mode!='other-runtime' else str(exe.parent/'other.exe'),
                    self.ledger.state_root if mode!='other-state' else exe.parent/'other-state')),encoding='utf8')
            with patch('onecrew.v2.tracking._runtime_exe',return_value=exe):
                t=tracking.detail(self.ledger.state_root,'P1')
            n=t['needs_user'][0]
            self.assertEqual(bool(n['human_command']),mode=='same',mode)
            self.assertEqual(n['action']['enabled'],mode=='same',mode)
            if mode!='same': self.assertIn('runtime',n['binding_reason'])

    def test_unbound_question_options_have_no_hidden_legacy_commands(self):
        root=self.propose(); self.ledger.create_request(root['anchor_task'],'owner-choice',QUESTION)
        with patch('onecrew.v2.tracking._runtime_exe',return_value=None):
            t=tracking.detail(self.ledger.state_root,'P1')
        for need in t['needs_user']:
            for n in [need,*need.get('options',[])]:
                self.assertIsNone(n.get('human_command'))
                self.assertIsNone(n.get('reply_command'))
                self.assertFalse((n.get('action') or {}).get('enabled'))

    def test_text_evidence_is_not_reported_unreadable(self):
        limits=[]; b=tracking_work._Blobs(self.ledger,limits)
        key=b.store.blob(b'valid text evidence')
        self.assertIsNone(b.get(key,optional_json=True))
        self.assertEqual(limits,[])
        b.get('a'*64,optional_json=True)
        self.assertTrue(limits,'missing evidence must still be visible')

    def test_finding_summary_uses_criterion_without_fabricating_diagnosis(self):
        self.assertEqual(tracking_work._finding_text({'head':'{"evidence":[]}', 'check':{'spec':'Check addition'},'criterion':'C'}),
                         'Không đạt: Check addition')
        self.assertEqual(tracking_work._finding_text({'head':'Concrete diagnosis','check':{'spec':'Check'}}),'Concrete diagnosis')


if __name__=='__main__': unittest.main()
