"""DEV31 slice D (#41): one owner-approved skill delivered to one worker attempt, pinned, bound and traceable.

The fixture builds a real skill candidate through skills.refresh from three completed outcomes (synthetic outcomes written with the core
helpers, so this module also runs against the installed wheel). The owner's approval is written as the ledger event the other skill tests
write; owner verbs (rollback, revoke) run in a process that is not an AI session, and a test shows they still refuse inside one.
Only temp ledgers and temp directories; LOCALAPPDATA/APPDATA point into the temp dir."""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from onecrew import control_core, interventions, outcome_core, skill_delivery, skills, task_intake
from onecrew.ledger import Ledger, LedgerError, content_hash
from onecrew.snapshots import durable_write

GOAL = 'Inspect calculation implementation and report subtraction evidence'
OTHER_GOAL = 'Review database migration rollback safety permissions'
GRANT = {'permissions': ['discover', 'report'], 'owned_paths': ['src/**'], 'tools': ['read', 'finish'], 'budget': {'max_calls': 5}}


def owner_env():
    """An owner's own terminal: no AI-session marker. The guard itself is untouched."""
    env = {k: v for k, v in os.environ.items() if k not in interventions.AI_SESSION_MARKERS}
    return mock.patch.dict(os.environ, env, clear=True)


def ai_env():
    """Inside an AI tool session: the marker the guard looks for."""
    return mock.patch.dict(os.environ, {interventions.AI_SESSION_MARKERS[0]: '1'})


class Fixture(unittest.TestCase):
    def setUp(self):
        # A skill file lives at state/skills/<project hash>/<id>/<revision hash>/ (about 200 characters); on Windows a long TEMP overflows
        # MAX_PATH, so the temp tree is made as short as the drive allows (still a throw-away directory, removed after each test).
        short = Path(tempfile.gettempdir()).anchor
        try: self.temp = tempfile.TemporaryDirectory(prefix='d', dir=short or None)
        except OSError: self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        patch = mock.patch.dict(os.environ, {'LOCALAPPDATA': str(base / 'local'), 'APPDATA': str(base / 'roaming')})
        patch.start(); self.addCleanup(patch.stop)
        self.root = base / 'project'; self.root.mkdir(); (self.root / 'calc.py').write_text('def add(a, b): return a - b\n')
        self.state = base / 'state'
        self.ledger = Ledger(self.root, self.state)
        self.tasks = []
        for i in range(3):
            self.tasks.append(task_intake.submit(self.ledger, GOAL, 'history-' + str(i))['id'])
        control_core.migrate(self.ledger)
        sig = skills.signature(GOAL, 'audit', {'calc.py': 'h'})
        with self.ledger.transaction(write=True) as conn:
            for i, task in enumerate(self.tasks):
                row = self.ledger._task(conn, task)
                conn.execute('INSERT INTO executions(task_id,configuration,revision,status) VALUES(?,?,?,?)', (task, '{}', 'r' + str(i), 'completed'))
                data = {'version': 1, 'task': task, 'task_revision': row['revision'], 'phase': 'completed', 'mode': 'audit',
                        'snapshot': 'snap' + str(i), 'verification': 'passed', 'signature': sig, 'procedure': ['read', 'finish']}
                data['id'] = outcome_core.outcome_id(data)
                outcome_core.append_outcome(conn, self.ledger, task, data)
        self.assertEqual(len(skills.refresh(self.ledger)), 1)
        self.skill = self.records()[next(iter(self.records()))]

    def records(self):
        with self.ledger.transaction() as conn:
            return skills.records(self.ledger, conn)

    def write_state(self, value):
        with self.ledger.transaction(write=True) as conn:
            self.ledger._event(conn, value['tasks'][0], 'skill.state', value)

    def approve(self, **changes):
        """The owner's approval as the ledger event the existing skill tests write."""
        value = dict(self.records()[self.skill['id']], status='approved', operator_reference='owner review', **changes)
        self.write_state(value); return value

    def new_revision(self, body):
        """A later revision of the same skill (its own file), approved."""
        value = dict(self.records()[self.skill['id']], body=body, status='approved', operator_reference='owner review 2')
        value['revision'] = content_hash({k: v for k, v in value.items() if k != 'revision'})
        durable_write(skills.skill_path(self.ledger, value), body.encode('utf-8'))
        self.write_state(value); return value

    def args(self, attempt=1, **over):
        a = dict(plan='p', plan_revision=1, node='N1', attempt=attempt)
        a.update(over); return a

    def deliver(self, attempt=1, ledger=None, **over):
        kw = dict(self.args(attempt), goal=GOAL, profile={'mode': 'audit'}, files={'calc.py': 'h'}, grant=copy.deepcopy(GRANT), skill_id=self.skill['id'])
        kw.update(over)
        return skill_delivery.deliver(ledger or self.ledger, self.tasks[0], **kw)


class DeliveryTests(Fixture):
    def test_selected_pinned_skill_is_delivered_with_its_hash_and_exact_content(self):
        value = self.approve()
        got = self.deliver()
        self.assertTrue(got['delivered']); self.assertEqual(got['status'], 'delivered')
        self.assertEqual(got['skill']['body'], value['body'])
        self.assertEqual(got['skill']['revision'], value['revision'])
        self.assertEqual(got['skill']['hash'], hashlib.sha256(value['body'].encode('utf-8')).hexdigest())
        self.assertEqual(got['binding'], {'project': self.ledger.project_id, 'task': self.tasks[0], 'plan': 'p', 'plan_revision': '1', 'node': 'N1', 'attempt': 1})
        # without a skill id the same approved skill is selected for a matching task
        auto = self.deliver(attempt=2, skill_id=None)
        self.assertEqual(auto['skill']['revision'], value['revision'])

    def test_candidate_without_owner_approval_is_not_delivered(self):
        got = self.deliver()
        self.assertFalse(got['delivered']); self.assertEqual(got['reason'], 'not_approved'); self.assertNotIn('skill_body', got)
        self.assertNotIn('body', (got['skill'] or {}))

    def test_wrong_permission_skill_is_refused_not_delivered(self):
        self.approve(required_permissions=['git.push'])
        got = self.deliver()
        self.assertFalse(got['delivered']); self.assertEqual(got['reason'], 'wrong_permission')
        self.assertIn('git.push', got['detail']); self.assertEqual([s['step'] for s in got['steps']], ['refused'])
        self.assertNotIn('body', got['skill'])

    def test_wrong_project_skill_is_refused(self):
        self.approve()
        other_root = Path(self.temp.name) / 'other'; other_root.mkdir()
        other = Ledger(other_root, self.state)
        anchor = task_intake.submit(other, GOAL, 'anchor')['id']
        got = skill_delivery.deliver(other, anchor, **dict(self.args(), goal=GOAL, profile={'mode': 'audit'}, files={'calc.py': 'h'},
                                                           grant=copy.deepcopy(GRANT), skill_id=self.skill['id']))
        self.assertFalse(got['delivered']); self.assertEqual(got['reason'], 'wrong_project')
        # a record in this project that names another project is refused as well
        self.approve(project='some-other-project')
        got = self.deliver()
        self.assertFalse(got['delivered']); self.assertEqual(got['reason'], 'wrong_project')

    def test_stale_revision_and_stale_evidence_are_refused(self):
        first = self.approve(); second = self.new_revision('Second reviewed procedure. Task acceptance overrides it.\n')
        got = self.deliver(expected_revision=first['revision'])
        self.assertFalse(got['delivered']); self.assertEqual(got['reason'], 'stale')
        self.assertEqual(got['skill']['revision'], second['revision'])
        ok = self.deliver(attempt=2, expected_revision=second['revision'])
        self.assertTrue(ok['delivered'])
        # the evidence the approval stood on stops being true
        with self.ledger.transaction(write=True) as conn:
            conn.execute("UPDATE executions SET status='failed' WHERE task_id=?", (self.skill['evidence'][0]['task'],))
        late = self.deliver(attempt=3)
        self.assertFalse(late['delivered']); self.assertEqual(late['reason'], 'stale')

    def test_tampered_content_is_refused(self):
        value = self.approve()
        bad = self.deliver(expected_hash='0' * 64)
        self.assertFalse(bad['delivered']); self.assertEqual(bad['reason'], 'tampered')
        path = skills.skill_path(self.ledger, value)
        path.write_text('Changed instructions after approval', encoding='utf-8')
        got = self.deliver(attempt=2)
        self.assertFalse(got['delivered']); self.assertEqual(got['reason'], 'tampered')
        path.write_bytes(value['body'].encode('utf-8'))
        fine = self.deliver(attempt=3, expected_hash=hashlib.sha256(value['body'].encode('utf-8')).hexdigest())
        self.assertTrue(fine['delivered'])

    def test_revoked_skill_is_never_delivered(self):
        self.approve()
        with owner_env(): skill_delivery.revoke(self.ledger, self.skill['id'], 'no longer wanted')
        got = self.deliver()
        self.assertFalse(got['delivered']); self.assertEqual(got['reason'], 'revoked')
        newer = self.new_revision('Another revision after the revoke.\n')
        self.assertEqual(newer['status'], 'approved')
        self.assertEqual(self.deliver(attempt=2)['reason'], 'revoked')
        with ai_env(), self.assertRaises(LedgerError): skill_delivery.revoke(self.ledger, self.skill['id'], 'from an AI session')

    def test_revoked_rejected_status_is_never_delivered(self):
        self.write_state(dict(self.skill, status='rejected', operator_reference='not useful'))
        got = self.deliver()
        self.assertFalse(got['delivered']); self.assertEqual(got['reason'], 'revoked')
        auto = self.deliver(attempt=2, skill_id=None)
        self.assertFalse(auto['delivered'])

    def test_rollback_to_previous_approved_revision_is_used_and_recorded(self):
        first = self.approve(); second = self.new_revision('Second reviewed procedure. Task acceptance overrides it.\n')
        before = self.deliver()
        self.assertEqual(before['skill']['revision'], second['revision'])
        with ai_env(), self.assertRaises(LedgerError): skill_delivery.rollback(self.ledger, self.skill['id'], first['revision'], 'AI session')
        with owner_env():
            with self.assertRaises(LedgerError): skill_delivery.rollback(self.ledger, self.skill['id'], 'no-such-revision', 'x')
            skill_delivery.rollback(self.ledger, self.skill['id'], first['revision'], 'second revision was wrong')
        after = self.deliver(attempt=2)
        self.assertTrue(after['delivered']); self.assertEqual(after['skill']['revision'], first['revision'])
        self.assertEqual(after['skill']['body'], first['body'])
        self.assertEqual(after['rollback'], {'from': second['revision'], 'to': first['revision'], 'reference': 'second revision was wrong'})
        # the attempt delivered before the rollback keeps what it was given
        again = self.deliver()
        self.assertEqual(again['skill']['revision'], second['revision'])

    def test_not_suitable_skill_is_not_delivered_and_the_reason_is_recorded(self):
        self.approve()
        got = self.deliver(goal=OTHER_GOAL)
        self.assertFalse(got['delivered']); self.assertEqual(got['reason'], 'not_suitable')
        self.assertIn('scope', got['detail'])
        shown = skill_delivery.record_of(self.ledger, self.tasks[0], **self.args())
        self.assertEqual((shown['status'], shown['reason']), ('refused', 'not_suitable'))
        none = self.deliver(attempt=2, goal=OTHER_GOAL, skill_id=None)
        self.assertEqual(none['reason'], 'not_suitable'); self.assertIsNone(none['skill'])
        wrong_tech = self.deliver(attempt=3, files={'calc.dart': 'h'})
        self.assertEqual(wrong_tech['reason'], 'not_suitable')

    def test_restart_keeps_binding_and_nothing_reselects_mid_attempt(self):
        first = self.approve()
        got = self.deliver()
        self.new_revision('A newer revision arrives while attempt 1 is running.\n')
        restarted = Ledger(self.root, self.state)
        again = self.deliver(ledger=restarted)
        self.assertEqual(again['binding'], got['binding']); self.assertEqual(again['skill'], got['skill'])
        self.assertEqual(again['steps'], got['steps']); self.assertEqual(again['skill']['revision'], first['revision'])
        read = skill_delivery.record_of(restarted, self.tasks[0], **self.args())
        self.assertEqual(read['skill']['hash'], got['skill']['hash'])
        self.assertEqual(self.event_count('skill.delivery'), 2)           # the replay wrote nothing
        # only a new attempt selects again, and then picks the revision in force
        self.assertNotEqual(self.deliver(attempt=2, ledger=restarted)['skill']['revision'], first['revision'])
        # another node has no record yet
        self.assertIsNone(skill_delivery.record_of(restarted, self.tasks[0], **self.args(node='other-node')))

    def event_count(self, kind):
        with self.ledger.transaction() as conn:
            return conn.execute('SELECT COUNT(*) FROM events WHERE kind=?', (kind,)).fetchone()[0]

    def test_selected_delivered_evaluated_are_three_ordered_steps_and_evaluation_is_separate(self):
        self.approve()
        got = self.deliver()
        self.assertEqual([s['step'] for s in got['steps']], ['selected', 'delivered'])
        self.assertNotIn('outcome', got)
        shown = skill_delivery.record_of(self.ledger, self.tasks[0], **self.args())
        self.assertEqual(shown['status'], 'delivered'); self.assertNotIn('outcome', shown)
        done = skill_delivery.evaluate(self.ledger, self.tasks[0], outcome='success', note='tests green', **self.args())
        self.assertEqual([s['step'] for s in done['steps']], ['selected', 'delivered', 'evaluated'])
        times = [s['at'] for s in done['steps']]
        self.assertEqual(times, sorted(times)); self.assertTrue(all(times))
        self.assertEqual((done['status'], done['outcome']), ('evaluated', 'success'))
        self.assertEqual(skill_delivery.evaluate(self.ledger, self.tasks[0], outcome='success', **self.args())['steps'], done['steps'])
        with self.assertRaises(LedgerError): skill_delivery.evaluate(self.ledger, self.tasks[0], outcome='failure', **self.args())
        with self.assertRaises(LedgerError): skill_delivery.evaluate(self.ledger, self.tasks[0], outcome='great', **self.args(attempt=5))
        with self.assertRaises(LedgerError): skill_delivery.evaluate(self.ledger, self.tasks[0], outcome='success', **self.args(attempt=5))
        refused = self.deliver(attempt=2, goal=OTHER_GOAL)
        self.assertFalse(refused['delivered'])
        with self.assertRaises(LedgerError): skill_delivery.evaluate(self.ledger, self.tasks[0], outcome='success', **self.args(attempt=2))

    def test_no_grant_widening_by_a_delivered_skill(self):
        self.approve()
        grant = copy.deepcopy(GRANT)
        got = skill_delivery.deliver(self.ledger, self.tasks[0], **dict(self.args(), goal=GOAL, profile={'mode': 'audit'}, files={'calc.py': 'h'},
                                                                         grant=grant, skill_id=self.skill['id']))
        self.assertTrue(got['delivered'])
        self.assertEqual(grant, GRANT); self.assertEqual(got['grant'], GRANT)          # nothing added: permissions, owned paths, tools, budget
        self.assertEqual(got['grant_digest'], content_hash(GRANT))
        self.assertEqual(set(got['skill']), {'id', 'revision', 'hash', 'body'})
        self.assertTrue(set(self.skill['required_permissions']) <= set(GRANT['permissions']))
        stored = skill_delivery.record_of(self.ledger, self.tasks[0], **self.args())
        self.assertNotIn('permissions', json.dumps({k: v for k, v in stored.items() if k not in ('skill', 'grant_digest', 'binding')}))
        # a skill that would need more than the contract grants is refused, never lets the grant grow
        self.approve(required_permissions=['git.push', 'git.commit'])
        late = self.deliver(attempt=2)
        self.assertEqual(late['reason'], 'wrong_permission'); self.assertEqual(late['grant'], GRANT)


class ReplayTests(Fixture):
    """F5/F6: a replay of a recorded binding is narrowed by revoke and re-checked against the request."""

    def test_replay_after_revoke_hands_out_no_body_and_records_a_refused_step(self):
        self.approve()
        first = self.deliver()
        self.assertTrue(first['delivered'])
        with owner_env(): skill_delivery.revoke(self.ledger, self.skill['id'], 'owner: this skill is wrong')
        again = self.deliver()
        self.assertFalse(again['delivered']); self.assertEqual((again['status'], again['reason']), ('refused', 'revoked'))
        self.assertEqual(again['detail'], 'revoked_after_delivery')
        self.assertNotIn('body', again['skill'])
        self.assertEqual([s['step'] for s in again['steps']], ['selected', 'delivered', 'refused'])      # the delivered step stays as history
        shown = skill_delivery.record_of(self.ledger, self.tasks[0], **self.args())
        self.assertFalse(shown['delivered']); self.assertNotIn('body', shown['skill'])
        replay_again = self.deliver()
        self.assertEqual(replay_again['steps'], again['steps'])                                          # recorded once
        self.assertEqual(self.deliver(attempt=2)['reason'], 'revoked')

    def test_read_after_revoke_withholds_the_body_even_before_any_replay(self):
        self.approve(); self.deliver()
        with owner_env(): skill_delivery.revoke(self.ledger, self.skill['id'], 'owner: wrong')
        shown = skill_delivery.record_of(self.ledger, self.tasks[0], **self.args())
        self.assertFalse(shown['delivered']); self.assertNotIn('body', shown['skill']); self.assertEqual(shown['reason'], 'revoked')

    def test_rollback_replay_keeps_the_pinned_revision_and_says_superseded(self):
        first = self.approve(); second = self.new_revision('Second reviewed procedure. Task acceptance overrides it.\n')
        got = self.deliver()
        self.assertEqual((got['skill']['revision'], got['superseded']), (second['revision'], False))
        with owner_env(): skill_delivery.rollback(self.ledger, self.skill['id'], first['revision'], 'second revision was wrong')
        again = self.deliver()
        self.assertTrue(again['delivered']); self.assertEqual(again['skill']['revision'], second['revision'])
        self.assertTrue(again['superseded'])

    def test_replay_with_a_grant_lacking_the_required_permission_is_refused_as_binding_mismatch(self):
        self.approve(required_permissions=['report'])
        self.deliver()
        narrow = dict(copy.deepcopy(GRANT), permissions=[])
        again = self.deliver(grant=narrow)
        self.assertFalse(again['delivered']); self.assertEqual(again['reason'], 'binding_mismatch')
        self.assertNotIn('body', again['skill'] or {})
        self.assertEqual(again['grant'], narrow)
        # recorded, but the real binding is untouched: the honest caller still gets the skill
        honest = self.deliver()
        self.assertTrue(honest['delivered']); self.assertIn('body', honest['skill'])
        self.assertEqual(self.deliver(grant=narrow)['steps'], again['steps'])                            # one record per distinct bad request
        self.assertEqual(self.event_count('skill.delivery'), 3)

    def test_replay_with_another_grant_or_another_skill_id_is_refused(self):
        self.approve(); self.deliver()
        wider = dict(copy.deepcopy(GRANT), tools=['read', 'finish', 'write'])
        self.assertEqual(self.deliver(grant=wider)['reason'], 'binding_mismatch')
        other = self.deliver(skill_id='some-other-skill')
        self.assertFalse(other['delivered']); self.assertEqual(other['reason'], 'binding_mismatch')
        self.assertNotEqual((other['skill'] or {}).get('id'), 'some-other-skill')
        same = self.deliver()
        self.assertTrue(same['delivered']); self.assertEqual(same['skill']['id'], self.skill['id'])

    def test_replay_without_a_skill_id_is_the_same_binding(self):
        self.approve(); self.deliver()
        self.assertTrue(self.deliver(skill_id=None)['delivered'])

    def test_plan_label_prefix_is_one_binding(self):
        self.approve()
        got = self.deliver(plan='plan-ns:P1')
        again = self.deliver(plan='P1')
        self.assertTrue(got['delivered']); self.assertEqual(again['skill'], got['skill'])
        self.assertEqual(again['binding']['plan'], 'P1')
        self.assertEqual(self.deliver(plan='plan:P1')['steps'], got['steps'])
        self.assertEqual(self.event_count('skill.delivery'), 2)

    def event_count(self, kind):
        with self.ledger.transaction() as conn:
            return conn.execute('SELECT COUNT(*) FROM events WHERE kind=?', (kind,)).fetchone()[0]


if __name__ == '__main__':
    unittest.main()
